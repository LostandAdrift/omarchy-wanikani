"""Read-only, bounded views of confirmed WaniKani learning progress.

``overview(engine)`` combines the small current-level and SRS summaries.
``level_board(engine, level=None, subject_type=None, offset=0, limit=60)``
returns a page of safe subject cards with prerequisite status. ``subject_status``
provides personal dates and answer counts without exposing a subject's answers.
No function changes sessions, assignments, outbox records, or local history.
"""
import json
import math
import unicodedata

from .common import UserError, epoch, plain, stamp


TYPES = ("radical", "kanji", "vocabulary", "kana_vocabulary")
KINDS = "('radical','kanji','vocabulary','kana_vocabulary')"
MAX_CATALOGUE = 12000
MAX_LEVEL_SUBJECTS = 1000
MAX_PREREQUISITES = 60
UNRESOLVED = "('pending','inflight','uncertain','blocked','conflicted')"
STAGES = {0: ("not_started", "Not started"), 1: ("apprentice", "Apprentice 1"),
    2: ("apprentice", "Apprentice 2"), 3: ("apprentice", "Apprentice 3"),
    4: ("apprentice", "Apprentice 4"), 5: ("guru", "Guru 1"),
    6: ("guru", "Guru 2"), 7: ("master", "Master"),
    8: ("enlightened", "Enlightened"), 9: ("burned", "Burned")}
GROUPS = (("locked", "Locked"), ("lessons", "Lesson ready"),
    ("apprentice", "Apprentice"), ("guru", "Guru"), ("master", "Master"),
    ("enlightened", "Enlightened"), ("burned", "Burned"), ("unknown", "Unknown"))
DATES = ("unlocked_at", "started_at", "available_at", "passed_at", "burned_at")
VALID_DATES = " AND ".join("(json_type(a.body,'$.data." + name
    + "') IS NULL OR json_type(a.body,'$.data." + name + "') IN ('text','null'))" for name in DATES)


def _text(value, maximum=160):
    value = plain(value) if isinstance(value, str) else ""
    return "".join(c for c in value if not unicodedata.category(c).startswith("C"))[:maximum].strip()


def _date(value, now, past=False):
    try:
        parsed = epoch(value) if isinstance(value, str) and len(value) <= 80 else None
        return stamp(parsed) if parsed is not None and math.isfinite(parsed) and (not past or parsed <= now) else None
    except (OverflowError, OSError, ValueError):
        return None


def _level(engine, value=None):
    value = engine.user().get("level") if value is None else value
    if type(value) is not int or not 1 <= value <= 60:
        raise UserError("Choose a WaniKani level from 1 to 60.")
    return value


def _markers(engine, level, include_progressions=False):
    if engine.demo:
        return True
    maximum = engine.store.get("cached_max_level")
    keys = ["cursor_subjects", "cursor_assignments"]
    if include_progressions:
        keys.append("cursor_level_progressions")
    return (type(maximum) is int and maximum >= level
        and not engine.clock_untrusted
        and all(_date(engine.store.get(key), engine.now(), past=True) for key in keys))


def _field(name):
    return ("CASE WHEN json_type(a.body,'$.data." + name + "')='text' "
        "THEN substr(json_extract(a.body,'$.data." + name + "'),1,80) END AS " + name)


# Grouping prevents malformed duplicate assignments from multiplying subjects.
# Their ambiguous progress is marked unknown rather than choosing a baseline.
PROJECTION = """SELECT CAST(s.id AS INTEGER) AS id,s.kind AS type,
    json_extract(s.body,'$.data.level') AS level,
    CASE WHEN json_type(s.body,'$.id')='integer' AND json_extract(s.body,'$.id')=CAST(s.id AS INTEGER)
      AND json_extract(s.body,'$.object')=s.kind THEN 1 ELSE 0 END AS valid_identity,
    COUNT(a.id) AS assignment_count,
    CASE WHEN a.id IS NULL OR (json_extract(a.body,'$.object')='assignment'
      AND json_type(a.body,'$.id')='integer' AND json_extract(a.body,'$.id')=CAST(a.id AS INTEGER)
      AND json_type(a.body,'$.data.subject_id')='integer'
      AND """ + VALID_DATES + """
      ) THEN 1 ELSE 0 END AS valid_assignment,
    CASE WHEN json_type(a.body,'$.data.srs_stage')='integer'
      THEN json_extract(a.body,'$.data.srs_stage') END AS srs_stage,
    """ + ",".join(_field(name) for name in DATES)
