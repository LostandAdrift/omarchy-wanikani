"""Prepare private authored QA repositories; never install or open a desktop plugin."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import native_qa as qa


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for authored audio fixtures")
class NativePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="wanikani-qa-preparation-test-")
        cls.directory = Path(cls.temporary.name)
        cls.source = cls.directory / "source"
        cls.source.mkdir()
        for name in qa.RUNTIME_FILES:
            shutil.copyfile(ROOT / name, cls.source / name)
        for name in qa.RUNTIME_ROOTS:
            shutil.copytree(ROOT / name, cls.source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for args in (["git", "init", "--quiet"], ["git", "add", "."],
                ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Authored fixture"]):
            qa.command(args, cwd=cls.source)
        (cls.source / "backend/untracked-private.txt").write_text("Authored private sentinel must not enter the QA source")
        command = qa.command
        cls.operations = []
        def local_only(args, cwd=None, timeout=30):
            cls.operations.append(args)
            if args[:3] == ["omarchy", "plugin", "validate"]:
                # This suite verifies isolation/fixtures, not the host's plugin manager.
                return "Validation is performed separately by the release checks."
            if args[0].startswith("omarchy"):
                raise AssertionError("Preparation attempted a desktop action")
            return command(args, cwd, timeout)
        with patch.object(qa, "command", side_effect=local_only):
            cls.record = qa.prepare(cls.source, cls.directory / "run")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_preparation_copies_only_tracked_runtime_and_mutes_only_qa_panel(self):
        repository = Path(self.record["repository"])
        panel = (repository / "Panel.qml").read_text()
        self.assertIn("audioOutput: AudioOutput { volume: 0 }", panel)
        self.assertIn("audioOutput: AudioOutput {}", (self.source / "Panel.qml").read_text())
        self.assertFalse((repository / "backend/untracked-private.txt").exists())
        self.assertFalse(any(path.suffix in (".sqlite3", ".mp3") for path in repository.rglob("*")))
        for name, expected in self.record["source_hashes"].items():
            self.assertEqual(expected, hashlib.sha256((self.source / name).read_bytes()).hexdigest())
        self.assertEqual(qa.QA_ID.fullmatch(self.record["id"]).group(), self.record["id"])
        self.assertNotIn(["omarchy", "plugin", "add"], [args[:3] for args in self.operations])
        self.assertEqual(self.record, qa.load_run(Path(self.record["root"]) / "run.json"))

    def test_three_authored_future_words_have_valid_generated_mp3(self):
        state = Path(self.record["state"])
        with closing(sqlite3.connect(state / "demo.sqlite3")) as connection:
            rows = connection.execute("SELECT url,path,size FROM media ORDER BY url").fetchall()
            self.assertEqual(3, len(rows))
            for sid in (14, 15, 16):
                subject = json.loads(connection.execute("SELECT body FROM resources WHERE kind='vocabulary' AND id=?", (str(sid),)).fetchone()[0])
                metadata = subject["data"]["pronunciation_audios"][0]["metadata"]
                self.assertEqual("Authored QA tone", metadata["voice_actor_name"])
                assignment = json.loads(connection.execute("SELECT body FROM resources WHERE kind='assignment' AND json_extract(body,'$.data.subject_id')=?", (sid,)).fetchone()[0])
                self.assertEqual(5, assignment["data"]["srs_stage"])
                self.assertIsNotNone(assignment["data"]["started_at"])
            for url, value, size in rows:
                path = Path(value)
                self.assertTrue(url.startswith("https://files.wanikani.com/qa/authored-tone-"))
                self.assertEqual(state / "media", path.parent)
                self.assertFalse(path.is_symlink())
                self.assertGreater(size, 0)
                self.assertEqual(0o600, path.stat().st_mode & 0o777)
                decoded = subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(0, decoded.returncode, decoded.stderr)
        self.assertIn("not Japanese speech", self.record["listening_fixture"]["audio"])

    def test_generated_worker_blocks_account_and_media_transports(self):
        program = """
import json,sys,urllib.request
sys.path.insert(0,sys.argv[1])
import qa_worker
blocked=0
for attempt in (lambda:qa_worker.worker.Api().request('GET','user'),
                lambda:urllib.request.urlopen('https://files.wanikani.com/qa/authored-tone-14.mp3'),
                lambda:urllib.request.build_opener().open('https://api.wanikani.com/v2/user')):
    try: attempt()
    except qa_worker.worker.UserError: blocked+=1
