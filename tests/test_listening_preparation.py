"""Authored listening preparation fixtures; no real transport or audio playback."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_listening as fixtures
from test_media_sync import Response
from wanikani import listening, listening_preparation as preparation
from wanikani.common import UserError, stamp
from wanikani.sync import Synchronizer


class InertMedia:
    """Exercise orchestration permission boundaries without network or grading."""
    def __init__(self, engine, before=None, after=None, outcome=None):
        self.engine = engine
        self.before, self.after, self.outcome = before, after, outcome
        self.calls = []

    def prepare_recordings(self, candidates, *, permitted, cancelled, progress):
        self.calls.append(copy.deepcopy(candidates))
        if self.before:
            self.before()
        result = {"downloaded": 0, "already_cached": 0, "failed": 0,
            "skipped_budget": 0, "cancelled": False, "complete": True}
        for item in candidates:
            if cancelled() or not permitted(item):
                result.update(cancelled=cancelled(), complete=False)
                break
            if self.outcome:
                result[self.outcome] += 1
                continue
            rows = self.engine.store.rows("SELECT path FROM media WHERE url=?", (item["url"],))
            if rows and Path(rows[0][0]).is_file():
                result["already_cached"] += 1
                continue
            # Model a network response before the executor's permission check.
            if self.after:
                callback, self.after = self.after, None
                callback()
            if cancelled() or not permitted(item):
                result.update(cancelled=cancelled(), complete=False)
                break
            path = self.engine.store.path.parent / "media" / (str(item["subject_id"]) + ".mp3")
            path.write_bytes(b"Original inert test recording bytes")
            self.engine.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)",
                (item["url"], str(path), path.stat().st_size, self.engine.now()))
            result["downloaded"] += 1
            progress({"downloaded": result["downloaded"], "already_cached": result["already_cached"]})
        return result


class ListeningPreparationTests(unittest.TestCase):
    setUp = fixtures.ListeningTests.setUp
    tearDown = fixtures.ListeningTests.tearDown
    word = fixtures.ListeningTests.word
    protect = fixtures.ListeningTests.protect
    act = fixtures.ListeningTests.act
    one = fixtures.ListeningTests.one
    record = fixtures.ListeningTests.record
    card = fixtures.ListeningTests.card

    def online(self):
        self.engine.connected = True
        self.engine.status = "ready"

    def missing(self, *ids):
        for sid in ids or range(1, 9):
            for clip in self.words[sid]["data"]["pronunciation_audios"]:
                rows = self.store.rows("SELECT path FROM media WHERE url=?", (clip["url"],))
                for row in rows:
                    Path(row[0]).unlink(missing_ok=True)
                self.store.execute("DELETE FROM media WHERE url=?", (clip["url"],))

    def durable(self):
        return {table: [tuple(row) for row in self.store.rows("SELECT * FROM " + table + " ORDER BY rowid")]
            for table in ("sessions", "outbox", "events", "commands", "meta")}

    def test_readonly_neutral_preflight_counts_cached_files_toward_five(self):
        self.online()
        self.missing(3, 4, 5, 6, 7, 8)
        before = self.durable()
        value = preparation.availability(self.engine)
        self.assertEqual({"ready": 2, "needs_download": 3, "complete": True, "reason": "needs_download"},
            {key: value[key] for key in ("ready", "needs_download", "complete", "reason")})
        self.assertEqual(before, self.durable())
        for private in ("subject_id", "url", "uri", "山", "やま", "meaning"):
            self.assertNotIn(private, json.dumps(value, ensure_ascii=False))

    def test_default_pool_still_requires_cached_media_and_no_outbox_is_created(self):
        self.online()
        self.missing()
        self.assertEqual(0, listening.status(self.engine)["available"])
        with self.assertRaises(UserError):
            self.act("start")
        before = self.durable()
        sync, notices = InertMedia(self.engine), []
        result = preparation.prepare(sync, progress=notices.append)
        self.assertEqual(("ready", 5, 0), (result["status"], result["downloaded"], result["already_cached"]))
        self.assertEqual(1, len(sync.calls))
        self.assertEqual(5, len(sync.calls[0]))
        self.assertEqual(before, self.durable())
        self.assertEqual(5, listening.status(self.engine)["available"])
        self.assertIsNone(listening.view(self.engine))
        self.assertEqual(5, listening.status(self.engine)["new_remaining"])
        for value in [result, *notices]:
            self.assertNotIn("https:", json.dumps(value))
            self.assertNotIn("subject_id", json.dumps(value))

    def test_cached_batch_does_not_invoke_media_executor(self):
        sync = InertMedia(self.engine)
        result = preparation.prepare(sync)
        self.assertEqual(("ready", 5, 0), (result["status"], result["already_cached"], result["downloaded"]))
        self.assertEqual([], sync.calls)

    def test_existing_five_ready_later_in_pool_prevent_unnecessary_download(self):
        self.online()
        self.missing(1, 2, 3)
        self.assertEqual(5, listening.status(self.engine)["available"])
        result = preparation.availability(self.engine)
        self.assertEqual((5, 0), (result["ready"], result["needs_download"]))
        sync = InertMedia(self.engine)
        self.assertEqual("ready", preparation.prepare(sync)["status"])
        self.assertEqual([], sync.calls)

    def test_cached_alternate_voice_precedes_missing_preferred_voice(self):
        self.online()
        self.engine.set_settings({"voice_actor_id": 2})
        item = self.words[1]
        preferred = copy.deepcopy(item["data"]["pronunciation_audios"][0])
        preferred["url"] += "-preferred"
        preferred["metadata"]["voice_actor_id"] = 2
        item["data"]["pronunciation_audios"].insert(0, preferred)
        self.store.put(item)
        first = listening.preparation_candidates(self.engine)["items"][0]
        self.assertEqual(1, first["clip"]["actor"])
        self.assertTrue(first["clip"]["path"])
        self.assertEqual(0, preparation.availability(self.engine)["needs_download"])

    def test_preferred_voice_selected_when_no_valid_recording_cached(self):
        self.online()
        self.engine.set_settings({"voice_actor_id": 2})
        item = self.words[1]
        alternate = copy.deepcopy(item["data"]["pronunciation_audios"][0])
        alternate["url"] += "-preferred"
        alternate["metadata"]["voice_actor_id"] = 2
        item["data"]["pronunciation_audios"].append(alternate)
        self.store.put(item)
        self.missing()
        first = listening.preparation_candidates(self.engine)["items"][0]
        self.assertEqual((2, None), (first["clip"]["actor"], first["clip"]["path"]))

    def test_offline_and_demo_do_not_attempt_download_or_mutate_state(self):
        self.missing()
        for state in ("disconnected", "offline", "demo"):
            with self.subTest(state=state):
                self.engine.connected = state != "disconnected"
                self.engine.status = state
                self.engine.demo = state == "demo"
                before = self.durable()
                sync = InertMedia(self.engine)
                self.assertEqual("offline", preparation.availability(self.engine)["reason"])
                self.assertEqual("offline", preparation.prepare(sync)["reason"])
                self.assertEqual([], sync.calls)
                self.assertEqual(before, self.durable())

    def test_saved_session_remains_exact_and_prevents_new_preparation(self):
        self.online()
        self.one()
        self.act("reveal")
        self.missing()
        before = self.durable()
        sync = InertMedia(self.engine)
        self.assertEqual("saved_session", preparation.availability(self.engine)["reason"])
        self.assertEqual("saved_session", preparation.prepare(sync)["reason"])
        self.assertEqual(before, self.durable())
        self.assertEqual([], sync.calls)

    def test_completed_session_does_not_block_and_daily_allowance_remains_local(self):
        self.online()
        for sid in range(1, 6):
            self.record(sid)
        self.missing()
        before = self.durable()
        sync = InertMedia(self.engine)
        self.assertEqual("daily_limit", preparation.availability(self.engine)["reason"])
        self.assertEqual("daily_limit", preparation.prepare(sync)["reason"])
        self.assertEqual(before, self.durable())
        self.assertEqual([], sync.calls)
        self.now += 86400
        self.assertEqual(5, preparation.availability(self.engine)["needs_download"])

    def test_due_local_word_precedes_fresh_and_future_local_interval_is_skipped(self):
        self.online()
        self.record(8, rating="again")
        self.record(7)
        self.missing()
        self.now += 600
        items = listening.preparation_candidates(self.engine)["items"]
        self.assertEqual(8, items[0]["subject_id"])
        self.assertNotIn(7, [item["subject_id"] for item in items])

    def test_distinct_sounds_and_all_graded_aliases_are_excluded(self):
        self.online()
        self.protect(1, "reviews")
        self.protect(2, "lessons")
        self.word(9, "ヤマ", "homophone")
        self.word(10, "しろ", "山2")
        self.word(11, "そら", "other-sky")
        self.missing(*self.words)
        items = listening.preparation_candidates(self.engine)["items"]
        self.assertFalse({1, 2, 9, 10}.intersection(item["subject_id"] for item in items))
        self.assertEqual(len(items), len({item["clip"]["pronunciation"] for item in items}))

    def test_unresolved_graded_work_hidden_and_invalid_grants_are_not_preparable(self):
        self.online()
        for sid, state in enumerate(("pending", "inflight", "uncertain", "conflicted", "blocked"), 1):
            self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)",
                ("work" + str(sid), "lesson" if sid == 1 else "review", sid, state, "{}", stamp(self.now), "fixture"))
        self.words[6]["data"]["hidden_at"] = stamp(self.now)
        self.words[7]["data"]["level"] = True
        self.words[8]["data"]["level"] = 61
        for sid in (6, 7, 8):
            self.store.put(self.words[sid])
        self.missing()
        self.assertEqual("no_candidates", preparation.availability(self.engine)["reason"])

    def test_malformed_audio_metadata_and_unsafe_hosts_are_not_download_candidates(self):
        self.online()
        for sid, modification in enumerate((
                {"url": "https://example.org/word.mp3"}, {"content_type": "image/png"},
                {"metadata": []}, {"metadata": {"pronunciation": "english"}},
                {"url": "https://files.wanikani.com:8443/word"}, {"url": "https://user@files.wanikani.com/word"}), 1):
            self.words[sid]["data"]["pronunciation_audios"][0].update(modification)
            self.store.put(self.words[sid])
        self.missing()
        self.assertEqual([7, 8], [item["subject_id"] for item in listening.preparation_candidates(self.engine)["items"]])

    def test_due_soon_projection_does_not_consume_hydration_budget(self):
        self.online()
        for sid in range(1, 7):
            assignment = self.store.related("assignment", sid)
            assignment["data"]["available_at"] = stamp(self.now + 86400)
            self.store.put(assignment)
        self.missing()
        with patch.object(listening, "MAX_CANDIDATES", 2):
            result = preparation.availability(self.engine)
        self.assertEqual((2, True), (result["needs_download"], result["complete"]))

    def test_incomplete_candidate_scan_has_honest_counts(self):
        self.online()
        self.missing()
        with patch.object(listening, "MAX_CANDIDATES", 2):
            result = preparation.availability(self.engine)
        self.assertEqual((2, False, "incomplete"), (result["needs_download"], result["complete"], result["reason"]))

    def test_context_and_eligibility_changes_before_or_after_io_fail_closed(self):
        def mutate(kind):
            if kind == "account":
                self.store.set("account_id", "other-account")
            elif kind in ("session_epoch", "milestone_reset_generation"):
                self.store.set(kind, "changed")
            elif kind == "grant":
                user = self.store.get("user")
                user["data"]["subscription"]["period_ends_at"] = stamp(self.now + 10)
                self.store.set("user", user)
            elif kind == "protection":
                self.protect(1)
            elif kind == "pending":
                self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)",
                    ("during", "review", 1, "pending", "{}", stamp(self.now), "fixture"))
            elif kind == "assignment":
                assignment = self.store.related("assignment", 1)
                assignment["data"]["available_at"] = stamp(self.now)
                self.store.put(assignment)
            elif kind == "day":
                self.now += 86400
            elif kind == "settings":
                self.store.set("listening_settings", {"avoid_due_24h": False})
            elif kind == "clock":
                self.engine.clock_untrusted = True
        for boundary in ("before", "after"):
            for kind in ("account", "session_epoch", "milestone_reset_generation", "grant", "protection", "pending", "assignment", "day", "settings", "clock"):
                with self.subTest(boundary=boundary, kind=kind):
                    self.tearDown()
                    self.setUp()
                    self.online()
                    self.missing()
                    sync = InertMedia(self.engine, **{boundary: lambda kind=kind: mutate(kind)})
                    value = preparation.prepare(sync)
                    self.assertEqual("permission_changed", value["reason"])
                    self.assertEqual(0, value["downloaded"])
                    self.assertEqual([], self.store.rows("SELECT * FROM media"))

    def test_time_crossing_subscription_expiry_invalidates_even_unchanged_user(self):
        self.online()
        self.missing()
        user = self.store.get("user")
        user["data"]["subscription"].update(type="recurring", period_ends_at=stamp(self.now + 1))
        self.store.set("user", user)
        sync = InertMedia(self.engine, after=lambda: setattr(self, "now", self.now + 2))
        self.assertEqual("permission_changed", preparation.prepare(sync)["reason"])

    def test_expiry_invalidates_even_when_effective_grant_stays_three(self):
        self.online()
        self.missing()
        user = self.store.get("user")
        user["data"]["subscription"].update(type="recurring", max_level_granted=3, period_ends_at=stamp(self.now + 1))
        self.store.set("user", user)
        sync = InertMedia(self.engine, after=lambda: setattr(self, "now", self.now + 2))
        self.assertEqual("permission_changed", preparation.prepare(sync)["reason"])

    def test_saved_session_created_during_io_stops_preparation(self):
        self.online()
        self.missing(1, 2, 3, 4, 5)
        sync = InertMedia(self.engine, after=lambda: self.one(8))
        self.assertEqual("permission_changed", preparation.prepare(sync)["reason"])
        self.assertEqual(0, listening.view(self.engine)["index"])

    def test_budget_and_network_failures_are_distinct_without_retry(self):
        self.online()
        self.missing()
        for outcome, reason in (("skipped_budget", "budget"), ("failed", "download_failed")):
            with self.subTest(outcome=outcome):
                sync = InertMedia(self.engine, outcome=outcome)
                result = preparation.prepare(sync)
                self.assertEqual((reason, 5, True), (result["reason"], result[outcome], result["complete"]))
                self.assertEqual(1, len(sync.calls))

    def test_cancel_does_not_start_or_continue_and_does_not_change_study(self):
        self.online()
        self.missing()
        before = self.durable()
        sync = InertMedia(self.engine)
        self.assertEqual("cancelled", preparation.prepare(sync, cancelled=lambda: True)["status"])
        self.assertEqual([], sync.calls)
        stopped = [False]
        sync = InertMedia(self.engine, after=lambda: stopped.__setitem__(0, True))
        result = preparation.prepare(sync, cancelled=lambda: stopped[0])
        self.assertEqual(("cancelled", False, 0), (result["status"], result["complete"], result["downloaded"]))
        self.assertEqual(before, self.durable())

    def test_malformed_saved_work_is_a_neutral_error_not_empty_ready_state(self):
        self.online()
        self.store.execute("INSERT INTO sessions VALUES(?,?)", ("broken", json.dumps({"mode": "reviews", "phase": "question", "queue": True})))
        value = preparation.availability(self.engine)
        self.assertEqual((0, 0, False, "protected_study"),
            (value["ready"], value["needs_download"], value["complete"], value["reason"]))
        with self.assertRaises(UserError):
            preparation.prepare(InertMedia(self.engine))

    def test_invalid_internal_limit_cannot_expand_fixed_batch(self):
        for limit in (0, 6, True, "5", None):
            with self.subTest(limit=limit), self.assertRaises(UserError):
                listening.preparation_candidates(self.engine, limit)

    def test_real_executor_uses_one_plan_five_mock_downloads_and_no_study_changes(self):
        from wanikani import media_plan
        self.online()
        self.missing()
        before = self.durable()
        sync = Synchronizer(self.engine, None, self.media_dir)
        with patch("socket.create_connection", side_effect=AssertionError("No live networking")), \
                patch("wanikani.sync.urllib.request.build_opener") as factory, \
                patch("wanikani.sync.media_plan.build", wraps=media_plan.build) as build:
            factory.return_value.open.side_effect = lambda *args, **kwargs: Response()
            result = preparation.prepare(sync)
        self.assertEqual(("ready", 5, True), (result["status"], result["downloaded"], result["complete"]))
        self.assertEqual((1, 5), (build.call_count, factory.return_value.open.call_count))
        self.assertEqual(before, self.durable())
        self.assertEqual(5, listening.status(self.engine)["available"])

    def test_cache_limit_change_during_read_stops_before_placement(self):
        self.online()
        self.missing()
        self.engine.set_settings({"cache_limit_mb": 64})
        for index in range(4):
            path = self.media_dir / ("weaker-" + str(index) + ".mp3")
            with path.open("wb") as stream:
                stream.truncate(8 * 1024 * 1024)
            self.store.execute("INSERT INTO media VALUES(?,?,?,?)",
                ("https://files.wanikani.com/weaker-" + str(index), str(path), path.stat().st_size, self.now))
        sync = Synchronizer(self.engine, None, self.media_dir)
        with patch("socket.create_connection", side_effect=AssertionError("No live networking")), \
                patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = Response(b"x", read_hook=lambda:
                self.engine.set_settings({"cache_limit_mb": 32}))
            result = preparation.prepare(sync)
        self.assertEqual(("permission_changed", 0, False),
            (result["reason"], result["downloaded"], result["complete"]))
        self.assertEqual(1, factory.return_value.open.call_count)
        self.assertEqual(32 * 1024 * 1024, sum(path.stat().st_size for path in self.media_dir.iterdir()))
        self.assertEqual(4, len(self.store.rows("SELECT * FROM media")))

    def test_final_ready_rechecks_actual_files_after_media_ownership_ends(self):
        self.online()
        self.missing()
        sync = Synchronizer(self.engine, None, self.media_dir)
        original = sync.prepare_recordings

        def cache_changed_after_release(*args, **kwargs):
            result = original(*args, **kwargs)
            for row in self.store.rows("SELECT path FROM media"):
                Path(row[0]).unlink()
            return result

        with patch.object(sync, "prepare_recordings", side_effect=cache_changed_after_release), \
                patch("socket.create_connection", side_effect=AssertionError("No live networking")), \
                patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = [Response() for _ in range(5)]
            result = preparation.prepare(sync)
        self.assertEqual(("partial", "incomplete", 5, False),
            (result["status"], result["reason"], result["downloaded"], result["complete"]))
        self.assertEqual(0, preparation.availability(self.engine)["ready"])


if __name__ == "__main__":
    unittest.main()
