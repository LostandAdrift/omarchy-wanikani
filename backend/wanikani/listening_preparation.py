"""Explicit cache preparation for five listening words; no study mutations.

availability(engine) is a neutral, read-only visible-preflight projection.
prepare(sync, *, cancelled, progress) runs on the worker's audio job thread.
No caller-selected subjects/URLs, playable URI, exposure or session creation.
"""
from . import listening
from .common import UserError


MESSAGES = {
    "ready": "These recordings are ready. Start listening when you choose.",
    "needs_download": "Prepare missing recordings, then choose Start listening.",
    "saved_session": "Resume your saved listening session before preparing another batch.",
    "offline": "These recordings are not cached. Connect before preparing them.",
    "no_candidates": "No eligible familiar words were found. Check the due-soon preference or learn more vocabulary.",
    "daily_limit": "Today's new listening words are used. Return when a local word is due or on another day.",
    "incomplete": "Only part of the catalogue could be checked. These counts describe the words found.",
    "budget": "Some recordings do not fit beside required study media. Increase the cache limit or use the ready words.",
    "cancelled": "Preparation stopped. Recordings already cached remain available.",
    "permission_changed": "Study or account access changed. Check listening availability again.",
    "download_failed": "Some recordings could not be downloaded. Try again when connected.",
    "cache_cleanup": "Interrupted cache files could not be cleaned. Check available storage before trying again.",
}


def _offline(engine):
    return engine.demo or not engine.connected or engine.status == "offline"


def _availability(engine, selection):
    items = selection["items"]
    ready = sum(bool(item["clip"]["path"]) for item in items)
    missing = len(items) - ready
    reason = selection["reason"] or ("offline" if missing and _offline(engine) else "needs_download" if missing else "ready")
    return {"ready": ready, "needs_download": missing, "complete": selection["complete"],
        "reason": reason, "message": MESSAGES[reason]}


def availability(engine):
    with engine.store.lock:
        try:
            return _availability(engine, listening.preparation_candidates(engine))
        except UserError as error:
            return {"ready": 0, "needs_download": 0, "complete": False,
                "reason": error.code, "message": str(error)}


def _result(reason, *, ready=0, complete=True, cancelled=False):
    return {"status": "cancelled" if cancelled else "ready" if reason == "ready" else "unavailable",
        "downloaded": 0, "already_cached": ready, "failed": 0, "skipped_budget": 0,
        "cancelled": cancelled, "complete": complete, "reason": reason,
        "message": MESSAGES.get(reason, "Recordings could not be prepared. Check listening availability again.")}


def prepare(sync, *, cancelled=lambda: False, progress=lambda value: None):
    engine = sync.engine
    if cancelled():
        return _result("cancelled", complete=False, cancelled=True)
    with engine.store.lock:
        selection = listening.preparation_candidates(engine)
        summary = _availability(engine, selection)
        if not selection["items"]:
            return _result(summary["reason"], complete=summary["complete"])
        if not summary["needs_download"]:
            return _result("ready", ready=summary["ready"], complete=summary["complete"])
        if _offline(engine):
            return _result("offline", ready=summary["ready"], complete=False)
        # Backend-only descriptors; nothing chosen in the UI can widen this set.
        chosen = {(item["subject_id"], item["clip"]["url"]): item for item in selection["items"]}
        candidates = [{"subject_id": sid, "url": url} for sid, url in chosen]

    def permitted(candidate):
        with engine.store.lock:
            item = chosen.get((candidate.get("subject_id"), candidate.get("url")))
            return bool(item and not cancelled() and not _offline(engine)
                and listening.preparation_permitted(engine, selection["context"], item))

    # The executor builds one complete cache plan, checks permission around IO,
    # and reports only aggregate counts. Never call listening.media() here.
    outcome = sync.prepare_recordings(candidates, permitted=permitted, cancelled=cancelled, progress=progress)
    result = {key: outcome.get(key, 0) for key in ("downloaded", "already_cached", "failed", "skipped_budget")}
    result["cancelled"] = bool(outcome.get("cancelled") or cancelled())
    result["complete"] = bool(outcome.get("complete") and selection["complete"])
    with engine.store.lock:
        valid = all(permitted(candidate) for candidate in candidates) if not result["cancelled"] else False
        cached = valid and all(listening.preparation_permitted(engine, selection["context"], item,
            require_cached=True) for item in chosen.values())
    if not valid:
        result["complete"] = False
    elif not cached and not result["failed"] and not result["skipped_budget"]:
        # Counts describe successful cache operations, not current playback
        # readiness. Another owner may have trimmed files since lock release.
        result["complete"] = False
    reason = ("cancelled" if result["cancelled"] else "permission_changed" if not valid else
        "cache_cleanup" if outcome.get("reason") == "cache_cleanup" else
        "budget" if result["skipped_budget"] else "download_failed" if result["failed"] else
        "incomplete" if not result["complete"] else "ready")
    result.update({"reason": reason, "message": MESSAGES[reason], "status": "cancelled" if result["cancelled"] else
        "ready" if reason == "ready" else "partial" if result["downloaded"] or result["already_cached"] else "unavailable"})
    return result
