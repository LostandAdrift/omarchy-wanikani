"""Confirmed milestones use authored account fixtures and mock API responses."""
import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_backend import Engine, EngineFixture, FakeApi, NOW, Store, UserError
from wanikani.api import ApiError
from wanikani.common import stamp
from wanikani.milestones import latest
from wanikani.sync import Synchronizer


class MilestoneTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.connect()

    def connect(self):
        self.api = FakeApi(self.store)
        self.sync = Synchronizer(self.engine, self.api, Path(self.temp.name) / "media")

    def run_sync(self):
        self.assertTrue(self.sync.run(for_study=True))

    def history(self, kind="account_milestone"):
        return [json.loads(row[0]) for row in self.store.rows("SELECT body FROM events WHERE kind=?", (kind,))]

    def restart(self):
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.connect()

    def increase(self, level=4):
        self.api.user["data"]["level"] = level
        self.run_sync()
        return self.engine.snapshot()["milestone"]

    def reset_resource(self):
        return {"id": 990091, "object": "reset", "data": {"target_level": 1, "confirmed_at": stamp(NOW)}}

    def test_first_successful_sync_establishes_baseline_without_celebration(self):
        self.api.user["data"]["level"] = 20
        self.run_sync()
        self.assertIsNone(self.engine.snapshot()["milestone"])
        self.assertEqual([], self.history())
        self.assertEqual(20, self.store.get("milestone_observation")["level"])

    def test_same_account_increase_is_publicly_attributed_to_wanikani(self):
        self.run_sync()
        milestone = self.increase(5)
        self.assertEqual({"id", "level", "confirmed_at", "source"}, set(milestone))
        self.assertEqual((5, stamp(NOW), "WaniKani account"), tuple(milestone[key] for key in ("level", "confirmed_at", "source")))
        self.assertEqual(milestone["id"], self.history()[0]["id"])
        self.assertEqual([], self.engine.snapshot()["activity"])

    def test_repeated_sync_and_restart_cannot_duplicate_an_unacknowledged_level(self):
        self.run_sync()
        first = self.increase()
        self.run_sync()
        self.restart()
        self.run_sync()
        self.assertEqual(first, self.engine.snapshot()["milestone"])
        self.assertEqual(1, len(self.history()))

    def test_acknowledgement_is_durable_id_specific_and_preserves_history(self):
        self.run_sync()
        milestone = self.increase()
        result = self.engine.command("ack-once", "ack_milestone", {"id": milestone["id"]})
        self.assertTrue(result["acknowledged"])
        self.assertIsNone(latest(self.engine))
        self.assertEqual(result, self.engine.command("ack-once", "ack_milestone", {"id": milestone["id"]}))
        self.assertFalse(self.engine.command("ack-twice", "ack_milestone", {"id": milestone["id"]})["acknowledged"])
        self.restart()
        self.run_sync()
        self.assertIsNone(latest(self.engine))
        self.assertEqual((1, 1), (len(self.history()), len(self.history("milestone_ack"))))

    def test_stale_acknowledgement_cannot_clear_a_newer_milestone(self):
        self.run_sync()
        older = self.increase(4)
        newer = self.increase(5)
        self.assertFalse(self.engine.command("ack-old", "ack_milestone", {"id": older["id"]})["acknowledged"])
        self.assertEqual(newer, latest(self.engine))

    def test_invalid_acknowledgement_preserves_pending_display(self):
        self.run_sync()
        milestone = self.increase()
        for invalid in (None, "", 5, [], "x" * 161):
            with self.subTest(invalid=invalid), self.assertRaises(UserError):
                self.engine.command("invalid-ack", "ack_milestone", {"id": invalid})
            self.assertEqual(milestone, latest(self.engine))

    def test_downshift_clears_pending_and_does_not_recelebrate_an_awarded_level(self):
        self.run_sync()
        self.increase(4)
        self.api.user["data"]["level"] = 2
        self.run_sync()
        self.assertIsNone(latest(self.engine))
        self.assertIsNone(self.increase(4))
        self.assertEqual(1, len(self.history()))
        self.assertEqual(5, self.increase(5)["level"])

    def test_an_account_switch_is_a_new_baseline_and_never_reuses_old_display(self):
        self.run_sync()
        self.increase(4)
        old_observation = self.store.get("milestone_observation")
        self.api.user["id"] = "other-authored-account"
        self.api.user["data"]["level"] = 30
        self.assertFalse(self.sync.run(for_study=True))
        self.assertEqual(old_observation, self.store.get("milestone_observation"))
        self.store.set("account_id", self.api.user["id"])
        self.store.set("user", self.api.user)
        self.assertIsNone(latest(self.engine))
        self.run_sync()
        self.assertIsNone(latest(self.engine))
        self.assertEqual(1, len(self.history()))
        self.assertEqual(31, self.increase(31)["level"])

    def test_demo_and_local_pending_results_cannot_create_account_milestones(self):
        self.run_sync()
        self.complete(limit=1)
        self.assertIsNone(latest(self.engine))
        self.assertEqual([], self.history())
        self.engine.demo = True
        self.api.user["data"]["level"] = 4
        self.run_sync()
        self.assertIsNone(latest(self.engine))
        self.assertEqual([], self.history())

    def test_confirmed_post_write_account_refresh_can_create_the_milestone(self):
        self.run_sync()
        self.complete(limit=1)
        original = self.api.request
        calls = 0
        def request(path, *args, **kwargs):
            nonlocal calls
            resource, etag = original(path, *args, **kwargs)
            if path == "user":
                calls += 1
                resource = copy.deepcopy(resource)
                resource["data"]["level"] = 4 if calls > 1 else 3
            return resource, etag
        with patch.object(self.api, "request", side_effect=request):
            self.run_sync()
        self.assertEqual(2, calls)
        self.assertEqual(4, latest(self.engine)["level"])
        self.assertEqual(1, len(self.api.mutations))

    def test_malformed_account_responses_never_advance_the_observation(self):
        self.run_sync()
        before = self.store.get("milestone_observation")
        valid = copy.deepcopy(self.api.user)
        for level in (None, True, "4", 0, 61):
            with self.subTest(level=level):
                self.api.user = copy.deepcopy(valid)
                self.api.user["data"]["level"] = level
                self.assertFalse(self.sync.run(for_study=True))
                self.assertEqual(before, self.store.get("milestone_observation"))
                self.assertEqual([], self.history())
        self.api.user = copy.deepcopy(valid)
        self.api.user["data"].update(level=4, username=None)
        self.run_sync()
        self.assertEqual(before, self.store.get("milestone_observation"))
        self.assertEqual([], self.history())

    def test_failure_after_account_fetch_does_not_emit_or_consume_the_increase(self):
        self.run_sync()
        self.api.user["data"]["level"] = 4
        with patch.object(self.api, "collection", side_effect=ApiError(0, "authored offline interruption")):
            self.assertFalse(self.sync.run(for_study=True))
        self.assertIsNone(latest(self.engine))
        self.assertEqual(3, self.store.get("milestone_observation")["level"])
        self.restart()
        self.run_sync()
        self.assertEqual(4, latest(self.engine)["level"])
        self.assertEqual(1, len(self.history()))

    def test_newly_confirmed_reset_suppresses_increase_but_future_progress_can_celebrate(self):
        self.run_sync()
        self.increase(4)
        reset = self.reset_resource()
        unconfirmed = copy.deepcopy(reset)
        unconfirmed["data"]["confirmed_at"] = None
        self.store.put(unconfirmed)
        self.api.resets = [reset]
        self.api.user["data"]["level"] = 5
        self.run_sync()
        self.assertIsNone(latest(self.engine))
        self.assertEqual(1, len(self.history()))
        self.assertEqual(1, self.store.get("milestone_reset_generation"))
        self.assertEqual(6, self.increase(6)["level"])
        self.assertEqual(1, self.store.get("milestone_reset_generation"))

    def test_reset_suppression_survives_failure_and_restart_before_completion(self):
        self.run_sync()
        self.increase(4)
        self.api.resets = [self.reset_resource()]
        self.api.user["data"]["level"] = 5
        original = self.api.collection
        def collection(endpoint, params=None):
            if endpoint == "subjects":
                raise ApiError(0, "authored interruption after reset")
            return original(endpoint, params)
        with patch.object(self.api, "collection", side_effect=collection):
            self.assertFalse(self.sync.run(for_study=True))
        self.assertIsNone(latest(self.engine))
        self.restart()
        self.run_sync()
        self.assertIsNone(latest(self.engine))
        self.assertEqual(1, len(self.history()))

    def test_reset_marker_rolls_back_with_failed_reset_observation(self):
        self.run_sync()
        milestone = self.increase(4)
        self.api.resets = [self.reset_resource()]
        original = self.store.put
        def fail(resource):
            if resource["object"] == "reset":
                raise OSError("authored reset persistence interruption")
            return original(resource)
        with patch.object(self.store, "put", side_effect=fail):
            self.assertFalse(self.sync.run(for_study=True))
        self.assertIsNone(self.store.get("milestone_reset_generation"))
        self.assertEqual(milestone, latest(self.engine))

    def test_actual_process_exit_at_each_milestone_boundary_never_duplicates_history(self):
        script = '''
import os, sys
from pathlib import Path
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani.milestones import observe
store = Store(Path(sys.argv[1]))
engine = Engine(store)
boundary = sys.argv[2]
original_set, original_event = store.set, store.event
def write(key, value):
    original_set(key, value)
    if key == boundary: os._exit(77)
def event(*args):
    original_event(*args)
    if boundary == 'event': os._exit(77)
store.set, store.event = write, event
observe(engine)
os._exit(77)
'''
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
        for boundary in ("event", "pending_milestone", "milestone_observation", "committed"):
            with self.subTest(boundary=boundary):
                self.store.set("milestone_observation", None)
                self.store.set("pending_milestone", None)
                self.store.execute("DELETE FROM events WHERE kind='account_milestone'")
                self.api.user["data"]["level"] = 3
                self.run_sync()
                user = self.store.get("user")
                user["data"]["level"] = 4
                self.store.set("user", user)
                result = subprocess.run([sys.executable, "-c", script, str(self.path), boundary], env=environment, capture_output=True, timeout=10)
                self.assertEqual(77, result.returncode, result.stderr.decode())
                self.assertEqual(1 if boundary == "committed" else 0, len(self.history()))
                self.restart()
                self.run_sync()
                self.assertEqual(1, len(self.history()))
                self.assertEqual(4, latest(self.engine)["level"])


if __name__ == "__main__":
    unittest.main()
