import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  required property var subject
  property bool expanded: false
  property bool busy: false
  property var examples: []
  property string error: ""
  property string notice: ""
  property bool complete: true
  property int generation: 0
  property int ownerSubjectId: -1
  readonly property bool contextAllowed: visible && typeof controller.kanjiExampleArgs === "function" && controller.kanjiExampleArgs(subject) !== null
  readonly property string contextKey: JSON.stringify([visible, contextAllowed, controller.opened, controller.view, controller.navigationSequence, controller.contentAccess, controller.service ? controller.service.ready : false, controller.service ? controller.service.locked : true, subject ? subject.id : null, controller.session ? controller.session.id : null, controller.session && controller.session.subject ? controller.session.subject.id : null, controller.detail ? controller.detail.id : null, controller.session ? controller.session.revision : null, controller.session ? controller.session.phase : null, controller.session ? controller.session.part : null, controller.session ? controller.session.lesson_flow : null, controller.snapshot ? controller.snapshot.last_sync : null, controller.snapshot ? controller.snapshot.session_revision : null, controller.snapshot ? controller.snapshot.pending : null, controller.snapshot ? controller.snapshot.attention : null])
  readonly property bool selectedAudio: controller.audioContext === "kanji_example" && controller.audioParentSubjectId === ownerSubjectId
  spacing: Style.space(8)

  function stopOwnedAudio() {
    if (selectedAudio && typeof controller.stopAudio === "function")
      controller.stopAudio()
  }
  function collapse() {
    generation++
    stopOwnedAudio()
    expanded = false
    busy = false
    examples = []
    error = ""
    notice = ""
    complete = true
    ownerSubjectId = -1
  }
  function current(key, expected) {
    return contextAllowed && expanded && key === contextKey && expected === generation
  }
  function loadExamples() {
    if (!contextAllowed || busy)
      return
    var args = controller.kanjiExampleArgs(subject)
    if (!args)
      return
    stopOwnedAudio()
    var key = contextKey
    var expected = ++generation
    ownerSubjectId = subject.id
    expanded = true
    busy = true
    error = ""
    notice = ""
    examples = []
    controller.service.request("kanji_examples", args, function (ok, data, message) {
      if (!root || !root.current(key, expected))
        return
      root.busy = false
      if (!ok || !data || data.parent_subject_id !== root.ownerSubjectId || !Array.isArray(data.examples) || data.examples.length > 3) {
        root.error = message || "Vocabulary recordings could not be checked. Try again."
        return
      }
      root.examples = data.examples
      root.complete = data.complete === true
      if (data.examples.length === 0)
        root.notice = ({
            protected_study: "Examples stay hidden while related graded study is unfinished.",
            pending_study: "This kanji or its examples have study results waiting to synchronize.",
            access_restricted: "This kanji is outside your current account access. Refresh your account to check.",
            stale_session: "Your saved study changed. Resume its current question before hearing examples.",
            unrevealed: "Examples become available when this kanji’s reading is revealed.",
            content_unavailable: "Related vocabulary information needs a cache refresh."
          })[data.reason] || "No eligible vocabulary recordings are available here yet. Examples awaiting graded study stay hidden."
      else if (!root.complete)
        root.notice = "Showing the available examples from a limited local check."
    })
  }
  onContextKeyChanged: collapse()
  Component.onDestruction: stopOwnedAudio()

  Label {
    Layout.fillWidth: true
    text: "Hear this kanji in a word"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Original recordings of whole vocabulary words. A kanji’s sound can change with the word."
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      objectName: "kanji-examples-open"
      text: root.busy ? "Checking examples…" : root.error ? "Retry vocabulary recordings" : root.expanded ? "Refresh examples" : "Show vocabulary recordings"
      enabled: root.contextAllowed && !root.busy
      onClicked: root.loadExamples()
    }
    Action {
      objectName: "kanji-examples-close"
      text: "Hide examples"
      visible: root.expanded
      onClicked: root.collapse()
    }
  }
  Repeater {
    model: root.expanded ? root.examples : []
    Card {
      id: exampleCard
      required property var modelData
      readonly property bool selectedClip: root.selectedAudio && root.controller.audioSubjectId === modelData.subject_id
      readonly property string playback: selectedClip ? root.controller.audioState || "" : ""
      readonly property var actualClip: selectedClip ? root.controller.audioExample || null : null
      Layout.fillWidth: true
      implicitHeight: exampleContent.implicitHeight + Style.space(24)
      ColumnLayout {
        id: exampleContent
        anchors.fill: parent
        anchors.margins: Style.space(12)
        spacing: Style.space(6)
        Label {
          objectName: "kanji-example-word-" + exampleCard.modelData.subject_id
          Layout.fillWidth: true
          text: exampleCard.actualClip && exampleCard.actualClip.characters || exampleCard.modelData.characters
          font.family: "Noto Sans CJK JP"
          font.pixelSize: 30
        }
        Label {
          Layout.fillWidth: true
          text: exampleCard.actualClip ? exampleCard.actualClip.pronunciation : exampleCard.modelData.pronunciation
          font.family: "Noto Sans CJK JP"
        }
        Label {
          Layout.fillWidth: true
          text: exampleCard.actualClip && exampleCard.actualClip.meaning || exampleCard.modelData.meaning
        }
        Label {
          Layout.fillWidth: true
          text: (exampleCard.modelData.learned ? "Learned vocabulary" : "Vocabulary preview · not learned yet") + " · " + (exampleCard.actualClip || exampleCard.modelData.cached ? "Recording available offline" : "Recording needs a download")
          font.pixelSize: Style.font.bodySmall
          secondary: true
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(8)
          Action {
            objectName: "kanji-example-play-" + exampleCard.modelData.subject_id
            text: exampleCard.playback === "loading" ? "Loading recording…" : exampleCard.playback === "playing" ? "Replay whole word" : exampleCard.playback === "failed" ? "Retry whole word" : "Play whole word"
            accessibleName: text + ": " + (exampleCard.actualClip && exampleCard.actualClip.characters || exampleCard.modelData.characters)
            enabled: root.contextAllowed && exampleCard.playback !== "loading"
            onClicked: root.controller.playKanjiExample(exampleCard.modelData, root.subject)
          }
          Action {
            objectName: "kanji-example-stop"
            text: "Stop"
            visible: exampleCard.playback === "playing"
            onClicked: root.controller.stopAudio()
          }
        }
        Label {
          Layout.fillWidth: true
          visible: exampleCard.selectedClip && text !== ""
          text: exampleCard.selectedClip ? root.controller.audioNotice : ""
          textColor: exampleCard.playback === "failed" ? Color.urgent : exampleCard.textColor
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.expanded && text !== ""
    text: root.error || root.notice
    textColor: root.error ? Color.urgent : Color.foreground
    font.pixelSize: Style.font.bodySmall
    Accessible.role: Accessible.StaticText
    Accessible.name: text
  }
}
