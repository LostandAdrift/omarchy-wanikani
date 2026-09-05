"""Local-history equivalence, indexed range selection, and clock regressions."""
import contextlib
import os
import random
import time
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW, stamp
from wanikani.history import activity
from wanikani.practice import _recent_mistakes
from wanikani.store import Store


ORIGINAL_ACTIVITY = """SELECT date(created_at,'localtime') AS day,COUNT(*) AS count
  FROM events WHERE kind IN ('subject_complete','practice_complete')
  GROUP BY day ORDER BY day DESC LIMIT 35"""


@contextlib.contextmanager
def timezone(name):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


class HistoryTests(EngineFixture, unittest.TestCase):
    def complete(self, when, kind="subject_complete"):
        self.store.event("authored-history", 2, kind, when, {})

    def original_activity(self):
        return [dict(row) for row in self.store.rows(ORIGINAL_ACTIVITY)]

    def assert_equivalent(self):
        self.assertEqual(self.original_activity(), activity(self.store))

    def test_empty_and_invalid_dates_preserve_null_group(self):
        self.assertEqual([], activity(self.store))
        for value in ("", "invalid", "2026-99-99T00:00:00Z"):
            self.complete(value)
        self.assertEqual([{"day": None, "count": 3}], activity(self.store))
        self.complete(stamp(NOW))
        self.assert_equivalent()

    def test_latest_nonempty_days_survive_sparse_history_and_long_hiatus(self):
        with self.store.transaction():
            for index in range(80):
                self.complete(stamp(NOW - (365 + index * 11) * 86400))
        result = activity(self.store)
        self.assertEqual(35, len(result))
        self.assert_equivalent()
        self.assertEqual(35, sum(row["count"] for row in result))

    def test_full_boundary_day_counts_and_completion_kinds(self):
        with timezone("America/Los_Angeles"), self.store.transaction():
            for index in range(90):
                for second in (0, 1, 28799, 28800, 43200, 86399):
                    for kind in ("subject_complete", "practice_complete", "answer", "correction", "other"):
                        self.complete(stamp(1744156800 - index * 86400 + second), kind)
            self.assert_equivalent()

    def test_invalid_group_only_fills_a_spare_calendar_slot(self):
        for index in range(34):
            self.complete(stamp(NOW - index * 86400))
        self.complete("invalid")
        self.assertEqual({"day": None, "count": 1}, activity(self.store)[-1])
        self.complete(stamp(NOW - 34 * 86400))
        self.assertEqual(35, len(activity(self.store)))
        self.assertNotIn(None, [row["day"] for row in activity(self.store)])
        self.assert_equivalent()

    def test_extreme_dates_fall_back_without_losing_valid_or_null_groups(self):
        for zone in ("UTC", "America/Los_Angeles", "Pacific/Apia"):
            with self.subTest(zone=zone), timezone(zone):
                self.store.execute("DELETE FROM events")
                for value in ("0000-01-01T00:00:00Z", "0001-01-01T00:00:00Z",
                        "-0001-12-31T23:59:59Z", "9999-12-31T23:59:59Z", "invalid", stamp(NOW)):
                    self.complete(value)
                self.assert_equivalent()

    def test_date_arithmetic_null_uses_the_original_query(self):
        self.complete("0001-01-01T00:00:00Z")
        self.complete(stamp(NOW))
        original = self.store.rows

        def null_bound(sql, args=()):
            if sql.startswith("SELECT value,date(value,'localtime')"):
                return [(None, None)]
            return original(sql, args)

        with patch.object(self.store, "rows", side_effect=null_bound):
            self.assert_equivalent()

    def test_randomized_equivalence_across_timezones_and_clock_order(self):
        for zone in ("UTC", "America/Los_Angeles", "Asia/Tokyo", "Pacific/Apia"):
            with timezone(zone):
                for seed in range(8):
                    with self.subTest(zone=zone, seed=seed):
                        rng = random.Random(seed)
                        self.store.execute("DELETE FROM events")
                        with self.store.transaction():
                            for index in range(800):
                                when = stamp(1735689600 + rng.randrange(-15_000_000, 15_000_000))
                                if index % 97 == 0:
                                    when = "invalid"
                                kind = rng.choice(("subject_complete", "practice_complete", "answer", "correction"))
                                self.complete(when, kind)
                        self.assert_equivalent()

    def test_current_timezone_is_used_after_a_timezone_change(self):
        self.complete("2026-09-01T01:00:00Z")
        with timezone("UTC"):
            self.assertEqual("2026-09-01", activity(self.store)[0]["day"])
        with timezone("America/Los_Angeles"):
            self.assertEqual("2026-08-31", activity(self.store)[0]["day"])
        self.assert_equivalent()

    def test_midnight_offset_changes_keep_whole_local_days(self):
        for zone, instant in (("Pacific/Apia", 1326844800), ("America/Havana", 1744156800)):
            with self.subTest(zone=zone), timezone(zone), self.store.transaction():
                self.store.execute("DELETE FROM events")
                for hour in range(100 * 24):
                    # Deliberately omit days so a boundary can be the 35th
                    # nonempty day rather than an always-discarded extra day.
                    if (hour // 24) % 3 != 0:
                        self.complete(stamp(instant - hour * 3600))
                self.assert_equivalent()

    def test_clock_rollback_correction_pairs_by_insertion_order(self):
        for age, kind in ((3600, "answer"), (10800, "answer"), (14400, "correction")):
            self.store.event("clock-rollback", 2, kind, stamp(NOW - age),
                {"part": "meaning", "kind": "incorrect"})
        result = _recent_mistakes(self.engine)
        self.assertEqual(1, result[2]["total"])
        self.assertEqual(stamp(NOW - 3600), result[2]["last_at"])

    def test_recent_mistake_index_matches_original_timestamp_filter(self):
        rng = random.Random(59081)
        with self.store.transaction():
            for index in range(3000):
                self.store.event("session-" + str(rng.randrange(3)), rng.randrange(1, 6),
                    rng.choice(("answer", "answer", "answer", "correction", "subject_complete")),
                    "invalid" if index % 101 == 0 else stamp(NOW - rng.randrange(30 * 86400)),
                    {"part": rng.choice(("meaning", "reading", "other")),
                     "kind": rng.choice(("incorrect", "correct", "retry"))})
        # The original timestamp comparison includes the exact cutoff.
        self.store.event("boundary", 20, "answer", stamp(NOW - 14 * 86400),
            {"part": "meaning", "kind": "incorrect"})
        indexed = _recent_mistakes(self.engine)
        original = self.store.rows

        def unindexed(sql, args=()):
            return original(sql.replace("INDEXED BY events_study_window", "NOT INDEXED"), args)

        with patch.object(self.store, "rows", side_effect=unindexed):
            self.assertEqual(_recent_mistakes(self.engine), indexed)
        self.assertEqual(1, indexed[20]["total"])

    def test_existing_history_gets_indexes_on_restart(self):
        self.store.execute("DROP INDEX events_study_window")
        self.store.execute("DROP INDEX events_completion_time")
        self.complete(stamp(NOW))
        expected = self.original_activity()
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(expected, activity(self.store))
        names = {row[1] for row in self.store.rows("PRAGMA index_list(events)")}
        self.assertTrue({"events_study_window", "events_completion_time"} <= names)

    def test_dense_history_queries_narrow_both_ranges_with_indexes(self):
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)",
                (("large-authored-history", 2, "subject_complete", stamp(NOW - index * 3600), "{}")
                 for index in range(50000)))
        trace = []
        original = self.store.rows

        def capture(sql, args=()):
            if "FROM events" in sql:
                trace.append((sql, args, [row[3] for row in original("EXPLAIN QUERY PLAN " + sql, args)]))
            return original(sql, args)

        with patch.object(self.store, "rows", side_effect=capture):
            self.assertEqual(35, len(activity(self.store)))
            _recent_mistakes(self.engine)
        grouped = [entry for entry in trace if "GROUP BY" in entry[0]]
        self.assertEqual(1, len(grouped))
        self.assertIn("julianday(created_at)>=?", grouped[0][0])
        self.assertTrue(any("SEARCH events USING INDEX events_completion_time" in plan for plan in grouped[0][2]))
        mistakes = next(entry for entry in trace if "events_study_window" in entry[0])
        self.assertTrue(any("SEARCH events USING INDEX events_study_window" in plan for plan in mistakes[2]))
        self.assertIn("ORDER BY id", mistakes[0])


if __name__ == "__main__":
    unittest.main()
