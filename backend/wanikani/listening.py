"""Local listening practice; no assignment, graded-session, or outbox writes.

API: status(engine), view(engine), command(engine, operation_id, action, args),
and media(engine, handle). A first media request durably counts exposure before
returning a URI: a later device/decoder failure may conservatively use that new
word's daily slot. Replay and exposure never change a learning interval.

All durable records use existing meta/events/commands tables. Deleting personal
data therefore removes this skill too. Command replies retain only operation
metadata; duplicate commands project the current safe view without reexecution.
"""
import hashlib
import json
import random
import uuid
from datetime import datetime

from .common import UserError, accessible_subject, epoch, stamp
from .api import user_id
from .grading import KANA, reading, validate_subject_answers
from .media_files import available_file
from .media_plan import valid_url
from . import progress


INTERVALS = (1, 3, 7, 14, 30)
LIMIT = 5
FRESH_LIMIT = 5
MAX_CANDIDATES = 256
MAX_CATALOGUE = 12000
FORMATS = ("audio/mpeg", "audio/ogg", "audio/mp4", "audio/webm")
PREFIX = "listening_"


def _context(engine):
    account = "demo" if engine.demo else engine.store.get("account_id")
    if not engine.user() or not isinstance(account, (str, int)) or isinstance(account, bool):
        raise UserError("Connect your account before starting listening practice.", "disconnected")
    if not engine.demo and user_id(engine.store.get("user")) != account:
        raise UserError("Refresh the current account before listening.", "listening_context")
    if engine.clock_untrusted or abs(engine.clock_offset) > 300:
        raise UserError("Verify the system clock before continuing local listening intervals.", "clock_untrusted")
    return {"account": str(account), "epoch": engine.store.get("session_epoch"),
        "reset": engine.store.get("milestone_reset_generation", 0), "demo": engine.demo}


def _scope(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()[:24]


def _card_key(context, subject_id):
    return PREFIX + "card_" + _scope(context) + "_" + str(subject_id)


def _day(engine, context):
    day = datetime.fromtimestamp(engine.now()).date().isoformat()
    key = PREFIX + "day_" + _scope(context) + "_" + day
    ids = engine.store.get(key, [])
    return key, {sid for sid in ids if type(sid) is int and sid > 0} if isinstance(ids, list) else set()


def _settings(engine):
    value = engine.store.get(PREFIX + "settings", {})
    if not isinstance(value, dict):
        value = {}
    return {"avoid_due_24h": value.get("avoid_due_24h", True) is not False}


def _record(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("step")) is not int or not -1 <= value["step"] <= 4
            or type(value.get("attempts")) is not int or value["attempts"] < 1
            or epoch(value.get("next_at")) is None):
        raise UserError("A saved listening interval could not be read. Export diagnostics before continuing.", "listening_state")
    return value


