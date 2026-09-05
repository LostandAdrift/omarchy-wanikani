pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var controller
  property string returnView: "dashboard"
  property bool navigationShortcutsEnabled: false
  property bool helpShortcutEnabled: false
  readonly property var basicShortcuts: [
    {
      key: "Escape",
      action: "Save and return to work"
    },
    {
      key: "Enter",
      action: "Check an answer, then continue from feedback"
    },
    {
      key: "Tab / Shift+Tab",
      action: "Move to the next or previous control"
    },
    {
      key: "Enter / Space",
      action: "Use the focused button"
    }
  ]
  readonly property var navigationShortcuts: [
    {
      key: "Ctrl+1",
      action: "Today"
    },
    {
      key: "Ctrl+2",
      action: "Study or resume"
    },
    {
      key: "Ctrl+3",
      action: "Lookup"
    },
    {
      key: "Ctrl+4",
      action: "Zen"
    },
    {
      key: "Ctrl+5",
      action: "Settings"
    },
    {
      key: "Ctrl+6",
      action: "Practice library"
    },
    {
      key: "Ctrl+7",
      action: "Listening practice"
    },
    {
      key: "Ctrl+8",
      action: "Level progress"
    },
    {
      key: "Ctrl+9",
      action: "Local learning activity"
    }
  ]
  spacing: Style.space(16)

  function focusInput() {
    returnButton.forceActiveFocus(Qt.TabFocusReason)
  }
  function returnToView() {
    if (typeof controller.closeHelp === "function")
      controller.closeHelp()
    else
      controller.navigate(returnView)
  }

  Label {
    Layout.fillWidth: true
    text: "Keyboard shortcuts"
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Your question and draft stay saved when you close the panel."
    secondary: true
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(8)
    Action {
      id: returnButton
      text: "Back to " + ({
          dashboard: "Today",
          study: "study",
          lookup: "lookup",
          zen: "Zen",
          settings: "Settings",
          recovery: "saved submissions",
          "review-overview": "Reviews",
          "lesson-overview": "Lessons",
          progress: "Progress",
          listen: "Listen",
          dictation: "Type kana",
          activity: "Activity",
          "practice-library": "practice"
        }[root.returnView] || "Today")
      selected: true
      accessibleHint: "Return to the page you opened help from"
      onClicked: root.returnToView()
    }
    Action {
      text: "Back to work"
      accessibleHint: "Close WaniKani and keep your saved study session"
      onClicked: root.controller.dismiss()
    }
  }
  Repeater {
    model: root.basicShortcuts
    RowLayout {
      id: basicRow
      required property var modelData
      Layout.fillWidth: true
      spacing: Style.space(14)
      Label {
        Layout.preferredWidth: Math.min(Style.space(200), root.width * 0.38)
        text: basicRow.modelData.key
        font.bold: true
        textColor: Color.accent
      }
      Label {
        Layout.fillWidth: true
        text: basicRow.modelData.action
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: "For reading answers, type romaji or use your Japanese input method. You can edit the answer with the usual text keys."
    secondary: true
  }
  RowLayout {
    Layout.fillWidth: true
    visible: root.helpShortcutEnabled
    spacing: Style.space(14)
    Label {
      Layout.preferredWidth: Math.min(Style.space(200), root.width * 0.38)
      text: "F1"
      font.bold: true
      textColor: Color.accent
    }
    Label {
      Layout.fillWidth: true
      text: "Show or close this help"
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.navigationShortcutsEnabled
    spacing: Style.space(10)
    Label {
      Layout.fillWidth: true
      text: "Move around the panel"
      font.bold: true
    }
    Label {
      Layout.fillWidth: true
      text: "These shortcuts work when you are outside a text field."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Repeater {
      model: root.navigationShortcutsEnabled ? root.navigationShortcuts : []
      RowLayout {
        id: navigationRow
        required property var modelData
        Layout.fillWidth: true
        spacing: Style.space(14)
        Label {
          Layout.preferredWidth: Math.min(Style.space(200), root.width * 0.38)
          text: navigationRow.modelData.key
          font.bold: true
          textColor: Color.accent
        }
        Label {
          Layout.fillWidth: true
          text: navigationRow.modelData.action
        }
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: "Choose your next session"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Use Reviews to recall learned subjects, Lessons to explore new subjects before a quiz, and Listen to train your ear with familiar recordings and local ratings. Each keeps its own saved position."
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    text: "In Listen, use the focused Play, Reveal, Got it, or Again buttons. Returning to a saved session stays silent. Configure autoplay and gentle reminders in Settings."
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    text: "From your desktop"
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Super+Alt+W opens study. Super+Alt+Shift+W looks up selected text. Enable desktop shortcuts in Settings; existing bindings are preserved."
    secondary: true
  }
}
