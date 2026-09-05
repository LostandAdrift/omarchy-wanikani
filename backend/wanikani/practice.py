"""Read-only practice-library queries. No session, answer, or outbox mutations.

Integration contract
--------------------
``catalogue(engine, group='suggested', query='', offset=0, limit=30)`` is the
handler for protocol method ``practice_catalogue``. Groups are ``suggested``,
``saved``, ``mistakes``, and ``learned``. The result contains:

* ``items``: subject summaries (id/type/characters/images/meaning/level),
  ``learned``, ``pinned``, ``srs_stage``, ``ready``/``cache_note``,
  ``pending_graded``, ``spoilers_hidden``, ``reasons`` ({code, label} entries),
  ``mistakes`` ({meaning, reading, total}), and ``last_mistake_at``.
* ``counts``: accessible item counts for each group before the search filter;
  ``ready_counts``: the subset available for offline practice.
* ``group``, ``query``, ``offset``, ``limit``, ``total``, ``ready_total``,
  ``has_more`` and ``next_offset`` describe the filtered page.
* ``mistake_days`` is the local-history window, ``selection_limit`` is 20,
  ``graded_paused`` reports unfinished graded work, and ``saved_practice`` is
  a spoiler-free {id, completed, total} summary or null.

Meaning/readings are never returned for subjects in unfinished graded work.
Readings are not included in other cards either: selection is for practice,
not an answer sheet. ``validate_selection(engine, subject_ids)`` validates an
explicit 1–20-subject practice request and returns unique numeric IDs in order.

Existing Engine.start should retain its default resume behavior. Add a
``replace_practice=False`` option, accepted only for mode='practice'; when true,
validate the explicit selection and skip resuming the previous practice. Save
the new session normally, retaining the old session row. The UI presents a
separate Resume button before allowing an explicitly selected replacement.
Never use this flag to abandon, replace, or mutate graded sessions.
"""
import json
from pathlib import Path

from .common import UserError, epoch, stamp


GROUPS = ("suggested", "saved", "mistakes", "learned")
MISTAKE_DAYS = 14
SELECTION_LIMIT = 20
SUBJECT_TYPES = "('radical','kanji','vocabulary','kana_vocabulary')"
PENDING_STATES = "('pending','inflight','uncertain','blocked','conflicted')"


def _recent_mistakes(engine):
    """Exclude guarded typo corrections from the local mistake collection."""
    answers = {}
    latest = {}
    cutoff = stamp(engine.now() - MISTAKE_DAYS * 86400)
    for row in engine.store.rows("""SELECT id,session_id,subject_id,kind,created_at,body
        FROM events WHERE kind IN ('answer','correction')
        AND julianday(created_at)>=julianday(?) ORDER BY id""", (cutoff,)):
        body = json.loads(row["body"])
        part = body.get("part")
        if part not in ("meaning", "reading"):
            continue
        key = (row["session_id"], row["subject_id"], part)
        if row["kind"] == "answer":
            latest[key] = row["id"]
            if body.get("kind") == "incorrect":
                answers[row["id"]] = (row["subject_id"], part, row["created_at"])
        else:
            answers.pop(latest.get(key), None)
    result = {}
    for subject_id, part, when in answers.values():
        entry = result.setdefault(subject_id, {"meaning": 0, "reading": 0, "total": 0, "last_at": None})
        entry[part] += 1
        entry["total"] += 1
        if not entry["last_at"] or (epoch(when) or 0) > (epoch(entry["last_at"]) or 0):
            entry["last_at"] = when
    return result


def _sessions(engine):
    protected = set()
    practice = None
    # Query all durable unfinished records. Replaced practice remains historical;
    # only the active practice reference can be resumed by the library button.
    active = engine.store.get("practice_session")
    for row in engine.store.rows("SELECT body FROM sessions WHERE json_extract(body,'$.phase')!='complete'"):
        session = json.loads(row[0])
        if session["mode"] == "practice":
            if session["id"] == active:
                practice = {"id": session["id"], "completed": session["completed"],
                    "total": min(len(session["queue"]), session.get("finish_at", len(session["queue"])))}
        else:
            protected.update(item["subject_id"] for item in session["queue"] if not item["done"])
    return protected, practice


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise UserError(label + " must be a whole number.")
    return min(maximum, max(minimum, value))


