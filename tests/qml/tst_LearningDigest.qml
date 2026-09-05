import QtQuick
import QtTest
import "../../qml/LearningDigest.mjs" as Digest

TestCase {
  name: "LearningDigest"
  readonly property string epoch: "01234567-89ab-cdef-0123-456789abcdef"
  readonly property var metrics: ({
      subject_completions: ["reviews", "lessons", "practice"],
      sessions_completed: ["reviews", "lessons", "practice"],
      listening_ratings: ["remembered", "again", "skipped"],
      dictation_ratings: ["matched", "again", "skipped"]
    })
  readonly property var scalars: ["listening_sessions_completed", "dictation_sessions_completed", "typo_corrections"]

  function window(days) {
    return {
      days: days,
      start_day: days === 7 ? "2026-08-30" : "2026-08-07",
      end_day: "2026-09-05",
      subject_completions: {
        reviews: days,
        lessons: 1,
        practice: 2
      },
      sessions_completed: {
        reviews: 1,
        lessons: 1,
        practice: 1
      },
      listening_ratings: {
        remembered: 2,
        again: 1,
        skipped: 0
      },
      listening_sessions_completed: 1,
      dictation_ratings: {
        matched: 2,
        again: 0,
        skipped: 1
      },
      dictation_sessions_completed: 1,
      typo_corrections: 1
    }
  }
  function value() {
    return {
      schema_version: 1,
      scope: "recorded_on_this_device",
      freshness: "cached",
      generated_at: new Date(2026, 8, 5, 12, 0, 0).toISOString(),
      data_epoch: epoch,
      demo: false,
      timezone: "system-local",
      complete: true,
      stale: false,
      coverage: "retained_local_records",
      includes_retained_pre_reset_activity: true,
      windows: {
        "7": window(7),
        "30": window(30)
      }
    }
  }
  function options() {
    return {
      ready: true,
      demo: false,
      epoch: epoch,
      dirty: false,
      clockChanged: false,
      now: new Date(2026, 8, 5, 12, 0, 0).getTime()
    }
  }
  function copy(item) {
    return JSON.parse(JSON.stringify(item))
  }
  function shiftWindows(item, days) {
    for (var name of ["7", "30"])
      for (var edge of ["start_day", "end_day"])
        item.windows[name][edge] = new Date(Date.parse(item.windows[name][edge] + "T00:00:00Z") + days * 86400000).toISOString().slice(0, 10)
  }

  function test_known_totals_remain_separate_and_timestamp_is_not_refreshed() {
    var raw = value(), now = options()
    now.now += 3600000
    var result = Digest.project(raw, now)
    verify(result !== null)
    compare(result.generated_at, raw.generated_at)
    compare(result.windows, raw.windows)
    compare(result.stale, null)
    verify(result.complete)
    verify(result.includes_retained_pre_reset_activity)
    compare(result.scope, "recorded_on_this_device")
  }
  function test_only_allowlisted_fields_escape_and_copies_do_not_alias_input() {
    var raw = value()
    raw.answer = "PRIVATE ANSWER"
    raw.username = "PRIVATE ACCOUNT"
    raw.token = "PRIVATE TOKEN"
    raw.windows.difficulty = [
      {
        meaning: "PRIVATE MEANING"
      }
    ]
    raw.windows["7"].notes = "PRIVATE NOTE"
    raw.windows["7"].dictation_ratings.recording = "PRIVATE URL"
    var before = JSON.stringify(raw), result = Digest.project(raw, options())
    verify(result !== null)
    verify(JSON.stringify(result).indexOf("PRIVATE") < 0)
    compare(Object.keys(result).sort(), Object.keys(value()).sort())
    compare(Object.keys(result.windows).sort(), ["30", "7"])
    compare(Object.keys(result.windows["7"]).sort(), Object.keys(window(7)).sort())
    compare(JSON.stringify(raw), before)
    result.windows["7"].dictation_ratings.matched = 900
    compare(raw.windows["7"].dictation_ratings.matched, 2)
    // Unknown properties must not even be evaluated while projecting.
    Object.defineProperty(raw, "privateGetter", {
      get: function () {
        throw new Error("PRIVATE")
      }
    })
    verify(Digest.project(raw, options()) !== null)
  }
  function test_unknown_and_malformed_metadata_never_become_zero() {
    for (var malformed of [undefined, null, false, 1, "value", [],
      {}
    ])
      compare(Digest.project(malformed, options()), null)
    var changes = {
      schema_version: [true, "1", 2],
      scope: ["all_account_history"],
      freshness: ["fresh"],
      coverage: ["all_history"],
      includes_retained_pre_reset_activity: [false, 1],
      demo: [null, 0, true],
      complete: [0, null],
      stale: [0, "false", undefined],
      data_epoch: ["", "PRIVATE", epoch.toUpperCase(), "different-epoch"],
      generated_at: [null, ""],
      timezone: [null, ""],
      windows: [null, [],
        {}
      ]
    }
    for (var field of Object.keys(changes))
      for (var change of changes[field]) {
        var raw = value()
        raw[field] = change
        compare(Digest.project(raw, options()), null, field + ": " + String(change))
      }
  }
  function test_unknown_worker_demo_and_epoch_context_is_unavailable() {
    var changes = {
      ready: [false, null, 1, undefined],
      demo: [true, null, 0, undefined],
      epoch: ["", "01234567-89ab-cdef-0123-456789abcdee", null, undefined],
      dirty: [null, 0, undefined],
      clockChanged: [null, 1, undefined],
      now: [null, true, "1", NaN, Infinity, 9e99]
    }
    compare(Digest.project(value(), null), null)
    for (var field of Object.keys(changes))
      for (var change of changes[field]) {
        var option = options()
        option[field] = change
        compare(Digest.project(value(), option), null, field + ": " + String(change))
      }
    var raw = value(), option = options()
    raw.demo = true
    option.demo = true
    verify(Digest.project(raw, option).demo)
  }
  function test_every_supported_counter_is_required_safe_and_nonnegative() {
    var invalid = [undefined, null, true, -1, 0.5, "2", NaN, Infinity, 9007199254740992]
    for (var span of ["7", "30"]) {
      for (var metric of Object.keys(metrics))
        for (var key of metrics[metric])
          for (var number of invalid) {
            var raw = value()
            raw.windows[span][metric][key] = number
            compare(Digest.project(raw, options()), null, span + "/" + metric + "/" + key)
          }
      for (var scalar of scalars)
        for (var number of invalid) {
          var item = value()
          item.windows[span][scalar] = number
          compare(Digest.project(item, options()), null, span + "/" + scalar)
        }
    }
    var maximum = value()
    for (var name of ["7", "30"]) {
      for (var kind of Object.keys(metrics))
        for (var counter of metrics[kind])
          maximum.windows[name][kind][counter] = 9007199254740991
      for (var single of scalars)
        maximum.windows[name][single] = 0
    }
    compare(Digest.project(maximum, options()).windows["7"].subject_completions.reviews, 9007199254740991)
    for (var kind of Object.keys(metrics))
      for (var counter of metrics[kind])
        maximum.windows["7"][kind][counter] = 0
    compare(Digest.project(maximum, options()).windows["7"].subject_completions.reviews, 0)
  }
  function test_seven_day_counts_cannot_exceed_thirty_day_counts() {
    for (var kind of Object.keys(metrics))
      for (var counter of metrics[kind]) {
        var raw = value()
        raw.windows["7"][kind][counter] = raw.windows["30"][kind][counter] + 1
        compare(Digest.project(raw, options()), null, kind + "/" + counter)
      }
    for (var scalar of scalars) {
      var item = value()
      item.windows["7"][scalar] = item.windows["30"][scalar] + 1
      compare(Digest.project(item, options()), null, scalar)
    }
  }
  function test_real_inclusive_calendar_windows_are_required() {
    for (var span of ["7", "30"]) {
      for (var invalid of [undefined, null, true, Number(span) + 1, span]) {
        var raw = value()
        raw.windows[span].days = invalid
        compare(Digest.project(raw, options()), null)
      }
      for (var edge of ["start_day", "end_day"])
        for (var bad of ["2026-2-01", "2026-02-29", "2026-09-31", "0000-01-01", "2026-13-01", "2026-00-01", "2026-09-00", "2026-09-05Z", null]) {
          var item = value()
          item.windows[span][edge] = bad
          compare(Digest.project(item, options()), null, edge + ": " + bad)
        }
    }
    var differentEnd = value()
    differentEnd.windows["7"].start_day = "2026-08-29"
    differentEnd.windows["7"].end_day = "2026-09-04"
    compare(Digest.project(differentEnd, options()), null)
    var offset = value()
    shiftWindows(offset, 3)
    compare(Digest.project(offset, options()), null)
  }
  function test_timestamp_does_not_normalize_invalid_dates_or_offsets() {
    for (var bad of ["2026-09-05", "2026-09-05T12:00:00", "2026-09-05 12:00:00Z", "2026-09-05T24:00:00Z", "2026-09-05T12:60:00Z", "2026-09-05T12:00:60Z", "2026-09-05T12:00:00+01:99", "2026-09-05T12:00:00+24:00", "2026-09-05T12:00:00+0100", "2026-02-29T12:00:00Z", "0000-09-05T12:00:00Z", "2026-09-05T12:00:00.1234567890Z", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"]) {
      var raw = value()
      raw.generated_at = bad
      compare(Digest.project(raw, options()), null, bad)
    }
    for (var stamp of ["2026-09-05T12:00:00.123456Z", "2026-09-05T12:00:00.123456789Z", "2026-09-05T12:00:00+23:59", "2026-09-05T12:00:00-23:59"]) {
      var item = value()
      item.generated_at = stamp
      verify(Digest.project(item, options()) !== null, stamp)
    }
  }
  function test_timezone_has_a_bounded_syntactic_contract() {
    for (var bad of ["/etc/localtime", "../secret", "America/../secret", "America//Los_Angeles", "America/Los_Angeles/", "America/.", "America/Los Angeles", "UTC\nPRIVATE", "x".repeat(129)]) {
      var raw = value()
      raw.timezone = bad
      compare(Digest.project(raw, options()), null, bad)
    }
    for (var zone of ["UTC", "Etc/GMT+12", "America/Argentina/Buenos_Aires", "system-local", "Author/Unknown_Zone"]) {
      var item = value()
      item.timezone = zone
      compare(Digest.project(item, options()).timezone, zone)
    }
  }
  function test_stale_is_known_true_or_unknown_never_a_freshness_promise() {
    var raw = value(), option = options()
    compare(Digest.project(raw, option).stale, null)
    raw.stale = null
    compare(Digest.project(raw, option).stale, null)
    raw.stale = true
    compare(Digest.project(raw, option).stale, true)
    raw.stale = false
    option.dirty = true
    compare(Digest.project(raw, option).stale, true)
    option.dirty = false
    option.clockChanged = true
    compare(Digest.project(raw, option).stale, true)
    option.clockChanged = false
    option.now -= 1
    compare(Digest.project(raw, option).stale, true)
    option = options()
    raw.generated_at = raw.generated_at.replace(".000Z", ".000000001Z")
    compare(Digest.project(raw, option).stale, true, "Sub-millisecond future precision must not round down")
    raw = value()
    option.now = new Date(2026, 8, 6, 0, 0, 0).getTime()
    compare(Digest.project(raw, option).stale, true)
    raw.complete = false
    compare(Digest.project(raw, option).complete, false)
  }
  function test_local_dst_days_and_leap_year_windows_use_calendar_dates() {
    for (var dates of [
      {
        end: "2026-03-09",
        short: "2026-03-03",
        long: "2026-02-08",
        now: new Date(2026, 2, 9, 12)
      },
      {
        end: "2026-11-02",
        short: "2026-10-27",
        long: "2026-10-04",
        now: new Date(2026, 10, 2, 12)
      },
      {
        end: "2024-03-01",
        short: "2024-02-24",
        long: "2024-02-01",
        now: new Date(2024, 2, 1, 12)
      }
    ]) {
      var raw = value(), option = options()
      raw.windows["7"].start_day = dates.short
      raw.windows["30"].start_day = dates.long
      raw.windows["7"].end_day = dates.end
      raw.windows["30"].end_day = dates.end
      raw.generated_at = dates.now.toISOString()
      option.now = dates.now.getTime()
      var result = Digest.project(raw, option)
      verify(result !== null, dates.end)
      compare(result.stale, null)
    }
  }
}
