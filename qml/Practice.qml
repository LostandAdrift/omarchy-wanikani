import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui

ColumnLayout {
  id: root
  required property var controller
  property string group: "suggested"
  property var selectedIds: []
  property bool loading: false
  property bool initialized: false
  property string notice: ""
  property int requestSerial: 0
  property int requestedOffset: 0
  property string observedSync: ""
  readonly property string contentAccess: controller.contentAccess || ""
  onContentAccessChanged: {
    requestSerial++
    selectedIds = []
    library = Object.assign({}, library, {
      items: [],
      counts: {},
      ready_counts: {},
      total: 0,
      ready_total: 0
    })
    if (initialized)
      loadPage(0)
  }
  property var library: ({
      items: [],
      counts: {},
      ready_counts: {},
      offset: 0,
      limit: 30,
      total: 0,
      ready_total: 0,
      selection_limit: 20,
      mistake_days: 14,
      has_more: false,
      saved_practice: null
    })
  readonly property int selectionLimit: library.selection_limit || 20
  spacing: Style.space(14)

  function focusInput() {
    searchField.forceActiveFocus()
  }
  function loadPage(offset) {
    if (!controller.service)
      return
    requestedOffset = offset || 0
    requestSerial++
    loading = true
    notice = ""
    // Construction, access and sync changes can request the same page in one
    // event-loop turn. Keep only their latest request before reading SQLite.
    Qt.callLater(fetchPage)
  }
  function fetchPage() {
    if (!controller.service)
      return
    var serial = requestSerial
    controller.service.request("practice_catalogue", {
      group: group,
      query: searchField.text,
      offset: requestedOffset,
      limit: 30,
      readiness_scope: "page"
    }, function (ok, data, message) {
      if (!root || serial !== root.requestSerial)
        return
      root.loading = false
      if (ok)
        root.library = data
      else
        root.notice = message || "The practice library could not be loaded. Refresh and try again."
    })
  }
  function chooseGroup(value) {
    group = value
    loadPage(0)
  }
  function toggleSubject(item) {
    var next = selectedIds.slice()
    var index = next.indexOf(item.id)
    if (index >= 0)
      next.splice(index, 1)
    else if (item.ready && next.length < selectionLimit)
      next.push(item.id)
    selectedIds = next
  }
  function selectFive() {
    var next = selectedIds.slice()
    var target = Math.min(selectionLimit, next.length + 5)
    for (var i = 0; i < library.items.length && next.length < target; i++) {
      var item = library.items[i]
      if (item.ready && next.indexOf(item.id) < 0)
        next.push(item.id)
    }
    selectedIds = next
  }
  function startSelected() {
    if (!selectedIds.length || selectedIds.length > selectionLimit || controller.busy)
      return
    // The fourth argument explicitly starts this selection. The default
    // practice action continues to resume an unfinished practice session.
    controller.begin("practice", selectedIds.length, selectedIds.slice(), true)
  }
  Component.onCompleted: {
    initialized = true
    observedSync = String(controller.snapshot.last_sync || "")
    loadPage(0)
  }
  Component.onDestruction: requestSerial++
  Connections {
    target: root.controller.service
    function onSnapshotChanged() {
      var refreshed = String(root.controller.snapshot.last_sync || "")
      if (refreshed !== root.observedSync) {
        root.observedSync = refreshed
        root.loadPage(root.library.offset)
      }
    }
  }

  Label {
    Layout.fillWidth: true
    text: "Your practice library"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Choose up to " + root.selectionLimit + " subjects for ungraded practice. Your WaniKani review schedule stays as it is."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Card {
    Layout.fillWidth: true
    Layout.preferredHeight: savedPracticeRow.implicitHeight + Style.space(24)
    visible: root.library.saved_practice !== null
    RowLayout {
      id: savedPracticeRow
      anchors.fill: parent
      anchors.margins: Style.space(12)
      ColumnLayout {
        Layout.fillWidth: true
        Label {
          Layout.fillWidth: true
          text: "Your earlier practice is saved"
          font.bold: true
        }
        Label {
          Layout.fillWidth: true
          text: root.library.saved_practice ? root.library.saved_practice.completed + " / " + root.library.saved_practice.total + " subjects completed" : ""
          color: Qt.alpha(Color.foreground, 0.76)
          font.pixelSize: Style.font.bodySmall
        }
      }
      Action {
        text: "Resume practice"
        enabled: !root.controller.busy
        onClicked: root.controller.begin("practice")
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.library.graded_paused === true
    text: "Your graded session is saved. Meanings stay hidden here for its unfinished subjects."
    color: Color.accent
    font.pixelSize: Style.font.bodySmall
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    Repeater {
      model: [
        {
          key: "suggested",
          label: "Suggested"
        },
        {
          key: "saved",
          label: "Saved"
        },
        {
          key: "mistakes",
          label: "Recent mistakes"
        },
        {
          key: "learned",
          label: "Learned"
        }
      ]
      Action {
        required property var modelData
        text: modelData.label + " · " + (root.library.counts[modelData.key] || 0)
        selected: root.group === modelData.key
        accessibleName: modelData.label + ", " + (root.library.counts[modelData.key] || 0) + " subjects"
        onClicked: root.chooseGroup(modelData.key)
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.group === "mistakes" ? "Mistakes recorded by this plugin in the last " + root.library.mistake_days + " days. Typo corrections are excluded." : root.group === "saved" ? "Subjects you chose to keep in difficult items from lookup." : root.group === "learned" ? "Subjects you have started, including completed lessons waiting to sync." : "Saved subjects, recent local mistakes, and subjects with WaniKani recorded accuracy below 90%."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Ui.TextField {
      id: searchField
      Layout.fillWidth: true
      placeholderText: "Characters, reading, or meaning…"
      Accessible.name: "Search the practice library"
      onTextEdited: searchDelay.restart()
      onAccepted: {
        searchDelay.stop()
        root.loadPage(0)
      }
    }
    Action {
      text: "Refresh"
      enabled: !root.loading
      onClicked: root.loadPage(root.library.offset)
    }
  }
  Timer {
    id: searchDelay
    interval: 160
    onTriggered: root.loadPage(0)
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      text: "Add five from this page"
      enabled: !root.loading && root.library.items.some(function (item) {
        return item.ready && root.selectedIds.indexOf(item.id) < 0
      }) && root.selectedIds.length < root.selectionLimit
      onClicked: root.selectFive()
    }
    Action {
      text: "Clear selection"
      enabled: root.selectedIds.length > 0
      onClicked: root.selectedIds = []
    }
    Action {
      text: root.selectedIds.length ? "Practice selected · " + root.selectedIds.length : "Select subjects to practice"
      selected: root.selectedIds.length > 0
      enabled: root.selectedIds.length > 0 && !root.controller.busy
      onClicked: root.startSelected()
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.selectedIds.length + " / " + root.selectionLimit + " selected. Selections stay with you as you change groups or pages."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.library.saved_practice !== null && root.selectedIds.length > 0
    text: "Starting this selection keeps the earlier practice record and begins a new ungraded set."
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
    visible: root.loading
    text: "Loading your local practice library…"
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.loading && root.library.items.length === 0
    text: searchField.text.length > 0 ? "No matching subjects in this group. Try a shorter search or another group." : root.group === "saved" ? "Save a subject from lookup to build your own practice collection." : root.group === "mistakes" ? "No uncorrected mistakes were recorded here during the last " + root.library.mistake_days + " days." : root.group === "learned" ? "Started subjects will appear here after account synchronization. Completed offline lessons appear immediately." : "No suggested subjects yet. Browse Learned to choose your own practice set."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Repeater {
    model: root.library.items
    Card {
      id: subjectCard
      required property var modelData
      readonly property bool chosen: root.selectedIds.indexOf(modelData.id) >= 0
      enabled: !root.loading
      opacity: root.loading ? 0.6 : 1
      Layout.fillWidth: true
      Layout.preferredHeight: itemRow.implicitHeight + Style.space(24)
      border.color: chosen ? Color.accent : Qt.alpha(Color.foreground, 0.12)
      RowLayout {
        id: itemRow
        anchors.fill: parent
        anchors.margins: Style.space(12)
        spacing: Style.space(12)
        SubjectGlyph {
          Layout.preferredWidth: Style.space(100)
          Layout.preferredHeight: Style.space(68)
          subject: subjectCard.modelData
          pixelSize: Style.space(34)
        }
        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(5)
          Label {
            Layout.fillWidth: true
            text: subjectCard.modelData.spoilers_hidden ? "Meaning hidden during your graded session" : subjectCard.modelData.meaning || "Radical image"
            color: subjectCard.modelData.spoilers_hidden ? Qt.alpha(Color.foreground, 0.76) : Color.foreground
            font.bold: !subjectCard.modelData.spoilers_hidden
          }
          Label {
            Layout.fillWidth: true
            text: subjectCard.modelData.type.replace("_", " ") + " · Level " + subjectCard.modelData.level + " · " + (subjectCard.modelData.learned ? "SRS " + subjectCard.modelData.srs_stage : "Lesson not started")
            color: Qt.alpha(Color.foreground, 0.76)
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            Layout.fillWidth: true
            text: subjectCard.modelData.reasons.map(function (reason) {
              return reason.label
            }).join(" · ")
            color: Qt.alpha(Color.foreground, 0.76)
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            Layout.fillWidth: true
            visible: !subjectCard.modelData.ready
            text: subjectCard.modelData.cache_note
            color: Color.urgent
            font.pixelSize: Style.font.bodySmall
          }
        }
        Action {
          text: subjectCard.chosen ? "Selected ✓" : "Select"
          selected: subjectCard.chosen
          enabled: subjectCard.chosen || (subjectCard.modelData.ready && root.selectedIds.length < root.selectionLimit)
          accessibleName: (subjectCard.chosen ? "Remove " : "Add ") + (subjectCard.modelData.characters || "radical") + (subjectCard.chosen ? " from" : " to") + " practice selection"
          onClicked: root.toggleSubject(subjectCard.modelData)
        }
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      Layout.fillWidth: true
      text: root.library.total ? (root.library.offset + 1) + "–" + Math.min(root.library.offset + root.library.items.length, root.library.total) + " of " + root.library.total + " · " + (root.library.readiness_scope === "page" ? root.library.page_ready + " on this page ready offline" : root.library.ready_total + " ready offline") : "0 subjects"
      color: Qt.alpha(Color.foreground, 0.76)
      font.pixelSize: Style.font.bodySmall
    }
    Action {
      text: "Previous"
      enabled: root.library.offset > 0 && !root.loading
      onClicked: root.loadPage(Math.max(0, root.library.offset - root.library.limit))
    }
    Action {
      text: "Next"
      enabled: root.library.has_more && !root.loading
      onClicked: root.loadPage(root.library.next_offset)
    }
  }
}
