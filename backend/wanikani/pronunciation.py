"""Permission-checked original vocabulary recordings and one-clip preparation.

``status(engine, subject_id, context='details', session_id=None, revision=None,
voice_actor_id=None)`` is read-only. Its response contains ``status`` (ready,
no_recording, not_cached, offline, budget, error), ``subject_id``, ``uri`` (only
when ready), ``voice_actor_id``, ``voice_fallback``, ``message`` and ``reason``.
Study requests require the active session ID and revision. Explicit details
retain deliberate lookup policy. Voice tests additionally require learned,
unprotected subjects and exclude known matching written/read pronunciation.

``sample(engine, voice_actor_id=None)`` selects a safe learned voice-test word.
``prepare(sync, **same_status_arguments)`` fetches only its selected clip. The
caller runs it off the foreground protocol thread and prevents account/store
replacement while it runs. Context and access are checked again after network
completion; callers must also discard stale presentation responses before play.
No playback, lesson/review submission, command journal or grading happens here.
"""
import json
import time

from . import media_plan
from .common import UserError, epoch
from .grading import reading
from .media_files import available_file
from .trail import _protected


MAX_SAMPLE_SUBJECTS = 512


def _result(subject_id, status, message, reason="", **values):
    return {"status": status, "subject_id": subject_id, "uri": None,
        "voice_actor_id": None, "voice_fallback": False,
        "message": message, "reason": reason, **values}


def _actor(item):
    metadata = item.get("metadata")
    actor = metadata.get("voice_actor_id") if isinstance(metadata, dict) else None
    return actor if type(actor) is int and 1 <= actor <= 10000 else None


