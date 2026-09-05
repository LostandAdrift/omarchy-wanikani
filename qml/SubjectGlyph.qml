import QtQuick
import qs.Commons

Item {
  id: root
  property var subject: null
  property bool revealLabel: true
  property real pixelSize: Style.space(94)
  property real minimumPixelSize: Style.space(22)
  implicitWidth: Style.space(140)
  implicitHeight: Math.max(pixelSize * 1.2, glyph.visible ? glyph.contentHeight : 0)
  JapaneseText {
    id: glyph
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    visible: !!(root.subject && root.subject.characters)
    text: root.subject ? root.subject.characters : ""
    color: Color.foreground
    font.pixelSize: root.pixelSize
    minimumPixelSize: Math.min(root.minimumPixelSize, root.pixelSize)
  }
  RadicalImage {
    anchors.centerIn: parent
    width: Math.min(parent.width, parent.height)
    height: width
    visible: !!(root.subject && !root.subject.characters && root.subject.images.length)
    subject: root.subject
    revealLabel: root.revealLabel
    radius: Style.cornerRadius
    imageMargin: Style.space(8)
  }
}