def _pronunciation(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return None
    value = reading(value)
    return value if KANA.fullmatch(value) else None


def _protection(engine):
    ids, characters = progress._protected(engine)
    if ids is None:
        raise UserError("Saved graded study could not be checked. Refresh or finish it before listening.", "protected_study")
    sounds = set()
    for sid in ids:
        subject = engine.store.subject(sid)
        if not accessible_subject(subject, engine.max_level()):
            # Hidden/restricted subjects cannot provide a safe comparison of
            # their possible readings. Withhold automatic listening meanwhile.
            raise UserError("Saved graded study must be refreshed before listening.", "protected_study")
        data = subject["data"]
        entries = data.get("readings", [])
        if not isinstance(entries, list) or len(entries) > 32:
            raise UserError("Saved readings could not be checked before listening.", "protected_study")
        for entry in entries:
            value = _pronunciation(entry.get("reading")) if isinstance(entry, dict) else None
            if not value:
                raise UserError("Saved readings could not be checked before listening.", "protected_study")
            sounds.add(value)
        if subject["object"] == "kana_vocabulary":
            value = _pronunciation(data.get("characters"))
            if not value:
                raise UserError("Saved readings could not be checked before listening.", "protected_study")
            sounds.add(value)
        if subject["object"] in ("kanji", "vocabulary") and not entries:
            raise UserError("Saved readings could not be checked before listening.", "protected_study")
        clips = data.get("pronunciation_audios", [])
        if not isinstance(clips, list) or len(clips) > 64:
            raise UserError("Saved pronunciation could not be checked before listening.", "protected_study")
        for clip in clips:
            metadata = clip.get("metadata") if isinstance(clip, dict) else None
            value = _pronunciation(metadata.get("pronunciation")) if isinstance(metadata, dict) else None
            if value:
                sounds.add(value)
    return ids, characters, sounds


def _scheduled(started_at, available_at, burned_at, now, avoid_due_24h):
    """Return the learned date only when the current assignment is eligible.

    Both catalogue projections and hydrated assignments use Python's parser:
    SQLite's date parser accepts values which the authoritative cache rejects.
    """
    started = epoch(started_at)
    if started is None or started > now:
        return None
    due, burned = epoch(available_at), epoch(burned_at)
    if avoid_due_24h and not (burned is not None and burned <= now) and (due is None or due <= now + 86400):
        return None
    return started


def _eligible(engine, subject_id, protection, settings, clip_url=None, pronunciation=None, *, require_cached=True):
    subject = engine.store.subject(subject_id)
    if not accessible_subject(subject, engine.max_level()) or subject.get("object") not in ("vocabulary", "kana_vocabulary"):
        return None
    if type(subject.get("id")) is not int or subject["id"] != subject_id:
        return None
    data = subject["data"]
    characters = data.get("characters")
    if not isinstance(characters, str) or not characters or len(characters) > 128:
        return None
    ids, aliases, sounds = protection
    if subject_id in ids or characters in aliases:
        return None
    assignments = engine.store.rows("SELECT body FROM resources INDEXED BY resource_subject WHERE kind='assignment' AND json_extract(body,'$.data.subject_id')=? LIMIT 2", (subject_id,))
    if len(assignments) != 1:
        return None
    resource = json.loads(assignments[0][0])
    if not isinstance(resource, dict):
        return None
    assignment = resource.get("data", {})
    if (resource.get("object") != "assignment" or not isinstance(assignment, dict)
            or type(assignment.get("subject_id")) is not int or assignment["subject_id"] != subject_id
            or type(assignment.get("srs_stage")) is not int or not 1 <= assignment["srs_stage"] <= 9):
        return None
    if assignment.get("hidden") not in (None, False):
        return None
    started = _scheduled(assignment.get("started_at"), assignment.get("available_at"),
        assignment.get("burned_at"), engine.now(), settings["avoid_due_24h"])
    if started is None:
        return None
    if engine.store.rows("SELECT 1 FROM outbox INDEXED BY outbox_state WHERE subject_id=? AND kind IN ('review','lesson') AND state IN " + progress.UNRESOLVED + " LIMIT 1", (subject_id,)):
        return None
    try:
        validate_subject_answers(subject)
    except UserError:
        return None
    # Revealing this card shows its other readings too. A safe selected clip
    # cannot justify exposing another unfinished question's reading afterward.
    readings = data.get("readings", [])
    if any(_pronunciation(entry.get("reading")) in sounds for entry in readings if isinstance(entry, dict)):
        return None
    if subject["object"] == "kana_vocabulary" and _pronunciation(characters) in sounds:
        return None
    clips = data.get("pronunciation_audios")
    if not isinstance(clips, list) or len(clips) > 64:
        return None
    candidates = []
    for clip in clips:
        if not isinstance(clip, dict) or clip.get("content_type") not in FORMATS or not isinstance(clip.get("metadata"), dict):
            continue
        url = clip.get("url")
        sound = _pronunciation(clip["metadata"].get("pronunciation"))
        if not valid_url(url) or not sound or sound in sounds:
            continue
        if clip_url is not None and (url != clip_url or sound != pronunciation):
            continue
        rows = engine.store.rows("SELECT path FROM media WHERE url=?", (url,))
        path = available_file(engine.store.path.parent / "media", rows[0][0]) if rows else None
        if path or not require_cached:
            candidates.append({"url": url, "path": str(path) if path else None, "pronunciation": sound,
                "actor": clip["metadata"].get("voice_actor_id"),
                "voice": progress._text(clip["metadata"].get("voice_actor_name"), 80) or "Recorded voice"})
    if not candidates:
        return None
    preferred = engine.settings()["voice_actor_id"]
    candidates.sort(key=lambda clip: (not bool(clip["path"]), clip["actor"] != preferred))
    return {"subject_id": subject_id, "characters": characters, "started_at": started, "clip": candidates[0]}


def _pool(engine, context, settings, subject_ids=None, *, require_cached=True, card_key=None):
    # Local audio skills share eligibility, but select their own due records.
    card_key = _card_key if card_key is None else card_key
    protection = _protection(engine)
    if subject_ids is None:
        rows = engine.store.rows("""SELECT CAST(s.id AS INTEGER),json_extract(a.body,'$.data.started_at'),
            json_extract(a.body,'$.data.available_at'),json_extract(a.body,'$.data.burned_at')
          FROM resources s INDEXED BY resource_search_identity JOIN resources a INDEXED BY resource_subject
          ON a.kind='assignment' AND json_extract(a.body,'$.data.subject_id')=CAST(s.id AS INTEGER)
          WHERE s.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
            AND s.kind IN ('vocabulary','kana_vocabulary') AND json_type(s.body,'$.data.level')='integer'
            AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ? AND json_extract(s.body,'$.data.hidden_at') IS NULL
            AND json_extract(a.body,'$.object')='assignment' AND json_type(a.body,'$.data')='object'
            AND json_type(a.body,'$.data.subject_id')='integer'
            AND json_type(a.body,'$.data.srs_stage')='integer'
            AND json_extract(a.body,'$.data.srs_stage') BETWEEN 1 AND 9
            AND (json_extract(a.body,'$.data.hidden') IS NULL OR json_extract(a.body,'$.data.hidden')=0)
            AND json_type(a.body,'$.data.started_at')='text'
            AND NOT EXISTS (SELECT 1 FROM outbox o INDEXED BY outbox_state
              WHERE o.subject_id=CAST(s.id AS INTEGER) AND o.kind IN ('review','lesson')
                AND o.state IN """ + progress.UNRESOLVED + """)
          GROUP BY s.id ORDER BY julianday(json_extract(a.body,'$.data.started_at')) DESC,CAST(s.id AS INTEGER)
          LIMIT ?""", (engine.max_level(), MAX_CATALOGUE + 1))
        # Due-soon or malformed schedules must not consume the expensive body
        # budget and hide older ready recordings. Project only metadata here;
        # _eligible still rechecks authoritative content, protection and audio.
        now = engine.now()
        ids = [row[0] for row in rows[:MAX_CATALOGUE]
            if _scheduled(row[1], row[2], row[3], now, settings["avoid_due_24h"]) is not None]
        complete = len(rows) <= MAX_CATALOGUE
        records = dict.fromkeys(ids)
        for offset in range(0, len(ids), 128):
            batch = ids[offset:offset + 128]
            keys = [card_key(context, sid) for sid in batch]
            for record in engine.store.rows("SELECT key,body FROM meta WHERE key IN (" + ",".join("?" for _ in keys) + ")", keys):
                sid = int(record[0].rsplit("_", 1)[-1])
                records[sid] = _record(json.loads(record[1]))
        pinned = engine.store.get("pinned_subjects", [])
        pinned = set(pinned) if isinstance(pinned, list) and all(type(sid) is int for sid in pinned) else set()
        ids.sort(key=lambda sid: (0 if records[sid] and (epoch(records[sid].get("next_at")) or 0) <= engine.now() else
            1 if sid in pinned else 2, epoch((records[sid] or {}).get("next_at")) or 0))
    else:
        ids = subject_ids
        complete = True
        records = {sid: _record(engine.store.get(card_key(context, sid))) for sid in ids}
    result = []
    checked = 0
    for sid in ids:
        record = records[sid]
        if subject_ids is None and record and (epoch(record.get("next_at")) or 0) > engine.now():
            continue
        if checked >= MAX_CANDIDATES:
            complete = False
            break
        checked += 1
        item = _eligible(engine, sid, protection, settings) if require_cached else \
            _eligible(engine, sid, protection, settings, require_cached=False)
        if item:
            item["record"] = record
            result.append(item)
    return result, complete


def _preparation_context(engine):
    """Capture grant and local selection inputs beyond durable skill identity."""
    context = _context(engine)
    subscription = engine.user().get("subscription")
    if not isinstance(subscription, dict):
        raise UserError("Refresh your account access before preparing recordings.", "access_restricted")
    day, introduced = _day(engine, context)
    expiry = epoch(subscription.get("period_ends_at"))
    preferences = engine.settings()
    return {"skill": context, "subscription": json.dumps(subscription, sort_keys=True),
        "expired": subscription.get("type") == "recurring" and (expiry is None or expiry <= engine.now()),
        "maximum": engine.max_level(), "day": day, "introduced": sorted(introduced),
        "settings": _settings(engine), "voice": preferences["voice_actor_id"],
        "cache_limit_mb": preferences["cache_limit_mb"]}


def preparation_candidates(engine, limit=LIMIT):
    """Read-only internal descriptors for one batch, never an IPC projection.

    Preparation and cached session creation share all content authorization.
    Missing files are permitted here only; this does not introduce/hear words.
    """
    if type(limit) is not int or not 1 <= limit <= LIMIT:
        raise UserError("Prepare between one and five recordings.")
    with engine.store.lock:
        context = _preparation_context(engine)
        saved = _session(engine)
        if saved and saved["context"] == context["skill"] and saved["phase"] != "complete":
            return {"context": context, "items": [], "complete": True, "reason": "saved_session"}
        pool, complete = _pool(engine, context["skill"], context["settings"], require_cached=False)
        # Fill the same usable cached pool before downloading additional words.
        # Preserve local due/pinned/recent order within each availability group.
        pool.sort(key=lambda item: not bool(item["clip"]["path"]))
        introduced = set(context["introduced"])
        remaining = max(0, FRESH_LIMIT - len(introduced))
        items, sounds, subjects = [], set(), set()
        daily_limited = False
        for item in pool:
            sound, sid = item["clip"]["pronunciation"], item["subject_id"]
            if sound in sounds or sid in subjects:
                continue
            fresh = not item["record"] and sid not in introduced
            if fresh and remaining <= 0:
                daily_limited = True
                continue
            remaining -= int(fresh)
            items.append(item)
            sounds.add(sound)
            subjects.add(sid)
            if len(items) == limit:
                break
        reason = "incomplete" if not complete else "daily_limit" if not items and daily_limited else "no_candidates" if not items else ""
        return {"context": context, "items": items, "complete": complete, "reason": reason}


def preparation_permitted(engine, context, item, *, require_cached=False):
    """Revalidate one selected descriptor without changing local study state."""
    with engine.store.lock:
        try:
            if _preparation_context(engine) != context:
                return False
            saved = _session(engine)
            if saved and saved["context"] == context["skill"] and saved["phase"] != "complete":
                return False
            sid, clip = item["subject_id"], item["clip"]
            current_record = _record(engine.store.get(_card_key(context["skill"], sid)))
            if current_record != item["record"] or (current_record and epoch(current_record["next_at"]) > engine.now()):
                return False
            return _eligible(engine, sid, _protection(engine), context["settings"],
                clip["url"], clip["pronunciation"], require_cached=require_cached) is not None
        except UserError:
            return False


def _session(engine):
    sid = engine.store.get(PREFIX + "active")
    session = engine.store.get(PREFIX + "session_" + sid) if isinstance(sid, str) else None
    if session is None:
        return None
    if (not isinstance(session, dict) or session.get("id") != sid or not isinstance(session.get("context"), dict)
            or session.get("phase") not in ("question", "revealed", "complete")
            or type(session.get("revision")) is not int or session["revision"] < 1
            or type(session.get("index")) is not int or not isinstance(session.get("queue"), list)
            or not 1 <= len(session["queue"]) <= LIMIT or not 0 <= session["index"] <= len(session["queue"])
            or (session["phase"] == "complete") != (session["index"] == len(session["queue"]))
            or not isinstance(session.get("summary"), dict) or type(session.get("extra")) is not bool
            or any(type(session["summary"].get(key)) is not int or session["summary"][key] < 0
                for key in ("remembered", "again", "skipped"))
            or any(not isinstance(entry, dict) or type(entry.get("subject_id")) is not int
                or not isinstance(entry.get("url"), str) or not isinstance(entry.get("handle"), str)
                or _pronunciation(entry.get("pronunciation")) is None for entry in session["queue"])):
        raise UserError("The saved listening session could not be read. Export diagnostics before starting a replacement.", "listening_state")
    return session


def _save(engine, session):
    session["revision"] += 1
    engine.store.set(PREFIX + "session_" + session["id"], session)
    engine.store.set(PREFIX + "active", session["id"])


def _checked(engine, session):
    if not isinstance(session, dict) or session.get("context") != _context(engine):
        raise UserError("This listening session belongs to an earlier account or reset. Start a new local session.", "listening_context")
    if session["phase"] == "complete":
        return None
    entry = session["queue"][session["index"]]
    item = _eligible(engine, entry["subject_id"], _protection(engine), _settings(engine), entry["url"], entry["pronunciation"])
    if not item:
        raise UserError("This word is no longer eligible or its recording is unavailable. Skip it or refresh before continuing.", "listening_unavailable")
    return item


def _alternatives(engine, item):
    sound = item["clip"]["pronunciation"]
    katakana = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in sound)
    rows = engine.store.rows("""SELECT CAST(s.id AS INTEGER)
      FROM resources s INDEXED BY resource_search_identity
      WHERE s.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
        AND s.kind IN ('vocabulary','kana_vocabulary')
        AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
        AND json_extract(s.body,'$.data.hidden_at') IS NULL
        AND EXISTS (SELECT 1 FROM json_each(CASE WHEN json_type(s.body,'$.data.pronunciation_audios')='array'
          THEN json_extract(s.body,'$.data.pronunciation_audios') ELSE '[]' END) clip
          WHERE clip.type='object' AND json_extract(clip.value,'$.metadata.pronunciation') IN (?,?))
      ORDER BY CAST(s.id AS INTEGER) LIMIT 17""", (engine.max_level(), sound, katakana))
    protection = _protection(engine)
    alternatives = []
    for row in rows[:16]:
        if row[0] == item["subject_id"]:
            continue
        other = _eligible(engine, row[0], protection, _settings(engine))
        if other and other["clip"]["pronunciation"] == sound:
            details = engine.details(row[0], False)
            alternatives.append({"characters": details["characters"], "meanings": details["meanings"]})
        if len(alternatives) >= 8:
            break
    return alternatives


