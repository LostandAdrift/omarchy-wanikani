"""Canonical cached Lookup status; authored rows only, no account/network IO."""
import copy
import json
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW, stamp
from wanikani import progress, subject_status, editor, journal
from wanikani.common import UserError


class LookupStatusTests(EngineFixture, unittest.TestCase):
    def assignment(self, stage=4, **changes):
        item = self.store.related("assignment", 2)
        item["data"].update(srs_stage=stage, unlocked_at=stamp(NOW-10000),
            started_at=stamp(NOW-9000), passed_at=None, burned_at=None,
            available_at=stamp(NOW+3600), hidden=False)
        item["data"].update(changes)
        self.store.put(item)
        return item

    def queued(self, state, kind="review", key=None):
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (
            key or state+kind, kind, 2, state, "{}", stamp(NOW), "PRIVATE ERROR"))

    def status(self):
        return self.engine.details(2, include_status=True)["learning_status"]

    def test_named_confirmed_stages_match_existing_progress(self):
        for stage in range(1, 10):
            self.assignment(stage, burned_at=stamp(NOW-1) if stage==9 else None)
            value = self.status()
            canonical = progress.subject_status(self.engine, 2)
            self.assertEqual({key: canonical[key] for key in value}, value)
            self.assertEqual(progress.STAGES[stage][1], value["stage_name"])
            self.assertFalse(value["pending"] or value["attention"])

    def test_pending_and_attention_do_not_predict_confirmed_stage(self):
        self.assignment(4)
        for state in ("pending", "inflight", "uncertain", "blocked", "conflicted"):
            with self.subTest(state=state):
                self.store.execute("DELETE FROM outbox")
                self.queued(state)
                value = self.status()
                self.assertEqual((4, "Apprentice 4"), (value["stage"], value["stage_name"]))
                self.assertEqual(state in ("pending", "inflight"), value["pending"])
                self.assertEqual(state in ("uncertain", "blocked", "conflicted"), value["attention"])
                search = self.engine.search("mountain")[0]
                self.assertEqual(value, search["learning_status"])
                self.assertTrue(search["pending"], "Legacy unresolved flag remains compatible")
        self.queued("pending", key="second")
        self.assertTrue(self.status()["attention"])
        self.assertFalse(self.status()["pending"])

    def test_material_confirmed_archived_and_other_subjects_do_not_look_pending(self):
        self.assignment()
        self.queued("pending", "material")
        self.queued("confirmed")
        self.queued("discarded")
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", ("other", "review", 3, "uncertain", "{}", stamp(NOW), "private"))
        self.assertFalse(self.status()["pending"] or self.status()["attention"])

    def test_not_started_ready_and_missing_or_malformed_assignment_stay_honest(self):
        self.assignment(0, started_at=None, available_at=None)
        self.assertEqual("lessons", self.status()["group"])
        self.assignment(0, started_at=None, available_at=None, unlocked_at=None)
        self.assertEqual("locked", self.status()["group"])
        for changes in ({"srs_stage": True}, {"srs_stage": "4"}, {"srs_stage": 12},
                {"started_at": "invalid"}, {"started_at": stamp(NOW+100)},
                {"unlocked_at": stamp(NOW-10), "started_at": stamp(NOW-100)}):
            self.assignment(4, **{key: value for key, value in changes.items() if key!="srs_stage"})
            if "srs_stage" in changes:
                item=self.store.related("assignment",2);item["data"]["srs_stage"]=changes["srs_stage"];self.store.put(item)
            self.assertEqual("unknown", self.status()["group"], changes)
        self.assignment(4)
        duplicate=copy.deepcopy(self.store.related("assignment",2));duplicate["id"]=987654;self.store.put(duplicate)
        self.assertEqual("unknown", self.status()["group"])

    def test_access_checks_still_precede_status_projection(self):
        value=self.store.subject(2);value["data"]["hidden_at"]=stamp(NOW);self.store.put(value)
        with patch.object(subject_status,"project",side_effect=AssertionError("No inaccessible projection")):
            with self.assertRaises(UserError):self.engine.details(2,include_status=True)
        self.assertEqual([],self.engine.search("mountain"))

    def test_status_reads_are_batched_and_selected_before_grouping_without_writes(self):
        original="\n".join(self.store.db.iterdump())
        trace=[];self.store.db.set_trace_callback(trace.append)
        with patch.object(subject_status,"project",wraps=subject_status.project) as project:
            results=self.engine.search("",filters={"type":"kanji"})
            self.assertTrue(results);self.assertEqual(1,project.call_count)
            self.assertEqual([row["id"] for row in results],project.call_args.args[1])
        self.store.db.set_trace_callback(None)
        self.assertEqual(original,"\n".join(self.store.db.iterdump()))
        metadata=[sql for sql in trace if "AS assignment_count" in sql]
        self.assertEqual(1,len(metadata));self.assertLess(metadata[0].index("CAST(s.id AS INTEGER) IN ("),metadata[0].index("GROUP BY"))
        self.assertTrue(any("outbox INDEXED BY outbox_state" in sql and "subject_id IN (" in sql for sql in trace))
        self.assertNotIn("PRIVATE",json.dumps([row["learning_status"] for row in results]))

    def test_study_and_lesson_detail_paths_do_not_compute_lookup_status(self):
        with patch.object(subject_status,"project",side_effect=AssertionError("No status work during study")):
            self.assertNotIn("learning_status",self.engine.details(2))
            session=self.engine.start("reviews",1)
            self.engine.draft("partial")
            self.engine.answer("fixture wrong answer")
            self.engine.session_view()
            self.engine.command("same-question","start",{"mode":"resume"})
            self.engine.command("same-question","start",{"mode":"resume"})
            self.assertEqual(session["id"],self.store.session()["id"])

    def test_duplicate_metadata_cannot_become_unique_at_a_batch_boundary(self):
        with self.store.transaction():
            self.store.execute("DELETE FROM resources")
            template = {"id": 1, "object": "kanji", "data": {"level": 1, "hidden_at": None}}
            for sid, kinds in ((1, ("radical", "kanji", "vocabulary", "kana_vocabulary")),
                    (2, ("kanji",)), (3, ("kanji", "vocabulary"))):
                for kind in kinds:
                    subject = {**template, "id": sid, "object": kind}
                    self.store.execute("INSERT INTO resources VALUES(?,?,?)", (kind, str(sid), json.dumps(subject)))
                self.store.put({"id": 100 + sid, "object": "assignment", "data": {
                    "subject_id": sid, "srs_stage": 4, "hidden": False,
                    "unlocked_at": stamp(NOW - 10000), "started_at": stamp(NOW - 9000),
                    "available_at": stamp(NOW + 3600), "passed_at": None, "burned_at": None}})
        batch = subject_status.project(self.engine, [1, 2, 3])
        self.assertEqual(subject_status.project(self.engine, [3])[3], batch[3])
        self.assertEqual("unknown", batch[1]["group"])
        self.assertEqual("unknown", batch[3]["group"])
        self.assertEqual("apprentice", batch[2]["group"], "An untruncated unique group remains useful")
        # Directly damaged numeric spellings can exceed four rows per ID.
        # The reached sentinel must withhold every baseline, even an earlier
        # individually unique group, without hiding real queued work.
        for index in range(15):
            subject = {**template, "id": 3}
            self.store.execute("INSERT INTO resources VALUES(?,?,?)", (
                "kanji", "0" * (index + 1) + "3", json.dumps(subject)))
        self.queued("uncertain")
        bounded = subject_status.project(self.engine, [1, 2, 3])
        self.assertTrue(all(value["group"] == "unknown" and value["stage"] is None for value in bounded.values()))
        self.assertTrue(bounded[2]["attention"])
        self.assertFalse(bounded[2]["pending"])

    def test_pin_material_discard_and_duplicate_lookup_reply_have_current_status(self):
        self.assignment(4);self.queued("pending")
        self.assertEqual(self.status(),self.engine.pin(2,True)["learning_status"])
        self.assertEqual(self.status(),editor.discard(self.engine,2)["learning_status"])
        saved=self.engine.command("pin-replay","pin",{"subject_id":2,"enabled":True})
        self.store.execute("UPDATE outbox SET state='uncertain'")
        replay=self.engine.command("pin-replay","pin",{"subject_id":3,"enabled":False})
        self.assertEqual(2,replay["id"]);self.assertTrue(replay["learning_status"]["attention"])
        self.assertFalse(saved["learning_status"]["attention"])
        result=self.engine.set_material(2,{"meaning_synonyms":[],"meaning_note":"Authored note","reading_note":""})
        self.assertTrue(result["learning_status"]["attention"])