def _readings(data):
    entries = data.get("readings")
    values = [item.get("reading") for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []
    # Kana-only vocabulary has no separate readings array. Its written kana
    # also identifies a known pronunciation that must not leak in a voice test.
    values.append(data.get("characters"))
    sounds = data.get("pronunciation_audios")
    for item in sounds if isinstance(sounds, list) else []:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        if isinstance(metadata, dict):
            values.append(metadata.get("pronunciation"))
    return {reading(value) for value in values if isinstance(value, str) and value.strip()}


def _protected_keys(engine):
    protected = _protected(engine)
    if protected is None:
        return None
    characters, readings = set(), set()
    ids = sorted(protected)
    for offset in range(0, len(ids), 128):
        chunk = ids[offset:offset + 128]
        placeholders = ",".join("?" for _ in chunk)
        for row in engine.store.rows(f"""SELECT json_object(
            'characters',json_extract(body,'$.data.characters'),
            'readings',json_extract(body,'$.data.readings'),
            'pronunciation_audios',json_extract(body,'$.data.pronunciation_audios'))
          FROM resources WHERE kind IN ('radical','kanji','vocabulary','kana_vocabulary')
            AND id IN ({placeholders})""", [str(sid) for sid in chunk]):
            data = json.loads(row[0])
            value = data.get("characters")
            if isinstance(value, str) and value:
                characters.add(value)
            readings.update(_readings(data))
    return protected, characters, readings


def _voice_safe(engine, subject, protection=None):
    assignment = engine.store.related("assignment", subject["id"])
    if not assignment or epoch(assignment["data"].get("started_at")) is None:
        return False
    protection = _protected_keys(engine) if protection is None else protection
    if protection is None:
        return False
    ids, characters, readings = protection
    return (subject["id"] not in ids and subject["data"].get("characters") not in characters
        and not _readings(subject["data"]).intersection(readings))


def _select(engine, subject_id, context, session_id, revision, voice_actor_id, protection=None):
    if type(subject_id) is not int or subject_id <= 0:
        raise UserError("Choose a valid vocabulary subject.")
    if context not in ("details", "study", "voice_test"):
        raise UserError("Choose a pronunciation context.")
    if voice_actor_id is not None and (type(voice_actor_id) is not int or not 1 <= voice_actor_id <= 10000):
        raise UserError("Choose a valid recording voice.")
    subject = engine.store.subject(subject_id)
    try:
        engine.ensure_access(subject)
    except UserError:
        return _result(subject_id, "error", "This recording is outside your current account access.", "access_restricted"), None
    assignment = engine.store.related("assignment", subject_id)
    if assignment and assignment["data"].get("hidden"):
        return _result(subject_id, "error", "This subject is hidden by WaniKani.", "access_restricted"), None
    if context == "study":
        session = engine.store.session()
        if (not session or session.get("id") != session_id or type(revision) is not int
                or session.get("revision", 0) != revision or session.get("phase") == "complete"):
            return _result(subject_id, "error", "The study question changed. Use the current playback control.", "stale_session"), None
        index = session.get("lesson_index") if session.get("phase") == "lesson" else session.get("index")
        queue = session.get("queue")
        if (session.get("mode") not in ("reviews", "lessons", "practice") or type(index) is not int
                or not isinstance(queue, list) or not 0 <= index < len(queue)
                or not isinstance(queue[index], dict) or queue[index].get("subject_id") != subject_id):
            return _result(subject_id, "error", "The study question changed. Use the current playback control.", "stale_session"), None
        allowed = (session.get("mode") == "lessons" and session.get("phase") == "lesson") or (
            session.get("phase") == "feedback" and isinstance(session.get("feedback"), dict)
            and not session["feedback"].get("retry") and (session.get("part") == "reading"
                or (subject["object"] == "kana_vocabulary" and session.get("part") == "meaning")))
        if not allowed:
            return _result(subject_id, "error", "Pronunciation is available after the reading answer is revealed.", "unrevealed"), None
    elif context == "voice_test" and not _voice_safe(engine, subject, protection):
        return _result(subject_id, "error", "Choose a learned sample outside paused graded work.", "protected_sample"), None
    if subject["object"] not in ("vocabulary", "kana_vocabulary"):
        return _result(subject_id, "no_recording", "WaniKani supplies pronunciation recordings for vocabulary."), None
    sounds = media_plan.assets(subject["data"].get("pronunciation_audios"))
    if not sounds:
        return _result(subject_id, "no_recording", "No original pronunciation recording is available for this word."), None
    preferred = voice_actor_id if voice_actor_id is not None else engine.settings()["voice_actor_id"]
    preferred_sounds = [item for item in sounds if _actor(item) == preferred]
    fallback = not preferred_sounds
    choices = preferred_sounds or sounds
    chosen = choices[0]
    chosen_cached = False
    for candidate in choices:
        cached = engine.store.rows("SELECT path FROM media WHERE url=?", (candidate["url"],))
        if cached and available_file(engine.store.path.parent / "media", cached[0][0]):
            chosen = candidate
            chosen_cached = True
            break
    if not chosen_cached and context != "voice_test":
        # Ordinary pronunciation remains useful offline even when the chosen
        # actor's version has not downloaded. Voice auditions stay exact.
        for candidate in sounds:
            cached = engine.store.rows("SELECT path FROM media WHERE url=?", (candidate["url"],))
            if cached and available_file(engine.store.path.parent / "media", cached[0][0]):
                chosen, fallback = candidate, _actor(candidate) != preferred
                break
    url = chosen["url"]
    rows = engine.store.rows("SELECT path FROM media WHERE url=?", (url,))
    path = available_file(engine.store.path.parent / "media", rows[0][0]) if rows else None
    values = {"voice_actor_id": _actor(chosen), "voice_fallback": fallback}
    if path:
        return _result(subject_id, "ready", "Ready to play.", uri=path.as_uri(), **values), chosen
    if engine.demo or not engine.connected or engine.status == "offline":
        return _result(subject_id, "offline", "This recording is not cached. Connect to download it.", **values), chosen
    return _result(subject_id, "not_cached", "Download this recording to play it and keep it available offline.", **values), chosen


def status(engine, subject_id, context="details", session_id=None, revision=None, voice_actor_id=None):
    with engine.store.lock:
        return _select(engine, subject_id, context, session_id, revision, voice_actor_id)[0]


def sample(engine, voice_actor_id=None):
    if voice_actor_id is not None and (type(voice_actor_id) is not int or not 1 <= voice_actor_id <= 10000):
        raise UserError("Choose a valid recording voice.")
    with engine.store.lock:
        protection = _protected_keys(engine)
        if protection is None:
            return _result(None, "error", "Paused study could not be checked. Resume it before testing a voice.", "protected_sample")
        rows = engine.store.rows("""SELECT s.id FROM resources s INDEXED BY resource_search_identity
          JOIN resources a INDEXED BY resource_assignment_schedule
            ON a.kind='assignment' AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
          WHERE s.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
            AND s.kind IN ('vocabulary','kana_vocabulary')
            AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
            AND json_extract(s.body,'$.data.hidden_at') IS NULL
            AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
            AND json_extract(a.body,'$.data.started_at') IS NOT NULL
          ORDER BY CAST(s.id AS INTEGER) LIMIT ?""", (engine.max_level(), MAX_SAMPLE_SUBJECTS))
        fallback = None
        for row in rows:
            subject = engine.store.subject(int(row[0]))
            if not _voice_safe(engine, subject, protection):
                continue
            result, chosen = _select(engine, subject["id"], "voice_test", None, None, voice_actor_id, protection)
            if chosen is None or (voice_actor_id is not None and _actor(chosen) != voice_actor_id):
                continue
            if result["status"] == "ready":
                return result
            fallback = fallback or result
        return fallback or _result(None, "no_recording", "No safe learned sample with this voice is available in the checked cache.")


def prepare(sync, subject_id, context="details", session_id=None, revision=None, voice_actor_id=None):
    engine = sync.engine
    arguments = (subject_id, context, session_id, revision, voice_actor_id)
    with engine.store.lock:
        result, chosen = _select(engine, *arguments)
        account = (engine.store.get("account_id"), engine.store.get("session_epoch"))
    if result["status"] != "not_cached":
        return result
    sync.media_requested.set()
    try:
        with sync.media_lock:
            with engine.store.lock:
                result, chosen = _select(engine, *arguments)
                if account != (engine.store.get("account_id"), engine.store.get("session_epoch")):
                    return _result(subject_id, "error", "The account changed. Choose the recording again.", "account_changed")
            if result["status"] != "not_cached":
                return result
            sync.check_cancelled()
            plan = media_plan.build(engine, sync.media_dir, time.monotonic() + 8, sync.cancelled.is_set)
            if not plan.complete:
                return _result(subject_id, "error", "The cache is still being checked. Try this recording again.", "cache_incomplete")
            if not sync._remove_media(plan.orphans, plan):
                return _result(subject_id, "error", "Interrupted cache files could not be cleaned. Try again after freeing space.", "cache_cleanup")
            url = chosen["url"]
            # Keep required radical images ahead of optional pronunciation,
            # and this explicit clip ahead of other optional prefetch content.
            plan._candidate(url, subject_id, "audio", (1, 3, 0), engine.now())
            previous = getattr(sync, "_media_plan", None)
            sync._media_plan = plan
            try:
                outcome = sync.download_media(url)
            finally:
                sync._media_plan = previous
            with engine.store.lock:
                if account != (engine.store.get("account_id"), engine.store.get("session_epoch")):
                    return _result(subject_id, "error", "The account changed. Choose the recording again.", "account_changed")
                current = status(engine, *arguments)
            if current["status"] in ("ready", "error", "no_recording", "offline"):
                return current
            if outcome == "skipped_budget":
                return {**current, "status": "budget", "message": "Required study media uses the cache budget. Increase the cache limit to keep this recording."}
            return {**current, "status": "error", "reason": "download_failed", "message": "This recording could not be downloaded. Retry when connected."}
    finally:
        sync.media_requested.clear()
