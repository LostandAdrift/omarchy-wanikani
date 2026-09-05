import QtQuick

Text {
  // Qt shapes and measures the complete text. Keep a readable minimum, then
  // wrap exceptionally long prompts instead of dropping characters or glyphs.
  font.family: "Noto Sans CJK JP"
  font.pixelSize: 94
  minimumPixelSize: Math.min(22, font.pixelSize)
  fontSizeMode: Text.HorizontalFit
  wrapMode: Text.Wrap
  elide: Text.ElideNone
  textFormat: Text.PlainText
  renderType: Text.NativeRendering
  horizontalAlignment: Text.AlignHCenter
  verticalAlignment: Text.AlignVCenter
  // Text's default implicitHeight reflects the requested font before fitting.
  // Its measured contentHeight reflects the fitted font and actual wrapping.
  height: Math.ceil(contentHeight)
  Accessible.role: Accessible.StaticText
  Accessible.name: text
  Accessible.ignored: !visible || text.length === 0
}
