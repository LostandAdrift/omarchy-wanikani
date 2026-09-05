"""Pure QML aggregate validation with authored fixtures and no live IO."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")


@unittest.skipUnless(RUNNER.is_file(), "QtTest required")
class LearningDigestProjectionTests(unittest.TestCase):
    def test_actual_pure_projection_in_a_dst_timezone(self):
        result = subprocess.run([str(RUNNER), "-input", str(ROOT / "tests/qml/tst_LearningDigest.qml")],
            capture_output=True, text=True, timeout=25, env={**os.environ,
                "TZ": "America/Los_Angeles", "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                "QT_QUICK_CONTROLS_STYLE": "Basic"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)

    def test_backend_aggregate_passes_unchanged_except_unknown_freshness(self):
        import test_learning_insights as authored
        from wanikani import learning_digest

        fixture = authored.LearningInsightsTests()
        fixture.setUp()
        cases = []
        try:
            for zone, stamp in (("UTC", "2026-09-05T19:00:00.123456+00:00"),
                    ("America/Los_Angeles", "2026-03-09T19:00:00.125000+00:00"),
                    ("America/Los_Angeles", "2026-11-02T20:00:00.125000+00:00")):
                fixture.now = datetime.fromisoformat(stamp).timestamp()
                fixture.event(mode="reviews")
                fixture.event(mode="lessons", when=fixture.now - 10 * 86400)
                fixture.event(mode="practice", when=fixture.now - 29 * 86400)
                fixture.session(count=2, finished=5)
                raw = learning_digest.project(fixture.engine, timezone=zone)
                expected = json.loads(json.dumps(raw))
                expected["stale"] = None
                cases.append({"tag": stamp, "raw": raw, "expected": expected,
                    "options": {"ready": True, "demo": False, "epoch": raw["data_epoch"], "dirty": False,
                        "clockChanged": False, "now": int(fixture.now * 1000) + 1}})
        finally:
            fixture.tearDown()
        with tempfile.TemporaryDirectory(prefix="wanikani-digest-contract-") as temporary:
            directory = Path(temporary)
            shutil.copyfile(ROOT / "qml/LearningDigest.mjs", directory / "LearningDigest.mjs")
            (directory / "tst_Contract.qml").write_text('''import QtQuick
import QtTest
import "LearningDigest.mjs" as Digest
TestCase {
  name: "BackendDigestContract"
  function test_projection_data() {return __CASES__}
  function test_projection(data) {
    failOnWarning(/.*/)
    var result=Digest.project(data.raw,data.options)
    verify(result!==null)
    compare(result,data.expected)
    verify(JSON.stringify(result).indexOf("PRIVATE")<0)
  }
}
'''.replace("__CASES__", json.dumps(cases)))
            result = subprocess.run([str(RUNNER), "-input", str(directory)], capture_output=True,
                text=True, timeout=25, env={**os.environ, "TZ": "America/Los_Angeles",
                    "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
