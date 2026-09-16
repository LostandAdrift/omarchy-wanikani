import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from wanikani.api import Api, ApiError
from wanikani.common import UserError, stamp
from wanikani.demo import populate
from wanikani.engine import Engine, baseline
from wanikani.grading import grade
from wanikani.store import Store
from wanikani.sync import Synchronizer

NOW = 1788550000


def subject(kind="vocabulary", meanings=None, readings=None):
    return {"id": 1, "object": kind, "data": {"level": 1, "characters": "入る", "meanings": meanings or [{"meaning": "to enter", "accepted_answer": True}], "readings": readings or [{"reading": "はいる", "accepted_answer": True}], "auxiliary_meanings": [{"meaning": "exit", "type": "blacklist"}]}}


class GradingTests(unittest.TestCase):
    def test_acceptance_and_normalization(self):
        self.assertTrue(grade(subject(), "meaning", " TO ENTER ")["correct"])
        self.assertTrue(grade(subject(), "reading", "ハイル")["correct"])
        self.assertTrue(grade(subject(), "reading", "ﾊｲﾙ")["correct"])

    def test_synonyms_and_exclusions(self):
        self.assertTrue(grade(subject(), "meaning", "go inside", {"meaning_synonyms": ["go inside"]})["correct"])
        self.assertFalse(grade(subject(), "meaning", "exit", {"meaning_synonyms": ["exit"]})["correct"])
        self.assertFalse(grade(subject(), "meaning", "exiit")["correct"])

    def test_retryable_input_is_not_wrong(self):
        for part, answer in [("meaning", "enter"), ("meaning", "はいる"), ("reading", "hairu"), ("reading", ""), ("meaning", "")]:
            with self.subTest(part=part, answer=answer):
                self.assertTrue(grade(subject(), part, answer)["retry"])

    def test_reading_strict_small_kana(self):
        item = subject(readings=[{"reading":"じゅう","accepted_answer":True}])
        self.assertFalse(grade(item, "reading", "じゆう")["correct"])

    def test_alternate_kanji_reading_is_retry(self):
        item = subject("kanji", readings=[{"reading":"にち","accepted_answer":True},{"reading":"ひ","accepted_answer":False}])
        self.assertTrue(grade(item,"reading","ひ")["retry"])
        item["object"] = "vocabulary"
        self.assertEqual("incorrect",grade(item,"reading","ひ")["kind"])

    def test_conservative_typo_tolerance(self):
        self.assertEqual("imprecise",grade(subject(),"meaning","to entr")["kind"])
        item=subject(meanings=[{"meaning":"one","accepted_answer":True}])
        self.assertFalse(grade(item,"meaning","on")["correct"])
        item=subject(meanings=[{"meaning":"number 12","accepted_answer":True}])
        self.assertFalse(grade(item,"meaning","number 13")["correct"])

    def test_nonaccepted_meaning_not_graded(self):
        item=subject(meanings=[{"meaning":"enter","accepted_answer":False},{"meaning":"go inside","accepted_answer":True}])
        self.assertFalse(grade(item,"meaning","enter")["correct"])


class EngineFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"state.sqlite3"
        self.store=Store(self.path)
        populate(self.store,NOW)
        self.engine=Engine(self.store,clock=lambda:NOW)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def correct_answer(self, view):
        return view["subject"]["meanings"][0] if view["part"]=="meaning" else next(r["reading"] for r in view["subject"]["readings"] if r["accepted"])

    def complete(self, mode="reviews", limit=1):
        view=self.engine.start(mode,limit)
        while view["phase"]=="lesson":
            view=self.engine.lesson_next()
        while view["phase"]!="complete":
            view=self.engine.answer(self.correct_answer(view))
            view=self.engine.advance()
        return view