import test_srs_worker as worker_fixtures


class LookupStatusWorkerTests(unittest.TestCase):
    setUp = worker_fixtures.SrsWorkerTests.setUp
    tearDown = worker_fixtures.SrsWorkerTests.tearDown
    request = worker_fixtures.SrsWorkerTests.request
    preserved = worker_fixtures.SrsWorkerTests.preserved
    assert_preserved = worker_fixtures.SrsWorkerTests.assert_preserved

    def test_lookup_and_progress_routes_project_same_pending_status_in_one_read_reply(self):
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", ("authored-pending", "review", 4, "uncertain", "{}", stamp(NOW), "PRIVATE QUEUE MESSAGE"))
        before = self.preserved()
        detail = self.request("details", {"subject_id": 4})
        guarded = self.request("progress_details", {"subject_id": 4})
        self.assertEqual(detail["learning_status"], guarded["learning_status"])
        self.assertTrue(detail["learning_status"]["attention"])
        self.assertEqual("apprentice", detail["learning_status"]["group"])
        self.assertNotIn("PRIVATE", json.dumps(detail["learning_status"]))
        self.assert_preserved(before)
    def test_new_paused_graded_subject_still_blocks_guarded_projection(self):
        self.engine.start("reviews", 1)
        subject_id = self.store.session()["queue"][0]["subject_id"]
        before = self.preserved()
        with patch.object(subject_status, "project", side_effect=AssertionError("Guard must win first")):
            with self.assertRaises(UserError):
                self.request("progress_details", {"subject_id": subject_id})
        self.assert_preserved(before)


if __name__=="__main__":unittest.main()
