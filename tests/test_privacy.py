"""Privacy and deletion checks use authored data in isolated temporary homes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani import diagnostics
from wanikani.demo import populate
from worker import Worker


class DiagnosticExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.snapshot = {"status": "online", "pending": 2, "attention": 1,
                         "cache": {"files": 3, "bytes": 400, "subjects": 16}}

    def test_export_has_only_explicit_aggregate_fields(self):
        marker = "PRIVATE-TOKEN-NOTE-USERNAME-ANSWER-URL"
        self.snapshot.update({"message": marker, "session": {"draft": marker},
            "username": marker, "token": marker, "outbox": [{"detail": marker}],
            "materials": [{"meaning_synonyms": [marker], "meaning_note": marker}]})
        self.snapshot["cache"].update({"urls": [marker], "path": marker})
        result = diagnostics.export(self.directory, False, self.snapshot, 2)
        path = Path(result["path"])
        written = path.read_text()
        self.assertNotIn(marker, written)
        self.assertNotIn(str(self.directory), written)
        report = json.loads(written)
        self.assertEqual({"version", "python", "protocol", "demo", "status", "pending",
                          "attention", "schema", "cache"}, set(report))
        self.assertEqual({"files": 3, "bytes": 400, "subjects": 16}, report["cache"])
        self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_private_values_cannot_escape_through_expected_fields(self):
        marker = "PRIVATE-UNEXPECTED-SERVER-RESPONSE"
        self.snapshot.update(status=marker, pending=marker, attention={"note": marker})
        self.snapshot["cache"] = {"files": [marker], "bytes": marker, "subjects": -1}
        result = diagnostics.export(self.directory, False, self.snapshot, marker)
        self.assertNotIn(marker, Path(result["path"]).read_text())
        self.assertEqual("unknown", result["status"])
        self.assertEqual(0, result["pending"])
        self.assertEqual({"files": 0, "bytes": 0, "subjects": 0}, result["cache"])

    def test_export_replaces_link_without_overwriting_its_target(self):
        victim = self.directory / "unrelated.txt"
        victim.write_text("keep this private note")
        destination = self.directory / "diagnostics-account.json"
        destination.symlink_to(victim)
        diagnostics.export(self.directory, False, self.snapshot, 2)
        self.assertFalse(destination.is_symlink())
        self.assertEqual("keep this private note", victim.read_text())
        self.assertEqual(2, json.loads(destination.read_text())["pending"])

    def test_interrupted_replacement_preserves_complete_export_and_cleans_temporary(self):
        result = diagnostics.export(self.directory, False, self.snapshot, 2)
        original = Path(result["path"]).read_bytes()
        self.snapshot["pending"] = 9
        with patch("wanikani.diagnostics.os.replace", side_effect=OSError("fixture interruption")):
            with self.assertRaises(OSError):
                diagnostics.export(self.directory, False, self.snapshot, 2)
        self.assertEqual(original, Path(result["path"]).read_bytes())
        self.assertEqual([], list(self.directory.glob(".diagnostics-*.tmp")))

    def test_cleanup_preserves_other_mode_and_removes_interrupted_export(self):
        account = Path(diagnostics.export(self.directory, False, self.snapshot, 2)["path"])
        demo = Path(diagnostics.export(self.directory, True, self.snapshot, 2)["path"])
        interrupted = self.directory / ".diagnostics-demo-interrupted.tmp"
        interrupted.write_text("incomplete demo export")
        legacy = self.directory / "diagnostics.json"
        legacy.write_text(json.dumps({"demo": False, "pending": 7}))
        diagnostics.clear(self.directory, True)
        self.assertFalse(demo.exists())
        self.assertFalse(interrupted.exists())
        self.assertTrue(account.exists())
        self.assertTrue(legacy.exists())
        diagnostics.clear(self.directory, False)
        self.assertFalse(account.exists())
        self.assertFalse(legacy.exists())


class WorkerPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.messages = []
        self.worker = Worker(self.directory, self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.worker.keyring = Mock()

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temporary.cleanup()

    def request(self, method, args=None):
        rid = "request-" + str(len(self.messages))
        self.worker.handle({"v": 1, "id": rid, "method": method, "args": args or {}})
        return next(message["data"] for message in self.messages if message.get("id") == rid)

    def test_worker_export_excludes_saved_token_notes_draft_and_error_message(self):
        marker = "PRIVATE-WORKER-REGRESSION-SENTINEL"
        worker = self.worker
        worker.token = marker
        worker.engine.store.set("user", {"id": marker, "object": "user", "data": {
            "username": marker, "level": 3, "subscription": {"max_level_granted": 60}}})
        worker.engine.set_material(2, {"meaning_note": marker, "meaning_synonyms": [marker]})
        worker.engine.start("reviews", 1)
        worker.engine.draft(marker)
        worker.engine.message = marker
        result = self.request("diagnostics")
        self.assertNotIn(marker, Path(result["path"]).read_text())
        self.assertEqual(1, result["pending"])
        self.assertEqual(marker, worker.engine.session_view()["draft"])

    def test_disconnect_preserves_pending_work_and_draft_across_restart(self):
        worker = self.worker
        worker.engine.store.set("credential_storage", "session")
        worker.engine.store.set("credential_may_exist", False)
        worker.token = "fixture-session-token"
        worker.engine.set_material(2, {"meaning_note": "saved personal note"})
        worker.engine.start("reviews", 1)
        worker.engine.draft("saved incomplete answer")
        self.request("disconnect")
        self.assertIsNone(worker.token)
        worker.keyring.delete.assert_not_called()
        worker.select_mode(False)
        worker.startup()
        worker.keyring.get.assert_not_called()
        self.assertEqual("saved incomplete answer", worker.engine.session_view()["draft"])
        self.assertEqual(1, worker.engine.snapshot()["pending"])
        self.assertEqual("saved personal note", worker.engine.store.get("material_draft_2")["meaning_note"])

    def test_delete_removes_owned_reports_and_derived_content(self):
        result = self.request("diagnostics")
        legacy = self.directory / "diagnostics.json"
        legacy.write_text(json.dumps({"demo": False, "pending": 7}))
        demo = Path(diagnostics.export(self.directory, True, self.worker.engine.snapshot(), 2)["path"])
        self.assertTrue(self.worker.engine.store.rows("SELECT 1 FROM search_documents"))
        self.request("delete_data", {"confirmation": "DELETE"})
        self.assertFalse(Path(result["path"]).exists())
        self.assertFalse(legacy.exists())
        self.assertTrue(demo.exists())
        self.assertEqual([], self.worker.engine.store.rows("SELECT * FROM search_documents"))
        self.assertEqual([], self.worker.engine.store.all("assignment"))

    def test_demo_deletion_preserves_account_draft_queue_media_and_report(self):
        worker = self.worker
        worker.engine.set_material(2, {"meaning_note": "account fixture note"})
        worker.engine.start("reviews", 1)
        worker.engine.draft("account fixture draft")
        report = Path(self.request("diagnostics")["path"])
        media = self.directory / "media" / "account-fixture.bin"
        media.parent.mkdir()
        media.write_bytes(b"account fixture media")
        worker.engine.store.execute("INSERT INTO media VALUES(?,?,?,?)",
            ("https://example.invalid/fixture", str(media), media.stat().st_size, NOW))
        worker.select_mode(True)
        demo_report = Path(self.request("diagnostics")["path"])
        self.request("delete_data", {"confirmation": "DELETE"})
        worker.keyring.delete.assert_not_called()
        self.assertFalse(demo_report.exists())
        self.assertTrue(report.exists())
        self.assertEqual(b"account fixture media", media.read_bytes())
        worker.select_mode(False)
        self.assertEqual("account fixture draft", worker.engine.session_view()["draft"])
        self.assertEqual(1, worker.engine.snapshot()["pending"])
        self.assertEqual("account fixture note", worker.engine.store.get("material_draft_2")["meaning_note"])


if __name__ == "__main__":
    unittest.main()
