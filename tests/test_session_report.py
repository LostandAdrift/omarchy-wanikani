import copy
import json
import unittest
from unittest.mock import patch

from test_backend import EngineFixture
from wanikani.common import UserError
from wanikani.session_report import report
from wanikani.store import Store
from wanikani.engine import Engine


class SessionReportTests(EngineFixture, unittest.TestCase):
    def finish_current(self, view):
        while view["phase"] == "lesson":
            view = self.engine.lesson_next()
        while view["phase"] != "complete":
            if view["phase"] == "feedback":
                view = self.engine.advance()
            else:
                view = self.engine.answer(self.correct_answer(view))
        return view

    def test_only_ended_session_has_recap(self):
        for session_id in (None, "missing"):
            with self.assertRaises(UserError):
                report(self.engine, session_id)
        self.engine.start("reviews", 1)
        with self.assertRaises(UserError):
            report(self.engine)

    def test_unacknowledged_final_feedback_does_not_expose_recap(self):
        view = self.engine.start("practice", 1, [1])
        self.engine.answer(self.correct_answer(view))
        with self.assertRaises(UserError):
            report(self.engine)
        self.engine.advance()
        self.assertEqual(1, report(self.engine)["counts"]["completed"])

    def test_errors_and_corrections_come_from_durable_final_counts(self):
        view = self.engine.start("practice", 1, [2])
        view = self.engine.answer("fixture wrong")
        view = self.engine.advance()
        view = self.engine.answer("another incorrect fixture")
        self.engine.correct()
        view = self.engine.advance()
        self.finish_current(view)
        recap = report(self.engine)
        self.assertEqual({"meaning": 1, "reading": 0, "total": 1}, recap["items"][0]["errors"])
        self.assertEqual(1, recap["typo_corrections"])
        self.assertEqual([2], recap["mistake_ids"])
        self.assertNotIn("fixture wrong", json.dumps(recap))
        self.assertEqual("ungraded", recap["items"][0]["state"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_corrected_typo_alone_is_not_suggested_for_mistake_practice(self):
        self.engine.start("practice", 1, [1])
        self.engine.answer("fixture wrong")
        self.engine.correct()
        self.finish_current(self.engine.advance())
        recap = report(self.engine)
        self.assertEqual([], recap["mistake_ids"])
        self.assertEqual(1, recap["counts"]["without_mistakes"])

    def test_each_submission_status_is_from_exact_session_operation(self):
        session = self.complete("reviews", 1)
        item_id = self.store.session()["queue"][0]["subject_id"]
        operation = session["id"] + ":" + str(item_id)
        for state in ("pending", "inflight", "uncertain", "conflicted", "blocked", "confirmed", "discarded"):
            self.store.execute("UPDATE outbox SET state=? WHERE id=?", (state, operation))
            recap = report(self.engine, session["id"])
            self.assertEqual(state, recap["items"][0]["state"])
            self.assertEqual(1, recap["counts"]["completed"])
        self.store.execute("DELETE FROM outbox WHERE id=?", (operation,))
        self.assertEqual("missing", report(self.engine)["items"][0]["state"])

    def test_demo_does_not_claim_account_confirmation(self):
        self.engine.demo = True
        self.complete("lessons", 1)
        recap = report(self.engine)
        self.assertEqual("confirmed", recap["items"][0]["state"])
        self.assertEqual("Confirmed locally in demo", recap["items"][0]["status_label"])

    def test_lost_entitlement_hides_content_but_retains_local_counts(self):
        self.finish_current(self.engine.start("practice", 1, [2]))
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 0
        self.store.set("user", user)
        recap = report(self.engine)
        self.assertEqual(1, recap["counts"]["completed"])
        self.assertFalse(recap["items"][0]["subject"]["accessible"])
        self.assertEqual([], recap["practice_ids"])
        for content in ("mountain", "山", "さん"):
            self.assertNotIn(content, json.dumps(recap, ensure_ascii=False))

    def test_missing_required_content_disables_practice(self):
        self.finish_current(self.engine.start("practice", 1, [2]))
        item = self.store.subject(2)
        item["data"]["readings"] = []
        self.store.put(item)
        recap = report(self.engine)
        self.assertEqual([], recap["practice_ids"])
        self.assertFalse(recap["items"][0]["practice_ready"])

    def test_reset_or_finish_boundary_does_not_count_unfinished_subjects(self):
        self.engine.start("reviews", 5)
        saved = self.store.session()
        saved["phase"] = "complete"
        saved["invalidated"] = "Authored reset"
        self.store.save_session(saved)
        recap = report(self.engine)
        self.assertEqual(0, recap["counts"]["completed"])
        self.assertEqual(5, recap["counts"]["not_completed"])
        self.assertEqual([], recap["practice_ids"])
        self.assertTrue(all(item["subject"]["spoilers_hidden"] for item in recap["items"]))

    def test_paused_graded_subjects_remain_hidden_in_practice_recap(self):
        graded = self.engine.start("reviews", 5)
        subject_id = graded["subject"]["id"]
        self.engine.draft("preserved partial")
        self.finish_current(self.engine.start("practice", 1, [subject_id]))
        recap = report(self.engine)
        self.assertTrue(recap["items"][0]["subject"]["spoilers_hidden"])
        self.assertEqual("", recap["items"][0]["subject"]["meaning"])
        self.assertEqual("preserved partial", self.engine.start("resume")["draft"])

    def test_recap_is_read_only_and_survives_restart(self):
        completed = self.complete("reviews", 5)
        before = list(self.store.db.iterdump())
        recap = report(self.engine)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store)
        self.assertEqual(recap, report(self.engine, completed["id"]))

    def test_old_recap_never_replaces_current_session(self):
        old = self.complete("reviews", 1)
        new = self.engine.start("practice", 1, [2])
        report(self.engine, old["id"])
        self.assertEqual(new["id"], self.store.session()["id"])

    def test_input_and_corrupt_counts_fail_without_writes(self):
        self.complete("reviews", 1)
        for value in (True, 1, "", "x" * 161, {}):
            with self.assertRaises(UserError):
                report(self.engine, value)
        saved = self.store.session()
        saved["queue"][0]["errors"]["meaning"] = -1
        self.store.save_session(saved)
        with self.assertRaises(UserError):
            report(self.engine)


if __name__ == "__main__":
    unittest.main()
