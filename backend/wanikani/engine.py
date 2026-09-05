import json
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from .common import UserError, epoch, plain, stamp
from .grading import grade

DEFAULTS = {
    "batch_size": 5, "notifications": True, "quiet_start": 22, "quiet_end": 8,
    "reminder_interval": 7200, "snooze_until": 0, "desktop_card": False,
    "idle_gallery": False, "companion_animation": True, "reduced_motion": False,
    "autoplay_audio": False, "voice_actor_id": 1, "cache_limit_mb": 256,
    "last_notification_at": 0,
}
SUBJECTS = "('radical','kanji','vocabulary','kana_vocabulary')"
BUSY_STATES = "('pending','inflight','uncertain','blocked','conflicted')"


def baseline(assignment):
    data = assignment.get("data", {})
    return {key: data.get(key) for key in ("subject_id", "started_at", "available_at", "srs_stage", "burned_at", "resurrected_at", "hidden")}


class Engine:
    def __init__(self, store, demo=False, clock=time.time):
        self.store = store
        self.demo = demo
        self.clock = clock
        self.connected = demo
        self.syncing = False
        self.status = "demo" if demo else "disconnected"
        self.message = ""
        self.clock_offset = 0
        self.clock_untrusted = False
        if demo:
            from .demo import populate
            populate(store, clock())

    def now(self):
        return self.clock() + self.clock_offset

    def user(self):
        return (self.store.get("user") or {}).get("data", {})

    def max_level(self):
        sub = self.user().get("subscription", {})
        end = epoch(sub.get("period_ends_at"))
        if end and self.now() >= end and sub.get("type") == "recurring":
            return 3
        return int(sub.get("max_level_granted", 0))

    def settings(self):
        return {**DEFAULTS, **self.store.get("settings", {})}

    def set_settings(self, values):
        values = dict(values)
        valid = {}
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            if isinstance(DEFAULTS[key], bool):
                if not isinstance(value, bool):
                    raise UserError("Expected an on/off setting.")
                valid[key] = value
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise UserError("Expected a numeric setting.")
                low, high = {"batch_size": (1, 20), "quiet_start": (0, 23), "quiet_end": (0, 23), "reminder_interval": (1800, 86400), "cache_limit_mb": (32, 1024), "voice_actor_id": (1, 10000), "snooze_until": (0, self.now() + 86400 * 30), "last_notification_at": (0, self.now() + 60)}.get(key, (0, 100000))
                valid[key] = max(low, min(high, int(value)))
        self.store.set("settings", {**self.settings(), **valid})
        return self.settings()

    def ensure_access(self, subject):
        if not subject or subject["data"].get("hidden_at") or subject["data"].get("level", 61) > self.max_level():
            raise UserError("This subject is outside your current WaniKani access.", "access_restricted")

    def assignments(self, mode="reviews", count_only=False):
        eligibility = """json_extract(a.body,'$.data.started_at') IS NULL
          AND julianday(json_extract(a.body,'$.data.unlocked_at'))<=julianday(?)""" if mode == "lessons" else """
          json_extract(a.body,'$.data.started_at') IS NOT NULL
          AND json_extract(a.body,'$.data.burned_at') IS NULL
          AND julianday(json_extract(a.body,'$.data.available_at'))<=julianday(?)"""
        columns = "COUNT(*)" if count_only else "a.body,s.body"
        rows = self.store.rows(f"""SELECT {columns} FROM resources a JOIN resources s
          ON s.kind IN {SUBJECTS} AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
          WHERE a.kind='assignment' AND json_extract(s.body,'$.data.level')<=?
          AND json_extract(s.body,'$.data.hidden_at') IS NULL
          AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
          AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER)
            AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})
          AND {eligibility}""", (self.max_level(), stamp(self.now())))
        if count_only:
            return rows[0][0]
        result = []
        for row in rows:
            assignment, subject = json.loads(row[0]), json.loads(row[1])
            data = assignment["data"]
            due = epoch(data.get("available_at"))
            unlocked = epoch(data.get("unlocked_at"))
            if mode == "lessons" and unlocked is not None and unlocked <= self.now() and not data.get("started_at"):
                result.append((assignment, subject))
            elif mode == "reviews" and data.get("started_at") and due is not None and due <= self.now() and not data.get("burned_at"):
                result.append((assignment, subject))
        return result

    def details(self, subject_id, include_relations=True):
        subject = self.store.subject(int(subject_id))
        self.ensure_access(subject)
        data = subject["data"]
        material = self.store.related("study_material", int(subject_id))
        draft = self.store.get("material_draft_" + str(subject_id))
        assignment = self.store.related("assignment", int(subject_id))
        statistic = self.store.related("review_statistic", int(subject_id))
        def relatives(ids):
            output = []
            for sid in ids[:30]:
                item = self.store.subject(sid)
                if item and item["data"].get("level", 61) <= self.max_level() and not item["data"].get("hidden_at"):
                    output.append({"id": sid, "characters": item["data"].get("characters") or "◇", "meaning": next((m["meaning"] for m in item["data"].get("meanings", []) if m.get("primary")), "")})
            return output
        audio = []
        for item in data.get("pronunciation_audios", []):
            url = item.get("url", "")
            rows = self.store.rows("SELECT path FROM media WHERE url=?", (url,))
            if rows and Path(rows[0][0]).is_file():
                audio.append({"url": Path(rows[0][0]).as_uri(), "actor": item.get("metadata", {}).get("voice_actor_id", 1)})
        audio.sort(key=lambda x: x["actor"] != self.settings()["voice_actor_id"])
        images = []
        for image in data.get("character_images", []):
            rows = self.store.rows("SELECT path FROM media WHERE url=?", (image.get("url", ""),))
            if rows and Path(rows[0][0]).is_file():
                images.append(Path(rows[0][0]).as_uri())
        return {
            "id": subject["id"], "type": subject["object"], "characters": data.get("characters") or "",
            "slug": data.get("slug", ""), "level": data.get("level"), "images": images,
            "meanings": [m["meaning"] for m in data.get("meanings", []) if m.get("accepted_answer")],
            "readings": [{"reading": r["reading"], "type": r.get("type", ""), "accepted": bool(r.get("accepted_answer"))} for r in data.get("readings", [])],
            "meaning_mnemonic": plain(data.get("meaning_mnemonic")), "meaning_hint": plain(data.get("meaning_hint")),
            "reading_mnemonic": plain(data.get("reading_mnemonic")), "reading_hint": plain(data.get("reading_hint")),
            "sentences": [{"ja": plain(s.get("ja")), "en": plain(s.get("en"))} for s in data.get("context_sentences", [])],
            "components": relatives(data.get("component_subject_ids", [])) if include_relations else [],
            "related": relatives(data.get("amalgamation_subject_ids", [])) if include_relations else [],
            "audio": audio, "audio_available": bool(data.get("pronunciation_audios")),
            "material": draft or (material or {}).get("data", {}), "material_pending": draft is not None,
            "pinned": int(subject_id) in self.store.get("pinned_subjects", []),
            "assignment": (assignment or {}).get("data", {}), "statistics": (statistic or {}).get("data", {}),
        }

    def search(self, text, limit=30):
        query = str(text).strip()[:256]
        if not query:
            return []
        # Match literal characters, meanings, or readings. Long selections also
        # surface contained Japanese subjects, without exporting the selection.
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.store.rows(f"""SELECT id,body FROM resources WHERE kind IN {SUBJECTS}
          AND json_extract(body,'$.data.level')<=? AND json_extract(body,'$.data.hidden_at') IS NULL
          AND (json_extract(body,'$.data.characters') LIKE ? ESCAPE '\\'
            OR json_extract(body,'$.data.meanings') LIKE ? ESCAPE '\\'
            OR json_extract(body,'$.data.readings') LIKE ? ESCAPE '\\'
            OR (length(json_extract(body,'$.data.characters'))>0 AND instr(?,json_extract(body,'$.data.characters'))>0))
          LIMIT 150""", (self.max_level(), pattern, pattern, pattern, query))
        rows = sorted(rows, key=lambda r: (json.loads(r[1])["data"].get("characters") != query, -len(json.loads(r[1])["data"].get("characters") or "")))
        return [self.details(int(row[0]), False) for row in rows[:limit]]

    def start(self, mode="reviews", limit=None, subjects=None):
        if mode not in ("reviews", "lessons", "practice"):
            raise UserError("Unknown study mode.")
        with self.store.transaction():
            existing = self.store.session()
            if existing and existing["phase"] != "complete":
                return self.session_view(existing)
            if not self.user():
                raise UserError("Connect your account or try the demo first.")
            if mode != "practice" and self.user().get("current_vacation_started_at"):
                raise UserError("WaniKani vacation mode is active. Ungraded practice is still available.", "vacation")
            if mode != "practice" and (abs(self.clock_offset) > 300 or self.clock_untrusted):
                raise UserError("The system clock differs from WaniKani. Correct it before graded study.", "clock_changed")
            count = max(1, min(20, int(limit or self.settings()["batch_size"])))
            if mode == "practice":
                ids = subjects or [s["id"] for s in self.difficult()]
                candidates = []
                for sid in list(dict.fromkeys(int(x) for x in ids))[:count]:
                    item = self.store.subject(sid)
                    self.ensure_access(item)
                    candidates.append((self.store.related("assignment", sid), item))
            else:
                candidates = self.assignments(mode)
            if mode == "lessons":
                candidates.sort(key=lambda pair: (pair[1]["data"].get("level", 0), pair[1]["data"].get("lesson_position", 0)))
            else:
                random.SystemRandom().shuffle(candidates)
            queue = []
            for assignment, subject in candidates:
                if len(queue) >= count:
                    break
                parts = {"meaning": False}
                if subject["object"] in ("kanji", "vocabulary"):
                    if not any(r.get("accepted_answer") for r in subject["data"].get("readings", [])):
                        continue  # incomplete/unknown subject data cannot be graded safely
                    parts["reading"] = False
                if not subject["data"].get("characters") and not self.details(subject["id"])["images"]:
                    continue  # image-only radical requires its cached image
                queue.append({"subject_id": subject["id"], "assignment_id": assignment["id"] if assignment else None,
                    "baseline": baseline(assignment) if assignment else {}, "parts": parts,
                    "errors": {"meaning": 0, "reading": 0}, "done": False})
            if not queue:
                raise UserError("No eligible cached items are ready for this session. Refresh or choose another activity.", "empty_queue")
            session = {"id": str(uuid.uuid4()), "mode": mode, "queue": queue, "index": 0,
                "phase": "lesson" if mode == "lessons" else "question", "part": "meaning", "feedback": None,
                "draft": "", "lesson_index": 0, "completed": 0, "overrides": 0, "started_at": stamp(self.now()), "ended_at": None}
            self.store.save_session(session)
            return self.session_view(session)

    def require_session(self):
        session = self.store.session()
        if not session or session["phase"] == "complete":
            raise UserError("There is no active session.")
        self.ensure_access(self.store.subject(session["queue"][session["index"]]["subject_id"]))
        return session

    def draft(self, text):
        with self.store.transaction():
            session = self.require_session()
            if session["phase"] == "question":
                session["draft"] = str(text)[:300]
                self.store.save_session(session)
        return {"saved": True}

    def answer(self, text):
        with self.store.transaction():
            session = self.require_session()
            self.ensure_study_state(session)
            if session["phase"] != "question":
                return self.session_view(session)
            entry = session["queue"][session["index"]]
            subject = self.store.subject(entry["subject_id"])
            material = self.store.get("material_draft_" + str(entry["subject_id"])) or (self.store.related("study_material", entry["subject_id"]) or {}).get("data", {})
            feedback = grade(subject, session["part"], str(text), material)
            feedback["answer"] = str(text)[:300]
            feedback["corrected"] = False
            session["draft"] = str(text)[:300]
            if feedback["retry"]:
                session["feedback"] = feedback
            else:
                if not feedback["correct"]:
                    entry["errors"][session["part"]] += 1
                session["feedback"] = feedback
                session["phase"] = "feedback"
            self.store.event(session["id"], entry["subject_id"], "answer", stamp(self.now()), {"part": session["part"], **feedback})
            self.store.save_session(session)
            return self.session_view(session)

    def correct(self):
        with self.store.transaction():
            session = self.require_session()
            feedback = session.get("feedback") or {}
            if session["phase"] != "feedback" or feedback.get("correct") or feedback.get("retry") or feedback.get("corrected"):
                raise UserError("Only the current incorrect answer can be corrected before advancing.")
            entry = session["queue"][session["index"]]
            entry["errors"][session["part"]] = max(0, entry["errors"][session["part"]] - 1)
            feedback.update(correct=True, corrected=True, kind="correct", message="Typo correction recorded locally.")
            session["overrides"] += 1
            self.store.event(session["id"], entry["subject_id"], "correction", stamp(self.now()), {"part": session["part"]})
            self.store.save_session(session)
            return self.session_view(session)

    def lesson_next(self, back=False):
        with self.store.transaction():
            session = self.require_session()
            self.ensure_study_state(session)
            if session["phase"] != "lesson":
                raise UserError("The lesson presentation is already complete.")
            session["lesson_index"] = max(0, session["lesson_index"] + (-1 if back else 1))
            if session["lesson_index"] >= len(session["queue"]):
                session["phase"] = "question"
            self.store.save_session(session)
            return self.session_view(session)

    def advance(self):
        with self.store.transaction():
            session = self.require_session()
            self.ensure_study_state(session)
            if session["phase"] != "feedback":
                raise UserError("Check your answer before advancing.")
            entry = session["queue"][session["index"]]
            if session["feedback"]["correct"]:
                entry["parts"][session["part"]] = True
            if all(entry["parts"].values()):
                entry["done"] = True
                session["completed"] += 1
                if session["mode"] != "practice":
                    kind = "lesson" if session["mode"] == "lessons" else "review"
                    operation_id = session["id"] + ":" + str(entry["subject_id"])
                    body = {"assignment_id": entry["assignment_id"], "baseline": entry["baseline"], "session_id": session["id"],
                        "completed_at": stamp(self.now()), "errors": entry["errors"], "account_id": self.store.get("account_id")}
                    self.store.execute("INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?,?,?)", (operation_id, kind, entry["subject_id"], "pending", json.dumps(body), stamp(self.now()), "Waiting to sync"))
                self.store.event(session["id"], entry["subject_id"], "practice_complete" if session["mode"] == "practice" else "subject_complete", stamp(self.now()), {"errors": entry["errors"], "mode": session["mode"]})
                session["index"] += 1
            session["feedback"] = None
            session["draft"] = ""
            if session["index"] >= min(len(session["queue"]), session.get("finish_at", len(session["queue"]))):
                session["phase"] = "complete"
                session["ended_at"] = stamp(self.now())
            else:
                current = session["queue"][session["index"]]
                session["part"] = next(part for part, done in current["parts"].items() if not done)
                session["phase"] = "question"
            self.store.save_session(session)
            if self.demo:
                self.confirm_demo()
            return self.session_view(session)

    def ensure_study_state(self, session):
        if session["mode"] == "practice":
            return
        if self.user().get("current_vacation_started_at"):
            raise UserError("Vacation mode is active. Your partial session is saved.", "vacation")
        if self.clock_untrusted or abs(self.clock_offset) > 300:
            raise UserError("The clock changed. Refresh to verify the time before continuing graded study.", "clock_changed")

    def finish(self):
        # Finish the current group of five, including all of its error counts.
        # Closing immediately uses durable pause instead of abandoning answers.
        with self.store.transaction():
            session = self.require_session()
            session["finish_at"] = min(len(session["queue"]), ((session["index"] // 5) + 1) * 5)
            self.store.save_session(session)
            return self.session_view(session)

    def session_view(self, session=None):
        session = session or self.store.session()
        if not session:
            return None
        view = {key: session[key] for key in ("id", "mode", "phase", "part", "feedback", "draft", "completed", "overrides", "started_at", "ended_at", "lesson_index")}
        view["total"] = len(session["queue"])
        view["finishing"] = "finish_at" in session
        view["invalidated"] = session.get("invalidated", "")
        view["errors"] = sum(sum(item["errors"].values()) for item in session["queue"])
        index = session["lesson_index"] if session["phase"] == "lesson" else session["index"]
        view["subject"] = None
        if session["phase"] != "complete" and index < len(session["queue"]):
            try:
                view["subject"] = self.details(session["queue"][index]["subject_id"])
            except UserError:
                view["restricted"] = True
        return view

    def confirm_demo(self):
        for row in self.store.rows("SELECT * FROM outbox WHERE state='pending'"):
            body = json.loads(row["body"])
            if row["kind"] in ("review", "lesson"):
                assignment = self.store.resource("assignment", body["assignment_id"])
                if not assignment:
                    continue
                if row["kind"] == "lesson":
                    assignment["data"]["started_at"] = body["completed_at"]
                    assignment["data"]["srs_stage"] = 1
                else:
                    assignment["data"]["srs_stage"] = max(1, assignment["data"]["srs_stage"] + (-1 if any(body["errors"].values()) else 1))
                assignment["data"]["available_at"] = stamp(self.now() + 4 * 3600)
                assignment["data_updated_at"] = stamp(self.now())
                self.store.put(assignment)
            elif row["kind"] == "material":
                self.store.put({"id": row["subject_id"] + 500, "object": "study_material", "data_updated_at": stamp(self.now()), "data": {"subject_id": row["subject_id"], **body["values"]}})
                self.store.set("material_draft_" + str(row["subject_id"]), None)
            self.store.execute("UPDATE outbox SET state='confirmed',detail='Demo only; nothing was sent to WaniKani' WHERE id=?", (row["id"],))

    def set_material(self, subject_id, values):
        self.ensure_access(self.store.subject(int(subject_id)))
        synonyms = values.get("meaning_synonyms", [])
        if not isinstance(synonyms, list) or len(synonyms) > 20 or any(not isinstance(s, str) or not s.strip() or len(s) > 64 for s in synonyms):
            raise UserError("Use at most 20 short, nonempty meaning synonyms.")
        values = {"meaning_synonyms": list(dict.fromkeys(s.strip() for s in synonyms)), "meaning_note": str(values.get("meaning_note", ""))[:2000], "reading_note": str(values.get("reading_note", ""))[:2000]}
        with self.store.transaction():
            if self.store.rows(f"SELECT 1 FROM outbox WHERE subject_id=? AND kind='material' AND state IN {BUSY_STATES}", (subject_id,)):
                raise UserError("Sync or resolve the previous edit for this subject first.")
            existing = self.store.related("study_material", subject_id)
            body = {"values": values, "baseline": (existing or {}).get("data", {}), "material_id": (existing or {}).get("id"), "account_id": self.store.get("account_id")}
            self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), "material", subject_id, "pending", json.dumps(body), stamp(self.now()), "Waiting to sync"))
            self.store.set("material_draft_" + str(subject_id), values)
            if self.demo:
                self.confirm_demo()
        return self.details(subject_id)

    def difficult(self):
        rows = self.store.rows("""SELECT DISTINCT subject_id FROM events WHERE kind='answer'
          AND json_extract(body,'$.kind')='incorrect' ORDER BY id DESC LIMIT 12""")
        ids = self.store.get("pinned_subjects", []) + [r[0] for r in rows]
        ids += [int(json.loads(r[0])["data"]["subject_id"]) for r in self.store.rows("""SELECT body FROM resources WHERE kind='review_statistic'
          AND json_extract(body,'$.data.percentage_correct')<90 ORDER BY json_extract(body,'$.data.percentage_correct') LIMIT 12""")]
        output = []
        for sid in dict.fromkeys(ids):
            try:
                output.append(self.details(sid, False))
            except UserError:
                continue
            if len(output) == 8:
                break
        return output

    def pin(self, subject_id, enabled):
        self.ensure_access(self.store.subject(subject_id))
        ids = self.store.get("pinned_subjects", [])
        if enabled and subject_id not in ids:
            ids.insert(0, subject_id)
        elif not enabled and subject_id in ids:
            ids.remove(subject_id)
        self.store.set("pinned_subjects", ids[:100])
        return self.details(subject_id)

    def ambient(self):
        rows = self.store.rows(f"""SELECT s.id FROM resources s JOIN resources a ON a.kind='assignment'
          AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
          WHERE s.kind IN {SUBJECTS} AND json_extract(s.body,'$.data.level')<=?
          AND json_extract(s.body,'$.data.hidden_at') IS NULL AND json_extract(a.body,'$.data.srs_stage')>=5
          AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
          AND (json_extract(a.body,'$.data.burned_at') IS NOT NULL OR julianday(json_extract(a.body,'$.data.available_at'))>julianday(?))
          AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER) AND o.state IN {BUSY_STATES})
          ORDER BY CAST(s.id AS INTEGER) LIMIT 60""", (self.max_level(), stamp(self.now() + 86400)))
        return [self.details(int(r[0]), False) for r in rows]

    def snapshot(self):
        now = self.now()
        level = self.user().get("level", 0)
        counts = self.store.rows(f"""SELECT COUNT(*),SUM(CASE WHEN json_extract(a.body,'$.data.srs_stage')>=5 THEN 1 ELSE 0 END)
          FROM resources s LEFT JOIN resources a ON a.kind='assignment' AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
          WHERE s.kind='kanji' AND json_extract(s.body,'$.data.level')=? AND json_extract(s.body,'$.data.hidden_at') IS NULL
          AND json_extract(s.body,'$.data.level')<=?""", (level, self.max_level()))[0]
        due = self.assignments("reviews", count_only=True)
        lessons = self.assignments("lessons", count_only=True)
        forecast = [0] * 24
        next_at = None
        for r in self.store.rows(f"""SELECT json_extract(a.body,'$.data.available_at') FROM resources a JOIN resources s
          ON s.kind IN {SUBJECTS} AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
          WHERE a.kind='assignment' AND json_extract(a.body,'$.data.burned_at') IS NULL
          AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0 AND json_extract(s.body,'$.data.hidden_at') IS NULL
          AND json_extract(s.body,'$.data.level')<=? AND NOT EXISTS(SELECT 1 FROM outbox o
            WHERE o.subject_id=CAST(s.id AS INTEGER) AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})""", (self.max_level(),)):
            value = epoch(r[0])
            if value and value > now:
                next_at = min(next_at or value, value)
                hour = int((value - now) // 3600)
                if 0 <= hour < 24:
                    forecast[hour] += 1
        activity = [dict(r) for r in self.store.rows("""SELECT date(created_at,'localtime') AS day,COUNT(*) AS count
          FROM events WHERE kind IN ('subject_complete','practice_complete') GROUP BY day ORDER BY day DESC LIMIT 35""")]
        outbox = [{"id": r["id"], "kind": r["kind"], "subject_id": r["subject_id"], "state": r["state"], "detail": r["detail"]} for r in self.store.rows("SELECT * FROM outbox WHERE state NOT IN ('confirmed','discarded') ORDER BY created_at")]
        media = self.store.rows("SELECT COUNT(*),COALESCE(SUM(size),0) FROM media")[0]
        session = self.session_view()
        return {"demo": self.demo, "status": self.status, "message": self.message, "connected": self.connected,
            "syncing": self.syncing, "username": self.user().get("username", ""), "level": level,
            "max_level": self.max_level(), "vacation": bool(self.user().get("current_vacation_started_at")),
            "reviews": due, "lessons": lessons, "next_reviews_at": stamp(next_at) if next_at else None,
            "forecast": forecast, "level_total": counts[0], "level_passed": counts[1] or 0,
            "activity": activity, "session": session, "pending": len([x for x in outbox if x["state"] in ("pending", "inflight", "blocked")]),
            "attention": len([x for x in outbox if x["state"] in ("uncertain", "conflicted", "blocked")]),
            "outbox": outbox, "last_sync": self.store.get("last_sync"), "settings": self.settings(),
            "cache": {"files": media[0], "bytes": media[1]}, "difficult": self.difficult(), "now": now,
            "credential_storage": self.store.get("credential_storage", "session")}

    def command(self, request_id, method, args):
        handlers = {"start": lambda: self.start(args.get("mode", "reviews"), args.get("limit"), args.get("subjects")),
            "draft": lambda: self.draft(args.get("text", "")), "answer": lambda: self.answer(args.get("text", "")),
            "advance": self.advance, "correct": self.correct, "finish": self.finish,
            "lesson_next": lambda: self.lesson_next(args.get("back", False)),
            "set_material": lambda: self.set_material(int(args["subject_id"]), args.get("values", {})),
            "pin": lambda: self.pin(int(args["subject_id"]), bool(args.get("enabled"))),
            "settings": lambda: self.set_settings(args),
            "snooze": lambda: self.set_settings({"snooze_until": self.now() + max(60, min(86400, int(args.get("seconds", 3600))))})}
        if method not in handlers:
            raise UserError("Unknown command.")
        # The effect and its reply commit together; replay of the same local
        # request after a transport interruption returns its original reply.
        with self.store.transaction():
            rows = self.store.rows("SELECT body FROM commands WHERE id=?", (request_id,))
            if rows:
                return json.loads(rows[0][0])
            value = handlers[method]()
            self.store.execute("INSERT INTO commands VALUES(?,?)", (request_id, json.dumps(value, ensure_ascii=False)))
            return value
