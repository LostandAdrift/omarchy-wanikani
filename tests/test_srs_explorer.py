"""SRS drill-down uses authored resources, not an account or API connection."""
import copy
import json
import threading
import unittest
from unittest.mock import patch

import test_learning_progress as authored
from wanikani import progress, srs_explorer
from wanikani.common import UserError


class SrsExplorerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.LearningProgressTests()
        self.fixture.setUp()
        self.engine, self.store = self.fixture.engine, self.fixture.store
        self.store.set("account_id", "authored-account")

    def tearDown(self):
        self.fixture.tearDown()

    def word(self, sid, stage=1, level=1, kind="kanji", **changes):
        self.fixture.subject(sid, kind, level)
        self.fixture.assignment(sid, stage, **changes)

    def list(self, **args):
        return srs_explorer.catalogue(self.engine, **args)

    def protect(self, sid, mode="reviews"):
        self.store.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", (mode, json.dumps({"id": mode,
            "mode": mode, "phase": "question", "queue": [{"subject_id": sid, "done": False}]})))

    def test_all_group_lists_match_canonical_distribution_across_levels(self):
        self.fixture.subject(1, "radical", level=1)
        self.word(2, 0, level=2)
        for stage in range(1, 10):
            self.word(stage + 2, stage, level=stage, kind="vocabulary" if stage % 2 else "kana_vocabulary")
        self.word(12, 3, level=12, available_at="malformed")
        self.word(13, 2, level=13, burned_at=authored.stamp(authored.NOW - 10))
        counts = {group["key"]: group["count"] for group in progress.distribution(self.engine)["groups"]}
        for group, expected in counts.items():
            with self.subTest(group=group):
                page = self.list(group=group)
                self.assertEqual(expected, page["total"])
                self.assertEqual(expected, len(page["items"]))
                self.assertTrue(all(item["status"]["group"] == group for item in page["items"]))
        self.assertIn(13, [item["id"] for item in self.list(group="burned")["items"]], "Canonical burned date beats raw Apprentice stage")

    def test_facets_and_filters_run_before_pagination(self):
        for sid, level, stage, kind in ((1, 3, 4, "kanji"), (2, 1, 1, "kanji"), (3, 2, 4, "kanji"),
                                      (4, 2, 3, "kanji"), (5, 2, 4, "vocabulary"), (6, 2, 6, "kanji")):
            self.word(sid, stage, level, kind)
        page = self.list(subject_type="kanji", stage=4, limit=1)
        self.assertEqual(2, page["total"])
        self.assertEqual([3], [item["id"] for item in page["items"]])
        self.assertEqual([{"level": 2, "count": 1}, {"level": 3, "count": 1}], page["levels"])
        next_page = self.list(subject_type="kanji", stage=4, limit=1, offset=page["next_offset"])
        self.assertEqual([1], [item["id"] for item in next_page["items"]])
        filtered = self.list(subject_type="kanji", level=2, stage=4)
        self.assertEqual({1: 0, 2: 0, 3: 1, 4: 1}, {item["stage"]: item["count"] for item in filtered["stages"]})
        self.assertEqual(page["levels"], filtered["levels"])
        self.assertEqual("Apprentice 4", filtered["stages"][-1]["label"])

    def test_next_review_order_uses_cached_dates_before_limit_and_stable_ties(self):
        self.word(1, level=1, available_at=None)
        self.word(2, level=3, available_at=authored.stamp(authored.NOW + 100))
        self.word(3, level=2, available_at=authored.stamp(authored.NOW - 100))
        self.word(4, level=1, available_at=authored.stamp(authored.NOW + 100))
        page = self.list(order="next_review", limit=2)
        self.assertEqual([3, 4], [item["id"] for item in page["items"]])
        self.assertTrue(page["items"][0]["status"]["due"])
        self.assertEqual([2, 1], [item["id"] for item in self.list(order="next_review", offset=2)["items"]])
        self.assertIsNone(self.list(order="next_review", offset=3)["items"][0]["status"]["next_review_at"])

    def test_pending_and_first_passing_never_predict_a_different_group(self):
        self.word(1, stage=4, passed=True)
        self.fixture.queued(1)
        self.fixture.queued(1, "uncertain")
        card = self.list()["items"][0]
        self.assertEqual("apprentice", card["status"]["group"])
        self.assertEqual("Apprentice 4", card["status"]["stage_name"])
        self.assertTrue(card["status"]["passed"])
        self.assertEqual("Needs attention", card["status"]["label"])
        self.assertEqual(0, self.list(group="guru")["total"])

    def test_all_types_and_guru_substages_have_exact_filters(self):
        for sid, kind in enumerate(progress.TYPES, 1):
            self.word(sid, 5 if sid % 2 else 6, sid, kind)
        for kind in progress.TYPES:
            page = self.list(group="guru", subject_type=kind)
            self.assertEqual(1, page["total"])
            self.assertEqual(kind, page["items"][0]["type"])
        self.assertEqual(2, self.list(group="guru", stage=6)["total"])
        self.assertEqual(["Guru 1", "Guru 2"], [value["label"] for value in self.list(group="guru")["stages"]])

    def test_burned_date_with_other_stage_keeps_facts_but_marks_facets_partial(self):
        self.word(1, 2, burned_at=authored.stamp(authored.NOW - 10))
        self.word(2, 9)
        page = self.list(group="burned")
        self.assertEqual(2, page["total"])
        self.assertEqual([{"stage": 9, "label": "Burned", "count": 1}], page["stages"])
        self.assertEqual(2, page["items"][0]["status"]["stage"])
        self.assertEqual(authored.stamp(authored.NOW - 10), page["items"][0]["status"]["burned_at"])
        self.assertEqual("burned", page["items"][0]["status"]["group"])
        self.assertFalse(page["complete"])
        self.assertTrue(page["total_complete"])
        exact = self.list(group="burned", stage=9)
        self.assertEqual([2], [item["id"] for item in exact["items"]])
        self.assertFalse(exact["complete"])
        self.assertEqual(0, self.list(stage=2)["total"], "A confirmed burned date is not an Apprentice card")

    def test_empty_pages_and_last_page_have_no_invented_next_offset(self):
        self.word(1)
        self.assertFalse(self.list()["has_more"])
        self.assertIsNone(self.list()["next_offset"])
        page = self.list(offset=12000)
        self.assertEqual(1, page["total"])
        self.assertEqual([], page["items"])
        self.assertIsNone(page["next_offset"])
        self.assertEqual(0, self.list(group="burned")["total"])

    def test_malformed_assignment_dates_identity_and_duplicate_rows_are_honest(self):
        self.word(1); self.word(2); self.word(3)
        self.fixture.assignment(1, stage=4, started_at=authored.stamp(authored.NOW + 20))
        duplicate = self.store.related("assignment", 2); duplicate["id"] += 500; self.store.put(duplicate)
        broken = self.store.subject(3); broken["id"] = 99
        self.store.execute("UPDATE resources SET body=? WHERE id='3' AND kind='kanji'", (json.dumps(broken),))
        page = self.list(group="unknown")
        self.assertEqual({1, 2}, {item["id"] for item in page["items"]})
        self.assertFalse(page["complete"])
        self.assertFalse(page["total_complete"])
        self.assertFalse(next(item for item in page["items"] if item["id"] == 2)["can_open"])
        with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 2)

    def test_duplicate_numeric_subject_identity_cannot_open_twice(self):
        self.word(1)
        alias = self.store.subject(1); alias["object"] = "vocabulary"
        self.store.execute("INSERT INTO resources VALUES(?,?,?)", ("vocabulary", "1", json.dumps(alias)))
        page = self.list()
        self.assertEqual([], page["items"])
        self.assertFalse(page["total_complete"])
        with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 1)

    def test_duplicate_identity_across_catalogue_limit_is_not_a_safe_card(self):
        self.word(1); self.word(2); self.word(3)
        alias = self.store.subject(3); alias["object"] = "vocabulary"
        self.store.execute("INSERT INTO resources VALUES(?,?,?)", ("vocabulary", "3", json.dumps(alias)))
        with patch.object(srs_explorer, "MAX_CATALOGUE", 3):
            page = self.list()
        self.assertEqual([1, 2], [item["id"] for item in page["items"]])
        self.assertFalse(page["total_complete"])
        self.assertFalse(page["complete"])

    def test_partial_markers_clock_and_catalogue_cap_remain_explicit(self):
        for sid in range(1, 6): self.word(sid)
        self.store.set("cursor_subjects", None)
        self.assertFalse(self.list()["complete"])
        self.assertTrue(self.list()["total_complete"])
        self.fixture.mark_complete(); self.engine.clock_untrusted = True
        self.assertFalse(self.list()["complete"])
        self.engine.clock_untrusted = False
        with patch.object(srs_explorer, "MAX_CATALOGUE", 3):
            page = self.list()
        self.assertEqual(3, page["total"])
        self.assertFalse(page["total_complete"])
        self.assertFalse(page["complete"])

    def test_account_identity_mismatch_and_bad_access_fail_before_content_read(self):
        self.word(1)
        for identity in (None, "another-account", True, 1):
            self.store.set("account_id", identity)
            with self.subTest(identity=identity), patch.object(self.engine, "details", side_effect=AssertionError("No content from mismatched account")):
                with self.assertRaises(UserError): self.list()
                with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 1)
        self.store.set("account_id", "authored-account")
        user = self.store.get("user"); user["data"]["subscription"]["max_level_granted"] = True; self.store.set("user", user)
        with self.assertRaises(UserError): self.list()

    def test_expired_subscription_hidden_and_malformed_level_are_not_listed(self):
        self.word(1, level=2); self.word(2, level=40); self.word(3)
        user = self.store.get("user"); user["data"]["subscription"].update(type="recurring", period_ends_at=authored.stamp(authored.NOW - 1)); self.store.set("user", user)
        subject = self.store.subject(3); subject["data"]["level"] = "1"; self.store.put(subject)
        self.assertEqual([1], [item["id"] for item in self.list()["items"]])
        with self.assertRaises(UserError): self.list(level=40)
        with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 2)
        assignment = self.store.related("assignment", 1); assignment["data"]["hidden"] = True; self.store.put(assignment)
        self.assertEqual([], self.list()["items"])
        with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 1)

    def test_reset_to_locked_uses_current_assignment_without_reusing_old_stage(self):
        self.word(1, 8, level=4)
        self.assertEqual(1, self.list(group="enlightened")["total"])
        self.store.set("milestone_reset_generation", 1)
        self.store.execute("DELETE FROM resources WHERE kind='assignment'")
        self.assertEqual(0, self.list(group="enlightened")["total"])
        self.assertEqual(1, self.list(group="locked")["total"])
        self.assertIsNone(self.list(group="locked")["items"][0]["status"]["next_review_at"])

    def test_protected_ids_and_exact_glyph_aliases_keep_counts_but_hide_answers(self):
        self.word(1); self.word(2, kind="vocabulary"); self.word(3)
        alias = self.store.subject(2); alias["data"]["characters"] = self.store.subject(1)["data"]["characters"]; self.store.put(alias)
        self.protect(1, "lessons")
        page = self.list(); cards = {item["id"]: item for item in page["items"]}
        self.assertEqual(3, page["total"])
        for sid in (1, 2):
            self.assertTrue(cards[sid]["spoilers_hidden"])
            self.assertEqual("", cards[sid]["meaning"])
            self.assertFalse(cards[sid]["can_open"])
            with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, sid)
        self.assertTrue(cards[3]["can_open"])
        self.assertEqual(3, srs_explorer.guarded_details(self.engine, 3)["id"])

    def test_malformed_graded_protection_fails_closed_without_affecting_counts(self):
        self.word(1)
        self.store.execute("INSERT INTO sessions VALUES(?,?)", ("broken", json.dumps({"mode": "reviews", "phase": "question", "queue": None})))
        page = self.list()
        self.assertEqual(1, page["total"])
        self.assertFalse(page["protection_complete"])
        self.assertFalse(page["items"][0]["can_open"])
        self.assertEqual("", page["items"][0]["meaning"])
        with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 1)

    def test_guarded_open_rechecks_protection_after_a_safe_list(self):
        self.word(1)
        self.assertTrue(self.list()["items"][0]["can_open"])
        self.protect(1)
        with patch.object(self.engine, "details", side_effect=AssertionError("Protected content must not be hydrated")):
            with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 1)
        # The explicitly manual catalogue policy remains unchanged.
        self.assertEqual(1, self.engine.details(1)["id"])

    def test_guarded_relations_and_comparisons_use_strict_done_and_alias_protection(self):
        for sid in range(1, 5): self.word(sid)
        alias = self.store.subject(3)
        alias["data"]["characters"] = self.store.subject(2)["data"]["characters"]
        self.store.put(alias)
        parent = self.store.subject(1)
        parent["data"].update(component_subject_ids=[2, 3, 4], amalgamation_subject_ids=[2, 3, 4],
            visually_similar_subject_ids=[2, 3, 4])
        self.store.put(parent)
        keys = ("components", "related", "visually_similar")
        for done in (False, 1, "false"):
            with self.subTest(done=done):
                self.store.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", ("paused", json.dumps({
                    "id": "paused", "mode": "reviews", "phase": "question",
                    "queue": [{"subject_id": 2, "done": done}]})))
                before = self.store.db.total_changes
                value = srs_explorer.guarded_details(self.engine, 1)
                for key in keys:
                    self.assertEqual([4], [item["id"] for item in value[key]])
                self.assertEqual(before, self.store.db.total_changes)
        # Deliberate manual Lookup keeps its existing policy; the stronger
        # automatic projection must not mutate shared subject/material data.
        manual = self.engine.details(1)
        for key in keys:
            self.assertEqual([2, 3, 4], [item["id"] for item in manual[key]])

    def test_guarded_detail_and_concurrent_account_change_are_one_read_boundary(self):
        self.word(1)
        entered, attempted, changed, done = [threading.Event() for _ in range(4)]
        output = []; errors = []
        original = self.engine.details
        def project(subject_id):
            entered.set()
            self.assertTrue(attempted.wait(2))
            self.assertFalse(changed.wait(.05), "Another thread must not change account between authorization and content")
            return original(subject_id)
        def change():
            entered.wait(2); attempted.set()
            self.store.set("account_id", "another-account"); changed.set()
        def read():
            try: output.append(srs_explorer.guarded_details(self.engine, 1))
            except BaseException as error: errors.append(error)
            finally: done.set()
        with patch.object(self.engine, "details", side_effect=project):
            reader = threading.Thread(target=read); writer = threading.Thread(target=change)
            reader.start(); writer.start()
            reader.join(3); writer.join(3)
        self.assertTrue(done.is_set()); self.assertFalse(reader.is_alive()); self.assertFalse(writer.is_alive())
        self.assertEqual([], errors); self.assertEqual(1, output[0]["id"]); self.assertTrue(changed.is_set())
        with self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, 1)

    def test_strict_arguments_do_not_coerce_or_clamp_requests(self):
        for kwargs in ({"group": "Guru"}, {"group": []}, {"subject_type": "all"}, {"level": True}, {"level": 61},
                       {"stage": True}, {"stage": 5}, {"group": "guru", "stage": 4}, {"group": "locked", "stage": 0},
                       {"order": "random"}, {"offset": -1}, {"offset": 12001}, {"limit": 0}, {"limit": 61}, {"limit": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(UserError): self.list(**kwargs)
        for sid in (True, 0, -1, "1", 9007199254740992, []):
            with self.subTest(sid=sid), self.assertRaises(UserError): srs_explorer.guarded_details(self.engine, sid)

    def test_list_is_read_only_page_projected_and_uses_existing_numeric_indices(self):
        for sid in range(1, 121):
            self.word(sid, 4, level=sid % 12 + 1)
            subject = self.store.subject(sid)
            subject["data"].update(meaning_mnemonic="PRIVATE MNEMONIC " * 1000, pronunciation_audios=[{"private": "PRIVATE AUDIO"}])
            self.store.put(subject)
        queries, projected = [], []
        original = self.store.rows
        def inspect(sql, args=()):
            rows = original(sql, args); queries.append((sql, args)); projected.extend(tuple(row) for row in rows); return rows
        before = self.store.db.total_changes
        with patch.object(self.store, "rows", side_effect=inspect), patch.object(self.engine, "details", side_effect=AssertionError("List must not hydrate full subject details")):
            page = self.list(offset=60, limit=7)
        self.assertEqual(7, len(page["items"])); self.assertEqual(120, page["total"])
        self.assertEqual(before, self.store.db.total_changes)
        self.assertNotIn("PRIVATE", repr(projected))
        content_reads = [query for query in queries if " AS meaning" in query[0]]
        self.assertEqual(1, len(content_reads)); self.assertEqual(8, content_reads[0][1][-2])
        primary = next((sql, args) for sql, args in queries if "AS valid_identity" in sql and " AS meaning" not in sql)
        plan = self.store.rows("EXPLAIN QUERY PLAN " + primary[0], primary[1])
        self.assertTrue(any("resource_search_identity" in row[3] for row in plan))
        self.assertTrue(any("resource_subject" in row[3] for row in plan))


if __name__ == "__main__":
    unittest.main()
