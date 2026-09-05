"""Cached whole-word kana dictation with independent, entirely local progress.

The exact recording label stays private until Check. Media delivery reserves a
fresh-word exposure; only an opaque completion acknowledgment enables Check.
Feedback is durable before Continue changes a local interval. No Engine graded
commands, assignment resources or outbox operations are used here.
"""
import json
import random
import uuid

from .common import UserError, epoch, stamp
from .grading import KANA, reading
from .media_files import available_file
from .media_plan import valid_url
from . import listening


PREFIX = "dictation_"
LIMIT = FRESH_LIMIT = 5
INTERVALS = listening.INTERVALS
TEXT_LIMIT = 256
INPUT_ERROR = "Type kana before checking. Finish romaji or Japanese input first."


def _bad_state():
    raise UserError("The saved dictation could not be read. Export diagnostics before starting a replacement.", "dictation_state")


def _identifier(value):
    return isinstance(value, str) and 1 <= len(value) <= 160 and all(32 <= ord(c) < 127 for c in value)


def _text(value, limit=TEXT_LIMIT):
    return isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 or 0xd800 <= ord(c) <= 0xdfff or ord(c) == 127 for c in value)


def _utf16(text):
    return len(text.encode("utf-16-le")) // 2


def _cursor(text, cursor):
    if type(cursor) is not int or not 0 <= cursor <= _utf16(text):
        return False
    position = 0
    for character in text:
        if position == cursor:
            return True
        position += 2 if ord(character) > 0xffff else 1
    return position == cursor


def _context(engine):
    return listening._context(engine)


def _card_key(context, subject_id):
    return PREFIX + "card_" + listening._scope(context) + "_" + str(subject_id)


def _day(engine, context):
    from datetime import datetime
    key = PREFIX + "day_" + listening._scope(context) + "_" + datetime.fromtimestamp(engine.now()).date().isoformat()
    value = engine.store.get(key, [])
    if not isinstance(value, list) or len(value) > FRESH_LIMIT or any(type(sid) is not int or sid <= 0 for sid in value):
        _bad_state()
    return key, set(value)


def _summary(value):
    return isinstance(value, dict) and set(value) == {"matched", "again", "skipped"} and all(type(count) is int and 0 <= count <= LIMIT for count in value.values())


def _session(engine):
    reference = engine.store.get(PREFIX + "active")
    if reference is None:
        return None
    if not _identifier(reference):
        _bad_state()
    session = engine.store.get(PREFIX + "session_" + reference)
    if (not isinstance(session, dict) or session.get("id") != reference or not isinstance(session.get("context"), dict)
            or type(session.get("revision")) is not int or session["revision"] < 1
            or type(session.get("draft_revision")) is not int or session["draft_revision"] < 0
            or epoch(session.get("started_at")) is None or session.get("phase") not in ("question", "feedback", "complete")
            or not isinstance(session.get("queue"), list) or not 1 <= len(session["queue"]) <= LIMIT
            or type(session.get("index")) is not int or not 0 <= session["index"] <= len(session["queue"])
            or (session["phase"] == "complete") != (session["index"] == len(session["queue"]))
            or not _summary(session.get("summary")) or sum(session["summary"].values()) != session["index"]):
        _bad_state()
    for entry in session["queue"]:
        if (not isinstance(entry, dict) or type(entry.get("subject_id")) is not int or entry["subject_id"] <= 0
                or not valid_url(entry.get("url")) or not _identifier(entry.get("handle"))
                or not isinstance(entry.get("pronunciation"), str)
                or listening._pronunciation(entry["pronunciation"]) != entry["pronunciation"]
                or type(entry.get("heard")) is not bool or type(entry.get("exposed")) is not bool
                or (entry["heard"] and not entry["exposed"])
                or (entry.get("playback_token") is not None and not _identifier(entry["playback_token"]))
                or not _text(entry.get("draft")) or not _cursor(entry["draft"], entry.get("cursor"))
                or not _text(entry.get("preedit")) or entry.get("input_error") not in ("", INPUT_ERROR)):
            _bad_state()
        feedback = entry.get("feedback")
        if feedback is not None and (not isinstance(feedback, dict) or set(feedback) != {"matched", "submitted", "recorded"} or type(feedback.get("matched")) is not bool
                or not _text(feedback.get("submitted")) or feedback.get("recorded") != entry["pronunciation"]
                or not entry["heard"] or feedback.get("matched") != (reading(feedback["submitted"]) == entry["pronunciation"])):
            _bad_state()
    for field in ("subject_id", "handle", "pronunciation"):
        if len({entry[field] for entry in session["queue"]}) != len(session["queue"]):
            _bad_state()
    if session["phase"] == "feedback" and session["queue"][session["index"]].get("feedback") is None:
        _bad_state()
    undo = session.get("undo")
    if undo is not None and (not isinstance(undo, dict) or type(undo.get("index")) is not int
            or undo["index"] != session["index"] - 1 or not 0 <= undo["index"] < len(session["queue"])
            or not _summary(undo.get("summary")) or sum(undo["summary"].values()) != undo["index"]
            or not _identifier(undo.get("operation")) or "record" not in undo or session["queue"][undo["index"]].get("feedback") is None):
        _bad_state()
    if undo is not None:
        try:
            listening._record(undo["record"])
        except UserError:
            _bad_state()
    return session


