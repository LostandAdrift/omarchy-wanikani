import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui

ColumnLayout {
  id: root
  required property var controller
  property bool initialized: false
  readonly property bool active: controller.opened && controller.service && controller.service.ready && !controller.service.locked
  onActiveChanged: {
    searchDelay.stop()
    if (initialized) {
      controller.searchSequence++
      controller.searching = false
      if (active)
        refreshWhenActive()
    }
  }
  spacing: Style.space(14)
  function focusInput() {
    searchField.forceActiveFocus()
  }
  function refreshWhenActive() {
    var expected = controller.searchSequence
    Qt.callLater(function () {
      // A route payload or account-change handler may already have searched.
      if (root && root.active && !root.controller.detail && root.controller.searchSequence === expected)
        root.searchNow(searchField.text)
    })
  }
  function editSearch() {
    controller.detail = null
    controller.query = String(searchField.text || "").slice(0, 256)
    controller.searchSequence++
    controller.searching = false
    if (active)
      searchDelay.restart()
  }
  function searchNow(text) {
    searchDelay.stop()
    if (active)
      controller.search(text)
  }
  Component.onCompleted: {
    initialized = true
    if (active)
      refreshWhenActive()
  }
  Label {
    text: "A word from your world."
    font.pixelSize: Style.font.title
    font.bold: true
  }
  Label {
    Layout.fillWidth: true
    text: "Search Japanese, romaji readings, meanings, or your synonyms. A selected sentence reveals matching words from your catalogue. Text stays on this computer."
    color: Qt.alpha(Color.foreground, 0.76)
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Ui.TextField {
      id: searchField
      Layout.fillWidth: true
      text: root.controller.query
      placeholderText: "Japanese, romaji, or meaning…"
      Accessible.name: "Search WaniKani material"
      onTextEdited: root.editSearch()
      onAccepted: root.searchNow(text)
    }
    Action {
      text: "Use selection"
      onClicked: root.controller.readSelection()
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    visible: !root.controller.detail
    Repeater {
      model: [
        {
          value: "all",
          label: "All types"
        },
        {
          value: "radical",
          label: "Radicals"
        },
        {
          value: "kanji",
          label: "Kanji"
        },
        {
          value: "vocabulary",
          label: "Vocabulary"
        },
        {
          value: "kana_vocabulary",
          label: "Kana vocabulary"
        }
      ]
      Action {
        required property var modelData
        text: modelData.label
        selected: root.controller.searchType === modelData.value
        accessibleHint: "Filter catalogue by subject type"
        onClicked: root.controller.setSearchFilter(modelData.value, root.controller.searchState)
      }
    }
  }
  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)
    visible: !root.controller.detail
    Repeater {
      model: [
        {
          value: "all",
          label: "Any progress"
        },
        {
          value: "learned",
          label: "Learned"
        },
        {
          value: "due",
          label: "Due reviews"
        },
        {
          value: "saved",
          label: "Saved difficult items"
        }
      ]
      Action {
        required property var modelData
        text: modelData.label
        selected: root.controller.searchState === modelData.value
        accessibleHint: "Filter catalogue by your learning progress"
        onClicked: root.controller.setSearchFilter(root.controller.searchType, modelData.value)
      }
    }
  }
  Timer {
    id: searchDelay
    interval: 140
    onTriggered: root.searchNow(searchField.text)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.controller.detail && (root.controller.query.length > 0 || root.controller.searchType !== "all" || root.controller.searchState !== "all") && root.controller.results.length === 0
    text: root.controller.searching ? "Searching your catalogue…" : "No cached match with these filters. Try a shorter word or another filter, or refresh your account to download its accessible catalogue."
    color: Qt.alpha(Color.foreground, 0.76)
  }
  Label {
    Layout.fillWidth: true
    visible: !root.controller.detail && root.controller.results.length > 0
    text: root.controller.results.length + (root.controller.results.length === 30 ? " matches shown · narrow your search for more" : root.controller.results.length === 1 ? " match" : " matches")
    font.pixelSize: Style.font.bodySmall
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
        SubjectGlyph {
          subject: modelData
          pixelSize: Style.space(30)
          Layout.preferredWidth: Style.space(120)
          Layout.preferredHeight: Style.space(50)
        }
        ColumnLayout {
          Layout.fillWidth: true
          Label {
            Layout.fillWidth: true
            text: modelData.meanings.join(" · ")
          }
          Label {
            Layout.fillWidth: true
            text: modelData.type.replace("_", " ") + " · Level " + modelData.level + " · " + (modelData.pending ? "Waiting to sync" : modelData.assignment.burned_at ? "Burned" : modelData.assignment.started_at ? "SRS " + modelData.assignment.srs_stage : "Not started")
            font.pixelSize: Style.font.bodySmall
            color: Qt.alpha(Color.foreground, 0.76)
          }
        }
        Action {
          text: "Open"
          accessibleName: "Open " + (modelData.characters || modelData.slug) + ", " + modelData.meanings.join(", ")
          onClicked: root.controller.showSubject(modelData.id)
        }
      }
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.controller.detail !== null
    spacing: Style.space(14)
    Action {
      text: "← Back to results"
      onClicked: {
        root.controller.detail = null
        root.focusInput()
      }
    }
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
