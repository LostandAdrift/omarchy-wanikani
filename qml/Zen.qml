import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  property int index: 0
  property bool ambientLease: false
  property bool quietRecall: false
  property bool answerRevealed: false
  property int recallSubjectId: 0
  readonly property bool wantsAmbient: controller.opened === true
  readonly property bool interactive: wantsAmbient && controller.service && controller.service.ready && !controller.service.locked
  readonly property string contentAccess: controller.contentAccess || ""
  readonly property var items: controller.service ? controller.service.ambientItems : []
  readonly property var subject: {
    if (!items.length)
      return null
    // A refresh may insert earlier subjects. Keep the unanswered card while
    // its ID is still in the current safe catalogue, never a cached old body.
    if (quietRecall && recallSubjectId) {
      for (var i = 0; i < items.length; i++) {
        if (items[i].id === recallSubjectId)
          return items[i]
      }
    }
    return items[index % items.length]
  }
  readonly property string subjectKey: subject ? String(subject.id) : ""
  readonly property bool answersVisible: !quietRecall || answerRevealed
  spacing: Style.space(22)
  function nextWord() {
    if (!interactive || items.length < 2)
      return
    var current = index % items.length
    for (var i = 0; subject && i < items.length; i++) {
      if (items[i].id === subject.id) {
        current = i
        break
      }
    }
    answerRevealed = false
    index = (current + 1) % items.length
    recallSubjectId = quietRecall ? items[index].id : 0
  }
  function recallAction() {
    if (!interactive || !quietRecall || !subject)
      return
    if (answerRevealed)
      nextWord()
    else
      answerRevealed = true
  }
  onQuietRecallChanged: {
    answerRevealed = false
    recallSubjectId = quietRecall && subject ? subject.id : 0
  }
  onSubjectKeyChanged: answerRevealed = false
  onItemsChanged: {
    if (quietRecall && items.length && !items.some(function (item) {
      return item.id === root.recallSubjectId
    }))
      recallSubjectId = items[index % items.length].id
  }
  onContentAccessChanged: {
    answerRevealed = false
    recallSubjectId = 0
  }
  function updateAmbientLease() {
    if (!controller.service || ambientLease === wantsAmbient)
      return
    ambientLease = wantsAmbient
    if (ambientLease)
      controller.service.acquireAmbient()
    else
      controller.service.releaseAmbient()
  }
  onWantsAmbientChanged: {
    answerRevealed = false
    updateAmbientLease()
  }
  Component.onCompleted: updateAmbientLease()
  Component.onDestruction: {
    if (ambientLease && controller.service)
      controller.service.releaseAmbient()
  }
  Label {
    Layout.fillWidth: true
    text: root.quietRecall ? "QUIET RECALL · UNGRADED" : "A MOMENT OF JAPANESE"
    horizontalAlignment: Text.AlignHCenter
    color: Qt.alpha(Color.foreground, 0.76)
    font.letterSpacing: 3
    font.pixelSize: Style.font.bodySmall
  }
  SubjectGlyph {
    objectName: "zen-subject-glyph"
    Layout.fillWidth: true
    subject: root.subject || {
      characters: "ひと休み",
      images: []
    }
    pixelSize: Style.space(116)
    revealLabel: root.answersVisible
  }
  Label {
    objectName: "zen-meaning"
    Layout.fillWidth: true
    visible: !root.subject || root.answersVisible
    text: root.subject ? root.subject.meanings.join(" · ") : "A little rest"
    font.pixelSize: Style.font.title
    color: Color.accent
    horizontalAlignment: Text.AlignHCenter
  }
  Label {
    objectName: "zen-reading"
    Layout.fillWidth: true
    visible: !root.subject || root.answersVisible
    text: root.subject ? root.subject.readings.map(function (r) {
      return r.reading
    }).join(" · ") : "Learned subjects will appear here when their next review is more than a day away."
    font.family: root.subject ? "Noto Sans CJK JP" : Style.font.family
    color: Qt.alpha(Color.foreground, 0.76)
    horizontalAlignment: Text.AlignHCenter
  }
  Label {
    objectName: "zen-recall-prompt"
    Layout.fillWidth: true
    visible: root.quietRecall && root.subject !== null
    text: root.answerRevealed ? "Take a moment, then try another word." : root.subject && root.subject.readings.length ? "Recall the meaning and reading. Take your time." : "Recall the meaning. Take your time."
    color: Qt.alpha(Color.foreground, 0.76)
    horizontalAlignment: Text.AlignHCenter
  }
  Crab {
    Layout.alignment: Qt.AlignHCenter
    Layout.preferredWidth: Style.space(140)
    Layout.preferredHeight: Style.space(112)
    animate: root.controller.opened && root.controller.service && root.controller.service.animations
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      objectName: "zen-next-gallery"
      text: "Another word"
      visible: !root.quietRecall
      enabled: root.interactive && root.items.length > 1
      onClicked: root.nextWord()
    }
    Action {
      objectName: "zen-reveal"
      text: root.answerRevealed ? "Next word" : "Reveal"
      visible: root.quietRecall && root.subject !== null
      enabled: root.interactive && (!root.answerRevealed || root.items.length > 1)
      selected: true
      onClicked: root.recallAction()
    }
    Action {
      objectName: "zen-recall-toggle"
      text: root.quietRecall ? "Return to gallery" : "Quiet recall"
      enabled: root.interactive && (root.subject !== null || root.quietRecall)
      selected: root.quietRecall
      onClicked: root.quietRecall = !root.quietRecall
    }
    Action {
      text: "Back to work"
      onClicked: root.controller.dismiss()
    }
  }
  Timer {
    objectName: "zen-gallery-timer"
    interval: 30000
    repeat: true
    running: root.interactive && !root.quietRecall && root.items.length > 1
    onTriggered: root.nextWord()
  }
}
