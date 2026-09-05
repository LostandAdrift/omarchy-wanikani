"""Schedule indexes preserve eligibility and the Python forecast date rules."""
import copy
import random
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW, stamp
from test_history import timezone
from wanikani.store import Store


class ScheduleQueryTests(EngineFixture, unittest.TestCase):
    def unindexed_snapshot(self):
        original = self.store.rows

        def without_schedule_indexes(sql, args=()):
            sql = sql.replace(" INDEXED BY resource_assignment_schedule", "")
            sql = sql.replace(" INDEXED BY resource_search_identity", "")
            return original(sql, args)

        with patch.object(self.store, "rows", side_effect=without_schedule_indexes):
            return self.engine.snapshot()

    def populate_mixed(self, seed, count=300):
        rng = random.Random(seed)
        subject, assignment = self.store.subject(1), self.store.related("assignment", 1)
        dates = [None, "", "invalid", "1970-01-01T00:00:00Z", stamp(NOW - 1), stamp(NOW),
            stamp(NOW + 1), stamp(NOW + 86400), "2026-09-04T12:00:00-07:00",
            "2026-09-04T19:00:00", 12345, {"invalid": "authored"}, "0001-01-01T00:00:00Z"]
        with self.store.transaction():
            for sid in range(100, count + 100):
                item = copy.deepcopy(subject)
                item["id"] = sid
                item["object"] = rng.choice(("radical", "kanji", "vocabulary", "kana_vocabulary"))
                item["data"]["level"] = rng.choice([1, 3, 20, 60, 61, "3", None, True])
                item["data"]["hidden_at"] = rng.choice([None, None, None, False, stamp(NOW - 1)])
                self.store.put(item)
                if rng.randrange(10) == 0:
                    continue
                item = copy.deepcopy(assignment)
                item["id"] = sid + 10000
                item["data"]["subject_id"] = str(sid) if sid % 2 else sid
                for field in ("started_at", "available_at", "unlocked_at"):
                    item["data"][field] = rng.choice(dates)
                item["data"]["burned_at"] = rng.choice([None, None, None, stamp(NOW - 1), "invalid"])
                item["data"]["hidden"] = rng.choice([None, False, False, True, 0, 1, "0"])
                self.store.put(item)
                if rng.randrange(30) == 0:
                    item["id"] += 10000
                    self.store.put(item)
                if rng.randrange(4) == 0:
                    self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (
                        "authored-" + str(sid), rng.choice(("review", "lesson", "material")), sid,
                        rng.choice(("pending", "inflight", "uncertain", "blocked", "conflicted", "confirmed", "discarded")),
                        "{}", stamp(NOW), "Authored schedule fixture"))

    def test_randomized_full_snapshot_equivalence(self):
        for seed in range(6):
            # Each seed deliberately replaces the authored catalogue fields and
            # adds fresh assignment/outbox variants before comparing both paths.
            self.store.execute("DELETE FROM outbox")
            self.store.execute("""DELETE FROM resources WHERE
              (kind IN ('radical','kanji','vocabulary','kana_vocabulary') AND CAST(id AS INTEGER)>=100)
              OR (kind='assignment' AND CAST(json_extract(body,'$.data.subject_id') AS INTEGER)>=100)""")
            self.populate_mixed(seed)
            for zone in ("UTC", "America/Los_Angeles", "Asia/Tokyo"):
                with timezone(zone):
                    for maximum, expired in ((0, False), (3, False), (20, False), (60, False), (60, True)):
                        with self.subTest(seed=seed, zone=zone, maximum=maximum, expired=expired):
                            user = self.store.get("user")
                            user["data"]["subscription"].update(type="recurring", max_level_granted=maximum,
                                period_ends_at=stamp(NOW - 1 if expired else NOW + 86400))
                            self.store.set("user", user)
                            self.assertEqual(min(3, maximum) if expired else maximum, self.engine.max_level())
                            self.assertEqual(self.unindexed_snapshot(), self.engine.snapshot())

    def test_catalogue_size_fixture_uses_both_indexes_without_timing_thresholds(self):
        subject, assignment = self.store.subject(1), self.store.related("assignment", 1)
        with self.store.transaction():
            for sid in range(100, 9100):
                item = copy.deepcopy(subject)
                item["id"] = sid
                item["data"]["level"] = sid % 60 + 1
                item["data"]["meaning_mnemonic"] = "Independently authored large catalogue mnemonic. " * 20
                self.store.put(item)
                item = copy.deepcopy(assignment)
                item["id"] = sid + 10000
                item["data"]["subject_id"] = sid
                item["data"]["available_at"] = stamp(NOW - 1 if sid % 3 == 0 else NOW + sid * 60)
                self.store.put(item)
        expected = self.unindexed_snapshot()
        captured = []
        original = self.store.rows

        def trace(sql, args=()):
            if "resources a INDEXED BY resource_assignment_schedule" in sql:
                captured.append((sql, [row[3] for row in original("EXPLAIN QUERY PLAN " + sql, args)]))
            return original(sql, args)

        with patch.object(self.store, "rows", side_effect=trace):
            self.assertEqual(expected, self.engine.snapshot())
        self.assertEqual(3, len(captured))
        for sql, plan in captured:
            self.assertTrue(any("USING COVERING INDEX resource_search_identity" in step for step in plan), plan)
            self.assertTrue(any("USING INDEX resource_assignment_schedule" in step for step in plan), plan)
        self.assertEqual(2, sum("SELECT COUNT(*)" in sql for sql, _ in captured))

    def test_full_study_assignment_loads_keep_complete_bodies(self):
        item = self.store.subject(2)
        item["data"]["meaning_mnemonic"] = "An authored mnemonic retained by full study loading."
        self.store.put(item)
        pairs = self.engine.assignments("reviews")
        assignment, subject = next(pair for pair in pairs if pair[1]["id"] == 2)
        self.assertEqual(item, subject)
        self.assertEqual(self.store.related("assignment", 2), assignment)

    def test_schedule_index_migrates_existing_resources_without_changing_state(self):
        self.populate_mixed(91)
        # Restart recovery deliberately changes in-flight writes. This fixture
        # isolates schema migration; those interruption semantics have own tests.
        self.store.execute("UPDATE outbox SET state='pending' WHERE state='inflight'")
        expected = self.engine.snapshot()
        self.store.execute("DROP INDEX resource_assignment_schedule")
        self.store.close()
        self.store = Store(self.path)
        self.engine.store = self.store
        self.assertEqual(expected, self.engine.snapshot())
        self.assertIn("resource_assignment_schedule", {row[1] for row in self.store.rows("PRAGMA index_list(resources)")})


if __name__ == "__main__":
    unittest.main()
