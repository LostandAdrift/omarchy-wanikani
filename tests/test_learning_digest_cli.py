"""Cached report contract with mocked shell transport and authored aggregates."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
import io
import json
import subprocess
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_agent_cli import cli


def digest(*, generated_at="2026-09-05T18:00:00.123456Z", zone="America/Los_Angeles"):
    instant = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    today = instant.astimezone(ZoneInfo(zone if zone != "system-local" else "UTC")).date()
    windows = {}
    for days in (7, 30):
        count = 2 if days == 7 else 9
        windows[str(days)] = {"days": days, "start_day": (today - timedelta(days=days - 1)).isoformat(),
            "end_day": today.isoformat(),
            **{metric: dict.fromkeys(names, count) for metric, names in cli.DIGEST_COUNTERS.items()},
            **dict.fromkeys(cli.DIGEST_SCALARS, count)}
    return {"schema_version": 1, "scope": "recorded_on_this_device", "freshness": "cached",
        "generated_at": generated_at, "data_epoch": "7e648d73-998e-4573-acdf-36938d90108c", "demo": False,
        "timezone": zone, "complete": True, "stale": None, "coverage": "retained_local_records",
        "includes_retained_pre_reset_activity": True, "windows": windows}


class LearningDigestCliTests(unittest.TestCase):
    def setUp(self):
        self.which = patch.object(cli.shutil, "which", return_value="/authored/bin/omarchy-shell").start()
        self.run = patch.object(cli.subprocess, "run").start()
        self.addCleanup(patch.stopall)

    def response(self, value):
        self.run.return_value = subprocess.CompletedProcess([], 0, json.dumps(value), "")

    def invoke(self, *arguments, machine=True):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli.main([*( ["--json"] if machine else []), *arguments])
        self.assertEqual("", errors.getvalue())
        return code, json.loads(output.getvalue()) if machine else output.getvalue()

    def one_status_call(self):
        self.run.assert_called_once()
        self.assertEqual(["omarchy-shell", "wanikani", "status"], self.run.call_args.args[0])
        self.assertNotIn("shell", self.run.call_args.kwargs)
        self.assertLessEqual(self.run.call_args.kwargs["timeout"], 15)

    def malformed(self, value):
        self.run.reset_mock()
        self.response({"status": "online", "learning_digest": value, "token": "PRIVATE_TOKEN"})
        code, result = self.invoke("report")
        self.assertEqual(4, code, result)
        self.assertEqual("invalid_response", result["error"]["code"])
        self.assertEqual("The cached learning summary is malformed or unsupported.", result["error"]["message"])
        self.assertIsNone(result["data"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.one_status_call()

    def test_report_defaults_to_seven_and_has_one_bounded_read_only_call(self):
        source = digest()
        self.response({"schemaVersion": 1, "status": "online", "learning_digest": source,
            "outbox_counts": {"confirmed": 999}, "last_sync": "2026-09-06T00:00:00Z"})
        code, result = self.invoke("report", "--timeout", "3")
        self.assertEqual(0, code)
        self.assertEqual(("wanikani-cli", 1, "report", True),
            (result["protocol"], result["version"], result["command"], result["ok"]))
        self.assertEqual({"available", "reason", "digest"}, set(result["data"]))
        self.assertTrue(result["data"]["available"])
        self.assertIsNone(result["data"]["reason"])
        report = result["data"]["digest"]
        self.assertEqual(source["windows"]["7"], report.pop("window"))
        self.assertEqual({key: value for key, value in source.items() if key != "windows"}, report)
        self.assertNotIn("confirmed", json.dumps(result["data"]))
        self.one_status_call()
        self.assertEqual(3, self.run.call_args.kwargs["timeout"])
        self.assertEqual("2.5s", self.run.call_args.kwargs["env"]["OMARCHY_SHELL_IPC_TIMEOUT"])

    def test_thirty_day_report_selects_only_requested_window_and_retains_timestamp(self):
        source = digest()
        self.response({"status": "offline", "learning_digest": source})
        code, result = self.invoke("report", "--days", "30", "--json")
        self.assertEqual(0, code)
        self.assertEqual(source["windows"]["30"], result["data"]["digest"]["window"])
        self.assertEqual(source["generated_at"], result["data"]["digest"]["generated_at"])
        self.assertNotIn("windows", result["data"]["digest"])
        self.one_status_call()

    def test_missing_and_null_old_service_digest_remain_unavailable_without_fallback(self):
        for value in ({"status": "online"}, {"status": "offline", "learning_digest": None}):
            with self.subTest(value=value):
                self.run.reset_mock(); self.response(value)
                code, result = self.invoke("report")
                self.assertEqual(0, code)
                self.assertEqual({"available": False, "reason": "unavailable", "digest": None}, result["data"])
                self.one_status_call()
                self.run.reset_mock()
                code, status = self.invoke("status")
                self.assertEqual(0, code)
                self.assertIsNone(status["data"]["learning_digest"])
                self.one_status_call()

    def test_optional_section_on_status_is_projected_without_private_keys_at_any_depth(self):
        source = digest()
        source.update(username="PRIVATE_USERNAME", session={"draft": "PRIVATE_DRAFT"}, token="PRIVATE_TOKEN")
        source["windows"]["private"] = {"answer": "PRIVATE_ANSWER"}
        for window in source["windows"].values():
            window["subject_ids"] = ["PRIVATE_ID"]
            for key in cli.DIGEST_COUNTERS:
                if key in window:
                    window[key]["notes"] = "PRIVATE_NOTES"
        self.response({"status": "online", "learning_digest": source})
        code, result = self.invoke("status")
        self.assertEqual(0, code)
        self.assertEqual(digest(), result["data"]["learning_digest"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.one_status_call()

    def test_known_empty_counts_are_zero_and_stale_flags_preserve_three_states(self):
        for stale in (True, False, None):
            with self.subTest(stale=stale):
                source = digest(); source["stale"] = stale
                for window in source["windows"].values():
                    for metric, names in cli.DIGEST_COUNTERS.items():
                        window[metric] = dict.fromkeys(names, 0)
                    window.update(dict.fromkeys(cli.DIGEST_SCALARS, 0))
                self.response({"status": "online", "learning_digest": source})
                code, result = self.invoke("report")
                self.assertEqual(0, code)
                self.assertTrue(result["data"]["available"])
                self.assertIs(stale, result["data"]["digest"]["stale"])
                self.assertEqual(0, result["data"]["digest"]["window"]["typo_corrections"])

    def test_schema_scope_and_required_metadata_reject_malformed_or_incompatible_values(self):
        cases = [("schema_version", True), ("schema_version", 2), ("scope", "PRIVATE_ACCOUNT"),
            ("freshness", "live"), ("coverage", "account_wide"), ("includes_retained_pre_reset_activity", 1),
            ("includes_retained_pre_reset_activity", False), ("demo", 1), ("complete", None), ("stale", "PRIVATE")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                source = digest(); source[key] = value; self.malformed(source)
        for key in digest():
            with self.subTest(missing=key):
                source = digest(); del source[key]; self.malformed(source)
        for source in (True, 0, [], "PRIVATE_RAW_DATA", {}):
            with self.subTest(section=source):
                self.malformed(source)

    def test_epoch_accepts_only_canonical_opaque_uuid(self):
        for value in (None, 123, "PRIVATE_ACCOUNT", "7E648D73-998E-4573-ACDF-36938D90108C",
                "{7e648d73-998e-4573-acdf-36938d90108c}", "7e648d73998e4573acdf36938d90108c",
                "7e648d73-998e-4573-acdf-36938d90108g"):
            with self.subTest(value=value):
                source = digest(); source["data_epoch"] = value; self.malformed(source)

    def test_timestamp_requires_real_date_time_and_strict_offset(self):
        for value in (None, 4, "2026-09-05", "2026-09-05T18:00:00", "2026-02-30T18:00:00Z",
                "2026-09-05T24:00:00Z", "2026-09-05T18:00:60Z", "2026-09-05T18:00:00+01:99",
                "2026-09-05T18:00:00+24:00", "2026-09-05T18:00:00Z\nPRIVATE"):
            with self.subTest(value=value):
                source = digest(); source["generated_at"] = value; self.malformed(source)
        for value in ("2026-09-05T11:00:00-07:00", "2026-09-05T18:00:00.123456789+00:00"):
            source = digest(generated_at=value)
            self.assertEqual(source, cli._learning_digest(source))

    def test_timezone_requires_known_safe_zone_and_never_uses_caller_override(self):
        for value in (None, False, "PRIVATE/ZONE", "/etc/passwd", "../../PRIVATE", "America/../PRIVATE",
                "America/Los_Angeles\nPRIVATE", "America/" + "X" * 129):
            with self.subTest(value=value):
                source = digest(); source["timezone"] = value; self.malformed(source)
        for zone in ("UTC", "Japan", "US/Pacific", "Etc/GMT+8", "Pacific/Kiritimati"):
            with self.subTest(zone=zone):
                source = digest(zone=zone)
                self.assertEqual(source, cli._learning_digest(source))
        self.run.reset_mock()
        code, result = self.invoke("report", "--timezone", "PRIVATE_ZONE")
        self.assertEqual(2, code)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.run.assert_not_called()

    def test_calendar_windows_use_zone_midnight_and_dst_not_fixed_seconds(self):
        for moment in ("2026-03-09T07:30:00Z", "2026-11-02T08:30:00Z", "2026-09-05T06:59:59Z"):
            with self.subTest(moment=moment):
                source = digest(generated_at=moment)
                self.assertEqual(source, cli._learning_digest(source))
        source = digest(generated_at="2026-09-05T06:59:59Z")
        self.assertEqual("2026-09-04", source["windows"]["7"]["end_day"])
        for window in source["windows"].values():
            window["start_day"] = (date.fromisoformat(window["start_day"]) + timedelta(days=1)).isoformat()
            window["end_day"] = (date.fromisoformat(window["end_day"]) + timedelta(days=1)).isoformat()
        self.malformed(source)

    def test_system_local_cached_zone_is_not_reinterpreted_after_timezone_changes(self):
        for difference in (-1, 0, 1):
            source = digest(zone="system-local")
            for window in source["windows"].values():
                for key in ("start_day", "end_day"):
                    window[key] = (date.fromisoformat(window[key]) + timedelta(days=difference)).isoformat()
            self.assertEqual(source, cli._learning_digest(source))
        source = digest(zone="system-local")
        for window in source["windows"].values():
            for key in ("start_day", "end_day"):
                window[key] = (date.fromisoformat(window[key]) + timedelta(days=2)).isoformat()
        self.malformed(source)

    def test_both_calendar_windows_are_required_and_inclusive_date_spans_exact(self):
        for window_key in ("7", "30"):
            source = digest(); del source["windows"][window_key]; self.malformed(source)
            for field, bad in (("days", True), ("days", 8), ("days", "7"), ("start_day", "2026-2-1"),
                    ("end_day", "2026-02-30"), ("end_day", None), ("start_day", "2026-09-05")):
                with self.subTest(window=window_key, field=field, bad=bad):
                    source = digest(); source["windows"][window_key][field] = bad; self.malformed(source)
        source = digest(zone="system-local")
        window = source["windows"]["7"]
        for key in ("start_day", "end_day"):
            window[key] = (date.fromisoformat(window[key]) + timedelta(days=1)).isoformat()
        self.malformed(source)

    def test_every_counter_is_present_strict_safe_integer_and_never_defaulted_to_zero(self):
        paths = [(metric, name) for metric, names in cli.DIGEST_COUNTERS.items() for name in names]
        paths.extend((metric,) for metric in cli.DIGEST_SCALARS)
        for path in paths:
            for bad in (None, True, -1, 1.0, "PRIVATE_COUNT", cli.MAX_SAFE_INTEGER + 1):
                with self.subTest(path=path, bad=bad):
                    source = digest(); target = source["windows"]["30"]
                    for part in path[:-1]:
                        target = target[part]
                    target[path[-1]] = bad; self.malformed(source)
            source = digest(); target = source["windows"]["7"]
            for part in path[:-1]:
                target = target[part]
            del target[path[-1]]; self.malformed(source)
        source = digest()
        for window in source["windows"].values():
            for metric, names in cli.DIGEST_COUNTERS.items():
                window[metric] = dict.fromkeys(names, cli.MAX_SAFE_INTEGER)
            window.update(dict.fromkeys(cli.DIGEST_SCALARS, cli.MAX_SAFE_INTEGER))
        self.assertEqual(source, cli._learning_digest(source))

    def test_every_seven_day_count_is_subset_of_thirty_day_count(self):
        paths = [(metric, name) for metric, names in cli.DIGEST_COUNTERS.items() for name in names]
        paths.extend((metric,) for metric in cli.DIGEST_SCALARS)
        for path in paths:
            with self.subTest(path=path):
                source = digest(); target = source["windows"]["7"]
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = 10; self.malformed(source)

    def test_report_validates_unselected_window_too(self):
        source = digest(); source["windows"]["30"]["dictation_ratings"]["matched"] = "PRIVATE"
        self.malformed(source)

    def test_invalid_days_and_extra_action_options_never_contact_shell(self):
        for arguments in (("--days", "1"), ("--days", "7.0"), ("--days", "-7"), ("--days", "PRIVATE"),
                ("--days", "31"), ("--refresh",), ("--account", "PRIVATE"), ("--from", "2026-09-01")):
            with self.subTest(arguments=arguments):
                code, result = self.invoke("report", *arguments)
                self.assertEqual(2, code)
                self.assertNotIn("PRIVATE", json.dumps(result))
        self.run.assert_not_called()

    def test_report_timeout_and_invalid_transport_never_fall_back_or_leak_raw_output(self):
        self.run.side_effect = subprocess.TimeoutExpired(["PRIVATE_COMMAND"], 5, output="PRIVATE_OUTPUT")
        code, result = self.invoke("report")
        self.assertEqual(5, code)
        self.assertEqual("not_applicable", result["error"]["delivery"])
        self.assertNotIn("PRIVATE", json.dumps(result)); self.one_status_call()
        self.run.side_effect = None
        for output in ("PRIVATE_NOT_JSON", "PRIVATE" * cli.MAX_RESPONSE):
            self.run.reset_mock(); self.run.return_value = subprocess.CompletedProcess([], 0, output, "PRIVATE_ERROR")
            code, result = self.invoke("report")
            self.assertEqual(4, code)
            self.assertNotIn("PRIVATE", json.dumps(result)); self.one_status_call()

    def test_human_report_is_scoped_dated_and_does_not_claim_server_confirmation(self):
        source = digest(); source.update(demo=True, stale=True, complete=False)
        self.response({"status": "online", "learning_digest": source})
        code, text = self.invoke("report", machine=False)
        self.assertEqual(0, code)
        self.assertTrue(text.startswith("Recorded on this device · cached through " + source["generated_at"]))
        for expected in ("America/Los_Angeles", "final day partial", "Authored demo", "known to be stale",
                "incomplete", "Completed cycles", "remembered", "matched", "skipped", "are not server confirmations"):
            self.assertIn(expected, text)
        self.assertNotIn(source["data_epoch"], text)
        self.one_status_call()
        source["stale"] = None; self.response({"status": "online", "learning_digest": source})
        self.assertIn("stale is unknown", self.invoke("report", machine=False)[1])
        self.response({"status": "online"})
        self.assertEqual("Cached local learning totals are unavailable. No refresh was requested.\n",
            self.invoke("report", machine=False)[1])

    def test_capabilities_truthfully_describe_cached_read_and_do_not_contact_shell(self):
        code, result = self.invoke("capabilities")
        self.assertEqual(0, code)
        report = result["data"]["commands"]["report"]
        self.assertEqual("read_only", report["effect"])
        self.assertEqual({"allowed": [7, 30], "default": 7}, report["days"])
        self.assertIn("single status call", report["description"])
        self.assertIn("No account refresh", report["description"])
        self.assertIn("fresh history calculation", report["description"])
        self.run.assert_not_called()

    def test_actual_authored_backend_digest_roundtrips_with_native_count_parity(self):
        from test_learning_digest import LearningDigestTests
        fixture = LearningDigestTests(); fixture.setUp()
        try:
            fixture.fixture.event(); fixture.fixture.event(mode="practice")
            source = fixture.parity(timezone="America/Los_Angeles")
            self.response({"status": "demo", "learning_digest": source})
            code, result = self.invoke("report")
            self.assertEqual(0, code)
            self.assertEqual(source["windows"]["7"], result["data"]["digest"]["window"])
            self.assertEqual(source["generated_at"], result["data"]["digest"]["generated_at"])
            self.one_status_call()
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
