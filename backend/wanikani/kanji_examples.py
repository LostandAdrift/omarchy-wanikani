"""Bounded whole-word recordings related to a currently authorized kanji.

An example is vocabulary containing a kanji, never an isolated pronunciation
or a claim about which mora belongs to that kanji. Only the revealed active
parent occurrence may be exempted from automatic graded-spoiler protection.
"""
import json

from .common import UserError, accessible_subject, epoch, session_queue_limit
from .grading import KANA, reading, validate_subject_answers
from .media_plan import assets
from .trail import MAX_SESSIONS


MAX_RELATIONS = 128
MAX_EXAMPLES = 3
PENDING = "('pending','inflight','uncertain','blocked','conflicted')"
FORMATS = ("audio/mpeg", "audio/ogg", "audio/mp4", "audio/webm")


def _id(value):
    return type(value) is int and 0 < value <= 9007199254740991


def _text(value, limit):
    return value if isinstance(value, str) and 0 < len(value) <= limit and value.strip() and not any(
        ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value) else None


def sound(value):
    value = _text(value, 128)
    if value is None:
        return None
    normalized = reading(value)
    return normalized if KANA.fullmatch(normalized) else None


def _assignment(engine, sid):
    rows = engine.store.rows("""SELECT body FROM resources INDEXED BY resource_subject
      WHERE kind='assignment' AND json_extract(body,'$.data.subject_id')=? LIMIT 2""", (sid,))
    if len(rows) > 1:
        raise UserError("This subject's account state needs a refresh.", "access_restricted")
    if not rows:
        return None
    value = json.loads(rows[0][0])
    data = value.get("data")
    if (value.get("object") != "assignment" or not isinstance(data, dict)
            or type(data.get("subject_id")) is not int or data["subject_id"] != sid
            or (data.get("hidden") is not None and data.get("hidden") is not False)):
        raise UserError("This subject's account state needs a refresh.", "access_restricted")
    return data


def _subject(engine, sid, kind=None):
    subject = engine.store.subject(sid)
    if (not accessible_subject(subject, engine.max_level()) or not _id(subject.get("id"))
            or subject["id"] != sid or subject.get("object") not in ("radical", "kanji", "vocabulary", "kana_vocabulary")
            or (kind is not None and subject["object"] != kind)):
        raise UserError("This example is outside the current subject access.", "access_restricted")
    _assignment(engine, sid)
    return subject


def _parent(engine, sid, context, session_id=None, revision=None):
    if not _id(sid) or context not in ("study", "details"):
        raise UserError("Choose a kanji and its current reading context.")
    if context == "details" and (session_id is not None or revision is not None):
        raise UserError("A details example cannot claim a study-session exemption.")
    if context == "study" and (not isinstance(session_id, str) or not 1 <= len(session_id) <= 160
            or type(revision) is not int or revision < 0):
        raise UserError("Choose the current saved study position.")
    parent = _subject(engine, sid, "kanji")
    if engine.store.rows("SELECT 1 FROM outbox INDEXED BY outbox_state WHERE subject_id=? AND kind IN ('lesson','review') AND state IN " + PENDING + " LIMIT 1", (sid,)):
        raise UserError("This kanji has an unresolved study result. Inspect it before hearing examples.", "pending_study")
    validate_subject_answers(parent)
    if not _text(parent["data"].get("characters"), 16):
        raise UserError("The kanji text could not be read.", "content_unavailable")
    exemption = None
    if context == "study":
        session = engine.store.session()
        if (not session or session.get("id") != session_id or session.get("revision", 0) != revision
                or session.get("mode") not in ("reviews", "lessons", "practice")):
            raise UserError("The study question changed. Choose the current example again.", "stale_session")
        index = session.get("lesson_index") if session.get("phase") == "lesson" else session.get("index")
        queue = session.get("queue")
        if (not isinstance(queue, list) or not 1 <= len(queue) <= session_queue_limit(session) or type(index) is not int
                or not 0 <= index < len(queue) or not isinstance(queue[index], dict)
                or queue[index].get("subject_id") != sid):
            raise UserError("The study question changed. Choose the current example again.", "stale_session")
        feedback = session.get("feedback")
        allowed = (session.get("mode") == "lessons" and session.get("phase") == "lesson"
            and session.get("lesson_step") in ("reading", "context")) or (
            session.get("phase") == "feedback" and session.get("part") == "reading"
            and isinstance(feedback, dict) and feedback.get("retry") is False)
        if not allowed:
            raise UserError("Vocabulary examples are available when this kanji's reading is revealed.", "unrevealed")
        exemption = (session_id, index, sid)
    return parent, exemption