assert qa_worker.worker.Keyring().get('authored') is None
print(json.dumps({'blocked':blocked}))
"""
        result = subprocess.run([sys.executable, "-B", "-c", program, str(Path(self.record["repository"]) / "backend")],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"blocked": 3}, json.loads(result.stdout))

    def test_actual_local_worker_listening_preserves_graded_fixture_state(self):
        before = qa.graded_fixture_state(self.record)
        program = """
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import qa_worker
messages=[]
worker=qa_worker.worker.Worker(Path(sys.argv[2]),messages.append)
counter=0
def request(method,args={}):
    global counter
    counter+=1;rid='fixture-'+str(counter)
    worker.handle({'v':1,'id':rid,'method':method,'args':args})
    reply=next(message for message in messages if message.get('id')==rid)
    assert reply['ok'],reply
    return reply['data']
try:
    status=request('listen_state')
    assert status['status']['available']==3
    session=request('listen',{'action':'start'})['session']
    assert session['total']==3 and session['subject'] is None
    played=request('listen_media',{'handle':session['media_handle']})
    assert played['session']['revision']>session['revision']
    session=played['session']
    session=request('listen',{'action':'reveal','session_id':session['id'],'revision':session['revision']})['session']
    assert session['subject']['voice']=='Authored QA tone'
    session=request('listen',{'action':'rate','rating':'remembered','session_id':session['id'],'revision':session['revision']})['session']
    print(json.dumps({'completed':session['index'],'local_only':session['local_only']}))
finally:
    worker.stopping=True;worker.readiness.stop();worker.engine.store.close()
"""
        result = subprocess.run([sys.executable, "-B", "-c", program, str(Path(self.record["repository"]) / "backend"), self.record["state"]],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"completed": 1, "local_only": True}, json.loads(result.stdout))
        self.assertEqual(before, qa.graded_fixture_state(self.record))

    def test_missing_new_runtime_helper_is_rejected_before_worker_or_desktop(self):
        original = self.source / "backend/wanikani/listening.py"
        hidden = self.source / "listening-withheld.py"
        original.rename(hidden)
        try:
            with self.assertRaisesRegex(RuntimeError, "Commit or stage"):
                qa.prepare(self.source, self.directory / "missing-runtime")
        finally:
            hidden.rename(original)

    def test_cleanup_rejects_production_id_without_desktop_command(self):
        with patch.object(qa, "command", side_effect=AssertionError("Unexpected desktop command")):
            with self.assertRaisesRegex(RuntimeError, "non-QA"):
                qa.cleanup({"id": qa.PRODUCTION_ID})

    def test_locking_or_unknown_desktop_defers_hosted_installation(self):
        for state in ({'locked': True, 'requested': True, 'pending': True, 'sessionLocked': False}, {}):
            with self.subTest(state=state), patch.object(qa, 'command', return_value=json.dumps(state)) as command:
                with self.assertRaisesRegex(RuntimeError, 'deferred'):
                    qa.hosted(self.record)
                command.assert_called_once_with(['omarchy-shell', 'lock', 'status'])

    def test_lock_beginning_during_scenario_defers_cleanup_and_preserves_owned_marker(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-qa-cleanup-") as temporary:
            directory = Path(temporary)
            run = {"id": self.record["id"], "root": str(directory / "run")}
            Path(run["root"]).mkdir()
            home = directory / "home"
            installed = home / ".config/omarchy/plugins" / run["id"]
            installed.mkdir(parents=True)
            marker = installed / ".native-qa.json"
            marker.write_text(json.dumps(run))
            for state in ({"locked": True, "requested": True, "pending": True, "sessionLocked": False}, {}):
                with self.subTest(state=state), patch.object(Path, "home", return_value=home), \
                        patch.object(qa, "command", return_value=json.dumps(state)) as command:
                    with self.assertRaisesRegex(RuntimeError, "cleanup is deferred"):
                        qa.cleanup(run)
                    command.assert_called_once_with(["omarchy-shell", "lock", "status"])
                    self.assertEqual("cleanup-deferred", json.loads((Path(run["root"]) / "run.json").read_text())["status"])
                    self.assertEqual({"id": run["id"], "root": run["root"]}, json.loads(marker.read_text()))
            unlocked = {key: False for key in ("locked", "requested", "pending", "sessionLocked")}
            with patch.object(Path, "home", return_value=home), \
                    patch.object(qa, "command", return_value=json.dumps(unlocked)) as command:
                qa.cleanup(run)
                self.assertEqual([["omarchy-shell", "lock", "status"],
                    ["omarchy", "plugin", "remove", run["id"], "--yes"]], [call.args[0] for call in command.call_args_list])
                self.assertEqual("removed", run["status"])


if __name__ == "__main__":
    unittest.main()
