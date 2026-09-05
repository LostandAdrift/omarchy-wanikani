"""Authored /user envelopes follow WaniKani's documented nested-ID shape.

https://docs.api.wanikani.com/20170710/#user-data-structure
No credentials or account data from a real user are used by these regressions.
"""
import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_backend import EngineFixture, FakeApi, NOW, UserError
from wanikani.api import ApiError, user_id, validate_user
from wanikani.common import stamp
from wanikani.milestones import latest
from wanikani.sync import Synchronizer
from worker import Worker


ACCOUNT_A = "11111111-2222-4333-8444-555555555555"
ACCOUNT_B = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def documented_user(identity=ACCOUNT_A, level=3):
    return {"object": "user", "url": "https://api.wanikani.com/v2/user",
        "data_updated_at": stamp(NOW), "data": {
            "id": identity, "username": "Authored learner", "level": level,
            "profile_url": "https://www.wanikani.com/users/authored-learner",
            "started_at": stamp(NOW - 86400), "current_vacation_started_at": None,
            "subscription": {"active": False, "type": "free", "max_level_granted": 3, "period_ends_at": None},
            "preferences": {"reviews_autoplay_audio": True}}}


class UserIdentityTests(unittest.TestCase):
    def test_documented_uuid_is_nested_and_envelope_is_not_rewritten(self):
        resource = documented_user()
        before = copy.deepcopy(resource)
        self.assertIs(resource, validate_user(resource))
        self.assertEqual(ACCOUNT_A, user_id(resource))
        self.assertEqual(before, resource)
        self.assertNotIn("id", resource)

    def test_matching_legacy_alias_is_safe_but_conflicting_alias_is_rejected(self):
        resource = documented_user()
        resource["id"] = ACCOUNT_A
        self.assertEqual(ACCOUNT_A, user_id(validate_user(resource)))
        for alias in (ACCOUNT_B, 1, True, None, ""):
            with self.subTest(alias=alias), self.assertRaises(ApiError):
                validate_user({**resource, "id": alias})

    def test_malformed_nested_identity_never_falls_back_to_legacy(self):
        for identity in (None, True, 1, 1.0, {}, [], "", " ", "in valid", "x\n", "x\x00y", "x" * 161):
            with self.subTest(identity=identity), self.assertRaises(ApiError):
                resource = documented_user(identity)
                resource["id"] = ACCOUNT_A
                validate_user(resource)

    def test_legacy_stored_identity_is_supported_only_when_unambiguous(self):
        resource = documented_user()
        del resource["data"]["id"]
        for identity in (ACCOUNT_A, "demo", 42):
            with self.subTest(identity=identity):
                resource["id"] = identity
                self.assertEqual(identity, user_id(validate_user(resource)))
        for identity in (None, True, False, 0, -1, {}, [], "", "bad identity"):
            with self.subTest(identity=identity), self.assertRaises(ApiError):
                validate_user({**resource, "id": identity})

    def test_documented_shape_still_requires_valid_access_information(self):
        for field, value in (("level", True), ("level", "3"), ("level", 0), ("level", 61), ("subscription", None)):
            with self.subTest(field=field, value=value), self.assertRaises(ApiError):
                resource = documented_user()
                resource["data"][field] = value
                validate_user(resource)
        for maximum in (None, True, "3", -1, 61):
            with self.subTest(maximum=maximum), self.assertRaises(ApiError):
                resource = documented_user()
                resource["data"]["subscription"]["max_level_granted"] = maximum
                validate_user(resource)


class AccountEnvelopeIntegrationTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store.set("account_id", ACCOUNT_A)
        self.store.set("user", documented_user())
        self.api = FakeApi(self.store)
        self.sync = Synchronizer(self.engine, self.api, Path(self.temp.name) / "media")

    def worker(self):
        worker = Worker.__new__(Worker)
        worker.engine = self.engine
        worker.directory = Path(self.temp.name)
        worker.request_budget = Mock()
        worker.keyring = Mock()
        worker.keyring.set.return_value = True
        worker.keyring.may_have_written = False
        worker.token = None
        worker.sync = None
        return worker

    def test_first_authentication_and_keyring_use_nested_uuid_without_write_scopes(self):
        self.store.execute("DELETE FROM meta WHERE key IN ('account_id','user')")
        worker = self.worker()
        # /user does not expose token permissions; read-only tokens can connect.
        self.assertNotIn("permissions", self.api.user["data"])
        with patch("worker.Api", return_value=self.api), patch.object(Synchronizer, "run", return_value=True) as sync:
            response = worker.authenticate({"token": "authored-fixture-token", "remember": True})
        self.assertTrue(response["connected"])
        self.assertTrue(response["remembered"])
        self.assertEqual(ACCOUNT_A, self.store.get("account_id"))
        self.assertNotIn("id", self.store.get("user"))
        worker.keyring.set.assert_called_once_with(ACCOUNT_A, "authored-fixture-token")
        sync.assert_called_once_with()
        self.assertEqual([], self.api.mutations)

    def test_authentication_account_mismatch_preserves_all_study_and_credentials(self):
        self.complete()
        worker = self.worker()
        worker.token = "previous-authored-token"
        previous_sync = Mock()
        worker.sync = previous_sync
        self.api.user = documented_user(ACCOUNT_B)
        before = list(self.store.db.iterdump())
        with patch("worker.Api", return_value=self.api), self.assertRaises(UserError) as failure:
            worker.authenticate({"token": "different-authored-token"})
        self.assertEqual("account_mismatch", failure.exception.code)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual("previous-authored-token", worker.token)
        self.assertIs(previous_sync, worker.sync)
        self.assertEqual([], worker.keyring.mock_calls)
        self.assertEqual([], self.api.mutations)

    def test_malformed_nested_identity_preserves_authentication_state(self):
        self.api.user["id"] = ACCOUNT_A
        self.api.user["data"]["id"] = None
        worker = self.worker()
        before = list(self.store.db.iterdump())
        with patch("worker.Api", return_value=self.api), self.assertRaises(ApiError):
            worker.authenticate({"token": "authored-fixture-token"})
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual([], worker.keyring.mock_calls)

    def test_sync_accepts_documented_shape_and_preserves_milestone_identity(self):
        self.assertTrue(self.sync.run(for_study=True))
        self.assertIsNone(latest(self.engine))
        self.api.user["data"]["level"] = 4
        self.assertTrue(self.sync.run(for_study=True))
        milestone = latest(self.engine)
        self.assertEqual(4, milestone["level"])
        self.assertEqual(ACCOUNT_A, self.store.get("milestone_observation")["account_id"])
        self.assertNotIn("id", self.store.get("user"))
        self.assertEqual([], self.api.mutations)

    def test_sync_mismatch_stops_before_replaying_pending_work(self):
        self.complete()
        before = list(self.store.db.iterdump())
        self.api.user = documented_user(ACCOUNT_B)
        self.assertFalse(self.sync.run(for_study=True))
        self.assertEqual("account_mismatch", self.engine.status)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual([], self.api.mutations)

    def test_post_write_refresh_checks_same_documented_uuid(self):
        self.sync.refresh_after_writes()
        self.assertEqual(documented_user(), self.store.get("user"))
        before = list(self.store.db.iterdump())
        self.api.user = documented_user(ACCOUNT_B)
        with self.assertRaises(UserError) as failure:
            self.sync.refresh_after_writes()
        self.assertEqual("account_mismatch", failure.exception.code)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual([], self.api.mutations)

    def test_nested_response_can_refresh_same_legacy_cached_identity(self):
        legacy = documented_user()
        legacy["id"] = legacy["data"].pop("id")
        self.store.set("user", legacy)
        self.assertTrue(self.sync.run(for_study=True))
        self.assertEqual(ACCOUNT_A, user_id(self.store.get("user")))
        self.assertNotIn("id", self.store.get("user"))


if __name__ == "__main__":
    unittest.main()
