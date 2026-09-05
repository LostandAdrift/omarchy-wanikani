"""Durable lesson discovery coordinates; grading remains in Engine.advance.

Only a current session ID and revision can move the guided presentation. Old
sessions need no migration: absent step values start at Meaning. Projection is
read-only and may omit an optional section after current content access changes.
"""
from .common import UserError


ORDER = ("meaning", "reading", "context")


def sections(detail):
    result = [{"id": "meaning", "label": "Meaning"}]
    if not isinstance(detail, dict):
        return result
    kind = detail.get("type")
    if kind in ("kanji", "vocabulary"):
        result.append({"id": "reading", "label": "Reading" if kind == "kanji" else "Reading & audio"})
    elif kind == "kana_vocabulary" and detail.get("audio_available") is True:
        result.append({"id": "reading", "label": "Sound"})
    sentences = detail.get("sentences")
    context = isinstance(sentences, list) and any(isinstance(item, dict) and any(
        isinstance(item.get(key), str) and item[key].strip() for key in ("ja", "en")) for item in sentences)
    relationships = any(isinstance(detail.get(key), list) and any(isinstance(item, dict)
        and type(item.get("id")) is int and item["id"] > 0 for item in detail[key])
        for key in ("components", "related", "visually_similar"))
    if context or relationships:
        result.append({"id": "context", "label": "Context"})
    return result


def project(session, detail):
    """Derive bounded navigation metadata without writing the saved record."""
    if session.get("mode") != "lessons" or session.get("phase") != "lesson":
        return None
    steps = sections(detail)
    old_flow = session.get("lesson_flow")
    requested = session.get("lesson_step", old_flow.get("step", "meaning") if isinstance(old_flow, dict) else "meaning")
    ids = [step["id"] for step in steps]
    if requested in ids:
        selected = requested
    elif requested in ORDER:
        selected = next(step for step in reversed(ids) if ORDER.index(step) < ORDER.index(requested))
    else:
        selected = "meaning"
    position = ids.index(selected)
    index = session.get("lesson_index", 0)
    queue = session.get("queue")
    total = len(queue) if isinstance(queue, list) else session.get("total", 0)
    later_subject = index + 1 < total
    later_step = position + 1 < len(steps)
    available = isinstance(detail, dict) and not detail.get("content_error")
    return {"step": selected, "steps": steps, "position": position + 1, "total": len(steps),
        "can_back": index > 0 or bool(available and position > 0),
        "can_next": bool(available and (later_step or later_subject)),
        "can_quiz": bool(available and not later_step and not later_subject),
        "next_label": "Next: " + steps[position + 1]["label"] if later_step else "Next subject" if later_subject else "",
        "adjusted": requested != selected}


def navigate(engine, values):
    if (not isinstance(values, dict) or set(values) != {"action", "session_id", "revision"}
            or values.get("action") not in ("next", "back", "quiz")
            or not isinstance(values.get("session_id"), str) or not 1 <= len(values["session_id"]) <= 160
            or type(values.get("revision")) is not int or values["revision"] < 0):
        raise UserError("Choose the current lesson step and a valid navigation action.", "invalid_request")
    with engine.store.transaction():
        session = engine.store.session()
        if (not session or session.get("id") != values["session_id"]
                or session.get("revision", 0) != values["revision"]):
            raise UserError("The lesson changed. Resume it to load your saved position.", "stale_session")
        if session.get("mode") != "lessons" or session.get("phase") != "lesson":
            raise UserError("Lesson discovery is not active. Your saved study was kept.", "invalid_mode")
        queue, index = session.get("queue"), session.get("lesson_index")
        if (not isinstance(queue, list) or not queue or type(index) is not int or not 0 <= index < len(queue)
                or not isinstance(queue[index], dict)):
            raise UserError("The saved lesson position could not be read. Your work was kept.", "invalid_session")
        engine.ensure_study_state(session)
        detail = None
        try:
            current = engine.store.subject(queue[index]["subject_id"])
            engine.ensure_study_content(current)
            detail = engine.details(current["id"])
        except UserError:
            # Going back may leave a missing radical image or inaccessible
            # current subject. Forward and quiz still require valid content.
            if values["action"] != "back":
                raise
        flow = project(session, detail)
        action = values["action"]
        if not flow["can_" + action]:
            message = "Choose Start lesson quiz when you are ready." if action == "next" and flow["can_quiz"] else "This lesson action is not available at the current step."
            raise UserError(message, "invalid_step")
        step_index = flow["position"] - 1
        if action == "quiz":
            # Validate the prompt being entered before changing the phase. No
            # answer, assignment start, or outbox operation is created here.
            engine.ensure_study_content(engine.store.subject(queue[session["index"]]["subject_id"]))
            session["phase"] = "question"
        elif action == "next" and step_index + 1 < len(flow["steps"]):
            session["lesson_step"] = flow["steps"][step_index + 1]["id"]
        elif action == "back" and detail is not None and step_index > 0:
            session["lesson_step"] = flow["steps"][step_index - 1]["id"]
        else:
            target = index + (1 if action == "next" else -1)
            subject = engine.store.subject(queue[target]["subject_id"])
            engine.ensure_study_content(subject)
            target_detail = engine.details(subject["id"])
            session["lesson_index"] = target
            session["lesson_step"] = "meaning" if action == "next" else sections(target_detail)[-1]["id"]
        engine.store.save_session(session)
        return engine.session_view(session)
