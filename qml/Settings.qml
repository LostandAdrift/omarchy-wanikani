import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Quickshell
import qs.Commons
import qs.Ui as Ui

ColumnLayout {
  id: root
  required property var controller
  readonly property var snapshot: controller.snapshot
  property string notice: ""
  property bool showDeletion: false
  property bool remember: true
  property bool discardPending: false
  spacing: Style.space(14)
  function focusInput() {
    if (!snapshot.connected && !snapshot.demo)
      token.forceActiveFocus()
  }
  Label {
    text: "Make it yours."
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "WaniKani account"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: snapshot.demo ? "You are exploring independently authored sample material. No account is connected in demo mode." : snapshot.username ? "Connected data for " + snapshot.username + ". Token storage: " + snapshot.credential_storage + "." : "Create a personal API token in WaniKani Settings. Reading works with a read-only token; native study also needs permissions to start assignments and create reviews. Notes need study-material create/update permissions."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Action {
    text: snapshot.demo ? "Leave demo" : "Explore demo"
    enabled: !root.controller.busy && !root.snapshot.syncing
    onClicked: root.controller.call("use_demo", {
      enabled: !root.snapshot.demo
    })
  }
  Flow {
    Layout.fillWidth: true
    visible: root.snapshot.demo
    spacing: Style.space(8)
    Action {
      text: root.snapshot.settings.demo_offline ? "Reconnect demo & sync" : "Simulate offline in demo"
      onClicked: root.controller.service.saveSettings({
        demo_offline: !root.snapshot.settings.demo_offline
      })
    }
    Action {
      text: "Reset demo progress"
      onClicked: root.controller.call("delete_data", {
        confirmation: "DELETE",
        discard_pending: true
      })
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: !root.snapshot.demo
    Action {
      text: "Open WaniKani API token settings ↗"
      onClicked: Qt.openUrlExternally("https://www.wanikani.com/settings/personal_access_tokens")
    }
    Ui.TextField {
      id: token
      Layout.fillWidth: true
      password: true
      placeholderText: "Paste your personal API token"
      Accessible.name: "WaniKani API token"
    }
    Controls.CheckBox {
      text: "Remember securely in the desktop keyring"
      checked: root.remember
      onToggled: root.remember = checked
      palette.windowText: Color.foreground
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        text: "Connect / replace token"
        enabled: token.text.length > 0 && !root.controller.busy && !root.snapshot.syncing
        onClicked: {
          var secret = token.text
          token.text = ""
          root.controller.call("authenticate", {
            token: secret,
            remember: root.remember
          }, function (ok, data) {
            if (ok)
              root.notice = data.credential_cleanup_needed ? "Connected for this session. Unlock the keyring and disconnect again to remove an older saved token." : data.remembered ? "Token saved in your keyring." : "Connected for this session. The token was not stored."
          })
          secret = ""
        }
      }
      Action {
        text: "Disconnect"
        enabled: root.snapshot.connected && !root.snapshot.syncing
        onClicked: root.controller.call("disconnect", {})
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: notice !== ""
    text: notice
    color: Color.accent
  }
  Label {
    text: "Study & atmosphere"
    font.bold: true
  }
  Repeater {
    model: [
      {
        key: "companion_animation",
        label: "Companion animation"
      },
      {
        key: "reduced_motion",
        label: "Reduce motion"
      },
      {
        key: "desktop_card",
        label: "Learned-kanji card on the desktop"
      },
      {
        key: "idle_gallery",
        label: "Kanji gallery before the screensaver"
      },
      {
        key: "autoplay_audio",
        label: "Play cached pronunciation after a reading answer"
      },
      {
        key: "notifications",
        label: "Gentle review reminders"
      }
    ]
    RowLayout {
      required property var modelData
      Layout.fillWidth: true
      Label {
        Layout.fillWidth: true
        text: modelData.label
      }
      Action {
        text: root.snapshot.settings[modelData.key] ? "On" : "Off"
        selected: root.snapshot.settings[modelData.key] === true
        onClicked: {
          var value = {}
          value[modelData.key] = !root.snapshot.settings[modelData.key]
          root.controller.service.saveSettings(value)
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: "Ambient subjects are learned and not due in the next 24 hours. Idle views yield to your existing screensaver and lock. Reminders respect Do Not Disturb, quiet hours, vacation, and study sessions."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Batch size"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      from: 1
      to: 20
      value: root.snapshot.settings.batch_size || 5
      onModified: function (value) {
        root.controller.service.saveSettings({
          batch_size: value
        })
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Quiet hours · local time"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      from: 0
      to: 23
      value: root.snapshot.settings.quiet_start === undefined ? 22 : root.snapshot.settings.quiet_start
      onModified: function (value) {
        root.controller.service.saveSettings({
          quiet_start: value
        })
      }
    }
    Label {
      text: "to"
    }
    Ui.NumberField {
      from: 0
      to: 23
      value: root.snapshot.settings.quiet_end === undefined ? 8 : root.snapshot.settings.quiet_end
      onModified: function (value) {
        root.controller.service.saveSettings({
          quiet_end: value
        })
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Minimum hours between reminders"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      from: 1
      to: 24
      value: Math.round((root.snapshot.settings.reminder_interval || 7200) / 3600)
      onModified: function (value) {
        root.controller.service.saveSettings({
          reminder_interval: value * 3600
        })
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Pronunciation voice actor ID"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      from: 1
      to: 100
      value: root.snapshot.settings.voice_actor_id || 1
      onModified: function (value) {
        root.controller.service.saveSettings({
          voice_actor_id: value
        })
      }
    }
  }
  Label {
    text: "Offline storage"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.snapshot.cache ? (root.snapshot.cache.subjects || 0) + " subjects available offline · " + root.snapshot.cache.files + " media files · " + (root.snapshot.cache.bytes / 1048576).toFixed(1) + " MB. Answers and sessions are saved separately." : "No cached media"
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Media cache limit (MB)"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      from: 32
      to: 1024
      stepSize: 32
      value: root.snapshot.settings.cache_limit_mb || 256
      onModified: function (value) {
        root.controller.service.saveSettings({
          cache_limit_mb: value
        })
      }
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: "Refresh cached material"
      enabled: !root.snapshot.syncing
      onClicked: root.controller.call("sync", {})
    }
    Action {
      text: "Clear downloaded media"
      enabled: !root.snapshot.syncing
      onClicked: root.controller.call("clear_cache", {})
    }
    Action {
      text: "Export diagnostics"
      onClicked: root.controller.call("diagnostics", {}, function (ok, data) {
        if (ok)
          root.notice = "Diagnostics saved to " + data.path + ". No token, answers, notes, or username included."
      })
    }
  }
  Label {
    text: "Synchronization"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Pending work stays saved until confirmed. If a request loses its response, refresh to reconcile. Keeping remote progress archives your local result without resubmitting it."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Repeater {
    model: root.snapshot.outbox || []
    Card {
      required property var modelData
      Layout.fillWidth: true
      Layout.preferredHeight: entry.implicitHeight + Style.space(24)
      ColumnLayout {
        id: entry
        anchors.fill: parent
        anchors.margins: Style.space(12)
        Label {
          Layout.fillWidth: true
          text: modelData.kind + " · Subject " + modelData.subject_id + " · " + modelData.state
          font.bold: true
        }
        Label {
          Layout.fillWidth: true
          text: modelData.detail
          color: Qt.alpha(Color.foreground, 0.76)
          font.pixelSize: Style.font.bodySmall
        }
        Action {
          text: "Keep remote progress & archive local result"
          visible: ["uncertain", "conflicted", "blocked"].indexOf(modelData.state) >= 0
          enabled: !root.snapshot.syncing
          onClicked: root.controller.call("resolve", {
            id: modelData.id,
            action: "keep_remote"
          })
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: "Super+Alt+W opens study; Super+Alt+Shift+W looks up selected text. Add the available shortcuts and Study/Lookup launcher entries here. Existing bindings are preserved."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: "Install shortcuts & launchers"
      onClicked: root.controller.desktopIntegration(false)
    }
    Action {
      text: "Remove shortcuts & launchers"
      onClicked: root.controller.desktopIntegration(true)
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.controller.integrationNotice !== ""
    text: root.controller.integrationNotice
    font.pixelSize: Style.font.bodySmall
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Action {
    text: showDeletion ? "Cancel data deletion" : "Remove local account data…"
    onClicked: root.showDeletion = !root.showDeletion
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.showDeletion
    Label {
      Layout.fillWidth: true
      text: "This removes the selected mode's cached account data, local history, saved sessions, and token. It does not delete your WaniKani account."
      color: Color.urgent
    }
    Controls.CheckBox {
      text: "Also discard unresolved local submissions"
      checked: root.discardPending
      onToggled: root.discardPending = checked
      palette.windowText: Color.foreground
    }
    Ui.TextField {
      id: confirmation
      Layout.fillWidth: true
      placeholderText: "Type DELETE"
      Accessible.name: "Confirm local data deletion"
    }
    Action {
      text: "Delete local data"
      enabled: confirmation.text === "DELETE" && !root.snapshot.syncing
      onClicked: root.controller.call("delete_data", {
        confirmation: confirmation.text,
        discard_pending: root.discardPending
      }, function (ok) {
        if (ok) {
          root.showDeletion = false
          confirmation.text = ""
        }
      })
    }
  }
  Label {
    Layout.fillWidth: true
    text: "WaniKani for Omarchy · 0.1.0\nAn independent community project. WaniKani content belongs to Tofugu. No telemetry, cloud backend, or AI grading."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
}
