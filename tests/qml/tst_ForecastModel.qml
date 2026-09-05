import QtQuick
import QtTest
import "../../qml/ForecastModel.mjs" as Model

TestCase {
  name: "ForecastModel"
  function test_first_hour_contains_only_the_backend_upcoming_bin() {
    var result = Model.summary([2, 3, 5], 0, 1000)
    compare(result.count, 2)
    compare(result.cumulative, 2)
    compare(result.total, 10)
    compare(result.start, 1000000)
    compare(result.end, 4600000)
  }
  function test_cumulative_and_window_edges() {
    var bins = Array(24).fill(1)
    var last = Model.summary(bins, 23, 1000.25)
    compare(last.count, 1)
    compare(last.cumulative, 24)
    compare(last.start, (1000.25 + 23 * 3600) * 1000)
    compare(last.end, (1000.25 + 86400) * 1000)
  }
  function test_utc_offsets_and_daylight_saving_keep_elapsed_hour_width() {
    var start = Date.parse("2026-11-01T00:00:00-04:00") / 1000
    for (var hour = 0; hour < 24; hour++) {
      var selection = Model.summary([0, 2], hour, start)
      compare(selection.end - selection.start, 3600000)
    }
    compare(Model.summary([], 23, start).end, (start + 86400) * 1000)
  }
  function test_keyboard_navigation_clamps_without_wrapping() {
    compare(Model.move(0, "previous"), 0)
    compare(Model.move(23, "next"), 23)
    compare(Model.move(4, "next"), 5)
    compare(Model.move(4, "previous"), 3)
    compare(Model.move(12, "first"), 0)
    compare(Model.move(12, "last"), 23)
    compare(Model.move(12, "unknown"), 12)
  }
  function test_malformed_counts_cannot_break_the_chart() {
    var values = Model.bins([3, -1, "4", null, true, NaN, Infinity, 1.5])
    compare(values.length, 24)
    compare(values.slice(0, 8), [3, 0, 0, 0, 0, 0, 0, 0])
    compare(Model.summary(null, 99, null).count, 0)
    compare(Model.summary([], 0, Infinity).start, null)
    compare(Model.summary([], 0, "1000").end, null)
  }
  function test_empty_and_first_nonzero_selection() {
    compare(Model.first([]), 0)
    compare(Model.first([0, 0, 2, 4]), 2)
    compare(Model.summary([], 0, 1000).peak, 1)
    var values = [3, 2]
    var result = Model.bins(values)
    result[0] = 99
    compare(values[0], 3)
  }
}