class EngineTests(EngineFixture, unittest.TestCase):
    def test_click_away_preference_defaults_on_and_persists_without_changing_study(self):
        self.assertIs(self.engine.settings()["close_on_outside_click"], True)
        session = self.engine.start("reviews", 5)
        before = self.store.db.execute("SELECT id,body FROM sessions ORDER BY id").fetchall()
        self.engine.set_settings({"close_on_outside_click": False})
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.assertIs(self.engine.settings()["close_on_outside_click"], False)
        self.assertEqual(before, self.store.db.execute("SELECT id,body FROM sessions ORDER BY id").fetchall())
        with self.assertRaises(UserError):
            self.engine.set_settings({"close_on_outside_click": "false"})

    def test_finish_current_group_preserves_answers(self):
        for a in self.store.all('assignment'):
            if a['data']['started_at']:
                a['data']['available_at']=stamp(NOW-1);self.store.put(a)
        view=self.engine.start('reviews',12)
        self.engine.answer('wrong');view=self.engine.finish()
        self.assertEqual('feedback',view['phase']);self.assertEqual(1,view['errors'])
        view=self.engine.advance()
        while view['phase']!='complete':
            self.engine.answer(self.correct_answer(view));view=self.engine.advance()
        self.assertEqual(5,view['completed']);self.assertEqual(5,self.engine.snapshot()['pending'])

    def test_pin_and_conflict_require_explicit_recovery(self):
        self.engine.pin(16,True)
        self.assertEqual(16,self.engine.difficult()[0]['id'])
        self.engine.pin(16,False)
        self.assertFalse(self.engine.details(16)['pinned'])
        self.complete(limit=5)
        self.store.execute("UPDATE outbox SET state='conflicted'")
        self.assertEqual(0,self.engine.snapshot()['reviews'])

    def test_clock_change_and_vacation_preserve_current_session(self):
        self.engine.start('reviews',1);self.engine.draft('partly typed')
        self.engine.clock_untrusted=True
        with self.assertRaises(UserError):self.engine.answer('wrong')
        self.assertEqual('partly typed',self.engine.session_view()['draft'])
        self.engine.clock_untrusted=False
        u=self.store.get('user');u['data']['current_vacation_started_at']=stamp(NOW);self.store.set('user',u)
        with self.assertRaises(UserError):self.engine.answer('wrong')

    def test_counts_and_lookup(self):
        state=self.engine.snapshot()
        self.assertEqual((5,3),(state["reviews"],state["lessons"]))
        self.assertEqual(2,len(self.engine.search("山")))
        self.assertGreaterEqual(len(self.engine.search("山が見えます")),1)
        self.assertEqual([],self.engine.search("%"))
        self.assertTrue(all(s["assignment"]["srs_stage"]>=5 for s in self.engine.ambient()))

    def test_draft_and_feedback_survive_restart(self):
        view=self.engine.start("reviews",1)
        self.engine.draft("partial")
        self.store.close();self.store=Store(self.path);self.engine=Engine(self.store,clock=lambda:NOW)
        self.assertEqual("partial",self.engine.session_view()["draft"])
        self.engine.answer("definitely wrong")
        self.store.close();self.store=Store(self.path);self.engine=Engine(self.store,clock=lambda:NOW)
        view=self.engine.session_view()
        self.assertEqual("feedback",view["phase"])
        self.assertEqual(1,view["errors"])
        self.assertEqual("definitely wrong",view["feedback"]["answer"])

    def test_current_typo_correction_only(self):
        self.engine.start("reviews",1)
        self.engine.answer("definitely wrong")
        view=self.engine.correct()
        self.assertEqual((0,1),(view["errors"],view["overrides"]))
        with self.assertRaises(UserError):self.engine.correct()
        self.engine.advance()
        with self.assertRaises(UserError):self.engine.correct()

    def test_no_submission_until_final_feedback_acknowledged(self):
        view=self.engine.start("reviews",1)
        while True:
            view=self.engine.answer(self.correct_answer(view))
            self.assertEqual([],self.store.rows("SELECT * FROM outbox"))
            # Last question is reading for two-part items, meaning for others.
            if view["part"]=="reading" or view["subject"]["type"] in ("radical","kana_vocabulary"):
                break
            view=self.engine.advance()
        self.engine.advance()
        self.assertEqual("pending",self.store.rows("SELECT state FROM outbox")[0][0])

    def test_offline_pending_excludes_next_graded_cycle(self):
        self.complete(limit=5)
        self.assertEqual(0,self.engine.snapshot()["reviews"])
        self.assertEqual(5,self.engine.snapshot()["pending"])
        with self.assertRaises(UserError):self.engine.start("reviews")

    def test_lessons_use_lesson_outbox_not_review(self):
        self.complete("lessons",2)
        self.assertEqual(["lesson","lesson"],[r[0] for r in self.store.rows("SELECT kind FROM outbox")])

    def test_practice_never_writes_progress(self):
        view=self.engine.start("practice",1,[3])
        while view["phase"]!="complete":
            self.engine.answer(self.correct_answer(view));view=self.engine.advance()
        self.assertEqual([],self.store.rows("SELECT * FROM outbox"))

    def test_duplicate_command_is_atomic_and_idempotent_locally(self):
        self.engine.start("reviews",1)
        one=self.engine.command("id1","answer",{"text":"definitely wrong"})
        two=self.engine.command("id1","answer",{"text":"something else"})
        self.assertEqual(one,two)
        self.assertEqual(1,self.engine.session_view()["errors"])
        self.assertEqual(1,self.store.rows("SELECT COUNT(*) FROM events WHERE kind='answer'")[0][0])

    def test_transaction_rollback_retains_question(self):
        self.engine.start("reviews",1)
        original=self.store.save_session
        def fail(session):
            original(session)
            raise OSError("simulated disk failure")
        with patch.object(self.store,"save_session",side_effect=fail):
            with self.assertRaises(OSError):self.engine.answer("wrong")
        self.assertEqual("question",self.engine.session_view()["phase"])
        self.assertEqual([],self.store.rows("SELECT * FROM events"))

    def test_inflight_recovers_uncertain(self):
        self.complete()
        self.store.execute("UPDATE outbox SET state='inflight'")
        self.store.close();self.store=Store(self.path);self.engine=Engine(self.store,clock=lambda:NOW)
        self.assertEqual("uncertain",self.store.rows("SELECT state FROM outbox")[0][0])

    def test_access_expiry_and_hidden_subjects(self):
        u=self.store.get("user");u["data"]["subscription"]={"active":True,"type":"recurring","max_level_granted":60,"period_ends_at":stamp(NOW-1)};self.store.set("user",u)
        s=self.store.subject(1);s["data"]["level"]=4;self.store.put(s)
        with self.assertRaises(UserError):self.engine.details(1)
        s=self.store.subject(2);s["data"]["hidden_at"]=stamp(NOW);self.store.put(s)
        self.assertEqual(3,self.engine.snapshot()["reviews"])

    def test_vacation_blocks_grading_but_not_practice(self):
        u=self.store.get("user");u["data"]["current_vacation_started_at"]=stamp(NOW);self.store.set("user",u)
        with self.assertRaises(UserError):self.engine.start()
        self.assertEqual("practice",self.engine.start("practice",1,[3])["mode"])

    def test_notes_are_durable_and_new_edits_wait_for_sync(self):
        detail=self.engine.set_material(2,{"meaning_synonyms":["peak"],"meaning_note":"My note"})
        self.assertTrue(detail["material_pending"])
        self.assertEqual("My note",self.engine.details(2)["material"]["meaning_note"])
        with self.assertRaises(UserError):self.engine.set_material(2,{"meaning_synonyms":["ridge"]})


