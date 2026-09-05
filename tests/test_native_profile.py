"""Authored proc and saved-report fixtures; never sample or change the host."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import profile_native as profile


def stat_line(pid=123, start=1000):
    values = ["0"] * 50
    values[0], values[1] = "S", "42"
    values[11], values[12] = "70", "30"
    values[13], values[14] = "9000", "9000"  # Child CPU must not count.
    values[19], values[21] = str(start), "12"
    return f"{pid} (PRIVATE name (with) parentheses)) " + " ".join(values)


def sample_value(ticks=100, start=1000):
    return {"pid": 123, "start_ticks": start, "cpu_ticks": ticks,
            "rss_bytes": 4096, "pss_bytes": 2048, "private_bytes": 1024}


class ProcParserTests(unittest.TestCase):
    def test_stat_ignores_private_name_and_child_cpu(self):
        result = profile.parse_stat(stat_line())
        self.assertEqual({"pid": 123, "ppid": 42, "cpu_ticks": 100,
                          "start_ticks": 1000, "rss_pages": 12, "state": "S"}, result)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_truncated_stat_and_negative_counters_are_rejected(self):
        for content in ("123 (short) S 1", stat_line(start=-1)):
            with self.subTest(content=content), self.assertRaises((ValueError, IndexError)):
                profile.parse_stat(content)

    def test_rollup_and_full_smaps_units_and_private_hugepages(self):
        block = "PRIVATE memory mapping\nRss: 10 kB\nPss: 6 kB\nPrivate_Clean: 2 kB\nPrivate_Dirty: 1 kB\nPrivate_Hugetlb: 4 kB\nShared_Clean: 7 kB\n"
        self.assertEqual({"rss_bytes": 10240, "pss_bytes": 6144, "private_bytes": 7168}, profile.parse_memory(block))
        self.assertEqual({"rss_bytes": 20480, "pss_bytes": 12288, "private_bytes": 14336}, profile.parse_memory(block * 2))

    def test_missing_memory_is_unknown_and_malformed_units_are_rejected(self):
        self.assertEqual({"rss_bytes": 1024, "pss_bytes": None, "private_bytes": None}, profile.parse_memory("Rss: 1 kB\n"))
        for content in ("Rss: 99 bytes", "Private_Dirty: -1 kB", "Pss: private-data kB"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                profile.parse_memory(content)

    def test_discovery_excludes_qa_worker_python_commands_and_ipc_clients(self):
        worker = Path("/fixture/production/backend/worker.py")
        shell = Path("/fixture/omarchy/shell")
        self.assertEqual("worker", profile.classify(["python3", "-B", str(worker), "--state-dir", "PRIVATE"], {worker}, shell))
        for argv in (["python3", "-c", "PRIVATE", str(worker)],
                     ["python3", "/fixture/qa/backend/qa_worker.py"],
                     ["quickshell", "ipc", "-p", str(shell), "call", "PRIVATE"]):
            self.assertIsNone(profile.classify(argv, {worker}, shell))
        self.assertEqual("shared_shell", profile.classify(["quickshell", "-n", "-p", str(shell)], {worker}, shell))
        self.assertEqual("shared_shell", profile.classify(["qs", "--path=" + str(shell)], {worker}, shell))

    def test_unavailable_smaps_preserves_approximate_rss_without_inventing_pss(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            process = proc / "123"
            process.mkdir()
            (process / "stat").write_text(stat_line())
            result = profile.observation(proc, 123, 4096)
        self.assertEqual(12 * 4096, result["rss_bytes"])
        self.assertIsNone(result["pss_bytes"])
        self.assertIsNone(result["private_bytes"])
        self.assertEqual("stat", result["memory_source"])
        self.assertEqual("unavailable", result["smaps_status"])

    def test_zombie_is_reported_as_exited_even_before_parent_reaps_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            process = proc / "123"
            process.mkdir()
            (process / "stat").write_text(stat_line().replace(") S ", ") Z "))
            with self.assertRaises(FileNotFoundError):
                profile.observation(proc, 123, 4096)

    def test_cpu_is_percent_of_one_core_and_tick_resolution_is_explicit(self):
        result = profile.summarize([sample_value(), sample_value(110)], 20, 100)
        self.assertEqual(0.5, result["cpu_percent_one_core"])
        self.assertEqual(0.05, result["cpu_tick_resolution_percent_one_core"])
        self.assertEqual(10, result["cpu_ticks_delta"])

    def test_reuse_restart_or_exit_invalidates_cpu(self):
        cases = [([sample_value(), sample_value(200, start=2000)], None),
                 ([sample_value(), sample_value(90)], None),
                 ([sample_value(), sample_value(101)], "process_exited")]
        for samples, invalid in cases:
            with self.subTest(invalid=invalid):
                result = profile.summarize(samples, 20, 100, invalid)
                self.assertEqual("invalid", result["status"])
                self.assertIsNone(result["cpu_percent_one_core"])
        self.assertEqual("not_running", profile.summarize([], 20, 100)["status"])


class ProfileComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        shell = profile.summarize([sample_value(), sample_value(110)], 20, 100)
        worker = copy.deepcopy(shell)
        worker["identity"]["pid"] = 456
        self.reports = [{"format": 1, "valid": True, "processes": {
            "shared_shell": copy.deepcopy(shell), "worker": copy.deepcopy(worker)}} for _ in range(3)]
        self.reports[1]["processes"]["worker"] = {"status": "not_running"}

    def compare(self):
        paths = []
        for index, report in enumerate(self.reports):
            path = self.directory / f"{index}.json"
            path.write_text(json.dumps(report))
            paths.append(path)
        return profile.compare(paths)

    def test_comparison_retains_negative_noise_and_unknown_memory(self):
        for report, cpu in zip(self.reports, (0.4, 0.5, 0.7)):
            report["processes"]["shared_shell"]["cpu_percent_one_core"] = cpu
        self.reports[1]["processes"]["shared_shell"]["memory"]["pss_bytes"] = None
        result = self.compare()
        cpu = result["shared_shell_cpu_percent_one_core"]
        self.assertAlmostEqual(-0.1, cpu["enabled_before_minus_disabled"])
        self.assertAlmostEqual(0.2, cpu["enabled_after_minus_disabled"])
        self.assertAlmostEqual(0.3, cpu["enabled_spread"])
        self.assertIsNone(result["shared_shell_memory_median_bytes"]["pss_bytes"])

    def test_shell_restart_cannot_be_used_as_a_baseline(self):
        self.reports[2]["processes"]["shared_shell"]["identity"]["start_ticks"] += 1
        with self.assertRaisesRegex(profile.ProfileError, "restarted"):
            self.compare()

    def test_disabled_baseline_must_actually_have_no_worker(self):
        self.reports[1]["processes"]["worker"] = self.reports[0]["processes"]["worker"]
        with self.assertRaisesRegex(profile.ProfileError, "worker absent"):
            self.compare()

    def test_imported_extra_fields_are_not_reexported_and_nonnumeric_metrics_fail(self):
        for report in self.reports:
            report["processes"]["shared_shell"]["identity"]["private_path"] = "PRIVATE"
        self.assertNotIn("PRIVATE", json.dumps(self.compare()))
        self.reports[0]["processes"]["worker"]["cpu_percent_one_core"] = "PRIVATE"
        with self.assertRaisesRegex(profile.ProfileError, "numeric metric"):
            self.compare()

    def test_output_is_private_and_replaces_a_link_without_touching_target(self):
        victim = self.directory / "unrelated.txt"
        victim.write_text("PRIVATE unrelated content")
        destination = self.directory / "profile.json"
        destination.symlink_to(victim)
        profile.write_report({"format": 1}, destination)
        self.assertEqual("PRIVATE unrelated content", victim.read_text())
        self.assertFalse(destination.is_symlink())
        self.assertEqual(0o600, destination.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
