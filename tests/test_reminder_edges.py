"""Reminder boundaries use authored clocks and never send desktop messages."""
from concurrent.futures import ThreadPoolExecutor
import unittest

import test_reminders as fixtures
from wanikani import reminders
from wanikani.engine import Engine
from wanikani.store import Store

at = fixtures.at


class ReminderEdgeTests(unittest.TestCase):
    setUp = fixtures.ReminderTests.setUp
    tearDown = fixtures.ReminderTests.tearDown
    context = fixtures.ReminderTests.context
    configure = fixtures.ReminderTests.configure
    claim = fixtures.ReminderTests.claim

    def test_leaving_suppression_does_not_replay_an_opportunity_inside_grace(self):
        for flag in ("dnd", "locked", "fullscreen", "studying", "vacation", "clock_untrusted"):
            with self.subTest(flag=flag):
                self.store.set(reminders.STATE_KEY, None)
                self.configure()
                self.claim("2026-09-05T09:59:00", **{flag: True})
                self.assertIsNone(self.claim("2026-09-05T10:00:30")["notification"])
                self.assertIsNotNone(self.claim("2026-09-05T14:00:00")["notification"])

    def test_initial_desktop_or_account_readiness_does_not_replay_elapsed_slots(self):
        for flag in ("hydrated", "account_ready"):
            with self.subTest(flag=flag):
                self.store.set(reminders.STATE_KEY, None)
                self.configure()
                self.claim("2026-09-05T09:59:00", **{flag: False})
                self.assertIsNone(self.claim("2026-09-05T10:00:30")["notification"])

    def test_due_increase_observed_on_leaving_dnd_is_consumed(self):
        self.configure({"mode": "due"})
        self.claim("2026-09-05T09:59:00", dnd=True, review_count=0)
        self.assertIsNone(self.claim("2026-09-05T10:00:00", dnd=False, review_count=5)["notification"])
        self.assertIsNone(self.claim("2026-09-05T12:00:00", review_count=5)["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T12:01:00", review_count=6)["notification"])

    def test_a_missed_snooze_does_not_hide_a_fresh_scheduled_slot(self):
        self.configure()
        self.configure({"action": "snooze", "minutes": 30}, self.context("2026-09-05T09:00:00"))
        result = self.claim("2026-09-05T10:00:00")
        self.assertIsNotNone(result["notification"])
        self.assertEqual("times", result["notification"]["reason"])
        self.assertEqual(0, result["snooze_until"])

    def test_snooze_and_regular_slot_share_one_opportunity_and_budget(self):
        self.configure()
        self.configure({"action": "snooze", "minutes": 60}, self.context("2026-09-05T09:00:00"))
        result = self.claim("2026-09-05T10:00:00")
        self.assertIsNotNone(result["notification"])
        self.assertEqual(2, result["remaining_today"])
        self.assertIsNone(self.claim("2026-09-05T10:00:01")["notification"])

    def test_suppression_cleared_before_the_slot_does_not_cancel_future_work(self):
        self.configure()
        self.claim("2026-09-05T09:58:00", locked=True)
        self.claim("2026-09-05T09:59:59", locked=False)
        self.assertIsNotNone(self.claim("2026-09-05T10:00:00")["notification"])

    def test_quiet_end_is_a_real_new_slot_not_a_suppression_backlog(self):
        self.configure({"mode": "times", "times": ["08:00"]}, self.context("2026-09-05T07:00:00"))
        self.assertEqual("quiet", self.claim("2026-09-05T07:59:30")["status"])
        self.assertIsNotNone(self.claim("2026-09-05T08:00:00")["notification"])

    def test_half_hour_dst_jump_skips_only_nonexistent_local_slot(self):
        zone = "Australia/Lord_Howe"
        result = self.configure({"mode": "times", "times": ["02:15", "02:45"],
            "quiet_start": "00:00", "quiet_end": "00:00"},
            self.context(now=at("2026-10-04T00:00:00", zone), timezone=zone))
        self.assertEqual(at("2026-10-04T02:45:00", zone), result["next_at"])
        result = self.claim(now=at("2026-10-04T02:45:00", zone), timezone=zone)
        self.assertIsNotNone(result["notification"])

    def test_daily_limit_uses_local_date_across_utc_midnight(self):
        zone = "America/Los_Angeles"
        self.configure({"mode": "times", "times": ["16:00", "20:00"], "daily_limit": 1},
            self.context(now=at("2026-09-05T15:00:00", zone), timezone=zone))
        first = self.claim(now=at("2026-09-05T16:00:00", zone), timezone=zone)
        self.assertIsNotNone(first["notification"])
        later = self.claim(now=at("2026-09-05T20:00:00", zone), timezone=zone)
        self.assertEqual("daily_limit", later["status"])
        self.assertIsNone(later["notification"])
        self.assertEqual(at("2026-09-06T16:00:00", zone), later["next_at"])

    def test_independent_connections_atomically_share_one_claim(self):
        self.configure()
        other = Store(self.path)
        second = Engine(other)
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda index: reminders.claim(self.engine if index % 2 else second,
                    self.context("2026-09-05T10:00:00")), range(16)))
            self.assertEqual(1, sum(result["notification"] is not None for result in results))
            self.assertEqual(1, self.store.get(reminders.STATE_KEY)["counts"]["2026-09-05"])
            self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
