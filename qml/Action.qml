import QtQuick
import qs.Commons
import qs.Ui as Ui
import "Theme.mjs" as Theme

Ui.Button {
  id: root
  property string accessibleName: text
  property string accessibleHint: tooltipText
  property color surfaceColor: Theme.surface(parent, Color.background)
  property color textColor: Theme.foreground(parent, Color.foreground)
  foreground: enabled ? Theme.readable(textColor, surfaceColor, Color.foreground) : Theme.secondary(textColor, surfaceColor)
  accent: Theme.readable(Color.accent, surfaceColor, Color.foreground)
  focusable: true
  bordered: true
  activeFocusOnTab: focusable && enabled
  Keys.enabled: enabled
  Keys.forwardTo: [activationGuard]
  // Keep disabled labels readable; disabled interaction and accessible state
  // still come from the native control. Do not fade its entire subtree.
  opacity: 1
  ActivationGuard {
    id: activationGuard
  }
  Rectangle {
    objectName: "wanikani-action-focus"
    anchors.fill: parent
    anchors.margins: 2
    radius: Math.max(0, root.radius - 2)
    color: "transparent"
    border.width: 2
    border.color: Theme.indicator(Color.accent, Theme.composite(root.color, root.surfaceColor), Color.foreground)
    visible: root.enabled && root.activeFocus
  }

  // The native button already owns Enter, Space, and the themed focus border.
  // Keep a focused action visible when Tab reaches below a long lesson/page.
  function revealInScrollView() {
    if (!activeFocus || !visible)
      return
    var ancestor = parent
    while (ancestor) {
      var flickable = ancestor as Flickable
      if (flickable) {
        var point = root.mapToItem(flickable.contentItem, 0, 0)
        var margin = 8
        var maximum = Math.max(0, flickable.contentHeight - flickable.height)
        if (point.y < flickable.contentY + margin)
          flickable.contentY = Math.max(0, point.y - margin)
        else if (point.y + root.height > flickable.contentY + flickable.height - margin)
          flickable.contentY = Math.min(maximum, point.y + root.height - flickable.height + margin)
      }
      ancestor = ancestor.parent
    }
  }
  onActiveFocusChanged: if (activeFocus)
    Qt.callLater(revealInScrollView)

  Accessible.role: Accessible.Button
  Accessible.name: accessibleName
  Accessible.description: accessibleHint
  Accessible.focusable: focusable && enabled
  Accessible.ignored: !visible
  Accessible.onPressAction: {
    if (root.enabled && root.visible) {
      if (root.focusable)
        root.forceActiveFocus(Qt.OtherFocusReason)
      root.clicked()
    }
  }
}
