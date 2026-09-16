"""Read-only, bounded local learning summaries; never account-wide history.

overview(engine, timezone=None, now=None, availability=None) returns the last
7/30 local calendar days, including today only through `now`. Activity survives
account resets in this account's database: acknowledged work still happened,
even if remote progress was later reset. Reset-invalidated unfinished batches
are not completed batches. Deletion/account-store replacement removes history.

Subject completions count cycles, not distinct subjects or answer parts. Batch
counts require an explicitly ended session (including "finish this batch").
Listening ratings exclude later local Undo events; completed listening batches
use their final surviving result time and current complete state. Corrections
are local uses of "I made a typo", never a guessed account accuracy metric.

All dates describe local activity. `current_submissions` describes the CURRENT
state of locally created operations, not dates of remote confirmations. Remote
review_statistics are deliberately absent. Answers, notes, readings, session
IDs and submission bodies never enter the result. Optional availability is a
caller-supplied aggregate, used only for navigation suggestions, never writes.
"""
from datetime import datetime, time, timedelta
import math
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .api import user_id
from .common import MAX_REVIEW_SESSION, UserError, plain, stamp
from .trail import _protected


MODES = ("reviews", "lessons", "practice")
STATES = ("pending", "inflight", "uncertain", "conflicted", "blocked", "confirmed", "discarded")
SUBJECTS = "('radical','kanji','vocabulary','kana_vocabulary')"
MAX_DIFFICULTIES = 6


def _clock(engine, now, timezone):
    now = engine.now() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or not 31536000 <= now <= 253339228800:
        raise UserError("Learning activity needs a valid current time.")
    if timezone is None:
        path = Path("/etc/localtime").resolve()
        try:
            timezone = str(path.relative_to("/usr/share/zoneinfo"))
        except ValueError:
            try:
                with path.open("rb") as handle:
                    return now, ZoneInfo.from_file(handle, key="system-local"), "system-local"
            except (OSError, ValueError) as error:
                raise UserError("The local timezone is unavailable.") from error
    if not isinstance(timezone, str) or not 1 <= len(timezone) <= 128:
        raise UserError("Choose a valid local timezone.")
    try:
        return now, ZoneInfo(timezone), timezone
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise UserError("Choose a valid local timezone.") from error


def _day_expression(column, boundaries):
    # SQLite's process-local modifier cannot take an IANA timezone. Use real
    # local-midnight boundaries so 23/25-hour DST days stay whole.
    cases, parameters = [], []
    for day, beginning, _ in reversed(boundaries):
        cases.append("WHEN " + column + ">=julianday(?) THEN ?")
        parameters.extend((stamp(beginning), day))
    return "CASE " + " ".join(cases) + " END", parameters


def _empty():
    return {"subject_completions": dict.fromkeys(MODES, 0), "sessions_completed": dict.fromkeys(MODES, 0),
        "listening_ratings": {"remembered": 0, "again": 0, "skipped": 0},
        "listening_sessions_completed": 0, "dictation_ratings": {"matched": 0, "again": 0, "skipped": 0},
        "dictation_sessions_completed": 0, "typo_corrections": 0}


def _completion_data(engine, boundaries, now, daily):
    day, values = _day_expression("julianday(created_at)", boundaries)
    rows = engine.store.rows("""SELECT """ + day + """ AS day,
      CASE WHEN kind='practice_complete' THEN 'practice' ELSE json_extract(body,'$.mode') END AS mode,
      COUNT(*) AS count FROM events WHERE kind IN ('subject_complete','practice_complete')
      AND julianday(created_at)>=julianday(?) AND julianday(created_at)<=julianday(?)
      AND typeof(subject_id)='integer' AND subject_id>0 GROUP BY day,mode""",
        (*values, stamp(boundaries[0][1]), stamp(now)))
    for row in rows:
        if row["mode"] in MODES and row["day"] in daily:
            daily[row["day"]]["subject_completions"][row["mode"]] = row["count"]
    rows = engine.store.rows("""SELECT """ + day + """ AS day, COUNT(*) AS count
      FROM events WHERE kind IN ('answer','correction') AND kind='correction'
      AND julianday(created_at)>=julianday(?) AND julianday(created_at)<=julianday(?)
      AND json_extract(body,'$.part') IN ('meaning','reading') GROUP BY day""",
        (*values, stamp(boundaries[0][1]), stamp(now)))
    for row in rows:
        if row["day"] in daily:
            daily[row["day"]]["typo_corrections"] = row["count"]