def _expose(engine, session, item):
    entry = session["queue"][session["index"]]
    if entry.get("exposed"):
        return
    context = session["context"]
    key, introduced = _day(engine, context)
    card = engine.store.get(_card_key(context, item["subject_id"]))
    if not card and item["subject_id"] not in introduced:
        if len(introduced) >= FRESH_LIMIT and not session["extra"]:
            raise UserError("Today's five new listening words are complete. Resume tomorrow or deliberately choose extra words.", "listening_daily_limit")
        introduced.add(item["subject_id"])
        engine.store.set(key, sorted(introduced))
    entry["exposed"] = True
    _save(engine, session)


def view(engine):
    with engine.store.lock:
        session = _session(engine)
        if not session:
            return None
        result = {key: session[key] for key in ("id", "revision", "phase", "index", "started_at")}
        result.update(total=len(session["queue"]), prompt="What does this word mean?", media_handle=None,
            subject=None, summary=dict(session["summary"]), undo_available=bool(session.get("undo")),
            local_only=True, intervals=None)
        try:
            item = _checked(engine, session)
            if item is None:
                return result
            entry = session["queue"][session["index"]]
            result["media_handle"] = entry["handle"]
            if session["phase"] == "revealed":
                record = _record(engine.store.get(_card_key(session["context"], item["subject_id"]))) or {}
                step = max(0, min(len(INTERVALS) - 1, record.get("step", -1) + 1))
                result["intervals"] = {"remembered_days": INTERVALS[step], "again_minutes": 10}
                details = engine.details(item["subject_id"], False)
                result["subject"] = {key: details[key] for key in ("id", "type", "characters", "meanings", "readings", "material")}
                result["subject"].update(pronunciation=item["clip"]["pronunciation"], voice=item["clip"]["voice"],
                    local_progress={"attempts": record.get("attempts", 0), "last_rating": record.get("last_rating"),
                        "next_at": record.get("next_at"), "local_only": True},
                    alternatives=_alternatives(engine, item),
                    ambiguity_note="Other Japanese words may share this sound. A plausible different meaning is not an error; skip if uncertain.")
        except UserError as error:
            result.update(unavailable=str(error), media_handle=None, subject=None, undo_available=False)
        return result


