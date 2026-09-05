"""Actual dictation adapter, inert player signals and ordered authored RPC.

No decoder, audio device, account, network or desktop service is instantiated.
The mock commits requests on receipt, while replies can be delayed/reordered.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
QML = r'''
import QtQuick
import QtTest
import QtMultimedia

Item {
  QtObject {
    id: owner
    property var service: backend
    property bool opened: false
    property string view: "dictation"
    property string contentAccess: "authored-account"
    property int navigationSequence: 0
    property var snapshot: ({})
    property int audioSequence: 0
    property string audioContext: ""
    property string audioState: ""
    property string audioNotice: ""
    function stopAudio() { core.cancelAudio(); audioSequence++; player.stop(); audioContext="" }
  }
  QtObject {
    id: player
    property url source: ""
    property int playbackState: MediaPlayer.StoppedState
    property int mediaStatus: MediaPlayer.NoMedia
    property int plays: 0
    signal errorOccurred(int code, string message)
    function play() { plays++ }
    function stop() { playbackState=MediaPlayer.StoppedState }
  }
  QtObject {
    id: backend
    property bool ready: true
    property bool locked: false
    property bool hold: false
    property var pending: []
    property var calls: []
    property var session: null
    property int mediaCount: 0
    property int heardCount: 0
    property int draftCount: 0
    property string currentToken: ""
    function clone(value) { return JSON.parse(JSON.stringify(value)) }
    function request(method,args,callback) {
      var ok=true, result=null, message=""
      if(method==="dictation_state") {
        result={status:{available:2,new_remaining:5,local_only:true},session:clone(session)}
      } else if(method==="dictation_media") {
        mediaCount++;currentToken="playback-"+mediaCount
        session=Object.assign({},session,{revision:session.revision+1})
        result={handle:session.media_handle,uri:"file:///tmp/authored-opaque.mp3",voice:"Authored player fixture",
          playback_token:currentToken,session_id:session.id,revision:session.revision,session:clone(session)}
      } else if(method==="dictation_draft") {
        draftCount++
        session=Object.assign({},session,{draft:args.text,draft_cursor:args.cursor,preedit:args.preedit,draft_revision:draftCount})
        result={saved:true,session_id:session.id,handle:session.media_handle,draft_revision:draftCount}
      } else if(method==="dictation") {
        if(args.session_id!==session.id || args.revision!==session.revision) {
          ok=false;message="Authored stale session rejection"
        } else if(args.action==="heard") {
          if(args.handle!==session.media_handle || args.playback_token!==currentToken) {
            ok=false;message="Authored stale playback rejection"
          } else {
            heardCount++;currentToken=""
            session=Object.assign({},session,{revision:session.revision+1,heard:true})
          }
        } else if(args.action==="check") {
          session=Object.assign({},session,{revision:session.revision+1,draft:args.text,
            draft_cursor:args.text.length,input_error:"Retryable authored input",preedit:""})
        } else if(args.action==="skip") {
          session=Object.assign({},session,{revision:session.revision+1,index:1,media_handle:"opaque-second",heard:false,draft:""})
        } else throw new Error("Unexpected action: "+args.action)
        result={duplicate:false,session:clone(session)}
      } else throw new Error("Unexpected method: "+method)
      var entry={method:method,args:clone(args),callback:callback,ok:ok,data:result,message:message}
      calls=calls.concat([entry])
      if(hold) pending=pending.concat([entry]); else callback(ok,result,message)
    }
  }
  DictationState { id: core; controller: owner; player: player }
  TestCase {
    name: "DictationStateLifecycle"; when: windowShown
    function init() {
      failOnWarning(/.*/)
      owner.opened=false;wait(1)
      backend.ready=true;backend.locked=false;backend.hold=false;backend.pending=[];backend.calls=[]
      backend.mediaCount=0;backend.heardCount=0;backend.draftCount=0;backend.currentToken=""
      owner.view="dictation";owner.contentAccess="authored-account";owner.navigationSequence=0
      owner.snapshot={last_sync:"old",session_revision:1,pending:0,attention:0,syncing:false,status:"online",state_revision:1}
      player.source="";player.playbackState=MediaPlayer.StoppedState;player.mediaStatus=MediaPlayer.NoMedia;player.plays=0
      backend.session={id:"authored-session",revision:1,phase:"question",index:0,total:2,started_at:"2026-09-05T00:00:00Z",
        media_handle:"opaque-first",heard:false,draft:"",draft_cursor:0,preedit:"",draft_revision:0,input_error:"",
        subject:null,feedback:null,summary:{matched:0,again:0,skipped:0},undo_available:false,local_only:true,intervals:null}
      owner.opened=true;tryVerify(function(){return core.session!==null&&!core.loading})
      compare(backend.calls.length,1);compare(backend.calls[0].method,"dictation_state");compare(player.plays,0)
    }
    function cleanup() { owner.opened=false;wait(1);backend.pending=[] }
    function reply(index, ok, data, message) {
      var entry=backend.pending[index]
      verify(!!entry,"Pending callback "+index)
      backend.pending=backend.pending.slice(0,index).concat(backend.pending.slice(index+1))
      entry.callback(ok===undefined?entry.ok:ok,data===undefined?entry.data:data,message===undefined?entry.message:message)
      wait(1)
    }
    function play() { core.play();verify(core.ticket!==null);compare(player.plays,1) }
    function started() { player.mediaStatus=MediaPlayer.LoadedMedia;player.playbackState=MediaPlayer.PlayingState;verify(core.ticket.started) }
    function ended() { player.mediaStatus=MediaPlayer.EndOfMedia;player.playbackState=MediaPlayer.StoppedState;wait(1) }
    function heard() { play();started();ended();verify(core.heard);verify(core.canCheck) }
    function test_end_without_current_playing_does_not_acknowledge() {
      play();ended();compare(backend.heardCount,0);verify(!core.canCheck)
      player.mediaStatus=MediaPlayer.LoadedMedia;started();ended()
      compare(backend.heardCount,1);verify(core.canCheck)
    }
    function test_replay_uses_new_token_without_counting_another_completion() {
      heard();core.play();verify(core.ticket!==null);compare(core.ticket.token,"playback-2")
      started();ended();compare(backend.mediaCount,2);compare(backend.heardCount,1);verify(core.heard)
      compare(backend.calls.filter(function(c){return c.method==="dictation"&&c.args.action==="heard"})[0].args.playback_token,"playback-1")
    }
    function test_wrong_media_reply_never_starts_a_player_data() {
      return ["handle","session","revision","uri"].map(function(edge){return {tag:edge,edge:edge}})
    }
    function test_wrong_media_reply_never_starts_a_player(data) {
      backend.hold=true;core.play();var value=backend.clone(backend.pending[0].data)
      if(data.edge==="handle")value.handle="foreign-clip"
      if(data.edge==="session")value.session.id="foreign-session"
      if(data.edge==="revision")value.revision++
      if(data.edge==="uri")value.uri="https://example.invalid/no-request"
      reply(0,true,value);compare(player.plays,0);compare(core.ticket,null);verify(core.error.length>0)
      compare(backend.pending.length,1);compare(backend.pending[0].method,"dictation_state");reply(0)
      verify(!core.loading);compare(core.session.revision,backend.session.revision)
    }
    function test_rejected_completion_reloads_without_claiming_heard_or_replaying() {
      play();started();backend.currentToken="replaced-token";ended()
      compare(backend.heardCount,0);verify(!core.heard);verify(!core.canCheck)
      verify(core.error.length>0);compare(player.plays,1)
      compare(backend.calls[backend.calls.length-1].method,"dictation_state")
    }
    function test_stop_error_and_foreign_source_never_finish_data() {
      return ["stop","error","source","panel-sequence"].map(function(edge){return {tag:edge,edge:edge}})
    }
    function test_stop_error_and_foreign_source_never_finish(data) {
      play();started()
      if(data.edge==="stop")owner.stopAudio()
      if(data.edge==="error")player.errorOccurred(1,"Authored decoder failure")
      if(data.edge==="source")player.source="file:///tmp/different-opaque.mp3"
      if(data.edge==="panel-sequence")owner.audioSequence++
      ended();compare(backend.heardCount,0);verify(!core.heard)
    }
    function test_pending_media_late_reply_drops_after_context_change_data() {
      return ["close","lock","restart","navigation","access","pending","clock"].map(function(edge){return {tag:edge,edge:edge}})
    }
    function test_pending_media_late_reply_drops_after_context_change(data) {
      backend.hold=true;core.play();compare(backend.pending.length,1)
      if(data.edge==="close"){owner.opened=false;owner.opened=true}
      if(data.edge==="lock"){backend.locked=true;backend.locked=false}
      if(data.edge==="restart"){backend.ready=false;backend.ready=true}
      if(data.edge==="navigation")owner.navigationSequence++
      if(data.edge==="access")owner.contentAccess="another-authored-account"
      if(data.edge==="pending")owner.snapshot=Object.assign({},owner.snapshot,{pending:1})
      if(data.edge==="clock")owner.snapshot=Object.assign({},owner.snapshot,{status:"clock_changed"})
      wait(1);reply(0);compare(player.plays,0);compare(core.ticket,null)
      verify(backend.calls.slice(2).every(function(c){return c.method==="dictation_state"}))
      while(backend.pending.length)reply(0)
      verify(!core.loading);compare(core.session.revision,backend.session.revision)
    }
    function test_cancel_pending_media_recovers_before_next_action_without_replay() {
      backend.hold=true;core.play();owner.stopAudio();verify(core.audioRecovering)
      core.check("かな");core.skip();compare(backend.calls.length,2)
      wait(1);compare(backend.calls.length,3);compare(backend.calls[2].method,"dictation_state")
      reply(0);compare(player.plays,0);reply(0)
      verify(!core.audioRecovering);verify(!core.loading);compare(core.session.revision,2)
      compare(backend.mediaCount,1);compare(backend.heardCount,0)
    }
    function test_cancel_pending_completion_recovers_committed_heard_state() {
      play();started();backend.hold=true;ended();verify(core.heardBusy);compare(backend.heardCount,1)
      owner.stopAudio();verify(core.audioRecovering);wait(1)
      compare(backend.pending.length,2);reply(0);verify(!core.heard);reply(0)
      verify(core.heard);verify(core.canCheck);compare(backend.heardCount,1);compare(player.plays,1)
    }
    function test_old_completion_reply_cannot_replace_newer_refresh() {
      play();started();backend.hold=true;ended()
      var old=backend.pending[0];backend.pending=[]
      owner.navigationSequence++;wait(1)
      backend.session=Object.assign({},backend.session,{revision:20,draft:"newer"})
      // The held state reply was read before this edit; replace it with the
      // later authoritative read to exercise old completion ordering directly.
      reply(0,true,{status:{available:1},session:backend.clone(backend.session)})
      compare(core.session.revision,20)
      old.callback(true,old.data,"");wait(1);compare(core.session.revision,20);compare(core.session.draft,"newer")
    }
    function test_partial_sync_end_refreshes_even_with_unchanged_last_sync() {
      play();started();owner.snapshot=Object.assign({},owner.snapshot,{syncing:true})
      tryVerify(function(){return !core.loading&&core.session!==null});compare(core.ticket,null)
      var reads=backend.calls.filter(function(c){return c.method==="dictation_state"}).length
      backend.session=Object.assign({},backend.session,{unavailable:"Authored hidden subject",media_handle:null,heard:false,subject:null,feedback:null})
      owner.snapshot=Object.assign({},owner.snapshot,{syncing:false,status:"offline"})
      tryVerify(function(){return core.session&&core.session.unavailable==="Authored hidden subject"})
      compare(backend.calls.filter(function(c){return c.method==="dictation_state"}).length,reads+1)
      compare(owner.snapshot.last_sync,"old");compare(player.plays,1);compare(core.ticket,null)
    }
    function test_unrelated_snapshot_revision_keeps_current_playback() {
      play();started();var calls=backend.calls.length;var saved=core.ticket
      owner.snapshot=Object.assign({},owner.snapshot,{state_revision:99})
      wait(20);compare(core.ticket,saved);verify(core.playing);compare(backend.calls.length,calls)
    }
    function test_drafts_precede_retryable_check_and_late_ack_cannot_replace_text() {
      heard();backend.hold=true
      core.saveDraft("old",3,"");core.saveDraft("newer",5,"");core.check("final?")
      compare(backend.calls.slice(-3).map(function(c){return c.method}),["dictation_draft","dictation_draft","dictation"])
      compare(backend.session.draft,"final?");compare(backend.session.phase,"question")
      reply(2);compare(core.session.draft,"final?")
      core.saveDraft("newest",6,"");compare(backend.session.draft,"newest")
      reply(2);compare(core.draftError,"")
      reply(0,false,null,"Older draft failure");reply(0,false,null,"Another stale failure")
      compare(core.draftError,"");compare(backend.session.draft,"newest")
      wait(30);compare(backend.calls.filter(function(c){return c.method==="dictation_draft"}).length,3)
    }
    function test_playback_ack_applies_metadata_without_overwriting_newer_draft() {
      play();started();backend.hold=true;ended();core.saveDraft("newer",5,"preedit")
      compare(backend.session.draft,"newer");reply(1);reply(0)
      verify(core.heard);compare(core.draftError,"");compare(backend.session.draft,"newer")
      // The adapter intentionally never exposes an input-write command from
      // draft acknowledgments; the view keeps its separate current buffer.
      compare(backend.calls.filter(function(c){return c.method==="dictation_draft"}).length,1)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "Qt test runner required")
class DictationStateTests(unittest.TestCase):
    def test_actual_state_with_inert_player_and_delayed_ordered_rpc(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-dictation-state-") as temporary:
            directory = Path(temporary)
            shutil.copyfile(ROOT / "qml/DictationState.qml", directory / "DictationState.qml")
            (directory / "tst_DictationState.qml").write_text(QML)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=40, env={**os.environ,
                    "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
