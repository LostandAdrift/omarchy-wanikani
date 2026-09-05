pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import "UnicodeText.mjs" as UnicodeText

ColumnLayout {
  id: root
  objectName: "wanikani-reading-trail"
  required property var controller
  readonly property var service: controller.service
  readonly property string query: controller.query || ""
  readonly property bool eligible: UnicodeText.characters(query).length > 1 && UnicodeText.characters(query).some(function (character) {
    var point = character.codePointAt(0)
    return point >= 0x3040 && point <= 0x30ff || point >= 0x3400 && point <= 0x9fff || point >= 0xf900 && point <= 0xfaff || point >= 0x20000 && point <= 0x323af || point === 0x3005
  })
  readonly property bool active: eligible && controller.opened && controller.view === "lookup" && !controller.detail && controller.service && controller.service.ready && !controller.service.locked
  readonly property string contentKey: JSON.stringify([controller.contentAccess || "", controller.snapshot ? controller.snapshot.last_sync || "" : "", controller.snapshot ? controller.snapshot.session_revision || 0 : 0, controller.snapshot ? controller.snapshot.state_revision : null, controller.snapshot ? controller.snapshot.pending : null, controller.snapshot ? controller.snapshot.attention : null, controller.snapshot ? controller.snapshot.syncing : null, controller.snapshot ? controller.snapshot.status : null])
  property var report: null
  property var selectedIds: []
  property bool wordsExpanded: false
  property bool loading: false
  property bool fetching: false
  property int inFlight: -1
  property bool dirty: true
  property bool initialized: false
  property int serial: 0
  property string notice: ""
  readonly property var matches: report ? report.matches : []
  readonly property var visibleMatches: selectedIds.length ? matches.filter(function (word) {
    return root.selectedIds.indexOf(word.id) >= 0
  }) : wordsExpanded ? matches : matches.slice(0, 8)
  visible: eligible && !controller.detail
  spacing: Style.space(10)

  function invalidate() {
    serial++
    dirty = true
    loading = false
    report = null
    selectedIds = []
    wordsExpanded = false
    notice = ""
    settle.stop()
    if (!active) {
      fetching = false
      inFlight = -1
    }
    if (active && initialized)
      settle.restart()
  }
  function loadTrail() {
    if (!active || !dirty || fetching || settle.running)
      return
    var expected = serial
    var text = query
    var owner = service
    dirty = false
    fetching = true
    inFlight = expected
    loading = true
    owner.request("reading_trail", {
      text: text
    }, function (ok, data, message) {
      if (!root || root.inFlight !== expected || root.service !== owner)
        return
      root.fetching = false
      root.inFlight = -1
      if (root.active && expected === root.serial && root.query === text) {
        root.loading = false
        if (ok && root.validReport(data, text))
          root.report = data
        else
          root.notice = message || "The reading trail could not be loaded. Try this selection again."
      }
      if (root.active && root.dirty && !settle.running)
        Qt.callLater(root.loadTrail)
    })
  }
  function validReport(data, text) {
    return data && data.text === text && Array.isArray(data.segments) && data.segments.length <= 512 && Array.isArray(data.matches) && data.matches.length <= 60 && data.matches.every(function (word) {
      return word && Number.isSafeInteger(word.id) && word.id > 0 && typeof word.characters === "string" && typeof word.state === "string" && typeof word.can_open === "boolean"
    }) && data.segments.every(function (segment) {
      return segment && typeof segment.text === "string" && segment.text.length > 0 && Array.isArray(segment.subject_ids) && segment.subject_ids.length <= 60 && segment.subject_ids.every(function (id) {
        return Number.isSafeInteger(id) && id > 0 && data.matches.some(function (word) {
          return word.id === id && word.characters === segment.text
        })
      })
    }) && data.segments.map(function (segment) {
      return segment.text
    }).join("") === text
  }
  function wordFor(id) {
    for (var index = 0; index < matches.length; index++)
      if (matches[index].id === id)
        return matches[index]
    return null
  }
  function openSubject(id) {
    var word = wordFor(id)
    if (active && word && word.can_open === true)
      controller.showSubject(id)
  }
  function escaped(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;")
  }
  function passageHtml() {
    if (!report)
      return ""
    // RichText can ignore Text.linkColor. QColor supplies trusted theme CSS.
    var accent = Color.accent.toString()
    return '<span style="white-space:pre-wrap">' + report.segments.map(function (segment, index) {
      var text = root.escaped(segment.text)
      var openable = segment.subject_ids.some(function (id) {
        var word = root.wordFor(id)
        return word && word.can_open === true
      })
      return openable ? '<a href="span:' + index + '" style="color:' + accent + '">' + text + '</a>' : text
    }).join("") + '</span>'
  }
  function activateLink(link) {
    if (!active || !report || !/^span:[0-9]+$/.test(link))
      return
    var index = Number(link.slice(5))
    if (!Number.isSafeInteger(index) || index >= report.segments.length)
      return
    var ids = report.segments[index].subject_ids
    if (ids.length === 1)
      openSubject(ids[0])
    else if (ids.some(function (id) {
      var word = root.wordFor(id)
      return word && word.can_open === true
    }))
      selectedIds = ids
  }
  onQueryChanged: invalidate()
  onContentKeyChanged: invalidate()
  onServiceChanged: {
    fetching = false
    inFlight = -1
    invalidate()
  }
  onActiveChanged: invalidate()
  Component.onCompleted: {
    initialized = true
    invalidate()
  }
  Component.onDestruction: serial++
  Timer {
    id: settle
    interval: 140
    onTriggered: root.loadTrail()
  }

  Label {
    Layout.fillWidth: true
    text: "Words in your selection"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "WaniKani catalogue matches. Select a linked word to explore it; this is not a translation."
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
  Card {
    Layout.fillWidth: true
    Layout.preferredHeight: passage.implicitHeight + Style.space(24)
    visible: root.report !== null
    Text {
      id: passage
      objectName: "reading-trail-passage"
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(12)
      text: root.passageHtml()
      textFormat: Text.RichText
      wrapMode: Text.Wrap
      font.family: "Noto Sans CJK JP"
      font.pixelSize: Style.font.title
      color: Color.foreground
      linkColor: Color.accent
      renderType: Text.NativeRendering
      Accessible.role: Accessible.StaticText
      Accessible.name: root.report ? root.report.text : ""
      Accessible.ignored: !visible || !root.report
      onLinkActivated: link => root.activateLink(link)
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.loading || root.notice !== "" || root.report !== null && root.matches.length === 0
    text: root.loading ? "Finding words in your cached catalogue…" : root.notice || "No matching words are cached for this selection."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  Label {
    Layout.fillWidth: true
    visible: root.selectedIds.length > 1
    text: "This text matches more than one subject. Choose one below."
    font.pixelSize: Style.font.bodySmall
  }
  Flow {
    id: words
    Layout.fillWidth: true
    spacing: Style.space(6)
    Repeater {
      model: root.visibleMatches.length
      Action {
        id: wordButton
        required property int index
        readonly property var word: root.visibleMatches[index] || ({
            id: 0,
            characters: "",
            state: "",
            can_open: false
          })
        readonly property int subjectId: word.id
        width: Math.min(implicitWidth, words.width)
        text: wordLabel.elidedText
        enabled: root.active && word.can_open === true
        accessibleName: word.characters + " · " + word.state
        accessibleHint: word.can_open ? "Open this WaniKani subject" : "Available after unfinished graded study is complete"
        tooltipText: accessibleName
        onClicked: root.openSubject(subjectId)
        TextMetrics {
          id: wordLabel
          text: wordButton.word.characters + " · " + wordButton.word.state
          font.family: wordButton.fontFamily
          font.pixelSize: wordButton.fontSize
          elide: Qt.ElideRight
          elideWidth: Math.max(24, words.width - wordButton.horizontalPadding * 2 - 8)
        }
      }
    }
  }
  Action {
    objectName: "reading-trail-more"
    visible: root.selectedIds.length === 0 && root.matches.length > 8
    text: root.wordsExpanded ? "Show fewer words" : "Show all " + root.matches.length + " words"
    onClicked: root.wordsExpanded = !root.wordsExpanded
  }
  TrailPractice {
    objectName: "reading-trail-practice"
    Layout.fillWidth: true
    visible: root.report !== null && root.matches.length > 0
    controller: root.controller
    passage: root.query
    matches: root.matches
    savedSelection: root.controller.trailPracticeSelection || ({})
    onSelectionSaved: state => root.controller.trailPracticeSelection = state
    onStartRequested: (preview, replacePractice) => root.controller.beginTrailPractice(preview, replacePractice)
  }
  Action {
    visible: root.selectedIds.length > 0
    text: "Show all matching words"
    onClicked: {
      root.selectedIds = []
      root.wordsExpanded = true
    }
  }
  Label {
    Layout.fillWidth: true
    visible: root.report !== null && root.report.truncated === true
    text: "A partial local trail is shown. Try a shorter selection for more matches."
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
}