def catalogue(engine, group="suggested", query="", offset=0, limit=30):
    if group not in GROUPS:
        raise UserError("Choose Suggested, Saved, Recent mistakes, or Learned.")
    if not isinstance(query, str):
        raise UserError("Search with characters, a reading, or a meaning.")
    query = query.strip()[:256]
    offset = _integer(offset, "Page offset", 0, 100000)
    limit = _integer(limit, "Page size", 1, 60)
    pinned = {sid: index for index, sid in enumerate(engine.store.get("pinned_subjects", []))}
    mistakes = _recent_mistakes(engine)
    protected, saved_practice = _sessions(engine)
    pending = {}
    for row in engine.store.rows(f"SELECT subject_id,kind FROM outbox WHERE kind IN ('review','lesson') AND state IN {PENDING_STATES}"):
        pending.setdefault(row["subject_id"], set()).add(row["kind"])
    media = {row["url"]: row["path"] for row in engine.store.rows("SELECT url,path FROM media")}
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = engine.store.rows(f"""SELECT CAST(s.id AS INTEGER) AS id,s.kind AS type,
        json_extract(s.body,'$.data.characters') AS characters,
        json_extract(s.body,'$.data.level') AS level,
        json_extract(s.body,'$.data.character_images') AS image_data,
        (SELECT json_extract(m.value,'$.meaning') FROM json_each(json_extract(s.body,'$.data.meanings')) m
          WHERE json_extract(m.value,'$.accepted_answer')=1
          ORDER BY json_extract(m.value,'$.primary') DESC LIMIT 1) AS meaning,
        EXISTS(SELECT 1 FROM json_each(json_extract(s.body,'$.data.readings')) r
          WHERE json_extract(r.value,'$.accepted_answer')=1) AS has_reading,
        json_extract(a.body,'$.data.started_at') AS started_at,
        COALESCE(json_extract(a.body,'$.data.srs_stage'),0) AS srs_stage,
        json_extract(rs.body,'$.data.percentage_correct') AS accuracy,
        (?='' OR json_extract(s.body,'$.data.characters') LIKE ? ESCAPE '\\'
          OR EXISTS(SELECT 1 FROM json_each(json_extract(s.body,'$.data.meanings')) m
            WHERE json_extract(m.value,'$.meaning') LIKE ? ESCAPE '\\')
          OR EXISTS(SELECT 1 FROM json_each(json_extract(s.body,'$.data.readings')) r
            WHERE json_extract(r.value,'$.reading') LIKE ? ESCAPE '\\')
          OR (length(json_extract(s.body,'$.data.characters'))>0
            AND instr(?,json_extract(s.body,'$.data.characters'))>0)) AS matches
      FROM resources s LEFT JOIN resources a ON a.kind='assignment'
        AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
      LEFT JOIN resources rs ON rs.kind='review_statistic'
        AND CAST(json_extract(rs.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
        AND COALESCE(json_extract(rs.body,'$.data.hidden'),0)=0
      WHERE s.kind IN {SUBJECT_TYPES} AND json_extract(s.body,'$.data.hidden_at') IS NULL
        AND json_extract(s.body,'$.data.level')<=?
        AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0""",
        (query, pattern, pattern, pattern, query, engine.max_level()))
    counts = dict.fromkeys(GROUPS, 0)
    ready_counts = dict.fromkeys(GROUPS, 0)
    result = []
    for row in rows:
        sid = row["id"]
        recent = mistakes.get(sid, {"meaning": 0, "reading": 0, "total": 0, "last_at": None})
        learned = bool(row["started_at"] or "lesson" in pending.get(sid, ()))
        saved = sid in pinned
        lower_accuracy = learned and row["accuracy"] is not None and row["accuracy"] < 90
        membership = {"saved": saved, "mistakes": recent["total"] > 0, "learned": learned,
            "suggested": saved or recent["total"] > 0 or lower_accuracy}
        if not any(membership.values()):
            continue
        images = []
        if not row["characters"]:
            for image in json.loads(row["image_data"] or "[]"):
                path = media.get(image.get("url"))
                if path and Path(path).is_file():
                    images.append(Path(path).as_uri())
        cache_note = "Ready offline"
        if not row["meaning"]:
            cache_note = "Refresh to cache accepted meanings."
        elif row["type"] in ("kanji", "vocabulary") and not row["has_reading"]:
            cache_note = "Refresh to cache accepted readings."
        elif not row["characters"] and not images:
            cache_note = "Refresh to download the radical image."
        ready = cache_note == "Ready offline"
        for name, included in membership.items():
            if included:
                counts[name] += 1
                ready_counts[name] += int(ready)
        if not membership[group] or not row["matches"]:
            continue
        reasons = []
        if saved:
            reasons.append({"code": "saved", "label": "Saved for practice"})
        if recent["total"]:
            parts = [str(recent[part]) + " " + part for part in ("meaning", "reading") if recent[part]]
            reasons.append({"code": "recent_mistakes", "label": "Recent mistakes: " + " · ".join(parts)})
        if lower_accuracy:
            reasons.append({"code": "lower_accuracy", "label": "WaniKani recorded accuracy: " + str(row["accuracy"]) + "%"})
        if sid in pending:
            reasons.append({"code": "pending_graded", "label": "Graded result waiting for synchronization or recovery"})
        if not reasons:
            reasons.append({"code": "learned", "label": "Learned subject"})
        result.append({"id": sid, "type": row["type"], "characters": row["characters"] or "", "images": images,
            "slug": "subject " + str(sid),  # neutral accessibility label for protected radical images
            "meaning": "" if sid in protected else row["meaning"] or "", "level": row["level"],
            "srs_stage": row["srs_stage"], "learned": learned, "pinned": saved, "ready": ready,
            "cache_note": cache_note, "pending_graded": sid in pending, "spoilers_hidden": sid in protected,
            "reasons": reasons, "mistakes": {part: recent[part] for part in ("meaning", "reading", "total")},
            "last_mistake_at": recent["last_at"], "_accuracy": row["accuracy"]})
    def order(item):
        exact = item["characters"] != query if query else False
        basic = (item["level"], item["id"])
        if group == "saved":
            return (exact, pinned.get(item["id"], 100000), *basic)
        if group == "mistakes":
            return (exact, -(epoch(item["last_mistake_at"]) or 0), -item["mistakes"]["total"], *basic)
        if group == "learned":
            return (exact, *basic)
        return (exact, not item["pinned"], pinned.get(item["id"], 100000), not item["mistakes"]["total"],
            -(epoch(item["last_mistake_at"]) or 0), item["_accuracy"] if item["_accuracy"] is not None else 100, *basic)
    result.sort(key=order)
    total = len(result)
    page = result[offset:offset + limit]
    for item in page:
        del item["_accuracy"]
    return {"items": page, "counts": counts, "ready_counts": ready_counts, "group": group, "query": query,
        "offset": offset, "limit": limit, "total": total, "ready_total": sum(item["ready"] for item in result),
        "has_more": offset + limit < total, "next_offset": offset + limit if offset + limit < total else None,
        "mistake_days": MISTAKE_DAYS, "selection_limit": SELECTION_LIMIT, "graded_paused": bool(protected),
        "saved_practice": saved_practice}


def validate_selection(engine, subject_ids):
    if not isinstance(subject_ids, list) or not 1 <= len(subject_ids) <= SELECTION_LIMIT:
        raise UserError("Choose between 1 and 20 subjects for ungraded practice.")
    if any(isinstance(sid, bool) or not isinstance(sid, int) or sid <= 0 for sid in subject_ids):
        raise UserError("Choose valid subject IDs from your practice library.")
    ids = list(dict.fromkeys(subject_ids))
    for sid in ids:
        subject = engine.store.subject(sid)
        engine.ensure_study_content(subject)
        assignment = engine.store.related("assignment", sid)
        if assignment and assignment["data"].get("hidden"):
            raise UserError("This subject is hidden by WaniKani and cannot enter practice.", "access_restricted")
    return ids
