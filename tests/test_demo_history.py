"""Fresh authored demo history and strictly inert reseeding of saved demo work."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_backend import Engine, Store, NOW, stamp
from wanikani.demo import populate
from wanikani import level_history


DAY = 86400


class DemoHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "authored-demo.db")
        self.guard = patch("socket.create_connection", side_effect=AssertionError("Demo must stay local"))
        self.guard.start()

    def tearDown(self):
        self.guard.stop()
        self.store.close()
        self.directory.cleanup()

    def test_fresh_demo_has_six_distinct_authored_visits_and_current_level_three(self):
        engine = Engine(self.store, demo=True, clock=lambda: NOW)
        report = level_history.catalogue(engine, offset=0, limit=12)
        self.assertEqual("Authored demo level progressions", report["source"])
        self.assertEqual(("available", 6, False, None),
            (report["status"], report["total"], report["has_more"], report["next_offset"]))
        self.assertTrue(report["cache_complete"])
        self.assertFalse(report["history_complete"])
        self.assertFalse(report["partial"])
        self.assertEqual(3, engine.user()["level"])
        self.assertEqual(stamp(NOW), self.store.get("cursor_level_progressions"))
        self.assertEqual([3, 2, 1, 3, 2, 1], [item["level"] for item in report["items"]])
        self.assertEqual(["Recorded visit 2"] * 3 + ["Recorded visit 1"] * 3,
            [item["attempt_label"] for item in report["items"]])
        self.assertEqual(["in_progress", "passed", "passed", "abandoned", "passed", "passed"],
            [item["state"] for item in report["items"]])
        self.assertEqual([4, 7, 7, 4, 10, 8], [item["elapsed_days"] for item in report["items"]])
        self.assertEqual(["now", "passed", "passed", "abandoned", "passed", "passed"],
            [item["elapsed_to"] for item in report["items"]])
        self.assertTrue(all(item["date_status"] == "known" for item in report["items"]))
        self.assertTrue(all(item["completed_at"] is None for item in report["items"]))
        self.assertEqual(stamp(NOW - 18 * DAY), report["items"][3]["abandoned_at"])
        self.assertTrue(all(item["abandoned_at"] is None for index, item in enumerate(report["items"]) if index != 3))
        self.assertEqual([], self.store.rows("SELECT id FROM sessions"))
        self.assertEqual([], self.store.rows("SELECT id FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT id FROM events"))

    def test_populate_is_byte_for_byte_inert_after_saved_answers_and_lesson_draft(self):
        engine = Engine(self.store, demo=True, clock=lambda: NOW)
        engine.start("reviews", 1)
        feedback = engine.answer("an authored incorrect answer")
        self.assertFalse(feedback["feedback"]["correct"])
        lesson = engine.start("lessons", 1)
        while lesson["phase"] == "lesson":
            lesson = engine.lesson_next()
        engine.draft("An unfinished local draft")
        self.assertEqual("An unfinished local draft", self.store.session()["draft"])
        self.store.set("settings", {"strict_meanings": True, "demo_offline": True})
        # Include nonstandard authored history to prove reseeding never repairs
        # or replaces an existing learner's stored records behind their back.
        history = self.store.all("level_progression")[0]
        history["data"]["created_at"] = "retained authored marker"
        self.store.put(history)
        before = self.store.db.serialize()
        changes = self.store.db.total_changes
        populate(self.store, NOW + 20 * DAY)
        self.assertEqual(before, self.store.db.serialize())
        self.assertEqual(changes, self.store.db.total_changes)
        self.assertEqual(stamp(NOW), self.store.get("cursor_level_progressions"))

    def test_old_seeded_demo_without_history_is_not_migrated_even_on_engine_reopen(self):
        Engine(self.store, demo=True, clock=lambda: NOW)
        self.store.execute("DELETE FROM resources WHERE kind='level_progression'")
        self.store.execute("DELETE FROM meta WHERE key='cursor_level_progressions'")
        before = self.store.db.serialize()
        changes = self.store.db.total_changes
        Engine(self.store, demo=True, clock=lambda: NOW + DAY)
        self.assertEqual(before, self.store.db.serialize())
        self.assertEqual(changes, self.store.db.total_changes)
        self.assertEqual([], self.store.all("level_progression"))

    def test_interrupted_fresh_population_rolls_back_history_and_seed_marker_together(self):
        original = self.store.put
        def interrupted(resource):
            original(resource)
            if resource["object"] == "level_progression" and resource["id"] == 305:
                raise RuntimeError("Authored interruption during history seed")
        before = self.store.db.serialize()
        with patch.object(self.store, "put", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "Authored interruption"):
                populate(self.store, NOW)
        self.assertEqual(before, self.store.db.serialize())
        self.assertIsNone(self.store.get("demo_seeded"))
        self.assertIsNone(self.store.get("cursor_level_progressions"))
        populate(self.store, NOW)
        self.assertEqual(6, len(self.store.all("level_progression")))


if __name__ == "__main__":
    unittest.main()
