import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui
import "Theme.mjs" as Theme
import "../vendor/WanaKana.mjs" as Kana

ColumnLayout {
  id: root
  required property var controller
  readonly property var core: controller.dictation
  readonly property var session: core.session
  readonly property var status: core.status || ({})
  readonly property bool interactive: visible && core.active
  readonly property bool busy: core.loading || core.actionBusy || core.mediaBusy || core.heardBusy || core.audioRecovering === true
  readonly property bool question: !!session && session.phase === "question" && !session.unavailable
  readonly property bool feedback: !!session && session.phase === "feedback" && !session.unavailable && !!session.feedback && !!session.subject
  readonly property bool complete: !!session && session.phase === "complete" && !session.unavailable
  readonly property bool saved: !!status.saved && status.saved.phase !== "complete"
  readonly property string cardKey: session ? [session.id, session.index, session.phase, session.media_handle || "", session.unavailable || ""].join(":") : ""
  property string restoredKey: ""
  property bool restoring: false
  property bool converting: false
  property bool feedbackFocus: false
  property string restoredPreedit: ""
  spacing: Style.space(16)

  function focusInput() {
    if (!interactive)
      return
    if (question && core.heard)
      answer.forceActiveFocus(Qt.TabFocusReason)
    else if (question)
      playButton.forceActiveFocus(Qt.TabFocusReason)
    else if (feedback)
      continueButton.forceActiveFocus(Qt.TabFocusReason)
    else if (complete)
      doneButton.forceActiveFocus(Qt.TabFocusReason)
    else
      startButton.forceActiveFocus(Qt.TabFocusReason)
  }
  function restoreInput() {
    if (cardKey === restoredKey)
      return
    restoredKey = cardKey
    restoring = true
    answer.text = question ? session.draft || "" : ""
    answer.cursorPosition = question && Number.isInteger(session.draft_cursor) ? Math.min(answer.text.length, session.draft_cursor) : answer.text.length
    restoredPreedit = question ? session.preedit || "" : ""
    restoring = false
    if (feedbackFocus && feedback) {
      feedbackFocus = false
      Qt.callLater(function () {
        if (root.interactive && root.feedback)
          continueButton.forceActiveFocus(Qt.TabFocusReason)
      })
    } else if (session) {
      var expected = cardKey
      Qt.callLater(function () {
        if (root.interactive && root.cardKey === expected)
          root.focusInput()
      })
    }
  }
  function saveInput() {
    if (!restoring && !converting && interactive && question && !core.actionBusy && restoredKey === cardKey)
      core.saveDraft(answer.text, answer.cursorPosition, answer.preeditText)
  }
  function convertInput() {
    if (restoring || converting || !interactive || !question)
      return
    if (!answer.inputMethodComposing) {
      var caret = answer.cursorPosition
      var value = Kana.toHiragana(answer.text, {
        IMEMode: true,
        convertLongVowelMark: false
      })
      var prefix = Kana.toHiragana(answer.text.slice(0, caret), {
        IMEMode: true,
        convertLongVowelMark: false
      })
      if (value !== answer.text) {
        converting = true
        answer.text = value
        answer.cursorPosition = prefix.length
        converting = false
      }
    }
    restoredPreedit = ""
    saveInput()
  }
  function submit() {
    if (!interactive || !question || !core.canCheck || answer.inputMethodComposing)
      return
    var text = Kana.toHiragana(answer.text, {
      IMEMode: false,
      convertLongVowelMark: false
    })
    converting = true
    answer.text = text
    answer.cursorPosition = text.length
    converting = false
    feedbackFocus = true
    core.check(text)
  }
  onCardKeyChanged: Qt.callLater(restoreInput)
  Component.onCompleted: Qt.callLater(restoreInput)
  Connections {
    target: root.core
    function onHeardChanged() {
      if (root.interactive && root.question && root.core.heard && playButton.activeFocus)
        answer.forceActiveFocus(Qt.TabFocusReason)
    }
  }

  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    Action {
      text: "Recall meaning"
      enabled: root.interactive
      onClicked: root.controller.navigate("listen")
    }
    Action {
      text: "Type kana"
      selected: true
      enabled: root.interactive
    }
  }
  Label {
    Layout.fillWidth: true
    text: "KANA DICTATION · LOCAL PROGRESS"
    secondary: true
    font.pixelSize: Style.font.bodySmall
    font.letterSpacing: 1.5
  }
  Label {
    objectName: "dictation-introduction-title"
    Layout.fillWidth: true
    visible: !root.session
    text: "Listen & type."
    font.pixelSize: Style.space(30)
    font.bold: true
  }
  Label {
    objectName: "dictation-introduction-copy"
    Layout.fillWidth: true
    visible: !root.session
    text: "Catch the sounds of a familiar word. Type kana, then compare it with the recording. Your WaniKani reviews and lesson progress stay separate."
    secondary: true
  }
  Label {
    objectName: "dictationError"
    Layout.fillWidth: true
    visible: !!root.core.error
    text: root.core.error
    textColor: Color.urgent
  }
  Flow {
    Layout.fillWidth: true
    visible: !root.session || !!root.core.error
    spacing: Style.space(8)
    Action {
      id: startButton
      objectName: "dictationStart"
      visible: !root.session
      text: root.saved ? "Resume dictation" : "Start up to five words"
      selected: true
      enabled: root.interactive && !root.busy && (root.saved || (root.status.available || 0) > 0)
      onClicked: root.core.start()
    }
    Action {
      text: "Refresh dictation"
      objectName: "dictationRefresh"
      enabled: root.interactive && !root.busy
      onClicked: root.core.refresh()
    }
  }
  Label {
    objectName: "dictationAvailability"
    Layout.fillWidth: true
    visible: !root.session
    text: root.core.loading ? "Checking cached recordings…" : root.status.message || "Learned vocabulary with cached recordings will appear here."
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    visible: !root.session || root.complete
    text: typeof root.status.new_remaining === "number" ? root.status.new_remaining + " of 5 new dictation words left today. Meaning listening has its own allowance." : "Five new dictation words per day, separate from meaning listening."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Card {
    Layout.fillWidth: true
    visible: !!root.session
    implicitHeight: practice.implicitHeight + Style.space(36)
    ColumnLayout {
      id: practice
      anchors.fill: parent
      anchors.margins: Style.space(18)
      spacing: Style.space(14)
      Label {
        Layout.fillWidth: true
        text: root.session ? root.complete ? "Batch complete" : "Word " + (root.session.index + 1) + " of " + root.session.total : ""
        font.bold: true
      }
      Label {
        objectName: "dictationUnavailable"
        Layout.fillWidth: true
        visible: !!root.session && !!root.session.unavailable
        text: root.session ? root.session.unavailable || "" : ""
        textColor: Color.urgent
      }
      Label {
        Layout.fillWidth: true
        visible: root.question
        text: "What kana did you hear?"
        font.pixelSize: Style.font.title
        horizontalAlignment: Text.AlignHCenter
      }
      Action {
        id: playButton
        objectName: "dictationPlay"
        Layout.alignment: Qt.AlignHCenter
        visible: root.question || root.feedback
        text: root.core.playing ? "Stop recording" : root.core.mediaBusy ? "Opening recording…" : root.core.heard ? "Replay recording" : "Play recording"
        selected: root.question && !root.core.heard
        enabled: root.interactive && (!root.busy || root.core.playing)
        onClicked: root.core.play()
      }
      Label {
        objectName: "dictationAudioNotice"
        Layout.fillWidth: true
        visible: !!root.core.mediaNotice
        text: root.core.mediaNotice
        secondary: true
        horizontalAlignment: Text.AlignHCenter
      }
      Ui.TextField {
        id: answer
        objectName: "dictationAnswer"
        Layout.fillWidth: true
        visible: root.question
        readOnly: !root.interactive || root.core.actionBusy || root.restoredKey !== root.cardKey
        readonly property color surfaceColor: Theme.surface(parent, Color.background)
        readonly property color textColor: Theme.foreground(parent, Color.foreground)
        readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
        foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
        accent: Theme.readable(Color.accent, surfaceColor, foreground)
        color: Theme.readable(foreground, renderedSurface, foreground)
        placeholderTextColor: Theme.secondary(foreground, renderedSurface)
        selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
        font.family: "Noto Sans CJK JP"
        font.pixelSize: Style.space(26)
        horizontalAlignment: TextInput.AlignHCenter
        maximumLength: 256
        placeholderText: "Type romaji or kana"
        Accessible.name: "Kana you heard"
        Accessible.description: "Finish playing the recording before checking. Romaji converts locally to kana."
        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function (event) {
          if (event.isAutoRepeat && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter))
            event.accepted = true
        }
        onTextEdited: root.convertInput()
        onCursorPositionChanged: root.saveInput()
        onPreeditTextChanged: root.saveInput()
        onInputMethodComposingChanged: if (!inputMethodComposing)
          root.convertInput()
        onAccepted: root.submit()
      }
      Label {
        Layout.fillWidth: true
        visible: root.question && !!root.restoredPreedit
        text: "Uncommitted input from your last visit: " + root.restoredPreedit + ". Type it again to finish composing."
        secondary: true
      }
      Label {
        objectName: "dictationDraftError"
        Layout.fillWidth: true
        visible: !!root.core.draftError
        text: root.core.draftError
        textColor: Color.urgent
      }
      Label {
        objectName: "dictationInputNotice"
        Layout.fillWidth: true
        visible: root.question
        text: root.session && root.session.input_error ? root.session.input_error : root.core.heardBusy ? "Saving playback completion…" : root.core.heard ? "Check when your kana is ready." : "Play the whole recording to enable Check. You can type while listening."
        secondary: true
      }
      Action {
        objectName: "dictationCheck"
        visible: root.question
        text: "Check kana · Enter"
        selected: true
        enabled: root.interactive && root.core.canCheck && !answer.inputMethodComposing
        onClicked: root.submit()
      }
      Loader {
        objectName: "dictationFeedback"
        Layout.fillWidth: true
        active: root.interactive && root.feedback
        visible: active
        sourceComponent: ColumnLayout {
          spacing: Style.space(12)
          Label {
            Layout.fillWidth: true
            text: root.session.feedback.matched ? "Matched the recording" : "A sound to revisit"
            textColor: root.session.feedback.matched ? Color.accent : Color.urgent
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Label {
            Layout.fillWidth: true
            text: "Your kana"
            secondary: true
          }
          JapaneseText {
            Layout.fillWidth: true
            text: root.session.feedback.submitted
            font.pixelSize: Style.space(26)
            color: Theme.readable(Theme.foreground(parent, Color.foreground), Theme.surface(parent, Color.background), Color.foreground)
          }
          Label {
            Layout.fillWidth: true
            text: "Recorded kana"
            secondary: true
          }
          JapaneseText {
            Layout.fillWidth: true
            text: root.session.feedback.recorded
            font.pixelSize: Style.space(30)
            color: Theme.readable(Theme.foreground(parent, Color.foreground), Theme.surface(parent, Color.background), Color.foreground)
          }
          Label {
            Layout.fillWidth: true
            text: root.session.subject.characters + " · " + root.session.subject.meanings.join(" · ")
            font.bold: true
          }
          Label {
            Layout.fillWidth: true
            text: root.session.feedback.message
            secondary: true
          }
          Label {
            Layout.fillWidth: true
            text: root.session.intervals ? root.session.feedback.matched ? "Continue schedules this dictation word in " + root.session.intervals.matched_days + (root.session.intervals.matched_days === 1 ? " day." : " days.") : "Continue brings this dictation word back in " + root.session.intervals.again_minutes + " minutes." : ""
            secondary: true
          }
        }
      }
      Action {
        id: continueButton
        objectName: "dictationContinue"
        visible: root.feedback
        text: "Save result & continue"
        selected: true
        enabled: root.interactive && !root.busy
        onClicked: root.core.advance()
      }
      Label {
        objectName: "dictationSummary"
        Layout.fillWidth: true
        visible: root.complete
        text: root.complete ? root.session.summary.matched + " matched the recording · " + root.session.summary.again + " to revisit · " + root.session.summary.skipped + " skipped" : ""
        font.pixelSize: Style.font.title
      }
      Flow {
        Layout.fillWidth: true
        spacing: Style.space(8)
        Action {
          objectName: "dictationCurrentAccount"
          text: "Start current dictation"
          visible: !!root.session && !!root.session.unavailable && !root.saved
          enabled: root.interactive && !root.busy && (root.status.available || 0) > 0
          onClicked: root.core.start()
        }
        Action {
          objectName: "dictationSkip"
          visible: !!root.session && !root.complete
          text: root.feedback ? "Skip without a result" : "Skip word"
          enabled: root.interactive && !root.busy
          onClicked: root.core.skip()
        }
        Action {
          objectName: "dictationUndo"
          text: "Undo last result"
          visible: !!root.session && root.session.undo_available === true
          enabled: root.interactive && !root.busy
          onClicked: root.core.undo()
        }
        Action {
          objectName: "dictationAnother"
          text: "Another batch"
          visible: root.complete
          enabled: root.interactive && !root.busy
          onClicked: root.core.start()
        }
        Action {
          id: doneButton
          objectName: "dictationDone"
          text: root.complete ? "Back to work" : "Save & return to work"
          selected: root.complete
          enabled: root.interactive
          onClicked: root.controller.dismiss()
        }
      }
    }
  }
}
