"""Local transcription history remains distinct, Undo-aware and answer-free."""
import json
import unittest

import test_dictation as authored
from test_backend import NOW
from wanikani import insights
from wanikani.common import stamp
from wanikani.store import Store


class DictationInsightsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.DictationTests()
        self.fixture.setUp()
        self.engine, self.store = self.fixture.engine, self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def view(self, **kwargs):
        return insights.overview(self.engine, timezone="UTC", **kwargs)

    def test_check_alone_is_not_a_result_and_continue_counts_only_dictation(self):
        self.fixture.start()
        self.fixture.play()
        self.fixture.check()
        value = self.view()["windows"]["7"]
        self.assertEqual({"matched": 0, "again": 0, "skipped": 0}, value["dictation_ratings"])
        self.fixture.act("continue")
        result = self.view()
        value = result["windows"]["7"]
        self.assertEqual({"matched": 1, "again": 0, "skipped": 0}, value["dictation_ratings"])
        self.assertEqual(1, value["dictation_sessions_completed"])
        self.assertEqual({"remembered": 0, "again": 0, "skipped": 0}, value["listening_ratings"])
        self.assertEqual(0, sum(value["subject_completions"].values()))
        for secret in ("やま", "山1", "Authored meaning", "PRIVATE", "playback_token", "media_handle"):
            self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))

    def test_undo_excludes_prior_result_and_batch_without_losing_later_continue(self):
        self.fixture.record()
        self.fixture.act("undo")
        value = self.view()["windows"]["30"]
        self.assertEqual(0, value["dictation_ratings"]["matched"])
        self.assertEqual(0, value["dictation_sessions_completed"])
        self.fixture.act("continue")
        value = self.view()["windows"]["30"]
        self.assertEqual(1, value["dictation_ratings"]["matched"])
        self.assertEqual(1, value["dictation_sessions_completed"])

    def test_skips_are_explicit_without_becoming_correctness_or_account_progress(self):
        self.fixture.start()
        self.fixture.act("skip")
        value = self.view()["windows"]["7"]
        self.assertEqual({"matched": 0, "again": 0, "skipped": 1}, value["dictation_ratings"])
        self.assertEqual(1, value["dictation_sessions_completed"])
        self.assertIsNone(self.fixture.card())
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_again_and_reset_retention_keep_scope_and_do_not_touch_durable_study(self):
        self.fixture.record("やも")
        self.store.set("milestone_reset_generation", 1)
        before = list(self.store.db.iterdump())
        value = self.view()
        self.assertEqual("recorded_on_this_device", value["scope"])
        self.assertEqual(1, value["windows"]["7"]["dictation_ratings"]["again"])
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.store.set("session_epoch", "replacement-data")
        self.assertEqual(0, self.view()["windows"]["7"]["dictation_ratings"]["again"])

    def test_current_and_future_dates_use_the_result_day_without_invented_history(self):
        self.fixture.record()
        result = self.view(now=NOW + 86400)
        day = stamp(NOW)[:10]
        rows = {row["day"]: row for row in result["daily"]}
        self.assertEqual(1, rows[day]["dictation_ratings"]["matched"])
        self.assertEqual(0, result["daily"][-1]["dictation_ratings"]["matched"])
        self.assertEqual(0, self.view(now=NOW - 1)["windows"]["7"]["dictation_ratings"]["matched"])

    def test_dictation_time_index_bounds_queries_and_recreates_without_state_changes(self):
        old = stamp(NOW - 90 * 86400)
        body = json.dumps({"rating": "again", "operation": "old", "private": "PRIVATE" * 1000})
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)",
                [("old", 1, "dictation_result", old, body) for _ in range(800)])
        self.fixture.record()
        plans = []
        original = self.store.rows
        def observed(sql, args=()):
            if "dictation_result" in sql:
                plans.extend(row[3] for row in original("EXPLAIN QUERY PLAN " + sql, args))
            return original(sql, args)
        self.store.rows = observed
        try:
            before = self.view()
        finally:
            self.store.rows = original
        self.assertTrue(any("SEARCH events USING INDEX events_dictation_window" in row for row in plans), plans)
        self.store.execute("DROP INDEX events_dictation_window")
        observer = Store(self.store.path)
        observer.close()
        self.assertEqual(before, self.view())
        self.assertTrue(self.store.rows("SELECT 1 FROM sqlite_master WHERE name='events_dictation_window'"))


if __name__ == "__main__":
    unittest.main()
