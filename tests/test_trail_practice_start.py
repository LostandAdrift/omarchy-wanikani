"""Atomic passage practice and replay, using only authored local study data."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import test_reading_trail as authored
from wanikani import session_report, trail, trail_practice
from wanikani.common import UserError, stamp
from wanikani.command_codec import decode
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from worker import Worker


class TrailPracticeStartTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored.ReadingTrailTests(); self.fixture.setUp()
        self.engine, self.store = self.fixture.engine, self.fixture.store
        self.store.set("account_id", "demo")

    def tearDown(self):
        self.fixture.store = self.store
        self.fixture.tearDown()

    def dump(self):
        return list(self.store.db.iterdump())

    def args(self, text="山と火山。ありがとう", ids=None, replace=False):
        ids = [2, 8, 5] if ids is None else ids
        preview = trail_practice.preview(self.engine, text, ids)
        return {"text": text, "subject_ids": ids, "expected_data_epoch": preview["data_epoch"],
            "expected_saved_practice_revision": preview["saved_practice"]["revision"], "replace_existing": replace}

    def start(self, args=None, rid="trail-start"):
        return self.engine.command(rid, "trail_practice_start", self.args() if args is None else args)

    def protect(self, sid, mode="reviews", activate=False):
        session = {"id": str(uuid4()), "mode": mode, "phase": "question", "index": 0,
            "completed": 0, "part": "meaning", "lesson_index": 0, "draft": "PRIVATE GRADED DRAFT",
            "overrides": 1, "started_at": stamp(authored.NOW), "ended_at": None, "feedback": None,
            "queue": [{"subject_id": sid, "done": False, "parts": {"meaning": False, "reading": True},
                "errors": {"meaning": 2, "reading": 1}}]}
        self.store.save_session(session, activate=activate)
        return session

    def unchanged_failure(self, args, code=None, rid="rejected-start"):
        before = self.dump()
        with self.assertRaises(UserError) as caught:
            self.start(args, rid)
        if code: self.assertEqual(code, caught.exception.code)
        self.assertEqual(before, self.dump())

    def test_explicit_selection_commits_only_new_practice_and_never_stores_passage(self):
        graded = [self.protect(3, "reviews"), self.protect(6, "lessons")]
        old = self.engine.start("practice", 1, [4], replace_practice=True)
        self.engine.draft("OLD PRACTICE DRAFT")
        saved = {item["id"]: self.store.session(item["id"]) for item in graded + [old]}
        refs = {name: self.store.get(name) for name in ("reviews_session", "lessons_session", "graded_session")}
        resources = [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")]
        passage = "PRIVATE PASSAGE\n山と火山。ありがとう🌊"
        result = self.start(self.args(passage, [8, 2, 5], replace=True))
        self.assertEqual("practice", result["mode"]); self.assertEqual(3, result["total"])
        self.assertEqual("reading_trail", result["practice_source"])
        self.assertEqual(self.store.get("session_epoch"), result["practice_data_epoch"])
        self.assertEqual({8, 2, 5}, {entry["subject_id"] for entry in self.store.session()["queue"]})
        for sid, value in saved.items(): self.assertEqual(value, self.store.session(sid))
        for key, value in refs.items(): self.assertEqual(value, self.store.get(key))
        self.assertEqual(resources, [tuple(row) for row in self.store.rows("SELECT * FROM resources ORDER BY kind,id")])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual([], self.store.rows("SELECT * FROM events"))
        reply = decode(self.store.rows("SELECT body FROM commands WHERE id='trail-start'")[0][0])
        self.assertEqual(result, reply)
        for value in (reply, self.store.session()): self.assertNotIn(passage, json.dumps(value, ensure_ascii=False))
        self.assertNotIn("trail_practice_context", reply); self.assertNotIn("account_id", reply)

    def test_generic_deliberate_practice_keeps_its_existing_policy(self):
        self.protect(2)
        result = self.engine.start("practice", 1, [2], replace_practice=True)
        self.assertEqual(2, result["subject"]["id"])
        self.assertNotIn("practice_source", result)
        self.assertEqual("feedback", self.engine.answer("wrong")["phase"])

    def test_pending_completed_graded_work_does_not_block_ungraded_selection(self):
        for sid, state in ((2, "pending"), (8, "uncertain")):
            self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (str(sid), "review", sid,
                state, "{}", stamp(authored.NOW), "PRIVATE RECOVERY NOTE"))
        before = [tuple(row) for row in self.store.rows("SELECT * FROM outbox")]
        result = self.start()
        self.assertEqual(3, result["total"])
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM outbox")])

    def test_exact_fields_types_epoch_and_selection_are_not_coerced(self):
        valid = self.args()
        variants = [{**valid, "extra": True}, {key: value for key, value in valid.items() if key != "replace_existing"}]
        for key, values in {"replace_existing": [1, "false", None],
                "expected_data_epoch": [None, "", str(uuid4()).upper(), True],
                "expected_saved_practice_revision": [True, -1, 1.2, "1", 9007199254740992],
                "subject_ids": [[], [True], [2, 2], ["2"], list(range(1, 22))],
                "text": [None, "", "𠮷" * 257, "\ud800"]}.items():
            variants.extend({**valid, key: value} for value in values)
        for index, args in enumerate(variants):
            with self.subTest(index=index): self.unchanged_failure(args, "invalid_request")
        self.unchanged_failure({**valid, "subject_ids": [3]}, "trail_changed")

    def test_existing_practice_requires_current_revision_and_explicit_replacement(self):
        self.engine.start("practice", 1, [4], replace_practice=True)
        current = self.args()
        self.unchanged_failure(current, "practice_choice_required")
        self.engine.draft("NEWER SAVED ANSWER")
        self.unchanged_failure({**current, "replace_existing": True}, "practice_changed")
        result = self.start(self.args(replace=True))
        self.assertEqual("reading_trail", result["practice_source"])

    def test_new_or_damaged_practice_since_preview_cannot_be_silently_replaced(self):
        old = self.args()
        self.engine.start("practice", 1, [4], replace_practice=True)
        self.unchanged_failure({**old, "replace_existing": True}, "practice_changed")
        self.store.set("practice_session", "missing-authored-session")
        self.unchanged_failure(old, "practice_changed")

    def test_completed_saved_practice_needs_no_replacement_choice(self):
        self.engine.start("practice", 1, [5], replace_practice=True)
        self.engine.answer("thank you"); self.engine.advance()
        args = self.args()
        self.assertIsNone(args["expected_saved_practice_revision"])
        self.assertEqual(3, self.start(args)["total"])

    def test_preview_is_revalidated_after_epoch_account_content_and_access_changes(self):
        original = self.args()
        self.store.set("session_epoch", str(uuid4()))
        self.unchanged_failure(original, "trail_changed")
        self.store.set("session_epoch", original["expected_data_epoch"])
        self.store.set("account_id", "another-account")
        self.unchanged_failure(original, "account_mismatch")
        self.store.set("account_id", "demo")
        original_subject = self.store.subject(2)
        for change in ({"characters": "岳"}, {"hidden_at": "hidden"}, {"level": 61}):
            subject = copy.deepcopy(original_subject); subject["data"].update(change); self.store.put(subject)
            with self.subTest(change=change): self.unchanged_failure(original)
        self.store.put(original_subject)
        assignment = self.store.related("assignment", 2); assignment["data"]["hidden"] = True; self.store.put(assignment)
        self.unchanged_failure(original)

    def test_new_paused_original_or_alias_blocks_start_without_touching_sessions(self):
        for alias in (False, True):
            args = self.args()
            sid = 2
            if alias:
                self.fixture.add(1001, "山"); sid = 1001
            session = self.protect(sid, mode="lessons")
            with self.subTest(alias=alias): self.unchanged_failure(args, "protected_study")
            self.store.execute("DELETE FROM sessions WHERE id=?", (session["id"],))
            self.store.set("lessons_session", None); self.store.set("graded_session", None)

    def test_unreadable_graded_queue_rejects_start_fail_closed(self):
        args = self.args(); session = self.protect(3)
        session["queue"] = None
        self.store.save_session(session, activate=False)
        self.unchanged_failure(args, "protected_study")

    def test_no_silent_shrink_if_creation_content_becomes_unavailable(self):
        args = self.args(); original_start = self.engine.start
        def changed_start(*values, **kwargs):
            item = self.store.subject(2); item["data"]["meanings"] = []; self.store.put(item)
            return original_start(*values, **kwargs)
        with patch.object(self.engine, "start", side_effect=changed_start):
            self.unchanged_failure(args)

    def test_valid_replay_uses_original_outcome_not_new_arguments_or_active_session(self):
        first = self.start()
        newer = self.engine.start("practice", 1, [4], replace_practice=True)
        self.engine.draft("NEW ACTIVE DRAFT")
        before = self.dump()
        with patch.object(self.engine, "start_trail_practice", side_effect=AssertionError("Never run twice")):
            replay = self.start({"text": "川", "subject_ids": [3]}, "trail-start")
        self.assertEqual(first["id"], replay["id"]); self.assertEqual(first["revision"], replay["revision"])
        self.assertEqual(first["subject"], replay["subject"])
        self.assertEqual(newer["id"], self.store.get("active_session"))
        self.assertEqual(before, self.dump())

    def test_nontrail_command_id_cannot_authorize_a_trail_start_reply(self):
        self.engine.command("generic", "start", {"mode": "practice", "subjects": [2], "limit": 1, "replace_practice": True})
        self.unchanged_failure(self.args(replace=True), "request_conflict", "generic")

    def test_static_stored_origin_protects_replay_even_with_different_claimed_method(self):
        first = self.start(self.args("山", [2]))
        self.engine.command("wrong-answer", "answer", {"text": "PRIVATE PRACTICE ANSWER"})
        self.protect(2); before = self.dump()
        for rid in ("trail-start", "wrong-answer"):
            for method in ("start", "answer", "draft", "trail_practice_start"):
                with self.subTest(rid=rid, method=method):
                    value = self.engine.command(rid, method, {"text": "川", "subjects": [3]})
                    self.assertEqual(first["id"], value["id"])
                    self.assertTrue(value["restricted"]); self.assertIsNone(value["subject"])
                    self.assertEqual("", value["draft"])
                    if value["feedback"]:
                        self.assertEqual([], value["feedback"]["accepted"])
                        self.assertEqual("", value["feedback"]["answer"])
        self.assertEqual(before, self.dump())

    def test_protected_resume_and_actions_retain_exact_answers_without_graded_mutations(self):
        first = self.start(self.args("山", [2]))
        self.engine.answer("PRIVATE WRONG ANSWER")
        durable = self.store.session()
        self.protect(2, "lessons")
        view = self.engine.session_view()
        self.assertTrue(view["restricted"]); self.assertIsNone(view["subject"])
        self.assertEqual([], view["feedback"]["accepted"]); self.assertEqual("", view["feedback"]["answer"])
        self.assertIn("saved graded study", view["unavailable"])
        before = self.dump()
        with patch("wanikani.engine.grade", side_effect=AssertionError("No grading when protected")):
            for method, args in (("answer", {"text": "mountain"}), ("correct", {}), ("advance", {}), ("finish", {}), ("draft", {"text": "EDIT"})):
                with self.subTest(method=method), self.assertRaises(UserError):
                    self.engine.command("blocked-" + method, method, args)
        self.assertEqual(before, self.dump())
        self.assertEqual(durable, self.store.session(first["id"]))

    def test_origin_context_invalidates_saved_view_and_replay_without_erasing_it(self):
        first = self.start(self.args("山", [2])); saved = self.store.session()
        for mutate, restore in (
                (lambda: self.store.set("session_epoch", str(uuid4())), lambda: self.store.set("session_epoch", first["session_epoch"])),
                (lambda: self.store.set("account_id", "changed"), lambda: self.store.set("account_id", "demo")),
                (lambda: setattr(self.engine, "demo", True), lambda: setattr(self.engine, "demo", False))):
            mutate()
            value = self.engine.session_view()
            self.assertTrue(value["restricted"]); self.assertIsNone(value["subject"])
            self.assertTrue(self.engine.command("trail-start", "answer", {})["restricted"])
            self.assertEqual(saved, self.store.session(saved["id"]))
            restore()
        self.assertEqual(2, self.engine.session_view()["subject"]["id"])

    def test_subsequent_actions_and_replay_never_rescan_original_passage(self):
        self.start(self.args("山", [2]))
        with patch.object(trail, "reading_trail", side_effect=AssertionError("No passage re-scan after start")):
            self.engine.start("practice")
            self.engine.draft("partial")
            self.assertEqual("partial", self.engine.session_view()["draft"])
            self.assertEqual("feedback", self.engine.command("checked", "answer", {"text": "mountain"})["phase"])
            self.assertEqual(2, self.engine.command("trail-start", "answer", {})["subject"]["id"])

    def test_marked_feedback_and_replay_filter_strict_protected_neighbors_and_aliases(self):
        self.fixture.add(1001, "川", "kanji")
        self.fixture.add(1002, "森", "kanji")
        item = self.store.subject(2)
        for key in ("component_subject_ids", "amalgamation_subject_ids", "visually_similar_subject_ids"):
            item["data"][key] = [3, 1001, 1002]
        self.store.put(item)
        protected = self.protect(3)
        protected["queue"][0]["done"] = 1
        self.store.save_session(protected, activate=False)
        # The legacy manual helper interprets this malformed completion flag
        # truthily. Strict trail/Explorer presentation must still protect it.
        for key in ("components", "related", "visually_similar"):
            self.assertEqual({3, 1001, 1002}, {entry["id"] for entry in self.engine.details(2)[key]})
        first = self.start(self.args("山", [2]))
        feedback = self.engine.command("neighbor-answer", "answer", {"text": "wrong"})
        before = self.dump()
        replies = [first, feedback, self.engine.session_view(),
            self.engine.command("trail-start", "answer", {}), self.engine.command("neighbor-answer", "start", {})]
        for reply in replies:
            for key in ("components", "related", "visually_similar"):
                self.assertEqual([1002], [entry["id"] for entry in reply["subject"][key]])
        self.assertEqual(before, self.dump())

    def test_completed_marked_recap_rechecks_original_alias_and_data_epoch_before_rows(self):
        first = self.start(self.args("ありがとう", [5]))
        self.engine.answer("thank you"); self.engine.advance()
        self.assertEqual([5], session_report.report(self.engine, first["id"])["practice_ids"])
        self.fixture.add(1001, "ありがとう", "kana_vocabulary")
        for sid in (5, 1001):
            protected = self.protect(sid)
            protected["queue"][0]["done"] = 1
            self.store.save_session(protected, activate=False)
            before = self.dump()
            with patch.object(session_report, "_subject", side_effect=AssertionError("No answer-bearing rows")):
                with self.subTest(sid=sid), self.assertRaises(UserError) as error:
                    session_report.report(self.engine, first["id"])
                self.assertEqual("protected_study", error.exception.code)
            self.assertEqual(before, self.dump())
            self.store.execute("DELETE FROM sessions WHERE id=?", (protected["id"],))
            self.store.set("reviews_session", None); self.store.set("graded_session", None)
        self.store.set("session_epoch", str(uuid4())); before = self.dump()
        with patch.object(session_report, "_subject", side_effect=AssertionError("No old-account rows")):
            with self.assertRaises(UserError) as error: session_report.report(self.engine, first["id"])
            self.assertEqual("trail_changed", error.exception.code)
        self.assertEqual(before, self.dump())

    def test_completed_marked_recap_guard_and_row_projection_share_lock(self):
        first = self.start(self.args("ありがとう", [5]))
        self.engine.answer("thank you"); self.engine.advance()
        original = session_report._subject; attempts = []
        def subject(*args):
            def attempt_write():
                acquired = self.store.lock.acquire(blocking=False); attempts.append(acquired)
                if acquired: self.store.lock.release()
            thread = threading.Thread(target=attempt_write); thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
            return original(*args)
        before = self.dump()
        with patch.object(session_report, "_subject", side_effect=subject):
            value = session_report.report(self.engine, first["id"])
        self.assertEqual([5], value["practice_ids"]); self.assertEqual([False], attempts)
        self.assertEqual(before, self.dump())

    def test_guard_and_one_card_projection_hold_same_store_context(self):
        self.start(self.args("山", [2])); original_details = self.engine.details
        attempts = []
        def details(*args, **kwargs):
            def attempt_write():
                locked = self.store.lock.acquire(blocking=False); attempts.append(locked)
                if locked: self.store.lock.release()
            thread = threading.Thread(target=attempt_write); thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
            return original_details(*args, **kwargs)
        with patch.object(self.engine, "details", side_effect=details):
            self.assertEqual(2, self.engine.session_view()["subject"]["id"])
        self.assertEqual([False], attempts)

    def test_match_validation_and_session_creation_hold_one_atomic_store_transaction(self):
        args = self.args(); original = trail_practice.preview; attempts = []
        def preview(*values):
            value = original(*values)
            def attempt_write():
                acquired = self.store.lock.acquire(blocking=False); attempts.append(acquired)
                if acquired: self.store.lock.release()
            thread = threading.Thread(target=attempt_write); thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive()); self.assertTrue(self.store.db.in_transaction)
            return value
        with patch.object(trail_practice, "preview", side_effect=preview): self.start(args)
        self.assertEqual([False], attempts)

    def test_journal_failure_rolls_back_new_session_replacement_and_references(self):
        self.engine.start("practice", 1, [4], replace_practice=True); self.engine.draft("OLD DRAFT")
        args = self.args(replace=True); original = self.store.execute
        def failing(sql, values=()):
            if sql.startswith("INSERT INTO commands"): raise UserError("Authored storage fault")
            return original(sql, values)
        with patch.object(self.store, "execute", side_effect=failing): self.unchanged_failure(args)

    def test_actual_process_crash_before_reply_commit_rolls_back_and_after_commit_replays_once(self):
        args = self.args(); before = self.dump()
        code = '''
import json, os, sys
from pathlib import Path
from wanikani.store import Store
from wanikani.engine import Engine
store=Store(Path(sys.argv[1])); engine=Engine(store,clock=lambda:1788550000)
args=json.loads(sys.argv[2]); boundary=sys.argv[3]
original=store.execute
def execute(sql, values=()):
    if boundary=='before' and sql.startswith('INSERT INTO commands'): os._exit(71)
    return original(sql,values)
store.execute=execute
engine.command('crash-start','trail_practice_start',args)
os._exit(72)
'''
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
        for boundary, expected in (("before", 71), ("after", 72)):
            process = subprocess.run([sys.executable, "-c", code, str(self.store.path), json.dumps(args), boundary],
                env=environment, capture_output=True, timeout=15)
            self.assertEqual(expected, process.returncode, process.stderr.decode())
            self.store.close(); self.store = Store(self.fixture.path); self.engine = Engine(self.store, clock=lambda: authored.NOW)
            if boundary == "before": self.assertEqual(before, self.dump())
        saved = self.store.session(); committed = self.dump()
        reply = self.engine.command("crash-start", "trail_practice_start", {"text": "CHANGED"})
        self.assertEqual(saved["id"], reply["id"])
        self.assertEqual(saved["revision"], reply["revision"])
        self.assertEqual(1, self.store.rows("SELECT COUNT(*) FROM sessions")[0][0])
        self.assertEqual(committed, self.dump())


class TrailPracticeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wanikani-trail-worker-")
        self.messages = []
        with patch("worker.Keyring", return_value=Mock()):
            self.worker = Worker(Path(self.temp.name), self.messages.append)
        self.store, self.engine = self.worker.engine.store, self.worker.engine
        populate(self.store, authored.NOW); self.store.set("account_id", "demo")
        self.engine.clock = lambda: authored.NOW
        self.worker.readiness.refresh = Mock()
        self.worker.sync = Mock()

    def tearDown(self):
        self.worker.stopping = True; self.worker.readiness.stop()
        self.store.close(); self.temp.cleanup()

    def send(self, method, args, rid="worker-trail"):
        self.messages.clear()
        self.worker.handle({"v": 1, "id": rid, "method": method, "args": args})
        return self.messages[0]["data"]

    def test_preview_is_one_read_only_reply_and_start_emits_only_compact_session(self):
        before = list(self.store.db.iterdump())
        with patch.object(self.worker, "snapshot", side_effect=AssertionError("No full snapshot")), \
                patch("wanikani.learning_digest.project", side_effect=AssertionError("No history scan")):
            preview = self.send("trail_practice_preview", {"text": "山", "subject_ids": [2]})
            self.assertEqual(1, len(self.messages)); self.assertEqual(before, list(self.store.db.iterdump()))
            self.assertIsNone(self.store.get("last_study_at"))
            args = {"text": "山", "subject_ids": [2], "expected_data_epoch": preview["data_epoch"],
                "expected_saved_practice_revision": None, "replace_existing": False}
            value = self.send("trail_practice_start", args, "start-worker-trail")
            self.assertEqual("practice", value["mode"])
            self.assertEqual(2, len(self.messages)); self.assertEqual("session", self.messages[1]["event"])
            self.assertNotIn("learning_after_revision", self.messages[0])
        self.assertEqual(authored.NOW, self.store.get("last_study_at"))
        self.worker.sync.run.assert_not_called(); self.worker.readiness.refresh.assert_not_called()
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_worker_routes_reject_unknown_or_missing_fields_before_any_effect(self):
        preview = {"text": "山", "subject_ids": [2]}
        start = {**preview, "expected_data_epoch": self.store.get("session_epoch"),
            "expected_saved_practice_revision": None, "replace_existing": False}
        before = list(self.store.db.iterdump())
        for method, values in (("trail_practice_preview", preview), ("trail_practice_start", start)):
            variants = [{**values, "extra": "PRIVATE"}] + [{key: value for key, value in values.items() if key != missing} for missing in values]
            for args in variants:
                with self.subTest(method=method, keys=set(args)), self.assertRaises(UserError) as error:
                    self.send(method, args)
                self.assertEqual("invalid_request", error.exception.code)
                self.assertEqual([], self.messages)
        self.assertEqual(before, list(self.store.db.iterdump()))


if __name__ == "__main__":
    unittest.main()
