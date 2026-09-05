import QtQuick

Rectangle {
  id: root
  property var subject: null
  property bool revealLabel: true
  property real imageMargin: 8
  // WaniKani's black radical images need a light backing in dark themes.
  color: "white"
  Image {
    id: image
    objectName: "radicalImage"
    anchors.fill: parent
    anchors.margins: root.imageMargin
    source: root.subject && root.subject.images && root.subject.images.length ? root.subject.images[0] : ""
    fillMode: Image.PreserveAspectFit
    Accessible.role: Accessible.Graphic
    Accessible.name: root.revealLabel && root.subject && root.subject.slug ? "Radical " + root.subject.slug : root.subject && root.subject.id !== undefined ? "Radical image, subject " + root.subject.id : "Radical image"
  }
}
