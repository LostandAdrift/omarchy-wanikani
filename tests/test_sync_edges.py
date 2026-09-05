"""Recovery regressions use independent fixtures and mock transports only."""
import copy
import http.client
import io
import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.api import Api, ApiError
from wanikani.common import UserError, stamp
from wanikani.credentials import Keyring
from wanikani.demo import populate
from wanikani.sync import Synchronizer
from worker import Worker


class SyncEdgeTests(EngineFixture, unittest.TestCase):
    def synchronizer(self):
        api = FakeApi(self.store)
        return Synchronizer(self.engine, api, Path(self.temp.name) / "media"), api

    def reset(self, confirmed=True):
        return {"id": 91, "object": "reset", "data": {
            "target_level": 1, "confirmed_at": stamp(NOW) if confirmed else None}}

    def state(self):
        return self.store.rows("SELECT state FROM outbox")[0][0]

    def test_previously_unconfirmed_reset_clears_removed_assignments(self):
        self.store.put(self.reset(False))
        self.store.set("reset_cursor", stamp(NOW - 60))
        self.complete()
        self.engine.start("reviews", 1)
        self.engine.draft("saved before reset")
        sync, api = self.synchronizer()
        api.resets = [self.reset()]
        self.assertTrue(sync.run())
        self.assertEqual([], api.mutations)
        self.assertEqual("conflicted", self.state())
        self.assertEqual([], self.store.all("assignment"))
        self.assertEqual(0, self.engine.snapshot()["reviews"])
        self.assertEqual("Account reset", self.engine.session_view()["invalidated"])
        self.assertEqual("saved before reset", self.engine.session_view()["draft"])

    def test_reset_observation_and_invalidation_rollback_together(self):
        self.complete()
        self.store.set("reset_cursor", stamp(NOW - 60))
        sync, api = self.synchronizer()
        api.resets = [self.reset()]
        original = self.store.put
        def fail(resource):
            if resource["object"] == "reset":
                raise OSError("simulated persistence interruption")
            return original(resource)
        with patch.object(self.store, "put", side_effect=fail):
            self.assertFalse(sync.run())
        self.assertIsNone(self.store.resource("reset", 91))
        self.assertEqual("pending", self.state())
        self.assertTrue(self.store.all("assignment"))
        self.assertEqual([], api.mutations)

    def test_reset_invalidates_pagination_cursors_durably(self):
        self.store.set("cursor_assignments", "old cursor")
        sync, _ = self.synchronizer()
        sync._invalidate_reset(self.reset())
        self.store.close()
        from wanikani.store import Store
        self.store = Store(self.path)
        self.assertIsNone(self.store.get("cursor_assignments"))
        self.assertEqual([], self.store.all("assignment"))

    def test_reset_invalidates_paused_graded_work_without_closing_practice(self):
        graded = self.engine.start("reviews", 1)
        self.engine.draft("paused answer")
        practice = self.engine.start("practice", 1, [3])
        sync, _ = self.synchronizer()
        sync._invalidate_reset(self.reset())
        self.assertEqual(practice["id"], self.engine.session_view()["id"])
        self.assertEqual("question", self.engine.session_view()["phase"])
        saved = self.store.session(graded["id"])
        self.assertEqual("complete", saved["phase"])
        self.assertEqual("paused answer", saved["draft"])

    def test_invalid_account_response_preserves_cached_access(self):
        sync, api = self.synchronizer()
        original = self.store.get("user")
        api.user["data"] = None
        self.assertFalse(sync.run())
        self.assertEqual(original, self.store.get("user"))
        self.assertEqual(5, self.engine.snapshot()["reviews"])

    def test_preflight_rejects_wrong_assignment_before_write(self):
        self.complete()
        sync, api = self.synchronizer()
        body = json.loads(self.store.rows("SELECT body FROM outbox")[0][0])
        api.assignments[body["assignment_id"]]["id"] += 1
        with self.assertRaises(ApiError):
            sync.flush()
        self.assertEqual("pending", self.state())
        self.assertEqual([], api.mutations)

    def test_unchanged_review_response_is_uncertain(self):
        self.complete()
        sync, api = self.synchronizer()
        row = self.store.rows("SELECT * FROM outbox")[0]
        body = json.loads(row["body"])
        sync.apply_result(row, {"object": "review", "id": 0, "resources_updated": {
            "assignment": api.assignments[body["assignment_id"]]}})
        self.assertEqual("uncertain", self.state())
        sync.flush()
        self.assertEqual([], api.mutations)

    def test_wrong_statistic_rolls_back_assignment_confirmation(self):
        self.complete()
        sync, api = self.synchronizer()
        row = self.store.rows("SELECT * FROM outbox")[0]
        body = json.loads(row["body"])
        original = self.store.resource("assignment", body["assignment_id"])
        assignment = copy.deepcopy(original)
        assignment["data"]["available_at"] = stamp(NOW + 14400)
        sync.apply_result(row, {"resources_updated": {"assignment": assignment,
            "review_statistic": {"id": 99, "object": "review_statistic", "data": {"subject_id": 999999}}}})
        self.assertEqual("uncertain", self.state())
        self.assertEqual(original, self.store.resource("assignment", body["assignment_id"]))
        self.assertIsNone(self.store.resource("review_statistic", 99))

    def test_wrong_lesson_assignment_is_uncertain(self):
        self.complete("lessons")
        sync, api = self.synchronizer()
        row = self.store.rows("SELECT * FROM outbox")[0]
        body = json.loads(row["body"])
        assignment = copy.deepcopy(api.assignments[body["assignment_id"]])
        assignment["id"] += 1
        assignment["data"]["started_at"] = stamp(NOW)
        sync.apply_result(row, assignment)
        self.assertEqual("uncertain", self.state())

    def test_vacation_and_unverified_clock_leave_pending_work_untouched(self):
        self.complete()
        sync, api = self.synchronizer()
        self.engine.clock_untrusted = True
        with self.assertRaises(UserError):
            sync.flush()
        self.engine.clock_untrusted = False
        user = self.store.get("user")
        user["data"]["current_vacation_started_at"] = stamp(NOW)
        self.store.set("user", user)
        with self.assertRaises(UserError):
            sync.flush()
        self.assertEqual("pending", self.state())
        self.assertEqual([], api.mutations)

    def test_subscription_upgrade_refetches_previously_unavailable_subjects(self):
        sync, api = self.synchronizer()
        self.store.set("cached_max_level", 3)
        self.store.set("cursor_subjects", stamp(NOW - 60))
        api.user["data"]["subscription"]["max_level_granted"] = 60
        calls = []
        original = api.collection
        def collection(endpoint, params=None):
            calls.append((endpoint, params))
            yield from original(endpoint, params)
        api.collection = collection
        self.assertTrue(sync.run())
        parameters = next(p for endpoint, p in calls if endpoint == "subjects")
        self.assertNotIn("updated_after", parameters)
        self.assertEqual("60", parameters["levels"].split(",")[-1])

    def test_media_prefetch_stops_after_wall_clock_budget(self):
        for kind in ("radical", "kanji", "vocabulary", "kana_vocabulary"):
            for subject in self.store.all(kind):
                subject["data"]["pronunciation_audios"] = [{
                    "url": "https://wanikani.com/fixture-" + str(subject["id"]) + ".mp3"}]
                self.store.put(subject)
        sync, _ = self.synchronizer()
        for duration, succeeds, expected_attempts in ((4, False, 2), (10, False, 1), (3, True, 3)):
            with self.subTest(duration=duration, succeeds=succeeds):
                self.store.execute("DELETE FROM meta WHERE key LIKE 'media_retry_%'")
                elapsed = [0]
                def download(url):
                    elapsed[0] += duration
                    return succeeds
                with patch("wanikani.sync.time.monotonic", side_effect=lambda: elapsed[0]), \
                        patch.object(sync, "download_media", side_effect=download) as request, \
                        patch.object(sync, "trim_media") as trim:
                    sync.cache_media()
                self.assertEqual(expected_attempts, request.call_count)
                trim.assert_called_once()
                failures = self.store.rows("SELECT * FROM meta WHERE key LIKE 'media_retry_%'")
                self.assertEqual(0 if succeeds else expected_attempts, len(failures))

    def test_confirmed_review_refreshes_level_and_newly_unlocked_assignment(self):
        self.complete()
        sync, api = self.synchronizer()
        subject = copy.deepcopy(self.store.subject(2))
        subject["id"] = 999
        subject["data"]["level"] = 2
        self.store.put(subject)
        unlocked = copy.deepcopy(self.engine.assignments("lessons")[0][0])
        unlocked["id"] = 9999
        unlocked["data"]["subject_id"] = subject["id"]
        unlocked["data"]["unlocked_at"] = stamp(NOW)
        requests, collections = [], []
        original_request, original_collection = api.request, api.collection
        def request(path, method="GET", data=None, etag=None):
            requests.append((path, method))
            result = original_request(path, method, data, etag)
            if method == "POST" and path == "reviews":
                api.user["data"]["level"] = 2
            if path == "summary" and api.mutations:
                return {"data": {"lessons": [{"subject_ids": [999]}]}}, "new-summary"
            return result
        def collection(endpoint, params=None):
            collections.append((endpoint, params))
            if endpoint == "assignments" and api.mutations:
                yield [unlocked]
            else:
                yield from original_collection(endpoint, params)
        api.request, api.collection = request, collection
        self.assertTrue(sync.run())
        self.assertEqual("confirmed", self.state())
        self.assertEqual(2, self.engine.user()["level"])
        self.assertEqual(4, self.engine.snapshot()["lessons"])
        self.assertEqual([999], self.store.get("summary")["data"]["lessons"][0]["subject_ids"])
        self.assertEqual(2, requests.count(("user", "GET")))
        self.assertEqual(2, requests.count(("summary", "GET")))
        self.assertEqual(1, len(api.mutations))
        self.assertNotIn(("reviews", "GET"), requests)
        assignment_calls = [p for endpoint, p in collections if endpoint == "assignments"]
        self.assertEqual(2, len(assignment_calls))
        self.assertIn("updated_after", assignment_calls[-1])

    def test_failed_followup_refresh_does_not_requeue_confirmed_write(self):
        self.complete()
        sync, api = self.synchronizer()
        original_request = api.request
        def request(path, method="GET", data=None, etag=None):
            if path == "user" and api.mutations:
                raise ApiError(0, "fixture connection lost after confirmation")
            return original_request(path, method, data, etag)
        api.request = request
        self.assertFalse(sync.run())
        self.assertEqual("confirmed", self.state())
        api.request = original_request
        self.assertTrue(sync.run())
        self.assertEqual(1, len(api.mutations))

    def test_post_write_refresh_caps_pages_without_skipping_remaining_updates(self):
        sync, api = self.synchronizer()
        original_cursor = stamp(NOW - 60)
        self.store.set("cursor_assignments", original_cursor)
        fetched = []
        def collection(endpoint, params=None):
            self.assertEqual("assignments", endpoint)
            for index in range(10):
                fetched.append(index)
                yield []
        api.collection = collection
        sync.refresh_after_writes()
        self.assertEqual([0, 1, 2, 3], fetched)
        self.assertEqual(original_cursor, self.store.get("cursor_assignments"))


