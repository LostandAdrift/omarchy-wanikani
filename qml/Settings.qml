import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Quickshell
import qs.Commons
import "Theme.mjs" as Theme
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
    secondary: true
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
      readonly property color surfaceColor: Theme.surface(parent, Color.background)
      readonly property color textColor: Theme.foreground(parent, Color.foreground)
      readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
      foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
      accent: Theme.readable(Color.accent, surfaceColor, foreground)
      color: Theme.readable(foreground, renderedSurface, foreground)
      placeholderTextColor: Theme.secondary(foreground, renderedSurface)
      selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
      objectName: "settings-token"
      Layout.fillWidth: true
      password: true
      placeholderText: "Paste your personal API token"
      Accessible.name: "WaniKani API token"
    }
    Controls.CheckBox {
      text: "Remember securely in the desktop keyring"
      checked: root.remember
      onToggled: root.remember = checked
      palette.windowText: Theme.readable(Theme.foreground(parent, Color.foreground), Theme.surface(parent, Color.background), Color.foreground)
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
        text: !root.snapshot.connected && root.snapshot.credential_cleanup_needed ? "Retry token removal" : "Disconnect"
        enabled: (root.snapshot.connected || root.snapshot.credential_cleanup_needed) && !root.snapshot.syncing && !root.controller.busy
        onClicked: root.controller.call("disconnect", {}, function (ok) {
          if (ok)
            root.notice = "Disconnected."
        })
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: notice !== ""
    text: notice
    textColor: Color.accent
  }
  Label {
    Layout.fillWidth: true
    visible: root.snapshot.credential_cleanup_needed === true && root.notice === ""
    text: "An older saved token still needs removal. Unlock the keyring, then use Disconnect or Retry token removal."
    textColor: Color.urgent
  }
  Label {
    text: "Study & atmosphere"
    font.bold: true
  }
  Repeater {
    model: [
      {
        key: "strict_meanings",
        label: "Require exact meanings"
      },
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
        label: "Autoplay pronunciation after review readings"
      },
      {
        key: "autoplay_lessons",
        label: "Autoplay pronunciation while learning lessons"
      },
      {
        key: "autoplay_listening",
        label: "Autoplay new listening prompts"
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
        accessibleName: modelData.label
        Accessible.checkable: true
        Accessible.checked: selected
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
    text: "Listening autoplay follows an explicit Start or rating action in local practice. Resuming a saved session, reopening the panel, and background updates stay silent."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    text: "Exact meanings keeps accepted variants and your saved synonyms, and turns off automatic spelling tolerance. Reading answers always require exact kana after normalization."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    text: "Ambient subjects are learned and not due in the next 24 hours. Idle views yield to your existing screensaver and lock. Reminders respect Do Not Disturb, quiet hours, vacation, and study sessions."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Batch size"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      id: batchSizeField
      readonly property color surfaceColor: Theme.surface(parent, Color.background)
      readonly property color textColor: Theme.foreground(parent, Color.foreground)
      foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
      accent: Theme.readable(Color.accent, surfaceColor, foreground)
      objectName: "settings-batch-size"
      Accessible.name: "Subjects in each study batch"
      Component.onCompleted: field.Accessible.name = batchSizeField.Accessible.name
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
  StudyRhythm {
    Layout.fillWidth: true
    controller: root.controller
  }
  VoiceChoices {
    Layout.fillWidth: true
    controller: root.controller
  }
  Label {
    text: "Offline storage"
    font.bold: true
  }
  OfflineStatus {
    Layout.fillWidth: true
    controller: root.controller
  }
  Label {
    Layout.fillWidth: true
    text: root.snapshot.cache ? (root.snapshot.cache.subjects || 0) + " subjects available offline · " + root.snapshot.cache.files + " media files · " + (root.snapshot.cache.bytes / 1048576).toFixed(1) + " MB. Answers and sessions are saved separately." : "No cached media"
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Media cache limit (MB)"
      Layout.fillWidth: true
    }
    Ui.NumberField {
      id: cacheLimitField
      readonly property color surfaceColor: Theme.surface(parent, Color.background)
      readonly property color textColor: Theme.foreground(parent, Color.foreground)
      foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
      accent: Theme.readable(Color.accent, surfaceColor, foreground)
      objectName: "settings-cache-limit"
      Accessible.name: "Media cache limit in megabytes"
      Component.onCompleted: field.Accessible.name = cacheLimitField.Accessible.name
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
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Action {
    text: "Open saved submissions · " + (root.snapshot.outbox_total || 0) + " open"
    onClicked: root.controller.navigate("recovery")
  }
  Label {
    Layout.fillWidth: true
    text: "Super+Alt+W opens study; Super+Alt+Shift+W looks up selected text. Add the available shortcuts and Study/Lookup launcher entries here. Existing bindings are preserved."
    secondary: true
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
    secondary: true
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
      textColor: Color.urgent
    }
    Controls.CheckBox {
      text: "Also discard unresolved local submissions"
      checked: root.discardPending
      onToggled: root.discardPending = checked
      palette.windowText: Theme.readable(Theme.foreground(parent, Color.foreground), Theme.surface(parent, Color.background), Color.foreground)
    }
    Ui.TextField {
      id: confirmation
      readonly property color surfaceColor: Theme.surface(parent, Color.background)
      readonly property color textColor: Theme.foreground(parent, Color.foreground)
      readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
      foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
      accent: Theme.readable(Color.accent, surfaceColor, foreground)
      color: Theme.readable(foreground, renderedSurface, foreground)
      placeholderTextColor: Theme.secondary(foreground, renderedSurface)
      selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
      objectName: "settings-delete-confirmation"
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
      }, function (ok, data) {
        if (ok) {
          root.showDeletion = false
          confirmation.text = ""
          root.notice = data.credential_cleanup_needed ? (data.warning || "Local data was deleted. A saved token may remain in the keyring; remove the WaniKani for Omarchy credential after unlocking it.") : "Local data deleted."
        }
      })
    }
  }
  Label {
    Layout.fillWidth: true
    text: "WaniKani for Omarchy · 0.2.2\nAn independent community project. WaniKani content belongs to Tofugu. No telemetry, cloud backend, or AI grading."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
}
