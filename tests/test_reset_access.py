"""A reset must recover even when cached subject access metadata is broken."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.common import stamp
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani.sync import Synchronizer


class ResetAccessTests(EngineFixture, unittest.TestCase):
    def complete_one(self):
        self.complete(limit=1)
        return dict(self.store.rows("SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1")[0])

    def test_unknown_levels_preserve_local_work_and_accept_remote_reset(self):
        # JSON booleans and integer-looking floats/strings are not valid levels.
        for level in (None, True, False, 0, -1, 61, 1.0, "1", [], {}):
            with self.subTest(level=level), tempfile.TemporaryDirectory() as directory:
                original_store, original_engine = self.store, self.engine
                self.store = Store(Path(directory) / "state.sqlite3")
                populate(self.store, NOW)
                self.engine = Engine(self.store, clock=lambda: NOW)
                try:
                    self.verify_reset_with_unknown_subject(level)
                finally:
                    self.store.close()
                    self.store, self.engine = original_store, original_engine

    def test_missing_subject_preserves_local_work_and_accepts_remote_reset(self):
        self.verify_reset_with_unknown_subject(None, missing=True)

    def verify_reset_with_unknown_subject(self, level, missing=False):
        kept = self.complete_one()
        affected = self.complete_one()
        graded = self.engine.start("reviews", 1)
        self.engine.draft("This unfinished answer survives the account reset.")
        graded_before = self.store.session(graded["id"])
        practice = self.engine.start("practice", 1, [kept["subject_id"]])
        practice_before = self.store.session(practice["id"])
        affected_subjects = {affected["subject_id"], graded["subject"]["id"], 6}
        for sid in affected_subjects:
            subject = self.store.subject(sid)
            if missing:
                self.store.execute("DELETE FROM resources WHERE id=? AND kind=?", (str(sid), subject["object"]))
            else:
                subject["data"]["level"] = level
                self.store.put(subject)
        # Vacation leaves the known, below-target pending review untouched by
        # the later flush; this fixture exercises reset acceptance, not writes.
        user = self.store.get("user")
        user["data"]["current_vacation_started_at"] = stamp(NOW)
        self.store.set("user", user)
        api = FakeApi(self.store)
        api.resets = [{"id": 91, "object": "reset", "data": {
            "confirmed_at": stamp(NOW), "target_level": 2}}]
        sync = Synchronizer(self.engine, api, Path(self.temp.name) / "media")
        self.assertTrue(sync.run(for_study=True))
        self.assertEqual("online", self.engine.status)
        self.assertEqual(api.resets[0], self.store.resource("reset", 91))
        self.assertEqual(stamp(NOW - 2), self.store.get("reset_cursor"))
        row = dict(self.store.rows("SELECT * FROM outbox WHERE id=?", (affected["id"],))[0])
        self.assertEqual("conflicted", row["state"])
        self.assertIn("cached level could not be verified", row["detail"])
        for key in ("id", "kind", "subject_id", "body", "created_at"):
            self.assertEqual(affected[key], row[key])
        self.assertEqual(kept, dict(self.store.rows("SELECT * FROM outbox WHERE id=?", (kept["id"],))[0]))
        saved = self.store.session(graded["id"])
        self.assertEqual("complete", saved["phase"])
        self.assertEqual("Account reset", saved["invalidated"])
        for key in ("id", "queue", "draft", "completed", "overrides", "started_at"):
            self.assertEqual(graded_before[key], saved[key])
        self.assertEqual(practice_before, self.store.session(practice["id"]))
        self.assertEqual(practice["id"], self.engine.session_view()["id"])
        for sid in affected_subjects:
            self.assertIsNone(self.store.related("assignment", sid))
            self.assertIsNone(self.store.related("review_statistic", sid))
        self.assertIsNotNone(self.store.related("assignment", kept["subject_id"]))
        self.assertEqual([], api.mutations)

    def test_failure_to_record_reset_rolls_back_unknown_level_invalidation(self):
        affected = self.complete_one()
        subject = self.store.subject(affected["subject_id"])
        subject["data"]["level"] = "1"
        self.store.put(subject)
        before = self.store.related("assignment", affected["subject_id"])
        api = FakeApi(self.store)
        api.resets = [{"id": 91, "object": "reset", "data": {
            "confirmed_at": stamp(NOW), "target_level": 2}}]
        sync = Synchronizer(self.engine, api, Path(self.temp.name) / "media")
        original = self.store.put
        def put(resource):
            if resource["object"] == "reset":
                raise OSError("Authored interruption before recording reset observation")
            return original(resource)
        with patch.object(self.store, "put", side_effect=put):
            self.assertFalse(sync.run(for_study=True))
        self.assertIsNone(self.store.resource("reset", 91))
        self.assertEqual(affected, dict(self.store.rows("SELECT * FROM outbox WHERE id=?", (affected["id"],))[0]))
        self.assertEqual(before, self.store.related("assignment", affected["subject_id"]))
        self.assertEqual([], api.mutations)


if __name__ == "__main__":
    unittest.main()