JOINS = """ FROM resources s INDEXED BY resource_search_identity
    LEFT JOIN resources a INDEXED BY resource_subject ON a.kind='assignment'
      AND json_extract(a.body,'$.data.subject_id')=CAST(s.id AS INTEGER)
    WHERE s.kind IN """ + KINDS + """
      AND json_type(s.body,'$.data.level')='integer'
      AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
      AND json_extract(s.body,'$.data.hidden_at') IS NULL
      AND (a.id IS NULL OR json_type(a.body,'$.data.hidden') IS NULL
        OR json_type(a.body,'$.data.hidden') IN ('false','null'))"""
CONTENT = """,
    CASE WHEN json_type(s.body,'$.data.characters')='text'
      THEN substr(json_extract(s.body,'$.data.characters'),1,128) ELSE '' END AS characters,
    (SELECT substr(json_extract(m.value,'$.meaning'),1,300)
      FROM json_each(CASE WHEN json_type(s.body,'$.data.meanings')='array'
        THEN json_extract(s.body,'$.data.meanings') ELSE '[]' END) m
      WHERE m.type='object' AND json_type(m.value,'$.accepted_answer')='true'
        AND json_type(m.value,'$.meaning')='text'
      ORDER BY json_type(m.value,'$.primary')='true' DESC LIMIT 1) AS meaning,
    (SELECT json_group_array(value) FROM (SELECT CASE WHEN type='integer' THEN value END AS value FROM json_each(
      CASE WHEN json_type(s.body,'$.data.component_subject_ids')='array'
        THEN json_extract(s.body,'$.data.component_subject_ids') ELSE '[]' END)
      LIMIT 61)) AS components,
    CASE WHEN json_type(s.body,'$.data.component_subject_ids') IS NULL
      OR json_type(s.body,'$.data.component_subject_ids')='array' THEN 1 ELSE 0 END AS components_valid"""


def _rows(engine, condition="", args=(), *, limit=MAX_CATALOGUE + 1, offset=0, content=False):
    sql = PROJECTION + (CONTENT if content else "") + JOINS + condition
    sql += " GROUP BY s.kind,s.id ORDER BY CAST(s.id AS INTEGER),s.kind LIMIT ? OFFSET ?"
    return [dict(row) for row in engine.store.rows(sql, (engine.max_level(), *args, limit, offset))]


def _valid(row):
    return bool(row["valid_identity"] and row["valid_assignment"] and row["id"] > 0 and row["assignment_count"] <= 1)


def _pending(engine, ids):
    result = {}
    for offset in range(0, len(ids), 128):
        batch = ids[offset:offset + 128]
        if not batch:
            continue
        for row in engine.store.rows("""SELECT subject_id,
          MAX(CASE WHEN state IN ('uncertain','blocked','conflicted') THEN 2 ELSE 1 END) AS priority,
          COUNT(*) AS count,
          SUM(state IN ('pending','inflight')) AS waiting,
          SUM(state IN ('uncertain','blocked','conflicted')) AS attention FROM outbox INDEXED BY outbox_state
          WHERE state IN """ + UNRESOLVED + """ AND kind IN ('review','lesson')
          AND subject_id IN (""" + ",".join("?" for _ in batch) + ") GROUP BY subject_id", batch):
            result[row[0]] = {"state": "attention" if row[1] == 2 else "pending", "count": row[2],
                "pending_count": row[3], "attention_count": row[4]}
    return result


