"""The actual QML status producer and CLI consumer share a private-free schema."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_agent_cli import cli


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
COUNTS = dict(total=4, checked=4, ready=4, missing_text=0, missing_images=0,
    audio_total=3, audio_cached=3, total_complete=True)


def fixture():
    return {"schemaVersion": 1, "status": "online", "ready": True, "connected": True,
        "reviews": 4, "lessons": 4, "pending": 2, "attention": 1, "listening_due": None,
        "readiness": {"complete": True, "checking": False, "checked_at": "2026-09-05T09:00:00.123456Z",
            **{mode: dict(COUNTS) for mode in cli.READINESS_GROUPS}},
        "sync": {"stage": "idle", "active": False, "completed": 0, "total": None},
        "outbox_counts": {"pending": 1, "inflight": 0, "confirmed": 12, "conflicted": 0,
            "uncertain": 1, "blocked": 0, "discarded": 0},
        "cache": {"files": 50, "bytes": 1000, "subjects": 100, "limit_bytes": 1024 * 1024 * 1024}}


QML = r'''
import QtQuick
import QtTest
Item {
  StatusCore { id: service }
  TestCase {
    name: "OperationalStatus"
    function group() { return {total:4,checked:4,ready:4,missing_text:0,missing_images:0,audio_total:3,audio_cached:2,total_complete:true,
      subject_id:123,meaning:"PRIVATE ANSWER",notes:"PRIVATE NOTES",path:"/private/cache"} }
    function init() {failOnWarning(/.*/);service.snapshot={};service.rhythm=null;service.calls=0}
    function test_actual_status_is_cached_typed_and_private_free() {
      service.snapshot={status:"online",connected:true,reviews:4,lessons:4,pending:2,attention:1,
        username:"PRIVATE ACCOUNT",token:"PRIVATE TOKEN",settings:{cache_limit_mb:1024},
        session:{draft:"PRIVATE DRAFT"},last_sync:"2026-09-05T09:00:00.123456Z",
        saved_sessions:{reviews:{question:"PRIVATE ANSWER"}},
        readiness:{complete:true,checking:false,checked_at:"2026-09-05T09:00:00.123456Z",
          reviews:group(),lessons:group(),upcoming_reviews:group(),message:"PRIVATE MESSAGE"},
        sync_progress:{stage:"submitting",active:true,completed:2,total:4,message:"PRIVATE ERROR"},
        cache:{files:50,bytes:1073741824,subjects:100,path:"/private/cache"},
        outbox_counts:{pending:1,inflight:0,confirmed:12,conflicted:0,uncertain:1,blocked:0,discarded:0,secret:"PRIVATE TOKEN"}}
      var before=JSON.stringify(service.snapshot)
      var text=service.status();var value=JSON.parse(text)
      compare(service.calls,0);compare(JSON.stringify(service.snapshot),before)
      verify(text.indexOf("PRIVATE")<0);verify(text.indexOf("/private/")<0);verify(text.indexOf("subject_id")<0)
      compare(value.readiness.reviews.ready,4);compare(value.readiness.upcoming_reviews.audio_cached,2)
      compare(value.cache.limit_bytes,1073741824);compare(value.cache.bytes,1073741824)
      compare(value.outbox_counts.uncertain,1);compare(value.sync.stage,"submitting")
      compare(value.listening_due,null)
      console.log("OPERATIONAL_CURRENT "+text)
    }
    function test_old_service_state_keeps_new_sections_unknown() {
      service.snapshot={status:"starting",reviews:0,lessons:0}
      var text=service.status();var value=JSON.parse(text)
      for(var name of ["readiness","sync","cache","outbox_counts","listening_due"])compare(value[name],null,name)
      compare(service.calls,0)
      console.log("OPERATIONAL_OLD "+text)
    }
    function test_malformed_nested_data_cannot_escape_as_messages_or_coerced_counts() {
      service.snapshot={status:"online",settings:{cache_limit_mb:true},cache:{files:true,bytes:9007199254740992,subjects:-1},
        sync_progress:{stage:"PRIVATE TOKEN",active:1,completed:"PRIVATE ANSWER",total:-1},
        outbox_counts:{pending:true,uncertain:-1},
        readiness:{complete:"PRIVATE",checking:1,checked_at:"PRIVATE TIME",reviews:["PRIVATE"],lessons:null,
          upcoming_reviews:{total:1.5,checked:true,ready:-1,total_complete:1}}}
      var text=service.status();var value=JSON.parse(text)
      verify(text.indexOf("PRIVATE")<0)
      compare(value.sync,{stage:"unknown",active:null,completed:null,total:null})
      compare(value.cache,{files:null,subjects:null,bytes:null,limit_bytes:null})
      compare(value.readiness.checked_at,null);compare(value.readiness.reviews,null)
      compare(value.readiness.upcoming_reviews.total,null);compare(value.readiness.upcoming_reviews.total_complete,null)
      compare(value.outbox_counts.pending,null)
      console.log("OPERATIONAL_MALFORMED "+text)
    }
    function test_null_and_array_sections_are_absent_without_scans() {
      for(var malformed of [null,[],"PRIVATE",1,true]) {
        service.snapshot={status:"online",readiness:malformed,cache:malformed,sync_progress:malformed,outbox_counts:malformed}
        var value=JSON.parse(service.status())
        for(var name of ["readiness","sync","cache","outbox_counts"])compare(value[name],null,name)
      }
      compare(service.calls,0)
    }
    function test_known_sync_stages_match_the_cli_allowlist() {
      for(var stage of KNOWN_STAGES) {
        service.snapshot={status:"online",sync_progress:{stage:stage,active:false,completed:0,total:null}}
        compare(JSON.parse(service.status()).sync.stage,stage)
      }
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class ActualStatusContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "Service.qml").read_text()
        match = re.search(r"(?ms)^    function status\(\): string \{.*?^    \}", source)
        if not match:
            raise AssertionError("Review status IPC source boundary")
        with tempfile.TemporaryDirectory(prefix="wanikani-operational-status-") as temporary:
            directory = Path(temporary)
            (directory / "StatusCore.qml").write_text('''import QtQuick
import "LearningDigest.mjs" as LearningDigest
QtObject {
 id: root
 property var snapshot: ({})
 property var rhythm: null
 property var manifest: null
 property var workerVersion: null
 property bool ready: true
 property bool learningDigestHydrated: false
 property bool learningDigestDirty: false
 property double learningDigestBarrier: -1
 property int learningDigestGeneration: 0
 property bool panelOpen: false
 property bool studying: false
 property int calls: 0
 function request() {calls++;throw new Error("Status must use its cached snapshot only")}
''' + re.search(r"(?ms)^  function productVersion\(.*?^  \}", source).group(0)
                + "\n" + match.group(0) + "\n}\n")
            (directory / "LearningDigest.mjs").write_text((ROOT / "qml/LearningDigest.mjs").read_text())
            (directory / "tst_Status.qml").write_text(QML.replace("KNOWN_STAGES", json.dumps(sorted(cli.SYNC_STAGES))))
            process = subprocess.run([str(RUNNER), "-input", str(directory)], capture_output=True,
                text=True, errors="replace", timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
            output = process.stdout + process.stderr
        if process.returncode or "QWARN" in output:
            raise AssertionError(output)
        cls.results = {name: json.loads(value) for name, value in re.findall(r"OPERATIONAL_(\w+) (\{[^\n]+\})", output)}
        if set(cls.results) != {"CURRENT", "OLD", "MALFORMED"}:
            raise AssertionError(output)

    def test_actual_service_output_is_accepted_by_the_cli_without_new_calls(self):
        for label, source in self.results.items():
            with self.subTest(label=label), patch.object(cli, "_call", return_value=json.dumps(source)) as call:
                value = cli.status()
                call.assert_called_once_with(["wanikani", "status"], 5)
                self.assertNotIn("PRIVATE", json.dumps(value))
                self.assertIsNone(value["listening_due"])
        with patch.object(cli, "_call", return_value=json.dumps(self.results["CURRENT"])):
            value = cli.status()
        self.assertEqual(1073741824, value["cache"]["bytes"])
        self.assertEqual(1, value["outbox_counts"]["uncertain"])
        self.assertEqual(2, value["readiness"]["upcoming_reviews"]["audio_cached"])

    def test_real_missing_fields_remain_unknown(self):
        with patch.object(cli, "_call", return_value=json.dumps(self.results["OLD"])):
            value = cli.status()
        for name in ("readiness", "cache", "sync", "outbox_counts"):
            self.assertIsNone(value[name])


class OperationalCliTests(unittest.TestCase):
    def read(self, source):
        with patch.object(cli, "_call", return_value=json.dumps(source)) as call:
            result = cli.status()
        call.assert_called_once_with(["wanikani", "status"], 5)
        return result

    def test_old_installed_service_keeps_unsupported_fields_unknown(self):
        value = self.read({"status": "online", "reviews": 4, "lessons": 3, "pending": 0, "attention": 0})
        self.assertTrue(all(value[key] is None for key in ("readiness", "sync", "cache", "outbox_counts")))

    def test_unknown_fields_and_freeform_sync_stage_are_removed(self):
        source = fixture()
        source["readiness"]["reviews"].update(notes="PRIVATE", subject_id=4)
        source["sync"].update(stage="PRIVATE STAGE", message="PRIVATE ERROR")
        source["cache"].update(path="/private/cache", file_names=["PRIVATE"])
        value = self.read(source)
        self.assertEqual("unknown", value["sync"]["stage"])
        self.assertNotIn("PRIVATE", json.dumps(value))
        self.assertNotIn("/private", json.dumps(value))

    def test_partial_nested_sections_preserve_null_instead_of_zero(self):
        source = {**fixture(), "readiness": {"checking": True, "reviews": {"checked": 3}}, "sync": {}, "cache": {}}
        value = self.read(source)
        self.assertIsNone(value["readiness"]["complete"])
        self.assertIsNone(value["readiness"]["reviews"]["total"])
        self.assertIsNone(value["readiness"]["upcoming_reviews"])
        self.assertTrue(all(item is None for item in value["sync"].values()))
        self.assertTrue(all(item is None for item in value["cache"].values()))

    def test_nested_types_ranges_and_timestamps_fail_with_redacted_errors(self):
        invalid = [{"readiness": []}, {"readiness": {"complete": 1}},
            {"readiness": {"checked_at": "PRIVATE TIME"}}, {"readiness": {"checked_at": "2026-02-30T12:00:00Z"}},
            {"readiness": {"reviews": []}}, {"readiness": {"lessons": {"ready": True}}},
            {"readiness": {"upcoming_reviews": {"missing_images": -1}}},
            {"sync": {"stage": ["PRIVATE"]}}, {"sync": {"active": 1}}, {"sync": {"completed": 1.5}},
            {"cache": {"bytes": True}}, {"cache": {"limit_bytes": -1}}, {"cache": {"bytes": cli.MAX_SAFE_INTEGER + 1}}]
        for extra in invalid:
            with self.subTest(extra=extra), self.assertRaises(cli.CliError) as caught:
                self.read({**fixture(), **extra})
            self.assertEqual("invalid_response", caught.exception.code)
            self.assertNotIn("PRIVATE", caught.exception.message)

    def test_cache_supports_the_full_configured_gibibyte_limit(self):
        source = fixture()
        source["cache"].update(bytes=1073741824, limit_bytes=1073741824)
        value = self.read(source)
        self.assertEqual(1073741824, value["cache"]["bytes"])
        self.assertEqual(1073741824, value["cache"]["limit_bytes"])

    def test_doctor_guidance_preserves_transport_health_and_uses_only_three_reads(self):
        source = fixture()
        source["readiness"]["lessons"].update(ready=3, missing_images=1)

        def answer(arguments, timeout, **kwargs):
            self.assertFalse(kwargs.get("changes", False))
            if arguments == ["shell", "ping"]:
                return "ok"
            if arguments == ["shell", "listPlugins"]:
                return json.dumps([{"id": cli.PLUGIN_ID, "enabled": False}])
            self.assertEqual(["wanikani", "status"], arguments)
            return json.dumps(source)

        with patch.object(cli.shutil, "which", return_value="/authored/bin/runtime"), patch.object(cli, "_call", side_effect=answer) as call:
            value = cli.doctor()
        self.assertEqual(3, call.call_count)
        self.assertTrue(value["healthy"])
        self.assertEqual([], value["issues"])
        self.assertEqual(["uncertain_work", "required_media_missing"], [item["code"] for item in value["guidance"]])
        self.assertTrue(all(set(item) == {"code", "action"} for item in value["guidance"]))

    def test_checking_partial_or_inconsistent_counts_never_claim_a_known_missing_item(self):
        for changes in ({"checking": True}, {"complete": False}, {"checked_at": None},
                {"upcoming_reviews": None}, {"reviews": {**COUNTS, "checked": 3}},
                {"reviews": {**COUNTS, "audio_cached": 100}}):
            source = fixture()
            source["readiness"]["lessons"].update(ready=3, missing_images=1)
            source["readiness"].update(changes)
            codes = {item["code"] for item in cli._guidance(self.read(source))}
            self.assertNotIn("required_media_missing", codes)
            self.assertTrue(codes.intersection(("offline_checking", "offline_readiness_incomplete")))

    def test_static_guidance_distinguishes_optional_audio_sync_and_budget(self):
        source = fixture()
        source["outbox_counts"]["uncertain"] = 0
        source["attention"] = 0
        source["sync"].update(stage="media", active=True)
        source["readiness"]["reviews"]["audio_cached"] = 0
        source["cache"].update(bytes=40 * 1024 * 1024, limit_bytes=32 * 1024 * 1024)
        guidance = cli._guidance(self.read(source))
        self.assertEqual(["pending_work", "sync_in_progress", "optional_audio_missing", "cache_over_limit"],
            [item["code"] for item in guidance])
        self.assertIn("does not block", next(item["action"] for item in guidance if item["code"] == "optional_audio_missing"))
        source["status"] = "unauthorized"
        self.assertIn("account_attention", [item["code"] for item in cli._guidance(self.read(source))])
        self.assertEqual([], cli._guidance(None))


if __name__ == "__main__":
    unittest.main()
