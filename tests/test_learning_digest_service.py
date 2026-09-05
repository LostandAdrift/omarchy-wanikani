"""Actual Service state/request/status functions with an inert ordered worker."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_agent_cli as helper
from test_listening_preparation_ui import build_adapter, RUNNER


ROOT = Path(__file__).resolve().parents[1]
QML = r'''
import QtQuick
import QtTest
Item {
  ServiceCore { id:service }
  TestCase {
    name:"LearningDigestService"
    readonly property string epoch:"01234567-89ab-4cde-8fab-0123456789ab"
    function metric(){return {reviews:2,lessons:1,practice:3}}
    function window(days,today){
      var start=new Date(today+"T00:00:00Z");start.setUTCDate(start.getUTCDate()-days+1)
      return {days:days,start_day:start.toISOString().slice(0,10),end_day:today,
        subject_completions:metric(),sessions_completed:metric(),listening_ratings:{remembered:2,again:1,skipped:1},
        listening_sessions_completed:1,dictation_ratings:{matched:3,again:1,skipped:0},dictation_sessions_completed:1,typo_corrections:1}
    }
    function digest(){
      var now=new Date(Date.now()-1000).toISOString(),today=now.slice(0,10)
      return {schema_version:1,scope:"recorded_on_this_device",freshness:"cached",generated_at:now,
        data_epoch:epoch,demo:true,timezone:"UTC",complete:true,stale:false,coverage:"retained_local_records",
        includes_retained_pre_reset_activity:true,windows:{"7":window(7,today),"30":window(30,today)}}
    }
    function snapshot(revision,sessionRevision){return {state_revision:revision||1,session_revision:sessionRevision||1,
      session_epoch:epoch,demo:true,username:"Authored learner",max_level:60,status:"demo",level:3,
      reviews:0,lessons:0,pending:0,attention:0,session:null,saved_sessions:{},learning_digest:digest()}}
    function status(){return JSON.parse(service.status()).learning_digest}
    function hydrate(){service.applySnapshot(snapshot());verify(status()!==null)}
    function reply(ok,data,bound){var request=service.writes[service.writes.length-1];service.receive(JSON.stringify({v:1,id:request.id,ok:ok,data:data||{},learning_after_revision:bound,error:ok?null:{message:"Authored failure"}}))}
    function init(){
      failOnWarning(/.*/)
      service.ready=false;service.snapshot={};service.stateOrder=service.initialOrder()
      service.callbacks={};service.requestContexts={};service.pendingCount=0;service.writes=[]
      service.listeningPreparationJobId="";service.listeningPreparationCancelling=false
      service.learningDigestHydrated=false;service.learningDigestDirty=false;service.learningDigestBarrier=-1
      service.receive(JSON.stringify({v:1,event:"ready",data:{version:"0.2.7"}}))
    }
    function test_cached_status_is_allowlisted_and_never_reads_worker(){
      var value=snapshot();value.learning_digest.secret="PRIVATE TOKEN"
      value.learning_digest.windows["7"].notes="PRIVATE NOTE"
      value.learning_digest.windows["30"].dictation_ratings.answer="PRIVATE ANSWER"
      service.applySnapshot(value);var count=service.writes.length
      for(var index=0;index<5;index++){
        var report=status();verify(report!==null);compare(report.stale,null)
        compare(report.generated_at,value.learning_digest.generated_at)
        verify(JSON.stringify(report).indexOf("PRIVATE")<0)
      }
      compare(service.writes.length,count)
      console.log("DIGEST_SERVICE "+service.status())
    }
    function test_worker_restart_withholds_old_digest_until_new_snapshot(){
      hydrate();service.restartWorker();compare(status(),null)
      service.receive(JSON.stringify({v:1,event:"ready",data:{version:"0.2.7"}}));compare(status(),null)
      service.applySnapshot(snapshot());verify(status()!==null)
    }
    function test_missing_or_bad_epoch_and_wrong_demo_never_reuse_old_totals(){
      for(var kind of ["missing","epoch","demo","malformed"]){
        var value=snapshot(service.stateOrder.stateRevision+1)
        if(kind==="missing")delete value.learning_digest
        if(kind==="epoch")value.learning_digest.data_epoch="01234567-89ab-4cde-8fab-0123456789ac"
        if(kind==="demo")value.learning_digest.demo=false
        if(kind==="malformed")value.learning_digest.windows["7"].subject_completions.reviews=true
        service.applySnapshot(value);compare(status(),null,kind)
      }
    }
    function test_new_epoch_cannot_be_overwritten_by_late_old_snapshot(){
      var old=snapshot();service.applySnapshot(old)
      var fresh=snapshot(2);fresh.session_epoch="01234567-89ab-4cde-8fab-0123456789ac"
      fresh.learning_digest.data_epoch=fresh.session_epoch
      service.applySnapshot(fresh);service.applySnapshot(old)
      compare(status().data_epoch,fresh.session_epoch)
    }
    function test_compact_session_and_retained_newer_session_mark_cache_stale(){
      hydrate();service.applySession({session:null,session_revision:2,session_epoch:epoch,saved_sessions:{}})
      compare(status().stale,true)
      service.applySnapshot(snapshot(2,1));compare(status().stale,true)
      service.applySnapshot(snapshot(3,2));compare(status().stale,null)
    }
    function test_local_audio_commit_marks_stale_without_requesting_a_snapshot_data(){
      return [{tag:"meaning rating",method:"listen",action:"rate"},{tag:"meaning undo",method:"listen",action:"undo"},
        {tag:"dictation commit",method:"dictation",action:"continue"},{tag:"dictation undo",method:"dictation",action:"undo"},
        {tag:"correction",method:"correct",action:""},{tag:"advance",method:"advance",action:""}]
    }
    function test_local_audio_commit_marks_stale_without_requesting_a_snapshot(data){
      hydrate();service.request(data.method,{action:data.action},function(){})
      compare(service.writes.length,1);reply(true);compare(status().stale,true);compare(service.writes.length,1)
    }
    function test_failed_actions_and_readonly_audio_paths_leave_freshness_unknown(){
      hydrate();service.request("dictation",{action:"continue"},function(){});reply(false);compare(status().stale,null)
      for(var method of ["snapshot","listen_state","dictation_state","dictation_draft","dictation_media","details","srs_catalogue"]){
        service.request(method,{},function(){});reply(true);compare(status().stale,null,method)
      }
      compare(service.writes.length,8)
    }
    function test_late_audio_result_cannot_dirty_a_different_account_cache(){
      hydrate();service.request("listen",{action:"rate"},function(){})
      var fresh=snapshot(2);fresh.session_epoch="01234567-89ab-4cde-8fab-0123456789ac"
      fresh.learning_digest.data_epoch=fresh.session_epoch
      service.applySnapshot(fresh);compare(status().stale,null)
      reply(true);compare(status().stale,null)
      compare(status().data_epoch,fresh.session_epoch)
      compare(service.writes.length,1)
    }
    function test_late_precommit_full_snapshot_cannot_clear_known_audio_staleness(){
      hydrate();var old=snapshot(2,1)
      service.request("listen",{action:"rate"},function(){});reply(true,{},2)
      compare(status().stale,true)
      service.applySnapshot(old);compare(status().stale,true)
      service.applySnapshot(snapshot(3,1));compare(status().stale,null)
    }
    function test_overlapping_results_keep_the_largest_causal_barrier(){
      hydrate();service.request("dictation",{action:"continue"},function(){});reply(true,{},4)
      service.request("listen",{action:"undo"},function(){});reply(true,{},2)
      service.applySnapshot(snapshot(4,1));compare(status().stale,true)
      service.applySnapshot(snapshot(5,1));compare(status().stale,null)
    }
    function test_newer_full_before_mutation_reply_already_includes_that_result(){
      hydrate();service.request("listen",{action:"rate"},function(){})
      service.applySnapshot(snapshot(3,1));compare(status().stale,null)
      reply(true,{},2);compare(status().stale,null)
    }
    function test_access_grant_change_does_not_erase_known_mutation_barrier(){
      hydrate();service.request("listen",{action:"rate"},function(){});reply(true,{},3)
      var restricted=snapshot(2,1);restricted.max_level=3
      service.applySnapshot(restricted);compare(status().stale,true)
      service.applySnapshot(snapshot(4,1));compare(status().stale,null)
    }
    function test_same_domain_old_worker_callback_cannot_apply_its_barrier(){
      hydrate();service.request("listen",{action:"rate"},function(){})
      var saved=service.callbacks[service.writes[0].id]
      service.restartWorker();service.receive(JSON.stringify({v:1,event:"ready",data:{version:"0.2.7"}}))
      service.applySnapshot(snapshot());saved(true,{},"",20)
      compare(status().stale,null)
    }
    function test_missing_or_invalid_mutation_barrier_is_conservative(){
      hydrate();service.request("listen",{action:"skip"},function(){});reply(true,{},true)
      service.applySnapshot(snapshot(30,1));compare(status().stale,true)
      service.restartWorker();service.receive(JSON.stringify({v:1,event:"ready",data:{version:"0.2.7"}}))
      service.applySnapshot(snapshot());compare(status().stale,null)
    }
    function test_clock_change_is_explicit_without_fabricating_new_timestamp(){
      hydrate();var original=status().generated_at
      service.snapshot=Object.assign({},service.snapshot,{status:"clock_changed"})
      compare(status().stale,true);compare(status().generated_at,original)
    }
  }
}
'''


def build(directory):
    build_adapter(directory)
    (directory / "tst_Preparation.qml").unlink()
    source = (ROOT / "Service.qml").read_text()
    status = re.search(r"(?ms)^    function status\(\): string \{.*?^    \}", source).group(0)
    core = directory / "ServiceCore.qml"
    core.write_text(core.read_text().rsplit("}", 1)[0]
        + '\nproperty var manifest:null\nfunction initialOrder(){return SessionState.initial()}\n' + status + "\n}\n")
    (directory / "tst_LearningDigestService.qml").write_text(QML)


@unittest.skipUnless(RUNNER.is_file(), "QtTest required")
class LearningDigestServiceTests(unittest.TestCase):
    def test_actual_service_cache_lifecycle_and_cli_boundary(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-digest-service-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=35,
                env={**os.environ,"TZ":"UTC","QT_QPA_PLATFORM":"offscreen","QT_QPA_PLATFORMTHEME":"","QT_QUICK_CONTROLS_STYLE":"Basic"})
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertNotIn("QWARN",result.stdout+result.stderr)
            raw=re.search(r"DIGEST_SERVICE (\{[^\n]+\})",result.stdout).group(1)
            with patch.object(helper.cli,"_call",return_value=raw) as call:
                value=helper.cli.status()
                call.assert_called_once()
            self.assertIsNotNone(value["learning_digest"])
            self.assertNotIn("PRIVATE",json.dumps(value["learning_digest"]))


if __name__ == "__main__":
    unittest.main()
