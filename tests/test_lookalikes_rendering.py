"""Render production comparisons and glyphs with independently authored content.

Only the shell theme and native button are adapted to plain Qt. Tests exercise
actual component bindings and synthetic button signals, not physical keys, IME,
the compositor, or screen-reader speech.
"""
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
  width: 500
  height: 2000
  color: "white"
  Kani.Lookalikes {
    id: comparison
    x: 10
    width: 460
    subject: null
  }
  TestCase {
    name: "LookalikesRendering"
    when: windowShown
    function fixture() {
      return {
        id: 990001, type: "kanji", characters: "未", images: [],
        meanings: ["Authored unripe <b>literal</b>"],
        readings: [{reading: "み", accepted: true}, {reading: "まだ", accepted: false}],
        visually_similar: [
          {id: 990002, type: "kanji", characters: "末", images: [],
            meanings: ["Authored end"], readings: [{reading: "まつ", accepted: true}]},
          {id: 990003, type: "kanji", characters: "朱", images: [],
            meanings: ["Authored vermilion"], readings: [{reading: "しゅ", accepted: true}]}
        ]
      }
    }
    function descendants(item) {
      var result = []
      for (var i = 0; i < item.children.length; i++) {
        var child = item.children[i]
        result.push(child)
        result = result.concat(descendants(child))
      }
      return result
    }
    function labels() {
      return descendants(comparison).filter(function (item) {
        // Production Label and JapaneseText explicitly use NativeRendering;
        // the shell-button adapter's private Text is outside this assertion.
        return item.textFormat !== undefined && item.text !== undefined && item.renderType === Text.NativeRendering
      })
    }
    function textItem(text) {
      var matches = labels().filter(function (item) { return item.text === text })
      compare(matches.length, 1, "One production text item: " + text)
      return matches[0]
    }
    function action(text) {
      var matches = descendants(comparison).filter(function (item) {
        return item.objectName === "fixture-action" && item.text === text
      })
      compare(matches.length, 1, "One comparison action: " + text)
      return matches[0]
    }
    function glyphs() {
      return descendants(comparison).filter(function (item) {
        return item.hasCharacters !== undefined && item.displayReady !== undefined
      })
    }
    function reveal() {
      action("Tell them apart · 2").clicked()
      tryCompare(comparison, "expanded", true)
      verify(waitForRendering(comparison))
      compare(glyphs().length, 2)
    }
    function init() {
      failOnWarning(/.*/)
      comparison.subject = null
      comparison.width = 460
      comparison.showMeaning = true
      comparison.showReading = true
      comparison.subject = fixture()
      verify(waitForRendering(comparison))
    }
    function test_default_collapsed_does_not_create_answer_cards() {
      verify(comparison.visible)
      verify(!comparison.expanded)
      compare(glyphs().length, 0)
      verify(action("Tell them apart · 2").visible)
      compare(action("Tell them apart · 2").Accessible.name, "Compare visually similar kanji")
      reveal()
      action("Close comparison").clicked()
      tryCompare(comparison, "expanded", false)
      tryVerify(function () { return glyphs().length === 0 })
    }
    function test_selected_candidate_switches_both_glyph_and_answers() {
      reveal()
      verify(textItem("Authored end").visible)
      action("朱").clicked()
      compare(comparison.selectedIndex, 1)
      verify(waitForRendering(comparison))
      compare(glyphs()[1].subject.id, 990003)
      verify(textItem("Authored vermilion").visible)
      verify(textItem("しゅ").visible)
      verify(!labels().some(function (item) { return item.text === "Authored end" }))
      verify(action("朱").selected)
      verify(!action("末").selected)
    }
    function test_answer_visibility_data() {
      return [
        {tag: "meaning only", meaning: true, reading: false},
        {tag: "reading only", meaning: false, reading: true},
        {tag: "neither part", meaning: false, reading: false},
        {tag: "both parts", meaning: true, reading: true}
      ]
    }
    function test_answer_visibility(data) {
      reveal()
      comparison.showMeaning = data.meaning
      comparison.showReading = data.reading
      verify(waitForRendering(comparison))
      compare(comparison.visible, data.meaning || data.reading)
      var rendered = labels()
      compare(rendered.some(function (item) { return item.text === "Authored end" }), data.meaning)
      compare(rendered.some(function (item) { return item.text === "まつ" }), data.reading)
      verify(!rendered.some(function (item) { return item.text.indexOf("まだ") >= 0 }), "Unaccepted reading is withheld")
      for (var i = 0; i < rendered.length; i++) {
        var item = rendered[i]
        if (!item.visible || item.text.length === 0)
          verify(item.Accessible.ignored, "Hidden or empty text is absent from accessibility")
      }
      if (data.meaning) {
        var meaning = textItem("Authored unripe <b>literal</b>")
        compare(meaning.textFormat, Text.PlainText)
        compare(meaning.Accessible.name, meaning.text)
      }
    }
    function test_subject_change_reset_and_list_shrink_clear_previous_selection() {
      reveal()
      action("朱").clicked()
      var next = fixture()
      next.visually_similar = [next.visually_similar[0]]
      comparison.subject = next
      compare(comparison.selectedIndex, 0)
      verify(comparison.expanded)
      verify(waitForRendering(comparison))
      compare(glyphs()[1].subject.id, 990002)
      next = fixture()
      next.id = 990004
      comparison.subject = next
      compare(comparison.selectedIndex, 0)
      verify(!comparison.expanded)
      compare(glyphs().length, 0)
      comparison.subject = null
      verify(!comparison.visible)
      compare(comparison.candidates.length, 0)
      compare(comparison.comparison, null)
      compare(glyphs().length, 0)
    }
    function test_empty_and_malformed_lists_data() {
      return [
        {tag: "missing list", value: undefined},
        {tag: "null list", value: null},
        {tag: "object list", value: ({})},
        {tag: "string list", value: "末"},
        {tag: "empty list", value: []},
        {tag: "null candidate", value: [null]},
        {tag: "empty candidate", value: [{}]},
        {tag: "missing answer arrays", value: [{id: 990005, characters: "木"}]},
        {tag: "invalid answer arrays", value: [{id: 990005, characters: "木", meanings: null, readings: "もく"}]},
        {tag: "invalid answer entries", value: [{id: 990005, characters: "木", meanings: [null], readings: [null]}]}
      ]
    }
    function test_empty_and_malformed_lists(data) {
      var next = fixture()
      next.visually_similar = data.value
      comparison.subject = next
      comparison.expanded = true
      verify(waitForRendering(comparison))
      compare(comparison.selectedIndex, 0)
      compare(comparison.candidates.length, 0, "Invalid candidates cannot create unusable comparison cards")
      verify(!comparison.visible)
      compare(glyphs().length, 0)
    }
    function test_valid_candidate_survives_malformed_neighbors() {
      var next = fixture()
      next.visually_similar = [null, {}, next.visually_similar[1], {id: 990005, characters: "木"}]
      comparison.subject = next
      compare(comparison.candidates.length, 1)
      action("Tell them apart · 1").clicked()
      verify(waitForRendering(comparison))
      compare(glyphs().length, 2)
      compare(glyphs()[1].subject.id, 990003)
      verify(textItem("Authored vermilion").visible)
      next = fixture()
      next.visually_similar = []
      comparison.subject = next
      verify(!comparison.expanded, "Losing all candidates collapses the same subject")
      verify(!comparison.visible)
      compare(glyphs().length, 0)
    }
    function test_narrow_cards_keep_japanese_and_long_meanings_data() {
      return [{tag: "320 px", width: 320}, {tag: "460 px", width: 460}]
    }
    function test_narrow_cards_keep_japanese_and_long_meanings(data) {
      var next = fixture()
      next.meanings = ["An independently authored long meaning with several distinct words"]
      next.visually_similar[0].meanings = ["Another independently authored comparison meaning"]
      next.readings = [{reading: "みじかいことばながいことば", accepted: true}]
      next.visually_similar[0].readings = [{reading: "まつながいよみかた", accepted: true}]
      comparison.width = data.width
      comparison.subject = next
      reveal()
      verify(textItem(next.meanings[0]).visible)
      verify(textItem(next.visually_similar[0].meanings[0]).visible)
      verify(textItem(next.readings[0].reading).visible)
      verify(textItem(next.visually_similar[0].readings[0].reading).visible)
      var texts = labels().filter(function (item) { return item.visible && item.text.length > 0 })
      for (var i = 0; i < texts.length; i++) {
        var item = texts[i]
        var point = item.mapToItem(comparison, 0, 0)
        verify(point.x >= -1, "Text begins inside comparison: " + item.text)
        verify(point.x + item.width <= comparison.width + 1, "Text stays inside comparison: " + item.text)
        verify(item.contentWidth <= item.width + 1, "Full text width fits: " + item.text)
        verify(item.contentHeight <= item.height + 1, "Full text height fits: " + item.text)
        verify(!item.truncated, "Japanese and meanings remain untruncated")
      }
      compare(glyphs().length, 2)
      for (var j = 0; j < glyphs().length; j++)
        verify(glyphs()[j].displayReady)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class LookalikesRenderingTests(unittest.TestCase):
    def test_authored_comparison_views(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-lookalikes-rendering-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("Lookalikes.qml", "SubjectGlyph.qml", "RadicalImage.qml", "JapaneseText.qml", "Label.qml", "Card.qml"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text('import QtQuick\nimport QtQuick.Controls\nButton {\n'
                '  objectName: "fixture-action"\n'
                '  property bool selected: false\n'
                '  property string accessibleName: text\n'
                '  Accessible.name: accessibleName\n'
                '  Accessible.ignored: !visible\n}\n')
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                '  function space(value) { return value }\n'
                '  readonly property var font: ({family: "Sans", body: 14, bodySmall: 12, title: 20})\n'
                '  readonly property int cornerRadius: 6\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                '  readonly property color foreground: "#202020"\n'
                '  readonly property color accent: "#006699"\n}\n')
            (directory / "tst_Lookalikes.qml").write_text(QML)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertNotIn("QWARN", process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
