"""Unsaved notes remain local and independent of saved/pending study material."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import EngineFixture, NOW
from wanikani import editor
from wanikani.common import UserError
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from worker import Worker


def raw(synonyms="clifftop,  mounta,", meaning="A half-written meaning note…\n", reading="読みかけ"):
    return {"synonyms_text": synonyms, "meaning_note": meaning, "reading_note": reading}


class EditorDraftTests(EngineFixture, unittest.TestCase):
    def write(self, values, rid="draft", subject_id=2):
        return self.engine.command(rid, "editor_draft", {"subject_id": subject_id, "values": values})

    def save(self, values, expected=None):
        return self.engine.command("save", "set_material", {"subject_id": 2,
            "values": editor.material_values(values), "editor_draft": expected})

    def test_raw_commas_notes_and_partial_text_survive_navigation_and_restart(self):
        values = raw()
        reply = self.write(values)
        self.assertLess(len(json.dumps(reply)), 180)
        self.assertNotIn("clifftop", json.dumps(reply))
        self.engine.details(3)  # Navigate away; no save or flush action.
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        detail = self.engine.details(2)
        self.assertEqual(values, detail["editor_draft"])
        self.assertTrue(detail["editor_dirty"])
        self.assertEqual(reply["revision"], detail["editor_revision"])

    def test_unsaved_synonyms_never_grade_search_or_create_outbox_work(self):
        self.write(raw("clifftop"))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertIsNone(self.store.get("material_draft_2"))
        self.assertEqual([], self.engine.search("clifftop"))
        view = self.engine.start("practice", 1, [2])
        if view["part"] == "reading":
            self.engine.answer("さん")
            self.engine.advance()
        feedback = self.engine.answer("clifftop")["feedback"]
        self.assertFalse(feedback["correct"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.engine.details(2)["material"]["meaning_synonyms"])

    def test_discard_returns_to_saved_material_without_syncing(self):
        self.store.put({"id": 500, "object": "study_material", "data": {
            "subject_id": 2, "meaning_synonyms": ["peak"], "meaning_note": "Saved note", "reading_note": ""}})
        self.write(raw())
        detail = self.engine.command("discard", "editor_discard", {"subject_id": 2, "expected": raw()})
        self.assertIsNone(detail["editor_draft"])
        self.assertFalse(detail["editor_dirty"])
        self.assertEqual("Saved note", detail["material"]["meaning_note"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_typing_back_to_saved_values_removes_local_draft(self):
        self.write(raw())
        reply = self.write(raw("", "", ""), "back-to-saved")
        self.assertFalse(reply["dirty"])
        self.assertIsNone(reply["revision"])
        self.assertIsNone(self.engine.details(2)["editor_draft"])

    def test_hidden_and_expired_access_blocks_read_edit_and_discard(self):
        self.write(raw())
        subject = self.store.subject(2)
        subject["data"]["level"] = 60
        self.store.put(subject)
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 3
        self.store.set("user", user)
        for operation in (lambda: self.engine.details(2), lambda: self.write(raw("new"), "restricted"),
                          lambda: editor.discard(self.engine, 2)):
            with self.assertRaises(UserError) as failure:
                operation()
            self.assertEqual("access_restricted", failure.exception.code)
        subject["data"]["level"] = 1
        subject["data"]["hidden_at"] = "2026-01-01T00:00:00Z"
        self.store.put(subject)
        with self.assertRaises(UserError):
            self.write(raw("hidden"), "hidden")
        subject["data"]["hidden_at"] = None
        self.store.put(subject)
        self.assertEqual(raw(), self.engine.details(2)["editor_draft"])

    def test_only_explicit_save_applies_synonyms_and_clears_matching_editor(self):
        values = raw(" peak, peak, clifftop, ")
        self.write(values)
        detail = self.save(values, values)
        self.assertIsNone(detail["editor_draft"])
        self.assertTrue(detail["material_pending"])
        self.assertEqual(["peak", "clifftop"], detail["material"]["meaning_synonyms"])
        self.assertEqual(1, len(self.store.rows("SELECT * FROM outbox")))
        body = json.loads(self.store.rows("SELECT body FROM outbox")[0][0])
        self.assertNotIn("synonyms_text", body["values"])
        self.assertEqual(values["meaning_note"], body["values"]["meaning_note"])

    def test_invalid_save_keeps_draft_and_creates_no_pending_work(self):
        values = raw("a" * 65)
        self.write(values)
        with self.assertRaises(UserError):
            self.save(values, values)
        self.assertEqual(values, self.engine.details(2)["editor_draft"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_pending_material_allows_future_draft_but_not_another_save(self):
        self.engine.set_material(2, {"meaning_synonyms": ["peak"], "meaning_note": "First saved note"})
        values = raw("clifftop", "Future note")
        self.write(values)
        with self.assertRaises(UserError):
            self.save(values, values)
        detail = self.engine.details(2)
        self.assertEqual(values, detail["editor_draft"])
        self.assertEqual("First saved note", detail["material"]["meaning_note"])
        self.assertEqual(1, len(self.store.rows("SELECT * FROM outbox")))
        discarded = editor.discard(self.engine, 2, values)
        self.assertEqual("First saved note", discarded["material"]["meaning_note"])
        self.assertTrue(discarded["material_pending"])

    def test_older_save_does_not_clear_newer_raw_edit_even_when_values_normalize_equal(self):
        old, newer = raw("peak"), raw("peak, ")
        self.write(old)
        self.write(newer, "newer")
        detail = self.save(old, old)
        self.assertEqual(newer, detail["editor_draft"])
        self.assertEqual(["peak"], detail["material"]["meaning_synonyms"])

    def test_older_discard_does_not_clear_newer_editor(self):
        self.write(raw("peak"))
        newer = raw("peak, new")
        self.write(newer, "newer")
        detail = editor.discard(self.engine, 2, raw("peak"))
        self.assertEqual(newer, detail["editor_draft"])

    def test_noneditor_save_preserves_unsaved_input(self):
        values = raw("peak")
        self.write(values)
        detail = self.engine.set_material(2, editor.material_values(values))
        self.assertEqual(values, detail["editor_draft"])

    def test_save_and_editor_clear_rollback_together_if_ack_commit_fails(self):
        values = raw("peak")
        self.write(values)
        original = self.store.execute
        def interrupt(sql, args=()):
            if sql.startswith("INSERT INTO commands"):
                raise OSError("fixture interruption at response commit")
            return original(sql, args)
        with patch.object(self.store, "execute", side_effect=interrupt), self.assertRaises(OSError):
            self.save(values, values)
        self.assertEqual(values, self.engine.details(2)["editor_draft"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertIsNone(self.store.get("material_draft_2"))

    def test_duplicate_command_returns_ack_without_replacing_newer_editor(self):
        reply = self.write(raw("old"))
        newer = raw("new")
        self.write(newer, "newer")
        self.assertEqual(reply, self.write(raw("old")))
        self.assertEqual(newer, self.engine.details(2)["editor_draft"])

    def test_editor_limits_fail_without_replacing_previous_draft(self):
        self.write(raw())
        for index, values in enumerate((None, {}, raw(meaning=7), raw("a" * 2001), raw(reading="あ" * 2001))):
            with self.subTest(values=values), self.assertRaises(UserError):
                self.write(values, "invalid-" + str(index))
        self.assertEqual(raw(), self.engine.details(2)["editor_draft"])


class WorkerEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.messages = []
        self.worker = Worker(self.directory, self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.keyring = Mock()

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temporary.cleanup()

    def write(self, values, rid="editor"):
        self.worker.handle({"v": 1, "id": rid, "method": "editor_draft", "args": {"subject_id": 2, "values": values}})

    def test_each_edit_gets_small_ack_without_snapshot_state_event_or_sync(self):
        self.worker.sync = Mock()
        with patch.object(self.worker, "changed", side_effect=AssertionError("unexpected snapshot")):
            self.write(raw())
        self.assertEqual(1, len(self.messages))
        self.assertTrue(self.messages[0]["ok"])
        self.assertLess(len(json.dumps(self.messages[0])), 230)
        self.worker.sync.run.assert_not_called()
        self.assertEqual(raw(), self.worker.engine.details(2)["editor_draft"])

    def test_account_demo_and_explicit_deletion_keep_drafts_isolated(self):
        account = raw("account fixture synonym", "PRIVATE-EDITOR-DELETION-MARKER")
        self.write(account)
        self.worker.select_mode(True)
        self.assertIsNone(self.worker.engine.details(2)["editor_draft"])
        self.write(raw("demo only"), "demo-editor")
        self.worker.select_mode(False)
        self.assertEqual(account, self.worker.engine.details(2)["editor_draft"])
        self.worker.handle({"v": 1, "id": "delete", "method": "delete_data", "args": {"confirmation": "DELETE"}})
        self.assertIsNone(self.worker.engine.store.get("material_editor_2"))
        for path in self.directory.glob("account.sqlite3*"):
            self.assertNotIn(b"PRIVATE-EDITOR-DELETION-MARKER", path.read_bytes())
        self.worker.select_mode(True)
        self.assertEqual(raw("demo only"), self.worker.engine.details(2)["editor_draft"])


if __name__ == "__main__":
    unittest.main()
