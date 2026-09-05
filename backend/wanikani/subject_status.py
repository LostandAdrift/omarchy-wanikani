"""Small cached status projection for explicit Lookup surfaces only.

No answer text, history, media, or network reads. The ID predicate precedes
grouping; selected search rows share the same bounded metadata/outbox reads.
"""
from . import progress


def project(engine, subject_ids):
    if not isinstance(subject_ids, (list, tuple)) or not 1 <= len(subject_ids) <= 100 or any(
            type(sid) is not int or not 1 <= sid <= 9007199254740991 for sid in subject_ids):
        return {}
    ids = list(dict.fromkeys(subject_ids))
    with engine.store.lock:
        # Four supported kinds can share a malformed numeric identity. Raw
        # legacy rows may also spell that identity differently (e.g. 2/02).
        # A sentinel beyond the normal kind bound detects an incomplete scan;
        # never interpret its final partial group as a unique assignment.
        row_limit = 4 * len(ids) + 1
        rows = progress._rows(engine, " AND CAST(s.id AS INTEGER) IN (" + ",".join("?" for _ in ids) + ")",
            tuple(ids), limit=row_limit)
        truncated = len(rows) >= row_limit
        grouped = {}
        for row in rows:
            grouped.setdefault(row["id"], []).append(row)
        pending = progress._pending(engine, ids)
        result = {}
        for sid in ids:
            selected = grouped.get(sid, [])
            if not truncated and len(selected) == 1:
                state = progress._status(selected[0], engine.now(), pending.get(sid))
            else:
                queue = pending.get(sid, {})
                state = {"stage": None, "stage_name": "Refresh progress", "group": "unknown",
                    "pending": queue.get("state") == "pending", "attention": queue.get("state") == "attention"}
            result[sid] = {key: state[key] for key in ("stage", "stage_name", "group", "pending", "attention")}
        return result