def _save(engine, session, *, structural=True):
    if structural:
        session["revision"] += 1
    engine.store.set(PREFIX + "session_" + session["id"], session)
    engine.store.set(PREFIX + "active", session["id"])


def _checked(engine, session):
    if not session or session.get("context") != _context(engine):
        raise UserError("This dictation belongs to an earlier account or reset. Start a new local session.", "dictation_context")
    if session["phase"] == "complete":
        return None
    entry = session["queue"][session["index"]]
    item = listening._eligible(engine, entry["subject_id"], listening._protection(engine), listening._settings(engine), entry["url"], entry["pronunciation"])
    if not item:
        raise UserError("This word or its pinned recording is no longer available for dictation. Skip it or refresh your cache.", "dictation_unavailable")
    return item


def _intervals(engine, session, entry):
    old = listening._record(engine.store.get(_card_key(session["context"], entry["subject_id"]))) or {}
    step = max(0, min(len(INTERVALS) - 1, old.get("step", -1) + 1))
    return {"matched_days": INTERVALS[step], "again_minutes": 10}


def _undo_available(engine, session):
    """Undo belongs to the previous result, independently of the next clip."""
    try:
        if not session.get("undo") or session["context"] != _context(engine):
            return False
        entry = session["queue"][session["undo"]["index"]]
        return bool(listening._eligible(engine, entry["subject_id"], listening._protection(engine),
            listening._settings(engine), entry["url"], entry["pronunciation"]))
    except UserError:
        return False


def view(engine):
    with engine.store.lock:
        session = _session(engine)
        if session is None:
            return None
        result = {key: session[key] for key in ("id", "revision", "phase", "index", "started_at", "draft_revision")}
        result.update(total=len(session["queue"]), prompt="Type what you heard", media_handle=None,
            heard=False, draft="", draft_cursor=0, preedit="", input_error="", feedback=None, subject=None,
            summary=dict(session["summary"]), undo_available=_undo_available(engine, session), local_only=True, intervals=None)
        try:
            item = _checked(engine, session)
            if item is None:
                return result
            entry = session["queue"][session["index"]]
            result.update(media_handle=entry["handle"], heard=entry["heard"], draft=entry["draft"],
                draft_cursor=entry["cursor"], preedit=entry["preedit"], input_error=entry["input_error"])
            if session["phase"] == "feedback":
                feedback = entry["feedback"]
                result["feedback"] = {**feedback, "message": "Matched the recording." if feedback["matched"] else "The kana differs from this recording's label. Skip without a result if another spelling fits what you heard."}
                details = engine.details(item["subject_id"], False)
                result["subject"] = {key: details[key] for key in ("id", "type", "characters", "meanings", "material")}
                result["subject"].update(pronunciation=item["clip"]["pronunciation"], voice=item["clip"]["voice"])
                result["intervals"] = _intervals(engine, session, entry)
        except UserError as error:
            result.update(unavailable=str(error), media_handle=None, heard=False, draft="", draft_cursor=0,
                preedit="", input_error="", feedback=None, subject=None, intervals=None)
        return result


