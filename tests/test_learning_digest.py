"""Authored digest fixtures; no shell, credentials, network or graded writes."""
from datetime import datetime
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_learning_insights as authored
import test_dictation as dictation_fixtures
from wanikani import insights, learning_digest
from wanikani.common import UserError, stamp
from wanikani.engine import Engine
from wanikani.store import Store


class LearningDigestTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.LearningInsightsTests()
        self.fixture.setUp()
        self.engine, self.store = self.fixture.engine, self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def project(self, **kwargs):
        return learning_digest.project(self.engine, timezone=kwargs.pop("timezone", "UTC"), **kwargs)

    def parity(self, **kwargs):
        report = self.project(**kwargs)
        native = self.fixture.view(**kwargs)
        self.assertEqual(native["windows"], report["windows"])
        self.assertEqual(native["as_of"], report["generated_at"])
        self.assertEqual(native["timezone"], report["timezone"])
        return report

    def test_empty_known_history_has_exact_aggregate_scope_and_two_windows(self):
        value = self.parity()
        self.assertEqual({"schema_version", "scope", "freshness", "generated_at", "data_epoch", "demo",
            "timezone", "complete", "stale", "coverage", "includes_retained_pre_reset_activity", "windows"}, set(value))
        self.assertEqual("recorded_on_this_device", value["scope"])
        self.assertEqual("retained_local_records", value["coverage"])
        self.assertEqual("cached", value["freshness"])
        self.assertTrue(value["complete"]); self.assertFalse(value["stale"])
        self.assertTrue(value["includes_retained_pre_reset_activity"])
        self.assertEqual(self.store.get("session_epoch"), value["data_epoch"])
        self.assertEqual({"7", "30"}, set(value["windows"]))
        for days, window in value["windows"].items():
            self.assertEqual(int(days), window["days"])
            for metric in learning_digest.COUNTERS:
                self.assertEqual(0, sum(window[metric].values()))
            for metric in learning_digest.SCALARS:
                self.assertEqual(0, window[metric])

    def test_cycles_batches_corrections_and_current_submissions_are_not_conflated(self):
        self.fixture.event(); self.fixture.event()
        self.fixture.event(mode="lessons"); self.fixture.event(mode="practice")
        self.fixture.session(count=2, finished=5, sid="finished-early")
        self.fixture.session(complete=False, sid="paused")
        self.fixture.session(invalidated="account reset", sid="reset")
        self.store.event("finished-early", 1, "correction", stamp(self.fixture.now),
            {"part": "reading", "answer": "PRIVATE ANSWER"})
        self.fixture.outbox("pending"); self.fixture.outbox("confirmed")
        value = self.parity()["windows"]["7"]
        self.assertEqual({"reviews": 2, "lessons": 1, "practice": 1}, value["subject_completions"])
        self.assertEqual({"reviews": 1, "lessons": 0, "practice": 0}, value["sessions_completed"])
        self.assertEqual(1, value["typo_corrections"])
        self.assertNotIn("confirmed", json.dumps(value))

    def test_window_boundaries_future_events_and_exact_generated_at(self):
        for ago in (0, 6, 7, 29, 30):
            self.fixture.event(when=self.fixture.now - ago * 86400)
        self.fixture.event(when=self.fixture.now + 1)
        as_of = self.fixture.now + .125
        value = self.parity(now=as_of)
        self.assertEqual(stamp(as_of), value["generated_at"])
        self.assertEqual(2, value["windows"]["7"]["subject_completions"]["reviews"])
        self.assertEqual(4, value["windows"]["30"]["subject_completions"]["reviews"])

    def test_local_midnight_and_both_dst_transitions_match_native_activity(self):
        cases = (("2026-03-09T07:30:00+00:00", "2026-03-03T08:00:00+00:00"),
                 ("2026-11-02T08:30:00+00:00", "2026-10-27T07:00:00+00:00"))
        for now, first in cases:
            with self.subTest(now=now):
                self.store.execute("DELETE FROM events")
                self.fixture.now = datetime.fromisoformat(now).timestamp()
                beginning = datetime.fromisoformat(first).timestamp()
                self.fixture.event(when=beginning - 1)
                self.fixture.event(when=beginning)
                self.fixture.event(when=self.fixture.now)
                value = self.parity(timezone="America/Los_Angeles")
                self.assertEqual(2, value["windows"]["7"]["subject_completions"]["reviews"])
                self.assertEqual(3, value["windows"]["30"]["subject_completions"]["reviews"])
        self.fixture.now = datetime.fromisoformat("2026-09-05T06:59:59+00:00").timestamp()
        value = self.parity(timezone="America/Los_Angeles")
        self.assertEqual("2026-09-04", value["windows"]["7"]["end_day"])

    def test_system_timezone_is_used_when_no_test_override_is_supplied(self):
        value = learning_digest.project(self.engine)
        native = insights.overview(self.engine)
        self.assertEqual(native["timezone"], value["timezone"])
        self.assertEqual(native["windows"], value["windows"])

    def test_listening_ratings_undo_and_skips_match_native_without_history_leaks(self):
        self.fixture.setup_listening()
        self.fixture.listen("start", subject_ids=[1])
        self.fixture.listen("reveal")
        self.fixture.listen("rate", rating="remembered")
        value = self.parity()["windows"]["7"]
        self.assertEqual(1, value["listening_ratings"]["remembered"])
        self.assertEqual(1, value["listening_sessions_completed"])
        self.fixture.listen("undo")
        self.assertEqual(0, self.parity()["windows"]["7"]["listening_sessions_completed"])
        self.fixture.listen("skip")
        value = self.parity()["windows"]["7"]
        self.assertEqual({"remembered": 0, "again": 0, "skipped": 1}, value["listening_ratings"])

    def test_dictation_check_continue_undo_and_reset_have_separate_counts(self):
        fixture = dictation_fixtures.DictationTests(); fixture.setUp()
        try:
            fixture.start(); fixture.play(); fixture.check()
            def report():
                value = learning_digest.project(fixture.engine, timezone="UTC")
                self.assertEqual(insights.overview(fixture.engine, timezone="UTC")["windows"], value["windows"])
                return value
            self.assertEqual(0, report()["windows"]["7"]["dictation_ratings"]["matched"])
            fixture.act("continue")
            self.assertEqual(1, report()["windows"]["7"]["dictation_ratings"]["matched"])
            fixture.act("undo")
            self.assertEqual(0, report()["windows"]["7"]["dictation_sessions_completed"])
            fixture.act("continue")
            fixture.store.set("milestone_reset_generation", 1)
            value = report()
            self.assertEqual(1, value["windows"]["7"]["dictation_sessions_completed"])
            self.assertEqual(0, sum(value["windows"]["7"]["listening_ratings"].values()))
            for forbidden in ("やま", "山1", "Authored meaning", "PRIVATE", "playback_token", "media_handle"):
                self.assertNotIn(forbidden, json.dumps(value, ensure_ascii=False))
        finally:
            fixture.tearDown()

    def test_account_identity_is_strict_and_unavailable_does_not_mean_zero(self):
        self.fixture.event()
        for identity in (None, True, 1, "different-account", {"private": "account"}):
            self.store.set("account_id", identity)
            with self.subTest(identity=identity), patch.object(insights, "_completion_data", side_effect=AssertionError("No foreign history")):
                with self.assertRaises(UserError) as caught: self.project()
                self.assertEqual("learning_digest_unavailable", caught.exception.code)
        self.store.set("account_id", "authored-account")
        self.assertEqual(1, self.project()["windows"]["7"]["subject_completions"]["reviews"])
        user = self.store.get("user"); user["data"]["subscription"]["max_level_granted"] = True
        self.store.set("user", user)
        with self.assertRaises(UserError): self.project()

    def test_demo_requires_its_explicit_identity_and_is_labeled(self):
        self.engine.demo = True
        with self.assertRaises(UserError): self.project()
        user = self.store.get("user"); user["data"]["id"] = "demo"; self.store.set("user", user)
        with self.assertRaises(UserError): self.project()
        self.store.set("account_id", None)
        value = self.project()
        self.assertTrue(value["demo"])
        self.assertEqual("recorded_on_this_device", value["scope"])
        self.assertNotIn("authored-account", json.dumps(value))

    def test_legacy_integer_identity_cannot_match_a_boolean_account_stamp(self):
        user = self.store.get("user"); user["data"].pop("id"); user["id"] = 1
        self.store.set("user", user); self.store.set("account_id", True)
        with self.assertRaises(UserError): self.project()
        self.store.set("account_id", 1)
        self.assertEqual("recorded_on_this_device", self.project()["scope"])

    def test_epoch_is_a_canonical_uuid_and_arbitrary_meta_text_is_never_exported(self):
        epoch = self.store.get("session_epoch")
        for bad in (None, True, "PRIVATE ACCOUNT TOKEN", "{" + epoch + "}", epoch.upper(), {}, "0" * 36):
            self.store.set("session_epoch", bad)
            with self.subTest(epoch=bad), self.assertRaises(UserError) as caught:
                self.project()
            self.assertNotIn("PRIVATE", str(caught.exception))
        self.store.set("session_epoch", epoch)
        self.assertEqual(epoch, self.project()["data_epoch"])

    def test_untrusted_clock_invalid_time_and_bad_timezone_are_unavailable(self):
        self.engine.clock_untrusted = True
        with self.assertRaises(UserError): self.project()
        self.engine.clock_untrusted = False
        for offset in (301, float("nan"), float("inf"), True):
            self.engine.clock_offset = offset
            with self.subTest(offset=offset), self.assertRaises(UserError): self.project()
        self.engine.clock_offset = 0
        for now in (True, float("nan"), float("inf"), -1, "PRIVATE CLOCK"):
            with self.subTest(now=now), self.assertRaises(UserError): self.project(now=now)
        for zone in ("PRIVATE TIMEZONE", "../UTC", {}, True):
            with self.subTest(zone=zone), self.assertRaises(UserError): self.project(timezone=zone)

    def test_restart_preserves_epoch_and_retained_reset_activity_but_deletion_does_not(self):
        self.fixture.event(); before = self.project()
        self.store.set("milestone_reset_generation", 1)
        self.assertEqual(before, self.project())
        self.store.close()
        self.store = Store(self.fixture.path); self.fixture.store = self.store
        self.engine = Engine(self.store, clock=lambda: self.fixture.now); self.fixture.engine = self.engine
        self.assertEqual(before, self.project())
        self.store.execute("DELETE FROM events")
        self.store.set("session_epoch", str(uuid4()))
        after = self.project()
        self.assertNotEqual(before["data_epoch"], after["data_epoch"])
        self.assertEqual(0, after["windows"]["7"]["subject_completions"]["reviews"])

    def test_private_extra_metrics_are_ignored_and_bad_known_counts_fail_closed(self):
        original = insights._completion_data
        def extras(engine, bounds, now, daily):
            original(engine, bounds, now, daily)
            for values in daily.values():
                values["PRIVATE"] = "PRIVATE NOTE"
                values["subject_completions"]["private_answer"] = "PRIVATE ANSWER"
        with patch.object(insights, "_completion_data", side_effect=extras):
            self.assertNotIn("PRIVATE", json.dumps(self.project()))
        for value in (-1, True, 1.5, None, learning_digest.MAX_COUNT + 1):
            def damaged(engine, bounds, now, daily):
                daily[bounds[-1][0]]["subject_completions"]["reviews"] = value
            with self.subTest(value=value), patch.object(insights, "_completion_data", side_effect=damaged):
                with self.assertRaises(UserError): self.project()

    def test_sum_overflow_cannot_leave_safe_individual_counts_with_unsafe_totals(self):
        def oversized(engine, bounds, now, daily):
            for day, _, _ in bounds[-2:]:
                daily[day]["dictation_ratings"]["again"] = learning_digest.MAX_COUNT
        with patch.object(insights, "_completion_data", side_effect=oversized), self.assertRaises(UserError):
            self.project()

    def test_projection_reads_counts_once_with_no_private_content_or_mutations(self):
        self.fixture.subject(1); self.fixture.event(errors={"meaning": 3})
        self.fixture.session(); self.fixture.outbox("uncertain")
        private = json.dumps({"answer": "PRIVATE OLD ANSWER" * 1000})
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)",
                [("old", 1, "answer", stamp(self.fixture.now - 90 * 86400), private) for _ in range(100)])
        queries = []; original = self.store.rows
        def rows(sql, args=()):
            result = original(sql, args); queries.append((sql, args, result)); return result
        before = self.store.db.total_changes
        with patch.object(self.store, "rows", side_effect=rows), \
                patch.object(insights, "overview", side_effect=AssertionError("No rich Activity projection")), \
                patch.object(insights, "_difficulties", side_effect=AssertionError("No subjects")), \
                patch.object(insights, "_current", side_effect=AssertionError("Use existing current status")), \
                patch.object(self.engine, "snapshot", side_effect=AssertionError("No full catalogue")), \
                patch.object(self.engine, "details", side_effect=AssertionError("No details")), \
                patch.object(insights, "_completion_data", wraps=insights._completion_data) as completed, \
                patch.object(insights, "_session_data", wraps=insights._session_data) as sessions, \
                patch.object(insights, "_listening_data", wraps=insights._listening_data) as audio:
            report = self.project()
        self.assertEqual(1, completed.call_count); self.assertEqual(1, sessions.call_count)
        self.assertEqual(2, audio.call_count)
        self.assertEqual(before, self.store.db.total_changes)
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("authored-account", json.dumps(report))
        plans = []
        for sql, args, result in queries:
            self.assertNotIn("FROM resources", sql)
            if "FROM events" in sql or "FROM sessions" in sql:
                for row in result:
                    self.assertNotIn("body", row.keys())
                plans.extend(row[3] for row in original("EXPLAIN QUERY PLAN " + sql, args))
        for index in ("events_completion_time", "events_study_window", "events_listening_window", "events_dictation_window", "sessions_completed_at"):
            self.assertIn(index, "\n".join(plans))

    def test_sql_error_text_is_not_exposed_as_a_status_message(self):
        with patch.object(insights, "_completion_data", side_effect=sqlite3.OperationalError("PRIVATE DATABASE SQL")):
            with self.assertRaises(UserError) as caught: self.project()
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual("learning_digest_unavailable", caught.exception.code)

    def test_account_cannot_change_between_authorization_and_aggregate_reads(self):
        self.fixture.event()
        entered, attempted, changed = [threading.Event() for _ in range(3)]
        original = insights._completion_data; values = []; errors = []
        def aggregate(*args):
            entered.set(); self.assertTrue(attempted.wait(2))
            self.assertFalse(changed.wait(.05))
            return original(*args)
        def read():
            try: values.append(self.project())
            except BaseException as error: errors.append(error)
        def write():
            entered.wait(2); attempted.set()
            self.store.set("account_id", "another-account"); changed.set()
        with patch.object(insights, "_completion_data", side_effect=aggregate):
            reader = threading.Thread(target=read); writer = threading.Thread(target=write)
            reader.start(); writer.start(); reader.join(3); writer.join(3)
        self.assertFalse(reader.is_alive()); self.assertFalse(writer.is_alive()); self.assertEqual([], errors)
        self.assertTrue(changed.is_set())
        self.assertEqual(1, values[0]["windows"]["7"]["subject_completions"]["reviews"])
        with self.assertRaises(UserError): self.project()


if __name__ == "__main__":
    unittest.main()
