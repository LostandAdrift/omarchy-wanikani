"""Agent CLI tests mock all shell calls; no desktop or account is touched."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wanikani_agent_cli", ROOT / "tools" / "wanikani.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class AgentCliTests(unittest.TestCase):
    def setUp(self):
        self.which = patch.object(cli.shutil, "which", side_effect=lambda name: "/authored/bin/" + name).start()
        self.run = patch.object(cli.subprocess, "run").start()
        self.addCleanup(patch.stopall)
        self.run.return_value = subprocess.CompletedProcess([], 0, "ok\n", "")

    def invoke(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli.main(list(arguments))
        return code, output.getvalue(), errors.getvalue()

    def machine(self, *arguments):
        code, output, errors = self.invoke("--json", *arguments)
        self.assertEqual("", errors)
        value = json.loads(output)
        self.assertEqual("wanikani-cli", value["protocol"])
        self.assertEqual(1, value["version"])
        self.assertEqual({"protocol", "version", "command", "ok", "data", "error"}, set(value))
        return code, value

    def response(self, data):
        self.run.return_value = subprocess.CompletedProcess([], 0, json.dumps(data), "")

    def status_fixture(self):
        return {"status": "online", "reviews": 42, "lessons": 18, "pending": 2, "attention": 1}

    def payload(self):
        command = self.run.call_args.args[0]
        self.assertEqual(["omarchy-shell", "shell", "summon", cli.PLUGIN_ID], command[:4])
        self.assertEqual(5, len(command))
        self.assertNotIn("shell", self.run.call_args.kwargs)
        self.assertLessEqual(self.run.call_args.kwargs["timeout"], 15)
        return json.loads(command[4])

    def test_capabilities_and_default_never_contact_shell(self):
        for args in ((), ("capabilities",), ("--json", "--help")):
            code, output, errors = self.invoke(*args)
            self.assertEqual(0, code)
            result = json.loads(output)
            self.assertTrue(result["ok"])
            self.assertEqual("read_only", result["data"]["commands"]["doctor"]["effect"])
            self.assertIn("forced recovery replay", result["data"]["not_supported"])
            self.assertEqual("", errors)
        self.run.assert_not_called()

    def test_json_option_works_after_subcommand(self):
        self.response(self.status_fixture())
        code, text, errors = self.invoke("status", "--json")
        self.assertEqual(0, code)
        self.assertTrue(json.loads(text)["ok"])
        self.assertEqual("", errors)

    def test_cached_status_is_projected_and_missing_values_stay_unknown(self):
        raw = {**self.status_fixture(), "username": "PRIVATE NAME", "message": "PRIVATE NOTE", "token": "PRIVATE TOKEN",
            "session": {"answer": "PRIVATE ANSWER"}, "path": "/private/home"}
        self.response(raw)
        code, result = self.machine("status")
        self.assertEqual(0, code)
        data = result["data"]
        self.assertEqual(2, data["pending"])
        self.assertEqual(1, data["attention"])
        self.assertIsNone(data["listening_due"])
        self.assertIsNone(data["connected"])
        self.assertIsNone(data["outbox_counts"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("/private", json.dumps(result))
        self.assertEqual(["omarchy-shell", "wanikani", "status"], self.run.call_args.args[0])

    def test_new_status_fields_and_confirmed_counts_are_optional_and_typed(self):
        self.response({**self.status_fixture(), "schemaVersion": 1, "ready": True, "connected": True,
            "listening_due": 7, "outbox_counts": {"confirmed": 21, "uncertain": 1, "secret": "PRIVATE"}})
        code, result = self.machine("status")
        self.assertEqual(0, code)
        self.assertEqual(21, result["data"]["outbox_counts"]["confirmed"])
        self.assertIsNone(result["data"]["outbox_counts"]["pending"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_learning_desktop_and_reminder_aggregates_are_strictly_projected(self):
        self.response({**self.status_fixture(), "panel_open": True, "studying": False,
            "next_reviews_at": "2026-09-05T18:00:00Z", "last_sync": "2026-09-05T10:05:00.123456+00:00",
            "learning_progress": {"level": 12, "complete": True, "passed": 24, "required": 27, "remaining": 3,
                "pending": 1, "attention": 0, "threshold_met": False, "subjects": ["PRIVATE"]},
            "saved_sessions": {"reviews": True, "lessons": False, "practice": True, "answer": "PRIVATE"},
            "reminders": {"status": "dnd", "next_at": 1788620000.0, "remaining_today": 2, "message": "PRIVATE"}})
        code, result = self.machine("status")
        self.assertEqual(0, code)
        data = result["data"]
        self.assertEqual((24, 27, 3), tuple(data["learning_progress"][key] for key in ("passed", "required", "remaining")))
        self.assertEqual({"reviews": True, "lessons": False, "practice": True}, data["saved_sessions"])
        self.assertEqual("dnd", data["reminders"]["status"])
        self.assertFalse(data["studying"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_partial_aggregate_fields_are_unknown_without_becoming_zero(self):
        self.response({**self.status_fixture(), "learning_progress": {"level": 12, "complete": False, "passed": 24},
            "saved_sessions": {}, "reminders": {"status": "PRIVATE", "next_at": None}})
        code, result = self.machine("status")
        self.assertEqual(0, code)
        self.assertIsNone(result["data"]["learning_progress"]["required"])
        self.assertIsNone(result["data"]["saved_sessions"]["reviews"])
        self.assertEqual("unknown", result["data"]["reminders"]["status"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_malformed_nested_aggregates_and_dates_fail_without_echo(self):
        invalid = [{"learning_progress": {"passed": "PRIVATE"}}, {"learning_progress": {"threshold_met": 1}},
            {"saved_sessions": {"reviews": "PRIVATE"}}, {"saved_sessions": []},
            {"reminders": {"next_at": float("nan")}}, {"reminders": {"next_at": True}},
            {"reminders": {"remaining_today": -1}}, {"reminders": {"status": ["PRIVATE"]}},
            {"last_sync": "PRIVATE"}, {"next_reviews_at": "2026-99-99T10:00:00Z"}]
        for extra in invalid:
            with self.subTest(extra=extra):
                self.response({**self.status_fixture(), **extra})
                code, result = self.machine("status")
                self.assertEqual(4, code)
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_starting_status_keeps_unavailable_pending_unknown(self):
        self.response({"status": "starting", "reviews": 0, "lessons": 0})
        code, result = self.machine("status")
        self.assertEqual(0, code)
        self.assertIsNone(result["data"]["pending"])

    def test_unknown_status_text_is_not_echoed(self):
        self.response({**self.status_fixture(), "status": "PRIVATE TOKEN"})
        code, result = self.machine("status")
        self.assertEqual(0, code)
        self.assertEqual("unknown", result["data"]["status"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_invalid_status_is_redacted_structured_error(self):
        for value in ([], {}, {**self.status_fixture(), "pending": "PRIVATE"},
                {**self.status_fixture(), "reviews": True}, {**self.status_fixture(), "attention": -1},
                {**self.status_fixture(), "ready": "PRIVATE"}, {**self.status_fixture(), "outbox_counts": []}):
            with self.subTest(value=value):
                self.response(value)
                code, result = self.machine("status")
                self.assertEqual(4, code)
                self.assertFalse(result["ok"])
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_malformed_or_future_protocol_cannot_masquerade_as_status(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, "not JSON PRIVATE", "PRIVATE stderr")
        code, result = self.machine("status")
        self.assertEqual(4, code)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.response({**self.status_fixture(), "schemaVersion": 2})
        code, result = self.machine("status")
        self.assertEqual("incompatible_version", result["error"]["code"])

    def test_all_surface_routes_dispatch_exact_validated_payload(self):
        for view in cli.VIEWS:
            with self.subTest(view=view):
                code, result = self.machine("open", view)
                self.assertEqual(0, code)
                self.assertEqual({"view": view}, self.payload())
                self.assertEqual("dispatch_only", result["data"]["completion"])

    def test_open_lookup_never_requests_clipboard(self):
        self.machine("open", "lookup")
        self.assertEqual({"view": "lookup"}, self.payload())

    def test_reviews_lessons_resume_are_explicit_bounded_starts(self):
        for command in ("reviews", "lessons", "resume"):
            self.machine(command)
            self.assertEqual({"view": command}, self.payload())
            self.machine(command, "--batch", "20")
            self.assertEqual({"view": command, "limit": 20}, self.payload())
        self.assertEqual("begin_study", cli.capabilities()["commands"]["reviews"]["effect"])

    def test_invalid_batch_view_or_unavailable_command_never_dispatches(self):
        for args in (("reviews", "--batch", "0"), ("lessons", "--batch", "21"), ("resume", "--batch", "5.5"),
                ("open", "PRIVATE_VIEW"), ("answer", "PRIVATE ANSWER"), ("recovery", "--force")):
            self.run.reset_mock()
            code, result = self.machine(*args)
            self.assertEqual(2, code)
            self.assertNotIn("PRIVATE", json.dumps(result))
            self.run.assert_not_called()

    def test_lookup_preserves_exact_unicode_whitespace_and_literal_metacharacters(self):
        text = '  山\n𠮷\t"$(touch /tmp/never)" `literal`  '
        code, result = self.machine("lookup", text)
        self.assertEqual(0, code)
        self.assertEqual({"view": "lookup", "text": text}, self.payload())
        self.assertNotIn(text, json.dumps(result, ensure_ascii=False))
        self.assertEqual("supplied_text", result["data"]["source"])

    def test_lookup_counts_codepoints_and_rejects_partial_or_control_input(self):
        text = "山" * 255 + "𠮷"
        self.assertEqual(0, self.machine("lookup", text)[0])
        self.assertEqual(text, self.payload()["text"])
        for bad in (text + "more", "", "   ", "山\x00", "山\x1b", "山\ud800"):
            self.run.reset_mock()
            code, result = self.machine("lookup", bad)
            self.assertEqual(2, code)
            self.run.assert_not_called()

    def test_literal_option_text_after_separator_is_a_lookup_not_cli_help(self):
        code, result = self.machine("lookup", "--", "--help")
        self.assertEqual(0, code)
        self.assertEqual({"view": "lookup", "text": "--help"}, self.payload())

    def test_selection_read_requires_an_explicit_flag_and_is_shell_owned(self):
        code, result = self.machine("lookup", "--selection")
        self.assertEqual(0, code)
        self.assertEqual({"view": "lookup", "selection": True}, self.payload())
        self.assertEqual("selection_or_clipboard", result["data"]["source"])
        self.run.reset_mock()
        self.assertEqual(2, self.machine("lookup")[0])
        self.assertEqual(2, self.machine("lookup", "山", "--selection")[0])
        self.run.assert_not_called()

    def test_refresh_reports_async_and_completed_work_effect(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, "", "")
        code, result = self.machine("refresh")
        self.assertEqual(0, code)
        self.assertEqual(["omarchy-shell", "wanikani", "refresh"], self.run.call_args.args[0])
        self.assertEqual("asynchronous", result["data"]["completion"])
        self.assertTrue(result["data"]["may_submit_completed_pending_work"])

    def test_unknown_plugin_and_unrecognized_ack_are_not_success(self):
        for response, delivery in (("unknown", "not_sent"), ("PRIVATE unexpected", "unknown")):
            self.run.return_value = subprocess.CompletedProcess([], 0, response, "")
            code, result = self.machine("open", "dashboard")
            self.assertEqual(4, code)
            self.assertEqual(delivery, result["error"]["delivery"])
            self.assertNotIn("PRIVATE", json.dumps(result))

    def test_timeout_is_bounded_never_retries_and_does_not_echo_args(self):
        self.run.side_effect = subprocess.TimeoutExpired(["PRIVATE COMMAND"], 5, output="PRIVATE OUTPUT")
        code, result = self.machine("refresh", "--timeout", "3")
        self.assertEqual(5, code)
        self.assertEqual("unknown", result["error"]["delivery"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.run.assert_called_once()
        self.assertEqual(3, self.run.call_args.kwargs["timeout"])
        self.assertEqual("2.5s", self.run.call_args.kwargs["env"]["OMARCHY_SHELL_IPC_TIMEOUT"])

    def test_bad_timeout_and_missing_dependency_do_not_launch(self):
        for value in ("0", "16", "nan", "inf", "PRIVATE"):
            self.assertEqual(2, self.machine("status", "--timeout", value)[0])
        self.which.side_effect = lambda name: None
        code, result = self.machine("status")
        self.assertEqual(3, code)
        self.assertEqual("missing_dependency", result["error"]["code"])
        self.run.assert_not_called()

    def test_shell_error_and_oversized_output_are_redacted(self):
        self.run.return_value = subprocess.CompletedProcess([], 1, "PRIVATE STDOUT", "PRIVATE STDERR")
        self.assertEqual(3, self.machine("status")[0])
        self.run.return_value = subprocess.CompletedProcess([], 0, "PRIVATE" * cli.MAX_RESPONSE, "")
        code, result = self.machine("status")
        self.assertEqual(4, code)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def doctor_responses(self, listed=True):
        def answer(command, **kwargs):
            method = command[2]
            if method == "ping":
                return subprocess.CompletedProcess(command, 0, "ok", "")
            if method == "listPlugins":
                rows = [{"id": "private.other", "name": "PRIVATE"}]
                if listed:
                    rows.append({"id": cli.PLUGIN_ID, "enabled": False, "name": "PRIVATE NAME", "path": "PRIVATE PATH"})
                return subprocess.CompletedProcess(command, 0, json.dumps(rows), "")
            if method == "status":
                return subprocess.CompletedProcess(command, 0, json.dumps(self.status_fixture()), "")
            self.fail("Unexpected mocked doctor command")
        self.run.side_effect = answer

    def test_doctor_uses_only_read_calls_and_projects_matching_plugin(self):
        self.doctor_responses()
        code, result = self.machine("doctor")
        self.assertEqual(0, code)
        data = result["data"]
        self.assertTrue(data["healthy"])
        self.assertTrue(data["plugin"]["service_accessible"])
        self.assertFalse(data["plugin"]["manager_enabled"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(["ping", "listPlugins", "status"], [call.args[0][2] for call in self.run.call_args_list])

    def test_doctor_reports_incomplete_without_attempting_repairs(self):
        self.doctor_responses(listed=False)
        code, result = self.machine("doctor")
        self.assertEqual(3, code)
        self.assertFalse(result["ok"])
        self.assertTrue(result["data"]["plugin"]["service_accessible"])
        self.assertIn("plugin_not_listed", [item["code"] for item in result["data"]["issues"]])
        self.assertEqual(3, self.run.call_count)

    def test_doctor_optional_keyring_clipboard_absence_is_not_failure(self):
        self.which.side_effect = lambda name: None if name in ("secret-tool", "wl-paste") else "/authored/bin/" + name
        self.doctor_responses()
        code, result = self.machine("doctor")
        self.assertEqual(0, code)
        self.assertFalse(result["data"]["dependencies"]["secret-tool"]["present"])


if __name__ == "__main__":
    unittest.main()
