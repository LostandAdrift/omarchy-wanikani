"""Authored clocks/accounts only; no desktop notification or API is invoked."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from wanikani.common import UserError
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani import reminders


def at(text, zone="UTC", fold=0):
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(zone), fold=fold).timestamp()


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wanikani-reminders-")
        self.path = Path(self.temp.name) / "study.sqlite3"
        self.store = Store(self.path)
        self.store.set("account_id", "authored-reminder-account")
        self.engine = Engine(self.store, clock=lambda: at("2026-09-05T09:00:00"))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def context(self, text="2026-09-05T09:00:00", **patch):
        return {"now": at(text), "timezone": "UTC", "event": "state", "hydrated": True,
            "dnd": False, "locked": False, "fullscreen": False, "studying": False,
            "vacation": False, "clock_untrusted": False, "account_ready": True,
            "review_count": 5, "listen_count": 0, **patch}

    def configure(self, patch=None, context=None):
        return reminders.configure(self.engine, patch or {"mode": "times"}, context or self.context())

    def claim(self, text="2026-09-05T10:00:00", **patch):
        return reminders.claim(self.engine, self.context(text, **patch))

    def test_defaults_preserve_explicit_legacy_choices_without_writes(self):
        legacy = {"notifications": False, "quiet_start": 23, "quiet_end": 7,
            "reminder_interval": 3600, "autoplay_audio": True, "last_notification_at": 123}
        self.store.set("settings", legacy)
        profile = reminders.defaults(self.engine)
        self.assertFalse(profile["enabled"])
        self.assertEqual(("23:00", "07:00", 3600), tuple(profile[key] for key in
            ("quiet_start", "quiet_end", "minimum_interval_seconds")))
        self.assertEqual(legacy, self.store.get("settings"))
        self.assertIsNone(self.store.get(reminders.CONFIG_KEY))
        self.assertEqual(["10:00", "14:00", "18:00"], reminders.defaults()["times"])
        profile["times"].append("19:00")
        self.assertEqual(3, len(reminders.defaults()["times"]))

    def test_configuration_validation_is_atomic(self):
        self.configure()
        before = self.store.get(reminders.CONFIG_KEY)
        invalid = [{"unknown": 1}, {"enabled": 1}, {"mode": "cron"}, {"target": "email"},
            {"times": []}, {"times": ["24:00"]}, {"times": [None]}, {"times": "10:00"},
            {"times": ["10:00"] * 13}, {"interval_hours": True}, {"interval_hours": 0},
            {"window_start": "22:00", "window_end": "08:00"}, {"daily_limit": 0},
            {"minimum_interval_seconds": 1799}, {"quiet_start": "8:00"},
            {"recent_study_seconds": float("inf")}, {"action": "snooze", "minutes": True},
            {"action": "snooze", "minutes": 0}, {"action": "skip_today", "extra": 1}]
        for patch in invalid:
            with self.subTest(patch=patch), self.assertRaises(UserError):
                self.configure(patch)
            self.assertEqual(before, self.store.get(reminders.CONFIG_KEY))

    def test_valid_time_list_is_sorted_and_deduplicated(self):
        result = self.configure({"times": ["18:00", "10:00", "10:00"]})
        self.assertEqual(["10:00", "18:00"], result["config"]["times"])

    def test_malformed_clock_or_timezone_does_not_mutate_state(self):
        self.configure()
        before = self.store.get(reminders.STATE_KEY)
        for patch in ({"now": float("nan")}, {"now": True}, {"now": -1}, {"now": 253402214400},
                {"timezone": "Not/A_Real_Zone"}, {"timezone": "/etc/passwd"}):
            with self.subTest(patch=patch), self.assertRaises(UserError):
                reminders.claim(self.engine, self.context(**patch))
            self.assertEqual(before, self.store.get(reminders.STATE_KEY))

    def test_disabled_or_corrupt_profile_never_emits(self):
        self.configure({"mode": "times", "enabled": False})
        result = self.claim()
        self.assertEqual("off", result["status"])
        self.assertIsNone(result["next_at"])
        self.assertIsNone(result["notification"])
        self.store.set(reminders.CONFIG_KEY, {"mode": "not-supported"})
        self.assertEqual("off", self.claim("2026-09-05T14:00:00")["status"])

    def test_persisted_legacy_cooldown_and_snooze_seed_private_ledger(self):
        self.store.set("settings", {"last_notification_at": at("2026-09-05T08:30:00"),
            "snooze_until": at("2026-09-05T10:30:00")})
        result = self.configure()
        self.assertEqual(at("2026-09-05T10:30:00"), result["next_at"])
        self.assertEqual("snoozed", self.claim()["status"])
        self.assertEqual("snooze", self.claim("2026-09-05T10:30:00")["notification"]["reason"])

    def test_due_first_observation_is_silent_then_only_increases_invite(self):
        self.assertIsNone(self.claim()["notification"])
        self.assertIsNone(self.claim("2026-09-05T10:01:00")["notification"])
        result = self.claim("2026-09-05T10:02:00", review_count=6)
        self.assertEqual("due", result["notification"]["reason"])
        self.assertEqual([{"label": "Review 5", "view": "reviews", "limit": 5}], result["notification"]["actions"])
        self.assertIsNone(self.claim("2026-09-05T13:00:00", review_count=6)["notification"])

    def test_suppressed_due_increase_is_consumed_without_backlog(self):
        self.claim(review_count=0)
        self.assertIsNone(self.claim("2026-09-05T10:01:00", dnd=True)["notification"])
        self.assertIsNone(self.claim("2026-09-05T12:01:00")["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T12:02:00", review_count=6)["notification"])

    def test_chosen_time_claim_has_future_deadline_and_one_shared_payload(self):
        first = self.configure()
        self.assertEqual(at("2026-09-05T10:00:00"), first["next_at"])
        result = self.claim(listen_count=7)
        self.assertEqual(["reviews", "listen"], [value["view"] for value in result["notification"]["actions"]])
        self.assertEqual(2, result["remaining_today"])
        self.assertEqual(at("2026-09-05T14:00:00"), result["next_at"])
        self.assertIsNone(self.claim()["notification"])

    def test_unchanged_due_pile_gets_timed_invitation(self):
        self.configure()
        self.assertIsNotNone(self.claim()["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T14:00:00")["notification"])

    def test_listening_target_caught_up_and_missing_media(self):
        self.configure({"mode": "times", "target": "listening"})
        empty = self.claim(review_count=0, listen_count=0)
        self.assertEqual("no_work", empty["status"])
        self.assertIsNone(empty["notification"])
        self.assertIsNone(self.claim("2026-09-05T10:00:30", review_count=0, listen_count=5)["notification"])
        result = self.claim("2026-09-05T14:00:00", review_count=0, listen_count=5)
        self.assertEqual(["listen"], [item["view"] for item in result["notification"]["actions"]])

    def test_all_suppression_flags_expire_slots_and_explain_preview(self):
        for flag in ("dnd", "locked", "fullscreen", "studying", "vacation", "clock_untrusted"):
            with self.subTest(flag=flag):
                self.configure()
                result = self.claim(**{flag: True})
                self.assertEqual(flag, result["status"])
                self.assertTrue(result["reason"])
                self.assertIsNone(result["notification"])
                self.assertIsNone(self.claim("2026-09-05T10:00:30")["notification"])

    def test_unknown_desktop_hydration_and_account_fail_closed(self):
        for field in ("hydrated", "account_ready", "dnd", "locked"):
            self.configure()
            context = self.context("2026-09-05T10:00:00")
            context.pop(field)
            self.assertIsNone(reminders.claim(self.engine, context)["notification"])

    def test_demo_cannot_emit_even_with_live_flags(self):
        self.configure()
        self.engine.demo = True
        result = self.claim()
        self.assertEqual("demo", result["status"])
        self.assertIsNone(result["notification"])

    def test_quiet_boundaries_skip_night_and_allow_end(self):
        self.configure({"mode": "times", "times": ["07:59", "08:00", "21:59", "22:00"],
            "minimum_interval_seconds": 1800, "daily_limit": 12}, self.context("2026-09-05T07:00:00"))
        self.assertEqual("quiet", self.claim("2026-09-05T07:59:00")["status"])
        self.assertIsNotNone(self.claim("2026-09-05T08:00:00")["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T21:59:00")["notification"])
        self.assertEqual("quiet", self.claim("2026-09-05T22:00:00")["status"])
        self.assertIsNone(self.claim("2026-09-06T07:00:00")["notification"])

    def test_interval_window_is_anchored_local_and_end_exclusive(self):
        result = self.configure({"mode": "interval", "window_start": "09:30", "window_end": "16:00", "interval_hours": 3},
            self.context("2026-09-05T09:00:00"))
        self.assertEqual(at("2026-09-05T09:30:00"), result["next_at"])
        result = self.claim("2026-09-05T09:30:00")
        self.assertEqual(at("2026-09-05T12:30:00"), result["next_at"])
        self.claim("2026-09-05T12:30:00")
        result = self.claim("2026-09-05T15:30:00")
        self.assertEqual(at("2026-09-06T09:30:00"), result["next_at"])

    def test_daily_budget_is_shared_and_rolls_over_local_midnight(self):
        self.configure({"mode": "interval", "interval_hours": 2, "daily_limit": 2})
        self.assertIsNotNone(self.claim()["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T12:00:00")["notification"])
        result = self.claim("2026-09-05T14:00:00")
        self.assertEqual("daily_limit", result["status"])
        self.assertIsNone(result["notification"])
        self.assertIsNotNone(self.claim("2026-09-06T08:00:00")["notification"])

    def test_cooldown_blocks_and_consumes_a_due_change(self):
        self.claim(review_count=0)
        self.claim("2026-09-05T10:01:00", review_count=1)
        result = self.claim("2026-09-05T11:00:00", review_count=2)
        self.assertEqual("cooldown", result["status"])
        self.assertIsNone(result["notification"])
        self.assertIsNone(self.claim("2026-09-05T12:01:00", review_count=2)["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T12:01:01", review_count=3)["notification"])

    def test_explicit_snooze_bypasses_only_cooldown_and_replaces_old_snooze(self):
        self.configure()
        self.claim()
        self.configure({"action": "snooze", "minutes": 30}, self.context("2026-09-05T10:01:00"))
        result = self.configure({"action": "snooze", "minutes": 10}, self.context("2026-09-05T10:02:00"))
        self.assertEqual(at("2026-09-05T10:12:00"), result["next_at"])
        result = self.claim("2026-09-05T10:12:00")
        self.assertEqual("snooze", result["notification"]["reason"])
        self.assertEqual(1, result["remaining_today"])
        self.assertEqual(0, result["snooze_until"])
        self.assertIsNone(self.claim("2026-09-05T10:31:00")["notification"])

    def test_snooze_still_obeys_suppression_and_budget(self):
        self.configure({"mode": "times", "daily_limit": 1})
        self.claim()
        self.configure({"action": "snooze", "minutes": 5}, self.context("2026-09-05T10:01:00"))
        self.assertIsNone(self.claim("2026-09-05T10:06:00")["notification"])
        self.configure({"mode": "times", "daily_limit": 3}, self.context("2026-09-05T11:00:00"))
        self.configure({"action": "snooze", "minutes": 5}, self.context("2026-09-05T11:00:00"))
        self.assertIsNone(self.claim("2026-09-05T11:05:00", locked=True)["notification"])
        self.assertIsNone(self.claim("2026-09-05T11:05:10")["notification"])

    def test_skip_today_cancels_snooze_and_preserves_tomorrow(self):
        self.configure()
        self.configure({"action": "snooze", "minutes": 10})
        result = self.configure({"action": "skip_today"})
        self.assertTrue(result["skip_today"])
        self.assertEqual(0, result["snooze_until"])
        self.assertEqual(at("2026-09-06T10:00:00"), result["next_at"])
        self.assertIsNone(self.claim()["notification"])
        self.assertIsNotNone(self.claim("2026-09-06T10:00:00")["notification"])

    def test_recent_study_uses_durable_fallback_and_expires_opportunity(self):
        self.configure()
        self.store.set("last_study_at", at("2026-09-05T09:50:00"))
        self.assertEqual("recent_study", self.claim()["status"])
        self.assertIsNone(self.claim("2026-09-05T10:21:00")["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T14:00:00")["notification"])

    def test_restart_wake_reconnect_and_clock_change_consume_current_slot(self):
        for event in ("startup", "wake", "reconnect", "clock_change"):
            with self.subTest(event=event):
                self.configure()
                self.assertIsNone(self.claim(event=event)["notification"])
                self.assertIsNone(self.claim("2026-09-05T10:00:10")["notification"])

    def test_late_timer_does_not_replay_a_missed_invitation(self):
        self.configure()
        self.assertIsNone(self.claim("2026-09-05T10:01:01")["notification"])
        self.assertIsNotNone(self.claim("2026-09-05T14:00:30")["notification"])

    def test_backward_clock_jump_and_timezone_change_do_not_resurrect(self):
        self.configure()
        self.claim()
        self.assertIsNone(self.claim("2026-09-05T09:00:00")["notification"])
        self.assertIsNone(self.claim()["notification"])
        self.assertIsNone(self.claim("2026-09-05T14:00:00", timezone="Europe/London")["notification"])

    def test_spring_nonexistent_time_is_skipped(self):
        zone = "America/Los_Angeles"
        result = self.configure({"mode": "times", "times": ["02:30", "04:00"], "quiet_start": "00:00", "quiet_end": "00:00"},
            self.context(now=at("2026-03-08T00:00:00", zone), timezone=zone))
        self.assertEqual(at("2026-03-08T04:00:00", zone), result["next_at"])

    def test_autumn_repeated_wall_slot_only_invites_once(self):
        zone = "America/Los_Angeles"
        self.configure({"mode": "times", "times": ["01:30"], "quiet_start": "00:00", "quiet_end": "00:00",
            "minimum_interval_seconds": 1800}, self.context(now=at("2026-11-01T00:00:00", zone), timezone=zone))
        first = self.claim(now=at("2026-11-01T01:30:00", zone), timezone=zone)
        self.assertIsNotNone(first["notification"])
        second = self.claim(now=at("2026-11-01T01:30:00", zone, fold=1), timezone=zone)
        self.assertIsNone(second["notification"])
        self.assertEqual(2, second["remaining_today"])

    def test_preview_never_changes_storage_or_fakes_a_claim(self):
        self.configure()
        before = self.store.get(reminders.STATE_KEY)
        result = reminders.preview(self.engine, self.context("2026-09-05T10:00:00"), {"target": "reviews"})
        self.assertIsNone(result["notification"])
        self.assertEqual(3, result["remaining_today"])
        self.assertEqual(0, result["last_notification_at"])
        self.assertEqual(before, self.store.get(reminders.STATE_KEY))
        self.assertIsNotNone(self.claim()["notification"])

    def test_new_data_epoch_or_account_cannot_reuse_prior_opportunity(self):
        self.configure()
        for key in ("session_epoch", "account_id"):
            self.store.set(key, "new-authored-domain")
            self.assertIsNone(self.claim()["notification"])

    def test_concurrent_claims_have_one_winner_and_no_graded_writes(self):
        self.configure()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.claim(), range(16)))
        self.assertEqual(1, sum(result["notification"] is not None for result in results))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM events"))

    def test_process_exit_after_commit_loses_toast_without_duplicate(self):
        self.configure()
        self._crash(False)
        self.assertIsNone(self.claim("2026-09-05T10:00:01")["notification"])
        self.assertEqual(1, self.store.get(reminders.STATE_KEY)["counts"]["2026-09-05"])

    def test_process_exit_before_commit_rolls_back_claim_atomically(self):
        self.configure()
        self._crash(True)
        self.assertIsNotNone(self.claim("2026-09-05T10:00:01")["notification"])
        self.assertEqual(1, self.store.get(reminders.STATE_KEY)["counts"]["2026-09-05"])

    def _crash(self, before_commit):
        program = '''import json,os,sys
from pathlib import Path
from wanikani.store import Store
from wanikani.engine import Engine
from wanikani import reminders
store=Store(Path(sys.argv[1]))
engine=Engine(store)
if sys.argv[3] == 'before':
 original=store.set
 def interrupt(key,value):
  original(key,value)
  if key == reminders.STATE_KEY: os._exit(41)
 store.set=interrupt
reminders.claim(engine,json.loads(sys.argv[2]))
os._exit(42)
'''
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")
            + os.pathsep + os.environ.get("PYTHONPATH", "")}
        result = subprocess.run([sys.executable, "-c", program, str(self.path), json.dumps(self.context("2026-09-05T10:00:00")),
            "before" if before_commit else "after"], capture_output=True, text=True, timeout=10, env=environment)
        self.assertEqual(41 if before_commit else 42, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
