pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  property var navigationState: ({})
  signal navigationChanged(var state)
  property string group: "apprentice"
  property var subjectType: null
  property var level: null
  property var stage: null
  property string order: "level"
  property int offset: 0
  readonly property int pageSize: 24
  property bool filtersOpen: false
  property bool levelsOpen: false
  property var page: null
  property bool initialized: false
  property bool dirty: true
  property bool loading: false
  property int serial: 0
  property int inFlight: -1
  property string error: ""
  readonly property var service: controller.service
  readonly property bool active: visible && controller.opened && !!service && service.ready && !service.locked
  readonly property int maximum: Number.isInteger(controller.snapshot.max_level) ? Math.max(0, Math.min(60, controller.snapshot.max_level)) : 0
  readonly property string context: JSON.stringify([controller.contentAccess, controller.snapshot.last_sync, controller.snapshot.session_epoch, controller.snapshot.session_revision, controller.snapshot.pending, controller.snapshot.attention, controller.snapshot.syncing, controller.snapshot.status])
  readonly property var groups: [
    {
      key: "locked",
      label: "Locked"
    },
    {
      key: "lessons",
      label: "Lesson ready"
    },
    {
      key: "apprentice",
      label: "Apprentice"
    },
    {
      key: "guru",
      label: "Guru"
    },
    {
      key: "master",
      label: "Master"
    },
    {
      key: "enlightened",
      label: "Enlightened"
    },
    {
      key: "burned",
      label: "Burned"
    },
    {
      key: "unknown",
      label: "Unknown"
    }
  ]
  readonly property var types: [
    {
      key: null,
      label: "All types"
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
  readonly property var rows: page ? page.items : []
  readonly property var emptyCard: ({
      id: 0,
      type: "kanji",
      level: 0,
      characters: "",
      meaning: "",
      can_open: false,
      spoilers_hidden: true,
      status: {
        label: "",
        pending: false,
        attention: false,
        passed: false,
        next_review_at: null
      }
    })
  readonly property var levelOptions: page ? page.levels : []
  readonly property var stageOptions: page ? page.stages : []
  readonly property int hiddenCount: rows.filter(function (row) {
    return row.spoilers_hidden
  }).length
  readonly property string selectedLabel: groups.filter(function (item) {
    return item.key === root.group
  })[0].label
  spacing: Style.space(14)

  function focusInput() {
    if (active) {
      var index = groups.findIndex(function (item) {
        return item.key === root.group
      })
      var button = groupButtons.itemAt(index)
      if (button)
        button.forceActiveFocus(Qt.TabFocusReason)
    }
  }
  function keysOnly(value, allowed) {
    return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).every(function (key) {
      return allowed.indexOf(key) >= 0
    })
  }
  function stagesFor(value) {
    return value === "apprentice" ? [1, 2, 3, 4] : value === "guru" ? [5, 6] : value === "master" ? [7] : value === "enlightened" ? [8] : value === "burned" ? [9] : []
  }
  function stageLabel(value) {
    return value <= 4 ? "Apprentice " + value : value <= 6 ? "Guru " + (value - 4) : value === 7 ? "Master" : value === 8 ? "Enlightened" : "Burned"
  }
  function selectionState() {
    return {
      group: group,
      subject_type: subjectType,
      level: level,
      stage: stage,
      order: order,
      offset: offset
    }
  }
  function normalize(value) {
    value = keysOnly(value, ["group", "subject_type", "level", "stage", "order", "offset"]) ? value : ({})
    var selected = groups.some(function (item) {
      return item.key === value.group
    }) ? value.group : "apprentice"
    return {
      group: selected,
      subject_type: types.some(function (item) {
        return item.key === value.subject_type
      }) ? value.subject_type : null,
      level: Number.isInteger(value.level) && value.level >= 1 && value.level <= maximum ? value.level : null,
      stage: Number.isInteger(value.stage) && stagesFor(selected).indexOf(value.stage) >= 0 ? value.stage : null,
      order: value.order === "next_review" ? "next_review" : "level",
      offset: Number.isInteger(value.offset) && value.offset >= 0 && value.offset <= 12000 ? value.offset : 0
    }
  }
  function restore(value) {
    var next = normalize(value)
    if (JSON.stringify(next) === JSON.stringify(selectionState()))
      return
    group = next.group
    subjectType = next.subject_type
    level = next.level
    stage = next.stage
    order = next.order
    offset = next.offset
    if (initialized)
      invalidate(false)
  }
  function notifyNavigation() {
    // The parent binds navigationState and saves this signal back into that
    // binding. Publish after restoration finishes, never inside its evaluation.
    Qt.callLater(publishNavigation)
  }
  function publishNavigation() {
    if (initialized)
      navigationChanged(selectionState())
  }
  function invalidate(resetPage) {
    serial++
    page = null
    error = ""
    dirty = true
    loading = active
    if (resetPage)
      offset = 0
    if (initialized) {
      notifyNavigation()
      if (active)
        Qt.callLater(fetch)
    }
  }
  function chooseGroup(value) {
    if (!groups.some(function (item) {
      return item.key === value
    }))
      return
    group = value
    stage = null
    levelsOpen = false
    invalidate(true)
  }
  function chooseType(value) {
    if (!types.some(function (item) {
      return item.key === value
    }) || subjectType === value)
      return
    subjectType = value
    invalidate(true)
  }
  function chooseLevel(value) {
    if (value !== null && (!Number.isInteger(value) || value < 1 || value > maximum))
      return
    levelsOpen = false
    if (level === value)
      return
    level = value
    invalidate(true)
  }
  function chooseStage(value) {
    if (value !== null && stagesFor(group).indexOf(value) < 0)
      return
    if (stage === value)
      return
    stage = value
    invalidate(true)
  }
  function chooseOrder(value) {
    if (["level", "next_review"].indexOf(value) < 0 || order === value)
      return
    order = value
    invalidate(true)
  }
  function changePage(value) {
    if (!active || loading || !Number.isInteger(value) || value < 0 || value > 12000)
      return
    offset = value
    invalidate(false)
  }
  function date(value) {
    return value === null || (typeof value === "string" && value.length <= 80 && !isNaN(new Date(value).getTime()))
  }
  function validStatus(value) {
    return keysOnly(value, ["stage", "stage_name", "group", "unlocked_at", "started_at", "available_at", "passed_at", "burned_at", "next_review_at", "due", "passed", "pending", "attention", "pending_operations", "label"]) && value.group === group && (value.stage === null || (Number.isInteger(value.stage) && value.stage >= 0 && value.stage <= 9)) && typeof value.stage_name === "string" && value.stage_name.length <= 160 && typeof value.label === "string" && value.label.length <= 160 && ["due", "passed", "pending", "attention"].every(function (key) {
      return typeof value[key] === "boolean"
    }) && Number.isInteger(value.pending_operations) && value.pending_operations >= 0 && ["unlocked_at", "started_at", "available_at", "passed_at", "burned_at", "next_review_at"].every(function (key) {
      return date(value[key])
    })
  }
  function validCard(value) {
    return keysOnly(value, ["id", "type", "level", "characters", "meaning", "can_open", "spoilers_hidden", "status", "prerequisites", "prerequisites_complete"]) && Number.isSafeInteger(value.id) && value.id > 0 && Number.isInteger(value.level) && value.level >= 1 && value.level <= maximum && types.some(function (item) {
      return item.key !== null && item.key === value.type
    }) && (!subjectType || value.type === subjectType) && (level === null || value.level === level) && typeof value.characters === "string" && value.characters.length <= 256 && typeof value.meaning === "string" && value.meaning.length <= 320 && typeof value.can_open === "boolean" && typeof value.spoilers_hidden === "boolean" && (!value.spoilers_hidden || (!value.can_open && value.meaning === "")) && Array.isArray(value.prerequisites) && value.prerequisites.length === 0 && value.prerequisites_complete === true && validStatus(value.status) && (stage === null || value.status.stage === stage)
  }
  function valid(data, requested) {
    if (!keysOnly(data, ["group", "subject_type", "level", "stage", "order", "offset", "limit", "total", "total_complete", "complete", "protection_complete", "items", "has_more", "next_offset", "levels", "stages", "last_sync", "source", "scope"]))
      return false
    if (!Object.keys(requested).every(function (key) {
      return data[key] === requested[key]
    }) || data.limit !== pageSize || data.source !== "cached_wanikani" || data.scope !== "Accessible cached subjects; confirmed current assignments" || !Number.isInteger(data.total) || data.total < 0 || data.total > 12000 || typeof data.total_complete !== "boolean" || typeof data.complete !== "boolean" || typeof data.protection_complete !== "boolean" || (data.complete && !data.total_complete) || typeof data.has_more !== "boolean" || data.has_more !== (offset + pageSize < data.total) || data.next_offset !== (data.has_more ? offset + pageSize : null) || !date(data.last_sync) || !Array.isArray(data.items) || data.items.length > Math.min(pageSize, Math.max(0, data.total - offset)) || !data.items.every(validCard) || new Set(data.items.map(function (row) {
      return row.id
    })).size !== data.items.length || (!data.protection_complete && data.items.some(function (row) {
        return !row.spoilers_hidden || row.can_open
      })) || !Array.isArray(data.levels) || data.levels.length > 60 || !data.levels.every(function (facet) {
      return keysOnly(facet, ["level", "count"]) && Number.isInteger(facet.level) && facet.level >= 1 && facet.level <= maximum && Number.isInteger(facet.count) && facet.count >= 0 && facet.count <= 12000
    }) || new Set(data.levels.map(function (facet) {
      return facet.level
    })).size !== data.levels.length || !Array.isArray(data.stages) || data.stages.length > 4 || !data.stages.every(function (facet) {
      return keysOnly(facet, ["stage", "label", "count"]) && stagesFor(group).indexOf(facet.stage) >= 0 && typeof facet.label === "string" && facet.label.length <= 80 && Number.isInteger(facet.count) && facet.count >= 0 && facet.count <= 12000
    }) || new Set(data.stages.map(function (facet) {
      return facet.stage
    })).size !== data.stages.length)
      return false
    return !data.complete || data.items.length === Math.min(pageSize, Math.max(0, data.total - offset))
  }
  function fetch() {
    if (!initialized || !active || !dirty || inFlight >= 0)
      return
    var expected = serial, access = context, owner = service, requested = selectionState()
    dirty = false
    loading = true
    inFlight = expected
    owner.request("srs_catalogue", Object.assign({}, requested, {
      limit: pageSize
    }), function (ok, data, message) {
      if (!root)
        return
      if (root.inFlight === expected)
        root.inFlight = -1
      if (root.active && root.serial === expected && root.context === access && root.service === owner) {
        root.loading = false
        if (ok && root.valid(data, requested))
          root.page = data
        else
          root.error = message || "These cached subjects could not be read. Refresh the list to try again."
      }
      if (root.active && root.dirty)
        Qt.callLater(root.fetch)
    })
  }
  function openSubject(id) {
    if (active && !loading && page && page.protection_complete && rows.some(function (row) {
      return row.id === id && row.can_open && !row.spoilers_hidden
    })) {
      // A deliberate handoff must save this page before the view is destroyed.
      publishNavigation()
      controller.showProgressSubject(id)
    }
  }
  function typeLabel(value) {
    return value === "radical" ? "Radical" : value === "kanji" ? "Kanji" : value === "vocabulary" ? "Vocabulary" : "Kana vocabulary"
  }
  function reviewLabel(value) {
    if (value.pending || value.attention)
      return "New scheduling follows server confirmation."
    if (!value.next_review_at)
      return "No cached next-review date"
    return value.due ? "Review available now" : "Next review · " + Qt.formatDateTime(new Date(value.next_review_at), "ddd d MMM, HH:mm")
  }
  onNavigationStateChanged: if (initialized)
    restore(navigationState)
  onActiveChanged: if (initialized)
    invalidate(false)
  onContextChanged: if (initialized) {
    if (level !== null && level > maximum)
      level = null
    invalidate(true)
  }
  onServiceChanged: if (initialized) {
    inFlight = -1
    invalidate(false)
  }
  Connections {
    target: root.service
    function onReadyChanged() {
      if (!root.service.ready) {
        root.inFlight = -1
        root.invalidate(false)
      }
    }
  }
  Component.onCompleted: {
    restore(navigationState)
    initialized = true
    notifyNavigation()
    Qt.callLater(fetch)
  }

  Label {
    Layout.fillWidth: true
    text: "Find your familiar ground"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.controller.snapshot.demo === true ? "Authored demo subjects, grouped by their recorded SRS state." : "Explore your confirmed SRS state across accessible levels. First passing and pending reviews remain separate."
    secondary: true
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    Repeater {
      id: groupButtons
      model: root.groups
      Action {
        required property var modelData
        text: modelData.label
        objectName: "srs-group-" + modelData.key
        selected: root.group === modelData.key
        Accessible.checkable: true
        Accessible.checked: selected
        enabled: root.active
        onClicked: root.chooseGroup(modelData.key)
      }
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      id: refreshButton
      objectName: "srs-refresh"
      text: root.loading ? "Reading subjects…" : "Refresh list"
      enabled: root.active && !root.loading
      onClicked: root.invalidate(false)
    }
    Action {
      objectName: "srs-refine"
      text: root.filtersOpen ? "Hide filters" : "Refine subjects"
      selected: root.filtersOpen
      Accessible.checkable: true
      Accessible.checked: selected
      enabled: root.active
      onClicked: root.filtersOpen = !root.filtersOpen
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.selectedLabel + " · " + (root.subjectType ? root.typeLabel(root.subjectType) : "All types") + " · " + (root.level === null ? "All accessible levels" : "Level " + root.level) + (root.stage === null ? "" : " · " + root.stageLabel(root.stage))
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  ColumnLayout {
    visible: root.filtersOpen
    Layout.fillWidth: true
    spacing: Style.space(10)
    Label {
      text: "Subject type"
      font.bold: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: root.types
        Action {
          required property var modelData
          objectName: "srs-type-" + (modelData.key || "all")
          text: modelData.label
          selected: root.subjectType === modelData.key
          Accessible.checkable: true
          Accessible.checked: selected
          enabled: root.active
          onClicked: root.chooseType(modelData.key)
        }
      }
    }
    Label {
      text: "SRS stage"
      font.bold: true
      visible: root.stagesFor(root.group).length > 1
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      visible: root.stagesFor(root.group).length > 1
      Action {
        objectName: "srs-stage-all"
        text: "All stages"
        selected: root.stage === null
        Accessible.checkable: true
        Accessible.checked: selected
        enabled: root.active
        onClicked: root.chooseStage(null)
      }
      Repeater {
        model: root.stageOptions
        Action {
          required property var modelData
          objectName: "srs-stage-" + modelData.stage
          text: modelData.label + " · " + modelData.count
          selected: root.stage === modelData.stage
          Accessible.checkable: true
          Accessible.checked: selected
          enabled: root.active
          onClicked: root.chooseStage(modelData.stage)
        }
      }
    }
    Action {
      objectName: "srs-levels"
      text: (root.level === null ? "All accessible levels" : "Level " + root.level) + (root.levelsOpen ? " ▴" : " ▾")
      enabled: root.active
      onClicked: root.levelsOpen = !root.levelsOpen
    }
    Flow {
      visible: root.levelsOpen
      Layout.fillWidth: true
      spacing: Style.space(6)
      Action {
        objectName: "srs-level-all"
        text: "All levels"
        selected: root.level === null
        Accessible.checkable: true
        Accessible.checked: selected
        enabled: root.active
        onClicked: root.chooseLevel(null)
      }
      Repeater {
        model: root.levelOptions
        Action {
          required property var modelData
          objectName: "srs-level-" + modelData.level
          text: "Level " + modelData.level + " · " + modelData.count
          selected: root.level === modelData.level
          Accessible.checkable: true
          Accessible.checked: selected
          enabled: root.active
          onClicked: root.chooseLevel(modelData.level)
        }
      }
    }
    Label {
      text: "Order"
      font.bold: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Action {
        objectName: "srs-level-order"
        text: "By level"
        selected: root.order === "level"
        Accessible.checkable: true
        Accessible.checked: selected
        enabled: root.active
        onClicked: root.chooseOrder("level")
      }
      Action {
        objectName: "srs-review-order"
        text: "By next review"
        selected: root.order === "next_review"
        Accessible.checkable: true
        Accessible.checked: selected
        enabled: root.active
        onClicked: root.chooseOrder("next_review")
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.order === "next_review"
    text: "Uses confirmed cached review dates, earliest first. Subjects without a date come last; no future level-up or burn date is predicted."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    objectName: "srs-error"
    Layout.fillWidth: true
    visible: root.error !== ""
    text: root.error
    textColor: Color.urgent
  }
  Label {
    objectName: "srs-partial"
    Layout.fillWidth: true
    visible: !!root.page && !root.page.complete
    text: root.page && !root.page.total_complete ? "This is a bounded, incomplete catalogue. Counts describe the cached subjects available so far." : "Some assignments or synchronization markers are incomplete. These are cached counts, not a complete account total."
    secondary: true
  }
  Label {
    objectName: "srs-protection"
    Layout.fillWidth: true
    visible: !!root.page && (!root.page.protection_complete || root.hiddenCount > 0)
    text: root.page && !root.page.protection_complete ? "Saved graded study could not be checked. Answers and subject links stay hidden." : root.hiddenCount + " answer" + (root.hiddenCount === 1 ? " is" : "s are") + " kept for saved graded study on this page. These subjects remain included in the counts."
    secondary: true
  }
  Label {
    objectName: "srs-count"
    Layout.fillWidth: true
    visible: !!root.page
    text: root.page ? (root.page.total_complete ? "" : "At least ") + root.page.total + " cached subject" + (root.page.total === 1 ? "" : "s") + " · " + root.selectedLabel : ""
    font.bold: true
  }
  Label {
    objectName: "srs-empty"
    Layout.fillWidth: true
    visible: !!root.page && root.rows.length === 0
    text: root.page && root.page.total > 0 ? "No subjects remain on this page. Return to the first page or choose another filter." : "No cached subjects match these filters. Try another SRS group, type, or level."
    secondary: true
  }
  Repeater {
    model: root.rows
    Card {
      id: srsCard
      required property int index
      readonly property var row: root.rows[index] || root.emptyCard
      visible: !!root.rows[index]
      Layout.fillWidth: true
      implicitHeight: body.implicitHeight + Style.space(28)
      ColumnLayout {
        id: body
        anchors.fill: parent
        anchors.margins: Style.space(14)
        spacing: Style.space(6)
        Label {
          Layout.fillWidth: true
          text: root.typeLabel(srsCard.row.type) + " · Level " + srsCard.row.level
          secondary: true
          font.pixelSize: Style.font.bodySmall
        }
        JapaneseText {
          Layout.fillWidth: true
          text: srsCard.row.characters || "Image radical"
          font.pixelSize: Style.space(30)
          color: srsCard.textColor
        }
        Label {
          Layout.fillWidth: true
          text: srsCard.row.spoilers_hidden ? "Answer kept for saved study" : srsCard.row.meaning || "Meaning unavailable"
          font.bold: true
        }
        Label {
          Layout.fillWidth: true
          text: srsCard.row.status.label
          textColor: srsCard.row.status.attention ? Color.urgent : Color.foreground
        }
        Label {
          Layout.fillWidth: true
          text: root.reviewLabel(srsCard.row.status)
          secondary: true
          font.pixelSize: Style.font.bodySmall
        }
        Label {
          Layout.fillWidth: true
          visible: srsCard.row.status.passed && !srsCard.row.spoilers_hidden
          text: "First passing recorded; current retention is shown above."
          secondary: true
          font.pixelSize: Style.font.bodySmall
        }
        Action {
          objectName: "srs-open-" + srsCard.row.id
          text: "Open subject"
          accessibleName: "Open " + (srsCard.row.characters || "radical") + ", level " + srsCard.row.level
          enabled: root.active && !root.loading && srsCard.row.can_open && !srsCard.row.spoilers_hidden
          onClicked: root.openSubject(srsCard.row.id)
        }
      }
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      objectName: "srs-first"
      text: "First page"
      visible: root.offset > 0
      enabled: root.active && !root.loading
      onClicked: root.changePage(0)
    }
    Action {
      objectName: "srs-previous"
      text: "← Previous"
      enabled: root.active && !root.loading && root.offset > 0
      onClicked: root.changePage(Math.max(0, root.offset - root.pageSize))
    }
    Action {
      objectName: "srs-next"
      text: "Next →"
      enabled: root.active && !root.loading && !!root.page && root.page.has_more
      onClicked: root.changePage(root.page.next_offset)
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.rows.length > 0
    text: root.page ? "Subjects " + (root.offset + 1) + "–" + (root.offset + root.rows.length) + " of " + root.page.total + " cached" : ""
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
}
