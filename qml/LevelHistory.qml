import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme

ColumnLayout {
  id: root
  required property var controller
  property var report: null
  property int offset: 0
  readonly property int pageSize: 12
  property var expandedId: -1
  property int serial: 0
  property int inFlight: -1
  property bool initialized: false
  property bool dirty: true
  property bool loading: false
  property string error: ""
  readonly property bool active: visible && controller.opened && controller.service && controller.service.ready && !controller.service.locked
  readonly property string contextKey: JSON.stringify([controller.contentAccess, controller.snapshot.last_sync, controller.snapshot.session_epoch, controller.snapshot.level, controller.snapshot.vacation])
  readonly property var items: report ? report.items : []
  readonly property real longest: Math.max(1, ...items.map(function (row) {
    return row.elapsed_seconds || 0
  }))
  spacing: Style.space(12)

  function focusInput() {
    historyRefresh.forceActiveFocus(Qt.TabFocusReason)
  }
  function invalidate(resetPage) {
    serial++
    report = null
    error = ""
    expandedId = -1
    dirty = true
    loading = false
    if (resetPage)
      offset = 0
    if (active && initialized)
      Qt.callLater(fetch)
  }
  function valid(data, start) {
    return data && typeof data === "object" && (data.source === "WaniKani level progressions" || (controller.snapshot.demo === true && data.source === "Authored demo level progressions")) && ["available", "empty", "unavailable"].indexOf(data.status) >= 0 && data.offset === start && data.limit === pageSize && ((Number.isSafeInteger(data.total) && data.total >= 0) || (data.status === "unavailable" && data.total === null)) && typeof data.has_more === "boolean" && (data.next_offset === null || (Number.isSafeInteger(data.next_offset) && data.next_offset > start)) && typeof data.cache_complete === "boolean" && data.history_complete === false && typeof data.partial === "boolean" && typeof data.truncated === "boolean" && typeof data.message === "string" && Array.isArray(data.items) && data.items.length <= pageSize && (data.status !== "unavailable" || (data.items.length === 0 && !data.has_more && data.next_offset === null)) && data.items.every(function (row) {
      return row && Number.isSafeInteger(row.id) && row.id > 0 && Number.isInteger(row.level) && row.level >= 1 && row.level <= 60 && typeof row.attempt_label === "string" && typeof row.label === "string" && (row.elapsed_seconds === null || (typeof row.elapsed_seconds === "number" && isFinite(row.elapsed_seconds) && row.elapsed_seconds >= 0)) && [null, "passed", "abandoned", "now"].indexOf(row.elapsed_to) >= 0
    })
  }
  function fetch() {
    if (!active || !initialized || !dirty || inFlight >= 0)
      return
    var expected = serial
    var key = contextKey
    var start = offset
    dirty = false
    loading = true
    error = ""
    inFlight = expected
    controller.service.request("level_history", {
      offset: start,
      limit: pageSize
    }, function (ok, data, message) {
      if (!root)
        return
      if (root.inFlight === expected)
        root.inFlight = -1
      if (root.active && root.serial === expected && root.contextKey === key) {
        root.loading = false
        if (ok && root.valid(data, start))
          root.report = data
        else
          root.error = message || "Level history could not be read. Try again."
      }
      if (root.dirty && root.active)
        Qt.callLater(root.fetch)
    })
  }
  function changePage(start) {
    if (!active || loading || !Number.isSafeInteger(start) || start < 0 || start > 1000)
      return
    offset = start
    invalidate(false)
  }
  function duration(row) {
    if (row.elapsed_seconds === null || row.elapsed_to === null)
      return "Duration unavailable"
    var hours = Math.floor(row.elapsed_seconds / 3600)
    var days = Math.floor(hours / 24)
    var value = days ? days + (days === 1 ? " day" : " days") + (hours % 24 ? " " + hours % 24 + "h" : "") : hours ? hours + (hours === 1 ? " hour" : " hours") : "Less than an hour"
    return value + (row.elapsed_to === "passed" ? " to passing" : row.elapsed_to === "abandoned" ? " before this visit ended" : " so far")
  }
  function dateText(value) {
    var date = typeof value === "string" ? new Date(value) : null
    return date && !isNaN(date.getTime()) ? Qt.formatDateTime(date, "d MMM yyyy, HH:mm") : "Not recorded"
  }
  function dates(row) {
    return [
      {
        label: "Level unlocked",
        value: row.unlocked_at
      },
      {
        label: "First lesson started",
        value: row.started_at
      },
      {
        label: "Kanji passing target reached",
        value: row.passed_at
      },
      {
        label: "All subjects burned",
        value: row.completed_at
      },
      {
        label: "Visit ended",
        value: row.abandoned_at
      }
    ]
  }
  onActiveChanged: invalidate(false)
  onContextKeyChanged: invalidate(true)
  Connections {
    target: root.controller.service
    function onReadyChanged() {
      if (!root.controller.service.ready) {
        root.inFlight = -1
        root.invalidate(false)
      }
    }
  }
  Component.onCompleted: {
    initialized = true
    Qt.callLater(fetch)
  }

  Label {
    Layout.fillWidth: true
    text: root.controller.snapshot.demo === true ? "Demo level history" : "Your path through the levels"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.controller.snapshot.demo === true ? "Independently authored demo records illustrate account milestones and separate visits after a reset." : "Account milestones from WaniKani, including separate recorded visits after a reset. Older account history may be missing."
    secondary: true
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      id: historyRefresh
      objectName: "history-refresh"
      text: root.loading ? "Reading history…" : root.error ? "Retry history" : "Refresh history"
      enabled: root.active && !root.loading
      onClicked: root.invalidate(false)
    }
    Action {
      objectName: "history-newer"
      text: "← Newer visits"
      enabled: root.active && !root.loading && root.offset > 0
      onClicked: root.changePage(Math.max(0, root.offset - root.pageSize))
    }
    Action {
      objectName: "history-older"
      text: "Older visits →"
      enabled: root.active && !root.loading && root.report && root.report.has_more
      onClicked: root.changePage(root.report.next_offset)
    }
  }
  Label {
    Layout.fillWidth: true
    visible: text !== ""
    text: root.error || (root.report ? root.report.message : "")
    textColor: root.error ? Color.urgent : Color.foreground
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.items.length > 0
    text: "Elapsed calendar time includes breaks and vacation. Bars scale to the longest recorded visit on this page."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Repeater {
    model: root.items
    Card {
      id: visit
      required property var modelData
      Layout.fillWidth: true
      implicitHeight: body.implicitHeight + Style.space(28)
      ColumnLayout {
        id: body
        anchors.fill: parent
        anchors.margins: Style.space(14)
        spacing: Style.space(8)
        Label {
          Layout.fillWidth: true
          text: "Level " + visit.modelData.level + " · " + visit.modelData.attempt_label
          font.bold: true
        }
        Label {
          Layout.fillWidth: true
          text: visit.modelData.label
          textColor: Color.accent
        }
        Label {
          objectName: "history-duration-" + visit.modelData.id
          Layout.fillWidth: true
          text: root.duration(visit.modelData)
          font.pixelSize: Style.font.bodySmall
        }
        Label {
          Layout.fillWidth: true
          visible: text !== ""
          text: visit.modelData.date_notice || ""
          font.pixelSize: Style.font.bodySmall
          secondary: true
        }
        Rectangle {
          objectName: "history-duration-meter-" + visit.modelData.id
          Layout.fillWidth: true
          implicitHeight: Style.space(6)
          radius: height / 2
          visible: visit.modelData.elapsed_seconds !== null && visit.modelData.elapsed_to !== null
          color: Theme.tint(visit.textColor, visit.color, 0.12)
          Accessible.ignored: true
          Rectangle {
            height: parent.height
            width: parent.width * Math.min(1, visit.modelData.elapsed_seconds / root.longest)
            radius: parent.radius
            color: Theme.indicator(Color.accent, parent.color, Color.foreground)
          }
        }
        Action {
          objectName: "history-dates-" + visit.modelData.id
          text: root.expandedId === visit.modelData.id ? "Hide dates" : "Show dates"
          accessibleName: text + " for level " + visit.modelData.level + ", " + visit.modelData.attempt_label
          onClicked: root.expandedId = root.expandedId === visit.modelData.id ? -1 : visit.modelData.id
        }
        Repeater {
          model: root.expandedId === visit.modelData.id ? root.dates(visit.modelData) : []
          ColumnLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: Style.space(2)
            Label {
              Layout.fillWidth: true
              text: parent.modelData.label
              secondary: true
              font.pixelSize: Style.font.bodySmall
            }
            Label {
              Layout.fillWidth: true
              text: root.dateText(parent.modelData.value)
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.report && root.items.length > 0
    text: root.report ? "Recorded visits " + (root.offset + 1) + "–" + (root.offset + root.items.length) + " of " + root.report.total + (root.report.truncated ? " in this cached window" : " cached") : ""
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
}
