import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  readonly property var s: controller.snapshot
  spacing: Style.space(18)
  Label { Layout.fillWidth: true; text: s.username ? (s.reviews > 0 ? "A little progress goes a long way." : "A moment to breathe.") : "Make Japanese part of your day."; font.pixelSize: Style.font.title; font.bold: true }
  Label { Layout.fillWidth: true; visible: !s.username; text: "Native lessons and reviews, ready whenever you have a few minutes. Connect your WaniKani account or explore with sample material."; color: Color.muted }
  Flow {
    Layout.fillWidth: true; spacing: Style.space(8); visible: !s.username
    Action { text: "Connect WaniKani"; selected: true; onClicked: root.controller.navigate("settings") }
    Action { text: "Try the demo"; onClicked: root.controller.call("use_demo", {enabled:true}) }
  }
  RowLayout {
    Layout.fillWidth: true; spacing: Style.space(12); visible: !!s.username
    Repeater {
      model: [{label:"REVIEWS READY",value:root.s.reviews || 0},{label:"LESSONS READY",value:root.s.lessons || 0},{label:"LEVEL",value:root.s.level || 0}]
      Card {
        required property var modelData
        Layout.fillWidth: true; Layout.preferredHeight: Style.space(116)
        Column {
          anchors.fill: parent; anchors.margins: Style.space(16); spacing: Style.space(8)
          Label { text: modelData.label; color: Color.muted; font.pixelSize: Style.font.bodySmall; font.letterSpacing: 1 }
          Label { text: String(modelData.value); font.pixelSize: Style.space(40); color: Color.accent }
        }
      }
    }
  }
  Label { Layout.fillWidth: true; visible: s.vacation === true; text: "Vacation mode is on. Take your time; ungraded practice is available."; color: Color.accent }
  Flow {
    Layout.fillWidth: true; spacing: Style.space(8); visible: !!s.username
    Action { text: root.s.session && root.s.session.phase !== "complete" ? "Resume your session →" : "Five reviews →"; selected: true; enabled: !root.controller.busy; onClicked: root.controller.begin("reviews",5) }
    Action { text: "Learn something new"; enabled: !root.controller.busy && root.s.lessons > 0 && !root.s.vacation; onClicked: root.controller.begin("lessons",5) }
    Action { text: "Refresh"; enabled: !root.s.syncing; onClicked: root.controller.call("sync",{}) }
    Action { text: "Snooze reminders · 1h"; onClicked: root.controller.call("snooze",{seconds:3600}) }
  }
  Label { Layout.fillWidth: true; visible: !!s.message; text: s.message || ""; color: Color.urgent }
  ColumnLayout {
    Layout.fillWidth: true; visible: !!s.username; spacing: Style.space(9)
    Label { text: "Coming up"; font.bold: true }
    Label { text: s.next_reviews_at ? "Next reviews at " + Qt.formatDateTime(new Date(s.next_reviews_at), "ddd HH:mm") : "No upcoming reviews in the cached schedule"; color: Color.muted; font.pixelSize: Style.font.bodySmall }
    Row {
      Layout.fillWidth: true; height: Style.space(85); spacing: Style.space(3)
      Repeater {
        model: root.s.forecast || []
        Item {
          required property int modelData
          required property int index
          width: (parent.width - 23 * Style.space(3)) / 24; height: parent.height
          Rectangle {
            anchors.bottom: parent.bottom; width: parent.width
            height: Math.max(Style.space(3), (parent.height - Style.space(22)) * modelData / Math.max(1, Math.max.apply(null, root.s.forecast || [1])))
            radius: Math.min(Style.cornerRadius, 3); color: modelData ? Color.accent : Qt.alpha(Color.foreground, 0.1)
          }
          Label { anchors.bottom: parent.bottom; anchors.bottomMargin: Math.max(Style.space(7), (parent.height - Style.space(22)) * modelData / Math.max(1,Math.max.apply(null,root.s.forecast || [1])) + 4); anchors.horizontalCenter: parent.horizontalCenter; text: modelData > 0 ? String(modelData) : ""; font.pixelSize: Style.font.bodySmall }
          Accessible.name: "In " + index + " hours: " + modelData + " reviews"
        }
      }
    }
    RowLayout { Layout.fillWidth:true; Label {text:"Now";color:Color.muted;font.pixelSize:Style.font.bodySmall}
Item {Layout.fillWidth:true}
Label {text:"Next 24 hours · cached schedule";color:Color.muted;font.pixelSize:Style.font.bodySmall} }
    Label { text: "Level " + (s.level || 0) + " kanji · " + (s.level_passed || 0) + " / " + (s.level_total || 0) + " at Guru or above"; font.pixelSize: Style.font.bodySmall }
    Rectangle { Layout.fillWidth:true; height:Style.space(5); radius:2; color:Qt.alpha(Color.foreground,0.1); Rectangle {height:parent.height; width:parent.width * Math.min(1,(root.s.level_passed || 0) / Math.max(1,root.s.level_total || 0)); color:Color.accent;radius:2} }
  }
  ColumnLayout {
    Layout.fillWidth: true; visible: (s.difficult || []).length > 0
    Label { text: "Worth another look"; font.bold: true }
    Label { Layout.fillWidth:true; text:"Practice recent mistakes and subjects with lower recorded accuracy. Practice never changes your WaniKani schedule."; color:Color.muted; font.pixelSize:Style.font.bodySmall }
    Flow {
      Layout.fillWidth: true; spacing: Style.space(6)
      Repeater { model: root.s.difficult || []; Action { required property var modelData; text:(modelData.characters || modelData.slug) + " · " + modelData.meanings[0]; onClicked:root.controller.showSubject(modelData.id) } }
    }
    Action { text: "Practice these items"; onClicked: root.controller.begin("practice",5,(root.s.difficult || []).map(function(x){return x.id})) }
  }
  ColumnLayout {
    Layout.fillWidth: true; visible: !!s.username
    Label { text: "Your activity here"; font.bold: true }
    Label { Layout.fillWidth:true; text:(s.activity || []).length ? "Completed subjects and practice recorded by this plugin. Other clients are not included." : "Your first session starts the story. Activity from other clients is not available as individual review history."; font.pixelSize:Style.font.bodySmall;color:Color.muted }
    Flow { Layout.fillWidth:true; spacing:Style.space(6); Repeater {model:root.s.activity || []; Card {required property var modelData;width:Style.space(90);height:Style.space(58); Column {anchors.centerIn:parent; Label{text:modelData.day.slice(5);font.pixelSize:Style.font.bodySmall;color:Color.muted}
Label{text:String(modelData.count);font.bold:true;color:Color.accent}}} } }
  }
  Action { visible: (s.attention || 0) > 0; text: "Review " + s.attention + " sync issue(s)"; onClicked: root.controller.navigate("settings") }
}
