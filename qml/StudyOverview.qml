import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  required property string mode
  readonly property bool lessons: mode === "lessons"
  readonly property var snapshot: controller.snapshot
  readonly property var saved: snapshot.saved_sessions ? snapshot.saved_sessions[mode] : null
  readonly property int available: lessons ? snapshot.lessons || 0 : snapshot.reviews || 0
  property int batch: 5
  spacing: Style.space(18)

  Label {
    Layout.fillWidth: true
    text: root.lessons ? "Learn something new." : "Recall what you have learned."
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.lessons ? "Lessons introduce new subjects. Read their meanings, readings, and examples, then take a short quiz." : "Reviews test subjects you have already learned. Finish each subject’s required meaning and reading before it counts as complete."
  }
  Card {
    Layout.fillWidth: true
    Layout.preferredHeight: savedContent.implicitHeight + Style.space(28)
    visible: !!root.saved
    ColumnLayout {
      id: savedContent
      anchors.fill: parent
      anchors.margins: Style.space(14)
      Label {
        Layout.fillWidth: true
        text: root.lessons ? "Your lessons are saved" : "Your reviews are saved"
        font.bold: true
      }
      Label {
        Layout.fillWidth: true
        text: root.saved ? root.saved.completed + " of " + root.saved.total + " subjects completed · " + (root.saved.phase === "lesson" ? "Learning" : root.lessons ? "Lesson quiz" : "Reviewing") : ""
      }
      Action {
        text: root.lessons ? "Resume lessons →" : "Resume reviews →"
        selected: true
        enabled: !root.controller.busy
        onClicked: root.controller.begin(root.mode)
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.available + (root.lessons ? " lessons available" : " reviews due")
    font.pixelSize: Style.space(30)
    textColor: Color.accent
  }
  Label {
    Layout.fillWidth: true
    visible: !root.saved && root.available === 0
    text: root.snapshot.vacation ? "Vacation mode is on. Your study will be here when you return." : root.lessons ? "No new lessons are ready. Reviews move your subjects toward their next unlock." : "You are caught up. Your next scheduled reviews appear on Today."
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: !root.saved && root.available > 0
    spacing: Style.space(10)
    Label { text: "Subjects in this batch" }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Repeater {
        model: [5, 10, 20]
        Action {
          required property int modelData
          text: String(modelData)
          selected: root.batch === modelData
          onClicked: root.batch = modelData
        }
      }
    }
    Action {
      text: root.lessons ? "Learn " + Math.min(root.batch, root.available) + " subjects →" : "Review " + Math.min(root.batch, root.available) + " subjects →"
      selected: true
      enabled: !root.controller.busy && !root.snapshot.vacation
      onClicked: root.controller.begin(root.mode, root.batch)
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.lessons ? "Learn → Lesson quiz → Scheduled reviews. You choose when to start the quiz." : "Another batch is always optional. Escape saves your exact place and returns to work."
    font.pixelSize: Style.font.bodySmall
  }
  Action {
    text: root.lessons ? "Open reviews" : "Open lessons"
    onClicked: root.controller.navigate(root.lessons ? "review-overview" : "lesson-overview")
  }
}
