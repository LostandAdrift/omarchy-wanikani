"""Media jobs remain local, responsive, and isolated from account replacement."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW, UserError
from wanikani.demo import populate
from worker import Worker


class PronunciationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(Path(self.temp.name), self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.readiness_refreshed = threading.Event()
        self.worker.readiness.refresh = Mock(side_effect=lambda **kwargs: self.readiness_refreshed.set())
        self.worker.changed = Mock()
        self.worker.token = "authored-test-token"
        guard = patch("socket.create_connection", side_effect=AssertionError("Worker fixture must never connect to network"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def send(self, method, args=None, rid=None):
        self.worker.handle({"v": 1, "id": rid or method, "method": method, "args": args or {}})

    def reply(self, rid):
        return next(message for message in self.messages if message.get("id") == rid)

    def wait_lock(self, lock):
        self.assertTrue(lock.acquire(timeout=3), "Fixture job did not finish")
        lock.release()

    @contextmanager
    def downloading(self, result=None):
        entered, release = threading.Event(), threading.Event()
        def prepare(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Authored media job timed out")
            return result or {"status": "not_cached", "subject_id": 4, "uri": None, "message": "Fixture not cached"}
        with patch("wanikani.pronunciation.prepare", side_effect=prepare) as requested:
            self.send("pronunciation_prepare", {"subject_id": 4}, "clip")
            try:
                self.assertTrue(entered.wait(3))
                yield requested, release
            finally:
                release.set()
                self.wait_lock(self.worker.audio_job_lock)
                if not self.worker.stopping:
                    self.assertTrue(self.readiness_refreshed.wait(3))

    def test_status_and_sample_are_read_only_without_heavy_state_events(self):
        before = list(self.worker.engine.store.db.iterdump())
        with patch.object(self.worker.engine, "snapshot", side_effect=AssertionError("Audio status must not build full state")):
            self.send("pronunciation", {"subject_id": 4})
            self.send("pronunciation_sample", {"voice_actor_id": 17})
        self.assertEqual("no_recording", self.reply("pronunciation")["data"]["status"])
        self.assertEqual("no_recording", self.reply("pronunciation_sample")["data"]["status"])
        self.assertEqual(before, list(self.worker.engine.store.db.iterdump()))
        self.worker.changed.assert_not_called()
        self.worker.readiness.refresh.assert_not_called()
        self.assertFalse(any("event" in message for message in self.messages))

    def test_every_account_or_cache_mutation_is_guarded_during_download(self):
        with self.downloading():
            before = list(self.worker.engine.store.db.iterdump())
            for method, args in (("authenticate", {"token": "authored-test-token"}),
                    ("use_demo", {"enabled": True}), ("disconnect", {}),
                    ("delete_data", {"confirmation": "DELETE", "discard_pending": True}),
                    ("clear_cache", {}), ("resolve", {"id": "authored-operation"})):
                with self.subTest(method=method), self.assertRaises(UserError) as failure:
                    self.send(method, args)
                self.assertEqual("busy", failure.exception.code)
            self.assertEqual(before, list(self.worker.engine.store.db.iterdump()))
            self.assertEqual("authored-test-token", self.worker.token)
            self.worker.keyring.get.assert_not_called()
            self.worker.keyring.set.assert_not_called()
            self.worker.keyring.delete.assert_not_called()
        self.assertTrue(self.reply("clip")["ok"])

    def test_answer_and_draft_remain_responsive_without_full_snapshot(self):
        self.worker.engine.start("practice", 1, [2])
        with self.downloading() as (_, release), \
                patch.object(self.worker.engine, "snapshot", side_effect=AssertionError("Answer should only publish its session")):
            self.send("draft", {"text": "unfinished"})
            self.send("answer", {"text": "wrong"})
            self.assertFalse(release.is_set())
            self.assertTrue(self.reply("draft")["data"]["saved"])
            self.assertEqual(("feedback", 1), (self.reply("answer")["data"]["phase"], self.reply("answer")["data"]["errors"]))
            self.assertEqual([], self.worker.engine.store.rows("SELECT * FROM outbox"))
        self.worker.changed.assert_not_called()
        self.assertEqual(["session"], [message["event"] for message in self.messages if "event" in message])

    def test_second_audio_request_is_busy_and_never_queues_a_retry(self):
        with self.downloading() as (requested, _):
            self.send("pronunciation_prepare", {"subject_id": 10}, "second")
            self.assertEqual("busy", self.reply("second")["error"]["code"])
            self.assertEqual(1, requested.call_count)
        self.assertEqual("not_cached", self.reply("clip")["data"]["status"])
        self.assertEqual(1, len([message for message in self.messages if message.get("id") == "clip"]))
        self.worker.changed.assert_not_called()
        self.worker.readiness.refresh.assert_called_once_with(force=True)

    def test_account_flag_is_set_before_authentication_thread_and_clears_after_failure(self):
        entered, release = threading.Event(), threading.Event()
        def authenticate(args):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Authentication fixture timed out")
            raise UserError("Authored authentication failure", "authentication")
        with patch.object(self.worker, "authenticate", side_effect=authenticate), \
                patch("wanikani.pronunciation.prepare") as prepare:
            self.send("authenticate", {"token": "authored-token"}, "auth")
            try:
                self.assertTrue(entered.wait(3))
                self.assertTrue(self.worker.account_job)
                with self.assertRaises(UserError) as failure:
                    self.send("pronunciation_prepare", {"subject_id": 4})
                self.assertEqual("busy", failure.exception.code)
                prepare.assert_not_called()
                self.assertFalse(self.worker.audio_job_lock.locked())
            finally:
                release.set()
                self.wait_lock(self.worker.job_lock)
        self.assertFalse(self.worker.account_job)
        self.assertEqual("authentication", self.reply("auth")["error"]["code"])

    def test_ordinary_sync_job_does_not_block_the_separate_audio_job(self):
        entered, release = threading.Event(), threading.Event()
        def ordinary_sync():
            entered.set()
            if not release.wait(5):
                raise AssertionError("Sync fixture timed out")
            return {"synced": True}
        self.worker.job("sync", ordinary_sync)
        try:
            self.assertTrue(entered.wait(3))
            self.assertFalse(self.worker.account_job)
            with self.downloading() as (_, audio_release):
                audio_release.set()
                self.wait_lock(self.worker.audio_job_lock)
                self.assertTrue(self.reply("clip")["ok"])
                self.assertFalse(release.is_set())
        finally:
            release.set()
            self.wait_lock(self.worker.job_lock)

    def test_errors_release_audio_guard_and_redact_exception_details(self):
        with patch("wanikani.pronunciation.prepare", side_effect=RuntimeError("PRIVATE-TOKEN-MARKER")):
            self.send("pronunciation_prepare", {"subject_id": 4})
            self.wait_lock(self.worker.audio_job_lock)
        response = self.reply("pronunciation_prepare")
        self.assertEqual("audio_error", response["error"]["code"])
        self.assertNotIn("PRIVATE-TOKEN", str(self.messages))
        self.worker.changed.assert_not_called()

    def test_worker_stop_suppresses_late_audio_reply_and_releases_guard(self):
        with self.downloading() as (_, release):
            self.worker.stopping = True
            release.set()
        self.assertFalse(any(message.get("id") == "clip" for message in self.messages))
        self.worker.readiness.refresh.assert_not_called()

    def test_media_initialization_failure_does_not_leave_account_actions_locked(self):
        with patch("worker.Synchronizer", side_effect=OSError("Authored unwritable media directory")):
            with self.assertRaises(OSError):
                self.send("pronunciation_prepare", {"subject_id": 4})
        self.assertFalse(self.worker.audio_job_lock.locked())

    def test_thread_start_failure_releases_audio_guard(self):
        with patch("worker.threading.Thread.start", side_effect=RuntimeError("Authored unavailable thread")):
            with self.assertRaises(RuntimeError):
                self.send("pronunciation_prepare", {"subject_id": 4})
        self.assertFalse(self.worker.audio_job_lock.locked())


if __name__ == "__main__":
    unittest.main()
