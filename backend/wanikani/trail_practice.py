"""Read-only preview of explicitly selected Reading Trail words.

preview(engine, text, subject_ids) does not start/resume/replace practice and
is not an authorization token. A future trail-specific start must revalidate
inside the same Store transaction that creates the ungraded session. Generic
explicit practice currently has a different, deliberate-selection policy.
"""
from collections import Counter
from uuid import UUID

from . import insights, progress, trail
from .common import UserError
from .srs_explorer import _account


MAX_SELECTION = 20
MAX_ID = 9007199254740991
STATES = {"Learned", "Not started", "Paused graded work", "Waiting to sync", "Needs attention"}


def _selection(subject_ids):
    if (not isinstance(subject_ids, list) or not 1 <= len(subject_ids) <= MAX_SELECTION
            or any(type(sid) is not int or not 1 <= sid <= MAX_ID for sid in subject_ids)
            or len(set(subject_ids)) != len(subject_ids)):
        raise UserError("Choose 1 to 20 different words from this reading trail.", "invalid_request")


def _arguments(text, subject_ids):
    if not isinstance(text, str) or not 1 <= len(text) <= trail.MAX_TEXT or any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise UserError("Choose words from a passage of 1 to 256 valid characters.", "invalid_request")
    _selection(subject_ids)


def _context(engine):
    try:
        _account(engine)
    except UserError:
        raise UserError("Refresh the current account before preparing these words.", "account_mismatch") from None
    epoch = engine.store.get("session_epoch")
    try:
        if not isinstance(epoch, str) or len(epoch) != 36 or str(UUID(epoch)) != epoch:
            raise ValueError
    except ValueError:
        raise UserError("Reload this reading trail before preparing practice.", "trail_changed") from None
    return epoch


def _protection(engine):
    protected, aliases = insights._protection(engine)
    if protected is None:
        raise UserError("Saved graded study could not be checked. Your saved work is unchanged.", "protected_study")
    return protected, aliases


def _metadata(engine, subject_ids):
    rows = progress._rows(engine, " AND CAST(s.id AS INTEGER) IN (" + ",".join("?" for _ in subject_ids) + ")",
        subject_ids, limit=len(subject_ids) + 1)
    occurrences = Counter(row["id"] for row in rows)
    return {row["id"]: row for row in rows if occurrences[row["id"]] == 1 and progress._valid(row)}


def guard_ids(engine, subject_ids):
    """Recheck durable trail-practice subjects before a start/replay projection.

    Internal helper only: it cannot establish passage membership. A new start
    still needs preview with the original text in its creation transaction.
    Returns IDs only and never recreates or changes a session.
    """
    _selection(subject_ids)
    with engine.store.lock:
        _context(engine)
        protected, aliases = _protection(engine)
        metadata = _metadata(engine, subject_ids)
        for sid in subject_ids:
            if sid in protected:
                raise UserError("This word is kept for saved graded study.", "protected_study")
            row = metadata.get(sid)
            if not row or row["type"] not in ("kanji", "vocabulary", "kana_vocabulary"):
                raise UserError("A practice word's current access needs a refresh.", "access_restricted")
            subject = engine.store.subject(sid)
            characters = subject["data"].get("characters") if subject else None
            if (not subject or subject["id"] != sid or subject["object"] != row["type"]
                    or not isinstance(characters, str) or not characters.strip() or len(characters) > trail.MAX_TEXT):
                raise UserError("A practice word's cached content needs a refresh.", "content_unavailable")
            if characters in aliases:
                raise UserError("This word is kept for saved graded study.", "protected_study")
            try:
                engine.ensure_study_content(subject)
            except UserError:
                raise UserError("A practice word's cached content needs a refresh.", "content_unavailable") from None
        return list(subject_ids)


