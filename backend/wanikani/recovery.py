"""Bounded read-only views of local submissions; this module never replays work.

Protocol method ``recovery`` accepts state (open/attention/individual state/all),
kind (all/review/lesson/material), offset, and limit (1–100). Returned pages keep
stable created_at/id ordering. Counts describe local records, not account-wide
review history. Restricted subject content and study-material bodies are never
included. The existing resolve/keep_remote action remains the only archive path.
"""
from .common import UserError, accessible_subject, plain


STATES = ("pending", "inflight", "uncertain", "conflicted", "blocked", "confirmed", "discarded")
OPEN = ("pending", "inflight", "uncertain", "conflicted", "blocked")
ATTENTION = ("uncertain", "conflicted", "blocked")
KINDS = ("review", "lesson", "material")
PREVIEW_LIMIT = 12

RATIONALES = {
    "pending": "Saved locally and awaiting confirmation. Refresh checks current account and assignment progress before sending.",
    "inflight": "A request is being sent. Wait for synchronization to finish; an interrupted response may leave its outcome uncertain.",
    "uncertain": "WaniKani may have received this request. Refresh checks remote progress; automatic replay is disabled. Check remote progress before archiving.",
    "conflicted": "Remote progress changed or the server rejected this result. The local record is retained and will not be replayed. Refresh before archiving.",
    "blocked": "Account access or API permissions need attention. Reconnect or restore access, then refresh and check remote progress before archiving.",
    "confirmed": "WaniKani confirmed this result. A committed review cannot be changed through local recovery.",
    "discarded": "You archived this record locally and kept remote progress. Archiving does not submit or change a WaniKani review.",
}
DEMO_RATIONALES = {
    "pending": "Saved locally in demonstration mode. Refresh simulates confirmation; nothing is sent to WaniKani.",
    "inflight": "A demonstration operation is in progress. No account request is sent.",
    "uncertain": "This demonstration result has an uncertain local outcome. Refresh before archiving; no account request is sent.",
    "conflicted": "This demonstration result has a local conflict and is retained for inspection. No account progress changed.",
    "blocked": "This demonstration result needs local attention. No account request is sent.",
    "confirmed": "Confirmed locally in demonstration mode. Nothing was sent to WaniKani.",
    "discarded": "This demonstration record was archived locally. No account progress changed.",
}


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise UserError(name + " must be a whole number between " + str(minimum) + " and " + str(maximum) + ".")
    return value


def counts(store):
    result = dict.fromkeys(STATES, 0)
    for row in store.rows("SELECT state,COUNT(*) AS count FROM outbox GROUP BY state"):
        if row["state"] in result:
            result[row["state"]] = row["count"]
    return result


def _totals(by_state):
    return {"open_total": sum(by_state[state] for state in OPEN),
        "pending": sum(by_state[state] for state in ("pending", "inflight", "blocked")),
        "attention": sum(by_state[state] for state in ATTENTION)}


def _accessible(subject, maximum):
    return accessible_subject(subject, maximum)


def _detail(row, accessible):
    return plain(row["detail"])[:800] if accessible else "Subject content is unavailable at your current account access."


def _page_rows(store, selected, kind, limit, offset=0, errors=False):
    columns = ",".join("o." + key for key in ("id", "kind", "subject_id", "state", "detail", "created_at"))
    if errors:
        columns += ",json_extract(o.body,'$.errors.meaning') AS meaning_errors,json_extract(o.body,'$.errors.reading') AS reading_errors"
    # Each state has its own ordered index range. Merge at most one page per
    # state instead of loading/sorting every open row (and its possibly large
    # study-material body) merely to show the first 12 or 30 results.
    queries, parameters = [], []
    multiple = selected and len(selected) > 1
    for state in selected or (None,):
        conditions = []
        if state:
            conditions.append("state=?")
            parameters.append(state)
        if kind != "all":
            conditions.append("kind=?")
            parameters.append(kind)
        where = " AND ".join(conditions) or "1"
        query = "SELECT id,created_at FROM outbox WHERE " + where + " ORDER BY created_at,id LIMIT ?"
        parameters.append(offset + limit if multiple else limit)
        if not multiple:
            query += " OFFSET ?"
            parameters.append(offset)
        queries.append("SELECT * FROM (" + query + ")")
    identifiers = " UNION ALL ".join(queries)
    if multiple:
        identifiers = "SELECT * FROM (" + identifiers + ") ORDER BY created_at,id LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
    # Fetch payload fields only after page membership is fixed. Deep offsets
    # walk compact index entries, never parse thousands of historical bodies.
    sql = "SELECT " + columns + " FROM (" + identifiers + ") p JOIN outbox o ON o.id=p.id ORDER BY p.created_at,p.id"
    return store.rows(sql, parameters)


