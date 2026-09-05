"""A bounded, read-only timeline of cached WaniKani level progression records.

``catalogue(engine, offset=0, limit=20)`` inspects at most 1,000 records through
the existing kind/numeric-ID index, then orders valid dates within that window.
``cache_complete`` describes the local collection, never lifetime completeness:
WaniKani explicitly says that older accounts can lack historical records.

Each record remains a separate visit. Passing is the 90% kanji milestone;
``completed_at`` means every assignment at that level was burned. Durations
measure calendar time, including vacations and pauses, never hours studied.
https://docs.api.wanikani.com/20170710/#level-progressions
"""
from datetime import datetime, timezone
import math
import re

from .api import ApiError, user_id, validate_user
from .common import UserError, stamp


MAX_RECORDS = 1000
MAX_PAGE = 50
MAX_ID = 9007199254740991
DATES = ("created_at", "unlocked_at", "started_at", "passed_at", "completed_at", "abandoned_at")
STEPS = ("unlocked_at", "started_at", "passed_at", "completed_at")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})")
NOTICE = "WaniKani may not supply your full history. Calendar time includes vacations and pauses."


def _date(value, now):
    if not isinstance(value, str) or len(value) > 40 or TIMESTAMP.fullmatch(value) is None:
        return None
    # fromisoformat normalizes oversized offset minutes (e.g. +01:99), but
    # those are not valid RFC3339 timestamps from the API.
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        seconds = parsed.timestamp()
        if not math.isfinite(seconds) or seconds > now:
            return None
        return seconds
    except (ValueError, OverflowError, OSError):
        return None


def _account(engine):
    resource = engine.store.get("user")
    try:
        validate_user(resource)
        identity = user_id(resource)
    except ApiError:
        return None
    stored_identity = engine.store.get("account_id")
    if type(identity) is not type(stored_identity) or identity != stored_identity:
        return None
    return resource["data"]["level"]


def _projection():
    fields = ["id AS resource_id", """CASE WHEN json_type(body,'$.data')='object'
      AND json_type(body,'$.id')='integer' AND json_extract(body,'$.id')=CAST(id AS INTEGER)
      AND json_extract(body,'$.object')='level_progression'
      THEN json_extract(body,'$.id') END AS id""",
        "CASE WHEN json_type(body,'$.data.level')='integer' THEN json_extract(body,'$.data.level') END AS level"]
    for name in DATES:
        # Pull only bounded scalar metadata, even if a damaged cached resource
        # contains a huge string or private fields beside the expected dates.
        fields.extend(("json_type(body,'$.data." + name + "') AS " + name + "_type",
            "CASE WHEN json_type(body,'$.data." + name + "')='text' THEN substr(json_extract(body,'$.data."
            + name + "'),1,41) END AS " + name))
    return "SELECT " + ",".join(fields) + """ FROM resources INDEXED BY resource_numeric_id
      WHERE kind='level_progression' ORDER BY CAST(id AS INTEGER) DESC LIMIT ?"""


PROJECTION = _projection()


def _record(row, now, clock_trusted):
    identity, level = row["id"], row["level"]
    if (type(identity) is not int or not 1 <= identity <= MAX_ID or str(identity) != row["resource_id"]
            or type(level) is not int or not 1 <= level <= 60):
        return None
    dates, partial = {}, not clock_trusted
    for name in DATES:
        kind = row[name + "_type"]
        value = _date(row[name], now) if kind == "text" else None
        dates[name] = value
        if (name == "created_at" and value is None) or (kind not in ("text", "null")) or (kind == "text" and value is None):
            partial = True
    # The API promises this chain. A later milestone without its prerequisite
    # does not establish a valid duration, even if its timestamp parses.
    for before, after in zip(STEPS, STEPS[1:]):
        if dates[after] is not None and (dates[before] is None or dates[before] > dates[after]):
            partial = True
    abandoned = dates["abandoned_at"]
    if abandoned is not None and any(dates[name] is not None and dates[name] > abandoned for name in STEPS):
        partial = True
    state, label = "unknown", "Recorded status unknown"
    if not partial:
        if abandoned is not None:
            state = "abandoned"
            label = "All assignments burned, later abandoned" if dates["completed_at"] is not None else (
                "Passed, later abandoned" if dates["passed_at"] is not None else "Abandoned visit")
        elif dates["completed_at"] is not None:
            state, label = "all_burned", "All assignments burned"
        elif dates["passed_at"] is not None:
            state, label = "passed", "Level passed"
    item = {"id": identity, "level": level, "attempt_label": "Recorded visit", "state": state, "label": label,
        **{name: stamp(value) if value is not None else None for name, value in dates.items()},
        "date_status": "partial" if partial else "known",
        "date_notice": "Recorded dates need a refresh; elapsed time is unknown." if partial else "",
        "elapsed_seconds": None, "elapsed_days": None, "elapsed_to": None}
    if not partial and dates["unlocked_at"] is not None:
        endpoint = "passed" if dates["passed_at"] is not None else "abandoned" if abandoned is not None else None
        if endpoint:
            _duration(item, dates[endpoint + "_at"] - dates["unlocked_at"], endpoint)
    # Invalid dates sort last; created_at is an honest fallback for an attempt
    # with no recorded unlock. Neither API resource IDs nor dates are invented.
    chronology = dates["unlocked_at"] if dates["unlocked_at"] is not None else dates["created_at"]
    return item, chronology


