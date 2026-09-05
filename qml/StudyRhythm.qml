pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui
import "Theme.mjs" as Theme

ColumnLayout {
  id: root
  objectName: "wanikani-study-rhythm"
  required property var controller
  readonly property var service: controller.service
  readonly property var rhythm: service ? service.rhythm || null : null
  readonly property var config: rhythm ? rhythm.config || null : null
  readonly property bool active: visible && controller.opened && service && service.ready && !service.locked && config !== null
  readonly property string contextKey: controller.contentAccess || ""
  property var draft: ({})
  property string timesText: ""
  property bool dirty: false
  property bool saving: false
  property bool previewing: false
  property bool extra: false
  property int serial: 0
  property var draftPreview: null
  property string notice: ""
  readonly property string validationError: validateDraft()
  readonly property var display: dirty ? draftPreview : rhythm
  spacing: Style.space(10)

  function loadDraft(savedConfig) {
    var values = savedConfig || config
    if (!values)
      return
    draft = Object.assign({}, values)
    timesText = Array.isArray(values.times) ? values.times.join(", ") : ""
    dirty = false
    draftPreview = null
    notice = ""
  }
  function change(key, value) {
    if (!active)
      return
    draft = Object.assign({}, draft, {
      [key]: value
    })
    edited()
  }
  function editTimes(value) {
    if (!active)
      return
    timesText = value
    edited()
  }
  function edited() {
    serial++
    dirty = true
    draftPreview = null
    notice = ""
    previewing = false
    settle.restart()
  }
  function validTime(value) {
    return typeof value === "string" && /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value)
  }
  function validateDraft() {
    if (!config)
      return ""
    var times = timesText.split(",").map(function (value) {
      return value.trim()
    })
    if (times.length < 1 || times.length > 12 || !times.every(validTime))
      return "Use one to twelve times, such as 10:00, 14:00, 18:00."
    for (var key of ["window_start", "window_end", "quiet_start", "quiet_end"])
      if (!validTime(draft[key]))
        return "Write hours and minutes as HH:MM, for example 08:00."
    if (draft.window_start >= draft.window_end)
      return "End the daytime window after it starts."
    for (var bound of [["interval_hours", 1, 12], ["daily_limit", 1, 12], ["minimum_interval_seconds", 1800, 86400], ["recent_study_seconds", 0, 7200]])
      if (!Number.isInteger(draft[bound[0]]) || draft[bound[0]] < bound[1] || draft[bound[0]] > bound[2])
        return "Choose a value within the displayed range."
    return ""
  }
  function patch() {
    return Object.assign({}, draft, {
      times: timesText.split(",").map(function (value) {
        return value.trim()
      })
    })
  }
  function previewDraft() {
    if (!active || !dirty || validationError)
      return
    var expected = serial
    var context = contextKey
    previewing = true
    service.previewRhythm(patch(), function (ok, data, message) {
      if (!root || !root.active || expected !== root.serial || context !== root.contextKey)
        return
      root.previewing = false
      if (ok)
        root.draftPreview = data
      else
        root.notice = message || (data && data.message) || "The reminder preview could not be checked."
    })
  }
  function apply() {
    if (!active || saving || !dirty || validationError)
      return
    settle.stop()
    var values = patch()
    var submitted = JSON.stringify(values)
    var context = contextKey
    saving = true
    service.configureRhythm(values, function (ok, data, message) {
      if (!root || context !== root.contextKey)
        return
      root.saving = false
      if (!ok) {
        root.notice = message || (data && data.message) || "The reminder settings were not saved. Your changes are still here."
        return
      }
      if (JSON.stringify(root.patch()) === submitted) {
        root.loadDraft(data && data.config)
        root.notice = "Study rhythm saved."
      } else {
        root.notice = "Saved. Your newer changes still need Apply."
      }
    })
  }
  function pause(patch) {
    if (!active || saving)
      return
    var context = contextKey
    saving = true
    service.configureRhythm(patch, function (ok, data, message) {
      if (!root || context !== root.contextKey)
        return
      root.saving = false
      root.notice = ok ? "Reminder pause updated." : message || (data && data.message) || "The reminder pause could not be saved."
    })
  }
  function deadlineText(value) {
    if (!value)
      return "No timed reminder is scheduled."
    return Qt.formatDateTime(new Date(value * 1000), "ddd d MMM, HH:mm")
  }
  onRhythmChanged: if (!dirty)
    loadDraft()
  onContextKeyChanged: {
    serial++
    dirty = false
    saving = false
    previewing = false
    draftPreview = null
    settle.stop()
    loadDraft()
  }
  onActiveChanged: {
    serial++
    previewing = false
    settle.stop()
    if (active && dirty)
      settle.restart()
  }
  Component.onCompleted: loadDraft()
  Timer {
    id: settle
    interval: 180
    onTriggered: root.previewDraft()
  }

  RowLayout {
    Layout.fillWidth: true
    Label {
      Layout.fillWidth: true
      Layout.minimumWidth: 0
      text: "Study rhythm"
      font.bold: true
    }
    Action {
      text: root.draft.enabled ? "On" : "Off"
      accessibleName: "Study reminders " + text.toLowerCase()
      selected: root.draft.enabled === true
      enabled: root.active
      onClicked: root.change("enabled", !root.draft.enabled)
    }
  }
  Label {
    Layout.fillWidth: true
    text: "Short invitations to review or listen. They never play audio or interrupt study."
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    text: !root.config ? "Loading reminder settings…" : root.display ? root.display.reason || "" : ""
    secondary: true
  }
  ColumnLayout {
    Layout.fillWidth: true
    enabled: root.active
    spacing: Style.space(10)
    Label {
      text: "When"
      font.bold: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: [
          {
            key: "due",
            label: "When due"
          },
          {
            key: "times",
            label: "At times"
          },
          {
            key: "interval",
            label: "At intervals"
          }
        ]
        Action {
          required property var modelData
          text: modelData.label
          selected: root.draft.mode === modelData.key
          Accessible.checkable: true
          Accessible.checked: selected
          onClicked: root.change("mode", modelData.key)
        }
      }
    }
    Label {
      Layout.fillWidth: true
      visible: root.draft.mode === "due"
      text: "An invitation when more reviews become available. Use times or intervals for a regular listening break."
      secondary: true
    }
    ColumnLayout {
      Layout.fillWidth: true
      visible: root.draft.mode === "times"
      Ui.TextField {
        readonly property color surfaceColor: Theme.surface(parent, Color.background)
        readonly property color textColor: Theme.foreground(parent, Color.foreground)
        readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
        foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
        accent: Theme.readable(Color.accent, surfaceColor, foreground)
        color: Theme.readable(foreground, renderedSurface, foreground)
        placeholderTextColor: Theme.secondary(foreground, renderedSurface)
        selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
        objectName: "rhythm-times"
        Layout.fillWidth: true
        text: root.timesText
        placeholderText: "10:00, 14:00, 18:00"
        Accessible.name: "Reminder times, separated by commas"
        maximumLength: 160
        onTextEdited: root.editTimes(text)
        onAccepted: root.apply()
      }
      Label {
        text: "Local times, separated by commas."
        secondary: true
      }
    }
    ColumnLayout {
      Layout.fillWidth: true
      visible: root.draft.mode === "interval"
      spacing: Style.space(8)
      RowLayout {
        Layout.fillWidth: true
        Label {
          Layout.fillWidth: true
          text: "Every (hours)"
        }
        Ui.NumberField {
          id: intervalHours
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          objectName: "rhythm-interval"
          from: 1
          to: 12
          value: root.draft.interval_hours || 2
          fieldWidth: Style.space(90)
          Accessible.name: "Hours between daytime opportunities"
          Component.onCompleted: field.Accessible.name = intervalHours.Accessible.name
          onModified: function (value) {
            root.change("interval_hours", value)
          }
        }
      }
      Label {
        text: "Daytime window"
      }
      RowLayout {
        Layout.fillWidth: true
        Ui.TextField {
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          color: Theme.readable(foreground, renderedSurface, foreground)
          placeholderTextColor: Theme.secondary(foreground, renderedSurface)
          selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
          objectName: "rhythm-window-start"
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: root.draft.window_start || ""
          Accessible.name: "Daytime window starts, HH:MM"
          maximumLength: 5
          onTextEdited: root.change("window_start", text)
        }
        Label {
          text: "to"
        }
        Ui.TextField {
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          color: Theme.readable(foreground, renderedSurface, foreground)
          placeholderTextColor: Theme.secondary(foreground, renderedSurface)
          selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
          objectName: "rhythm-window-end"
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: root.draft.window_end || ""
          Accessible.name: "Daytime window ends, HH:MM"
          maximumLength: 5
          onTextEdited: root.change("window_end", text)
        }
      }
    }
    Label {
      text: "Invite me to"
      font.bold: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: [
          {
            key: "reviews",
            label: "Reviews"
          },
          {
            key: "listening",
            label: "Listening"
          },
          {
            key: "both",
            label: "Both"
          }
        ]
        Action {
          required property var modelData
          text: modelData.label
          selected: root.draft.target === modelData.key
          Accessible.checkable: true
          Accessible.checked: selected
          onClicked: root.change("target", modelData.key)
        }
      }
    }
    Action {
      text: root.extra ? "Hide quiet hours & limits" : "Quiet hours & limits"
      onClicked: root.extra = !root.extra
    }
    ColumnLayout {
      Layout.fillWidth: true
      visible: root.extra
      spacing: Style.space(8)
      Label {
        text: "Quiet hours"
      }
      RowLayout {
        Layout.fillWidth: true
        Ui.TextField {
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          color: Theme.readable(foreground, renderedSurface, foreground)
          placeholderTextColor: Theme.secondary(foreground, renderedSurface)
          selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
          objectName: "rhythm-quiet-start"
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: root.draft.quiet_start || ""
          Accessible.name: "Quiet hours start, HH:MM"
          maximumLength: 5
          onTextEdited: root.change("quiet_start", text)
        }
        Label {
          text: "to"
        }
        Ui.TextField {
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          color: Theme.readable(foreground, renderedSurface, foreground)
          placeholderTextColor: Theme.secondary(foreground, renderedSurface)
          selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
          objectName: "rhythm-quiet-end"
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: root.draft.quiet_end || ""
          Accessible.name: "Quiet hours end, HH:MM"
          maximumLength: 5
          onTextEdited: root.change("quiet_end", text)
        }
      }
      Label {
        Layout.fillWidth: true
        text: "Matching start and end times turn off quiet hours. Do Not Disturb, locking, fullscreen apps, vacation and recent study still keep reminders quiet."
        secondary: true
      }
      RowLayout {
        Layout.fillWidth: true
        Label {
          Layout.fillWidth: true
          text: "Maximum per day"
        }
        Ui.NumberField {
          id: dailyLimit
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          objectName: "rhythm-daily-limit"
          from: 1
          to: 12
          value: root.draft.daily_limit || 3
          fieldWidth: Style.space(90)
          Accessible.name: "Maximum reminders per local day"
          Component.onCompleted: field.Accessible.name = dailyLimit.Accessible.name
          onModified: function (value) {
            root.change("daily_limit", value)
          }
        }
      }
      RowLayout {
        Layout.fillWidth: true
        Label {
          Layout.fillWidth: true
          text: "Minimum gap (minutes)"
        }
        Ui.NumberField {
          id: minimumGap
          readonly property color surfaceColor: Theme.surface(parent, Color.background)
          readonly property color textColor: Theme.foreground(parent, Color.foreground)
          foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
          accent: Theme.readable(Color.accent, surfaceColor, foreground)
          objectName: "rhythm-minimum-gap"
          from: 30
          to: 1440
          stepSize: 30
          value: Math.round((root.draft.minimum_interval_seconds || 7200) / 60)
          fieldWidth: Style.space(90)
          Accessible.name: "Minimum minutes between unsolicited reminders"
          Component.onCompleted: field.Accessible.name = minimumGap.Accessible.name
          onModified: function (value) {
            root.change("minimum_interval_seconds", value * 60)
          }
        }
      }
    }
  }
  Label {
    objectName: "rhythm-next"
    Layout.fillWidth: true
    text: root.dirty && !root.draftPreview ? root.validationError ? "Correct the highlighted setting to preview the next time." : "Checking your proposed schedule…" : (root.dirty ? "Preview · " : "Next opportunity · ") + root.deadlineText(root.display ? root.display.next_at : null)
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.previewing ? "Checking the next time…" : root.display ? root.display.next_reason || "" : ""
    secondary: true
  }
  Label {
    objectName: "rhythm-validation"
    Layout.fillWidth: true
    visible: root.dirty && root.validationError !== ""
    text: visible ? root.validationError : ""
    textColor: Color.urgent
  }
  Label {
    Layout.fillWidth: true
    visible: root.notice !== ""
    text: root.notice
    textColor: Color.accent
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: root.saving ? "Saving…" : "Apply study rhythm"
      enabled: root.active && root.dirty && !root.saving && !root.validationError
      onClicked: root.apply()
    }
    Action {
      text: "Discard changes"
      visible: root.dirty
      enabled: !root.saving
      onClicked: {
        root.serial++
        settle.stop()
        root.loadDraft()
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.dirty
    text: "These changes stay local until you apply them."
    secondary: true
  }
  Flow {
    Layout.fillWidth: true
    visible: root.config && root.config.enabled === true
    spacing: Style.space(8)
    Action {
      text: "Snooze 15 min"
      enabled: root.active && !root.saving
      onClicked: root.pause({
        action: "snooze",
        minutes: 15
      })
    }
    Action {
      text: "Snooze 1 hour"
      enabled: root.active && !root.saving
      onClicked: root.pause({
        action: "snooze",
        minutes: 60
      })
    }
    Action {
      text: "Skip today"
      enabled: root.active && !root.saving
      onClicked: root.pause({
        action: "skip_today"
      })
    }
  }
  Label {
    Layout.fillWidth: true
    text: "Missed invitations expire. Snooze replaces one reminder and still respects quiet hours and your daily limit."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
}