class FakeApi:
    def __init__(self, store):
        self.assignments={r["id"]:copy.deepcopy(r) for r in store.all("assignment")}
        self.user=copy.deepcopy(store.get("user"))
        self.mutations=[]
        self.error=None
        self.server_offset=0
        self.resets=[]
    def request(self,path,method="GET",data=None,etag=None):
        if method=="GET":
            if path=="user":return self.user,None
            if path=="summary":return {"data":{}},"etag"
            if path.startswith("assignments/"):return copy.deepcopy(self.assignments[int(path.split("/")[1])]),None
            raise AssertionError(path)
        self.mutations.append((path,method,data))
        if self.error:raise self.error
        if path=="reviews":
            assignment=self.assignments[data["review"]["assignment_id"]]
            assignment["data"]["srs_stage"]+=1
            assignment["data"]["available_at"]=stamp(NOW+14400)
            return {"id":0,"object":"review","resources_updated":{"assignment":copy.deepcopy(assignment)}},None
        if path.endswith("/start"):
            assignment=self.assignments[int(path.split("/")[1])]
            assignment["data"]["started_at"]=data["assignment"]["started_at"]
            assignment["data"]["available_at"]=stamp(NOW+14400)
            assignment["data"]["srs_stage"]=1
            return copy.deepcopy(assignment),None
        if path=="study_materials":return {"id":999,"object":"study_material","data":data["study_material"]},None
        raise AssertionError(path)
    def collection(self,endpoint,params=None):
        yield self.resets if endpoint=="resets" else []


