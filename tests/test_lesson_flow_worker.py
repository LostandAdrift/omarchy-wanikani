"""Guided lesson commands commit before compact worker replies and events."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.common import UserError
from wanikani.demo import populate
from wanikani.store import Store
from worker import Worker


class LessonFlowWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wanikani-lesson-worker-")
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(Path(self.directory.name), self.messages.append)
        self.engine = self.worker.engine
        self.store = self.engine.store
        populate(self.store, NOW)
        self.engine.clock = lambda: NOW
        self.view = self.engine.start("lessons", subjects=[6])
        self.worker.readiness.refresh = Mock()
        self.worker.changed = Mock(side_effect=AssertionError("Discovery must not rebuild catalogue state"))
        self.worker.sync = Mock()
        guard = patch("socket.create_connection", side_effect=AssertionError("Authored lesson worker must not contact a network"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.store.close()
        self.directory.cleanup()

    def request(self, action, rid="step", view=None, **extra):
        current = view or self.engine.session_view()
        self.messages.clear()
        request = {"v": 1, "id": rid, "method": "lesson_navigate", "args": {
            "action": action, "session_id": current["id"], "revision": current["revision"], **extra}}
        try:
            self.worker.handle(request)
        except UserError as error:
            self.worker.reply_error(rid, error)
        replies = [value for value in self.messages if value.get("id") == rid]
        self.assertEqual(1, len(replies))
        return replies[0]

    def test_durable_step_precedes_reply_and_small_session_event(self):
        original_emit = self.worker.emit
        def emit(value):
            if value.get("id") == "step":
                observer = Store(self.store.path)
                try:
                    saved = observer.session(self.view["id"])
                    self.assertEqual("reading", saved["lesson_step"])
                    self.assertEqual(value["data"]["revision"], saved["revision"])
                    self.assertEqual(1, observer.rows("SELECT COUNT(*) FROM commands WHERE id='step'")[0][0])
                finally:
                    observer.close()
            original_emit(value)
        self.worker.emit = emit
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("No full snapshot for a step")):
            reply = self.request("next")
        self.assertTrue(reply["ok"])
        self.assertEqual(["session"], [value["event"] for value in self.messages if "event" in value])
        self.assertEqual(reply["data"]["lesson_flow"], self.messages[1]["data"]["session"]["lesson_flow"])
        self.assertEqual(NOW, self.store.get("last_study_at"))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.worker.readiness.refresh.assert_not_called()
        self.worker.sync.run.assert_not_called()

    def test_quiz_transition_is_session_only_even_with_completed_work_pending(self):
        self.request("next")
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)",
            ("already-pending", "review", 3, "pending", "{}", "2026-09-01T00:00:00Z", "Authored prior work"))
        reply = self.request("quiz", rid="quiz")
        self.assertTrue(reply["ok"])
        self.assertEqual("question", reply["data"]["phase"])
        self.assertIsNone(reply["data"]["lesson_flow"])
        self.assertEqual(["session"], [value["event"] for value in self.messages if "event" in value])
        self.assertEqual(1, self.store.rows("SELECT COUNT(*) FROM outbox")[0][0])
        self.worker.sync.run.assert_not_called()
        self.worker.changed.assert_not_called()

    def test_stale_or_unknown_step_is_one_error_without_state_events(self):
        old = self.view
        self.request("next")
        before = list(self.store.db.iterdump())
        reply = self.request("quiz", rid="stale", view=old)
        self.assertFalse(reply["ok"])
        self.assertEqual("stale_session", reply["error"]["code"])
        self.assertEqual(1, len(self.messages))
        self.assertEqual(before, list(self.store.db.iterdump()))
        reply = self.request("quiz", rid="extra", target_subject=7)
        self.assertFalse(reply["ok"])
        self.assertEqual("invalid_request", reply["error"]["code"])
        self.assertEqual(1, len(self.messages))
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_sync_ownership_does_not_block_local_discovery_or_start_network_work(self):
        self.worker.job_lock.acquire()
        try:
            reply = self.request("next")
            self.assertTrue(reply["ok"])
            self.assertEqual("reading", reply["data"]["lesson_flow"]["step"])
            self.assertTrue(self.worker.job_lock.locked())
        finally:
            self.worker.job_lock.release()
        self.worker.sync.run.assert_not_called()

    def test_duplicate_reply_keeps_the_current_step_and_revision(self):
        first = self.request("next")
        saved = self.store.session()
        second = self.request("quiz", view=self.view)
        self.assertTrue(second["ok"])
        self.assertEqual(first["data"], second["data"])
        self.assertEqual(saved, self.store.session())
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))


if __name__ == "__main__":
    unittest.main()
