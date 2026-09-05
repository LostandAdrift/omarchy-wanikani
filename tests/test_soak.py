"""Checks the developer-only randomized harness, never a real service."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("wanikani_developer_soak", Path(__file__).resolve().parents[1] / "tools/soak.py")
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


class SoakToolTests(unittest.TestCase):
    def test_seed_reproduces_actions_ids_and_outcomes(self):
        first = soak.run_seed(19, 60)
        second = soak.run_seed(19, 60)
        self.assertTrue(first["passed"], first.get("error"))
        self.assertEqual(first, second)
        self.assertGreater(first["counts"]["answer"], 0)
        self.assertGreater(first["counts"]["restarts"], 0)

    def test_failure_retains_seed_and_authored_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(soak.Harness, "assert_invariants", side_effect=AssertionError("Injected harness check")):
                result = soak.run_seed(27, 10, directory)
            self.assertFalse(result["passed"])
            saved = json.loads(Path(result["failure_trace"]).read_text())
            self.assertEqual(27, saved["seed"])
            self.assertEqual("Injected harness check", saved["error"])
            self.assertEqual(1, len(saved["trace"]))
            self.assertEqual(0, saved["trace"][0]["step"])

    def test_network_is_blocked_even_if_a_future_harness_action_attempts_it(self):
        def tries_network(self, index):
            import urllib.request
            urllib.request.urlopen("https://invalid.example/never-requested")
        with patch.object(soak.Harness, "step", tries_network):
            result = soak.run_seed(1, 1)
        self.assertFalse(result["passed"])
        self.assertIn("cannot use network or subprocesses", result["error"])

    def test_cli_step_and_seed_counts_have_finite_limits(self):
        for value in ("0", "5001"):
            with self.assertRaises(soak.argparse.ArgumentTypeError):
                soak.bounded_number(5000)(value)
        self.assertEqual(500, soak.bounded_number(5000)("500"))

    def test_replay_oracle_still_rejects_newer_identity_and_changed_grading_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            harness = soak.Harness(9, temporary)
            try:
                harness.engine.start("practice", 1, [2])
                original = harness.engine.command("oracle-answer", "answer", {"text": "wrong"})
                for field, value in (("id", "different-session"), ("revision", 999999), ("errors", 0)):
                    changed = copy.deepcopy(original)
                    changed[field] = value
                    with self.subTest(field=field), self.assertRaises(AssertionError):
                        harness.assert_replayed_reply(original, changed)
                changed = copy.deepcopy(original)
                changed["feedback"]["correct"] = True
                with self.assertRaises(AssertionError):
                    harness.assert_replayed_reply(original, changed)
            finally:
                harness.store.close()


if __name__ == "__main__":
    unittest.main()
