import QtQuick

Rectangle {
  id: root
  property var subject: null
  property bool revealLabel: true
  property real imageMargin: 8
  readonly property var imageSources: subject && Array.isArray(subject.images) ? subject.images : []
  readonly property string sourceKey: JSON.stringify([subject ? subject.id : null, imageSources])
  property int sourceIndex: 0
  readonly property bool displayReady: imageSources.length > 0 && image.status === Image.Ready
  readonly property bool displayLoading: imageSources.length > 0 && !displayReady && !displayFailed
  readonly property bool displayFailed: imageSources.length === 0 || image.status === Image.Error && sourceIndex >= imageSources.length - 1
  onSourceKeyChanged: sourceIndex = 0
  // WaniKani's black radical images need a light backing in dark themes.
  color: "white"
  Image {
    id: image
    objectName: "radicalImage"
    anchors.fill: parent
    anchors.margins: root.imageMargin
    source: root.sourceIndex < root.imageSources.length ? root.imageSources[root.sourceIndex] : ""
    asynchronous: true
    fillMode: Image.PreserveAspectFit
    onStatusChanged: {
      if (status !== Image.Error || root.sourceIndex >= root.imageSources.length - 1)
        return
      // Try another cached format without retrying the same damaged file forever.
      const key = root.sourceKey
      const index = root.sourceIndex
      Qt.callLater(function () {
        if (root.sourceKey === key && root.sourceIndex === index && image.status === Image.Error)
          root.sourceIndex++
      })
    }
    Accessible.role: Accessible.Graphic
    Accessible.name: root.revealLabel && root.subject && root.subject.slug ? "Radical " + root.subject.slug : root.subject && root.subject.id !== undefined ? "Radical image, subject " + root.subject.id : "Radical image"
  }
}
