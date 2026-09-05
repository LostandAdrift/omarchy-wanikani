import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme

ColumnLayout {
  id: root
  required property var controller
  readonly property var session: controller.listenSession || null
  readonly property var status: controller.listenStatus || ({})
  readonly property bool interactive: visible && controller.opened && controller.service && controller.service.ready && !controller.service.locked
  readonly property bool preparing: !!(controller.service && controller.service.listeningPreparationJobId)
  readonly property var preparation: status.preparation || ({})
  readonly property var preparationProgress: controller.service && controller.service.listeningPreparationProgress || ({})
  readonly property bool busy: controller.listenBusy === true || preparing
  readonly property bool complete: !!session && session.phase === "complete"
  readonly property bool revealed: !!session && session.phase === "revealed" && !session.unavailable
  readonly property var subject: interactive && revealed && session.subject && typeof session.subject.characters === "string" ? session.subject : null
  readonly property bool hasRecording: !!session && !complete && !session.unavailable && typeof session.media_handle === "string" && session.media_handle.length > 0
  readonly property string cardKey: session ? String(session.id) + ":" + String(session.index) + ":" + String(session.media_handle || "") : ""
  readonly property string contentAccess: controller.contentAccess || ""
  readonly property bool saved: !!status.saved && status.saved.phase !== "complete"
  readonly property int batchSize: Math.min(5, Math.max(1, status.available || 5))
  readonly property int preparationSize: (preparation.ready || 0) + (preparation.needs_download || 0)
  readonly property bool playing: controller.audioContext === "listening" && controller.audioState === "playing"
  readonly property bool loadingAudio: controller.audioContext === "listening" && controller.audioState === "loading"
  readonly property string audioNotice: controller.audioContext === "listening" ? controller.audioNotice || "" : ""
  readonly property string actionError: controller.listenError || ""
  property string playedKey: ""
  property bool autoplayArmed: false
  spacing: Style.space(16)

  function strings(value) {
    return Array.isArray(value) ? value.filter(function (entry) {
      return typeof entry === "string"
    }).slice(0, 32) : []
  }
  function stop() {
    if (controller.audioContext === "listening" && typeof controller.stopAudio === "function")
      controller.stopAudio()
  }
  function play() {
    if (!interactive || busy || !hasRecording || loadingAudio)
      return
    playedKey = cardKey
    controller.playListening()
  }
  function stopPlayback() {
    var wasLoading = loadingAudio
    autoplayArmed = false
    stop()
    // A cancelled media reply may already have saved its first exposure.
    // Reload the authoritative revision before offering another local action.
    if (wasLoading && interactive)
      controller.loadListening()
  }
  function act(action, args) {
    if (!interactive || busy)
      return
    if ((action === "reveal" || action === "rate") && !hasRecording)
      return
    if (action === "rate" && !subject)
      return
    // Only the learner's explicit actions can arm the next sound. Returning
    // to this view, unlocking, and asynchronous background updates cannot.
    autoplayArmed = action === "start" || action === "rate"
    if (action === "start" && saved)
      autoplayArmed = false
    controller.listenAction(action, args || {})
  }
  function changedCard() {
    stop()
    playedKey = ""
    var key = cardKey
    var access = contentAccess
    var armed = autoplayArmed
    autoplayArmed = false
    if (!armed || !interactive || !session || session.phase !== "question" || !hasRecording)
      return
    Qt.callLater(function () {
      if (root.interactive && root.cardKey === key && root.contentAccess === access && root.session.phase === "question" && root.controller.snapshot.settings.autoplay_listening === true)
        root.play()
    })
  }
  onCardKeyChanged: changedCard()
  onInteractiveChanged: {
    if (!interactive) {
      autoplayArmed = false
      stop()
    }
  }
  onContentAccessChanged: {
    autoplayArmed = false
    playedKey = ""
    stop()
  }
  onHasRecordingChanged: if (!hasRecording)
    stop()
  onBusyChanged: if (!busy && controller.listenError)
    autoplayArmed = false
  onActionErrorChanged: if (actionError)
    autoplayArmed = false
  Component.onDestruction: stop()

  Label {
    Layout.fillWidth: true
    text: "LISTENING PRACTICE · LOCAL PROGRESS"
    secondary: true
    font.pixelSize: Style.font.bodySmall
    font.letterSpacing: 1.5
  }
  Label {
    objectName: "listeningError"
    Layout.fillWidth: true
    visible: !!root.controller.listenError
    text: root.controller.listenError || ""
    textColor: Color.urgent
  }

  Action {
    objectName: "listeningReload"
    visible: !!root.controller.listenError
    text: "Reload listening"
    enabled: root.interactive && !root.busy
    onClicked: root.controller.loadListening()
  }

  Card {
    id: introduction
    Layout.fillWidth: true
    visible: !root.session
    implicitHeight: welcome.implicitHeight + Style.space(36)
    ColumnLayout {
      id: welcome
      anchors.fill: parent
      anchors.margins: Style.space(18)
      spacing: Style.space(14)
      Label {
        Layout.fillWidth: true
        text: "Know it by ear."
        font.pixelSize: Style.space(30)
        font.bold: true
      }
      Label {
        Layout.fillWidth: true
        text: "Listen to a familiar word, recall a meaning, then reveal it. Five quiet moments of Japanese, at your pace."
      }
      Label {
        objectName: "listeningAvailability"
        Layout.fillWidth: true
        text: root.saved ? "Your listening session is saved, separately from lessons and reviews." : root.preparing ? "Preparing your next listening break…" : root.busy ? "Checking familiar recordings…" : (root.status.available || 0) > 0 ? (root.status.complete === false ? "At least " : "") + root.status.available + " familiar recordings ready · " + (root.status.new_remaining || 0) + " new words left today" : root.status.new_remaining === 0 ? "Today's five new listening words are complete. Due local listening words will return at their next interval." : root.preparation.message || root.status.message || "Refresh your account and download vocabulary audio to begin. Learned words with cached recordings will appear here."
        secondary: true
      }
      Flow {
        Layout.fillWidth: true
        spacing: Style.space(8)
        Action {
          objectName: "listeningStart"
          text: root.saved ? "Resume listening" : "Listen to " + root.batchSize + (root.batchSize === 1 ? " word" : " words")
          enabled: root.interactive && !root.busy && (root.saved || (root.status.available || 0) > 0)
          onClicked: root.act("start", {})
        }
        Action {
          objectName: "listeningDuePreference"
          text: root.status.settings && root.status.settings.avoid_due_24h === false ? "Include due-soon words ✓" : "Include due-soon words"
          enabled: root.interactive && !root.busy
          onClicked: root.act("settings", {
            avoid_due_24h: !!(root.status.settings && root.status.settings.avoid_due_24h === false)
          })
        }
      }
      Label {
        Layout.fillWidth: true
        text: "Saved graded questions and their matching readings stay protected. Listening never clears WaniKani reviews or changes your level."
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
    }
  }

  Card {
    id: studyCard
    Layout.fillWidth: true
    visible: !!root.session && !root.complete
    implicitHeight: studyContent.implicitHeight + Style.space(36)
    ColumnLayout {
      id: studyContent
      anchors.fill: parent
      anchors.margins: Style.space(18)
      spacing: Style.space(18)
      Label {
        objectName: "listeningPosition"
        Layout.fillWidth: true
        text: root.session ? "WORD " + (root.session.index + 1) + " OF " + root.session.total : ""
        font.pixelSize: Style.font.bodySmall
        font.letterSpacing: 2
        horizontalAlignment: Text.AlignHCenter
        secondary: true
      }
      Row {
        Layout.alignment: Qt.AlignHCenter
        spacing: Style.space(5)
        Layout.preferredHeight: Style.space(58)
        Accessible.ignored: true
        Repeater {
          model: [12, 24, 38, 52, 34, 58, 34, 52, 38, 24, 12]
          Rectangle {
            required property int modelData
            width: Style.space(5)
            height: Style.space(modelData)
            y: (Style.space(58) - height) / 2
            radius: width / 2
            color: Theme.indicator(root.playing ? Color.accent : Color.foreground, studyCard.color, Color.foreground)
            opacity: root.playing ? 1 : 0.45
          }
        }
      }
      Label {
        objectName: "listeningPrompt"
        Layout.fillWidth: true
        visible: !root.subject
        text: "What does this word mean?"
        horizontalAlignment: Text.AlignHCenter
        font.pixelSize: Style.space(24)
        font.bold: true
      }
      Label {
        Layout.fillWidth: true
        visible: !root.subject && !(root.session && root.session.unavailable)
        text: "Recall a meaning. Replay as often as you like."
        secondary: true
        horizontalAlignment: Text.AlignHCenter
      }
      Label {
        objectName: "listeningUnavailable"
        Layout.fillWidth: true
        visible: !!(root.session && root.session.unavailable)
        text: root.session ? root.session.unavailable || "" : ""
        textColor: Color.urgent
      }
      Action {
        objectName: "listeningNewContext"
        visible: !!(root.session && root.session.unavailable) && !root.status.saved
        text: "Start a new local session"
        enabled: root.interactive && !root.busy && (root.status.available || 0) > 0
        onClicked: root.act("start", {})
      }
      RowLayout {
        Layout.alignment: Qt.AlignHCenter
        spacing: Style.space(8)
        Action {
          objectName: "listeningPlay"
          text: root.loadingAudio ? "Preparing…" : root.controller.audioContext === "listening" && root.controller.audioState === "failed" ? "Retry recording" : root.playedKey === root.cardKey ? "Replay recording" : "Play recording"
          accessibleName: text
          enabled: root.interactive && !root.busy && root.hasRecording && !root.loadingAudio
          onClicked: root.play()
        }
        Action {
          objectName: "listeningStop"
          visible: root.playing || root.loadingAudio
          text: "Stop"
          accessibleName: "Stop listening recording"
          enabled: root.interactive
          onClicked: root.stopPlayback()
        }
      }
      Label {
        objectName: "listeningAudioNotice"
        Layout.fillWidth: true
        visible: root.audioNotice.length > 0
        text: root.audioNotice
        secondary: true
        horizontalAlignment: Text.AlignHCenter
      }
      Action {
        objectName: "listeningReveal"
        Layout.alignment: Qt.AlignHCenter
        visible: !root.revealed
        text: "Reveal word"
        enabled: root.interactive && !root.busy && root.hasRecording
        onClicked: root.act("reveal", {})
      }
      Loader {
        id: answerLoader
        objectName: "listeningAnswer"
        Layout.fillWidth: true
        active: root.interactive && root.subject !== null
        visible: active
        sourceComponent: ColumnLayout {
          spacing: Style.space(12)
          Label {
            objectName: "listeningCharacters"
            Layout.fillWidth: true
            text: root.subject ? root.subject.characters : ""
            horizontalAlignment: Text.AlignHCenter
            font.family: "Noto Sans CJK JP"
            font.pixelSize: Style.space(58)
            wrapMode: Text.WrapAnywhere
          }
          Label {
            objectName: "listeningReading"
            Layout.fillWidth: true
            text: root.subject && typeof root.subject.pronunciation === "string" ? root.subject.pronunciation : ""
            horizontalAlignment: Text.AlignHCenter
            font.family: "Noto Sans CJK JP"
            font.pixelSize: Style.space(25)
            textColor: Color.accent
          }
          Label {
            objectName: "listeningMeaning"
            Layout.fillWidth: true
            text: root.subject ? root.strings(root.subject.meanings).join(" · ") : ""
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: Style.space(22)
            font.bold: true
          }
          Label {
            Layout.fillWidth: true
            visible: root.audioNotice.length === 0
            text: "Original WaniKani recording" + (root.subject && typeof root.subject.voice === "string" ? " · " + root.subject.voice : "")
            secondary: true
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            Layout.fillWidth: true
            visible: !!(root.subject && root.subject.local_progress && root.subject.local_progress.attempts > 0)
            text: visible ? root.subject.local_progress.attempts + " previous local listening " + (root.subject.local_progress.attempts === 1 ? "rating" : "ratings") : ""
            secondary: true
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: Style.font.bodySmall
          }
          Repeater {
            model: root.subject && root.subject.material ? [root.subject.material.meaning_note, root.subject.material.reading_note].filter(function (note) {
              return typeof note === "string" && note.length > 0
            }) : []
            Label {
              required property string modelData
              Layout.fillWidth: true
              text: modelData
              secondary: true
            }
          }
          Label {
            objectName: "listeningAmbiguity"
            Layout.fillWidth: true
            text: root.subject && typeof root.subject.ambiguity_note === "string" ? root.subject.ambiguity_note : ""
            secondary: true
            font.pixelSize: Style.font.bodySmall
          }
          Repeater {
            model: root.subject && Array.isArray(root.subject.alternatives) ? root.subject.alternatives.slice(0, 8) : []
            Label {
              required property int index
              readonly property var candidate: root.subject && root.subject.alternatives ? root.subject.alternatives[index] : null
              Layout.fillWidth: true
              text: candidate && typeof candidate.characters === "string" ? candidate.characters + " · " + root.strings(candidate.meanings).join(" · ") : ""
              secondary: true
              font.pixelSize: Style.font.bodySmall
            }
          }
          Flow {
            Layout.fillWidth: true
            spacing: Style.space(8)
            Action {
              objectName: "listeningRemembered"
              text: "Got it" + (root.session && root.session.intervals ? " · " + root.session.intervals.remembered_days + (root.session.intervals.remembered_days === 1 ? " day" : " days") : "")
              enabled: root.interactive && !root.busy && root.hasRecording
              onClicked: root.act("rate", {
                rating: "remembered"
              })
            }
            Action {
              objectName: "listeningAgain"
              text: "Again · 10 minutes"
              enabled: root.interactive && !root.busy && root.hasRecording
              onClicked: root.act("rate", {
                rating: "again"
              })
            }
          }
        }
      }
      Flow {
        Layout.fillWidth: true
        spacing: Style.space(8)
        Action {
          objectName: "listeningSkip"
          text: "Skip this word"
          enabled: root.interactive && !root.busy
          onClicked: root.act("skip", {})
        }
        Action {
          objectName: "listeningUndo"
          visible: !!(root.session && root.session.undo_available)
          text: "Undo last rating"
          enabled: root.interactive && !root.busy
          onClicked: root.act("undo", {})
        }
      }
    }
  }

  Card {
    Layout.fillWidth: true
    visible: root.complete
    implicitHeight: recap.implicitHeight + Style.space(36)
    ColumnLayout {
      id: recap
      anchors.fill: parent
      anchors.margins: Style.space(18)
      spacing: Style.space(14)
      Label {
        Layout.fillWidth: true
        text: "A little more familiar."
        font.pixelSize: Style.space(30)
        font.bold: true
      }
      Label {
        objectName: "listeningSummary"
        Layout.fillWidth: true
        text: root.session && root.session.summary ? root.session.summary.remembered + " recalled · " + root.session.summary.again + " to revisit · " + root.session.summary.skipped + " skipped" : ""
      }
      Label {
        Layout.fillWidth: true
        text: "Your listening ratings are saved locally. Words marked Again can return in a later session; this batch is finished."
        secondary: true
      }
      Flow {
        Layout.fillWidth: true
        spacing: Style.space(8)
        Action {
          objectName: "listeningAnother"
          text: "Listen to " + root.batchSize + " more"
          enabled: root.interactive && !root.busy && (root.status.available || 0) > 0
          onClicked: root.act("start", {})
        }
        Action {
          objectName: "listeningDone"
          text: "Back to work"
          enabled: root.interactive
          onClicked: root.controller.close()
        }
        Action {
          objectName: "listeningFinalUndo"
          visible: !!(root.session && root.session.undo_available)
          text: "Undo last rating"
          enabled: root.interactive && !root.busy
          onClicked: root.act("undo", {})
        }
      }
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: (!root.session || root.complete) && !root.saved
    spacing: Style.space(10)
    Label {
      Layout.fillWidth: true
      visible: (root.preparation.needs_download || 0) > 0 && !root.preparing
      text: (root.preparation.ready || 0) + " ready · " + (root.preparation.needs_download || 0) + (root.preparation.needs_download === 1 ? " recording can be prepared. " : " recordings can be prepared. ") + "Downloads keep your listening words hidden until you start and reveal them."
      secondary: true
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      Action {
        objectName: "listeningPrepare"
        visible: !root.preparing && (root.preparation.needs_download || 0) > 0
        text: "Prepare " + root.preparationSize + (root.preparationSize === 1 ? " recording" : " recordings")
        enabled: root.interactive && !root.busy && root.preparation.reason !== "offline"
        accessibleHint: "Cache up to five familiar recordings without starting study or playing audio"
        onClicked: root.controller.prepareListening()
      }
      Action {
        objectName: "listeningPrepareCancel"
        visible: root.preparing
        text: root.controller.service && root.controller.service.listeningPreparationCancelling ? "Stopping…" : "Cancel preparation"
        enabled: root.interactive && !root.controller.service.listeningPreparationCancelling
        onClicked: root.controller.service.cancelListeningPreparation()
      }
    }
    Label {
      objectName: "listeningPrepareProgress"
      Layout.fillWidth: true
      visible: root.preparing
      text: (root.preparationProgress.downloaded || 0) + " saved · " + (root.preparationProgress.already_cached || 0) + " already cached" + (root.controller.service && root.controller.service.listeningPreparationCancelling ? ". Finishing the current file, then stopping." : ". You choose when to start listening afterward.")
      secondary: true
    }
    Label {
      objectName: "listeningPrepareNotice"
      Layout.fillWidth: true
      visible: !!root.controller.listenPreparationNotice
      text: root.controller.listenPreparationNotice || ""
      secondary: true
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!root.session
    text: "Local listening practice. Your WaniKani lessons, reviews, and SRS stages stay as they are."
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
}
