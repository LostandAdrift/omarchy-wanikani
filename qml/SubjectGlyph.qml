import QtQuick
import qs.Commons

Item {
  id: root
  property var subject: null
  property real pixelSize: Style.space(94)
  implicitWidth: Style.space(140)
  implicitHeight: pixelSize * 1.2
  Label {
    anchors.fill: parent
    visible: !!(root.subject && root.subject.characters)
    text: root.subject ? root.subject.characters : ""
    font.family: "Noto Sans CJK JP"
    font.pixelSize: root.pixelSize
    horizontalAlignment: Text.AlignHCenter
    verticalAlignment: Text.AlignVCenter
    maximumLineCount: 1
    elide: Text.ElideRight
  }
  Rectangle {
    anchors.centerIn: parent
    width: Math.min(parent.width, parent.height)
    height: width
    visible: !!(root.subject && !root.subject.characters && root.subject.images.length)
    // WaniKani's black radical images need a light backing in dark themes.
    color: "white"
    radius: Style.cornerRadius
    Image {
      anchors.fill: parent
      anchors.margins: Style.space(8)
      source: root.subject && root.subject.images.length ? root.subject.images[0] : ""
      fillMode: Image.PreserveAspectFit
      Accessible.name: root.subject ? "Radical " + root.subject.slug : "Radical image"
    }
  }
}
