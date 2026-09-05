"""Actual StudyRhythm handlers with inert account/shell adapters; no toasts."""
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
import "qml"

Item {
  width: 700
  height: 1800
  QtObject {
    id: backendService
    property bool ready: true
    property bool locked: false
    property var rhythm: null
    property var previews: []
    property var saves: []
    function previewRhythm(patch, callback) { previews = previews.concat([{patch:patch,callback:callback}]) }
    function configureRhythm(patch, callback) { saves = saves.concat([{patch:patch,callback:callback}]) }
  }
  QtObject {
    id: controller
    property var service: backendService
    property bool opened: true
    property string contentAccess: "authored-account-a"
  }
  StudyRhythm { id: page; controller: controller; width: 460 }
  TestCase {
    id: testCase
    name: "StudyRhythm"
    when: windowShown
    function report() {
      return {config:{enabled:true,mode:"due",target:"both",times:["10:00","14:00","18:00"],
        interval_hours:2,window_start:"08:00",window_end:"22:00",quiet_start:"22:00",quiet_end:"08:00",
        minimum_interval_seconds:7200,daily_limit:3,recent_study_seconds:1800},
        reason:"A short Japanese break is available.",next_at:1788602400,next_reason:"When more reviews become available."}
    }
    function init() {
      controller.opened = false
      backendService.ready = true
      backendService.locked = false
      controller.contentAccess = "authored-account-a"
      backendService.rhythm = report()
      page.dirty = false
      page.saving = false
      page.extra = false
      page.loadDraft()
      page.width = 460
      backendService.previews = []
      backendService.saves = []
      controller.opened = true
    }
    function allItems(item) {
      var result = [item]
      for (var i = 0; i < item.children.length; i++)
        result = result.concat(allItems(item.children[i]))
      return result
    }
    function action(text) {
      var found = allItems(page).filter(function (item) { return item.objectName === "fixture-action" && item.text === text })
      compare(found.length, 1, text)
      return found[0]
    }
    function field(name) {
      var result = findChild(page, name)
      verify(result !== null, name)
      return result
    }
    function answerPreview(index, patch) {
      var next = report()
      next.config = Object.assign({}, next.config, backendService.previews[index].patch)
      backendService.previews[index].callback(true, Object.assign(next, patch || {}))
    }
    function answerSave(index, ok) {
      var pending = backendService.saves[index]
      if (ok) {
        var next = report()
        if (!pending.patch.action)
          next.config = Object.assign({}, next.config, pending.patch)
        backendService.rhythm = next
        pending.callback(true, next)
      } else {
        pending.callback(false, null, "Authored save failure")
      }
    }
    function test_readonly_initial_settings() {
      compare(page.dirty, false)
      compare(page.timesText, "10:00, 14:00, 18:00")
      compare(backendService.previews.length, 0)
      compare(backendService.saves.length, 0)
      verify(!action("Apply study rhythm").enabled)
      verify(!page.extra)
    }
    function test_mode_target_and_coalesced_preview() {
      action("At times").clicked()
      action("Listening").clicked()
      page.editTimes("09:30, 15:00")
      tryVerify(function () { return backendService.previews.length === 1 })
      compare(backendService.previews[0].patch.mode, "times")
      compare(backendService.previews[0].patch.target, "listening")
      compare(backendService.saves.length, 0)
      answerPreview(0)
      compare(page.draftPreview.config.target, "listening")
    }
    function test_raw_invalid_times_are_kept_and_never_sent() {
      action("At times").clicked()
      page.editTimes("10:00,  partial,")
      verify(page.validationError.length > 0)
      verify(field("rhythm-validation").visible)
      page.previewDraft()
      page.apply()
      compare(backendService.previews.length, 0)
      compare(backendService.saves.length, 0)
      compare(page.timesText, "10:00,  partial,")
      verify(!action("Apply study rhythm").enabled)
      action("Discard changes").clicked()
      compare(page.timesText, "10:00, 14:00, 18:00")
      compare(page.dirty, false)
    }
    function test_enter_applies_actual_input_and_acknowledges_save() {
      page.change("mode", "times")
      page.editTimes("09:30, 15:00")
      var input = field("rhythm-times")
      input.forceActiveFocus()
      keyClick(Qt.Key_Return)
      compare(backendService.saves.length, 1)
      compare(backendService.saves[0].patch.times.join("|"), "09:30|15:00")
      verify(page.saving)
      answerSave(0, true)
      verify(!page.saving)
      verify(!page.dirty)
      compare(page.notice, "Study rhythm saved.")
    }
    function test_save_failure_keeps_raw_draft() {
      page.editTimes("09:30,  15:00")
      page.apply()
      answerSave(0, false)
      compare(page.timesText, "09:30,  15:00")
      verify(page.dirty)
      compare(page.notice, "Authored save failure")
    }
    function test_newer_edit_is_not_discarded_by_saved_response() {
      page.editTimes("09:30, 15:00")
      page.apply()
      page.editTimes("09:30, 15:00, ")
      answerSave(0, true)
      compare(page.timesText, "09:30, 15:00, ")
      verify(page.dirty)
      verify(page.notice.indexOf("newer changes") >= 0)
    }
    function test_stale_preview_query_and_account_are_discarded() {
      page.change("mode", "times")
      page.previewDraft()
      page.editTimes("11:00")
      answerPreview(0, {reason:"STALE"})
      compare(page.draftPreview, null)
      page.previewDraft()
      controller.contentAccess = "authored-account-b"
      answerPreview(1, {reason:"STALE ACCOUNT"})
      compare(page.draftPreview, null)
      verify(!page.dirty)
    }
    function test_close_before_debounce_and_one_preview_on_reopen() {
      page.change("mode", "times")
      controller.opened = false
      wait(210)
      compare(backendService.previews.length, 0)
      controller.opened = true
      tryVerify(function () { return backendService.previews.length === 1 })
      controller.opened = false
      answerPreview(0, {reason:"CLOSED"})
      compare(page.draftPreview, null)
    }
    function test_locked_unready_and_hidden_prevent_preview_or_save() {
      for (var state of ["locked", "unready", "hidden"]) {
        page.change("mode", "times")
        if (state === "locked") backendService.locked = true
        if (state === "unready") backendService.ready = false
        if (state === "hidden") page.visible = false
        page.previewDraft()
        page.apply()
        page.pause({action:"snooze",minutes:15})
        compare(backendService.previews.length, 0)
        compare(backendService.saves.length, 0)
        page.dirty = false
        backendService.locked = false
        backendService.ready = true
        page.visible = true
      }
    }
    function test_pause_actions_are_explicit_and_preserve_unsaved_schedule() {
      page.editTimes("11:00")
      action("Snooze 15 min").clicked()
      compare(backendService.saves[0].patch.action, "snooze")
      compare(backendService.saves[0].patch.minutes, 15)
      answerSave(0, true)
      compare(page.timesText, "11:00")
      verify(page.dirty)
      action("Skip today").clicked()
      compare(backendService.saves[1].patch.action, "skip_today")
    }
    function test_limits_validation_and_revealed_inputs() {
      action("At intervals").clicked()
      action("Quiet hours & limits").clicked()
      verify(field("rhythm-window-start").visible)
      verify(field("rhythm-quiet-start").visible)
      page.change("window_start", "23:00")
      verify(page.validationError.indexOf("after it starts") >= 0)
      page.change("window_start", "08:00")
      page.change("minimum_interval_seconds", 1)
      verify(page.validationError.length > 0)
    }
    function test_narrow_layout_data() { return [{tag:"320 px", width:320}, {tag:"460 px", width:460}] }
    function test_narrow_layout(data) {
      page.width = data.width
      page.change("mode", "interval")
      page.extra = true
      verify(waitForRendering(page))
      for (var item of allItems(page)) {
        if (!item.visible || !item.width || !item.height)
          continue
        var point = item.mapToItem(page, 0, 0)
        verify(point.x >= -1 && point.x + item.width <= page.width + 1,
          String(item.objectName || item.text || item) + " exceeds " + page.width + " px")
      }
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class StudyRhythmRenderingTests(unittest.TestCase):
    def test_authored_settings_previews_and_edits(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-study-rhythm-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("StudyRhythm.qml", "Label.qml", "Theme.mjs"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text('import QtQuick.Controls\nButton {\n'
                ' objectName: "fixture-action"\n property bool selected: false\n'
                ' property string accessibleName: text\n property string accessibleHint: ""\n}\n')
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' function space(value) { return value }\n readonly property var font: ({family:"Sans",body:14,bodySmall:12,title:20})\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' property color background: "#ffffff"\n property color foreground: "#202020"\n'
                ' property color accent: "#006699"\n property color urgent: "#990000"\n}\n')
            ui = directory / "qs" / "Ui"
            ui.mkdir()
            (ui / "qmldir").write_text("module qs.Ui\nTextField 1.0 TextField.qml\nNumberField 1.0 NumberField.qml\n")
            (ui / "TextField.qml").write_text('import QtQuick\nimport QtQuick.Controls\nTextField { property color foreground: "#202020"; property color accent: "#006699"; color: foreground }\n')
            (ui / "NumberField.qml").write_text('import QtQuick\nimport QtQuick.Controls\nSpinBox {\n'
                ' property color foreground: "#202020"\n property color accent: "#006699"\n id: spin\n property alias field: spin\n property real fieldWidth: 90\n implicitWidth: fieldWidth\n signal modified(int value)\n onValueModified: modified(value)\n}\n')
            (directory / "tst_StudyRhythm.qml").write_text(QML)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
