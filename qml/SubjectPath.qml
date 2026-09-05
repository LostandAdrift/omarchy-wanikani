pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.Commons
import "UnicodeText.mjs" as UnicodeText

ColumnLayout {
  id: root
  objectName: "wanikani-subject-path"
  required property var subject
  property bool showMeaning: true
  property bool showReading: true
  property bool editable: false
  property bool openEnabled: false
  property bool expanded: false
  property bool allComponents: false
  property bool allRelated: false
  signal requestSubject(var subjectId)
  readonly property string subjectType: subject && ["radical", "kanji", "vocabulary", "kana_vocabulary"].indexOf(subject.type) >= 0 ? subject.type : "subject"
  readonly property var components: showMeaning ? validRows(subject ? subject.components : null) : []
  readonly property var related: showMeaning && showReading ? validRows(subject ? subject.related : null) : []
  readonly property bool mayOpen: editable && openEnabled && showMeaning && showReading
  readonly property string countsLabel: components.length + (components.length === 1 ? " component" : " components") + " · " + related.length + (related.length === 1 ? " related subject" : " related subjects")
  readonly property string componentLabel: subjectType === "kanji" ? "Radicals in this kanji" : subjectType === "vocabulary" ? "Kanji in this word" : "Components"
  readonly property string relatedLabel: subjectType === "radical" ? "Kanji using this radical" : subjectType === "kanji" ? "Words using this kanji" : "Related subjects"
  readonly property string currentLabel: subjectType === "radical" ? "This radical" : subjectType === "kanji" ? "This kanji" : subjectType === "vocabulary" || subjectType === "kana_vocabulary" ? "This word" : "This subject"
  visible: !!subject && Number.isSafeInteger(subject.id) && subject.id > 0 && components.length + related.length > 0
  spacing: Style.space(6)

  function text(value, limit) {
    return typeof value === "string" ? UnicodeText.characters(value.slice(0, limit * 2)).slice(0, limit).join("").trim() : ""
  }
  function glyph(item) {
    const value = text(item ? item.characters : null, 256)
    return value === "◇" ? "" : value
  }
  function validRows(value) {
    if (!Array.isArray(value))
      return []
    var result = []
    var seen = {}
    for (var row of value.slice(0, 30)) {
      if (!row || !Number.isSafeInteger(row.id) || row.id <= 0 || subject && row.id === subject.id || seen[row.id])
        continue
      seen[row.id] = true
      result.push(row)
    }
    return result
  }
  function meanings() {
    return subject && Array.isArray(subject.meanings) ? subject.meanings.filter(function (value) {
      return typeof value === "string" && value.trim().length > 0
    }).slice(0, 8).map(function (value) {
      return root.text(value, 300)
    }).join(" · ") : ""
  }
  function readings() {
    return subject && Array.isArray(subject.readings) ? subject.readings.filter(function (value) {
      return value && value.accepted === true && typeof value.reading === "string" && value.reading.trim().length > 0
    }).slice(0, 8).map(function (value) {
      return root.text(value.reading, 256)
    }).join(" · ") : ""
  }
  function openSubject(subjectId) {
    if (!visible || !expanded || !mayOpen || !Number.isSafeInteger(subjectId))
      return
    if (components.concat(related).some(function (row) {
      return row.id === subjectId
    }))
      requestSubject(subjectId)
  }
  function reset() {
    expanded = false
    allComponents = false
    allRelated = false
  }
  onSubjectChanged: reset()
  onShowMeaningChanged: reset()
  onShowReadingChanged: reset()
  onVisibleChanged: if (!visible)
    reset()

  Action {
    Layout.fillWidth: true
    text: root.expanded ? "Hide connections" : "How this subject connects"
    selected: root.expanded
    Accessible.checkable: true
    Accessible.checked: root.expanded
    accessibleName: text + ", " + root.countsLabel.replace(" · ", " and ") + " available in this view"
    onClicked: if (root.visible)
      root.expanded = !root.expanded
  }
  Label {
    Layout.fillWidth: true
    text: "Available: " + root.countsLabel
    font.pixelSize: Style.font.bodySmall
    secondary: true
  }
  Loader {
    Layout.fillWidth: true
    active: root.expanded && root.visible
    sourceComponent: ColumnLayout {
      spacing: Style.space(8)
      Label {
        Layout.fillWidth: true
        visible: root.components.length > 0
        text: root.componentLabel
        font.bold: true
      }
      Flow {
        Layout.fillWidth: true
        visible: root.components.length > 0
        spacing: Style.space(8)
        Repeater {
          model: root.allComponents ? root.components : root.components.slice(0, 4)
          ConnectionCard {
            required property var modelData
            entry: modelData
            width: Math.max(1, (parent.width - Style.space(8)) / 2)
          }
        }
      }
      Action {
        visible: root.components.length > 4
        text: root.allComponents ? "Show fewer components" : "Show all " + root.components.length + " components"
        onClicked: root.allComponents = !root.allComponents
      }
      Label {
        Layout.fillWidth: true
        visible: root.components.length > 0
        text: "↓"
        horizontalAlignment: Text.AlignHCenter
        Accessible.name: "Components connect to this subject"
      }
      ConnectionCard {
        Layout.fillWidth: true
        entry: root.subject
        current: true
      }
      Label {
        Layout.fillWidth: true
        visible: root.related.length > 0
        text: "↓"
        horizontalAlignment: Text.AlignHCenter
        Accessible.name: "This subject connects to related subjects"
      }
      Label {
        Layout.fillWidth: true
        visible: root.related.length > 0
        text: root.relatedLabel
        font.bold: true
      }
      Flow {
        Layout.fillWidth: true
        visible: root.related.length > 0
        spacing: Style.space(8)
        Repeater {
          model: root.allRelated ? root.related : root.related.slice(0, 4)
          ConnectionCard {
            required property var modelData
            entry: modelData
            width: Math.max(1, (parent.width - Style.space(8)) / 2)
          }
        }
      }
      Action {
        visible: root.related.length > 4
        text: root.allRelated ? "Show fewer related subjects" : "Show all " + root.related.length + " related subjects"
        onClicked: root.allRelated = !root.allRelated
      }
      Label {
        Layout.fillWidth: true
        text: "Available connections from this cached WaniKani record. This is a partial view."
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
    }
  }

  component ConnectionCard: Card {
    id: card
    required property var entry
    property bool current: false
    readonly property var subjectId: entry ? entry.id : 0
    readonly property string characters: root.glyph(entry)
    objectName: "wanikani-path-card"
    implicitHeight: body.implicitHeight + Style.space(20)
    ColumnLayout {
      id: body
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(10)
      spacing: Style.space(6)
      Label {
        Layout.fillWidth: true
        visible: card.current
        text: root.currentLabel
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
      }
      Loader {
        Layout.fillWidth: true
        active: card.characters !== ""
        sourceComponent: JapaneseText {
          text: card.characters
          color: card.textColor
          font.pixelSize: Style.space(card.current ? 62 : 40)
          minimumPixelSize: Style.space(18)
        }
      }
      Label {
        Layout.fillWidth: true
        visible: card.characters === ""
        text: (card.current && root.subjectType === "radical" ? "Image radical" : "Glyph unavailable") + "\nNot shown in this path"
        horizontalAlignment: Text.AlignHCenter
        secondary: true
        font.pixelSize: Style.font.bodySmall
      }
      Loader {
        Layout.fillWidth: true
        active: root.showMeaning
        sourceComponent: Label {
          objectName: "wanikani-path-meaning"
          text: (card.current ? root.meanings() : root.text(card.entry ? card.entry.meaning : null, 300)) || "Meaning unavailable"
          horizontalAlignment: Text.AlignHCenter
        }
      }
      Loader {
        Layout.fillWidth: true
        active: card.current && root.subjectType !== "radical" && root.showReading && root.readings() !== ""
        sourceComponent: JapaneseText {
          objectName: "wanikani-path-reading"
          text: root.readings()
          color: card.textColor
          font.pixelSize: Style.font.body
          minimumPixelSize: Style.space(12)
        }
      }
      Loader {
        Layout.fillWidth: true
        active: !card.current && root.mayOpen
        sourceComponent: Action {
          text: "Open"
          accessibleName: "Open " + (card.characters || "subject with unavailable glyph")
          onClicked: root.openSubject(card.subjectId)
        }
      }
    }
  }
}
