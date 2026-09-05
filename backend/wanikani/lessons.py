"""Read-only lesson catalogue/preview and checked explicit batch selection.

catalogue(engine, subject_type='all', offset=0, limit=30) returns items, counts
for all four subject types, total/has_more/next_offset, complete, and a small
saved_session summary. Only the requested page hydrates full subject content.

preview(engine, subject_ids=None, limit=5) returns an ordered batch and counts.
An unfinished lesson session instead returns resume_required=True without
revealing its unanswered content or replacing it. New selections contain 1–20
unique subject IDs; validate_selection returns their assignment/subject pairs
for Engine.start's existing durable transaction. No API/outbox writes occur.

WaniKani's confirmed unlocked_at is authoritative. Prerequisite cards explain
cached history; a later demotion never relocks an already unlocked lesson.
"""
import json

from .common import UserError, epoch, stamp
from .trail import _protected


TYPES = ("radical", "kanji", "vocabulary", "kana_vocabulary")
SUBJECTS = "('radical','kanji','vocabulary','kana_vocabulary')"
BUSY = "('pending','inflight','uncertain','blocked','conflicted')"
MAX_CATALOGUE = 12000
MAX_PREVIEW_SCAN = 256


def _integer(value, label, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise UserError(f"{label} must be a whole number from {lower} to {upper}.")
    return value


def _saved(engine):
    session = engine.saved_session("lessons")
    if not session:
        return None
    total = min(len(session["queue"]), session.get("finish_at", len(session["queue"])))
    position = session["lesson_index"] if session["phase"] == "lesson" else session["index"]
    return {"id": session["id"], "mode": "lessons", "phase": session["phase"],
        "completed": session["completed"], "total": total, "position": min(position + 1, total),
        "revision": session.get("revision", 0)}


def _protection(engine):
    ids = _protected(engine)
    if ids is None:
        raise UserError("Paused study could not be checked. Resume it before choosing new lessons.", "protected_session")
    characters = set()
    ordered = sorted(ids)
    for offset in range(0, len(ordered), 128):
        chunk = ordered[offset:offset + 128]
        placeholders = ",".join("?" for _ in chunk)
        characters.update(row[0] for row in engine.store.rows(f"""SELECT json_extract(body,'$.data.characters')
          FROM resources WHERE kind IN {SUBJECTS} AND id IN ({placeholders})
            AND json_type(body,'$.data.characters')='text' AND length(json_extract(body,'$.data.characters'))>0""",
            [str(sid) for sid in chunk]))
    return ids, characters


def _protected_subject(subject, protection):
    ids, characters = protection
    value = subject["data"].get("characters")
    return subject["id"] in ids or (isinstance(value, str) and value in characters)


def _available(engine, protection):
    now = engine.now()
    rows = engine.store.rows(f"""SELECT CAST(s.id AS INTEGER) AS id,s.kind AS type,
        json_extract(s.body,'$.data.characters') AS characters,
        json_extract(s.body,'$.data.level') AS level,
        json_extract(a.body,'$.data.unlocked_at') AS unlocked_at,
        CASE WHEN json_type(s.body,'$.data.lesson_position')='integer'
          THEN json_extract(s.body,'$.data.lesson_position') ELSE 0 END AS position
      FROM resources a INDEXED BY resource_assignment_schedule
      JOIN resources s INDEXED BY resource_search_identity ON s.kind IN {SUBJECTS}
        AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
      WHERE a.kind='assignment' AND json_type(s.body,'$.data.level')='integer'
        AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
        AND json_extract(s.body,'$.data.hidden_at') IS NULL
        AND json_type(s.body,'$.id')='integer' AND json_extract(s.body,'$.id')=CAST(s.id AS INTEGER)
        AND CAST(s.id AS INTEGER)>0 AND json_extract(s.body,'$.object')=s.kind
        AND json_type(a.body,'$.data.subject_id')='integer'
        AND json_type(a.body,'$.id')='integer' AND json_extract(a.body,'$.id')=CAST(a.id AS INTEGER)
        AND CAST(a.id AS INTEGER)>0 AND json_extract(a.body,'$.object')='assignment'
        AND json_extract(a.body,'$.data.started_at') IS NULL
        AND json_type(a.body,'$.data.srs_stage')='integer' AND json_extract(a.body,'$.data.srs_stage')=0
        AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
        AND julianday(json_extract(a.body,'$.data.unlocked_at'))<=julianday(?)
        AND (SELECT COUNT(*) FROM resources duplicate WHERE duplicate.kind='assignment'
          AND CAST(json_extract(duplicate.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER))=1
        AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER)
          AND o.kind IN ('review','lesson') AND o.state IN {BUSY})
      ORDER BY level,position,CAST(s.id AS INTEGER) LIMIT ?""", (engine.max_level(), stamp(now), MAX_CATALOGUE + 1))
    complete = len(rows) <= MAX_CATALOGUE
    ids, characters = protection
    output, seen = [], set()
    for row in rows[:MAX_CATALOGUE]:
        unlocked = epoch(row["unlocked_at"])
        if row["id"] in seen or row["id"] in ids or row["characters"] in characters or unlocked is None or unlocked > now:
            continue
        seen.add(row["id"])
        output.append(row)
    return output, complete


def _prerequisites(engine, subject, protection):
    ids = subject["data"].get("component_subject_ids", [])
    if not isinstance(ids, list):
        return [], False
    output, seen = [], set()
    complete = len(ids) <= 60
    for sid in ids[:60]:
        if type(sid) is not int or sid <= 0 or sid in seen:
            complete = False
            continue
        seen.add(sid)
        item = engine.store.subject(sid)
        try:
            engine.ensure_access(item)
        except UserError:
            complete = False
            continue
        assignment = engine.store.related("assignment", sid)
        data = (assignment or {}).get("data", {})
        if data.get("hidden"):
            complete = False
            continue
        protected = _protected_subject(item, protection)
        passed = epoch(data.get("passed_at")) is not None
        stage = data.get("srs_stage")
        unlocked = epoch(data.get("unlocked_at"))
        state = "Paused graded work" if protected else "Passed" if passed else (
            "Guru or above" if type(stage) is int and stage >= 5 else "Learned" if epoch(data.get("started_at")) is not None
            else "Lesson available" if unlocked is not None and unlocked <= engine.now() else "Not yet unlocked")
        characters = item["data"].get("characters")
        output.append({"id": sid, "type": item["object"], "characters": characters if isinstance(characters, str) else "",
            "state": state, "can_open": not protected})
    return output, complete


def _card(engine, subject_id, protection):
    subject = engine.store.subject(subject_id)
    engine.ensure_access(subject)
    detail = engine.details(subject_id, False)
    ready, note = True, "Ready offline"
    try:
        engine.ensure_study_content(subject)
    except UserError as error:
        if error.code != "content_unavailable":
            raise
        ready, note = False, str(error)
    prerequisites, complete = _prerequisites(engine, subject, protection)
    return {"id": subject_id, "type": detail["type"], "characters": detail["characters"], "level": detail["level"],
        "meanings": detail["meanings"], "images": detail["images"], "ready": ready, "cache_note": note,
        "prerequisites": prerequisites, "prerequisites_complete": complete, "unlock_status": "Unlocked by WaniKani"}


def catalogue(engine, subject_type="all", offset=0, limit=30):
    if subject_type not in ("all", *TYPES):
        raise UserError("Choose radicals, kanji, vocabulary, or kana vocabulary.")
    _integer(offset, "Page offset", 0, 100000)
    _integer(limit, "Page size", 1, 60)
    with engine.store.lock:
        protection = _protection(engine)
        rows, complete = _available(engine, protection)
        counts = {kind: sum(row["type"] == kind for row in rows) for kind in TYPES}
        selected = [row for row in rows if subject_type == "all" or row["type"] == subject_type]
        page = selected[offset:offset + limit]
        total = len(selected)
        return {"items": [_card(engine, row["id"], protection) for row in page], "counts": counts,
            "subject_type": subject_type, "offset": offset, "limit": limit, "total": total,
            "has_more": offset + limit < total, "next_offset": offset + limit if offset + limit < total else None,
            "complete": complete, "message": "" if complete else "The cached lesson list is larger than this bounded check. Counts shown are partial.",
            "saved_session": _saved(engine)}


def validate_selection(engine, subject_ids):
    if not isinstance(subject_ids, list) or not 1 <= len(subject_ids) <= 20:
        raise UserError("Choose between one and twenty lessons.")
    if any(type(sid) is not int or sid <= 0 for sid in subject_ids) or len(set(subject_ids)) != len(subject_ids):
        raise UserError("Choose distinct valid lesson subjects.")
    with engine.store.lock:
        protection, now = _protection(engine), engine.now()
        selected = []
        for sid in subject_ids:
            subject = engine.store.subject(sid)
            engine.ensure_access(subject)
            if type(subject.get("id")) is not int or subject["id"] != sid or subject.get("object") not in TYPES:
                raise UserError("Refresh to verify the selected lesson subject.", "lesson_unavailable")
            if _protected_subject(subject, protection):
                raise UserError("A selected subject shares a prompt with paused graded work. Finish that saved work first.", "protected_session")
            rows = engine.store.rows("SELECT body FROM resources WHERE kind='assignment' AND json_extract(body,'$.data.subject_id')=?", (sid,))
            if len(rows) != 1:
                raise UserError("Refresh to verify the selected lesson assignment.", "lesson_unavailable")
            assignment = json.loads(rows[0][0])
            data = assignment["data"]
            unlocked = epoch(data.get("unlocked_at"))
            if (type(assignment.get("id")) is not int or assignment["id"] <= 0 or assignment.get("object") != "assignment"
                    or type(data.get("subject_id")) is not int or data["subject_id"] != sid
                    or data.get("hidden") or data.get("started_at") is not None or unlocked is None or unlocked > now
                    or type(data.get("srs_stage")) is not int or data["srs_stage"] != 0):
                raise UserError("A selected subject is no longer an available lesson. Refresh the lesson list.", "lesson_unavailable")
            if engine.store.rows(f"SELECT 1 FROM outbox WHERE subject_id=? AND kind IN ('review','lesson') AND state IN {BUSY} LIMIT 1", (sid,)):
                raise UserError("A selected lesson already has a graded result waiting for synchronization or recovery.", "lesson_pending")
            engine.ensure_study_content(subject)
            selected.append((assignment, subject))
        return selected


def preview(engine, subject_ids=None, limit=5):
    _integer(limit, "Batch size", 1, 20)
    with engine.store.lock:
        saved = _saved(engine)
        if saved:
            return {"batch": [], "counts": dict.fromkeys(TYPES, 0), "resume_required": True,
                "saved_session": saved, "complete": True, "message": "Resume your saved lessons before choosing another batch."}
        protection = _protection(engine)
        if subject_ids is not None:
            pairs = validate_selection(engine, subject_ids)
            batch = [_card(engine, subject["id"], protection) for _, subject in pairs]
            complete = True
        else:
            rows, complete = _available(engine, protection)
            batch = []
            for row in rows[:MAX_PREVIEW_SCAN]:
                card = _card(engine, row["id"], protection)
                if card["ready"]:
                    batch.append(card)
                if len(batch) >= limit:
                    break
            if len(batch) < limit and len(rows) > MAX_PREVIEW_SCAN:
                complete = False
        return {"batch": batch, "counts": {kind: sum(item["type"] == kind for item in batch) for kind in TYPES},
            "resume_required": False, "saved_session": None, "complete": complete,
            "message": "" if batch and complete else "Refresh to cache more lesson material."}