def status(engine):
    with engine.store.lock:
        context = _context(engine)
        pool, complete = listening._pool(engine, context, listening._settings(engine), card_key=_card_key)
        _, introduced = _day(engine, context)
        remaining = max(0, FRESH_LIMIT - len(introduced))
        saved = _session(engine)
        valid_saved = saved and saved["context"] == context
        sounds, available = set(), 0
        for item in pool:
            sound = item["clip"]["pronunciation"]
            fresh = not item["record"] and item["subject_id"] not in introduced
            if sound not in sounds and (not fresh or remaining > 0):
                available += 1
                remaining -= int(fresh)
                sounds.add(sound)
        return {"eligible": len(pool), "complete": complete, "due": sum(bool(item["record"]) for item in pool),
            "available": available, "new_remaining": max(0, FRESH_LIMIT - len(introduced)), "new_limit": FRESH_LIMIT,
            "settings": listening._settings(engine), "local_only": True,
            "saved": {"id": saved["id"], "phase": saved["phase"], "completed": saved["index"], "total": len(saved["queue"])} if valid_saved else None,
            "message": "Five new dictation words per day, separate from meaning listening." if pool else "No eligible cached recordings are ready for dictation. Download vocabulary audio or adjust Listen's due-soon preference."}


def _expose(engine, session, entry):
    if entry["exposed"]:
        return
    key, introduced = _day(engine, session["context"])
    record = listening._record(engine.store.get(_card_key(session["context"], entry["subject_id"])))
    if record is None and entry["subject_id"] not in introduced:
        if len(introduced) >= FRESH_LIMIT:
            raise UserError("Today's five new dictation words are used. Resume tomorrow; meaning listening has its own allowance.", "dictation_daily_limit")
        introduced.add(entry["subject_id"])
        engine.store.set(key, sorted(introduced))
    entry["exposed"] = True


def media(engine, handle):
    if not _identifier(handle):
        raise UserError("Choose the current dictation recording.", "invalid_request")
    with engine.store.transaction():
        session = _session(engine)
        item = _checked(engine, session)
        if item is None or session["queue"][session["index"]]["handle"] != handle:
            raise UserError("This is no longer the current dictation recording.", "stale_dictation")
        entry = session["queue"][session["index"]]
        path = available_file(engine.store.path.parent / "media", item["clip"]["path"])
        if path is None:
            raise UserError("The pinned recording is unavailable. Retry or skip without a result.", "dictation_unavailable")
        _expose(engine, session, entry)
        entry["playback_token"] = uuid.uuid4().hex
        _save(engine, session)
        return {"handle": handle, "uri": path.as_uri(), "voice": item["clip"]["voice"],
            "playback_token": entry["playback_token"], "session_id": session["id"], "revision": session["revision"]}


def _set_draft(session, entry, text, cursor, preedit):
    entry.update(draft=text, cursor=cursor, preedit=preedit, input_error="")
    session["draft_revision"] += 1


def draft(engine, session_id, handle, text, cursor, preedit=""):
    if not _identifier(session_id) or not _identifier(handle) or not _text(text) or not _cursor(text, cursor) or not _text(preedit):
        raise UserError("Dictation drafts require bounded text and a valid cursor.", "invalid_request")
    with engine.store.transaction():
        session = _session(engine)
        _checked(engine, session)
        if session["id"] != session_id or session["phase"] != "question" or session["queue"][session["index"]]["handle"] != handle:
            raise UserError("This dictation draft belongs to an earlier card.", "stale_dictation")
        entry = session["queue"][session["index"]]
        _set_draft(session, entry, text, cursor, preedit)
        _save(engine, session, structural=False)
        return {"saved": True, "session_id": session_id, "handle": handle, "draft_revision": session["draft_revision"]}