class SyncTests(EngineFixture, unittest.TestCase):
    def synchronizer(self):
        api=FakeApi(self.store)
        return Synchronizer(self.engine,api,Path(self.temp.name)/"media"),api

    def test_confirm_review_id_zero_updates_assignment(self):
        self.complete();sync,api=self.synchronizer();sync.flush()
        self.assertEqual(1,len(api.mutations))
        self.assertEqual("confirmed",self.store.rows("SELECT state FROM outbox")[0][0])

    def test_lost_response_never_automatically_replayed(self):
        self.complete();sync,api=self.synchronizer();api.error=ApiError(0,"lost",True)
        with self.assertRaises(ApiError):sync.flush()
        self.assertEqual("uncertain",self.store.rows("SELECT state FROM outbox")[0][0])
        api.error=None;sync.reconcile_uncertain();sync.flush()
        self.assertEqual(1,len(api.mutations))
        self.assertEqual("uncertain",self.store.rows("SELECT state FROM outbox")[0][0])

    def test_another_device_progress_prevents_stale_write(self):
        self.complete();sync,api=self.synchronizer()
        operation=json.loads(self.store.rows("SELECT body FROM outbox")[0][0])
        api.assignments[operation["assignment_id"]]["data"]["available_at"]=stamp(NOW+86400)
        sync.flush()
        self.assertEqual([],api.mutations)
        self.assertEqual("conflicted",self.store.rows("SELECT state FROM outbox")[0][0])

    def test_uncertain_changed_remote_stays_unattributed(self):
        self.complete();sync,api=self.synchronizer()
        self.store.execute("UPDATE outbox SET state='uncertain'")
        op=json.loads(self.store.rows("SELECT body FROM outbox")[0][0])
        api.assignments[op["assignment_id"]]["data"]["available_at"]=stamp(NOW+86400)
        sync.reconcile_uncertain()
        self.assertEqual("conflicted",self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual([],api.mutations)

    def test_permissions_block_and_rate_limit_remains_pending(self):
        for status,expected in [(403,"blocked"),(401,"blocked"),(429,"pending")]:
            with self.subTest(status=status):
                self.store.execute("DELETE FROM outbox")
                self.store.set("active_session",None)
                self.complete();sync,api=self.synchronizer();api.error=ApiError(status,"blocked")
                with self.assertRaises(ApiError):sync.flush()
                self.assertEqual(expected,self.store.rows("SELECT state FROM outbox")[0][0])

    def test_malformed_success_is_uncertain(self):
        self.complete();sync,api=self.synchronizer()
        row=self.store.rows("SELECT * FROM outbox")[0]
        sync.apply_result(row,{"object":"review","id":0})
        self.assertEqual("uncertain",self.store.rows("SELECT state FROM outbox")[0][0])

    def test_recovery_archives_without_resubmitting(self):
        self.complete();sync,api=self.synchronizer();self.store.execute("UPDATE outbox SET state='uncertain'")
        rid=self.store.rows("SELECT id FROM outbox")[0][0]
        with self.assertRaises(UserError):sync.resolve(rid,"retry")
        sync.resolve(rid,"keep_remote")
        self.assertEqual("discarded",self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual([],api.mutations)

    def test_reset_invalidates_pending_and_partial_session(self):
        self.complete();self.engine.start("reviews",1)
        sync,api=self.synchronizer()
        sync._invalidate_reset({"data":{"target_level":1}})
        self.assertEqual("conflicted",self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual("complete",self.engine.session_view()["phase"])

    def test_lesson_writes_start_endpoint(self):
        self.complete("lessons");sync,api=self.synchronizer();sync.flush()
        self.assertTrue(api.mutations[0][0].endswith("/start"))
        self.assertEqual("PUT",api.mutations[0][1])

    def test_material_write(self):
        self.engine.set_material(2,{"meaning_synonyms":["peak"]})
        sync,api=self.synchronizer();sync.flush()
        self.assertFalse(self.engine.details(2)["material_pending"])
        self.assertEqual("study_materials",api.mutations[0][0])


class TransportTests(unittest.TestCase):
    def test_foreign_api_host_rejected_without_request(self):
        api=Api("test-token")
        with patch.object(api.opener,"open") as opened:
            with self.assertRaises(ApiError):api.request("https://example.com/v2/user")
            opened.assert_not_called()

    def test_network_mutation_uncertain_but_get_safe(self):
        api=Api("test-token")
        with patch.object(api.opener,"open",side_effect=urllib.error.URLError("offline")):
            for method in ["GET","POST"]:
                api.next_allowed=0
                with self.assertRaises(ApiError) as error:api.request("reviews",method,{"review":{}} if method=="POST" else None)
                self.assertEqual(method=="POST",error.exception.uncertain)
                self.assertNotIn("test-token",str(error.exception))

    def test_pagination_cycle_rejected(self):
        api=Api("test-token")
        with patch.object(api,"request",return_value=({"data":[],"pages":{"next_url":"assignments"}},None)):
            with self.assertRaises(ApiError):list(api.collection("assignments"))


if __name__=="__main__":unittest.main()
