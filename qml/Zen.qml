import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  property int index: 0
  readonly property var items: controller.service ? controller.service.ambientItems : []
  readonly property var subject: items.length ? items[index % items.length] : null
  spacing: Style.space(22)
  Label {
    Layout.fillWidth: true
    text: "A MOMENT OF JAPANESE"
    horizontalAlignment: Text.AlignHCenter
    color: Qt.alpha(Color.foreground, 0.76)
    font.letterSpacing: 3
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    text: root.subject ? root.subject.characters : "ひと休み"
    font.family: "Noto Sans CJK JP"
    font.pixelSize: Style.space(root.subject && root.subject.characters.length > 4 ? 76 : 116)
    horizontalAlignment: Text.AlignHCenter
  }
  Label {
    Layout.fillWidth: true
    text: root.subject ? root.subject.meanings.join(" · ") : "A little rest"
    font.pixelSize: Style.font.title
    color: Color.accent
    horizontalAlignment: Text.AlignHCenter
  }
  Label {
    Layout.fillWidth: true
    text: root.subject ? root.subject.readings.map(function (r) {
      return r.reading
    }).join(" · ") : "Learned subjects will appear here when their next review is more than a day away."
    font.family: root.subject ? "Noto Sans CJK JP" : Style.font.family
    color: Qt.alpha(Color.foreground, 0.76)
    horizontalAlignment: Text.AlignHCenter
  }
  Crab {
    Layout.alignment: Qt.AlignHCenter
    Layout.preferredWidth: Style.space(140)
    Layout.preferredHeight: Style.space(112)
    animate: root.controller.opened && root.controller.service && root.controller.service.animations
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: "Another word"
      enabled: root.items.length > 1
      onClicked: root.index++
    }
    Action {
      text: "Back to work"
      onClicked: root.controller.dismiss()
    }
  }
  Timer {
    interval: 30000
    repeat: true
    running: root.controller.opened && root.items.length > 1
    onTriggered: root.index++
  }
}
