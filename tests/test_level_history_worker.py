"""The cached history route cannot mutate study, request API work or leak notes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.common import UserError, stamp
from wanikani.demo import populate
from worker import Worker


class LevelHistoryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(Path(self.directory.name), self.messages.append)
        self.engine = self.worker.engine
        self.engine.clock = lambda: NOW
        populate(self.engine.store, NOW)
        self.engine.store.set("user", {"object": "user", "data": {
            "id": "authored-history-worker", "username": "PRIVATE LEARNER", "level": 3,
            "subscription": {"type": "lifetime", "max_level_granted": 60}}})
        self.engine.store.set("account_id", "authored-history-worker")
        self.engine.store.db.execute("DELETE FROM resources WHERE kind='level_progression'")
        self.engine.store.set("cursor_level_progressions", stamp(NOW - 1))
        self.engine.start("practice", 1, [2])
        self.engine.draft("PRIVATE DRAFT")
        for identity in range(1, 16):
            began = NOW - (30 - identity) * 86400
            self.engine.store.put({"id": identity, "object": "level_progression", "data": {
                "level": 1, "created_at": stamp(began), "unlocked_at": stamp(began),
                "started_at": stamp(began + 60), "passed_at": stamp(began + 86400),
                "completed_at": None, "abandoned_at": None, "private_extra": "PRIVATE NOTE"}})
        self.worker.changed = Mock(side_effect=AssertionError("History cannot emit a full state"))
        self.worker.session_changed = Mock(side_effect=AssertionError("History cannot emit a session change"))
        self.worker.readiness.refresh = Mock(side_effect=AssertionError("History does not trigger media checks"))
        self.worker.snapshot = Mock(side_effect=AssertionError("History does not build a full snapshot"))
        guard = patch("socket.create_connection", side_effect=AssertionError("No network in history tests"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.engine.store.close()
        self.directory.cleanup()

    def request(self, args=None):
        self.messages.clear()
        self.worker.handle({"v": 1, "id": "history-fixture", "method": "level_history", "args": args or {}})
        self.assertEqual(1, len(self.messages))
        self.assertTrue(self.messages[0]["ok"])
        return self.messages[0]["data"]

    def test_paginated_history_is_only_metadata_and_preserves_private_saved_study(self):
        before = list(self.engine.store.db.iterdump())
        result = self.request({"offset": 0, "limit": 12})
        self.assertEqual((12, 15, 12), (len(result["items"]), result["total"], result["next_offset"]))
        self.assertEqual("WaniKani level progressions", result["source"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        second = self.request({"offset": 12, "limit": 12})
        self.assertEqual(3, len(second["items"]))
        self.assertFalse(second["has_more"])
        self.assertEqual(before, list(self.engine.store.db.iterdump()))

    def test_invalid_and_extra_arguments_cannot_forge_context_or_write(self):
        before = list(self.engine.store.db.iterdump())
        for args in ({"now": NOW}, {"account_id": "other"}, {"limit": True}, {"offset": -1}, {"limit": 51}):
            with self.subTest(args=args), self.assertRaises(UserError):
                self.request(args)
        self.assertEqual(before, list(self.engine.store.db.iterdump()))

    def test_unavailable_account_is_an_honest_empty_response(self):
        self.engine.store.set("account_id", "a-different-account")
        result = self.request()
        self.assertEqual(("unavailable", None, []), (result["status"], result["total"], result["items"]))
        self.assertFalse(result["history_complete"])

    def test_existing_sync_ownership_does_not_queue_or_start_account_work(self):
        self.worker.job_lock.acquire()
        self.engine.syncing = True
        try:
            result = self.request({"offset": 0, "limit": 12})
            self.assertEqual(12, len(result["items"]))
            self.assertFalse(result["cache_complete"])
            self.assertTrue(result["partial"])
            self.assertTrue(self.worker.job_lock.locked())
        finally:
            self.worker.job_lock.release()


if __name__ == "__main__":
    unittest.main()
