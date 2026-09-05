import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  objectName: "wanikani-session-recap"
  required property var controller
  required property var session
  property var report: null
  property bool expanded: false
  property bool loading: false
  property string notice: ""
  property int requestSerial: 0
  property string observedSync: ""
  readonly property string access: controller.contentAccess || ""
  readonly property string sessionId: session ? session.id : ""
  readonly property bool panelOpen: controller.opened
  spacing: Style.space(12)

  function refresh() {
    if (!controller.service || !controller.opened || !session || session.phase !== "complete")
      return
    var serial = ++requestSerial
    loading = true
    controller.service.request("session_report", {
      session_id: session.id
    }, function (ok, data, message) {
      if (!root || root.requestSerial !== serial)
        return
      root.loading = false
      root.report = ok ? data : null
      root.notice = ok ? "" : message || "This batch recap could not be loaded."
    })
  }
  function practice(ids) {
    if (ids.length && !controller.busy)
      controller.begin("practice", ids.length, ids.slice(), true)
  }
  onSessionIdChanged: {
    requestSerial++
    expanded = false
    report = null
    refreshDelay.restart()
  }
  onAccessChanged: {
    requestSerial++
    report = null
    refreshDelay.restart()
  }
  onPanelOpenChanged: {
    if (panelOpen)
      refreshDelay.restart()
    else {
      requestSerial++
      refreshDelay.stop()
    }
  }
  Component.onCompleted: refreshDelay.restart()
  Component.onDestruction: requestSerial++
  Timer {
    id: refreshDelay
    interval: 60
    onTriggered: root.refresh()
  }
  Connections {
    target: root.controller.service
    function onSnapshotChanged() {
      if (!root.controller.opened || !root.session || root.session.phase !== "complete")
        return
      var state = root.controller.snapshot
      var key = JSON.stringify([state.last_sync, state.pending, state.attention, state.outbox_counts])
      if (key !== root.observedSync) {
        root.observedSync = key
        refreshDelay.restart()
      }
    }
  }

  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: root.expanded ? "Hide batch recap" : "Review this batch"
      enabled: !!root.report && !root.loading
      selected: root.expanded
      onClicked: root.expanded = !root.expanded
    }
    Action {
      visible: !!root.report && root.report.mistake_ids.length > 0
      text: root.report ? "Practice items to revisit · " + root.report.mistake_ids.length : "Practice items to revisit"
      enabled: !root.controller.busy
      onClicked: root.practice(root.report.mistake_ids)
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.notice !== ""
    text: root.notice
    textColor: Color.urgent
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.expanded && !!root.report
    spacing: Style.space(10)
    Label {
      Layout.fillWidth: true
      text: "This session only. Mistake counts keep acknowledged answers and exclude your guarded typo corrections."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Repeater {
      model: root.expanded && root.report ? root.report.items : []
      Card {
        required property var modelData
        Layout.fillWidth: true
        implicitHeight: recapRow.implicitHeight + Style.space(24)
        RowLayout {
          id: recapRow
          anchors.fill: parent
          anchors.margins: Style.space(12)
          spacing: Style.space(12)
          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.space(5)
            Label {
              Layout.fillWidth: true
              text: modelData.subject.label + (modelData.subject.meaning ? " · " + modelData.subject.meaning : "")
              font.family: "Noto Sans CJK JP"
              font.pixelSize: Style.font.title
            }
            Label {
              Layout.fillWidth: true
              visible: modelData.subject.spoilers_hidden || !modelData.subject.accessible
              text: !modelData.subject.accessible ? "Subject content is unavailable at your current account access." : "Meaning hidden while this subject has unfinished graded work."
              textColor: Qt.alpha(Color.foreground, 0.7)
              font.pixelSize: Style.font.bodySmall
            }
            Label {
              Layout.fillWidth: true
              text: modelData.done ? (modelData.errors.total ? modelData.errors.meaning + " meaning · " + modelData.errors.reading + " reading mistakes" : "No recorded mistakes") : "The saved session ended before this subject was finished."
              secondary: true
              font.pixelSize: Style.font.bodySmall
            }
            Label {
              Layout.fillWidth: true
              text: modelData.status_label
              textColor: ["uncertain", "conflicted", "blocked", "missing"].indexOf(modelData.state) >= 0 ? Color.urgent : Color.accent
              font.pixelSize: Style.font.bodySmall
            }
          }
          Action {
            text: "Open"
            visible: modelData.done && modelData.subject.accessible && !modelData.subject.spoilers_hidden
            onClicked: root.controller.showSubject(modelData.subject.id)
          }
        }
      }
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        text: "Practice this batch"
        enabled: !!root.report && root.report.practice_ids.length > 0 && !root.controller.busy
        onClicked: root.practice(root.report.practice_ids)
      }
      Action {
        text: "Saved submissions"
        visible: root.report && root.report.mode !== "practice"
        onClicked: root.controller.navigate("recovery")
      }
    }
  }
}
