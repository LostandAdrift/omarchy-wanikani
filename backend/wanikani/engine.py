import json
import random
import re
import time
import uuid
from datetime import datetime
from .common import UserError, accessible_subject, epoch, plain, stamp
from .media_files import available_file
from .grading import grade, validate_subject_answers
from . import comparisons, editor, history, milestones

DEFAULTS = {
    "batch_size": 5, "notifications": True, "quiet_start": 22, "quiet_end": 8,
    "reminder_interval": 7200, "snooze_until": 0, "desktop_card": False,
    "idle_gallery": False, "companion_animation": True, "reduced_motion": False,
    "autoplay_audio": False, "voice_actor_id": 1, "cache_limit_mb": 256,
    "autoplay_lessons": False, "autoplay_listening": True,
    "strict_meanings": False,
    "last_notification_at": 0,
    "demo_offline": False,
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
            self.status = "offline" if self.settings()["demo_offline"] else "demo"

    def now(self):
        return self.clock() + self.clock_offset

    def user(self):
        return (self.store.get("user") or {}).get("data", {})

    def max_level(self, at=None):
        sub = self.user().get("subscription", {})
        granted = sub.get("max_level_granted", 0)
        if type(granted) is not int or not 0 <= granted <= 60:
            return 0
        kind = sub.get("type")
        # WaniKani requires unknown subscription states to behave as free.
        # Never expand an explicit lower grant while applying an expiry cap.
        if kind not in ("recurring", "lifetime"):
            return min(3, granted)
        end = epoch(sub.get("period_ends_at"))
        if kind == "recurring" and (end is None or (self.now() if at is None else at) >= end):
            return min(3, granted)
        return granted

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
        if self.demo and "demo_offline" in valid:
            self.status = "offline" if valid["demo_offline"] else "demo"
            if not valid["demo_offline"]:
                self.confirm_demo()
        return self.settings()

    def ensure_access(self, subject):
        if not accessible_subject(subject, self.max_level()):
            raise UserError("This subject is outside your current WaniKani access.", "access_restricted")

    def ensure_study_content(self, subject):
        self.ensure_access(subject)
        data = subject["data"]
        material = self.store.get("material_draft_" + str(subject["id"]))
        if material is None:
            material = (self.store.related("study_material", subject["id"]) or {}).get("data")
        validate_subject_answers(subject, material)
        if not data.get("characters") and not self.details(subject["id"], False)["images"]:
            raise UserError("The radical image is not cached. Refresh before continuing; your saved answers are retained.", "content_unavailable")

    def _assignment_rows(self, mode, columns, indexed=False):
        eligibility = """json_extract(a.body,'$.data.started_at') IS NULL
          AND julianday(json_extract(a.body,'$.data.unlocked_at'))<=julianday(?)""" if mode == "lessons" else """
          json_extract(a.body,'$.data.started_at') IS NOT NULL
          AND json_extract(a.body,'$.data.burned_at') IS NULL
          AND julianday(json_extract(a.body,'$.data.available_at'))<=julianday(?)"""
        assignment_index = " INDEXED BY resource_assignment_schedule" if indexed else ""
        subject_index = " INDEXED BY resource_search_identity" if indexed else ""
        return self.store.rows(f"""SELECT {columns} FROM resources a{assignment_index} JOIN resources s{subject_index}
          ON s.kind IN {SUBJECTS} AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
          WHERE a.kind='assignment' AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
          AND json_extract(s.body,'$.data.hidden_at') IS NULL
          AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
          AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER)
            AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})
          AND {eligibility}""", (self.max_level(), stamp(self.now())))

    def assignments(self, mode="reviews", count_only=False):
        # Preserve the full-body catalogue API for callers that need it. Counts
        # and new-session selection use projected schedule/access fields.
        rows = self._assignment_rows(mode, "COUNT(*)" if count_only else "a.body,s.body", indexed=count_only)
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

    def _study_candidates(self, mode):
        """Shuffle cheap identities; materialize subjects only as needed.

        Engine.start owns a transaction while consuming this iterator, so the
        eligibility projection and each selected assignment baseline agree.
        Shuffling the entire eligible identity list preserves the old random
        permutation, including continuation past unavailable cached content.
        """
        columns = "a.id AS assignment_id,s.id AS subject_id"
        if mode == "lessons":
            columns += """,json_extract(s.body,'$.data.level') AS level,
              CASE WHEN json_type(s.body,'$.data.lesson_position') IS NULL THEN 0
                ELSE json_extract(s.body,'$.data.lesson_position') END AS lesson_position,
              json_extract(a.body,'$.data.unlocked_at') AS unlocked_at"""
        rows = self._assignment_rows(mode, columns, indexed=True)
        from .practice import _sessions
        protected, _ = _sessions(self)
        rows = [row for row in rows if int(row["subject_id"]) not in protected]
        if mode == "lessons":
            # The old full-body path rejected malformed unlock dates before
            # lesson sorting. Preserve that order using only projected dates.
            rows = [row for row in rows if (unlocked := epoch(row["unlocked_at"])) is not None
                and unlocked <= self.now()]
            rows.sort(key=lambda row: (row["level"], row["lesson_position"]))
        else:
            random.SystemRandom().shuffle(rows)
        for row in rows:
            assignment = self.store.resource("assignment", row["assignment_id"])
            data = assignment["data"]
            # SQLite's date parser is more permissive than epoch(). Keep the
            # existing Python checks, including timezone handling, before load.
            due = epoch(data.get("available_at"))
            unlocked = epoch(data.get("unlocked_at"))
            eligible = (mode == "lessons" and unlocked is not None and unlocked <= self.now()
                and not data.get("started_at")) or (mode == "reviews" and data.get("started_at")
                and due is not None and due <= self.now() and not data.get("burned_at"))
            if eligible:
                yield assignment, self.store.subject(row["subject_id"])

    def details(self, subject_id, include_relations=True):
        subject = self.store.subject(int(subject_id))
        self.ensure_access(subject)
        data = subject["data"]
        material = self.store.related("study_material", int(subject_id))
        draft = self.store.get("material_draft_" + str(subject_id))
        study_material = draft if draft is not None else (material or {}).get("data")
        content_error = ""
        try:
            validate_subject_answers(subject, study_material)
        except UserError as error:
            content_error = str(error)
        # Display safely shaped values without rewriting the cached resource.
        # Graded entry points still validate the original subject and material.
        visible_material = dict(study_material) if isinstance(study_material, dict) else {}
        synonyms = visible_material.get("meaning_synonyms")
        visible_material["meaning_synonyms"] = [value for value in synonyms if isinstance(value, str)] if isinstance(synonyms, list) else []
        for key in ("meaning_note", "reading_note"):
            if not isinstance(visible_material.get(key), str):
                visible_material[key] = ""
        assignment = self.store.related("assignment", int(subject_id))
        statistic = self.store.related("review_statistic", int(subject_id))
        def objects(name):
            entries = data.get(name)
            return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []
        def relatives(ids):
            output = []
            if not isinstance(ids, list) or not ids:
                return output
            from .practice import _sessions
            protected, _ = _sessions(self)
            for sid in ids[:30] if isinstance(ids, list) else []:
                if type(sid) is not int or sid in protected:
                    continue
                item = self.store.subject(sid)
                if accessible_subject(item, self.max_level()):
                    meanings = item["data"].get("meanings")
                    output.append({"id": sid, "characters": item["data"].get("characters") if isinstance(item["data"].get("characters"), str) else "◇",
                        "meaning": next((m["meaning"] for m in meanings if isinstance(m, dict) and m.get("primary") is True
                          and m.get("accepted_answer") is True and isinstance(m.get("meaning"), str)), "") if isinstance(meanings, list) else ""})
            return output
        audio = []
        media_dir = self.store.path.parent / "media"
        audio_items = [item for item in objects("pronunciation_audios") if isinstance(item.get("url"), str)]
        for item in audio_items:
            url = item["url"]
            rows = self.store.rows("SELECT path FROM media WHERE url=?", (url,))
            path = available_file(media_dir, rows[0][0]) if rows else None
            if path:
                metadata = item.get("metadata")
                actor = metadata.get("voice_actor_id") if isinstance(metadata, dict) else None
                audio.append({"url": path.as_uri(), "actor": actor if type(actor) is int else 1})
        audio.sort(key=lambda x: x["actor"] != self.settings()["voice_actor_id"])
        images = []
        for image in objects("character_images"):
            if not isinstance(image.get("url"), str):
                continue
            rows = self.store.rows("SELECT path FROM media WHERE url=?", (image["url"],))
            path = available_file(media_dir, rows[0][0]) if rows else None
            if path:
                images.append(path.as_uri())
        return {
            "id": subject["id"], "type": subject["object"], "characters": data.get("characters") if isinstance(data.get("characters"), str) else "",
            "slug": data.get("slug") if isinstance(data.get("slug"), str) else "", "level": data.get("level"), "images": images,
            "meanings": [m["meaning"] for m in objects("meanings") if m.get("accepted_answer") is True and isinstance(m.get("meaning"), str)],
            "readings": [{"reading": r["reading"], "type": r.get("type", ""), "accepted": r.get("accepted_answer") is True} for r in objects("readings") if isinstance(r.get("reading"), str)],
            "meaning_mnemonic": plain(data.get("meaning_mnemonic")), "meaning_hint": plain(data.get("meaning_hint")),
            "reading_mnemonic": plain(data.get("reading_mnemonic")), "reading_hint": plain(data.get("reading_hint")),
            "sentences": [{"ja": plain(s.get("ja")), "en": plain(s.get("en"))} for s in objects("context_sentences")],
            "components": relatives(data.get("component_subject_ids", [])) if include_relations else [],
            "related": relatives(data.get("amalgamation_subject_ids", [])) if include_relations else [],
            "visually_similar": comparisons.for_subject(self, subject) if include_relations else [],
            "audio": audio, "audio_available": bool(audio_items), "content_error": content_error,
            "material": visible_material, "material_pending": draft is not None,
            **editor.view(self, int(subject_id), visible_material),
            "pinned": int(subject_id) in self.store.get("pinned_subjects", []),
            "assignment": (assignment or {}).get("data", {}), "statistics": (statistic or {}).get("data", {}),
        }

    def search(self, text, limit=30, filters=None, reading_query=None):
        from .search import lookup
        return lookup(self, text, limit, filters, reading_query)

    def saved_session(self, mode="resume"):
        """Resolve a saved mode without changing its draft or active reference."""
        if mode not in ("reviews", "lessons", "practice", "resume"):
            raise UserError("Unknown study mode.", "invalid_mode")
        def unfinished(reference, expected=None):
            session = self.store.session(reference) if isinstance(reference, str) else None
            return session if (session and session.get("phase") != "complete"
                and session.get("mode") in ("reviews", "lessons", "practice")
                and (expected is None or session["mode"] == expected)) else None
        with self.store.lock:
            if mode != "resume":
                return unfinished(self.store.get(mode + "_session"), mode)
            latest = unfinished(self.store.get("graded_session"))
            if latest and latest["mode"] in ("reviews", "lessons"):
                return latest
            candidates = [unfinished(self.store.get(name + "_session"), name) for name in ("reviews", "lessons")]
            candidates = [session for session in candidates if session]
            if candidates:
                return max(candidates, key=lambda session: session.get("revision", 0))
            active = unfinished(self.store.get("active_session"), "practice")
            return active or unfinished(self.store.get("practice_session"), "practice")

    def start(self, mode="reviews", limit=None, subjects=None, replace_practice=False):
        if mode not in ("reviews", "lessons", "practice", "resume"):
            raise UserError("Unknown study mode.", "invalid_mode")
        if not isinstance(replace_practice, bool) or (replace_practice and mode != "practice"):
            raise UserError("Only ungraded practice can start a new selection.")
        with self.store.transaction():
            if replace_practice:
                from .practice import validate_selection
                subjects = validate_selection(self, subjects)
            saved = self.saved_session(mode)
            if saved and not replace_practice:
                self.store.save_session(saved)
                return self.session_view(saved)
            if mode == "resume":
                mode = "reviews"
            if not self.user():
                raise UserError("Connect your account or try the demo first.")
            if mode != "practice" and self.user().get("current_vacation_started_at"):
                raise UserError("WaniKani vacation mode is active. Ungraded practice is still available.", "vacation")
            if mode != "practice" and (abs(self.clock_offset) > 300 or self.clock_untrusted):
                raise UserError("The system clock differs from WaniKani. Correct it before graded study.", "clock_changed")
            count = max(1, min(20, int(limit or self.settings()["batch_size"])))
            if mode == "practice":
                if subjects:
                    ids = subjects
                else:
                    from .practice import _sessions
                    protected, _ = _sessions(self)
                    ids = [s["id"] for s in self.difficult() if s["id"] not in protected]
                candidates = []
                for sid in list(dict.fromkeys(int(x) for x in ids))[:count]:
                    item = self.store.subject(sid)
                    self.ensure_access(item)
                    candidates.append((self.store.related("assignment", sid), item))
                random.SystemRandom().shuffle(candidates)
            elif mode == "lessons" and subjects is not None:
                from .lessons import validate_selection
                candidates = validate_selection(self, subjects)
                count = len(candidates)
            else:
                candidates = self._study_candidates(mode)
            queue = []
            for assignment, subject in candidates:
                try:
                    self.ensure_study_content(subject)
                except UserError as error:
                    if error.code != "content_unavailable":
                        raise
                    continue
                parts = {"meaning": False}
                if subject["object"] in ("kanji", "vocabulary"):
                    parts["reading"] = False
                queue.append({"subject_id": subject["id"], "assignment_id": assignment["id"] if assignment else None,
                    "baseline": baseline(assignment) if assignment else {}, "parts": parts,
                    "errors": {"meaning": 0, "reading": 0}, "done": False})
                if len(queue) >= count:
                    break
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
        if session.get("mode") not in ("reviews", "lessons", "practice"):
            raise UserError("Unknown saved study mode. Your saved work was retained.", "invalid_mode")
        index = session["lesson_index"] if session["phase"] == "lesson" else session["index"]
        self.ensure_study_content(self.store.subject(session["queue"][index]["subject_id"]))
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
            material = self.store.get("material_draft_" + str(entry["subject_id"]))
            if material is None:
                material = (self.store.related("study_material", entry["subject_id"]) or {}).get("data")
            feedback = grade(subject, session["part"], str(text), material,
                strict_meanings=self.settings()["strict_meanings"])
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
            self.ensure_study_state(session)
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
        view["revision"] = session.get("revision", 0)
        view["session_epoch"] = self.store.get("session_epoch", "")
        view["total"] = min(len(session["queue"]), session.get("finish_at", len(session["queue"])))
        view["finishing"] = "finish_at" in session
        view["invalidated"] = session.get("invalidated", "")
        view["errors"] = sum(sum(item["errors"].values()) for item in session["queue"])
        index = session["lesson_index"] if session["phase"] == "lesson" else session["index"]
        view["subject"] = None
        if session["phase"] != "complete" and index < len(session["queue"]):
            try:
                subject = self.store.subject(session["queue"][index]["subject_id"])
                self.ensure_study_content(subject)
                view["subject"] = self.details(subject["id"])
            except UserError as error:
                if error.code == "access_restricted":
                    from .journal import restricted_session
                    view = restricted_session(view)
                else:
                    view["unavailable"] = str(error)
        return view

    def confirm_demo(self):
        if self.settings()["demo_offline"]:
            return
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

    def set_material(self, subject_id, values, editor_draft=None):
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
            editor.clear_saved(self, subject_id, values, editor_draft)
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
          WHERE s.kind IN {SUBJECTS} AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
          AND length(json_extract(s.body,'$.data.characters'))>0
          AND json_extract(s.body,'$.data.hidden_at') IS NULL AND json_extract(a.body,'$.data.srs_stage')>=5
          AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
          AND (json_extract(a.body,'$.data.burned_at') IS NOT NULL OR julianday(json_extract(a.body,'$.data.available_at'))>julianday(?))
          AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER) AND o.state IN {BUSY_STATES})
          ORDER BY CAST(s.id AS INTEGER) LIMIT 60""", (self.max_level(), stamp(self.now() + 86400)))
        return [self.details(int(r[0]), False) for r in rows]

    def session_state(self):
        """Current durable session without rescanning account-wide collections."""
        with self.store.lock:
            session = self.session_view()
            summaries = {}
            for mode in ("reviews", "lessons", "practice"):
                saved = self.saved_session(mode)
                if not saved:
                    summaries[mode] = None
                    continue
                total = min(len(saved["queue"]), saved.get("finish_at", len(saved["queue"])))
                position = saved["lesson_index"] if saved["phase"] == "lesson" else saved["index"]
                summaries[mode] = {key: saved[key] for key in ("id", "mode", "phase", "part", "completed")}
                summaries[mode].update(total=total, position=min(position + 1, total),
                    active=bool(session and session["id"] == saved["id"]),
                    invalidated=saved.get("invalidated", ""), revision=saved.get("revision", 0))
            paused = any(value and not value["active"] for mode, value in summaries.items() if mode != "practice")
            return {"session": session, "saved_sessions": summaries, "paused_graded": paused,
                "session_revision": self.store.get("session_revision", 0),
                "session_epoch": self.store.get("session_epoch", "")}

    def snapshot(self):
        now = self.now()
        level = self.user().get("level", 0)
        counts = self.store.rows(f"""SELECT COUNT(*),SUM(CASE WHEN json_extract(a.body,'$.data.srs_stage')>=5 THEN 1 ELSE 0 END)
          FROM resources s LEFT JOIN resources a ON a.kind='assignment' AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
          WHERE s.kind='kanji' AND json_extract(s.body,'$.data.level')=? AND json_extract(s.body,'$.data.hidden_at') IS NULL
          AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?""", (level, self.max_level()))[0]
        due = self.assignments("reviews", count_only=True)
        lessons = self.assignments("lessons", count_only=True)
        forecast = [0] * 24
        next_at = None
        for r in self.store.rows(f"""SELECT json_extract(a.body,'$.data.available_at')
          FROM resources a INDEXED BY resource_assignment_schedule JOIN resources s INDEXED BY resource_search_identity
          ON s.kind IN {SUBJECTS} AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
          WHERE a.kind='assignment' AND json_extract(a.body,'$.data.burned_at') IS NULL
          AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0 AND json_extract(s.body,'$.data.hidden_at') IS NULL
          AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ? AND NOT EXISTS(SELECT 1 FROM outbox o
            WHERE o.subject_id=CAST(s.id AS INTEGER) AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})""", (self.max_level(),)):
            value = epoch(r[0])
            if value and value > now:
                next_at = min(next_at or value, value)
                hour = int((value - now) // 3600)
                if 0 <= hour < 24:
                    forecast[hour] += 1
        activity = history.activity(self.store)
        from .recovery import snapshot_summary
        outbox_summary = snapshot_summary(self)
        media = self.store.rows("SELECT COUNT(*),COALESCE(SUM(size),0) FROM media")[0]
        cached_subjects = self.store.rows(f"SELECT COUNT(*) FROM resources WHERE kind IN {SUBJECTS} AND json_type(body,'$.data.level')='integer' AND json_extract(body,'$.data.level') BETWEEN 1 AND ? AND json_extract(body,'$.data.hidden_at') IS NULL", (self.max_level(),))[0][0]
        session_state = self.session_state()
        return {"demo": self.demo, "status": self.status, "message": self.message, "connected": self.connected,
            "syncing": self.syncing, "username": self.user().get("username", ""), "level": level,
            "max_level": self.max_level(), "vacation": bool(self.user().get("current_vacation_started_at")),
            "reviews": due, "lessons": lessons, "next_reviews_at": stamp(next_at) if next_at else None,
            "forecast": forecast, "level_total": counts[0], "level_passed": counts[1] or 0,
            "activity": activity, "milestone": milestones.latest(self), **session_state,
            **outbox_summary, "last_sync": self.store.get("last_sync"), "settings": self.settings(),
            "cache": {"files": media[0], "bytes": media[1], "subjects": cached_subjects}, "difficult": self.difficult(), "now": now,
            "credential_storage": self.store.get("credential_storage", "session"),
            "credential_cleanup_needed": bool(self.store.get("credential_may_exist", False)) and self.store.get("credential_storage") in ("session", "disconnected")}

    def command(self, request_id, method, args):
        handlers = {"start": lambda: self.start(args.get("mode", "reviews"), args.get("limit"), args.get("subjects"), args.get("replace_practice", False)),
            "draft": lambda: self.draft(args.get("text", "")), "answer": lambda: self.answer(args.get("text", "")),
            "advance": self.advance, "correct": self.correct, "finish": self.finish,
            "lesson_next": lambda: self.lesson_next(args.get("back", False)),
            "set_material": lambda: self.set_material(int(args["subject_id"]), args.get("values", {}), args.get("editor_draft")),
            "editor_draft": lambda: editor.write(self, int(args["subject_id"]), args.get("values")),
            "editor_discard": lambda: editor.discard(self, int(args["subject_id"]), args.get("expected")),
            "pin": lambda: self.pin(int(args["subject_id"]), bool(args.get("enabled"))),
            "settings": lambda: self.set_settings(args),
            "ack_milestone": lambda: milestones.acknowledge(self, args.get("id")),
            "snooze": lambda: self.set_settings({"snooze_until": self.now() + max(60, min(86400, int(args.get("seconds", 3600))))})}
        if method not in handlers:
            raise UserError("Unknown command.")
        # The effect and its reply commit together; replay of the same local
        # request never repeats its effect. Reproject subject presentation to
        # current access without replacing the original outcome or revision.
        from .command_codec import UnreadableReply, decode, encode
        with self.store.transaction():
            rows = self.store.rows("SELECT body FROM commands WHERE id=?", (request_id,))
            if rows:
                from .journal import replay
                try:
                    value = decode(rows[0][0])
                except UnreadableReply:
                    raise UserError("This request is already recorded, but its saved reply cannot be read. Your work was retained. Close and resume study to load the saved session; restore a backup or reinstall the current plugin if the problem continues.", "reply_unavailable") from None
                return replay(self, value)
            value = handlers[method]()
            self.store.execute("INSERT INTO commands VALUES(?,?)", (request_id, encode(value)))
            return value
