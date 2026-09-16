"""All-due sessions use authored cache data only; no live account or transport."""
import copy
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, Engine, Store, UserError, NOW, stamp
from wanikani import insights, kanji_examples, media_plan, session_report, trail


class AllReviewTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.now = NOW
        self.engine.clock = lambda: self.now
        for sid in range(1001, 1031):
            self.add_subject(sid)
        self.due = self.engine.assignments("reviews", count_only=True)

    def add_subject(self, sid, due=NOW - 1):
        subject = copy.deepcopy(self.store.subject(4))
        subject["id"] = sid
        subject["data"]["characters"] = "水" + str(sid)
        self.store.put(subject)
        assignment = copy.deepcopy(self.store.resource("assignment", 104))
        assignment["id"] = 10000 + sid
        assignment["data"].update(subject_id=sid, available_at=stamp(due))
        self.store.put(assignment)

    def finish_session(self):
        view = self.engine.session_view()
        while view["phase"] != "complete":
            if view["phase"] == "question":
                view = self.engine.answer(self.correct_answer(view))
            view = self.engine.advance()
        return view

    def test_all_means_every_eligible_subject_not_twenty(self):
        view = self.engine.command("all-start", "start", {"mode": "reviews", "all_reviews": True})
        self.assertEqual(self.due, view["total"])
        self.assertGreater(view["total"], 20)
        self.assertTrue(view["all_reviews"])
        queue = self.store.session()["queue"]
        self.assertEqual(self.due, len({entry["subject_id"] for entry in queue}))
        replay = self.engine.command("all-start", "start", {"mode": "reviews", "all_reviews": True})
        self.assertEqual(view, replay)
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_batch_default_explicit_override_and_preference_persist(self):
        self.assertFalse(self.engine.settings()["review_all"])
        self.assertEqual(5, self.engine.start("reviews")["total"])
        self.finish_session()
        self.engine.set_settings({"review_all": True})
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.assertTrue(self.engine.settings()["review_all"])
        batch = self.engine.start("reviews", 10)
        self.assertEqual(10, batch["total"])
        self.assertFalse(batch["all_reviews"])
        self.finish_session()
        self.assertEqual(self.due - 15, self.engine.start("reviews")["total"])

    def test_reopen_preserves_exact_stack_feedback_draft_and_errors(self):
        self.engine.start("reviews", all_reviews=True)
        self.engine.answer("incorrect authored answer")
        expected = self.store.session()
        self.engine.set_settings({"review_all": False})
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        resumed = self.engine.start("reviews", 5, all_reviews=False)
        self.assertEqual((expected["id"], self.due, 1, "feedback"),
            (resumed["id"], resumed["total"], resumed["errors"], resumed["phase"]))
        actual = self.store.session()
        self.assertEqual({k:v for k,v in expected.items() if k != "revision"},
            {k:v for k,v in actual.items() if k != "revision"})
        self.assertTrue(self.engine.session_state()["saved_sessions"]["reviews"]["all_reviews"])

    def test_newly_due_or_newly_cached_items_do_not_extend_the_stack(self):
        self.add_subject(2001, NOW + 30)
        self.engine.start("reviews", all_reviews=True)
        expected = self.store.session()["queue"]
        self.now += 60
        self.add_subject(2002)
        resumed = self.engine.start("reviews", all_reviews=True)
        self.assertEqual(self.due, resumed["total"])
        self.assertEqual(expected, self.store.session()["queue"])

    def test_finish_batch_keeps_errors_commits_once_and_leaves_rest_due(self):
        self.engine.start("reviews", all_reviews=True)
        self.engine.answer("incorrect authored answer")
        self.engine.finish()
        self.assertEqual(5, self.engine.session_view()["total"])
        self.assertEqual(1, self.engine.session_view()["errors"])
        self.engine.advance()
        completed = self.finish_session()
        self.assertEqual(5, completed["completed"])
        self.assertEqual(5, len(self.store.rows("SELECT * FROM outbox")))
        self.assertEqual(self.due - 5, self.engine.assignments("reviews", count_only=True))
        resumed = self.engine.start("reviews", all_reviews=True)
        self.assertEqual(self.due - 5, resumed["total"])
        self.assertNotEqual(completed["id"], resumed["id"])

    def test_all_completion_recap_pages_and_local_history_include_large_session(self):
        self.engine.start("reviews", all_reviews=True)
        completed = self.finish_session()
        self.assertEqual(self.due, completed["completed"])
        self.assertEqual(self.due, len(self.store.rows("SELECT * FROM outbox")))
        first = session_report.report(self.engine)
        second = session_report.report(self.engine, offset=20)
        self.assertEqual(self.due, first["counts"]["completed"])
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(20, len(first["items"]))
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(self.due, len(first["items"]) + len(second["items"]))
        self.assertLessEqual(len(first["practice_ids"]), 20)
        self.assertFalse(set(first["practice_ids"]) & set(second["practice_ids"]))
        digest = insights.overview(self.engine, timezone="UTC", now=self.now)
        self.assertEqual(1, digest["windows"]["7"]["sessions_completed"]["reviews"])
        self.assertEqual(self.due, digest["windows"]["7"]["subject_completions"]["reviews"])
        for value in (-1, True, self.due, "20"):
            with self.assertRaises(UserError):
                session_report.report(self.engine, offset=value)

    def test_stack_protection_and_media_priority_extend_past_first_twenty(self):
        self.engine.start("reviews", all_reviews=True)
        queue = self.store.session()["queue"]
        ids = {entry["subject_id"] for entry in queue}
        self.assertEqual(ids, trail._protected(self.engine))
        active = media_plan._active_subjects(self.store)
        self.assertEqual(ids, set(active))
        with self.assertRaises(UserError) as error:
            kanji_examples._protection(self.engine, None, queue[-1]["subject_id"])
        self.assertEqual("protected_study", error.exception.code)
        # It must recognize the protected subject, not reject the queue as damaged.
        self.assertIn("Another saved question", str(error.exception))

    def test_pending_inaccessible_and_missing_content_are_excluded(self):
        pending = 1001
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)",
            ("pending-fixture", "review", pending, "uncertain", "{}", stamp(NOW), "fixture"))
        hidden = self.store.subject(1002)
        hidden["data"]["hidden_at"] = stamp(NOW)
        self.store.put(hidden)
        invalid = self.store.subject(1003)
        invalid["data"]["meanings"] = []
        self.store.put(invalid)
        view = self.engine.start("reviews", all_reviews=True)
        ids = {entry["subject_id"] for entry in self.store.session()["queue"]}
        self.assertFalse({1001, 1002, 1003} & ids)
        self.assertEqual(self.due - 3, view["total"])

    def test_invalid_all_requests_and_oversized_unmarked_sessions_fail_closed(self):
        before = list(self.store.db.iterdump())
        for mode, value in (("reviews", "true"), ("reviews", 1), ("lessons", True), ("practice", True)):
            with self.assertRaises(UserError):
                self.engine.start(mode, all_reviews=value)
            self.assertEqual(before, list(self.store.db.iterdump()))
        self.engine.start("reviews", all_reviews=True)
        session = self.store.session()
        del session["all_reviews"]
        self.store.save_session(session)
        self.assertIsNone(trail._protected(self.engine))

    def test_oversized_all_stack_rolls_back_without_truncation(self):
        before = list(self.store.db.iterdump())
        with patch("wanikani.engine.MAX_REVIEW_SESSION", 25), self.assertRaises(UserError):
            self.engine.start("reviews", all_reviews=True)
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_all_start_failure_rolls_back_entire_saved_queue(self):
        before = list(self.store.db.iterdump())
        original = self.store.save_session
        def interrupted(value):
            original(value)
            raise RuntimeError("authored persistence interruption")
        with patch.object(self.store, "save_session", side_effect=interrupted), self.assertRaises(RuntimeError):
            self.engine.command("interrupted-start", "start", {"mode": "reviews", "all_reviews": True})
        self.assertEqual(before, list(self.store.db.iterdump()))
