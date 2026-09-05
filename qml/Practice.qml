import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui
import "SubjectStatus.mjs" as SubjectStatus

ColumnLayout {
  id: root
  required property var controller
  property string group: "suggested"
  property var selectedIds: []
  property bool loading: false
  property bool initialized: false
  property bool dirty: true
  property bool fetching: false
  property string notice: ""
  property int requestSerial: 0
  property int requestedOffset: 0
  property string observedSync: ""
  readonly property bool active: controller.opened && controller.service && controller.service.ready && !controller.service.locked
  onActiveChanged: {
    requestSerial++
    dirty = true
    loading = false
    searchDelay.stop()
    if (active && initialized)
      Qt.callLater(fetchPage)
  }
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
    requestedOffset = 0
    dirty = true
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
    requestedOffset = offset || 0
    requestSerial++
    dirty = true
    notice = ""
    searchDelay.stop()
    // Construction, access and sync changes can request the same page in one
    // event-loop turn. Keep only their latest request before reading SQLite.
    if (active && initialized)
      Qt.callLater(fetchPage)
  }
  function editSearch() {
    requestedOffset = 0
    requestSerial++
    dirty = true
    if (active)
      searchDelay.restart()
  }
  function fetchPage() {
    if (!active || !dirty || fetching || searchDelay.running)
      return
    var serial = requestSerial
    dirty = false
    fetching = true
    loading = true
    controller.service.request("practice_catalogue", {
      group: group,
      query: searchField.text,
      offset: requestedOffset,
      limit: 30,
      readiness_scope: "page"
    }, function (ok, data, message) {
      if (!root)
        return
      root.fetching = false
      if (serial === root.requestSerial && root.active) {
        root.loading = false
        if (ok)
          root.library = data
        else
          root.notice = message || "The practice library could not be loaded. Refresh and try again."
      }
      if (root.active && root.dirty && !searchDelay.running)
        Qt.callLater(root.fetchPage)
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
  function stageLabel(item) {
    var named = SubjectStatus.stageName(item.srs_stage)
    if (named)
      return named
    if (item.srs_stage === 0 && item.pending_graded === true)
      return "No confirmed SRS stage yet"
    return item.srs_stage === 0 && item.learned === false ? "Lesson not started" : "SRS stage unavailable"
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
        root.loadPage(root.requestedOffset)
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
    secondary: true
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
          secondary: true
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
    textColor: Color.accent
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
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Ui.TextField {
      id: searchField
      Layout.fillWidth: true
      placeholderText: "Characters, reading, or meaning…"
      Accessible.name: "Search the practice library"
      onTextEdited: root.editSearch()
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
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.library.saved_practice !== null && root.selectedIds.length > 0
    text: "Starting this selection keeps the earlier practice record and begins a new ungraded set."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.notice !== ""
    text: root.notice
    textColor: Color.urgent
  }
  Label {
    Layout.fillWidth: true
    visible: root.loading
    text: "Loading your local practice library…"
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    visible: !root.loading && root.library.items.length === 0
    text: searchField.text.length > 0 ? "No matching subjects in this group. Try a shorter search or another group." : root.group === "saved" ? "Save a subject from lookup to build your own practice collection." : root.group === "mistakes" ? "No uncorrected mistakes were recorded here during the last " + root.library.mistake_days + " days." : root.group === "learned" ? "Started subjects will appear here after account synchronization. Completed offline lessons appear immediately." : "No suggested subjects yet. Browse Learned to choose your own practice set."
    secondary: true
  }
  Repeater {
    model: root.library.items
    Card {
      id: subjectCard
      objectName: "practice-subject-card"
      required property var modelData
      required property int index
      readonly property var glyphSubject: Array.isArray(root.library.items) && index >= 0 && index < root.library.items.length && root.library.items[index] && root.library.items[index].id === modelData.id ? root.library.items[index] : null
      readonly property bool chosen: root.selectedIds.indexOf(modelData.id) >= 0
      enabled: !root.loading
      opacity: root.loading ? 0.6 : 1
      Layout.fillWidth: true
      Layout.preferredHeight: itemContent.implicitHeight + Style.space(24)
      border.color: chosen ? Color.accent : Qt.alpha(Color.foreground, 0.12)
      ColumnLayout {
        id: itemContent
        anchors.fill: parent
        anchors.margins: Style.space(12)
        spacing: Style.space(8)
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(12)
          SubjectGlyph {
            objectName: "practice-subject-glyph"
            Layout.preferredWidth: Style.space(78)
            Layout.preferredHeight: Style.space(64)
            subject: subjectCard.glyphSubject
            pixelSize: Style.space(34)
          }
          Label {
            objectName: "practice-subject-meaning"
            Layout.fillWidth: true
            text: subjectCard.modelData.spoilers_hidden ? "Meaning hidden during your graded session" : subjectCard.modelData.meaning || "Radical image"
            secondary: subjectCard.modelData.spoilers_hidden
            font.bold: !subjectCard.modelData.spoilers_hidden
          }
        }
        Label {
          objectName: "practice-subject-status"
          Layout.fillWidth: true
          text: subjectCard.modelData.type.replace("_", " ") + " · Level " + subjectCard.modelData.level + " · " + root.stageLabel(subjectCard.modelData)
          secondary: true
          font.pixelSize: Style.font.bodySmall
        }
        Label {
          objectName: "practice-subject-reasons"
          Layout.fillWidth: true
          text: subjectCard.modelData.reasons.map(function (reason) {
            return reason.label
          }).join(" · ")
          secondary: true
          font.pixelSize: Style.font.bodySmall
        }
        Label {
          Layout.fillWidth: true
          visible: !subjectCard.modelData.ready
          text: subjectCard.modelData.cache_note
          textColor: Color.urgent
          font.pixelSize: Style.font.bodySmall
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(6)
          Action {
            objectName: "practice-subject-select"
            text: subjectCard.chosen ? "Selected ✓" : "Select"
            selected: subjectCard.chosen
            enabled: subjectCard.chosen || (subjectCard.modelData.ready && root.selectedIds.length < root.selectionLimit)
            accessibleName: (subjectCard.chosen ? "Remove " : "Add ") + (subjectCard.modelData.characters || "radical") + (subjectCard.chosen ? " from" : " to") + " practice selection"
            Accessible.checkable: true
            Accessible.checked: subjectCard.chosen
            onClicked: root.toggleSubject(subjectCard.modelData)
          }
        }
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Label {
      Layout.fillWidth: true
      text: root.library.total ? (root.library.offset + 1) + "–" + Math.min(root.library.offset + root.library.items.length, root.library.total) + " of " + root.library.total + " · " + (root.library.readiness_scope === "page" ? root.library.page_ready + " on this page ready offline" : root.library.ready_total + " ready offline") : "0 subjects"
      secondary: true
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
