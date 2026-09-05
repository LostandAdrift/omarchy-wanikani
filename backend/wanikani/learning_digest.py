"""Aggregate-only local history for a cached shell status section.

This projection has no cache, timer, transport, content lookup or write path.
The snapshot producer owns its lifetime and marks a retained result stale.
"""
from datetime import datetime, time, timedelta
import math
import sqlite3
from uuid import UUID

from . import insights
from .api import ApiError, user_id, validate_user
from .common import UserError, stamp


MAX_COUNT = 9007199254740991
COUNTERS = {
    "subject_completions": ("reviews", "lessons", "practice"),
    "sessions_completed": ("reviews", "lessons", "practice"),
    "listening_ratings": ("remembered", "again", "skipped"),
    "dictation_ratings": ("matched", "again", "skipped"),
}
SCALARS = ("listening_sessions_completed", "dictation_sessions_completed", "typo_corrections")


def _unavailable():
    return UserError("Local learning totals are unavailable. They have not been replaced with zero.",
        "learning_digest_unavailable")


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise _unavailable()
    return value


def _context(engine):
    user = validate_user(engine.store.get("user"))
    identity = user_id(user)
    account = engine.store.get("account_id")
    if engine.demo:
        if identity != "demo" or (account is not None and (type(account) is not str or account != "demo")):
            raise _unavailable()
        account = "demo"
    elif type(account) is not type(identity) or account != identity:
        raise _unavailable()
    epoch = engine.store.get("session_epoch")
    # Never expose arbitrary meta text through this otherwise aggregate API.
    if not isinstance(epoch, str) or len(epoch) != 36 or str(UUID(epoch)) != epoch:
        raise _unavailable()
    offset = engine.clock_offset
    if (engine.clock_untrusted or type(offset) not in (int, float)
            or not math.isfinite(offset) or abs(offset) > 300):
        raise _unavailable()
    return str(account), epoch


def _window(boundaries, daily):
    total = {metric: dict.fromkeys(keys, 0) for metric, keys in COUNTERS.items()}
    total.update(dict.fromkeys(SCALARS, 0))
    for day, _, _ in boundaries:
        values = daily[day]
        for metric, keys in COUNTERS.items():
            source = values.get(metric)
            if not isinstance(source, dict):
                raise _unavailable()
            for key in keys:
                total[metric][key] = _count(total[metric][key] + _count(source.get(key)))
        for metric in SCALARS:
            total[metric] = _count(total[metric] + _count(values.get(metric)))
    return {"days": len(boundaries), "start_day": boundaries[0][0], "end_day": boundaries[-1][0], **total}


def project(engine, *, timezone=None, now=None):
    """Compute both 7/30 local-day windows at one exact, trusted instant.

    timezone/now are test seams; runtime callers use the system zone/clock.
    Known empty local records produce zero. Unavailable context/calculation
    raises UserError so the caller can retain an explicitly stale cache or
    expose an unavailable section without breaking ordinary status.
    """
    try:
        with engine.store.lock:
            account, epoch = _context(engine)
            now, zone, name = insights._clock(engine, now, timezone)
            today = datetime.fromtimestamp(now, zone).date()
            boundaries = []
            daily = {}
            for ago in range(29, -1, -1):
                day = today - timedelta(days=ago)
                label = day.isoformat()
                beginning = datetime.combine(day, time(), zone).timestamp()
                end = datetime.combine(day + timedelta(days=1), time(), zone).timestamp()
                boundaries.append((label, beginning, end))
                daily[label] = insights._empty()
            insights._completion_data(engine, boundaries, now, daily)
            insights._session_data(engine, boundaries, now, daily)
            insights._listening_data(engine, boundaries, now, daily, account)
            insights._listening_data(engine, boundaries, now, daily, account, skill="dictation")
            return {"schema_version": 1, "scope": "recorded_on_this_device", "freshness": "cached",
                "generated_at": stamp(now), "data_epoch": epoch, "demo": bool(engine.demo),
                "timezone": name, "complete": True, "stale": False, "coverage": "retained_local_records",
                "includes_retained_pre_reset_activity": True,
                "windows": {str(days): _window(boundaries[-days:], daily) for days in (7, 30)}}
    except (ApiError, UserError, sqlite3.DatabaseError, ValueError, TypeError, OverflowError, OSError):
        # Never carry SQL text, arbitrary cached values or account error text
        # into a diagnostic/status response. Unknown totals are not zero.
        raise _unavailable() from None
