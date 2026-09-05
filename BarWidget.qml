import QtQuick
import Quickshell
import qs.Commons
import qs.Ui as Ui
import "qml" as Kani
import "qml/Theme.mjs" as Theme

Ui.BarWidget {
  id: root
  moduleName: "io.github.lostandadrift.wanikani"
  readonly property color kaniSurface: Theme.composite(root.bar ? root.bar.background : Color.bar.background, Color.background)
  readonly property color kaniText: root.bar ? root.bar.barForeground : Color.bar.text
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property var info: service ? service.snapshot : ({})
  readonly property real nextReviewTime: typeof info.next_reviews_at === "string" ? Date.parse(info.next_reviews_at) : NaN
  property real countdownNow: Date.now()
  readonly property bool countdownEligible: visible && Window.window && Window.window.visible && service && service.ready && !service.locked && !info.syncing && !(info.attention > 0) && info.status !== "offline" && !(info.pending > 0) && !!info.username && info.reviews === 0 && isFinite(nextReviewTime)
  readonly property bool scheduleNeedsRefresh: !!info.next_reviews_at && info.reviews === 0 && (!isFinite(nextReviewTime) || nextReviewTime <= countdownNow)
  onInfoChanged: countdownNow = Date.now()
  onCountdownEligibleChanged: countdownNow = Date.now()

  SystemClock {
    id: countdownClock
    precision: SystemClock.Minutes
    enabled: root.countdownEligible && root.nextReviewTime > root.countdownNow
    onDateChanged: root.countdownNow = date.getTime()
  }

  readonly property string label: {
    if (!service || !service.ready)
      return "…"
    if (info.syncing)
      return "↻ " + (info.reviews || 0)
    if (info.attention > 0)
      return "! " + (info.reviews || 0)
    if (info.status === "offline")
      return "○ " + (info.reviews || 0)
    if (info.pending > 0)
      return (info.reviews || 0) + " · " + info.pending
    if (!info.username)
      return "+"
    if (info.reviews > 0)
      return String(info.reviews)
    if (info.next_reviews_at) {
      if (!isFinite(nextReviewTime) || nextReviewTime <= countdownNow)
        return "…"
      var minutes = Math.ceil((nextReviewTime - countdownNow) / 60000)
      return minutes < 60 ? minutes + "m" : Math.ceil(minutes / 60) + "h"
    }
    return "✓"
  }
  implicitWidth: vertical ? barSize : content.implicitWidth + Style.space(16)
  implicitHeight: barSize
  Ui.WidgetButton {
    anchors.fill: parent
    bar: root.bar
    text: ""
    hasVisualContent: true
    tooltipText: "WaniKani · " + (root.info.status || "starting") + " · " + (root.info.reviews || 0) + " reviews · " + (root.scheduleNeedsRefresh ? "Review schedule needs a refresh · " : "") + "Click for Today, middle-click to study, right-click for Settings"
    onPressed: function (button) {
      if (!root.service)
        return
      if (button === Qt.RightButton)
        root.service.summon("settings")
      else if (button === Qt.MiddleButton)
        root.service.summon("reviews")
      else
        root.service.summon("dashboard")
    }
  }
  Row {
    id: content
    anchors.centerIn: parent
    spacing: Style.space(5)
    Kani.Crab {
      width: Style.space(23)
      height: Style.space(20)
      ink: root.bar && root.bar.transparent ? root.kaniText : Theme.readable(root.kaniText, root.kaniSurface, Color.foreground)
      shellColor: ink
      animate: root.service && root.service.animations && !root.service.locked && root.Window.window && root.Window.window.visible
      celebrating: !!root.info.milestone
    }
    Kani.Label {
      visible: !root.vertical
      anchors.verticalCenter: parent.verticalCenter
      text: root.label
      font.pixelSize: Style.font.bodySmall
      textColor: root.kaniText
      surfaceColor: root.kaniSurface
      color: root.bar && root.bar.transparent ? root.kaniText : Theme.readable(textColor, surfaceColor, Color.foreground)
    }
  }
  Kani.Label {
    visible: root.vertical
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    text: root.label.replace(/ /g, "")
    width: root.width
    wrapMode: Text.NoWrap
    elide: Text.ElideRight
    horizontalAlignment: Text.AlignRight
    font.pixelSize: Style.space(9)
    textColor: root.kaniText
    surfaceColor: root.kaniSurface
    color: root.bar && root.bar.transparent ? root.kaniText : Theme.readable(textColor, surfaceColor, Color.foreground)
  }
  Accessible.role: Accessible.Button
  Accessible.name: "WaniKani, " + (info.reviews || 0) + " reviews, " + (info.pending || 0) + " pending"
}
