#!/usr/bin/env python3
"""Bounded local CLI for the existing WaniKani shell service. No daemon."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
import re
import shutil
import subprocess
import sys
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PLUGIN_ID = "io.github.lostandadrift.wanikani"
VERSION = 1
VIEWS = ("dashboard", "review-overview", "lesson-overview", "progress", "activity", "listen", "dictation", "lookup",
    "practice-library", "settings", "recovery", "help", "zen")
STATUSES = {"starting", "online", "offline", "disconnected", "demo", "clock_changed", "unauthorized",
    "forbidden", "rate_limited", "api_error", "sync_error", "access_restricted", "vacation", "invalid_request"}
COUNTS = ("reviews", "lessons", "pending", "attention", "listening_due", "level")
BOOLS = ("ready", "connected", "demo", "syncing", "vacation", "panel_open", "studying")
RHYTHM_STATUSES = {"off", "demo", "desktop_not_ready", "account_not_ready", "dnd", "locked", "fullscreen",
    "studying", "vacation", "clock_untrusted", "skip_today", "quiet", "snoozed", "daily_limit", "no_work", "recent_study", "cooldown", "ready"}
OUTBOX_STATES = ("pending", "inflight", "confirmed", "conflicted", "uncertain", "blocked", "discarded")
READINESS_GROUPS = ("reviews", "lessons", "upcoming_reviews")
READINESS_COUNTS = ("total", "checked", "ready", "missing_text", "missing_images", "audio_total", "audio_cached")
SYNC_STAGES = STATUSES | {"idle", "account", "resets", "subjects", "assignments", "study_materials", "review_statistics",
    "level_progressions", "spaced_repetition_systems", "summary", "unlocks", "reconcile", "submitting", "media", "complete", "cancelled"}
MAX_SAFE_INTEGER = 2**53 - 1
MAX_RESPONSE = 65536
PRODUCT_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")
DIGEST_COUNTERS = {
    "subject_completions": ("reviews", "lessons", "practice"),
    "sessions_completed": ("reviews", "lessons", "practice"),
    "listening_ratings": ("remembered", "again", "skipped"),
    "dictation_ratings": ("matched", "again", "skipped"),
}
DIGEST_SCALARS = ("listening_sessions_completed", "dictation_sessions_completed", "typo_corrections")


class CliError(Exception):
    def __init__(self, code, message, exit_code=4, action="Run doctor to inspect local availability.", delivery="not_sent"):
        self.code, self.message, self.exit_code = code, message, exit_code
        self.action, self.delivery = action, delivery


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's original error can contain supplied lookup text/options.
        raise CliError("invalid_arguments", "Invalid arguments.", 2, "Run --help or capabilities.")


def capabilities():
    return {
        "plugin_id": PLUGIN_ID, "transport": "local Omarchy shell IPC", "requires_daemon": False,
        "commands": {
            "capabilities": {"effect": "read_only", "shell_required": False, "description": "Describe this CLI's supported interface and effects."},
            "status": {"effect": "read_only", "description": "Read allowlisted aggregate cached status; no account request is initiated."},
            "report": {"effect": "read_only", "days": {"allowed": [7, 30], "default": 7},
                "description": "Project one cached local learning window through a single status call. No account refresh, network request, UI opening or fresh history calculation is initiated."},
            "doctor": {"effect": "read_only", "description": "Check dependency presence, shell/plugin accessibility and redacted cached status."},
            "open": {"effect": "show_ui", "views": list(VIEWS), "description": "Open a named surface; does not itself begin study or read clipboard text."},
            "reviews": {"effect": "begin_study", "user_intent_required": True, "all_due": True, "batch": {"minimum": 1, "maximum": 20, "default": "plugin preference"}},
            "lessons": {"effect": "begin_study", "user_intent_required": True, "batch": {"minimum": 1, "maximum": 20, "default": "plugin preference"}},
            "resume": {"effect": "begin_study", "user_intent_required": True, "batch": {"minimum": 1, "maximum": 20, "default": "plugin preference"}},
            "lookup": {"effect": "show_ui", "source": ["explicit TEXT", "--selection"], "maximum_code_points": 256,
                "description": "Read selection/clipboard only with --selection; supplied text is not echoed in output."},
            "refresh": {"effect": "sync_account_and_completed_work", "user_intent_required": True,
                "description": "Refresh the account and permit normal safe replay of previously completed pending work. Uncertain writes are never blindly retried."},
        },
        "study_effects": "Beginning/resuming creates or restores a local session and may refresh online, including normal replay of already completed pending work. It never supplies or acknowledges answers.",
        "completion": "A successful UI/refresh command acknowledges dispatch, not rendering, audio playback, completed synchronization, or a submitted study item.",
        "not_supported": ["answer", "grade", "automatic study", "forced recovery replay", "credential access", "raw worker/SQL access", "install", "desktop configuration", "background scheduling"],
        "status_semantics": {"pending": "Saved locally, not confirmed server progress.",
            "attention": "Records requiring inspection; may overlap pending.",
            "outbox_counts.confirmed": "Locally recorded confirmed operations when available; not account-wide review history.",
            "learning_progress": "Confirmed current-level requirement; required/remaining may be unknown while the cache is incomplete.",
            "learning_digest": "Retained local learning through its own generated_at timestamp, separate from confirmed remote operations and current account progress. Missing history stays unknown; status does not refresh it.",
            "saved_sessions": "Only presence flags; no questions, drafts, or subject IDs.",
            "reminders": "Current suppression status and next opportunity; never proof that a notification was delivered.",
            "readiness": "Cached last-check counts for due reviews, lessons and the next 24 hours. Partial or checking counts do not prove current offline availability; audio is optional for graded study.",
            "sync": "Cached synchronization stage and counts; no account request is initiated and no freeform error is returned.",
            "cache": "Registered cache file/byte counts and configured limit, not a fresh filesystem measurement or proof of playable audio.",
            "versions": "Reported loaded plugin manifest and worker product versions, not a Git revision or proof that every nested QML component was reloaded. Missing versions remain unknown.",
            "doctor.guidance": "Static suggestions from cached aggregates; separate from transport health and never executed automatically.",
            "null": "Unavailable in the installed service, not zero."},
        "exit_codes": {"0": "Read succeeded or action dispatch accepted.", "2": "Invalid arguments.",
            "3": "Missing dependency, inaccessible shell/plugin, or incomplete doctor.",
            "4": "Malformed/incompatible IPC response or unavailable view.", "5": "Bounded IPC timeout; an action may already have been accepted."},
    }


def parser():
    root = Parser(prog="wanikani", description="Inspect or deliberately open WaniKani through the running Omarchy shell.")
    common = argparse.ArgumentParser(add_help=False)
    for target, default in ((root, False), (common, argparse.SUPPRESS)):
        target.add_argument("--json", action="store_true", default=default, help="Print a versioned JSON envelope.")
        target.add_argument("--timeout", type=float, default=5.0 if target is root else argparse.SUPPRESS,
            help="Per-call timeout in seconds (1–15; default 5).")
    sub = root.add_subparsers(dest="command", parser_class=Parser)
    for command in ("capabilities", "status", "doctor", "refresh"):
        sub.add_parser(command, parents=[common])
    report_parser = sub.add_parser("report", parents=[common])
    report_parser.add_argument("--days", type=int, choices=(7, 30), default=7,
        help="Choose a cached local calendar window (7 or 30 days; default 7).")
    opened = sub.add_parser("open", parents=[common])
    opened.add_argument("view", choices=VIEWS)
    for command in ("reviews", "lessons", "resume"):
        study = sub.add_parser(command, parents=[common])
        size = study.add_mutually_exclusive_group()
        size.add_argument("--batch", type=int, choices=range(1, 21), metavar="1–20")
        if command == "reviews":
            size.add_argument("--all", dest="all_reviews", action="store_true", help="Review all eligible cached subjects due at session start.")
    lookup = sub.add_parser("lookup", parents=[common])
    source = lookup.add_mutually_exclusive_group(required=True)
    source.add_argument("text", nargs="?", help="Exact text to search; at most 256 Unicode code points.")
    source.add_argument("--selection", action="store_true", help="Explicitly read selection, falling back to clipboard.")
    return root


def _call(arguments, timeout, changes=False):
    if shutil.which("omarchy-shell") is None:
        raise CliError("missing_dependency", "The Omarchy shell command is unavailable.", 3,
            "Run this helper inside the installed Omarchy desktop.")
    try:
        result = subprocess.run(["omarchy-shell", *arguments], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
            # The packaged wrapper also bounds its qs child. Keep that inner
            # limit below ours even if the caller inherited a longer override.
            env={**os.environ, "OMARCHY_SHELL_IPC_TIMEOUT": str(max(.5, timeout - .5)) + "s"})
    except subprocess.TimeoutExpired as exc:
        raise CliError("timeout", "The local shell did not answer before the timeout.", 5,
            "Inspect status and the desktop before retrying; dispatch may already have occurred." if changes else "Run doctor or retry this read later.",
            "unknown" if changes else "not_applicable") from exc
    except OSError as exc:
        raise CliError("shell_unavailable", "The local shell command could not be started.", 3) from exc
    if result.returncode:
        raise CliError("shell_unavailable", "The running shell or requested plugin method is unavailable.", 3,
            "Run doctor; inspect plugin enablement in Omarchy Settings.", "unknown" if changes else "not_applicable")
    if len(result.stdout) > MAX_RESPONSE:
        raise CliError("invalid_response", "The shell response exceeded this interface's size limit.")
    return result.stdout.strip()


def _json(value):
    try:
        return json.loads(value)
    except (ValueError, TypeError) as exc:
        raise CliError("invalid_response", "The shell returned an invalid JSON response.") from exc


def _count(value, maximum=1_000_000_000):
    if value is not None and (type(value) is not int or not 0 <= value <= maximum):
        raise CliError("invalid_response", "An aggregate status field has an invalid type or range.")
    return value


def _boolean(value):
    if value is not None and type(value) is not bool:
        raise CliError("invalid_response", "An aggregate status flag has an invalid type.")
    return value


def _object(value):
    if not isinstance(value, dict):
        raise CliError("invalid_response", "An aggregate status section is malformed.")
    return value


def _enum(value, allowed):
    if value is not None and not isinstance(value, str):
        raise CliError("invalid_response", "An aggregate status label is malformed.")
    return value if value in allowed else "unknown" if value is not None else None


def _timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise CliError("invalid_response", "An aggregate timestamp is malformed.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliError("invalid_response", "An aggregate timestamp is malformed.") from exc
    return value


def _product_version(value):
    if value is not None and (not isinstance(value, str) or len(value) > 64 or PRODUCT_VERSION.fullmatch(value) is None):
        raise CliError("invalid_response", "A product version is malformed.")
    return value


def _learning_digest(value):
    """Validate the complete optional aggregate, then copy only public fields.

    Calendar validation uses the digest's zone, never the caller's timezone.
    A system-local cache lacks a stable IANA name, so its end day can only be
    checked against the possible local-date range of its recorded instant.
    """
    if value is None:
        return None
    try:
        if not isinstance(value, dict):
            raise ValueError
        expected = {"schema_version": 1, "scope": "recorded_on_this_device", "freshness": "cached",
            "coverage": "retained_local_records", "includes_retained_pre_reset_activity": True}
        if any(type(value.get(key)) is not type(wanted) or value[key] != wanted for key, wanted in expected.items()):
            raise ValueError
        for key in ("demo", "complete"):
            if type(value.get(key)) is not bool:
                raise ValueError
        if "stale" not in value or (value["stale"] is not None and type(value["stale"]) is not bool):
            raise ValueError
        epoch = value.get("data_epoch")
        if not isinstance(epoch, str) or len(epoch) != 36 or str(UUID(epoch)) != epoch:
            raise ValueError
        generated = _timestamp(value.get("generated_at"))
        if generated is None:
            raise ValueError
        if int(generated[11:13]) > 23 or int(generated[14:16]) > 59 or int(generated[17:19]) > 59:
            raise ValueError
        # datetime.fromisoformat normalizes offsets such as +01:99; a public
        # diagnostic must not accept that malformed timestamp as another time.
        if generated[-1] != "Z" and (int(generated[-5:-3]) > 23 or int(generated[-2:]) > 59):
            raise ValueError
        instant = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        zone_name = value.get("timezone")
        if (not isinstance(zone_name, str) or not 1 <= len(zone_name) <= 128
                or re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", zone_name) is None
                or any(part in (".", "..") for part in zone_name.split("/"))):
            raise ValueError
        zone = None if zone_name == "system-local" else ZoneInfo(zone_name)
        raw_windows = value.get("windows")
        if not isinstance(raw_windows, dict):
            raise ValueError
        windows = {}
        for days in (7, 30):
            raw = raw_windows.get(str(days))
            if not isinstance(raw, dict) or type(raw.get("days")) is not int or raw["days"] != days:
                raise ValueError
            dates = {}
            for key in ("start_day", "end_day"):
                label = raw.get(key)
                if not isinstance(label, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", label) is None:
                    raise ValueError
                dates[key] = date.fromisoformat(label)
            if dates["end_day"] - dates["start_day"] != timedelta(days=days - 1):
                raise ValueError
            if zone is not None:
                if instant.astimezone(zone).date() != dates["end_day"]:
                    raise ValueError
            elif abs((dates["end_day"] - instant.astimezone(timezone.utc).date()).days) > 1:
                raise ValueError
            window = {"days": days, **{key: dates[key].isoformat() for key in dates}}
            for metric, names in DIGEST_COUNTERS.items():
                counters = raw.get(metric)
                if not isinstance(counters, dict):
                    raise ValueError
                window[metric] = {}
                for name in names:
                    count = counters.get(name)
                    if type(count) is not int or not 0 <= count <= MAX_SAFE_INTEGER:
                        raise ValueError
                    window[metric][name] = count
            for metric in DIGEST_SCALARS:
                count = raw.get(metric)
                if type(count) is not int or not 0 <= count <= MAX_SAFE_INTEGER:
                    raise ValueError
                window[metric] = count
            windows[str(days)] = window
        short, long = windows["7"], windows["30"]
        if short["end_day"] != long["end_day"]:
            raise ValueError
        if any(short[metric][name] > long[metric][name]
                for metric, names in DIGEST_COUNTERS.items() for name in names):
            raise ValueError
        if any(short[metric] > long[metric] for metric in DIGEST_SCALARS):
            raise ValueError
        return {**expected, "generated_at": generated, "data_epoch": epoch, "demo": value["demo"],
            "timezone": zone_name, "complete": value["complete"], "stale": value["stale"], "windows": windows}
    except (CliError, ValueError, TypeError, OverflowError, OSError, ZoneInfoNotFoundError):
        raise CliError("invalid_response", "The cached learning summary is malformed or unsupported.") from None


def status(timeout=5):
    value = _json(_call(["wanikani", "status"], timeout))
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        raise CliError("invalid_response", "The plugin did not return aggregate status.")
    if "schemaVersion" in value and (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1):
        raise CliError("incompatible_version", "This plugin uses an unsupported status protocol.", 4, "Update the helper and plugin together.")
    result = {"status": value["status"] if value["status"] in STATUSES else "unknown"}
    result["versions"] = None
    if value.get("versions") is not None:
        versions = _object(value["versions"])
        result["versions"] = {key: _product_version(versions.get(key)) for key in ("plugin", "worker")}
    for key in COUNTS:
        result[key] = _count(value.get(key))
    for key in BOOLS:
        result[key] = _boolean(value.get(key))
    for key in ("next_reviews_at", "last_sync"):
        result[key] = _timestamp(value.get(key))
    result["outbox_counts"] = None
    if value.get("outbox_counts") is not None:
        if not isinstance(value["outbox_counts"], dict):
            raise CliError("invalid_response", "The submission summary is malformed.")
        result["outbox_counts"] = {key: _count(value["outbox_counts"].get(key)) for key in OUTBOX_STATES}
    result["learning_progress"] = None
    if value.get("learning_progress") is not None:
        progress = _object(value["learning_progress"])
        result["learning_progress"] = {key: _count(progress.get(key))
            for key in ("level", "passed", "required", "remaining", "pending", "attention")}
        result["learning_progress"].update({key: _boolean(progress.get(key)) for key in ("complete", "threshold_met")})
    result["learning_digest"] = _learning_digest(value.get("learning_digest"))
    result["saved_sessions"] = None
    if value.get("saved_sessions") is not None:
        sessions = _object(value["saved_sessions"])
        result["saved_sessions"] = {key: _boolean(sessions.get(key)) for key in ("reviews", "lessons", "practice")}
    result["reminders"] = None
    if value.get("reminders") is not None:
        rhythm = _object(value["reminders"])
        state = rhythm.get("status")
        if state is not None and not isinstance(state, str):
            raise CliError("invalid_response", "The reminder status is malformed.")
        deadline = rhythm.get("next_at")
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline) or not 0 <= deadline <= 253339228800):
            raise CliError("invalid_response", "The next reminder time is malformed.")
        result["reminders"] = {"status": state if state in RHYTHM_STATUSES else "unknown" if state is not None else None,
            "next_at": deadline, "remaining_today": _count(rhythm.get("remaining_today"))}
    result["readiness"] = None
    if value.get("readiness") is not None:
        readiness = _object(value["readiness"])
        result["readiness"] = {key: _boolean(readiness.get(key)) for key in ("complete", "checking")}
        result["readiness"]["checked_at"] = _timestamp(readiness.get("checked_at"))
        for mode in READINESS_GROUPS:
            group = readiness.get(mode)
            if group is not None:
                group = _object(group)
                group = {**{key: _count(group.get(key)) for key in READINESS_COUNTS},
                    "total_complete": _boolean(group.get("total_complete"))}
            result["readiness"][mode] = group
    result["sync"] = None
    if value.get("sync") is not None:
        sync = _object(value["sync"])
        result["sync"] = {"stage": _enum(sync.get("stage"), SYNC_STAGES), "active": _boolean(sync.get("active")),
            "completed": _count(sync.get("completed")), "total": _count(sync.get("total"))}
    result["cache"] = None
    if value.get("cache") is not None:
        cache = _object(value["cache"])
        result["cache"] = {**{key: _count(cache.get(key)) for key in ("files", "subjects")},
            **{key: _count(cache.get(key), MAX_SAFE_INTEGER) for key in ("bytes", "limit_bytes")}}
    # No unknown key, freeform message, username, subject, answer, or path enters
    # the output, even if a future service accidentally includes one.
    return result


def report(timeout=5, days=7):
    """Select a cached window using exactly the existing status transport."""
    if type(days) is not int or days not in (7, 30):
        raise CliError("invalid_arguments", "Choose a cached report window of 7 or 30 days.", 2,
            "Run report --help or capabilities.")
    digest = status(timeout)["learning_digest"]
    if digest is None:
        return {"available": False, "reason": "unavailable", "digest": None}
    return {"available": True, "reason": None,
        "digest": {**{key: value for key, value in digest.items() if key != "windows"},
            "window": digest["windows"][str(days)]}}


def _report_text(data):
    if not data["available"]:
        return "Cached local learning totals are unavailable. No refresh was requested."
    digest = data["digest"]
    window = digest["window"]
    completions = window["subject_completions"]
    sessions = window["sessions_completed"]
    listening = window["listening_ratings"]
    dictation = window["dictation_ratings"]
    lines = ["Recorded on this device · cached through " + digest["generated_at"],
        f"{window['start_day']}–{window['end_day']} · {digest['timezone']} · {window['days']} local days (final day partial)"]
    if digest["demo"]:
        lines.append("Authored demo activity.")
    if digest["stale"] is True:
        lines.append("This cached summary is known to be stale.")
    elif digest["stale"] is None:
        lines.append("Whether this cached summary is stale is unknown.")
    if not digest["complete"]:
        lines.append("The supported aggregate calculation is incomplete.")
    lines.extend([
        f"Completed cycles: {completions['reviews']} reviews · {completions['lessons']} lessons · {completions['practice']} practice",
        f"Completed batches: {sessions['reviews']} reviews · {sessions['lessons']} lessons · {sessions['practice']} practice",
        f"Listening: {listening['remembered']} remembered · {listening['again']} again · {listening['skipped']} skipped · {window['listening_sessions_completed']} batches",
        f"Dictation: {dictation['matched']} matched · {dictation['again']} again · {dictation['skipped']} skipped · {window['dictation_sessions_completed']} batches",
        f"Typo corrections: {window['typo_corrections']}",
        "Retained local records, including earlier resets; review cycles are not server confirmations."])
    return "\n".join(lines)


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise CliError("invalid_text", "Supply nonempty lookup text of at most 256 Unicode code points.", 2,
            "Use lookup TEXT or lookup --selection.")
    if any(0xD800 <= ord(char) <= 0xDFFF or (ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127 for char in value):
        raise CliError("invalid_text", "Lookup text contains unsupported control characters.", 2)
    return value


def dispatch(args):
    command = args.command or "capabilities"
    if command == "capabilities":
        return capabilities(), 0
    if command == "status":
        return status(args.timeout), 0
    if command == "report":
        return report(args.timeout, args.days), 0
    if command == "doctor":
        data = doctor(args.timeout)
        return data, 0 if data["healthy"] else 3
    if command == "refresh":
        output = _call(["wanikani", "refresh"], args.timeout, changes=True)
        if output not in ("", "ok"):
            raise CliError("invalid_response", "The refresh acknowledgement was not recognized.", 4,
                "Inspect status before trying again.", "unknown")
        return {"accepted": True, "completion": "asynchronous", "may_submit_completed_pending_work": True}, 0
    payload = {"view": args.view if command == "open" else command}
    if command in ("reviews", "lessons", "resume") and args.batch is not None:
        payload["limit"] = args.batch
    if command == "reviews" and args.all_reviews:
        payload["all_reviews"] = True
    if command == "lookup":
        if args.selection:
            payload["selection"] = True
        else:
            payload["text"] = _text(args.text)
    output = _call(["shell", "summon", PLUGIN_ID, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))], args.timeout, changes=True)
    if output != "ok":
        raise CliError("view_unavailable", "The shell did not accept this plugin view.", 4,
            "Run doctor and ensure the helper matches the installed plugin.", "not_sent" if output == "unknown" else "unknown")
    result = {"accepted": True, "view": payload["view"], "completion": "dispatch_only"}
    if "limit" in payload:
        result["batch"] = payload["limit"]
    if payload.get("all_reviews"):
        result["all_reviews"] = True
    if command == "lookup":
        result["source"] = "selection_or_clipboard" if args.selection else "supplied_text"
    return result, 0


def _guidance(status):
    """Suggest native controls using cached evidence, without taking an action."""
    if status is None:
        return []
    result = []

    def add(code, action):
        result.append({"code": code, "action": action})

    versions = status.get("versions") or {}
    if versions.get("plugin") is not None and versions.get("worker") is not None and versions["plugin"] != versions["worker"]:
        add("runtime_version_mismatch", "The loaded plugin and worker report different versions; a hot reload may be incomplete. Wait until study is closed and the desktop is unlocked before a normal plugin update or shell restart. This diagnostic performs neither action.")
    counts = status.get("outbox_counts") or {}
    if (counts.get("uncertain") or 0) > 0:
        add("uncertain_work", "Open Recovery to inspect uncertain submissions. Never force or blindly repeat a write.")
    elif (status.get("attention") or 0) > 0:
        add("recovery_attention", "Open Recovery to inspect saved operations that need attention.")
    elif (status.get("pending") or 0) > 0:
        add("pending_work", "Work is saved locally. Refresh only when you intend to synchronize; it may submit already completed pending work.")
    if status.get("status") in ("unauthorized", "forbidden", "access_restricted", "disconnected"):
        add("account_attention", "Open Settings to inspect account access. This diagnostic has not checked credentials or contacted WaniKani.")
    elif status.get("status") == "clock_changed":
        add("clock_attention", "Inspect the system clock and the account status in Settings before relying on offline schedules.")
    sync = status.get("sync") or {}
    if sync.get("active") is True:
        add("sync_in_progress", "Synchronization is already active. Read status again later instead of starting another refresh.")
    readiness = status.get("readiness")
    if readiness is None:
        add("offline_readiness_unknown", "Offline readiness is unavailable in this cached status. Open Settings to inspect supported cache checks.")
    else:
        groups = [readiness.get(mode) for mode in READINESS_GROUPS]
        known = (readiness.get("complete") is True and readiness.get("checking") is False
            and readiness.get("checked_at") is not None and all(group is not None
                and group.get("total_complete") is True and all(group.get(key) is not None for key in READINESS_COUNTS)
                and group["checked"] == group["total"] and group["ready"] <= group["checked"]
                and group["missing_text"] <= group["checked"] and group["missing_images"] <= group["checked"]
                and group["audio_cached"] <= group["audio_total"] <= group["checked"]
                for group in groups))
        if readiness.get("checking") is True:
            add("offline_checking", "Offline availability is being checked. Counts may be from a previous check; read status again when it finishes.")
        elif not known:
            add("offline_readiness_incomplete", "The cached offline check is incomplete. Open Settings and choose Check offline availability; no account refresh is started by this diagnostic.")
        elif any(group["missing_text"] or group["missing_images"] for group in groups):
            add("required_media_missing", "Required text or radical images were missing at the last check. Inspect offline availability in Settings; an explicit account refresh may also submit completed pending work.")
        elif any(group["audio_cached"] < group["audio_total"] for group in groups):
            add("optional_audio_missing", "Some pronunciation audio was missing at the last check. This does not block text-based graded study; open Settings for cache coverage, or Listen for its separate familiar-word recording check.")
    cache = status.get("cache") or {}
    if cache.get("bytes") is not None and cache.get("limit_bytes") is not None and cache["bytes"] > cache["limit_bytes"]:
        add("cache_over_limit", "Registered cache bytes exceed the configured limit. Inspect cache management in Settings; this diagnostic neither measures files nor deletes them.")
    return result


def doctor(timeout=5):
    dependencies = {name: {"present": shutil.which(name) is not None, "required": required}
        for name, required in (("python3", True), ("omarchy-shell", True), ("qs", True), ("secret-tool", False), ("wl-paste", False))}
    result = {"dependencies": dependencies, "shell_accessible": False,
        "plugin": {"id": PLUGIN_ID, "listed": None, "manager_enabled": None, "service_accessible": False},
        "status": None, "issues": []}
    for command, required in (("python3", True), ("omarchy-shell", True), ("qs", True)):
        if not dependencies[command]["present"]:
            result["issues"].append({"code": "missing_dependency", "dependency": command,
                "action": "Use the installed Omarchy desktop and its required runtime."})
    try:
        result["shell_accessible"] = _call(["shell", "ping"], timeout) == "ok"
        if not result["shell_accessible"]:
            result["issues"].append({"code": "shell_not_ready", "action": "Wait for the existing shell to be ready."})
    except CliError as error:
        result["issues"].append({"code": error.code, "action": error.action})
    if result["shell_accessible"]:
        try:
            listing = _json(_call(["shell", "listPlugins"], timeout))
            if not isinstance(listing, list):
                raise CliError("invalid_response", "The shell plugin inventory is malformed.")
            matches = [entry for entry in listing if isinstance(entry, dict) and entry.get("id") == PLUGIN_ID]
            result["plugin"]["listed"] = bool(matches)
            if len(matches) == 1 and type(matches[0].get("enabled")) is bool:
                result["plugin"]["manager_enabled"] = matches[0]["enabled"]
            if not matches:
                result["issues"].append({"code": "plugin_not_listed", "action": "Install or enable the plugin through Omarchy Settings when requested."})
        except CliError as error:
            result["issues"].append({"code": error.code, "action": error.action})
        try:
            result["status"] = status(timeout)
            result["plugin"]["service_accessible"] = True
        except CliError as error:
            result["issues"].append({"code": error.code, "action": error.action})
    result["healthy"] = (not result["issues"] and result["shell_accessible"] and result["plugin"]["service_accessible"])
    result["guidance"] = _guidance(result["status"])
    result["limits"] = ["Does not check the token, keyring contents, audio device, network, or WaniKani account correctness.",
        "For a bar widget, manager_enabled describes bar placement; service_accessible is the direct service check.",
        "Pending records are local work, not confirmed progress. Inspect attention in Recovery; never force a retry."]
    return result


def envelope(command, data=None, error=None):
    return {"protocol": "wanikani-cli", "version": VERSION, "command": command,
        "ok": error is None, "data": data, "error": None if error is None else {
            "code": error.code, "message": error.message, "action": error.action, "delivery": error.delivery}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    options = argv[:argv.index("--")] if "--" in argv else argv
    as_json = "--json" in options
    command = next((value for value in argv if value in capabilities()["commands"]), "capabilities")
    try:
        if as_json and ("--help" in options or "-h" in options):
            data, code, command = capabilities(), 0, "capabilities"
        else:
            args = parser().parse_args(argv)
            as_json = args.json
            command = args.command or "capabilities"
            if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 15:
                raise CliError("invalid_timeout", "Choose a per-call timeout between 1 and 15 seconds.", 2)
            data, code = dispatch(args)
        problem = CliError("doctor_incomplete", "Some local availability checks need attention.", 3,
            "Read the doctor's issues; no repair was attempted.") if code else None
        result = envelope(command, data, problem)
    except CliError as error:
        code = error.exit_code
        result = envelope(command, error=error)
    if as_json or command == "capabilities":
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    elif result["error"]:
        print(result["error"]["message"] + " " + result["error"]["action"], file=sys.stderr)
        if result["data"]:
            print(json.dumps(result["data"], ensure_ascii=False, indent=2))
    elif command == "report":
        print(_report_text(result["data"]))
    else:
        print(json.dumps(result["data"], ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
