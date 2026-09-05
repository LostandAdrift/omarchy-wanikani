#!/usr/bin/env python3
"""Bounded local CLI for the existing WaniKani shell service. No daemon."""
import argparse
from datetime import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys


PLUGIN_ID = "io.github.lostandadrift.wanikani"
VERSION = 1
VIEWS = ("dashboard", "review-overview", "lesson-overview", "progress", "activity", "listen", "lookup",
    "practice-library", "settings", "recovery", "help", "zen")
STATUSES = {"starting", "online", "offline", "disconnected", "demo", "clock_changed", "unauthorized",
    "forbidden", "rate_limited", "api_error", "sync_error", "access_restricted", "vacation", "invalid_request"}
COUNTS = ("reviews", "lessons", "pending", "attention", "listening_due", "level")
BOOLS = ("ready", "connected", "demo", "syncing", "vacation", "panel_open", "studying")
RHYTHM_STATUSES = {"off", "demo", "desktop_not_ready", "account_not_ready", "dnd", "locked", "fullscreen",
    "studying", "vacation", "clock_untrusted", "skip_today", "quiet", "snoozed", "daily_limit", "no_work", "recent_study", "cooldown", "ready"}
OUTBOX_STATES = ("pending", "inflight", "confirmed", "conflicted", "uncertain", "blocked", "discarded")
MAX_RESPONSE = 65536


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
            "doctor": {"effect": "read_only", "description": "Check dependency presence, shell/plugin accessibility and redacted cached status."},
            "open": {"effect": "show_ui", "views": list(VIEWS), "description": "Open a named surface; does not itself begin study or read clipboard text."},
            "reviews": {"effect": "begin_study", "user_intent_required": True, "batch": {"minimum": 1, "maximum": 20, "default": "plugin preference"}},
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
            "saved_sessions": "Only presence flags; no questions, drafts, or subject IDs.",
            "reminders": "Current suppression status and next opportunity; never proof that a notification was delivered.",
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
    opened = sub.add_parser("open", parents=[common])
    opened.add_argument("view", choices=VIEWS)
    for command in ("reviews", "lessons", "resume"):
        study = sub.add_parser(command, parents=[common])
        study.add_argument("--batch", type=int, choices=range(1, 21), metavar="1–20")
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


def _count(value):
    if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000_000):
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


def status(timeout=5):
    value = _json(_call(["wanikani", "status"], timeout))
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        raise CliError("invalid_response", "The plugin did not return aggregate status.")
    if "schemaVersion" in value and (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1):
        raise CliError("incompatible_version", "This plugin uses an unsupported status protocol.", 4, "Update the helper and plugin together.")
    result = {"status": value["status"] if value["status"] in STATUSES else "unknown"}
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
    # No unknown key, freeform message, username, subject, answer, or path enters
    # the output, even if a future service accidentally includes one.
    return result


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
    if command == "lookup":
        result["source"] = "selection_or_clipboard" if args.selection else "supplied_text"
    return result, 0


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
    else:
        print(json.dumps(result["data"], ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
