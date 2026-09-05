import QtQuick
import QtQuick.Layouts
import qs.Commons
import "LearningDigest.mjs" as LearningDigest

Card {
  id: root
  objectName: "today-activity"
  required property var controller
  readonly property var snapshot: controller.snapshot || ({})
  readonly property var service: controller.service
  readonly property var digest: visible && controller.opened === true && service && service.locked === false ? LearningDigest.project(snapshot.learning_digest, {
    ready: service && service.ready === true && service.learningDigestHydrated === true,
    demo: snapshot.demo,
    epoch: snapshot.session_epoch,
    dirty: service ? service.learningDigestDirty : undefined,
    clockChanged: typeof snapshot.status === "string" ? snapshot.status === "clock_changed" : undefined,
    now: Date.now()
  }) : null
  readonly property var totals: digest ? digest.windows["7"] : null
  readonly property string cacheLabel: digest ? (digest.complete ? "Saved recap" : "Partial saved recap") + (digest.stale === true ? " · needs updating." : " · latest activity not checked.") : "A saved seven-day recap isn’t available yet."
  implicitHeight: content.implicitHeight + Style.space(24)

  function calculationTime() {
    if (!digest)
      return ""
    var date = new Date(digest.generated_at)
    if (!Number.isFinite(date.getTime()))
      return "Calculated " + digest.generated_at
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    var time = [date.getUTCHours(), date.getUTCMinutes(), date.getUTCSeconds()].map(function (part) {
      return String(part).padStart(2, "0")
    }).join(":")
    return "Calculated " + date.getUTCDate() + " " + months[date.getUTCMonth()] + " " + date.getUTCFullYear() + ", " + time + " UTC"
  }

  ColumnLayout {
    id: content
    anchors.fill: parent
    anchors.margins: Style.space(12)
    spacing: Style.space(8)
    Label {
      objectName: "today-activity-heading"
      Layout.fillWidth: true
      text: "Your last seven days here"
      font.bold: true
    }
    Label {
      objectName: "today-activity-scope"
      Layout.fillWidth: true
      text: root.digest && root.digest.demo ? "Demo · recorded on this device" : "Recorded on this device"
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "today-activity-window"
      Layout.fillWidth: true
      visible: root.totals !== null
      text: root.totals ? root.totals.start_day + " – " + root.totals.end_day + " · " + (root.digest.timezone === "system-local" ? "local calendar days" : root.digest.timezone) : ""
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "today-activity-cache"
      Layout.fillWidth: true
      text: root.cacheLabel
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    ColumnLayout {
      objectName: "today-activity-written"
      Layout.fillWidth: true
      visible: root.totals !== null
      spacing: Style.space(4)
      Label {
        Layout.fillWidth: true
        text: "Finished written study"
        font.bold: true
        font.pixelSize: Style.font.bodySmall
      }
      Flow {
        Layout.fillWidth: true
        spacing: Style.space(12)
        Repeater {
          model: root.totals ? [{key: "reviews", label: "Reviews"}, {key: "lessons", label: "Lessons"}, {key: "practice", label: "Practice"}] : []
          Label {
            required property var modelData
            objectName: "today-activity-" + modelData.key
            width: Math.min(implicitWidth, parent.width)
            text: root.totals ? modelData.label + " " + root.totals.subject_completions[modelData.key] : ""
          }
        }
      }
    }
    ColumnLayout {
      objectName: "today-activity-listening"
      Layout.fillWidth: true
      visible: root.totals !== null
      spacing: Style.space(4)
      Label {
        Layout.fillWidth: true
        text: "Meaning listening · your ratings"
        font.bold: true
        font.pixelSize: Style.font.bodySmall
      }
      Label {
        objectName: "today-activity-listening-results"
        Layout.fillWidth: true
        text: root.totals ? root.totals.listening_ratings.remembered + " remembered · " + root.totals.listening_ratings.again + " Again · " + root.totals.listening_ratings.skipped + " skipped" : ""
      }
    }
    ColumnLayout {
      objectName: "today-activity-dictation"
      Layout.fillWidth: true
      visible: root.totals !== null
      spacing: Style.space(4)
      Label {
        Layout.fillWidth: true
        text: "Kana dictation · recording matches"
        font.bold: true
        font.pixelSize: Style.font.bodySmall
      }
      Label {
        objectName: "today-activity-dictation-results"
        Layout.fillWidth: true
        text: root.totals ? root.totals.dictation_ratings.matched + " matched · " + root.totals.dictation_ratings.again + " Again · " + root.totals.dictation_ratings.skipped + " skipped" : ""
      }
    }
    Label {
      objectName: "today-activity-definition"
      Layout.fillWidth: true
      visible: root.totals !== null
      text: "Other devices are not included. Earlier activity stays visible after a reset."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Label {
      objectName: "today-activity-calculated"
      Layout.fillWidth: true
      visible: root.digest !== null
      text: root.calculationTime()
      Accessible.name: root.digest ? "Calculated " + root.digest.generated_at + ". Reporting calendar: " + root.digest.timezone + "." : ""
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Action {
      objectName: "today-activity-explore"
      text: "Explore local activity →"
      accessibleHint: "Open the activity view for seven or thirty days of local study and audio practice"
      enabled: root.controller.opened === true && !(root.service && root.service.locked === true)
      onClicked: root.controller.navigate("activity")
    }
  }
}
