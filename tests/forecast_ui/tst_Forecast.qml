import QtQuick
import QtTest
import "../../qml" as Kani

Rectangle {
  id: host
  width: 950
  height: 700
  color: "#15171a"
  Flickable {
    id: viewport
    visible: false
    width: 640
    height: 260
    y: 300
    clip: true
    contentWidth: width
    contentHeight: 1100
  }
  Kani.Forecast {
    id: graph
    x: 10
    y: 10
    width: 420
    snapshotTime: 1788550000
    forecast: [2, 3, 0, 4, 0, 8, 2, 0, 1, 4, 0, 0, 3, 1, 0, 2, 0, 5, 0, 0, 8, 1, 0, 2]
  }
  TestCase {
    name: "ForecastSurface"
    when: windowShown
    function init() {
      failOnWarning(/.*/)
      graph.active = true
      graph.selectedHour = 0
    }
    function test_keyboard_accessible_value_and_hidden_lifecycle() {
      var chart = findChild(graph, "reviewForecast")
      verify(chart !== null)
      chart.forceActiveFocus()
      keyClick(Qt.Key_End)
      compare(graph.selectedHour, 23)
      compare(chart.value, 23)
      keyClick(Qt.Key_Home)
      keyClick(Qt.Key_Right)
      compare(graph.selectedHour, 1)
      compare(graph.selection.cumulative, 5)
      chart.value = 5
      compare(graph.selectedHour, 5)
      compare(graph.selection.count, 8)
      graph.active = false
      keyClick(Qt.Key_Left)
      compare(graph.selectedHour, 5)
      compare(chart.activeFocusOnTab, false)
    }
    function test_focus_and_selection_reveal_the_hourly_detail_below_the_chart() {
      var chart = findChild(graph, "reviewForecast")
      var detail = findChild(graph, "reviewForecastDetail")
      try {
        viewport.visible = true
        viewport.contentY = 0
        graph.parent = viewport.contentItem
        graph.x = 0
        graph.y = 400
        graph.width = 620
        chart.forceActiveFocus()
        wait(20)
        verify(viewport.contentY > 0)
        verify(detail.mapToItem(viewport.contentItem, 0, detail.height).y <= viewport.contentY + viewport.height - 7)
        viewport.contentY = 0
        keyClick(Qt.Key_End)
        wait(20)
        compare(graph.selectedHour, 23)
        verify(detail.mapToItem(viewport.contentItem, 0, detail.height).y <= viewport.contentY + viewport.height - 7)
      } finally {
        graph.active = false
        graph.parent = host
        graph.x = 10
        graph.y = 10
        viewport.visible = false
        graph.active = true
      }
    }
    function test_responsive_layout_and_hover() {
      for (var width of [360, 620, 900]) {
        graph.width = width
        wait(20)
        verify(graph.implicitHeight > 200)
        verify(graph.implicitHeight < 500)
        var chart = findChild(graph, "reviewForecast")
        compare(chart.width, width)
        mouseMove(chart, chart.width * 0.52, chart.height * 0.5)
        verify(graph.hoveredHour >= 0 && graph.hoveredHour < 24)
        mouseMove(chart, -5, -5)
        compare(graph.hoveredHour, -1)
      }
      graph.width = 620
    }
  }
}