def _status(row, now, pending=None):
    valid = _valid(row)
    dates = {name: _date(row[name], now, past=name != "available_at") if valid else None
        for name in ("unlocked_at", "started_at", "available_at", "passed_at", "burned_at")}
    stage = row["srs_stage"] if valid and type(row["srs_stage"]) is int else None
    if valid and row["assignment_count"]:
        ordered = [dates[name] for name in ("unlocked_at", "started_at", "passed_at", "burned_at") if dates[name]]
        invalid_dates = any(row[name] is not None and dates[name] is None for name in dates)
        invalid_dates = invalid_dates or any(epoch(left) > epoch(right) for left, right in zip(ordered, ordered[1:]))
        if invalid_dates:
            valid = False
            dates = dict.fromkeys(dates)
            stage = None
    if not valid or (row["assignment_count"] and stage not in STAGES):
        group, label = "unknown", "Refresh progress"
    elif dates["burned_at"]:
        group, label = "burned", "Burned"
    elif not dates["started_at"]:
        group, label = ("lessons", "Lesson ready") if dates["unlocked_at"] else ("locked", "Locked")
    else:
        group, label = STAGES.get(stage, ("unknown", "Refresh progress"))
        if stage == 0:
            group, label = "unknown", "Refresh progress"
    next_review = dates["available_at"] if dates["started_at"] and not dates["burned_at"] else None
    state = (pending or {}).get("state")
    return {"stage": stage, "stage_name": label, "group": group,
        **dates, "next_review_at": next_review,
        "due": bool(next_review and epoch(next_review) <= now),
        "passed": dates["passed_at"] is not None, "pending": state == "pending",
        "attention": state == "attention", "pending_operations": (pending or {}).get("count", 0),
        "label": "Needs attention" if state == "attention" else "Waiting to sync" if state == "pending" else label}


def _progression(engine, level, now):
    rows = engine.store.rows("""SELECT
      json_extract(body,'$.data.unlocked_at') AS unlocked,
      json_extract(body,'$.data.passed_at') AS passed,
      json_extract(body,'$.data.abandoned_at') AS abandoned
      FROM resources INDEXED BY resource_level WHERE kind='level_progression'
        AND json_type(body,'$.data.level')='integer' AND json_extract(body,'$.data.level')=?
      ORDER BY julianday(json_extract(body,'$.data.unlocked_at')) DESC,CAST(id AS INTEGER) DESC LIMIT 1""", (level,))
    if not rows or rows[0]["abandoned"] is not None:
        return None, None
    return _date(rows[0]["unlocked"], now, past=True), _date(rows[0]["passed"], now, past=True)


