"""Worker adapters preserve anchored authorization and one audio job."""
import json
import threading
import unittest
from unittest.mock import Mock, patch

from test_backend import UserError
from test_kanji_examples import KanjiExampleFixture
from test_media_sync import Response
from worker import Worker


class KanjiExampleWorkerTests(KanjiExampleFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(self.path.parent, self.messages.append)
        # Use the authored catalogue owned by this fixture. The worker's unused
        # account connection is closed before replacing it; no real state copy.
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.worker.engine = self.engine
        self.worker.sync = self.sync
        self.refreshed = threading.Event()
        self.worker.readiness = Mock()
        self.worker.readiness.refresh.side_effect = lambda **kwargs: self.refreshed.set()
        self.worker.changed = Mock(side_effect=AssertionError("Examples must not emit catalogue events"))
        self.worker.session_changed = Mock()

    def tearDown(self):
        self.worker.stopping = True
        self.assertTrue(self.worker.audio_job_lock.acquire(timeout=5))
        self.worker.audio_job_lock.release()
        super().tearDown()

    def send(self, method, args=None, rid=None):
        rid = rid or method
        try:
            self.worker.handle({"v": 1, "id": rid, "method": method, "args": args or {}})
        except UserError as error:
            self.worker.reply_error(rid, error)

    def reply(self, rid):
        values = [message for message in self.messages if message.get("id") == rid]
        self.assertEqual(1, len(values), "One final reply per request")
        return values[0]

    def test_readonly_catalogue_and_cached_playback_are_small_without_state_events(self):
        self.word(cached=True)
        view = self.study()
        before = list(self.store.db.iterdump())
        self.send("kanji_examples", {"parent_subject_id": 6, "context": "study", "session_id": view["id"], "revision": view["revision"]})
        page = self.reply("kanji_examples")
        self.assertTrue(page["ok"])
        self.assertEqual("available", page["data"]["status"])
        self.send("pronunciation", self.arguments(view))
        clip = self.reply("pronunciation")
        self.assertEqual(("ready", "にちご"), (clip["data"]["status"], clip["data"]["example"]["pronunciation"]))
        self.assertEqual(2, len(self.messages))
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.worker.session_changed.assert_not_called()
        self.worker.readiness.refresh.assert_not_called()

    def test_extra_url_empty_and_missing_context_arguments_never_start_an_audio_job(self):
        valid = self.arguments()
        cases = [{}, {**valid, "url": "https://PRIVATE.invalid"}, {**valid, "subjects": [6]},
            {key: value for key, value in valid.items() if key != "parent_subject_id"},
            {**valid, "origin_context": "study"}, {"subject_id": 101, "context": "details", "parent_subject_id": 6}]
        with patch("worker.threading.Thread.start", side_effect=AssertionError("Invalid args cannot start IO")):
            for index, args in enumerate(cases):
                for method in ("pronunciation", "pronunciation_prepare"):
                    rid = str(index) + method
                    self.send(method, args, rid)
                    reply = self.reply(rid)
                    self.assertFalse(reply["ok"])
                    self.assertNotIn("PRIVATE", json.dumps(reply))
        self.assertFalse(self.worker.audio_job_lock.locked())

    def test_async_example_download_keeps_audio_ownership_and_account_guard(self):
        self.word()
        view = self.study()
        entered, release = threading.Event(), threading.Event()
        def block():
            entered.set()
            if not release.wait(5):
                raise AssertionError("Fixture download was not released")
        with patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = Response(read_hook=block)
            self.send("pronunciation_prepare", self.arguments(view), "first")
            try:
                self.assertTrue(entered.wait(5))
                self.send("pronunciation_prepare", self.arguments(view), "second")
                self.assertEqual("busy", self.reply("second")["error"]["code"])
                self.send("authenticate", {"token": "authored-token"}, "account")
                self.assertEqual("busy", self.reply("account")["error"]["code"])
            finally:
                release.set()
                self.assertTrue(self.refreshed.wait(5))
        self.assertTrue(self.reply("first")["ok"])
        self.assertEqual("ready", self.reply("first")["data"]["status"])
        self.assertEqual(1, factory.return_value.open.call_count)
        self.worker.keyring.get.assert_not_called()
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_foreground_step_change_during_download_prevents_placement_and_late_uri(self):
        self.word()
        view = self.study()
        entered, release = threading.Event(), threading.Event()
        def block():
            entered.set()
            if not release.wait(5):
                raise AssertionError("Fixture download was not released")
        with patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = Response(read_hook=block)
            self.send("pronunciation_prepare", self.arguments(view), "audio")
            try:
                self.assertTrue(entered.wait(5))
                self.send("lesson_navigate", {"action": "back", "session_id": view["id"], "revision": view["revision"]}, "back")
                self.assertTrue(self.reply("back")["ok"])
                self.assertEqual("meaning", self.reply("back")["data"]["lesson_flow"]["step"])
                self.assertFalse(release.is_set())
            finally:
                release.set()
                self.assertTrue(self.refreshed.wait(5))
        reply = self.reply("audio")
        self.assertTrue(reply["ok"])
        self.assertEqual("stale_session", reply["data"]["reason"])
        self.assertIsNone(reply["data"]["uri"])
        self.assertNotIn("example", reply["data"])
        self.assertEqual([], self.store.rows("SELECT * FROM media"))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.worker.session_changed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
