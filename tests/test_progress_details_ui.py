"""Actual detail editor reauthorizes progress-origin refreshes with inert IO."""
import os
from pathlib import Path
import tempfile
import unittest

import test_lesson_flow_ui as foundation
import test_stock_palette_surfaces as palettes


QML = r'''
import QtQuick
import QtTest
import "qml" as Kani

Rectangle {
  width:600;height:2000;color:"white"
  property var screen:null
  Component {id:component;Kani.SubjectDetails {width:350;controller:owner;subject:owner.detail;editable:true}}
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property var calls:[]
    property var pending:[]
    signal snapshotChanged()
    function request(method,args,callback){
      calls=calls.concat([{method:method,args:args}])
      if(method==="editor_draft"){callback(true,{dirty:true},"");return}
      pending=pending.concat([{method:method,args:args,callback:callback}])
    }
  }
  QtObject {
    id:owner
    property var service:backend
    property bool opened:true
    property bool busy:false
    property string view:"lookup"
    property string contentAccess:"authored-account"
    property string progressContext:"confirmed-one"
    property bool progressReturn:true
    property int navigationSequence:1
    property var progressNavigation:({group:"guru",offset:24})
    property var detail:null
    property string error:""
    property string query:"authored manual lookup"
    property var routes:[]
    function call(method,args,callback){backend.request(method,args,callback)}
    function search(text){routes=routes.concat(["search:"+text])}
    function returnToProgress(){routes=routes.concat(["progress"]);view="progress";navigationSequence++;detail=null;progressReturn=false}
  }
  TestCase {
    name:"ProgressDetailsUi";when:windowShown
    function data(label){return {id:101,type:"vocabulary",characters:"山",meanings:[label||"Authored mountain"],readings:[],
      components:[],related:[],visually_similar:[],sentences:[],meaning_mnemonic:"",reading_mnemonic:"",meaning_hint:"",reading_hint:"",audio:[],audio_available:false,
      material:{meaning_synonyms:[],meaning_note:"Original note",reading_note:""},editor_dirty:false,material_pending:false}}
    function make(){owner.detail=data();screen=component.createObject(parent);verify(screen!==null);wait(1)}
    function item(name){var value=findChild(screen,name);verify(value!==null,name);return value}
    function reply(index,ok,value,message){var entry=backend.pending[index];backend.pending=backend.pending.slice(0,index).concat(backend.pending.slice(index+1));entry.callback(ok,value,message||"");wait(1)}
    function init(){
      failOnWarning(/.*/)
      backend.ready=true;backend.locked=false;backend.calls=[];backend.pending=[]
      owner.service=backend;owner.opened=true;owner.busy=false;owner.view="lookup";owner.contentAccess="authored-account";owner.progressContext="confirmed-one"
      owner.progressReturn=true;owner.navigationSequence=1;owner.progressNavigation={group:"guru",offset:24};owner.detail=null;owner.error="";owner.routes=[]
    }
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    function test_snapshot_uses_atomic_guarded_read_and_publishes_current_result(){
      make();compare(backend.calls.length,0);backend.snapshotChanged()
      compare(backend.calls,[{method:"progress_details",args:{subject_id:101}}])
      reply(0,true,data("Fresh guarded word"));compare(owner.detail.meanings,["Fresh guarded word"])
      verify(!screen.refreshingDetails);compare(owner.routes,[])
    }
    function test_manual_lookup_retains_ordinary_detail_route_and_policy(){
      owner.progressReturn=false;make();backend.snapshotChanged();compare(backend.calls[0].method,"details")
      owner.progressContext="irrelevant-progress-change"
      reply(0,true,data("Manual detail"));compare(owner.detail.meanings,["Manual detail"])
      backend.snapshotChanged();reply(0,false,null,"Authored inaccessible manual word")
      compare(owner.detail,null);compare(owner.routes,["search:authored manual lookup"])
    }
    function test_current_guard_failure_returns_to_preserved_progress_instead_of_manual_search(){
      make();var saved=JSON.stringify(owner.progressNavigation);backend.snapshotChanged();reply(0,false,null,"Kept for saved graded work")
      compare(owner.view,"progress");compare(owner.detail,null);compare(owner.routes,["progress"])
      compare(owner.error,"Kept for saved graded work");compare(JSON.stringify(owner.progressNavigation),saved)
    }
    function test_late_refresh_after_context_change_never_rehydrates_answers_data(){return ["access","progress","navigation","origin","view","closed","locked","unready","subject"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_late_refresh_after_context_change_never_rehydrates_answers(row){
      make();backend.snapshotChanged()
      if(row.edge==="access")owner.contentAccess="different-account"
      if(row.edge==="progress")owner.progressContext="new-saved-work"
      if(row.edge==="navigation")owner.navigationSequence++
      if(row.edge==="origin")owner.progressReturn=false
      if(row.edge==="view")owner.view="help"
      if(row.edge==="closed")owner.opened=false
      if(row.edge==="locked")backend.locked=true
      if(row.edge==="unready")backend.ready=false
      if(row.edge==="subject")owner.detail=Object.assign(data("Different word"),{id:102})
      var kept=JSON.stringify(owner.detail);reply(0,true,data("STALE ANSWER"))
      compare(JSON.stringify(owner.detail),kept);compare(owner.routes,[])
    }
    function test_old_reply_cannot_release_or_overwrite_a_newer_refresh(){
      make();backend.snapshotChanged();owner.progressContext="new-progress";backend.snapshotChanged()
      compare(backend.pending.length,2);verify(screen.refreshingDetails)
      reply(0,true,data("OLD"));verify(screen.refreshingDetails);compare(owner.detail.meanings,["Authored mountain"])
      reply(0,true,data("NEW"));verify(!screen.refreshingDetails);compare(owner.detail.meanings,["NEW"])
    }
    function test_worker_restart_allows_new_refresh_without_waiting_for_old_reply(){
      make();backend.snapshotChanged();backend.ready=false;backend.ready=true;backend.snapshotChanged()
      compare(backend.pending.length,2);reply(0,true,data("OLD"));verify(screen.refreshingDetails)
      reply(0,true,data("Restarted"));compare(owner.detail.meanings,["Restarted"])
    }
    function test_closed_locked_unready_or_readonly_views_do_not_refresh_data(){return ["closed","locked","unready","readonly"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_closed_locked_unready_or_readonly_views_do_not_refresh(row){
      make();if(row.edge==="closed")owner.opened=false;if(row.edge==="locked")backend.locked=true;if(row.edge==="unready")backend.ready=false;if(row.edge==="readonly")screen.editable=false
      backend.snapshotChanged();compare(backend.calls,[])
    }
    function test_guarded_material_success_rehydrates_only_a_fresh_safe_projection_data(){return [{tag:"save",action:"save"},{tag:"discard",action:"discard"}]}
    function test_guarded_material_success_rehydrates_only_a_fresh_safe_projection(row){
      make();item("editor-meaning-note").text="Saved local draft";var generation=screen.editGeneration
      if(row.action==="save")screen.saveEditor();else screen.discardEditor()
      compare(backend.pending[0].method,row.action==="save"?"set_material":"editor_discard")
      reply(0,true,data("RAW COMMAND ANSWER"))
      compare(owner.detail.meanings,["Authored mountain"]);compare(backend.pending[0].method,"progress_details")
      compare(item("editor-meaning-note").text,"Saved local draft")
      var safe=data("Fresh guarded projection");safe.material.meaning_note="Confirmed note"
      reply(0,true,safe);compare(owner.detail.meanings,["Fresh guarded projection"])
      compare(item("editor-meaning-note").text,"Confirmed note")
    }
    function test_failed_material_command_never_fetches_or_replaces_current_detail_data(){return [{tag:"save",action:"save"},{tag:"discard",action:"discard"}]}
    function test_failed_material_command_never_fetches_or_replaces_current_detail(row){
      make();if(row.action==="save")screen.saveEditor();else screen.discardEditor();var before=JSON.stringify(owner.detail)
      reply(0,false,null,"Authored command failure")
      compare(backend.pending,[]);compare(JSON.stringify(owner.detail),before);compare(owner.routes,[])
    }
    function test_guarded_material_reply_from_an_old_context_never_requests_another_read(){
      make();screen.saveEditor();owner.progressContext="new-context";reply(0,true,data("RAW OLD COMMAND"))
      compare(backend.pending,[]);compare(owner.detail.meanings,["Authored mountain"])
    }
    function test_manual_material_success_keeps_established_direct_reply_policy_data(){return [{tag:"save",action:"save"},{tag:"discard",action:"discard"}]}
    function test_manual_material_success_keeps_established_direct_reply_policy(row){
      owner.progressReturn=false;make();if(row.action==="save")screen.saveEditor();else screen.discardEditor()
      reply(0,true,data("Manual command result"));compare(owner.detail.meanings,["Manual command result"]);compare(backend.pending,[])
    }
    function test_newer_unsaved_draft_survives_the_guarded_material_refresh(){
      make();var note=item("editor-meaning-note");note.text="First saved draft";screen.saveEditor();reply(0,true,data("Raw response"))
      note.text="A newer unsaved draft";var fresh=data("Guarded answer");fresh.material.meaning_note="First saved draft"
      reply(0,true,fresh);compare(owner.detail.meanings,["Guarded answer"]);compare(note.text,"A newer unsaved draft")
      verify(screen.editorDirty)
    }
    function test_guarded_material_refresh_failure_preserves_navigation_and_never_applies_raw_answer(){
      make();screen.saveEditor();reply(0,true,data("RAW COMMAND ANSWER"));reply(0,false,null,"A new graded session protects this answer")
      compare(owner.detail,null);compare(owner.view,"progress");compare(owner.routes,["progress"])
      compare(owner.progressNavigation,{group:"guru",offset:24})
    }
    function test_destroyed_editor_discards_late_refresh(){
      make();backend.snapshotChanged();screen.destroy();screen=null;wait(1);reply(0,true,data("Destroyed reply"))
      compare(owner.detail.meanings,["Authored mountain"]);compare(owner.routes,[])
    }
  }
}
'''


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    palettes.pure_native_style(directory)
    (directory / "tst_ProgressDetails.qml").write_text(QML)


@unittest.skipUnless(foundation.RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Qt and native controls required")
class ProgressDetailsUiTests(unittest.TestCase):
    def test_actual_editor_refreshes_use_current_origin_and_preserve_drafts(self):
        import subprocess
        with tempfile.TemporaryDirectory(prefix="wanikani-progress-details-ui-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(foundation.RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=35, env={**os.environ,
                    "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
