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
  property bool moreNavigation: false
  property bool busy: false
  property string error: ""
  property var session: null
  property var listenSession: null
  property var listenStatus: null
  readonly property var dictation: dictationCore
  property bool listenBusy: false
  property string listenError: ""
  property string listenPreparationNotice: ""
  property int listenSequence: 0
  readonly property string listenContext: JSON.stringify([contentAccess, snapshot.last_sync, snapshot.session_revision, snapshot.pending, snapshot.attention, snapshot.state_revision])
  onListenContextChanged: invalidateListening()
  property var results: []
  property var detail: null
  property var progressNavigation: ({})
  property bool progressReturn: false
  property bool helpReturnProgress: false
  readonly property string progressContext: JSON.stringify([contentAccess, snapshot.last_sync, snapshot.session_epoch, snapshot.session_revision, snapshot.pending, snapshot.attention, snapshot.syncing, snapshot.status])
  onProgressContextChanged: invalidateProgressDetails()
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
  property int audioParentSubjectId: -1
  property var audioExample: null
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
    progressReturn = false
    progressNavigation = ({})
    listenSequence++
    listenSession = null
    listenStatus = null
    listenBusy = false
    listenPreparationNotice = ""
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
    helpReturnProgress = progressReturn
    navigate("help")
  }
  function closeHelp() {
    navigate(helpReturnView)
    if (helpReturnView === "lookup" && helpReturnDetail)
      showSubject(helpReturnDetail.id, helpReturnProgress)
    helpReturnDetail = null
  }

  function open(payloadJson) {
    if (service && service.locked) {
      close()
      return
    }
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
      navigate(["dashboard", "review-overview", "lesson-overview", "progress", "activity", "listen", "dictation", "lookup", "zen", "settings", "help", "practice-library", "recovery"].indexOf(requested) >= 0 ? requested : "dashboard")
    if (requested === "lookup" && payload.selection)
      readSelection()
    else if (requested === "lookup" && typeof payload.text === "string")
      search(payload.text)
  }
  function close() {
    if (service && typeof service.cancelListeningPreparation === "function")
      service.cancelListeningPreparation()
    listenSequence++
    listenBusy = false
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
    if (next !== "listen" && service && typeof service.cancelListeningPreparation === "function")
      service.cancelListeningPreparation()
    listenPreparationNotice = ""
    listenSequence++
    listenBusy = false
    stopAudio()
    navigationSequence++
    progressReturn = false
    view = next
    moreNavigation = ["practice-library", "activity", "zen", "settings", "help", "recovery"].indexOf(next) >= 0
    if (next === "listen")
      Qt.callLater(loadListening)
    detail = null
    error = ""
    if (service)
      service.studying = next === "study" || next === "listen" || next === "dictation"
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
    progressReturn = false
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
  function showProgressSubject(id) {
    showSubject(id, true)
  }
  function returnToProgress() {
    navigate("progress")
  }
  function invalidateProgressDetails() {
    if (opened && view === "lookup" && progressReturn && detail) {
      navigate("progress")
      error = "Account progress changed. Reopen the subject from the refreshed list. Your note drafts are saved."
    }
  }
  function showSubject(id, fromProgress) {
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
    var guarded = fromProgress === true || progressReturn === true
    var expectedProgress = progressContext
    call(guarded ? "progress_details" : "details", {
      subject_id: id
    }, function (ok, data) {
      if (root.opened && root.service && root.service.ready && !root.service.locked && root.detailSequence === expectedDetail && root.navigationSequence === expectedNavigation && root.searchSequence === expectedSearch && root.contentAccess === expectedAccess && (!guarded || root.progressContext === expectedProgress)) {
        if (ok) {
          root.progressReturn = guarded
          root.detail = data
          root.view = "lookup"
          if (root.service)
            root.service.studying = false
        } else if (guarded) {
          var reason = root.error
          root.navigate("progress")
          root.error = reason || "This subject could not be opened from current progress. Choose another subject or refresh your account."
        }
      }
    })
  }
  function audioContextCurrent(sequence, navigation, access, studyId, studyRevision) {
    return sequence === audioSequence && navigation === navigationSequence && access === contentAccess && opened && service && service.ready && !service.locked && (!studyId || (view === "study" && session && session.id === studyId && session.revision === studyRevision))
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
    audioParentSubjectId = audioContext === "kanji_example" ? args.parent_subject_id : -1
    audioState = "loading"
    audioNotice = "Checking pronunciation…"
    function current() {
      if (!root.audioContextCurrent(sequence, navigation, access, studyId, studyRevision))
        return false
      if (args.context !== "kanji_example")
        return true
      var parent = root.kanjiExampleArgs({
        id: args.parent_subject_id,
        type: "kanji"
      })
      return parent && parent.context === args.origin_context && parent.session_id === args.session_id && parent.revision === args.revision
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
        if (args.context === "kanji_example" && data.subject_id !== args.subject_id) {
          root.audioState = "failed"
          root.audioNotice = "This example changed. Open the vocabulary recordings again."
          return
        }
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
        if (args.context === "kanji_example") {
          if (!data.example || data.example.parent_subject_id !== args.parent_subject_id || data.subject_id !== args.subject_id) {
            root.audioState = "failed"
            root.audioNotice = "This example changed. Open the vocabulary recordings again."
            return
          }
          root.audioExample = data.example
        }
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
    var args = {
      subject_id: subject.id,
      context: view === "study" ? "study" : "details"
    }
    if (view === "study") {
      if (!session || !session.subject || session.subject.id !== subject.id || (session.phase !== "lesson" && !(session.phase === "feedback" && session.feedback && !session.feedback.retry && (session.part === "reading" || subject.type === "kana_vocabulary"))))
        return
      args.session_id = session.id
      args.revision = session.revision
    }
    requestAudio(args)
  }
  function testVoice(actor) {
    requestAudio({
      context: "voice_test",
      voice_actor_id: actor
    }, "pronunciation_sample")
  }
  function kanjiExampleArgs(parent) {
    if (!parent || parent.type !== "kanji" || !opened || !service || !service.ready || service.locked)
      return null
    var args = {
      parent_subject_id: parent.id
    }
    if (view === "study") {
      if (!session || !session.subject || session.subject.id !== parent.id)
        return null
      var discovery = session.phase === "lesson" && session.lesson_flow && ["reading", "context"].indexOf(session.lesson_flow.step) >= 0
      var revealed = session.phase === "feedback" && session.part === "reading" && session.feedback && !session.feedback.retry
      if (!discovery && !revealed)
        return null
      args.context = "study"
      args.session_id = session.id
      args.revision = session.revision
    } else if (view === "lookup" && detail && detail.id === parent.id) {
      args.context = "details"
    } else {
      return null
    }
    return args
  }
  function playKanjiExample(word, parent) {
    var args = kanjiExampleArgs(parent)
    if (!args || !word || !Number.isInteger(word.subject_id) || word.subject_id <= 0)
      return
    args.subject_id = word.subject_id
    args.origin_context = args.context
    args.context = "kanji_example"
    requestAudio(args)
  }
  function stopAudio() {
    if (typeof dictationCore !== "undefined" && dictationCore)
      dictationCore.cancelAudio()
    if (audioContext === "listening" && audioState === "loading" && listenBusy) {
      listenSequence++
      listenBusy = false
    }
    audioSequence++
    if (audio)
      audio.stop()
    audioSubjectId = -1
    audioParentSubjectId = -1
    audioExample = null
    audioContext = ""
    audioState = ""
    audioNotice = ""
  }
  function invalidateListening() {
    listenSequence++
    listenBusy = false
    listenSession = null
    listenStatus = null
    if (audioContext === "listening")
      stopAudio()
    if (opened && view === "listen")
      Qt.callLater(loadListening)
  }
  function listenCurrent(sequence, access) {
    return sequence === listenSequence && access === listenContext && opened && view === "listen" && service && service.ready && !service.locked
  }
  function loadListening() {
    if (!opened || view !== "listen" || !service || !service.ready || service.locked || listenBusy)
      return
    var sequence = ++listenSequence
    var access = listenContext
    listenBusy = true
    listenError = ""
    service.request("listen_state", {}, function (ok, data, message) {
      if (!root.listenCurrent(sequence, access))
        return
      root.listenBusy = false
      if (ok) {
        root.listenStatus = data.status
        root.listenSession = data.session
      } else {
        root.listenError = message || "Listening practice could not be loaded."
      }
      Qt.callLater(root.focusContent)
    })
  }
  function listenAction(action, args) {
    if (!opened || view !== "listen" || !service || !service.ready || service.locked || listenBusy)
      return
    if (action !== "reveal")
      stopAudio()
    var sequence = ++listenSequence
    var access = listenContext
    var values = Object.assign({}, args || {}, {
      action: action
    })
    if (listenSession) {
      values.session_id = listenSession.id
      values.revision = listenSession.revision
    }
    listenBusy = true
    listenError = ""
    service.request("listen", values, function (ok, data, message) {
      if (!root.listenCurrent(sequence, access))
        return
      root.listenBusy = false
      if (ok) {
        root.listenSession = data.session
        if (action === "settings" || (data.session && data.session.phase === "complete"))
          Qt.callLater(root.loadListening)
      } else {
        root.listenError = message || "The listening action could not be saved."
      }
      Qt.callLater(root.focusContent)
    })
  }
  function prepareListening() {
    if (!opened || view !== "listen" || listenBusy || !service || !service.ready || service.locked || service.listeningPreparationJobId)
      return
    stopAudio()
    listenPreparationNotice = ""
    var owner = service
    var access = contentAccess
    var navigation = navigationSequence
    service.prepareListening(function (ok, data, message) {
      if (!root.opened || root.view !== "listen" || root.navigationSequence !== navigation || root.service !== owner || !owner.ready || owner.locked || root.contentAccess !== access)
        return
      if (!ok)
        root.listenPreparationNotice = message || "Recordings could not be prepared. Try again."
      else {
        var reasons = {
          ready: "Recordings are ready. Start listening when you choose.",
          cancelled: "Preparation stopped. Recordings already saved remain available.",
          offline: "Connect before preparing missing recordings.",
          budget: "Some recordings do not fit beside required study media. Use the ready words or adjust the cache limit in Settings.",
          permission_changed: "Study or account access changed. Availability has been checked again.",
          daily_limit: "Today's new listening allowance is used. Previously introduced words return at their local interval.",
          saved_session: "Resume your saved listening session before preparing another batch.",
          no_candidates: "No eligible familiar recordings were found.",
          incomplete: "The bounded preparation pass finished. Only the recordings found were checked.",
          download_failed: "Some recordings could not be downloaded. Try again when connected.",
          cache_cleanup: "Interrupted cache files could not be cleaned. Check available storage."
        }
        var downloaded = data.downloaded || 0
        root.listenPreparationNotice = downloaded + (downloaded === 1 ? " recording saved · " : " recordings saved · ") + (data.already_cached || 0) + " already cached. " + (reasons[data.reason] || "Check availability before trying again.")
      }
      root.loadListening()
    })
  }
  function playListening() {
    if (!listenSession || !listenSession.media_handle || listenBusy || !opened || view !== "listen" || !service || !service.ready || service.locked)
      return
    stopAudio()
    var sequence = ++listenSequence
    var audioRequest = audioSequence
    var access = listenContext
    var handle = listenSession.media_handle
    listenBusy = true
    listenError = ""
    audioContext = "listening"
    audioState = "loading"
    audioNotice = "Preparing the recording…"
    service.request("listen_media", {
      handle: handle
    }, function (ok, data, message) {
      if (!root.listenCurrent(sequence, access) || audioRequest !== root.audioSequence)
        return
      root.listenBusy = false
      if (ok && data.handle === handle && data.session && data.session.media_handle === handle) {
        // First hearing is durably recorded before the player receives a URI.
        // Apply its revision before allowing the Reveal or rating controls.
        root.listenSession = data.session
        root.audioNotice = "Original recording · " + (data.voice || "WaniKani")
        audio.source = data.uri
        audio.play()
      } else {
        root.audioState = "failed"
        root.audioNotice = message || "This recording is no longer available. Skip it or refresh your cache."
      }
    })
  }
  function readSelection() {
    if (opened && view === "lookup" && !clipboard.running) {
      progressReturn = false
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
  Kani.DictationState {
    id: dictationCore
    controller: root
    player: audio
  }
  MediaDevices {
    onDefaultAudioOutputChanged: {
      var wasDictation = root.audioContext === "dictation"
      root.stopAudio()
      if (wasDictation)
        dictationCore.mediaNotice = "Audio output changed. Replay when your device is ready."
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
    function onReadyChanged() {
      if (!root.service.ready)
        root.stopAudio()
      root.invalidateListening()
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
        model: ["dashboard", "study", "lookup", "zen", "settings", "practice-library", "listen", "progress", "activity"]
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
            text: "Listen"
            selected: root.view === "listen" || root.view === "dictation"
            onClicked: root.navigate("listen")
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
            text: root.moreNavigation ? "More ▴" : "More ▾"
            accessibleName: "More WaniKani views"
            selected: root.moreNavigation
            onClicked: root.moreNavigation = !root.moreNavigation
          }
        }
        Flow {
          Layout.fillWidth: true
          visible: root.moreNavigation
          spacing: Style.space(6)
          Kani.Action {
            text: "Practice"
            selected: root.view === "practice-library"
            onClicked: root.navigate("practice-library")
          }
          Kani.Action {
            text: "Activity"
            selected: root.view === "activity"
            onClicked: root.navigate("activity")
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
            sourceComponent: root.view === "study" ? studyPage : root.view === "review-overview" ? reviewOverviewPage : root.view === "lesson-overview" ? lessonOverviewPage : root.view === "progress" ? progressPage : root.view === "activity" ? activityPage : root.view === "listen" ? listeningPage : root.view === "dictation" ? dictationPage : root.view === "lookup" ? lookupPage : root.view === "practice-library" ? practicePage : root.view === "recovery" ? recoveryPage : root.view === "settings" ? settingsPage : root.view === "zen" ? zenPage : root.view === "help" ? helpPage : dashboardPage
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
    Kani.StudyOverview {
      controller: root
      mode: "reviews"
    }
  }
  Component {
    id: lessonOverviewPage
    Kani.StudyOverview {
      controller: root
      mode: "lessons"
    }
  }
  Component {
    id: listeningPage
    Kani.Listening {
      controller: root
    }
  }
  Component {
    id: dictationPage
    Kani.Dictation {
      controller: root
    }
  }
  Component {
    id: activityPage
    Kani.LearningActivity {
      controller: root
    }
  }
  Component {
    id: progressPage
    Kani.Progress {
      controller: root
    }
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
