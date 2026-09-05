#!/usr/bin/env python3
"""Verify one explicit, trusted Git revision without modifying its checkout."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


VERSION = 1
RUNNER_PATH = Path(__file__).resolve()
RUNNER_SHA256 = hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest()
PLUGIN_ID = "io.github.lostandadrift.wanikani"
STAGES = ("python", "manifest", "qmllint", "core_qt")
HEX = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SHELL_IMPORT = Path("/usr/share/omarchy/shell")


class VerificationError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def git(repository, *arguments):
    executable = shutil.which("git")
    if not executable:
        raise VerificationError("Git is required to resolve and archive the selected revision.")
    # Do not inherit injected Git options, credentials, tracing or work trees.
    environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        result = subprocess.run([executable, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "-C", str(repository), *arguments], stdin=subprocess.DEVNULL, capture_output=True,
            timeout=60, env=environment)
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError("The local Git read did not finish successfully.") from None
    if result.returncode:
        raise VerificationError("Git could not read the requested local repository or revision.")
    return result.stdout


def resolve(repository, revision):
    repository = Path(repository).resolve(strict=True)
    root = Path(os.fsdecode(git(repository, "rev-parse", "--show-toplevel")).strip()).resolve(strict=True)
    oid = git(root, "rev-parse", "--verify", "--end-of-options", revision).decode().strip()
    if not HEX.fullmatch(oid):
        raise VerificationError("The revision did not resolve to one exact Git object.")
    kind = git(root, "cat-file", "-t", oid).decode().strip()
    if kind not in ("commit", "tree"):
        raise VerificationError("Choose a commit or tree revision, not a tag object or file blob.")
    tree = git(root, "rev-parse", "--verify", "--end-of-options", oid + "^{tree}").decode().strip()
    if not HEX.fullmatch(tree):
        raise VerificationError("The selected object has no valid source tree.")
    return root, oid, tree, kind


def safe_name(name):
    return (bool(name) and not name.startswith("/") and "\\" not in name
        and all(part not in ("", ".", "..") for part in name.split("/"))
        and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name))


def entries(repository, tree):
    result = {}
    for record in git(repository, "ls-tree", "-r", "-z", "--full-tree", tree).split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        name = os.fsdecode(raw_name)
        if mode not in ("100644", "100755") or kind != "blob":
            raise VerificationError("Frozen verification accepts regular files only; links and submodules are unsupported.")
        if not safe_name(name) or not HEX.fullmatch(oid) or name in result:
            raise VerificationError("The Git tree contains an unsafe or ambiguous file path.")
        result[name] = {"blob": oid, "executable": mode == "100755"}
    if not result or "manifest.json" not in result:
        raise VerificationError("The source tree does not contain a plugin manifest.")
    return result


def output_directory(parent, repository):
    parent = Path(os.path.abspath(os.fspath(parent)))
    for path in (parent, *parent.parents):
        if path.is_symlink():
            raise VerificationError("The output parent must not contain symlink components.")
        if (path / "manifest.json").exists():
            raise VerificationError("Choose an output parent outside plugin directories.")
    if not parent.is_dir() or parent == repository or repository in parent.parents:
        raise VerificationError("Choose an existing output parent outside the source repository.")
    parts = parent.parts
    if any(parts[i:i + 2] == ("omarchy", "plugins") or parts[i:i + 3] == ("omarchy", "shell", "plugins")
            for i in range(len(parts))):
        raise VerificationError("Verification artifacts cannot be placed inside installed plugin directories.")
    destination = Path(tempfile.mkdtemp(prefix="wanikani-verify-", dir=parent))
    destination.chmod(0o700)
    if destination.resolve().parent != parent:
        raise VerificationError("The output parent changed while creating the private run directory.")
    return destination


def extract(repository, tree, expected, destination):
    archive = destination / "source.tar"
    archive.write_bytes(git(repository, "archive", "--format=tar", tree))
    archive.chmod(0o600)
    source = destination / "source"
    source.mkdir(mode=0o700)
    with tarfile.open(archive, "r:") as stream:
        members = stream.getmembers()
        seen = set()
        # Validate the entire member list before creating any archived path.
        for member in members:
            name = member.name.rstrip("/") if member.isdir() else member.name
            if not safe_name(name) or name in seen or not (member.isdir() or member.isreg()):
                raise VerificationError("The Git archive contains an unsafe path, duplicate, or non-regular file.")
            seen.add(name)
            if member.isreg() and name not in expected:
                raise VerificationError("The Git archive contains a file absent from its source tree.")
        for member in members:
            target = source.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with stream.extractfile(member) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(0o500 if expected[member.name]["executable"] else 0o400)
    for path in sorted(source.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o500)
    source.chmod(0o500)
    integrity(source, expected)
    return source


def integrity(source, expected):
    actual = {}
    directories = {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != "."}
    if source.is_symlink() or source.stat().st_mode & 0o222:
        raise VerificationError("The frozen archive directory became writable or changed identity.")
    for path in source.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise VerificationError("The frozen archive contains a link or non-regular path.")
        if mode & 0o222:
            raise VerificationError("A frozen path became writable during verification.")
        if stat.S_ISDIR(mode) and path.relative_to(source).as_posix() not in directories:
            raise VerificationError("A verification stage created an unexpected directory in the frozen archive.")
        if stat.S_ISREG(mode):
            name = path.relative_to(source).as_posix()
            if name not in expected:
                raise VerificationError("A verification stage created an unexpected file in the frozen archive.")
            if stat.S_IMODE(mode) != (0o500 if expected[name]["executable"] else 0o400):
                raise VerificationError("A frozen file's permissions or Git executable flag changed.")
            algorithm = "sha1" if len(expected[name]["blob"]) == 40 else "sha256"
            digest = hashlib.new(algorithm)
            digest.update(b"blob " + str(path.stat().st_size).encode("ascii") + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual[name] = digest.hexdigest()
    if set(actual) != set(expected) or any(actual[name] != data["blob"] for name, data in expected.items()):
        raise VerificationError("The archived bytes do not match every tracked Git blob.")


def environment(destination, source):
    values = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join((str(source / "backend"), str(source / "tests"))),
        "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "TMPDIR"):
        path = destination / "environment" / name.lower()
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
        values[name] = str(path)
    # All other inherited variables, including host/audio sockets, token keys,
    # WANIKANI_DECODER_QA and any future opt-in test flags, are omitted.
    return values


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def execute(argv, cwd, env, log, timeout):
    started = time.monotonic()
    process = None
    with log.open("xb") as output:
        log.chmod(0o600)
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            code = process.wait(timeout=timeout)
            return {"exit_code": code, "duration_seconds": round(time.monotonic() - started, 3),
                "status": "passed" if code == 0 else "failed"}
        except subprocess.TimeoutExpired:
            stop(process)
            return {"exit_code": process.returncode, "duration_seconds": round(time.monotonic() - started, 3),
                "status": "timed_out"}
        except KeyboardInterrupt:
            if process:
                stop(process)
            return {"exit_code": process.returncode if process else None,
                "duration_seconds": round(time.monotonic() - started, 3), "status": "cancelled"}
        except OSError:
            return {"exit_code": None, "duration_seconds": round(time.monotonic() - started, 3),
                "status": "could_not_start"}


def summary(stage, log, json_path, qml_paths):
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 2 * 1024 * 1024))
        text = stream.read().decode("utf-8", errors="replace")
    if stage == "python":
        runs = list(re.finditer(r"^Ran (\d+) tests? in [\d.]+s$", text, re.M))
        tail = text[runs[-1].end():].strip().splitlines() if runs else []
        ending = re.fullmatch(r"(OK|FAILED)(?: \(([^\n]*)\))?", tail[0]) if tail else None
        if not runs or ending is None:
            raise VerificationError("The Python log has no complete test summary.")
        counts = {"tests": int(runs[-1][1]), "skipped": 0, "failures": 0, "errors": 0,
            "expected_failures": 0, "unexpected_successes": 0, "outcome": ending[1]}
        if ending[2]:
            for field in ending[2].split(", "):
                count = re.fullmatch(r"(skipped|failures|errors|expected failures|unexpected successes)=(\d+)", field)
                if not count:
                    raise VerificationError("The Python test summary has an unknown result count.")
                counts[count[1].replace(" ", "_")] = int(count[2])
        if not counts["tests"] or counts["skipped"] >= counts["tests"]:
            raise VerificationError("The required Python tests did not execute any checks.")
        return counts
    if stage == "core_qt":
        totals = re.findall(r"^Totals: (\d+) passed, (\d+) failed, (\d+) skipped,", text, re.M)
        checks = len(re.findall(r"^PASS\s*:\s*[^\n]*::(?!initTestCase\(|cleanupTestCase\()[^\n]+", text, re.M))
        if not totals or not checks:
            raise VerificationError("The required core Qt tests did not report completed checks.")
        return {"checks": checks, **{key: sum(int(row[index]) for row in totals)
            for index, key in enumerate(("passed", "failures", "skipped"))}}
    if stage == "qmllint":
        if not json_path.is_file() or json_path.is_symlink() or json_path.stat().st_size > 16 * 1024 * 1024:
            raise VerificationError("qmllint did not produce a bounded JSON report.")
        try:
            data = json.loads(json_path.read_text())
            rows = data["files"]
            if not isinstance(rows, list) or len(rows) != len(qml_paths):
                raise ValueError
            if {row["filename"] for row in rows} != set(qml_paths):
                raise ValueError
            counts = {"files": len(rows), "warnings": 0, "errors": 0, "info": 0}
            for row in rows:
                if type(row["success"]) is not bool or not isinstance(row["warnings"], list):
                    raise ValueError
                for warning in row["warnings"]:
                    category = "errors" if warning["type"] in ("error", "critical") else "info" if warning["type"] == "info" else "warnings"
                    counts[category] += 1
                if row["success"] is False and not row["warnings"]:
                    counts["errors"] += 1
            return counts
        except (KeyError, TypeError, ValueError):
            raise VerificationError("The qmllint JSON report does not cover every requested runtime file.") from None
    return {}


def write_report(destination, report):
    pending = destination / "report.pending.json"
    pending.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
    pending.chmod(0o600)
    pending.replace(destination / "report.json")


def discover_tools():
    return {"python": sys.executable, "manifest": shutil.which("omarchy"),
        "qmllint": "/usr/lib/qt6/bin/qmllint", "core_qt": "/usr/lib/qt6/bin/qmltestrunner"}


def verify(repository, revision, output_parent, timeout=1800):
    root, oid, tree, kind = resolve(repository, revision)
    expected = entries(root, tree)
    destination = output_directory(output_parent, root)
    report = {"schema_version": VERSION, "runner": "wanikani-frozen-verification", "started_at": utc_now(),
        "runner_source": {"path": str(RUNNER_PATH), "sha256": RUNNER_SHA256, "scope": "invoking_file_outside_archive"},
        "finished_at": None, "status": "running", "revision": oid, "revision_kind": kind, "tree": tree,
        "plugin_version": None, "archive": str(destination / "source"), "report": str(destination / "report.json"),
        "integrity": {"before": None, "after": None, "tracked_files": len(expected)},
        "stages": [{"name": name, "required": True, "status": "not_run", "exit_code": None,
            "duration_seconds": None, "summary": None, "missing_tools": []} for name in STAGES]}
    write_report(destination, report)
    source = None
    try:
        source = extract(root, tree, expected, destination)
        report["integrity"]["before"] = "passed"
        manifest = json.loads((source / "manifest.json").read_text())
        if not isinstance(manifest, dict) or manifest.get("id") != PLUGIN_ID or not isinstance(manifest.get("version"), str):
            raise VerificationError("The frozen manifest must identify this WaniKani plugin and its version.")
        report["plugin_version"] = manifest["version"]
        (destination / "tracked-blobs.json").write_text(json.dumps(expected, indent=2) + "\n")
        (destination / "tracked-blobs.json").chmod(0o600)
        env = environment(destination, source)
        imports = destination / "imports"
        imports.mkdir(mode=0o700)
        if SHELL_IMPORT.is_dir():
            (imports / "qs").symlink_to(SHELL_IMPORT, target_is_directory=True)
        qml = [str(source / name) for name in sorted(expected)
            if name.endswith(".qml") and ("/" not in name or name.startswith("qml/"))]
        json_path = destination / "qmllint.json"
        tools = discover_tools()
        for stage in report["stages"]:
            name, executable = stage["name"], tools[stage["name"]]
            if not executable or not Path(executable).is_file() or not os.access(executable, os.X_OK):
                stage.update(status="missing_dependency", missing_tools=[name])
            elif name in ("qmllint", "core_qt") and not SHELL_IMPORT.is_dir():
                stage.update(status="missing_dependency", missing_tools=["installed shell QML imports"])
            elif name == "python" and not any(p.startswith("tests/test_") and p.endswith(".py") for p in expected):
                stage.update(status="missing_input")
            elif name == "core_qt" and not any(p.startswith("tests/qml/tst_") and p.endswith(".qml") for p in expected):
                stage.update(status="missing_input")
            elif name == "qmllint" and not qml:
                stage.update(status="missing_input")
            else:
                arguments = {"python": ["-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                    "manifest": ["plugin", "validate", str(source)],
                    "qmllint": ["--ignore-settings", "--json", str(json_path), "-I", str(imports), *qml],
                    "core_qt": ["-input", str(source / "tests/qml"), "-import", str(imports)]}[name]
                stage.update(status="running", argv=[executable, *arguments], log=str(destination / (name + ".log")))
                write_report(destination, report)
                stage.update(execute(stage["argv"], source, env, Path(stage["log"]), timeout))
                if stage["status"] not in ("cancelled", "timed_out", "could_not_start"):
                    try:
                        stage["summary"] = summary(name, Path(stage["log"]), json_path, qml)
                        if name == "manifest":
                            stage["summary"]["validated"] = stage["exit_code"] == 0
                        if stage["status"] == "passed":
                            counts = stage["summary"]
                            if counts.get("failures", 0) or counts.get("errors", 0) or counts.get("outcome", "OK") != "OK":
                                stage["status"] = "failed"
                            elif counts.get("skipped", 0):
                                stage["status"] = "passed_with_skips"
                            elif counts.get("expected_failures", 0):
                                stage["status"] = "passed_with_expected_failures"
                            elif counts.get("warnings", 0):
                                stage["status"] = "passed_with_warnings"
                    except VerificationError as error:
                        stage.update(status="incomplete" if stage["status"] == "passed" else stage["status"], notice=str(error))
            integrity(source, expected)
            write_report(destination, report)
            if stage["status"] == "cancelled":
                break
        report["status"] = ("cancelled" if any(s["status"] == "cancelled" for s in report["stages"])
            else "passed" if all(s["status"].startswith("passed") for s in report["stages"]) else "failed")
    except KeyboardInterrupt:
        report["status"] = "cancelled"
        for stage in report["stages"]:
            if stage["status"] == "running":
                stage["status"] = "cancelled"
    except (VerificationError, OSError, ValueError, tarfile.TarError) as error:
        report["status"] = "failed"
        report["notice"] = str(error) if isinstance(error, VerificationError) else "The private archive or verification report could not be prepared."
    finally:
        if source is not None:
            try:
                integrity(source, expected)
                report["integrity"]["after"] = "passed"
            except (VerificationError, OSError):
                report["integrity"]["after"] = "failed"
                report["status"] = "failed"
        report["finished_at"] = utc_now()
        write_report(destination, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Explicit trusted local commit or tree; resolved once to its exact hash")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output-parent", type=Path, default=Path("/tmp"), help="Existing external directory; creates a new private child (default /tmp)")
    parser.add_argument("--timeout", type=int, default=1800, help="Maximum seconds per required stage (1–7200; default 1800)")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 7200:
        parser.error("--timeout must be from 1 to 7200 seconds")
    old_umask = os.umask(0o077)
    old_term = signal.getsignal(signal.SIGTERM)
    def cancel(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, cancel)
    try:
        report = verify(args.repository, args.revision, args.output_parent, args.timeout)
        print("Verification " + report["status"] + ": " + report["revision"])
        print("Report: " + report["report"])
        print("Archive: " + report["archive"])
        return 0 if report["status"] == "passed" else 130 if report["status"] == "cancelled" else 1
    except KeyboardInterrupt:
        print("Verification cancelled before archive preparation completed.", file=sys.stderr)
        return 130
    except (VerificationError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, VerificationError) else "Verification could not prepare its private output.", file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGTERM, old_term)
        os.umask(old_umask)


if __name__ == "__main__":
    raise SystemExit(main())
