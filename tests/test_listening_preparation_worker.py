"""Preparation jobs use authored barriers, never live media or account IO."""
from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.common import UserError
from wanikani.demo import populate
from wanikani.store import Store
from worker import Worker, main


class ListeningPreparationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wanikani-prepare-worker-")
        self.path = Path(self.directory.name)
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(self.path, self.messages.append)
        self.engine = self.worker.engine
        populate(self.engine.store, NOW)
        self.engine.clock = lambda: NOW
        self.refreshed = threading.Event()
        self.worker.readiness.refresh = Mock(side_effect=lambda **kwargs: self.refreshed.set())
        self.worker.changed = Mock()
        self.worker.startup = Mock()
        guard = patch("socket.create_connection", side_effect=AssertionError("Authored worker must not contact a network"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.cancel_listening_preparation()
        self.wait_unlocked(self.worker.audio_job_lock)
        self.wait_unlocked(self.worker.job_lock)
        self.worker.readiness.stop()
        self.engine.store.close()
        self.directory.cleanup()

    @staticmethod
    def result(**extra):
        return {"status": "ready", "downloaded": 2, "already_cached": 1, "failed": 0,
            "skipped_budget": 0, "cancelled": False, "complete": True, "reason": "ready",
            "message": "These recordings are ready. Start listening when you choose.", **extra}

    def send(self, method, args=None, rid=None):
        self.worker.handle({"v": 1, "id": rid or method, "method": method, "args": args or {}})

    def reply(self, rid):
        matches = [message for message in self.messages if message.get("id") == rid]
        self.assertEqual(1, len(matches), "Each request must have one final reply")
        return matches[0]

    def wait_unlocked(self, lock):
        self.assertTrue(lock.acquire(timeout=5), "Authored job did not release its lock")
        lock.release()

    @contextmanager
    def preparing(self, result=None, progress_value=None, rid="prepare-one"):
        entered, release = threading.Event(), threading.Event()
        cancelled_functions = []
        def prepare(synchronizer, *, cancelled, progress):
            self.assertIs(synchronizer.engine, self.engine)
            cancelled_functions.append(cancelled)
            if progress_value is not None:
                progress(progress_value)
            entered.set()
            if not release.wait(5):
                raise AssertionError("Fixture did not release recording preparation")
            if cancelled():
                return self.result(status="cancelled", cancelled=True, complete=False, reason="cancelled")
            return result if result is not None else self.result()
        with patch("wanikani.listening_preparation.prepare", side_effect=prepare) as requested:
            self.send("listen_prepare", rid=rid)
            try:
                self.assertTrue(entered.wait(5), "Preparation did not begin")
                yield requested, release, cancelled_functions[0]
            finally:
                release.set()
                self.wait_unlocked(self.worker.audio_job_lock)
                if not self.worker.stopping:
                    self.assertTrue(self.refreshed.wait(5))

    def test_draft_and_answer_are_durable_while_preparation_is_waiting(self):
        session = self.engine.start("practice", 1, [2])
        with self.preparing() as (_, release, _), \
                patch.object(self.engine, "snapshot", side_effect=AssertionError("Answer must not build a catalogue snapshot")):
            self.send("draft", {"text": "authored partial"})
            self.send("answer", {"text": "wrong"})
            self.assertFalse(release.is_set(), "Answer finished only after preparation was released")
            self.assertTrue(self.reply("draft")["data"]["saved"])
            self.assertEqual("feedback", self.reply("answer")["data"]["phase"])
            observer = Store(self.engine.store.path)
            try:
                durable = observer.session(session["id"])
                self.assertEqual("wrong", durable["draft"])
                self.assertEqual(1, durable["queue"][0]["errors"]["meaning"])
            finally:
                observer.close()
            self.assertEqual([], self.engine.store.rows("SELECT * FROM outbox"))
        self.worker.changed.assert_not_called()
        self.assertEqual(["session"], [message["event"] for message in self.messages if message.get("event") != "listening_preparation" and "event" in message])

    def test_preparation_has_single_audio_ownership_and_no_queued_retry(self):
        with self.preparing() as (requested, _, _), patch("wanikani.pronunciation.prepare") as other_audio:
            self.send("listen_prepare", rid="second-preparation")
            self.send("pronunciation_prepare", {"subject_id": 4}, rid="other-audio")
            for rid in ("second-preparation", "other-audio"):
                self.assertEqual("busy", self.reply(rid)["error"]["code"])
            self.assertEqual(1, requested.call_count)
            other_audio.assert_not_called()
        self.assertTrue(self.reply("prepare-one")["ok"])
        self.worker.readiness.refresh.assert_called_once_with(force=True)
        self.worker.changed.assert_not_called()

    def test_an_existing_single_recording_download_blocks_preparation(self):
        self.worker.audio_job_lock.acquire()
        try:
            with patch("wanikani.listening_preparation.prepare") as prepare:
                self.send("listen_prepare")
                self.assertEqual("busy", self.reply("listen_prepare")["error"]["code"])
                prepare.assert_not_called()
                self.assertIsNone(self.worker.preparation_job)
        finally:
            self.worker.audio_job_lock.release()

    def test_account_and_cache_changes_are_blocked_without_credential_reads(self):
        with self.preparing():
            before = list(self.engine.store.db.iterdump())
            for method, args in (("authenticate", {"token": "authored-input"}), ("use_demo", {"enabled": True}),
                    ("disconnect", {}), ("delete_data", {"confirmation": "DELETE", "discard_pending": True}),
                    ("clear_cache", {}), ("resolve", {"id": "authored-operation"})):
                with self.subTest(method=method), self.assertRaises(UserError) as error:
                    self.send(method, args)
                self.assertEqual("busy", error.exception.code)
            self.assertEqual(before, list(self.engine.store.db.iterdump()))
            self.worker.keyring.get.assert_not_called()
            self.worker.keyring.set.assert_not_called()
            self.worker.keyring.delete.assert_not_called()

    def test_authentication_ownership_blocks_new_preparation(self):
        self.worker.account_job = True
        try:
            with patch("wanikani.listening_preparation.prepare") as prepare, self.assertRaises(UserError) as error:
                self.send("listen_prepare")
            self.assertEqual("busy", error.exception.code)
            prepare.assert_not_called()
            self.assertFalse(self.worker.audio_job_lock.locked())
            self.assertIsNone(self.worker.preparation_job)
        finally:
            self.worker.account_job = False

    def test_exact_job_cancel_does_not_stop_ordinary_sync(self):
        sync_entered, sync_release = threading.Event(), threading.Event()
        account_cancelled = threading.Event()
        self.worker.sync = Mock(engine=self.engine, cancelled=account_cancelled)
        def sync():
            sync_entered.set()
            if not sync_release.wait(5):
                raise AssertionError("Fixture synchronization was not released")
            return {"synced": True}
        self.worker.job("ordinary-sync", sync)
        try:
            self.assertTrue(sync_entered.wait(5))
            with self.preparing() as (_, _, cancelled):
                self.send("listen_prepare_cancel", {"job_id": "other-job"}, rid="wrong-cancel")
                self.assertFalse(self.reply("wrong-cancel")["data"]["cancelled"])
                self.assertFalse(cancelled())
                self.send("listen_prepare_cancel", {"job_id": "prepare-one"}, rid="right-cancel")
                self.assertTrue(self.reply("right-cancel")["data"]["cancelled"])
                self.assertTrue(cancelled())
                self.assertFalse(account_cancelled.is_set())
                self.assertTrue(self.worker.job_lock.locked())
                self.assertFalse(sync_release.is_set())
            self.assertTrue(self.reply("prepare-one")["data"]["cancelled"])
            self.assertIsNone(self.worker.preparation_job)
            self.send("listen_prepare_cancel", {"job_id": "prepare-one"}, rid="late-cancel")
            self.assertFalse(self.reply("late-cancel")["data"]["cancelled"])
        finally:
            sync_release.set()
            self.wait_unlocked(self.worker.job_lock)

    def test_old_job_cancel_cannot_cancel_a_new_preparation(self):
        with self.preparing(rid="completed-job"):
            pass
        with self.preparing(rid="new-job") as (_, _, cancelled):
            self.send("listen_prepare_cancel", {"job_id": "completed-job"}, rid="stale-cancel")
            self.assertFalse(self.reply("stale-cancel")["data"]["cancelled"])
            self.assertFalse(cancelled())

    def test_caller_cannot_inject_download_targets_or_broad_cancellation(self):
        with patch("wanikani.listening_preparation.prepare") as prepare:
            for args in ({"url": "https://private.invalid/fixture"}, {"subjects": [1]}, {"subject_id": 1},
                    {"limit": 100}, {"extra": True}):
                with self.subTest(args=args), self.assertRaises(UserError):
                    self.send("listen_prepare", args)
            for args in ({}, {"job_id": ""}, {"job_id": None}, {"job_id": True}, {"job_id": "x" * 161},
                    {"job_id": "valid", "all": True}):
                with self.subTest(args=args), self.assertRaises(UserError):
                    self.send("listen_prepare_cancel", args)
            prepare.assert_not_called()
        self.assertFalse(self.worker.audio_job_lock.locked())
        self.assertIsNone(self.worker.preparation_job)

    def test_progress_and_final_reply_never_expose_download_descriptors(self):
        private = {"subject_id": 2, "url": "https://private.invalid/PRIVATE", "uri": "file:///PRIVATE", "message": "PRIVATE",
            "handle": "PRIVATE", "items": [{"characters": "PRIVATE"}], "account_id": "PRIVATE"}
        with self.preparing(result=self.result(**private), progress_value={**self.result(), **private}):
            pass
        self.assertNotIn("PRIVATE", json.dumps(self.messages))
        allowed = {"status", "downloaded", "already_cached", "failed", "skipped_budget", "cancelled", "complete", "reason"}
        for message in self.messages:
            if message.get("event") == "listening_preparation":
                self.assertEqual("prepare-one", message["data"]["job_id"])
                self.assertTrue(set(message["data"]) <= allowed | {"job_id"})
        reply = self.reply("prepare-one")
        self.assertTrue(reply["ok"])
        self.assertTrue(set(reply["data"]) <= allowed)
        self.assertEqual([], self.engine.store.rows("SELECT * FROM sessions"))
        self.assertEqual([], self.engine.store.rows("SELECT * FROM outbox"))

    def test_malformed_progress_and_final_results_are_neutral_errors(self):
        malformed = [None, "PRIVATE", [], {"status": "PRIVATE"}, self.result(reason="PRIVATE"),
            self.result(downloaded=True), self.result(downloaded="PRIVATE"), self.result(failed=-1),
            self.result(skipped_budget=6), self.result(downloaded=3, already_cached=3),
            self.result(cancelled="PRIVATE"), self.result(complete=1)]
        for phase in ("progress", "final"):
            for index, value in enumerate(malformed):
                with self.subTest(phase=phase, value=value):
                    self.messages.clear()
                    self.refreshed.clear()
                    def prepare(sync, *, cancelled, progress):
                        if phase == "progress":
                            progress(value)
                            return self.result()
                        return value
                    rid = f"malformed-{phase}-{index}"
                    with patch("wanikani.listening_preparation.prepare", side_effect=prepare) as requested:
                        self.send("listen_prepare", rid=rid)
                        self.wait_unlocked(self.worker.audio_job_lock)
                        self.assertTrue(self.refreshed.wait(5))
                    requested.assert_called_once()
                    reply = self.reply(rid)
                    self.assertFalse(reply["ok"])
                    self.assertEqual("audio_error", reply["error"]["code"])
                    self.assertNotIn("PRIVATE", json.dumps(self.messages))
                    events = [item for item in self.messages if item.get("event") == "listening_preparation"]
                    self.assertEqual(1, len(events), "Only the initial neutral progress event may escape")
                    self.assertEqual("preparing", events[0]["data"]["status"])
                    self.assertEqual(0, events[0]["data"]["downloaded"])
                    self.assertIsNone(self.worker.preparation_job)
        self.worker.changed.assert_not_called()
        self.assertEqual([], self.engine.store.rows("SELECT * FROM outbox"))

    def test_prepare_exception_is_redacted_and_releases_job(self):
        for error, expected in ((RuntimeError("PRIVATE TRANSPORT DETAILS"), "audio_error"),
                (UserError("No eligible recordings.", "empty_listening"), "empty_listening")):
            self.messages.clear()
            self.refreshed.clear()
            with self.subTest(error=type(error).__name__), patch("wanikani.listening_preparation.prepare", side_effect=error):
                self.send("listen_prepare")
                self.wait_unlocked(self.worker.audio_job_lock)
                self.assertTrue(self.refreshed.wait(5))
                self.assertEqual(expected, self.reply("listen_prepare")["error"]["code"])
                self.assertNotIn("PRIVATE", json.dumps(self.messages))
                self.assertIsNone(self.worker.preparation_job)

    def test_initialization_and_thread_start_failures_release_all_ownership(self):
        for target, error in (("worker.Synchronizer", OSError("Authored cache initialization failure")),
                ("worker.threading.Thread.start", RuntimeError("Authored thread start failure"))):
            with self.subTest(target=target), patch(target, side_effect=error):
                with self.assertRaises(type(error)):
                    self.send("listen_prepare")
            self.assertFalse(self.worker.audio_job_lock.locked())
            self.assertIsNone(self.worker.preparation_job)
            self.assertFalse(self.worker.cancel_listening_preparation("listen_prepare"))

    def test_shutdown_cancels_job_suppresses_late_events_and_restart_has_no_job(self):
        entered, release = threading.Event(), threading.Event()
        cancellation_observed = []
        def prepare(sync, *, cancelled, progress):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Shutdown fixture was not released")
            cancellation_observed.append(cancelled())
            progress(self.result())
            return self.result()
        class Input:
            calls = 0
            def readline(inner, limit):
                inner.calls += 1
                if inner.calls == 1:
                    return json.dumps({"v": 1, "id": "shutdown-preparation", "method": "listen_prepare", "args": {}}) + "\n"
                if not entered.wait(5):
                    raise AssertionError("Preparation did not start before stdin closed")
                return ""
        with (self.path / "worker.lock").open("a+") as worker_lock, \
                patch("worker.open", return_value=worker_lock, create=True), \
                patch("wanikani.listening_preparation.prepare", side_effect=prepare), \
                patch("worker.Worker", return_value=self.worker), patch("worker.sys.stdin", Input()), \
                patch("worker.sys.argv", ["worker.py", "--state-dir", str(self.path)]), redirect_stdout(io.StringIO()):
            try:
                self.assertEqual(0, main())
                self.assertTrue(self.worker.stopping)
                messages_at_stop = list(self.messages)
            finally:
                release.set()
                self.wait_unlocked(self.worker.audio_job_lock)
                self.wait_unlocked(self.worker.job_lock)
        self.assertEqual([True], cancellation_observed)
        self.assertEqual(messages_at_stop, self.messages)
        self.assertFalse(any(message.get("id") == "shutdown-preparation" for message in self.messages))
        self.assertIsNone(self.worker.preparation_job)
        self.engine.store.close()
        with patch("worker.Keyring", return_value=Mock()):
            restarted = Worker(self.path, lambda value: None)
        try:
            self.assertIsNone(restarted.preparation_job)
            self.assertFalse(restarted.audio_job_lock.locked())
            self.assertEqual([], restarted.engine.store.rows("SELECT * FROM outbox"))
            self.assertEqual([], restarted.engine.store.rows("SELECT * FROM sessions"))
        finally:
            restarted.readiness.stop()
            restarted.engine.store.close()


if __name__ == "__main__":
    unittest.main()