def current_level(engine):
    """Confirmed first passing toward the current level's 90% threshold."""
    with engine.store.lock:
        now = engine.now()
        level = engine.user().get("level", 0)
        accessible = type(level) is int and 1 <= level <= engine.max_level()
        rows = _rows(engine, " AND s.kind='kanji' AND json_extract(s.body,'$.data.level')=?", (level,),
            limit=MAX_LEVEL_SUBJECTS + 1) if accessible else []
        truncated = len(rows) > MAX_LEVEL_SUBJECTS
        rows = rows[:MAX_LEVEL_SUBJECTS]
        complete = bool(accessible and rows and not truncated
            and all(_valid(row) and _status(row, now)["group"] != "unknown" for row in rows)
            and _markers(engine, level, include_progressions=True))
        passed = sum(bool(_status(row, now)["passed"]) for row in rows)
        required = (len(rows) * 9 + 9) // 10 if complete else None
        pending = _pending(engine, [row["id"] for row in rows])
        unlocked, server_passed = _progression(engine, level, now) if accessible else (None, None)
        final = level == 60
        message = ("Connect your account to see level progress." if not engine.user() else
            "Current-level content is outside your account access." if not accessible else
            "Refresh to finish caching this level's confirmed progress." if not complete else
            "Final level passing target reached." if final and passed >= required else
            "Passing target reached; WaniKani confirms level advancement." if passed >= required else
            str(max(0, required - passed)) + " more kanji to pass" + (" on the final level." if final else " to reach the level-up target."))
        return {"level": level, "accessible": accessible, "complete": complete, "total": len(rows),
            "passed": passed, "required": required, "remaining": max(0, required - passed) if complete else None,
            "fraction": min(1.0, passed / required) if complete and required else None,
            "threshold_met": passed >= required if complete else None, "final_level": final,
            "level_passed_at": server_passed, "unlocked_at": unlocked,
            "elapsed_days": max(0, int((now - epoch(unlocked)) // 86400)) if unlocked else None,
            "pending": sum(item["pending_count"] for item in pending.values()),
            "attention": sum(item["attention_count"] for item in pending.values()),
            "message": message}


def distribution(engine):
    """Current SRS, separate from first passing and local pending work."""
    with engine.store.lock:
        rows = _rows(engine)
        complete = len(rows) <= MAX_CATALOGUE and _markers(engine, engine.max_level())
        rows = rows[:MAX_CATALOGUE]
        groups = {key: {"key": key, "label": label, "count": 0, "types": dict.fromkeys(TYPES, 0)} for key, label in GROUPS}
        now = engine.now()
        for row in rows:
            if not row["valid_identity"]:
                complete = False
                continue
            state = _status(row, now)
            complete = complete and _valid(row) and state["group"] != "unknown"
            group = groups.get(state["group"], groups["unknown"])
            group["count"] += 1
            group["types"][row["type"]] += 1
        return {"complete": bool(complete), "total": sum(group["count"] for group in groups.values()),
            "groups": list(groups.values()), "scope": "Accessible cached subjects; confirmed current assignments"}


def _accuracy(engine, subject_id):
    rows = engine.store.rows("""SELECT """ + ",".join("CASE WHEN json_type(body,'$.data." + part + "_" + outcome + "')='integer' THEN json_extract(body,'$.data." + part + "_" + outcome + "') END AS " + part + "_" + outcome
        for part in ("meaning", "reading") for outcome in ("correct", "incorrect")) + """
      FROM resources INDEXED BY resource_subject WHERE kind='review_statistic'
        AND json_extract(body,'$.data.subject_id')=?
        AND (json_type(body,'$.data.hidden') IS NULL OR json_type(body,'$.data.hidden') IN ('false','null'))
      ORDER BY CAST(id AS INTEGER) DESC LIMIT 2""", (subject_id,))
    output = {}
    for part in ("meaning", "reading"):
        correct = rows[0][part + "_correct"] if len(rows) == 1 else None
        incorrect = rows[0][part + "_incorrect"] if len(rows) == 1 else None
        valid = type(correct) is int and type(incorrect) is int and min(correct, incorrect) >= 0
        total = correct + incorrect if valid else None
        output[part] = {"correct": correct if valid else None, "incorrect": incorrect if valid else None,
            "total": total, "percent": round(correct * 100 / total, 1) if total else None}
    return output


def subject_status(engine, subject_id):
    with engine.store.lock:
        if type(subject_id) is not int or subject_id <= 0:
            raise UserError("Choose a valid subject.")
        rows = _rows(engine, " AND CAST(s.id AS INTEGER)=?", (subject_id,), limit=2)
        if len(rows) != 1 or not rows[0]["valid_identity"]:
            raise UserError("This subject is outside your current WaniKani access.", "access_restricted")
        return {"id": subject_id, **_status(rows[0], engine.now(), _pending(engine, [subject_id]).get(subject_id)),
            "accuracy": _accuracy(engine, subject_id), "source": "cached_wanikani"}


def _protected(engine):
    # Read all unfinished graded sessions, including separate paused lesson and
    # review references. A damaged or oversized scan withholds every open link.
    from .trail import _protected as unfinished
    ids = unfinished(engine)
    if ids is None:
        return None, set()
    characters = set()
    ordered = sorted(ids)
    for offset in range(0, len(ordered), 128):
        batch = ordered[offset:offset + 128]
        rows = engine.store.rows("""SELECT substr(json_extract(body,'$.data.characters'),1,129)
          FROM resources INDEXED BY resource_numeric_id WHERE kind IN """ + KINDS + """
            AND CAST(id AS INTEGER) IN (""" + ",".join("?" for _ in batch) + """ )
            AND json_type(body,'$.id')='integer' AND json_extract(body,'$.id')=CAST(id AS INTEGER)
            AND json_extract(body,'$.object')=kind AND json_type(body,'$.data.level')='integer'
            AND json_extract(body,'$.data.level') BETWEEN 1 AND ?
            AND json_extract(body,'$.data.hidden_at') IS NULL
            AND json_type(body,'$.data.characters')='text' LIMIT 513""", (*batch, engine.max_level()))
        if len(rows) > 512 or any(len(row[0]) > 128 for row in rows):
            return None, set()
        characters.update(row[0] for row in rows if row[0])
    return ids, characters


def _card(row, now, pending, protected, characters):
    hidden = protected is None or row["id"] in protected or bool(row["characters"] and row["characters"] in characters)
    return {"id": row["id"], "type": row["type"], "level": row["level"],
        "characters": row["characters"], "meaning": "" if hidden else _text(row["meaning"]),
        "can_open": not hidden and _valid(row), "spoilers_hidden": hidden,
        "status": _status(row, now, pending.get(row["id"])), "prerequisites": [], "prerequisites_complete": True}


def level_board(engine, level=None, subject_type=None, offset=0, limit=60):
    """Page through an accessible level, including known prerequisite dates."""
    with engine.store.lock:
        level = _level(engine, level)
        if level > engine.max_level():
            raise UserError("This level is outside your current WaniKani access.", "access_restricted")
        if subject_type is not None and subject_type not in TYPES:
            raise UserError("Choose radicals, kanji, vocabulary, or kana vocabulary.")
        if type(offset) is not int or type(limit) is not int or not 0 <= offset <= MAX_LEVEL_SUBJECTS or not 1 <= limit <= 60:
            raise UserError("Choose a page of 1 to 60 subjects.")
        condition = " AND json_extract(s.body,'$.data.level')=?"
        args = [level]
        if subject_type:
            condition += " AND s.kind=?"
            args.append(subject_type)
        # Bound level metadata independently of pagination. Never hydrate full
        # mnemonics/audio/notes just to count or display these cards.
        metadata = _rows(engine, condition, args, limit=MAX_LEVEL_SUBJECTS + 1)
        total_complete = len(metadata) <= MAX_LEVEL_SUBJECTS
        rows = _rows(engine, condition, args, limit=min(limit, max(0, MAX_LEVEL_SUBJECTS - offset)), offset=offset, content=True)
        rows = [row for row in rows if row["valid_identity"]]
        ids = [row["id"] for row in rows]
        prerequisite_ids = set()
        for row in rows:
            entries = json.loads(row["components"])
            row["component_ids"] = list(dict.fromkeys(value for value in entries if type(value) is int and value > 0))[:MAX_PREREQUISITES]
            row["components_complete"] = bool(row["components_valid"] and len(entries) <= MAX_PREREQUISITES
                and all(type(value) is int and value > 0 for value in entries))
            prerequisite_ids.update(row["component_ids"])
        relatives = {}
        ordered = sorted(prerequisite_ids)
        for start in range(0, len(ordered), 128):
            batch = ordered[start:start + 128]
            for row in _rows(engine, " AND CAST(s.id AS INTEGER) IN (" + ",".join("?" for _ in batch) + ")", batch, limit=128, content=True):
                if row["valid_identity"]:
                    relatives[row["id"]] = row
        pending = _pending(engine, list(set(ids) | prerequisite_ids))
        protected, characters = _protected(engine)
        now = engine.now()
        items = []
        for row in rows:
            card = _card(row, now, pending, protected, characters)
            # Protected cards do not reveal their prerequisite graph either.
            if not card["spoilers_hidden"]:
                for sid in row["component_ids"]:
                    if sid not in relatives:
                        card["prerequisites_complete"] = False
                        continue
                    relative = _card(relatives[sid], now, pending, protected, characters)
                    relative["required"] = not relative["status"]["passed"]
                    card["prerequisites"].append(relative)
                card["prerequisites_complete"] = card["prerequisites_complete"] and row["components_complete"]
            items.append(card)
        total = min(len(metadata), MAX_LEVEL_SUBJECTS)
        return {"level": level, "subject_type": subject_type, "offset": offset, "limit": limit,
            "total": total, "total_complete": total_complete,
            "complete": bool(total_complete and all(_valid(row) and _status(row, now)["group"] != "unknown" for row in metadata) and _markers(engine, level)),
            "items": items, "has_more": offset + limit < total,
            "next_offset": offset + limit if offset + limit < total else None,
            "protection_complete": protected is not None, "source": "cached_wanikani"}


def overview(engine):
    with engine.store.lock:
        return {"current": current_level(engine), "distribution": distribution(engine),
            "last_sync": engine.store.get("last_sync"), "source": "cached_wanikani"}