def _relations(parent):
    values = parent["data"].get("amalgamation_subject_ids")
    if values is None:
        return [], True
    if not isinstance(values, list):
        raise UserError("Related vocabulary needs a cache refresh.", "content_unavailable")
    complete = len(values) <= MAX_RELATIONS and all(_id(value) for value in values[:MAX_RELATIONS])
    return list(dict.fromkeys(value for value in values[:MAX_RELATIONS] if _id(value))), complete


def _protection(engine, exemption, parent_id):
    rows = engine.store.rows("""SELECT id,json_extract(body,'$.mode') AS mode,
        json_extract(body,'$.queue') AS queue,json_type(body,'$.queue') AS queue_type,
        json_type(body,'$.all_reviews') AS all_reviews
      FROM sessions INDEXED BY sessions_unfinished_graded WHERE json_extract(body,'$.phase')!='complete'
        AND json_extract(body,'$.mode')!='practice' LIMIT ?""", (MAX_SESSIONS + 1,))
    def unreadable():
        raise UserError("Saved graded study could not be checked. Resume or refresh it before hearing examples.", "protected_study")
    if len(rows) > MAX_SESSIONS:
        unreadable()
    ids = set()
    for row in rows:
        if row["mode"] not in ("reviews", "lessons") or row["queue_type"] != "array":
            unreadable()
        queue = json.loads(row["queue"])
        limit = session_queue_limit({"mode": row["mode"], "all_reviews": row["all_reviews"] == "true"})
        if not isinstance(queue, list) or not 1 <= len(queue) <= limit:
            unreadable()
        for index, entry in enumerate(queue):
            if not isinstance(entry, dict) or not _id(entry.get("subject_id")):
                unreadable()
            if entry.get("done") is not True and (row["id"], index, entry["subject_id"]) != exemption:
                ids.add(entry["subject_id"])
    if parent_id in ids:
        raise UserError("Another saved question still uses this kanji. Resume it before hearing examples.", "protected_study")
    characters, sounds = set(), set()
    for sid in ids:
        try:
            subject = _subject(engine, sid)
            data = subject["data"]
            validate_subject_answers(subject)
        except UserError:
            unreadable()
        glyphs = _text(data.get("characters"), 128)
        if glyphs:
            characters.add(glyphs)
        elif subject["object"] != "radical":
            unreadable()
        readings = data.get("readings", [])
        if not isinstance(readings, list) or len(readings) > 32:
            unreadable()
        for entry in readings:
            value = sound(entry.get("reading")) if isinstance(entry, dict) else None
            if not value:
                unreadable()
            sounds.add(value)
        if subject["object"] == "kana_vocabulary":
            value = sound(glyphs)
            if not value:
                unreadable()
            sounds.add(value)
        clips = data.get("pronunciation_audios", [])
        if not isinstance(clips, list) or len(clips) > 64:
            unreadable()
        for clip in clips:
            metadata = clip.get("metadata") if isinstance(clip, dict) else None
            value = sound(metadata.get("pronunciation")) if isinstance(metadata, dict) else None
            if not value:
                unreadable()
            sounds.add(value)
    return ids, characters, sounds


