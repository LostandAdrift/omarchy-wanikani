"""Quota and latency models are entirely local; no account requests are sent."""
import copy
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from email.message import Message
from email.utils import formatdate
from pathlib import Path
from unittest.mock import Mock, patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.api import Api, ApiError, RequestBudget, elapsed_clock
from wanikani.common import UserError, stamp
from wanikani.demo import populate
from wanikani.sync import Synchronizer
from worker import Worker


class Clock:
    def __init__(self):
        self.wall = NOW
        self.elapsed = 0.0
        self.sleeps = []
    def advance(self, seconds):
        self.wall += seconds
        self.elapsed += seconds
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds)
    def budget(self):
        return RequestBudget(clock=lambda: self.wall, monotonic=lambda: self.elapsed, sleep=self.sleep)


class Reply:
    def __init__(self, body, headers=None):
        self.body = json.dumps(body).encode()
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = str(value)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        return self.body[:limit]


class RequestBudgetTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.budget = self.clock.budget()

    def test_first_nine_requests_need_no_artificial_sleep(self):
        for _ in range(9):
            self.budget.acquire()
            self.clock.advance(.02)
        self.assertEqual([], self.clock.sleeps)
        self.assertAlmostEqual(.18, self.clock.elapsed)

    def test_burst_cap_allows_ten_and_briefly_smooths_the_eleventh(self):
        for _ in range(11):
            self.budget.acquire()
        self.assertEqual([1], self.clock.sleeps)
        self.assertEqual(11, len(self.budget.requests))

    def test_fallback_never_exceeds_sixty_requests_in_a_rolling_minute(self):
        for _ in range(60):
            self.budget.acquire()
        self.assertEqual(5, self.clock.elapsed)
        with self.assertRaises(ApiError) as failure:
            self.budget.acquire()
        self.assertEqual(429, failure.exception.status)
        self.assertFalse(failure.exception.uncertain)
        self.assertEqual(5, self.clock.elapsed)  # No long sleep holding the job.
        self.clock.advance(55)
        self.budget.acquire()
        self.assertEqual(51, len(self.budget.requests))

    def test_lower_authoritative_limit_and_remaining_are_obeyed(self):
        self.budget.acquire()
        self.budget.observe({"Date": formatdate(NOW, usegmt=True), "RateLimit-Limit": "5",
            "RateLimit-Remaining": "2", "RateLimit-Reset": str(NOW + 20)})
        self.budget.acquire()
        self.budget.acquire()
        with self.assertRaises(ApiError):
            self.budget.acquire()
        self.assertEqual(5, self.budget.limit)
        self.clock.advance(20.1)
        self.budget.acquire()

    def test_server_headers_cannot_raise_local_ceiling_above_sixty(self):
        self.budget.observe({"RateLimit-Limit": "1000", "RateLimit-Remaining": "1000"})
        self.assertEqual(60, self.budget.limit)
        for _ in range(60):
            self.budget.acquire()
        with self.assertRaises(ApiError):
            self.budget.acquire()

    def test_retry_after_seconds_survives_forward_wall_clock_jump(self):
        self.budget.observe({"Retry-After": "120"}, 429)
        self.clock.wall += 86400
        with self.assertRaises(ApiError):
            self.budget.acquire()
        self.assertEqual([], self.clock.sleeps)
        self.clock.advance(120)
        self.budget.acquire()

    def test_retry_after_http_date_uses_server_time_when_local_clock_is_wrong(self):
        self.clock.wall += 3600
        self.budget.observe({"Date": formatdate(NOW, usegmt=True),
            "Retry-After": formatdate(NOW + 30, usegmt=True)}, 429)
        with self.assertRaises(ApiError):
            self.budget.acquire()
        self.clock.advance(30.1)
        self.budget.acquire()

    def test_reset_without_date_uses_prior_server_clock_observation(self):
        self.budget.observe({"Date": formatdate(NOW, usegmt=True)})
        self.clock.advance(10)
        self.clock.wall += 86400
        self.budget.observe({"RateLimit-Remaining": "0", "RateLimit-Reset": str(NOW + 30)})
        with self.assertRaises(ApiError):
            self.budget.acquire()
        self.clock.advance(20.1)
        self.budget.acquire()

    def test_429_without_usable_headers_has_a_conservative_backoff(self):
        self.budget.observe({"RateLimit-Remaining": "bad", "RateLimit-Reset": "nan"}, 429)
        with self.assertRaises(ApiError):
            self.budget.acquire()
        self.clock.advance(60)
        self.budget.acquire()

    def test_transport_never_retries_a_rate_limited_mutation(self):
        api = Api("fixture-token", clock=lambda: self.clock.wall, limiter=self.budget)
        response = urllib.error.HTTPError(api.BASE + "reviews", 429, "fixture", {"Retry-After": "20"}, io.BytesIO())
        with patch.object(api.opener, "open", side_effect=response) as opened:
            for _ in range(2):
                with self.assertRaises(ApiError) as failure:
                    api.request("reviews", "POST", {"review": {}})
                self.assertFalse(failure.exception.uncertain)
            self.assertEqual(1, opened.call_count)
        response.close()

    def test_failed_transport_still_consumes_local_quota_and_is_not_retried(self):
        api = Api("fixture-token", clock=lambda: self.clock.wall, limiter=self.budget)
        with patch.object(api.opener, "open", side_effect=urllib.error.URLError("fixture offline")) as opened:
            with self.assertRaises(ApiError) as failure:
                api.request("reviews", "POST", {"review": {}})
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(1, opened.call_count)
        self.assertEqual(1, len(self.budget.requests))

    def test_malformed_quota_header_does_not_hide_a_clock_offset(self):
        api = Api("fixture-token", clock=lambda: NOW + 3600, limiter=self.budget)
        api._headers({"Date": formatdate(NOW, usegmt=True), "RateLimit-Limit": "bad",
            "RateLimit-Remaining": "bad", "RateLimit-Reset": "inf"})
        self.assertEqual(-3600, api.server_offset)
        self.assertEqual(60, self.budget.limit)


