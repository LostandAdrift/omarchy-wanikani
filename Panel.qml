import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import QtMultimedia
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import "qml" as Kani
import "vendor/WanaKana.mjs" as Kana

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
  property string searchType: "all"
  property string searchState: "all"
  property int searchSequence: 0
  property bool searching: false
  property string helpReturnView: "dashboard"
  property var helpReturnDetail: null
  property var chosenScreen: null
  property bool focusPrimed: false
  property string integrationNotice: ""
  readonly property var snapshot: service ? service.snapshot : ({
      settings: {},
      outbox: [],
      difficult: [],
      forecast: [],
      activity: []
    })
  readonly property string pluginId: "io.github.lostandadrift.wanikani"
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
    detail = helpReturnDetail
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
      navigate(["dashboard", "lookup", "zen", "settings", "help", "practice-library"].indexOf(requested) >= 0 ? requested : "dashboard")
    if (requested === "lookup" && payload.selection)
      readSelection()
    else if (requested === "lookup" && typeof payload.text === "string")
      search(payload.text.slice(0, 256))
  }
  function close() {
    opened = false
    audio.stop()
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
    view = next
    detail = null
    error = ""
    if (service)
      service.studying = next === "study"
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
      if (ok)
        root.session = data
      Qt.callLater(root.focusContent)
    })
  }
  function search(text) {
    query = String(text || "").slice(0, 256)
    detail = null
    if (!service)
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
      if (root.searchSequence === expected) {
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
    call("details", {
      subject_id: id
    }, function (ok, data) {
      if (ok) {
        root.detail = data
        root.view = "lookup"
        if (root.service)
          root.service.studying = false
      }
    })
  }
  function play(subject) {
    if (subject && subject.audio && subject.audio.length) {
      audio.source = subject.audio[0].url
      audio.play()
    }
  }
  function readSelection() {
    if (!clipboard.running) {
      clipboard.captured = ""
      clipboard.primary = true
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
    command: primary ? ["wl-paste", "--primary", "--no-newline", "--type", "text"] : ["wl-paste", "--no-newline", "--type", "text"]
    property string captured: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: clipboard.captured = text.slice(0, 4096)
    }
    onExited: {
      if (!captured.trim() && primary) {
        primary = false
        Qt.callLater(function () {
          clipboard.running = true
        })
      } else {
        root.query = captured.trim().slice(0, 256)
        root.search(root.query)
        captured = ""
        Qt.callLater(root.focusContent)
      }
    }
  }
  MediaPlayer {
    id: audio
    audioOutput: AudioOutput {}
  }
  Connections {
    target: root.service
    function onSnapshotChanged() {
      if (root.view === "study" && root.snapshot.session)
        root.session = root.snapshot.session
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
    Rectangle {
      id: frame
      anchors.centerIn: parent
      width: Math.min(parent.width - Style.gapsOut * 2, Style.space(root.expanded ? 1060 : 760))
      height: Math.min(parent.height - Style.gapsOut * 2, Style.space(root.expanded ? 920 : 760))
      color: Color.background
      border.color: Color.popups.border
      border.width: Math.max(1, Style.space(2))
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
          Kani.Crab {
            Layout.preferredWidth: Style.space(52)
            Layout.preferredHeight: Style.space(44)
            animate: root.opened && root.service && root.service.animations
          }
          ColumnLayout {
            spacing: 1
            Kani.Label {
              text: "WaniKani"
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Kani.Label {
              text: root.snapshot.demo ? "DEMO · Nothing is sent to WaniKani" : "Five reviews, then back to work."
              font.pixelSize: Style.font.bodySmall
              color: root.snapshot.demo ? Color.accent : Qt.alpha(Color.foreground, 0.76)
            }
          }
          Item {
            Layout.fillWidth: true
          }
          Kani.Action {
            text: root.expanded ? "Compact" : "Expand"
            onClicked: root.expanded = !root.expanded
          }
          Kani.Action {
            text: "Close · Esc"
            onClicked: root.dismiss()
          }
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(6)
          Kani.Action {
            id: todayTab
            text: "Today"
            selected: root.view === "dashboard"
            onClicked: root.navigate("dashboard")
          }
          Kani.Action {
            text: "Study"
            selected: root.view === "study"
            onClicked: root.begin("resume")
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
          color: Color.urgent
          text: root.error || (root.service ? root.service.error : "")
        }
        Kani.Label {
          Layout.fillWidth: true
          visible: root.busy
          color: Qt.alpha(Color.foreground, 0.76)
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
            sourceComponent: root.view === "study" ? studyPage : root.view === "lookup" ? lookupPage : root.view === "practice-library" ? practicePage : root.view === "settings" ? settingsPage : root.view === "zen" ? zenPage : root.view === "help" ? helpPage : dashboardPage
            onLoaded: {
              if (scroll.contentItem && scroll.contentItem.contentY !== undefined)
                scroll.contentItem.contentY = 0
              Qt.callLater(root.focusContent)
            }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          Kani.Label {
            text: root.snapshot.syncing ? "● Syncing" : "● " + (root.snapshot.status || "starting")
            color: root.snapshot.status === "offline" ? Color.urgent : Qt.alpha(Color.foreground, 0.76)
            font.pixelSize: Style.font.bodySmall
          }
          Kani.Label {
            text: (root.snapshot.pending || 0) + " pending"
            visible: root.snapshot.pending > 0
            color: Color.accent
            font.pixelSize: Style.font.bodySmall
          }
          Item {
            Layout.fillWidth: true
          }
          Kani.Label {
            text: root.snapshot.username ? root.snapshot.username + " · Level " + root.snapshot.level : "Connect an account or explore the demo"
            font.pixelSize: Style.font.bodySmall
            color: Qt.alpha(Color.foreground, 0.76)
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
    id: helpPage
    Kani.ShortcutHelp {
      controller: root
      returnView: root.helpReturnView
      helpShortcutEnabled: true
      navigationShortcutsEnabled: true
    }
  }
}
