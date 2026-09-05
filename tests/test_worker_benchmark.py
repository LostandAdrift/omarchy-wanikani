"""The developer benchmark really completes one durable batch over stdio."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wanikani_worker_benchmark", ROOT / "tools/benchmark_worker.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class WorkerBenchmarkTests(unittest.TestCase):
    def test_five_subjects_share_one_completed_session_and_measure_both_completions(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "fixture"
            result = benchmark.benchmark(ROOT, directory, 1, "authored five-subject test", 5)
            self.assertEqual(5, result["completed_authored_reviews"])
            self.assertEqual(5, result["batch_size"])
            self.assertEqual("draft", result["operations"]["subject_advance"]["queued_command"])
            self.assertEqual("session", result["operations"]["final_subject_advance"]["queued_command"])
            for operation in result["operations"].values():
                self.assertEqual(1, operation["response"]["samples"])
                self.assertEqual(1, operation["pipeline_drain"]["samples"])
            with sqlite3.connect((directory / "demo.sqlite3").as_uri() + "?mode=ro", uri=True) as database:
                sessions = database.execute("SELECT body FROM sessions").fetchall()
                self.assertEqual(1, len(sessions))
                session = json.loads(sessions[0][0])
                self.assertEqual(("complete", 5), (session["phase"], session["completed"]))
                self.assertEqual(5, len({item["subject_id"] for item in session["queue"]}))
                self.assertEqual(5, database.execute("SELECT COUNT(*) FROM outbox WHERE state='confirmed'").fetchone()[0])
                self.assertEqual(1, database.execute("SELECT COUNT(DISTINCT json_extract(body,'$.session_id')) FROM outbox").fetchone()[0])
            self.assertGreater(result["command_journal"]["response_bytes"], 0)

    def test_single_subject_compatibility_has_only_end_of_batch_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = benchmark.benchmark(ROOT, Path(temporary) / "fixture", 1, "authored single-subject test", 1)
        self.assertEqual(1, result["completed_authored_reviews"])
        self.assertNotIn("subject_advance", result["operations"])
        self.assertIn("final_subject_advance", result["operations"])

    def test_cli_batch_bounds_fail_before_creating_a_worker(self):
        for size in ("0", "21"):
            result = subprocess.run([sys.executable, str(ROOT / "tools/benchmark_worker.py"),
                "--batch-size", size], capture_output=True, text=True, timeout=10)
            self.assertEqual(2, result.returncode)
            self.assertIn("--batch-size must be between 1 and 20", result.stderr)
            self.assertEqual("", result.stdout)

    def test_worker_bootstrap_blocks_network_and_keyring_helpers(self):
        for action in ("urllib.request.urlopen('https://fixture.invalid/never-contacted')", "Keyring().get('authored-account')"):
            script = benchmark.RUN_WORKER.replace("raise SystemExit(worker.main())", action)
            with tempfile.TemporaryDirectory() as temporary:
                result = subprocess.run([sys.executable, "-c", script, str(ROOT), temporary],
                    capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("Developer benchmark forbids network/keyring/subprocess access", result.stderr)
                self.assertEqual([], list(Path(temporary).iterdir()))


if __name__ == "__main__":
    unittest.main()
