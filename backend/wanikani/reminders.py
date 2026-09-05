"""Durable, local study rhythm. This module never sends a notification.

The worker supplies current shell flags and work counts; claim() commits the
opportunity before returning a toast payload. The caller may lose a toast after
a crash, but must not retry its claim ID. preview() never writes. next_at is a
real epoch deadline for the service's one-shot timer, not a polling interval.
"""
import copy
from datetime import datetime, time, timedelta
import math
from pathlib import Path
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import UserError


CONFIG_KEY = "study_rhythm"
STATE_KEY = "study_rhythm_state"
GRACE_SECONDS = 60
RESET_EVENTS = {"startup", "wake", "clock_change", "reconnect"}
BASE = {
    "enabled": True, "mode": "due", "target": "both",
    "times": ["10:00", "14:00", "18:00"], "interval_hours": 2,
    "window_start": "08:00", "window_end": "22:00",
    "quiet_start": "22:00", "quiet_end": "08:00",
    "minimum_interval_seconds": 7200, "daily_limit": 3,
    "recent_study_seconds": 1800,
}


def _number(value, default=0):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else default


def defaults(engine=None):
    """Return independent defaults, honoring explicit legacy preferences."""
    result = copy.deepcopy(BASE)
    if engine is not None:
        legacy = engine.store.get("settings", {})
        if isinstance(legacy, dict):
            if type(legacy.get("notifications")) is bool:
                result["enabled"] = legacy["notifications"]
            for key in ("quiet_start", "quiet_end"):
                if type(legacy.get(key)) is int and 0 <= legacy[key] <= 23:
                    result[key] = f"{legacy[key]:02}:00"
            interval = legacy.get("reminder_interval")
            if type(interval) is int and 1800 <= interval <= 86400:
                result["minimum_interval_seconds"] = interval
    return result


