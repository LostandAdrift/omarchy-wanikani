import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme

Card {
  id: root
  required property var progress
  property bool showExplore: true
  signal explore()
  readonly property var value: progress || ({})
  readonly property bool hasLevel: Number.isInteger(value.level) && value.level >= 1 && value.level <= 60
  readonly property bool ready: value.complete === true && Number.isInteger(value.passed) && value.passed >= 0 && Number.isInteger(value.required) && value.required > 0 && typeof value.fraction === "number" && isFinite(value.fraction)
  readonly property string headline: hasLevel ? "Level " + value.level + (value.final_level ? " · Final level" : " · Your progress") : "Your current level"
  readonly property string explanation: typeof value.message === "string" && value.message ? value.message : "Refresh your account to see confirmed level progress."
  implicitHeight: content.implicitHeight + Style.space(32)
  Layout.fillWidth: true

  ColumnLayout {
    id: content
    anchors.fill: parent
    anchors.margins: Style.space(16)
    spacing: Style.space(10)
    Label {
      objectName: "levelProgressHeading"
      Layout.fillWidth: true
      text: root.headline
      surfaceColor: root.color
      font.bold: true
    }
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(12)
      Label {
        objectName: "levelProgressCount"
        text: root.ready ? root.value.passed + " / " + root.value.required : "—"
        surfaceColor: root.color
        textColor: Color.accent
        font.pixelSize: Style.space(34)
        font.bold: true
      }
      Label {
        Layout.fillWidth: true
        text: root.ready ? "required kanji passed" : root.value.accessible === false ? "Progress unavailable" : "Waiting for a complete sync"
        surfaceColor: root.color
        secondary: true
      }
    }
    Rectangle {
      objectName: "levelPassingMeter"
      Layout.fillWidth: true
      implicitHeight: Style.space(9)
      radius: height / 2
      color: Theme.tint(Color.foreground, root.color, 0.12)
      readonly property real value: root.ready ? Math.max(0, Math.min(1, root.value.fraction)) : 0
      Accessible.role: Accessible.ProgressBar
      Accessible.name: root.ready ? root.value.passed + " of " + root.value.required + " required kanji passed" : "Level progress unavailable until synchronization completes"
      Rectangle {
        width: parent.width * parent.value
        height: parent.height
        radius: parent.radius
        color: Theme.indicator(Color.accent, root.color, Color.foreground)
      }
    }
    Label {
      objectName: "levelProgressExplanation"
      Layout.fillWidth: true
      text: root.explanation
      surfaceColor: root.color
    }
    Label {
      Layout.fillWidth: true
      visible: root.ready && Number.isInteger(root.value.elapsed_days) && root.value.elapsed_days >= 0
      text: visible ? root.value.elapsed_days + (root.value.elapsed_days === 1 ? " day" : " days") + " since this level unlocked" : ""
      surfaceColor: root.color
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "levelPendingProgress"
      Layout.fillWidth: true
      visible: (root.value.pending || 0) > 0 || (root.value.attention || 0) > 0
      text: [(root.value.pending || 0) > 0 ? root.value.pending + " waiting to sync" : "", (root.value.attention || 0) > 0 ? root.value.attention + " need attention" : ""].filter(function (entry) { return entry.length > 0 }).join(" · ") + ". Confirmed progress stays separate."
      surfaceColor: root.color
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Action {
      objectName: "exploreLevel"
      visible: root.showExplore
      text: "Explore this level →"
      enabled: root.hasLevel && root.value.accessible === true
      surfaceColor: root.color
      onClicked: root.explore()
    }
  }
}
