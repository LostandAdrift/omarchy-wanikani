"""Read-only level history uses authored metadata, never an account or network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_backend import Engine, Store, NOW, stamp
from wanikani import level_history
from wanikani.common import UserError


DAY = 86400


class LevelHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "history.db")
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.user = {"object": "user", "data": {"id": "authored-history-account", "level": 3,
            "username": "PRIVATE ACCOUNT", "subscription": {"type": "lifetime", "max_level_granted": 60,
                "period_ends_at": None}, "current_vacation_started_at": None}}
        self.store.set("user", self.user)
        self.store.set("account_id", "authored-history-account")
        self.store.set("cursor_level_progressions", stamp(NOW - 10))
        guard = patch("socket.create_connection", side_effect=AssertionError("History is cached metadata only"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def record(self, identity=1, level=3, **dates):
        data = {"level": level, "created_at": stamp(NOW - 10 * DAY), "unlocked_at": stamp(NOW - 10 * DAY),
            "started_at": stamp(NOW - 9 * DAY), "passed_at": None, "completed_at": None, "abandoned_at": None}
        data.update(dates)
        value = {"id": identity, "object": "level_progression", "data": data}
        self.store.put(value)
        return value

    def item(self, **args):
        value = level_history.catalogue(self.engine, **args)
        self.assertEqual(1, len(value["items"]))
        return value["items"][0]

    def test_empty_synced_cache_never_claims_lifetime_completeness(self):
        value = level_history.catalogue(self.engine)
        self.assertEqual(("empty", 0, [], False, None),
            (value["status"], value["total"], value["items"], value["has_more"], value["next_offset"]))
        self.assertTrue(value["cache_complete"])
        self.assertFalse(value["history_complete"])
        self.assertIn("may not supply your full history", value["message"])
        self.assertNotIn("PRIVATE", json.dumps(value))

    def test_passed_and_all_burned_are_distinct_and_both_duration_end_at_passing(self):
        self.record(passed_at=stamp(NOW - 3 * DAY))
        item = self.item()
        self.assertEqual(("passed", "Level passed", "passed", 7 * DAY, 7),
            tuple(item[key] for key in ("state", "label", "elapsed_to", "elapsed_seconds", "elapsed_days")))
        self.assertIsNone(item["completed_at"])
        self.record(passed_at=stamp(NOW - 3 * DAY), completed_at=stamp(NOW - DAY))
        item = self.item()
        self.assertEqual(("all_burned", "All assignments burned", "passed", 7 * DAY),
            tuple(item[key] for key in ("state", "label", "elapsed_to", "elapsed_seconds")))
        self.assertNotEqual(item["passed_at"], item["completed_at"])

    def test_abandoned_visits_preserve_prior_passing_without_inflating_its_duration(self):
        self.record(abandoned_at=stamp(NOW - DAY))
        item = self.item()
        self.assertEqual(("abandoned", "abandoned", 9 * DAY), (item["state"], item["elapsed_to"], item["elapsed_seconds"]))
        self.record(passed_at=stamp(NOW - 3 * DAY), abandoned_at=stamp(NOW - DAY))
        item = self.item()
        self.assertEqual("Passed, later abandoned", item["label"])
        self.assertEqual(("passed", 7 * DAY), (item["elapsed_to"], item["elapsed_seconds"]))
        self.assertIsNotNone(item["abandoned_at"])

    def test_visits_stay_separate_sorted_by_dates_without_assuming_ids_are_dates(self):
        self.record(90, abandoned_at=stamp(NOW - 2 * DAY))
        self.record(10, created_at=stamp(NOW - DAY), unlocked_at=stamp(NOW - DAY), started_at=stamp(NOW - 100))
        items = level_history.catalogue(self.engine)["items"]
        self.assertEqual([10, 90], [item["id"] for item in items])
        self.assertEqual(["Recorded visit 2", "Recorded visit 1"], [item["attempt_label"] for item in items])
        self.assertEqual(["now", "abandoned"], [item["elapsed_to"] for item in items])
        self.assertEqual(DAY, items[0]["elapsed_seconds"])

    def test_history_above_reset_level_or_expired_content_grant_is_retained(self):
        self.record(1, 60, passed_at=stamp(NOW - 3 * DAY), abandoned_at=stamp(NOW - DAY))
        self.user["data"]["level"] = 1
        self.user["data"]["subscription"].update(type="recurring", max_level_granted=60, period_ends_at=stamp(NOW - DAY))
        self.store.set("user", self.user)
        self.assertEqual(3, self.engine.max_level())
        item = self.item()
        self.assertEqual((60, "abandoned", "passed"), (item["level"], item["state"], item["elapsed_to"]))
        self.assertNotIn("61", json.dumps(item))

    def test_only_latest_current_level_unfinished_visit_gets_an_open_duration(self):
        self.record(1, 2)
        self.record(2, 3, created_at=stamp(NOW - 20 * DAY), unlocked_at=stamp(NOW - 20 * DAY), started_at=stamp(NOW - 19 * DAY))
        self.record(3, 3)
        records = {item["id"]: item for item in level_history.catalogue(self.engine)["items"]}
        self.assertEqual(("in_progress", "now", 10 * DAY),
            (records[3]["state"], records[3]["elapsed_to"], records[3]["elapsed_seconds"]))
        for identity in (1, 2):
            self.assertEqual("unknown", records[identity]["state"])
            self.assertIsNone(records[identity]["elapsed_seconds"])
        self.assertTrue(level_history.catalogue(self.engine)["partial"])

    def test_later_passed_abandoned_or_invalid_visit_cannot_revive_an_older_open_visit(self):
        for changes in ({"passed_at": stamp(NOW - DAY)}, {"abandoned_at": stamp(NOW - DAY)},
                {"started_at": stamp(NOW + DAY)}):
            with self.subTest(changes=changes):
                self.record(1, created_at=stamp(NOW - 20 * DAY), unlocked_at=stamp(NOW - 20 * DAY), started_at=stamp(NOW - 19 * DAY))
                self.record(2, **changes)
                items = level_history.catalogue(self.engine)["items"]
                old = next(item for item in items if item["id"] == 1)
                self.assertEqual("unknown", old["state"])
                self.assertIsNone(old["elapsed_seconds"])
                self.assertFalse(any(item["elapsed_to"] == "now" for item in items))

    def test_not_unlocked_and_waiting_for_first_lesson_have_explicit_states(self):
        self.record(unlocked_at=None, started_at=None)
        self.assertEqual(("not_unlocked", None), (self.item()["state"], self.item()["elapsed_to"]))
        self.record(started_at=None)
        self.assertEqual(("unlocked", "Lessons available", "now"),
            tuple(self.item()[key] for key in ("state", "label", "elapsed_to")))

    def test_all_known_dates_must_be_past_and_strict_timezone_timestamps(self):
        invalid = [True, 1, [], {}, "PRIVATE invalid date", "2026-02-30T12:00:00Z", "2026-01-01",
            "2026-01-01T12:00:00", "2026-01-01T12:00:00+25:00", "2026-01-01T12:00:00+01:99",
            "2026-01-01T12:00:00-00:60", "2026-01-01T12:00:00Z\n",
            "２０２６-01-01T12:00:00Z", stamp(NOW + 1), "x" * 10000]
        for field in level_history.DATES:
            for value in invalid:
                with self.subTest(field=field, value=str(value)[:30]):
                    self.record(**{field: value})
                    item = self.item()
                    self.assertEqual(("unknown", "partial", None), (item["state"], item["date_status"], item["elapsed_seconds"]))
                    self.assertIsNone(item[field])
                    self.assertNotIn("PRIVATE", json.dumps(item))

    def test_out_of_order_or_missing_prerequisite_dates_have_no_confident_duration(self):
        changes = [{"started_at": stamp(NOW - 11 * DAY)}, {"passed_at": stamp(NOW - 11 * DAY)},
            {"completed_at": stamp(NOW - DAY)}, {"passed_at": stamp(NOW - DAY), "completed_at": stamp(NOW - 2 * DAY)},
            {"started_at": None, "passed_at": stamp(NOW - DAY)}, {"unlocked_at": None},
            {"abandoned_at": stamp(NOW - 11 * DAY)}, {"passed_at": stamp(NOW - DAY), "abandoned_at": stamp(NOW - 2 * DAY)}]
        for dates in changes:
            with self.subTest(dates=dates):
                self.record(**dates)
                self.assertEqual("partial", self.item()["date_status"])
                self.assertIsNone(self.item()["elapsed_seconds"])

    def test_missing_required_or_nullable_fields_are_partial_not_invented(self):
        for field in level_history.DATES:
            value = self.record()
            del value["data"][field]
            self.store.put(value)
            with self.subTest(field=field):
                self.assertEqual("partial", self.item()["date_status"])
                self.assertIsNone(self.item()["elapsed_seconds"])

    def test_valid_timezone_offsets_normalize_and_vacation_does_not_subtract_time(self):
        self.record(created_at="2026-01-01T00:00:00Z", unlocked_at="2026-01-01T09:00:00+09:00",
            started_at="2026-01-01T00:00:00.123456789Z", passed_at="2026-01-08T00:00:00Z")
        self.user["data"]["current_vacation_started_at"] = "2026-01-02T00:00:00Z"
        self.store.set("user", self.user)
        item = self.item()
        self.assertEqual("2026-01-01T00:00:00Z", item["unlocked_at"])
        self.assertEqual(7 * DAY, item["elapsed_seconds"])
        self.assertIn("vacations and pauses", level_history.catalogue(self.engine)["message"])

    def test_malformed_identity_level_and_object_are_omitted_without_private_content(self):
        base = self.record()
        malformed = []
        for level in (True, 0, 61, "3", None):
            value = copy.deepcopy(base)
            value["data"]["level"] = level
            malformed.append(value)
        for identity in (True, -1, 0, "1", 2, level_history.MAX_ID + 1):
            value = copy.deepcopy(base)
            value["id"] = identity
            malformed.append(value)
        malformed.append({**base, "object": "subject", "notes": "PRIVATE"})
        for value in malformed:
            self.store.execute("UPDATE resources SET body=? WHERE kind='level_progression' AND id='1'", (json.dumps(value),))
            with self.subTest(value=value):
                result = level_history.catalogue(self.engine)
                self.assertEqual(([], 1, True), (result["items"], result["omitted_invalid"], result["partial"]))
                self.assertNotIn("PRIVATE", json.dumps(result))
        self.store.execute("DELETE FROM resources WHERE kind='level_progression'")
        self.store.execute("INSERT INTO resources VALUES('level_progression','01',?)", (json.dumps(base),))
        self.assertEqual([], level_history.catalogue(self.engine)["items"])

    def test_account_mismatch_or_invalid_user_never_reads_progression_records(self):
        self.record()
        invalid = [None, {}, {**self.user, "object": "subject"}, {**self.user, "id": "contradiction"},
            {"object": "user", "data": {**self.user["data"], "id": "other-account"}},
            {"object": "user", "data": {**self.user["data"], "level": True}}]
        for user in invalid:
            self.store.set("user", user)
            with patch.object(self.store, "rows", wraps=self.store.rows) as rows:
                value = level_history.catalogue(self.engine)
            self.assertEqual(("unavailable", None, []), (value["status"], value["total"], value["items"]))
            self.assertFalse(any("FROM resources" in call.args[0] for call in rows.call_args_list))
        self.store.set("user", self.user)
        self.store.set("account_id", None)
        self.assertEqual("account_unavailable", level_history.catalogue(self.engine)["reason"])

    def test_legacy_numeric_account_identity_cannot_match_boolean_or_float_metadata(self):
        self.record()
        legacy = copy.deepcopy(self.user)
        del legacy["data"]["id"]
        legacy["id"] = 1
        self.store.set("user", legacy)
        self.store.set("account_id", 1)
        self.assertEqual("available", level_history.catalogue(self.engine)["status"])
        for identity in (True, 1.0, "1"):
            with self.subTest(identity=identity):
                self.store.set("account_id", identity)
                self.assertEqual("account_unavailable", level_history.catalogue(self.engine)["reason"])

    def test_incomplete_or_active_sync_and_clock_uncertainty_never_create_open_durations(self):
        self.record()
        for cursor in (None, "PRIVATE", stamp(NOW + 1)):
            self.store.set("cursor_level_progressions", cursor)
            result = level_history.catalogue(self.engine)
            self.assertFalse(result["cache_complete"])
            self.assertIsNone(result["items"][0]["elapsed_seconds"])
        self.store.set("cursor_level_progressions", stamp(NOW - 1))
        self.engine.syncing = True
        self.assertFalse(level_history.catalogue(self.engine)["cache_complete"])
        self.engine.syncing = False
        self.engine.clock_untrusted = True
        self.assertEqual("partial", self.item()["date_status"])
        self.assertIsNone(self.item()["elapsed_seconds"])
        for now in (float("nan"), float("inf"), -1, 253402300800):
            self.engine.clock = lambda: now
            result = level_history.catalogue(self.engine)
            self.assertEqual("clock_unavailable", result["reason"])
            self.assertIsNone(result["checked_at"])

    def test_cached_offline_history_and_local_state_are_unchanged_by_reading(self):
        value = self.record(passed_at=stamp(NOW - DAY))
        value.update(token="PRIVATE TOKEN", url="https://private.invalid")
        value["data"].update(meaning="PRIVATE ANSWER", note="PRIVATE NOTE", subject_ids=[123])
        self.store.put(value)
        self.engine.status, self.engine.connected = "offline", False
        before = list(self.store.db.iterdump())
        result = level_history.catalogue(self.engine)
        self.assertEqual("passed", result["items"][0]["state"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("subject_ids", json.dumps(result))
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_paging_is_deterministic_and_visit_numbers_do_not_restart_per_page(self):
        for identity in range(1, 42):
            start = NOW - (50 - identity) * DAY
            self.record(identity, created_at=stamp(start), unlocked_at=stamp(start), started_at=stamp(start), passed_at=stamp(start + 1))
        pages = [level_history.catalogue(self.engine, offset=offset, limit=12) for offset in (0, 12, 24, 36)]
        ids = [item["id"] for page in pages for item in page["items"]]
        self.assertEqual(list(range(41, 0, -1)), ids)
        self.assertEqual([12, 24, 36, None], [page["next_offset"] for page in pages])
        self.assertEqual("Recorded visit 29", pages[1]["items"][0]["attempt_label"])
        self.assertTrue(all(page["total"] == 41 for page in pages))
        self.assertEqual([], level_history.catalogue(self.engine, offset=41)["items"])

    def test_invalid_page_arguments_are_rejected(self):
        for args in ({"offset": True}, {"offset": -1}, {"offset": 1001}, {"limit": False},
                {"limit": 0}, {"limit": 51}, {"limit": 1.5}, {"offset": "0"}):
            with self.subTest(args=args), self.assertRaises(UserError):
                level_history.catalogue(self.engine, **args)

    def test_limited_window_does_not_claim_global_date_order_or_current_duration(self):
        for identity in range(1, 5):
            self.record(identity)
        self.record(1, created_at=stamp(NOW - 10), unlocked_at=stamp(NOW - 10), started_at=stamp(NOW - 9))
        with patch.object(level_history, "MAX_RECORDS", 3):
            value = level_history.catalogue(self.engine)
        self.assertEqual([4, 3, 2], [item["id"] for item in value["items"]])
        self.assertEqual((3, 3, True, True), (value["inspected"], value["total"], value["truncated"], value["partial"]))
        self.assertIn("dates are ordered within this window", value["message"])
        self.assertFalse(any(item["elapsed_to"] == "now" for item in value["items"]))

    def test_large_history_query_uses_bounded_indexed_projection_without_body_hydration(self):
        value = self.record(passed_at=stamp(NOW - DAY))
        self.store.execute("DELETE FROM resources WHERE kind='level_progression'")
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO resources VALUES('level_progression',?,?)", (
                (str(identity), json.dumps({**value, "id": identity})) for identity in range(1, 50001)))
        huge = {**value, "id": 50000, "data": {**value["data"], "private_note": "PRIVATE" * 10000}}
        self.store.put(huge)
        plan = self.store.rows("EXPLAIN QUERY PLAN " + level_history.PROJECTION, (1001,))
        details = " ".join(row["detail"] for row in plan)
        self.assertIn("resource_numeric_id", details)
        self.assertNotIn("TEMP B-TREE", details)
        original = self.store.rows
        projected = []
        def rows(sql, args=()):
            result = original(sql, args)
            if "FROM resources" in sql:
                projected.append(result)
            return result
        with patch.object(self.store, "rows", side_effect=rows), patch.object(self.store, "subject", side_effect=AssertionError("No subject content")):
            result = level_history.catalogue(self.engine, limit=12)
        self.assertEqual(1, len(projected))
        self.assertEqual(1001, len(projected[0]))
        self.assertTrue(all("body" not in row.keys() for row in projected[0]))
        self.assertLess(len(json.dumps([dict(row) for row in projected[0]])), 1000000)
        self.assertEqual((12, 1000, True), (len(result["items"]), result["inspected"], result["truncated"]))
        self.assertEqual(50000, result["items"][0]["id"])
        self.assertNotIn("PRIVATE", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
