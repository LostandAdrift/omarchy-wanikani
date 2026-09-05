"""Bounded explicit cache preparation uses authored bytes and mock transport."""
import contextlib
import http.client
import json
import sqlite3
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_backend import NOW, UserError
from test_media_plan import MediaFixture, MIB
from test_media_sync import Response
from wanikani import media_plan
from wanikani.sync import Synchronizer


class RecordingPreparationTests(MediaFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.api = Mock()
        self.api.request.side_effect = AssertionError("Preparation cannot access account APIs")
        self.sync = Synchronizer(self.engine, self.api, self.media_dir)
        self.candidates = []
        for sid in range(100, 105):
            url = self.url(str(sid) + ".mp3")
            self.subject(sid, audio=[{"url": url}], characters="Authored", when=NOW + 7 * 86400)
            self.candidates.append({"subject_id": sid, "url": url})
        guard = patch("socket.create_connection", side_effect=AssertionError("No real network in fixtures"))
        guard.start()
        self.addCleanup(guard.stop)

    def prepare(self, responses=(), candidates=None, **kwargs):
        with patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = list(responses)
            result = self.sync.prepare_recordings(self.candidates if candidates is None else candidates,
                permitted=kwargs.pop("permitted", lambda _: True), **kwargs)
        return result, factory.return_value.open

    def private_learning_state(self):
        return {table: [tuple(row) for row in self.store.rows("SELECT * FROM " + table)]
            for table in ("resources", "meta", "sessions", "events", "outbox", "commands")}

    def fill_weaker_cache(self):
        return [self.cached(self.url("unrelated-" + str(index) + ".mp3"), 8 * MIB, index)
            for index in range(4)]

    def test_one_plan_prepares_five_original_clips_without_learning_or_account_writes(self):
        before, updates = self.private_learning_state(), []
        prior = object()
        self.sync._media_plan = prior
        with patch("wanikani.sync.media_plan.build", wraps=media_plan.build) as planner:
            result, opened = self.prepare([Response() for _ in range(5)], progress=updates.append)
        self.assertEqual(1, planner.call_count)
        self.assertEqual((5, 0, 0, 0, "ready", True), tuple(result[key] for key in
            ("downloaded", "already_cached", "failed", "skipped_budget", "status", "complete")))
        self.assertEqual(5, opened.call_count)
        self.assertTrue(all(call.kwargs["timeout"] == 10 and "Authorization" not in call.args[0].headers
            for call in opened.call_args_list))
        self.assertEqual(before, self.private_learning_state())
        self.assertEqual([0, 1, 2, 3, 4, 5], [update["completed"] for update in updates])
        encoded = json.dumps([result, updates])
        for private in ("subject_id", "url", "Authored", "uri", "pronunciation", "wanikani.com"):
            self.assertNotIn(private, encoded)
        self.assertIs(prior, self.sync._media_plan)
        self.assertFalse(self.sync.media_requested.is_set())
        self.assertFalse(self.sync.cancelled.is_set())
        self.api.request.assert_not_called()

    def test_all_selected_cached_clips_keep_equal_priority_against_later_downloads(self):
        cached = [self.cached(item["url"], 8 * MIB) for item in self.candidates[:2]]
        result, opened = self.prepare([Response(b"x" * (8 * MIB)) for _ in range(3)])
        self.assertEqual((2, 2, 1, "partial", "budget", True), tuple(result[key] for key in
            ("downloaded", "already_cached", "skipped_budget", "status", "reason", "complete")))
        self.assertEqual(2, opened.call_count)
        self.assertTrue(all(path.exists() for path in cached))
        self.assertEqual(32 * MIB, self.store.rows("SELECT SUM(size) FROM media")[0][0])
        self.assertEqual([], self.store.rows("SELECT key FROM meta WHERE key LIKE 'media_retry_%'"))

    def test_required_images_remain_ahead_of_explicit_audio(self):
        original = []
        for sid in range(200, 204):
            url = self.url(str(sid) + ".svg")
            self.subject(sid, images=[{"url": url}])
            original.append(self.cached(url, 8 * MIB))
        result, opened = self.prepare()
        self.assertEqual((0, 5, "budget", True), tuple(result[key] for key in
            ("downloaded", "skipped_budget", "reason", "complete")))
        opened.assert_not_called()
        self.assertTrue(all(path.exists() for path in original))

    def test_invalid_descriptors_are_rejected_before_planning_or_network(self):
        item = self.candidates[0]
        invalid = (self.candidates * 2, [item, item], [dict(item, subject_id=True)],
            [dict(item, url="https://attacker.invalid/audio")], [dict(item, extra=True)],
            [dict(item, url="file:///private")], None, "url", [dict(item, subject_id=-1)])
        with patch("wanikani.sync.media_plan.build") as planner:
            for candidates in invalid:
                with self.subTest(candidates=candidates), self.assertRaises(UserError):
                    self.sync.prepare_recordings(candidates, permitted=lambda _: True)
        planner.assert_not_called()

    def test_focus_rejects_incomplete_or_invalid_plan_and_preserves_required_kind(self):
        plan = media_plan.MediaPlan(self.media_dir, 32 * MIB)
        item = self.candidates[0]
        with self.assertRaises(ValueError):
            plan.focus_audio(item["url"], item["subject_id"], NOW)
        plan.complete = True
        for url, sid, now in (("file:///private", 1, NOW), (item["url"], True, NOW),
                (item["url"], 1, float("inf"))):
            with self.assertRaises(ValueError):
                plan.focus_audio(url, sid, now)
        plan._candidate(item["url"], 1, "image", (0, 0, 0), NOW)
        with self.assertRaises(ValueError):
            plan.focus_audio(item["url"], item["subject_id"], NOW)
        self.assertEqual("image", plan.candidates[item["url"]].kind)

    def test_cancel_before_ownership_does_not_plan_or_change_sync_cancellation(self):
        with patch("wanikani.sync.media_plan.build") as planner:
            result, opened = self.prepare(cancelled=lambda: True)
        self.assertEqual(("cancelled", False, True), (result["status"], result["complete"], result["cancelled"]))
        planner.assert_not_called()
        opened.assert_not_called()
        self.assertFalse(self.sync.cancelled.is_set())
        self.assertFalse(self.sync.media_requested.is_set())

    def test_waiting_job_requests_prefetch_yield_then_honors_its_own_cancellation(self):
        stop, results, failures = threading.Event(), [], []

        def job():
            try:
                results.append(self.sync.prepare_recordings(self.candidates, permitted=lambda _: True,
                    cancelled=stop.is_set))
            except BaseException as error:
                failures.append(error)

        with patch("wanikani.sync.media_plan.build") as planner:
            with self.sync.media_lock:
                thread = threading.Thread(target=job)
                thread.start()
                self.assertTrue(self.sync.media_requested.wait(2))
                stop.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], failures)
        self.assertEqual("cancelled", results[0]["status"])
        planner.assert_not_called()
        self.assertFalse(self.sync.cancelled.is_set())
        self.assertFalse(self.sync.media_requested.is_set())

    def test_invalidated_candidate_stops_before_its_read_without_failing_unattempted_words(self):
        allowed = {item["subject_id"] for item in self.candidates}

        def progress(value):
            if value["downloaded"]:
                allowed.discard(self.candidates[1]["subject_id"])

        result, opened = self.prepare([Response()], permitted=lambda item: item["subject_id"] in allowed,
            progress=progress)
        self.assertEqual((1, 0, "permission_changed", False), tuple(result[key] for key in
            ("downloaded", "failed", "reason", "complete")))
        self.assertEqual(1, opened.call_count)
        with patch("wanikani.sync.media_plan.build") as planner:
            result, opened = self.prepare(permitted=lambda _: False)
        self.assertEqual((0, "permission_changed"), (result["failed"], result["reason"]))
        planner.assert_not_called()
        opened.assert_not_called()

    def test_cancel_during_read_preserves_existing_recordings_and_stops_batch(self):
        original, stop = self.fill_weaker_cache(), threading.Event()
        before = [tuple(row) for row in self.store.rows("SELECT * FROM media")]
        result, opened = self.prepare([Response(read_hook=stop.set)], cancelled=stop.is_set)
        self.assertEqual(("cancelled", 0, 0, False), tuple(result[key] for key in
            ("status", "downloaded", "failed", "complete")))
        self.assertEqual(1, opened.call_count)
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM media")])
        self.assertTrue(all(path.exists() for path in original))
        self.assertEqual([], list(self.media_dir.glob("*.tmp")))
        self.assertFalse(self.sync.cancelled.is_set())

    def test_cancel_after_success_keeps_valid_cached_work_and_never_starts_next_clip(self):
        stop = threading.Event()

        def update(value):
            if value["downloaded"]:
                stop.set()

        result, opened = self.prepare([Response()], progress=update, cancelled=stop.is_set)
        self.assertEqual(("cancelled", 1, False), (result["status"], result["downloaded"], result["complete"]))
        self.assertEqual(1, opened.call_count)
        self.assertEqual(1, len(self.store.rows("SELECT * FROM media")))

    def test_permission_loss_during_network_read_cannot_place_or_evict(self):
        original, allowed = self.fill_weaker_cache(), [True]
        result, opened = self.prepare([Response(read_hook=lambda: allowed.__setitem__(0, False))],
            permitted=lambda _: allowed[0])
        self.assertEqual(("permission_changed", False, 0, 0), tuple(result[key] for key in
            ("reason", "complete", "downloaded", "failed")))
        self.assertEqual(1, opened.call_count)
        self.assertTrue(all(path.exists() for path in original))
        self.assertEqual(4, len(self.store.rows("SELECT * FROM media")))

    def test_permission_is_rechecked_after_temporary_write_under_store_lock(self):
        original, allowed = self.fill_weaker_cache(), [True]
        temporary_file = __import__("tempfile").NamedTemporaryFile

        @contextlib.contextmanager
        def revoke_after_write(*args, **kwargs):
            with temporary_file(*args, **kwargs) as stream:
                yield stream
            allowed[0] = False

        def permitted(_):
            self.assertTrue(self.store.lock._is_owned(), "Authorization must serialize against cached study changes")
            return allowed[0]

        with patch("wanikani.sync.tempfile.NamedTemporaryFile", side_effect=revoke_after_write):
            result, opened = self.prepare([Response()], permitted=permitted)
        self.assertEqual(("permission_changed", 0), (result["reason"], result["downloaded"]))
        self.assertEqual(1, opened.call_count)
        self.assertTrue(all(path.exists() for path in original))
        self.assertEqual([], list(self.media_dir.glob("*.tmp")))

    def test_incomplete_plan_and_expired_pass_cannot_clean_or_download(self):
        orphan = self.media_dir / ("a" * 64 + ".mp3")
        orphan.write_bytes(b"authored interrupted file")
        incomplete = media_plan.MediaPlan(self.media_dir, 32 * MIB)
        with patch("wanikani.sync.media_plan.build", return_value=incomplete):
            result, opened = self.prepare()
        self.assertEqual((False, "incomplete"), (result["complete"], result["reason"]))
        opened.assert_not_called()
        self.assertTrue(orphan.exists())
        ticks = iter((0, 9))
        with patch("wanikani.sync.time.monotonic", side_effect=lambda: next(ticks, 9)):
            result, opened = self.prepare()
        self.assertEqual((False, "incomplete"), (result["complete"], result["reason"]))
        opened.assert_not_called()
        self.assertTrue(orphan.exists())

    def test_soft_deadline_stops_after_inflight_read_without_automatic_retry(self):
        now = [0]
        with patch("wanikani.sync.time.monotonic", side_effect=lambda: now[0]):
            result, opened = self.prepare([Response(read_hook=lambda: now.__setitem__(0, 9))])
        self.assertEqual((1, "incomplete", False), (result["downloaded"], result["reason"], result["complete"]))
        self.assertEqual(1, opened.call_count)

    def test_invalid_mime_oversize_empty_and_interrupted_reads_preserve_weaker_files(self):
        original = self.fill_weaker_cache()
        responses = [Response(mime="text/html"), Response(b""), Response(b"short", length=100),
            Response(b"x" * (media_plan.MAX_FILE_BYTES + 1), length=1),
            Response(error=http.client.IncompleteRead(b"short", 100))]
        result, opened = self.prepare(responses)
        self.assertEqual((5, 0, True), (result["failed"], result["downloaded"], result["complete"]))
        self.assertEqual(5, opened.call_count)
        self.assertTrue(all(path.exists() for path in original))
        self.assertEqual([media_plan.MAX_FILE_BYTES + 1], responses[3].read_limits)
        self.assertEqual([], self.store.rows("SELECT key FROM meta WHERE key LIKE 'media_retry_%'"))

    def test_store_remains_available_for_durable_foreground_work_during_read(self):
        completed = threading.Event()
        failures = []

        def foreground():
            try:
                with self.store.transaction():
                    self.store.set("authored_foreground_draft", "durable partial kana")
                completed.set()
            except BaseException as error:
                failures.append(error)

        def read_hook():
            thread = threading.Thread(target=foreground)
            thread.start()
            thread.join(2)
            self.assertTrue(completed.is_set(), "Network read cannot hold the Store lock")

        result, _ = self.prepare([Response(read_hook=read_hook)], candidates=self.candidates[:1])
        self.assertEqual([], failures)
        self.assertEqual(1, result["downloaded"])
        self.assertEqual("durable partial kana", self.store.get("authored_foreground_draft"))

    def test_progress_failure_and_database_failure_release_plan_and_media_ownership(self):
        def bad_progress(_):
            raise RuntimeError("Authored presentation failure")

        result, _ = self.prepare([Response()], candidates=self.candidates[:1], progress=bad_progress)
        self.assertEqual(1, result["downloaded"])
        original = self.store.execute

        def disk_failure(sql, args=()):
            if sql.startswith("INSERT OR REPLACE INTO media"):
                raise sqlite3.OperationalError("Authored persistence failure")
            return original(sql, args)

        with patch.object(self.store, "execute", side_effect=disk_failure), self.assertRaises(sqlite3.OperationalError):
            self.prepare([Response()], candidates=self.candidates[1:2])
        self.assertFalse(self.sync.media_requested.is_set())
        self.assertIsNone(self.sync._media_plan)
        self.assertEqual(1, len(self.store.rows("SELECT * FROM media")))
        self.assertEqual([], list(self.media_dir.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
