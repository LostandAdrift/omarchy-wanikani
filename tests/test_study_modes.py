"""Independent durable study modes, using only authored local fixtures."""
import json
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, Engine, Store, UserError, NOW, stamp
from wanikani.practice import _sessions, catalogue


class StudyModeTests(EngineFixture, unittest.TestCase):
    def restart(self):
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)

    def without_revision(self, session):
        return {key: value for key, value in session.items() if key != "revision"}

    def finish(self, view):
        while view["phase"] == "lesson":
            view = self.engine.lesson_next()
        while view["phase"] != "complete":
            self.engine.answer(self.correct_answer(view))
            view = self.engine.advance()
        return view

    def test_explicit_modes_preserve_both_drafts_errors_and_discovery_position(self):
        review = self.engine.start("reviews", 1)
        self.engine.answer("unfinished wrong review")
        review_saved = self.store.session()
        lesson = self.engine.start("lessons", 2)
        self.assertEqual("lessons", lesson["mode"])
        self.assertNotEqual(review["id"], lesson["id"])
        self.engine.lesson_next()
        lesson_saved = self.store.session()
        practice = self.engine.start("practice", 1, [3])
        self.engine.draft("separate practice draft")
        self.restart()
        self.assertEqual(lesson["id"], self.engine.start("resume")["id"])
        self.assertEqual(self.without_revision(lesson_saved), self.without_revision(self.store.session()))
        resumed = self.engine.start("reviews")
        self.assertEqual(review["id"], resumed["id"])
        self.assertEqual(("feedback", 1, "unfinished wrong review"),
            (resumed["phase"], resumed["errors"], resumed["draft"]))
        self.assertEqual(self.without_revision(review_saved), self.without_revision(self.store.session()))
        self.assertEqual(practice["id"], self.engine.start("practice")["id"])
        self.assertEqual("separate practice draft", self.engine.session_view()["draft"])
        self.assertEqual(review["id"], self.engine.start("resume")["id"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_lesson_quiz_partial_answer_survives_switch_and_restart(self):
        lesson = self.engine.start("lessons", 1)
        self.engine.lesson_next()
        self.engine.answer("wrong lesson answer")
        self.engine.advance()
        self.engine.draft("partial lesson correction")
        expected = self.store.session()
        review = self.engine.start("reviews", 1)
        self.engine.draft("partial review")
        self.restart()
        self.assertEqual(review["id"], self.engine.start("resume")["id"])
        self.assertEqual(lesson["id"], self.engine.start("lessons")["id"])
        self.assertEqual(self.without_revision(expected), self.without_revision(self.store.session()))

    def test_final_feedback_waits_for_its_own_resume_and_acknowledgement(self):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != 1:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)
        review = self.engine.start("reviews", 1)
        self.engine.answer("ground")
        lesson = self.engine.start("lessons", 1)
        self.restart()
        self.assertEqual(lesson["id"], self.engine.start("lessons")["id"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        feedback = self.engine.start("reviews")
        self.assertEqual((review["id"], "feedback", True),
            (feedback["id"], feedback["phase"], feedback["feedback"]["correct"]))
        self.engine.command("ack-review", "advance", {})
        self.engine.command("ack-review", "advance", {})
        rows = self.store.rows("SELECT kind,subject_id FROM outbox")
        self.assertEqual([("review", 1)], [tuple(row) for row in rows])
        self.assertEqual(lesson["id"], self.engine.start("resume")["id"])

    def test_pending_completed_lesson_and_review_still_allow_explicit_practice(self):
        review = self.finish(self.engine.start("reviews", 1))
        lesson = self.finish(self.engine.start("lessons", 1))
        rows = self.store.rows("SELECT kind,subject_id FROM outbox")
        self.assertEqual({"review", "lesson"}, {row["kind"] for row in rows})
        for row in rows:
            self.assertNotIn(row["subject_id"], {s["id"] for _, s in self.engine._study_candidates("reviews")})
            self.assertNotIn(row["subject_id"], {s["id"] for _, s in self.engine._study_candidates("lessons")})
            self.finish(self.engine.start("practice", 1, [row["subject_id"]]))
        self.assertEqual(2, self.store.rows("SELECT COUNT(*) FROM outbox")[0][0])
        self.assertIsNone(self.engine.session_state()["saved_sessions"]["reviews"])
        self.assertIsNone(self.engine.session_state()["saved_sessions"]["lessons"])

    def test_summary_is_small_spoiler_free_and_marks_both_modes(self):
        review = self.engine.start("reviews", 1)
        self.engine.answer("private answer draft")
        lesson = self.engine.start("lessons", 1)
        state = self.engine.session_state()
        saved = state["saved_sessions"]
        self.assertEqual({"reviews", "lessons", "practice"}, set(saved))
        self.assertEqual((review["id"], False), (saved["reviews"]["id"], saved["reviews"]["active"]))
        self.assertEqual((lesson["id"], True, 1),
            (saved["lessons"]["id"], saved["lessons"]["active"], saved["lessons"]["position"]))
        self.assertTrue(state["paused_graded"])
        self.assertNotIn("private answer", json.dumps(saved))
        for summary in (saved["reviews"], saved["lessons"]):
            self.assertFalse({"subject", "draft", "feedback", "queue"}.intersection(summary))

    def test_legacy_active_only_migration_does_not_change_saved_body(self):
        review = self.engine.start("reviews", 1)
        self.engine.answer("saved before upgrade")
        expected = self.store.rows("SELECT body FROM sessions WHERE id=?", (review["id"],))[0][0]
        self.store.execute("DELETE FROM meta WHERE key IN ('graded_session','reviews_session','lessons_session','study_mode_references')")
        self.restart()
        self.assertEqual(review["id"], self.store.get("reviews_session"))
        self.assertEqual(review["id"], self.store.get("graded_session"))
        self.assertEqual(expected, self.store.rows("SELECT body FROM sessions WHERE id=?", (review["id"],))[0][0])
        self.assertEqual("saved before upgrade", self.engine.saved_session("reviews")["draft"])
        self.restart()
        self.assertEqual(expected, self.store.rows("SELECT body FROM sessions WHERE id=?", (review["id"],))[0][0])

    def test_migration_recovers_both_old_graded_records_while_practice_stays_active(self):
        review = self.engine.start("reviews", 1)
        self.engine.draft("old review")
        lesson = self.engine.start("lessons", 1)
        practice = self.engine.start("practice", 1, [3])
        original = [tuple(row) for row in self.store.rows("SELECT id,body FROM sessions ORDER BY id")]
        self.store.execute("DELETE FROM meta WHERE key IN ('reviews_session','lessons_session','study_mode_references')")
        self.restart()
        self.assertEqual(original, [tuple(row) for row in self.store.rows("SELECT id,body FROM sessions ORDER BY id")])
        self.assertEqual(practice["id"], self.store.get("active_session"))
        self.assertEqual(review["id"], self.engine.saved_session("reviews")["id"])
        self.assertEqual(lesson["id"], self.engine.saved_session("lessons")["id"])
        self.assertEqual(lesson["id"], self.engine.saved_session("resume")["id"])

    def test_migration_failure_rolls_back_every_reference_without_touching_answers(self):
        self.engine.start("reviews", 1)
        self.engine.draft("migration must retain me")
        self.engine.start("lessons", 1)
        self.store.execute("DELETE FROM meta WHERE key IN ('reviews_session','lessons_session','study_mode_references')")
        before = list(self.store.db.iterdump())
        original = self.store.set
        def fail(key, value):
            original(key, value)
            if key == "lessons_session":
                raise OSError("Authored interruption during reference migration")
        with patch.object(self.store, "set", side_effect=fail), self.assertRaises(OSError):
            with self.store.transaction():
                self.store._migrate_study_references()
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.restart()
        self.assertEqual("migration must retain me", self.engine.saved_session("reviews")["draft"])

    def test_remote_kind_change_cannot_create_second_graded_owner(self):
        lesson = self.engine.start("lessons", 1)
        subject_id = lesson["subject"]["id"]
        assignment = self.store.related("assignment", subject_id)
        assignment["data"].update(started_at=stamp(NOW - 500), available_at=stamp(NOW - 1), srs_stage=1)
        self.store.put(assignment)
        self.assertNotIn(subject_id, {subject["id"] for _, subject in self.engine._study_candidates("reviews")})
        self.engine.start("reviews", 5)
        self.assertNotIn(subject_id, {item["subject_id"] for item in self.store.session()["queue"]})
        self.assertEqual(lesson["id"], self.engine.saved_session("lessons")["id"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_failed_new_mode_rolls_back_references_and_retains_answer(self):
        review = self.engine.start("reviews", 1)
        self.engine.draft("keep review")
        before = list(self.store.db.iterdump())
        original = self.store.execute
        def fail(sql, args=()):
            if sql.startswith("INSERT INTO commands"):
                raise OSError("Authored crash before reply commit")
            return original(sql, args)
        with patch.object(self.store, "execute", side_effect=fail), self.assertRaises(OSError):
            self.engine.command("new-lessons", "start", {"mode": "lessons", "limit": 1})
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(review["id"], self.engine.saved_session("resume")["id"])

    def test_invalid_mode_cannot_select_lessons_or_write_progress(self):
        for mode in ("lesson", "listening", "", None, True):
            with self.subTest(mode=mode):
                before = list(self.store.db.iterdump())
                with self.assertRaises(UserError) as failure:
                    self.engine.start(mode)
                self.assertEqual("invalid_mode", failure.exception.code)
                self.assertEqual(before, list(self.store.db.iterdump()))
        self.engine.start("reviews", 1)
        broken = self.store.session()
        broken["mode"] = "listening"
        self.store.execute("UPDATE sessions SET body=? WHERE id=?", (json.dumps(broken), broken["id"]))
        for action in (lambda: self.engine.answer("ground"), self.engine.advance, self.engine.correct):
            with self.assertRaises(UserError) as failure:
                action()
            self.assertEqual("invalid_mode", failure.exception.code)
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_inactive_reset_updates_do_not_change_latest_mode_or_active_practice(self):
        review = self.engine.start("reviews", 1)
        lesson = self.engine.start("lessons", 1)
        practice = self.engine.start("practice", 1, [3])
        old = self.store.session(review["id"])
        old.update(phase="complete", invalidated="Account reset")
        self.store.save_session(old, activate=False)
        self.assertEqual(practice["id"], self.store.get("active_session"))
        self.assertEqual(lesson["id"], self.store.get("graded_session"))
        self.assertEqual(lesson["id"], self.engine.saved_session("resume")["id"])

    def test_all_unfinished_sessions_and_written_aliases_protect_automatic_surfaces(self):
        # Fix the review to kanji mountain; an authored vocabulary alias is a
        # different ID and may otherwise appear in automatic lesson selection.
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != 2:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)
        alias = self.store.subject(8)
        alias["data"]["characters"] = "山"
        self.store.put(alias)
        review = self.engine.start("reviews", 1)
        lesson = self.engine.start("lessons", 1)
        self.engine.start("practice", 1, [3])
        protected, _ = _sessions(self.engine)
        lesson_id = self.store.session(lesson["id"])["queue"][0]["subject_id"]
        self.assertTrue({2, 8, lesson_id}.issubset(protected))
        self.assertNotIn(8, {s["id"] for _, s in self.engine._study_candidates("lessons")})
        host = self.store.subject(16)
        host["data"]["amalgamation_subject_ids"] = [2, 8, lesson_id]
        self.store.put(host)
        self.assertEqual([], self.engine.details(16)["related"])
        self.store.set("pinned_subjects", [2, 8, lesson_id])
        cards = catalogue(self.engine, group="saved")["items"]
        self.assertTrue(all(item["spoilers_hidden"] and not item["meaning"] for item in cards))
        # Deliberate lookup and explicit ungraded selection retain their
        # established policy; automatic suggestions never reveal these items.
        self.assertTrue(self.engine.details(2)["meanings"])
        self.finish(self.engine.start("practice", 1, [2], replace_practice=True))
        self.engine.start("practice")
        self.assertTrue(protected.isdisjoint(item["subject_id"] for item in self.store.session()["queue"]))
        self.assertEqual(review["id"], self.engine.saved_session("reviews")["id"])


if __name__ == "__main__":
    unittest.main()