def _session_data(engine, boundaries, now, daily):
    day, values = _day_expression("julianday(json_extract(body,'$.ended_at'))", boundaries)
    rows = engine.store.rows("""SELECT """ + day + """ AS day,
      json_extract(body,'$.mode') AS mode,COUNT(*) AS count FROM sessions
      WHERE json_extract(body,'$.phase')='complete' AND json_extract(body,'$.mode') IN ('reviews','lessons','practice')
      AND julianday(json_extract(body,'$.ended_at'))>=julianday(?)
      AND julianday(json_extract(body,'$.ended_at'))<=julianday(?)
      AND julianday(json_extract(body,'$.started_at'))<=julianday(json_extract(body,'$.ended_at'))
      AND json_extract(body,'$.invalidated') IS NULL
      AND json_type(body,'$.completed')='integer' AND json_extract(body,'$.completed') BETWEEN 1 AND
        CASE WHEN json_extract(body,'$.mode')='reviews' AND json_type(body,'$.all_reviews')='true' THEN ? ELSE 20 END
      AND json_type(body,'$.queue')='array' AND json_array_length(body,'$.queue') BETWEEN 1 AND
        CASE WHEN json_extract(body,'$.mode')='reviews' AND json_type(body,'$.all_reviews')='true' THEN ? ELSE 20 END
      AND json_extract(body,'$.completed')=COALESCE(json_extract(body,'$.finish_at'),json_array_length(body,'$.queue'))
      AND NOT EXISTS (SELECT 1 FROM json_each(json_extract(sessions.body,'$.queue')) item
        WHERE item.key<json_extract(sessions.body,'$.completed')
          AND COALESCE(json_type(CASE WHEN item.type='object' THEN item.value ELSE '{}' END,'$.done'),'null')!='true')
      GROUP BY day,mode""", (*values, stamp(boundaries[0][1]), stamp(now), MAX_REVIEW_SESSION, MAX_REVIEW_SESSION))
    for row in rows:
        if row["day"] in daily:
            daily[row["day"]]["sessions_completed"][row["mode"]] = row["count"]


