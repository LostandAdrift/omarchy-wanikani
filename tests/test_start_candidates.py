"""New batches select uniformly without decoding the entire due catalogue."""
from collections import Counter
import copy
import itertools
import tracemalloc
import unittest
from unittest.mock import Mock, patch

from test_backend import EngineFixture, NOW, stamp
from test_history import timezone
import test_schedule_queries as schedule


def ordered_shuffle(ids):
    positions = {str(value): index for index, value in enumerate(ids)}
    return Mock(shuffle=lambda rows: rows.sort(key=lambda row: positions[row["subject_id"]]))


class StartCandidateTests(EngineFixture, unittest.TestCase):
    def test_projected_candidates_match_full_load_with_access_pending_and_malformed_dates(self):
        for seed in range(3):
            self.store.execute("DELETE FROM outbox")
            self.store.execute("""DELETE FROM resources WHERE
              (kind IN ('radical','kanji','vocabulary','kana_vocabulary') AND CAST(id AS INTEGER)>=100)
              OR (kind='assignment' AND CAST(json_extract(body,'$.data.subject_id') AS INTEGER)>=100)""")
            schedule.ScheduleQueryTests.populate_mixed(self, seed, 150)
            for zone in ("UTC", "America/Los_Angeles", "Asia/Tokyo"):
                for maximum in (3, 60):
                    user = self.store.get("user")
                    user["data"]["subscription"]["max_level_granted"] = maximum
                    self.store.set("user", user)
                    with timezone(zone):
                        for mode in ("reviews", "lessons"):
                            with self.subTest(seed=seed, zone=zone, maximum=maximum, mode=mode):
                                original = self.engine.assignments(mode)
                                projected = list(self.engine._study_candidates(mode))
                                # Count duplicate assignment records too: every
                                # eligible candidate keeps its original weight.
                                key = lambda pair: (pair[0]["id"], pair[1]["id"])
                                self.assertEqual(Counter(map(key, original)), Counter(map(key, projected)))
                                originals = {key(pair): pair for pair in original}
                                for pair in projected:
                                    self.assertEqual(originals[key(pair)], pair)

    def test_every_permutation_samples_the_whole_eligible_population(self):
        # Exhaust all 4! shuffle outcomes; every two-subject subset must occur
        # equally often. This catches limiting before random selection without
        # relying on a flaky probability threshold or a particular PRNG seed.
        self.store.execute("DELETE FROM resources WHERE kind='assignment' AND id='105'")
        selected = Counter()
        for permutation in itertools.permutations((1, 2, 3, 4)):
            self.store.execute("DELETE FROM sessions")
            self.store.set("active_session", None)
            self.store.set("graded_session", None)
            with patch("wanikani.engine.random.SystemRandom", return_value=ordered_shuffle(permutation)):
                self.engine.start("reviews", 2)
            ids = tuple(item["subject_id"] for item in self.store.session()["queue"])
            self.assertEqual(permutation[:2], ids)
            selected[tuple(sorted(ids))] += 1
        self.assertEqual(set(itertools.combinations((1, 2, 3, 4), 2)), set(selected))
        self.assertEqual({4}, set(selected.values()))

    def test_missing_image_and_invalid_answers_are_skipped_before_filling_batch(self):
        radical = self.store.subject(1)
        radical["data"]["characters"] = None
        radical["data"]["character_images"] = [{"url": "https://fixture.invalid/missing.svg"}]
        self.store.put(radical)
        kanji = self.store.subject(2)
        kanji["data"]["meanings"][0]["accepted_answer"] = False
        self.store.put(kanji)
        resource = self.store.resource
        with patch("wanikani.engine.random.SystemRandom", return_value=ordered_shuffle((1, 2, 3, 4, 5))), \
                patch.object(self.store, "resource", wraps=resource) as loaded:
            self.engine.start("reviews", 2)
        entries = self.store.session()["queue"]
        self.assertEqual([3, 4], [entry["subject_id"] for entry in entries])
        self.assertEqual(["101", "102", "103", "104"],
            [call.args[1] for call in loaded.call_args_list if call.args[0] == "assignment"])
        self.assertEqual("103", str(entries[0]["assignment_id"]))
        self.assertEqual(stamp(NOW - 3600), entries[0]["baseline"]["available_at"])

    def test_lessons_keep_level_then_lesson_position_order(self):
        for sid, level, position in ((6, 2, 0), (7, 1, 99), (8, 1, 2)):
            subject = self.store.subject(sid)
            subject["data"].update(level=level, lesson_position=position)
            self.store.put(subject)
        with patch("wanikani.engine.random.SystemRandom", side_effect=AssertionError("Lessons must not shuffle")):
            self.engine.start("lessons", 2)
        self.assertEqual([8, 7], [entry["subject_id"] for entry in self.store.session()["queue"]])
        self.assertEqual("lesson", self.store.session()["phase"])

    def test_resume_does_not_query_candidates_or_change_saved_answers(self):
        self.engine.start("reviews", 2)
        self.engine.draft("authored saved draft")
        before = self.store.session()
        with patch.object(self.engine, "_study_candidates", side_effect=AssertionError("Resume queried catalogue")):
            view = self.engine.start("resume")
        self.assertEqual(before["queue"], self.store.session()["queue"])
        self.assertEqual(before["id"], view["id"])
        self.assertEqual("authored saved draft", view["draft"])

    def test_invalid_unlock_date_is_removed_before_lesson_sorting(self):
        assignment = self.store.related("assignment", 8)
        assignment["data"]["unlocked_at"] = 12345  # SQLite accepts a Julian day; epoch rejects it.
        self.store.put(assignment)
        subject = self.store.subject(8)
        subject["data"]["lesson_position"] = None
        self.store.put(subject)
        self.assertEqual([6, 7], [pair[1]["id"] for pair in self.engine.assignments("lessons")])
        self.engine.start("lessons", 3)
        self.assertEqual([6, 7], [entry["subject_id"] for entry in self.store.session()["queue"]])

    def test_full_catalogue_only_materializes_the_requested_batch(self):
        subject = self.store.subject(4)
        assignment = self.store.related("assignment", 4)
        with self.store.transaction():
            for sid in range(100, 9100):
                item = copy.deepcopy(subject)
                item["id"] = sid
                item["data"]["level"] = sid % 60 + 1
                item["data"]["meaning_mnemonic"] = "Independently authored large catalogue mnemonic. " * 20
                self.store.put(item)
                current = copy.deepcopy(assignment)
                current["id"] = sid + 10000
                current["data"]["subject_id"] = sid
                current["data"]["available_at"] = stamp(NOW - 1 if sid % 3 == 0 else NOW + sid * 60)
                self.store.put(current)
        resource, subject_load, rows = self.store.resource, self.store.subject, self.store.rows
        captured = []
        def inspect_query(sql, args=()):
            if "SELECT a.id AS assignment_id,s.id AS subject_id" in sql:
                captured.extend(row[3] for row in rows("EXPLAIN QUERY PLAN " + sql, args))
            return rows(sql, args)
        tracemalloc.start()
        try:
            with patch.object(self.engine, "assignments", side_effect=AssertionError("Full catalogue decoded")), \
                    patch.object(self.store, "resource", wraps=resource) as assignments, \
                    patch.object(self.store, "subject", wraps=subject_load) as subjects, \
                    patch.object(self.store, "rows", side_effect=inspect_query):
                self.engine.start("reviews", 5)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(5, sum(call.args[0] == "assignment" for call in assignments.call_args_list))
        selected = {str(entry["subject_id"]) for entry in self.store.session()["queue"]}
        self.assertEqual(selected, {str(call.args[0]) for call in subjects.call_args_list})
        self.assertLessEqual(subjects.call_count, 9)  # Includes visible-question detail checks.
        self.assertLess(peak, 4 * 1024 * 1024)
        self.assertTrue(any("resource_assignment_schedule" in step for step in captured), captured)
        self.assertTrue(any("USING COVERING INDEX resource_search_identity" in step for step in captured), captured)


if __name__ == "__main__":
    unittest.main()
