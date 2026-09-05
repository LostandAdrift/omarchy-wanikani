"""Study and session-switching regressions with authored fixtures only."""
import unittest
from pathlib import Path
from unittest.mock import patch

from test_backend import EngineFixture, Engine, Store, UserError, NOW, stamp


class StudyEdgesTests(EngineFixture, unittest.TestCase):
    def test_search_only_matches_subject_values_and_literal_selection(self):
        for query in ("accepted", "primary", "reading", "meaning", "onyomi", "%", "_", "\\"):
            with self.subTest(query=query):
                self.assertEqual([], self.engine.search(query))
        self.assertEqual([2], [item["id"] for item in self.engine.search("mountain")])
        self.assertEqual([4], [item["id"] for item in self.engine.search("みず")])
        self.assertEqual({2, 8}, {item["id"] for item in self.engine.search("山")})
        self.assertEqual([2], [item["id"] for item in self.engine.search("山が見えます。")])
        item = self.store.subject(16)
        item["data"]["meanings"] += [{"meaning": "100% effort_with_a_literal\\slash", "accepted_answer": True}]
        self.store.put(item)
        for query in ("%", "_", "\\"):
            self.assertEqual([16], [match["id"] for match in self.engine.search(query)])

    def restart(self, demo=False):
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, demo=demo, clock=lambda: NOW)

    def finish_view(self, view):
        while view["phase"] == "lesson":
            view = self.engine.lesson_next()
        while view["phase"] != "complete":
            self.engine.answer(self.correct_answer(view))
            view = self.engine.advance()
        return view

    def only_due(self, subject_id):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != subject_id:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)

    def image_radical(self):
        item = self.store.subject(1)
        item["data"]["characters"] = None
        item["data"]["character_images"] = [{"url": "https://example.invalid/authored-radical.svg"}]
        self.store.put(item)
        self.only_due(1)
        return item

    def cache_image(self, item):
        image = Path(self.temp.name) / "authored-radical.svg"
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><path d="M4 16H28" stroke="black"/></svg>')
        self.store.execute("INSERT INTO media VALUES(?,?,?,?)", (item["data"]["character_images"][0]["url"], str(image), image.stat().st_size, NOW))
        return image

    def test_all_subject_types_require_their_exact_parts(self):
        for subject_id, parts in ((1, ["meaning"]), (2, ["meaning", "reading"]), (4, ["meaning", "reading"]), (5, ["meaning"])):
            with self.subTest(subject_id=subject_id):
                view = self.engine.start("practice", 1, [subject_id])
                seen = []
                while view["phase"] != "complete":
                    seen.append(view["part"])
                    self.engine.answer(self.correct_answer(view))
                    self.assertEqual(0, self.engine.session_view()["completed"])
                    view = self.engine.advance()
                self.assertEqual(parts, seen)
                self.assertEqual(1, view["completed"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_image_only_radical_requires_real_cached_image(self):
        item = self.image_radical()
        with self.assertRaises(UserError) as failure:
            self.engine.start("reviews", 1)
        self.assertEqual("empty_queue", failure.exception.code)
        self.cache_image(item)
        view = self.engine.start("reviews", 1)
        self.assertEqual("", view["subject"]["characters"])
        self.assertEqual(1, len(view["subject"]["images"]))
        self.engine.answer("ground")
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual(1, self.engine.advance()["completed"])

    def test_evicted_image_retains_feedback_until_cache_restored(self):
        image = self.cache_image(self.image_radical())
        self.engine.start("reviews", 1)
        self.engine.answer("wrong")
        image.unlink()
        self.restart()
        view = self.engine.session_view()
        self.assertEqual("feedback", view["phase"])
        self.assertEqual(1, view["errors"])
        self.assertIsNone(view["subject"])
        self.assertIn("image is not cached", view["unavailable"])
        with self.assertRaises(UserError):
            self.engine.correct()
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.engine.correct()
        self.assertEqual(1, self.engine.advance()["completed"])

    def test_missing_accepted_meaning_cannot_enter_quiz(self):
        self.only_due(1)
        item = self.store.subject(1)
        item["data"]["meanings"][0]["accepted_answer"] = False
        self.store.put(item)
        with self.assertRaises(UserError):
            self.engine.start("reviews", 1)
        self.assertIsNone(self.store.session())

    def test_lesson_access_is_checked_for_visible_subject(self):
        self.engine.start("lessons", 3)
        view = self.engine.lesson_next()
        item = self.store.subject(view["subject"]["id"])
        item["data"]["hidden_at"] = stamp(NOW)
        self.store.put(item)
        with self.assertRaises(UserError) as failure:
            self.engine.lesson_next()
        self.assertEqual("access_restricted", failure.exception.code)
        self.assertEqual(1, self.store.session()["lesson_index"])
        self.assertTrue(self.engine.session_view()["restricted"])

    def test_current_correction_obeys_vacation_and_clock(self):
        self.engine.start("reviews", 1)
        self.engine.answer("wrong")
        self.engine.clock_untrusted = True
        with self.assertRaises(UserError):
            self.engine.correct()
        self.engine.clock_untrusted = False
        user = self.store.get("user")
        user["data"]["current_vacation_started_at"] = stamp(NOW)
        self.store.set("user", user)
        with self.assertRaises(UserError):
            self.engine.correct()
        self.assertEqual(1, self.engine.session_view()["errors"])

    def test_finish_group_after_first_five_preserves_errors_and_total(self):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["started_at"]:
                assignment["data"]["available_at"] = stamp(NOW - 1)
                self.store.put(assignment)
        view = self.engine.start("reviews", 12)
        while view["completed"] < 5:
            self.engine.answer(self.correct_answer(view))
            view = self.engine.advance()
        self.engine.answer("wrong")
        self.engine.finish()
        self.restart()
        view = self.engine.session_view()
        self.assertEqual(10, view["total"])
        self.assertTrue(view["finishing"])
        self.assertEqual(1, view["errors"])
        view = self.engine.advance()
        view = self.finish_view(view)
        self.assertEqual((10, 10, 1), (view["completed"], view["total"], view["errors"]))
        self.assertEqual(10, len(self.store.rows("SELECT * FROM outbox")))

    def test_practice_switch_preserves_graded_feedback_and_draft(self):
        graded = self.engine.start("reviews", 1)
        self.engine.answer("my incorrect answer")
        practice = self.engine.start("practice", 1, [3])
        self.assertEqual("practice", practice["mode"])
        self.assertTrue(self.engine.snapshot()["paused_graded"])
        self.engine.draft("practice draft")
        self.restart()
        resumed = self.engine.start("resume")
        self.assertFalse(self.engine.snapshot()["paused_graded"])
        self.assertEqual(graded["id"], resumed["id"])
        self.assertEqual("feedback", resumed["phase"])
        self.assertEqual("my incorrect answer", resumed["draft"])
        self.assertEqual(1, resumed["errors"])
        resumed_practice = self.engine.start("practice", 1, [4])
        self.assertEqual(practice["id"], resumed_practice["id"])
        self.assertEqual("practice draft", resumed_practice["draft"])
        self.finish_view(resumed_practice)
        self.assertTrue(self.engine.snapshot()["paused_graded"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual(graded["id"], self.engine.start("reviews")["id"])

    def test_vacation_practice_is_available_with_paused_graded_session(self):
        graded = self.engine.start("lessons", 2)
        self.engine.lesson_next()
        user = self.store.get("user")
        user["data"]["current_vacation_started_at"] = stamp(NOW)
        self.store.set("user", user)
        practice = self.engine.start("practice", 1, [1])
        self.finish_view(practice)
        resumed = self.engine.start("resume")
        self.assertEqual(graded["id"], resumed["id"])
        self.assertEqual(1, resumed["lesson_index"])
        with self.assertRaises(UserError):
            self.engine.lesson_next()

    def test_failed_practice_start_retains_active_graded_session(self):
        graded = self.engine.start("reviews", 1)
        self.engine.draft("saved graded draft")
        with self.assertRaises(UserError):
            self.engine.start("practice", 1, [99999])
        self.assertEqual(graded["id"], self.engine.session_view()["id"])
        self.assertEqual("saved graded draft", self.engine.session_view()["draft"])

    def test_offline_demo_reconnect_confirms_once_without_new_cycle(self):
        self.engine = Engine(self.store, demo=True, clock=lambda: NOW)
        self.engine.command("go-offline", "settings", {"demo_offline": True})
        view = self.finish_view(self.engine.start("reviews", 1))
        operation = self.store.rows("SELECT * FROM outbox")[0]
        subject_id = operation["subject_id"]
        original_stage = self.store.related("assignment", subject_id)["data"]["srs_stage"]
        self.restart(demo=True)
        self.assertEqual("offline", self.engine.status)
        self.assertEqual(1, self.engine.snapshot()["pending"])
        self.finish_view(self.engine.start("practice", 1, [subject_id]))
        self.assertEqual(1, len(self.store.rows("SELECT * FROM outbox")))
        self.engine.command("go-online", "settings", {"demo_offline": False})
        self.engine.command("go-online", "settings", {"demo_offline": False})
        self.assertEqual("confirmed", self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual(original_stage + 1, self.store.related("assignment", subject_id)["data"]["srs_stage"])
        self.assertEqual(0, self.engine.snapshot()["pending"])

    def test_switch_effect_and_command_reply_rollback_together(self):
        graded = self.engine.start("reviews", 1)
        original = self.store.execute

        def fail(sql, args=()):
            if sql.startswith("INSERT INTO commands"):
                raise OSError("Simulated durable reply failure")
            return original(sql, args)

        with patch.object(self.store, "execute", side_effect=fail):
            with self.assertRaises(OSError):
                self.engine.command("switch", "start", {"mode": "practice", "subjects": [1]})
        self.assertEqual(graded["id"], self.engine.session_view()["id"])
        self.assertIsNone(self.store.get("practice_session"))
        self.assertEqual(1, self.store.rows("SELECT COUNT(*) FROM sessions")[0][0])