def _duration(item, seconds, endpoint):
    item.update(elapsed_seconds=int(seconds), elapsed_days=int(seconds // 86400), elapsed_to=endpoint)


def catalogue(engine, offset=0, limit=20):
    """Return bounded account metadata; never inspect subjects or local answers.

    ``total`` and numbered recorded visits describe only the inspected window.
    ``partial`` flags incomplete/ambiguous cached data; ``history_complete`` is
    always false independently. Unknown and omitted records never get an open
    duration. Only a verified latest current-level visit can run through now.
    """
    if type(offset) is not int or not 0 <= offset <= MAX_RECORDS or type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise UserError("Choose a valid page of cached level history.")
    with engine.store.lock:
        now = engine.now()
        valid_clock = type(now) in (int, float) and math.isfinite(now) and 0 <= now <= 253402300799
        result = {"status": "unavailable", "source": "Authored demo level progressions" if engine.demo else "WaniKani level progressions",
            "items": [], "total": None, "offset": offset, "limit": limit, "has_more": False, "next_offset": None,
            "cache_complete": False, "history_complete": False, "truncated": False, "partial": True,
            "inspected": 0, "omitted_invalid": 0, "checked_at": stamp(now) if valid_clock else None,
            "reason": "account_unavailable", "message": "Cached account identity could not be verified. " + NOTICE}
        level = _account(engine)
        if level is None:
            return result
        if not valid_clock:
            return {**result, "reason": "clock_unavailable", "message": "The clock could not be checked. " + NOTICE}
        trusted = not engine.clock_untrusted
        cache_complete = bool(trusted and not engine.syncing and _date(engine.store.get("cursor_level_progressions"), now) is not None)
        rows = engine.store.rows(PROJECTION, (MAX_RECORDS + 1,))
        truncated = len(rows) > MAX_RECORDS
        rows = rows[:MAX_RECORDS]
        records = [_record(row, now, trusted) for row in rows]
        omitted = sum(record is None for record in records)
        records = [record for record in records if record is not None]
        records.sort(key=lambda record: (record[1] is not None, record[1] or 0, record[0]["id"]), reverse=True)
        current = [record for record in records if record[0]["level"] == level]
        # A later completed/abandoned visit must prevent an older unfinished
        # one from growing forever. Ambiguous current-level dates do the same.
        latest = current[0][0] if current else None
        current_known = all(record[0]["date_status"] == "known" for record in current)
        if (latest is not None and latest["state"] == "unknown" and current_known
                and cache_complete and not truncated and not omitted):
            if latest["unlocked_at"] is None:
                latest.update(state="not_unlocked", label="Not unlocked")
            else:
                latest.update(state="in_progress" if latest["started_at"] else "unlocked",
                    label="In progress" if latest["started_at"] else "Lessons available")
                _duration(latest, now - _date(latest["unlocked_at"], now), "now")
        visits = {}
        for item, _ in reversed(records):
            visits[item["level"]] = visits.get(item["level"], 0) + 1
            item["attempt_label"] = "Recorded visit " + str(visits[item["level"]])
            if item["state"] == "unknown" and item["date_status"] == "known":
                item["date_notice"] = "This unfinished record does not establish a current visit; elapsed time is unknown."
        total = len(records)
        more = offset + limit < total
        partial = not cache_complete or truncated or omitted > 0 or any(
            item["date_status"] != "known" or item["state"] == "unknown" for item, _ in records)
        message = (f"Limited to the {MAX_RECORDS:,} newest cached resource IDs; dates are ordered within this window. " if truncated else "")
        if not cache_complete:
            message += "Collection synchronization or its clock check is incomplete. "
        if omitted:
            message += "Some malformed cached records were omitted. "
        return {**result, "status": "available" if total else "empty", "items": [record[0] for record in records[offset:offset + limit]],
            "total": total, "has_more": more, "next_offset": offset + limit if more else None,
            "cache_complete": cache_complete, "truncated": truncated, "partial": bool(partial),
            "inspected": len(rows), "omitted_invalid": omitted, "reason": "partial_cache" if partial else "ready",
            "message": message + NOTICE}
