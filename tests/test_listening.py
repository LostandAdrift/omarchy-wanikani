"""Listening contracts use authored media bytes; no audio-quality/live-API claim."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from test_backend import Engine, Store, NOW, stamp
from wanikani import listening
from wanikani.common import UserError


class ListeningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "state.db"
        self.media_dir = self.path.parent / "media"
        self.media_dir.mkdir()
        self.now = NOW
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.store.set("account_id", "authored-account")
        self.store.set("user", {"object": "user", "data": {"id": "authored-account", "level": 2,
            "subscription": {"type": "lifetime", "max_level_granted": 60, "period_ends_at": None}}})
        self.words = {}
        for sid, sound in enumerate(("やま", "かわ", "そら", "みず", "つき", "ほし", "あめ", "もり"), 1):
            self.word(sid, sound)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def word(self, sid, sound, characters=None, kind="vocabulary", stage=5):
        url = "https://files.wanikani.com/authored-clip-" + str(sid)
        self.words[sid] = {"id": sid, "object": kind, "data": {"level": 1, "hidden_at": None,
            "characters": characters or "山" + str(sid), "slug": "authored-word",
            "meanings": [{"meaning": "Authored meaning " + str(sid), "accepted_answer": True, "primary": True}],
            "readings": [] if kind == "kana_vocabulary" else [{"reading": sound, "accepted_answer": True}],
            "auxiliary_meanings": [], "pronunciation_audios": [{"url": url, "content_type": "audio/mpeg",
                "metadata": {"pronunciation": sound, "voice_actor_id": 1, "voice_actor_name": "Fixture voice"}}],
            "meaning_mnemonic": "Authored mnemonic", "component_subject_ids": [], "character_images": []}}
        self.store.put(self.words[sid])
        self.store.put({"id": sid + 1000, "object": "assignment", "data": {"subject_id": sid,
            "srs_stage": stage, "hidden": False, "started_at": stamp(self.now - 86400),
            "unlocked_at": stamp(self.now - 2 * 86400), "available_at": stamp(self.now + 365 * 86400), "burned_at": None}})
        media = self.media_dir / (str(sid) + ".mp3")
        media.write_bytes(b"Independently authored nonempty media fixture; not decodable speech.")
        self.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)", (url, str(media), media.stat().st_size, self.now))

    def act(self, action, args=None, key=None):
        args = dict(args or {})
        if action not in ("start", "settings"):
            state = listening.view(self.engine)
            args = {"session_id": state["id"], "revision": state["revision"], **args}
        return listening.command(self.engine, key or uuid.uuid4().hex, action, args)

    def one(self, sid=1, **kwargs):
        return self.act("start", {"subject_ids": [sid], **kwargs})["session"]

    def record(self, sid=1, rating="remembered", **kwargs):
        self.one(sid, **kwargs)
        self.act("reveal")
        return self.act("rate", {"rating": rating})["session"]

    def card(self, sid):
        return self.store.get(listening._card_key(listening._context(self.engine), sid))

    def protect(self, sid, mode="reviews"):
        self.store.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", (mode, json.dumps({"id": mode,
            "mode": mode, "phase": "question", "queue": [{"subject_id": sid, "done": False}]})))

    def test_unrevealed_projection_contains_only_neutral_controls_and_opaque_handle(self):
        self.store.put({"id": 9000, "object": "study_material", "data": {"subject_id": 1,
            "meaning_synonyms": [], "meaning_note": "PRIVATE AUTHORED NOTE", "reading_note": "Secret mnemonic"}})
        front = self.one()
        self.assertIsNone(front["subject"])
        encoded = json.dumps(front, ensure_ascii=False)
        for hidden in ("山1", "やま", "Authored meaning", "PRIVATE AUTHORED NOTE", "pronunciation", "metadata", "subject_id"):
            self.assertNotIn(hidden, encoded)
        self.assertEqual(32, len(front["media_handle"]))
        shown = self.act("reveal")["session"]
        self.assertEqual("山1", shown["subject"]["characters"])
        self.assertEqual("PRIVATE AUTHORED NOTE", shown["subject"]["material"]["meaning_note"])

    def test_play_exposure_counts_once_and_preserves_intervals(self):
        front = self.one()
        before = listening.status(self.engine)["new_remaining"]
        first = listening.media(self.engine, front["media_handle"])
        second = listening.media(self.engine, front["media_handle"])
        self.assertEqual(first["uri"], second["uri"])
        self.assertEqual(first["revision"], second["revision"])
        self.assertEqual(before - 1, listening.status(self.engine)["new_remaining"])
        self.assertIsNone(self.card(1))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_rating_requires_reveal_and_current_revision(self):
        front = self.one()
        with self.assertRaises(UserError):
            self.act("rate", {"rating": "remembered"})
        listening.media(self.engine, front["media_handle"])
        with self.assertRaises(UserError):
            listening.command(self.engine, "stale-reveal", "reveal", {"session_id": front["id"], "revision": front["revision"]})
        self.act("reveal")
        self.act("rate", {"rating": "remembered"})
        self.assertEqual(1, self.card(1)["attempts"])

    def test_fixed_intervals_and_again_retry_do_not_expand_batch(self):
        for days in (1, 3, 7, 14, 30, 30):
            self.record()
            self.assertEqual(stamp(self.now + days * 86400), self.card(1)["next_at"])
            self.now += days * 86400
        end = self.record(rating="again")
        self.assertEqual("complete", end["phase"])
        self.assertEqual(1, end["total"])
        self.assertEqual(stamp(self.now + 600), self.card(1)["next_at"])
        self.assertEqual(-1, self.card(1)["step"])
        self.record()
        self.assertEqual(stamp(self.now + 86400), self.card(1)["next_at"])

    def test_skip_and_missing_media_do_not_create_false_ratings(self):
        self.one()
        self.media_dir.joinpath("1.mp3").unlink()
        blocked = listening.view(self.engine)
        self.assertIn("unavailable", blocked)
        self.assertIsNone(blocked["media_handle"])
        with self.assertRaises(UserError):
            self.act("reveal")
        end = self.act("skip")["session"]
        self.assertEqual({"remembered": 0, "again": 0, "skipped": 1}, end["summary"])
        self.assertIsNone(self.card(1))
        self.assertEqual(5, listening.status(self.engine)["new_remaining"])

    def test_daily_five_new_words_and_deliberate_extra_selection(self):
        for sid in range(1, 6):
            self.record(sid)
        self.assertEqual(0, listening.status(self.engine)["new_remaining"])
        self.assertEqual(0, listening.status(self.engine)["available"])
        with self.assertRaises(UserError):
            self.one(6)
        with self.assertRaises(UserError):
            self.act("start", {"extra": True})
        self.record(6, extra=True)
        self.assertEqual(1, self.card(6)["attempts"])
        self.now += 86400
        self.assertEqual(5, listening.status(self.engine)["new_remaining"])

    def test_default_pool_avoids_due_and_next_day_and_setting_can_widen_it(self):
        assignment = self.store.related("assignment", 1)
        for due in (self.now - 1, self.now + 86400, None):
            assignment["data"]["available_at"] = stamp(due) if due else None
            self.store.put(assignment)
            with self.assertRaises(UserError):
                self.one(1)
        self.act("settings", {"avoid_due_24h": False})
        self.assertEqual("question", self.one(1)["phase"])

    def test_no_duplicate_pronunciations_and_reveal_acknowledges_homophones(self):
        self.word(9, "ヤマ", "山別")
        state = self.act("start", {"subject_ids": [1, 9]})["session"]
        self.assertEqual(1, state["total"])
        state = self.act("reveal")["session"]
        self.assertEqual(1, len(state["subject"]["alternatives"]))
        self.assertIn("Other Japanese words", state["subject"]["ambiguity_note"])

    def test_all_saved_subjects_aliases_readings_and_audio_variants_are_protected(self):
        self.protect(1, "reviews")
        self.protect(2, "lessons")
        self.word(9, "やま", "Another written word")
        self.word(10, "しろ", "山1")
        item = self.words[2]
        item["data"]["pronunciation_audios"][0]["metadata"]["pronunciation"] = "にわ"
        self.store.put(item)
        self.word(11, "にわ", "Different kana")
        for sid in (1, 2, 9, 10, 11):
            with self.subTest(sid=sid), self.assertRaises(UserError):
                self.one(sid, extra=True)
        self.assertEqual("question", self.one(3)["phase"])

    def test_new_protection_invalidates_front_reveal_and_play(self):
        front = self.one()
        self.protect(1)
        state = listening.view(self.engine)
        self.assertIsNone(state["subject"])
        self.assertIsNone(state["media_handle"])
        with self.assertRaises(UserError):
            listening.media(self.engine, front["media_handle"])
        with self.assertRaises(UserError):
            self.act("reveal")
        self.act("skip")

    def test_subscription_hidden_pending_and_reset_changes_block_reveal_and_rating(self):
        for change in ("subscription", "hidden", "pending", "reset"):
            with self.subTest(change=change):
                self.setUp_case()
                self.one()
                self.act("reveal")
                if change == "subscription":
                    user = self.store.get("user")
                    user["data"]["subscription"]["max_level_granted"] = 0
                    self.store.set("user", user)
                elif change == "hidden":
                    item = self.words[1]
                    item["data"]["hidden_at"] = stamp(self.now)
                    self.store.put(item)
                elif change == "pending":
                    self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", ("pending", "review", 1, "pending", "{}", stamp(self.now), "Authored"))
                else:
                    self.store.set("milestone_reset_generation", 1)
                self.assertIsNone(listening.view(self.engine)["subject"])
                with self.assertRaises(UserError):
                    self.act("rate", {"rating": "remembered"})

    def setUp_case(self):
        self.store.execute("DELETE FROM outbox")
        self.store.set("listening_active", None)
        self.store.set("milestone_reset_generation", 0)
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 60
        self.store.set("user", user)
        self.word(1, "やま")

    def test_restart_preserves_exact_reveal_queue_and_graded_references(self):
        self.store.set("graded_session", "authored-graded")
        self.store.set("reviews_session", "authored-review")
        self.store.set("lessons_session", "authored-lesson")
        self.act("start")
        self.act("reveal")
        before = listening.view(self.engine)
        durable = self.store.get("listening_session_" + before["id"])
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.assertEqual(before, listening.view(self.engine))
        self.assertEqual(durable, self.store.get("listening_session_" + before["id"]))
        self.assertEqual("authored-graded", self.store.get("graded_session"))
        self.assertEqual("authored-review", self.store.get("reviews_session"))
        self.assertEqual("authored-lesson", self.store.get("lessons_session"))

    def test_duplicate_rating_and_undo_do_not_repeat_effects(self):
        self.one()
        self.act("reveal")
        result = self.act("rate", {"rating": "remembered"}, key="one-rating")
        self.assertTrue(listening.command(self.engine, "one-rating", "rate", {})["duplicate"])
        self.assertEqual(1, self.card(1)["attempts"])
        self.act("undo", key="one-undo")
        self.assertTrue(listening.command(self.engine, "one-undo", "undo", {})["duplicate"])
        self.assertIsNone(self.card(1))
        state = listening.view(self.engine)
        self.assertEqual("revealed", state["phase"])
        self.assertEqual(0, state["index"])
        self.assertEqual(0, state["summary"]["remembered"])
        self.assertEqual(4, listening.status(self.engine)["new_remaining"], "Hearing the word is not undone")
        with self.assertRaises(UserError):
            self.act("undo")

    def test_transaction_failure_rolls_back_rating_schedule_history_and_journal(self):
        self.one()
        self.act("reveal")
        before = listening.view(self.engine)
        rows_before = self.store.rows("SELECT COUNT(*) FROM events")[0][0]
        original = self.store.execute
        def fail(sql, args=()):
            if sql.startswith("INSERT INTO commands"):
                raise RuntimeError("Authored interruption before durable reply")
            return original(sql, args)
        with patch.object(self.store, "execute", side_effect=fail), self.assertRaises(RuntimeError):
            self.act("rate", {"rating": "remembered"}, key="interrupted")
        self.assertEqual(before, listening.view(self.engine))
        self.assertIsNone(self.card(1))
        self.assertEqual(rows_before, self.store.rows("SELECT COUNT(*) FROM events")[0][0])
        self.assertFalse(self.store.rows("SELECT 1 FROM commands WHERE id='listening_command:interrupted'"))

    def test_stale_media_handle_and_account_change_cannot_reveal_prior_word(self):
        front = self.one()
        self.act("skip")
        self.one(2)
        with self.assertRaises(UserError):
            listening.media(self.engine, front["media_handle"])
        user = self.store.get("user")
        user["data"]["id"] = "other-account"
        self.store.set("user", user)
        self.store.set("account_id", "other-account")
        self.assertIsNone(listening.view(self.engine)["subject"])
        self.assertIsNone(listening.view(self.engine)["media_handle"])

    def test_original_owned_media_only_and_voice_change_does_not_make_new_card(self):
        self.media_dir.joinpath("1.mp3").unlink()
        self.media_dir.joinpath("1.mp3").symlink_to(self.media_dir / "2.mp3")
        with self.assertRaises(UserError):
            self.one()
        self.record(2)
        self.engine.set_settings({"voice_actor_id": 2})
        self.record(2)
        self.assertEqual(2, self.card(2)["attempts"])

    def test_every_action_stays_local_and_independent_of_graded_activity(self):
        before = [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")]
        self.record()
        self.act("undo")
        self.act("skip")
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM sessions"))
        kinds = {row[0] for row in self.store.rows("SELECT DISTINCT kind FROM events")}
        self.assertEqual({"listening_result", "listening_undo"}, kinds)
        journal = [row[0] for row in self.store.rows("SELECT body FROM commands")]
        self.assertFalse(any("Authored meaning" in row or "pronunciation" in row for row in journal))

    def test_other_reading_cannot_leak_a_protected_answer_after_reveal(self):
        self.protect(1)
        subject = self.words[2]
        subject["data"]["readings"].append({"reading": "やま", "accepted_answer": True})
        self.store.put(subject)
        with self.assertRaises(UserError):
            self.one(2, extra=True)
        self.word(9, "そら", characters="やま", kind="kana_vocabulary")
        with self.assertRaises(UserError):
            self.one(9, extra=True)

    def test_resuming_an_unavailable_card_preserves_position_and_offers_skip(self):
        before = self.one()
        self.media_dir.joinpath("1.mp3").unlink()
        resumed = self.act("start")["session"]
        self.assertEqual(before["id"], resumed["id"])
        self.assertEqual(before["revision"], resumed["revision"])
        self.assertIn("unavailable", resumed)
        self.assertIsNone(resumed["subject"])
        self.assertEqual("complete", self.act("skip")["session"]["phase"])

    def test_malformed_state_and_assignment_types_fail_safely(self):
        for value in (0, True, "5", None):
            assignment = self.store.related("assignment", 1)
            assignment["data"]["srs_stage"] = value
            self.store.put(assignment)
            with self.subTest(stage=value), self.assertRaises(UserError):
                self.one()
        self.word(1, "やま")
        state = self.one()
        with self.assertRaises(UserError):
            self.act("reveal", {"revision": True})
        with self.assertRaises(UserError):
            self.act("start", {"replace": "yes"})
        self.store.set("listening_session_" + state["id"], {"id": state["id"], "queue": 1})
        with self.assertRaises(UserError):
            listening.view(self.engine)
        replacement = self.one(replace=True)
        self.assertNotEqual(state["id"], replacement["id"])
        self.store.set(listening._card_key(listening._context(self.engine), 1), {"step": "bad"})
        with self.assertRaises(UserError):
            listening.status(self.engine)

    def test_clock_change_blocks_intervals_without_losing_the_saved_card(self):
        before = self.one()
        card_key = listening._card_key(listening._context(self.engine), 1)
        self.engine.clock_untrusted = True
        with self.assertRaises(UserError):
            listening.media(self.engine, before["media_handle"])
        with self.assertRaises(UserError):
            self.act("reveal")
        self.assertIsNone(listening.view(self.engine)["subject"])
        self.assertIsNone(self.store.get(card_key))
        self.engine.clock_untrusted = False
        self.assertEqual(before, listening.view(self.engine))

    def test_candidate_budget_is_explicit_and_protection_is_fail_closed(self):
        with patch.object(listening, "MAX_CANDIDATES", 2):
            status = listening.status(self.engine)
        self.assertFalse(status["complete"])
        self.assertEqual(2, status["eligible"])
        self.store.execute("INSERT INTO sessions VALUES(?,?)", ("broken", json.dumps({"mode": "reviews", "phase": "question", "queue": None})))
        with self.assertRaises(UserError):
            self.act("start", {"subject_ids": [3], "extra": True})

    def test_actual_process_death_before_and_after_rating_commit(self):
        self.one()
        self.act("reveal")
        before = listening.view(self.engine)
        program = """
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from wanikani.store import Store
from wanikani.engine import Engine
from wanikani import listening
store=Store(Path(sys.argv[2])); engine=Engine(store,clock=lambda:float(sys.argv[3]))
state=listening.view(engine)
if sys.argv[4]=='before':
    original=store.execute
    def interrupted(sql,args=()):
        if sql.startswith('INSERT INTO commands'): os._exit(71)
        return original(sql,args)
    store.execute=interrupted
listening.command(engine,'actual-crash-rating','rate',{'rating':'remembered','session_id':state['id'],'revision':state['revision']})
os._exit(72)
"""
        args = [sys.executable, "-c", program, str(Path(__file__).resolve().parents[1] / "backend"), str(self.path), str(self.now)]
        crashed = subprocess.run(args + ["before"], capture_output=True, text=True, timeout=10)
        self.assertEqual(71, crashed.returncode, crashed.stderr)
        self.assertEqual(before, listening.view(self.engine))
        self.assertIsNone(self.card(1))
        self.assertFalse(self.store.rows("SELECT 1 FROM commands WHERE id='listening_command:actual-crash-rating'"))
        committed = subprocess.run(args + ["after"], capture_output=True, text=True, timeout=10)
        self.assertEqual(72, committed.returncode, committed.stderr)
        self.assertEqual("complete", listening.view(self.engine)["phase"])
        self.assertEqual(1, self.card(1)["attempts"])
        self.assertTrue(listening.command(self.engine, "actual-crash-rating", "rate", {})["duplicate"])
        self.assertEqual(1, self.card(1)["attempts"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))


if __name__ == "__main__":
    unittest.main()
