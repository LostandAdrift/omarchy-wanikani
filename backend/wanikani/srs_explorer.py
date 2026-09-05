"""Bounded, read-only drill-down into the same confirmed SRS as Progress.

The metadata pass intentionally uses progress._status before filtering or
pagination. A raw srs_stage SQL predicate would disagree about burned dates,
not-yet-started assignments and invalid cached timelines. Only one selected
page is hydrated; no mnemonic, note or audio bodies are read for catalogue
cards. guarded_details is the deliberate, separately authorized detail read.
"""
from collections import Counter

from .api import ApiError, user_id, validate_user
from .common import UserError, epoch
from . import progress


MAX_CATALOGUE = 12000
MAX_PAGE = 60
MAX_ID = 9007199254740991
GROUPS = tuple(key for key, _ in progress.GROUPS)
ORDERS = ("level", "next_review")


def _account(engine):
    """Cached account access is useful offline, but never across identities."""
    resource = engine.store.get("user")
    try:
        validate_user(resource)
        identity = user_id(resource)
    except ApiError:
        raise UserError("Connect or refresh your account before exploring SRS progress.", "account_mismatch") from None
    if not engine.demo:
        stored = engine.store.get("account_id")
        if type(stored) is not type(identity) or stored != identity:
            raise UserError("Refresh the current account before exploring SRS progress.", "account_mismatch")
    return engine.max_level()


def _arguments(group, subject_type, level, stage, order, offset, limit):
    if not isinstance(group, str) or group not in GROUPS:
        raise UserError("Choose a known SRS group.", "invalid_request")
    if subject_type is not None and (not isinstance(subject_type, str) or subject_type not in progress.TYPES):
        raise UserError("Choose radicals, kanji, vocabulary, or kana vocabulary.", "invalid_request")
    if level is not None and (type(level) is not int or not 1 <= level <= 60):
        raise UserError("Choose a WaniKani level from 1 to 60.", "invalid_request")
    if stage is not None and (type(stage) is not int or stage not in progress.STAGES or progress.STAGES[stage][0] != group):
        raise UserError("Choose a stage within the selected SRS group.", "invalid_request")
    if not isinstance(order, str) or order not in ORDERS:
        raise UserError("Order subjects by level or their cached next review.", "invalid_request")
    if type(offset) is not int or not 0 <= offset <= MAX_CATALOGUE or type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise UserError("Choose a page of 1 to 60 subjects.", "invalid_request")


def _identity(row):
    return row["valid_identity"] and type(row["id"]) is int and 1 <= row["id"] <= MAX_ID


