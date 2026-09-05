"""Frozen-verifier tests use tiny authored Git repositories and fake tools."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verification_runner", ROOT / "tools/verify.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


TOOL = '''#!__PYTHON__
import json, os, pathlib, sys, time
args = sys.argv[1:]
stage = 'python' if '-m' in args else 'manifest' if args[0] == 'plugin' else 'qmllint' if '--json' in args else 'core_qt'
__EXTRA__
if stage == 'python':
    print('Ran 2 tests in 0.001s\\n\\nOK')
elif stage == 'manifest':
    print('Valid authored manifest')
elif stage == 'qmllint':
    paths = args[args.index('-I') + 2:]
    data = {'revision':4,'files':[{'filename':path,'success':True,'warnings':[]} for path in paths]}
    pathlib.Path(args[args.index('--json') + 1]).write_text(json.dumps(data))
else:
    print('PASS   : Authored::test_example()')
    print('Totals: 3 passed, 0 failed, 0 skipped, 0 blacklisted, 1ms')
'''


class VerificationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wanikani-verifier-tests-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repo = self.directory / "checkout"
        self.repo.mkdir()
        self.output = self.directory / "reports"
        self.output.mkdir()
        self.shell = self.directory / "installed-shell"
        self.shell.mkdir()
        self.shell_patch = patch.object(runner, "SHELL_IMPORT", self.shell).start()
        self.addCleanup(patch.stopall)
        self.git("init", "--quiet")
        self.write("manifest.json", json.dumps({"id":runner.PLUGIN_ID,"version":"0.0.1-authored"}))
        self.write("Panel.qml", "import QtQuick\nItem {}\n")
        self.write("qml/Example.qml", "import QtQuick\nItem {}\n")
        self.write("tests/test_example.py", "import unittest\nclass Check(unittest.TestCase):\n def test_example(self): self.assertEqual(1, 1)\n")
        self.write("tests/qml/tst_Example.qml", "import QtTest\nTestCase { name: 'Example' }\n")
        self.revision = self.commit()
        self.tool = self.directory / "mock-check"
        self.configure_tool()

    def git(self, *arguments):
        result = subprocess.run(["git", "-C", str(self.repo), *arguments], capture_output=True, text=True,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM":"1", "GIT_CONFIG_GLOBAL":os.devnull,
                "GIT_AUTHOR_NAME":"Authored fixture", "GIT_AUTHOR_EMAIL":"fixture@example.invalid",
                "GIT_COMMITTER_NAME":"Authored fixture", "GIT_COMMITTER_EMAIL":"fixture@example.invalid"}, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Authored fixture")
        return self.git("rev-parse", "HEAD")

    def configure_tool(self, extra=""):
        self.tool.write_text(TOOL.replace("__PYTHON__", sys.executable).replace("__EXTRA__", extra))
        self.tool.chmod(0o700)

    def verify(self, revision=None, tools=None):
        with patch.object(runner, "discover_tools", return_value=tools or {name:str(self.tool) for name in runner.STAGES}):
            return runner.verify(self.repo, revision or self.revision, self.output, timeout=5)

    def test_frozen_revision_hashes_readonly_archive_and_source_unchanged(self):
        self.write("Panel.qml", "uncommitted content must not be verified\n")
        self.write("private-untracked.txt", "authored private fixture")
        before = self.git("status", "--porcelain=v1")
        report = self.verify()
        self.assertEqual("passed", report["status"], report)
        self.assertEqual(self.revision, report["revision"])
        self.assertEqual(self.git("rev-parse", self.revision + "^{tree}"), report["tree"])
        self.assertEqual("0.0.1-authored", report["plugin_version"])
        self.assertEqual("invoking_file_outside_archive", report["runner_source"]["scope"])
        self.assertEqual(runner.RUNNER_SHA256, report["runner_source"]["sha256"])
        source = Path(report["archive"])
        self.assertEqual("import QtQuick\nItem {}\n", (source / "Panel.qml").read_text())
        self.assertFalse((source / "private-untracked.txt").exists())
        self.assertEqual(before, self.git("status", "--porcelain=v1"))
        self.assertEqual("uncommitted content must not be verified\n", (self.repo / "Panel.qml").read_text())
        self.assertEqual({"before":"passed","after":"passed","tracked_files":5}, report["integrity"])
        self.assertEqual(0o700, source.parent.stat().st_mode & 0o777)
        self.assertEqual(0o600, Path(report["report"]).stat().st_mode & 0o777)
        for path in [source, *source.rglob("*")]:
            self.assertEqual(0, path.stat().st_mode & 0o222)
        for stage in report["stages"]:
            self.assertEqual("passed", stage["status"])
            self.assertGreaterEqual(stage["duration_seconds"], 0)
            self.assertEqual(0o600, Path(stage["log"]).stat().st_mode & 0o777)
        lint = report["stages"][2]["argv"]
        self.assertIn("--ignore-settings", lint)
        self.assertNotIn("--fix", lint)
        self.assertNotIn(source, Path(lint[lint.index("--json") + 1]).parents)

    def test_explicit_tree_revision_supported_and_blob_rejected(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assertEqual("tree", self.verify(tree)["revision_kind"])
        blob = self.git("rev-parse", "HEAD:Panel.qml")
        with self.assertRaises(runner.VerificationError):
            runner.resolve(self.repo, blob)

    def test_revision_is_one_argv_value_after_end_of_options(self):
        observed = []
        original = runner.subprocess.run
        def call(argv, **kwargs):
            observed.append(argv)
            return original(argv, **kwargs)
        with patch.object(runner.subprocess, "run", side_effect=call):
            with self.assertRaises(runner.VerificationError):
                runner.resolve(self.repo, "--output=/tmp/never-created-by-verifier")
        command = next(argv for argv in observed if "--verify" in argv)
        self.assertEqual(["--end-of-options", "--output=/tmp/never-created-by-verifier"], command[-2:])

    def test_all_tracked_symlinks_rejected_before_archive(self):
        (self.repo / "external").symlink_to(self.output, target_is_directory=True)
        self.revision = self.commit()
        with self.assertRaisesRegex(runner.VerificationError, "regular files"):
            self.verify()
        self.assertEqual([], list(self.output.iterdir()))

    def test_output_rejects_repository_installed_plugin_and_symlink_escape(self):
        alias = self.directory / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        installed = self.directory / "config" / "omarchy" / "plugins" / "example"
        installed.mkdir(parents=True)
        for parent in (self.repo, self.repo / "tests", alias, installed):
            with self.subTest(parent=parent), self.assertRaises(runner.VerificationError):
                runner.output_directory(parent, self.repo)
        self.assertEqual([], list(self.output.iterdir()))

    def test_archive_export_ignore_cannot_silently_omit_tracked_files(self):
        self.write(".gitattributes", "Panel.qml export-ignore\n")
        self.revision = self.commit()
        report = self.verify()
        self.assertEqual("failed", report["status"])
        self.assertIsNone(report["integrity"]["before"])
        self.assertTrue(all(stage["status"] == "not_run" for stage in report["stages"]))

    def test_tar_hardlink_and_traversal_rejected_before_extract(self):
        _, _, tree, _ = runner.resolve(self.repo, self.revision)
        expected = runner.entries(self.repo, tree)
        for name, kind in (("../escaped", tarfile.REGTYPE), ("linked", tarfile.LNKTYPE)):
            with self.subTest(name=name):
                data = io.BytesIO()
                with tarfile.open(fileobj=data, mode="w") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "../escaped"
                    archive.addfile(member)
                output = runner.output_directory(self.output, self.repo)
                with patch.object(runner, "git", return_value=data.getvalue()):
                    with self.assertRaises(runner.VerificationError):
                        runner.extract(self.repo, tree, expected, output)
                self.assertEqual([], list((output / "source").iterdir()))
        self.assertFalse((self.output / "escaped").exists())

    def test_mutation_detected_and_remaining_stages_not_run(self):
        self.configure_tool("if stage == 'python':\n    target=pathlib.Path('Panel.qml'); target.chmod(0o600); target.write_text('changed'); target.chmod(0o400)")
        report = self.verify()
        self.assertEqual("failed", report["status"])
        self.assertEqual("failed", report["integrity"]["after"])
        self.assertTrue(all(stage["status"] == "not_run" for stage in report["stages"][1:]))
        self.assertEqual("import QtQuick\nItem {}\n", (self.repo / "Panel.qml").read_text())

    def test_executable_flag_changes_fail_even_when_bytes_match(self):
        self.write("script.py", "print('authored')\n")
        (self.repo / "script.py").chmod(0o700)
        self.revision = self.commit()
        for file, mode in (("script.py", 0o400), ("Panel.qml", 0o500)):
            with self.subTest(file=file):
                self.configure_tool("if stage == 'python': pathlib.Path(" + repr(file) + ").chmod(" + str(mode) + ")")
                report = self.verify()
                self.assertEqual("failed", report["status"])
                self.assertEqual("failed", report["integrity"]["after"])

    def test_failure_preserves_logs_and_continues_independent_checks(self):
        self.configure_tool("if stage == 'python':\n    print('Ran 2 tests in 0.001s\\n\\nFAILED (failures=1)'); sys.exit(1)")
        report = self.verify()
        self.assertEqual("failed", report["status"])
        self.assertEqual(1, report["stages"][0]["summary"]["failures"])
        self.assertTrue(all(s["status"] == "passed" for s in report["stages"][1:]))
        self.assertIn("FAILED", Path(report["stages"][0]["log"]).read_text())
        self.assertEqual("passed", report["integrity"]["after"])

    def test_missing_required_tools_and_zero_checks_never_pass(self):
        tools = {name:str(self.tool) for name in runner.STAGES}
        tools["core_qt"] = None
        report = self.verify(tools=tools)
        self.assertEqual("failed", report["status"])
        self.assertEqual("missing_dependency", report["stages"][3]["status"])
        self.assertEqual(["core_qt"], report["stages"][3]["missing_tools"])
        self.configure_tool("if stage == 'python':\n    print('Ran 0 tests in 0.000s\\n\\nOK'); sys.exit(0)")
        self.assertEqual("incomplete", self.verify()["stages"][0]["status"])

    def test_failed_or_unknown_python_ending_cannot_pass_with_exit_zero(self):
        for ending, status in (("FAILED", "failed"), ("UNKNOWN", "incomplete")):
            with self.subTest(ending=ending):
                self.configure_tool("if stage == 'python':\n    print(" + repr("Ran 2 tests in 0.001s\n\n" + ending) + "); sys.exit(0)")
                report = self.verify()
                self.assertEqual("failed", report["status"])
                self.assertEqual(status, report["stages"][0]["status"])
        self.configure_tool("if stage == 'python':\n    print('Ran 1 test in 0.001s\\n\\nOK\\nRan 2 tests in 0.001s\\n\\nUNKNOWN'); sys.exit(0)")
        self.assertEqual("incomplete", self.verify()["stages"][0]["status"])

    def test_expected_failure_summary_is_not_misread_as_failure(self):
        self.configure_tool("if stage == 'python':\n    print('Ran 2 tests in 0.001s\\n\\nOK (expected failures=1)'); sys.exit(0)")
        stage = self.verify()["stages"][0]
        self.assertEqual("passed_with_expected_failures", stage["status"])
        self.assertEqual(1, stage["summary"]["expected_failures"])
        self.assertEqual(0, stage["summary"]["failures"])

    def test_malformed_manifest_is_reported_without_traceback(self):
        self.write("manifest.json", "[]")
        self.revision = self.commit()
        report = self.verify()
        self.assertEqual("failed", report["status"])
        self.assertIn("manifest", report["notice"])
        self.assertTrue(all(s["status"] == "not_run" for s in report["stages"]))

    def test_qt_init_cleanup_only_is_not_substantive_coverage(self):
        self.configure_tool("if stage == 'core_qt':\n    print('PASS   : Empty::initTestCase()\\nPASS   : Empty::cleanupTestCase()\\nTotals: 2 passed, 0 failed, 0 skipped, 0 blacklisted, 1ms'); sys.exit(0)")
        self.assertEqual("incomplete", self.verify()["stages"][3]["status"])

    def test_manifest_failure_does_not_claim_validated_true(self):
        self.configure_tool("if stage == 'manifest': sys.exit(1)")
        report = self.verify()
        self.assertEqual("failed", report["stages"][1]["status"])
        self.assertIs(False, report["stages"][1]["summary"]["validated"])

    def test_skips_and_lint_warnings_are_reported_explicitly(self):
        self.configure_tool("""if stage == 'python':
    print('Ran 2 tests in 0.001s\\n\\nOK (skipped=1)'); sys.exit(0)