def _listening_data(engine, boundaries, now, daily, account, *, skill="listening"):
    # Private fixed skill names select SQL literals, never user input.
    if skill not in ("listening", "dictation"):
        raise ValueError("Unknown local audio skill")
    # Project only small event metadata in SQL. Old large answer bodies are not
    # selected; the listening-only time index also avoids walking those rows.
    cte = """WITH recent_ids AS MATERIALIZED (
      SELECT id FROM events WHERE kind IN ('listening_result','listening_undo') AND kind='listening_result'
        AND julianday(created_at)>=julianday(?)),
      event_ids AS (SELECT id FROM recent_ids UNION ALL
        SELECT id FROM events WHERE id>(SELECT MIN(id) FROM recent_ids)
          AND kind IN ('listening_result','listening_undo') AND kind='listening_undo'),
      projected AS MATERIALIZED (
      SELECT e.id,session_id,kind,julianday(created_at) AS happened,
        json_extract(body,'$.rating') AS rating,
        CASE WHEN json_type(body,'$.operation')='text'
          THEN substr(json_extract(body,'$.operation'),1,201) END AS operation
      FROM event_ids chosen JOIN events e ON e.id=chosen.id
        WHERE EXISTS (SELECT 1 FROM meta m WHERE m.key='listening_session_'||e.session_id
          AND CAST(json_extract(m.body,'$.context.account') AS TEXT)=?
          AND json_extract(m.body,'$.context.epoch')=? AND json_extract(m.body,'$.context.demo')=?)),
      final AS MATERIALIZED (SELECT r.* FROM projected r
        WHERE r.kind='listening_result' AND r.rating IN ('remembered','again','skipped')
        AND length(r.operation) BETWEEN 1 AND 200 AND r.happened IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM projected u WHERE u.kind='listening_undo'
          AND u.session_id=r.session_id AND u.operation=r.operation AND u.id>r.id
          AND u.happened<=julianday(?))) """
    if skill == "dictation":
        cte = cte.replace("listening_", "dictation_").replace("'remembered'", "'matched'")
    # Include future result dates to avoid re-dating a clock-shifted completed
    # batch to its earlier cards. Undo is selected by durable event order, not
    # its wall date: a clock correction across midnight must still undo once.
    context = (account, engine.store.get("session_epoch"), int(engine.demo))
    day, values = _day_expression("happened", boundaries)
    rows = engine.store.rows(cte + "SELECT " + day + """ AS day,rating,COUNT(*) AS count FROM final
      WHERE happened>=julianday(?) AND happened<=julianday(?) GROUP BY day,rating""",
        (stamp(boundaries[0][1]), *context, stamp(now), *values, stamp(boundaries[0][1]), stamp(now)))
    for row in rows:
        if row["day"] in daily:
            daily[row["day"]][skill + "_ratings"][row["rating"]] = row["count"]
    day, values = _day_expression("last_at", boundaries)
    session_sql = cte + """, ended AS (
        SELECT session_id,MAX(happened) AS last_at FROM final GROUP BY session_id)
      SELECT """ + day + """ AS day,COUNT(*) AS count FROM ended e JOIN meta m
        ON m.key='listening_session_'||e.session_id
      WHERE last_at>=julianday(?) AND last_at<=julianday(?)
        AND json_extract(m.body,'$.phase')='complete'
        AND json_type(m.body,'$.queue')='array' AND json_array_length(m.body,'$.queue') BETWEEN 1 AND 5
        AND json_type(m.body,'$.index')='integer'
        AND json_extract(m.body,'$.index')=json_array_length(m.body,'$.queue')
        AND CAST(json_extract(m.body,'$.context.account') AS TEXT)=?
        AND json_extract(m.body,'$.context.epoch')=?
        AND json_extract(m.body,'$.context.demo')=? GROUP BY day"""
    if skill == "dictation":
        session_sql = session_sql.replace("listening_session_", "dictation_session_")
    rows = engine.store.rows(session_sql,
        (stamp(boundaries[0][1]), *context, stamp(now), *values, stamp(boundaries[0][1]), stamp(now), *context))
    for row in rows:
        if row["day"] in daily:
            daily[row["day"]][skill + "_sessions_completed"] = row["count"]


def _protection(engine):
    ids = _protected(engine)
    if ids is None:
        return None, set()
    characters = set()
    ordered = sorted(ids)
    for offset in range(0, len(ordered), 128):
        batch = ordered[offset:offset + 128]
        rows = engine.store.rows("""SELECT CAST(id AS INTEGER) AS id,kind,
          CASE WHEN json_type(body,'$.data.characters')='text' AND instr(json_extract(body,'$.data.characters'),char(0))=0
            THEN substr(json_extract(body,'$.data.characters'),1,129) END AS characters
          FROM resources INDEXED BY resource_numeric_id WHERE kind IN """ + SUBJECTS + """
          AND CAST(id AS INTEGER) IN (""" + ",".join("?" for _ in batch) + ")", batch)
        if {row["id"] for row in rows} != set(batch):
            return None, set()
        for row in rows:
            text = row["characters"]
            if text is None and row["kind"] == "radical":
                continue
            if not isinstance(text, str) or not text.strip() or len(text) > 128 or "\0" in text:
                return None, set()
            characters.add(text)
    return ids, characters


