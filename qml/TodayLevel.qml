import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme

Card {
  id: root
  objectName: "today-level"
  required property var progress
  property bool demo: false
  signal explore()
  readonly property var value: progress || ({})
  readonly property bool hasLevel: Number.isInteger(value.level) && value.level >= 1 && value.level <= 60
  readonly property bool ready: value.accessible === true && value.complete === true && Number.isSafeInteger(value.passed) && value.passed >= 0 && Number.isSafeInteger(value.required) && value.required > 0 && typeof value.fraction === "number" && isFinite(value.fraction) && value.fraction >= 0 && value.fraction <= 1
  readonly property string headline: hasLevel ? "Level " + value.level + (value.final_level === true ? " · Final level" : "") : "Current level"
  readonly property string target: !ready ? (value.accessible === false ? "Outside current account access." : "Refresh to finish caching this level.") : value.passed >= value.required ? (demo ? "Demo passing target reached." : value.final_level === true ? "Final level passing target reached." : "Target reached; WaniKani confirms advancement.") : (value.required - value.passed) + " more kanji to pass" + (value.final_level === true ? " on this final level." : " for level-up.")
  readonly property var pending: [Number.isSafeInteger(value.pending) && value.pending > 0 ? value.pending + " waiting to sync" : "", Number.isSafeInteger(value.attention) && value.attention > 0 ? value.attention + " need attention" : ""].filter(function (part) {
    return part.length > 0
  })
  implicitHeight: content.implicitHeight + Style.space(24)

  ColumnLayout {
    id: content
    anchors.fill: parent
    anchors.margins: Style.space(12)
    spacing: Style.space(6)
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Label {
        objectName: "today-level-heading"
        Layout.fillWidth: true
        text: root.headline
        font.bold: true
      }
      Action {
        objectName: "today-level-explore"
        text: "Progress →"
        accessibleName: "Explore " + (root.hasLevel ? "level " + root.value.level : "current level") + " progress"
        accessibleHint: "See the full level, SRS stages, and recorded level history"
        enabled: root.hasLevel && root.value.accessible === true
        onClicked: root.explore()
      }
    }
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(10)
      Label {
        objectName: "today-level-count"
        text: root.ready ? root.value.passed + " / " + root.value.required : "—"
        font.pixelSize: Style.space(28)
        font.bold: true
        textColor: Color.accent
      }
      Label {
        objectName: "today-level-count-label"
        Layout.fillWidth: true
        text: root.ready ? "required kanji passed" : root.value.accessible === false ? "Progress unavailable" : "Waiting for a complete sync"
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
    }
    Rectangle {
      objectName: "today-level-meter"
      Layout.fillWidth: true
      implicitHeight: Style.space(7)
      radius: height / 2
      color: Theme.tint(Color.foreground, root.kaniSurface, 0.12)
      readonly property real value: root.ready ? root.value.fraction : 0
      Accessible.role: Accessible.ProgressBar
      Accessible.name: root.ready ? root.value.passed + " of " + root.value.required + " required kanji passed, " + (root.demo ? "confirmed locally in demo" : "confirmed by WaniKani") : "Level progress unavailable until synchronization completes"
      Rectangle {
        width: parent.width * parent.value
        height: parent.height
        radius: parent.radius
        color: Theme.indicator(Color.accent, parent.color, Color.foreground)
      }
    }
    Label {
      objectName: "today-level-target"
      Layout.fillWidth: true
      text: root.target
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "today-level-pending"
      Layout.fillWidth: true
      visible: root.pending.length > 0
      text: root.pending.join(" · ") + "; outside the confirmed count."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
  }
}
