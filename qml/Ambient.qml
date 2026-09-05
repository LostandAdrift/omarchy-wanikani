import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons

Item {
  id: root
  required property var service
  property bool gallery: false
  property bool showCard: false
  Variants {
    model: Quickshell.screens
    PanelWindow {
      required property var modelData
      screen: modelData
      visible: (root.gallery || root.showCard) && root.service.ambientSubject !== null
      anchors { top: true; bottom: true; left: true; right: true }
      exclusionMode: ExclusionMode.Ignore
      WlrLayershell.layer: root.gallery ? WlrLayer.Overlay : WlrLayer.Bottom
      WlrLayershell.namespace: "omarchy-wanikani-ambient"
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      mask: Region {}
      color: root.gallery ? Color.background : "transparent"
      Column {
        x: root.gallery ? (parent.width - width) / 2 : parent.width - width - Style.space(44)
        y: root.gallery ? (parent.height - height) / 2 : parent.height - height - Style.space(70)
        width: root.gallery ? Math.min(parent.width * 0.7, Style.space(700)) : Style.space(280)
        spacing: Style.space(12)
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.gallery ? "A MOMENT OF JAPANESE" : "LEARNED & GROWING"; color: Color.muted; font.pixelSize: Style.font.bodySmall; font.letterSpacing: 2 }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.service.ambientSubject ? root.service.ambientSubject.characters : ""; font.family: "Noto Sans CJK JP"; font.pixelSize: root.gallery ? Style.space(150) : Style.space(66) }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.service.ambientSubject ? root.service.ambientSubject.meanings.join(" · ") : ""; color: Color.accent; font.pixelSize: Style.font.title }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.service.ambientSubject ? root.service.ambientSubject.readings.map(function(r) { return r.reading }).join(" · ") : ""; font.family: "Noto Sans CJK JP" }
        Crab { anchors.horizontalCenter: parent.horizontalCenter; animate: false; width: Style.space(64); height: Style.space(52) }
      }
    }
  }
}
