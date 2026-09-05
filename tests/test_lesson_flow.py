"""Guided discovery uses authored content and never advances WaniKani itself."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import unittest

from test_backend import EngineFixture, Engine, Store, Synchronizer, NOW, UserError
from wanikani import lesson_flow


class LessonFlowTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sequence = 0

    def move(self, action, view=None, rid=None):
        view = view or self.engine.session_view()
        self.sequence += 1
        return self.engine.command(rid or "navigation-" + str(self.sequence), "lesson_navigate",
            {"action": action, "session_id": view["id"], "revision": view["revision"]})

    def lesson(self, sid, kind="vocabulary", context=False, audio=False, image=False):
        source = {"radical": 1, "kanji": 6, "vocabulary": 7, "kana_vocabulary": 5}[kind]
        subject = copy.deepcopy(self.store.subject(source))
        subject["id"] = sid
        subject["data"].update(component_subject_ids=[], amalgamation_subject_ids=[],
            visually_similar_subject_ids=[], context_sentences=[{"ja": "独自の例。", "en": "An authored example."}] if context else [])
        if audio:
            subject["data"]["pronunciation_audios"] = [{"url": "https://fixture.invalid/voice.mp3", "metadata": {"voice_actor_id": 1}}]
        if image:
            subject["data"].update(characters=None, character_images=[{"url": "https://fixture.invalid/radical.png"}])
            media = self.path.parent / "media"
            media.mkdir(exist_ok=True)
            self.image = media / "authored-radical.png"
            self.image.write_bytes(b"Authored byte fixture; native decoding is tested separately")
            self.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)",
                ("https://fixture.invalid/radical.png", str(self.image), self.image.stat().st_size, NOW))
        self.store.put(subject)
        assignment = copy.deepcopy(self.store.related("assignment", 6))
        assignment["id"] = sid + 10000
        assignment["data"].update(subject_id=sid, subject_type=kind)
        self.store.put(assignment)

    def test_subject_types_have_only_applicable_bounded_sections(self):
        for sid, kind, context, audio, expected in (
                (31, "radical", False, False, ["Meaning"]),
                (32, "radical", True, False, ["Meaning", "Context"]),
                (33, "kanji", False, False, ["Meaning", "Reading"]),
                (34, "vocabulary", True, True, ["Meaning", "Reading & audio", "Context"]),
                (35, "kana_vocabulary", False, False, ["Meaning"]),
                (36, "kana_vocabulary", True, True, ["Meaning", "Sound", "Context"])):
            with self.subTest(kind=kind, context=context, audio=audio):
                self.lesson(sid, kind, context, audio)
                self.assertEqual(expected, [item["label"] for item in lesson_flow.sections(self.engine.details(sid))])
        self.assertEqual([{"id": "meaning", "label": "Meaning"}], lesson_flow.sections({
            "type": "radical", "sentences": [{"ja": " ", "en": ""}, None], "related": [None, {"id": True}]}))

    def test_next_and_back_preserve_subject_order_and_section_coordinate(self):
        self.lesson(31, context=True)
        view = self.engine.start("lessons", subjects=[31, 6])
        self.assertEqual("meaning", view["lesson_flow"]["step"])
        self.assertFalse(view["lesson_flow"]["can_back"])
        view = self.move("next")
        self.assertEqual((31, "reading", 2), (view["subject"]["id"], view["lesson_flow"]["step"], view["lesson_flow"]["position"]))
        self.assertEqual("Next: Context", view["lesson_flow"]["next_label"])
        self.assertEqual("context", self.move("next")["lesson_flow"]["step"])
        self.assertEqual((6, "meaning"), ((view := self.move("next"))["subject"]["id"], view["lesson_flow"]["step"]))
        view = self.move("back")
        self.assertEqual((31, "context"), (view["subject"]["id"], view["lesson_flow"]["step"]))
        self.assertEqual("reading", self.move("back")["lesson_flow"]["step"])
        self.assertEqual("meaning", self.move("back")["lesson_flow"]["step"])
        self.assertEqual([31, 6], [row["subject_id"] for row in self.store.session()["queue"]])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM events"))

    def test_quiz_is_explicit_and_submits_only_after_final_answer_acknowledgment(self):
        self.engine.start("lessons", subjects=[6])
        with self.assertRaises(UserError) as early:
            self.move("quiz")
        self.assertEqual("invalid_step", early.exception.code)
        final = self.move("next")
        self.assertTrue(final["lesson_flow"]["can_quiz"])
        self.assertFalse(final["lesson_flow"]["can_next"])
        before = self.store.session()
        with self.assertRaises(UserError):
            self.move("next")
        self.assertEqual(before, self.store.session())
        view = self.move("quiz")
        self.assertEqual("question", view["phase"])
        self.assertIsNone(view["lesson_flow"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.engine.answer(self.correct_answer(view))
        view = self.engine.advance()
        self.assertEqual("reading", view["part"])
        view = self.engine.answer(self.correct_answer(view))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual("complete", self.engine.advance()["phase"])
        self.assertEqual([("lesson", "pending")], [tuple(row) for row in self.store.rows("SELECT kind,state FROM outbox")])

    def test_restart_and_mode_switch_restore_the_exact_step(self):
        self.lesson(31, context=True)
        original = self.engine.start("lessons", subjects=[6, 31])
        self.move("next")
        self.move("next")
        self.move("next")
        expected = self.store.session()
        self.engine.start("reviews", 1)
        self.engine.draft("review draft stays separate")
        review = self.store.session()
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        resumed = self.engine.start("lessons", subjects=[7])
        self.assertEqual((original["id"], 31, "reading"), (resumed["id"], resumed["subject"]["id"], resumed["lesson_flow"]["step"]))
        self.assertEqual(expected["queue"], self.store.session()["queue"])
        self.assertEqual(review, self.store.session(review["id"]))

    def test_legacy_records_project_meaning_without_migration_and_legacy_navigation_still_works(self):
        self.engine.start("lessons", subjects=[6, 7])
        saved = self.store.session()
        del saved["lesson_step"]
        self.store.save_session(saved)
        before = list(self.store.db.iterdump())
        self.assertEqual("meaning", self.engine.session_view()["lesson_flow"]["step"])
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(1, self.engine.lesson_next()["lesson_index"])
        self.assertEqual("question", self.engine.lesson_next()["phase"])

    def test_invalid_and_stale_commands_cannot_change_any_saved_state(self):
        view = self.engine.start("lessons", subjects=[6])
        valid = {"action": "next", "session_id": view["id"], "revision": view["revision"]}
        invalid = [{}, {**valid, "action": "jump"}, {**valid, "step": "context"}, {**valid, "revision": True},
            {**valid, "revision": -1}, {**valid, "revision": str(view["revision"])}, {**valid, "session_id": 2},
            {**valid, "session_id": "other"}, {**valid, "revision": view["revision"] + 1}]
        for index, values in enumerate(invalid):
            before = list(self.store.db.iterdump())
            with self.subTest(values=values), self.assertRaises(UserError):
                self.engine.command("invalid-" + str(index), "lesson_navigate", values)
            self.assertEqual(before, list(self.store.db.iterdump()))
        self.move("next")
        before = self.store.session()
        with self.assertRaises(UserError) as stale:
            self.move("quiz", view)
        self.assertEqual("stale_session", stale.exception.code)
        self.assertEqual(before, self.store.session())

    def test_navigation_cannot_operate_reviews_practice_or_finished_discovery(self):
        for mode in ("reviews", "practice"):
            view = self.engine.start(mode, 1, [2] if mode == "practice" else None)
            before = self.store.session()
            with self.subTest(mode=mode), self.assertRaises(UserError) as invalid:
                self.move("next", view)
            self.assertEqual("invalid_mode", invalid.exception.code)
            self.assertEqual(before, self.store.session())
        self.engine.start("lessons", subjects=[6])
        self.move("next")
        view = self.move("quiz")
        with self.assertRaises(UserError):
            self.move("back", view)

    def test_duplicate_id_replays_one_durable_transition(self):
        view = self.engine.start("lessons", subjects=[6])
        first = self.move("next", view, "one-transition")
        expected = self.store.session()
        again = self.move("quiz", view, "one-transition")
        self.assertEqual(first, again)
        self.assertEqual(expected, self.store.session())
        self.assertEqual(1, self.store.rows("SELECT COUNT(*) FROM commands WHERE id='one-transition'")[0][0])

    def test_refresh_removes_optional_context_without_automatically_entering_quiz(self):
        self.lesson(31, context=True)
        self.engine.start("lessons", subjects=[31])
        self.move("next")
        self.move("next", rid="context-transition")
        saved = self.store.session()
        original_journal = self.store.rows("SELECT body FROM commands WHERE id='context-transition'")[0][0]
        subject = self.store.subject(31)
        subject["data"]["context_sentences"] = []
        self.store.put(subject)
        view = self.engine.session_view()
        self.assertEqual("reading", view["lesson_flow"]["step"])
        self.assertTrue(view["lesson_flow"]["adjusted"])
        self.assertTrue(view["lesson_flow"]["can_quiz"])
        replay = self.move("next", rid="context-transition")
        self.assertEqual(view["lesson_flow"], replay["lesson_flow"])
        self.assertEqual(saved, self.store.session())
        self.assertEqual(original_journal, self.store.rows("SELECT body FROM commands WHERE id='context-transition'")[0][0])

    def test_lost_current_image_can_go_back_but_cannot_move_forward(self):
        self.lesson(31, kind="radical", image=True)
        self.engine.start("lessons", subjects=[6, 31])
        self.move("next")
        self.move("next")
        self.image.unlink()
        view = self.engine.session_view()
        self.assertIsNone(view["subject"])
        self.assertTrue(view["lesson_flow"]["can_back"])
        self.assertFalse(view["lesson_flow"]["can_next"])
        self.assertFalse(view["lesson_flow"]["can_quiz"])
        before = self.store.session()
        with self.assertRaises(UserError):
            self.move("quiz")
        self.assertEqual(before, self.store.session())
        view = self.move("back")
        self.assertEqual((6, "reading"), (view["subject"]["id"], view["lesson_flow"]["step"]))

    def test_access_change_restricts_projection_and_replay_but_preserves_coordinate(self):
        self.lesson(31, context=True)
        subject = self.store.subject(31)
        subject["data"]["level"] = 50
        self.store.put(subject)
        self.engine.start("lessons", subjects=[6, 31])
        self.move("next")
        self.move("next", rid="level-fifty")
        before = self.store.session()
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 3
        self.store.set("user", user)
        for view in (self.engine.session_view(), self.move("next", rid="level-fifty")):
            self.assertIsNone(view["subject"])
            self.assertTrue(view["restricted"])
            self.assertFalse(view["lesson_flow"]["can_next"])
            self.assertTrue(view["lesson_flow"]["can_back"])
        self.assertEqual(before, self.store.session())
        self.assertEqual(6, self.move("back")["subject"]["id"])

    def test_newly_protected_relationships_do_not_create_an_empty_context_step(self):
        self.engine.start("lessons", subjects=[8])
        self.assertEqual("context", self.engine.session_view()["lesson_flow"]["steps"][-1]["id"])
        self.engine.start("practice", 1, [2])
        self.engine.start("reviews", 1)
        saved = self.store.session()
        saved["queue"][0]["subject_id"] = 2
        self.store.save_session(saved)
        self.engine.start("lessons")
        view = self.engine.session_view()
        self.assertEqual([], view["subject"]["components"])
        self.assertEqual(["meaning", "reading"], [step["id"] for step in view["lesson_flow"]["steps"]])

    def test_vacation_clock_and_reset_do_not_discard_saved_discovery(self):
        self.engine.start("lessons", subjects=[6])
        for reason in ("vacation", "clock"):
            user = self.store.get("user")
            user["data"]["current_vacation_started_at"] = "2026-01-01T00:00:00Z" if reason == "vacation" else None
            self.store.set("user", user)
            self.engine.clock_untrusted = reason == "clock"
            before = self.store.session()
            with self.subTest(reason=reason), self.assertRaises(UserError):
                self.move("next")
            self.assertEqual(before, self.store.session())
        self.engine.clock_untrusted = False
        before = self.engine.session_view()
        Synchronizer(self.engine, None, self.path.parent / "media")._invalidate_reset({"data": {"target_level": 1}})
        with self.assertRaises(UserError):
            self.move("next", before)
        self.assertEqual("Account reset", self.store.session()["invalidated"])
        self.assertEqual("complete", self.store.session()["phase"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_actual_process_exit_preserves_atomic_step_and_command_acknowledgment(self):
        self.engine.start("lessons", subjects=[6])
        code = '''
import os, sys
from pathlib import Path
from wanikani.store import Store
from wanikani.engine import Engine
store = Store(Path(sys.argv[1])); engine = Engine(store, clock=lambda: int(sys.argv[3]))
view = engine.session_view()
original = store.execute
def execute(sql, args=()):
    if sys.argv[2] == 'before' and sql.startswith('INSERT INTO commands'):
        os._exit(23)
    return original(sql, args)
store.execute = execute
engine.command('crash-step', 'lesson_navigate', {'action':'next','session_id':view['id'],'revision':view['revision']})
os._exit(24)
'''
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
        before = self.store.session()
        process = subprocess.run([sys.executable, "-c", code, str(self.path), "before", str(NOW)],
            env=environment, capture_output=True, timeout=10)
        self.assertEqual(23, process.returncode, process.stderr)
        self.assertEqual(before, self.store.session())
        self.assertEqual([], self.store.rows("SELECT * FROM commands WHERE id='crash-step'"))
        process = subprocess.run([sys.executable, "-c", code, str(self.path), "after", str(NOW)],
            env=environment, capture_output=True, timeout=10)
        self.assertEqual(24, process.returncode, process.stderr)
        durable = self.store.session()
        self.assertEqual("reading", durable["lesson_step"])
        replay = self.move("next", self.engine.session_view(), rid="crash-step")
        self.assertEqual("reading", replay["lesson_flow"]["step"])
        self.assertEqual(durable, self.store.session())
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))


if __name__ == "__main__":
    unittest.main()
