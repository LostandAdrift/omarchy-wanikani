"""Lesson choices use authored resources and never submit account progress."""
import copy
import json
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, Engine, Store, UserError, NOW, stamp
from wanikani import lessons


class LessonDiscoveryTests(EngineFixture, unittest.TestCase):
    def add_lesson(self, sid, kind, position=0, characters=None):
        source = {"radical": 1, "kanji": 6, "vocabulary": 7, "kana_vocabulary": 5}[kind]
        subject = copy.deepcopy(self.store.subject(source))
        subject["id"] = sid
        subject["data"].update(lesson_position=position, component_subject_ids=[])
        if characters is not None:
            subject["data"]["characters"] = characters
        self.store.put(subject)
        assignment = copy.deepcopy(self.store.related("assignment", 6))
        assignment["id"] = sid + 10000
        assignment["data"].update(subject_id=sid, subject_type=kind, started_at=None, srs_stage=0)
        self.store.put(assignment)
        return subject

    def queue_ids(self):
        return [item["subject_id"] for item in self.store.session()["queue"]]

    def test_catalogue_counts_and_pages_are_by_explicit_subject_type(self):
        self.add_lesson(31, "radical", position=1)
        self.add_lesson(32, "kana_vocabulary", position=2)
        page = lessons.catalogue(self.engine, limit=2)
        self.assertEqual({"radical": 1, "kanji": 1, "vocabulary": 2, "kana_vocabulary": 1}, page["counts"])
        self.assertEqual((5, True, 2, True), (page["total"], page["has_more"], page["next_offset"], page["complete"]))
        self.assertEqual([31, 32], [item["id"] for item in page["items"]])
        rest = lessons.catalogue(self.engine, offset=2, limit=3)
        self.assertEqual([6, 7, 8], [item["id"] for item in rest["items"]])
        self.assertFalse(rest["has_more"])
        vocabulary = lessons.catalogue(self.engine, subject_type="vocabulary")
        self.assertEqual([7, 8], [item["id"] for item in vocabulary["items"]])
        self.assertEqual(page["counts"], vocabulary["counts"])

    def test_recommended_batch_respects_level_then_lesson_position(self):
        for sid, level, position in ((6, 2, 0), (7, 1, 99), (8, 1, 2)):
            subject = self.store.subject(sid)
            subject["data"].update(level=level, lesson_position=position)
            self.store.put(subject)
        result = lessons.preview(self.engine, limit=2)
        self.assertEqual([8, 7], [item["id"] for item in result["batch"]])
        self.assertEqual(2, result["counts"]["vocabulary"])
        self.assertFalse(result["resume_required"])
        self.assertIsNone(self.store.session())

    def test_selected_order_is_preserved_even_when_default_limit_is_smaller(self):
        before = list(self.store.db.iterdump())
        result = lessons.preview(self.engine, [8, 6, 7], limit=1)
        self.assertEqual([8, 6, 7], [item["id"] for item in result["batch"]])
        self.assertEqual(before, list(self.store.db.iterdump()))
        view = self.engine.start("lessons", limit=1, subjects=[8, 6, 7])
        self.assertEqual(("lesson", 3), (view["phase"], view["total"]))
        self.assertEqual([8, 6, 7], self.queue_ids())
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_unfinished_lessons_always_resume_without_replacing_feedback(self):
        first = self.engine.start("lessons", subjects=[7])
        self.engine.lesson_next()
        self.engine.answer("my incorrect lesson answer")
        expected = self.store.session()
        self.engine.start("reviews", 1)
        before = list(self.store.db.iterdump())
        result = lessons.preview(self.engine, [8, 6])
        self.assertTrue(result["resume_required"])
        self.assertEqual([], result["batch"])
        self.assertEqual(first["id"], result["saved_session"]["id"])
        self.assertNotIn("incorrect lesson answer", json.dumps(result))
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(first["id"], self.engine.start("lessons", subjects=[99999])["id"])
        self.assertEqual({key: value for key, value in expected.items() if key != "revision"},
            {key: value for key, value in self.store.session().items() if key != "revision"})

    def test_saved_selection_and_discovery_position_survive_restart(self):
        first = self.engine.start("lessons", subjects=[8, 7, 6])
        self.engine.lesson_next()
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.assertEqual(first["id"], self.engine.start("lessons", subjects=[7])["id"])
        self.assertEqual([8, 7, 6], self.queue_ids())
        self.assertEqual(1, self.store.session()["lesson_index"])

    def test_invalid_selections_never_mutate_session_or_outbox(self):
        for values in (None, [], [True], ["6"], [6, 6], [6] * 21, [0], [99999], [4]):
            before = list(self.store.db.iterdump())
            with self.subTest(values=values), self.assertRaises(UserError):
                lessons.validate_selection(self.engine, values)
            self.assertEqual(before, list(self.store.db.iterdump()))

    def test_changed_lock_pending_hidden_and_subscription_are_rechecked_before_start(self):
        for change in ("locked", "future", "started", "pending", "hidden", "grant"):
            with self.subTest(change=change):
                subject = self.add_lesson(100, "vocabulary", characters="独自")
                assignment = self.store.related("assignment", 100)
                if change == "locked":
                    assignment["data"]["unlocked_at"] = None
                elif change == "future":
                    assignment["data"]["unlocked_at"] = stamp(NOW + 1)
                elif change == "started":
                    assignment["data"].update(started_at=stamp(NOW), srs_stage=1)
                elif change == "hidden":
                    assignment["data"]["hidden"] = True
                elif change == "grant":
                    subject["data"]["level"] = 61
                    self.store.put(subject)
                elif change == "pending":
                    self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", ("authored-pending", "lesson", 100, "uncertain", "{}", stamp(NOW), ""))
                self.store.put(assignment)
                before = list(self.store.db.iterdump())
                with self.assertRaises(UserError):
                    self.engine.start("lessons", subjects=[100])
                self.assertEqual(before, list(self.store.db.iterdump()))
                self.assertNotIn(100, {item["id"] for item in lessons.catalogue(self.engine)["items"]})
                self.store.execute("DELETE FROM outbox WHERE id='authored-pending'")

    def test_paused_review_and_its_written_alias_are_not_lesson_choices(self):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != 2:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)
        self.engine.start("reviews", 1)
        self.add_lesson(100, "vocabulary", characters="山")
        page = lessons.catalogue(self.engine)
        self.assertNotIn(100, {item["id"] for item in page["items"]})
        with self.assertRaises(UserError) as failure:
            self.engine.start("lessons", subjects=[100])
        self.assertEqual("protected_session", failure.exception.code)
        # A compound remains a real separate lesson, but its protected
        # prerequisite cannot open an answer through the preview.
        card = next(item for item in page["items"] if item["id"] == 8)
        self.assertEqual([{ "id": 2, "type": "kanji", "characters": "山", "state": "Paused graded work", "can_open": False}], card["prerequisites"])

    def test_confirmed_unlock_survives_later_prerequisite_demotion(self):
        prerequisite = self.store.related("assignment", 2)
        prerequisite["data"].update(passed_at=stamp(NOW - 86400), srs_stage=1)
        self.store.put(prerequisite)
        card = lessons.preview(self.engine, [8])["batch"][0]
        self.assertEqual("Unlocked by WaniKani", card["unlock_status"])
        self.assertEqual("Passed", card["prerequisites"][0]["state"])
        self.engine.start("lessons", subjects=[8])
        self.assertEqual([8], self.queue_ids())

    def test_missing_required_images_are_visible_but_cannot_be_selected(self):
        subject = self.add_lesson(31, "radical", position=0)
        subject["data"].update(characters=None, character_images=[{"url": "https://files.wanikani.com/authored-image.svg"}])
        self.store.put(subject)
        card = lessons.catalogue(self.engine)["items"][0]
        self.assertEqual(31, card["id"])
        self.assertFalse(card["ready"])
        self.assertIn("not cached", card["cache_note"])
        self.assertNotIn(31, {item["id"] for item in lessons.preview(self.engine)["batch"]})
        with self.assertRaises(UserError) as failure:
            self.engine.start("lessons", subjects=[31])
        self.assertEqual("content_unavailable", failure.exception.code)
        path = self.path.parent / "media" / "authored-image.svg"
        path.parent.mkdir(exist_ok=True)
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.store.execute("INSERT INTO media VALUES(?,?,?,?)", (subject["data"]["character_images"][0]["url"], str(path), path.stat().st_size, NOW))
        self.assertTrue(lessons.preview(self.engine, [31])["batch"][0]["ready"])

    def test_metadata_list_and_preview_budgets_are_honest(self):
        with patch("wanikani.lessons.MAX_CATALOGUE", 2):
            page = lessons.catalogue(self.engine)
        self.assertFalse(page["complete"])
        self.assertEqual(2, page["total"])
        item = self.store.subject(6)
        item["data"]["meanings"] = []
        self.store.put(item)
        with patch("wanikani.lessons.MAX_PREVIEW_SCAN", 1):
            result = lessons.preview(self.engine, limit=2)
        self.assertFalse(result["complete"])
        self.assertEqual([], result["batch"])

    def test_failed_command_commit_rolls_back_explicit_selection(self):
        review = self.engine.start("reviews", 1)
        before = list(self.store.db.iterdump())
        original = self.store.execute
        def fail(sql, args=()):
            if sql.startswith("INSERT INTO commands"):
                raise OSError("Authored interruption before committed lesson reply")
            return original(sql, args)
        with patch.object(self.store, "execute", side_effect=fail), self.assertRaises(OSError):
            self.engine.command("chosen-lessons", "start", {"mode": "lessons", "subjects": [7]})
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(review["id"], self.engine.session_view()["id"])

    def test_catalogue_hydrates_only_the_requested_page(self):
        with self.store.transaction():
            for sid in range(100, 300):
                self.add_lesson(sid, "vocabulary", position=sid)
        with patch.object(self.engine, "details", wraps=self.engine.details) as details, \
                patch.object(self.store, "subject", wraps=self.store.subject) as subjects:
            page = lessons.catalogue(self.engine, offset=50, limit=3)
        self.assertEqual(203, page["total"])
        self.assertEqual(3, details.call_count)
        self.assertLessEqual(subjects.call_count, 6)

    def test_ambiguous_assignment_and_invalid_content_never_enter_selected_queue(self):
        duplicate = copy.deepcopy(self.store.related("assignment", 7))
        duplicate["id"] = 999
        self.store.put(duplicate)
        self.assertNotIn(7, {item["id"] for item in lessons.catalogue(self.engine)["items"]})
        with self.assertRaises(UserError) as failure:
            self.engine.start("lessons", subjects=[7])
        self.assertEqual("lesson_unavailable", failure.exception.code)
        subject = self.store.subject(6)
        subject["data"]["meanings"] = [{"meaning": "authored invalid flag", "accepted_answer": "true"}]
        self.store.put(subject)
        card = next(item for item in lessons.catalogue(self.engine)["items"] if item["id"] == 6)
        self.assertFalse(card["ready"])
        with self.assertRaises(UserError) as failure:
            self.engine.start("lessons", subjects=[6])
        self.assertEqual("content_unavailable", failure.exception.code)
        self.assertIsNone(self.store.session())

    def test_invalid_page_bounds_and_damaged_protection_fail_without_disclosure(self):
        for args in ({"subject_type": "all-content"}, {"offset": -1}, {"limit": True}, {"limit": 61}):
            with self.subTest(args=args), self.assertRaises(UserError):
                lessons.catalogue(self.engine, **args)
        self.store.execute("INSERT INTO sessions VALUES(?,?)", ("damaged", json.dumps({"mode": "reviews", "phase": "question", "queue": 12})))
        before = list(self.store.db.iterdump())
        for request in (lambda: lessons.catalogue(self.engine), lambda: lessons.preview(self.engine),
                lambda: self.engine.start("lessons", subjects=[7])):
            with self.assertRaises(UserError) as failure:
                request()
            self.assertEqual("protected_session", failure.exception.code)
        self.assertEqual(before, list(self.store.db.iterdump()))


if __name__ == "__main__":
    unittest.main()
