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
from .media_files import available_file

from .common import UserError, epoch, stamp
from .grading import validate_subject_answers


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
        FROM events INDEXED BY events_study_window WHERE kind IN ('answer','correction')
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


def _content(row, media, directory):
    images = []
    if not row["characters"]:
        image_data = json.loads(row["image_data"])
        for image in image_data if isinstance(image_data, list) else []:
            if not isinstance(image, dict) or not isinstance(image.get("url"), str):
                continue
            path = available_file(directory, media.get(image.get("url")))
            if path:
                images.append(path.as_uri())
    cache_note = "Ready offline"
    meaning = ""
    try:
        answers = json.loads(row["answers"])
        prepared = validate_subject_answers({"object": row["type"], "data": answers},
            json.loads(row["material"]) if row["material"] else None)
        meaning = next((item["meaning"] for item in answers["meanings"]
            if item.get("primary") is True and item["accepted_answer"] is True), prepared["meanings"][0])
    except UserError:
        cache_note = "Refresh to cache valid accepted answers."
    if cache_note == "Ready offline" and not row["characters"] and not images:
        cache_note = "Refresh to download the radical image."
    ready = cache_note == "Ready offline"
    return images, meaning, cache_note, ready


def catalogue(engine, group="suggested", query="", offset=0, limit=30, readiness_scope="all"):
    # Keep page identities, access and hydrated content from one local snapshot.
    # Native pages validate at most 60 subjects rather than every learned item.
    with engine.store.lock:
        return _catalogue(engine, group, query, offset, limit, readiness_scope)


def _catalogue(engine, group, query, offset, limit, readiness_scope):
    if readiness_scope not in ("all", "page"):
        raise UserError("Choose all-library or current-page offline availability.")
    page_readiness = readiness_scope == "page"
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
    content_projection = "NULL AS answers,NULL AS material,NULL AS image_data" if page_readiness else """json_object('meanings',json_extract(s.body,'$.data.meanings'),
          'readings',json_extract(s.body,'$.data.readings'),
          'auxiliary_meanings',CASE WHEN json_type(s.body,'$.data.auxiliary_meanings') IS NULL
            THEN json('[]') ELSE json_extract(s.body,'$.data.auxiliary_meanings') END) AS answers,
        CASE WHEN d.body IS NOT NULL AND json_type(d.body)!='null'
          THEN d.body ELSE json_extract(m.body,'$.data') END AS material,
        json_quote(json_extract(s.body,'$.data.character_images')) AS image_data"""
    material_joins = "" if page_readiness else """LEFT JOIN resources m ON m.kind='study_material'
        AND CAST(json_extract(m.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
      LEFT JOIN meta d ON d.key='material_draft_'||s.id"""
    rows = engine.store.rows(f"""SELECT CAST(s.id AS INTEGER) AS id,s.kind AS type,
        {content_projection},
        json_extract(s.body,'$.data.characters') AS characters,
        json_extract(s.body,'$.data.level') AS level,
        json_extract(a.body,'$.data.started_at') AS started_at,
        COALESCE(json_extract(a.body,'$.data.srs_stage'),0) AS srs_stage,
        json_extract(rs.body,'$.data.percentage_correct') AS accuracy,
        (?='' OR json_extract(s.body,'$.data.characters') LIKE ? ESCAPE '\\'
          OR EXISTS(SELECT 1 FROM json_each(CASE WHEN json_type(s.body,'$.data.meanings')='array'
              THEN json_extract(s.body,'$.data.meanings') ELSE '[]' END) m
            WHERE json_type(CASE WHEN m.type='object' THEN m.value ELSE '{{}}' END,'$.meaning')='text'
              AND json_extract(CASE WHEN m.type='object' THEN m.value ELSE '{{}}' END,'$.meaning') LIKE ? ESCAPE '\\')
          OR EXISTS(SELECT 1 FROM json_each(CASE WHEN json_type(s.body,'$.data.readings')='array'
              THEN json_extract(s.body,'$.data.readings') ELSE '[]' END) r
            WHERE json_type(CASE WHEN r.type='object' THEN r.value ELSE '{{}}' END,'$.reading')='text'
              AND json_extract(CASE WHEN r.type='object' THEN r.value ELSE '{{}}' END,'$.reading') LIKE ? ESCAPE '\\')
          OR (length(json_extract(s.body,'$.data.characters'))>0
            AND instr(?,json_extract(s.body,'$.data.characters'))>0)) AS matches
      FROM resources s LEFT JOIN resources a ON a.kind='assignment'
        AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
      {material_joins}
      LEFT JOIN resources rs ON rs.kind='review_statistic'
        AND CAST(json_extract(rs.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
        AND COALESCE(json_extract(rs.body,'$.data.hidden'),0)=0
      WHERE s.kind IN {SUBJECT_TYPES} AND json_extract(s.body,'$.data.hidden_at') IS NULL
        AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
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
        images, meaning, cache_note, ready = ([], "", "", False) if page_readiness else _content(row, media, engine.store.path.parent / "media")
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
            "meaning": "" if sid in protected else meaning, "level": row["level"],
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
        if page_readiness:
            # Only page members need answer validation and radical images.
            subject = engine.store.subject(item["id"])
            engine.ensure_access(subject)
            data = subject["data"]
            draft = engine.store.get("material_draft_" + str(item["id"]))
            material = draft if draft is not None else (engine.store.related("study_material", item["id"]) or {}).get("data")
            row = {"characters": data.get("characters"), "type": subject["object"],
                "answers": json.dumps({key: data[key] for key in ("meanings", "readings", "auxiliary_meanings") if key in data}),
                "image_data": json.dumps(data.get("character_images")),
                "material": json.dumps(material) if material is not None else None}
            images, meaning, note, ready = _content(row, media, engine.store.path.parent / "media")
            item.update(images=images, meaning="" if item["spoilers_hidden"] else meaning, cache_note=note, ready=ready)
    return {"items": page, "counts": counts, "ready_counts": None if page_readiness else ready_counts, "group": group, "query": query,
        "offset": offset, "limit": limit, "total": total, "ready_total": None if page_readiness else sum(item["ready"] for item in result),
        "readiness_scope": readiness_scope, "page_ready": sum(item["ready"] for item in page),
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
