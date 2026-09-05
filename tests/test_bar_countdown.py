"""Production bar bindings with an inert, manually advanced minute clock.

No shell, host configuration, worker request, real timer wait, or account is
involved. The native clock API is checked separately against installed qmltypes.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
NATIVE_BAR = Path("/usr/share/omarchy/shell/Ui/BarWidget.qml")
CLOCK_TYPES = Path("/usr/lib/qt6/qml/Quickshell/quickshell-core.qmltypes")


QML = r'''
import QtQuick
import QtTest

Rectangle {
  width: 700
  height: 180
  color: "#171923"
  QtObject {
    id: service
    property var snapshot: ({})
    property bool ready: true
    property bool locked: false
    property bool animations: false
    property int requests: 0
    property var summoned: []
    function request() { requests++; throw new Error("The bar must not fetch state") }
    function summon(view) { summoned = summoned.concat([view]) }
  }
  QtObject {
    id: shell
    function serviceFor(id) {
      if (id !== "io.github.lostandadrift.wanikani") throw new Error("Unexpected service")
      return service
    }
  }
  QtObject {
    id: bar
    property var shell: null
    property string position: "top"
    readonly property bool vertical: position === "left" || position === "right"
    property int barSize: 40
    property color background: "#171923"
    property color barForeground: "#f4f4f4"
    property bool transparent: false
  }
  BarWidget { id: widget; bar: bar; x: 30; y: 30 }
  TestCase {
    name: "BarCountdown"
    when: windowShown
    property double base: 0
    function clock() { return findChild(widget, "fixture-minute-clock") }
    function button() { return findChild(widget, "fixture-widget-button") }
    function snapshot(patch) {
      var value = {username:"Authored example",reviews:0,pending:0,attention:0,status:"ready",
        syncing:false,next_reviews_at:new Date(base + 121 * 60000).toISOString()}
      for (var key in patch) value[key] = patch[key]
      service.snapshot = value
      widget.countdownNow = base
    }
    function init() {
      failOnWarning(/.*/)
      base = Math.floor(Date.now() / 60000) * 60000
      widget.visible = true
      widget.bar = bar
      bar.shell = shell
      bar.position = "top"
      service.ready = true
      service.locked = false
      service.requests = 0
      service.summoned = []
      snapshot({})
      clock().date = new Date(base)
    }
    function cleanup() { compare(service.requests, 0) }
    function test_minute_ticks_update_same_snapshot_and_stop_when_elapsed() {
      var original = service.snapshot
      compare(clock().precision, 1)
      compare(clock().enabled, true)
      compare(widget.label, "3h")
      clock().tick(new Date(base + 60000))
      compare(widget.label, "2h")
      clock().tick(new Date(base + 61 * 60000))
      compare(widget.label, "1h")
      clock().tick(new Date(base + 62 * 60000))
      compare(widget.label, "59m")
      clock().tick(new Date(base + 120 * 60000))
      compare(widget.label, "1m")
      clock().tick(new Date(base + 121 * 60000))
      compare(widget.label, "…")
      compare(clock().enabled, false)
      verify(button().tooltipText.indexOf("Review schedule needs a refresh") >= 0)
      compare(service.snapshot, original)
      compare(service.snapshot.reviews, 0)
    }
    function test_status_priority_data() {
      return [
        {tag:"sync before attention",patch:{syncing:true,attention:2,status:"offline",pending:4,reviews:7},label:"↻ 7"},
        {tag:"attention before offline",patch:{attention:2,status:"offline",pending:4,reviews:7},label:"! 7"},
        {tag:"offline before pending",patch:{status:"offline",pending:4,reviews:7},label:"○ 7"},
        {tag:"pending before count",patch:{pending:4,reviews:7},label:"7 · 4"},
        {tag:"reviews",patch:{reviews:7},label:"7"},
        {tag:"disconnected",patch:{username:null},label:"+"}
      ]
    }
    function test_status_priority(data) {
      snapshot(data.patch)
      compare(widget.label, data.label)
      compare(clock().enabled, false)
    }
    function test_lifecycle_gates_and_reopening_refreshes_local_time() {
      service.ready = false
      compare(widget.label, "…")
      compare(clock().enabled, false)
      service.ready = true
      compare(clock().enabled, true)
      service.locked = true
      compare(clock().enabled, false)
      service.locked = false
      compare(clock().enabled, true)
      widget.visible = false
      compare(clock().enabled, false)
      widget.countdownNow = 0
      clock().tick(new Date(base + 60000))
      compare(widget.countdownNow, 0)
      var before = Date.now()
      widget.visible = true
      verify(widget.countdownNow >= before)
      compare(clock().enabled, true)
      var window = widget.Window.window
      window.visible = false
      compare(clock().enabled, false)
      window.visible = true
      compare(clock().enabled, true)
      bar.shell = null
      compare(widget.label, "…")
      compare(clock().enabled, false)
    }
    function test_missing_invalid_and_past_dates_data() {
      return [
        {tag:"missing",date:null,label:"✓",needs:false},
        {tag:"empty",date:"",label:"✓",needs:false},
        {tag:"malformed",date:"not a date",label:"…",needs:true},
        {tag:"wrong type",date:42,label:"…",needs:true},
        {tag:"past",date:"2000-01-01T00:00:00Z",label:"…",needs:true}
      ]
    }
    function test_missing_invalid_and_past_dates(data) {
      snapshot({next_reviews_at:data.date})
      compare(widget.label, data.label)
      compare(clock().enabled, false)
      compare(widget.scheduleNeedsRefresh, data.needs)
      verify(widget.label.indexOf("NaN") < 0)
      compare(service.snapshot.reviews, 0)
    }
    function test_new_schedule_reenables_after_expiry() {
      snapshot({next_reviews_at:new Date(base - 60000).toISOString()})
      compare(clock().enabled, false)
      snapshot({next_reviews_at:new Date(base + 90001).toISOString()})
      compare(clock().enabled, true)
      compare(widget.label, "2m")
    }
    function test_all_bar_positions_preserve_labels_and_actions() {
      for (var i = 0; i < 4; i++) {
        bar.position = ["top", "bottom", "left", "right"][i]
        compare(widget.vertical, i >= 2)
        compare(widget.implicitHeight, 40)
        if (i >= 2) compare(widget.implicitWidth, 40)
        else verify(widget.implicitWidth > 40)
        var labels = findChild(widget, "fixture-crab").parent.children
        compare(labels[1].visible, i < 2)
        compare(labels[1].text, widget.label)
        compare(clock().enabled, true)
      }
      button().pressed(Qt.LeftButton)
      button().pressed(Qt.MiddleButton)
      button().pressed(Qt.RightButton)
      compare(service.summoned, ["dashboard", "reviews", "settings"])
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file() and NATIVE_BAR.is_file(), "Installed Qt and native bar required")
class BarCountdownTests(unittest.TestCase):
    def test_native_clock_contract_and_production_bar_bindings(self):
        types = CLOCK_TYPES.read_text()
        clock = re.search(r'name: "SystemClock"(?P<body>.*?)\n    Component \{', types, re.S)
        self.assertIsNotNone(clock)
        for value in ('name: "enabled"', 'write: "setEnabled"', 'name: "date"', '"Minutes"'):
            self.assertIn(value, clock["body"])
        with tempfile.TemporaryDirectory(prefix="wanikani-bar-clock-") as temporary:
            directory = Path(temporary)
            source = (ROOT / "BarWidget.qml").read_text()
            self.assertIn("precision: SystemClock.Minutes", source)
            (directory / "BarWidget.qml").write_text(source.replace("import Quickshell\n", ""))
            (directory / "SystemClock.qml").write_text('''import QtQuick
QtObject {
  objectName: "fixture-minute-clock"
  enum Precision { Hours, Minutes, Seconds }
  property int precision: SystemClock.Hours
  property bool enabled: true
  property date date: new Date()
  function tick(value) { if (enabled) date = value }
}
''')
            qml = directory / "qml"
            qml.mkdir()
            for name in ("Label.qml", "Theme.mjs"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Crab.qml").write_text('''import QtQuick
Item { objectName: "fixture-crab"; property color ink; property color shellColor;
  property bool animate: false; property bool celebrating: false }
''')
            commons = directory / "qs" / "Commons"
            commons.mkdir(parents=True)
            (commons / "qmldir").write_text("module qs.Commons\nsingleton Color 1.0 Color.qml\nsingleton Style 1.0 Style.qml\n")
            (commons / "Color.qml").write_text('''pragma Singleton
import QtQuick
QtObject { property color background: "#171923"; property color foreground: "#f4f4f4";
  property var bar: ({background: "#171923", text: "#f4f4f4"}) }
''')
            (commons / "Style.qml").write_text('''pragma Singleton
import QtQuick
QtObject { property var font: ({family:"Sans Serif",body:14,bodySmall:12});
  property var bar: ({sizeHorizontal:40}); function space(value) { return value } }
''')
            ui = directory / "qs" / "Ui"
            ui.mkdir()
            (ui / "qmldir").write_text("module qs.Ui\nBarWidget 1.0 BarWidget.qml\nWidgetButton 1.0 WidgetButton.qml\n")
            shutil.copyfile(NATIVE_BAR, ui / "BarWidget.qml")
            (ui / "WidgetButton.qml").write_text('''import QtQuick
Item { objectName: "fixture-widget-button"; property var bar; property string text;
  property bool hasVisualContent: false; property string tooltipText; signal pressed(int button) }
''')
            (directory / "tst_Bar.qml").write_text(QML)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            output = result.stdout + result.stderr
            self.assertEqual(0, result.returncode, output)
            self.assertNotIn("QWARN", output, output)
            self.assertRegex(output, r"Totals: \d+ passed, 0 failed", output)


if __name__ == "__main__":
    unittest.main()
