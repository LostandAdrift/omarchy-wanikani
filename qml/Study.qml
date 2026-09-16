import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme
import qs.Ui as Ui
import "../vendor/WanaKana.mjs" as Kana

ColumnLayout {
  id: root
  required property var controller
  readonly property var session: controller.session
  readonly property var subject: session ? session.subject : null
  readonly property var lessonFlow: session && session.phase === "lesson" ? session.lesson_flow || null : null
  readonly property string lessonSection: lessonFlow ? lessonFlow.step : "all"
  readonly property bool promptReady: !subject || subjectGlyph.displayReady
  readonly property bool interactive: controller.opened && controller.service && controller.service.ready && !controller.service.locked
  readonly property bool feedback: session && session.phase === "feedback"
  readonly property color subjectColor: !subject ? Color.accent : subject.type === "radical" ? "#48a9de" : subject.type === "kanji" ? "#e56cb0" : "#a68be8"
  property bool dockActions: false
  readonly property bool readingQuestion: !!session && session.part === "reading"
  readonly property bool audioRevealed: !!session && !!subject && (session.phase === "lesson" || (feedback && session.feedback && !session.feedback.retry && (readingQuestion || subject.type === "kana_vocabulary")))
  readonly property bool canPlayPronunciation: interactive && !controller.busy && !input.inputMethodComposing && audioRevealed && subject.audio_available === true && controller.audioState !== "loading"
  function playPronunciation() {
    if (canPlayPronunciation)
      controller.play(subject)
  }
  function showDetails() {
    if (interactive && feedback && !input.inputMethodComposing)
      detailsHeading.forceActiveFocus(Qt.ShortcutFocusReason)
  }
  Shortcut {
    sequence: "Alt+P"
    enabled: root.visible && root.canPlayPronunciation
    autoRepeat: false
    onActivated: root.playPronunciation()
  }
  Shortcut {
    sequence: "Alt+D"
    enabled: root.visible && root.interactive && root.feedback && !input.inputMethodComposing
    autoRepeat: false
    onActivated: root.showDetails()
  }
  property bool converting: false
  property string questionKey: ""
  property var lessonAutoplayIntent: null
  spacing: Style.space(16)

  property Component reviewActions: Component {
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      visible: root.session && root.session.phase !== "lesson" && root.session.phase !== "complete"
      Action {
        text: root.feedback ? "Continue · Enter" : "Check answer · Enter"
        selected: true
        enabled: root.interactive && !root.controller.busy && root.promptReady
        onClicked: root.submit()
      }
      Action {
        objectName: "study-play-pronunciation"
        text: root.controller.audioState === "loading" ? "Loading audio…" : "Play pronunciation · Alt+P"
        visible: !!root.subject && (root.subject.type === "vocabulary" || root.subject.type === "kana_vocabulary")
        enabled: root.canPlayPronunciation
        accessibleHint: root.audioRevealed ? "Hear the recorded pronunciation without advancing" : "Available after checking the reading"
        onClicked: root.playPronunciation()
      }
      Action {
        text: "Details · Alt+D"
        visible: root.feedback
        onClicked: root.showDetails()
      }
      Action {
        text: "I made a typo"
        visible: root.feedback && root.session && root.session.feedback && root.session.feedback && !root.session.feedback.correct
        enabled: !root.controller.busy
        onClicked: root.controller.studyAction("correct", {})
      }
      Action {
        text: root.session && root.session.finishing ? "Finishing this batch" : "Finish this batch"
        visible: root.session && root.session.total > 5
        enabled: root.session && !root.session.finishing && !root.controller.busy
        onClicked: root.controller.studyAction("finish", {})
      }
    }
  }

  function focusInput() {
    if (!interactive)
      return
    if (root.session && root.session.phase === "lesson") {
      if (root.lessonFlow && root.lessonFlow.can_quiz)
        lessonQuiz.forceActiveFocus(Qt.TabFocusReason)
      else
        subjectCard.forceActiveFocus(Qt.OtherFocusReason)
    } else if (root.session && root.session.phase === "complete")
      returnToWork.forceActiveFocus(Qt.TabFocusReason)
    else if (root.session)
      input.forceActiveFocus()
  }
  function restoreInput() {
    if (!session || !subject || !input) {
      lessonAutoplayIntent = null
      if (questionKey && typeof controller.stopAudio === "function")
        controller.stopAudio()
      questionKey = ""
      return
    }
    var key = session.id + ":" + subject.id + ":" + session.part + ":" + session.phase + ":" + lessonSection
    if (key !== questionKey) {
      var lessonAudio = lessonAutoplayIntent
      lessonAutoplayIntent = null
      if (typeof controller.stopAudio === "function")
        controller.stopAudio()
      questionKey = key
      converting = true
      input.text = session.draft || ""
      converting = false
      if (typeof controller.resetStudyScroll === "function")
        controller.resetStudyScroll()
      Qt.callLater(focusInput)
      if (interactive && subject.audio_available === true && session.phase === "feedback" && session.feedback && session.feedback.correct && (session.part === "reading" || subject.type === "kana_vocabulary") && controller.snapshot.settings.autoplay_audio)
        controller.play(subject)
      else if (interactive && subject.audio_available === true && session.phase === "lesson" && controller.snapshot.settings.autoplay_lessons && (!lessonFlow || (lessonAudio && lessonSection === "reading" && session.id === lessonAudio.sessionId && session.revision > lessonAudio.revision && subject.id === lessonAudio.subjectId && (controller.contentAccess || "") === lessonAudio.access)))
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
    if (!interactive || controller.busy || !session || session.phase !== "lesson")
      return
    if (lessonFlow) {
      if (back === true ? !lessonFlow.can_back : !lessonFlow.can_next || !subject || !promptReady)
        return
      navigateLesson(back === true ? "back" : "next")
      return
    }
    if (!subject || (back !== true && !promptReady))
      return
    controller.studyAction("lesson_next", {
      back: back === true
    })
  }
  function navigateLesson(action) {
    if (!interactive || controller.busy || !lessonFlow || !session)
      return
    if (["next", "back", "quiz"].indexOf(action) < 0)
      return
    if (action === "back" ? !lessonFlow.can_back : !subject || !promptReady || !(action === "quiz" ? lessonFlow.can_quiz : lessonFlow.can_next))
      return
    var target = lessonFlow.position - 1 + (action === "back" ? -1 : 1)
    var next = action !== "quiz" && lessonFlow.steps[target]
    lessonAutoplayIntent = next && next.id === "reading" && subject ? {
      sessionId: session.id,
      revision: session.revision,
      subjectId: subject.id,
      access: controller.contentAccess || ""
    } : null
    controller.studyAction("lesson_navigate", {
      action: action,
      session_id: session.id,
      revision: session.revision
    })
  }
  onInteractiveChanged: {
    if (!interactive)
      lessonAutoplayIntent = null
    else
      Qt.callLater(focusInput)
  }
  Connections {
    target: root.controller
    function onErrorChanged() {
      if (root.controller.error)
        root.lessonAutoplayIntent = null
    }
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
    text: root.session && root.session.unavailable ? root.session.unavailable : "This subject is no longer accessible with the current account. Your saved answers are retained; refresh your account in Settings."
    textColor: Color.urgent
  }
  Action {
    objectName: "lesson-unavailable-back"
    visible: !!root.lessonFlow && !root.subject && root.lessonFlow.can_back
    text: "Back to the previous lesson"
    enabled: root.interactive && !root.controller.busy
    onClicked: root.nextLesson(true)
  }
  Label {
    Layout.fillWidth: true
    visible: !!(root.session && root.session.unavailable && !root.session.restricted)
    text: root.session ? root.session.unavailable || "" : ""
    textColor: Color.urgent
  }
  RowLayout {
    Layout.fillWidth: true
    visible: root.session !== null
    Label {
      Layout.fillWidth: true
      text: !root.session ? "" : (root.session.mode === "practice" ? "PRACTICE" : root.session.mode === "lessons" ? "LESSONS" : root.session.all_reviews ? "ALL DUE REVIEWS" : "REVIEWS") + " · " + (root.session.phase === "lesson" ? "LEARN" : root.session.phase === "complete" ? "COMPLETE" : (root.session.mode === "lessons" ? "QUIZ · " : "") + (root.session.part === "reading" ? "READING" : "MEANING"))
      font.pixelSize: Style.font.bodySmall
      font.letterSpacing: 2
      secondary: true
    }
    Label {
      objectName: "study-session-total"
      Layout.maximumWidth: parent.width * 0.52
      text: root.session ? root.session.phase === "lesson" ? "Subject " + (root.session.lesson_index + 1) + " of " + root.session.total : root.session.completed + " / " + root.session.total + " subjects" : ""
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
  }
  Label {
    objectName: "study-reviews-remaining"
    Layout.fillWidth: true
    visible: !!root.session && root.session.all_reviews === true && root.session.phase !== "complete"
    text: root.session ? Math.max(0, root.session.total - root.session.completed) + (root.session.finishing ? " left before this batch ends" : " left in this session") : ""
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Rectangle {
    objectName: "study-completion-meter"
    Layout.fillWidth: true
    implicitHeight: Style.space(5)
    color: Theme.tint(Color.foreground, Theme.surface(parent, Color.background), 0.1)
    radius: 2
    visible: root.session !== null && !root.lessonFlow
    Accessible.role: Accessible.ProgressBar
    Accessible.name: root.session ? root.session.completed + " of " + root.session.total + " subjects completed" : "Session progress"
    Rectangle {
      height: parent.height
      width: parent.width * (root.session ? root.session.completed / Math.max(1, root.session.total) : 0)
      color: Theme.indicator(Color.accent, parent.color, Color.foreground)
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
    Flow {
      objectName: "lesson-path"
      Layout.fillWidth: true
      visible: !!root.lessonFlow
      spacing: Style.space(8)
      Repeater {
        model: root.lessonFlow ? root.lessonFlow.steps : []
        Rectangle {
          required property var modelData
          required property int index
          readonly property bool current: root.lessonSection === modelData.id
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          readonly property color kaniSurface: color
          readonly property color kaniText: textColor
          width: lessonStepLabel.implicitWidth + Style.space(22)
          height: lessonStepLabel.implicitHeight + Style.space(14)
          radius: Style.cornerRadius
          color: Theme.tint(textColor, surfaceColor, current ? 0.12 : 0.035)
          border.color: current ? Theme.indicator(Color.accent, color, textColor) : "transparent"
          Accessible.role: Accessible.StaticText
          Accessible.name: (index + 1) + ". " + modelData.label + (current ? ", current step" : "")
          Label {
            id: lessonStepLabel
            anchors.centerIn: parent
            text: (index + 1) + " · " + modelData.label
            font.bold: parent.current
            font.pixelSize: Style.font.bodySmall
            Accessible.ignored: true
          }
        }
      }
    }
    Label {
      Layout.fillWidth: true
      visible: !!root.lessonFlow && root.lessonFlow.adjusted
      text: "This lesson's available content changed. Your place has moved to the nearest available step."
      secondary: true
    }
    Card {
      id: subjectCard
      Layout.fillWidth: true
      Layout.preferredHeight: Math.max(Style.space(root.feedback ? 130 : 200), subjectPrompt.implicitHeight + Style.space(24))
      activeFocusOnTab: root.session && root.session.phase === "lesson"
      border.color: activeFocus ? Theme.indicator(Color.accent, kaniSurface, kaniText) : Theme.tint(kaniText, kaniSurface, 0.14)
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
          pixelSize: Style.space(root.feedback ? 60 : 88)
          revealLabel: !!root.session && (root.session.phase === "lesson" || root.session.phase === "feedback")
        }
        Label {
          width: parent.width
          objectName: "study-question-cue"
          text: root.session && root.session.phase === "lesson" ? "Discover · " + (root.session.lesson_index + 1) + " of " + root.session.total : root.readingQuestion ? "READING · Type the pronunciation" : "MEANING · Answer in English"
          horizontalAlignment: Text.AlignHCenter
          textColor: Color.accent
          font.pixelSize: Style.space(22)
          font.bold: true
        }
        Label {
          width: parent.width
          visible: !!root.session && root.session.phase === "question"
          text: root.readingQuestion ? "Japanese kana · romaji converts as you type" : "English words · no kana needed"
          horizontalAlignment: Text.AlignHCenter
          secondary: true
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
      readonly property color surfaceColor: Theme.surface(parent, Color.background)
      readonly property color textColor: Theme.foreground(parent, Color.foreground)
      readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
      foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
      accent: Theme.readable(Color.accent, surfaceColor, foreground)
      color: Theme.readable(foreground, renderedSurface, foreground)
      placeholderTextColor: Theme.secondary(foreground, renderedSurface)
      selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
      objectName: "study-answer"
      Layout.fillWidth: true
      visible: root.session && root.session.phase !== "lesson"
      readOnly: root.feedback || root.controller.busy
      horizontalAlignment: TextInput.AlignHCenter
      font.pixelSize: Style.space(32)
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
      objectName: "study-accepted-answer"
      text: root.session && root.session.feedback ? root.session.feedback.accepted.join(" · ") : ""
      horizontalAlignment: Text.AlignHCenter
      font.family: root.session && root.session.part === "reading" ? "Noto Sans CJK JP" : Style.font.family
      font.pixelSize: Style.space(root.session && root.session.part === "reading" ? 36 : 24)
    }
    Loader {
      Layout.fillWidth: true
      active: !root.dockActions
      sourceComponent: root.reviewActions
    }
    Label {
      id: detailsHeading
      objectName: "study-details-heading"
      Layout.fillWidth: true
      visible: root.feedback
      text: root.readingQuestion ? "Reading explanation" : "Meaning explanation"
      font.bold: true
      activeFocusOnTab: true
      Keys.onReturnPressed: function(event) { if (!event.isAutoRepeat) root.submit() }
      Keys.onEnterPressed: function(event) { if (!event.isAutoRepeat) root.submit() }
    }
    Label {
      Layout.fillWidth: true
      visible: root.audioRevealed && !!root.controller.audioNotice
      text: root.controller.audioNotice || ""
      secondary: true
    }
    SubjectDetails {
      Layout.fillWidth: true
      subject: root.subject
      controller: root.controller
      section: root.lessonSection
      showPronunciation: root.session && root.session.phase === "lesson"
      visible: root.session && (root.session.phase === "lesson" || root.feedback)
      showMeaning: root.session && (root.session.phase === "lesson" || root.session.part === "meaning")
      showReading: root.session && (root.session.phase === "lesson" || root.session.part === "reading")
    }
    KanjiExamples {
      Layout.fillWidth: true
      controller: root.controller
      subject: root.subject
      visible: root.feedback && root.session && root.session.part === "reading" && root.session.feedback && root.session.feedback.correct && !root.session.feedback.retry && root.subject && root.subject.type === "kanji"
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      visible: root.session && root.session.phase === "lesson"
      Action {
        text: "Previous"
        objectName: "lesson-previous"
        enabled: root.interactive && root.session && (root.lessonFlow ? root.lessonFlow.can_back : root.session.lesson_index > 0) && !root.controller.busy
        onClicked: root.nextLesson(true)
      }
      Action {
        id: lessonNext
        objectName: "lesson-next"
        visible: !root.lessonFlow || root.lessonFlow.can_next
        text: root.lessonFlow ? root.lessonFlow.next_label + " →" : root.session && root.session.lesson_index + 1 >= root.session.total ? "Start the quiz →" : "Next subject →"
        selected: true
        enabled: root.interactive && !root.controller.busy && root.promptReady
        onClicked: root.nextLesson(false)
      }
      Action {
        id: lessonQuiz
        objectName: "lesson-start-quiz"
        visible: !!root.lessonFlow && root.lessonFlow.can_quiz
        text: "Start lesson quiz →"
        selected: true
        enabled: root.interactive && !root.controller.busy && root.promptReady
        accessibleHint: "Begin the quiz for this batch of lessons"
        onClicked: root.navigateLesson("quiz")
      }
    }
    Label {
      Layout.fillWidth: true
      visible: !!root.lessonFlow && root.lessonFlow.can_quiz
      text: "Ready to recall this batch? The quiz checks meanings and applicable readings. Your lessons are completed only after their quiz answers are checked and acknowledged."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
  }
}