def snapshot_summary(engine):
    """Aggregate all states in SQL and return a small compatible open preview."""
    by_state = counts(engine.store)
    totals = _totals(by_state)
    rows = _page_rows(engine.store, OPEN, "all", PREVIEW_LIMIT)
    maximum = engine.max_level()
    preview = []
    for row in rows:
        item = {key: row[key] for key in ("id", "kind", "subject_id", "state", "created_at")}
        item["detail"] = _detail(row, _accessible(engine.store.subject(row["subject_id"]), maximum))
        preview.append(item)
    return {"outbox_counts": by_state, "outbox_total": totals["open_total"], "outbox": preview,
        "outbox_has_more": totals["open_total"] > len(preview), "pending": totals["pending"], "attention": totals["attention"]}


def _protected_subjects(engine):
    # The two durable pointers bound this check independently of accumulated
    # completed sessions. Graded sessions cannot be replaced by this interface.
    protected = set()
    references = {engine.store.get("graded_session"), engine.store.get("active_session")}
    for reference in references - {None}:
        session = engine.store.session(reference)
        if session and session.get("mode") != "practice" and session.get("phase") != "complete":
            protected.update(item["subject_id"] for item in session.get("queue", [])[:20] if not item.get("done"))
    return protected


def _subject(engine, subject_id, maximum, protected):
    subject = engine.store.subject(subject_id)
    accessible = _accessible(subject, maximum)
    result = {"id": subject_id, "label": "Subject " + str(subject_id), "characters": "", "meaning": "",
        "type": "", "level": None, "accessible": accessible, "spoilers_hidden": subject_id in protected}
    if accessible:
        data = subject["data"]
        characters = plain(data.get("characters"))[:64] if isinstance(data.get("characters"), str) else ""
        entries = data.get("meanings")
        meanings = [m for m in entries if isinstance(m, dict) and m.get("accepted_answer") is True
            and isinstance(m.get("meaning"), str)] if isinstance(entries, list) else []
        primary = next((m for m in meanings if m.get("primary") is True), meanings[0] if meanings else {})
        meaning = "" if result["spoilers_hidden"] else plain(primary.get("meaning"))[:160]
        result.update(type=subject["object"], characters=characters, meaning=meaning, level=data["level"],
            label=characters or ("Image radical" if subject["object"] == "radical" else result["label"]))
    return result


def _actions(state, demo=False):
    output = []
    if state in ("pending", "uncertain", "conflicted", "blocked"):
        output.append({"id": "refresh", "label": "Refresh demonstration results" if demo else "Refresh remote progress",
            "description": "Simulate local confirmation. Nothing is sent to WaniKani." if demo else
                "Check WaniKani before making a recovery decision. Uncertain writes are never automatically retried."})
    if state in ATTENTION:
        output.append({"id": "keep_remote", "label": "Archive demonstration result" if demo else "Keep remote progress and archive locally",
            "description": "Keep this demonstration record in the local archive. No account progress changes." if demo else
                "Refresh first. This preserves the local record, archives it, and never resubmits it or changes remote progress."})
    return output


def catalogue(engine, state="open", kind="all", offset=0, limit=30):
    if state not in (*STATES, "open", "attention", "all"):
        raise UserError("Choose a known submission state.")
    if kind not in (*KINDS, "all"):
        raise UserError("Choose reviews, lessons, study material, or all kinds.")
    offset = _integer(offset, "Offset", 0, 1000000)
    limit = _integer(limit, "Page size", 1, 100)
    filters, parameters = [], []
    selected = OPEN if state == "open" else ATTENTION if state == "attention" else (state,)
    if state != "all":
        filters.append("state IN (" + ",".join("?" for _ in selected) + ")")
        parameters.extend(selected)
    if kind != "all":
        filters.append("kind=?")
        parameters.append(kind)
    where = " AND ".join(filters) or "1"
    by_state = counts(engine.store)
    total = engine.store.rows("SELECT COUNT(*) FROM outbox WHERE " + where, parameters)[0][0]
    # Select only the error counters from durable bodies. Notes, answers, account
    # identifiers, and baseline payloads do not enter the recovery read model.
    rows = _page_rows(engine.store, selected if state != "all" else None, kind, limit, offset, errors=True)
    maximum, protected = engine.max_level(), _protected_subjects(engine)
    items = []
    for row in rows:
        subject = _subject(engine, row["subject_id"], maximum, protected)
        errors = None
        if row["kind"] in ("review", "lesson") and all(type(row[key]) is int and row[key] >= 0 for key in ("meaning_errors", "reading_errors")):
            errors = {"meaning": row["meaning_errors"], "reading": row["reading_errors"],
                "total": row["meaning_errors"] + row["reading_errors"]}
        items.append({"id": row["id"], "kind": row["kind"], "subject_id": row["subject_id"],
            "state": row["state"], "created_at": row["created_at"], "detail": _detail(row, subject["accessible"]),
            "errors": errors, "subject": subject,
            "rationale": (DEMO_RATIONALES if engine.demo else RATIONALES).get(row["state"], "Retained local record; refresh before recovery."),
            "actions": _actions(row["state"], engine.demo)})
    next_offset = offset + len(items)
    has_more = next_offset < total
    return {"items": items, "total": total, "offset": offset, "limit": limit,
        "has_more": has_more, "next_offset": next_offset if has_more else None,
        "state": state, "kind": kind, "counts": by_state, **_totals(by_state)}
