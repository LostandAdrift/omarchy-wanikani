import QtQuick
import QtMultimedia

// One local practice adapter; the panel still owns the only audio player.
Item {
  id: root
  required property var controller
  required property var player
  property var session: null
  property var status: null
  property string error: ""
  property string draftError: ""
  property string mediaNotice: ""
  property bool loading: false
  property bool actionBusy: false
  property bool mediaBusy: false
  property bool heardBusy: false
  property bool audioRecovering: false
  property int sequence: 0
  property int audioSequence: 0
  property int draftSequence: 0
  property var ticket: null
  readonly property var service: controller.service
  readonly property bool active: controller.opened && controller.view === "dictation" && !!service && service.ready && !service.locked
  readonly property string context: JSON.stringify([controller.contentAccess, controller.navigationSequence, controller.snapshot.last_sync, controller.snapshot.session_revision, controller.snapshot.pending, controller.snapshot.attention, controller.snapshot.syncing, controller.snapshot.status])
  readonly property bool heard: !!session && session.heard === true && !session.unavailable
  readonly property bool playing: !!ticket && player.playbackState === MediaPlayer.PlayingState
  readonly property bool canCheck: active && !!session && session.phase === "question" && heard && !loading && !actionBusy && !mediaBusy && !heardBusy && !audioRecovering

  onActiveChanged: invalidate()
  onContextChanged: invalidate()
  onServiceChanged: invalidate()
  Component.onCompleted: invalidate()

  function invalidate() {
    sequence++
    draftSequence++
    loading = false
    actionBusy = false
    heardBusy = false
    if (controller.audioContext === "dictation")
      controller.stopAudio()
    else
      cancelAudio()
    session = null
    status = null
    error = ""
    draftError = ""
    if (active)
      Qt.callLater(refresh)
  }
  function current(serial, access, owner) {
    return active && sequence === serial && context === access && service === owner
  }
  function validSession(value) {
    if (value === null)
      return true
    return !!value && typeof value.id === "string" && value.id.length > 0 && Number.isInteger(value.revision) && value.revision > 0 && ["question", "feedback", "complete"].indexOf(value.phase) >= 0 && Number.isInteger(value.index) && Number.isInteger(value.total) && value.total > 0 && value.total <= 5 && value.index >= 0 && value.index <= value.total && value.local_only === true && (value.phase !== "question" || (value.subject === null && value.feedback === null))
  }
  function apply(value) {
    if (!validSession(value)) {
      error = "The dictation reply could not be read. Refresh to recover saved work."
      return false
    }
    session = value
    return true
  }
  function refresh(keepError) {
    if (!active || loading || actionBusy || mediaBusy || heardBusy || audioRecovering)
      return
    controller.stopAudio()
    var serial = ++sequence
    var access = context
    var owner = service
    loading = true
    if (keepError !== true)
      error = ""
    owner.request("dictation_state", {}, function (ok, data, message) {
      if (!root.current(serial, access, owner))
        return
      root.loading = false
      if (ok && data && root.apply(data.session))
        root.status = data.status
      else if (!ok)
        root.error = message || "Dictation could not be loaded. Your saved work is retained."
    })
  }
  function action(name, extra) {
    if (!active || loading || actionBusy || mediaBusy || heardBusy || audioRecovering)
      return
    if (name !== "start" && !session)
      return
    controller.stopAudio()
    draftSequence++
    var values = Object.assign({}, extra || {}, {
      action: name
    })
    if (name !== "start") {
      values.session_id = session.id
      values.revision = session.revision
    }
    var serial = ++sequence
    var access = context
    var owner = service
    actionBusy = true
    error = ""
    owner.request("dictation", values, function (ok, data, message) {
      if (!root.current(serial, access, owner))
        return
      root.actionBusy = false
      if (ok && data) {
        if (root.apply(data.session)) {
          root.draftError = ""
          if (data.session && data.session.phase === "complete")
            Qt.callLater(root.refresh)
        }
      } else {
        root.error = message || "That dictation action could not be confirmed. Refresh before trying again."
        // Re-read durable state; never automatically replay a local action.
        root.refresh(true)
      }
    })
  }
  function start() {
    action("start", {})
  }
  function check(text) {
    if (canCheck && typeof text === "string")
      action("check", {
        text: text
      })
  }
  function advance() {
    if (session && session.phase === "feedback" && !session.unavailable)
      action("continue", {})
  }
  function skip() {
    if (session && session.phase !== "complete")
      action("skip", {})
  }
  function undo() {
    if (session && session.undo_available === true)
      action("undo", {})
  }
  function saveDraft(text, cursor, preedit) {
    if (!active || !session || session.phase !== "question" || !session.media_handle || actionBusy)
      return
    var serial = ++draftSequence
    var access = context
    var owner = service
    var identity = session.id
    var handle = session.media_handle
    // Send immediately on the ordered worker pipe. Check carries final text;
    // there is no delayed draft that could overwrite a retryable check.
    owner.request("dictation_draft", {
      session_id: identity,
      handle: handle,
      text: text,
      cursor: cursor,
      preedit: preedit || ""
    }, function (ok, data, message) {
      if (!root.active || root.draftSequence !== serial || root.context !== access || root.service !== owner || !root.session || root.session.id !== identity || root.session.media_handle !== handle)
        return
      root.draftError = ok && data && data.saved === true ? "" : message || "This draft has not been confirmed saved. Keep this view open and retry the edit."
    // An acknowledgement never replaces the input control's newer buffer.
    })
  }
  function cancelAudio() {
    // Pure cancellation: Panel.stopAudio calls this before stopping the player.
    var uncertainReply = mediaBusy || heardBusy || audioRecovering
    audioSequence++
    ticket = null
    mediaBusy = false
    heardBusy = false
    mediaNotice = ""
    audioRecovering = uncertainReply && active
    if (audioRecovering) {
      var serial = audioSequence
      Qt.callLater(function () {
        if (root.audioSequence !== serial)
          return
        root.audioRecovering = false
        // The prior message can have committed before Stop. This read follows
        // it on the same ordered pipe, before another local action is enabled.
        if (root.active)
          root.refresh(true)
      })
    }
  }
  function audioCurrent(value) {
    return !!value && active && value.serial === audioSequence && value.access === context && value.owner === service && value.panelAudio === controller.audioSequence && !!session && session.id === value.sessionId && session.media_handle === value.handle && String(player.source) === value.uri
  }
  function play() {
    if (playing) {
      controller.stopAudio()
      return
    }
    if (!active || !session || !session.media_handle || session.unavailable || loading || actionBusy || mediaBusy || heardBusy || audioRecovering)
      return
    controller.stopAudio()
    var serial = ++audioSequence
    var access = context
    var owner = service
    var identity = session.id
    var handle = session.media_handle
    var panelAudio = controller.audioSequence
    mediaBusy = true
    mediaNotice = "Opening the cached recording…"
    controller.audioContext = "dictation"
    controller.audioState = "loading"
    owner.request("dictation_media", {
      handle: handle
    }, function (ok, data, message) {
      if (!root.active || root.audioSequence !== serial || root.context !== access || root.service !== owner || root.controller.audioSequence !== panelAudio || !root.session || root.session.id !== identity || root.session.media_handle !== handle)
        return
      root.mediaBusy = false
      if (!ok || !data || data.handle !== handle || data.session_id !== identity || !data.session || data.session.id !== identity || data.session.media_handle !== handle || data.revision !== data.session.revision || typeof data.playback_token !== "string" || !data.playback_token || typeof data.uri !== "string" || data.uri.indexOf("file:///") !== 0 || !root.apply(data.session)) {
        root.error = message || "This recording could not be opened. Refresh or skip without a result."
        root.controller.audioState = "failed"
        root.refresh(true)
        return
      }
      root.mediaNotice = "Original recording · " + (data.voice || "WaniKani")
      root.controller.audioNotice = root.mediaNotice
      root.player.source = data.uri
      root.ticket = {
        serial: serial,
        access: access,
        owner: owner,
        panelAudio: panelAudio,
        sessionId: identity,
        handle: handle,
        uri: data.uri,
        revision: data.revision,
        token: data.playback_token,
        started: false
      }
      root.player.play()
    })
  }
  function playbackChanged() {
    var value = ticket
    if (!audioCurrent(value))
      return
    if (player.playbackState === MediaPlayer.PlayingState) {
      ticket = Object.assign({}, value, {
        started: true
      })
    } else if (player.playbackState === MediaPlayer.StoppedState) {
      Qt.callLater(function () {
        if (root.ticket === value && root.player.playbackState === MediaPlayer.StoppedState && root.player.mediaStatus !== MediaPlayer.EndOfMedia)
          root.playbackFailed("Playback stopped before the recording finished. Replay to enable Check.")
      })
    }
  }
  function playbackFailed(message) {
    if (!ticket && !mediaBusy)
      return
    cancelAudio()
    mediaNotice = message || "Playback failed. Check the output device and replay."
  }
  function playbackFinished() {
    var value = ticket
    if (player.mediaStatus !== MediaPlayer.EndOfMedia || !audioCurrent(value) || !value.started)
      return
    ticket = null
    if (session.heard === true)
      return
    heardBusy = true
    var serial = sequence
    value.owner.request("dictation", {
      action: "heard",
      session_id: value.sessionId,
      revision: value.revision,
      handle: value.handle,
      playback_token: value.token
    }, function (ok, data, message) {
      if (!root.current(serial, value.access, value.owner) || root.audioSequence !== value.serial || root.controller.audioSequence !== value.panelAudio || !root.session || root.session.id !== value.sessionId || root.session.media_handle !== value.handle)
        return
      root.heardBusy = false
      if (ok && data)
        root.apply(data.session)
      else {
        root.error = message || "Playback completion could not be confirmed. Refresh, then replay if needed."
        root.refresh(true)
      }
    })
  }
  Connections {
    target: root.player
    function onPlaybackStateChanged() {
      root.playbackChanged()
    }
    function onMediaStatusChanged() {
      root.playbackFinished()
    }
    function onErrorOccurred() {
      root.playbackFailed("")
    }
  }
}