class StudyPreflightTests(EngineFixture, unittest.TestCase):
    def test_nine_read_preflight_model_takes_nine_roundtrips_and_no_media(self):
        clock = Clock()
        api = Api("fixture-token", clock=lambda: clock.wall, limiter=clock.budget())
        calls = []
        def opened(request, timeout):
            endpoint = urllib.parse.urlsplit(request.full_url).path.split("/")[-1]
            calls.append(endpoint)
            clock.advance(.02)
            body = self.store.get("user") if endpoint == "user" else (
                {"object": "report", "data": {}} if endpoint == "summary" else
                {"object": "collection", "data": [], "pages": {"next_url": None}})
            return Reply(body, {"Date": formatdate(clock.wall, usegmt=True), "RateLimit-Limit": "60",
                "RateLimit-Remaining": str(60 - len(calls)), "RateLimit-Reset": str(NOW + 60)})
        sync = Synchronizer(self.engine, api, Path(self.temp.name) / "media")
        with patch.object(api.opener, "open", side_effect=opened), patch.object(sync, "cache_media") as media:
            self.assertTrue(sync.run(for_study=True))
        media.assert_not_called()
        self.assertEqual(9, len(calls))
        self.assertEqual([], clock.sleeps)
        self.assertAlmostEqual(.18, clock.elapsed)
        for required in ("user", "resets", "subjects", "assignments", "study_materials"):
            self.assertIn(required, calls)

    def test_study_preflight_still_reconciles_external_progress(self):
        self.complete()
        api = FakeApi(self.store)
        body = json.loads(self.store.rows("SELECT body FROM outbox")[0][0])
        api.assignments[body["assignment_id"]]["data"]["available_at"] = stamp(NOW + 86400)
        sync = Synchronizer(self.engine, api, Path(self.temp.name) / "media")
        with patch.object(sync, "cache_media") as media:
            self.assertTrue(sync.run(for_study=True))
        media.assert_not_called()
        self.assertEqual("conflicted", self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual([], api.mutations)

    def test_study_deferral_keeps_missing_required_images_explicitly_unavailable(self):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != 1:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)
        radical = self.store.subject(1)
        radical["data"]["characters"] = None
        radical["data"]["character_images"] = [{"url": "https://wanikani.com/fixture-missing.svg"}]
        self.store.put(radical)
        sync = Synchronizer(self.engine, FakeApi(self.store), Path(self.temp.name) / "media")
        with patch.object(sync, "cache_media") as media:
            self.assertTrue(sync.run(for_study=True))
        media.assert_not_called()
        with self.assertRaises(UserError) as failure:
            self.engine.start("reviews", 1)
        self.assertEqual("empty_queue", failure.exception.code)


class WorkerWakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.worker = Worker(self.directory, lambda value: None)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.worker.engine.status = "offline"
        self.worker.changed = Mock()
        self.worker.last_clock = NOW
        self.worker.last_monotonic = 100
        self.worker.last_elapsed = 100
        self.worker.last_attempt = NOW + 590

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def tick(self, wall, elapsed, monotonic):
        with patch("worker.time.time", return_value=wall), patch("worker.time.monotonic", return_value=monotonic), \
                patch("worker.elapsed_clock", return_value=elapsed):
            self.worker.handle({"v": 1, "id": "tick", "method": "tick"})

    def test_offline_suspend_does_not_revoke_cached_graded_study(self):
        worker = self.worker
        worker.engine.start("reviews", 1)
        worker.engine.draft("saved before suspend")
        self.tick(NOW + 600, 700, 100.1)
        self.assertFalse(worker.engine.clock_untrusted)
        self.assertEqual("offline", worker.engine.status)
        self.assertEqual("saved before suspend", worker.engine.session_view()["draft"])
        self.assertEqual("feedback", worker.engine.answer("fixture wrong answer")["phase"])

    def test_actual_wall_clock_jump_still_blocks_grading(self):
        worker = self.worker
        worker.engine.start("reviews", 1)
        worker.engine.draft("saved before clock change")
        self.tick(NOW + 660, 700, 100.1)
        self.assertTrue(worker.engine.clock_untrusted)
        self.assertEqual("clock_changed", worker.engine.status)
        with self.assertRaises(UserError):
            worker.engine.answer("fixture wrong answer")
        self.assertEqual("saved before clock change", worker.engine.session_view()["draft"])

    def test_wake_queues_refresh_without_overwriting_a_partial_answer(self):
        worker = self.worker
        view = worker.engine.start("reviews", 1)
        worker.engine.draft("saved across refresh")
        api = FakeApi(worker.engine.store)
        assignment = copy.deepcopy(worker.engine.store.related("assignment", view["subject"]["id"]))
        assignment["data"]["available_at"] = stamp(NOW + 86400)
        original_collection = api.collection
        def collection(endpoint, params=None):
            if endpoint == "assignments":
                yield [assignment]
            else:
                yield from original_collection(endpoint, params)
        api.collection = collection
        worker.sync = Synchronizer(worker.engine, api, self.directory / "media")
        worker.job = Mock()
        self.tick(NOW + 600, 700, 100.1)
        worker.job.assert_called_once()
        self.assertIsNone(worker.job.call_args.args[0])
        self.assertFalse(worker.engine.clock_untrusted)
        worker.job.call_args.args[1]()
        self.assertEqual("saved across refresh", worker.engine.session_view()["draft"])
        self.assertEqual([], api.mutations)

    def test_authentication_and_sync_share_one_request_budget(self):
        worker = self.worker
        worker.keyring = Mock()
        instances = []
        user = worker.engine.store.get("user")
        def make_api(token, limiter=None):
            api = Api(token, limiter=limiter)
            api.opener.open = Mock(return_value=Reply(user))
            instances.append(api)
            return api
        with patch("worker.Api", side_effect=make_api), patch.object(Synchronizer, "run", return_value=True):
            worker.authenticate({"token": "fixture-token", "remember": False})
        self.assertEqual(2, len(instances))
        self.assertIs(instances[0].limiter, instances[1].limiter)
        self.assertEqual(1, len(worker.request_budget.requests))

    def test_part_only_advance_does_not_spend_api_quota(self):
        worker = self.worker
        for assignment in worker.engine.store.all("assignment"):
            if assignment["data"]["subject_id"] != 2:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                worker.engine.store.put(assignment)
        view = worker.engine.start("reviews", 1)
        worker.engine.answer(view["subject"]["meanings"][0])
        worker.sync = Mock()
        worker.job = Mock()
        worker.handle({"v": 1, "id": "meaning-next", "method": "advance"})
        worker.job.assert_not_called()
        view = worker.engine.session_view()
        self.assertEqual("reading", view["part"])
        worker.engine.answer(next(r["reading"] for r in view["subject"]["readings"] if r["accepted"]))
        worker.handle({"v": 1, "id": "subject-done", "method": "advance"})
        worker.job.assert_called_once()
        self.assertEqual("pending", worker.engine.store.rows("SELECT state FROM outbox")[0][0])

    def test_boottime_helper_uses_suspend_aware_clock_and_falls_back_safely(self):
        with patch("wanikani.api.time.clock_gettime", return_value=123.4) as clock:
            self.assertEqual(123.4, elapsed_clock())
            clock.assert_called_once()
        with patch("wanikani.api.time.clock_gettime", side_effect=OSError), patch("wanikani.api.time.monotonic", return_value=55):
            self.assertEqual(55, elapsed_clock())


if __name__ == "__main__":
    unittest.main()
