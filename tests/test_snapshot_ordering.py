"""Late account snapshots cannot inherit freshness from a newer study session."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.demo import populate
from worker import Worker


class SnapshotOrderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.messages = []
        self.worker = Worker(Path(self.temp.name), self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.worker.readiness.refresh = Mock()
        self.worker.readiness.get = Mock(return_value={})

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def test_late_counts_keep_older_generation_even_when_session_is_latest(self):
        engine = self.worker.engine
        view = engine.start("reviews", 1)
        while True:
            answer = view["subject"]["meanings"][0] if view["part"] == "meaning" else next(
                item["reading"] for item in view["subject"]["readings"] if item["accepted"])
            view = engine.answer(answer)
            session = engine.store.session()
            entry = session["queue"][session["index"]]
            if all(done or part == session["part"] for part, done in entry["parts"].items()):
                break
            view = engine.advance()
        counts_captured, release, completed = threading.Event(), threading.Event(), threading.Event()
        original = engine.session_state
        errors = []
        def delayed_session():
            if threading.current_thread().name == "old-account-snapshot":
                counts_captured.set()
                if not release.wait(5):
                    raise AssertionError("Snapshot ordering fixture timed out")
            return original()
        def emit_old():
            try:
                self.worker.changed()
            except BaseException as error:
                errors.append(error)
        def finish_subject():
            try:
                self.worker.handle({"v": 1, "id": "finish-authored-subject", "method": "advance"})
            except BaseException as error:
                errors.append(error)
            finally:
                completed.set()
        with patch.object(engine, "session_state", side_effect=delayed_session):
            old = threading.Thread(target=emit_old, name="old-account-snapshot")
            old.start()
            self.assertTrue(counts_captured.wait(5))
            new = threading.Thread(target=finish_subject)
            new.start()
            try:
                self.assertTrue(completed.wait(5), "A slow snapshot blocked study instead of only allocating its revision")
            finally:
                release.set()
                old.join(5)
                new.join(5)
        self.assertFalse(errors, errors)
        states = [message["data"] for message in self.messages if message.get("event") == "state"]
        self.assertEqual(2, len(states))
        fresh, stale = states
        self.assertEqual((4, 1), (fresh["reviews"], fresh["pending"]))
        self.assertEqual((5, 0), (stale["reviews"], stale["pending"]))
        self.assertEqual(fresh["session_revision"], stale["session_revision"])
        self.assertEqual(1, stale["session"]["completed"])
        self.assertLess(stale["state_revision"], fresh["state_revision"])

    def test_full_snapshot_sequence_is_monotonic_and_fresh_after_worker_restart(self):
        first = self.worker.snapshot()["state_revision"]
        second = self.worker.snapshot()["state_revision"]
        self.assertGreater(second, first)
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.worker = Worker(Path(self.temp.name), self.messages.append)
        self.worker.readiness.refresh = Mock()
        self.worker.readiness.get = Mock(return_value={})
        self.assertEqual(first, self.worker.snapshot()["state_revision"])

    def test_compact_session_updates_do_not_claim_a_new_account_snapshot(self):
        revision = self.worker.snapshot()["state_revision"]
        self.worker.handle({"v": 1, "id": "start-authored-practice", "method": "start",
            "args": {"mode": "practice", "subjects": [2], "limit": 1}})
        session_event = next(message for message in self.messages if message.get("event") == "session")
        self.assertNotIn("state_revision", session_event["data"])
        self.assertEqual(revision + 1, self.worker.snapshot()["state_revision"])


if __name__ == "__main__":
    unittest.main()
