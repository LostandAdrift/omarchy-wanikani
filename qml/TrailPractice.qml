pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import "UnicodeText.mjs" as UnicodeText

ColumnLayout {
  id: root
  required property var controller
  property string passage: ""
  property var matches: []
  property var savedSelection: null
  signal selectionSaved(var state)
  signal startRequested(var preview, bool replacePractice)
  property bool expanded: false
  property bool initialized: false
  property var selectedIds: []
  property var preview: null
  property bool loading: false
  property int serial: 0
  property string notice: ""
  readonly property var service: controller.service
  readonly property var snapshot: controller.snapshot || ({})
  readonly property string contentAccess: controller.contentAccess || ""
  readonly property bool available: visible && controller.opened && controller.view === "lookup" && !controller.detail && service && service.ready && !service.locked && validText(passage)
  readonly property bool active: available && expanded
  readonly property var words: validMatches(matches) ? matches.filter(function (word) {
    return word.can_open === true
  }) : []
  readonly property var currentIds: selectedIds.filter(function (id) {
    return root.words.some(function (word) {
      return word.id === id
    })
  })
  readonly property string contextKey: JSON.stringify([passage, contentAccess, controller.navigationSequence, controller.view, controller.opened, !!controller.detail, service ? service.ready : false, service ? service.locked : true, snapshot.session_epoch, snapshot.session_revision, snapshot.last_sync, snapshot.pending, snapshot.attention, snapshot.max_level, snapshot.syncing, snapshot.status, snapshot.state_revision])
  readonly property string selectionKey: JSON.stringify(currentIds)
  readonly property bool canStart: active && !controller.busy && !loading && preview !== null && preview.can_start === true && preview.text === passage && JSON.stringify(preview.subject_ids) === selectionKey
  spacing: Style.space(10)

  function positive(value) {
    return Number.isSafeInteger(value) && value > 0
  }
  function validText(text) {
    if (typeof text !== "string")
      return false
    var points = UnicodeText.characters(text)
    return points.length > 0 && points.length <= 256 && points.every(function (value) {
      var point = value.codePointAt(0)
      return point < 0xd800 || point > 0xdfff
    })
  }
  function validMatches(value) {
    return Array.isArray(value) && value.length <= 60 && value.every(function (word, index) {
      return word && positive(word.id) && validText(word.characters) && passage.indexOf(word.characters) >= 0 && ["kanji", "vocabulary", "kana_vocabulary"].indexOf(word.type) >= 0 && Number.isInteger(word.level) && word.level >= 1 && word.level <= (snapshot.max_level || 0) && typeof word.can_open === "boolean" && ["Learned", "Not started", "Paused graded work", "Waiting to sync", "Needs attention"].indexOf(word.state) >= 0 && value.findIndex(function (other) {
        return other && other.id === word.id
      }) === index
    })
  }
  function saveSelection() {
    selectionSaved({
      schema: 1,
      text: passage,
      ids: selectedIds.slice()
    })
  }
  function setIds(ids, publish) {
    if (JSON.stringify(ids) === JSON.stringify(selectedIds))
      return
    selectedIds = ids.slice()
    if (publish)
      saveSelection()
  }
  function restoreSelection() {
    if (!initialized)
      return
    var saved = savedSelection
    if (!saved || saved.schema !== 1 || saved.text !== passage || !Array.isArray(saved.ids) || saved.ids.length > 20 || !saved.ids.every(function (id, index) {
      return positive(id) && saved.ids.indexOf(id) === index
    }))
      return
    setIds(saved.ids, false)
    Qt.callLater(reconcileMatches)
  }
  function reconcileMatches() {
    // An empty report is also the parent's transient loading/closed state.
    // Retain its saved selection, but require current matches before use.
    if (initialized && available && validMatches(matches) && matches.length > 0)
      setIds(currentIds, true)
  }
  function clearSelection() {
    setIds([], false)
    expanded = false
    invalidatePreview()
    if (initialized)
      saveSelection()
  }
  function invalidatePreview() {
    serial++
    preview = null
    loading = false
    notice = ""
    delay.stop()
    if (initialized && active && currentIds.length > 0)
      delay.restart()
  }
  function toggleWord(id) {
    if (!active || controller.busy || !words.some(function (word) {
      return word.id === id
    }))
      return
    var next = currentIds.slice(), index = next.indexOf(id)
    if (index >= 0)
      next.splice(index, 1)
    else if (next.length < 20)
      next.push(id)
    setIds(next, true)
  }
  function projected(data, text, ids, epoch) {
    if (!data || data.text !== text || data.data_epoch !== epoch || typeof epoch !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(epoch) || data.scope !== "ungraded_practice" || data.effect !== "preview_only" || data.protection_complete !== true || typeof data.trail_truncated !== "boolean" || typeof data.can_start !== "boolean" || typeof data.requires_practice_choice !== "boolean" || JSON.stringify(data.subject_ids) !== JSON.stringify(ids) || data.total !== ids.length || !Number.isInteger(data.ready_count) || !Array.isArray(data.items) || data.items.length !== ids.length)
      return null
    var saved = data.saved_practice
    if (!saved || typeof saved.present !== "boolean" || typeof saved.valid !== "boolean" || data.requires_practice_choice !== saved.present)
      return null
    if (!saved.present && (!saved.valid || saved.completed !== 0 || saved.total !== 0 || saved.revision !== null))
      return null
    if (saved.present && saved.valid && (!Number.isInteger(saved.completed) || !Number.isInteger(saved.total) || saved.completed < 0 || saved.completed >= saved.total || saved.total > 20 || !Number.isSafeInteger(saved.revision) || saved.revision < 0))
      return null
    if (!saved.valid && (!saved.present || saved.completed !== null || saved.total !== null || saved.revision !== null))
      return null
    var items = []
    for (var index = 0; index < ids.length; index++) {
      var item = data.items[index], word = words.find(function (candidate) {
        return candidate.id === ids[index]
      })
      if (!item || !word || item.id !== ids[index] || item.characters !== word.characters || item.type !== word.type || item.level !== word.level || ["Learned", "Not started", "Paused graded work", "Waiting to sync", "Needs attention"].indexOf(item.state) < 0 || typeof item.ready !== "boolean" || ["ready", "protected_study", "content_unavailable"].indexOf(item.reason) < 0 || item.ready !== (item.reason === "ready") || (item.reason === "protected_study") !== (item.state === "Paused graded work"))
        return null
      items.push({
        id: item.id,
        type: item.type,
        level: item.level,
        characters: item.characters,
        state: item.state,
        ready: item.ready,
        reason: item.reason
      })
    }
    var count = items.filter(function (item) {
      return item.ready
    }).length
    if (data.ready_count !== count || (data.can_start && (count !== ids.length || !saved.valid)))
      return null
    return {
      text: text,
      subject_ids: ids.slice(),
      data_epoch: epoch,
      items: items,
      total: ids.length,
      ready_count: count,
      can_start: data.can_start,
      trail_truncated: data.trail_truncated,
      protection_complete: true,
      saved_practice: {
        present: saved.present,
        valid: saved.valid,
        completed: saved.completed,
        total: saved.total,
        revision: saved.revision
      },
      requires_practice_choice: saved.present,
      scope: "ungraded_practice",
      effect: "preview_only"
    }
  }
  function fetchPreview() {
    if (!active || currentIds.length < 1 || currentIds.length > 20)
      return
    var request = ++serial, owner = controller, backend = service, context = contextKey, selection = selectionKey, text = passage, ids = currentIds.slice(), epoch = snapshot.session_epoch
    loading = true
    backend.request("trail_practice_preview", {
      text: text,
      subject_ids: ids
    }, function (ok, data) {
      if (!root || request !== root.serial || !root.active || owner !== root.controller || backend !== root.service || context !== root.contextKey || selection !== root.selectionKey)
        return
      root.loading = false
      var result = ok ? root.projected(data, text, ids, epoch) : null
      root.preview = result
      if (!result)
        root.notice = "These words could not be checked. Try checking the selection again."
    })
  }
  function startSelected() {
    if (!canStart)
      return
    var result = projected(preview, passage, currentIds, snapshot.session_epoch)
    if (!result || !result.can_start)
      return
    startRequested(result, result.requires_practice_choice)
  }
  function resumeEarlier() {
    if (active && !controller.busy && preview && preview.saved_practice.present && preview.saved_practice.valid)
      controller.begin("practice", 5)
  }
  function focusInput() {
    if (!available)
      return
    if (expanded && choices.count > 0)
      choices.itemAt(0).forceActiveFocus(Qt.TabFocusReason)
    else
      disclosure.forceActiveFocus(Qt.TabFocusReason)
  }
  onPassageChanged: if (initialized)
    clearSelection()
  onContentAccessChanged: if (initialized)
    clearSelection()
  onSavedSelectionChanged: if (initialized) {
    var owner = controller, access = contentAccess, text = passage
    Qt.callLater(function () {
      if (root && root.controller === owner && root.contentAccess === access && root.passage === text)
        root.restoreSelection()
    })
  }
  onMatchesChanged: {
    invalidatePreview()
    if (initialized)
      Qt.callLater(reconcileMatches)
  }
  onSelectionKeyChanged: invalidatePreview()
  onContextKeyChanged: invalidatePreview()
  onServiceChanged: invalidatePreview()
  onControllerChanged: invalidatePreview()
  onActiveChanged: {
    invalidatePreview()
    if (initialized)
      Qt.callLater(reconcileMatches)
  }
  Component.onCompleted: {
    initialized = true
    restoreSelection()
    Qt.callLater(reconcileMatches)
  }
  Component.onDestruction: serial++
  Timer {
    id: delay
    interval: 140
    onTriggered: root.fetchPreview()
  }

  Action {
    id: disclosure
    objectName: "trail-practice-choose"
    text: root.expanded ? "Hide practice choices" : "Choose words to practise"
    selected: root.expanded
    enabled: root.available
    Accessible.checkable: true
    Accessible.checked: selected
    onClicked: root.expanded = !root.expanded
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.expanded
    spacing: Style.space(10)
    Label {
      Layout.fillWidth: true
      text: "Choose up to 20 words for ungraded practice. Your review and lesson sessions stay saved."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "trail-practice-count"
      Layout.fillWidth: true
      text: root.currentIds.length + " / 20 selected"
      font.bold: true
    }
    Flow {
      id: wordFlow
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        id: choices
        model: root.words
        Action {
          id: wordButton
          required property var modelData
          objectName: "trail-practice-word-" + modelData.id
          width: Math.min(implicitWidth, wordFlow.width)
          text: fitted.elidedText
          accessibleName: modelData.characters + " · " + modelData.state
          accessibleHint: "Choose this word for ungraded practice"
          tooltipText: accessibleName
          selected: root.currentIds.indexOf(modelData.id) >= 0
          enabled: root.active && !root.controller.busy && (selected || root.currentIds.length < 20)
          Accessible.checkable: true
          Accessible.checked: selected
          onClicked: root.toggleWord(modelData.id)
          TextMetrics {
            id: fitted
            text: wordButton.modelData.characters
            font.family: wordButton.fontFamily
            font.pixelSize: wordButton.fontSize
            elide: Qt.ElideRight
            elideWidth: Math.max(24, wordFlow.width - wordButton.horizontalPadding * 2 - 8)
          }
        }
      }
    }
    Label {
      Layout.fillWidth: true
      visible: root.words.length === 0
      text: "No words are selectable yet. Words in unfinished graded study remain protected."
      secondary: true
    }
    Label {
      Layout.fillWidth: true
      visible: root.loading || root.notice !== ""
      text: root.loading ? "Checking cached study content…" : root.notice
      secondary: true
    }
    Label {
      objectName: "trail-practice-readiness"
      Layout.fillWidth: true
      visible: root.preview !== null
      text: root.preview ? root.preview.ready_count + " / " + root.preview.total + " selected words ready offline" : ""
      font.bold: true
    }
    Repeater {
      model: root.preview ? root.preview.items.filter(function (item) {
        return !item.ready
      }) : []
      Label {
        required property var modelData
        Layout.fillWidth: true
        text: modelData.characters + " · " + (modelData.reason === "protected_study" ? "Saved graded study protects this word" : "Required study text is not cached")
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
    }
    Label {
      Layout.fillWidth: true
      visible: root.preview !== null && root.preview.trail_truncated
      text: "This trail is partial. Only the words you selected will enter practice."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "trail-practice-replacement"
      Layout.fillWidth: true
      visible: root.preview !== null && root.preview.saved_practice.present
      text: root.preview && root.preview.saved_practice.valid ? "Your earlier ungraded practice is saved. Starting this selection replaces that practice session; graded work stays saved." : "Your earlier practice needs a refresh before it can be resumed or replaced."
      secondary: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        objectName: "trail-practice-start"
        text: root.preview && root.preview.saved_practice.present ? "Start new practice" : "Start selected practice"
        selected: true
        enabled: root.canStart
        onClicked: root.startSelected()
      }
      Action {
        objectName: "trail-practice-resume"
        visible: root.preview !== null && root.preview.saved_practice.present
        text: "Resume earlier practice"
        enabled: root.active && !root.controller.busy && root.preview !== null && root.preview.saved_practice.valid
        onClicked: root.resumeEarlier()
      }
      Action {
        objectName: "trail-practice-check"
        visible: root.notice !== ""
        text: "Check selection again"
        enabled: root.active && !root.loading && root.currentIds.length > 0
        onClicked: root.invalidatePreview()
      }
      Action {
        objectName: "trail-practice-clear"
        text: "Clear selection"
        enabled: root.active && !root.controller.busy && root.currentIds.length > 0
        onClicked: root.setIds([], true)
      }
    }
  }
}
