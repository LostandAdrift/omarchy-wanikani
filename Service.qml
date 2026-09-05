import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Networking
import "qml" as Kani
import "qml/DesktopPolicy.mjs" as Policy
import "qml/SessionState.mjs" as SessionState

Item {
  id: root
  property var shell: null
  property var manifest: null
  property string stateDirectory: ""
  readonly property string pluginId: "io.github.lostandadrift.wanikani"
  readonly property string sourceDir: decodeURIComponent(String(Qt.resolvedUrl(".")).replace(/^file:\/\//, ""))
  property var snapshot: ({
      settings: {},
      reviews: 0,
      lessons: 0,
      status: "starting",
      forecast: [],
      activity: [],
      outbox: [],
      difficult: []
    })
  property var ambientItems: []
  property bool ready: false
  property bool panelOpen: false
  property bool studying: false
  property string error: ""
  property int sequence: 0
  property string epochId: String(Date.now()) + "-" + Math.random().toString(36).slice(2)
  property var callbacks: ({})
  property var requestContexts: ({})
  property var stateOrder: SessionState.initial()
  property int pendingCount: 0
  property int previousReviews: -1
  property double lastNotification: 0
  property int ambientIndex: 0
  property int restartAttempts: 0
  property int zenUsers: 0
  property bool ambientDirty: true
  property bool ambientFetching: false
  property int ambientGeneration: 0
  property double ambientFetchedAt: 0
  readonly property string contentAccess: JSON.stringify([snapshot.demo === true, snapshot.username || "", snapshot.max_level || 0, snapshot.session_epoch || ""])
  onContentAccessChanged: {
    ambientItems = []
    refreshAmbient()
  }
  readonly property bool networkOnline: Networking.connectivity === NetworkConnectivity.Full || (Networking.connectivity === NetworkConnectivity.Unknown && Networking.devices && Networking.devices.values.some(function (device) {
      return device.connected
    }))
  onNetworkOnlineChanged: {
    if (networkOnline && ready && snapshot.connected && !snapshot.demo)
      reconnectTimer.restart()
  }
  readonly property var lockService: shell ? shell.serviceFor("omarchy.lock") : null
  readonly property var notificationsService: shell ? shell.serviceFor("omarchy.notifications") : null
  readonly property var idleService: shell ? shell.serviceFor("omarchy.idle") : null
  readonly property bool locked: lockService ? lockService.locked : true
  readonly property bool dnd: notificationsService ? notificationsService.doNotDisturb : false
  readonly property bool fullscreen: ToplevelManager.activeToplevel ? ToplevelManager.activeToplevel.fullscreen : false
  readonly property bool canDecorate: Policy.ambientAllowed({
    locked: locked,
    fullscreen: fullscreen,
    studying: studying,
    panelOpen: panelOpen
  })
  readonly property bool animations: snapshot.settings.companion_animation === true && snapshot.settings.reduced_motion !== true
  readonly property var ambientSubject: ambientItems.length ? ambientItems[ambientIndex % ambientItems.length] : null
  readonly property var idleConfig: shell && shell.shellConfig ? shell.shellConfig.idle || {} : {}
  readonly property int idleDeadline: idleService ? idleService.firstIdleTimeoutSeconds : Math.min(Number(idleConfig.screensaver || 150), Number(idleConfig.lock || 300))
  readonly property var idleWindow: Policy.idleWindow(idleDeadline)
  readonly property bool idleVisible: canDecorate && snapshot.settings.idle_gallery === true && idleWindow.enabled && idleStart.isIdle && !idleEnd.isIdle && ambientSubject !== null
  readonly property bool ambientWanted: Policy.ambientDemand(snapshot.settings, {
    ready: ready,
    locked: locked,
    studying: studying,
    fullscreen: fullscreen,
    panelOpen: panelOpen,
    zen: zenUsers > 0,
    desktopIdle: desktopIdle.isIdle,
    idleEligible: idleStart.enabled && idleStart.isIdle && !idleEnd.isIdle
  })
  onAmbientWantedChanged: queueAmbient()

  function ordering() {
    return Object.assign({}, stateOrder, {
      snapshot: snapshot
    })
  }
  function applySnapshot(data) {
    var next = SessionState.full(ordering(), data)
    if (next.catalogueAccepted && next.sessionEpoch !== stateOrder.sessionEpoch)
      ambientItems = []
    stateOrder = next
    if (next.catalogueAccepted || next.sessionAccepted)
      snapshot = next.snapshot
    if (next.catalogueAccepted) {
      considerNotification()
      refreshAmbient()
    }
  }
  function applySession(data) {
    var next = SessionState.partial(ordering(), data)
    stateOrder = next
    if (next.sessionAccepted)
      snapshot = next.snapshot
  }

  function request(method, args, callback) {
    if (!ready) {
      error = "The study service is starting. Try again in a moment."
      if (callback)
        callback(false, null, error)
      return ""
    }
    var id = epochId + ":" + (++sequence)
    var next = Object.assign({}, callbacks)
    next[id] = callback || function () {}
    callbacks = next
    var contexts = Object.assign({}, requestContexts)
    contexts[id] = stateOrder.context
    requestContexts = contexts
    pendingCount++
    worker.write(JSON.stringify({
      v: 1,
      id: id,
      method: method,
      args: args || {}
    }) + "\n")
    return id
  }
  function receive(line) {
    var message
    try {
      message = JSON.parse(line)
    } catch (_) {
      error = "The study service returned an unreadable response."
      return
    }
    if (message.v !== 1)
      return
    if (message.event === "ready") {
      stateOrder = SessionState.workerRestart(ordering())
      ready = true
      restartAttempts = 0
      error = ""
      return
    }
    if (message.event === "state") {
      applySnapshot(message.data)
      return
    }
    if (message.event === "session") {
      applySession(message.data)
      return
    }
    if (message.event === "readiness") {
      snapshot = Object.assign({}, snapshot, {
        readiness: message.data
      })
      return
    }
    if (message.event === "sync_progress") {
      snapshot = Object.assign({}, snapshot, {
        sync_progress: message.data
      })
      return
    }
    if (message.id && callbacks[message.id]) {
      var callback = callbacks[message.id]
      var issuedContext = requestContexts[message.id]
      var contexts = Object.assign({}, requestContexts)
      delete contexts[message.id]
      requestContexts = contexts
      var next = Object.assign({}, callbacks)
      delete next[message.id]
      callbacks = next
      pendingCount = Math.max(0, pendingCount - 1)
      if (message.ok && SessionState.isSession(message.data)) {
        var nextOrder = SessionState.reply(ordering(), message.data, issuedContext)
        stateOrder = nextOrder
        if (!nextOrder.replyAccepted) {
          callback(false, null, "The saved session changed. Resume to load its latest state.")
          return
        }
        if (nextOrder.sessionAccepted)
          snapshot = nextOrder.snapshot
        message.data = SessionState.visibleSession(message.data, snapshot.max_level)
      }
      if (!message.ok)
        error = message.error ? message.error.message : "Something went wrong."
      else
        error = ""
      callback(message.ok, message.data, message.error ? message.error.message : "")
    }
  }
  function refreshAmbient() {
    ambientDirty = true
    ambientGeneration++
    queueAmbient()
  }
  function acquireAmbient() {
    zenUsers++
    queueAmbient()
  }
  function releaseAmbient() {
    zenUsers = Math.max(0, zenUsers - 1)
    queueAmbient()
  }
  function queueAmbient() {
    if (!ambientRefreshTimer)
      return
    if (Policy.ambientFetch(ambientWanted, ready, ambientFetching, ambientDirty, Date.now(), ambientFetchedAt))
      ambientRefreshTimer.restart()
    else if (!ambientWanted)
      ambientRefreshTimer.stop()
  }
  function fetchAmbient() {
    if (!Policy.ambientFetch(ambientWanted, ready, ambientFetching, ambientDirty, Date.now(), ambientFetchedAt))
      return
    var access = contentAccess
    var generation = ambientGeneration
    ambientFetching = true
    request("ambient", {}, function (ok, data) {
      root.ambientFetching = false
      if (ok && root.contentAccess === access && root.ambientGeneration === generation) {
        root.ambientItems = data
        root.ambientDirty = false
        root.ambientFetchedAt = Date.now()
      }
      // Coalesce updates received during one fetch into at most one follow-up.
      // A failed worker response waits for the next visible refresh opportunity.
      if (ok)
        root.queueAmbient()
    })
  }
  function summon(view, extra) {
    var payload = Object.assign({
      view: view || "dashboard"
    }, extra || {})
    if (shell)
      shell.summon(pluginId, JSON.stringify(payload))
  }
  function considerNotification() {
    var due = Number(snapshot.reviews || 0)
    var now = Date.now() / 1000
    var settings = Object.assign({}, snapshot.settings, {
      last_notification_at: Math.max(lastNotification, Number(snapshot.settings.last_notification_at || 0))
    })
    var decision = Policy.notification(previousReviews, due, now, new Date().getHours(), settings, {
      demo: snapshot.demo,
      locked: locked,
      dnd: dnd,
      studying: studying,
      vacation: snapshot.vacation
    })
    previousReviews = decision.previousDue
    if (!decision.notify)
      return
    lastNotification = now
    saveSettings({
      last_notification_at: now
    })
    Quickshell.execDetached(["omarchy", "notification", "send", "--app-name", "WaniKani", "--urgency", "low", "WaniKani · " + due + " reviews ready", "A few reviews, then back to work.", "--exec", "omarchy-shell", "shell", "summon", pluginId, '{"view":"reviews","limit":5}'])
  }
  function saveSettings(values) {
    request("settings", values)
  }

  Process {
    id: worker
    command: ["python3", "-B", root.sourceDir + "backend/worker.py"].concat(root.stateDirectory ? ["--state-dir", root.stateDirectory] : [])
    stdinEnabled: true
    running: true
    stdout: SplitParser {
      onRead: function (line) {
        root.receive(line)
      }
    }
    onExited: {
      root.ready = false
      root.error = "The study service stopped. Reconnecting to your saved session…"
      var pending = root.callbacks
      root.callbacks = ({})
      root.requestContexts = ({})
      root.pendingCount = 0
      for (var key in pending)
        pending[key](false, null, root.error)
      restartTimer.restart()
    }
  }
  Timer {
    id: reconnectTimer
    interval: 2000
    onTriggered: {
      if (root.ready && root.networkOnline && root.snapshot.connected && !root.snapshot.demo && !root.snapshot.syncing)
        root.request("sync", {})
    }
  }
  Timer {
    id: restartTimer
    interval: Math.min(30000, 1000 * Math.pow(2, root.restartAttempts))
    onTriggered: {
      root.restartAttempts++
      worker.running = true
    }
  }
  Timer {
    interval: 60000
    repeat: true
    running: root.ready
    onTriggered: {
      root.request("tick", {})
      root.request("snapshot", {}, function (ok, data) {
        if (ok)
          root.applySnapshot(data)
      })
    }
  }
  Timer {
    id: ambientRefreshTimer
    interval: 25
    onTriggered: root.fetchAmbient()
  }
  Timer {
    interval: 60000
    repeat: true
    running: root.ready && root.ambientWanted
    onTriggered: root.refreshAmbient()
  }
  Timer {
    interval: 30000
    repeat: true
    running: root.canDecorate && root.ambientWanted && root.ambientItems.length > 1
    onTriggered: root.ambientIndex++
  }
  IdleMonitor {
    id: desktopIdle
    timeout: 10
    enabled: root.snapshot.settings.desktop_card === true
    respectInhibitors: true
  }
  IdleMonitor {
    id: idleStart
    timeout: root.idleWindow.start
    enabled: root.snapshot.settings.idle_gallery === true && root.idleWindow.enabled && root.idleService && root.idleService.idleEnabled
    respectInhibitors: true
  }
  IdleMonitor {
    id: idleEnd
    timeout: Math.max(61, root.idleWindow.end)
    enabled: idleStart.enabled
    respectInhibitors: true
  }
  Kani.Ambient {
    service: root
    gallery: root.idleVisible
    showCard: root.canDecorate && root.snapshot.settings.desktop_card === true && desktopIdle.isIdle
  }
  IpcHandler {
    target: "wanikani"
    function dashboard(): void {
      root.summon("dashboard")
    }
    function reviews(): void {
      root.summon("reviews")
    }
    function lessons(): void {
      root.summon("lessons")
    }
    function resume(): void {
      root.summon("resume")
    }
    function lookup(): void {
      root.summon("lookup", {
        selection: true
      })
    }
    function practice(): void {
      root.summon("practice-library")
    }
    function recovery(): void {
      root.summon("recovery")
    }
    function help(): void {
      root.summon("help")
    }
    function zen(): void {
      root.summon("zen")
    }
    function refresh(): void {
      root.request("sync", {})
    }
    function settings(): void {
      root.summon("settings")
    }
    function demo(enabled: string): void {
      root.request("use_demo", {
        enabled: enabled !== "false"
      })
    }
    function status(): string {
      return JSON.stringify({
        status: root.snapshot.status,
        reviews: root.snapshot.reviews,
        lessons: root.snapshot.lessons,
        pending: root.snapshot.pending,
        attention: root.snapshot.attention
      })
    }
  }
  Component.onDestruction: {
    restartTimer.stop()
    worker.running = false
  }
}
