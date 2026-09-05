"""Render the real Zen view with authored content and inert shell adapters."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")


QML = r'''
import QtQuick
import QtTest
import "qml" as Kani

Rectangle {
  width: 800
  height: 900
  QtObject {
    id: ambientService
    property bool ready: true
    property bool locked: false
    property bool animations: false
    property var ambientItems: []
    property int leases: 0
    function acquireAmbient() { leases++ }
    function releaseAmbient() { leases-- }
    function request() { throw new Error("Quiet recall must never write study data") }
  }
  QtObject {
    id: owner
    property bool opened: true
    property var service: ambientService
    property string contentAccess: "authored-account-1"
    function dismiss() { opened = false }
  }
  Kani.Zen { id: zen; width: 700; controller: owner }
  TestCase {
    name: "ZenRecall"
    when: windowShown
    function item(id, meaning) {
      return {id: id, characters: "山", images: [], meanings: [meaning], readings: [{reading: "さん"}]}
    }
    function child(name) {
      var value = findChild(zen, "zen-" + name)
      verify(value !== null)
      return value
    }
    function click(name) { mouseClick(child(name)) }
    function init() {
      failOnWarning(/.*/)
      owner.opened = false
      owner.contentAccess = "authored-account-1"
      ambientService.ready = true
      ambientService.locked = false
      ambientService.ambientItems = [item(990001, "First authored meaning"), item(990002, "Second authored meaning")]
      zen.quietRecall = false
      zen.index = 0
      child("gallery-timer").interval = 30000
      owner.opened = true
      verify(waitForRendering(zen))
    }
    function test_gallery_default_and_keyboard_reveal_then_next() {
      verify(!zen.quietRecall)
      verify(child("meaning").visible)
      verify(child("reading").visible)
      verify(child("gallery-timer").running)
      compare(child("gallery-timer").interval, 30000)
      click("recall-toggle")
      verify(zen.quietRecall)
      verify(!child("meaning").visible)
      verify(!child("reading").visible)
      verify(child("meaning").Accessible.ignored)
      verify(!child("subject-glyph").revealLabel)
      verify(!child("gallery-timer").running)
      verify(!child("next-gallery").visible)
      var reveal = child("reveal")
      compare(reveal.text, "Reveal")
      reveal.forceActiveFocus(Qt.TabFocusReason)
      keyClick(Qt.Key_Space)
      verify(zen.answerRevealed)
      compare(reveal.text, "Next word")
      verify(child("meaning").visible)
      verify(child("reading").visible)
      verify(child("subject-glyph").revealLabel)
      keyClick(Qt.Key_Space)
      compare(zen.subject.id, 990002)
      verify(!zen.answerRevealed)
      verify(!child("meaning").visible)
      compare(reveal.text, "Reveal")
    }
    function test_automatic_rotation_never_skips_a_quiet_recall_card() {
      child("gallery-timer").interval = 10
      tryVerify(function () { return zen.subject.id !== 990001 })
      click("recall-toggle")
      var id = zen.subject.id
      verify(!child("gallery-timer").running)
      wait(45)
      compare(zen.subject.id, id)
      verify(!zen.answerRevealed)
      zen.recallAction()
      wait(45)
      compare(zen.subject.id, id)
      verify(zen.answerRevealed)
    }
    function test_close_reopen_and_lock_preserve_mode_but_reset_reveal() {
      click("recall-toggle")
      zen.recallAction()
      verify(zen.answerRevealed)
      owner.opened = false
      compare(ambientService.leases, 0)
      verify(!zen.answerRevealed)
      zen.recallAction()
      verify(!zen.answerRevealed)
      owner.opened = true
      compare(ambientService.leases, 1)
      verify(zen.quietRecall)
      verify(!child("meaning").visible)
      ambientService.locked = true
      zen.recallAction()
      verify(!zen.answerRevealed)
      verify(!child("reveal").enabled)
    }
    function test_access_change_hides_answer_and_uses_only_new_catalogue_bodies() {
      click("recall-toggle")
      zen.recallAction()
      owner.contentAccess = "authored-account-2"
      verify(!zen.answerRevealed)
      ambientService.ambientItems = []
      compare(zen.subject, null)
      verify(child("meaning").text.indexOf("First authored") < 0)
      ambientService.ambientItems = [item(990001, "New account authored meaning")]
      verify(!child("meaning").visible)
      zen.recallAction()
      compare(child("meaning").text, "New account authored meaning")
    }
    function test_refresh_keeps_same_unanswered_safe_subject_and_removal_resets() {
      click("recall-toggle")
      ambientService.ambientItems = [item(990000, "Earlier authored item"), item(990001, "Updated authored meaning"), item(990002, "Second authored meaning")]
      compare(zen.subject.id, 990001)
      verify(!zen.answerRevealed)
      zen.recallAction()
      compare(child("meaning").text, "Updated authored meaning")
      ambientService.ambientItems = [item(990002, "Only still-safe authored item")]
      compare(zen.subject.id, 990002)
      verify(!zen.answerRevealed)
      verify(!child("meaning").visible)
    }
    function test_single_and_empty_catalogue_keep_a_useful_exit() {
      ambientService.ambientItems = [item(990001, "A single authored item")]
      click("recall-toggle")
      zen.recallAction()
      compare(child("reveal").text, "Next word")
      verify(!child("reveal").enabled)
      ambientService.ambientItems = []
      verify(!child("reveal").visible)
      verify(child("recall-toggle").enabled)
      verify(child("reading").text.indexOf("Learned subjects will appear") >= 0)
      verify(!child("gallery-timer").running)
      click("recall-toggle")
      verify(!zen.quietRecall)
      verify(!child("recall-toggle").enabled)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class ZenRecallTests(unittest.TestCase):
    def test_authored_gallery_recall_and_access_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-zen-recall-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("Zen.qml", "Label.qml"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text("import QtQuick.Controls\nButton { property bool selected: false }\n")
            (qml / "Crab.qml").write_text("import QtQuick\nItem { property bool animate: false }\n")
            (qml / "SubjectGlyph.qml").write_text("import QtQuick\nItem { implicitHeight: 130; property var subject; property int pixelSize; property bool revealLabel: true }\n")
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                '  function space(value) { return value }\n'
                '  readonly property var font: ({family: "Sans", body: 14, bodySmall: 12, title: 20})\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                '  readonly property color foreground: "#202020"\n'
                '  readonly property color accent: "#006699"\n}\n')
            (directory / "tst_ZenRecall.qml").write_text(QML)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertIn("8 passed", process.stdout)


if __name__ == "__main__":
    unittest.main()
