"""Render the real subject detail layout with authored notes and Qt-only controls.

The shell theme/control adapters are test fixtures; note blocks, visibility,
plain-text labels, editor, and lesson ordering are copied from production QML.
Native shell appearance is verified separately by the desktop QA workflow.
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
  width: 600
  height: 1800
  color: "white"
  QtObject {
    id: service
    property bool ready: true
    property bool allowEditorWrites: false
    property var savedDraft: null
    signal snapshotChanged()
    function request(method, args, callback) {
      if (!allowEditorWrites || method !== "editor_draft")
        throw new Error("Read-only lesson notes must not issue requests")
      savedDraft = args.values
      callback(true, {dirty: true}, "")
    }
  }
  QtObject {
    id: controller
    property var service: null
    property bool opened: true
    property bool busy: false
    property var detail: null
    property string error: ""
    property string contentAccess: "authored-account"
  }
  Kani.SubjectDetails {
    id: details
    x: 10
    width: 380
    controller: controller
    subject: ({id: 990001, meanings: [], readings: [], components: [], related: [], sentences: [], material: {}})
  }
  TestCase {
    name: "StudyNotes"
    when: windowShown
    function fixture() {
      return {
        id: 990001,
        meanings: ["Authored mountain"],
        readings: [{reading: "さん", type: "onyomi", accepted: true}],
        meaning_mnemonic: "An independently authored meaning mnemonic.",
        reading_mnemonic: "An independently authored reading mnemonic.",
        meaning_hint: "", reading_hint: "",
        sentences: [{ja: "山を見ます。", en: "An authored example sentence."}],
        components: [], related: [], audio: [], audio_available: false,
        material: {
          meaning_synonyms: [],
          meaning_note: "My <b>literal</b> meaning note\nA second line.",
          reading_note: "My reading note: さん is the sound."
        }
      }
    }
    function child(name) {
      var item = findChild(details, "subject-" + name)
      verify(item !== null, name + " is part of the actual subject detail view")
      return item
    }
    function init() {
      failOnWarning(/.*/)
      controller.service = service
      service.allowEditorWrites = false
      service.savedDraft = null
      details.editable = false
      details.showMeaning = true
      details.showReading = true
      details.subject = fixture()
      verify(waitForRendering(details))
    }
    function test_lesson_sections_keep_each_personal_note_with_its_mnemonic() {
      verify(child("meaning-heading").visible)
      verify(child("meaning-note").visible)
      verify(child("reading-heading").visible)
      verify(child("reading-note").visible)
      verify(child("context-heading").visible)
      verify(child("meaning-heading").y < child("meaning-note").y)
      verify(child("meaning-note").y < child("reading-heading").y)
      verify(child("reading-heading").y < child("reading-note").y)
      verify(child("reading-note").y < child("context-heading").y)
    }
    function test_meaning_feedback_does_not_reveal_reading_notes_or_context() {
      details.showReading = false
      verify(child("meaning-note").visible)
      verify(!child("reading-note").visible)
      verify(!child("reading-heading").visible)
      verify(!child("context-heading").visible)
      verify(child("reading-note-text").Accessible.ignored)
    }
    function test_reading_feedback_does_not_reveal_meaning_notes_or_context() {
      details.showMeaning = false
      verify(!child("meaning-note").visible)
      verify(!child("meaning-heading").visible)
      verify(child("reading-note").visible)
      verify(!child("context-heading").visible)
      verify(child("meaning-note-text").Accessible.ignored)
    }
    function test_question_hides_both_parts_and_editable_lookup_does_not_duplicate_notes() {
      details.showMeaning = false
      details.showReading = false
      verify(!child("meaning-note").visible)
      verify(!child("reading-note").visible)
      details.showMeaning = true
      details.showReading = true
      details.editable = true
      verify(!child("meaning-note").visible)
      verify(!child("reading-note").visible)
    }
    function test_plain_text_and_multiline_notes_wrap_without_clipping() {
      var meaning = child("meaning-note-text")
      compare(meaning.text, details.subject.material.meaning_note)
      compare(meaning.textFormat, Text.PlainText)
      compare(meaning.Accessible.name, meaning.text)
      var next = fixture()
      next.material.meaning_note = "Authored long note 日本語. ".repeat(70)
      details.subject = next
      verify(waitForRendering(details))
      verify(meaning.contentHeight <= meaning.height + 1)
      verify(meaning.contentWidth <= meaning.width + 1)
      verify(meaning.lineCount > 2)
      verify(!meaning.truncated)
    }
    function test_new_subject_clears_old_notes_and_radicals_have_no_empty_reading_heading() {
      var next = fixture()
      next.id = 990002
      next.material = {meaning_synonyms: [], meaning_note: "  \n", reading_note: ""}
      next.readings = []
      next.reading_mnemonic = ""
      next.sentences = []
      details.subject = next
      verify(!child("meaning-note").visible)
      verify(!child("reading-note").visible)
      verify(!child("reading-heading").visible)
      verify(!child("context-heading").visible)
      compare(child("reading-note-text").text, "")
      details.subject = null
      compare(child("meaning-note-text").text, "")
      compare(child("reading-note-text").text, "")
    }
    function test_editable_note_limits_preserve_a_supplementary_kanji() {
      service.allowEditorWrites = true
      details.editable = true
      var expected = "a".repeat(1999) + "𠮷"
      details.authoredMeaningEditor.text = expected + " extra"
      compare(details.authoredMeaningEditor.text.codePointAt(1999), 0x20bb7)
      compare(details.authoredMeaningEditor.text, expected)
      compare(service.savedDraft.meaning_note, expected)
      details.authoredReadingEditor.text = expected + " extra"
      compare(details.authoredReadingEditor.text, expected)
      compare(service.savedDraft.reading_note, expected)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class StudyNotesRenderingTests(unittest.TestCase):
    def test_authored_lesson_and_feedback_views(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-study-notes-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("SubjectDetails.qml", "Label.qml", "UnicodeText.mjs", "Theme.mjs", "Pronunciation.qml"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            # Expose the existing private inputs for interaction; their actual
            # text handlers/limit behavior remain unchanged from production.
            details = qml / "SubjectDetails.qml"
            details.write_text(details.read_text().replace("  id: root\n", "  id: root\n"
                "  property alias authoredMeaningEditor: meaningNote\n"
                "  property alias authoredReadingEditor: readingNote\n", 1))
            (qml / "Action.qml").write_text("import QtQuick.Controls\nButton { property string accessibleName: text }\n")
            (qml / "Lookalikes.qml").write_text("import QtQuick\nItem { property var subject; property bool showMeaning; property bool showReading }\n")
            (qml / "KanjiExamples.qml").write_text("import QtQuick\nItem { property var controller; property var subject }\n")
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                '  function space(value) { return value }\n'
                '  readonly property var font: ({family: "Sans", body: 14, bodySmall: 12, title: 20})\n'
                '  readonly property int cornerRadius: 6\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                '  readonly property color background: \"#ffffff\"\n  readonly property color foreground: "#202020"\n'
                '  readonly property color accent: "#006699"\n'
                '  readonly property color urgent: "#bb0000"\n}\n')
            ui = directory / "qs" / "Ui"
            ui.mkdir()
            (ui / "qmldir").write_text("module qs.Ui\nTextField 1.0 TextField.qml\n")
            (ui / "TextField.qml").write_text("import QtQuick\nimport QtQuick.Controls\n"
                "TextField { property color foreground: '#202020'; property color accent: '#006699' }\n")
            (directory / "tst_StudyNotes.qml").write_text(QML)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertIn("9 passed", process.stdout)


if __name__ == "__main__":
    unittest.main()