def _start(engine, args):
    context = _context(engine)
    old = _session(engine) if not args.get("replace", False) else None
    if old and old["context"] == context and old["phase"] != "complete":
        return
    pool, _ = listening._pool(engine, context, listening._settings(engine), card_key=_card_key)
    _, introduced = _day(engine, context)
    remaining = max(0, FRESH_LIMIT - len(introduced))
    queue, sounds, ids = [], set(), set()
    for item in pool:
        clip, sid = item["clip"], item["subject_id"]
        if sid in ids or clip["pronunciation"] in sounds:
            continue
        fresh = not item["record"] and sid not in introduced
        if fresh and remaining <= 0:
            continue
        remaining -= int(fresh)
        ids.add(sid)
        sounds.add(clip["pronunciation"])
        queue.append({"subject_id": sid, "url": clip["url"], "pronunciation": clip["pronunciation"],
            "handle": uuid.uuid4().hex, "exposed": False, "heard": False, "playback_token": None,
            "draft": "", "cursor": 0, "preedit": "", "input_error": "", "feedback": None})
        if len(queue) == LIMIT:
            break
    if not queue:
        raise UserError("No cached recordings fit this dictation batch or today's separate allowance.", "empty_dictation")
    random.SystemRandom().shuffle(queue)
    session = {"id": uuid.uuid4().hex, "context": context, "queue": queue, "phase": "question", "index": 0,
        "revision": 0, "draft_revision": 0, "started_at": stamp(engine.now()),
        "summary": {"matched": 0, "again": 0, "skipped": 0}, "undo": None}
    _save(engine, session)


def _arguments(operation_id, action, args):
    if not _identifier(operation_id) or not isinstance(args, dict):
        raise UserError("Provide a local dictation operation and its arguments.", "invalid_request")
    schema = {"start": (set(), {"replace"}), "heard": ({"session_id", "revision", "handle", "playback_token"}, set()),
        "check": ({"session_id", "revision", "text"}, set()),
        "continue": ({"session_id", "revision"}, set()), "skip": ({"session_id", "revision"}, set()),
        "undo": ({"session_id", "revision"}, set())}
    if not isinstance(action, str) or action not in schema:
        raise UserError("Unknown dictation action.", "invalid_request")
    required, optional = schema[action]
    if not required <= set(args) or set(args) - required - optional:
        raise UserError("Unexpected or missing dictation arguments.", "invalid_request")
    if action == "start":
        if type(args.get("replace", False)) is not bool:
            raise UserError("Choose whether to replace only the saved dictation.", "invalid_request")
    elif not _identifier(args["session_id"]) or type(args["revision"]) is not int or args["revision"] < 1:
        raise UserError("Use the current dictation session and revision.", "invalid_request")
    if action == "heard" and (not _identifier(args["handle"]) or not _identifier(args["playback_token"])):
        raise UserError("Use the current recording completion token.", "invalid_request")
    if action == "check" and not _text(args["text"]):
        raise UserError("Type at most 256 characters of kana or romaji.", "invalid_request")


