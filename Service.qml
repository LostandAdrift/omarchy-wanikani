import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import "qml" as Kani

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
  property int pendingCount: 0
  property int previousReviews: -1
  property double lastNotification: 0
  property int ambientIndex: 0
  property int restartAttempts: 0
  readonly property var lockService: shell ? shell.serviceFor("omarchy.lock") : null
  readonly property var notificationsService: shell ? shell.serviceFor("omarchy.notifications") : null
  readonly property var idleService: shell ? shell.serviceFor("omarchy.idle") : null
  readonly property bool locked: lockService ? lockService.locked : true
  readonly property bool dnd: notificationsService ? notificationsService.doNotDisturb : false
  readonly property bool fullscreen: ToplevelManager.activeToplevel ? ToplevelManager.activeToplevel.fullscreen : false
  readonly property bool canDecorate: !locked && !fullscreen && !studying && !panelOpen
  readonly property bool animations: snapshot.settings.companion_animation === true && snapshot.settings.reduced_motion !== true
  readonly property var ambientSubject: ambientItems.length ? ambientItems[ambientIndex % ambientItems.length] : null
  readonly property var idleConfig: shell && shell.shellConfig ? shell.shellConfig.idle || {} : {}
  readonly property int idleDeadline: idleService ? idleService.firstIdleTimeoutSeconds : Math.min(Number(idleConfig.screensaver || 150), Number(idleConfig.lock || 300))
  readonly property bool idleVisible: canDecorate && snapshot.settings.idle_gallery === true && idleDeadline > 65 && idleStart.isIdle && !idleEnd.isIdle && ambientSubject !== null

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
      ready = true
      restartAttempts = 0
      error = ""
      return
    }
    if (message.event === "state") {
      snapshot = message.data
      considerNotification()
      if (ready)
        refreshAmbient()
      return
    }
    if (message.id && callbacks[message.id]) {
      var callback = callbacks[message.id]
      var next = Object.assign({}, callbacks)
      delete next[message.id]
      callbacks = next
      pendingCount = Math.max(0, pendingCount - 1)
      if (!message.ok)
        error = message.error ? message.error.message : "Something went wrong."
      else
        error = ""
      callback(message.ok, message.data, message.error ? message.error.message : "")
    }
  }
  function refreshAmbient() {
    request("ambient", {}, function (ok, data) {
      if (ok)
        ambientItems = data
    })
  }
  function summon(view, extra) {
    var payload = Object.assign({
      view: view || "dashboard"
    }, extra || {})
    if (shell)
      shell.summon(pluginId, JSON.stringify(payload))
  }
  function quietNow() {
    var hour = new Date().getHours()
    var start = snapshot.settings.quiet_start === undefined ? 22 : snapshot.settings.quiet_start
    var end = snapshot.settings.quiet_end === undefined ? 8 : snapshot.settings.quiet_end
    return start === end ? false : start > end ? hour >= start || hour < end : hour >= start && hour < end
  }
  function considerNotification() {
    var due = Number(snapshot.reviews || 0)
    var increased = previousReviews >= 0 && due > previousReviews
    previousReviews = due
    // suppressed changes are consumed, never replayed later
    var now = Date.now() / 1000
    if (!increased || snapshot.demo || snapshot.settings.notifications === false || locked || dnd || studying || snapshot.vacation || quietNow())
      return
    if (now < Number(snapshot.settings.snooze_until || 0) || now - Math.max(lastNotification, Number(snapshot.settings.last_notification_at || 0)) < Number(snapshot.settings.reminder_interval || 7200))
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
      root.pendingCount = 0
      for (var key in pending)
        pending[key](false, null, root.error)
      restartTimer.restart()
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
        if (ok) {
          root.snapshot = data
          root.considerNotification()
          root.refreshAmbient()
        }
      })
    }
  }
  Timer {
    interval: 30000
    repeat: true
    running: root.canDecorate && (root.snapshot.settings.desktop_card === true || root.idleVisible)
    onTriggered: root.ambientIndex++
  }
  IdleMonitor {
    id: idleStart
    timeout: 60
    enabled: root.snapshot.settings.idle_gallery === true && root.idleDeadline > 65 && root.idleService && root.idleService.idleEnabled
    respectInhibitors: true
  }
  IdleMonitor {
    id: idleEnd
    timeout: Math.max(61, root.idleDeadline - 2)
    enabled: idleStart.enabled
    respectInhibitors: true
  }
  Kani.Ambient {
    service: root
    gallery: root.idleVisible
    showCard: root.canDecorate && root.snapshot.settings.desktop_card === true
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
