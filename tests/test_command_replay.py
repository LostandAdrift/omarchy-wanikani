"""A duplicate acknowledgment respects current access without another effect."""
import copy
import json
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW, UserError, stamp


class CommandReplayTests(EngineFixture, unittest.TestCase):
    def start_answer(self, subject_id=2):
        self.engine.start("practice", 1, [subject_id])
        return self.engine.command("authored-answer", "answer", {"text": "wrong fixture"})

    def cached_body(self, rid="authored-answer"):
        return self.store.rows("SELECT body FROM commands WHERE id=?", (rid,))[0][0]

    def duplicate(self, method="answer"):
        with patch.object(self.engine, "answer", side_effect=AssertionError("Regraded duplicate")), \
                patch.object(self.engine, "draft", side_effect=AssertionError("Reused ID executed a different method")):
            return self.engine.command("authored-answer", method, {"text": "ignored input"})

    def test_unchanged_duplicate_keeps_exact_result_and_never_regrades(self):
        first = self.start_answer()
        before = list(self.store.db.iterdump())
        self.assertEqual(first, self.duplicate())
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_expired_subscription_redacts_subject_and_answer_text_without_erasing_record(self):
        subject = self.store.subject(2)
        subject["data"]["level"] = 4
        self.store.put(subject)
        self.store.set("material_draft_2", {"meaning_synonyms": ["AUTHORED_PRIVATE_ALIAS"],
            "meaning_note": "AUTHORED_OLD_NOTE", "reading_note": ""})
        original = self.start_answer()
        user = self.store.get("user")
        user["data"]["subscription"].update(type="recurring", max_level_granted=60, period_ends_at=stamp(NOW - 1))
        self.store.set("user", user)
        before = list(self.store.db.iterdump())
        replayed = self.duplicate("draft")  # The claimed new method cannot bypass projection.
        self.assertEqual(3, self.engine.max_level())
        self.assertTrue(replayed["restricted"])
        self.assertIsNone(replayed["subject"])
        self.assertEqual("", replayed["draft"])
        self.assertEqual("", replayed["feedback"]["answer"])
        self.assertEqual([], replayed["feedback"]["accepted"])
        self.assertNotIn("AUTHORED_", json.dumps(replayed))
        for field in ("id", "phase", "part", "revision", "session_epoch", "errors", "completed", "overrides"):
            self.assertEqual(original[field], replayed[field])
        for field in ("kind", "correct", "retry", "corrected"):
            self.assertEqual(original["feedback"][field], replayed["feedback"][field])
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertIn("AUTHORED_OLD_NOTE", self.cached_body())
        self.assertEqual("wrong fixture", self.store.session()["draft"])

    def test_hidden_missing_and_malformed_access_metadata_all_restrict_replay(self):
        self.start_answer()
        original = self.store.subject(2)
        variations = [("hidden_at", False), ("hidden_at", stamp(NOW)),
            *(('level', value) for value in (None, True, "2", 2.0, 0, -1, 61))]
        for field, value in variations:
            with self.subTest(field=field, value=value):
                subject = copy.deepcopy(original)
                subject["data"][field] = value
                self.store.put(subject)
                replayed = self.duplicate()
                self.assertIsNone(replayed["subject"])
                self.assertTrue(replayed["restricted"])
        self.store.execute("DELETE FROM resources WHERE kind='kanji' AND id='2'")
        self.assertIsNone(self.duplicate()["subject"])

    def test_legacy_already_restricted_reply_redacts_feedback_without_inventing_identity(self):
        original = self.start_answer()
        original.update(subject=None, restricted=True)
        original.pop("session_epoch")
        original.pop("revision")
        self.store.execute("UPDATE commands SET body=? WHERE id='authored-answer'", (json.dumps(original),))
        cached = self.cached_body()
        replayed = self.duplicate()
        self.assertEqual("", replayed["draft"])
        self.assertEqual("", replayed["feedback"]["answer"])
        self.assertEqual([], replayed["feedback"]["accepted"])
        self.assertNotIn("session_epoch", replayed)
        self.assertNotIn("revision", replayed)
        self.assertEqual(cached, self.cached_body())

    def test_current_session_view_redaction_does_not_modify_saved_or_supplied_session(self):
        self.start_answer()
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 0
        self.store.set("user", user)
        saved = self.store.session()
        original = copy.deepcopy(saved)
        before = list(self.store.db.iterdump())
        view = self.engine.session_view(saved)
        self.assertTrue(view["restricted"])
        self.assertIsNone(view["subject"])
        self.assertEqual("", view["draft"])
        self.assertEqual("", view["feedback"]["answer"])
        self.assertEqual([], view["feedback"]["accepted"])
        self.assertEqual(1, view["errors"])
        self.assertEqual(original, saved)
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_personal_material_and_editor_display_come_from_current_state(self):
        self.store.set("material_draft_2", {"meaning_synonyms": ["AUTHORED_OLD_ALIAS"],
            "meaning_note": "AUTHORED_OLD_NOTE", "reading_note": ""})
        self.store.set("material_editor_2", {"revision": "old-editor", "values": {
            "synonyms_text": "", "meaning_note": "AUTHORED_OLD_EDITOR", "reading_note": ""}})
        old = self.start_answer()
        cached = self.cached_body()
        self.store.set("material_draft_2", {"meaning_synonyms": [], "meaning_note": "New saved note", "reading_note": ""})
        self.store.set("material_editor_2", {"revision": "new-editor", "values": {
            "synonyms_text": "unfinished,", "meaning_note": "New unsaved note", "reading_note": ""}})
        replayed = self.duplicate()
        self.assertNotIn("AUTHORED_OLD_", json.dumps(replayed))
        self.assertEqual("New saved note", replayed["subject"]["material"]["meaning_note"])
        self.assertEqual("New unsaved note", replayed["subject"]["editor_draft"]["meaning_note"])
        self.assertEqual(["mountain"], replayed["feedback"]["accepted"])
        self.assertEqual(old["feedback"]["correct"], replayed["feedback"]["correct"])
        self.assertEqual(old["revision"], replayed["revision"])
        self.assertEqual(cached, self.cached_body())

    def test_replay_never_substitutes_the_new_active_session(self):
        old = self.start_answer()
        self.engine.correct()
        view = self.engine.advance()
        self.engine.answer(self.correct_answer(view))
        self.engine.advance()
        newer = self.engine.start("practice", 1, [4])
        self.engine.draft("new session draft")
        before = self.store.session()
        replayed = self.duplicate()
        self.assertEqual(old["id"], replayed["id"])
        self.assertEqual(old["revision"], replayed["revision"])
        self.assertEqual(old["session_epoch"], replayed["session_epoch"])
        self.assertEqual("feedback", replayed["phase"])
        self.assertFalse(replayed["feedback"]["correct"])
        self.assertEqual(2, replayed["subject"]["id"])
        self.assertNotEqual(newer["id"], replayed["id"])
        self.assertEqual(before, self.store.session())

    def test_current_related_access_and_downloaded_audio_are_rechecked(self):
        subject = self.store.subject(2)
        subject["data"]["pronunciation_audios"] = [{"url": "https://fixture.invalid/audio", "metadata": {}}]
        self.store.put(subject)
        audio = self.path.parent / "authored-audio"
        audio.write_bytes(b"authored cached fixture")
        self.store.execute("INSERT INTO media VALUES(?,?,?,?)", ("https://fixture.invalid/audio", str(audio), audio.stat().st_size, NOW))
        old = self.start_answer()
        self.assertTrue(old["subject"]["related"])
        self.assertTrue(old["subject"]["audio"])
        relative = self.store.subject(8)
        relative["data"]["hidden_at"] = stamp(NOW)
        self.store.put(relative)
        audio.unlink()
        replayed = self.duplicate()
        self.assertEqual([], replayed["subject"]["related"])
        self.assertEqual([], replayed["subject"]["audio"])

    def test_direct_subject_reply_is_projected_without_repeating_pin_or_material_edit(self):
        self.engine.command("pin-once", "pin", {"subject_id": 2, "enabled": True})
        self.store.set("pinned_subjects", [])
        self.store.set("material_draft_2", {"meaning_synonyms": [], "meaning_note": "Current note", "reading_note": ""})
        with patch.object(self.engine, "pin", side_effect=AssertionError("Pin repeated")):
            reply = self.engine.command("pin-once", "pin", {"subject_id": 2, "enabled": True})
        self.assertFalse(reply["pinned"])
        self.assertEqual("Current note", reply["material"]["meaning_note"])
        subject = self.store.subject(2)
        subject["data"]["hidden_at"] = stamp(NOW)
        self.store.put(subject)
        with self.assertRaises(UserError) as failure:
            self.engine.command("pin-once", "pin", {"subject_id": 2, "enabled": True})
        self.assertEqual("access_restricted", failure.exception.code)
        self.assertEqual([], self.store.get("pinned_subjects"))
        self.assertEqual(1, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])

    def test_large_journal_lookup_does_not_scan_history_or_touch_durable_rows(self):
        old = self.start_answer(4)
        body = self.cached_body()
        with self.store.transaction():
            for index in range(10000):
                self.store.execute("INSERT INTO commands VALUES(?,?)", ("history-" + str(index), body))
        plans = []
        rows = self.store.rows
        def capture(sql, args=()):
            if "FROM commands" in sql:
                plans.extend(row[3] for row in rows("EXPLAIN QUERY PLAN " + sql, args))
            return rows(sql, args)
        with patch.object(self.engine, "snapshot", side_effect=AssertionError("Replay scanned account")), \
                patch.object(self.store, "all", side_effect=AssertionError("Replay scanned catalogue")), \
                patch.object(self.store, "rows", side_effect=capture):
            self.assertEqual(old, self.duplicate())
        self.assertTrue(any("SEARCH commands USING INDEX" in step for step in plans), plans)
        self.assertFalse(any("SCAN commands" in step for step in plans), plans)
        self.assertEqual(10001, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])


if __name__ == "__main__":
    unittest.main()