def media(engine, handle):
    with engine.store.transaction():
        session = _session(engine)
        item = _checked(engine, session)
        if item is None or not isinstance(handle, str) or handle != session["queue"][session["index"]]["handle"]:
            raise UserError("This recording is no longer the current listening card.", "stale_listening")
        _expose(engine, session, item)
        path = available_file(engine.store.path.parent / "media", item["clip"]["path"])
        if path is None:
            raise UserError("The cached recording is no longer available.", "listening_unavailable")
        return {"handle": handle, "uri": path.as_uri(),
            "voice": item["clip"]["voice"], "session_id": session["id"], "revision": session["revision"]}


def status(engine):
    with engine.store.lock:
        context = _context(engine)
        settings = _settings(engine)
        pool, complete = _pool(engine, context, settings)
        _, introduced = _day(engine, context)
        saved = _session(engine)
        valid_saved = saved and saved.get("context") == context
        remaining = max(0, FRESH_LIMIT - len(introduced))
        sounds = set()
        available = 0
        for item in pool:
            sound = item["clip"]["pronunciation"]
            fresh = not item["record"] and item["subject_id"] not in introduced
            if sound not in sounds and (not fresh or remaining > 0):
                available += 1
                remaining -= int(fresh)
                sounds.add(sound)
        return {"eligible": len(pool), "complete": complete, "due": sum(bool(item["record"]) for item in pool),
            "available": available,
            "new_remaining": max(0, FRESH_LIMIT - len(introduced)), "settings": settings,
            "saved": {"id": saved["id"], "phase": saved["phase"], "completed": saved["index"], "total": len(saved["queue"])} if valid_saved else None,
            "local_only": True, "message": "Choose up to five familiar recordings." if pool else "No eligible cached vocabulary recordings are ready. Refresh audio or adjust the due-soon preference."}


