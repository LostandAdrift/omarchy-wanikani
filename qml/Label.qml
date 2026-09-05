import QtQuick
import qs.Commons

Text {
  id: root
  color: Color.foreground
  font.family: Style.font.family
  font.pixelSize: Style.font.body
  wrapMode: Text.Wrap
  textFormat: Text.PlainText
  renderType: Text.NativeRendering
  Accessible.role: Accessible.StaticText
  Accessible.name: text
  Accessible.ignored: !visible || text.length === 0
}
