"""Hot-path protocol tests: durable answers before compact, ordered updates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import EngineFixture, NOW
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from worker import Worker


class SessionRevisionTests(EngineFixture, unittest.TestCase):
    def test_monotonic_revision_covers_edits_answers_corrections_and_navigation(self):
        revisions = []
        def record():
            state = self.engine.session_state()
            revisions.append(state["session_revision"])
            self.assertEqual(state["session_revision"], state["session"]["revision"])
        self.engine.start("practice", 1, [1]); record()
        self.engine.draft("saved draft"); record()
        self.engine.answer("incorrect fixture"); record()
        self.engine.correct(); record()
        self.engine.advance(); record()
        self.assertEqual(sorted(set(revisions)), revisions)
        self.assertEqual(len(revisions), len(set(revisions)))

    def test_revision_persists_across_restart_and_mode_switch(self):
        self.engine.start("reviews", 1)
        original = self.engine.session_state()["session_revision"]
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.assertEqual(original, self.engine.session_state()["session_revision"])
        self.engine.start("practice", 1, [2])
        self.assertGreater(self.engine.session_state()["session_revision"], original)
        self.assertTrue(self.engine.session_state()["paused_graded"])

    def test_failed_transaction_rolls_back_revision_and_session_together(self):
        self.engine.start("practice", 1, [1])
        before = self.engine.session_state()
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.engine.draft("must roll back")
                raise RuntimeError("authored interruption")
        self.assertEqual(before, self.engine.session_state())

    def test_duplicate_command_does_not_increment_revision_or_regrade(self):
        self.engine.start("practice", 1, [1])
        first = self.engine.command("same-answer", "answer", {"text": "incorrect fixture"})
        revision = self.engine.session_state()["session_revision"]
        again = self.engine.command("same-answer", "answer", {"text": "different ignored text"})
        self.assertEqual(first, again)
        self.assertEqual(revision, self.engine.session_state()["session_revision"])

    def test_new_personal_data_has_new_epoch_even_for_same_account_name(self):
        self.engine.start("practice", 1, [1])
        before = self.engine.session_state()
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(before["session_epoch"], self.store.get("session_epoch"))
        with self.store.transaction():
            self.store.execute("DELETE FROM meta")
            self.store.execute("DELETE FROM sessions")
        self.store.close()
        self.store = Store(self.path)
        populate(self.store, NOW)
        self.engine = Engine(self.store, clock=lambda: NOW)
        after = self.engine.session_state()
        self.assertNotEqual(before["session_epoch"], after["session_epoch"])
        self.assertEqual(0, after["session_revision"])
        self.assertIsNone(after["session"])


class SessionProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.messages = []
        self.worker = Worker(Path(self.temp.name), self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.worker.readiness.refresh = Mock()
        self.sequence = 0

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def send(self, method, args=None):
        self.messages.clear()
        self.sequence += 1
        rid = "fixture-" + str(self.sequence)
        self.worker.handle({"v": 1, "id": rid, "method": method, "args": args or {}})
        return next(item["data"] for item in self.messages if item.get("id") == rid)

    def assert_session_only(self):
        events = [item for item in self.messages if "event" in item]
        self.assertEqual(["session"], [item["event"] for item in events])
        self.assertEqual({"session", "session_revision", "session_epoch", "paused_graded"}, set(events[0]["data"]))
        self.assertEqual(self.worker.engine.session_state(), events[0]["data"])
        self.assertNotIn("event", self.messages[0])  # Durable response comes first.
        self.worker.readiness.refresh.assert_not_called()

    def test_start_answer_retry_correction_and_finish_skip_catalogue_reads(self):
        with patch.object(self.worker.engine, "snapshot", side_effect=AssertionError("hot path scanned catalogue")):
            self.send("start", {"mode": "practice", "subjects": [2], "limit": 1})
            self.assert_session_only()
            self.send("answer", {"text": ""})
            self.assert_session_only()
            self.send("answer", {"text": "incorrect fixture"})
            self.assert_session_only()
            self.send("correct")
            self.assert_session_only()
            self.send("finish")
            self.assert_session_only()
            self.send("advance")  # Meaning acknowledged; reading remains.
            self.assert_session_only()

    def test_lesson_navigation_uses_small_durable_session_events(self):
        with patch.object(self.worker.engine, "snapshot", side_effect=AssertionError("lesson scanned catalogue")):
            self.send("start", {"mode": "lessons", "limit": 1})
            self.send("lesson_next")
            self.assert_session_only()

    def test_completed_subject_still_refreshes_counts_and_pending_work(self):
        view = self.send("start", {"mode": "practice", "subjects": [1], "limit": 1})
        self.send("answer", {"text": view["subject"]["meanings"][0]})
        self.send("advance")
        state = next(item["data"] for item in self.messages if item.get("event") == "state")
        self.assertEqual(1, state["session"]["completed"])
        self.assertEqual("complete", state["session"]["phase"])
        self.assertTrue(state["activity"])
        self.worker.readiness.refresh.assert_called()

    def test_drafts_and_recap_are_read_only_from_state_event_perspective(self):
        view = self.send("start", {"mode": "practice", "subjects": [1], "limit": 1})
        self.send("draft", {"text": "kept locally"})
        self.assertFalse(any("event" in item for item in self.messages))
        self.send("answer", {"text": view["subject"]["meanings"][0]})
        self.send("advance")
        with patch.object(self.worker.engine, "snapshot", side_effect=AssertionError("recap scanned catalogue")):
            recap = self.send("session_report")
        self.assertEqual(1, recap["counts"]["completed"])
        self.assertFalse(any("event" in item for item in self.messages))

    def test_replayed_old_answer_response_emits_latest_durable_session(self):
        self.send("start", {"mode": "practice", "subjects": [2], "limit": 1})
        request = {"v": 1, "id": "replayed", "method": "answer", "args": {"text": "incorrect fixture"}}
        self.worker.handle(request)
        self.send("correct")
        latest = self.worker.engine.session_state()
        self.messages.clear()
        self.worker.handle(request)
        event = next(item["data"] for item in self.messages if item.get("event") == "session")
        response = next(item["data"] for item in self.messages if item.get("id") == "replayed")
        self.assertLess(response["revision"], latest["session_revision"])
        self.assertEqual(latest, event)


if __name__ == "__main__":
    unittest.main()
