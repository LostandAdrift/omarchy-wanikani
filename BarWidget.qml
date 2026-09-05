import QtQuick
import Quickshell
import qs.Commons
import qs.Ui as Ui
import "qml" as Kani

Ui.BarWidget {
  id: root
  moduleName: "io.github.lostandadrift.wanikani"
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property var info: service ? service.snapshot : ({})
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
      var minutes = Math.max(1, Math.ceil((Date.parse(info.next_reviews_at) - Date.now()) / 60000))
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
    tooltipText: "WaniKani · " + (root.info.status || "starting") + " · " + (root.info.reviews || 0) + " reviews · Click for Today, middle-click to study, right-click for Settings"
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
      ink: root.bar ? root.bar.barForeground : Color.foreground
      shellColor: ink
    }
    Kani.Label {
      visible: !root.vertical
      anchors.verticalCenter: parent.verticalCenter
      text: root.label
      font.pixelSize: Style.font.bodySmall
      color: root.bar ? root.bar.barForeground : Color.foreground
    }
  }
  Kani.Label {
    visible: root.vertical
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    text: root.info.attention > 0 ? "!" : String(root.info.reviews || 0)
    font.pixelSize: Style.space(9)
    color: root.bar ? root.bar.barForeground : Color.foreground
  }
  Accessible.role: Accessible.Button
  Accessible.name: "WaniKani, " + (info.reviews || 0) + " reviews, " + (info.pending || 0) + " pending"
}