def _minute(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise UserError("Choose a local time in HH:MM format.")
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


def _validated(config, patch):
    if not isinstance(patch, dict) or any(key not in BASE for key in patch):
        raise UserError("Choose supported study rhythm settings.")
    result = {**copy.deepcopy(config), **copy.deepcopy(patch)}
    if type(result["enabled"]) is not bool:
        raise UserError("Choose whether study reminders are on or off.")
    if result["mode"] not in ("due", "times", "interval") or result["target"] not in ("reviews", "listening", "both"):
        raise UserError("Choose a reminder schedule and activity.")
    for key, low, high in (("interval_hours", 1, 12), ("minimum_interval_seconds", 1800, 86400),
            ("daily_limit", 1, 12), ("recent_study_seconds", 0, 7200)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise UserError("Choose a study rhythm value within the displayed range.")
    for key in ("window_start", "window_end", "quiet_start", "quiet_end"):
        _minute(result[key])
    if _minute(result["window_start"]) >= _minute(result["window_end"]):
        raise UserError("The daytime window must end after it starts.")
    times = result["times"]
    if not isinstance(times, list) or not 1 <= len(times) <= 12:
        raise UserError("Choose between one and twelve reminder times.")
    for value in times:
        _minute(value)
    result["times"] = sorted(set(times))
    return result


def _config(engine):
    base = defaults(engine)
    saved = engine.store.get(CONFIG_KEY, {})
    try:
        return _validated(base, saved)
    except UserError:
        # A damaged profile must not turn on a new stream of reminders.
        return {**base, "enabled": False}


def _clock(engine, context):
    if not isinstance(context, dict):
        raise UserError("Study rhythm needs current desktop context.")
    now = context.get("now", engine.now())
    # Leave a full year for timezone conversion and the bounded future window.
    if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now <= 253339228800:
        raise UserError("Study rhythm needs a valid current time.")
    name = context.get("timezone")
    if name is None:
        local = Path("/etc/localtime").resolve()
        try:
            name = str(local.relative_to("/usr/share/zoneinfo"))
        except ValueError:
            # ZoneInfo.from_file retains DST rules, unlike a fixed UTC offset.
            try:
                with local.open("rb") as handle:
                    return float(now), ZoneInfo.from_file(handle, key="system-local"), "system-local"
            except OSError as exc:
                raise UserError("The local timezone is unavailable.") from exc
    if not isinstance(name, str) or not name or len(name) > 128:
        raise UserError("Choose a valid local timezone.")
    try:
        return float(now), ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UserError("Choose a valid local timezone.") from exc


def _local_slot(day, minute, zone):
    naive = datetime.combine(day, time(minute // 60, minute % 60))
    # Only the first occurrence of an autumn repeated wall time is an
    # opportunity. A spring-forward nonexistent time is skipped completely.
    value = naive.replace(tzinfo=zone, fold=0).timestamp()
    return value if datetime.fromtimestamp(value, zone).replace(tzinfo=None) == naive else None


def _quiet(config, local):
    start, end = _minute(config["quiet_start"]), _minute(config["quiet_end"])
    minute = local.hour * 60 + local.minute
    if start < end:
        return start <= minute < end
    if start > end:
        return minute >= start or minute < end
    return False


def _slots(config, now, zone):
    if config["mode"] == "due":
        return []
    minutes = ([_minute(value) for value in config["times"]] if config["mode"] == "times" else
        range(_minute(config["window_start"]), _minute(config["window_end"]), config["interval_hours"] * 60))
    today = datetime.fromtimestamp(now, zone).date()
    result = []
    # Yesterday covers a timer crossing midnight; the following week provides
    # the next eligible deadline even with a full daily budget or a skipped day.
    for offset in range(-1, 8):
        day = today + timedelta(days=offset)
        for minute in minutes:
            at = _local_slot(day, minute, zone)
            if at is not None:
                result.append((at, f"{day.isoformat()}T{minute // 60:02}:{minute % 60:02}", config["mode"]))
    return sorted(result)


def _actions(config, context):
    actions = []
    if config["target"] != "listening" and _number(context.get("review_count")) > 0:
        actions.append({"label": "Review 5", "view": "reviews", "limit": 5})
    if config["target"] != "reviews" and _number(context.get("listen_count")) > 0:
        actions.append({"label": "Listen 5", "view": "listen", "limit": 5})
    return actions


def _identity(engine):
    return [engine.store.get("account_id", ""), engine.store.get("session_epoch", ""), bool(engine.demo)]


def _fresh(engine, config):
    legacy = engine.store.get("settings", {})
    legacy = legacy if isinstance(legacy, dict) else {}
    return {"version": 1, "identity": _identity(engine), "previous_due": -1,
        "last_notification_at": _number(legacy.get("last_notification_at")), "counts": {},
        "consumed": [], "snooze_at": _number(legacy.get("snooze_until")), "skip_date": ""}


def _state(engine, config):
    state = engine.store.get(STATE_KEY)
    if (not isinstance(state, dict) or state.get("version") != 1 or state.get("identity") != _identity(engine)
            or not isinstance(state.get("counts"), dict) or not isinstance(state.get("consumed"), list)):
        return _fresh(engine, config)
    return copy.deepcopy(state)


def _reason(engine, config, context, state, now, local, actions, snoozed=False):
    if not config["enabled"]:
        return "off", "Study reminders are off."
    if engine.demo or context.get("demo") is True:
        return "demo", "Reminders stay quiet in the example account."
    if context.get("hydrated") is not True:
        return "desktop_not_ready", "Waiting for desktop notification settings."
    if context.get("account_ready") is not True:
        return "account_not_ready", "Waiting for the account to be ready."
    for flag, status, message in (
            ("dnd", "dnd", "Paused by Do Not Disturb."), ("locked", "locked", "Paused while the desktop is locked."),
            ("fullscreen", "fullscreen", "Paused while an application is fullscreen."),
            ("studying", "studying", "Paused while you study."), ("vacation", "vacation", "Paused during vacation."),
            ("clock_untrusted", "clock_untrusted", "Waiting for the clock to be checked.")):
        if context.get(flag) is not False:
            return status, message
    if state.get("skip_date") == local.date().isoformat():
        return "skip_today", "Skipped for today."
    if _quiet(config, local):
        return "quiet", "Paused during quiet hours."
    if _number(state.get("snooze_at")) > now:
        return "snoozed", "Snoozed until the chosen reminder."
    if _number(state["counts"].get(local.date().isoformat())) >= config["daily_limit"]:
        return "daily_limit", "Today's reminder limit is reached."
    if not actions:
        return "no_work", "No eligible review or listening work is available."
    recent = max(_number(context.get("last_study_at")), _number(engine.store.get("last_study_at")))
    if recent and now < recent + config["recent_study_seconds"]:
        return "recent_study", "You studied recently; the next invitation can wait."
    if not snoozed and _number(state.get("last_notification_at")) and now < state["last_notification_at"] + config["minimum_interval_seconds"]:
        return "cooldown", "Waiting between study reminders."
    return "ready", "A short Japanese break is available."


def _next(config, context, state, now, zone, slots):
    if not config["enabled"]:
        return None, "Study reminders are off."
    snooze = _number(state.get("snooze_at"))
    if snooze > now:
        return snooze, "Your snoozed study reminder."
    for at, key, kind in slots:
        if at <= now or key in state["consumed"]:
            continue
        local = datetime.fromtimestamp(at, zone)
        if _quiet(config, local) or state.get("skip_date") == local.date().isoformat():
            continue
        if _number(state["counts"].get(local.date().isoformat())) >= config["daily_limit"]:
            continue
        if _number(state.get("last_notification_at")) and at < state["last_notification_at"] + config["minimum_interval_seconds"]:
            continue
        return at, "At a chosen time." if kind == "times" else "During your daytime study window."
    if config["mode"] == "due":
        due = _number(context.get("next_review_at"))
        return (due if due > now else None), "When more reviews become available."
    return None, "No reminder is scheduled in the next week."


def _evaluate(engine, config, context, state, emit=True):
    now, zone, zone_name = _clock(engine, context)
    local = datetime.fromtimestamp(now, zone)
    today = local.date().isoformat()
    observed = _number(state.get("observed_at"), -1)
    suppressed_context = (context.get("hydrated") is not True or context.get("account_ready") is not True
        or context.get("demo") is True or any(context.get(flag) is not False for flag in
            ("dnd", "locked", "fullscreen", "studying", "vacation", "clock_untrusted")))
    reset = (observed < 0 or context.get("event") in RESET_EVENTS or state.get("timezone") != zone_name
        or now < observed or (state.get("suppressed_context") is True and not suppressed_context))
    old_due = state.get("previous_due", -1)
    due = _number(context.get("review_count"))
    slots = _slots(config, now, zone)
    candidates = []
    if not reset:
        candidates = [(at, key, kind) for at, key, kind in slots
            if observed < at <= now and key not in state["consumed"]]
        if config["mode"] == "due" and type(old_due) in (int, float) and old_due >= 0 and due > old_due:
            candidates.append((now, "due:" + str(now), "due"))
    snooze = _number(state.get("snooze_at"))
    if snooze and snooze <= now:
        if not reset and observed < snooze:
            candidates.append((snooze, "snooze:" + str(snooze), "snooze"))
        state["snooze_at"] = 0
    # Every observed slot is consumed, including suppressed/late opportunities.
    for at, key, kind in slots:
        if at <= now and key not in state["consumed"]:
            state["consumed"].append(key)
    cutoff = (local.date() - timedelta(days=7)).isoformat()
    state["consumed"] = [key for key in state["consumed"] if isinstance(key, str) and key[:10] >= cutoff][-192:]
    state["counts"] = {day: int(count) for day, count in state["counts"].items()
        if isinstance(day, str) and day >= cutoff and type(count) is int and count >= 0}
    # Returning from DND/lock/study or initial hydration starts observing now.
    # The timer may have missed a slot while suppressed even inside its grace
    # period; leaving suppression must not turn that slot into a fresh toast.
    state.update(observed_at=now, timezone=zone_name, previous_due=due, suppressed_context=suppressed_context)
    # Snooze is collected separately. An expired snooze must not mask a newer
    # scheduled opportunity; equal-time snooze still uses its explicit policy.
    opportunity = max(candidates, key=lambda item: (item[0], item[2] == "snooze")) if candidates else None
    explicit_snooze = bool(opportunity and opportunity[2] == "snooze")
    actions = _actions(config, context)
    status, reason = _reason(engine, config, context, state, now, local, actions, explicit_snooze)
    notification = None
    if emit and opportunity and now - opportunity[0] <= GRACE_SECONDS and status == "ready":
        notification = {"id": str(uuid.uuid4()), "title": "Take a Japanese break",
            "body": "Choose a short review or listening session." if len(actions) > 1 else
                "Five reviews, then back to work." if actions[0]["view"] == "reviews" else "Listen to five words.",
            "actions": actions, "reason": opportunity[2]}
        state["last_notification_at"] = now
        state["counts"][today] = state["counts"].get(today, 0) + 1
        state["last_claim_id"] = notification["id"]
    next_at, next_reason = _next(config, context, state, now, zone, slots)
    result = {"config": config, "status": status, "reason": reason,
        "next_at": next_at, "next_reason": next_reason, "timezone": zone_name,
        "available_actions": actions, "remaining_today": max(0, config["daily_limit"] - state["counts"].get(today, 0)),
        "last_notification_at": _number(state.get("last_notification_at")),
        "snooze_until": _number(state.get("snooze_at")), "skip_today": state.get("skip_date") == today,
        "notification": notification}
    return result, state


def preview(engine, context, patch=None):
    """Read-only future deadline and current suppression explanation."""
    with engine.store.lock:
        config = _config(engine)
        if patch is not None:
            config = _validated(config, patch)
        result, _ = _evaluate(engine, config, context, _state(engine, config), emit=False)
        result["notification"] = None
        return result


def claim(engine, context):
    """Consume exactly once before the worker is allowed to emit a toast."""
    with engine.store.transaction():
        config = _config(engine)
        result, state = _evaluate(engine, config, context, _state(engine, config))
        engine.store.set(STATE_KEY, state)
        return result


def configure(engine, patch, context):
    """Save validated preferences, or one explicit snooze/skip action.

    Actions: {action:'snooze', minutes:30}, {action:'skip_today'}, or
    {action:'clear_snooze'}. Snooze replaces any prior snooze and bypasses only
    unsolicited cooldown; daily budget and every suppression rule still apply.
    """
    with engine.store.transaction():
        config = _config(engine)
        now, zone, zone_name = _clock(engine, context)
        state = _state(engine, config)
        if isinstance(patch, dict) and "action" in patch:
            action = patch["action"]
            if action == "snooze" and set(patch) == {"action", "minutes"}:
                minutes = patch["minutes"]
                if type(minutes) is not int or not 5 <= minutes <= 1440:
                    raise UserError("Choose a snooze between five minutes and one day.")
                state["snooze_at"] = now + minutes * 60
            elif action == "skip_today" and set(patch) == {"action"}:
                state["skip_date"] = datetime.fromtimestamp(now, zone).date().isoformat()
                state["snooze_at"] = 0
            elif action == "clear_snooze" and set(patch) == {"action"}:
                state["snooze_at"] = 0
            else:
                raise UserError("Choose a supported reminder action.")
        else:
            config = _validated(config, patch)
            engine.store.set(CONFIG_KEY, config)
        # Saving a schedule begins observing now; it never replays today's past
        # times or immediately invites the existing pile of due reviews.
        baseline = {**context, "event": "startup"}
        result, state = _evaluate(engine, config, baseline, state)
        engine.store.set(STATE_KEY, state)
        return result
