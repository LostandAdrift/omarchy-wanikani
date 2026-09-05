import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui

ColumnLayout {
  id: root
  required property var controller
  spacing: Style.space(14)
  function focusInput() {
    searchField.forceActiveFocus()
  }
  Label {
    text: "A word from your world."
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Search characters, readings, or meanings in your WaniKani material. Selected text stays on this computer."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Ui.TextField {
      id: searchField
      Layout.fillWidth: true
      text: root.controller.query
      placeholderText: "Japanese, reading, or meaning…"
      Accessible.name: "Search WaniKani material"
      onTextEdited: {
        root.controller.detail = null
        searchDelay.restart()
      }
      onAccepted: root.controller.search(text)
    }
    Action {
      text: "Use selection"
      onClicked: root.controller.readSelection()
    }
  }
  Timer {
    id: searchDelay
    interval: 140
    onTriggered: root.controller.search(searchField.text)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.controller.detail && root.controller.query.length > 0 && root.controller.results.length === 0
    text: "No cached match. Try a shorter word, or refresh your account to download its accessible catalogue."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Repeater {
    model: root.controller.detail ? [] : root.controller.results
    Card {
      required property var modelData
      Layout.fillWidth: true
      Layout.preferredHeight: row.implicitHeight + Style.space(24)
      RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: Style.space(12)
        Label {
          text: modelData.characters || "◇"
          font.family: "Noto Sans CJK JP"
          font.pixelSize: Style.space(30)
          Layout.preferredWidth: Style.space(120)
          elide: Text.ElideRight
          maximumLineCount: 1
        }
        ColumnLayout {
          Layout.fillWidth: true
          Label {
            Layout.fillWidth: true
            text: modelData.meanings.join(" · ")
          }
          Label {
            Layout.fillWidth: true
            text: modelData.type.replace("_", " ") + " · Level " + modelData.level + " · " + (modelData.assignment.started_at ? "SRS " + modelData.assignment.srs_stage : "Not started")
            font.pixelSize: Style.font.bodySmall
            color: Qt.alpha(Color.foreground, 0.76)
          }
        }
        Action {
          text: "Open"
          onClicked: root.controller.showSubject(modelData.id)
        }
      }
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.controller.detail !== null
    spacing: Style.space(14)
    SubjectGlyph {
      Layout.fillWidth: true
      subject: root.controller.detail
      pixelSize: Style.space(64)
    }
    Label {
      text: root.controller.detail ? root.controller.detail.type.replace("_", " ") + " · Level " + root.controller.detail.level + " · SRS " + (root.controller.detail.assignment.srs_stage || 0) : ""
      color: Qt.alpha(Color.foreground, 0.76)
    }
    Action {
      text: "Practice this subject"
      onClicked: root.controller.begin("practice", 1, [root.controller.detail.id])
    }
    Action {
      text: root.controller.detail && root.controller.detail.pinned ? "Remove from difficult items" : "Keep in difficult items"
      onClicked: root.controller.call("pin", {
        subject_id: root.controller.detail.id,
        enabled: !root.controller.detail.pinned
      }, function (ok, data) {
        if (ok)
          root.controller.detail = data
      })
    }
    SubjectDetails {
      Layout.fillWidth: true
      subject: root.controller.detail
      controller: root.controller
      editable: true
    }
  }
}
