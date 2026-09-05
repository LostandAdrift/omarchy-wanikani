import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  property string stateFilter: "open"
  property string kindFilter: "all"
  property bool loading: false
  property string notice: ""
  property string confirmId: ""
  property int requestSerial: 0
  readonly property string contentAccess: controller.contentAccess || ""
  onContentAccessChanged: {
    requestSerial++
    confirmId = ""
    page = Object.assign({}, page, {
      items: [],
      total: 0
    })
    refreshDelay.restart()
  }
  property var page: ({
      items: [],
      total: 0,
      offset: 0,
      limit: 15,
      has_more: false,
      counts: {},
      open_total: 0,
      attention: 0,
      pending: 0
    })
  spacing: Style.space(14)

  function focusInput() {
    refreshButton.forceActiveFocus(Qt.TabFocusReason)
  }
  function loadPage(offset) {
    if (!controller.service)
      return
    var serial = ++requestSerial
    loading = true
    controller.service.request("recovery", {
      state: stateFilter,
      kind: kindFilter,
      offset: offset || 0,
      limit: 15
    }, function (ok, data, message) {
      if (!root || serial !== root.requestSerial)
        return
      root.loading = false
      if (ok) {
        root.page = data
        root.notice = ""
      } else
        root.notice = message || "Saved submissions could not be loaded. Try again."
    })
  }
  function chooseState(value) {
    stateFilter = value
    confirmId = ""
    loadPage(0)
  }
  function refreshRemote() {
    confirmId = ""
    controller.call("sync", {}, function (ok) {
      if (ok)
        root.loadPage(root.page.offset)
    })
  }
  function archive(id) {
    controller.call("resolve", {
      id: id,
      action: "keep_remote"
    }, function (ok) {
      if (ok) {
        root.confirmId = ""
        root.loadPage(0)
      }
    })
  }
  function stateLabel(value) {
    return ({
        pending: "Waiting to send",
        inflight: "Sending",
        uncertain: "Response uncertain",
        conflicted: "Remote progress changed",
        blocked: "Needs attention",
        confirmed: "Confirmed",
        discarded: "Archived"
      })[value] || value
  }
  function createdLabel(value) {
    var date = new Date(value)
    return isNaN(date.getTime()) ? "Time unavailable" : Qt.formatDateTime(date, "MMM d, yyyy · h:mm AP")
  }
  Component.onCompleted: loadPage(0)
  Component.onDestruction: requestSerial++
  Connections {
    target: root.controller.service
    function onSnapshotChanged() {
      refreshDelay.restart()
    }
  }
  Timer {
    id: refreshDelay
    interval: 250
    onTriggered: root.loadPage(root.page.offset)
  }

  Label {
    Layout.fillWidth: true
    text: "Saved submissions"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Your local answers stay saved while WaniKani confirms progress. An uncertain response is checked against your account before any recovery action."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      Layout.fillWidth: true
      text: root.page.pending + " pending · " + root.page.attention + " need attention"
      color: root.page.attention ? Color.urgent : Color.accent
    }
    Action {
      id: refreshButton
      text: root.controller.snapshot.syncing ? "Refreshing…" : "Refresh remote progress"
      enabled: !root.controller.snapshot.syncing && !root.controller.busy
      onClicked: root.refreshRemote()
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    Repeater {
      model: [
        {
          key: "open",
          label: "Open"
        },
        {
          key: "attention",
          label: "Needs attention"
        },
        {
          key: "pending",
          label: "Waiting"
        },
        {
          key: "confirmed",
          label: "Confirmed"
        },
        {
          key: "discarded",
          label: "Archived"
        }
      ]
      Action {
        required property var modelData
        text: modelData.label + " · " + (modelData.key === "open" ? root.page.open_total : modelData.key === "attention" ? root.page.attention : root.page.counts[modelData.key] || 0)
        selected: root.stateFilter === modelData.key
        onClicked: root.chooseState(modelData.key)
      }
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    Repeater {
      model: [
        {
          key: "all",
          label: "All work"
        },
        {
          key: "review",
          label: "Reviews"
        },
        {
          key: "lesson",
          label: "Lessons"
        },
        {
          key: "material",
          label: "Notes & synonyms"
        }
      ]
      Action {
        required property var modelData
        text: modelData.label
        selected: root.kindFilter === modelData.key
        onClicked: {
          root.kindFilter = modelData.key
          root.confirmId = ""
          root.loadPage(0)
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: "This history records submissions made by this plugin. It is not your account’s complete review history."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.notice !== ""
    text: root.notice
    color: Color.urgent
  }
  Label {
    Layout.fillWidth: true
    visible: root.page.items.length === 0
    text: root.loading ? "Loading saved submissions…" : "No submissions in this view."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Repeater {
    model: root.page.items
    Card {
      id: itemCard
      required property var modelData
      Layout.fillWidth: true
      Layout.preferredHeight: entry.implicitHeight + Style.space(24)
      ColumnLayout {
        id: entry
        anchors.fill: parent
        anchors.margins: Style.space(12)
        spacing: Style.space(8)
        RowLayout {
          Layout.fillWidth: true
          Label {
            visible: !!itemCard.modelData.subject.characters
            text: itemCard.modelData.subject.characters
            font.family: "Noto Sans CJK JP"
            font.pixelSize: Style.space(30)
            Layout.maximumWidth: Style.space(170)
          }
          ColumnLayout {
            Layout.fillWidth: true
            Label {
              Layout.fillWidth: true
              text: itemCard.modelData.subject.meaning || itemCard.modelData.subject.label
              font.bold: true
            }
            Label {
              Layout.fillWidth: true
              text: itemCard.modelData.kind + " · " + root.stateLabel(itemCard.modelData.state)
              color: ["uncertain", "conflicted", "blocked"].indexOf(itemCard.modelData.state) >= 0 ? Color.urgent : Color.accent
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
        Label {
          Layout.fillWidth: true
          text: "Saved " + root.createdLabel(itemCard.modelData.created_at) + (itemCard.modelData.errors ? " · Errors: " + itemCard.modelData.errors.meaning + " meaning, " + itemCard.modelData.errors.reading + " reading" : "")
          color: Qt.alpha(Color.foreground, 0.76)
          font.pixelSize: Style.font.bodySmall
        }
        Label {
          Layout.fillWidth: true
          text: itemCard.modelData.detail
          visible: text !== ""
        }
        Label {
          Layout.fillWidth: true
          text: itemCard.modelData.rationale
          color: Qt.alpha(Color.foreground, 0.76)
          font.pixelSize: Style.font.bodySmall
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(6)
          Repeater {
            model: itemCard.modelData.actions
            Action {
              required property var modelData
              text: modelData.label
              accessibleHint: modelData.description
              enabled: !root.controller.snapshot.syncing && !root.controller.busy
              onClicked: {
                if (modelData.id === "refresh")
                  root.refreshRemote()
                else if (modelData.id === "keep_remote")
                  root.confirmId = itemCard.modelData.id
              }
            }
          }
        }
        Label {
          Layout.fillWidth: true
          visible: root.confirmId === itemCard.modelData.id
          text: "Archive this local submission and keep WaniKani’s progress? Your session and answers remain in local history. This submission will not be sent again."
          color: Color.urgent
        }
        Flow {
          Layout.fillWidth: true
          visible: root.confirmId === itemCard.modelData.id
          spacing: Style.space(6)
          Action {
            text: "Keep remote & archive"
            enabled: !root.controller.busy && !root.controller.snapshot.syncing
            onClicked: root.archive(itemCard.modelData.id)
          }
          Action {
            text: "Cancel"
            onClicked: root.confirmId = ""
          }
        }
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      Layout.fillWidth: true
      text: root.page.total ? (root.page.offset + 1) + "–" + Math.min(root.page.offset + root.page.items.length, root.page.total) + " of " + root.page.total : "0 submissions"
      color: Qt.alpha(Color.foreground, 0.76)
      font.pixelSize: Style.font.bodySmall
    }
    Action {
      text: "Previous"
      enabled: !root.loading && root.page.offset > 0
      onClicked: root.loadPage(Math.max(0, root.page.offset - root.page.limit))
    }
    Action {
      text: "Next"
      enabled: !root.loading && root.page.has_more
      onClicked: root.loadPage(root.page.next_offset)
    }
  }
}
