import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Theme.mjs" as Theme
import qs.Ui as Ui
import "UnicodeText.mjs" as UnicodeText
import "SubjectStatus.mjs" as SubjectStatus

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
    if (controller.detail)
      detailBack.forceActiveFocus(Qt.TabFocusReason)
    else
      searchField.forceActiveFocus()
  }
  function togglePin() {
    var subject = controller.detail
    if (!active || !subject)
      return
    var id = subject.id
    var access = controller.contentAccess
    var navigation = controller.navigationSequence
    var guarded = controller.progressReturn === true
    var context = controller.progressContext
    controller.call("pin", {
      subject_id: id,
      enabled: !subject.pinned
    }, function (ok, data) {
      if (!root || !ok || !root.active || !root.controller.detail || root.controller.detail.id !== id || root.controller.contentAccess !== access || root.controller.navigationSequence !== navigation || (root.controller.progressReturn === true) !== guarded || (guarded && root.controller.progressContext !== context))
        return
      if (guarded)
        root.controller.showProgressSubject(id)
      else
        root.controller.detail = data
    })
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
    if (typeof controller.progressReturn !== "undefined")
      controller.progressReturn = false
    controller.detail = null
    var points = UnicodeText.characters(searchField.text)
    controller.queryTruncated = points.length > 256
    controller.query = points.slice(0, 256).join("")
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
    secondary: true
    font.pixelSize: Style.font.bodySmall
  }
  RowLayout {
    Layout.fillWidth: true
    Ui.TextField {
      id: searchField
      readonly property color surfaceColor: Theme.surface(parent, Color.background)
      readonly property color textColor: Theme.foreground(parent, Color.foreground)
      readonly property color renderedSurface: Theme.composite(background && background.color !== undefined ? background.color : "transparent", surfaceColor)
      foreground: Theme.readable(textColor, surfaceColor, Color.foreground)
      accent: Theme.readable(Color.accent, surfaceColor, foreground)
      color: Theme.readable(foreground, renderedSurface, foreground)
      placeholderTextColor: Theme.secondary(foreground, renderedSurface)
      selectedTextColor: Theme.readable(foreground, Theme.composite(selectionColor, renderedSurface), foreground)
      objectName: "lookup-search"
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
        Accessible.checkable: true
        Accessible.checked: selected
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
        Accessible.checkable: true
        Accessible.checked: selected
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
    visible: root.controller.queryTruncated === true
    text: "Showing the first 256 characters of your selection."
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
  ReadingTrail {
    Layout.fillWidth: true
    controller: root.controller
  }
  Label {
    Layout.fillWidth: true
    visible: !root.controller.detail && (root.controller.query.length > 0 || root.controller.searchType !== "all" || root.controller.searchState !== "all") && root.controller.results.length === 0
    text: root.controller.searching ? "Searching your catalogue…" : "No cached match with these filters. Try a shorter word or another filter, or refresh your account to download its accessible catalogue."
    secondary: true
  }
  Label {
    Layout.fillWidth: true
    visible: !root.controller.detail && root.controller.results.length > 0
    text: root.controller.results.length + (root.controller.results.length === 30 ? " matches shown · narrow your search for more" : root.controller.results.length === 1 ? " match" : " matches")
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
  Repeater {
    model: root.controller.detail ? [] : root.controller.results
    Card {
      id: resultCard
      required property int index
      readonly property var entry: root.controller.results && index >= 0 && index < root.controller.results.length ? root.controller.results[index] : null
      Layout.fillWidth: true
      Layout.preferredHeight: row.implicitHeight + Style.space(24)
      ColumnLayout {
        id: row
        anchors.fill: parent
        anchors.margins: Style.space(12)
        RowLayout {
          Layout.fillWidth: true
          SubjectGlyph {
            subject: resultCard.entry
            pixelSize: Style.space(30)
            Layout.preferredWidth: Style.space(root.width < 420 ? 80 : 120)
            Layout.preferredHeight: Style.space(50)
          }
          Label {
            Layout.fillWidth: true
            text: resultCard.entry ? resultCard.entry.meanings.join(" · ") : ""
          }
          Action {
            text: "Open"
            accessibleName: resultCard.entry ? "Open " + (resultCard.entry.characters || resultCard.entry.slug) + ", " + resultCard.entry.meanings.join(", ") : "Open subject"
            enabled: root.active && resultCard.entry !== null
            onClicked: if (resultCard.entry)
              root.controller.showSubject(resultCard.entry.id)
          }
        }
        Label {
          objectName: "lookup-result-status"
          Layout.fillWidth: true
          text: resultCard.entry ? resultCard.entry.type.replace("_", " ") + " · Level " + resultCard.entry.level + " · " + SubjectStatus.label(resultCard.entry.learning_status) : ""
          font.pixelSize: Style.font.bodySmall
          secondary: true
        }
      }
    }
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.controller.detail !== null
    spacing: Style.space(14)
    Action {
      id: detailBack
      objectName: "lookup-detail-back"
      text: root.controller.progressReturn === true ? "← Back to progress" : "← Back to results"
      onClicked: {
        if (root.controller.progressReturn === true)
          root.controller.returnToProgress()
        else {
          root.controller.detail = null
          root.focusInput()
        }
      }
    }
    SubjectGlyph {
      Layout.fillWidth: true
      subject: root.controller.detail
      pixelSize: Style.space(64)
    }
    Label {
      objectName: "lookup-detail-status"
      Layout.fillWidth: true
      text: root.controller.detail ? root.controller.detail.type.replace("_", " ") + " · Level " + root.controller.detail.level + " · " + SubjectStatus.label(root.controller.detail.learning_status) : ""
      secondary: true
    }
    Action {
      text: "Practice this subject"
      onClicked: root.controller.begin("practice", 1, [root.controller.detail.id])
    }
    Action {
      text: root.controller.detail && root.controller.detail.pinned ? "Remove from difficult items" : "Keep in difficult items"
      onClicked: root.togglePin()
    }
    SubjectDetails {
      Layout.fillWidth: true
      subject: root.controller.detail
      controller: root.controller
      editable: true
    }
  }
}