if stage == 'qmllint':
    paths=args[args.index('-I')+2:]
    rows=[{'filename':p,'success':False,'warnings':[{'type':'warning','message':'authored warning'},{'type':'info','message':'authored info'}]} for p in paths]
    pathlib.Path(args[args.index('--json')+1]).write_text(json.dumps({'files':rows})); sys.exit(0)
""")
        report = self.verify()
        self.assertEqual("passed", report["status"])
        self.assertEqual("passed_with_skips", report["stages"][0]["status"])
        self.assertEqual(1, report["stages"][0]["summary"]["skipped"])
        self.assertEqual("passed_with_warnings", report["stages"][2]["status"])
        self.assertEqual(2, report["stages"][2]["summary"]["warnings"])
        self.assertEqual(2, report["stages"][2]["summary"]["info"])

    def test_missing_lint_json_does_not_use_exit_zero_as_proof(self):
        self.configure_tool("if stage == 'qmllint': sys.exit(0)")
        report = self.verify()
        self.assertEqual("failed", report["status"])
        self.assertEqual("incomplete", report["stages"][2]["status"])

    def test_clean_environment_omits_host_and_optin_flags(self):
        self.configure_tool("""if stage == 'python':
    forbidden=('WANIKANI_DECODER_QA','FUTURE_HOST_QA','DBUS_SESSION_BUS_ADDRESS','DISPLAY','WAYLAND_DISPLAY',
        'PULSE_SERVER','PIPEWIRE_REMOTE','HYPRLAND_INSTANCE_SIGNATURE','SECRET_API_TOKEN','PYTHONSTARTUP')
    assert all(key not in os.environ for key in forbidden)
    assert os.environ['QT_QPA_PLATFORM']=='offscreen'
    assert os.environ['QT_QUICK_CONTROLS_STYLE']=='Basic'
    assert os.environ['PYTHONDONTWRITEBYTECODE']=='1'
    for key in ('HOME','XDG_RUNTIME_DIR','XDG_CONFIG_HOME','TMPDIR'):
        path=pathlib.Path(os.environ[key]); assert path.stat().st_mode&0o777==0o700
        assert pathlib.Path.cwd() not in path.parents
