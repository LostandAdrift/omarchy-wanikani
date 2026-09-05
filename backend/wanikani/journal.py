"""Reproject a durable command acknowledgment without repeating its effect.

The original session identity, revision and grading outcome remain historical.
Subject presentation is read through current account access and material state,
so replay cannot resurrect restricted content or an obsolete personal note.
Only the reply's one subject is loaded; no session/history/catalogue scan occurs.
"""
from .common import UserError, accessible_subject
from .grading import validate_subject_answers


def _details(engine, value):
    subject_id = value.get("id")
    if type(subject_id) is not int or subject_id < 1:
        raise UserError("This completed request's subject is no longer accessible.", "access_restricted")
    subject = engine.store.subject(subject_id)
    if not accessible_subject(subject, engine.max_level()):
        raise UserError("This request already completed. Its subject is outside your current WaniKani access.", "access_restricted")
    return subject, engine.details(subject_id)


def restricted_session(value):
    """Hide display text while leaving the saved session and outcome intact."""
    result = {**value, "subject": None, "restricted": True, "draft": ""}
    if isinstance(value.get("feedback"), dict):
        result["feedback"] = {**value["feedback"], "accepted": [], "answer": ""}
    return result


def replay(engine, value):
    if not isinstance(value, dict):
        return value
    # Match the stored response shape, not the new request's claimed method.
    # A request ID reused with different arguments must still be deduplicated.
    if "subject" in value and "phase" in value and "mode" in value:
        old_subject = value.get("subject")
        if old_subject is None:
            # Older versions retained feedback text in an already-restricted
            # view. Completed/unavailable replies must not pick a new session.
            return restricted_session(value) if value.get("restricted") else value
        result = dict(value)
        try:
            if not isinstance(old_subject, dict):
                raise UserError("The saved subject is unavailable.", "access_restricted")
            subject, detail = _details(engine, old_subject)
        except UserError as error:
            if error.code != "access_restricted":
                raise
            return restricted_session(value)
        result["subject"] = detail
        feedback = value.get("feedback")
        if isinstance(feedback, dict) and feedback.get("accepted"):
            # Keep the historical verdict, but don't redisplay a removed
            # synonym or reading as an accepted answer after material changes.
            try:
                prepared = validate_subject_answers(subject, detail.get("material"))
                allowed = set(prepared["readings" if value.get("part") == "reading" else "meanings"])
            except UserError:
                allowed = set()
            accepted = feedback["accepted"] if isinstance(feedback["accepted"], list) else []
            result["feedback"] = {**feedback,
                "accepted": [answer for answer in accepted[:64] if isinstance(answer, str) and answer in allowed]}
        return result
    if "id" in value and "type" in value:
        # Pin, save material and discard editor return subject details directly.
        # If access ended, return a normal error while retaining the durable ID.
        return _details(engine, value)[1]
    return value  # Small settings/draft acknowledgments contain no subject text.
