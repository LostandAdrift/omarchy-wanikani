"""The typed listening bridge never starts or submits graded account work."""
import json
import threading
import unittest
from unittest.mock import Mock, patch

import test_listening_worker as fixtures
from wanikani import dictation
from wanikani.common import UserError
from wanikani.store import Store


class DictationWorkerTests(unittest.TestCase):
    setUp = fixtures.ListeningWorkerTests.setUp
    tearDown = fixtures.ListeningWorkerTests.tearDown
    request = fixtures.ListeningWorkerTests.request

    def start(self):
        reply = self.request("dictation", {"action": "start"})
        self.assertTrue(reply["ok"], reply)
        return reply["data"]["session"]

    def action(self, name, session, **args):
        return self.request("dictation", {"action": name, "session_id": session["id"],
            "revision": session["revision"], **args})

    def media(self, session):
        reply = self.request("dictation_media", {"handle": session["media_handle"]})
        self.assertTrue(reply["ok"], reply)
        return reply["data"]

    def test_status_is_read_only_and_atomic_without_full_snapshot(self):
        before = list(self.store.db.iterdump())
        self.worker.snapshot = Mock(side_effect=AssertionError("No full snapshot"))
        result = self.request("dictation_state")
        self.assertTrue(result["ok"], result)
        self.assertEqual(2, result["data"]["status"]["available"])
        self.assertIsNone(result["data"]["session"])
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.worker.readiness.refresh.assert_not_called()

    def test_media_returns_committed_pinned_attempt_and_hidden_projection(self):
        session = self.start()
        value = self.media(session)
        self.assertGreater(value["revision"], session["revision"])
        self.assertEqual(value["revision"], value["session"]["revision"])
        self.assertFalse(value["session"]["heard"])
        self.assertIsNone(value["session"]["subject"])
        self.assertIsNone(value["session"]["feedback"])
        self.assertNotIn("Authored meaning", json.dumps(value))
        observer = Store(self.path)
        try:
            durable = observer.get("dictation_session_" + session["id"])
            self.assertEqual(value["playback_token"], durable["queue"][0]["playback_token"])
            self.assertTrue(durable["queue"][0]["exposed"])
        finally:
            observer.close()

    def test_status_and_media_hold_the_store_lock_through_safe_view_projection(self):
        session = self.start()
        original = dictation.view
        observations = []

        def project(engine):
            def probe():
                acquired = engine.store.lock.acquire(blocking=False)
                observations.append(acquired)
                if acquired:
                    engine.store.lock.release()
            thread = threading.Thread(target=probe, daemon=True)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            return original(engine)

        with patch("wanikani.dictation.view", side_effect=project):
            self.assertTrue(self.request("dictation_state")["ok"])
            self.assertTrue(self.request("dictation_media", {"handle": session["media_handle"]})["ok"])
        self.assertEqual([False, False], observations,
            "A reset could enter between the first projection and its accompanying session")

    def test_check_requires_current_completion_and_only_continue_records_interval(self):
        before = [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")]
        value = self.media(self.start())
        session = value["session"]
        rejected = self.action("check", session, text="やま")
        self.assertFalse(rejected["ok"])
        heard = self.action("heard", session, handle=value["handle"], playback_token=value["playback_token"])
        self.assertTrue(heard["ok"], heard)
        checked = self.action("check", heard["data"]["session"], text="やま")
        self.assertTrue(checked["ok"], checked)
        self.assertEqual("feedback", checked["data"]["session"]["phase"])
        self.assertEqual([], self.store.rows("SELECT * FROM events WHERE kind='dictation_result'"))
        done = self.action("continue", checked["data"]["session"])
        self.assertTrue(done["ok"], done)
        self.assertEqual(1, len(self.store.rows("SELECT * FROM events WHERE kind='dictation_result'")))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM sessions"))
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")])
        self.worker.readiness.refresh.assert_not_called()

    def test_draft_reply_is_compact_durable_and_does_not_mark_study_activity(self):
        session = self.start()
        self.store.set("last_study_at", 0)
        reply = self.request("dictation_draft", {"session_id": session["id"], "handle": session["media_handle"],
            "text": "やm", "cursor": 2, "preedit": "ま"})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual({"saved", "session_id", "handle", "draft_revision"}, set(reply["data"]))
        self.assertEqual(0, self.store.get("last_study_at"))
        durable = dictation.view(self.engine)
        self.assertEqual(("やm", 2, "ま"), (durable["draft"], durable["draft_cursor"], durable["preedit"]))

    def test_method_schemas_reject_forged_urls_times_context_and_extra_fields(self):
        for method, args in (
            ("dictation_state", {"now": 1}), ("dictation_media", {"handle": "x", "url": "https://example.org"}),
            ("dictation_draft", {"text": "あ"}),
            ("dictation_draft", {"session_id": "x", "handle": "y", "text": "あ", "cursor": 1, "revision": 1}),
            ("dictation", {"action": "start", "subject_ids": [1]}),
            ("dictation", {"action": "check", "session_id": "x", "revision": 1, "text": "あ", "heard": True}),
        ):
            with self.subTest(method=method, args=args):
                before = list(self.store.db.iterdump())
                reply = self.request(method, args)
                self.assertFalse(reply["ok"], reply)
                self.assertEqual(before, list(self.store.db.iterdump()))

    def test_clock_restriction_returns_honest_availability_without_erasing_saved_state(self):
        session = self.start()
        self.engine.clock_untrusted = True
        value = self.request("dictation_state")
        self.assertTrue(value["ok"], value)
        self.assertFalse(value["data"]["status"]["complete"])
        self.assertEqual(session["id"], value["data"]["session"]["id"])
        self.assertIn("unavailable", value["data"]["session"])

    def test_duplicate_local_operation_reprojects_without_reapplying(self):
        first = self.request("dictation", {"action": "start"}, rid="same-local-operation")
        second = self.request("dictation", {"action": "start"}, rid="same-local-operation")
        self.assertEqual(first["data"]["session"]["id"], second["data"]["session"]["id"])
        self.assertTrue(second["data"]["duplicate"])


if __name__ == "__main__":
    unittest.main()
