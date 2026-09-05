"""Loaded runtime identity uses actual Service events and bounded local CLI reads."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_agent_cli import cli
from test_listening_preparation_ui import build_adapter, ROOT, RUNNER


VALID = ["0.0.0", "0.2.2", "1.0.0-rc.1+build.7", "12.34.56-alpha-beta.001a+00",
    "1.2.3+" + "a" * 58]
INVALID = ["", "PRIVATE TOKEN", "v0.2.2", "0.2", "01.2.3", "1.02.3", "1.2.03",
    "1.2.3-01", "1.2.3-", "1.2.3+", "1.2.3-a..b", "1.2.3+a..b", "1.2.3-a_b",
    "1.2.3\n", "1.2.3\r", "1.2.3\u2028", "1.2.3\u2029", "1.2.3\x00", "1.2.3+日本語", "１.2.3", "1.2.3+" + "a" * 59,
    1, True, [], {"version": "1.2.3", "token": "PRIVATE TOKEN"}]


QML = r'''
import QtQuick
import QtTest
Item {
  ServiceCore { id: service }
  TestCase {
    name: "RuntimeVersions"
    function ready(data,protocol) {
      service.receive(JSON.stringify({v:protocol===undefined?1:protocol,event:"ready",data:data}))
    }
    function versions() { return JSON.parse(service.status()).versions }
    function init() {
      failOnWarning(/.*/)
      service.ready=false;service.workerVersion=null;service.manifest=null;service.snapshot={status:"starting"}
      service.callbacks={};service.requestContexts={};service.pendingCount=0;service.writes=[]
    }
    function test_versions_are_unknown_until_their_actual_sources_arrive() {
      compare(versions(),{plugin:null,worker:null})
      service.manifest={version:"0.2.2",token:"PRIVATE TOKEN"}
      compare(versions(),{plugin:"0.2.2",worker:null})
      ready({version:"0.2.1",token:"PRIVATE TOKEN"})
      verify(service.ready);compare(versions(),{plugin:"0.2.2",worker:"0.2.1"})
      compare(service.writes.length,0)
      verify(service.status().indexOf("PRIVATE")<0)
      console.log("VERSION_MISMATCH "+service.status())
    }
    function test_actual_worker_exit_clears_version_before_draining_callbacks() {
      service.manifest={version:"0.2.2"};ready({version:"0.2.2"})
      var calls=0
      service.callbacks={pending:function(ok,data,error) {
        calls++;verify(!ok);verify(!service.ready);compare(versions(),{plugin:"0.2.2",worker:null})
      }}
      service.pendingCount=1
      service.restartWorker()
      compare(calls,1);compare(service.pendingCount,0);compare(service.workerVersion,null)
      ready({version:"0.2.3"});compare(versions(),{plugin:"0.2.2",worker:"0.2.3"})
      compare(service.writes.length,0)
    }
    function test_missing_or_invalid_new_ready_does_not_keep_previous_worker_version() {
      for(var value of INVALID_VERSIONS.concat([null])) {
        ready({version:"0.2.2"});ready({version:value})
        compare(versions().worker,null)
      }
      for(var data of [null,{},true,42,"0.2.2",[]]) {
        ready({version:"0.2.2"});ready(data);compare(versions().worker,null)
      }
      compare(service.writes.length,0)
    }
    function test_only_valid_ready_event_can_set_worker_version() {
      ready({version:"0.2.2"})
      ready({version:"9.9.9"},2);compare(versions().worker,"0.2.2")
      service.receive(JSON.stringify({v:1,event:"readiness",data:{version:"9.9.9"}}))
      compare(versions().worker,"0.2.2")
      compare(service.writes.length,0)
    }
    function test_manifest_and_worker_apply_identical_bounded_validation() {
      for(var value of VALID_VERSIONS) {
        service.manifest={version:value};ready({version:value});compare(versions(),{plugin:value,worker:value})
      }
      for(var value of INVALID_VERSIONS) {
        service.manifest={version:value};service.workerVersion=value
        compare(versions(),{plugin:null,worker:null})
      }
      for(var manifest of [null,{},true,42,"0.2.2",[]]) {
        service.manifest=manifest;compare(versions().plugin,null)
      }
      compare(service.writes.length,0)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class ActualRuntimeVersionTests(unittest.TestCase):
    def test_actual_ready_exit_status_and_cli_contract(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-runtime-versions-") as temporary:
            directory = Path(temporary)
            build_adapter(directory)
            (directory / "tst_Preparation.qml").unlink()
            source = (ROOT / "Service.qml").read_text()
            status = re.search(r"(?ms)^    function status\(\): string \{.*?^    \}", source).group(0)
            core = directory / "ServiceCore.qml"
            core.write_text(core.read_text().rsplit("}", 1)[0] + "\nproperty var manifest: null\n" + status + "\n}\n")
            (directory / "tst_Versions.qml").write_text(QML.replace("INVALID_VERSIONS", json.dumps(INVALID))
                .replace("VALID_VERSIONS", json.dumps(VALID)))
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, errors="replace", timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        output = process.stdout + process.stderr
        self.assertEqual(0, process.returncode, output)
        self.assertNotIn("QWARN", output)
        raw = re.search(r"VERSION_MISMATCH (\{[^\n]+\})", output).group(1)
        with patch.object(cli, "_call", return_value=raw) as call:
            value = cli.status()
        call.assert_called_once_with(["wanikani", "status"], 5)
        self.assertEqual({"plugin": "0.2.2", "worker": "0.2.1"}, value["versions"])
        self.assertIn("runtime_version_mismatch", [item["code"] for item in cli._guidance(value)])


class RuntimeVersionCliTests(unittest.TestCase):
    def read(self, **extra):
        with patch.object(cli, "_call", return_value=json.dumps({"status": "online", **extra})) as call:
            result = cli.status()
        call.assert_called_once_with(["wanikani", "status"], 5)
        return result

    def test_old_service_missing_section_and_partial_versions_remain_unknown(self):
        self.assertIsNone(self.read()["versions"])
        self.assertIsNone(self.read(versions=None)["versions"])
        self.assertEqual({"plugin": None, "worker": None}, self.read(versions={})["versions"])
        self.assertEqual({"plugin": "0.2.2", "worker": None}, self.read(versions={"plugin": "0.2.2"})["versions"])
        for source in ({}, {"versions": None}, {"versions": {}}, {"versions": {"plugin": "0.2.2"}},
                {"versions": {"worker": "0.2.2"}}, {"versions": {"plugin": "0.2.2", "worker": "0.2.2"}}):
            self.assertNotIn("runtime_version_mismatch", [item["code"] for item in cli._guidance(self.read(**source))])

    def test_versions_are_strict_bounded_and_private_fields_are_removed(self):
        for version in VALID:
            self.assertEqual({"plugin": version, "worker": version},
                self.read(versions={"plugin": version, "worker": version, "path": "PRIVATE", "git": "PRIVATE"})["versions"])
        for version in INVALID:
            for key in ("plugin", "worker"):
                with self.subTest(version=version, key=key), self.assertRaises(cli.CliError) as caught:
                    self.read(versions={key: version})
                self.assertEqual("invalid_response", caught.exception.code)
                self.assertNotIn("PRIVATE", caught.exception.message)
        for malformed in ([], "PRIVATE", True, 3):
            with self.assertRaises(cli.CliError):
                self.read(versions=malformed)

    def test_doctor_mismatch_is_static_guidance_without_repair_or_health_failure(self):
        def answer(arguments, timeout, **kwargs):
            self.assertFalse(kwargs.get("changes", False))
            if arguments == ["shell", "ping"]:
                return "ok"
            if arguments == ["shell", "listPlugins"]:
                return json.dumps([{"id": cli.PLUGIN_ID, "enabled": True}])
            self.assertEqual(["wanikani", "status"], arguments)
            return json.dumps({"status": "online", "versions": {"plugin": "0.2.2", "worker": "0.2.1"}})

        with patch.object(cli.shutil, "which", return_value="/authored/runtime"), patch.object(cli, "_call", side_effect=answer) as call:
            value = cli.doctor()
        self.assertEqual(3, call.call_count)
        self.assertTrue(value["healthy"])
        self.assertEqual([], value["issues"])
        advice = next(item for item in value["guidance"] if item["code"] == "runtime_version_mismatch")
        self.assertEqual({"code", "action"}, set(advice))
        self.assertIn("study is closed", advice["action"])
        self.assertIn("desktop is unlocked", advice["action"])
        self.assertIn("performs neither", advice["action"])


if __name__ == "__main__":
    unittest.main()
