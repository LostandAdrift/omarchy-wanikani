"""Authored account fixtures for real learner-facing progress semantics."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_backend import Engine, Store, NOW, stamp
from wanikani import progress
from wanikani.common import UserError


class LearningProgressTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "state.db")
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.store.set("user", {"object": "user", "data": {"id": "authored-account", "level": 1,
            "username": "Fixture learner", "subscription": {"type": "lifetime", "max_level_granted": 60,
                "period_ends_at": None}, "current_vacation_started_at": None}})
        self.mark_complete()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def mark_complete(self):
        for key in ("cursor_subjects", "cursor_assignments", "cursor_level_progressions", "last_sync"):
            self.store.set(key, stamp(NOW - 10))
        self.store.set("cached_max_level", 60)

    def subject(self, sid, kind="kanji", level=1, characters=None, components=()):
        value = {"id": sid, "object": kind, "data": {"level": level, "hidden_at": None,
            "characters": characters or "山" + str(sid), "component_subject_ids": list(components),
            "meanings": [{"meaning": "Authored word " + str(sid), "accepted_answer": True, "primary": True}],
            "readings": [{"reading": "やま", "accepted_answer": True}], "auxiliary_meanings": []}}
        self.store.put(value)
        return value

    def assignment(self, sid, stage=1, passed=False, **changes):
        data = {"subject_id": sid, "srs_stage": stage, "hidden": False,
            "unlocked_at": stamp(NOW - 10000), "started_at": stamp(NOW - 9000) if stage else None,
            "passed_at": stamp(NOW - 3600) if passed else None,
            "burned_at": stamp(NOW - 100) if stage == 9 else None,
            "available_at": None if stage in (0, 9) else stamp(NOW + 3600)}
        data.update(changes)
        value = {"id": sid + 100000, "object": "assignment", "data": data}
        self.store.put(value)
        return value

    def queued(self, sid, state="pending", kind="review", key=None):
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (
            key or str(sid) + state + kind, kind, sid, state, "{}", stamp(NOW), "Authored queue fixture"))

    def test_first_passing_survives_demotion_and_fills_at_90_percent(self):
        for sid in range(1, 19):
            self.subject(sid)
            self.assignment(sid, stage=2 if sid == 1 else 5 if sid < 18 else 4, passed=sid < 18)
        value = progress.current_level(self.engine)
        self.assertTrue(value["complete"])
        self.assertEqual((18, 17, 17, 0, 1.0), tuple(value[key] for key in ("total", "passed", "required", "remaining", "fraction")))
        self.assertTrue(value["threshold_met"])
        self.assertIsNone(value["level_passed_at"], "A computed threshold is not a fabricated server confirmation")

    def test_current_guru_without_passing_timestamp_is_not_invented_progress(self):
        self.subject(1)
        self.assignment(1, stage=5)
        self.assertEqual(0, progress.current_level(self.engine)["passed"])
        self.assertEqual("Guru 1", progress.subject_status(self.engine, 1)["stage_name"])

    def test_pending_and_uncertain_work_stay_separate_from_confirmed_passing(self):
        self.subject(1)
        self.assignment(1, stage=4)
        self.queued(1)
        self.queued(1, "uncertain")
        self.queued(1, "pending", "material")
        current = progress.current_level(self.engine)
        self.assertEqual((0, 1, 1), (current["passed"], current["pending"], current["attention"]))
        state = progress.subject_status(self.engine, 1)
        self.assertEqual("Needs attention", state["label"])
        self.assertEqual(2, state["pending_operations"])
        self.assertEqual("Apprentice 4", state["stage_name"])

    def test_missing_or_future_sync_markers_do_not_claim_complete_progress(self):
        self.subject(1)
        self.assignment(1, passed=True)
        for key, value in (("cursor_subjects", None), ("cursor_assignments", None),
                ("cursor_level_progressions", None), ("cached_max_level", 0),
                ("cursor_subjects", stamp(NOW + 3600)), ("cursor_assignments", "bad date")):
            with self.subTest(key=key, value=value):
                self.mark_complete()
                self.store.set(key, value)
                result = progress.current_level(self.engine)
                self.assertFalse(result["complete"])
                self.assertIsNone(result["required"])
                self.assertIsNone(result["remaining"])
                self.assertIsNone(result["fraction"])
                self.assertIsNone(result["threshold_met"])

    def test_complete_catalogue_with_no_assignments_can_show_locked_subjects(self):
        self.subject(1)
        result = progress.current_level(self.engine)
        self.assertTrue(result["complete"])
        self.assertEqual(1, result["remaining"])
        self.assertEqual("Locked", progress.subject_status(self.engine, 1)["label"])

    def test_empty_current_level_never_claims_completion(self):
        result = progress.current_level(self.engine)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["fraction"])

    def test_level_60_and_subscription_limits_do_not_promise_level_61(self):
        user = self.store.get("user")
        user["data"]["level"] = 60
        self.store.set("user", user)
        self.subject(1, level=60)
        self.assignment(1, stage=5, passed=True)
        value = progress.current_level(self.engine)
        self.assertTrue(value["final_level"])
        self.assertEqual("Final level passing target reached.", value["message"])
        user["data"]["subscription"].update(type="free", max_level_granted=3)
        self.store.set("user", user)
        value = progress.current_level(self.engine)
        self.assertFalse(value["accessible"])
        self.assertIsNone(value["required"])
        self.assertEqual(0, value["total"])
        with self.assertRaises(UserError):
            progress.level_board(self.engine)

    def test_new_reset_attempt_does_not_reuse_previous_level_dates(self):
        self.subject(1)
        self.assignment(1)
        self.store.put({"id": 1, "object": "level_progression", "data": {"level": 1,
            "unlocked_at": stamp(NOW - 10 * 86400), "passed_at": stamp(NOW - 9 * 86400),
            "abandoned_at": stamp(NOW - 2 * 86400)}})
        self.store.put({"id": 2, "object": "level_progression", "data": {"level": 1,
            "unlocked_at": stamp(NOW - 86400), "passed_at": None, "abandoned_at": None}})
        value = progress.current_level(self.engine)
        self.assertEqual(1, value["elapsed_days"])
        self.assertIsNone(value["level_passed_at"])
        self.store.execute("DELETE FROM resources WHERE kind='level_progression' AND id='2'")
        self.assertIsNone(progress.current_level(self.engine)["unlocked_at"])

    def test_future_passing_timestamp_is_not_confirmed(self):
        self.subject(1)
        self.assignment(1, stage=5, passed_at=stamp(NOW + 1))
        self.assertEqual(0, progress.current_level(self.engine)["passed"])

    def test_srs_distribution_retains_locked_lessons_and_all_named_stages(self):
        self.subject(1, "radical")
        self.subject(2, "kanji")
        self.assignment(2, 0)
        for stage in range(1, 10):
            sid = stage + 2
            self.subject(sid, "vocabulary" if stage % 2 else "kana_vocabulary")
            self.assignment(sid, stage)
        groups = {item["key"]: item for item in progress.distribution(self.engine)["groups"]}
        self.assertEqual({"locked": 1, "lessons": 1, "apprentice": 4, "guru": 2,
            "master": 1, "enlightened": 1, "burned": 1, "unknown": 0}, {key: item["count"] for key, item in groups.items()})
        self.assertEqual(1, groups["locked"]["types"]["radical"])

    def test_subject_accuracy_uses_real_answer_counts_and_zero_is_unknown(self):
        self.subject(1)
        self.assignment(1, 4)
        self.store.put({"id": 1, "object": "review_statistic", "data": {"subject_id": 1,
            "meaning_correct": 9, "meaning_incorrect": 1, "reading_correct": 0, "reading_incorrect": 0,
            "percentage_correct": 12}})
        result = progress.subject_status(self.engine, 1)
        self.assertEqual({"correct": 9, "incorrect": 1, "total": 10, "percent": 90.0}, result["accuracy"]["meaning"])
        self.assertIsNone(result["accuracy"]["reading"]["percent"])
        self.assertEqual(stamp(NOW + 3600), result["next_review_at"])
        self.assertFalse(result["due"])

    def test_hidden_restricted_and_malformed_levels_are_not_exposed(self):
        user = self.store.get("user")
        user["data"]["subscription"].update(type="free", max_level_granted=3)
        self.store.set("user", user)
        for sid, level in ((1, 1), (2, 4), (3, "1"), (4, True), (5, 1), (6, 1)):
            item = self.subject(sid, level=level)
            if sid == 5:
                item["data"]["hidden_at"] = stamp(NOW - 1)
                self.store.put(item)
            if sid == 6:
                self.assignment(sid, hidden=True)
        board = progress.level_board(self.engine)
        self.assertEqual([1], [item["id"] for item in board["items"]])
        self.assertEqual(1, progress.distribution(self.engine)["total"])
        for sid in range(2, 7):
            with self.assertRaises(UserError):
                progress.subject_status(self.engine, sid)

    def test_board_paging_types_prerequisites_and_known_dates(self):
        self.subject(1, "radical")
        self.assignment(1, 4)
        self.subject(2, "radical")
        self.assignment(2, 3, passed=True)
        for sid in range(3, 10):
            self.subject(sid, components=[1, 2])
        first = progress.level_board(self.engine, subject_type="kanji", limit=2)
        self.assertEqual((7, True, 2), (first["total"], first["has_more"], first["next_offset"]))
        self.assertEqual([3, 4], [item["id"] for item in first["items"]])
        self.assertEqual([True, False], [item["required"] for item in first["items"][0]["prerequisites"]])
        self.assertEqual(stamp(NOW + 3600), first["items"][0]["prerequisites"][0]["status"]["next_review_at"])
        second = progress.level_board(self.engine, subject_type="kanji", offset=2, limit=2)
        self.assertEqual([5, 6], [item["id"] for item in second["items"]])

    def test_paused_reviews_lessons_and_written_aliases_hide_answers(self):
        self.subject(1, characters="山")
        self.subject(2, "vocabulary", characters="山")
        self.subject(3, "radical", characters="土")
        self.subject(4, components=[3])
        self.subject(5, "kanji", characters="土")
        for key, mode, sid in (("review", "reviews", 1), ("lesson", "lessons", 3)):
            self.store.execute("INSERT INTO sessions VALUES(?,?)", (key, json.dumps({"id": key, "mode": mode,
                "phase": "question", "queue": [{"subject_id": sid, "done": False}]})))
        items = {item["id"]: item for item in progress.level_board(self.engine)["items"]}
        for sid in (1, 2, 3, 5):
            self.assertTrue(items[sid]["spoilers_hidden"])
            self.assertFalse(items[sid]["can_open"])
            self.assertEqual("", items[sid]["meaning"])
        prerequisite = items[4]["prerequisites"][0]
        self.assertFalse(prerequisite["can_open"])
        self.assertEqual("", prerequisite["meaning"])

    def test_damaged_or_oversized_protection_scan_fails_closed(self):
        self.subject(1)
        for queue in (None, True, 3, {}, [{}], [{"subject_id": "1"}]):
            self.store.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", ("broken", json.dumps({"mode": "reviews", "phase": "question", "queue": queue})))
            result = progress.level_board(self.engine)
            self.assertFalse(result["protection_complete"])
            self.assertFalse(result["items"][0]["can_open"])
            self.assertEqual("", result["items"][0]["meaning"])

    def test_duplicate_assignments_do_not_double_count_a_subject(self):
        self.subject(1)
        item = self.assignment(1, 5, passed=True)
        item["id"] += 1
        self.store.put(item)
        result = progress.current_level(self.engine)
        self.assertEqual(1, result["total"])
        self.assertEqual(0, result["passed"])
        self.assertFalse(result["complete"])
        self.assertEqual("Refresh progress", progress.subject_status(self.engine, 1)["label"])

    def test_board_and_overview_do_not_mutate_private_state_or_load_full_bodies(self):
        for sid in range(1, 12):
            self.subject(sid)
            self.assignment(sid)
        before = self.store.db.total_changes
        captured = []
        original = self.store.rows
        def observe(sql, args=()):
            captured.append(sql)
            return original(sql, args)
        with patch.object(self.store, "rows", side_effect=observe):
            progress.overview(self.engine)
            progress.level_board(self.engine)
            progress.subject_status(self.engine, 1)
        self.assertEqual(before, self.store.db.total_changes)
        self.assertFalse(any("SELECT body FROM resources" in sql or "SELECT * FROM" in sql for sql in captured))

    def test_catalogue_bound_is_explicit_and_never_fabricates_full_percentage(self):
        for sid in range(1, 7):
            self.subject(sid)
            self.assignment(sid, 5, passed=True)
        with patch.object(progress, "MAX_LEVEL_SUBJECTS", 3), patch.object(progress, "MAX_CATALOGUE", 3):
            self.assertFalse(progress.current_level(self.engine)["complete"])
            self.assertIsNone(progress.current_level(self.engine)["fraction"])
            self.assertFalse(progress.distribution(self.engine)["complete"])
            board = progress.level_board(self.engine)
            self.assertFalse(board["total_complete"])
            self.assertLessEqual(len(board["items"]), 3)

    def test_malformed_dates_and_boolean_accuracy_never_become_progress(self):
        self.subject(1)
        for value in (True, 100, {}, [], "bad date", "0001-01-01T00:00:00+14:00"):
            with self.subTest(value=value):
                self.assignment(1, 5, passed_at=value)
                self.assertEqual(0, progress.current_level(self.engine)["passed"])
                self.assertFalse(progress.current_level(self.engine)["complete"])
                self.assertEqual("unknown", progress.subject_status(self.engine, 1)["group"])
        self.store.put({"id": 1, "object": "review_statistic", "data": {"subject_id": 1,
            "meaning_correct": True, "meaning_incorrect": 0, "reading_correct": -1, "reading_incorrect": 4}})
        state = progress.subject_status(self.engine, 1)
        self.assertIsNone(state["accuracy"]["meaning"]["percent"])
        self.assertIsNone(state["accuracy"]["reading"]["percent"])

    def test_malformed_components_do_not_fabricate_prerequisite_ids(self):
        self.subject(1, "radical")
        item = self.subject(2, components=[True, "1", {}, 1])
        board = progress.level_board(self.engine, subject_type="kanji")
        card = board["items"][0]
        self.assertFalse(card["prerequisites_complete"])
        self.assertEqual([1], [entry["id"] for entry in card["prerequisites"]])
        item["data"]["component_subject_ids"] = 1
        self.store.put(item)
        self.assertFalse(progress.level_board(self.engine, subject_type="kanji")["items"][0]["prerequisites_complete"])

    def test_partial_catalogue_does_not_lose_outside_page_alias_protection(self):
        self.subject(1, characters="山")
        self.subject(20000, "vocabulary", level=2, characters="山")
        self.store.execute("INSERT INTO sessions VALUES(?,?)", ("paused", json.dumps({"mode": "reviews", "phase": "question",
            "queue": [{"subject_id": 20000, "done": False}]})))
        with patch.object(progress, "MAX_LEVEL_SUBJECTS", 1):
            card = progress.level_board(self.engine)["items"][0]
        self.assertFalse(card["can_open"])
        self.assertEqual("", card["meaning"])

    def test_large_catalogue_pages_remain_projected_and_preserve_all_stage_counts(self):
        # Large mnemonic bodies must not become Python values in progress reads.
        with self.store.transaction():
            for sid in range(1, 9017):
                item = {"id": sid, "object": "kanji", "data": {"level": sid % 60 + 1,
                    "hidden_at": None, "characters": "山" + str(sid),
                    "meanings": [{"meaning": "Authored word", "accepted_answer": True}],
                    "meaning_mnemonic": "An independently authored mnemonic. " * 60}}
                self.store.execute("INSERT INTO resources VALUES(?,?,?)", ("kanji", str(sid), json.dumps(item)))
                self.assignment(sid, (sid - 1) % 9 + 1)
        captured = []
        original = self.store.rows
        def observe(sql, args=()):
            rows = original(sql, args)
            captured.extend(rows)
            return rows
        with patch.object(self.store, "rows", side_effect=observe):
            result = progress.distribution(self.engine)
            page = progress.level_board(self.engine, level=1, offset=60, limit=30)
        self.assertEqual(9016, result["total"])
        self.assertTrue(result["complete"])
        self.assertEqual(30, len(page["items"]))
        self.assertTrue(page["has_more"])
        self.assertFalse(any("mnemonic" in str(tuple(row)) for row in captured))


if __name__ == "__main__":
    unittest.main()
