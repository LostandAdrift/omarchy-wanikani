pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import "ForecastModel.mjs" as Model

ColumnLayout {
  id: root
  property var forecast: []
  property real snapshotTime: 0
  property string nextReviewsAt: ""
  property bool active: true
  readonly property bool compact: width < Style.space(660)
  readonly property var values: Model.bins(forecast)
  property int selectedHour: Model.first(values)
  property int hoveredHour: -1
  readonly property int displayedHour: hoveredHour >= 0 ? hoveredHour : selectedHour
  readonly property var selection: Model.summary(values, displayedHour, snapshotTime)
  readonly property string interval: timeInterval(selection)
  spacing: Style.space(9)

  function timeInterval(value) {
    return value.start !== null ? Qt.formatDateTime(new Date(value.start), "ddd HH:mm") + "–" + Qt.formatDateTime(new Date(value.end), "ddd HH:mm") : "Cached hour " + (value.hour + 1)
  }

  function describe(value) {
    return timeInterval(value) + ". " + value.count + " reviews in this hour; " + value.cumulative + " upcoming reviews by the end of this hour. Already-due reviews are separate."
  }

  function selectHour(index, focusChart) {
    if (!active)
      return
    hoveredHour = -1
    selectedHour = Model.hour(index)
    if (focusChart)
      chart.forceActiveFocus(Qt.MouseFocusReason)
    if (chart.activeFocus)
      Qt.callLater(chart.reveal)
  }

  onActiveChanged: {
    if (!active) {
      hoveredHour = -1
      chart.focus = false
    }
  }
  onSelectedHourChanged: {
    hoveredHour = -1
    if (selectedHour !== Model.hour(selectedHour))
      selectedHour = Model.hour(selectedHour)
  }

  RowLayout {
    Layout.fillWidth: true
    Label {
      text: "Plan your next break"
      font.bold: true
    }
    Item {
      Layout.fillWidth: true
    }
    Label {
      Layout.fillWidth: true
      horizontalAlignment: Text.AlignRight
      text: root.selection.total + " in 24h" + (root.nextReviewsAt ? " · next " + Qt.formatDateTime(new Date(root.nextReviewsAt), "ddd HH:mm") : "")
      textColor: Color.accent
      font.pixelSize: Style.font.bodySmall
    }
  }
  Item {
    id: chart
    objectName: "reviewForecast"
    Layout.fillWidth: true
    Layout.preferredHeight: Style.space(root.compact ? 85 : 100)
    activeFocusOnTab: root.active
    property alias value: root.selectedHour
    readonly property int minimumValue: 0
    readonly property int maximumValue: 23
    readonly property int stepSize: 1
    Accessible.role: Accessible.Slider
    Accessible.name: "Hourly review forecast"
    Accessible.description: root.describe(Model.summary(root.values, root.selectedHour, root.snapshotTime)) + " Use Left and Right to choose an hour, Home for the first, End for the last."
    Accessible.focusable: root.active
    Accessible.ignored: !root.active
    Accessible.onIncreaseAction: root.selectHour(Model.move(root.selectedHour, "next"), false)
    Accessible.onDecreaseAction: root.selectHour(Model.move(root.selectedHour, "previous"), false)
    function reveal() {
      if (!activeFocus || !root.active)
        return
      var ancestor = parent
      while (ancestor) {
        var flickable = ancestor as Flickable
        if (flickable) {
          var point = chart.mapToItem(flickable.contentItem, 0, 0)
          var detailBottom = detailCard.mapToItem(flickable.contentItem, 0, detailCard.height).y
          var maximum = Math.max(0, flickable.contentHeight - flickable.height)
          var desired = flickable.contentY
          if (detailBottom > desired + flickable.height - 8)
            desired = detailBottom - flickable.height + 8
          if (point.y < desired + 8)
            desired = point.y - 8
          flickable.contentY = Math.max(0, Math.min(maximum, desired))
        }
        ancestor = ancestor.parent
      }
    }
    onActiveFocusChanged: if (activeFocus)
      Qt.callLater(reveal)
    Keys.enabled: root.active
    Keys.onPressed: event => {
      if (event.modifiers !== Qt.NoModifier)
        return
      var action = event.key === Qt.Key_Left || event.key === Qt.Key_Down ? "previous" : event.key === Qt.Key_Right || event.key === Qt.Key_Up ? "next" : event.key === Qt.Key_Home ? "first" : event.key === Qt.Key_End ? "last" : ""
      if (action) {
        root.selectHour(Model.move(root.selectedHour, action), false)
        event.accepted = true
      }
    }
    Card {
      anchors.fill: parent
      border.color: chart.activeFocus ? Color.accent : Qt.alpha(Color.foreground, 0.14)
    }
    Row {
      id: bars
      anchors.fill: parent
      anchors.margins: Style.space(10)
      spacing: Style.space(3)
      Repeater {
        model: root.values
        Item {
          id: bar
          required property int index
          required property var modelData
          readonly property bool selected: root.displayedHour === index
          width: Math.max(1, (bars.width - bars.spacing * 23) / 24)
          height: bars.height
          Accessible.ignored: true
          Rectangle {
            anchors.fill: parent
            color: bar.selected ? Qt.alpha(Color.accent, 0.10) : "transparent"
            radius: Math.min(Style.cornerRadius, 3)
          }
          Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: Math.max(Style.space(3), (parent.height - Style.space(9)) * bar.modelData / root.selection.peak)
            radius: Math.min(Style.cornerRadius, 3)
            color: bar.modelData > 0 ? (bar.selected ? Color.accent : Qt.alpha(Color.accent, 0.48)) : Qt.alpha(Color.foreground, bar.selected ? 0.38 : 0.12)
          }
          HoverHandler {
            enabled: root.active
            onHoveredChanged: {
              if (hovered)
                root.hoveredHour = bar.index
              else if (root.hoveredHour === bar.index)
                root.hoveredHour = -1
            }
          }
          TapHandler {
            enabled: root.active
            onTapped: root.selectHour(bar.index, true)
          }
        }
      }
    }
  }
  Item {
    Layout.fillWidth: true
    Layout.preferredHeight: Style.space(20)
    Repeater {
      model: root.compact ? [0, 6, 12, 18, 24] : [0, 4, 8, 12, 16, 20, 24]
      Label {
        required property int modelData
        text: root.selection.start !== null ? Qt.formatDateTime(new Date((root.snapshotTime + modelData * 3600) * 1000), "HH:mm") : "+" + modelData + "h"
        x: Math.max(0, Math.min(parent.width - width, parent.width * modelData / 24 - width / 2))
        textColor: Qt.alpha(Color.foreground, 0.60)
        font.pixelSize: Style.font.bodySmall
        Accessible.ignored: true
      }
    }
  }
  Card {
    id: detailCard
    objectName: "reviewForecastDetail"
    Layout.fillWidth: true
    Layout.preferredHeight: selectedDetail.implicitHeight + Style.space(20)
    ColumnLayout {
      id: selectedDetail
      anchors.fill: parent
      anchors.margins: Style.space(10)
      spacing: Style.space(4)
      Label {
        Layout.fillWidth: true
        text: (root.displayedHour === 0 ? "First hour · " : "Hour " + (root.displayedHour + 1) + " · ") + root.interval
        font.pixelSize: Style.font.bodySmall
        secondary: true
      }
      Label {
        Layout.fillWidth: true
        text: root.selection.count + (root.selection.count === 1 ? " review" : " reviews") + " in this hour · " + root.selection.cumulative + " upcoming by then"
        textColor: Color.accent
        font.bold: true
      }
    }
  }
  Label {
    Layout.fillWidth: true
    text: root.selection.total ? "Choose an hour with the pointer or arrow keys. Hourly windows follow the cached schedule; reviews already due are shown above." : "No upcoming reviews in this 24-hour window. Reviews already due are shown above."
    textColor: Qt.alpha(Color.foreground, 0.60)
    font.pixelSize: Style.font.bodySmall
  }
}
