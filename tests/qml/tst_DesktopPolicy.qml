import QtQuick
import QtTest
import "../../qml/DesktopPolicy.mjs" as Policy

TestCase {
    name: "DesktopPolicy"
    readonly property real now: 100000

    function test_only_new_increases_notify_data() {
        return [
            {tag: "initial load consumes existing reviews", previous: -1, due: 20, expected: false},
            {tag: "caught up", previous: 0, due: 0, expected: false},
            {tag: "unchanged", previous: 5, due: 5, expected: false},
            {tag: "reviews decrease", previous: 5, due: 2, expected: false},
            {tag: "reviews become due", previous: 0, due: 1, expected: true},
            {tag: "more reviews become due", previous: 1, due: 3, expected: true}
        ]
    }
    function test_only_new_increases_notify(data) {
        var result = Policy.notification(data.previous, data.due, now, 12, {}, {})
        compare(result.notify, data.expected)
        compare(result.previousDue, data.due)
    }

    function test_suppressed_increases_never_replay_data() {
        return [
            {tag: "demo", flags: {demo: true}},
            {tag: "locked", flags: {locked: true}},
            {tag: "Do Not Disturb", flags: {dnd: true}},
            {tag: "active study", flags: {studying: true}},
            {tag: "vacation", flags: {vacation: true}}
        ]
    }
    function test_suppressed_increases_never_replay(data) {
        var suppressed = Policy.notification(0, 5, now, 12, {}, data.flags)
        compare(suppressed.notify, false)
        compare(suppressed.previousDue, 5)
        compare(Policy.notification(suppressed.previousDue, 5, now + 1, 12, {}, {}).notify, false)
        compare(Policy.notification(suppressed.previousDue, 6, now + 1, 12, {}, {}).notify, true)
    }

    function test_default_quiet_boundaries_data() {
        return [
            {tag: "midnight", hour: 0, expected: false},
            {tag: "last quiet hour", hour: 7, expected: false},
            {tag: "quiet hours end", hour: 8, expected: true},
            {tag: "last awake hour", hour: 21, expected: true},
            {tag: "quiet hours start", hour: 22, expected: false},
            {tag: "late evening", hour: 23, expected: false}
        ]
    }
    function test_default_quiet_boundaries(data) {
        compare(Policy.notification(0, 1, now, data.hour, {}, {}).notify, data.expected)
    }

    function test_daytime_and_disabled_quiet_hours() {
        var settings = {quiet_start: 9, quiet_end: 17}
        compare(Policy.notification(0, 1, now, 8, settings, {}).notify, true)
        compare(Policy.notification(0, 1, now, 9, settings, {}).notify, false)
        compare(Policy.notification(0, 1, now, 16, settings, {}).notify, false)
        compare(Policy.notification(0, 1, now, 17, settings, {}).notify, true)
        compare(Policy.notification(0, 1, now, 22, {quiet_start: 22, quiet_end: 22}, {}).notify, true)
    }

    function test_persisted_minimum_interval_and_exact_boundary() {
        var settings = {last_notification_at: now - 7199}
        compare(Policy.notification(0, 1, now, 12, settings, {}).notify, false)
        compare(Policy.notification(0, 1, now + 1, 12, settings, {}).notify, true)
        settings.reminder_interval = 14400
        compare(Policy.notification(0, 1, now + 1, 12, settings, {}).notify, false)
        compare(Policy.notification(0, 1, now + 7201, 12, settings, {}).notify, true)
        settings.last_notification_at = now + 60
        compare(Policy.notification(0, 1, now, 12, settings, {}).notify, false)
    }

    function test_snooze_off_and_quiet_consumed_without_backlog() {
        var cases = [
            {settings: {snooze_until: now + 1}, hour: 12},
            {settings: {notifications: false}, hour: 12},
            {settings: {}, hour: 22},
            {settings: {last_notification_at: now}, hour: 12}
        ]
        for (var i = 0; i < cases.length; ++i) {
            var result = Policy.notification(0, 5, now, cases[i].hour, cases[i].settings, {})
            compare(result.notify, false)
            compare(result.previousDue, 5)
            compare(Policy.notification(result.previousDue, 5, now + 86400, 12, {}, {}).notify, false)
        }
        compare(Policy.notification(0, 1, now, 12, {snooze_until: now}, {}).notify, true)
    }

    function test_idle_window_data() {
        return [
            {tag: "short deadline", deadline: 60, enabled: false, end: 58},
            {tag: "minimum interval boundary", deadline: 65, enabled: false, end: 63},
            {tag: "usable interval", deadline: 66, enabled: true, end: 64},
            {tag: "installed screensaver", deadline: 150, enabled: true, end: 148},
            {tag: "lock is first", deadline: 90, enabled: true, end: 88}
        ]
    }
    function test_idle_window(data) {
        var result = Policy.idleWindow(data.deadline)
        compare(result.start, 60)
        compare(result.end, data.end)
        compare(result.enabled, data.enabled)
    }

    function test_ambient_gates_data() {
        return [
            {tag: "desktop available", flags: {}, expected: true},
            {tag: "locked", flags: {locked: true}, expected: false},
            {tag: "fullscreen", flags: {fullscreen: true}, expected: false},
            {tag: "study", flags: {studying: true}, expected: false},
            {tag: "panel open", flags: {panelOpen: true}, expected: false},
            {tag: "multiple suppressors", flags: {locked: true, fullscreen: true}, expected: false}
        ]
    }
    function test_ambient_gates(data) {
        compare(Policy.ambientAllowed(data.flags), data.expected)
    }

    function test_ambient_fetch_requires_a_visible_consumer_data() {
        return [
            {tag: "switches off", settings: {}, flags: {ready: true}, expected: false},
            {tag: "card before idle", settings: {desktop_card: true}, flags: {ready: true}, expected: false},
            {tag: "idle card", settings: {desktop_card: true}, flags: {ready: true, desktopIdle: true}, expected: true},
            {tag: "gallery before interval", settings: {idle_gallery: true}, flags: {ready: true}, expected: false},
            {tag: "idle gallery", settings: {idle_gallery: true}, flags: {ready: true, idleEligible: true}, expected: true},
            {tag: "manual Zen with switches off", settings: {}, flags: {ready: true, zen: true, panelOpen: true}, expected: true},
            {tag: "closed Zen", settings: {}, flags: {ready: true, zen: true}, expected: false},
            {tag: "locked Zen", settings: {}, flags: {ready: true, zen: true, panelOpen: true, locked: true}, expected: false},
            {tag: "studying", settings: {desktop_card: true}, flags: {ready: true, desktopIdle: true, studying: true}, expected: false},
            {tag: "fullscreen card", settings: {desktop_card: true}, flags: {ready: true, desktopIdle: true, fullscreen: true}, expected: false},
            {tag: "other panel", settings: {desktop_card: true}, flags: {ready: true, desktopIdle: true, panelOpen: true}, expected: false},
            {tag: "worker unavailable", settings: {desktop_card: true}, flags: {desktopIdle: true}, expected: false}
        ]
    }
    function test_ambient_fetch_requires_a_visible_consumer(data) {
        compare(Policy.ambientDemand(data.settings, data.flags), data.expected)
    }
    function test_ambient_request_coalescing_and_freshness() {
        compare(Policy.ambientFetch(false, true, false, true, 100000, 0), false)
        compare(Policy.ambientFetch(true, true, true, true, 100000, 0), false)
        compare(Policy.ambientFetch(true, false, false, true, 100000, 0), false)
        compare(Policy.ambientFetch(true, true, false, true, 100000, 100000), true)
        compare(Policy.ambientFetch(true, true, false, false, 100000, 40001), false)
        compare(Policy.ambientFetch(true, true, false, false, 100000, 40000), true)
    }
}
