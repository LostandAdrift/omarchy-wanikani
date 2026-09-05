import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  required property var subject
  readonly property bool selectedAudio: !!subject && controller.audioSubjectId === subject.id
  readonly property bool cached: !!(subject && subject.audio && subject.audio.length)
  readonly property string playback: selectedAudio ? controller.audioState || "" : ""
  spacing: Style.space(6)
  visible: !!subject && subject.audio_available === true

  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: root.playback === "loading" ? "Loading pronunciation…" : root.playback === "playing" ? "Replay pronunciation" : root.playback === "failed" ? "Retry pronunciation" : "Play pronunciation"
      accessibleName: text
      enabled: root.controller.opened && root.controller.service && root.controller.service.ready && !root.controller.service.locked && root.playback !== "loading"
      onClicked: root.controller.play(root.subject)
    }
    Action {
      text: "Stop"
      visible: root.playback === "playing"
      onClicked: root.controller.stopAudio()
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.selectedAudio && root.controller.audioNotice ? root.controller.audioNotice : root.cached ? "Recording ready offline" : "Download this word’s recording when connected."
    font.pixelSize: Style.font.bodySmall
    textColor: root.playback === "failed" ? Color.urgent : Color.foreground
    Accessible.role: Accessible.StaticText
    Accessible.name: text
  }
}