def _saved(engine):
    absent = {"present": False, "valid": True, "completed": 0, "total": 0, "revision": None}
    damaged = {"present": True, "valid": False, "completed": None, "total": None, "revision": None}
    reference = engine.store.get("practice_session")
    if reference is None:
        return absent
    if not isinstance(reference, str) or not 1 <= len(reference) <= 200:
        return damaged
    rows = engine.store.rows("""SELECT json_extract(body,'$.id') AS id,
      json_extract(body,'$.mode') AS mode,json_extract(body,'$.phase') AS phase,
      json_type(body,'$.queue') AS queue_type,json_array_length(body,'$.queue') AS size,
      json_extract(body,'$.completed') AS completed,json_type(body,'$.completed') AS completed_type,
      json_extract(body,'$.finish_at') AS finish_at,json_type(body,'$.finish_at') AS finish_type,
      json_extract(body,'$.revision') AS revision,json_type(body,'$.revision') AS revision_type
      FROM sessions WHERE id=? LIMIT 1""", (reference,))
    if not rows:
        return damaged
    row = rows[0]
    if row["id"] != reference or row["mode"] != "practice":
        return damaged
    if row["phase"] == "complete":
        return absent
    size = row["size"]
    if (row["phase"] not in ("question", "feedback") or row["queue_type"] != "array"
            or type(size) is not int or not 1 <= size <= MAX_SELECTION
            or row["completed_type"] != "integer" or row["revision_type"] != "integer"
            or not 0 <= row["revision"] <= MAX_ID):
        return damaged
    total = size
    if row["finish_type"] not in (None, "null"):
        if row["finish_type"] != "integer" or not 1 <= row["finish_at"] <= size:
            return damaged
        total = row["finish_at"]
    if not 0 <= row["completed"] < total:
        return damaged
    return {"present": True, "valid": True, "completed": row["completed"], "total": total, "revision": row["revision"]}


def preview(engine, text, subject_ids):
    """Return glyph/status/readiness only; preserve caller order and text.

    A missing current match raises rather than silently shrinking a selection.
    Protected or uncached content remains a neutral, disabled preview card.
    Completed pending graded work may be practised without changing its outbox.
    """
    _arguments(text, subject_ids)
    with engine.store.lock:
        epoch = _context(engine)
        protected, aliases = _protection(engine)
        report = trail.reading_trail(engine, text)
        matches = {item["id"]: item for item in report["matches"]}
        if any(sid not in matches for sid in subject_ids):
            raise UserError("Some selected words are no longer in this reading trail. Refresh the selection.", "trail_changed")
        metadata = _metadata(engine, subject_ids)
        items = []
        for sid in subject_ids:
            match = matches[sid]
            row = metadata.get(sid)
            if not row or row["type"] != match["type"] or row["level"] != match["level"]:
                raise UserError("A selected word's cached access needs a refresh.", "trail_changed")
            protected_word = sid in protected or match["characters"] in aliases or match["can_open"] is not True
            ready, reason = False, "protected_study" if protected_word else "content_unavailable"
            if not protected_word:
                subject = engine.store.subject(sid)
                if (subject and subject["id"] == sid and subject["object"] == match["type"]
                        and subject["data"].get("characters") == match["characters"]):
                    try:
                        # Trail matches have visible text, so this cannot take
                        # the radical-image/details branch or request audio.
                        engine.ensure_study_content(subject)
                        ready, reason = True, "ready"
                    except UserError:
                        pass
            items.append({"id": sid, "type": match["type"], "level": match["level"],
                "characters": match["characters"],
                "state": "Paused graded work" if protected_word else match["state"] if match["state"] in STATES else "Not started",
                "ready": ready, "reason": reason})
        saved = _saved(engine)
        ready_count = sum(item["ready"] for item in items)
        return {"text": text, "subject_ids": list(subject_ids), "data_epoch": epoch,
            "items": items, "total": len(items), "ready_count": ready_count,
            "can_start": ready_count == len(items) and saved["valid"],
            "trail_truncated": report["truncated"], "protection_complete": True,
            "saved_practice": saved, "requires_practice_choice": saved["present"],
            "scope": "ungraded_practice", "effect": "preview_only"}