def _difficulties(engine, beginning, now):
    protected, characters = _protection(engine)
    if protected is None:
        return [], True
    clauses, values = [], [stamp(beginning), stamp(now), engine.max_level()]
    if protected:
        clauses.append("CAST(s.id AS INTEGER) NOT IN (" + ",".join("?" for _ in protected) + ")")
        values.extend(sorted(protected))
    if characters:
        clauses.append("COALESCE(json_extract(s.body,'$.data.characters'),'') NOT IN (" + ",".join("?" for _ in characters) + ")")
        values.extend(sorted(characters))
    rows = engine.store.rows("""WITH mistakes AS (
      SELECT subject_id,
        SUM(CASE WHEN json_type(body,'$.errors.meaning')='integer'
          AND json_extract(body,'$.errors.meaning') BETWEEN 0 AND 1000000
          THEN json_extract(body,'$.errors.meaning') ELSE 0 END) AS meaning,
        SUM(CASE WHEN json_type(body,'$.errors.reading')='integer'
          AND json_extract(body,'$.errors.reading') BETWEEN 0 AND 1000000
          THEN json_extract(body,'$.errors.reading') ELSE 0 END) AS reading,
        MAX(julianday(created_at)) AS last_at
      FROM events WHERE kind IN ('subject_complete','practice_complete')
        AND julianday(created_at)>=julianday(?) AND julianday(created_at)<=julianday(?)
      GROUP BY subject_id)
      SELECT CAST(s.id AS INTEGER) AS id,s.kind AS type,json_extract(s.body,'$.data.level') AS level,
        CASE WHEN json_type(s.body,'$.data.characters')='text'
          THEN substr(json_extract(s.body,'$.data.characters'),1,129) ELSE '' END AS characters,
        m.meaning,m.reading FROM mistakes m JOIN resources s INDEXED BY resource_numeric_id
        ON CAST(s.id AS INTEGER)=m.subject_id
      WHERE s.kind IN """ + SUBJECTS + """ AND json_type(s.body,'$.id')='integer'
        AND json_extract(s.body,'$.id')=CAST(s.id AS INTEGER) AND CAST(s.id AS INTEGER)>0
        AND json_extract(s.body,'$.object')=s.kind AND json_type(s.body,'$.data.level')='integer'
        AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
        AND json_extract(s.body,'$.data.hidden_at') IS NULL AND (m.meaning+m.reading)>0
        AND instr(COALESCE(json_extract(s.body,'$.data.characters'),''),char(0))=0
        """ + (" AND " + " AND ".join(clauses) if clauses else "") + """
      ORDER BY (m.meaning+m.reading) DESC,m.last_at DESC,CAST(s.id AS INTEGER) LIMIT 6""", values)
    result = []
    for row in rows:
        text = row["characters"]
        if len(text) > 128 or "\0" in text:
            continue
        result.append({"id": row["id"], "type": row["type"], "level": row["level"],
            "label": plain(text) or ("Image radical" if row["type"] == "radical" else "Subject " + str(row["id"])),
            "meaning_mistakes": row["meaning"], "reading_mistakes": row["reading"],
            "can_open": True})
    return result, False


def _current(engine, now):
    states = dict.fromkeys(STATES, 0)
    by_kind = {kind: dict.fromkeys(STATES, 0) for kind in ("review", "lesson", "material")}
    for row in engine.store.rows("""SELECT kind,state,COUNT(*) AS count FROM outbox
      WHERE julianday(created_at)<=julianday(?) GROUP BY kind,state""", (stamp(now),)):
        if row["kind"] in by_kind and row["state"] in states:
            states[row["state"]] += row["count"]
            by_kind[row["kind"]][row["state"]] = row["count"]
    return {"by_state": states, "by_kind": by_kind,
        "waiting": states["pending"] + states["inflight"],
        "attention": sum(states[state] for state in ("uncertain", "conflicted", "blocked")),
        "confirmed": states["confirmed"], "archived": states["discarded"],
        "label": "Current status of this device's saved submissions",
        "confirmed_label": "Confirmed locally in demo" if engine.demo else "Confirmed by WaniKani"}


def _saved(engine):
    saved = dict.fromkeys(MODES, False)
    for mode in MODES:
        reference = engine.store.get(mode + "_session")
        if not isinstance(reference, str):
            continue
        rows = engine.store.rows("""SELECT 1 FROM sessions WHERE id=?
          AND json_extract(body,'$.mode')=? AND json_extract(body,'$.phase')!='complete' LIMIT 1""", (reference, mode))
        saved[mode] = bool(rows)
    return saved