def _start(engine, args):
    context = _context(engine)
    if type(args.get("replace", False)) is not bool:
        raise UserError("Choose whether to replace the saved listening session.")
    requested = args.get("subject_ids")
    if requested is not None and (not isinstance(requested, list) or not 1 <= len(requested) <= LIMIT
            or any(type(sid) is not int or sid <= 0 for sid in requested)):
        raise UserError("Choose one to five listening words.")
    if type(args.get("extra", False)) is not bool or (args.get("extra") and not requested):
        raise UserError("Extra practice requires an explicit selection of words.")
    old = _session(engine) if not args.get("replace", False) else None
    if old and old.get("context") == context and old["phase"] != "complete":
        # The view rechecks the current card and can offer Skip when media or
        # eligibility changed, while preserving the exact saved position.
        return old
    pool, _ = _pool(engine, context, _settings(engine), list(dict.fromkeys(requested)) if requested else None)
    _, introduced = _day(engine, context)
    remaining = max(0, FRESH_LIMIT - len(introduced))
    queue, sounds, subjects = [], set(), set()
    for item in pool:
        clip = item["clip"]
        if clip["pronunciation"] in sounds or item["subject_id"] in subjects:
            continue
        fresh = not item["record"] and item["subject_id"] not in introduced
        if fresh and remaining <= 0 and not args.get("extra", False):
            continue
        remaining -= int(fresh)
        sounds.add(clip["pronunciation"])
        subjects.add(item["subject_id"])
        queue.append({"subject_id": item["subject_id"], "url": clip["url"], "pronunciation": clip["pronunciation"],
            "handle": uuid.uuid4().hex, "exposed": False})
        if len(queue) == LIMIT:
            break
    if not queue:
        raise UserError("No eligible recordings fit this listening session. Refresh audio, adjust the due-soon preference, or return after the next local interval.", "empty_listening")
    random.SystemRandom().shuffle(queue)
    session = {"id": uuid.uuid4().hex, "context": context, "queue": queue, "phase": "question", "index": 0,
        "revision": 0, "started_at": stamp(engine.now()), "summary": {"remembered": 0, "again": 0, "skipped": 0},
        "extra": args.get("extra", False), "undo": None}
    _save(engine, session)
    return session