class TransportEdgeTests(unittest.TestCase):
    def test_server_request_timeout_is_uncertain_for_writes(self):
        api = Api("fixture-only-token")
        response = urllib.error.HTTPError(api.BASE + "reviews", 408, "Timeout", {}, io.BytesIO())
        with patch.object(api.opener, "open", side_effect=response):
            with self.assertRaises(ApiError) as failure:
                api.request("reviews", "POST", {"review": {}})
        response.close()
        self.assertTrue(failure.exception.uncertain)

    def test_truncated_response_is_uncertain_for_writes(self):
        api = Api("fixture-only-token")
        with patch.object(api.opener, "open", side_effect=http.client.IncompleteRead(b"partial")):
            with self.assertRaises(ApiError) as failure:
                api.request("reviews", "POST", {"review": {}})
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(0, failure.exception.status)

    def test_unexpected_not_modified_cannot_confirm_write(self):
        api = Api("fixture-only-token")
        response = urllib.error.HTTPError(api.BASE + "reviews", 304, "Not Modified", {}, io.BytesIO())
        with patch.object(api.opener, "open", side_effect=response):
            with self.assertRaises(ApiError) as failure:
                api.request("reviews", "POST", {"review": {}})
        response.close()
        self.assertTrue(failure.exception.uncertain)

    def test_malformed_pagination_fails_without_following_it(self):
        api = Api("fixture-only-token")
        for pages in ([], {"next_url": ["bad"]}):
            with self.subTest(pages=pages), patch.object(api, "request", return_value=({"data": [], "pages": pages}, None)) as request:
                with self.assertRaises(ApiError):
                    list(api.collection("assignments"))
                self.assertEqual(1, request.call_count)


class CredentialStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.messages = []
        self.worker = Worker(self.directory, self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.keyring = Mock()

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def test_locked_keyring_does_not_prevent_disconnect_or_reconnect_later(self):
        worker = self.worker
        worker.engine.store.set("credential_storage", "keyring")
        worker.engine.connected = True
        worker.token = "fixture-only-token"
        worker.keyring.delete.return_value = False
        with self.assertRaises(UserError):
            worker.handle({"v": 1, "id": "disconnect", "method": "disconnect"})
        self.assertFalse(worker.engine.connected)
        self.assertIsNone(worker.token)
        self.assertEqual("disconnected", worker.engine.store.get("credential_storage"))
        worker.startup()
        worker.keyring.get.assert_not_called()

    def test_session_only_authentication_clears_older_keyring_token(self):
        worker = self.worker
        worker.engine.store.set("credential_storage", "keyring")
        api = FakeApi(worker.engine.store)
        worker.keyring.delete.return_value = True
        with patch("worker.Api", return_value=api), patch.object(Synchronizer, "run", return_value=True):
            response = worker.authenticate({"token": "fixture-new-token", "remember": False})
        worker.keyring.set.assert_not_called()
        worker.keyring.delete.assert_called_once_with(api.user["id"])
        self.assertFalse(response["remembered"])
        self.assertEqual("session", worker.engine.store.get("credential_storage"))

    def test_fresh_session_only_authentication_needs_no_keyring_cleanup(self):
        worker = self.worker
        api = FakeApi(worker.engine.store)
        worker.keyring.delete.return_value = False
        with patch("worker.Api", return_value=api), patch.object(Synchronizer, "run", return_value=True):
            result = worker.authenticate({"token": "fixture-session-token", "remember": False})
        self.assertFalse(result["credential_cleanup_needed"])
        self.assertFalse(worker.engine.store.get("credential_may_exist"))
        worker.handle({"v": 1, "id": "disconnect", "method": "disconnect"})
        worker.keyring.delete.assert_not_called()
        self.assertEqual("disconnected", worker.engine.status)

    def test_missing_secret_tool_fallback_needs_no_keyring_cleanup(self):
        worker = self.worker
        worker.keyring = Keyring()
        api = FakeApi(worker.engine.store)
        with patch("worker.Api", return_value=api), patch.object(Synchronizer, "run", return_value=True), \
                patch("wanikani.credentials.subprocess.run", side_effect=FileNotFoundError), \
                patch.object(worker.keyring, "delete", wraps=worker.keyring.delete) as delete:
            result = worker.authenticate({"token": "fixture-session-token", "remember": True})
            worker.handle({"v": 1, "id": "disconnect", "method": "disconnect"})
            delete.assert_not_called()
        self.assertFalse(result["remembered"])
        self.assertFalse(result["credential_cleanup_needed"])
        self.assertFalse(worker.engine.store.get("credential_may_exist"))

    def test_timed_out_keyring_write_keeps_cleanup_warning_without_auto_reconnect(self):
        worker = self.worker
        worker.keyring = Keyring()
        api = FakeApi(worker.engine.store)
        with patch("worker.Api", return_value=api), patch.object(Synchronizer, "run", return_value=True), \
                patch("wanikani.credentials.subprocess.run", side_effect=subprocess.TimeoutExpired("secret-tool", 30)):
            result = worker.authenticate({"token": "fixture-session-token", "remember": True})
        self.assertTrue(result["credential_cleanup_needed"])
        self.assertTrue(worker.engine.store.get("credential_may_exist"))
        self.assertEqual("session", worker.engine.store.get("credential_storage"))
        with patch.object(worker.keyring, "get") as lookup:
            worker.startup()
            lookup.assert_not_called()

    def test_session_only_local_deletion_succeeds_without_secret_service(self):
        worker = self.worker
        worker.engine.store.set("credential_storage", "session")
        worker.engine.store.set("credential_may_exist", False)
        worker.keyring.delete.return_value = False
        worker.handle({"v": 1, "id": "delete", "method": "delete_data", "args": {"confirmation": "DELETE"}})
        worker.keyring.delete.assert_not_called()
        response = next(message["data"] for message in self.messages if message.get("id") == "delete")
        self.assertTrue(response["deleted"])
        self.assertFalse(response["credential_cleanup_needed"])
        self.assertIsNone(worker.engine.store.get("account_id"))

    def test_local_deletion_proceeds_with_honest_warning_if_saved_token_cannot_clear(self):
        worker = self.worker
        worker.engine.store.set("credential_storage", "keyring")
        worker.keyring.delete.return_value = False
        worker.handle({"v": 1, "id": "delete", "method": "delete_data", "args": {"confirmation": "DELETE"}})
        response = next(message["data"] for message in self.messages if message.get("id") == "delete")
        self.assertTrue(response["deleted"])
        self.assertTrue(response["credential_cleanup_needed"])
        self.assertIn("keyring", response["warning"])
        self.assertIsNone(worker.engine.store.get("account_id"))
        self.assertIsNone(worker.token)
        worker.startup()
        worker.keyring.get.assert_not_called()

    def test_local_deletion_still_requires_explicit_consent_for_pending_work(self):
        worker = self.worker
        worker.engine.set_material(2, {"meaning_synonyms": ["fixture peak"]})
        worker.keyring.delete.return_value = False
        with self.assertRaises(UserError):
            worker.handle({"v": 1, "id": "delete", "method": "delete_data", "args": {"confirmation": "DELETE"}})
        self.assertIsNotNone(worker.engine.store.get("account_id"))
        self.assertEqual(1, worker.engine.snapshot()["pending"])
        worker.keyring.delete.assert_not_called()
        worker.handle({"v": 1, "id": "delete-agreed", "method": "delete_data", "args": {"confirmation": "DELETE", "discard_pending": True}})
        self.assertIsNone(worker.engine.store.get("account_id"))

    def test_resume_returns_authoritative_draft_without_waiting_for_sync(self):
        worker = self.worker
        worker.engine.clock = lambda: NOW
        worker.engine.start("reviews", 1)
        worker.engine.draft("authoritative saved draft")
        worker.engine.start("practice", 1, [3])
        worker.sync = Mock()
        worker.sync.run.side_effect = AssertionError("resume must not wait for network")
        worker.changed = Mock()
        worker.handle({"v": 1, "id": "resume", "method": "start", "args": {"mode": "resume"}})
        response = next(message["data"] for message in self.messages if message.get("id") == "resume")
        self.assertEqual("authoritative saved draft", response["draft"])
        self.assertEqual("reviews", response["mode"])
        worker.sync.run.assert_not_called()

    def test_resume_falls_back_to_active_practice_without_network(self):
        worker = self.worker
        worker.engine.clock = lambda: NOW
        worker.engine.start("practice", 1, [3])
        worker.engine.draft("practice saved draft")
        worker.sync = Mock()
        worker.changed = Mock()
        worker.handle({"v": 1, "id": "resume", "method": "start", "args": {"mode": "resume"}})
        response = next(message["data"] for message in self.messages if message.get("id") == "resume")
        self.assertEqual("practice saved draft", response["draft"])
        worker.sync.run.assert_not_called()

    def test_new_graded_work_still_refreshes_before_start(self):
        worker = self.worker
        worker.engine.clock = lambda: NOW
        order = []
        arrived = threading.Event()
        def emit(value):
            self.messages.append(value)
            if value.get("id") == "new":
                order.append("reply")
                arrived.set()
        worker.emit = emit
        worker.changed = Mock()
        worker.sync = Mock()
        worker.sync.run.side_effect = lambda: order.append("sync") or True
        worker.handle({"v": 1, "id": "new", "method": "start", "args": {"mode": "reviews", "limit": 1}})
        self.assertTrue(arrived.wait(2))
        self.assertTrue(worker.job_lock.acquire(timeout=2))
        worker.job_lock.release()
        self.assertEqual(["sync", "reply"], order)

    def test_explicit_deletion_removes_recoverable_sqlite_pages(self):
        worker = self.worker
        marker = "PERSONAL-REMOVAL-REGRESSION-UNIQUE-TEST-CONTENT"
        worker.engine.store.set("personal_test_note", marker * 1000)
        worker.keyring.delete.return_value = True
        worker.handle({"v": 1, "id": "delete", "method": "delete_data", "args": {"confirmation": "DELETE"}})
        for path in self.directory.glob("account.sqlite3*"):
            self.assertNotIn(marker.encode(), path.read_bytes(), str(path))
        self.assertIsNone(worker.engine.store.get("account_id"))


if __name__ == "__main__":
    unittest.main()
