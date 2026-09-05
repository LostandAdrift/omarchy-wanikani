import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import QtMultimedia
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Ui as Ui
import "qml" as Kani
import "vendor/WanaKana.mjs" as Kana
import "qml/UnicodeText.mjs" as UnicodeText
import "qml/Theme.mjs" as Theme

Item {
  id: root
  property var shell: null
  property var manifest: null
  property var service: null
  property bool opened: false
  property string view: "dashboard"
  property bool expanded: false
  property bool busy: false
  property string error: ""
  property var session: null
  property var results: []
  property var detail: null
  property string query: ""
  property bool queryTruncated: false
  property string searchType: "all"
  property string searchState: "all"
  property int searchSequence: 0
  property int navigationSequence: 0
  property int detailSequence: 0
  property bool searching: false
  property string observedSync: ""
  property string helpReturnView: "dashboard"
  property var helpReturnDetail: null
  property var chosenScreen: null
  property bool focusPrimed: false
  property string integrationNotice: ""
  property int audioSequence: 0
  property string audioContext: ""
  property int audioSubjectId: -1
  property string audioState: ""
  property string audioNotice: ""
  readonly property var snapshot: service ? service.snapshot : ({
      settings: {},
      outbox: [],
      difficult: [],
      forecast: [],
      activity: []
    })
  readonly property string pluginId: "io.github.lostandadrift.wanikani"
  readonly property string sessionEpoch: snapshot.session_epoch || ""
  onSessionEpochChanged: session = snapshot.session || null
  readonly property string contentAccess: JSON.stringify([snapshot.demo === true, snapshot.username || "", snapshot.max_level || 0, snapshot.session_epoch || ""])
  onContentAccessChanged: {
    // Presentation caches must not outlive the account or its content grant.
    // Durable answers remain owned by the worker and are revalidated there.
    detail = null
    helpReturnDetail = null
    results = []
    searchSequence++
    searching = false
    stopAudio()
    if (opened && view === "lookup")
      Qt.callLater(function () {
        root.search(root.query)
      })
  }
  readonly property var focusedItem: frame.Window.activeFocusItem
  readonly property bool editingText: isTextEditor(focusedItem)
  readonly property bool composingText: focusedItem && focusedItem.inputMethodComposing === true
  onFocusedItemChanged: Qt.callLater(revealFocus)

  function isTextEditor(item) {
    var candidate = item
    while (candidate && candidate !== frame) {
      if ((candidate as TextInput) || (candidate as TextEdit))
        return true
      candidate = candidate.parent
    }
    return false
  }
  function revealFocus() {
    var item = focusedItem
    var ancestor = item
    while (ancestor && ancestor !== content.item)
      ancestor = ancestor.parent
    var flickable = scroll.contentItem as Flickable
    if (!root.opened || !ancestor || !flickable)
      return
    var point = item.mapToItem(flickable.contentItem, 0, 0)
    var maximum = Math.max(0, flickable.contentHeight - flickable.height)
    if (point.y < flickable.contentY + 8)
      flickable.contentY = Math.max(0, point.y - 8)
    else if (point.y + item.height > flickable.contentY + flickable.height - 8)
      flickable.contentY = Math.min(maximum, point.y + item.height - flickable.height + 8)
  }
  function showHelp() {
    if (view === "help") {
      closeHelp()
      return
    }
    helpReturnView = view
    helpReturnDetail = detail
    navigate("help")
  }
  function closeHelp() {
    navigate(helpReturnView)
    if (helpReturnView === "lookup" && helpReturnDetail)
      showSubject(helpReturnDetail.id)
    helpReturnDetail = null
  }

  function open(payloadJson) {
    var payload = ({})
    try {
      payload = JSON.parse(payloadJson || "{}")
    } catch (_) {}
    var monitor = Hyprland.focusedMonitor
    chosenScreen = Quickshell.screens.find(function (s) {
      return monitor && s.name === monitor.name
    }) || Quickshell.screens[0]
    opened = true
    focusPrimed = false
    focusTimer.restart()
    error = ""
    if (service)
      service.panelOpen = true
    var requested = payload.view || "dashboard"
    if (["reviews", "lessons", "practice", "resume"].indexOf(requested) >= 0)
      begin(requested, payload.limit, payload.subjects)
    else
      navigate(["dashboard", "review-overview", "lesson-overview", "progress", "lookup", "zen", "settings", "help", "practice-library", "recovery"].indexOf(requested) >= 0 ? requested : "dashboard")
    if (requested === "lookup" && payload.selection)
      readSelection()
    else if (requested === "lookup" && typeof payload.text === "string")
      search(payload.text)
  }
  function close() {
    navigationSequence++
    opened = false
    stopAudio()
    if (service) {
      service.panelOpen = false
      service.studying = false
    }
  }
  function dismiss() {
    close()
    if (shell)
      shell.hide(pluginId)
  }
  function navigate(next) {
    stopAudio()
    navigationSequence++
    view = next
    detail = null
    error = ""
    if (service)
      service.studying = next === "study"
    if (service && service.ready && (next === "dashboard" || next === "settings")) {
      // Session-only events keep the question path small. Refresh richer local
      // account summaries when those views are actually requested.
      service.request("snapshot", {}, function (ok, data) {
        if (ok && root.service)
          root.service.applySnapshot(data)
      })
    }
    Qt.callLater(focusContent)
  }
  function focusContent() {
    if (content.item && typeof content.item.focusInput === "function")
      content.item.focusInput()
    else
      todayTab.forceActiveFocus(Qt.TabFocusReason)
  }
  function call(method, args, callback) {
    if (!service)
      return
    busy = true
    error = ""
    service.request(method, args || {}, function (ok, data, message) {
      root.busy = false
      if (!ok)
        root.error = message
      if (callback)
        callback(ok, data)
    })
  }
  function begin(mode, limit, subjects, replacePractice) {
    navigate("study")
    var saved = snapshot.session
    if (mode === "resume" && saved && saved.phase === "complete" && !snapshot.paused_graded && snapshot.reviews === 0) {
      session = saved
      Qt.callLater(focusContent)
      return
    }
    session = null
    call("start", {
      mode: mode,
      limit: limit || snapshot.settings.batch_size || 5,
      subjects: subjects,
      replace_practice: replacePractice === true
    }, function (ok, data) {
      if (ok)
        root.session = data
      Qt.callLater(root.focusContent)
    })
  }
  function studyAction(method, args) {
    call(method, args, function (ok, data) {
      if (ok && (!root.session || Number(data.revision || 0) >= Number(root.session.revision || 0)))
        root.session = data
      Qt.callLater(root.focusContent)
    })
  }
  function search(text) {
    stopAudio()
    var characters = UnicodeText.characters(String(text || ""))
    queryTruncated = characters.length > 256
    query = characters.slice(0, 256).join("")
    detail = null
    refreshSearch()
  }
  function refreshSearch() {
    if (!service || !service.ready || service.locked || !opened || view !== "lookup")
      return
    var expected = ++searchSequence
    searching = true
    service.request("search", {
      text: query,
      filters: {
        type: searchType,
        state: searchState
      },
      reading_query: Kana.isRomaji(query) ? Kana.toHiragana(query, {
        convertLongVowelMark: false
      }) : ""
    }, function (ok, data) {
      if (root.searchSequence === expected && root.opened && root.view === "lookup") {
        root.searching = false
        if (ok)
          root.results = data
      }
    })
  }
  function setSearchFilter(type, state) {
    searchType = type
    searchState = state
    search(query)
  }
  function showSubject(id) {
    stopAudio()
    if (!opened || !service || !service.ready || service.locked)
      return
    // An explicit subject supersedes a new lookup view's queued initial query.
    searchSequence++
    searching = false
    var expectedDetail = ++detailSequence
    var expectedNavigation = navigationSequence
    var expectedSearch = searchSequence
    var expectedAccess = contentAccess
    call("details", {
      subject_id: id
    }, function (ok, data) {
      if (ok && root.opened && root.service && root.service.ready && !root.service.locked && root.detailSequence === expectedDetail && root.navigationSequence === expectedNavigation && root.searchSequence === expectedSearch && root.contentAccess === expectedAccess) {
        root.detail = data
        root.view = "lookup"
        if (root.service)
          root.service.studying = false
      }
    })
  }
  function audioContextCurrent(sequence, navigation, access, studyId, studyRevision) {
    return sequence === audioSequence && navigation === navigationSequence && access === contentAccess
      && opened && service && service.ready && !service.locked
      && (!studyId || (view === "study" && session && session.id === studyId && session.revision === studyRevision))
  }
  function requestAudio(args, method) {
    if (!opened || !service || !service.ready || service.locked)
      return
    stopAudio()
    var sequence = audioSequence
    var navigation = navigationSequence
    var access = contentAccess
    var studyId = args.session_id || ""
    var studyRevision = args.revision
    audioSubjectId = args.subject_id || -1
    audioContext = args.context || "details"
    audioState = "loading"
    audioNotice = "Checking pronunciation…"
    function current() {
      return root.audioContextCurrent(sequence, navigation, access, studyId, studyRevision)
    }
    function receive(ok, data, message) {
      if (!current())
        return
      if (!ok) {
        root.audioState = "failed"
        root.audioNotice = message || "The recording could not be prepared. Try again."
        return
      }
      root.audioSubjectId = data.subject_id || -1
      if (data.status === "not_cached") {
        args.subject_id = data.subject_id
        root.audioNotice = "Downloading this recording for offline playback…"
        root.service.request("pronunciation_prepare", args, function (prepared, clip, error) {
          // A failed download must remain a visible retry, never a retry loop.
          if (current() && prepared && clip.status === "not_cached") {
            root.audioState = "failed"
            root.audioNotice = clip.message || "This recording is not downloaded yet."
          } else {
            receive(prepared, clip, error)
          }
        })
      } else if (data.status === "ready" && data.uri) {
        root.audioNotice = data.voice_fallback ? "Using another downloaded voice for this word." : "Recording ready offline"
        audio.source = data.uri
        audio.play()
      } else {
        root.audioState = "failed"
        root.audioNotice = data.message || "No recording is available for this word."
      }
    }
    service.request(method || "pronunciation", args, receive)
  }
  function play(subject) {
    if (!subject)
      return
    var args = {subject_id: subject.id, context: view === "study" ? "study" : "details"}
    if (view === "study") {
      if (!session || !session.subject || session.subject.id !== subject.id || (session.phase !== "lesson" && !(session.phase === "feedback" && session.feedback && !session.feedback.retry && (session.part === "reading" || subject.type === "kana_vocabulary"))))
        return
      args.session_id = session.id
      args.revision = session.revision
    }
    requestAudio(args)
  }
  function testVoice(actor) {
    requestAudio({context: "voice_test", voice_actor_id: actor}, "pronunciation_sample")
  }
  function stopAudio() {
    audioSequence++
    if (audio)
      audio.stop()
    audioSubjectId = -1
    audioContext = ""
    audioState = ""
    audioNotice = ""
  }
  function readSelection() {
    if (opened && view === "lookup" && !clipboard.running) {
      // An explicit selection request supersedes the view's queued initial search.
      searchSequence++
      searching = false
      clipboard.captured = ""
      clipboard.primary = true
      clipboard.requestNavigation = navigationSequence
      clipboard.requestSearch = searchSequence
      clipboard.requestAccess = contentAccess
      clipboard.running = true
    }
  }
  function desktopIntegration(remove) {
    if (!service || integration.running)
      return
    integrationNotice = ""
    integration.command = ["python3", "-B", service.sourceDir + "tools/integrate.py", remove ? "remove" : "install"]
    integration.running = true
  }
  Process {
    id: integration
    property string result: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: integration.result = text.slice(0, 4096)
    }
    onExited: function (exitCode) {
      root.integrationNotice = exitCode === 0 ? integration.result.trim() || "Desktop integration is up to date." : "Desktop integration could not finish. Existing bindings were preserved; check the dependency guide in the README."
      integration.result = ""
    }
  }
  Process {
    id: clipboard
    property bool primary: true
    property int requestNavigation: -1
    property int requestSearch: -1
    property string requestAccess: ""
    function contextCurrent() {
      return root.opened && root.view === "lookup" && root.navigationSequence === requestNavigation && root.searchSequence === requestSearch && root.contentAccess === requestAccess
    }
    command: primary ? ["wl-paste", "--primary", "--no-newline", "--type", "text"] : ["wl-paste", "--no-newline", "--type", "text"]
    property string captured: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: clipboard.captured = text.slice(0, 4096)
    }
    onExited: {
      if (!contextCurrent()) {
        captured = ""
        return
      }
      if (!captured.trim() && primary) {
        primary = false
        Qt.callLater(function () {
          if (clipboard.contextCurrent())
            clipboard.running = true
        })
      } else {
        root.search(captured)
        captured = ""
        Qt.callLater(root.focusContent)
      }
    }
  }
  MediaPlayer {
    id: audio
    audioOutput: AudioOutput {}
    onPlaybackStateChanged: {
      if (playbackState === MediaPlayer.PlayingState)
        root.audioState = "playing"
      else if (root.audioState === "playing")
        root.audioState = "ready"
    }
    onErrorOccurred: function (error, errorString) {
      root.audioState = "failed"
      root.audioNotice = "Playback failed. Check the output device and try again."
    }
    onMediaStatusChanged: {
      if (mediaStatus === MediaPlayer.EndOfMedia)
        root.audioState = "ready"
    }
  }
  Connections {
    target: root.service
    function onSnapshotChanged() {
      if (root.view === "study")
        root.session = root.snapshot.session || null
      var refreshed = String(root.snapshot.last_sync || "")
      if (refreshed !== root.observedSync) {
        root.observedSync = refreshed
        if (root.opened && root.view === "lookup" && !root.detail)
          root.refreshSearch()
      }
    }
    function onLockedChanged() {
      if (root.service.locked)
        root.dismiss()
    }
  }
  Timer {
    id: focusTimer
    interval: 60
    onTriggered: {
      root.focusPrimed = true
      root.focusContent()
    }
  }

  PanelWindow {
    id: window
    screen: root.chosenScreen
    visible: root.opened
    anchors {
      top: true
      bottom: true
      left: true
      right: true
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-wanikani"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: !root.opened ? WlrKeyboardFocus.None : root.focusPrimed ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.Exclusive
    color: "transparent"
    Rectangle {
      anchors.fill: parent
      color: Qt.alpha(Color.background, 0.55)
    }
    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }
    Ui.BorderSurface {
      id: frame
      anchors.centerIn: parent
      width: Math.min(parent.width - Style.gapsOut * 2, Style.space(root.expanded ? 1060 : 760))
      height: Math.min(parent.height - Style.gapsOut * 2, Style.space(root.expanded ? 920 : 760))
      color: Color.popups.background
      readonly property color kaniSurface: Theme.composite(color, Color.background)
      readonly property color kaniText: Color.popups.text
      borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      MouseArea {
        anchors.fill: parent
      } // consume clicks inside the card
      Keys.onEscapePressed: root.dismiss()
      Shortcut {
        sequence: "F1"
        enabled: root.opened && !root.composingText
        autoRepeat: false
        onActivated: root.showHelp()
      }
      Repeater {
        model: ["dashboard", "study", "lookup", "zen", "settings", "practice-library"]
        Item {
          id: navigationShortcut
          required property string modelData
          required property int index
          Shortcut {
            sequence: "Ctrl+" + (navigationShortcut.index + 1)
            enabled: root.opened && !root.editingText
            autoRepeat: false
            onActivated: navigationShortcut.modelData === "study" ? root.begin("resume") : root.navigate(navigationShortcut.modelData)
          }
        }
      }
      ColumnLayout {
        anchors.fill: parent
        anchors.margins: Style.space(22)
        spacing: Style.space(14)
        RowLayout {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          Kani.Crab {
            Layout.preferredWidth: Style.space(frame.width < Style.space(520) ? 40 : 52)
            Layout.preferredHeight: Style.space(frame.width < Style.space(520) ? 34 : 44)
            animate: root.opened && root.service && root.service.animations
          }
          ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            spacing: 1
            Kani.Label {
              Layout.fillWidth: true
              Layout.minimumWidth: 0
              text: "WaniKani"
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Kani.Label {
              Layout.fillWidth: true
              Layout.minimumWidth: 0
              text: root.snapshot.demo ? "DEMO · Nothing is sent to WaniKani" : "Five reviews, then back to work."
              font.pixelSize: Style.font.bodySmall
              textColor: root.snapshot.demo ? Color.accent : Qt.alpha(Color.foreground, 0.76)
            }
          }
          Kani.Action {
            text: root.expanded ? "Compact" : "Expand"
            onClicked: root.expanded = !root.expanded
          }
          Kani.Action {
            text: frame.width < Style.space(520) ? "Close" : "Close · Esc"
            accessibleName: "Close and keep your saved session"
            accessibleHint: "Also available with Escape"
            onClicked: root.dismiss()
          }
        }
        Flow {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          Layout.preferredWidth: 1
          spacing: Style.space(6)
          Kani.Action {
            id: todayTab
            text: "Today"
            selected: root.view === "dashboard"
            onClicked: root.navigate("dashboard")
          }
          Kani.Action {
            text: "Reviews"
            selected: root.view === "review-overview" || (root.view === "study" && root.session && root.session.mode === "reviews")
            onClicked: root.navigate("review-overview")
          }
          Kani.Action {
            text: "Lessons"
            selected: root.view === "lesson-overview" || (root.view === "study" && root.session && root.session.mode === "lessons")
            onClicked: root.navigate("lesson-overview")
          }
          Kani.Action {
            text: "Progress"
            selected: root.view === "progress"
            onClicked: root.navigate("progress")
          }
          Kani.Action {
            text: "Lookup"
            selected: root.view === "lookup"
            onClicked: root.navigate("lookup")
          }
          Kani.Action {
            text: "Practice"
            selected: root.view === "practice-library"
            onClicked: root.navigate("practice-library")
          }
          Kani.Action {
            text: "Zen"
            selected: root.view === "zen"
            onClicked: root.navigate("zen")
          }
          Kani.Action {
            text: "Settings"
            selected: root.view === "settings"
            onClicked: root.navigate("settings")
          }
          Kani.Action {
            text: "?"
            accessibleName: "Keyboard shortcuts"
            accessibleHint: "Show keyboard help, also available with F1"
            selected: root.view === "help"
            onClicked: root.showHelp()
          }
        }
        Kani.Label {
          Layout.fillWidth: true
          visible: text !== ""
          textColor: Color.urgent
          text: root.error || (root.service ? root.service.error : "")
        }
        Kani.Label {
          Layout.fillWidth: true
          visible: root.busy
          secondary: true
          text: root.snapshot.syncing ? "Refreshing your progress… Cached study remains saved." : "Saving…"
        }
        Controls.ScrollView {
          id: scroll
          Layout.fillWidth: true
          Layout.fillHeight: true
          contentWidth: availableWidth
          clip: true
          Loader {
            id: content
            width: scroll.availableWidth
            sourceComponent: root.view === "study" ? studyPage : root.view === "review-overview" ? reviewOverviewPage : root.view === "lesson-overview" ? lessonOverviewPage : root.view === "progress" ? progressPage : root.view === "lookup" ? lookupPage : root.view === "practice-library" ? practicePage : root.view === "recovery" ? recoveryPage : root.view === "settings" ? settingsPage : root.view === "zen" ? zenPage : root.view === "help" ? helpPage : dashboardPage
            onLoaded: {
              if (scroll.contentItem && scroll.contentItem.contentY !== undefined)
                scroll.contentItem.contentY = 0
              Qt.callLater(root.focusContent)
            }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          Kani.Label {
            text: root.snapshot.syncing ? "● Syncing" : "● " + (root.snapshot.status || "starting")
            textColor: root.snapshot.status === "offline" ? Color.urgent : Qt.alpha(Color.foreground, 0.76)
            font.pixelSize: Style.font.bodySmall
          }
          Kani.Label {
            text: (root.snapshot.pending || 0) + " pending"
            visible: root.snapshot.pending > 0
            textColor: Color.accent
            font.pixelSize: Style.font.bodySmall
          }
          Kani.Label {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            horizontalAlignment: Text.AlignRight
            text: root.snapshot.username ? root.snapshot.username + " · Level " + root.snapshot.level : "Connect an account or explore the demo"
            font.pixelSize: Style.font.bodySmall
            secondary: true
          }
        }
      }
    }
  }
  Component {
    id: dashboardPage
    Kani.Dashboard {
      controller: root
    }
  }
  Component {
    id: reviewOverviewPage
    Kani.StudyOverview { controller: root; mode: "reviews" }
  }
  Component {
    id: lessonOverviewPage
    Kani.StudyOverview { controller: root; mode: "lessons" }
  }
  Component {
    id: progressPage
    Kani.Progress { controller: root }
  }
  Component {
    id: studyPage
    Kani.Study {
      controller: root
    }
  }
  Component {
    id: lookupPage
    Kani.Lookup {
      controller: root
    }
  }
  Component {
    id: settingsPage
    Kani.Settings {
      controller: root
    }
  }
  Component {
    id: zenPage
    Kani.Zen {
      controller: root
    }
  }
  Component {
    id: practicePage
    Kani.Practice {
      controller: root
    }
  }
  Component {
    id: recoveryPage
    Kani.Recovery {
      controller: root
    }
  }
  Component {
    id: helpPage
    Kani.ShortcutHelp {
      controller: root
      returnView: root.helpReturnView
      helpShortcutEnabled: true
      navigationShortcutsEnabled: true
    }
  }
}
