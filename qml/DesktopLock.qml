import QtQuick
import Quickshell.Io
import "LockStatus.mjs" as LockStatus

// Omarchy 4.0.3 scopes serviceFor() to the calling plugin. Read only the
// public status IPC when the legacy live lock service is unavailable.
Item {
  id: root
  property bool initialized: false
  property bool active: false
  property bool visibleSurface: false
  property bool known: false
  property bool lockedValue: true
  readonly property bool locked: !known || lockedValue
  property var callbacks: []

  function check(callback) {
    if (typeof callback === "function")
      callbacks = callbacks.concat([callback])
    if (!active) {
      finish("", false)
      return
    }
    if (!probe.running)
      probe.running = true
  }
  function finish(text, succeeded) {
    var result = LockStatus.decode(text, succeeded && active)
    known = result.known
    lockedValue = result.locked
    var waiting = callbacks
    callbacks = []
    for (var callback of waiting)
      callback(result.known && !result.locked)
  }
  onActiveChanged: {
    if (!initialized)
      return
    if (active)
      check()
    else {
      probe.running = false
      finish("", false)
    }
  }
  Timer {
    interval: root.visibleSurface ? 1000 : 15000
    running: root.active
    repeat: true
    onTriggered: root.check()
  }
  Process {
    id: probe
    objectName: "desktop-lock-probe"
    command: ["timeout", "--kill-after=1s", "3s", "omarchy-shell", "lock", "status"]
    stdout: StdioCollector { id: output }
    stderr: StdioCollector {}
    onExited: function (code, status) {
      root.finish(output.text, code === 0 && status === 0)
    }
  }
  Component.onCompleted: {
    initialized = true
    if (active)
      check()
  }
  Component.onDestruction: {
    callbacks = []
    probe.running = false
  }
}
