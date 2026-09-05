"""Local listening retains its selected recording during ordinary cache work."""
import copy
import unittest
from unittest.mock import patch

import test_listening as authored
from wanikani import listening
from wanikani.media_plan import build


MIB = 1024 * 1024


class ListeningMediaLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.ListeningTests()
        self.fixture.setUp()
        self.engine, self.store, self.directory = self.fixture.engine, self.fixture.store, self.fixture.media_dir
        self.engine.set_settings({"cache_limit_mb": 32})
        for sid in range(1, 9):
            self.cache(self.url(sid), str(sid) + ".mp3", sid)

    def tearDown(self):
        self.fixture.tearDown()

    def url(self, sid):
        return self.fixture.words[sid]["data"]["pronunciation_audios"][0]["url"]

    def cache(self, url, name, used_at=1):
        path = self.directory / name
        with path.open("wb") as stream:
            stream.truncate(8 * MIB)
        self.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)", (url, str(path), 8 * MIB, used_at))
        return path

    def plan(self):
        result = build(self.engine, self.directory)
        self.assertTrue(result.complete)
        return result

    def evicted(self, plan):
        return {item.url for item in plan.evictions()}

    def test_current_listening_recording_survives_pressure_from_ordinary_audio(self):
        self.fixture.one(1)
        plan = self.plan()
        self.assertEqual((2, 0, 0), plan.priority(self.url(1)))
        self.assertNotIn(self.url(1), self.evicted(plan))
        self.assertTrue(self.evicted(plan))
        retained = [item for url, item in plan.cached.items() if url not in self.evicted(plan)]
        self.assertLessEqual(sum(item.size for item in retained), plan.limit_bytes)

    def test_changed_preferred_voice_cannot_replace_selected_cached_clip(self):
        self.fixture.one(1)
        item = copy.deepcopy(self.fixture.words[1])
        preferred = "https://files.wanikani.com/authored-preferred-alternate.mp3"
        clip = copy.deepcopy(item["data"]["pronunciation_audios"][0])
        clip["url"] = preferred
        clip["metadata"]["voice_actor_id"] = 2
        item["data"]["pronunciation_audios"].append(clip)
        self.store.put(item)
        self.engine.set_settings({"voice_actor_id": 2})
        plan = self.plan()
        self.assertEqual((2, 0, 0), plan.priority(self.url(1)))
        self.assertNotIn(self.url(1), self.evicted(plan))
        self.assertNotIn(self.url(1), {item.url for item in plan.placement(preferred, 8 * MIB).evictions})

    def test_completed_last_rating_keeps_only_its_still_undoable_clip(self):
        self.fixture.record(1)
        plan = self.plan()
        self.assertNotIn(self.url(1), self.evicted(plan))
        self.assertEqual((2, 0, 0), plan.priority(self.url(1)))
        self.fixture.act("undo")
        self.fixture.act("skip")
        self.assertIn(self.url(1), self.evicted(self.plan()))

    def test_reset_hidden_account_and_graded_protection_do_not_pin_old_content(self):
        self.fixture.one(1)
        context = self.store.get("listening_session_" + self.store.get("listening_active"))["context"]
        for change in ("reset", "hidden", "account", "graded", "grant"):
            with self.subTest(change=change):
                self.store.set("milestone_reset_generation", context["reset"])
                self.store.set("account_id", "authored-account")
                user = self.store.get("user")
                user["data"]["id"] = "authored-account"
                user["data"]["subscription"]["max_level_granted"] = 60
                self.store.set("user", user)
                item = copy.deepcopy(self.fixture.words[1])
                self.store.execute("DELETE FROM sessions")
                if change == "reset":
                    self.store.set("milestone_reset_generation", context["reset"] + 1)
                elif change == "hidden":
                    item["data"]["hidden_at"] = authored.stamp(self.fixture.now)
                elif change == "account":
                    self.store.set("account_id", "different-authored-account")
                    user["data"]["id"] = "different-authored-account"
                    self.store.set("user", user)
                elif change == "graded":
                    self.fixture.protect(1)
                else:
                    user["data"]["subscription"]["max_level_granted"] = 0
                    self.store.set("user", user)
                self.store.put(item)
                self.assertIn(self.url(1), self.evicted(self.plan()))

    def test_malformed_large_saved_queue_cannot_turn_into_unbounded_pinning(self):
        session = self.fixture.one(1)
        key = "listening_session_" + session["id"]
        saved = self.store.get(key)
        saved["queue"] *= 100
        self.store.set(key, saved)
        self.assertIn(self.url(1), self.evicted(self.plan()))

    def test_current_card_wins_if_five_large_listening_clips_cannot_all_fit(self):
        session = self.fixture.act("start", {"subject_ids": [1, 2, 3, 4, 5]})["session"]
        durable = self.store.get("listening_session_" + session["id"])
        current = durable["queue"][0]["url"]
        last = durable["queue"][-1]["url"]
        plan = self.plan()
        self.assertNotIn(current, self.evicted(plan))
        self.assertIn(last, self.evicted(plan))
        retained = [item for url, item in plan.cached.items() if url not in self.evicted(plan)]
        self.assertEqual(32 * MIB, sum(item.size for item in retained))

    def test_required_study_images_still_win_and_global_limit_remains_finite(self):
        self.fixture.one(1)
        for sid in range(101, 105):
            url = "https://files.wanikani.com/authored-image-" + str(sid) + ".svg"
            item = copy.deepcopy(self.fixture.words[1])
            item.update(id=sid, object="radical")
            item["data"].update(characters=None, readings=[], pronunciation_audios=[], character_images=[{"url": url}])
            self.store.put(item)
            self.store.put({"id": sid + 1000, "object": "assignment", "data": {"subject_id": sid,
                "srs_stage": 0, "hidden": False, "started_at": None,
                "unlocked_at": authored.stamp(self.fixture.now - 60), "available_at": None, "burned_at": None}})
            self.cache(url, str(sid) + ".svg")
        plan = self.plan()
        self.assertIn(self.url(1), self.evicted(plan), "Audio retention must never displace required images beyond the byte budget")
        self.assertTrue(all("authored-image" not in url for url in self.evicted(plan)))


class ListeningPoolLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.ListeningTests()
        self.fixture.setUp()
        self.engine, self.store = self.fixture.engine, self.fixture.store
        for sid in range(1, 9):
            self.assignment(sid, started_at=authored.stamp(self.fixture.now - sid * 86400))

    def tearDown(self):
        self.fixture.tearDown()

    def assignment(self, sid, **values):
        item = self.store.related("assignment", sid)
        item["data"].update(values)
        self.store.put(item)

    def pool(self, avoid_due_24h=True):
        with patch.object(listening, "MAX_CANDIDATES", 2), patch.object(
                listening, "_eligible", wraps=listening._eligible) as checked:
            pool, complete = listening._pool(self.engine, listening._context(self.engine),
                {"avoid_due_24h": avoid_due_24h})
        return [item["subject_id"] for item in pool], complete, [call.args[1] for call in checked.call_args_list]

    def pending(self, sid, state, kind="review"):
        self.store.execute("INSERT OR REPLACE INTO outbox VALUES(?,?,?,?,?,?,?)", (str(sid), kind, sid,
            state, "{}", authored.stamp(self.fixture.now), "Authored lifecycle fixture"))

    def test_recent_due_words_cannot_hide_older_ready_recordings(self):
        for sid in (1, 2):
            self.assignment(sid, available_at=authored.stamp(self.fixture.now + 3600))
        self.assertEqual(([3, 4], False, [3, 4]), self.pool())
        with patch.object(listening, "MAX_CANDIDATES", 2):
            status = listening.status(self.engine)
            self.assertEqual((2, 5, False), (status["available"], status["new_remaining"], status["complete"]))
            session = self.fixture.act("start")["session"]
        saved = self.store.get("listening_session_" + session["id"])
        self.assertEqual({3, 4}, {item["subject_id"] for item in saved["queue"]})
        self.assertIsNone(session["subject"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_every_unresolved_graded_state_is_removed_before_body_budget(self):
        for state in ("pending", "inflight", "uncertain", "blocked", "conflicted"):
            with self.subTest(state=state):
                self.pending(1, state, "review")
                self.pending(2, state, "lesson")
                self.assertEqual(([3, 4], False, [3, 4]), self.pool())
        for state, kind in (("confirmed", "review"), ("discarded", "lesson"), ("pending", "material")):
            with self.subTest(state=state, kind=kind):
                self.pending(1, state, kind)
                self.pending(2, state, kind)
                self.assertEqual(([1, 2], False, [1, 2]), self.pool())

    def test_malformed_unlearned_hidden_and_future_assignments_do_not_spend_body_budget(self):
        original = {sid: copy.deepcopy(self.store.related("assignment", sid)) for sid in (1, 2)}
        for invalid in ({"started_at": None}, {"started_at": "bad-date"}, {"started_at": 2460000},
                {"started_at": authored.stamp(self.fixture.now + 1)}, {"available_at": None},
                {"available_at": "bad-date"}, {"available_at": 2460000}, {"available_at": {}},
                {"available_at": authored.stamp(self.fixture.now + 86400)},
                {"srs_stage": 0}, {"srs_stage": True}, {"srs_stage": "5"}, {"hidden": True}):
            with self.subTest(invalid=invalid):
                for sid in (1, 2):
                    self.store.put(original[sid])
                    self.assignment(sid, **invalid)
                self.assertEqual(([3, 4], False, [3, 4]), self.pool())

    def test_confirmed_burned_words_need_no_review_date_but_future_burn_does_not_qualify(self):
        for sid in (1, 2):
            self.assignment(sid, srs_stage=9, available_at=None, burned_at=authored.stamp(self.fixture.now - 1))
        self.assertEqual(([1, 2], False, [1, 2]), self.pool())
        for invalid in (authored.stamp(self.fixture.now + 1), "bad-date", 2460000):
            for sid in (1, 2):
                self.assignment(sid, burned_at=invalid)
            self.assertEqual(([3, 4], False, [3, 4]), self.pool())

    def test_due_preference_can_widen_schedule_without_bypassing_pending_or_learning_gates(self):
        for sid in (1, 2):
            self.assignment(sid, available_at=None)
        self.assertEqual(([1, 2], False, [1, 2]), self.pool(avoid_due_24h=False))
        self.pending(1, "pending")
        self.assignment(2, started_at=None)
        self.assertEqual(([3, 4], False, [3, 4]), self.pool(avoid_due_24h=False))

    def test_hidden_and_restricted_subjects_are_not_candidate_content(self):
        for values in ({"hidden_at": authored.stamp(self.fixture.now)}, {"level": 61},
                {"level": True}, {"level": "1"}, {"level": 0}):
            with self.subTest(values=values):
                for sid in (1, 2):
                    item = copy.deepcopy(self.fixture.words[sid])
                    item["data"].update(values)
                    self.store.put(item)
                self.assertEqual(([3, 4], False, [3, 4]), self.pool())

    def test_local_due_then_pinned_priority_survives_schedule_prefiltering(self):
        self.fixture.record(6)
        self.fixture.now += 86400
        self.store.set("pinned_subjects", [5])
        for sid in (1, 2):
            self.assignment(sid, available_at=authored.stamp(self.fixture.now + 3600))
        self.assertEqual(([6, 5], False, [6, 5]), self.pool())

    def test_final_hydration_rechecks_current_access_after_metadata_selection(self):
        for sid in (1, 2):
            self.assignment(sid, available_at=authored.stamp(self.fixture.now + 3600))
        eligible = listening._eligible

        def changed(engine, sid, protection, settings):
            if sid == 3:
                item = copy.deepcopy(self.fixture.words[sid])
                item["data"]["hidden_at"] = authored.stamp(self.fixture.now)
                self.store.put(item)
            return eligible(engine, sid, protection, settings)

        with patch.object(listening, "_eligible", side_effect=changed):
            self.assertEqual(([4], False, [3, 4]), self.pool())

    def test_entire_due_catalogue_is_honestly_complete_without_body_checks(self):
        for sid in range(1, 9):
            self.assignment(sid, available_at=authored.stamp(self.fixture.now))
        self.assertEqual(([], True, []), self.pool())


if __name__ == "__main__":
    unittest.main()
