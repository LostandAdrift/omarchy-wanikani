"""Optional full-snapshot history, tested without a shell, token or network."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import test_learning_insights as history_fixtures
import test_listening as audio_fixtures
from test_backend import NOW
from wanikani import insights, learning_digest
from wanikani.common import UserError, stamp
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from worker import Worker


class LearningDigestWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wanikani-digest-worker-")
        self.messages = []
        self.keyring = Mock()
        with patch("worker.Keyring", return_value=self.keyring):
            self.worker = Worker(Path(self.directory.name), self.messages.append)
        self.engine, self.store = self.worker.engine, self.worker.engine.store
        self.now, self.sequence = NOW, 0
        self.engine.clock = lambda: self.now
        populate(self.store, NOW)
        self.engine.connected = True
        self.engine.status = "online"
        self.store.set("account_id", "authored-digest-account")
        self.store.set("user", {"object": "user", "data": {"id": "authored-digest-account",
            "username": "PRIVATE_USERNAME", "level": 3,
            "subscription": {"type": "lifetime", "max_level_granted": 60}}})
        self.worker.readiness.refresh = Mock()
        self.worker.readiness.get = Mock(return_value={"checking": False})
        self.media_dir = self.store.path.parent / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.words = {}
        self.network = patch("socket.create_connection", side_effect=AssertionError("No network in digest fixtures"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.store.close()
        self.directory.cleanup()

    def send(self, method, args=None):
        self.messages.clear()
        self.sequence += 1
        rid = "authored-digest-" + str(self.sequence)
        self.worker.handle({"v": 1, "id": rid, "method": method, "args": args or {}})
        reply = next(message for message in self.messages if message.get("id") == rid)
        self.assertTrue(reply["ok"], reply)
        return reply["data"]

    def event(self, **kwargs):
        history_fixtures.LearningInsightsTests.event(self, **kwargs)

    def assert_no_digest_event(self):
        for message in self.messages:
            self.assertNotIn("learning_digest", json.dumps(message))
            if "event" in message:
                self.assertEqual("session", message["event"])

    def assert_history_bound(self, expected):
        reply = next(message for message in self.messages if "id" in message)
        self.assertEqual(expected, reply.get("learning_after_revision"))
        if expected is None:
            self.assertNotIn("learning_after_revision", reply)
        else:
            self.assertIs(type(reply["learning_after_revision"]), int)
        if isinstance(reply.get("data"), dict):
            self.assertNotIn("learning_after_revision", reply["data"])

    def test_full_snapshot_calls_project_once_and_matches_real_native_windows(self):
        for ago in (0, 0, 6, 7, 29, 30):
            self.event(when=self.now - ago * 86400)
        self.event(mode="lessons"); self.event(mode="practice")
        self.event(when=self.now + 1)
        session = history_fixtures.LearningInsightsTests.session(self, count=2, finished=5, sid="authored-finished-batch")
        session.update(part="meaning", overrides=0, lesson_index=0)
        for entry in session["queue"]:
            entry["errors"] = {"meaning": 0, "reading": 0}
        self.store.save_session(session)
        self.store.event("authored-finished-batch", 1, "correction", stamp(self.now),
            {"answer": "PRIVATE_ANSWER", "meaning_note": "PRIVATE_NOTE"})
        before = self.store.db.total_changes
        with patch("wanikani.learning_digest.project", wraps=learning_digest.project) as project, \
                patch("wanikani.insights.overview", side_effect=AssertionError("Never obtain a private Activity payload")):
            value = self.worker.snapshot()
        project.assert_called_once_with(self.engine)
        self.assertEqual(before, self.store.db.total_changes)
        digest = value["learning_digest"]
        native = insights.overview(self.engine, timezone=digest["timezone"], now=self.now)
        self.assertEqual(native["windows"], digest["windows"])
        self.assertEqual(native["as_of"], digest["generated_at"])
        self.assertEqual(self.store.get("session_epoch"), digest["data_epoch"])
        self.assertEqual("recorded_on_this_device", digest["scope"])
        self.assertTrue(digest["complete"])
        self.assertNotIn("PRIVATE", json.dumps(digest))
        self.assertNotIn("subject_id", json.dumps(digest))
        self.assertNotIn("outbox", digest)
        self.keyring.get.assert_not_called()

    def test_explicit_snapshot_and_existing_state_boundary_each_compute_exactly_once(self):
        with patch("wanikani.learning_digest.project", wraps=learning_digest.project) as project:
            first = self.send("snapshot")
            self.assertEqual(1, project.call_count)
            self.assertEqual(1, len(self.messages))
            self.worker.changed()
            self.assertEqual(2, project.call_count)
        state = self.messages[-1]
        self.assertEqual("state", state["event"])
        self.assertGreater(state["data"]["state_revision"], first["state_revision"])
        self.assertEqual(first["learning_digest"], state["data"]["learning_digest"])

    def test_missing_auth_identity_epoch_or_clock_trust_keeps_ordinary_snapshot_available(self):
        original_user = self.store.get("user")
        original_epoch = self.store.get("session_epoch")
        cases = ("missing_user", "mismatched_account", "missing_epoch", "private_epoch", "clock_untrusted", "clock_skew")
        for case in cases:
            with self.subTest(case=case):
                self.store.set("user", original_user)
                self.store.set("account_id", "authored-digest-account")
                self.store.set("session_epoch", original_epoch)
                self.engine.clock_untrusted = False; self.engine.clock_offset = 0
                if case == "missing_user": self.store.set("user", None)
                elif case == "mismatched_account": self.store.set("account_id", "other-authored-account")
                elif case == "missing_epoch": self.store.set("session_epoch", None)
                elif case == "private_epoch": self.store.set("session_epoch", "PRIVATE_ACCOUNT_VALUE")
                elif case == "clock_untrusted": self.engine.clock_untrusted = True
                else: self.engine.clock_offset = 301
                value = self.send("snapshot")
                self.assertIsNone(value["learning_digest"])
                self.assertIn("status", value)
                self.assertIn("reviews", value)
                self.assertEqual(1, len(self.messages))

    def test_optional_sql_failure_returns_unknown_not_old_totals_or_private_error(self):
        self.event()
        self.assertIsNotNone(self.worker.snapshot()["learning_digest"])
        with patch("wanikani.insights._completion_data", side_effect=sqlite3.OperationalError("PRIVATE_SQL_SENTINEL")):
            value = self.send("snapshot")
        self.assertIsNone(value["learning_digest"])
        self.assertEqual("online", value["status"])
        self.assertNotIn("PRIVATE_SQL_SENTINEL", json.dumps(self.messages))
        self.assertEqual(1, len(self.messages))

    def test_unexpected_optional_projector_error_is_redacted_and_cannot_break_snapshot(self):
        with patch("wanikani.learning_digest.project", side_effect=RuntimeError("PRIVATE_PROJECTOR_SENTINEL")) as project:
            value = self.send("snapshot")
        project.assert_called_once()
        self.assertIsNone(value["learning_digest"])
        self.assertNotIn("PRIVATE_PROJECTOR_SENTINEL", json.dumps(self.messages))

    def test_account_epoch_and_demo_changes_between_snapshot_and_digest_discard_projection(self):
        original_snapshot = self.engine.snapshot
        original_user = self.store.get("user")
        original_epoch = self.store.get("session_epoch")
        for field in ("account", "epoch", "demo"):
            with self.subTest(field=field):
                self.store.set("account_id", "authored-digest-account")
                self.store.set("user", original_user)
                self.store.set("session_epoch", original_epoch)
                self.engine.demo = False
                def change_context():
                    value = original_snapshot()
                    if field == "account":
                        user = copy.deepcopy(original_user); user["data"]["id"] = "new-authored-account"
                        self.store.set("user", user); self.store.set("account_id", "new-authored-account")
                    elif field == "epoch": self.store.set("session_epoch", str(uuid4()))
                    else: self.engine.demo = True
                    return value
                with patch.object(self.engine, "snapshot", side_effect=change_context), \
                        patch("wanikani.learning_digest.project", wraps=learning_digest.project) as project:
                    value = self.worker.snapshot()
                self.assertIsNone(value["learning_digest"])
                project.assert_not_called()

    def test_replaced_engine_cannot_export_old_store_totals_even_with_same_identity(self):
        self.event()
        second_store = Store(Path(self.directory.name) / "other-authored.sqlite3")
        try:
            second_store.set("user", self.store.get("user"))
            second_store.set("account_id", self.store.get("account_id"))
            second_store.set("session_epoch", self.store.get("session_epoch"))
            replacement = Engine(second_store, clock=lambda: self.now)
            original = self.engine.snapshot
            def replace():
                value = original()
                self.worker.engine = replacement
                return value
            with patch.object(self.engine, "snapshot", side_effect=replace), \
                    patch("wanikani.learning_digest.project", wraps=learning_digest.project) as project:
                value = self.worker.snapshot()
            project.assert_not_called()
            self.assertIsNone(value["learning_digest"])
        finally:
            self.worker.engine = self.engine
            second_store.close()

    def test_snapshot_epoch_or_demo_mismatch_withholds_digest_without_recomputing(self):
        original = self.engine.snapshot
        for field, replacement in (("session_epoch", str(uuid4())), ("demo", True), ("demo", 0)):
            with self.subTest(field=field, replacement=replacement):
                def inconsistent():
                    value = original(); value[field] = replacement; return value
                with patch.object(self.engine, "snapshot", side_effect=inconsistent), \
                        patch("wanikani.learning_digest.project", wraps=learning_digest.project) as project:
                    value = self.worker.snapshot()
                project.assert_not_called()
                self.assertIsNone(value["learning_digest"])

    def test_project_has_store_lock_without_serializing_the_entire_engine_snapshot(self):
        original = self.engine.snapshot
        observations = []
        def probe(label):
            def other_thread():
                acquired = self.store.lock.acquire(blocking=False)
                observations.append((label, acquired))
                if acquired: self.store.lock.release()
            thread = threading.Thread(target=other_thread)
            thread.start(); thread.join(5)
            self.assertFalse(thread.is_alive())
        def engine_snapshot():
            probe("engine_snapshot")
            return original()
        actual_project = learning_digest.project
        def locked_project(engine):
            probe("project")
            return actual_project(engine)
        with patch.object(self.engine, "snapshot", side_effect=engine_snapshot), \
                patch("wanikani.learning_digest.project", side_effect=locked_project):
            value = self.worker.snapshot()
        self.assertIsNotNone(value["learning_digest"])
        self.assertEqual([("engine_snapshot", True), ("project", False)], observations)

    def test_answer_draft_correction_and_partial_advance_have_no_history_projection(self):
        revision = self.worker.snapshot()["state_revision"]
        self.worker.readiness.refresh.reset_mock()
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("Fast action requested a full snapshot")), \
                patch("wanikani.learning_digest.project", side_effect=AssertionError("Fast action scanned history")) as project:
            self.send("start", {"mode": "practice", "subjects": [2], "limit": 1}); self.assert_no_digest_event()
            self.assert_history_bound(None)
            self.send("draft", {"text": "PRIVATE_DRAFT"}); self.assertEqual(1, len(self.messages))
            self.assert_history_bound(None)
            self.send("answer", {"text": ""}); self.assert_no_digest_event()
            self.assert_history_bound(None)
            self.send("answer", {"text": "wrong authored answer"}); self.assert_no_digest_event()
            self.assert_history_bound(None)
            self.send("correct"); self.assert_no_digest_event()
            self.assert_history_bound(revision)
            self.send("finish"); self.assert_no_digest_event()
            self.assert_history_bound(revision)
            self.send("advance"); self.assert_no_digest_event()
            self.assert_history_bound(revision)
            project.assert_not_called()
        self.assertEqual(revision, self.worker.snapshot_sequence)
        self.worker.readiness.refresh.assert_not_called()

    def test_guided_and_legacy_lesson_navigation_have_no_history_projection(self):
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("Lesson step requested a full snapshot")), \
                patch("wanikani.learning_digest.project", side_effect=AssertionError("Lesson step scanned history")) as project:
            view = self.send("start", {"mode": "lessons", "limit": 2})
            flow = view["lesson_flow"]
            self.assertTrue(flow["can_next"])
            view = self.send("lesson_navigate", {"action": "next", "session_id": view["id"], "revision": view["revision"]})
            self.assert_no_digest_event()
            self.send("lesson_next"); self.assert_no_digest_event()
            project.assert_not_called()
        self.worker.readiness.refresh.assert_not_called()

    def test_completed_subject_uses_existing_full_boundary_and_counts_once(self):
        view = self.send("start", {"mode": "practice", "subjects": [1], "limit": 1})
        self.send("answer", {"text": view["subject"]["meanings"][0]})
        with patch("wanikani.learning_digest.project", wraps=learning_digest.project) as project:
            self.send("advance")
        project.assert_called_once()
        self.assertEqual(2, len(self.messages))
        state = self.messages[-1]
        self.assert_history_bound(0)
        self.assertEqual("state", state["event"])
        self.assertGreater(state["data"]["state_revision"], self.messages[0]["learning_after_revision"])
        self.assertEqual(1, state["data"]["learning_digest"]["windows"]["7"]["subject_completions"]["practice"])

    def test_listening_play_reveal_rating_and_read_state_never_compute_digest(self):
        audio_fixtures.ListeningTests.word(self, 201, "やま")
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("Listening requested a full snapshot")), \
                patch("wanikani.learning_digest.project", side_effect=AssertionError("Listening scanned history")) as project:
            state = self.send("listen_state"); self.assertEqual(1, state["status"]["available"])
            self.assert_history_bound(None)
            view = self.send("listen", {"action": "start", "subject_ids": [201]})["session"]
            self.assert_history_bound(None)
            view = self.send("listen_media", {"handle": view["media_handle"]})["session"]
            self.assert_history_bound(None)
            view = self.send("listen", {"action": "reveal", "session_id": view["id"], "revision": view["revision"]})["session"]
            self.assert_history_bound(None)
            done = self.send("listen", {"action": "rate", "rating": "remembered", "session_id": view["id"], "revision": view["revision"]})
            self.assert_history_bound(0)
            self.assertEqual("complete", done["session"]["phase"])
            self.assertEqual(1, len(self.messages)); self.assert_no_digest_event()
            project.assert_not_called()
        self.assertEqual(1, len(self.store.rows("SELECT 1 FROM events WHERE kind='listening_result'")))
        self.worker.readiness.refresh.assert_not_called()

    def test_dictation_play_completion_draft_check_continue_and_read_state_skip_digest(self):
        audio_fixtures.ListeningTests.word(self, 201, "やま")
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("Dictation requested a full snapshot")), \
                patch("wanikani.learning_digest.project", side_effect=AssertionError("Dictation scanned history")) as project:
            state = self.send("dictation_state"); self.assertEqual(1, state["status"]["available"])
            self.assert_history_bound(None)
            view = self.send("dictation", {"action": "start"})["session"]
            self.assert_history_bound(None)
            media = self.send("dictation_media", {"handle": view["media_handle"]})
            self.assert_history_bound(None)
            view = media["session"]
            self.send("dictation_draft", {"session_id": view["id"], "handle": view["media_handle"],
                "text": "やm", "cursor": 2, "preedit": "ま"})
            self.assert_history_bound(None)
            view = self.send("dictation", {"action": "heard", "session_id": view["id"], "revision": view["revision"],
                "handle": media["handle"], "playback_token": media["playback_token"]})["session"]
            self.assert_history_bound(None)
            view = self.send("dictation", {"action": "check", "session_id": view["id"], "revision": view["revision"], "text": "やま"})["session"]
            self.assert_history_bound(None)
            done = self.send("dictation", {"action": "continue", "session_id": view["id"], "revision": view["revision"]})
            self.assert_history_bound(0)
            self.assertEqual("complete", done["session"]["phase"])
            self.assertEqual(1, len(self.messages)); self.assert_no_digest_event()
            project.assert_not_called()
        self.assertEqual(1, len(self.store.rows("SELECT 1 FROM events WHERE kind='dictation_result'")))
        self.worker.readiness.refresh.assert_not_called()

    def test_both_audio_undo_and_skip_acknowledge_the_existing_snapshot_barrier(self):
        audio_fixtures.ListeningTests.word(self, 201, "やま")
        revision = self.worker.snapshot()["state_revision"]
        listening = self.send("listen", {"action": "start", "subject_ids": [201]})["session"]
        listening = self.send("listen", {"action": "reveal", "session_id": listening["id"],
            "revision": listening["revision"]})["session"]
        listening = self.send("listen", {"action": "rate", "rating": "remembered", "session_id": listening["id"],
            "revision": listening["revision"]})["session"]
        for action in ("undo", "skip"):
            listening = self.send("listen", {"action": action, "session_id": listening["id"],
                "revision": listening["revision"]})["session"]
            self.assert_history_bound(revision)
            self.assertEqual(1, len(self.messages))
        dictation = self.send("dictation", {"action": "start"})["session"]
        media = self.send("dictation_media", {"handle": dictation["media_handle"]})
        dictation = self.send("dictation", {"action": "heard", "session_id": media["session"]["id"],
            "revision": media["session"]["revision"], "handle": media["handle"], "playback_token": media["playback_token"]})["session"]
        dictation = self.send("dictation", {"action": "check", "session_id": dictation["id"],
            "revision": dictation["revision"], "text": "やま"})["session"]
        for action in ("continue", "undo", "skip"):
            dictation = self.send("dictation", {"action": action, "session_id": dictation["id"],
                "revision": dictation["revision"]})["session"]
            self.assert_history_bound(revision)
            self.assertEqual(1, len(self.messages))
        self.assertEqual(revision, self.worker.snapshot_sequence)

    def test_failed_history_actions_and_read_only_replies_have_no_barrier(self):
        revision = self.worker.snapshot()["state_revision"]
        requests = [(method, {}) for method in ("correct", "advance", "finish")]
        requests.extend(("listen", {"action": action}) for action in ("rate", "skip", "undo"))
        requests.extend(("dictation", {"action": action}) for action in ("continue", "skip", "undo"))
        for method, args in requests:
            with self.subTest(method=method, args=args):
                self.messages.clear()
                with self.assertRaises(UserError) as error:
                    self.worker.handle({"v": 1, "id": "authored-failure", "method": method, "args": args})
                self.assertEqual([], self.messages)
                self.worker.reply_error("authored-failure", error.exception)
                self.assertFalse(self.messages[0]["ok"])
                self.assert_history_bound(None)
        for method, args in (("session", {}), ("search", {"text": "山"}), ("progress", {}), ("tick", {})):
            self.send(method, args)
            self.assert_history_bound(None)
        self.assertEqual(revision, self.worker.snapshot_sequence)

    def test_late_started_snapshot_is_behind_durable_audio_reply_and_next_snapshot_is_after(self):
        audio_fixtures.ListeningTests.word(self, 201, "やま")
        view = self.send("listen", {"action": "start", "subject_ids": [201]})["session"]
        view = self.send("listen", {"action": "reveal", "session_id": view["id"], "revision": view["revision"]})["session"]
        self.assertEqual(0, self.worker.snapshot_sequence)
        began, release = threading.Event(), threading.Event()
        snapshots, failures = [], []
        original = self.engine.snapshot
        def delayed():
            value = original()
            began.set()
            if not release.wait(5):
                raise AssertionError("Authored snapshot was not released")
            return value
        def old_snapshot():
            try:
                snapshots.append(self.worker.snapshot())
            except BaseException as error:
                failures.append(error)
        thread = threading.Thread(target=old_snapshot, daemon=True)
        with patch.object(self.engine, "snapshot", side_effect=delayed):
            thread.start()
            try:
                self.assertTrue(began.wait(5))
                done = self.send("listen", {"action": "rate", "rating": "remembered",
                    "session_id": view["id"], "revision": view["revision"]})
                self.assertEqual("complete", done["session"]["phase"])
                barrier = self.messages[0]["learning_after_revision"]
                self.assertEqual(1, barrier)
                # An independent connection sees the result before the reply's
                # barrier is consumed; this is not a speculative action marker.
                observer = Store(self.store.path)
                try:
                    self.assertEqual(1, len(observer.rows("SELECT 1 FROM events WHERE kind='listening_result'")))
                finally:
                    observer.close()
                self.assertEqual(barrier, self.worker.snapshot_sequence)
            finally:
                release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], failures)
        self.assertEqual(1, len(snapshots))
        self.assertLessEqual(snapshots[0]["state_revision"], barrier)
        after = self.worker.snapshot()
        self.assertGreater(after["state_revision"], barrier)
        self.assertEqual(1, after["learning_digest"]["windows"]["7"]["listening_ratings"]["remembered"])


if __name__ == "__main__":
    unittest.main()
