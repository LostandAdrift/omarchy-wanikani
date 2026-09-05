"""Actual worker-thread ordering, using authored local data and inert refreshes."""
import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from test_backend import NOW
from wanikani.common import UserError
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from worker import Worker


class StartPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.messages = []
        self.worker = Worker(Path(self.temp.name), self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.worker.readiness.refresh = Mock()
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        owner = self
        class InertSync:
            def run(self, *args, **kwargs):
                owner.started.set()
                if not owner.release.wait(5):
                    raise RuntimeError("Authored preflight timed out")
        self.sync = InertSync()
        original = self.worker.changed
        def changed(*args, **kwargs):
            try:
                original(*args, **kwargs)
            finally:
                self.finished.set()
        self.worker.changed = changed

    def tearDown(self):
        self.release.set()
        if self.started.is_set():
            self.assertTrue(self.finished.wait(5))
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def send(self, rid, mode, **args):
        self.worker.handle({"v": 1, "id": rid, "method": "start",
                            "args": {"mode": mode, "limit": 1, **args}})

    def begin_preflight(self, mode="reviews"):
        self.worker.sync = self.sync
        self.worker.last_attempt = 0
        self.send("earlier", mode)
        self.assertTrue(self.started.wait(2))

    def finish_preflight(self):
        self.release.set()
        self.assertTrue(self.finished.wait(3))
        return next(value for value in self.messages if value.get("id") == "earlier")

    def assert_stale(self):
        reply = self.finish_preflight()
        self.assertFalse(reply["ok"])
        self.assertEqual("stale_start", reply["error"]["code"])
        self.assertIsNone(self.worker.engine.store.execute(
            "SELECT id FROM commands WHERE id='earlier'").fetchone())

    def test_late_reviews_cannot_activate_or_create_after_newer_lessons(self):
        self.begin_preflight()
        self.send("latest", "lessons")
        state = self.worker.engine.session_state()
        self.assertEqual("lessons", state["session"]["mode"])
        self.assert_stale()
        self.assertEqual(state, self.worker.engine.session_state())
        self.assertIsNone(self.worker.engine.saved_session("reviews"))

    def test_late_lessons_cannot_replace_newer_explicit_practice(self):
        self.begin_preflight("lessons")
        self.send("latest", "practice", subjects=[2], replace_practice=True)
        self.worker.engine.draft("retained kana draft")
        state = self.worker.engine.session_state()
        self.assert_stale()
        self.assertEqual(state, self.worker.engine.session_state())
        self.assertIsNone(self.worker.engine.saved_session("lessons"))

    def test_completed_duplicate_is_replay_not_a_new_start_intent(self):
        self.send("completed", "reviews")
        self.begin_preflight("lessons")
        generation = self.worker.start_generation
        self.send("completed", "reviews")
        self.assertEqual(generation, self.worker.start_generation)
        reply = self.finish_preflight()
        self.assertTrue(reply["ok"])
        self.assertEqual("lessons", self.worker.engine.store.session()["mode"])

    def test_epoch_change_blocks_old_start_and_preserves_new_state(self):
        self.begin_preflight()
        self.worker.engine.store.set("session_epoch", "new-authored-epoch")
        state = self.worker.engine.session_state()
        self.assert_stale()
        self.assertEqual(state, self.worker.engine.session_state())
        self.assertEqual("new-authored-epoch", self.worker.engine.store.get("session_epoch"))

    def test_account_stamp_change_blocks_old_start(self):
        self.begin_preflight()
        self.worker.engine.store.set("account_id", "different-authored-account")
        self.assert_stale()
        self.assertIsNone(self.worker.engine.store.session())
        self.assertEqual("different-authored-account", self.worker.engine.store.get("account_id"))

    def test_cached_account_identity_change_blocks_old_start(self):
        self.begin_preflight()
        user = copy.deepcopy(self.worker.engine.store.get("user"))
        user["id"] = "different-authored-identity"
        self.worker.engine.store.set("user", user)
        self.assert_stale()
        self.assertIsNone(self.worker.engine.store.session())
        self.assertEqual(user, self.worker.engine.store.get("user"))

    def test_closed_previous_store_is_never_read_after_engine_replacement(self):
        self.begin_preflight()
        old = self.worker.engine
        replacement = Store(Path(self.temp.name) / "replacement.sqlite3")
        populate(replacement, NOW)
        self.worker.engine = Engine(replacement, clock=lambda: NOW)
        old.store.close()
        self.assert_stale()
        self.assertIsNone(replacement.session())

    def test_invalid_newer_trail_intent_also_cancels_older_preflight(self):
        self.begin_preflight()
        with self.assertRaises(UserError):
            self.worker.handle({"v": 1, "id": "new-trail", "method": "trail_practice_start", "args": {}})
        self.assert_stale()
        self.assertIsNone(self.worker.engine.store.session())

    def test_newer_trail_selection_remains_active_after_old_reviews_finish(self):
        from wanikani.trail_practice import preview
        self.worker.engine.store.set("account_id", "demo")
        selected = preview(self.worker.engine, "山", [2])
        self.begin_preflight()
        self.worker.handle({"v": 1, "id": "new-trail", "method": "trail_practice_start", "args": {
            "text": "山", "subject_ids": [2], "expected_data_epoch": selected["data_epoch"],
            "expected_saved_practice_revision": None, "replace_existing": False}})
        state = self.worker.engine.session_state()
        self.assertEqual("practice", state["session"]["mode"])
        self.assert_stale()
        self.assertEqual(state, self.worker.engine.session_state())

    def test_start_registration_cannot_interleave_guard_and_command(self):
        # A real second thread tries to register a newer intent while the
        # previous command is entering its transaction. The store lock must
        # remain owned throughout, rather than just protecting the check.
        ticket = self.worker.register_start("first")
        entered = threading.Event()
        acquired = threading.Event()
        completed = threading.Event()
        errors = []
        original = self.worker.command
        def contender():
            entered.set()
            try:
                self.worker.register_start("later")
                acquired.set()
            except Exception as error:
                errors.append(error)
            finally:
                completed.set()
        def command(*args):
            thread.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(acquired.wait(0.05))
            return original(*args)
        thread = threading.Thread(target=contender)
        self.worker.command = command
        try:
            result = self.worker.finish_start("first", "start", {"mode": "reviews", "limit": 1}, ticket)
        finally:
            self.worker.command = original
        self.assertTrue(completed.wait(2))
        thread.join()
        self.assertEqual([], errors)
        self.assertTrue(acquired.is_set())
        self.assertEqual("reviews", result["mode"])

    def test_stopping_worker_does_not_commit_preflight(self):
        self.begin_preflight()
        self.worker.stopping = True
        self.assert_stale()
        self.assertIsNone(self.worker.engine.store.session())
