"""Listening adapters use authored local media and never send account writes."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import test_listening as fixtures
from test_backend import NOW
from wanikani.common import UserError, stamp
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani import listening
from worker import Worker


class ListeningWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wanikani-listening-worker-")
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(Path(self.directory.name), self.messages.append)
        self.engine = self.worker.engine
        self.store = self.engine.store
        self.path = self.store.path
        self.media_dir = self.path.parent / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.now = NOW
        self.engine.clock = lambda: self.now
        self.engine.connected = True
        self.engine.status = "online"
        self.store.set("account_id", "authored-worker-account")
        self.store.set("user", {"object": "user", "data": {"id": "authored-worker-account", "username": "Fixture",
            "level": 2, "subscription": {"type": "lifetime", "max_level_granted": 60}}})
        self.store.set("last_sync", stamp(NOW - 600))
        self.words = {}
        fixtures.ListeningTests.word(self, 1, "やま")
        fixtures.ListeningTests.word(self, 2, "かわ")
        self.worker.readiness.refresh = Mock()
        self.worker.readiness.get = Mock(return_value={})
        self.worker.changed = Mock(side_effect=AssertionError("Listening must not emit a full catalogue state"))
        self.worker.session_changed = Mock(side_effect=AssertionError("Listening must not emit graded-session events"))
        self.guard = patch("socket.create_connection", side_effect=AssertionError("Worker fixture must not connect to a network"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.sequence = 0

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.store.close()
        self.directory.cleanup()

    def request(self, method, args=None, rid=None):
        self.sequence += 1
        self.messages.clear()
        request = {"v": 1, "id": rid or "authored-" + str(self.sequence), "method": method, "args": args or {}}
        try:
            self.worker.handle(request)
        except UserError as error:
            # This is exactly the public framing performed by worker.main.
            self.worker.reply_error(request["id"], error)
        self.assertEqual(1, len(self.messages), self.messages)
        self.assertNotIn("event", self.messages[0])
        return self.messages[0]

    def act(self, action, session=None, **args):
        if session:
            args.update(session_id=session["id"], revision=session["revision"])
        return self.request("listen", {"action": action, **args})

    def start(self, ids=None):
        reply = self.act("start", subject_ids=ids or [1])
        self.assertTrue(reply["ok"], reply)
        return reply["data"]["session"]

    def assert_safe_front(self, front):
        self.assertIsNone(front["subject"])
        encoded = json.dumps(front, ensure_ascii=False)
        for hidden in ("山1", "やま", "Authored meaning", "subject_id", "pronunciation", "meaning_note"):
            self.assertNotIn(hidden, encoded)

    def test_media_reply_contains_durable_new_revision_and_hidden_view(self):
        before = self.start()
        self.assert_safe_front(before)
        result = self.request("listen_media", {"handle": before["media_handle"]})
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(before["id"], data["session_id"])
        self.assertEqual(data["revision"], data["session"]["revision"])
        self.assertGreater(data["revision"], before["revision"])
        self.assert_safe_front(data["session"])
        self.assertTrue(data["uri"].startswith(self.media_dir.as_uri() + "/"))
        durable = self.store.get("listening_session_" + before["id"])
        self.assertEqual(data["revision"], durable["revision"])
        self.assertTrue(durable["queue"][0]["exposed"])
        # Independent connection confirms the transaction is committed before
        # the caller receives a file URI or the next revision.
        observer = Store(self.path)
        try:
            self.assertEqual(durable, observer.get("listening_session_" + before["id"]))
        finally:
            observer.close()

    def test_replayed_media_does_not_repeat_exposure_or_touch_graded_revision(self):
        before = self.start()
        graded_revision = self.store.get("session_revision", 0)
        first = self.request("listen_media", {"handle": before["media_handle"]})["data"]
        replay = self.request("listen_media", {"handle": before["media_handle"]})["data"]
        self.assertEqual(first["revision"], replay["revision"])
        self.assertEqual(graded_revision, self.store.get("session_revision", 0))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM sessions"))

    def test_rating_replies_are_small_local_transactions_without_catalogue_events(self):
        before_resources = [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")]
        session = self.start()
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("Rating should not request a full snapshot")):
            shown = self.act("reveal", session)["data"]["session"]
            reply = self.act("rate", shown, rating="remembered")
            self.assertTrue(reply["ok"])
            self.assertEqual("complete", reply["data"]["session"]["phase"])
        self.assertEqual(before_resources, [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM sessions"))
        self.worker.changed.assert_not_called()
        self.worker.session_changed.assert_not_called()
        self.worker.readiness.refresh.assert_not_called()

    def test_stale_revision_returns_recoverable_error_and_fresh_state(self):
        first = self.start()
        current = self.request("listen_media", {"handle": first["media_handle"]})["data"]["session"]
        stale = self.act("reveal", first)
        self.assertFalse(stale["ok"])
        self.assertEqual("stale_listening", stale["error"]["code"])
        self.assertEqual(current, self.request("listen_state")["data"]["session"])
        self.assertTrue(self.act("reveal", current)["ok"])

    def test_restart_restores_exposed_card_and_exact_revision(self):
        first = self.start()
        exposed = self.request("listen_media", {"handle": first["media_handle"]})["data"]["session"]
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.worker.engine = self.engine
        reply = self.request("listen_state")
        self.assertEqual(exposed, reply["data"]["session"])
        self.assert_safe_front(reply["data"]["session"])

    def test_new_graded_protection_withholds_cached_listening_front_and_media(self):
        session = self.start()
        shown = self.act("reveal", session)["data"]["session"]
        self.assertIsNotNone(shown["subject"])
        self.store.save_session({"id": "authored-protected", "mode": "reviews", "phase": "question",
            "queue": [{"subject_id": 1, "done": False}]})
        reply = self.request("listen_state")["data"]["session"]
        self.assertIsNone(reply["subject"])
        self.assertIsNone(reply["media_handle"])
        self.assertIn("unavailable", reply)
        denied = self.request("listen_media", {"handle": shown["media_handle"]})
        self.assertFalse(denied["ok"])
        self.assertEqual("listening_unavailable", denied["error"]["code"])

    def test_partial_sync_failure_requires_full_state_generation_invalidation(self):
        session = self.start()
        self.act("reveal", session)
        before = self.worker.snapshot()
        changed = copy.deepcopy(self.words[1])
        changed["data"]["hidden_at"] = stamp(self.now)
        self.store.put(changed)  # A committed page before a later API page fails.
        self.engine.status = "sync_error"
        after = self.worker.snapshot()
        for key in ("last_sync", "session_revision", "pending", "attention", "max_level", "session_epoch"):
            self.assertEqual(before[key], after[key], key)
        self.assertGreater(after["state_revision"], before["state_revision"])
        safe = self.request("listen_state")["data"]["session"]
        self.assertIsNone(safe["subject"])
        self.assertIsNone(safe["media_handle"])

    def test_account_reset_preserves_old_record_and_allows_explicit_fresh_session(self):
        before = self.start()
        old_record = self.store.get("listening_session_" + before["id"])
        self.store.set("milestone_reset_generation", 1)
        reply = self.request("listen_state")["data"]
        self.assertIsNone(reply["status"]["saved"])
        self.assertIn("unavailable", reply["session"])
        self.assert_safe_front(reply["session"])
        self.assertFalse(self.act("skip", reply["session"])["ok"])
        replacement = self.start([2])
        self.assertNotEqual(before["id"], replacement["id"])
        self.assertEqual(old_record, self.store.get("listening_session_" + before["id"]))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_concurrent_reset_waits_for_atomic_status_and_safe_view(self):
        before = self.start()
        durable = self.store.get("listening_session_" + before["id"])
        self.messages.clear()
        status_read = threading.Event()
        continue_view = threading.Event()
        reset_attempted = threading.Event()
        reset_done = threading.Event()
        failures, lock_available, order = [], [], []
        original_status, original_view = listening.status, listening.view

        def paused_status(engine):
            value = original_status(engine)
            status_read.set()
            if not continue_view.wait(5):
                raise AssertionError("Fixture did not release the status/view barrier")
            return value

        def observed_view(engine):
            value = original_view(engine)
            order.append("view")
            return value

        def read_state():
            try:
                self.worker.handle({"v": 1, "id": "authored-atomic-listening",
                    "method": "listen_state", "args": {}})
            except BaseException as error:
                failures.append(error)

        def reset():
            try:
                # Public lock acquisition from a different thread, not RLock
                # ownership introspection or a timing-dependent sleep. This
                # records whether a real reset could enter the protected gap.
                acquired = self.store.lock.acquire(blocking=False)
                lock_available.append(acquired)
                reset_attempted.set()
                if acquired:
                    self.store.lock.release()
                with self.store.transaction():
                    self.store.set("milestone_reset_generation", 1)
                    order.append("reset")
                reset_done.set()
            except BaseException as error:
                failures.append(error)

        reader = threading.Thread(target=read_state, name="authored-listening-read", daemon=True)
        writer = threading.Thread(target=reset, name="authored-reset", daemon=True)
        with patch("wanikani.listening.status", side_effect=paused_status), \
                patch("wanikani.listening.view", side_effect=observed_view):
            reader.start()
            try:
                self.assertTrue(status_read.wait(5), "Status projection did not reach its barrier")
                writer.start()
                self.assertTrue(reset_attempted.wait(5), "Reset thread did not attempt acquisition")
                self.assertEqual([False], lock_available,
                    "A concurrent reset entered between status and safe-view projection")
                self.assertFalse(reset_done.is_set())
            finally:
                continue_view.set()
                reader.join(5)
                if writer.ident is not None:
                    writer.join(5)
        self.assertFalse(reader.is_alive())
        self.assertFalse(writer.is_alive())
        self.assertEqual([], failures)
        self.assertEqual(["view", "reset"], order)
        self.assertTrue(reset_done.is_set())
        self.assertEqual(1, len(self.messages))
        self.assertTrue(self.messages[0]["ok"])
        reply = self.messages[0]["data"]
        self.assertEqual(before["id"], reply["status"]["saved"]["id"])
        self.assertEqual(before, reply["session"])
        self.assert_safe_front(reply["session"])
        # The next read observes the entire reset, including the recovery
        # affordance's saved=null condition. Neither reply mixes generations.
        after = self.request("listen_state")["data"]
        self.assertIsNone(after["status"]["saved"])
        self.assertIn("unavailable", after["session"])
        self.assert_safe_front(after["session"])
        self.assertEqual(durable, self.store.get("listening_session_" + before["id"]))

    def test_missing_media_can_be_skipped_without_rating_or_graded_effects(self):
        before = self.start()
        (self.media_dir / "1.mp3").unlink()
        denied = self.request("listen_media", {"handle": before["media_handle"]})
        self.assertFalse(denied["ok"])
        safe = self.request("listen_state")["data"]["session"]
        self.assertIn("unavailable", safe)
        skipped = self.act("skip", safe)
        self.assertEqual("complete", skipped["data"]["session"]["phase"])
        self.assertEqual(1, skipped["data"]["session"]["summary"]["skipped"])
        self.assertIsNone(self.store.get(listening._card_key(listening._context(self.engine), 1)))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_duplicate_rating_projects_current_access_without_reexecution(self):
        session = self.start()
        shown = self.act("reveal", session)["data"]["session"]
        args = {"action": "rate", "rating": "again", "session_id": shown["id"], "revision": shown["revision"]}
        first = self.request("listen", args, rid="same-authored-rating")
        second = self.request("listen", args, rid="same-authored-rating")
        self.assertTrue(second["data"]["duplicate"])
        self.assertEqual(first["data"]["session"], second["data"]["session"])
        self.assertEqual(1, len(self.store.rows("SELECT * FROM events WHERE kind='listening_result'")))

    def test_reminder_optional_count_failure_is_quiet_without_breaking_preview(self):
        context = {"hydrated": True, "locked": False, "dnd": False, "fullscreen": False, "studying": False}
        for error in (UserError("Authored unavailable listening cache"), OSError("Authored failed optional count")):
            with self.subTest(error=type(error).__name__), patch("wanikani.listening.status", side_effect=error):
                self.assertEqual(0, self.worker.rhythm_context({"context": context})["listen_count"])
                reply = self.request("rhythm_preview", {"context": context})
                self.assertTrue(reply["ok"])
                self.assertIn("next_at", reply["data"])
                self.assertFalse(any(item["view"] == "listen" for item in reply["data"]["available_actions"]))


if __name__ == "__main__":
    unittest.main()