def command(engine, operation_id, action, args=None):
    args = {} if args is None else args
    _arguments(operation_id, action, args)
    key = PREFIX + "command:" + operation_id
    with engine.store.transaction():
        if engine.store.rows("SELECT 1 FROM commands WHERE id=?", (key,)):
            return {"duplicate": True, "session": view(engine)}
        if action == "start":
            _start(engine, args)
        else:
            session = _session(engine)
            if not session or session["context"] != _context(engine):
                raise UserError("Start a current dictation session first.", "dictation_context")
            if session["id"] != args["session_id"] or session["revision"] != args["revision"]:
                raise UserError("This dictation changed. Use its current controls.", "stale_dictation")
            if action == "undo":
                undo = session.get("undo")
                if not undo:
                    raise UserError("There is no immediate dictation result to undo.", "dictation_undo")
                session["index"], session["phase"] = undo["index"], "feedback"
                _checked(engine, session)
                entry = session["queue"][session["index"]]
                engine.store.set(_card_key(session["context"], entry["subject_id"]), undo["record"])
                session["summary"], session["undo"] = undo["summary"], None
                engine.store.event(session["id"], None, "dictation_undo", stamp(engine.now()), {"operation": undo["operation"], "local_only": True})
                _save(engine, session)
            else:
                if session["phase"] == "complete":
                    raise UserError("This dictation batch is complete.", "dictation_complete")
                item = _checked(engine, session) if action != "skip" else None
                entry = session["queue"][session["index"]]
                if action == "heard":
                    if entry["handle"] != args["handle"] or entry["playback_token"] != args["playback_token"]:
                        raise UserError("This playback completion is no longer current.", "stale_dictation")
                    entry["heard"], entry["playback_token"] = True, None
                elif action == "check":
                    if session["phase"] != "question" or not entry["heard"]:
                        raise UserError("Finish playing this recording before checking kana.", "dictation_not_heard")
                    _set_draft(session, entry, args["text"], _utf16(args["text"]), "")
                    answer = reading(args["text"])
                    if not answer or not KANA.fullmatch(answer):
                        entry["input_error"] = INPUT_ERROR
                    else:
                        entry["feedback"] = {"matched": answer == entry["pronunciation"], "submitted": args["text"], "recorded": entry["pronunciation"]}
                        session["phase"] = "feedback"
                else:
                    if action == "continue" and session["phase"] != "feedback":
                        raise UserError("Check the kana before saving a dictation result.", "dictation_feedback")
                    rating = "matched" if action == "continue" and entry["feedback"]["matched"] else "again" if action == "continue" else "skipped"
                    if action == "continue":
                        card_key = _card_key(session["context"], entry["subject_id"])
                        old = listening._record(engine.store.get(card_key))
                        step = max(0, min(4, (old or {}).get("step", -1) + 1)) if rating == "matched" else -1
                        seconds = INTERVALS[step] * 86400 if rating == "matched" else 600
                        session["undo"] = {"index": session["index"], "record": old,
                            "summary": dict(session["summary"]), "operation": operation_id}
                        engine.store.set(card_key, {"subject_id": entry["subject_id"], "step": step,
                            "next_at": stamp(engine.now() + seconds), "attempts": (old or {}).get("attempts", 0) + 1,
                            "last_rating": rating, "last_at": stamp(engine.now())})
                    else:
                        session["undo"] = None
                    session["summary"][rating] += 1
                    engine.store.event(session["id"], entry["subject_id"], "dictation_result", stamp(engine.now()),
                        {"rating": rating, "operation": operation_id, "local_only": True})
                    session["index"] += 1
                    session["phase"] = "complete" if session["index"] == len(session["queue"]) else "question"
                    if session["phase"] == "question":
                        session["queue"][session["index"]].update(feedback=None, input_error="")
                _save(engine, session)
        engine.store.execute("INSERT INTO commands VALUES(?,?)", (key, json.dumps({"dictation_operation": action})))
        return {"duplicate": False, "session": view(engine)}


def retained_urls(engine):
    """Bounded, reauthorized audio hints for the existing media budget planner."""
    with engine.store.lock:
        try:
            session = _session(engine)
            if not session or session["context"] != _context(engine):
                return {}
            indices = set(range(session["index"], len(session["queue"])))
            if session.get("undo"):
                indices.add(session["undo"]["index"])
            protection, settings = listening._protection(engine), listening._settings(engine)
            result = {}
            for index in sorted(indices):
                entry = session["queue"][index]
                if listening._eligible(engine, entry["subject_id"], protection, settings, entry["url"], entry["pronunciation"]):
                    position = 0 if session["phase"] == "complete" else index - session["index"] if index >= session["index"] else LIMIT
                    result[entry["url"]] = min(result.get(entry["url"], 99), position)
            return result
        except UserError:
            return {}
