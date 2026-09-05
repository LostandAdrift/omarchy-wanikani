import QtQuick
import qs.Commons
import "Theme.mjs" as Theme

Text {
  id: root
  property color surfaceColor: Theme.surface(parent, Color.background)
  property color textColor: Theme.foreground(parent, Color.foreground)
  property bool secondary: false
  color: secondary ? Theme.secondary(textColor, surfaceColor) : Theme.readable(textColor, surfaceColor, Color.foreground)
  font.family: Style.font.family
  font.pixelSize: Style.font.body
  wrapMode: Text.Wrap
  textFormat: Text.PlainText
  renderType: Text.NativeRendering
  Accessible.role: Accessible.StaticText
  Accessible.name: text
  Accessible.ignored: !visible || text.length === 0
}
