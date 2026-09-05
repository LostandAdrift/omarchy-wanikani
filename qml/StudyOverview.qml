import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  required property string mode
  readonly property bool lessons: mode === "lessons"
  readonly property var snapshot: controller.snapshot || ({})
  property var discoveredSaved: null
  readonly property var saved: (snapshot.saved_sessions ? snapshot.saved_sessions[mode] : null) || (lessons ? discoveredSaved : null)
  readonly property int available: lessons ? snapshot.lessons || 0 : snapshot.reviews || 0
  readonly property bool active: visible && controller.opened === true && !!controller.service && controller.service.ready === true && controller.service.locked !== true
  readonly property bool canDiscover: lessons && active && !saved
  readonly property bool studyAllowed: active && !controller.busy && snapshot.vacation !== true && snapshot.status !== "clock_changed"
  readonly property string contextKey: JSON.stringify([controller.contentAccess || "", snapshot.last_sync, snapshot.session_epoch, snapshot.session_revision, snapshot.pending, snapshot.attention, snapshot.saved_sessions, snapshot.max_level])
  property int batch: 5
  property string subjectType: "all"
  property int offset: 0
  readonly property int pageSize: 12
  property var catalogue: ({
      items: [],
      counts: {},
      total: 0,
      has_more: false,
      complete: true
    })
  property var selectedItems: []
  readonly property var selectedIds: selectedItems.map(function (item) {
    return item.id
  })
  property bool initialized: false
  property bool loading: false
  property bool fetching: false
  property bool dirty: true
  property int pageSerial: 0
  property bool previewing: false
  property bool previewFetching: false
  property bool previewDirty: false
  property bool recommendation: false
  property bool previewReady: false
  property int previewSerial: 0
  property string notice: ""
  property string selectionNotice: ""
  spacing: Style.space(16)

  function focusInput() {
    if (saved)
      resumeAction.forceActiveFocus(Qt.TabFocusReason)
    else if (lessons)
      recommendAction.forceActiveFocus(Qt.TabFocusReason)
    else
      reviewAction.forceActiveFocus(Qt.TabFocusReason)
  }
  function invalidate(clear) {
    pageSerial++
    previewSerial++
    loading = false
    previewing = false
    previewReady = false
    previewDirty = false
    pageDelay.stop()
    previewDelay.stop()
    dirty = true
    if (clear) {
      catalogue = {
        items: [],
        counts: {},
        total: 0,
        has_more: false,
        complete: true
      }
      selectedItems = []
      discoveredSaved = null
      offset = 0
      notice = ""
      selectionNotice = ""
    }
    if (initialized && canDiscover) {
      pageDelay.restart()
      if (selectedItems.length)
        queuePreview(false)
    }
  }
  function loadPage(next, type) {
    offset = Math.max(0, next || 0)
    if (type !== undefined)
      subjectType = type
    pageSerial++
    dirty = true
    notice = ""
    if (canDiscover)
      pageDelay.restart()
  }
  function validCard(item) {
    return item && Number.isSafeInteger(item.id) && item.id > 0 && Number.isInteger(item.level) && item.level >= 1 && item.level <= (snapshot.max_level || 0) && ["radical", "kanji", "vocabulary", "kana_vocabulary"].indexOf(item.type) >= 0 && (typeof item.characters === "string" || item.characters === null) && Array.isArray(item.meanings) && item.meanings.every(function (value) {
      return typeof value === "string"
    }) && Array.isArray(item.images) && typeof item.ready === "boolean"
  }
  function validCounts(counts) {
    return counts && ["radical", "kanji", "vocabulary", "kana_vocabulary"].every(function (type) {
      return Number.isInteger(counts[type]) && counts[type] >= 0
    })
  }
  function uniqueCards(cards) {
    return cards.every(function (item, index) {
      return cards.findIndex(function (other) {
        return other.id === item.id
      }) === index
    })
  }
  function fetchPage() {
    if (!initialized || !canDiscover || !dirty || fetching)
      return
    dirty = false
    fetching = true
    loading = true
    var serial = pageSerial
    var context = contextKey
    var start = offset
    var type = subjectType
    controller.service.request("lesson_catalogue", {
      subject_type: type,
      offset: start,
      limit: pageSize
    }, function (ok, data, message) {
      if (!root)
        return
      root.fetching = false
      if (root.canDiscover && serial === root.pageSerial && context === root.contextKey) {
        root.loading = false
        if (ok && data && data.offset === start && data.subject_type === type && Array.isArray(data.items) && data.items.length <= root.pageSize && data.items.every(root.validCard) && root.uniqueCards(data.items) && root.validCounts(data.counts) && Number.isInteger(data.total) && data.total >= 0 && typeof data.complete === "boolean" && typeof data.has_more === "boolean" && (!data.has_more || data.next_offset === start + root.pageSize)) {
          root.catalogue = data
          root.discoveredSaved = data.saved_session || null
          root.notice = data.message || ""
        } else {
          root.catalogue = {
            items: [],
            counts: {},
            total: 0,
            has_more: false,
            complete: true
          }
          root.notice = message || "Lessons could not be loaded. Try again after refreshing your account."
        }
      }
      if (root.canDiscover && root.dirty && !pageDelay.running)
        pageDelay.restart()
    })
  }
  function toggleSubject(item) {
    if (!canDiscover || controller.busy)
      return
    var next = selectedItems.slice()
    var index = selectedIds.indexOf(item.id)
    if (index >= 0)
      next.splice(index, 1)
    else if (item.ready && next.length < 20)
      next.push(item)
    else
      return
    selectedItems = next
    queuePreview(false)
  }
  function clearSelection() {
    selectedItems = []
    queuePreview(false)
  }
  function queuePreview(recommended) {
    previewSerial++
    previewReady = false
    selectionNotice = ""
    recommendation = recommended
    previewDirty = recommended || selectedItems.length > 0
    previewing = previewDirty
    previewDelay.stop()
    if (canDiscover && previewDirty)
      previewDelay.restart()
  }
  function fetchPreview() {
    if (!canDiscover || !previewDirty || previewFetching)
      return
    previewDirty = false
    previewFetching = true
    previewing = true
    var serial = previewSerial
    var context = contextKey
    var ids = selectedIds.slice()
    var recommend = recommendation
    var args = {
      limit: recommend ? batch : ids.length
    }
    if (!recommend)
      args.subject_ids = ids
    controller.service.request("lesson_preview", args, function (ok, data, message) {
      if (!root)
        return
      root.previewFetching = false
      if (root.canDiscover && serial === root.previewSerial && context === root.contextKey) {
        root.previewing = false
        if (ok && data && data.resume_required && data.saved_session) {
          root.discoveredSaved = data.saved_session
          root.selectedItems = []
        } else if (ok && data && Array.isArray(data.batch) && data.batch.length <= 20 && data.batch.every(root.validCard) && (recommend || JSON.stringify(data.batch.map(function (item) {
            return item.id
          })) === JSON.stringify(ids))) {
          root.selectedItems = data.batch
          root.previewReady = data.batch.length > 0 && data.batch.every(function (item) {
            return item.ready
          })
          root.selectionNotice = data.message || ""
        } else {
          root.selectionNotice = message || "This selection could not be checked. Refresh the list and choose again."
        }
      }
      if (root.canDiscover && root.previewDirty && !previewDelay.running)
        previewDelay.restart()
    })
  }
  function startLessons() {
    if (canDiscover && studyAllowed && previewReady && selectedIds.length > 0 && selectedIds.length <= 20)
      controller.begin("lessons", selectedIds.length, selectedIds.slice())
  }
  function typeLabel(type) {
    return type === "radical" ? "Radical" : type === "kanji" ? "Kanji" : type === "kana_vocabulary" ? "Kana vocabulary" : "Vocabulary"
  }
  function prerequisiteText(item) {
    var parts = (item.prerequisites || []).slice(0, 60).map(function (part) {
      return (part.characters || "Image radical") + " · " + part.state
    })
    return parts.length ? "Uses: " + parts.join("; ") : "Unlocked by WaniKani"
  }
  onContextKeyChanged: if (initialized)
    invalidate(true)
  onActiveChanged: if (initialized)
    invalidate(false)
  onSavedChanged: if (initialized)
    invalidate(false)
  onCanDiscoverChanged: if (initialized)
    invalidate(false)
  onModeChanged: if (initialized)
    invalidate(true)
  Component.onCompleted: {
    initialized = true
    invalidate(false)
  }
  Component.onDestruction: {
    pageSerial++
    previewSerial++
  }
  Timer {
    id: pageDelay
    interval: 100
    onTriggered: root.fetchPage()
  }
  Timer {
    id: previewDelay
    interval: 140
    onTriggered: root.fetchPreview()
  }

  Label {
    Layout.fillWidth: true
    text: root.lessons ? "Learn something new." : "Recall what you have learned."
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.lessons ? "Choose new subjects to explore. Learn their meanings, readings, and examples, then start the lesson quiz when you are ready." : "Reviews test subjects you have already learned. Finish each subject’s required meaning and reading before it counts as complete."
  }
  Card {
    Layout.fillWidth: true
    Layout.preferredHeight: savedContent.implicitHeight + Style.space(28)
    visible: !!root.saved
    ColumnLayout {
      id: savedContent
      anchors.fill: parent
      anchors.margins: Style.space(14)
      Label {
        Layout.fillWidth: true
        text: root.lessons ? "Your lessons are saved" : "Your reviews are saved"
        font.bold: true
      }
      Label {
        Layout.fillWidth: true
        text: root.saved ? root.saved.completed + " of " + root.saved.total + " subjects completed · " + (root.saved.phase === "lesson" ? "Learning" : root.lessons ? "Lesson quiz" : "Reviewing") : ""
      }
      Action {
        id: resumeAction
        text: root.lessons ? "Resume lessons →" : "Resume reviews →"
        selected: true
        enabled: root.studyAllowed
        onClicked: root.controller.begin(root.mode)
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.snapshot.vacation === true || root.snapshot.status === "clock_changed"
    text: root.snapshot.vacation ? "Vacation mode is on. Your saved study will be here when you return." : "Refresh your account to verify the system clock before graded study."
    textColor: Color.accent
  }
  Label {
    Layout.fillWidth: true
    text: root.available + (root.lessons ? (root.available === 1 ? " lesson available" : " lessons available") : (root.available === 1 ? " review due" : " reviews due"))
    font.pixelSize: Style.space(30)
    textColor: Color.accent
  }
  Label {
    Layout.fillWidth: true
    visible: !root.saved && root.available === 0
    text: root.lessons ? "No new lessons are ready. Reviews move your subjects toward their next unlock." : "You are caught up. Your next scheduled reviews appear on Today."
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: !root.lessons && !root.saved && root.available > 0
    spacing: Style.space(10)
    Label {
      text: "Subjects in this batch"
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Repeater {
        model: [5, 10, 20]
        Action {
          required property int modelData
          text: String(modelData)
          selected: root.batch === modelData
          onClicked: root.batch = modelData
        }
      }
    }
    Action {
      id: reviewAction
      text: "Review " + Math.min(root.batch, root.available) + (Math.min(root.batch, root.available) === 1 ? " subject →" : " subjects →")
      selected: true
      enabled: root.studyAllowed
      onClicked: root.controller.begin(root.mode, root.batch)
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.lessons && !root.saved
    spacing: Style.space(12)
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: [
          {
            key: "all",
            label: "All"
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
          text: modelData.label + " · " + (modelData.key === "all" ? Object.values(root.catalogue.counts).reduce(function (a, b) {
              return a + b
            }, 0) : root.catalogue.counts[modelData.key] || 0)
          selected: root.subjectType === modelData.key
          enabled: root.active
          onClicked: root.loadPage(0, modelData.key)
        }
      }
    }
    Label {
      Layout.fillWidth: true
      text: "Recommended order follows your level and WaniKani lesson order. Or choose 1–20 subjects below."
      secondary: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: [5, 10, 20]
        Action {
          required property int modelData
          text: String(modelData)
          selected: root.batch === modelData
          onClicked: root.batch = modelData
        }
      }
      Action {
        id: recommendAction
        text: "Preview recommended"
        enabled: root.canDiscover && !root.controller.busy && !root.previewing
        onClicked: root.queuePreview(true)
      }
    }
    Card {
      Layout.fillWidth: true
      Layout.preferredHeight: selectionContent.implicitHeight + Style.space(24)
      ColumnLayout {
        id: selectionContent
        anchors.fill: parent
        anchors.margins: Style.space(12)
        spacing: Style.space(8)
        Label {
          Layout.fillWidth: true
          text: root.selectedItems.length + " / 20 selected · your lesson order"
          font.bold: true
        }
        Label {
          Layout.fillWidth: true
          visible: !root.selectedItems.length
          text: "Preview a recommended batch, or add subjects below."
          secondary: true
        }
        Repeater {
          model: root.selectedItems
          RowLayout {
            id: selectedRow
            Layout.fillWidth: true
            required property var modelData
            required property int index
            Label {
              Layout.fillWidth: true
              text: (selectedRow.index + 1) + ". " + (selectedRow.modelData.characters || "Image radical") + " · " + selectedRow.modelData.meanings.join(", ")
            }
            Action {
              text: "Remove"
              accessibleName: "Remove lesson " + (selectedRow.index + 1)
              enabled: root.canDiscover && !root.controller.busy
              onClicked: root.toggleSubject(selectedRow.modelData)
            }
          }
        }
        Label {
          Layout.fillWidth: true
          visible: root.previewing || !!root.selectionNotice
          text: root.previewing ? "Checking your lesson preview…" : root.selectionNotice
          secondary: true
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(8)
          Action {
            objectName: "start-selected-lessons"
            text: "Start " + root.selectedItems.length + (root.selectedItems.length === 1 ? " lesson →" : " lessons →")
            selected: true
            enabled: root.studyAllowed && root.previewReady && !root.previewing && root.selectedItems.length > 0
            onClicked: root.startLessons()
          }
          Action {
            text: "Clear selection"
            visible: root.selectedItems.length > 0
            enabled: !root.controller.busy
            onClicked: root.clearSelection()
          }
        }
        Label {
          Layout.fillWidth: true
          text: "Starts lesson discovery. The quiz begins only when you choose it."
          font.pixelSize: Style.font.bodySmall
          secondary: true
        }
      }
    }
    RowLayout {
      Layout.fillWidth: true
      Label {
        Layout.fillWidth: true
        text: root.loading ? "Loading lessons…" : root.catalogue.total + " eligible" + (root.catalogue.complete === false ? " · partial count" : "") + " · choose from the cached list"
        secondary: true
      }
      Action {
        text: "Reload list"
        enabled: root.canDiscover && !root.loading
        onClicked: root.loadPage(root.offset)
      }
    }
    Label {
      Layout.fillWidth: true
      visible: !!root.notice
      text: root.notice
      textColor: Color.accent
    }
    Label {
      Layout.fillWidth: true
      visible: !root.loading && !root.catalogue.items.length
      text: "No eligible subjects in this list. Paused graded prompts and results waiting to sync are kept out of new lessons."
      secondary: true
    }
    Repeater {
      model: root.catalogue.items
      Card {
        id: lessonCard
        required property var modelData
        required property int index
        Layout.fillWidth: true
        Layout.preferredHeight: lessonContent.implicitHeight + Style.space(24)
        ColumnLayout {
          id: lessonContent
          anchors.fill: parent
          anchors.margins: Style.space(12)
          spacing: Style.space(6)
          RowLayout {
            Layout.fillWidth: true
            SubjectGlyph {
              Layout.preferredWidth: Style.space(66)
              Layout.preferredHeight: Style.space(66)
              // Repeater roles wrap nested arrays; keep the original cached
              // image list and reject a stale delegate during page changes.
              subject: root.catalogue.items[lessonCard.index] && root.catalogue.items[lessonCard.index].id === lessonCard.modelData.id ? root.catalogue.items[lessonCard.index] : null
              pixelSize: Style.space(42)
            }
            ColumnLayout {
              Layout.fillWidth: true
              Label {
                Layout.fillWidth: true
                text: root.typeLabel(lessonCard.modelData.type) + " · Level " + lessonCard.modelData.level
                font.pixelSize: Style.font.bodySmall
                secondary: true
              }
              Label {
                Layout.fillWidth: true
                text: lessonCard.modelData.meanings.join(", ")
                font.bold: true
              }
            }
          }
          Label {
            Layout.fillWidth: true
            text: lessonCard.modelData.cache_note || (lessonCard.modelData.ready ? "Ready offline" : "Required content is not cached")
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            Layout.fillWidth: true
            text: root.prerequisiteText(lessonCard.modelData)
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
          Action {
            text: root.selectedIds.indexOf(lessonCard.modelData.id) >= 0 ? "✓ Added · " + (root.selectedIds.indexOf(lessonCard.modelData.id) + 1) : "Add to lessons"
            accessibleName: (root.selectedIds.indexOf(lessonCard.modelData.id) >= 0 ? "Remove " : "Add ") + root.typeLabel(lessonCard.modelData.type) + " " + lessonCard.modelData.meanings.join(", ")
            selected: root.selectedIds.indexOf(lessonCard.modelData.id) >= 0
            enabled: root.canDiscover && !root.controller.busy && (selected || lessonCard.modelData.ready && root.selectedItems.length < 20)
            onClicked: root.toggleSubject(lessonCard.modelData)
          }
        }
      }
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        text: "Previous lessons"
        enabled: root.offset > 0 && !root.loading
        onClicked: root.loadPage(Math.max(0, root.offset - root.pageSize))
      }
      Action {
        text: "More lessons"
        enabled: root.catalogue.has_more === true && !root.loading
        onClicked: root.loadPage(root.catalogue.next_offset)
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.lessons ? "Learn → Lesson quiz → Scheduled reviews. You choose when to start the quiz." : "Another batch is always optional. Escape saves your exact place and returns to work."
    font.pixelSize: Style.font.bodySmall
  }
  Action {
    text: root.lessons ? "Open reviews" : "Open lessons"
    onClicked: root.controller.navigate(root.lessons ? "review-overview" : "lesson-overview")
  }
}