def catalogue(engine, group="apprentice", subject_type=None, level=None,
              stage=None, order="level", offset=0, limit=24):
    """Return confirmed-stage facets and a safe page across accessible levels.

    `levels` applies group/type/stage before the exact-level filter. `stages`
    applies group/type/level before the exact-stage filter. Counts include
    protected cards; their answers and automatic open controls remain hidden.
    Pending local reviews retain the server's cached stage and review date.
    """
    _arguments(group, subject_type, level, stage, order, offset, limit)
    with engine.store.lock:
        maximum = _account(engine)
        if level is not None and level > maximum:
            raise UserError("This level is outside your current account access.", "access_restricted")
        now = engine.now()
        metadata = progress._rows(engine, limit=MAX_CATALOGUE + 1)
        bounded = len(metadata) <= MAX_CATALOGUE
        # Ambiguous numeric identities can occur only in a damaged cache. Do
        # not show two cards/links for the same subject, even across types.
        # Include the sentinel: a duplicate can straddle the catalogue limit.
        occurrences = Counter(row["id"] for row in metadata if _identity(row))
        metadata = metadata[:MAX_CATALOGUE]
        identities_complete = all(_identity(row) and occurrences[row["id"]] == 1 for row in metadata)
        states = []
        assignments_complete = True
        for row in metadata:
            if not _identity(row) or occurrences[row["id"]] != 1:
                continue
            state = progress._status(row, now)
            assignments_complete &= progress._valid(row) and state["group"] != "unknown"
            # Canonical dates can establish Burned even when the stored stage
            # disagrees. Keep both facts, but do not claim complete exact-stage
            # facets or invent stage 9 to make their counts add up.
            if state["stage"] not in (None, 0):
                assignments_complete &= progress.STAGES.get(state["stage"], (None,))[0] == state["group"]
            if state["group"] == group and (subject_type is None or row["type"] == subject_type):
                states.append((row, state))
        levels = Counter(row["level"] for row, status in states if stage is None or status["stage"] == stage)
        stages = Counter(status["stage"] for row, status in states if level is None or row["level"] == level)
        selected = [(row, status) for row, status in states
            if (level is None or row["level"] == level) and (stage is None or status["stage"] == stage)]
        def key(value):
            row, state = value
            stable = (row["level"], row["id"], row["type"])
            if order == "level":
                return stable
            next_at = epoch(state["next_review_at"])
            # No date is manufactured for burned, locked or unknown progress.
            return (next_at is None, next_at or 0, *stable)
        selected.sort(key=key)
        total = len(selected)
        requested = selected[offset:offset + limit]
        ids = [row["id"] for row, _ in requested]
        hydrated = {}
        if ids:
            page_rows = progress._rows(engine, " AND CAST(s.id AS INTEGER) IN (" + ",".join("?" for _ in ids) + ")", ids,
                limit=len(ids) + 1, content=True)
            page_counts = Counter(row["id"] for row in page_rows)
            expected = {row["id"]: (row["type"], row["level"]) for row, _ in requested}
            for row in page_rows:
                if (_identity(row) and page_counts[row["id"]] == 1
                        and expected.get(row["id"]) == (row["type"], row["level"])):
                    hydrated[row["id"]] = row
        pending = progress._pending(engine, ids)
        protected, aliases = progress._protected(engine)
        items = [progress._card(hydrated[row["id"]], now, pending, protected, aliases)
            for row, _ in requested if row["id"] in hydrated]
        total_complete = bool(bounded and identities_complete)
        complete = bool(total_complete and assignments_complete and progress._markers(engine, maximum)
            and len(items) == len(requested))
        return {"group": group, "subject_type": subject_type, "level": level, "stage": stage, "order": order,
            "offset": offset, "limit": limit, "total": total, "total_complete": total_complete,
            "complete": complete, "protection_complete": protected is not None, "items": items,
            "has_more": offset + limit < total, "next_offset": offset + limit if offset + limit < total else None,
            "levels": [{"level": number, "count": count} for number, count in sorted(levels.items())],
            "stages": [{"stage": number, "label": label, "count": stages.get(number, 0)}
                for number, (key, label) in progress.STAGES.items() if key == group],
            "last_sync": progress._date(engine.store.get("last_sync"), now, past=True),
            "source": "cached_wanikani", "scope": "Accessible cached subjects; confirmed current assignments"}


def guarded_details(engine, subject_id):
    """Reauthorize automatic progress links independently of manual Lookup.

    The same lock covers identity, current assignment/access, every unfinished
    graded session and glyph alias, then detail projection. A safe earlier list
    response is not authorization to reveal a newly protected subject.
    """
    if type(subject_id) is not int or not 1 <= subject_id <= MAX_ID:
        raise UserError("Choose a valid subject.", "invalid_request")
    with engine.store.lock:
        _account(engine)
        rows = progress._rows(engine, " AND CAST(s.id AS INTEGER)=?", (subject_id,), limit=2, content=True)
        if len(rows) != 1 or not _identity(rows[0]) or not progress._valid(rows[0]):
            raise UserError("This subject's current account access or assignment needs a refresh.", "access_restricted")
        protected, aliases = progress._protected(engine)
        if protected is None or subject_id in protected or bool(rows[0]["characters"] and rows[0]["characters"] in aliases):
            raise UserError("This answer is kept for your saved graded study. Resume that session to reveal it.", "protected_study")
        result = engine.details(subject_id)
        # Ordinary manual Lookup's helpers use truthy `done` flags. Preserve
        # the Explorer's stricter protection for every automatic relationship
        # and comparison too, including malformed non-boolean completion flags.
        for key in ("components", "related", "visually_similar"):
            result[key] = [item for item in result[key]
                if type(item.get("id")) is int and item["id"] not in protected
                and item.get("characters") not in aliases]
        return result