""")
        with patch.dict(os.environ, {key:"AUTHORED SECRET" for key in ("WANIKANI_DECODER_QA", "FUTURE_HOST_QA",
                "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY", "PULSE_SERVER", "PIPEWIRE_REMOTE",
                "HYPRLAND_INSTANCE_SIGNATURE", "SECRET_API_TOKEN", "PYTHONSTARTUP")}):
            report = self.verify()
        self.assertEqual("passed", report["status"], report)

    def test_cancelled_stage_writes_final_report_and_does_not_start_more(self):
        with patch.object(runner, "execute", return_value={"status":"cancelled","exit_code":-signal.SIGTERM,"duration_seconds":0.1}):
            report = self.verify()
        self.assertEqual("cancelled", report["status"])
        self.assertTrue(all(s["status"] == "not_run" for s in report["stages"][1:]))
        self.assertIsNotNone(report["finished_at"])
        self.assertEqual(report, json.loads(Path(report["report"]).read_text()))
        self.assertEqual("passed", report["integrity"]["after"])

    def test_timeout_terminates_owned_child_and_records_nonpass(self):
        log = self.directory / "timeout.log"
        result = runner.execute([sys.executable, "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(30)"],
            self.directory, {"PATH":os.defpath}, log, .1)
        self.assertEqual("timed_out", result["status"])
        self.assertEqual(-signal.SIGTERM, result["exit_code"])
        self.assertLess(result["duration_seconds"], 2)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(log.read_text().strip()), 0)

    def test_keyboard_interrupt_terminates_owned_child(self):
        original = runner.subprocess.Popen
        def spawn(*args, **kwargs):
            self.assertTrue(kwargs["start_new_session"])
            process = original(*args, **kwargs)
            wait = process.wait
            calls = 0
            def interrupted(timeout=None):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise KeyboardInterrupt
                return wait(timeout=timeout)
            process.wait = interrupted
            return process
        with patch.object(runner.subprocess, "Popen", side_effect=spawn):
            result = runner.execute([sys.executable,"-c","import time; time.sleep(30)"], self.directory,
                {"PATH":os.defpath}, self.directory / "interrupt.log", 5)
        self.assertEqual("cancelled", result["status"])
        self.assertEqual(-signal.SIGTERM, result["exit_code"])

    def test_revision_required_and_timeout_validated_before_work(self):
        for args in ([], ["--revision","HEAD","--timeout","0"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.main(args)
            self.assertEqual(2, error.exception.code)
        self.assertEqual([], list(self.output.iterdir()))

    def test_cli_prints_only_status_hash_and_paths(self):
        output = io.StringIO()
        with patch.object(runner,"discover_tools",return_value={name:str(self.tool) for name in runner.STAGES}), redirect_stdout(output):
            code = runner.main(["--repository",str(self.repo),"--revision",self.revision,"--output-parent",str(self.output)])
        self.assertEqual(0, code)
        self.assertEqual(3, len(output.getvalue().splitlines()))
        self.assertIn("Verification passed: " + self.revision, output.getvalue())


if __name__ == "__main__":
    unittest.main()
