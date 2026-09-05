import QtQuick
import qs.Commons

Item {
  id: root
  property var subject: null
  property bool revealLabel: true
  property real pixelSize: Style.space(94)
  property real minimumPixelSize: Style.space(22)
  readonly property bool hasCharacters: !!(subject && typeof subject.characters === "string" && subject.characters.trim().length)
  readonly property bool displayReady: hasCharacters || !!subject && radical.displayReady
  readonly property bool displayLoading: !!subject && !hasCharacters && radical.displayLoading
  readonly property bool displayFailed: !!subject && !hasCharacters && radical.displayFailed
  implicitWidth: Style.space(140)
  implicitHeight: Math.max(pixelSize * 1.2, glyph.visible ? glyph.contentHeight : 0)
  JapaneseText {
    id: glyph
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    visible: root.hasCharacters
    text: root.hasCharacters ? root.subject.characters : ""
    color: Color.foreground
    font.pixelSize: root.pixelSize
    minimumPixelSize: Math.min(root.minimumPixelSize, root.pixelSize)
  }
  RadicalImage {
    id: radical
    anchors.centerIn: parent
    width: Math.min(parent.width, parent.height)
    height: width
    visible: !!root.subject && !root.hasCharacters
    subject: root.hasCharacters ? null : root.subject
    revealLabel: root.revealLabel
    radius: Style.cornerRadius
    imageMargin: Style.space(8)
  }
}
