"""Actual native reading-trail practice picker with authored inert previews."""
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
QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme
Rectangle {
  id:surface;width:322;height:1600;color:Color.background
  readonly property color kaniSurface:color
  property var page:null
  property string passage:"火山、山と川。"
  property var matches:[]
  property var saved:null
  property var saves:[]
  property var starts:[]
  Component {id:component;Kani.TrailPractice {x:16;y:16;width:290;controller:owner;passage:surface.passage;matches:surface.matches;savedSelection:surface.saved;
    onSelectionSaved:function(state){surface.saves=surface.saves.concat([state]);surface.saved=state}
    onStartRequested:function(value,replace){surface.starts=surface.starts.concat([{preview:value,replace:replace}])}}}
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property var requests:[]
    property var pending:[]
    function request(method,args,callback){
      if(method!=="trail_practice_preview")throw new Error("Only local readonly preview is allowed")
      requests=requests.concat([{method:method,args:args}]);pending=pending.concat([{args:args,callback:callback}])
    }
  }
  QtObject {
    id:alternateBackend
    property bool ready:true
    property bool locked:false
    function request(method,args,callback){backend.request(method,args,callback)}
  }
  QtObject {
    id:owner
    property var service:backend
    property bool opened:true
    property bool busy:false
    property string view:"lookup"
    property var detail:null
    property string contentAccess:"authored-account"
    property int navigationSequence:1
    property var snapshot:({})
    property var resumes:[]
    function begin(mode,size){resumes=resumes.concat([{mode:mode,size:size}])}
  }
  TestCase {
    name:"TrailPracticeUi";when:windowShown
    function word(id,characters,open){return {id:id,characters:characters,type:"vocabulary",level:1,state:open===false?"Paused graded work":"Learned",can_open:open!==false}}
    function rows(){return [word(101,"火山"),word(102,"山"),word(103,"川",false)]}
    function make(){page=component.createObject(surface);verify(page!==null);wait(1)}
    function item(name){var found=findChild(page,name);verify(found!==null,name);return found}
    function click(name){var button=item(name);verify(button.visible&&button.enabled,name);button.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
    function open(){click("trail-practice-choose")}
    function choose(id){click("trail-practice-word-"+id)}
    function pending(count){tryVerify(function(){return backend.pending.length===count},1000)}
    function result(args){return {text:args.text,subject_ids:args.subject_ids.slice(),data_epoch:owner.snapshot.session_epoch,
      items:args.subject_ids.map(function(id){var value=surface.matches.find(function(word){return word.id===id});return {id:id,type:value.type,level:value.level,characters:value.characters,state:value.state,ready:true,reason:"ready"}}),
      total:args.subject_ids.length,ready_count:args.subject_ids.length,can_start:true,trail_truncated:false,protection_complete:true,
      saved_practice:{present:false,valid:true,completed:0,total:0,revision:null},requires_practice_choice:false,scope:"ungraded_practice",effect:"preview_only"}}
    function reply(index,value,ok){var entry=backend.pending[index];backend.pending=backend.pending.slice(0,index).concat(backend.pending.slice(index+1));entry.callback(ok!==false,value===undefined?result(entry.args):value,"PRIVATE FAILURE");wait(1)}
    function init(){
      failOnWarning(/.*/);backend.ready=true;backend.locked=false;backend.requests=[];backend.pending=[]
      owner.service=backend;owner.opened=true;owner.busy=false;owner.view="lookup";owner.detail=null;owner.contentAccess="authored-account";owner.navigationSequence=1;owner.resumes=[]
      owner.snapshot={session_epoch:"01234567-89ab-cdef-0123-456789abcdef",session_revision:1,last_sync:"old",pending:0,attention:0,max_level:60}
      surface.passage="火山、山と川。";surface.matches=rows();surface.saved=null;surface.saves=[];surface.starts=[]
      Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"
    }
    function cleanup(){if(page)page.destroy();page=null;wait(1)}
    function test_collapsed_and_unselected_picker_never_reads_or_starts(){
      make();verify(!page.expanded);wait(180);compare(backend.requests,[])
      open();wait(180);compare(backend.requests,[]);verify(!item("trail-practice-start").enabled)
      compare(page.words.length,2);compare(findChild(page,"trail-practice-word-103"),null);compare(surface.starts,[])
      page.focusInput();verify(item("trail-practice-word-101").activeFocus)
    }
    function test_explicit_choices_debounce_and_start_only_after_current_ready_preview(){
      make();open();choose(102);choose(101);pending(1)
      compare(backend.requests,[{method:"trail_practice_preview",args:{text:surface.passage,subject_ids:[102,101]}}])
      verify(!page.canStart);verify(item("trail-practice-word-101").Accessible.checked)
      var raw=result(backend.pending[0].args);raw.meaning="PRIVATE MEANING";raw.items[0].answer="PRIVATE ANSWER";reply(0,raw)
      verify(page.canStart);compare(surface.starts,[]);compare(item("trail-practice-readiness").text,"2 / 2 selected words ready offline")
      click("trail-practice-start");compare(surface.starts.length,1);verify(!surface.starts[0].replace)
      compare(surface.starts[0].preview.subject_ids,[102,101]);verify(JSON.stringify(surface.starts).indexOf("PRIVATE")<0)
      compare(owner.resumes,[])
    }
    function test_exact_unicode_passage_is_preserved_without_normalization(){
      surface.passage="🦀 火山\nか\u3099、山";surface.matches=rows().slice(0,2);make();open();choose(101);choose(102);pending(1)
      compare(backend.pending[0].args.text,surface.passage);compare(surface.saved.text,surface.passage);reply(0)
      compare(page.preview.text,surface.passage);verify(!page.validText("\ud800"));verify(!page.validText("a".repeat(257)))
    }
    function test_selection_limit_and_unselecting_use_actual_checkable_controls(){
      surface.matches=Array.from({length:21},function(_,index){return word(index+1,"山")});make();open()
      for(var i=1;i<=20;i++)choose(i)
      compare(page.currentIds.length,20);verify(!item("trail-practice-word-21").enabled)
      choose(1);verify(!item("trail-practice-word-1").Accessible.checked);verify(item("trail-practice-word-21").enabled);choose(21)
      pending(1);compare(backend.pending[0].args.subject_ids.length,20);compare(new Set(backend.pending[0].args.subject_ids).size,20)
    }
    function test_saved_practice_requires_deliberate_resume_or_replacement(){
      make();open();choose(101);pending(1);var raw=result(backend.pending[0].args)
      raw.saved_practice={present:true,valid:true,completed:2,total:5,revision:9};raw.requires_practice_choice=true;reply(0,raw)
      compare(item("trail-practice-start").text,"Start new practice");verify(item("trail-practice-replacement").visible)
      click("trail-practice-resume");compare(owner.resumes,[{mode:"practice",size:5}]);compare(surface.starts,[])
      click("trail-practice-start");verify(surface.starts[0].replace)
    }
    function test_protected_or_uncached_content_and_damaged_saved_work_are_never_started(){
      make();open();choose(101);choose(102);pending(1);var raw=result(backend.pending[0].args)
      raw.items[0].ready=false;raw.items[0].reason="content_unavailable";raw.items[1].ready=false;raw.items[1].reason="protected_study";raw.items[1].state="Paused graded work"
      raw.ready_count=0;raw.can_start=false;reply(0,raw);verify(page.preview!==null);verify(!page.canStart)
      page.startSelected();compare(surface.starts,[])
      page.invalidatePreview();pending(1);raw=result(backend.pending[0].args);raw.saved_practice={present:true,valid:false,completed:null,total:null,revision:null};raw.requires_practice_choice=true;raw.can_start=false
      reply(0,raw);verify(!page.canStart);verify(!item("trail-practice-resume").enabled)
    }
    function test_late_replies_are_rejected_data(){return ["closed","hidden","detail","view","access","query","epoch","revision","sync","pending","grant","locked","restart","collapse","syncing","status","state"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_late_replies_are_rejected(data){
      make();open();choose(101);pending(1);var raw=result(backend.pending[0].args)
      if(data.edge==="closed")owner.opened=false;if(data.edge==="hidden")page.visible=false;if(data.edge==="detail")owner.detail={id:101};if(data.edge==="view")owner.view="help"
      if(data.edge==="access")owner.contentAccess="another-account";if(data.edge==="query")surface.passage="川";if(data.edge==="locked")backend.locked=true
      if(data.edge==="epoch")owner.snapshot=Object.assign({},owner.snapshot,{session_epoch:"01234567-89ab-cdef-0123-456789abcdee"})
      if(data.edge==="revision")owner.snapshot=Object.assign({},owner.snapshot,{session_revision:2});if(data.edge==="sync")owner.snapshot=Object.assign({},owner.snapshot,{last_sync:"new"})
      if(data.edge==="pending")owner.snapshot=Object.assign({},owner.snapshot,{pending:1});if(data.edge==="grant")owner.snapshot=Object.assign({},owner.snapshot,{max_level:0})
      if(data.edge==="syncing")owner.snapshot=Object.assign({},owner.snapshot,{syncing:true});if(data.edge==="status")owner.snapshot=Object.assign({},owner.snapshot,{status:"syncing"});if(data.edge==="state")owner.snapshot=Object.assign({},owner.snapshot,{state_revision:2})
      if(data.edge==="restart"){backend.ready=false;backend.ready=true}if(data.edge==="collapse")page.expanded=false
      reply(0,raw);compare(page.preview,null);verify(!page.canStart);compare(surface.starts,[])
    }
    function test_older_reply_cannot_clear_newer_loading_or_ready_choice(){
      make();open();choose(101);pending(1);choose(102);pending(2)
      reply(0);verify(page.loading);compare(page.preview,null);reply(0);verify(page.canStart);compare(page.preview.subject_ids,[101,102])
      choose(101);verify(!page.canStart);pending(1);reply(0);compare(page.preview.subject_ids,[102])
    }
    function test_service_replacement_releases_loading_and_drops_old_owner_reply(){
      make();open();choose(101);pending(1);owner.service=alternateBackend;pending(2)
      reply(0);verify(page.loading);compare(page.preview,null);reply(0);verify(page.canStart)
    }
    function test_identical_field_controller_replacement_cannot_keep_old_request_owner(){
      make();open();choose(101);pending(1)
      page.controller={service:backend,opened:true,busy:false,view:"lookup",detail:null,contentAccess:owner.contentAccess,navigationSequence:owner.navigationSequence,snapshot:owner.snapshot,begin:function(){throw new Error("No resume in readonly fixture")}}
      pending(2);reply(0);verify(page.loading);compare(page.preview,null);reply(0);verify(page.canStart)
    }
    function test_destroyed_picker_drops_late_reply(){
      make();open();choose(101);pending(1);var raw=result(backend.pending[0].args);page.destroy();page=null;wait(1);reply(0,raw)
      compare(surface.starts,[]);compare(owner.resumes,[])
    }
    function test_failures_do_not_auto_retry_or_render_private_error_text(){
      make();open();choose(101);pending(1);reply(0,null,false);verify(page.notice.length>0);verify(page.notice.indexOf("PRIVATE")<0)
      wait(200);compare(backend.requests.length,1);click("trail-practice-check");pending(1);reply(0);verify(page.canStart)
    }
    function test_saved_selection_survives_details_close_and_empty_loading_reports(){
      make();open();choose(102);choose(101);var saved=JSON.stringify(surface.saved)
      owner.detail={id:101};surface.matches=[];wait(180);compare(backend.requests,[]);compare(JSON.stringify(surface.saved),saved)
      owner.detail=null;surface.matches=rows();pending(1);reply(0);compare(page.currentIds,[102,101])
      owner.opened=false;page.destroy();page=null;wait(1);owner.opened=true;make();compare(page.selectedIds,[102,101]);verify(!page.expanded)
      wait(180);compare(backend.requests.length,1);open();pending(1);reply(0);compare(page.preview.subject_ids,[102,101])
    }
    function test_new_protection_prunes_selection_and_access_query_changes_clear_it(){
      make();open();choose(101);choose(102);surface.matches=[word(101,"火山",false),word(102,"山")];tryCompare(page,"currentIds",[102]);tryVerify(function(){return JSON.stringify(surface.saved.ids)==="[102]"})
      owner.contentAccess="new-account";wait(1);compare(page.selectedIds,[]);compare(surface.saved.ids,[]);verify(!page.expanded)
      open();choose(102);surface.passage="川";wait(1);compare(page.selectedIds,[]);compare(surface.saved,{schema:1,text:"川",ids:[]})
    }
    function test_malformed_preview_fields_never_enable_start(){
      make();open();choose(101);pending(1);var good=result(backend.pending[0].args)
      var bad=[function(v){v.can_start="true"},function(v){v.ready_count=2},function(v){v.subject_ids=[102]},function(v){v.data_epoch="other"},function(v){v.items[0].characters="PRIVATE"},function(v){v.items[0].level=true},function(v){v.items[0].ready=true;v.items[0].reason="protected_study"},function(v){v.protection_complete=false},function(v){v.saved_practice.revision=1},function(v){v.effect="start"}]
      for(var change of bad){var raw=JSON.parse(JSON.stringify(good));change(raw);compare(page.projected(raw,surface.passage,[101],owner.snapshot.session_epoch),null)}
      reply(0);verify(page.canStart);owner.busy=true;page.startSelected();compare(surface.starts,[])
    }
    __CHECKS__
    function test_narrow_native_palette_selection_stays_readable_data(){return paletteData()}
    function test_narrow_native_palette_selection_stays_readable(data){
      make();open();choose(101);pending(1);reply(0);var saved=JSON.stringify(surface.saved),reads=backend.requests.length
      applyPalette(data);checkText(page,data.tag);checkButtons(page,data.tag)
      compare(JSON.stringify(surface.saved),saved);compare(backend.requests.length,reads);compare(surface.starts,[])
      for(var node of paletteItems(page))if(node.visible&&typeof node.text==="string"&&node.textFormat!==undefined){verify(!node.truncated,node.text);verify(node.contentWidth<=node.width+1,node.text)}
    }
  }
}
'''


def build(directory):
    foundation.build(directory)
    (directory / 'tst_LessonFlow.qml').unlink()
    shutil.copyfile(ROOT / 'qml/TrailPractice.qml', directory / 'qml/TrailPractice.qml')
    palettes.pure_native_style(directory)
    checks = palettes.CHECKS.replace('__PALETTES__', json.dumps(palettes.palettes()))
    (directory / 'tst_TrailPractice.qml').write_text(QML.replace('__CHECKS__', checks))


@unittest.skipUnless(foundation.RUNNER.is_file(), 'QtTest required')
class TrailPracticeUiTests(unittest.TestCase):
    def test_actual_native_picker_and_context_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-trail-practice-ui-') as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(foundation.RUNNER), '-input', str(directory), '-import', str(directory)],
                capture_output=True, text=True, timeout=60, env={**os.environ, 'QT_QPA_PLATFORM':'offscreen',
                    'QT_QPA_PLATFORMTHEME':'', 'QT_QUICK_CONTROLS_STYLE':'Basic'})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn('QWARN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
