"""Authored cached clips; completion tokens simulate a player, never live audio."""
import copy
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import test_listening as authored
from wanikani import dictation, listening
from wanikani.common import UserError, epoch
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani.media_plan import build


class DictationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.ListeningTests()
        self.fixture.setUp()
        self.engine, self.store, self.path = self.fixture.engine, self.fixture.store, self.fixture.path

    def tearDown(self):
        self.fixture.tearDown()

    def only(self, sid=1):
        self.store.execute("DELETE FROM media WHERE url!=?", (self.fixture.words[sid]["data"]["pronunciation_audios"][0]["url"],))

    def act(self, action, args=None, operation=None):
        values = dict(args or {})
        if action != "start":
            state = dictation.view(self.engine)
            values = {"session_id": state["id"], "revision": state["revision"], **values}
        return dictation.command(self.engine, operation or uuid.uuid4().hex, action, values)["session"]

    def start(self, single=True, **args):
        if single:
            self.only()
        return self.act("start", args)

    def entry(self):
        session = dictation._session(self.engine)
        return session["queue"][session["index"]]

    def play(self, complete=True):
        state = dictation.view(self.engine)
        result = dictation.media(self.engine, state["media_handle"])
        if complete:
            self.act("heard", {"handle": result["handle"], "playback_token": result["playback_token"]})
        return result

    def check(self, text=None):
        return self.act("check", {"text": self.entry()["pronunciation"] if text is None else text})

    def record(self, text=None):
        self.start()
        self.play()
        self.check(text)
        return self.act("continue")

    def card(self, sid=1):
        return self.store.get(dictation._card_key(dictation._context(self.engine), sid))

    def protected_state(self):
        return {table: [tuple(row) for row in self.store.rows("SELECT * FROM " + table + " ORDER BY 1")]
            for table in ("resources", "sessions", "outbox")}

    def test_front_media_and_heard_never_expose_expected_kana_or_notes(self):
        self.store.put({"id": 99, "object": "study_material", "data": {"subject_id": 1,
            "meaning_synonyms": [], "meaning_note": "PRIVATE NOTE", "reading_note": "PRIVATE READING"}})
        self.start()
        for value in (dictation.view(self.engine), self.play(), dictation.view(self.engine), dictation.status(self.engine)):
            encoded = json.dumps(value, ensure_ascii=False)
            for secret in ("やま", "山1", "Authored meaning", "PRIVATE", "subject_id"):
                self.assertNotIn(secret, encoded)
        self.assertTrue(dictation.view(self.engine)["heard"])
        feedback = self.check()
        self.assertEqual("やま", feedback["feedback"]["recorded"])
        self.assertEqual("PRIVATE NOTE", feedback["subject"]["material"]["meaning_note"])

    def test_check_requires_current_completed_playback_not_just_media_delivery(self):
        self.start()
        with self.assertRaises(UserError):
            self.check()
        issued = self.play(complete=False)
        with self.assertRaises(UserError):
            self.check()
        later = self.play(complete=False)
        with self.assertRaises(UserError):
            self.act("heard", {"handle": issued["handle"], "playback_token": issued["playback_token"]})
        self.assertFalse(dictation.view(self.engine)["heard"])
        self.act("heard", {"handle": later["handle"], "playback_token": later["playback_token"]})
        with self.assertRaises(UserError):
            self.act("heard", {"handle": later["handle"], "playback_token": later["playback_token"]})
        self.play(complete=False)
        self.assertTrue(self.check()["feedback"]["matched"], "An earlier full hearing of this same pinned clip remains valid")

    def test_exposure_once_before_playback_is_independent_of_meaning_listening(self):
        self.start()
        self.assertEqual(5, dictation.status(self.engine)["new_remaining"])
        self.play(complete=False)
        self.assertEqual(4, dictation.status(self.engine)["new_remaining"])
        self.assertEqual(5, listening.status(self.engine)["new_remaining"])
        self.play()
        self.assertEqual(4, dictation.status(self.engine)["new_remaining"])
        self.assertIsNone(self.card())
        self.assertEqual([], self.store.rows("SELECT * FROM events WHERE kind='dictation_result'"))

    def test_missing_failed_or_interrupted_recording_never_creates_a_result(self):
        self.start()
        issued = self.play(complete=False)
        (self.fixture.media_dir / "1.mp3").unlink()
        with self.assertRaises(UserError):
            self.act("heard", {"handle": issued["handle"], "playback_token": issued["playback_token"]})
        with self.assertRaises(UserError):
            self.check()
        self.assertIsNone(dictation.view(self.engine)["subject"])
        self.assertIsNone(self.card())
        self.assertEqual("complete", self.act("skip")["phase"])
        self.assertEqual(4, dictation.status(self.engine)["new_remaining"])

    def test_check_persists_feedback_but_only_continue_commits_interval_and_result(self):
        self.start(); self.play()
        feedback = self.check()
        self.assertEqual("feedback", feedback["phase"])
        self.assertEqual({"matched_days": 1, "again_minutes": 10}, feedback["intervals"])
        self.assertIsNone(self.card())
        self.assertEqual([], self.store.rows("SELECT * FROM events"))
        self.assertEqual(0, sum(feedback["summary"].values()))
        completed = self.act("continue")
        self.assertEqual("complete", completed["phase"])
        self.assertEqual({"matched": 1, "again": 0, "skipped": 0}, completed["summary"])
        self.assertEqual(self.fixture.now + 86400, epoch(self.card()["next_at"]))
        self.assertEqual(1, self.card()["attempts"])

    def test_exact_canonical_kana_keeps_small_kana_and_vowel_spelling_significant(self):
        cases = [("がっこう", "ガッコウ", True), ("がっこう", "ｶﾞｯｺｳ", True),
            ("がっこう", "か\u3099っこう", True), ("がっこう", "がこう", False),
            ("きゃく", "きやく", False), ("こーひー", "コーヒー", True),
            ("こーひー", "こおひい", False), ("とうきょう", "とおきょお", False),
            ("は", "わ", False), ("ん", "ン", True)]
        for expected, text, matched in cases:
            with self.subTest(expected=expected, text=text):
                self.fixture.word(1, expected)
                self.start(replace=True); self.play()
                feedback = self.check(text)
                self.assertEqual(matched, feedback["feedback"]["matched"])
                self.assertEqual(expected, feedback["feedback"]["recorded"])
                self.act("skip")
                self.assertIsNone(self.card())

    def test_subject_alternate_reading_is_not_an_answer_for_a_different_clip(self):
        word = self.fixture.words[1]
        word["data"]["readings"].append({"reading": "やめ", "accepted_answer": True})
        self.store.put(word)
        self.start(); self.play()
        self.assertFalse(self.check("やめ")["feedback"]["matched"])
        self.assertEqual("やま", dictation.view(self.engine)["subject"]["pronunciation"])

    def test_empty_romaji_and_kanji_are_retryable_without_revealing_word(self):
        self.start(); self.play()
        for text in ("", " ", "n", "yama", "山", "や ま"):
            with self.subTest(text=text):
                state = self.check(text)
                self.assertEqual("question", state["phase"])
                self.assertEqual(text, state["draft"])
                self.assertTrue(state["input_error"])
                self.assertIsNone(state["subject"])
                self.assertIsNone(state["feedback"])
                self.assertIsNone(self.card())
        self.assertTrue(self.check("やま")["feedback"]["matched"])

    def test_draft_has_small_ack_no_structural_revision_or_command_rows(self):
        state = self.start()
        before = self.store.rows("SELECT COUNT(*) FROM commands")[0][0]
        text = "や𠮷n"
        ack = dictation.draft(self.engine, state["id"], state["media_handle"], text, 3, "か")
        self.assertEqual({"saved", "session_id", "handle", "draft_revision"}, set(ack))
        saved = dictation.view(self.engine)
        self.assertEqual(state["revision"], saved["revision"])
        self.assertEqual((text, 3, "か", 1), (saved["draft"], saved["draft_cursor"], saved["preedit"], saved["draft_revision"]))
        self.assertEqual(before, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])
        with self.assertRaises(UserError):
            dictation.draft(self.engine, state["id"], state["media_handle"], text, 2)
        other = Store(self.path)
        try:
            restarted = Engine(other, clock=lambda: self.fixture.now)
            self.assertEqual(saved, dictation.view(restarted))
        finally:
            other.close()

    def test_stale_draft_for_previous_card_or_feedback_is_rejected(self):
        state = self.start(single=False)
        self.act("skip")
        with self.assertRaises(UserError):
            dictation.draft(self.engine, state["id"], state["media_handle"], "old", 3)
        current = dictation.view(self.engine)
        self.play(); self.check()
        with self.assertRaises(UserError):
            dictation.draft(self.engine, current["id"], current["media_handle"], "old", 3)

    def test_check_includes_final_text_and_does_not_grade_preedit(self):
        state = self.start(); self.play()
        dictation.draft(self.engine, state["id"], state["media_handle"], "やn", 2, "山")
        state = self.check("やま")
        self.assertEqual("やま", state["draft"])
        self.assertEqual("", state["preedit"])
        self.assertTrue(state["feedback"]["matched"])

    def test_undo_restores_only_immediate_result_and_keeps_heard_exposure(self):
        self.record()
        before = dictation.status(self.engine)["new_remaining"]
        undo = self.act("undo")
        self.assertEqual("feedback", undo["phase"])
        self.assertTrue(undo["heard"])
        self.assertTrue(undo["feedback"]["matched"])
        self.assertEqual({"matched": 0, "again": 0, "skipped": 0}, undo["summary"])
        self.assertIsNone(self.card())
        self.assertEqual(before, dictation.status(self.engine)["new_remaining"])
        with self.assertRaises(UserError):
            self.act("undo")
        self.act("continue")
        self.assertEqual(1, self.card()["attempts"])

    def test_skip_feedback_is_ungraded_and_expires_the_previous_undo(self):
        self.start(single=False); self.play(); self.check(); self.act("continue")
        sid = dictation._session(self.engine)["queue"][0]["subject_id"]
        self.play(); self.check("べつ")
        skipped = self.act("skip")
        self.assertFalse(skipped["undo_available"])
        self.assertEqual(1, self.card(sid)["attempts"])
        self.assertEqual({"matched": 1, "again": 0, "skipped": 1}, skipped["summary"])
        with self.assertRaises(UserError):
            self.act("undo")

    def test_all_actions_keep_meaning_session_and_graded_state_byte_identical(self):
        self.fixture.one(2)
        meaning = [tuple(row) for row in self.store.rows("SELECT * FROM meta WHERE key LIKE 'listening_%' ORDER BY key")]
        protected = self.protected_state()
        with patch.object(self.engine, "command", side_effect=AssertionError("No graded engine command")), patch.object(self.engine, "advance", side_effect=AssertionError("No graded advance")):
            self.record("べつ"); self.act("undo"); self.act("skip")
        self.assertEqual(meaning, [tuple(row) for row in self.store.rows("SELECT * FROM meta WHERE key LIKE 'listening_%' ORDER BY key")])
        self.assertEqual(protected, self.protected_state())
        self.assertEqual({"dictation_result", "dictation_undo"}, {row[0] for row in self.store.rows("SELECT DISTINCT kind FROM events")})
        for row in self.store.rows("SELECT body FROM commands WHERE id LIKE 'dictation_%'"):
            self.assertEqual({"dictation_operation"}, set(json.loads(row[0])))

    def test_five_new_dictation_words_do_not_use_meaning_allowance(self):
        self.start(single=False)
        for _ in range(5):
            self.play(complete=False); self.act("skip")
        self.assertEqual(0, dictation.status(self.engine)["new_remaining"])
        self.assertEqual(5, listening.status(self.engine)["new_remaining"])
        # Skipping changes no interval. Already introduced words remain safe
        # to revisit; only a sixth NEW word is withheld by the daily allowance.
        self.assertEqual(5, dictation.status(self.engine)["available"])
        introduced = dictation._day(self.engine, dictation._context(self.engine))[1]
        self.act("start")
        self.assertEqual(introduced, {entry["subject_id"] for entry in dictation._session(self.engine)["queue"]})
        self.fixture.now += 86400
        self.assertEqual(5, dictation.status(self.engine)["new_remaining"])
        self.assertGreater(dictation.status(self.engine)["available"], 0)

    def test_undo_remains_available_when_only_next_recording_disappears(self):
        self.start(single=False)
        self.play()
        self.check()
        previous = copy.deepcopy(self.entry())
        current = self.act("continue")
        next_entry = copy.deepcopy(self.entry())
        self.store.execute("DELETE FROM media WHERE url=?", (next_entry["url"],))
        unavailable = dictation.view(self.engine)
        self.assertIn("unavailable", unavailable)
        self.assertTrue(unavailable["undo_available"])
        self.assertIsNone(unavailable["subject"])
        self.assertIsNone(unavailable["feedback"])
        self.assertEqual("feedback", self.act("undo")["phase"])
        self.assertEqual(previous["handle"], self.entry()["handle"])
        self.assertIsNone(self.store.get(dictation._card_key(dictation._context(self.engine), previous["subject_id"])))

    def test_undo_is_withheld_if_previous_recording_or_access_is_lost(self):
        self.start(single=False)
        self.play()
        self.check()
        previous = copy.deepcopy(self.entry())
        self.act("continue")
        self.store.execute("DELETE FROM media WHERE url=?", (previous["url"],))
        self.assertFalse(dictation.view(self.engine)["undo_available"])
        with self.assertRaises(UserError):
            self.act("undo")

    def test_loaded_queue_rejects_duplicate_subject_handles_or_sounds_without_repair(self):
        self.start(single=False)
        original = copy.deepcopy(dictation._session(self.engine))
        key = "dictation_session_" + original["id"]
        for field in ("subject_id", "handle", "pronunciation"):
            with self.subTest(field=field):
                value = copy.deepcopy(original)
                value["queue"][1][field] = value["queue"][0][field]
                self.store.set(key, value)
                before = list(self.store.db.iterdump())
                with self.assertRaises(UserError) as error:
                    dictation.view(self.engine)
                self.assertEqual("dictation_state", error.exception.code)
                self.assertEqual(before, list(self.store.db.iterdump()))
        self.store.set(key, original)

    def test_dictation_pool_reads_its_own_intervals_and_preserves_listening_default(self):
        self.only()
        self.fixture.record(1)
        self.assertEqual(0, listening.status(self.engine)["available"])
        self.assertEqual(1, dictation.status(self.engine)["available"])
        meaning_record = copy.deepcopy(self.fixture.card(1))
        self.record()
        self.assertEqual(0, dictation.status(self.engine)["available"])
        self.assertEqual(meaning_record, self.fixture.card(1))

    def test_local_interval_ladder_and_again_do_not_expand_batch(self):
        for days in (1, 3, 7, 14, 30, 30):
            self.record()
            self.assertEqual(self.fixture.now + days * 86400, epoch(self.card()["next_at"]))
            self.fixture.now += days * 86400 + 1
        final = self.record("べつ")
        self.assertEqual("complete", final["phase"])
        self.assertEqual(self.fixture.now + 600, epoch(self.card()["next_at"]))
        self.assertEqual(-1, self.card()["step"])

    def test_protection_added_after_check_hides_all_answer_and_draft_content(self):
        self.start(); self.play(); self.check()
        private = self.store.get("dictation_session_" + self.store.get("dictation_active"))
        self.fixture.protect(1)
        state = dictation.view(self.engine)
        for key in ("subject", "feedback", "media_handle", "intervals"):
            self.assertIsNone(state[key])
        self.assertEqual("", state["draft"])
        self.assertEqual(private, self.store.get("dictation_session_" + private["id"]))
        with self.assertRaises(UserError):
            self.act("continue")
        self.assertEqual("complete", self.act("skip")["phase"])
        self.assertIsNone(self.card())

    def test_aliases_sounds_and_unresolved_graded_work_exclude_automatic_candidates(self):
        self.fixture.protect(2)
        self.only()
        for field, value in (("characters", self.fixture.words[2]["data"]["characters"]), ("reading", "かわ"), ("audio", "かわ")):
            original = copy.deepcopy(self.fixture.words[1])
            word = copy.deepcopy(original)
            if field == "characters": word["data"]["characters"] = value
            elif field == "reading": word["data"]["readings"].append({"reading": value, "accepted_answer": True})
            else: word["data"]["pronunciation_audios"][0]["metadata"]["pronunciation"] = value
            self.store.put(word)
            with self.subTest(field=field): self.assertEqual(0, dictation.status(self.engine)["available"])
            self.store.put(original)
        for state in ("pending", "inflight", "uncertain", "blocked", "conflicted"):
            self.store.execute("INSERT OR REPLACE INTO outbox VALUES(?,?,?,?,?,?,?)", ("pending", "review", 1, state, "{}", authored.stamp(self.fixture.now), ""))
            with self.subTest(state=state): self.assertEqual(0, dictation.status(self.engine)["available"])

    def test_reset_or_data_epoch_cannot_resume_old_dictation_but_keeps_record(self):
        state = self.start(); self.play(); self.check()
        private = self.store.get("dictation_session_" + state["id"])
        self.store.set("milestone_reset_generation", 1)
        hidden = dictation.view(self.engine)
        self.assertIn("unavailable", hidden)
        self.assertIsNone(hidden["subject"])
        replacement = self.act("start")
        self.assertNotEqual(state["id"], replacement["id"])
        self.assertEqual(private, self.store.get("dictation_session_" + state["id"]))
        self.store.set("session_epoch", uuid.uuid4().hex)
        self.assertIsNone(dictation.view(self.engine)["media_handle"])

    def test_duplicate_check_continue_and_undo_never_repeat_effects(self):
        self.start(); self.play()
        state = dictation.view(self.engine)
        args = {"session_id": state["id"], "revision": state["revision"], "text": "やま"}
        dictation.command(self.engine, "check-once", "check", args)
        self.assertTrue(dictation.command(self.engine, "check-once", "check", args)["duplicate"])
        state = dictation.view(self.engine)
        args = {"session_id": state["id"], "revision": state["revision"]}
        dictation.command(self.engine, "continue-once", "continue", args)
        self.assertTrue(dictation.command(self.engine, "continue-once", "continue", args)["duplicate"])
        state = dictation.view(self.engine)
        undo = {"session_id": state["id"], "revision": state["revision"]}
        dictation.command(self.engine, "undo-once", "undo", undo)
        self.assertTrue(dictation.command(self.engine, "undo-once", "undo", undo)["duplicate"])
        self.assertIsNone(self.card())
        self.assertEqual(2, self.store.rows("SELECT COUNT(*) FROM events")[0][0])
        self.assertEqual("feedback", dictation.command(self.engine, "check-once", "check", args | {"text": "old"})["session"]["phase"])

    def test_malformed_requests_drafts_and_state_fail_without_writes(self):
        self.start()
        before = self.store.db.total_changes
        for action, args in (("start", {"subject_ids": [1]}), ("start", {"replace": 1}), ("check", {}), ("check", {"session_id": "a", "revision": True, "text": "a"}), ("heard", {"session_id": "a", "revision": 1, "handle": "a", "playback_token": "a", "url": "https://private"})):
            with self.subTest(action=action, args=args), self.assertRaises(UserError):
                dictation.command(self.engine, "bad", action, args)
        state = dictation.view(self.engine)
        for text, cursor, preedit in (("x" * 257, 0, ""), ("a", True, ""), ("a", 2, ""), ("\ud800", 0, ""), ("a", 0, "x" * 257)):
            with self.assertRaises(UserError): dictation.draft(self.engine, state["id"], state["media_handle"], text, cursor, preedit)
        self.assertEqual(before, self.store.db.total_changes)
        original = dictation._session(self.engine)
        for change in ("queue", "pronunciation", "undo", "cursor"):
            broken = copy.deepcopy(original)
            if change == "queue": broken["queue"] *= 10
            if change == "pronunciation": broken["queue"][0]["pronunciation"] = None
            if change == "undo": broken["undo"] = {"index": 999}
            if change == "cursor": broken["queue"][0]["cursor"] = True
            self.store.set("dictation_session_" + original["id"], broken)
            with self.subTest(change=change), self.assertRaises(UserError): dictation.view(self.engine)
            self.assertEqual({}, dictation.retained_urls(self.engine))
        self.store.set("dictation_session_" + original["id"], original)

    def test_changed_voice_does_not_replace_pinned_clip_or_expected_answer(self):
        self.start()
        word = copy.deepcopy(self.fixture.words[1]); clip = copy.deepcopy(word["data"]["pronunciation_audios"][0])
        clip["url"] += "-alternate"; clip["metadata"].update(voice_actor_id=2, pronunciation="やめ")
        word["data"]["pronunciation_audios"].append(clip)
        self.store.put(word); self.engine.set_settings({"voice_actor_id": 2})
        issued = self.play()
        self.assertTrue(issued["uri"].endswith("/1.mp3"))
        self.assertEqual("やま", self.check()["feedback"]["recorded"])
        word["data"]["pronunciation_audios"][0]["metadata"]["pronunciation"] = "やも"
        self.store.put(word)
        self.assertIsNone(dictation.view(self.engine)["subject"])
        with self.assertRaises(UserError): self.act("continue")

    def test_both_active_queues_and_undo_clip_keep_normal_budget_priority(self):
        self.fixture.one(2)
        self.start()
        # Restore the second cached row, which the single-candidate fixture hid.
        self.fixture.word(2, "かわ")
        plan = build(self.engine, self.fixture.media_dir)
        url1 = self.entry()["url"]
        url2 = self.fixture.words[2]["data"]["pronunciation_audios"][0]["url"]
        self.assertEqual((2, 0, 0), plan.priority(url1))
        self.assertEqual((2, 0, 0), plan.priority(url2))
        self.play(); self.check(); self.act("continue")
        self.assertEqual({url1: 0}, dictation.retained_urls(self.engine))
        self.act("undo"); self.act("skip")
        self.assertEqual({}, dictation.retained_urls(self.engine))

    def test_clock_access_and_missing_recording_invalidate_retention_safely(self):
        self.start(); self.play(); self.check()
        for edge in ("clock", "grant", "hidden", "missing"):
            with self.subTest(edge=edge):
                user = self.store.get("user"); word = copy.deepcopy(self.fixture.words[1])
                if edge == "clock": self.engine.clock_untrusted = True
                if edge == "grant": user["data"]["subscription"]["max_level_granted"] = 0; self.store.set("user", user)
                if edge == "hidden": word["data"]["hidden_at"] = authored.stamp(self.fixture.now); self.store.put(word)
                if edge == "missing": (self.fixture.media_dir / "1.mp3").unlink()
                self.assertEqual({}, dictation.retained_urls(self.engine))
                self.assertIsNone(dictation.view(self.engine)["subject"])
                self.engine.clock_untrusted = False
                user["data"]["subscription"]["max_level_granted"] = 60; self.store.set("user", user)
                self.fixture.word(1, "やま")

    def test_actual_crash_before_and_after_check_continue_and_undo(self):
        self.start(); self.play()
        program = r'''
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from wanikani.store import Store
from wanikani.engine import Engine
from wanikani import dictation
store=Store(Path(sys.argv[2]));engine=Engine(store,clock=lambda:float(sys.argv[3]))
state=dictation.view(engine); action=sys.argv[4]
if sys.argv[5]=='before':
 original=store.execute
 def interrupted(sql,args=()):
  if sql.startswith('INSERT INTO commands'):os._exit(71)
  return original(sql,args)
 store.execute=interrupted
values={'session_id':state['id'],'revision':state['revision']}
if action=='check':values['text']='やま'
dictation.command(engine,'crash-'+action,action,values)
os._exit(72)
'''
        command = [sys.executable, "-B", "-c", program, str(Path(__file__).resolve().parents[1] / "backend"), str(self.path), str(self.fixture.now)]
        for action in ("check", "continue", "undo"):
            before = dictation.view(self.engine)
            record = copy.deepcopy(self.card())
            result = subprocess.run(command + [action, "before"], capture_output=True, text=True, timeout=10)
            self.assertEqual(71, result.returncode, result.stderr)
            self.assertEqual(before, dictation.view(self.engine))
            self.assertEqual(record, self.card())
            result = subprocess.run(command + [action, "after"], capture_output=True, text=True, timeout=10)
            self.assertEqual(72, result.returncode, result.stderr)
            self.assertTrue(self.store.rows("SELECT 1 FROM commands WHERE id=?", ("dictation_command:crash-" + action,)))
            if action == "check": self.assertIsNone(self.card())
            elif action == "continue": self.assertEqual(1, self.card()["attempts"])
            else: self.assertIsNone(self.card())

    def test_actual_crash_rolls_back_or_preserves_final_draft_without_command_growth(self):
        state = self.start()
        program = r'''
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from wanikani.store import Store
from wanikani.engine import Engine
from wanikani import dictation
store=Store(Path(sys.argv[2]));engine=Engine(store,clock=lambda:float(sys.argv[3]));state=dictation.view(engine)
if sys.argv[4]=='before':
 original=store.execute
 def interrupted(sql,args=()):
  if args and args[0]=='dictation_active':os._exit(71)
  return original(sql,args)
 store.execute=interrupted
dictation.draft(engine,state['id'],state['media_handle'],'やn',2,'か')
os._exit(72)
'''
        command = [sys.executable, "-B", "-c", program, str(Path(__file__).resolve().parents[1] / "backend"), str(self.path), str(self.fixture.now)]
        count = self.store.rows("SELECT COUNT(*) FROM commands")[0][0]
        for boundary, code in (("before", 71), ("after", 72)):
            result = subprocess.run(command + [boundary], capture_output=True, text=True, timeout=10)
            self.assertEqual(code, result.returncode, result.stderr)
            saved = dictation.view(self.engine)
            self.assertEqual("" if boundary == "before" else "やn", saved["draft"])
            self.assertEqual(state["revision"], saved["revision"])
            self.assertEqual(count, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])


if __name__ == "__main__":
    unittest.main()
