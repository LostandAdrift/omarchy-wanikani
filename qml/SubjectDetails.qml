import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui as Ui
import "UnicodeText.mjs" as UnicodeText

ColumnLayout {
  id: root
  required property var subject
  required property var controller
  property bool showMeaning: true
  property bool showReading: true
  property bool editable: false
  property bool editorReady: false
  property bool restoringEditor: false
  property bool preserveEditor: false
  property bool refreshingDetails: false
  property int editorSubjectId: 0
  property int editGeneration: 0
  property bool editorDirty: false
  property bool draftSaving: false
  property string draftError: ""
  property var savedEditor: ({
      synonyms_text: "",
      meaning_note: "",
      reading_note: ""
    })
  readonly property bool composingEditor: synonyms.inputMethodComposing || meaningNote.inputMethodComposing || readingNote.inputMethodComposing
  readonly property bool editorAvailable: !!(controller.service && controller.service.ready)
  readonly property string meaningNoteText: subject && subject.material ? subject.material.meaning_note || "" : ""
  readonly property string readingNoteText: subject && subject.material ? subject.material.reading_note || "" : ""
  spacing: Style.space(12)

  function rawEditor() {
    return {
      synonyms_text: synonyms.text,
      meaning_note: meaningNote.text,
      reading_note: readingNote.text
    }
  }
  function sameEditor(a, b) {
    return a.synonyms_text === b.synonyms_text && a.meaning_note === b.meaning_note && a.reading_note === b.reading_note
  }
  function restoreEditor(force) {
    if (!editorReady)
      return
    var id = subject ? Number(subject.id) : 0
    var material = subject ? subject.material : ({})
    savedEditor = {
      synonyms_text: (material.meaning_synonyms || []).join(", "),
      meaning_note: material.meaning_note || "",
      reading_note: material.reading_note || ""
    }
    // Refreshing metadata must not replace focused input or an in-flight edit.
    if (id === editorSubjectId && !force && (preserveEditor || editorDirty || draftSaving || composingEditor)) {
      editorDirty = !sameEditor(rawEditor(), savedEditor)
      return
    }
    restoringEditor = true
    editorSubjectId = id
    editGeneration++
    var values = subject && subject.editor_draft ? subject.editor_draft : savedEditor
    synonyms.text = values.synonyms_text
    meaningNote.text = values.meaning_note
    readingNote.text = values.reading_note
    editorDirty = !!(subject && subject.editor_dirty)
    draftSaving = false
    draftError = ""
    restoringEditor = false
  }
  function persistEditor(field) {
    if (!editorReady || restoringEditor || !editable || !editorSubjectId)
      return
    // TextArea has no maximumLength. Limit committed text without disturbing
    // an IME preedit or splitting a Unicode character at the boundary.
    if (field && !field.inputMethodComposing) {
      var characters = UnicodeText.characters(field.text)
      if (characters.length > 2000) {
        var cursor = field.cursorPosition
        restoringEditor = true
        field.text = characters.slice(0, 2000).join("")
        field.cursorPosition = Math.min(cursor, field.text.length)
        restoringEditor = false
      }
    }
    var values = rawEditor()
    if (UnicodeText.characters(values.meaning_note).length > 2000 || UnicodeText.characters(values.reading_note).length > 2000)
      // The composition-ended handler will limit and persist it.
      return
    var id = editorSubjectId
    var generation = ++editGeneration
    editorDirty = !sameEditor(values, savedEditor)
    draftSaving = true
    draftError = ""
    // Every committed edit is sent immediately. There is no timer or close-time
    // flush that could drop the final character when Escape destroys a view.
    controller.service.request("editor_draft", {
      subject_id: id,
      values: values
    }, function (ok, data, message) {
      if (!root || root.editorSubjectId !== id || root.editGeneration !== generation)
        return
      root.draftSaving = false
      if (ok)
        root.editorDirty = data.dirty
      else {
        root.draftError = message || "The draft could not be kept. Try again before closing."
        root.controller.error = root.draftError
      }
    })
  }
  function materialResult(ok, data, id, generation) {
    if (!ok || !data || !controller.detail || controller.detail.id !== id)
      return
    var newer = editorSubjectId === id && editGeneration !== generation
    preserveEditor = newer
    controller.detail = data
    preserveEditor = false
    if (!newer && editorSubjectId === id)
      restoreEditor(true)
  }
  function saveEditor() {
    var values = rawEditor()
    var id = editorSubjectId
    var generation = editGeneration
    controller.call("set_material", {
      subject_id: id,
      values: {
        meaning_synonyms: values.synonyms_text.split(",").map(function (s) {
          return s.trim()
        }).filter(function (s) {
          return s.length > 0
        }),
        meaning_note: values.meaning_note,
        reading_note: values.reading_note
      },
      editor_draft: values
    }, function (ok, data) {
      if (root)
        root.materialResult(ok, data, id, generation)
    })
  }
  function discardEditor() {
    var id = editorSubjectId
    var generation = editGeneration
    controller.call("editor_discard", {
      subject_id: id,
      expected: rawEditor()
    }, function (ok, data) {
      if (root)
        root.materialResult(ok, data, id, generation)
    })
  }
  onSubjectChanged: restoreEditor(false)
  Component.onCompleted: {
    editorReady = true
    restoreEditor(true)
  }
  Connections {
    target: root.controller.service
    function onSnapshotChanged() {
      if (!root.editable || !root.controller.opened || !root.editorSubjectId || root.refreshingDetails)
        return
      var id = root.editorSubjectId
      var owner = root.controller
      var access = owner.contentAccess
      root.refreshingDetails = true
      owner.service.request("details", {
        subject_id: id
      }, function (ok, data, message) {
        if (!root)
          return
        root.refreshingDetails = false
        if (owner.contentAccess === access && owner.detail && owner.detail.id === id) {
          if (ok)
            owner.detail = data
          else {
            owner.detail = null
            owner.error = message || "This subject is no longer available. Your draft is kept on this computer."
            owner.search(owner.query)
          }
        }
      })
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!(root.subject && root.subject.content_error)
    text: root.subject ? root.subject.content_error || "" : ""
    color: Color.urgent
  }
  Label {
    objectName: "subject-meaning-heading"
    Layout.fillWidth: true
    visible: root.showMeaning
    text: "Meaning"
    font.bold: true
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: root.showMeaning
    text: root.subject ? root.subject.meanings.join(" · ") : ""
    font.pixelSize: Style.font.title
    color: Color.accent
  }
  Label {
    Layout.fillWidth: true
    visible: root.showMeaning
    text: root.subject ? root.subject.meaning_mnemonic : ""
  }
  Label {
    Layout.fillWidth: true
    visible: root.showMeaning && text !== ""
    text: root.subject ? root.subject.meaning_hint : ""
    color: Qt.alpha(Color.foreground, 0.76)
  }
  ColumnLayout {
    objectName: "subject-meaning-note"
    Layout.fillWidth: true
    visible: !root.editable && root.showMeaning && root.meaningNoteText.trim() !== ""
    spacing: Style.space(4)
    Label {
      text: "Your meaning note"
      font.bold: true
      font.pixelSize: Style.font.bodySmall
      color: Color.accent
    }
    Label {
      objectName: "subject-meaning-note-text"
      Layout.fillWidth: true
      text: root.meaningNoteText
    }
  }
  Label {
    objectName: "subject-reading-heading"
    Layout.fillWidth: true
    visible: root.showReading && root.subject && root.subject.readings.length > 0
    text: "Reading"
    font.bold: true
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: root.showReading && text !== ""
    text: root.subject ? root.subject.readings.map(function (r) {
      return r.reading + (r.type ? " (" + r.type + ")" : "")
    }).join(" · ") : ""
    font.family: "Noto Sans CJK JP"
  }
  Label {
    Layout.fillWidth: true
    visible: root.showReading && text !== ""
    text: root.subject ? root.subject.reading_mnemonic : ""
  }
  Label {
    Layout.fillWidth: true
    visible: root.showReading && text !== ""
    text: root.subject ? root.subject.reading_hint : ""
    color: Qt.alpha(Color.foreground, 0.76)
  }
  ColumnLayout {
    objectName: "subject-reading-note"
    Layout.fillWidth: true
    visible: !root.editable && root.showReading && root.readingNoteText.trim() !== ""
    spacing: Style.space(4)
    Label {
      text: "Your reading note"
      font.bold: true
      font.pixelSize: Style.font.bodySmall
      color: Color.accent
    }
    Label {
      objectName: "subject-reading-note-text"
      Layout.fillWidth: true
      text: root.readingNoteText
    }
  }
  RowLayout {
    visible: root.showReading && root.subject && root.subject.audio_available
    Action {
      text: "Play pronunciation"
      enabled: root.subject && root.subject.audio.length > 0
      onClicked: root.controller.play(root.subject)
    }
    Label {
      text: root.subject && root.subject.audio.length ? "Cached for offline use" : "Audio not cached yet"
      color: Qt.alpha(Color.foreground, 0.76)
      font.pixelSize: Style.font.bodySmall
    }
  }
  Label {
    objectName: "subject-context-heading"
    Layout.fillWidth: true
    visible: root.showMeaning && root.showReading && root.subject && root.subject.sentences.length > 0
    text: "In context"
    font.bold: true
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Repeater {
    model: root.showMeaning && root.showReading && root.subject ? root.subject.sentences : []
    ColumnLayout {
      required property var modelData
      Layout.fillWidth: true
      Label {
        Layout.fillWidth: true
        text: modelData.ja
        font.family: "Noto Sans CJK JP"
      }
      Label {
        Layout.fillWidth: true
        text: modelData.en
        color: Qt.alpha(Color.foreground, 0.76)
        font.pixelSize: Style.font.bodySmall
      }
    }
  }
  Lookalikes {
    Layout.fillWidth: true
    subject: root.subject
    showMeaning: root.showMeaning
    showReading: root.showReading
  }
  Label {
    text: "Made from"
    font.bold: true
    visible: root.showMeaning && root.subject && root.subject.components.length > 0
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    visible: root.showMeaning
    Repeater {
      model: root.subject ? root.subject.components : []
      Action {
        required property var modelData
        text: modelData.characters + " · " + modelData.meaning
        enabled: root.editable
        onClicked: root.controller.showSubject(modelData.id)
      }
    }
  }
  Label {
    text: "Related subjects"
    font.bold: true
    visible: root.showMeaning && root.showReading && root.subject && root.subject.related.length > 0
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    visible: root.showMeaning && root.showReading
    Repeater {
      model: root.subject ? root.subject.related : []
      Action {
        required property var modelData
        text: modelData.characters + " · " + modelData.meaning
        enabled: root.editable
        onClicked: root.controller.showSubject(modelData.id)
      }
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.editable
    spacing: Style.space(9)
    Label {
      text: "Your study material"
      font.bold: true
    }
    Label {
      Layout.fillWidth: true
      text: root.subject && root.subject.material_pending ? "Your local edit is waiting to sync." : "Synonyms and notes synchronize with WaniKani. Separate synonyms with commas."
      color: Qt.alpha(Color.foreground, 0.76)
      font.pixelSize: Style.font.bodySmall
    }
    Ui.TextField {
      id: synonyms
      Layout.fillWidth: true
      placeholderText: "Meaning synonyms, separated by commas"
      maximumLength: 2000
      readOnly: !root.editorAvailable
      onTextChanged: root.persistEditor(null)
      Accessible.name: "Meaning synonyms"
    }
    Controls.TextArea {
      id: meaningNote
      Layout.fillWidth: true
      Layout.preferredHeight: Style.space(90)
      readOnly: !root.editorAvailable
      textFormat: TextEdit.PlainText
      onTextChanged: root.persistEditor(meaningNote)
      onInputMethodComposingChanged: if (!inputMethodComposing)
        root.persistEditor(meaningNote)
      placeholderText: "Your meaning note"
      color: Color.foreground
      placeholderTextColor: Qt.alpha(Color.foreground, 0.76)
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      wrapMode: TextEdit.Wrap
      background: Rectangle {
        color: Qt.alpha(Color.foreground, 0.04)
        border.color: meaningNote.activeFocus ? Color.accent : Qt.alpha(Color.foreground, 0.76)
        radius: Style.cornerRadius
      }
      Accessible.name: "Meaning note"
    }
    Controls.TextArea {
      id: readingNote
      Layout.fillWidth: true
      Layout.preferredHeight: Style.space(90)
      readOnly: !root.editorAvailable
      textFormat: TextEdit.PlainText
      onTextChanged: root.persistEditor(readingNote)
      onInputMethodComposingChanged: if (!inputMethodComposing)
        root.persistEditor(readingNote)
      placeholderText: "Your reading note"
      color: Color.foreground
      placeholderTextColor: Qt.alpha(Color.foreground, 0.76)
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      wrapMode: TextEdit.Wrap
      background: Rectangle {
        color: Qt.alpha(Color.foreground, 0.04)
        border.color: readingNote.activeFocus ? Color.accent : Qt.alpha(Color.foreground, 0.76)
        radius: Style.cornerRadius
      }
      Accessible.name: "Reading note"
    }
    Label {
      Layout.fillWidth: true
      text: root.draftError || (root.draftSaving ? "Keeping your draft…" : root.editorDirty ? "Draft kept on this computer. Save notes to apply it." : "Notes are up to date.")
      color: root.draftError ? Color.urgent : Qt.alpha(Color.foreground, 0.76)
      font.pixelSize: Style.font.bodySmall
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        text: "Save notes & synonyms"
        enabled: root.editorAvailable && !root.controller.busy && root.subject && !root.subject.material_pending && root.editorDirty && !root.composingEditor
        onClicked: root.saveEditor()
      }
      Action {
        text: "Discard draft"
        enabled: root.editorAvailable && !root.controller.busy && root.editorDirty && !root.composingEditor
        onClicked: root.discardEditor()
      }
    }
  }
}
