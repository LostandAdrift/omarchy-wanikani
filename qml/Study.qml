import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui
import "../vendor/WanaKana.mjs" as Kana

ColumnLayout {
  id: root
  required property var controller
  readonly property var session: controller.session
  readonly property var subject: session ? session.subject : null
  readonly property bool promptReady: !subject || subjectGlyph.displayReady
  readonly property bool interactive: controller.opened && controller.service && controller.service.ready && !controller.service.locked
  readonly property bool feedback: session && session.phase === "feedback"
  readonly property color subjectColor: !subject ? Color.accent : subject.type === "radical" ? "#48a9de" : subject.type === "kanji" ? "#e56cb0" : "#a68be8"
  property bool converting: false
  property string questionKey: ""
  spacing: Style.space(16)

  function focusInput() {
    if (!interactive)
      return
    if (root.session && root.session.phase === "lesson")
      subjectCard.forceActiveFocus(Qt.OtherFocusReason)
    else if (root.session && root.session.phase === "complete")
      returnToWork.forceActiveFocus(Qt.TabFocusReason)
    else if (root.session)
      input.forceActiveFocus()
  }
  function restoreInput() {
    if (!session || !subject || !input) {
      if (questionKey && typeof controller.stopAudio === "function")
        controller.stopAudio()
      questionKey = ""
      return
    }
    var key = session.id + ":" + subject.id + ":" + session.part + ":" + session.phase
    if (key !== questionKey) {
      if (typeof controller.stopAudio === "function")
        controller.stopAudio()
      questionKey = key
      converting = true
      input.text = session.draft || ""
      converting = false
      Qt.callLater(focusInput)
      if (interactive && session.phase === "feedback" && session.feedback && session.feedback.correct && (session.part === "reading" || subject.type === "kana_vocabulary") && controller.snapshot.settings.autoplay_audio)
        controller.play(subject)
      else if (interactive && session.phase === "lesson" && controller.snapshot.settings.autoplay_lessons)
        controller.play(subject)
    }
  }
  function convertInput() {
    if (converting || !session || session.phase !== "question" || input.inputMethodComposing)
      return
    if (session.part === "reading") {
      var caret = input.cursorPosition
      var value = Kana.toHiragana(input.text, {
        IMEMode: true,
        convertLongVowelMark: false
      })
      var prefix = Kana.toHiragana(input.text.slice(0, caret), {
        IMEMode: true,
        convertLongVowelMark: false
      })
      if (value !== input.text) {
        converting = true
        input.text = value
        input.cursorPosition = prefix.length
        converting = false
      }
    }
    if (controller.service)
      controller.service.request("draft", {
        text: input.text
      })
  }
  function submit() {
    if (!interactive || controller.busy || !session || !subject || !promptReady || input.inputMethodComposing)
      return
    if (session.phase === "feedback")
      controller.studyAction("advance", {})
    else if (session.phase === "question")
      controller.studyAction("answer", {
        text: session.part === "reading" ? Kana.toHiragana(input.text, {
          IMEMode: false,
          convertLongVowelMark: false
        }) : input.text
      })
  }
  function nextLesson(back) {
    if (!interactive || controller.busy || !session || session.phase !== "lesson" || !subject || (back !== true && !promptReady))
      return
    controller.studyAction("lesson_next", {
      back: back === true
    })
  }
  onSessionChanged: Qt.callLater(restoreInput)
  onSubjectChanged: Qt.callLater(restoreInput)
  Component.onCompleted: Qt.callLater(restoreInput)

  Label {
    Layout.fillWidth: true
    visible: !root.session
    text: root.controller.busy ? "Preparing your next few minutes…" : "Choose reviews, lessons, or practice from Today."
    font.pixelSize: Style.font.title
  }
  Label {
    Layout.fillWidth: true
    visible: root.session && root.session.restricted === true
    text: "This subject is no longer accessible with the current account. Your saved answers are retained; refresh your account in Settings."
    textColor: Color.urgent
  }
  Label {
    Layout.fillWidth: true
    visible: !!(root.session && root.session.unavailable)
    text: root.session ? root.session.unavailable || "" : ""
    textColor: Color.urgent
  }
  RowLayout {
    Layout.fillWidth: true
    visible: root.session !== null
    Label {
      text: !root.session ? "" : (root.session.mode === "practice" ? "PRACTICE" : root.session.mode === "lessons" ? "LESSONS" : "REVIEWS") + " · " + (root.session.phase === "lesson" ? "LEARN" : root.session.phase === "complete" ? "COMPLETE" : (root.session.mode === "lessons" ? "QUIZ · " : "") + (root.session.part === "reading" ? "READING" : "MEANING"))
      font.pixelSize: Style.font.bodySmall
      font.letterSpacing: 2
      secondary: true
    }
    Item {
      Layout.fillWidth: true
    }
    Label {
      text: root.session ? root.session.completed + " / " + root.session.total + " subjects" : ""
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
  }
  Rectangle {
    Layout.fillWidth: true
    height: Style.space(5)
    color: Qt.alpha(Color.foreground, 0.1)
    radius: 2
    visible: root.session !== null
    Rectangle {
      height: parent.height
      width: parent.width * (root.session ? root.session.completed / Math.max(1, root.session.total) : 0)
      color: Color.accent
      radius: 2
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.session && root.session.phase === "complete"
    spacing: Style.space(18)
    Crab {
      Layout.alignment: Qt.AlignHCenter
      Layout.preferredWidth: Style.space(130)
      Layout.preferredHeight: Style.space(105)
      animate: visible && root.controller.opened && root.controller.service && root.controller.service.animations
      celebrating: visible
    }
    Label {
      Layout.fillWidth: true
      text: "A little more learned."
      font.pixelSize: Style.space(32)
      horizontalAlignment: Text.AlignHCenter
    }
    Label {
      Layout.fillWidth: true
      visible: !!(root.session && root.session.invalidated)
      text: root.session ? root.session.invalidated : ""
      textColor: Color.urgent
      horizontalAlignment: Text.AlignHCenter
    }
    Label {
      Layout.fillWidth: true
      text: root.session ? root.session.completed + (root.session.completed === 1 ? " subject completed · " : " subjects completed · ") + root.session.errors + (root.session.errors === 1 ? " mistake · " : " mistakes · ") + root.session.overrides + (root.session.overrides === 1 ? " typo correction" : " typo corrections") : ""
      horizontalAlignment: Text.AlignHCenter
      secondary: true
    }
    Label {
      Layout.fillWidth: true
      text: root.controller.snapshot.pending > 0 ? "Saved on this computer. " + root.controller.snapshot.pending + " results are waiting to sync." : root.controller.snapshot.demo ? "Demo progress stays on this computer." : "Your session is saved."
      horizontalAlignment: Text.AlignHCenter
      textColor: Color.accent
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        id: returnToWork
        text: "Back to work →"
        selected: true
        onClicked: root.controller.dismiss()
      }
      Action {
        text: "Another five"
        onClicked: root.controller.begin(root.session.mode, 5)
      }
      Action {
        text: "Today"
        onClicked: root.controller.navigate("dashboard")
      }
    }
    Loader {
      Layout.fillWidth: true
      active: root.session && root.session.phase === "complete"
      sourceComponent: Component {
        SessionRecap {
          controller: root.controller
          session: root.session
        }
      }
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.subject !== null && root.session && root.session.phase !== "complete"
    spacing: Style.space(14)
    Card {
      id: subjectCard
      Layout.fillWidth: true
      Layout.preferredHeight: Math.max(Style.space(220), subjectPrompt.implicitHeight + Style.space(32))
      activeFocusOnTab: root.session && root.session.phase === "lesson"
      border.color: activeFocus ? Color.accent : Qt.alpha(Color.foreground, 0.14)
      Accessible.role: Accessible.Grouping
      Accessible.name: "Study subject"
      Keys.onReturnPressed: function (event) {
        if (!event.isAutoRepeat)
          root.nextLesson(false)
      }
      Keys.onEnterPressed: function (event) {
        if (!event.isAutoRepeat)
          root.nextLesson(false)
      }
      Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: Style.space(3)
        color: root.subjectColor
      }
      Column {
        id: subjectPrompt
        anchors.centerIn: parent
        width: parent.width - Style.space(32)
        spacing: Style.space(9)
        Label {
          width: parent.width
          text: root.subject ? root.subject.type.replace("_", " ").toUpperCase() + " · LEVEL " + root.subject.level : ""
          secondary: true
          font.pixelSize: Style.font.bodySmall
          horizontalAlignment: Text.AlignHCenter
          font.letterSpacing: 2
        }
        SubjectGlyph {
          id: subjectGlyph
          width: parent.width
          subject: root.subject
          pixelSize: Style.space(94)
          revealLabel: !!root.session && (root.session.phase === "lesson" || root.session.phase === "feedback")
        }
        Label {
          width: parent.width
          text: root.session && root.session.phase === "lesson" ? "Discover · " + (root.session.lesson_index + 1) + " of " + root.session.total : root.session && root.session.part === "reading" ? "What is the reading?" : "What is the meaning?"
          horizontalAlignment: Text.AlignHCenter
          textColor: Color.accent
          font.pixelSize: Style.font.title
        }
      }
    }
    Label {
      Layout.fillWidth: true
      visible: !!root.subject && !root.promptReady
      text: subjectGlyph.displayLoading ? "Loading this subject image…" : "This subject image could not be shown. Refresh your account to try again."
      textColor: subjectGlyph.displayLoading ? Qt.alpha(Color.foreground, 0.76) : Color.urgent
    }
    Ui.TextField {
      id: input
      Layout.fillWidth: true
      visible: root.session && root.session.phase !== "lesson"
      readOnly: root.feedback || root.controller.busy
      horizontalAlignment: TextInput.AlignHCenter
      font.pixelSize: Style.space(24)
      font.family: root.session && root.session.part === "reading" ? "Noto Sans CJK JP" : Style.font.family
      placeholderText: root.session && root.session.part === "reading" ? "Type romaji or kana" : "Type the English meaning"
      Accessible.name: root.session && root.session.part === "reading" ? "Reading answer" : "Meaning answer"
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function (event) {
        if (event.isAutoRepeat && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter))
          event.accepted = true
      }
      onTextEdited: root.convertInput()
      onInputMethodComposingChanged: if (!inputMethodComposing)
        root.convertInput()
      onAccepted: root.submit()
    }
    Label {
      Layout.fillWidth: true
      visible: root.session && root.session.feedback !== null
      text: root.session && root.session.feedback ? root.session.feedback.message : ""
      textColor: root.session && root.session.feedback && root.session.feedback.correct ? Color.accent : Color.urgent
      horizontalAlignment: Text.AlignHCenter
    }
    Label {
      Layout.fillWidth: true
      visible: root.feedback && root.session && root.session.feedback && root.session.feedback && !root.session.feedback.correct
      text: root.session && root.session.feedback ? root.session.feedback.accepted.join(" · ") : ""
      horizontalAlignment: Text.AlignHCenter
      font.pixelSize: Style.font.title
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      visible: root.session && root.session.phase !== "lesson"
      Action {
        text: root.feedback ? "Continue · Enter" : "Check answer · Enter"
        selected: true
        enabled: root.interactive && !root.controller.busy && root.promptReady
        onClicked: root.submit()
      }
      Action {
        text: "I made a typo"
        visible: root.feedback && root.session && root.session.feedback && root.session.feedback && !root.session.feedback.correct
        enabled: !root.controller.busy
        onClicked: root.controller.studyAction("correct", {})
      }
      Action {
        text: "Save & return to work"
        onClicked: root.controller.dismiss()
      }
      Action {
        text: root.session && root.session.finishing ? "Finishing this batch" : "Finish this batch"
        visible: root.session && root.session.total > 5
        enabled: root.session && !root.session.finishing && !root.controller.busy
        onClicked: root.controller.studyAction("finish", {})
      }
    }
    SubjectDetails {
      Layout.fillWidth: true
      subject: root.subject
      controller: root.controller
      visible: root.session && (root.session.phase === "lesson" || (root.feedback && root.session && root.session.feedback && !root.session.feedback.correct))
      showMeaning: root.session && (root.session.phase === "lesson" || root.session.part === "meaning")
      showReading: root.session && (root.session.phase === "lesson" || root.session.part === "reading")
    }
    Pronunciation {
      Layout.fillWidth: true
      controller: root.controller
      subject: root.subject
      visible: root.feedback && root.session && root.session.feedback && root.session.feedback.correct && root.subject && root.subject.audio_available && (root.session.part === "reading" || root.subject.type === "kana_vocabulary")
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      visible: root.session && root.session.phase === "lesson"
      Action {
        text: "Previous"
        enabled: root.interactive && root.session && root.session.lesson_index > 0 && !root.controller.busy
        onClicked: root.nextLesson(true)
      }
      Action {
        id: lessonNext
        text: root.session && root.session.lesson_index + 1 >= root.session.total ? "Start the quiz →" : "Next subject →"
        selected: true
        enabled: root.interactive && !root.controller.busy && root.promptReady
        onClicked: root.nextLesson(false)
      }
      Action {
        text: "Save & return to work"
        onClicked: root.controller.dismiss()
      }
    }
  }
}
