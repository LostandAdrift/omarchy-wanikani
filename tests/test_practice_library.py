"""Practice catalogue selection, provenance, access, and spoiler regressions."""
import copy
import unittest
from pathlib import Path

from test_backend import EngineFixture, NOW, UserError, stamp
from wanikani.practice import catalogue, validate_selection, MISTAKE_DAYS


class PracticeLibraryTests(EngineFixture, unittest.TestCase):
    def event(self, sid, kind="answer", part="meaning", answer_kind="incorrect", when=NOW, session="authored-session"):
        self.store.event(session, sid, kind, stamp(when), {"part": part, "kind": answer_kind})

    def ids(self, result):
        return [item["id"] for item in result["items"]]

    def item(self, result, sid):
        return next(item for item in result["items"] if item["id"] == sid)

    def finish(self, view):
        while view["phase"] == "lesson":
            view = self.engine.lesson_next()
        while view["phase"] != "complete":
            self.engine.answer(self.correct_answer(view))
            view = self.engine.advance()
        return view

    def test_default_groups_and_provenance(self):
        result = catalogue(self.engine)
        self.assertEqual({"suggested": 2, "saved": 0, "mistakes": 0, "learned": 13}, result["counts"])
        self.assertEqual({3, 4}, set(self.ids(result)))
        self.assertEqual("lower_accuracy", result["items"][0]["reasons"][0]["code"])
        self.assertIn("WaniKani recorded", result["items"][0]["reasons"][0]["label"])
        self.assertEqual(result["counts"], result["ready_counts"])
        self.assertEqual(20, result["selection_limit"])
        self.assertEqual(14, result["mistake_days"])

    def test_hidden_accuracy_record_does_not_recommend_an_accessible_subject(self):
        statistic = self.store.related("review_statistic", 3)
        statistic["data"]["hidden"] = True
        self.store.put(statistic)
        self.assertEqual([4], self.ids(catalogue(self.engine)))
        self.assertIn(3, self.ids(catalogue(self.engine, "learned")))

    def test_saved_subjects_keep_personal_order_and_include_explicit_preparation(self):
        self.engine.pin(16, True)
        self.engine.pin(6, True)
        result = catalogue(self.engine, "saved")
        self.assertEqual([6, 16], self.ids(result))
        self.assertFalse(self.item(result, 6)["learned"])
        self.assertNotIn(6, self.ids(catalogue(self.engine, "learned")))
        self.assertTrue(self.item(result, 6)["ready"])
        self.assertEqual([6], validate_selection(self.engine, [6]))

    def test_recent_mistakes_exclude_only_the_guarded_corrected_answer(self):
        self.event(2, when=NOW - 20)
        self.event(2, when=NOW - 10)
        self.event(2, kind="correction", when=NOW - 9)
        self.event(2, part="reading", when=NOW - 5)
        self.event(3, when=NOW - MISTAKE_DAYS * 86400 - 1)
        result = catalogue(self.engine, "mistakes")
        self.assertEqual([2], self.ids(result))
        self.assertEqual({"meaning": 1, "reading": 1, "total": 2}, result["items"][0]["mistakes"])
        self.assertEqual(stamp(NOW - 5), result["items"][0]["last_mistake_at"])

    def test_retryable_and_accepted_answers_never_become_mistakes(self):
        for kind in ("retry", "correct", "imprecise"):
            self.event(2, answer_kind=kind)
        self.assertEqual([], self.ids(catalogue(self.engine, "mistakes")))

    def test_recent_order_prefers_latest_local_mistake(self):
        self.event(2, when=NOW - 50)
        self.event(4, part="reading", when=NOW - 5)
        self.assertEqual([4, 2], self.ids(catalogue(self.engine, "mistakes")))

    def test_pending_review_and_pending_lesson_remain_practiceable(self):
        self.finish(self.engine.start("reviews", 5))
        self.finish(self.engine.start("lessons", 1))
        result = catalogue(self.engine, "learned")
        self.assertEqual(14, result["total"])
        pending_ids = [row[0] for row in self.store.rows("SELECT subject_id FROM outbox")]
        for sid in pending_ids:
            item = self.item(result, sid)
            self.assertTrue(item["pending_graded"])
            self.assertTrue(item["ready"])
            self.assertIn("pending_graded", [reason["code"] for reason in item["reasons"]])
        self.assertEqual(pending_ids, validate_selection(self.engine, pending_ids))
        before = [tuple(row) for row in self.store.rows("SELECT * FROM outbox")]
        self.finish(self.engine.start("practice", len(pending_ids), pending_ids))
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM outbox")])

    def test_hidden_and_inaccessible_subjects_are_absent_from_all_counts(self):
        for sid in (1, 2, 3):
            self.engine.pin(sid, True)
            self.event(sid)
        subject = self.store.subject(1)
        subject["data"]["hidden_at"] = stamp(NOW)
        self.store.put(subject)
        assignment = self.store.related("assignment", 2)
        assignment["data"]["hidden"] = True
        self.store.put(assignment)
        subject = self.store.subject(3)
        subject["data"]["level"] = 4
        self.store.put(subject)
        user = self.store.get("user")
        user["data"]["subscription"] = {"type": "recurring", "max_level_granted": 60, "period_ends_at": stamp(NOW - 1)}
        self.store.set("user", user)
        for group in ("suggested", "saved", "mistakes", "learned"):
            result = catalogue(self.engine, group)
            self.assertFalse({1, 2, 3} & set(self.ids(result)))
            self.assertEqual(0, result["counts"]["saved"])
            self.assertEqual(0, result["counts"]["mistakes"])
        for sid in (1, 2, 3):
            with self.assertRaises(UserError):
                validate_selection(self.engine, [sid])

    def test_paginated_results_cover_each_learned_subject_once(self):
        seen = []
        offset = 0
        while True:
            result = catalogue(self.engine, "learned", offset=offset, limit=4)
            self.assertEqual(13, result["total"])
            seen += self.ids(result)
            if not result["has_more"]:
                self.assertIsNone(result["next_offset"])
                break
            offset = result["next_offset"]
        self.assertEqual(13, len(seen))
        self.assertEqual(13, len(set(seen)))
        self.assertEqual(sorted(seen), seen)

    def test_literal_search_only_matches_values_and_preserves_group_counts(self):
        for query in ("accepted", "primary", "%", "_", "\\"):
            self.assertEqual([], self.ids(catalogue(self.engine, "learned", query)))
        result = catalogue(self.engine, "learned", "mountain")
        self.assertEqual([2], self.ids(result))
        self.assertEqual(13, result["counts"]["learned"])
        self.assertEqual([4], self.ids(catalogue(self.engine, "learned", "みず")))
        self.assertEqual([2], self.ids(catalogue(self.engine, "learned", "山が見える")))
        subject = self.store.subject(16)
        subject["data"]["meanings"] += [{"meaning": "100% effort_with_a\\slash", "accepted_answer": True}]
        self.store.put(subject)
        for query in ("%", "_", "\\"):
            self.assertEqual([16], self.ids(catalogue(self.engine, "learned", query)))

    def test_image_only_radical_availability_is_explicit(self):
        subject = self.store.subject(1)
        subject["data"]["characters"] = None
        subject["data"]["character_images"] = [{"url": "https://example.invalid/practice-image.svg"}]
        self.store.put(subject)
        result = catalogue(self.engine, "learned")
        item = self.item(result, 1)
        self.assertFalse(item["ready"])
        self.assertIn("radical image", item["cache_note"])
        self.assertEqual(12, result["ready_counts"]["learned"])
        with self.assertRaises(UserError):
            validate_selection(self.engine, [1])
        image = Path(self.temp.name) / "media" / "radical.svg"
        image.parent.mkdir(exist_ok=True)
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.store.execute("INSERT INTO media VALUES(?,?,?,?)", (subject["data"]["character_images"][0]["url"], str(image), image.stat().st_size, NOW))
        item = self.item(catalogue(self.engine, "learned"), 1)
        self.assertTrue(item["ready"])
        self.assertEqual([image.as_uri()], item["images"])

    def test_graded_questions_remain_spoiler_free_while_practice_is_active(self):
        view = self.engine.start("reviews", 5)
        protected = {item["subject_id"] for item in self.store.session()["queue"]}
        self.engine.start("practice", 1, [16])
        result = catalogue(self.engine, "learned")
        self.assertTrue(result["graded_paused"])
        for item in result["items"]:
            if item["id"] in protected:
                self.assertTrue(item["spoilers_hidden"])
                self.assertEqual("", item["meaning"])
            self.assertNotIn("readings", item)
            self.assertNotIn("reading_mnemonic", item)
        self.assertIsNotNone(result["saved_practice"])
        self.assertEqual({"id", "completed", "total"}, set(result["saved_practice"]))
        self.assertNotEqual(view["id"], result["saved_practice"]["id"])

    def test_catalogue_and_validation_do_not_mutate_personal_state(self):
        self.engine.pin(16, True)
        self.engine.start("reviews", 2)
        self.engine.draft("a saved graded draft")
        before = list(self.store.db.iterdump())
        for group in ("suggested", "saved", "mistakes", "learned"):
            catalogue(self.engine, group)
        self.assertEqual([1, 2], validate_selection(self.engine, [1, 2, 1]))
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_selection_bounds_and_types_fail_before_start(self):
        for values in ([], list(range(1, 22)), [True], ["1"], [0], None, "1", [99999]):
            with self.subTest(values=values), self.assertRaises(UserError):
                validate_selection(self.engine, values)
        self.assertIsNone(self.store.session())
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_twenty_selected_subjects_enter_the_explicit_practice_set(self):
        for sid in range(17, 21):
            subject = copy.deepcopy(self.store.subject(1))
            subject["id"] = sid
            self.store.put(subject)
        ids = list(range(1, 21))
        self.assertEqual(ids, validate_selection(self.engine, ids))
        view = self.engine.start("practice", 20, ids, replace_practice=True)
        self.assertEqual(20, view["total"])
        self.assertEqual(set(ids), {item["subject_id"] for item in self.store.session()["queue"]})
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_bad_filters_and_page_values_are_rejected(self):
        for args in ({"group": "all"}, {"query": []}, {"limit": True}, {"offset": "next"}):
            with self.subTest(args=args), self.assertRaises(UserError):
                catalogue(self.engine, **args)

    def test_explicit_replacement_preserves_old_practice_and_paused_graded_work(self):
        graded = self.engine.start("reviews", 1)
        self.engine.draft("my unfinished graded answer")
        first = self.engine.start("practice", 1, [3])
        self.engine.draft("my unfinished practice answer")
        previous = self.store.session()
        # An ordinary practice action still resumes the earlier set.
        self.assertEqual(first["id"], self.engine.start("practice", 1, [4])["id"])
        resumed_practice = self.store.session()
        self.assertEqual({key: value for key, value in previous.items() if key != "revision"},
            {key: value for key, value in resumed_practice.items() if key != "revision"})
        previous = resumed_practice
        second = self.engine.start("practice", 1, [4], replace_practice=True)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(4, second["subject"]["id"])
        self.assertEqual(previous, self.store.session(first["id"]))
        self.assertEqual(second["id"], catalogue(self.engine)["saved_practice"]["id"])
        resumed = self.engine.start("resume")
        self.assertEqual(graded["id"], resumed["id"])
        self.assertEqual("my unfinished graded answer", resumed["draft"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_invalid_replacement_preserves_active_reference_and_draft(self):
        practice = self.engine.start("practice", 1, [3])
        self.engine.draft("keep this draft")
        before = list(self.store.db.iterdump())
        for args in ({"subjects": [99999]}, {"subjects": []}, {"mode": "reviews", "subjects": [1]}):
            with self.subTest(args=args), self.assertRaises(UserError):
                self.engine.start(**{"mode": "practice", "limit": 1, "replace_practice": True, **args})
            self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(practice["id"], self.store.get("active_session"))
        self.assertEqual("keep this draft", self.engine.session_view()["draft"])
