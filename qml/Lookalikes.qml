import QtQuick
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  objectName: "wanikani-lookalikes"
  required property var subject
  property bool showMeaning: true
  property bool showReading: true
  property bool expanded: false
  property int selectedIndex: 0
  readonly property var candidates: subject && Array.isArray(subject.visually_similar) ? subject.visually_similar.filter(function (item) {
    return item && Number.isSafeInteger(item.id) && item.id > 0 && typeof item.characters === "string" && item.characters.trim().length > 0 && meaningsFor(item).length > 0 && readingsFor(item).length > 0
  }) : []
  readonly property var comparison: candidates.length ? candidates[Math.min(selectedIndex, candidates.length - 1)] : null
  readonly property int subjectId: subject ? subject.id : 0
  visible: candidates.length > 0 && (showMeaning || showReading)
  spacing: Style.space(10)
  function meaningsFor(item) {
    return item && Array.isArray(item.meanings) ? item.meanings.filter(function (value) {
      return typeof value === "string" && value.trim().length > 0
    }) : []
  }
  function readingsFor(item) {
    return item && Array.isArray(item.readings) ? item.readings.filter(function (r) {
      return r && r.accepted === true && typeof r.reading === "string" && r.reading.trim().length > 0
    }).map(function (r) {
      return r.reading
    }) : []
  }
  onSubjectIdChanged: {
    expanded = false
    selectedIndex = 0
  }
  onCandidatesChanged: {
    selectedIndex = Math.max(0, Math.min(selectedIndex, candidates.length - 1))
    if (!candidates.length)
      expanded = false
  }
  Action {
    text: root.expanded ? "Close comparison" : "Tell them apart · " + root.candidates.length
    selected: root.expanded
    accessibleName: root.expanded ? "Close similar kanji comparison" : "Compare visually similar kanji"
    onClicked: root.expanded = !root.expanded
  }
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.expanded
    spacing: Style.space(10)
    Label {
      Layout.fillWidth: true
      text: "Look for the stroke that changes. Say each " + (root.showMeaning && root.showReading ? "meaning and reading" : root.showMeaning ? "meaning" : "reading") + " to yourself."
      secondary: true
      font.pixelSize: Style.font.bodySmall
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      visible: root.candidates.length > 1
      Repeater {
        model: root.expanded ? root.candidates : []
        Action {
          required property var modelData
          required property int index
          text: modelData.characters
          selected: root.selectedIndex === index
          accessibleName: "Compare with " + modelData.characters
          onClicked: root.selectedIndex = index
        }
      }
    }
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(10)
      Repeater {
        model: root.expanded && root.comparison ? [root.subject, root.comparison] : []
        Card {
          required property var modelData
          required property int index
          readonly property var cardSubject: index === 0 ? root.subject : root.comparison
          Layout.fillWidth: true
          Layout.preferredWidth: 1
          Layout.preferredHeight: comparisonBody.implicitHeight + Style.space(24)
          ColumnLayout {
            id: comparisonBody
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Style.space(12)
            spacing: Style.space(8)
            Label {
              Layout.fillWidth: true
              text: index === 0 ? "THIS KANJI" : "COMPARE"
              horizontalAlignment: Text.AlignHCenter
              textColor: Qt.alpha(Color.foreground, 0.66)
              font.pixelSize: Style.font.bodySmall
              font.letterSpacing: 1
            }
            SubjectGlyph {
              Layout.fillWidth: true
              subject: cardSubject
              pixelSize: Style.space(76)
            }
            Label {
              Layout.fillWidth: true
              visible: root.showMeaning
              text: root.showMeaning ? root.meaningsFor(cardSubject).join(" · ") : ""
              horizontalAlignment: Text.AlignHCenter
              font.pixelSize: Style.font.title
              textColor: Color.accent
            }
            Label {
              Layout.fillWidth: true
              visible: root.showReading
              text: root.showReading ? root.readingsFor(cardSubject).join(" · ") : ""
              horizontalAlignment: Text.AlignHCenter
              font.family: "Noto Sans CJK JP"
            }
          }
        }
      }
    }
    Label {
      Layout.fillWidth: true
      text: "Similar kanji from WaniKani. Subjects in unfinished graded work are kept out of comparisons."
      textColor: Qt.alpha(Color.foreground, 0.66)
      font.pixelSize: Style.font.bodySmall
    }
  }
}