def command(engine, operation_id, action, args=None):
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 160:
        raise UserError("Provide a local operation identifier.")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise UserError("Invalid listening action.")
    key = PREFIX + "command:" + operation_id
    with engine.store.transaction():
        previous = engine.store.rows("SELECT body FROM commands WHERE id=?", (key,))
        if previous:
            return {"duplicate": True, "session": view(engine)}
        if action == "settings":
            value = args.get("avoid_due_24h")
            if type(value) is not bool:
                raise UserError("Choose whether to avoid reviews in the next 24 hours.")
            engine.store.set(PREFIX + "settings", {"avoid_due_24h": value})
        elif action == "start":
            _start(engine, args)
        else:
            session = _session(engine)
            if not session or session.get("context") != _context(engine):
                raise UserError("Start a current listening session first.", "listening_context")
            if (args.get("session_id") != session["id"] or type(args.get("revision")) is not int
                    or args["revision"] != session["revision"]):
                raise UserError("This listening card changed. Use its current controls.", "stale_listening")
            if action == "undo":
                undo = session.get("undo")
                if not undo:
                    raise UserError("There is no current listening rating to undo.")
                session["index"] = undo["index"]
                session["phase"] = "revealed"
                _checked(engine, session)
                engine.store.set(undo["card_key"], undo["record"])
                session["summary"] = undo["summary"]
                session["undo"] = None
                engine.store.event(session["id"], None, "listening_undo", stamp(engine.now()), {"operation": undo["operation"]})
                _save(engine, session)
            elif action in ("reveal", "rate", "skip"):
                if session["phase"] == "complete":
                    raise UserError("This listening session is complete.")
                item = _checked(engine, session) if action != "skip" else None
                if action == "reveal":
                    _expose(engine, session, item)
                    session["phase"] = "revealed"
                    _save(engine, session)
                else:
                    entry = session["queue"][session["index"]]
                    choice = args.get("rating") if action == "rate" else "skipped"
                    if action == "rate" and (session["phase"] != "revealed" or choice not in ("remembered", "again")):
                        raise UserError("Reveal the word before recording a listening rating.")
                    card_key = _card_key(session["context"], entry["subject_id"])
                    old = _record(engine.store.get(card_key))
                    if action == "rate":
                        _expose(engine, session, item)
                        step = max(0, min(4, (old or {}).get("step", -1) + 1)) if choice == "remembered" else -1
                        seconds = INTERVALS[step] * 86400 if choice == "remembered" else 600
                        session["undo"] = {"index": session["index"], "card_key": card_key, "record": old,
                            "summary": dict(session["summary"]), "operation": operation_id}
                        engine.store.set(card_key, {"subject_id": entry["subject_id"], "step": step,
                            "next_at": stamp(engine.now() + seconds), "attempts": (old or {}).get("attempts", 0) + 1,
                            "last_rating": choice, "last_at": stamp(engine.now())})
                    else:
                        session["undo"] = None
                    session["summary"][choice] += 1
                    engine.store.event(session["id"], entry["subject_id"], "listening_result", stamp(engine.now()),
                        {"rating": choice, "local_only": True, "operation": operation_id})
                    session["index"] += 1
                    session["phase"] = "complete" if session["index"] == len(session["queue"]) else "question"
                    _save(engine, session)
            else:
                raise UserError("Unknown listening action.")
        engine.store.execute("INSERT INTO commands VALUES(?,?)", (key, json.dumps({"listening_operation": action})))
        return {"duplicate": False, "session": view(engine)}
