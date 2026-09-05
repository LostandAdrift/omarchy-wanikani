"""Explicit passage practice previews with authored cache/session fixtures."""
import copy
import json
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_reading_trail as authored
from wanikani import practice, trail, trail_practice
from wanikani.common import UserError, stamp


class TrailPracticeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.ReadingTrailTests(); self.fixture.setUp()
        self.engine, self.store = self.fixture.engine, self.fixture.store
        self.store.set("account_id", "demo")

    def tearDown(self):
        self.fixture.tearDown()

    def preview(self, text="山と火山。ありがとう", ids=None):
        return trail_practice.preview(self.engine, text, [2, 8, 5] if ids is None else ids)

    def protect(self, sid, done=False, mode="reviews"):
        session = {"id": str(uuid4()), "mode": mode, "phase": "question", "index": 0, "completed": 0,
            "part": "meaning", "lesson_index": 0, "draft": "PRIVATE ANSWER", "feedback": None,
            "queue": [{"subject_id": sid, "done": done, "parts": {"meaning": False},
                "errors": {"meaning": 0, "reading": 0}}]}
        self.store.save_session(session)
        return session

    def test_exact_passage_selected_order_neutral_fields_and_absent_saved_practice(self):
        text = '  山と火山🌊\nありがとう。<b>&\t  '
        result = self.preview(text, [5, 8, 2])
        self.assertEqual(text, result["text"])
        self.assertEqual([5, 8, 2], result["subject_ids"])
        self.assertEqual([5, 8, 2], [item["id"] for item in result["items"]])
        self.assertEqual({"id", "type", "level", "characters", "state", "ready", "reason"}, set(result["items"][0]))
        self.assertEqual(3, result["ready_count"]); self.assertTrue(result["can_start"])
        self.assertEqual("preview_only", result["effect"]); self.assertEqual("ungraded_practice", result["scope"])
        self.assertEqual(self.store.get("session_epoch"), result["data_epoch"])
        self.assertEqual({"present": False, "valid": True, "completed": 0, "total": 0, "revision": None}, result["saved_practice"])
        self.assertFalse(result["requires_practice_choice"])
        for private in ("meaning", "readings", "mnemonic", "audio", "mountain", "volcano", "thank you"):
            self.assertNotIn(private, json.dumps(result, ensure_ascii=False))

    def test_strict_unique_selection_does_not_coerce_clamp_or_drop_ids(self):
        for selected in ([], [True], [0], [-1], ["2"], [2, 2], list(range(1, 22)), [9007199254740992], {}, None):
            with self.subTest(ids=selected), self.assertRaises(UserError):
                trail_practice.preview(self.engine, "山", selected)
        for text in (None, True, "", "山" * 257, "𠮷" * 257, "\ud800"):
            with self.subTest(text=repr(text)[:20]), self.assertRaises(UserError):
                trail_practice.preview(self.engine, text, [2])
        for selected in ([2, 3], [1], [99999]):
            with self.subTest(ids=selected), self.assertRaises(UserError) as caught:
                self.preview("山", selected)
            self.assertEqual("trail_changed", caught.exception.code)

    def test_supplementary_and_combining_characters_match_exactly(self):
        self.fixture.add(1001, "𠮷", "kanji")
        self.fixture.add(1002, "か", "kana_vocabulary")
        self.assertTrue(self.preview("𠮷" * 256, [1001])["can_start"])
        with self.assertRaises(UserError): self.preview("か\u3099", [1002])
        self.fixture.add(1003, "か\u3099", "kana_vocabulary")
        self.assertEqual("か\u3099", self.preview("か\u3099", [1003])["text"])

    def test_partial_trail_permits_only_the_current_returned_matches(self):
        with patch.object(trail, "MAX_MATCHES", 1):
            result = self.preview("山と火山", [2])
            self.assertTrue(result["trail_truncated"])
            self.assertTrue(result["can_start"])
            with self.assertRaises(UserError): self.preview("山と火山", [8])

    def test_paused_subjects_and_aliases_are_disabled_without_loading_answers(self):
        self.fixture.add(1001, "山", "vocabulary")
        self.protect(2, mode="lessons")
        with patch.object(self.engine, "ensure_study_content", side_effect=AssertionError("No protected answers")):
            result = self.preview("山", [2, 1001])
        self.assertEqual(0, result["ready_count"]); self.assertFalse(result["can_start"])
        for item in result["items"]:
            self.assertEqual("protected_study", item["reason"])
            self.assertEqual("Paused graded work", item["state"])
        self.assertEqual("PRIVATE ANSWER", self.store.session()["draft"])

    def test_done_must_be_literal_true_and_all_saved_graded_modes_are_checked(self):
        for done in (1, "false", False):
            self.store.execute("DELETE FROM sessions")
            self.protect(2, done=done)
            with self.subTest(done=done): self.assertFalse(self.preview("山", [2])["can_start"])
        self.store.execute("DELETE FROM sessions"); self.protect(2, done=True)
        self.assertTrue(self.preview("山", [2])["can_start"])
        self.protect(3, mode="lessons")
        self.assertFalse(self.preview("川", [3])["can_start"])

    def test_protected_alias_outside_the_trail_scan_still_withholds_word(self):
        self.fixture.add(1001, "山", "vocabulary")
        self.protect(1001)
        with patch.object(trail, "MAX_SUBJECTS", 3):
            value = self.preview("山", [2])
        self.assertTrue(value["trail_truncated"])
        self.assertFalse(value["can_start"])

    def test_unreadable_or_missing_graded_metadata_fails_closed(self):
        session = self.protect(2)
        for queue in (None, [{"subject_id": "2", "done": False}], [{"subject_id": 99999, "done": False}]):
            session["queue"] = queue; self.store.save_session(session)
            with self.subTest(queue=queue), self.assertRaises(UserError) as caught:
                self.preview()
            self.assertEqual("protected_study", caught.exception.code)

    def test_stale_matches_hidden_access_reset_and_duplicate_identity_are_rechecked(self):
        self.assertTrue(self.preview("山", [2])["can_start"])
        original = copy.deepcopy(self.store.subject(2))
        for change in ({"hidden_at": "hidden"}, {"level": 61}, {"level": "1"}, {"characters": "岳"}):
            subject = copy.deepcopy(original); subject["data"].update(change); self.store.put(subject)
            with self.subTest(change=change), self.assertRaises(UserError): self.preview("山", [2])
        self.store.put(original)
        assignment = self.store.related("assignment", 2); assignment["data"]["hidden"] = True; self.store.put(assignment)
        with self.assertRaises(UserError): self.preview("山", [2])
        self.store.execute("DELETE FROM resources WHERE kind='assignment' AND json_extract(body,'$.data.subject_id')=2")
        self.assertEqual("Not started", self.preview("山", [2])["items"][0]["state"])
        alias = copy.deepcopy(original); alias["object"] = "vocabulary"
        self.store.execute("INSERT INTO resources VALUES(?,?,?)", ("vocabulary", "2", json.dumps(alias)))
        with self.assertRaises(UserError): self.preview("山", [2])

    def test_invalid_cached_answers_disable_card_and_never_echo_the_error(self):
        subject = self.store.subject(2); subject["data"]["meanings"] = [{"meaning": "PRIVATE MALFORMED ANSWER", "accepted_answer": "true"}]
        self.store.put(subject)
        value = self.preview("山", [2])
        self.assertFalse(value["can_start"])
        self.assertEqual("content_unavailable", value["items"][0]["reason"])
        self.assertNotIn("PRIVATE", json.dumps(value))

    def test_pending_completed_work_and_missing_optional_audio_stay_practiceable(self):
        for sid, state, kind in ((2, "pending", "review"), (8, "uncertain", "lesson")):
            self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (str(sid), kind, sid, state,
                "{}", stamp(authored.NOW), "PRIVATE RECOVERY NOTE"))
        before = [tuple(row) for row in self.store.rows("SELECT * FROM outbox")]
        result = self.preview("山と火山", [2, 8])
        self.assertTrue(result["can_start"])
        self.assertEqual(["Waiting to sync", "Needs attention"], [item["state"] for item in result["items"]])
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM outbox")])

    def test_existing_practice_summary_preserves_draft_and_requires_explicit_choice(self):
        session = self.engine.start("practice", 2, [2, 3], replace_practice=True)
        self.engine.draft("PRIVATE UNFINISHED ANSWER")
        before = list(self.store.db.iterdump())
        result = self.preview()
        saved = result["saved_practice"]
        self.assertTrue(saved["present"]); self.assertTrue(saved["valid"])
        self.assertEqual(0, saved["completed"]); self.assertEqual(2, saved["total"])
        self.assertEqual(self.store.session(session["id"])["revision"], saved["revision"])
        self.assertTrue(result["requires_practice_choice"]); self.assertTrue(result["can_start"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn(session["id"], json.dumps(saved))
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_malformed_saved_practice_is_neutral_and_cannot_be_silently_replaced(self):
        self.store.set("practice_session", "PRIVATE LOST REFERENCE")
        result = self.preview()
        self.assertEqual({"present": True, "valid": False, "completed": None, "total": None, "revision": None}, result["saved_practice"])
        self.assertFalse(result["can_start"]); self.assertNotIn("PRIVATE", json.dumps(result))
        session = self.engine.start("practice", 1, [2], replace_practice=True)
        raw = self.store.session(session["id"]); raw["completed"] = True; self.store.save_session(raw)
        self.assertFalse(self.preview()["saved_practice"]["valid"])

    def test_completed_practice_does_not_require_a_replacement_choice(self):
        view = self.engine.start("practice", 1, [5], replace_practice=True)
        self.engine.answer(view["subject"]["meanings"][0]); self.engine.advance()
        result = self.preview()
        self.assertFalse(result["requires_practice_choice"])
        self.assertIsNone(result["saved_practice"]["revision"])

    def test_account_mismatch_and_arbitrary_epoch_are_not_previewed(self):
        self.store.set("account_id", "another-account")
        with self.assertRaises(UserError): self.preview()
        self.store.set("account_id", "demo"); self.store.set("session_epoch", "PRIVATE EPOCH")
        with self.assertRaises(UserError) as caught: self.preview()
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_preview_never_starts_or_writes_and_does_not_hydrate_subject_details(self):
        before = list(self.store.db.iterdump())
        with patch.object(self.engine, "start", side_effect=AssertionError("Preview cannot start")), \
                patch.object(self.engine, "details", side_effect=AssertionError("No full detail projections")):
            self.assertTrue(self.preview()["can_start"])
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_generic_explicit_practice_policy_differs_from_guarded_trail_preview(self):
        self.protect(2)
        self.assertFalse(self.preview("山", [2])["can_start"])
        self.assertEqual([2], practice.validate_selection(self.engine, [2]))
        view = self.engine.start("practice", 1, [2], replace_practice=True)
        self.assertEqual(2, view["subject"]["id"])
        self.assertEqual([], self.store.rows("SELECT 1 FROM outbox"))

    def test_internal_guard_rechecks_protection_aliases_access_content_and_no_writes(self):
        self.fixture.add(1001, "山", "vocabulary")
        before = list(self.store.db.iterdump())
        self.assertEqual([2, 8], trail_practice.guard_ids(self.engine, [2, 8]))
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.protect(2)
        for selected in ([2], [1001]):
            with self.subTest(ids=selected), self.assertRaises(UserError) as caught:
                trail_practice.guard_ids(self.engine, selected)
            self.assertEqual("protected_study", caught.exception.code)
        hidden = self.store.subject(8); hidden["data"]["hidden_at"] = "hidden"; self.store.put(hidden)
        with self.assertRaises(UserError): trail_practice.guard_ids(self.engine, [8])
        broken = self.store.subject(5); broken["data"]["meanings"] = []; self.store.put(broken)
        with self.assertRaises(UserError): trail_practice.guard_ids(self.engine, [5])
        for selected in ([], [True], [2, 2], [1]):
            with self.subTest(ids=selected), self.assertRaises(UserError): trail_practice.guard_ids(self.engine, selected)

    def test_account_change_cannot_interleave_match_and_content_validation(self):
        entered, attempted, changed = [threading.Event() for _ in range(3)]
        original = trail.reading_trail; values = []; errors = []
        def matching(*args):
            entered.set(); self.assertTrue(attempted.wait(2)); self.assertFalse(changed.wait(.05))
            return original(*args)
        def read():
            try: values.append(self.preview())
            except BaseException as error: errors.append(error)
        def change():
            entered.wait(2); attempted.set(); self.store.set("account_id", "changed"); changed.set()
        with patch.object(trail, "reading_trail", side_effect=matching):
            reader = threading.Thread(target=read); writer = threading.Thread(target=change)
            reader.start(); writer.start(); reader.join(3); writer.join(3)
        self.assertFalse(reader.is_alive()); self.assertFalse(writer.is_alive()); self.assertEqual([], errors)
        self.assertTrue(values[0]["can_start"]); self.assertTrue(changed.is_set())
        with self.assertRaises(UserError): self.preview()


if __name__ == "__main__":
    unittest.main()
