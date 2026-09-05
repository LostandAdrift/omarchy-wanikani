import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme

ColumnLayout {
  id: root
  objectName: "wanikani-learning-activity"
  required property var controller
  property var report: null
  property int days: 7
  property bool initialized: false
  property bool loading: false
  property bool dirty: true
  property int serial: 0
  property int inFlight: -1
  property string notice: ""
  readonly property var snapshot: controller.snapshot || ({})
  readonly property bool active: visible && controller.opened === true && !!controller.service && controller.service.ready === true && controller.service.locked !== true
  readonly property string contextKey: JSON.stringify([controller.contentAccess || "", snapshot.state_revision, snapshot.session_revision, snapshot.last_sync, snapshot.pending, snapshot.attention])
  readonly property var totals: report ? report.windows[String(days)] : null
  readonly property var rows: report ? report.daily.slice(-days) : []
  readonly property int maximum: Math.max(1, ...rows.map(dayTotal))
  readonly property bool empty: totals && sum(totals.subject_completions) + sum(totals.listening_ratings) === 0
  spacing: Style.space(16)

  function sum(value) {
    return Object.keys(value || {}).reduce(function (total, key) {
      return total + value[key]
    }, 0)
  }
  function dayTotal(value) {
    return sum(value.subject_completions) + sum(value.listening_ratings)
  }
  function dayText(value) {
    var counts = value.subject_completions
    return value.day + ": " + counts.reviews + " reviews, " + counts.lessons + " lessons, " + counts.practice + " practice; " + sum(value.listening_ratings) + " listening ratings."
  }
  function counts(value, keys) {
    return value && keys.every(function (key) {
      return Number.isSafeInteger(value[key]) && value[key] >= 0
    })
  }
  function valid(value) {
    if (!value || value.schema_version !== 1 || value.scope !== "recorded_on_this_device" || !value.windows || !Array.isArray(value.daily) || value.daily.length !== 30)
      return false
    var modes = ["reviews", "lessons", "practice"]
    var periods = [value.windows["7"], value.windows["30"]].concat(value.daily)
    if (!periods.every(function (row) {
      return row && counts(row.subject_completions, modes) && counts(row.sessions_completed, modes) && counts(row.listening_ratings, ["remembered", "again", "skipped"]) && counts(row, ["listening_sessions_completed", "typo_corrections"])
    }))
      return false
    return value.daily.every(function (row) {
      return typeof row.day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(row.day)
    }) && counts(value.current_submissions, ["waiting", "attention", "confirmed", "archived"]) && Array.isArray(value.difficulties) && value.difficulties.length <= 6 && value.difficulties.every(function (row) {
      return row && Number.isSafeInteger(row.id) && row.id > 0 && typeof row.label === "string" && row.label.length <= 160 && counts(row, ["meaning_mistakes", "reading_mistakes"]) && typeof row.can_open === "boolean"
    }) && Array.isArray(value.suggestions) && value.suggestions.length <= 4 && value.suggestions.every(function (row) {
      return row && typeof row.label === "string" && row.label.length <= 160 && typeof row.reason === "string" && row.reason.length <= 400 && row.effect === "navigation_only" && row.route && ["recovery", "review-overview", "lesson-overview", "listen", "practice-library"].indexOf(row.route.view) >= 0
    })
  }
  function invalidate() {
    serial++
    dirty = true
    report = null
    notice = ""
    loading = false
    refreshDelay.stop()
    if (!active)
      inFlight = -1
    if (initialized && active)
      refreshDelay.restart()
  }
  function fetch() {
    if (!initialized || !active || !dirty || inFlight >= 0)
      return
    refreshDelay.stop()
    dirty = false
    loading = true
    var request = serial
    var context = contextKey
    inFlight = request
    controller.service.request("learning_insights", {}, function (ok, data, message) {
      if (root.inFlight !== request)
        return
      root.inFlight = -1
      if (root.active && root.serial === request && root.contextKey === context) {
        root.loading = false
        if (ok && root.valid(data)) {
          root.report = data
          root.notice = ""
        } else {
          root.report = null
          root.notice = ok ? "This activity summary could not be read. Refresh to try again." : message || "Local activity could not be loaded. Try again."
        }
      }
      if (root.active && root.dirty)
        Qt.callLater(root.fetch)
    })
  }
  function focusInput() {
    sevenDays.forceActiveFocus(Qt.TabFocusReason)
  }
  function openSuggestion(value) {
    if (!active || !report || !value || !value.route)
      return
    var current = report.suggestions.find(function (row) {
      return row.code === value.code && row.route.view === value.route.view
    })
    if (current)
      controller.navigate(current.route.view)
  }
  function openDifficulty(value) {
    if (!active || !report || !value)
      return
    var current = report.difficulties.find(function (row) {
      return row.id === value.id
    })
    if (current && current.can_open)
      controller.showSubject(current.id)
  }
  function suggestionAction(value) {
    return {
      "recovery": "Check submissions",
      "review-overview": "Open reviews",
      "lesson-overview": "Open lessons",
      "listen": "Open listening",
      "practice-library": "Open practice"
    }[value.route.view]
  }
  onActiveChanged: invalidate()
  onContextKeyChanged: invalidate()
  Component.onCompleted: {
    initialized = true
    invalidate()
  }
  Timer {
    id: refreshDelay
    interval: 150
    onTriggered: root.fetch()
  }

  Label {
    Layout.fillWidth: true
    text: "YOUR LOCAL LEARNING"
    secondary: true
    font.pixelSize: Style.font.bodySmall
    font.letterSpacing: 1.5
  }
  Label {
    Layout.fillWidth: true
    text: "Small sessions add up."
    font.pixelSize: Style.space(28)
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Recorded on this device. Reviews, lessons and listening on other devices are not included."
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      id: sevenDays
      text: "7 days"
      selected: root.days === 7
      onClicked: root.days = 7
    }
    Action {
      text: "30 days"
      selected: root.days === 30
      onClicked: root.days = 30
    }
    Action {
      text: root.loading ? "Loading…" : "Refresh activity"
      enabled: root.active && root.inFlight < 0
      onClicked: root.invalidate()
    }
  }
  Label {
    objectName: "activityNotice"
    Layout.fillWidth: true
    visible: root.loading || root.notice.length > 0
    text: root.loading ? "Reading your saved local activity…" : root.notice
    textColor: root.notice ? Color.urgent : Color.foreground
  }
  Label {
    objectName: "activityEmpty"
    Layout.fillWidth: true
    visible: !!root.empty
    text: "No completed study is recorded here in this period. Your next finished subject or listening rating will appear here."
    secondary: true
  }
  GridLayout {
    Layout.fillWidth: true
    visible: !!root.totals
    columns: root.width < Style.space(600) ? 2 : 4
    columnSpacing: Style.space(10)
    rowSpacing: Style.space(10)
    Repeater {
      model: root.totals ? [
        {
          label: "Reviews",
          count: root.totals.subject_completions.reviews,
          description: root.totals.sessions_completed.reviews + " batches completed"
        },
        {
          label: "Lessons",
          count: root.totals.subject_completions.lessons,
          description: root.totals.sessions_completed.lessons + " batches completed"
        },
        {
          label: "Ungraded practice",
          count: root.totals.subject_completions.practice,
          description: root.totals.sessions_completed.practice + " batches completed"
        },
        {
          label: "Listening ratings",
          count: root.sum(root.totals.listening_ratings),
          description: root.totals.listening_sessions_completed + " listening batches completed"
        }
      ] : []
      Card {
        required property var modelData
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        implicitHeight: metric.implicitHeight + Style.space(28)
        ColumnLayout {
          id: metric
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(14)
          Label {
            Layout.fillWidth: true
            text: modelData.label
            font.bold: true
          }
          Label {
            Layout.fillWidth: true
            text: String(modelData.count)
            font.pixelSize: Style.space(32)
            font.bold: true
          }
          Label {
            Layout.fillWidth: true
            text: modelData.description
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.totals
    text: root.totals ? "Listening: " + root.totals.listening_ratings.remembered + " remembered · " + root.totals.listening_ratings.again + " again · " + root.totals.listening_ratings.skipped + " skipped. Undone ratings are excluded." : ""
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.totals
    text: root.totals ? root.totals.typo_corrections + " local typo corrections. Subjects count after their final feedback is acknowledged; each repeated study cycle counts separately." : ""
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Card {
    Layout.fillWidth: true
    visible: !!root.report
    implicitHeight: current.implicitHeight + Style.space(32)
    ColumnLayout {
      id: current
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(16)
      Label {
        Layout.fillWidth: true
        text: "Saved submissions · current status"
        font.bold: true
      }
      Label {
        objectName: "activitySubmissions"
        Layout.fillWidth: true
        text: root.report ? root.report.current_submissions.waiting + " waiting to sync · " + root.report.current_submissions.attention + " need attention · " + root.report.current_submissions.confirmed + (root.report.demo ? " confirmed in demo" : " confirmed by WaniKani") : ""
      }
      Label {
        Layout.fillWidth: true
        text: "These are current submission states, not confirmation dates in the selected period."
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
      Action {
        text: "View saved submissions"
        enabled: root.active
        onClicked: root.controller.navigate("recovery")
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.report
    text: "Day by day"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.report
    text: "Completed subjects and listening ratings. Days follow your local timezone."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Repeater {
    model: root.rows
    ColumnLayout {
      required property var modelData
      objectName: "activityDay"
      Layout.fillWidth: true
      spacing: Style.space(4)
      Label {
        Layout.fillWidth: true
        text: root.dayText(modelData)
        font.pixelSize: Style.font.bodySmall
      }
      Rectangle {
        Layout.fillWidth: true
        implicitHeight: Style.space(5)
        radius: height / 2
        color: Theme.tint(Theme.foreground(parent, Color.foreground), Theme.surface(parent, Color.background), 0.10)
        Accessible.ignored: true
        Rectangle {
          width: parent.width * root.dayTotal(modelData) / root.maximum
          height: parent.height
          radius: height / 2
          color: Theme.indicator(Color.accent, Theme.surface(parent, Color.background), Color.foreground)
          Accessible.ignored: true
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.report && root.report.difficulties.length > 0
    text: "Worth another look"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Repeater {
    model: root.report ? root.report.difficulties : []
    ColumnLayout {
      required property var modelData
      Layout.fillWidth: true
      Label {
        Layout.fillWidth: true
        text: modelData.label + " · " + modelData.meaning_mistakes + " meaning, " + modelData.reading_mistakes + " reading mistakes"
      }
      Action {
        text: "Open subject"
        accessibleName: "Open " + modelData.label
        enabled: root.active && modelData.can_open
        onClicked: root.openDifficulty(modelData)
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.report && root.report.difficulties.length > 0
    text: "From final mistakes in completed local study over 30 days. Subjects in paused graded study stay hidden."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Repeater {
    model: root.report ? root.report.suggestions : []
    ColumnLayout {
      required property var modelData
      Layout.fillWidth: true
      Label {
        Layout.fillWidth: true
        text: modelData.label
        font.bold: true
      }
      Action {
        text: root.suggestionAction(modelData)
        enabled: root.active
        onClicked: root.openSuggestion(modelData)
      }
      Label {
        Layout.fillWidth: true
        text: modelData.reason
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.report
    text: "Earlier local work stays in this history after an account reset. It does not describe your current WaniKani level or progress."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
}
