pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  readonly property var snapshot: controller.snapshot
  readonly property int preferred: snapshot.settings.voice_actor_id || 1
  readonly property string cacheIdentity: (controller.contentAccess || "") + "|" + (snapshot.last_sync || "") + "|" + (snapshot.cache ? snapshot.cache.subjects : 0)
  property var voices: []
  property string notice: ""
  property bool loading: false
  property bool initialized: false
  property bool dirty: true
  property bool fetching: false
  property int requestSerial: 0
  readonly property bool active: controller.opened && controller.service && controller.service.ready && !controller.service.locked
  onActiveChanged: {
    requestSerial++
    dirty = true
    loading = false
    refreshDelay.stop()
    if (active && initialized)
      Qt.callLater(loadVoices)
  }
  readonly property bool preferenceAvailable: voices.some(function (voice) {
    return voice.id === root.preferred
  })
  readonly property string selectedDescription: {
    for (var index = 0; index < voices.length; index++) {
      if (voices[index].id === preferred)
        return voices[index].description
    }
    return ""
  }
  spacing: Style.space(8)

  function loadVoices() {
    if (!active || !dirty || fetching)
      return
    var serial = requestSerial
    dirty = false
    fetching = true
    loading = true
    refreshDelay.stop()
    controller.service.request("voices", {}, function (ok, data, message) {
      if (!root)
        return
      root.fetching = false
      if (serial === root.requestSerial && root.active) {
        root.loading = false
        root.voices = ok ? data.items : []
        root.notice = ok ? data.message || "" : message || "Cached voices could not be loaded."
      }
      if (root.active && root.dirty)
        Qt.callLater(root.loadVoices)
    })
  }
  onCacheIdentityChanged: {
    requestSerial++
    dirty = true
    voices = []
    if (active && initialized)
      refreshDelay.restart()
  }
  Component.onCompleted: {
    initialized = true
    refreshDelay.stop()
    Qt.callLater(loadVoices)
  }
  Component.onDestruction: requestSerial++
  Timer {
    id: refreshDelay
    interval: 150
    onTriggered: root.loadVoices()
  }

  Label {
    text: "Pronunciation voice"
  }
  Flow {
    id: choiceFlow
    Layout.fillWidth: true
    spacing: Style.space(8)
    Repeater {
      model: root.voices
      Action {
        id: voiceButton
        required property var modelData
        width: Math.min(implicitWidth, parent.width)
        text: voiceLabel.elidedText
        accessibleName: modelData.label
        selected: modelData.id === root.preferred
        tooltipText: modelData.label + (modelData.description ? " · " + modelData.description : "")
        accessibleHint: (modelData.description ? modelData.description + ". " : "") + (selected ? "Preferred pronunciation voice." : "Choose this pronunciation voice.")
        onClicked: root.controller.service.saveSettings({
          voice_actor_id: modelData.id
        })
        TextMetrics {
          id: voiceLabel
          text: voiceButton.modelData.label
          font.family: voiceButton.fontFamily
          font.pixelSize: voiceButton.fontSize
          font.bold: voiceButton.selected
          elide: Qt.ElideRight
          elideWidth: Math.max(24, choiceFlow.width - voiceButton.horizontalPadding * 2 - 8)
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.selectedDescription !== ""
    text: root.selectedDescription
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    text: root.loading ? "Reading available voices from your cached catalogue…" : root.voices.length === 0 ? "Voices appear when pronunciation metadata is cached from your account. Your saved voice preference is kept." : "Uses downloaded pronunciation clips. If the preferred voice is not cached for a word, another downloaded voice is used."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: !root.loading && root.voices.length > 0 && !root.preferenceAvailable
    text: "Saved preference: Voice " + root.preferred + ". This voice is not listed in the accessible cached catalogue."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.notice !== ""
    text: root.notice
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
}
