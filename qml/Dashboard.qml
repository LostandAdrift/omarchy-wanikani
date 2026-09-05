import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  readonly property var s: controller.snapshot
  spacing: Style.space(18)
  Label {
    Layout.fillWidth: true
    text: s.username ? (s.reviews > 0 ? "A little progress goes a long way." : "A moment to breathe.") : "Make Japanese part of your day."
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    visible: !s.username
    text: "Native lessons and reviews, ready whenever you have a few minutes. Connect your WaniKani account or explore with sample material."
    secondary: true
  }
  Card {
    Layout.fillWidth: true
    Layout.preferredHeight: milestoneRow.implicitHeight + Style.space(24)
    visible: !!root.s.milestone
    RowLayout {
      id: milestoneRow
      anchors.fill: parent
      anchors.margins: Style.space(12)
      spacing: Style.space(14)
      Crab {
        Layout.preferredWidth: Style.space(64)
        Layout.preferredHeight: Style.space(52)
        animate: root.controller.opened && root.controller.service && root.controller.service.animations
        celebrating: visible && !!root.s.milestone
      }
      ColumnLayout {
        Layout.fillWidth: true
        Label {
          Layout.fillWidth: true
          text: root.s.milestone ? (root.s.demo ? "Demo milestone · Level " + root.s.milestone.level : "Level " + root.s.milestone.level + " confirmed") : ""
          font.bold: true
          textColor: Color.accent
        }
        Label {
          Layout.fillWidth: true
          text: root.s.demo ? "A presentation preview using authored fixtures. Account milestones appear only after WaniKani confirms a new level." : "WaniKani confirmed your account’s new level. A little progress, shared across your devices."
          secondary: true
          font.pixelSize: Style.font.bodySmall
        }
      }
      Action {
        text: "Dismiss"
        accessibleName: "Dismiss confirmed level milestone"
        enabled: !root.controller.busy
        onClicked: root.controller.call("ack_milestone", {
          id: root.s.milestone.id
        })
      }
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    visible: !s.username
    Action {
      text: "Connect WaniKani"
      selected: true
      onClicked: root.controller.navigate("settings")
    }
    Action {
      text: "Try the demo"
      onClicked: root.controller.call("use_demo", {
        enabled: true
      })
    }
  }
  GridLayout {
    Layout.fillWidth: true
    columns: root.width < Style.space(480) ? 1 : 2
    columnSpacing: Style.space(12)
    rowSpacing: Style.space(12)
    visible: !!s.username
    Repeater {
      model: [
        {
          label: "Reviews",
          mode: "reviews",
          value: root.s.reviews || 0
        },
        {
          label: "Lessons",
          mode: "lessons",
          value: root.s.lessons || 0
        }
      ]
      Card {
        id: studyCard
        required property var modelData
        readonly property var saved: root.s.saved_sessions ? root.s.saved_sessions[modelData.mode] : null
        Layout.fillWidth: true
        Layout.preferredHeight: studyCardContent.implicitHeight + Style.space(32)
        ColumnLayout {
          id: studyCardContent
          anchors.fill: parent
          anchors.margins: Style.space(16)
          spacing: Style.space(8)
          Label {
            Layout.fillWidth: true
            text: studyCard.modelData.label
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Label {
            text: studyCard.modelData.value + (studyCard.modelData.mode === "reviews" ? " due" : " new")
            font.pixelSize: Style.space(40)
            textColor: Color.accent
          }
          Label {
            Layout.fillWidth: true
            text: studyCard.saved ? studyCard.saved.completed + " of " + studyCard.saved.total + " subjects completed · Session saved" : studyCard.modelData.mode === "reviews" ? "Recall subjects you have learned." : "Discover new meanings and readings."
            font.pixelSize: Style.font.bodySmall
          }
          Flow {
            Layout.fillWidth: true
            spacing: Style.space(6)
            Action {
              text: studyCard.saved ? "Resume " + studyCard.modelData.mode + " →" : studyCard.modelData.mode === "reviews" ? "Review 5 →" : "Choose lessons →"
              selected: true
              enabled: !root.controller.busy && (!!studyCard.saved || (studyCard.modelData.value > 0 && !root.s.vacation))
              onClicked: {
                if (studyCard.saved || studyCard.modelData.mode === "reviews")
                  root.controller.begin(studyCard.modelData.mode, 5)
                else
                  root.controller.navigate("lesson-overview")
              }
            }
            Action {
              text: "Overview"
              accessibleName: studyCard.modelData.label + " overview"
              onClicked: root.controller.navigate(studyCard.modelData.mode === "reviews" ? "review-overview" : "lesson-overview")
            }
          }
        }
      }
    }
  }
  LevelProgress {
    Layout.fillWidth: true
    visible: !!root.s.username
    progress: root.s.learning_progress || null
    onExplore: root.controller.navigate("progress")
  }
  Card {
    Layout.fillWidth: true
    visible: !!root.s.username
    implicitHeight: listenInvitation.implicitHeight + Style.space(28)
    ColumnLayout {
      id: listenInvitation
      anchors.fill: parent
      anchors.margins: Style.space(14)
      spacing: Style.space(8)
      Label {
        text: "Give your eyes a break"
        font.bold: true
      }
      Label {
        Layout.fillWidth: true
        text: "Hear familiar vocabulary, reveal the word, then choose Got it or Again. Listening has its own local practice schedule."
        secondary: true
      }
      Action {
        text: "Open Listen 5 →"
        onClicked: root.controller.navigate("listen")
      }
    }
  }
  Label {
    Layout.fillWidth: true
    visible: s.vacation === true
    text: "Vacation mode is on. Take your time; ungraded practice is available."
    textColor: Color.accent
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    visible: !!s.username
    Action {
      text: "Refresh"
      enabled: !root.s.syncing
      onClicked: root.controller.call("sync", {})
    }
    Action {
      text: "Snooze reminders · 1h"
      onClicked: root.controller.service.configureRhythm({
        action: "snooze",
        minutes: 60
      })
    }
  }
  Label {
    Layout.fillWidth: true
    visible: !!s.message
    text: s.message || ""
    textColor: Color.urgent
  }
  OfflineStatus {
    Layout.fillWidth: true
    visible: !!root.s.username
    controller: root.controller
    compact: true
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: !!s.username
    spacing: Style.space(9)
    Forecast {
      Layout.fillWidth: true
      forecast: root.s.forecast || []
      snapshotTime: root.s.now || 0
      nextReviewsAt: root.s.next_reviews_at || ""
      active: root.controller.opened && root.visible
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: (s.difficult || []).length > 0
    Label {
      text: "Worth another look"
      font.bold: true
    }
    Label {
      Layout.fillWidth: true
      text: "Practice recent mistakes and subjects with lower recorded accuracy. Practice never changes your WaniKani schedule."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: root.s.difficult || []
        Action {
          required property var modelData
          text: (modelData.characters || modelData.slug) + " · " + modelData.meanings[0]
          onClicked: root.controller.showSubject(modelData.id)
        }
      }
    }
    Action {
      text: "Practice these items"
      onClicked: root.controller.begin("practice", 5, (root.s.difficult || []).map(function (x) {
        return x.id
      }))
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: !!s.username
    Label {
      text: "Your activity here"
      font.bold: true
    }
    Label {
      Layout.fillWidth: true
      text: (s.activity || []).length ? "Completed subjects and practice recorded by this plugin. Other clients are not included." : "Your first session starts the story. Activity from other clients is not available as individual review history."
      font.pixelSize: Style.font.bodySmall
      secondary: true
    }
    Action {
      text: "Explore local activity →"
      accessibleHint: "See seven or thirty days of local study, listening, and saved-submission status"
      onClicked: root.controller.navigate("activity")
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: root.s.activity || []
        Card {
          required property var modelData
          width: Style.space(90)
          height: Style.space(58)
          Column {
            anchors.centerIn: parent
            Label {
              text: modelData.day.slice(5)
              font.pixelSize: Style.font.bodySmall
              secondary: true
            }
            Label {
              text: String(modelData.count)
              font.bold: true
              textColor: Color.accent
            }
          }
        }
      }
    }
  }
  Action {
    visible: (s.attention || 0) > 0 || (s.pending || 0) > 0
    text: s.attention > 0 ? "Review " + s.attention + " sync issue(s)" : "View " + s.pending + " pending submission(s)"
    onClicked: root.controller.navigate("recovery")
  }
}
