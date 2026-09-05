import QtQuick
import qs.Ui as Ui

Ui.Button {
  id: root
  property string accessibleName: text
  property string accessibleHint: tooltipText
  focusable: true
  bordered: true
  activeFocusOnTab: focusable && enabled
  Keys.enabled: enabled
  Keys.forwardTo: [activationGuard]
  opacity: enabled ? 1 : 0.45
  ActivationGuard {
    id: activationGuard
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
