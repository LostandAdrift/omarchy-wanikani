"""Authored local learning activity: no account traffic or study mutations."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_backend import NOW
import test_listening as listening_fixtures
from wanikani import insights, listening
from wanikani.common import UserError, stamp
from wanikani.engine import Engine
from wanikani.store import Store


class LearningInsightsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "state.db"
        self.store = Store(self.path)
        self.now = NOW
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.store.set("account_id", "authored-account")
        self.store.set("user", {"object": "user", "data": {"id": "authored-account", "username": "Private learner",
            "level": 2, "subscription": {"type": "lifetime", "max_level_granted": 60}}})
        self.media_dir = self.path.parent / "media"
        self.media_dir.mkdir()
        self.words = {}
        self.sequence = 0

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def view(self, **kwargs):
        return insights.overview(self.engine, timezone=kwargs.pop("timezone", "UTC"), **kwargs)

    def event(self, sid=1, mode="reviews", when=None, errors=None, session="fixture"):
        self.store.event(session, sid, "practice_complete" if mode == "practice" else "subject_complete",
            stamp(self.now if when is None else when), {"mode": mode, "errors": errors or {"meaning": 0, "reading": 0}})

    def subject(self, sid, chars=None, level=1, **data):
        value = {"id": sid, "object": "kanji", "data": {"level": level, "characters": chars or "山" + str(sid),
            "meanings": [{"meaning": "PRIVATE MEANING", "accepted_answer": True}],
            "readings": [{"reading": "ひみつ", "accepted_answer": True}], "hidden_at": None, **data}}
        self.store.put(value)
        return value

    def session(self, mode="reviews", complete=True, count=5, finished=None, invalidated=None, sid="session", ended=None):
        value = {"id": sid, "mode": mode, "phase": "complete" if complete else "question", "index": count if complete else 0,
            "completed": count if complete else 0, "started_at": stamp(self.now - 100),
            "ended_at": stamp(self.now if ended is None else ended) if complete else None,
            "draft": "PRIVATE ANSWER", "feedback": {"answer": "PRIVATE ANSWER"},
            "queue": [{"subject_id": i + 1, "done": i < count if complete else False} for i in range(finished or count)]}
        if finished:
            value["finish_at"] = count
        if invalidated:
            value["invalidated"] = invalidated
        self.store.save_session(value)
        return value

    def outbox(self, state, kind="review", when=None):
        self.sequence += 1
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (str(self.sequence), kind, 1, state,
            json.dumps({"meaning_note": "PRIVATE NOTE", "assignment_id": 12345}),
            stamp(self.now if when is None else when), "PRIVATE DETAIL"))

    def listen(self, action, **args):
        self.sequence += 1
        if action not in ("start", "settings"):
            current = listening.view(self.engine)
            args.update(session_id=current["id"], revision=current["revision"])
        return listening.command(self.engine, "fixture-operation-" + str(self.sequence), action, args)["session"]

    def setup_listening(self):
        listening_fixtures.ListeningTests.word(self, 1, "やま")
        listening_fixtures.ListeningTests.word(self, 2, "かわ")

    def test_empty_metrics_have_explicit_local_scope_and_no_inferred_history(self):
        self.store.put({"id": 991, "object": "review_statistic", "data": {"subject_id": 1,
            "meaning_correct": 8000, "reading_correct": 9000}})
        value = self.view()
        self.assertEqual("recorded_on_this_device", value["scope"])
        self.assertEqual(30, len(value["daily"]))
        self.assertEqual({"reviews": 0, "lessons": 0, "practice": 0}, value["windows"]["30"]["subject_completions"])
        self.assertNotIn("accuracy", value)
        self.assertIn("other devices", value["history_note"])

    def test_subject_cycles_are_not_answer_parts_or_distinct_subjects(self):
        self.event(sid=1)
        self.event(sid=1)
        self.event(mode="lessons")
        self.event(mode="practice")
        for part in ("meaning", "reading"):
            self.store.event("fixture", 1, "answer", stamp(self.now), {"part": part, "correct": True, "answer": "PRIVATE ANSWER"})
        value = self.view()["windows"]["7"]
        self.assertEqual({"reviews": 2, "lessons": 1, "practice": 1}, value["subject_completions"])
        self.assertEqual({"reviews": 0, "lessons": 0, "practice": 0}, value["sessions_completed"])

    def test_seven_and_thirty_calendar_day_windows_exclude_future(self):
        for ago in (0, 6, 7, 29, 30):
            self.event(when=self.now - ago * 86400)
        self.event(when=self.now + 1)
        value = self.view()
        self.assertEqual(2, value["windows"]["7"]["subject_completions"]["reviews"])
        self.assertEqual(4, value["windows"]["30"]["subject_completions"]["reviews"])

    def test_spring_day_has_twenty_three_hours_and_includes_both_sides(self):
        zone = ZoneInfo("America/Los_Angeles")
        self.now = datetime(2026, 3, 9, 12, tzinfo=zone).timestamp()
        for hour in (0, 1, 3, 23):
            self.event(when=datetime(2026, 3, 8, hour, 30, tzinfo=zone).timestamp())
        self.event(when=datetime(2026, 3, 9, 0, tzinfo=zone).timestamp())
        days = {row["day"]: row for row in self.view(timezone="America/Los_Angeles")["daily"]}
        self.assertEqual(4, days["2026-03-08"]["subject_completions"]["reviews"])
        self.assertEqual(1, days["2026-03-09"]["subject_completions"]["reviews"])

    def test_fall_repeated_hour_counts_each_real_event_once(self):
        zone = ZoneInfo("America/Los_Angeles")
        self.now = datetime(2026, 11, 2, 12, tzinfo=zone).timestamp()
        for fold in (0, 1):
            self.event(when=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=fold).timestamp())
        days = {row["day"]: row for row in self.view(timezone="America/Los_Angeles")["daily"]}
        self.assertEqual(2, days["2026-11-01"]["subject_completions"]["reviews"])

    def test_system_zone_is_used_without_fixed_offset_assumptions(self):
        value = insights.overview(self.engine)
        self.assertTrue(value["timezone"])
        self.assertEqual(datetime.fromtimestamp(self.now).date().isoformat(), value["windows"]["7"]["end_day"])

    def test_completed_batches_include_finish_at_but_not_reset_or_partial(self):
        self.session(count=5, finished=20)
        self.session(mode="lessons", count=2, sid="lesson")
        self.session(mode="practice", count=1, sid="practice")
        self.session(complete=False, sid="paused")
        self.session(invalidated="Account reset", sid="reset")
        self.session(sid="future", ended=self.now + 10)
        value = self.view()["windows"]["7"]["sessions_completed"]
        self.assertEqual({"reviews": 1, "lessons": 1, "practice": 1}, value)

    def test_reset_retains_acknowledged_activity_without_claiming_a_finished_batch(self):
        self.event(session="reset", errors={"meaning": 1, "reading": 0})
        self.session(sid="reset", invalidated="Account reset")
        self.store.set("milestone_reset_generation", 4)
        value = self.view()
        self.assertEqual(1, value["windows"]["7"]["subject_completions"]["reviews"])
        self.assertEqual(0, value["windows"]["7"]["sessions_completed"]["reviews"])
        self.assertIn("before account resets", value["history_note"])

    def test_corrections_are_labeled_events_not_an_accuracy_claim(self):
        self.store.event("fixture", 1, "correction", stamp(self.now), {"part": "reading"})
        self.store.event("fixture", 1, "correction", stamp(self.now + 10), {"part": "meaning"})
        value = self.view()
        self.assertEqual(1, value["windows"]["7"]["typo_corrections"])
        self.assertEqual("Local uses of I made a typo", value["correction_label"])

    def test_current_states_are_separate_from_activity_and_from_each_other(self):
        for state in insights.STATES:
            self.outbox(state)
        self.outbox("pending", "material")
        self.outbox("confirmed", when=self.now + 60)
        current = self.view()["current_submissions"]
        self.assertEqual((3, 3, 1, 1), tuple(current[key] for key in ("waiting", "attention", "confirmed", "archived")))
        self.assertEqual(1, current["by_kind"]["material"]["pending"])
        self.assertNotIn("confirmed_at", current)
        self.assertEqual(0, self.view()["windows"]["7"]["subject_completions"]["reviews"])

    def test_listening_ratings_and_batches_are_local_and_undo_removes_result(self):
        self.setup_listening()
        self.listen("start", subject_ids=[1])
        self.listen("reveal")
        self.listen("rate", rating="again")
        value = self.view()["windows"]["7"]
        self.assertEqual({"remembered": 0, "again": 1, "skipped": 0}, value["listening_ratings"])
        self.assertEqual(1, value["listening_sessions_completed"])
        self.listen("undo")
        value = self.view()["windows"]["7"]
        self.assertEqual(0, value["listening_ratings"]["again"])
        self.assertEqual(0, value["listening_sessions_completed"])
        self.listen("reveal")
        self.listen("rate", rating="remembered")
        value = self.view()["windows"]["7"]
        self.assertEqual({"remembered": 1, "again": 0, "skipped": 0}, value["listening_ratings"])
        self.assertEqual(1, value["listening_sessions_completed"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_listening_skip_is_not_remembered_and_partial_session_not_complete(self):
        self.setup_listening()
        self.listen("start", subject_ids=[1, 2])
        self.listen("skip")
        value = self.view()["windows"]["7"]
        self.assertEqual(1, value["listening_ratings"]["skipped"])
        self.assertEqual(0, value["listening_sessions_completed"])

    def test_future_listening_completion_does_not_move_into_today(self):
        self.setup_listening()
        before = self.now
        self.listen("start", subject_ids=[1, 2])
        self.listen("skip")
        self.now += 3600
        self.listen("skip")
        self.now = before
        value = self.view()["windows"]["7"]
        self.assertEqual(1, value["listening_ratings"]["skipped"])
        self.assertEqual(0, value["listening_sessions_completed"])

    def test_listening_undo_across_midnight_removes_the_original_day(self):
        self.setup_listening()
        self.now = datetime(2026, 9, 4, 23, 50, tzinfo=ZoneInfo("UTC")).timestamp()
        self.listen("start", subject_ids=[1])
        self.listen("reveal")
        self.listen("rate", rating="again")
        self.now += 1200
        self.listen("undo")
        self.listen("reveal")
        self.listen("rate", rating="remembered")
        days = {row["day"]: row for row in self.view()["daily"]}
        self.assertEqual(0, days["2026-09-04"]["listening_ratings"]["again"])
        self.assertEqual(1, days["2026-09-05"]["listening_ratings"]["remembered"])
        self.assertEqual(1, days["2026-09-05"]["listening_sessions_completed"])

    def test_listening_previous_reset_counts_but_foreign_account_context_does_not(self):
        self.setup_listening()
        session = self.listen("start", subject_ids=[1])
        self.listen("skip")
        self.store.set("milestone_reset_generation", 1)
        self.assertEqual(1, self.view()["windows"]["7"]["listening_sessions_completed"])
        key = "listening_session_" + session["id"]
        record = self.store.get(key)
        record["context"]["account"] = "different-account"
        self.store.set(key, record)
        value = self.view()["windows"]["7"]
        self.assertEqual(0, value["listening_sessions_completed"])
        self.assertEqual(0, value["listening_ratings"]["skipped"])

    def test_clock_correction_undo_before_window_date_still_removes_later_record(self):
        self.now = datetime(2026, 9, 1, 0, 1, tzinfo=ZoneInfo("UTC")).timestamp()
        self.setup_listening()
        self.listen("start", subject_ids=[1])
        self.listen("reveal")
        self.listen("rate", rating="again")
        self.now -= 120
        self.listen("undo")
        self.now = datetime(2026, 9, 30, 12, tzinfo=ZoneInfo("UTC")).timestamp()
        self.assertEqual(0, self.view()["windows"]["30"]["listening_ratings"]["again"])

    def test_difficulty_uses_acknowledged_final_mistakes_without_answer_content(self):
        self.subject(1)
        self.event(errors={"meaning": 0, "reading": 2})
        self.store.event("fixture", 1, "answer", stamp(self.now), {"answer": "PRIVATE ANSWER", "kind": "incorrect", "part": "meaning"})
        value = self.view()
        self.assertEqual([{"id": 1, "type": "kanji", "level": 1, "label": "山1",
            "meaning_mistakes": 0, "reading_mistakes": 2, "can_open": True}], value["difficulties"])
        for secret in ("PRIVATE ANSWER", "PRIVATE MEANING", "ひみつ", "Private learner"):
            self.assertNotIn(secret, json.dumps(value, ensure_ascii=False))

    def test_protected_ids_and_glyph_aliases_are_removed_before_limit(self):
        for sid in range(1, 10):
            self.subject(sid, chars="山" if sid < 3 else "字" + str(sid))
            self.event(sid=sid, errors={"meaning": 11 - sid, "reading": 0})
        self.session(complete=False, count=1)
        value = self.view()
        self.assertEqual([3, 4, 5, 6, 7, 8], [row["id"] for row in value["difficulties"]])
        self.assertNotIn("山", json.dumps(value["difficulties"], ensure_ascii=False))

    def test_restricted_hidden_and_malformed_levels_are_withheld(self):
        for sid, level in ((1, 50), (2, True), (3, "2"), (4, 2)):
            self.subject(sid, level=level, hidden_at=stamp(self.now) if sid == 4 else None)
            self.event(sid=sid, errors={"meaning": 1, "reading": 0})
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 3
        self.store.set("user", user)
        self.assertEqual([], self.view()["difficulties"])

    def test_hidden_protected_subject_still_withholds_accessible_glyph_alias(self):
        self.subject(1, chars="山", hidden_at=stamp(self.now))
        self.subject(2, chars="山")
        self.subject(3, chars="川")
        self.event(sid=2, errors={"meaning": 2, "reading": 0})
        self.event(sid=3, errors={"meaning": 1, "reading": 0})
        self.session(complete=False, count=1)
        self.assertEqual([3], [row["id"] for row in self.view()["difficulties"]])

    def test_embedded_nul_label_is_never_truncated_into_a_different_glyph(self):
        self.subject(1, chars="山\0川")
        self.event(errors={"meaning": 1, "reading": 0})
        self.assertEqual([], self.view()["difficulties"])

    def test_invalid_completed_queue_does_not_count_as_finished(self):
        session = self.session(count=1)
        session["queue"][0]["done"] = False
        self.store.save_session(session)
        self.assertEqual(0, self.view()["windows"]["7"]["sessions_completed"]["reviews"])

    def test_missing_derived_indexes_rebuild_without_changing_history(self):
        self.setup_listening()
        self.listen("start", subject_ids=[1])
        self.listen("skip")
        self.session(count=1)
        self.event()
        before = self.view()
        durable = {table: [tuple(row) for row in self.store.rows("SELECT * FROM " + table)]
            for table in ("sessions", "events", "outbox")}
        self.store.execute("DROP INDEX events_listening_window")
        self.store.execute("DROP INDEX sessions_completed_at")
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.assertEqual(before, self.view())
        for table, rows in durable.items():
            self.assertEqual(rows, [tuple(row) for row in self.store.rows("SELECT * FROM " + table)])
        names = {row[0] for row in self.store.rows("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertTrue({"events_listening_window", "sessions_completed_at"} <= names)

    def test_actual_projection_uses_time_indexes_and_bounded_rows_with_large_old_bodies(self):
        old = stamp(self.now - 90 * 86400)
        large = json.dumps({"answer": "PRIVATE ANSWER" * 1000})
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)",
                [("old", 1, "answer", old, large) for _ in range(600)])
            record = {"mode": "reviews", "phase": "complete", "started_at": old, "ended_at": old,
                "completed": 1, "queue": [{"subject_id": 1, "done": True}], "draft": "PRIVATE ANSWER" * 1000}
            self.store.db.executemany("INSERT INTO sessions VALUES(?,?)",
                [("old-" + str(i), json.dumps(record)) for i in range(300)])
            self.store.db.executemany("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)",
                [("old-listening", 1, "listening_result", old, json.dumps({"rating":"again","operation":"old-"+str(i)})) for i in range(600)])
        self.setup_listening()
        self.listen("start", subject_ids=[1])
        self.listen("skip")
        self.session(count=1)
        self.event()
        plans, sizes = [], []
        original = self.store.rows
        def rows(sql, args=()):
            if "FROM events" in sql or "FROM sessions" in sql:
                plans.extend(row[3] for row in original("EXPLAIN QUERY PLAN " + sql, args))
            result = original(sql, args)
            sizes.append(len(result))
            return result
        with patch.object(self.store, "rows", side_effect=rows):
            value = self.view()
        plan = "\n".join(plans)
        for name in ("events_completion_time", "events_study_window", "events_listening_window", "sessions_completed_at"):
            self.assertIn(name, plan)
        self.assertIn("SEARCH events USING INDEX events_listening_window (<expr>>?)", plan)
        self.assertIn("SEARCH events USING INTEGER PRIMARY KEY (rowid>?)", plan)
        self.assertLessEqual(max(sizes), 30)
        self.assertEqual(1, value["windows"]["30"]["sessions_completed"]["reviews"])
        self.assertEqual(1, value["windows"]["30"]["listening_ratings"]["skipped"])

    def test_missing_protected_content_withholds_all_automatic_difficulties(self):
        self.subject(5)
        self.event(sid=5, errors={"meaning": 1, "reading": 0})
        self.session(complete=False, count=1)
        self.assertTrue(self.view()["difficulties_withheld"])
        self.assertEqual([], self.view()["difficulties"])

    def test_navigation_suggestions_never_start_or_submit_work(self):
        self.session(complete=False, count=1)
        self.outbox("uncertain")
        with patch.object(self.engine, "start", side_effect=AssertionError("read only")), patch.object(self.engine, "snapshot", side_effect=AssertionError("no full catalogue")):
            value = self.view(availability={"reviews": 42, "listening": 8})
        self.assertEqual(["saved_submissions", "resume_reviews", "listen_five"], [item["code"] for item in value["suggestions"]])
        self.assertTrue(all(item["effect"] == "navigation_only" for item in value["suggestions"]))
        self.assertTrue(all(item["route"]["view"] not in ("reviews", "lessons", "resume") for item in value["suggestions"]))

    def test_read_only_query_does_not_fetch_private_bodies_or_mutate_database(self):
        self.session()
        self.outbox("confirmed")
        self.event()
        before = self.store.db.total_changes
        original = self.store.rows
        returned_keys = set()
        def rows(sql, args=()):
            result = original(sql, args)
            if any("FROM " + table in sql for table in ("events", "sessions", "outbox", "resources")):
                for row in result:
                    returned_keys.update(row.keys())
            return result
        with patch.object(self.store, "rows", side_effect=rows):
            value = self.view()
        self.assertEqual(before, self.store.db.total_changes)
        self.assertNotIn("body", returned_keys)
        for text in ("PRIVATE ANSWER", "PRIVATE NOTE", "PRIVATE DETAIL", "assignment_id"):
            self.assertNotIn(text, json.dumps(value))

    def test_account_identity_and_invalid_clock_do_not_project_other_history(self):
        self.event()
        self.store.set("account_id", "different-account")
        with self.assertRaises(UserError):
            self.view()
        self.store.set("account_id", "authored-account")
        for value in (True, float("nan"), float("inf"), -1, "2026"):
            with self.subTest(value=value), self.assertRaises(UserError):
                self.view(now=value)
        with self.assertRaises(UserError):
            self.view(timezone="Not/A-Timezone")

    def test_deletion_clears_local_history_and_demo_confirmation_is_labeled(self):
        self.event()
        self.engine.demo = True
        self.outbox("confirmed")
        self.assertEqual("Confirmed locally in demo", self.view()["current_submissions"]["confirmed_label"])
        for table in ("events", "outbox", "sessions"):
            self.store.execute("DELETE FROM " + table)
        value = self.view()
        self.assertEqual(0, value["windows"]["30"]["subject_completions"]["reviews"])
        self.assertEqual(0, value["current_submissions"]["confirmed"])


if __name__ == "__main__":
    unittest.main()
