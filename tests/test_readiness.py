import copy
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.api import ApiError
from wanikani.readiness import OfflineReadiness, calculate
from wanikani.sync import Synchronizer


class ReadinessTests(EngineFixture, unittest.TestCase):
    def cache(self, url, filename):
        path = Path(self.temp.name) / "media" / filename
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"independently authored test fixture")
        self.store.execute("INSERT INTO media VALUES(?,?,?,?)", (url, str(path), path.stat().st_size, NOW))
        return path

    def test_all_subject_types_have_correct_cached_readiness(self):
        result = calculate(self.engine)
        self.assertTrue(result["complete"])
        self.assertFalse(result["checking"])
        self.assertEqual((5, 5, 5), tuple(result["reviews"][key] for key in ("total", "checked", "ready")))
        self.assertEqual((3, 3), (result["lessons"]["total"], result["lessons"]["ready"]))
        self.assertEqual(0, result["reviews"]["missing_text"])
        self.assertEqual(0, result["reviews"]["missing_images"])

    def test_image_radical_requires_an_actual_cached_file(self):
        radical = self.store.subject(1)
        radical["data"]["characters"] = None
        radical["data"]["character_images"] = [{"url": "https://wanikani.com/fixture.svg"}]
        self.store.put(radical)
        missing = calculate(self.engine)["reviews"]
        self.assertEqual(1, missing["missing_images"])
        self.assertEqual(4, missing["ready"])
        path = self.cache("https://wanikani.com/fixture.svg", "radical.svg")
        self.assertEqual(5, calculate(self.engine)["reviews"]["ready"])
        path.unlink()
        self.assertEqual(4, calculate(self.engine)["reviews"]["ready"])

    def test_optional_audio_never_blocks_a_graded_item(self):
        vocabulary = self.store.subject(3)
        vocabulary["data"]["pronunciation_audios"] = [{"url": "https://wanikani.com/fixture.mp3"}]
        self.store.put(vocabulary)
        missing = calculate(self.engine)
        self.assertEqual(5, missing["reviews"]["ready"])
        self.assertEqual((1, 0), (missing["reviews"]["audio_total"], missing["reviews"]["audio_cached"]))
        self.assertIn("optional", missing["message"])
        self.cache("https://wanikani.com/fixture.mp3", "audio.mp3")
        self.assertEqual(1, calculate(self.engine)["reviews"]["audio_cached"])

    def test_incomplete_reading_data_is_distinct_from_missing_media(self):
        kanji = self.store.subject(2)
        kanji["data"]["readings"] = []
        self.store.put(kanji)
        result = calculate(self.engine)["reviews"]
        self.assertEqual(4, result["ready"])
        self.assertEqual((1, 0), (result["missing_text"], result["missing_images"]))

    def test_pending_and_conflicted_work_is_excluded_from_offline_cycles(self):
        self.complete(limit=1)
        self.assertEqual(4, calculate(self.engine)["reviews"]["ready"])
        self.store.execute("UPDATE outbox SET state='conflicted'")
        self.assertEqual(4, calculate(self.engine)["reviews"]["ready"])

    def test_entitlement_and_hidden_content_are_not_counted(self):
        subject = self.store.subject(1)
        subject["data"]["level"] = self.engine.max_level() + 1
        self.store.put(subject)
        subject = self.store.subject(2)
        subject["data"]["hidden_at"] = "2026-01-01T00:00:00.000000Z"
        self.store.put(subject)
        self.assertEqual(3, calculate(self.engine)["reviews"]["total"])

    def test_large_queue_and_time_budget_return_honest_partial_counts(self):
        result = calculate(self.engine, max_items=3)
        self.assertFalse(result["complete"])
        self.assertEqual(5, result["reviews"]["total"])
        self.assertEqual(3, result["reviews"]["ready"])
        self.assertEqual(0, result["lessons"]["checked"])
        self.assertIn("partially", result["message"])
        result = calculate(self.engine, budget_seconds=0)
        self.assertFalse(result["complete"])
        self.assertEqual(0, result["reviews"]["checked"])

    def test_cancelled_check_does_not_claim_availability(self):
        result = calculate(self.engine, cancelled=lambda: True)
        self.assertFalse(result["complete"])
        self.assertEqual(0, result["reviews"]["ready"])

    def test_cached_snapshot_never_scans_resources_or_media(self):
        cache = OfflineReadiness(self.engine)
        cache.value = calculate(self.engine)
        with patch.object(self.store, "rows", side_effect=AssertionError("unexpected database scan")), \
                patch("wanikani.readiness.available_file", side_effect=AssertionError("unexpected file scan")):
            value = cache.get()
        self.assertEqual(5, value["reviews"]["ready"])
        value["reviews"]["ready"] = 999
        self.assertEqual(5, cache.get()["reviews"]["ready"])

    def test_refresh_runs_in_background_and_emits_counts(self):
        arrived = threading.Event()
        updates = []
        def changed(value):
            updates.append(value)
            arrived.set()
        cache = OfflineReadiness(self.engine, changed)
        cache.refresh()
        self.assertTrue(arrived.wait(2))
        self.assertEqual(5, updates[-1]["reviews"]["ready"])
        cache.stop()


class SyncProgressTests(EngineFixture, unittest.TestCase):
    def test_stages_and_confirmed_submission_counts_are_reported(self):
        self.complete()
        updates = []
        sync = Synchronizer(self.engine, FakeApi(self.store), Path(self.temp.name) / "media", progress=updates.append)
        self.assertTrue(sync.run())
        stages = [update["stage"] for update in updates]
        self.assertEqual("account", stages[0])
        self.assertIn("subjects", stages)
        self.assertIn("submitting", stages)
        self.assertIn("unlocks", stages)
        self.assertIn("media", stages)
        self.assertEqual("complete", stages[-1])
        self.assertFalse(updates[-1]["active"])
        finished = [update for update in updates if update["stage"] == "submitting"][-1]
        self.assertEqual((1, 1), (finished["completed"], finished["total"]))
        self.assertNotIn(self.engine.user()["username"], json.dumps(updates))

    def test_lost_response_reports_offline_and_keeps_uncertainty(self):
        self.complete()
        api = FakeApi(self.store)
        api.error = ApiError(0, "Offline fixture", uncertain=True)
        updates = []
        sync = Synchronizer(self.engine, api, Path(self.temp.name) / "media", progress=updates.append)
        self.assertFalse(sync.run())
        self.assertEqual("offline", updates[-1]["stage"])
        self.assertFalse(updates[-1]["active"])
        self.assertEqual("uncertain", self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual(1, len(api.mutations))

    def test_presentation_callback_failure_cannot_change_write_outcome(self):
        self.complete()
        def fail(value):
            raise RuntimeError("fixture presentation failure")
        sync = Synchronizer(self.engine, FakeApi(self.store), Path(self.temp.name) / "media", progress=fail)
        self.assertTrue(sync.run())
        self.assertEqual("confirmed", self.store.rows("SELECT state FROM outbox")[0][0])


if __name__ == "__main__":
    unittest.main()
