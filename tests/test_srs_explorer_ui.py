"""Actual native SRS Explorer with authored, delayed, read-only replies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation
import test_stock_palette_surfaces as palettes


ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER


def actual_pages():
    from test_srs_explorer import SrsExplorerTests
    from wanikani import progress
    fixture = SrsExplorerTests()
    fixture.setUp()
    try:
        fixture.fixture.subject(1, "radical", level=1)
        fixture.word(2, 0, level=2)
        for stage in range(1, 10):
            fixture.word(stage + 2, stage, level=stage)
        fixture.word(12, 3, available_at="malformed")
        fixture.protect(3)
        return [fixture.list(group=key, limit=24) for key, _ in progress.GROUPS]
    finally:
        fixture.tearDown()


QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme
Rectangle {
  width:800;height:3500;color:Color.background
  property var screen:null
  property var actualPages:__ACTUAL_PAGES__
  Component { id: pageComponent;Kani.SrsExplorer { width:290;controller:owner;navigationState:owner.saved;onNavigationChanged:function(state){owner.saved=state} } }
  QtObject {
    id:owner
    property var service:backend
    property bool opened:true
    property string contentAccess:"authored-account"
    property var saved:({})
    property var openedIds:[]
    property var snapshot:({})
    function showProgressSubject(id){openedIds=openedIds.concat([id])}
  }
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property bool hold:false
    property bool protectedCard:false
    property bool unknownProtection:false
    property bool partial:false
    property bool empty:false
    property var calls:[]
    property var pending:[]
    function stageLabel(stage){return stage<=4?"Apprentice "+stage:stage<=6?"Guru "+(stage-4):stage===7?"Master":stage===8?"Enlightened":"Burned"}
    function data(args){
      var stages=args.group==="apprentice"?[1,2,3,4]:args.group==="guru"?[5,6]:args.group==="master"?[7]:args.group==="enlightened"?[8]:args.group==="burned"?[9]:[]
      var stage=args.stage!==null?args.stage:stages.length?stages[0]:args.group==="unknown"?null:0
      var label=stage>0?stageLabel(stage):args.group==="locked"?"Locked":args.group==="lessons"?"Lesson ready":"Refresh progress"
      var total=empty?0:26,items=[]
      for(var index=args.offset;index<Math.min(total,args.offset+args.limit);index++){
        var protectedValue=unknownProtection||(protectedCard&&index===0)
        var next=args.group==="burned"||stage===0?null:"2026-09-05T14:00:00Z"
        items.push({id:index+1,type:args.subject_type||"kanji",level:args.level||1,
          characters:index===0?"山":"川",meaning:protectedValue?"":"Authored <b>literal</b> meaning "+(index+1),
          can_open:!protectedValue,spoilers_hidden:protectedValue,prerequisites:[],prerequisites_complete:true,
          status:{stage:stage,stage_name:label,group:args.group,unlocked_at:null,started_at:null,available_at:null,passed_at:null,burned_at:null,
            next_review_at:next,due:false,passed:index===2,pending:index===1,attention:index===3,pending_operations:index===1||index===3?1:0,
            label:index===1?"Waiting to sync":index===3?"Needs attention":label}})
      }
      return Object.assign({},args,{items:items,total:total,total_complete:!partial,complete:!partial,
        protection_complete:!unknownProtection,has_more:args.offset+args.limit<total,next_offset:args.offset+args.limit<total?args.offset+args.limit:null,
        levels:[{level:1,count:20},{level:2,count:6}],stages:stages.map(function(value){return {stage:value,label:stageLabel(value),count:6}}),
        last_sync:"2026-09-05T12:00:00Z",source:"cached_wanikani",scope:"Accessible cached subjects; confirmed current assignments"})
    }
    function request(method,args,callback){
      if(method!=="srs_catalogue")throw new Error("No overview, network, answer or detail reads from Explorer: "+method)
      var entry={method:method,args:args,callback:callback,data:data(args)}
      calls=calls.concat([entry]);if(hold)pending=pending.concat([entry]);else callback(true,entry.data,"")
    }
  }
  TestCase {
    name:"SrsExplorerUi";when:windowShown
    function init(){
      failOnWarning(/.*/)
      backend.ready=true;backend.locked=false;backend.hold=false;backend.protectedCard=false;backend.unknownProtection=false;backend.partial=false;backend.empty=false;backend.calls=[];backend.pending=[]
      owner.opened=true;owner.contentAccess="authored-account";owner.saved={};owner.openedIds=[]
      owner.snapshot={demo:false,max_level:60,last_sync:"old",session_epoch:"authored",session_revision:1,pending:0,attention:0,syncing:false,status:"online",state_revision:1}
      Color.background="#ffffff";Color.foreground="#222222";Color.accent="#006699";Color.urgent="#aa0000"
    }
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    function make(){screen=pageComponent.createObject(parent);verify(screen!==null);wait(1)}
    function settle(){tryVerify(function(){return !!screen.page&&!screen.loading});verify(waitForRendering(screen))}
    function item(name){var value=findChild(screen,name);verify(value!==null,name);return value}
    function click(name){var value=item(name);verify(value.visible&&value.enabled,name);value.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
    function reply(index,ok,data){var entry=backend.pending[index];backend.pending=backend.pending.slice(0,index).concat(backend.pending.slice(index+1));entry.callback(ok===undefined?true:ok,data||entry.data,ok===false?"Authored failure":"");wait(1)}
    function descendants(node){var result=[];for(var child of node.children){result.push(child);result=result.concat(descendants(child))};return result}
    function labels(){return descendants(screen).filter(function(node){return node.visible&&node.renderType===Text.NativeRendering&&typeof node.text==="string"})}
    function test_initial_request_is_single_bounded_catalogue_and_plain_content(){
      make();settle();compare(backend.calls.length,1)
      compare(backend.calls[0].args,{group:"apprentice",subject_type:null,level:null,stage:null,order:"level",offset:0,limit:24})
      compare(screen.rows.length,24);wait(20);compare(backend.calls.length,1)
      verify(labels().some(function(node){return node.text==="Authored <b>literal</b> meaning 1"&&node.textFormat===Text.PlainText}))
      verify(labels().some(function(node){return node.text==="Waiting to sync"}));verify(labels().some(function(node){return node.text==="New scheduling follows server confirmation."}))
      verify(labels().some(function(node){return node.text.indexOf("First passing recorded")===0}))
    }
    function test_native_group_and_faceted_filters_reset_pages_and_echo_navigation(){
      make();settle();click("srs-next");settle();compare(screen.offset,24)
      click("srs-group-guru");settle();compare(screen.group,"guru");compare(screen.offset,0)
      click("srs-refine");click("srs-type-vocabulary");settle();click("srs-stage-6");settle()
      click("srs-levels");click("srs-level-2");settle();click("srs-review-order");settle()
      compare(backend.calls[backend.calls.length-1].args,{group:"guru",subject_type:"vocabulary",level:2,stage:6,order:"next_review",offset:0,limit:24})
      compare(owner.saved,screen.selectionState());var count=backend.calls.length;owner.saved=Object.assign({},owner.saved);wait(20);compare(backend.calls.length,count)
      verify(labels().some(function(node){return node.text.indexOf("Uses confirmed cached review dates")===0}))
    }
    function test_details_navigation_and_recreation_preserve_exact_page(){
      owner.saved={group:"guru",subject_type:"vocabulary",level:2,stage:5,order:"next_review",offset:24};make();settle()
      click("srs-open-25");compare(owner.openedIds,[25]);compare(owner.saved.offset,24)
      screen.destroy();screen=null;wait(1);make();settle();compare(backend.calls.length,2)
      compare(screen.selectionState(),owner.saved);compare(screen.page.offset,24)
    }
    function test_invalid_saved_navigation_is_normalized_without_private_echo(){
      owner.saved={group:"not-a-group",level:99,stage:9,subject_type:"notes",order:"raw",offset:-1};make();settle()
      compare(screen.selectionState(),{group:"apprentice",subject_type:null,level:null,stage:null,order:"level",offset:0})
    }
    function test_external_navigation_normalization_does_not_write_inside_its_binding(){
      make();settle()
      owner.saved={group:"guru",subject_type:null,level:61,stage:4,order:"next_review",offset:24}
      settle();compare(screen.selectionState(),{group:"guru",subject_type:null,level:null,stage:null,order:"next_review",offset:24})
      compare(owner.saved,screen.selectionState());compare(backend.calls.length,2)
      owner.snapshot=Object.assign({},owner.snapshot,{max_level:3});owner.contentAccess="new-grant";owner.saved={}
      settle();compare(owner.saved,screen.selectionState());compare(screen.group,"apprentice");compare(screen.offset,0)
    }
    function test_all_canonical_groups_and_stage_reset(){
      make();settle();screen.chooseStage(3);settle()
      for(var group of screen.groups){screen.chooseGroup(group.key);settle();compare(screen.page.group,group.key);compare(screen.stage,null)}
      compare(backend.calls.length,10)
    }
    function test_real_backend_pages_validate_and_render_every_canonical_group(){
      make();settle()
      for(var value of actualPages){
        screen.group=value.group
        verify(screen.valid(value,{group:value.group,subject_type:null,level:null,stage:null,order:"level",offset:0}),value.group)
        screen.page=value;wait(1);verify(waitForRendering(screen))
      }
    }
    function test_protected_answers_counts_and_open_controls(){
      backend.protectedCard=true;make();settle();compare(screen.page.total,26);compare(screen.hiddenCount,1)
      verify(item("srs-protection").text.indexOf("remain included in the counts")>=0)
      verify(!item("srs-open-1").enabled);screen.openSubject(1);compare(owner.openedIds,[])
      verify(!labels().some(function(node){return node.text==="Authored <b>literal</b> meaning 1"}))
      screen.openSubject(2);compare(owner.openedIds,[2]);screen.openSubject(999);compare(owner.openedIds,[2])
    }
    function test_partial_metadata_and_unknown_protection_are_distinct(){
      backend.partial=true;backend.unknownProtection=true;make();settle()
      verify(item("srs-partial").visible);verify(item("srs-protection").text.indexOf("could not be checked")>=0)
      verify(screen.rows.every(function(row){return row.spoilers_hidden&&!row.can_open&&row.meaning===""}))
      screen.openSubject(1);compare(owner.openedIds,[])
    }
    function test_empty_page_is_success_and_retry_only_follows_explicit_action(){
      backend.empty=true;make();settle();verify(item("srs-empty").visible);compare(screen.error,"")
      backend.hold=true;click("srs-refresh");reply(0,false);verify(!screen.loading);verify(screen.error.length>0)
      var calls=backend.calls.length;wait(20);compare(backend.calls.length,calls)
      backend.hold=false;click("srs-refresh");settle()
    }
    function test_hidden_closed_locked_unready_do_not_read_data(){return ["hidden","closed","locked","unready"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_hidden_closed_locked_unready_do_not_read(data){
      if(data.edge==="closed")owner.opened=false;if(data.edge==="locked")backend.locked=true;if(data.edge==="unready")backend.ready=false
      screen=pageComponent.createObject(parent,{visible:data.edge!=="hidden"});verify(screen!==null);wait(20);screen.fetch();compare(backend.calls.length,0)
    }
    function test_late_request_cannot_own_new_filter_loading(){
      backend.hold=true;make();compare(backend.pending.length,1);screen.chooseGroup("guru");verify(screen.loading)
      reply(0);compare(screen.page,null);verify(screen.loading);compare(backend.pending.length,1);compare(backend.pending[0].args.group,"guru")
      reply(0);settle();compare(screen.group,"guru");compare(backend.calls.length,2)
    }
    function test_restart_releases_request_and_late_old_reply_does_not_clear_new_loading(){
      backend.hold=true;make();backend.ready=false;backend.ready=true;wait(1);compare(backend.pending.length,2)
      reply(0);compare(screen.page,null);verify(screen.loading);reply(0);settle()
    }
    function test_access_reset_and_partial_sync_drop_rows_immediately(){
      owner.saved={group:"guru",level:20,stage:null,subject_type:null,order:"level",offset:24};make();settle();backend.hold=true
      owner.snapshot=Object.assign({},owner.snapshot,{max_level:3});owner.contentAccess="grant-three";compare(screen.rows.length,0);compare(screen.level,null);compare(screen.offset,0)
      wait(1);reply(0);settle();owner.snapshot=Object.assign({},owner.snapshot,{syncing:true});compare(screen.rows.length,0);wait(1);reply(0);settle()
      owner.snapshot=Object.assign({},owner.snapshot,{syncing:false,status:"offline"});compare(screen.rows.length,0);wait(1);reply(0);settle();compare(owner.snapshot.last_sync,"old")
    }
    function test_unrelated_revision_palette_and_disclosures_never_fetch(){
      make();settle();var count=backend.calls.length;owner.snapshot=Object.assign({},owner.snapshot,{state_revision:99})
      click("srs-refine");click("srs-levels");Color.background="#171717";Color.foreground="#eeeeee";wait(20);compare(backend.calls.length,count)
    }
    function test_malformed_or_answer_bearing_reply_is_rejected_data(){return ["filter","duplicate","reading","facet","protection","date","pagination"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_malformed_or_answer_bearing_reply_is_rejected(data){
      backend.hold=true;make();var value=backend.pending[0].data
      if(data.edge==="filter")value.group="guru"
      if(data.edge==="duplicate")value.items[1].id=value.items[0].id
      if(data.edge==="reading")value.items[0].readings=["PRIVATE"]
      if(data.edge==="facet")value.levels=[{level:61,count:1}]
      if(data.edge==="protection")value.protection_complete=false
      if(data.edge==="date")value.items[0].status.next_review_at="not-a-date"
      if(data.edge==="pagination")value.next_offset=25
      reply(0,true,value);compare(screen.page,null);verify(screen.error.length>0);verify(!screen.loading)
    }
    function test_late_reply_after_hidden_or_destroyed_view_never_opens_data(){return [{tag:"hidden",destroy:false},{tag:"destroyed",destroy:true}]}
    function test_late_reply_after_hidden_or_destroyed_view_never_opens(data){
      backend.hold=true;make();if(data.destroy){screen.destroy();screen=null;wait(1)}else screen.visible=false
      reply(0);compare(backend.calls.length,1);compare(owner.openedIds,[])
    }
    __PALETTE_CHECKS__
    function test_narrow_native_stock_palettes_data(){return paletteData()}
    function test_narrow_native_stock_palettes(data){
      make();settle();click("srs-refine");click("srs-levels");var calls=backend.calls.length
      applyPalette(data);checkText(screen,data.tag+" explorer");checkButtons(screen,data.tag+" explorer")
      for(var label of labels()){verify(!label.truncated,label.text);verify(label.contentWidth<=label.width+1,"Fits: "+label.text)}
      compare(backend.calls.length,calls);screen.focusInput();verify(item("srs-group-"+screen.group).activeFocus)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Native Qt controls required")
class SrsExplorerUiTests(unittest.TestCase):
    def test_actual_explorer_and_native_keyboard_controls(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-srs-explorer-") as temporary:
            directory = Path(temporary)
            foundation.build(directory)
            (directory / "tst_LessonFlow.qml").unlink()
            shutil.copyfile(ROOT / "qml/SrsExplorer.qml", directory / "qml/SrsExplorer.qml")
            palettes.pure_native_style(directory)
            checks = palettes.CHECKS.replace("__PALETTES__", json.dumps(palettes.palettes()))
            source = QML.replace("__PALETTE_CHECKS__", checks).replace("__ACTUAL_PAGES__", json.dumps(actual_pages()))
            (directory / "tst_SrsExplorer.qml").write_text(source)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=60, env={**os.environ,
                    "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic",
                    "TZ": "UTC", "LC_ALL": "C.UTF-8"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
