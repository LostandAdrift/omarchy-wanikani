import QtQuick
import qs.Commons
import "Theme.mjs" as Theme

Rectangle {
  readonly property color kaniSurface: Theme.composite(color, surfaceColor)
  readonly property color kaniText: Theme.foreground(parent, Color.foreground)
  property color surfaceColor: Theme.surface(parent, Color.background)
  readonly property color textColor: Theme.readable(kaniText, kaniSurface, Color.foreground)
  color: Theme.tint(kaniText, surfaceColor, 0.035)
  border.color: Theme.tint(kaniText, kaniSurface, 0.14)
  border.width: 1
  radius: Style.cornerRadius
}
