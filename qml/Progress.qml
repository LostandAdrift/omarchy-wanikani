import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme

ColumnLayout {
  id: root
  required property var controller
  readonly property var service: controller.service
  property int selectedLevel: 0
  property string section: "subjects"
  readonly property bool historyOpen: section === "history"
  readonly property bool explorerOpen: section === "explorer"
  property var explorerNavigation: ({})
  property string subjectType: ""
  property int offset: 0
  readonly property int pageSize: 24
  property var overview: null
  property var page: ({
      items: [],
      total: 0,
      has_more: false,
      complete: false
    })
  property bool loading: false
  property bool fetching: false
  property bool dirty: true
  property bool initialized: false
  property int serial: 0
  property int fetchOwner: -1
  property string overviewContext: ""
  property string notice: ""
  readonly property string contentAccess: controller.contentAccess || ""
  readonly property bool active: visible && !historyOpen && !explorerOpen && controller.opened && controller.service && controller.service.ready && !controller.service.locked
  readonly property string contextKey: JSON.stringify([controller.contentAccess || "", controller.snapshot.last_sync, controller.snapshot.session_epoch, controller.snapshot.session_revision, controller.snapshot.pending, controller.snapshot.attention, controller.snapshot.level, controller.snapshot.syncing, controller.snapshot.status])
  readonly property int currentLevel: overview && overview.current && Number.isInteger(overview.current.level) ? overview.current.level : (controller.snapshot.level || 0)
  readonly property int boardLevel: selectedLevel || currentLevel
  readonly property int maximumLevel: Math.min(currentLevel, controller.snapshot.max_level || currentLevel)
  readonly property var groups: overview && overview.distribution && Array.isArray(overview.distribution.groups) ? overview.distribution.groups.filter(function (group) {
    return group && typeof group.label === "string" && Number.isInteger(group.count) && group.count >= 0
  }).slice(0, 8) : []
  spacing: Style.space(16)

  function focusInput() {
    if (explorerOpen)
      srsExplorer.focusInput()
    else if (historyOpen)
      historyPage.focusInput()
    else
      refreshProgress.forceActiveFocus(Qt.TabFocusReason)
  }
  function saveNavigation() {
    if (!initialized || typeof controller.progressNavigation === "undefined")
      return
    controller.progressNavigation = {
      schema: 1,
      section: section,
      selected_level: selectedLevel,
      subject_type: subjectType,
      offset: offset,
      explorer: explorerNavigation
    }
  }
  function restoreNavigation() {
    var state = controller.progressNavigation
    if (!state || state.schema !== 1)
      return
    if (["subjects", "history", "explorer"].indexOf(state.section) >= 0)
      section = state.section
    if (Number.isInteger(state.selected_level) && state.selected_level >= 0 && state.selected_level <= (controller.snapshot.max_level || 0))
      selectedLevel = state.selected_level
    if (["", "radical", "kanji", "vocabulary", "kana_vocabulary"].indexOf(state.subject_type) >= 0)
      subjectType = state.subject_type
    if (Number.isInteger(state.offset) && state.offset >= 0 && state.offset <= 1000)
      offset = state.offset
    if (state.explorer && typeof state.explorer === "object")
      explorerNavigation = state.explorer
  }
  function chooseSection(next) {
    if (["subjects", "history", "explorer"].indexOf(next) < 0)
      return
    section = next
    saveNavigation()
    Qt.callLater(focusInput)
  }
  function chooseExplorer(group) {
    chooseSection("explorer")
    srsExplorer.chooseGroup(group)
  }
  function invalidate(clearOverview) {
    serial++
    dirty = true
    loading = false
    fetching = false
    fetchOwner = -1
    page = {
      items: [],
      total: 0,
      has_more: false,
      complete: false
    }
    if (clearOverview) {
      overview = null
      overviewContext = ""
    }
    if (active && initialized)
      Qt.callLater(fetch)
  }
  function chooseType(type) {
    if (subjectType === type)
      return
    subjectType = type
    offset = 0
    saveNavigation()
    invalidate(false)
  }
  function chooseLevel(level) {
    if (!Number.isInteger(level) || level < 1 || level > maximumLevel)
      return
    selectedLevel = level
    offset = 0
    saveNavigation()
    invalidate(false)
  }
  function changePage(next) {
    if (loading || !Number.isInteger(next) || next < 0 || next > 1000)
      return
    offset = next
    saveNavigation()
    invalidate(false)
  }
  function validCard(card, nested) {
    return card && typeof card === "object" && Number.isSafeInteger(card.id) && card.id > 0 && Number.isInteger(card.level) && card.level >= 1 && card.level <= (controller.snapshot.max_level || 0) && ["radical", "kanji", "vocabulary", "kana_vocabulary"].indexOf(card.type) >= 0 && typeof card.characters === "string" && typeof card.meaning === "string" && typeof card.can_open === "boolean" && typeof card.spoilers_hidden === "boolean" && card.status && typeof card.status === "object" && (!card.spoilers_hidden || (card.can_open === false && card.meaning === "" && (nested || (Array.isArray(card.prerequisites) && card.prerequisites.length === 0)))) && (nested || (Array.isArray(card.prerequisites) && card.prerequisites.length <= 60 && card.prerequisites.every(function (item) {
          return validCard(item, true)
        })))
  }
  function validPage(data, level, type, start) {
    return data && data.level === level && data.subject_type === (type || null) && data.offset === start && Number.isInteger(data.total) && data.total >= 0 && typeof data.has_more === "boolean" && Array.isArray(data.items) && data.items.length <= pageSize && data.items.every(function (item) {
      return validCard(item, false) && item.level === level && (!type || item.type === type)
    })
  }
  function fetch() {
    if (!active || !dirty || fetching || !initialized)
      return
    dirty = false
    fetching = true
    loading = true
    notice = ""
    var request = serial
    fetchOwner = request
    var context = contextKey
    var start = offset
    var type = subjectType
    function fetchBoard(data) {
      if (!current(request, context)) {
        finishFetch(request)
        return
      }
      var level = selectedLevel || data.current.level
      if (!Number.isInteger(level) || level < 1 || level > (controller.snapshot.max_level || 0)) {
        notice = "This level is outside your current account access."
        finishFetch(request)
        return
      }
      controller.service.request("level_board", {
        level: level,
        subject_type: type || null,
        offset: start,
        limit: pageSize
      }, function (boardOk, board, boardMessage) {
        if (current(request, context)) {
          if (boardOk && validPage(board, level, type, start))
            page = board
          else
            notice = boardMessage || "The level board could not be loaded. Refresh to try again."
        }
        finishFetch(request)
      })
    }
    if (overview && overviewContext === context) {
      fetchBoard(overview)
      return
    }
    controller.service.request("progress", {}, function (ok, data, message) {
      if (!current(request, context)) {
        finishFetch(request)
        return
      }
      if (!ok || !data || !data.current || !data.distribution) {
        notice = message || "Progress could not be loaded. Try refreshing your account."
        finishFetch(request)
        return
      }
      overview = data
      overviewContext = context
      fetchBoard(data)
    })
  }
  function current(request, context) {
    return active && request === serial && context === contextKey
  }
  function finishFetch(request) {
    if (request !== fetchOwner)
      return
    fetching = false
    loading = false
    fetchOwner = -1
    if (dirty && active && initialized)
      Qt.callLater(fetch)
  }
  function openSubject(id) {
    if (!active || loading)
      return
    var matches = []
    for (var i = 0; i < page.items.length; ++i) {
      matches.push(page.items[i])
      matches = matches.concat(page.items[i].prerequisites || [])
    }
    if (matches.some(function (item) {
      return item.id === id && item.can_open === true && item.spoilers_hidden === false
    }))
      controller.showProgressSubject(id)
  }
  function statusLabel(item) {
    if (item.spoilers_hidden)
      return "Saved graded study"
    var state = item.status || ({})
    if (state.attention || state.pending)
      return state.label || "Waiting to sync"
    return state.passed ? "Passed · " + (state.stage_name || "Progress cached") : (state.label || "Progress unavailable")
  }
  function reviewLabel(item) {
    var state = item.status || ({})
    if (state.pending || state.attention)
      return "New scheduling follows server confirmation."
    if (!state.next_review_at)
      return ""
    var date = new Date(state.next_review_at)
    return isNaN(date.getTime()) ? "" : state.due ? "Review available now" : "Next review · " + Qt.formatDateTime(date, "ddd d MMM, HH:mm")
  }
  function prerequisiteSchedule(item) {
    return (item.prerequisites || []).filter(function (part) {
      return part.required && !part.spoilers_hidden && (part.status.next_review_at || part.status.pending || part.status.attention)
    }).slice(0, 4).map(function (part) {
      return (part.characters || "Radical") + " · " + reviewLabel(part)
    }).join("\n")
  }
  onServiceChanged: invalidate(true)
  Connections {
    target: root.service
    function onReadyChanged() {
      if (!root.service.ready)
        root.invalidate(true)
    }
  }
  onActiveChanged: invalidate(false)
  onContentAccessChanged: {
    selectedLevel = 0
    offset = 0
    explorerNavigation = ({})
    saveNavigation()
    invalidate(true)
  }
  onContextKeyChanged: invalidate(true)
  Component.onCompleted: {
    restoreNavigation()
    initialized = true
    saveNavigation()
    Qt.callLater(fetch)
  }

  Label {
    Layout.fillWidth: true
    text: "See what you’re building"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    visible: root.section === "subjects"
    text: "Follow your level, see what unlocks next, and recognize what you already know."
    secondary: true
  }
  LevelProgress {
    id: fullLevel
    objectName: "progress-full-level"
    visible: root.section === "subjects"
    progress: root.overview ? root.overview.current : controller.snapshot.learning_progress || null
    showExplore: false
  }
  ColumnLayout {
    objectName: "progress-compact-level"
    Layout.fillWidth: true
    visible: root.section !== "subjects"
    spacing: Style.space(4)
    Label {
      objectName: "progress-compact-level-target"
      Layout.fillWidth: true
      text: (fullLevel.hasLevel ? "Level " + fullLevel.value.level + (fullLevel.value.final_level ? " · Final level" : "") : "Current level") + " · " + (fullLevel.ready && fullLevel.value.accessible !== false ? fullLevel.value.passed + " / " + fullLevel.value.required + " required kanji passed" : fullLevel.value.accessible === false ? "Progress unavailable" : "Waiting for a complete sync")
      font.bold: true
    }
    Label {
      objectName: "progress-compact-level-pending"
      Layout.fillWidth: true
      readonly property var parts: [Number.isSafeInteger(fullLevel.value.pending) && fullLevel.value.pending > 0 ? fullLevel.value.pending + " waiting to sync" : "", Number.isSafeInteger(fullLevel.value.attention) && fullLevel.value.attention > 0 ? fullLevel.value.attention + " need attention" : ""].filter(function (part) {
        return part.length > 0
      })
      visible: parts.length > 0
      text: parts.join(" · ") + "; outside confirmed progress."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      id: refreshProgress
      text: "Refresh account"
      enabled: !root.loading && !root.controller.snapshot.syncing
      onClicked: root.controller.call("sync", {}, function (ok) {
        if (ok && root.active)
          root.invalidate(true)
      })
    }
    Label {
      text: root.loading ? "Loading confirmed progress…" : root.overview && root.overview.last_sync ? "Last synced " + Qt.formatDateTime(new Date(root.overview.last_sync), "ddd HH:mm") : "Based on your cached account"
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.notice.length > 0
    text: root.notice
    textColor: Color.urgent
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      objectName: "progress-subjects-tab"
      text: "Subjects & unlocks"
      selected: root.section === "subjects"
      Accessible.checkable: true
      Accessible.checked: selected
      onClicked: root.chooseSection("subjects")
    }
    Action {
      objectName: "progress-explorer-tab"
      text: "SRS explorer"
      selected: root.explorerOpen
      Accessible.checkable: true
      Accessible.checked: selected
      onClicked: root.chooseSection("explorer")
    }
    Action {
      objectName: "progress-history-tab"
      text: "Level history"
      selected: root.historyOpen
      Accessible.checkable: true
      Accessible.checked: selected
      onClicked: root.chooseSection("history")
    }
  }
  LevelHistory {
    id: historyPage
    Layout.fillWidth: true
    controller: root.controller
    visible: root.historyOpen
  }
  SrsExplorer {
    id: srsExplorer
    objectName: "srs-explorer"
    Layout.fillWidth: true
    controller: root.controller
    visible: root.explorerOpen
    navigationState: root.explorerNavigation
    onNavigationChanged: function (state) {
      root.explorerNavigation = state
      root.saveNavigation()
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.section === "subjects"
    spacing: Style.space(16)
    Label {
      text: "Your learning, now"
      font.bold: true
    }
    Label {
      Layout.fillWidth: true
      text: root.overview && root.overview.distribution.complete ? "Current retention across accessible cached subjects. First passing stays recorded even when a subject needs more practice." : "Some account progress is still being cached. These counts show what is available so far."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Flow {
      id: distributionFlow
      Layout.fillWidth: true
      spacing: Style.space(8)
      Repeater {
        model: root.groups
        Card {
          id: distributionCard
          required property int index
          readonly property var group: root.groups[index]
          width: Math.max(90, (distributionFlow.width - distributionFlow.spacing * (distributionFlow.width < 500 ? 2 : 3)) / (distributionFlow.width < 500 ? 3 : 4))
          height: groupContent.implicitHeight + Style.space(20)
          Action {
            id: distributionAction
            anchors.fill: parent
            objectName: "progress-group-" + distributionCard.group.key
            text: ""
            accessibleName: "Explore " + distributionCard.group.label + ", " + distributionCard.group.count + " subjects"
            surfaceColor: distributionCard.color
            onClicked: root.chooseExplorer(distributionCard.group.key)
          }
          ColumnLayout {
            id: groupContent
            anchors.fill: parent
            anchors.margins: Style.space(10)
            spacing: Style.space(4)
            Label {
              Layout.fillWidth: true
              objectName: "progress-group-label-" + distributionCard.group.key
              text: distributionCard.group.label || "Unknown"
              surfaceColor: Theme.composite(distributionAction.color, distributionCard.color)
              secondary: true
              font.pixelSize: Style.font.bodySmall
            }
            Label {
              objectName: "progress-group-count-" + distributionCard.group.key
              text: String(distributionCard.group.count || 0)
              surfaceColor: Theme.composite(distributionAction.color, distributionCard.color)
              textColor: Color.accent
              font.pixelSize: Style.space(25)
              font.bold: true
            }
          }
        }
      }
    }
    Label {
      Layout.fillWidth: true
      text: "Level " + (root.boardLevel || "—") + " subjects"
      font.bold: true
      font.pixelSize: Style.font.title
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        text: "← Previous level"
        enabled: !root.loading && root.boardLevel > 1
        onClicked: root.chooseLevel(root.boardLevel - 1)
      }
      Action {
        text: "Current level"
        selected: root.boardLevel === root.currentLevel
        enabled: !root.loading && root.currentLevel <= root.maximumLevel
        onClicked: root.chooseLevel(root.currentLevel)
      }
      Action {
        text: "Next level →"
        enabled: !root.loading && root.boardLevel < root.maximumLevel
        onClicked: root.chooseLevel(root.boardLevel + 1)
      }
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: [
          {
            key: "",
            label: "All subjects"
          },
          {
            key: "radical",
            label: "Radicals"
          },
          {
            key: "kanji",
            label: "Kanji"
          },
          {
            key: "vocabulary",
            label: "Vocabulary"
          },
          {
            key: "kana_vocabulary",
            label: "Kana vocabulary"
          }
        ]
        Action {
          required property var modelData
          text: modelData.label
          selected: root.subjectType === modelData.key
          onClicked: root.chooseType(modelData.key)
        }
      }
    }
    Label {
      Layout.fillWidth: true
      text: root.loading ? "Loading this level…" : root.page.items.length ? (root.offset + 1) + "–" + (root.offset + root.page.items.length) + " of " + root.page.total + " subjects" + (root.page.complete ? "" : " · partial cache") : "No subjects are cached for this selection. Refresh your account or choose another subject type."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Repeater {
      model: root.page.items
      Card {
        id: subjectCard
        required property int index
        readonly property var subject: root.page.items[index]
        Layout.fillWidth: true
        Layout.preferredHeight: subjectContent.implicitHeight + Style.space(24)
        ColumnLayout {
          id: subjectContent
          anchors.fill: parent
          anchors.margins: Style.space(12)
          spacing: Style.space(8)
          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(14)
            Label {
              Layout.preferredWidth: Style.space(100)
              text: subjectCard.subject.characters || "◇"
              font.family: "Noto Sans CJK JP"
              font.pixelSize: Style.space(34)
              surfaceColor: subjectCard.color
            }
            ColumnLayout {
              Layout.fillWidth: true
              Label {
                Layout.fillWidth: true
                text: subjectCard.subject.meaning || (subjectCard.subject.spoilers_hidden ? "Answer kept for your saved session" : "Subject details")
                surfaceColor: subjectCard.color
                font.bold: true
              }
              Label {
                Layout.fillWidth: true
                text: subjectCard.subject.type.replace("_", " ") + " · " + root.statusLabel(subjectCard.subject)
                surfaceColor: subjectCard.color
                secondary: true
                font.pixelSize: Style.font.bodySmall
              }
            }
          }
          Label {
            Layout.fillWidth: true
            text: root.reviewLabel(subjectCard.subject)
            visible: text.length > 0
            surfaceColor: subjectCard.color
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            Layout.fillWidth: true
            visible: subjectCard.subject.prerequisites.length > 0
            text: "Prerequisites · " + subjectCard.subject.prerequisites.filter(function (part) {
              return part.required
            }).length + " still to pass"
            surfaceColor: subjectCard.color
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
          Flow {
            Layout.fillWidth: true
            spacing: Style.space(6)
            visible: subjectCard.subject.prerequisites.length > 0
            Repeater {
              model: subjectCard.subject.prerequisites
              Action {
                required property int index
                readonly property var prerequisite: subjectCard.subject.prerequisites[index]
                text: (prerequisite.characters || "◇") + " · " + (prerequisite.status.passed ? "Passed" : root.statusLabel(prerequisite))
                accessibleName: (prerequisite.characters || "Radical") + ", prerequisite, " + root.statusLabel(prerequisite)
                enabled: prerequisite.can_open === true && !prerequisite.spoilers_hidden
                surfaceColor: subjectCard.color
                onClicked: root.openSubject(prerequisite.id)
              }
            }
          }
          Label {
            Layout.fillWidth: true
            text: root.prerequisiteSchedule(subjectCard.subject)
            visible: text.length > 0
            surfaceColor: subjectCard.color
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            Layout.fillWidth: true
            visible: subjectCard.subject.prerequisites_complete === false
            text: "Some prerequisite information is unavailable in the current cache."
            surfaceColor: subjectCard.color
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
          Action {
            text: subjectCard.subject.spoilers_hidden ? "Protected while graded study is saved" : "Open subject →"
            enabled: subjectCard.subject.can_open === true && !subjectCard.subject.spoilers_hidden
            surfaceColor: subjectCard.color
            onClicked: root.openSubject(subjectCard.subject.id)
          }
        }
      }
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        text: "← Previous page"
        enabled: !root.loading && root.offset > 0
        onClicked: root.changePage(Math.max(0, root.offset - root.pageSize))
      }
      Action {
        text: "Next page →"
        enabled: !root.loading && root.page.has_more === true
        onClicked: root.changePage(root.page.next_offset)
      }
    }
  }
}
