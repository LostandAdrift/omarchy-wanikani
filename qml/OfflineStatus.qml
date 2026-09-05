import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  property bool compact: false
  readonly property var snapshot: controller.snapshot || ({})
  readonly property var readiness: snapshot.readiness || null
  readonly property var upcoming: readiness ? readiness.upcoming_reviews || null : null
  readonly property var progress: snapshot.sync_progress || null
  spacing: Style.space(8)

  function availability(group) {
    return group.ready + " / " + (group.total_complete === false ? "?" : group.total)
  }

  function audioCount(field) {
    if (!readiness)
      return 0
    return readiness.reviews[field] + readiness.lessons[field] + (upcoming ? upcoming[field] : 0)
  }

  Label {
    text: "Offline readiness"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: root.readiness && root.readiness.checked_at ? root.availability(root.readiness.reviews) + " reviews due now · " + root.availability(root.readiness.lessons) + " lessons ready offline" : "Checking cached study material…"
    color: root.readiness && root.readiness.complete ? Color.accent : Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    objectName: "upcomingOfflineReadiness"
    Layout.fillWidth: true
    visible: root.upcoming !== null && root.readiness.checked_at !== null
    text: root.upcoming ? "Next 24 hours: " + root.availability(root.upcoming) + " scheduled reviews ready offline" : ""
    font.pixelSize: Style.font.bodySmall
    color: root.readiness && root.readiness.complete ? Color.accent : Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.compact || !!(root.readiness && (!root.readiness.complete || root.readiness.reviews.ready < root.readiness.reviews.total || root.readiness.lessons.ready < root.readiness.lessons.total || (root.upcoming && root.upcoming.ready < root.upcoming.total)))
    text: root.readiness ? root.readiness.message : "Text and required radical images are checked separately from optional pronunciation audio."
    font.pixelSize: Style.font.bodySmall
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.compact && root.readiness !== null
    text: root.readiness ? "Pronunciation cached for " + root.audioCount("audio_cached") + " / " + root.audioCount("audio_total") + " current and scheduled subjects with audio. Missing audio does not block study." : ""
    font.pixelSize: Style.font.bodySmall
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.compact || !!(root.progress && root.progress.active)
    text: root.progress && root.progress.active ? root.progress.message + (root.progress.total !== null ? " · " + root.progress.completed + " / " + root.progress.total : "") : root.snapshot.demo ? "Demo content stays local." : root.snapshot.last_sync ? "Account last refreshed " + Qt.formatDateTime(new Date(root.snapshot.last_sync), "ddd d MMM, HH:mm") + ". New scheduling requires server confirmation." : "Refresh your account while online to cache its current schedule."
    font.pixelSize: Style.font.bodySmall
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    visible: !root.compact
    Action {
      text: root.readiness && root.readiness.checking ? "Checking cache…" : "Check offline availability"
      enabled: !(root.readiness && root.readiness.checking)
      onClicked: root.controller.service.request("readiness", {
        refresh: true
      })
    }
    Action {
      text: "Refresh while online"
      enabled: !root.snapshot.syncing && !!(root.snapshot.connected || root.snapshot.demo)
      onClicked: root.controller.call("sync", {})
    }
  }
}