def _suggestions(saved, submissions, difficult, availability, vacation):
    result = []
    def add(code, label, reason, view, limit=None):
        route = {"view": view}
        if limit is not None:
            route["limit"] = limit
        result.append({"code": code, "label": label, "reason": reason, "route": route, "effect": "navigation_only"})
    if submissions["attention"]:
        add("saved_submissions", "Check saved submissions", "Some local results need attention before they can be confirmed.", "recovery")
    for mode in ("reviews", "lessons"):
        if saved[mode]:
            add("resume_" + mode, "Return to saved " + mode, "Your exact question and partial answers are saved.",
                "review-overview" if mode == "reviews" else "lesson-overview")
    availability = availability if isinstance(availability, dict) else {}
    if not saved["reviews"] and not vacation and type(availability.get("reviews")) is int and availability["reviews"] > 0:
        add("review_five", "Review five", "Open Reviews and choose when to begin.", "review-overview", 5)
    if type(availability.get("listening")) is int and availability["listening"] > 0:
        add("listen_five", "Listen to five familiar words", "Local listening practice keeps WaniKani scheduling separate.", "listen", 5)
    if difficult or saved["practice"]:
        add("practice", "Practice at your pace", "Choose local practice from your completed study mistakes.", "practice-library")
    if not result and not vacation and type(availability.get("lessons")) is int and availability["lessons"] > 0:
        add("lessons", "Explore available lessons", "Preview new subjects before choosing a lesson batch.", "lesson-overview", 5)
    return result[:4]


def overview(engine, *, timezone=None, now=None, availability=None):
    now, zone, name = _clock(engine, now, timezone)
    with engine.store.lock:
        account = "demo" if engine.demo else engine.store.get("account_id")
        if not engine.user() or (not engine.demo and (account is None or user_id(engine.store.get("user")) != account)):
            raise UserError("Connect the current account before viewing its local learning activity.", "insights_account")
        today = datetime.fromtimestamp(now, zone).date()
        boundaries = []
        daily = {}
        for offset in range(29, -1, -1):
            date = today - timedelta(days=offset)
            beginning = datetime.combine(date, time(), zone).timestamp()
            end = datetime.combine(date + timedelta(days=1), time(), zone).timestamp()
            boundaries.append((date.isoformat(), beginning, end))
            daily[date.isoformat()] = _empty()
        _completion_data(engine, boundaries, now, daily)
        _session_data(engine, boundaries, now, daily)
        _listening_data(engine, boundaries, now, daily, str(account))
        _listening_data(engine, boundaries, now, daily, str(account), skill="dictation")
        windows = {}
        for count in (7, 30):
            total = _empty()
            selected = boundaries[-count:]
            for day, _, _ in selected:
                for metric, value in daily[day].items():
                    if isinstance(value, dict):
                        for key, amount in value.items():
                            total[metric][key] += amount
                    else:
                        total[metric] += value
            windows[str(count)] = {"days": count, "start_day": selected[0][0], "end_day": today.isoformat(), **total}
        submissions = _current(engine, now)
        saved = _saved(engine)
        difficulties, withheld = _difficulties(engine, boundaries[0][1], now)
        return {"schema_version": 1, "scope": "recorded_on_this_device", "label": "Recorded on this device",
            "demo": bool(engine.demo), "timezone": name, "as_of": stamp(now), "windows": windows,
            "daily": [{"day": day, **values} for day, values in daily.items()],
            "current_submissions": submissions, "saved_sessions": saved,
            "difficulties": difficulties, "difficulties_withheld": withheld,
            "difficulty_basis": "Final uncorrected mistakes in subjects completed on this device in the last 30 local days",
            "history_note": "Activity includes retained work from before account resets; it does not describe current WaniKani progress or activity on other devices.",
            "session_note": "Completed batches include finish-this-batch sessions; question parts and reset-interrupted batches are not completed batches.",
            "correction_label": "Local uses of I made a typo",
            "suggestions": _suggestions(saved, submissions, difficulties, availability,
                bool(engine.user().get("current_vacation_started_at")))}
