"""Queue actual Panel detail callbacks across navigation/account changes."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")


QML = r'''
import QtQuick
import QtTest

Item {
  QtObject {
    id: worker
    property bool ready: true
    property bool locked: false
    property bool panelOpen: true
    property bool studying: false
    property var pending: []
    function request(method, args, callback) { pending.push({method: method, args: args, callback: callback}) }
    function applySnapshot(data) {}
    function reply(index, id) { pending[index].callback(true, {id: id, characters: "山", meanings: ["Authored meaning"]}, "") }
  }
  PanelCore { id: panel; service: worker }
  TestCase {
    name: "PanelDetails"
    function init() {
      failOnWarning(/.*/)
      worker.ready = true
      worker.locked = false
      worker.pending = []
      panel.opened = true
      panel.view = "dashboard"
      panel.contentAccess = "authored-account"
      panel.navigationSequence = 0
      panel.detailSequence = 0
      panel.searchSequence = 0
      panel.detail = null
      panel.busy = false
      panel.error = ""
      panel.query = ""
      panel.queryTruncated = false
      panel.clipboardState.running = false
      panel.clipboardState.primary = true
      panel.clipboardState.captured = ""
    }
    function cleanup() {
      panel.close()
      wait(0)
    }
    function test_dashboard_open_and_related_subject_followup_still_work() {
      panel.showSubject(990001)
      compare(worker.pending.length, 1)
      compare(worker.pending[0].method, "details")
      compare(worker.pending[0].args.subject_id, 990001)
      worker.reply(0, 990001)
      compare(panel.view, "lookup")
      compare(panel.detail.id, 990001)
      panel.showSubject(990002)
      worker.reply(1, 990002)
      compare(panel.view, "lookup")
      compare(panel.detail.id, 990002)
    }
    function test_return_from_help_keeps_subject_instead_of_deferred_initial_query() {
      panel.view = "help"
      panel.navigate("lookup")
      var component = Qt.createComponent("LookupCore.qml")
      compare(component.status, Component.Ready, component.errorString())
      var lookup = component.createObject(panel, {controller: panel})
      verify(lookup !== null)
      try {
        panel.searching = true
        panel.showSubject(990001)
        wait(20)
        compare(worker.pending.length, 1, "Explicit detail supersedes deferred initial lookup query")
        compare(worker.pending[0].method, "details")
        verify(!panel.searching)
        worker.reply(0, 990001)
        compare(panel.detail.id, 990001)
        compare(panel.view, "lookup")
      } finally {
        lookup.destroy()
      }
    }
    function test_old_details_do_not_reappear_after_close_and_reopen() {
      panel.showSubject(990001)
      panel.close()
      verify(!panel.opened)
      panel.opened = true
      worker.reply(0, 990001)
      compare(panel.view, "dashboard")
      compare(panel.detail, null)
    }
    function test_navigation_away_and_back_invalidates_an_old_reply() {
      panel.view = "lookup"
      panel.showSubject(990001)
      panel.navigate("zen")
      panel.navigate("lookup")
      worker.reply(0, 990001)
      compare(panel.detail, null)
      compare(panel.view, "lookup")
    }
    function test_access_change_never_rehydrates_an_old_subject() {
      panel.showSubject(990001)
      panel.contentAccess = "authored-account-with-reduced-access"
      worker.reply(0, 990001)
      compare(panel.detail, null)
      compare(panel.view, "dashboard")
    }
    function test_editing_the_query_invalidates_an_inflight_detail() {
      panel.view = "lookup"
      panel.showSubject(990001)
      panel.searchSequence++
      worker.reply(0, 990001)
      compare(panel.detail, null)
    }
    function test_reversed_detail_responses_keep_the_latest_selection() {
      panel.showSubject(990001)
      panel.showSubject(990002)
      worker.reply(1, 990002)
      worker.reply(0, 990001)
      compare(panel.detail.id, 990002)
    }
    function test_closed_unready_and_locked_calls_do_not_issue_requests() {
      panel.opened = false
      panel.showSubject(990001)
      panel.opened = true
      worker.ready = false
      panel.showSubject(990001)
      worker.ready = true
      worker.locked = true
      panel.showSubject(990001)
      compare(worker.pending.length, 0)
    }
    function test_a_successful_response_after_lock_cannot_open_a_detail() {
      panel.showSubject(990001)
      worker.locked = true
      worker.reply(0, 990001)
      compare(panel.detail, null)
      compare(panel.view, "dashboard")
    }
    function test_a_successful_response_after_worker_stops_cannot_open_a_detail() {
      panel.showSubject(990001)
      worker.ready = false
      worker.reply(0, 990001)
      compare(panel.detail, null)
    }
    function test_current_selection_is_preserved_and_unicode_cap_never_splits_a_character() {
      panel.view = "lookup"
      panel.readSelection()
      verify(panel.clipboardState.running)
      panel.clipboardState.finish("  山か\u3099𠮷\n  ")
      compare(panel.query, "  山か\u3099𠮷\n  ")
      panel.readSelection()
      panel.clipboardState.finish("山".repeat(255) + "𠮷" + "more")
      compare(panel.query.codePointAt(255), 0x20bb7)
      compare(panel.query, "山".repeat(255) + "𠮷")
      verify(panel.queryTruncated)
    }
    function test_empty_primary_falls_back_only_while_the_request_is_current() {
      panel.view = "lookup"
      panel.readSelection()
      panel.clipboardState.finish("")
      tryCompare(panel.clipboardState, "running", true)
      verify(!panel.clipboardState.primary)
      panel.clipboardState.finish("Clipboard 山")
      compare(panel.query, "Clipboard 山")
      panel.readSelection()
      panel.clipboardState.finish("")
      panel.close()
      panel.opened = true
      wait(10)
      verify(!panel.clipboardState.running)
      compare(panel.query, "Clipboard 山")
    }
    function test_stale_selection_data() {
      return [{tag: "query edited", change: "query"}, {tag: "close and reopen", change: "close"},
        {tag: "navigated away and back", change: "navigation"}, {tag: "account changed", change: "access"}]
    }
    function test_stale_selection(data) {
      panel.view = "lookup"
      panel.query = "Current typed 山"
      panel.readSelection()
      if (data.change === "query")
        panel.search("New typed 𠮷")
      else if (data.change === "close") {
        panel.close()
        panel.opened = true
      } else if (data.change === "navigation") {
        panel.navigate("zen")
        panel.navigate("lookup")
      } else
        panel.contentAccess = "another-authored-account"
      var kept = panel.query
      panel.clipboardState.finish("Old selected answer 山")
      compare(panel.query, kept)
      compare(panel.clipboardState.captured, "")
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class PanelDetailsTests(unittest.TestCase):
    def test_production_detail_callbacks_respect_current_view_and_access(self):
        source = (ROOT / "Panel.qml").read_text()
        functions = []
        for name in ("call", "showSubject", "navigate", "close", "readSelection", "search", "refreshSearch"):
            match = re.search(r"(?ms)^  function " + name + r"\(.*?(?=^  function )", source)
            self.assertIsNotNone(match, "Review the actual Panel function boundary for " + name)
            functions.append(match.group(0))
        clipboard = source.split("    id: clipboard\n", 1)[1].split("\n  MediaPlayer", 1)[0]
        clipboard_function = re.search(r"(?ms)^    function contextCurrent\(\) \{.*?^    \}", clipboard)
        clipboard_exit = re.search(r"(?ms)^    onExited: \{.*?^    \}", clipboard)
        self.assertIsNotNone(clipboard_function, "Review the actual clipboard context function")
        self.assertIsNotNone(clipboard_exit, "Review the actual clipboard exit handler")
        core = '''import QtQuick
import "WanaKana.mjs" as Kana
import "UnicodeText.mjs" as UnicodeText
Item {
  id: root
  required property var service
  property bool opened: true
  property string view: "dashboard"
  property string contentAccess: "authored-account"
  property int navigationSequence: 0
  property int detailSequence: 0
  property int searchSequence: 0
  property bool busy: false
  property string error: ""
  property var detail: null
  property string query: ""
  property bool queryTruncated: false
  property string searchType: "all"
  property string searchState: "all"
  property bool searching: false
  property var results: []
  QtObject { id: audio; function stop() {} }
  function focusContent() {}
  property alias clipboardState: clipboard
  QtObject {
    id: clipboard
    property bool running: false
    property bool primary: true
    property int requestNavigation: -1
    property int requestSearch: -1
    property string requestAccess: ""
    property string captured: ""
    signal exited()
    function finish(text) { captured = text; running = false; exited() }
'''
        core += clipboard_function.group(0) + "\n" + clipboard_exit.group(0) + "\n  }\n"
        lookup_source = (ROOT / "qml/Lookup.qml").read_text()
        lookup = lookup_source.split("\n  Label {", 1)[0]
        self.assertNotEqual(lookup, lookup_source, "Review actual Lookup behavior fixture boundary")
        lookup = re.sub(r"^import qs\..*\n", "", lookup, flags=re.M)
        lookup = re.sub(r"^  spacing:.*\n", "", lookup, flags=re.M)
        lookup += '\n  QtObject { id: searchField; property string text: root.controller.query; function forceActiveFocus() {} }\n'
        lookup_timer = re.search(r"(?ms)^  Timer \{\n    id: searchDelay.*?^  \}", lookup_source)
        self.assertIsNotNone(lookup_timer, "Review actual Lookup timer fixture boundary")
        lookup += lookup_timer.group(0) + "\n}\n"
        with tempfile.TemporaryDirectory(prefix="wanikani-panel-details-") as temporary:
            directory = Path(temporary)
            (directory / "PanelCore.qml").write_text(core + "\n".join(functions) + "}\n")
            (directory / "LookupCore.qml").write_text(lookup)
            shutil.copyfile(ROOT / "vendor" / "WanaKana.mjs", directory / "WanaKana.mjs")
            shutil.copyfile(ROOT / "qml" / "UnicodeText.mjs", directory / "UnicodeText.mjs")
            (directory / "tst_PanelDetails.qml").write_text(QML)
            process = subprocess.run([str(RUNNER), "-input", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertIn("18 passed", process.stdout)


if __name__ == "__main__":
    unittest.main()
