"""SRS worker routes are strict cached reads, including guarded detail links."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.common import UserError, stamp
from wanikani.demo import populate
from worker import Worker


class SrsWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(Path(self.directory.name), self.messages.append)
        self.engine = self.worker.engine
        self.store = self.engine.store
        self.engine.clock = lambda: NOW
        populate(self.store, NOW)
        self.store.set("user", {"object": "user", "data": {
            "id": "authored-srs-account", "username": "PRIVATE LEARNER", "level": 3,
            "subscription": {"type": "lifetime", "max_level_granted": 60}}})
        self.store.set("account_id", "authored-srs-account")
        for kind in ("subjects", "assignments", "review_statistics"):
            self.store.set("cursor_" + kind, stamp(NOW - 1))
        self.engine.start("practice", 1, [2])
        self.engine.draft("PRIVATE SAVED ANSWER")
        self.store.event("authored-history", 2, "answer", stamp(NOW), {"answer": "PRIVATE HISTORICAL ANSWER"})
        self.store.set("last_study_at", NOW - 3600)
        # Any accidental fall-through to a mutating or broad event path is a
        # fixture failure, even if that path happens to make no database write.
        for name in ("changed", "session_changed", "snapshot", "command", "note_study_activity", "job"):
            setattr(self.worker, name, Mock(side_effect=AssertionError("SRS read called worker." + name)))
        self.worker.readiness.refresh = Mock(side_effect=AssertionError("SRS read started a cache check"))
        self.engine.snapshot = Mock(side_effect=AssertionError("SRS read built a full snapshot"))
        self.worker.sync = Mock()
        self.worker.sync.run.side_effect = AssertionError("SRS read requested account synchronization")
        self.network = patch("socket.create_connection", side_effect=AssertionError("No network in SRS worker fixtures"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.store.close()
        self.directory.cleanup()

    def request(self, method="srs_catalogue", args=None):
        self.messages.clear()
        request = {"v": 1, "id": "authored-srs-read", "method": method}
        if args is not None:
            request["args"] = args
        self.worker.handle(request)
        self.assertEqual(1, len(self.messages), "Exactly one reply; no state, session, or readiness events")
        response = self.messages[0]
        self.assertEqual((1, "authored-srs-read", True), (response["v"], response["id"], response["ok"]))
        self.assertNotIn("event", response)
        return response["data"]

    def preserved(self):
        return self.store.db.serialize(), self.store.db.total_changes

    def assert_preserved(self, before):
        self.assertEqual(before, self.preserved())
        self.worker.keyring.get.assert_not_called()
        self.worker.keyring.set.assert_not_called()
        self.worker.keyring.delete.assert_not_called()
        self.worker.sync.run.assert_not_called()

    def test_default_catalogue_forwards_only_documented_defaults(self):
        before = self.preserved()
        with patch("wanikani.srs_explorer.catalogue", return_value={"authored": "projection"}) as catalogue:
            self.assertEqual({"authored": "projection"}, self.request())
        catalogue.assert_called_once_with(self.engine, group="apprentice", subject_type=None, level=None,
            stage=None, order="level", offset=0, limit=24)
        self.assert_preserved(before)

    def test_explicit_catalogue_filters_forward_without_coercion(self):
        args = {"group": "guru", "subject_type": "vocabulary", "level": 2, "stage": 5,
            "order": "next_review", "offset": 3, "limit": 2}
        before = self.preserved()
        with patch("wanikani.srs_explorer.catalogue", return_value={"authored": "filtered"}) as catalogue:
            self.assertEqual({"authored": "filtered"}, self.request(args=args))
        catalogue.assert_called_once_with(self.engine, **args)
        self.assert_preserved(before)

    def test_actual_pages_preserve_saved_draft_history_and_reminder_activity(self):
        before = self.preserved()
        first = self.request(args={"limit": 2})
        self.assertEqual([1, 2], [item["id"] for item in first["items"]])
        self.assertEqual(("apprentice", 5, 2), (first["group"], first["total"], first["next_offset"]))
        second = self.request(args={"offset": 2, "limit": 2})
        self.assertEqual([3, 4], [item["id"] for item in second["items"]])
        filtered = self.request(args={"group": "guru", "subject_type": "vocabulary", "level": 2, "stage": 5})
        self.assertEqual([10, 12, 14, 15, 16], [item["id"] for item in filtered["items"]])
        self.assertNotIn("PRIVATE", json.dumps([first, second, filtered]))
        self.assert_preserved(before)

    def test_catalogue_rejects_extra_keys_before_calling_backend(self):
        before = self.preserved()
        with patch("wanikani.srs_explorer.catalogue") as catalogue:
            for key, value in (("account_id", "other"), ("now", NOW), ("subject_ids", [2]),
                    ("url", "https://authored.invalid"), ("session_id", "saved"), ("action", "start"), ("refresh", True)):
                with self.subTest(key=key), self.assertRaises(UserError):
                    self.request(args={key: value})
                self.assertEqual([], self.messages)
            catalogue.assert_not_called()
        self.assert_preserved(before)

    def test_catalogue_backend_rejects_bad_types_ranges_and_mismatched_stage(self):
        cases = [{"group": value} for value in (None, True, [], "bogus")]
        cases += [{"subject_type": value} for value in (False, [], "word")]
        cases += [{"level": value} for value in (True, 0, -1, 61, 2.0, "2")]
        cases += [{"stage": value} for value in (True, 0, 5, 10, "2")]
        cases += [{"order": value} for value in (None, False, [], "random")]
        cases += [{"offset": value} for value in (True, -1, 12001, "0")]
        cases += [{"limit": value} for value in (True, 0, 61, "24")]
        before = self.preserved()
        for args in cases:
            with self.subTest(args=args), self.assertRaises(UserError):
                self.request(args=args)
            self.assertEqual([], self.messages)
        self.assert_preserved(before)

    def test_progress_details_uses_the_atomic_guarded_adapter(self):
        before = self.preserved()
        with patch("wanikani.srs_explorer.guarded_details", return_value={"id": 4, "authored": True}) as guarded:
            self.assertEqual({"id": 4, "authored": True}, self.request("progress_details", {"subject_id": 4}))
        guarded.assert_called_once_with(self.engine, 4)
        self.assert_preserved(before)

    def test_actual_guarded_detail_is_a_read_without_session_or_outbox_effects(self):
        before = self.preserved()
        detail = self.request("progress_details", {"subject_id": 4})
        self.assertEqual((4, "水", ["water"]), (detail["id"], detail["characters"], detail["meanings"]))
        self.assertNotIn("PRIVATE", json.dumps(detail))
        self.assert_preserved(before)

    def test_details_rejects_missing_or_extra_keys_before_backend_guard(self):
        before = self.preserved()
        with patch("wanikani.srs_explorer.guarded_details") as guarded:
            for args in ({}, {"id": 4}, {"subject_id": 4, "context": "lookup"},
                    {"subject_id": 4, "allow_protected": True}, {"subject_id": 4, "revision": 1}):
                with self.subTest(args=args), self.assertRaises(UserError):
                    self.request("progress_details", args)
                self.assertEqual([], self.messages)
            guarded.assert_not_called()
        self.assert_preserved(before)

    def test_details_rejects_boolean_string_and_out_of_range_ids_without_coercion(self):
        before = self.preserved()
        for identity in (True, False, 0, -1, 4.0, "4", None, [], {}, 9007199254740992):
            with self.subTest(identity=identity), self.assertRaises(UserError):
                self.request("progress_details", {"subject_id": identity})
            self.assertEqual([], self.messages)
        self.assert_preserved(before)

    def test_prior_openable_card_cannot_bypass_new_graded_subject_or_written_alias_protection(self):
        prior = self.request()
        self.assertTrue(next(item for item in prior["items"] if item["id"] == 2)["can_open"])
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != 2 and assignment["data"]["started_at"]:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)
        self.engine.start("reviews", 1)
        self.engine.draft("PRIVATE GRADED ANSWER")
        alias = copy.deepcopy(self.store.subject(4))
        alias["id"] = 99
        alias["data"]["characters"] = "山"
        self.store.put(alias)
        assignment = copy.deepcopy(self.store.related("assignment", 4))
        assignment["id"] = 199
        assignment["data"]["subject_id"] = 99
        self.store.put(assignment)
        before = self.preserved()
        with patch.object(self.engine, "details", side_effect=AssertionError("Protected link must not hydrate details")):
            for identity in (2, 99):
                with self.subTest(identity=identity), self.assertRaises(UserError) as failure:
                    self.request("progress_details", {"subject_id": identity})
                self.assertEqual("protected_study", failure.exception.code)
        page = self.request()
        for item in page["items"]:
            if item["id"] in (2, 99):
                self.assertFalse(item["can_open"])
                self.assertEqual("", item["meaning"])
        self.assertNotIn("PRIVATE", json.dumps(page))
        self.assert_preserved(before)

    def test_changed_account_identity_blocks_both_cached_routes_without_clearing_private_state(self):
        self.store.set("account_id", "different-authored-account")
        before = self.preserved()
        for method, args in (("srs_catalogue", {}), ("progress_details", {"subject_id": 4})):
            with self.subTest(method=method), self.assertRaises(UserError) as failure:
                self.request(method, args)
            self.assertEqual("account_mismatch", failure.exception.code)
        self.assert_preserved(before)

    def test_existing_account_and_media_jobs_do_not_turn_reads_into_queued_work(self):
        self.worker.job_lock.acquire()
        self.worker.audio_job_lock.acquire()
        self.worker.account_job = True
        self.engine.syncing = True
        before = self.preserved()
        try:
            self.assertEqual(5, self.request()["total"])
            self.assertEqual(4, self.request("progress_details", {"subject_id": 4})["id"])
            self.assertTrue(self.worker.job_lock.locked())
            self.assertTrue(self.worker.audio_job_lock.locked())
        finally:
            self.worker.job_lock.release()
            self.worker.audio_job_lock.release()
        self.assert_preserved(before)

    def test_non_object_arguments_are_rejected_by_the_protocol_envelope(self):
        before = self.preserved()
        for method in ("srs_catalogue", "progress_details"):
            for value in (None, False, 0, [], "PRIVATE MALFORMED"):
                self.messages.clear()
                with self.subTest(method=method, value=value), self.assertRaises(UserError):
                    self.worker.handle({"v": 1, "id": "authored-invalid", "method": method, "args": value})
                self.assertEqual([], self.messages)
        self.assert_preserved(before)


if __name__ == "__main__":
    unittest.main()
