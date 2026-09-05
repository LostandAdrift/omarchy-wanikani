#!/usr/bin/env python3
"""Read-only Linux process measurements; never starts, stops, or changes the desktop."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
import time

PLUGIN_ID = "io.github.lostandadrift.wanikani"
MEMORY_FIELDS = ("rss_bytes", "pss_bytes", "private_bytes")


class ProfileError(ValueError):
    """An intentionally safe, locally authored error message."""


def parse_stat(text):
    # comm can contain spaces and parentheses. Fields after its final ')' have
    # fixed positions; splitting the complete line shifts them incorrectly.
    opening, closing = text.index("("), text.rindex(")")
    values = text[closing + 1:].split()
    result = {"pid": int(text[:opening]), "ppid": int(values[1]),
        "cpu_ticks": int(values[11]) + int(values[12]),
        "start_ticks": int(values[19]), "rss_pages": int(values[21])}
    if any(value < 0 for value in result.values()):
        raise ValueError("Invalid process counters")
    return {**result, "state": values[0]}


def parse_memory(text):
    wanted = {"Rss", "Pss", "Private_Clean", "Private_Dirty", "Private_Hugetlb"}
    totals = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            parts = value.split()
            if len(parts) != 2 or parts[1] != "kB" or not parts[0].isdigit():
                raise ValueError("Invalid memory counters")
            totals[key] = totals.get(key, 0) + int(parts[0]) * 1024
    private = None
    if "Private_Clean" in totals and "Private_Dirty" in totals:
        private = sum(totals.get(key, 0) for key in ("Private_Clean", "Private_Dirty", "Private_Hugetlb"))
    return {"rss_bytes": totals.get("Rss"), "pss_bytes": totals.get("Pss"), "private_bytes": private}


def classify(argv, worker_scripts, shell_root):
    """Inspect argv only for discovery; its content never enters the report."""
    if not argv:
        return None
    executable = Path(argv[0]).name
    if re.fullmatch(r"python(?:\d+(?:\.\d+)?)?", executable):
        remaining = argv[1:]
        while remaining and remaining[0] in ("-B", "-u", "-E", "-I", "-s", "-S", "-O", "-OO", "-q"):
            remaining = remaining[1:]
        if remaining and Path(remaining[0]).is_absolute():
            if Path(remaining[0]).resolve() in worker_scripts:
                return "worker"
    if executable in ("qs", "quickshell") and not any(value in ("ipc", "kill", "list") for value in argv[1:]):
        for index, value in enumerate(argv[1:], start=1):
            target = argv[index + 1] if value in ("-p", "--path") and index + 1 < len(argv) else None
            if value.startswith("--path="):
                target = value.partition("=")[2]
            if target and Path(target).resolve() == shell_root:
                return "shared_shell"
    return None


def discover(proc, worker_scripts, shell_root):
    found = {"worker": [], "shared_shell": []}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            argv = (entry / "cmdline").read_bytes().decode(errors="replace").rstrip("\0").split("\0")
            role = classify(argv, worker_scripts, shell_root)
            if role:
                found[role].append(int(entry.name))
        except (OSError, ValueError):
            continue  # Processes can disappear during this read-only scan.
    return {role: sorted(pids) for role, pids in found.items()}


def observation(proc, pid, page_size):
    directory = proc / str(pid)
    before = parse_stat((directory / "stat").read_text())
    memory = {"rss_bytes": before["rss_pages"] * page_size, "pss_bytes": None, "private_bytes": None}
    source, unavailable = "stat", None
    for name in ("smaps_rollup", "smaps"):
        try:
            measured = parse_memory((directory / name).read_text())
            memory.update({key: value for key, value in measured.items() if value is not None})
            source = name
            unavailable = None if all(value is not None for value in measured.values()) else "incomplete"
            break
        except FileNotFoundError:
            unavailable = "unavailable"
        except PermissionError:
            unavailable = "permission_denied"
            break
        except (OSError, ValueError):
            unavailable = "unreadable"
            break
    after = parse_stat((directory / "stat").read_text())
    if before["state"] in ("Z", "X", "x") or after["state"] in ("Z", "X", "x"):
        raise FileNotFoundError("Process exited")
    if before["pid"] != pid or (before["pid"], before["start_ticks"]) != (after["pid"], after["start_ticks"]):
        raise ValueError("Process identity changed during observation")
    return {**after, **memory, "memory_source": source, "smaps_status": unavailable or "available"}


def summarize(samples, elapsed, ticks_per_second, invalid=None):
    if not samples:
        return {"status": "invalid" if invalid else "not_running", "reason": invalid}
    identity = {"pid": samples[0]["pid"], "start_ticks": samples[0]["start_ticks"]}
    if any((sample["pid"], sample["start_ticks"]) != (identity["pid"], identity["start_ticks"]) for sample in samples):
        invalid = "pid_reused_or_restarted"
    ticks = samples[-1]["cpu_ticks"] - samples[0]["cpu_ticks"]
    if ticks < 0:
        invalid = "cpu_counter_decreased"
    if len(samples) < 2 or elapsed <= 0:
        invalid = invalid or "insufficient_samples"
    memory = {}
    for key in MEMORY_FIELDS:
        values = [sample[key] for sample in samples if sample[key] is not None]
        memory[key] = {"first": values[0], "last": values[-1], "min": min(values), "max": max(values),
                       "median": statistics.median(values), "available_samples": len(values)} if values else None
    return {"status": "invalid" if invalid else "sampled", "reason": invalid, "identity": identity,
        "cpu_ticks_delta": None if invalid else ticks,
        "cpu_percent_one_core": None if invalid else round(100 * ticks / ticks_per_second / elapsed, 6),
        "cpu_tick_resolution_percent_one_core": round(100 / ticks_per_second / elapsed, 6) if elapsed > 0 else None,
        "memory": memory, "samples": samples}


def sample(args):
    proc = Path("/proc")
    scripts = {Path(args.worker_script).resolve()} if args.worker_script else {
        (Path.home() / ".config/omarchy/plugins" / PLUGIN_ID / "backend/worker.py").resolve(),
        (Path(__file__).resolve().parents[1] / "backend/worker.py").resolve()}
    shell_root = Path(args.shell_root).resolve()
    needs_discovery = args.worker_pid is None or args.shell_pid is None
    initial = discover(proc, scripts, shell_root) if needs_discovery else {"worker": [], "shared_shell": []}
    targets, automatic = {}, set()
    for role, supplied in (("worker", args.worker_pid), ("shared_shell", args.shell_pid)):
        if supplied is None:
            automatic.add(role)
            if len(initial[role]) > 1:
                raise ProfileError(f"Multiple {role} candidates; specify the intended PID")
            targets[role] = initial[role][0] if initial[role] else None
        else:
            targets[role] = supplied
    if targets["shared_shell"] is None:
        raise ProfileError("No shared Omarchy shell found; specify --shell-pid or --shell-root")
    ticks_per_second, page_size = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    samples = {role: [] for role in targets}
    invalid = {}
    while True:
        found = discover(proc, scripts, shell_root) if automatic else {}
        for role, pid in targets.items():
            if role in automatic and found[role] != initial[role]:
                invalid[role] = "process_set_changed"
            if pid is None or role in invalid:
                continue
            try:
                value = observation(proc, pid, page_size)
                value["elapsed_seconds"] = round(time.monotonic() - started, 6)
                samples[role].append(value)
                if samples[role][0]["start_ticks"] != value["start_ticks"]:
                    invalid[role] = "pid_reused_or_restarted"
            except FileNotFoundError:
                invalid[role] = "process_exited"
            except PermissionError:
                invalid[role] = "process_unreadable"
            except (OSError, ValueError, IndexError):
                invalid[role] = "process_unreadable_or_restarted"
        elapsed = time.monotonic() - started
        if elapsed >= args.seconds:
            break
        time.sleep(min(args.interval, args.seconds - elapsed))
    processes = {}
    for role in targets:
        values = samples[role]
        duration = values[-1]["elapsed_seconds"] - values[0]["elapsed_seconds"] if len(values) >= 2 else elapsed
        processes[role] = summarize(values, duration, ticks_per_second, invalid.get(role))
        processes[role]["selection"] = "discovered" if role in automatic else "explicit_pid"
    return {"format": 1, "started_at": started_at, "requested_seconds": args.seconds,
        "elapsed_seconds": round(elapsed, 6), "interval_seconds": args.interval,
        "clock_ticks_per_second": ticks_per_second,
        "valid": all(value["status"] != "invalid" for value in processes.values()), "processes": processes,
        "notes": ["CPU is percent of one core, from user plus system process ticks; child processes are excluded.",
                  "shared_shell measures the entire existing shell, not this plugin's QML alone.",
                  "Missing PSS/private values are unavailable, never zero; stat RSS is an approximate fallback."]}


def compare(paths):
    reports = [json.loads(Path(path).read_text()) for path in paths]
    if any(report.get("format") != 1 or not report.get("valid") for report in reports):
        raise ProfileError("Comparison requires three valid profiler samples")
    shells = [report["processes"]["shared_shell"] for report in reports]
    workers = [report["processes"]["worker"] for report in reports]
    identities = [{key: shell["identity"][key] for key in ("pid", "start_ticks")} for shell in shells]
    if any(type(value) is not int or value < 0 for identity in identities for value in identity.values()):
        raise ProfileError("Invalid process identity in saved sample")
    if any(shell.get("status") != "sampled" for shell in shells) or any(identity != identities[0] for identity in identities):
        raise ProfileError("Shared shell restarted or changed; collect a sequence with the same shell process")
    if [worker["status"] for worker in workers] != ["sampled", "not_running", "sampled"]:
        raise ProfileError("Expected enabled, disabled, enabled samples with the worker absent only in the middle")
    def metric(value):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ProfileError("Invalid numeric metric in saved sample")
        return value
    def delta(values):
        values = [metric(value) for value in values]
        if any(value is None for value in values):
            return None
        before, after = values[0] - values[1], values[2] - values[1]
        return {"enabled_before_minus_disabled": before, "enabled_after_minus_disabled": after,
                "mean_difference": (before + after) / 2, "enabled_spread": abs(after - before)}
    memory = {}
    for key in MEMORY_FIELDS:
        memory[key] = delta([(shell["memory"].get(key) or {}).get("median") for shell in shells])
    return {"format": 1, "kind": "paired_estimate", "shared_shell_identity": identities[0],
        "shared_shell_cpu_percent_one_core": delta([shell["cpu_percent_one_core"] for shell in shells]),
        "shared_shell_memory_median_bytes": memory,
        "worker_cpu_percent_one_core": [metric(workers[index]["cpu_percent_one_core"]) for index in (0, 2)],
        "notes": ["These are noisy differences in the whole shared shell, not isolated QML allocation measurements.",
                  "Allocator retention, other plugins, background work, and activity can dominate differences.",
                  "Negative differences are retained; neither a negative nor a zero reading certifies zero cost."]}


def write_report(report, destination=None):
    text = json.dumps(report, indent=2) + "\n"
    if destination:
        destination = Path(destination)
        descriptor, temporary = tempfile.mkstemp(prefix=".wanikani-profile-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(text)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
    else:
        sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("sample", help="Measure existing processes; default 45 seconds")
    capture.add_argument("--seconds", type=float, default=45)
    capture.add_argument("--interval", type=float, default=5)
    capture.add_argument("--worker-pid", type=int)
    capture.add_argument("--shell-pid", type=int)
    capture.add_argument("--worker-script", type=Path)
    capture.add_argument("--shell-root", type=Path, default=Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell")
    capture.add_argument("--output", type=Path)
    paired = commands.add_parser("compare", help="Compare enabled, disabled, enabled saved samples")
    paired.add_argument("reports", nargs=3, type=Path, metavar="REPORT")
    paired.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "sample":
            if not (0 < args.seconds <= 3600 and 0 < args.interval <= 30):
                parser.error("Use 0 < seconds <= 3600 and 0 < interval <= 30")
            if any(pid is not None and pid <= 0 for pid in (args.worker_pid, args.shell_pid)):
                parser.error("PIDs must be positive")
            report = sample(args)
        else:
            report = compare(args.reports)
        write_report(report, args.output)
        return 0 if report.get("valid", True) else 1
    except ProfileError as error:
        print(str(error) + ". No desktop changes were made.", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        # Avoid paths, command lines, environment, and imported JSON in errors.
        print("Cannot collect or compare these samples. Check process selection, file access, and sample validity; no desktop changes were made.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Sampling cancelled; no desktop changes were made.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
