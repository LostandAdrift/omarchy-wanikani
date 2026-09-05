"""A bounded, read-only recap of one completed local session.

The durable queue establishes what was completed; the matching local outbox
record establishes submission status. No account-wide accuracy or elapsed
study time is inferred. Answer text, notes and assignment baselines stay private.
"""
from .common import UserError
from .recovery import _protected_subjects, _subject


STATUS_LABELS = {
    "pending": "Saved · waiting to sync",
    "inflight": "Sending · awaiting confirmation",
    "uncertain": "Outcome uncertain · check saved submissions",
    "conflicted": "Needs review · local result retained",
    "blocked": "Account access needs attention",
    "confirmed": "Confirmed by WaniKani",
    "discarded": "Archived · remote progress kept",
    "ungraded": "Practice only · no account change",
    "unfinished": "Not completed in this session",
    "missing": "Local completion · submission record unavailable",
}


def report(engine, session_id=None):
    if session_id is not None and (not isinstance(session_id, str) or not session_id or len(session_id) > 160):
        raise UserError("Choose a completed local session.")
    session = engine.store.session(session_id)
    if not session or session.get("phase") != "complete":
        raise UserError("The batch recap is available after the session ends.", "session_unfinished")
    if session.get("mode") not in ("reviews", "lessons", "practice"):
        raise UserError("This saved session has an unavailable study mode.")
    queue = session.get("queue")
    if not isinstance(queue, list) or len(queue) > 20:
        raise UserError("This saved session needs inspection before a recap is available.")
    maximum, protected = engine.max_level(), _protected_subjects(engine)
    items, practice_ids, mistake_ids = [], [], []
    totals = {"completed": 0, "not_completed": 0, "meaning": 0, "reading": 0, "without_mistakes": 0}
    for entry in queue:
        subject_id = entry.get("subject_id") if isinstance(entry, dict) else None
        if type(subject_id) is not int or subject_id < 1:
            raise UserError("This saved session contains an unavailable subject reference.")
        done = entry.get("done") is True
        # Ended/reset sessions may still contain unfinished subjects. Do not
        # expose their answers as if they were acknowledged completions.
        subject = _subject(engine, subject_id, maximum, protected | ({subject_id} if not done else set()))
        counters = entry.get("errors", {})
        if not isinstance(counters, dict):
            raise UserError("This saved session contains invalid mistake counts.")
        errors = {part: counters.get(part, 0) for part in ("meaning", "reading")}
        if any(type(value) is not int or value < 0 for value in errors.values()):
            raise UserError("This saved session contains invalid mistake counts.")
        errors["total"] = errors["meaning"] + errors["reading"]
        state = "unfinished"
        if done:
            totals["completed"] += 1
            totals["meaning"] += errors["meaning"]
            totals["reading"] += errors["reading"]
            totals["without_mistakes"] += int(errors["total"] == 0)
            if session["mode"] == "practice":
                state = "ungraded"
            else:
                rows = engine.store.rows("SELECT state,subject_id,kind FROM outbox WHERE id=?",
                    (session["id"] + ":" + str(subject_id),))
                expected = "lesson" if session["mode"] == "lessons" else "review"
                if rows and rows[0]["subject_id"] == subject_id and rows[0]["kind"] == expected:
                    state = rows[0]["state"] if rows[0]["state"] in STATUS_LABELS else "missing"
                else:
                    state = "missing"
        else:
            totals["not_completed"] += 1
        ready = False
        if done and subject["accessible"]:
            try:
                engine.ensure_study_content(engine.store.subject(subject_id))
                ready = True
            except UserError:
                pass
        if ready:
            practice_ids.append(subject_id)
            if errors["total"]:
                mistake_ids.append(subject_id)
        label = STATUS_LABELS[state]
        if engine.demo and state == "confirmed":
            label = "Confirmed locally in demo"
        elif engine.demo and state == "conflicted":
            label = "Demo conflict · local result retained"
        elif engine.demo and state == "discarded":
            label = "Archived locally in demo"
        items.append({"subject": subject, "done": done, "errors": errors,
            "state": state, "status_label": label, "practice_ready": ready})
    return {"id": session["id"], "mode": session["mode"], "ended_at": session.get("ended_at"),
        "items": items, "counts": totals, "typo_corrections": session.get("overrides", 0),
        "practice_ids": practice_ids, "mistake_ids": mistake_ids,
        "local_only": True, "demo": engine.demo}