def _candidate(engine, parent, sid, protection):
    subject = _subject(engine, sid, "vocabulary")
    data = subject["data"]
    glyphs = _text(data.get("characters"), 128)
    components = data.get("component_subject_ids")
    if (not glyphs or parent["data"]["characters"] not in glyphs or not isinstance(components, list)
            or len(components) > 60 or parent["id"] not in [value for value in components if _id(value)]):
        raise UserError("This vocabulary is no longer a verified example of the kanji.", "unrelated_example")
    ids, characters, protected_sounds = protection
    if sid in ids or glyphs in characters:
        raise UserError("This vocabulary is part of saved graded study.", "protected_study")
    if engine.store.rows("SELECT 1 FROM outbox INDEXED BY outbox_state WHERE subject_id=? AND kind IN ('lesson','review') AND state IN " + PENDING + " LIMIT 1", (sid,)):
        raise UserError("This vocabulary has an unresolved study result.", "pending_study")
    answers = validate_subject_answers(subject)
    readings = data.get("readings", [])
    if not isinstance(readings, list) or len(readings) > 32:
        raise UserError("The vocabulary reading could not be checked.", "content_unavailable")
    word_sounds = {sound(item.get("reading")) for item in readings if isinstance(item, dict)}
    if None in word_sounds or not word_sounds or word_sounds.intersection(protected_sounds):
        raise UserError("This vocabulary's readings cannot be used beside saved study.", "protected_study")
    raw_clips = data.get("pronunciation_audios", [])
    if not isinstance(raw_clips, list) or len(raw_clips) > 64:
        raise UserError("The vocabulary recording could not be checked.", "content_unavailable")
    clips = []
    for clip in assets(raw_clips):
        metadata = clip.get("metadata")
        pronunciation = sound(metadata.get("pronunciation")) if isinstance(metadata, dict) else None
        if pronunciation in protected_sounds:
            raise UserError("This vocabulary's recording overlaps saved graded study.", "protected_study")
        if clip.get("content_type") in FORMATS and pronunciation and pronunciation in answers["readings"]:
            clips.append(clip)
    meanings = [value for value in answers["meanings"] if _text(value, 300)]
    if not clips or not meanings:
        raise UserError("No usable original whole-word recording is cached in the catalogue.", "no_recording")
    assignment = _assignment(engine, sid)
    started = epoch(assignment.get("started_at")) if assignment else None
    base = {"parent_subject_id": parent["id"], "characters": glyphs, "meaning": meanings[0]}
    return subject, clips, base, bool(started is not None and started <= engine.now())


def selection(engine, subject_id, parent_subject_id, origin_context, session_id=None, revision=None):
    parent, exemption = _parent(engine, parent_subject_id, origin_context, session_id, revision)
    relations, _ = _relations(parent)
    if not _id(subject_id) or subject_id not in relations:
        raise UserError("Choose one of this kanji's current vocabulary examples.", "unrelated_example")
    return _candidate(engine, parent, subject_id, _protection(engine, exemption, parent_subject_id))


def catalogue(engine, values):
    if not isinstance(values, dict):
        raise UserError("Choose a kanji example context.")
    context = values.get("context")
    expected = {"parent_subject_id", "context"} | ({"session_id", "revision"} if context == "study" else set())
    if set(values) != expected:
        raise UserError("Choose only a kanji and its current example context.")
    # Argument errors are explicit request failures. Access/protection errors
    # yield a bounded empty state without exposing candidate content.
    if (not _id(values.get("parent_subject_id")) or context not in ("study", "details")
            or (context == "study" and (not isinstance(values.get("session_id"), str)
                or not 1 <= len(values["session_id"]) <= 160 or type(values.get("revision")) is not int or values["revision"] < 0))):
        raise UserError("Choose a kanji and the current saved reading position.")
    result = {"parent_subject_id": values["parent_subject_id"], "status": "empty", "examples": [], "complete": True, "reason": "no_examples"}
    with engine.store.lock:
        try:
            parent, exemption = _parent(engine, values["parent_subject_id"], context, values.get("session_id"), values.get("revision"))
            relations, complete = _relations(parent)
            protection = _protection(engine, exemption, parent["id"])
        except UserError as error:
            return {**result, "status": "unavailable", "complete": False, "reason": error.code}
        from .pronunciation import _select
        candidates = []
        for sid in relations:
            try:
                chosen = _candidate(engine, parent, sid, protection)
            except UserError:
                continue
            clip, _ = _select(engine, sid, "kanji_example", values.get("session_id"), values.get("revision"), None,
                parent_subject_id=parent["id"], origin_context=context, prepared_example=chosen)
            if clip["status"] not in ("ready", "not_cached", "offline") or not clip.get("example"):
                continue
            subject, _, base, learned = chosen
            item = {"subject_id": sid, "characters": base["characters"], "meaning": base["meaning"],
                "pronunciation": clip["example"]["pronunciation"], "learned": learned, "cached": clip["status"] == "ready"}
            candidates.append((not item["cached"], not learned, subject["data"]["level"], sid, item))
        candidates.sort(key=lambda value: value[:4])
        examples = [value[4] for value in candidates[:MAX_EXAMPLES]]
        return {**result, "examples": examples, "complete": complete,
            "status": "available" if examples else "empty", "reason": "ready" if examples else "no_examples" if complete else "partial_catalogue"}
