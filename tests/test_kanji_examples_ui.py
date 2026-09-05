"""Actual kanji-example cards with native buttons and authored inert IO.

The wrapper shares the guided-lesson theme fixture and unchanged installed
Omarchy Button source. It does not launch the shell, authenticate, fetch media,
or exercise physical audio devices.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation


ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER
NATIVE = foundation.NATIVE


QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme

Rectangle {
  id: surface; width:640; height:1800; color:Color.background
  property var page:null
  Component {id: component; Kani.KanjiExamples {width:290; controller:owner; subject:owner.parentSubject}}
  QtObject {
    id: backend
    property bool ready:true
    property bool locked:false
    property var pending:[]
    function request(method,args,callback) {pending=pending.concat([{method:method,args:args,callback:callback}])}
  }
  QtObject {
    id: owner
    property var service:backend
    property bool opened:true
    property bool allowed:true
    property bool busy:false
    property string view:"study"
    property int navigationSequence:1
    property string contentAccess:"authored-access"
    property var snapshot:({session_revision:1,state_revision:1,last_sync:"old",pending:0,attention:0})
    property var parentSubject:({id:100,type:"kanji",characters:"火"})
    property var session:({id:"authored-review",revision:7,phase:"feedback",part:"reading",subject:{id:100},feedback:{retry:false}})
    property var detail:null
    property var plays:[]
    property int stops:0
    property var audioExample:null
    property string audioContext:""
    property int audioSubjectId:-1
    property int audioParentSubjectId:-1
    property string audioState:""
    property string audioNotice:""
    function kanjiExampleArgs(parent) {
      if(!allowed || !parent || parent.type!=="kanji" || !opened || !backend.ready || backend.locked)return null
      if(view==="study")return {parent_subject_id:parent.id,context:"study",session_id:session.id,revision:session.revision}
      if(view==="lookup")return {parent_subject_id:parent.id,context:"details"}
      return null
    }
    function playKanjiExample(word,parent) {plays=plays.concat([{word:word,parent:parent}])}
    function stopAudio() {stops++;audioContext="";audioExample=null;audioState="";audioSubjectId=-1}
    function play() {throw new Error("Kanji examples must use anchored whole-word playback")}
  }
  TestCase {
    name:"KanjiExamplesUi";when:windowShown
    function words() {
      return [{subject_id:201,characters:"火山",pronunciation:"かざん",meaning:"Volcano",learned:true,cached:true},
        {subject_id:202,characters:"火曜日",pronunciation:"かようび",meaning:"Tuesday",learned:true,cached:false},
        {subject_id:203,characters:"花火",pronunciation:"はなび",meaning:"Fireworks",learned:false,cached:true}]
    }
    function result() {return {parent_subject_id:100,status:"available",examples:words(),complete:true,reason:"ready"}}
    function make() {
      page=component.createObject(surface);verify(page!==null);verify(waitForRendering(page));wait(1)
      return page
    }
    function item(name) {var value=findChild(page,name);verify(value!==null,name);return value}
    function descendants(parent) {
      var items=[]
      for(var child of parent.children){items.push(child);items=items.concat(descendants(child))}
      return items
    }
    function labels() {return descendants(page).filter(function(value){return value.visible&&value.renderType===Text.NativeRendering&&typeof value.text==="string"})}
    function text(value) {return labels().some(function(label){return label.text===value})}
    function click(name) {var button=item(name);verify(button.enabled&&button.visible,name);button.forceActiveFocus();keyClick(Qt.Key_Space)}
    function reply(index,ok,data,message) {backend.pending[index].callback(ok,data,message||"");wait(1)}
    function reveal() {click("kanji-examples-open");compare(backend.pending.length,1);reply(0,true,result())}
    function invalidate(edge) {
      if(edge==="close")owner.opened=false
      if(edge==="lock")backend.locked=true
      if(edge==="restart")backend.ready=false
      if(edge==="view")owner.view="zen"
      if(edge==="navigation")owner.navigationSequence++
      if(edge==="access")owner.contentAccess="other-access"
      if(edge==="subject")owner.parentSubject={id:101,type:"kanji",characters:"水"}
      if(edge==="session")owner.session=Object.assign({},owner.session,{id:"different-session"})
      if(edge==="revision")owner.session=Object.assign({},owner.session,{revision:8})
      if(edge==="phase")owner.session=Object.assign({},owner.session,{phase:"question"})
      if(edge==="state")owner.snapshot=Object.assign({},owner.snapshot,{state_revision:2})
      if(edge==="sync")owner.snapshot=Object.assign({},owner.snapshot,{last_sync:"new"})
      if(edge==="session-state")owner.snapshot=Object.assign({},owner.snapshot,{session_revision:2})
      if(edge==="pending")owner.snapshot=Object.assign({},owner.snapshot,{pending:1})
      if(edge==="attention")owner.snapshot=Object.assign({},owner.snapshot,{attention:1})
      wait(1)
    }
    function init() {
      failOnWarning(/.*/)
      Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"
      backend.ready=true;backend.locked=false;backend.pending=[]
      owner.opened=true;owner.allowed=true;owner.busy=false;owner.view="study";owner.navigationSequence=1;owner.contentAccess="authored-access"
      owner.parentSubject={id:100,type:"kanji",characters:"火"}
      owner.session={id:"authored-review",revision:7,phase:"feedback",part:"reading",subject:{id:100},feedback:{retry:false}}
      owner.snapshot={session_revision:1,state_revision:1,last_sync:"old",pending:0,attention:0};owner.detail=null
      owner.plays=[];owner.stops=0;owner.audioExample=null;owner.audioContext="";owner.audioSubjectId=-1;owner.audioParentSubjectId=-1;owner.audioState="";owner.audioNotice=""
    }
    function cleanup() {if(page)page.destroy();page=null;wait(1)}
    function test_collapsed_is_silent_and_native_open_requests_only_catalogue() {
      make();verify(!page.expanded);compare(backend.pending.length,0);compare(owner.plays.length,0)
      click("kanji-examples-open");verify(page.busy)
      compare(backend.pending[0].method,"kanji_examples")
      compare(backend.pending[0].args,{parent_subject_id:100,context:"study",session_id:"authored-review",revision:7})
      page.loadExamples();compare(backend.pending.length,1,"No duplicate while loading")
      reply(0,true,result());verify(!page.busy);compare(page.examples.length,3)
      verify(text("火山"));verify(text("かざん"));verify(text("Volcano"))
      compare(owner.plays.length,0);compare(backend.pending.length,1)
    }
    function test_play_uses_current_word_and_parent_and_native_keyboard() {
      make();reveal();click("kanji-example-play-201")
      compare(owner.plays,[{word:words()[0],parent:owner.parentSubject}])
      compare(backend.pending.length,1)
    }
    function test_details_arguments_do_not_claim_a_study_session() {
      owner.view="lookup";owner.detail=owner.parentSubject;make();click("kanji-examples-open")
      compare(backend.pending[0].args,{parent_subject_id:100,context:"details"})
    }
    function test_collapse_ignores_late_reply_and_reopen_is_explicit() {
      make();click("kanji-examples-open");page.collapse();reply(0,true,result())
      verify(!page.expanded);verify(!page.busy);compare(page.examples.length,0)
      wait(30);compare(backend.pending.length,1);compare(owner.plays.length,0)
      click("kanji-examples-open");compare(backend.pending.length,2)
      reply(0,true,result());compare(page.examples.length,0,"Earlier generation cannot populate reopening")
      reply(1,true,result());compare(page.examples.length,3)
    }
    function test_destroyed_component_cannot_receive_late_catalogue() {
      make();click("kanji-examples-open");page.destroy();page=null;wait(1)
      reply(0,true,result());compare(owner.plays.length,0);compare(backend.pending.length,1)
    }
    function test_late_reply_data() {
      return ["close","lock","restart","view","navigation","access","subject","session","revision","phase","sync","session-state","pending","attention"].map(function(edge){return {tag:edge,edge:edge}})
    }
    function test_late_reply(data) {
      make();click("kanji-examples-open");invalidate(data.edge);reply(0,true,result())
      verify(!page.expanded);verify(!page.busy);compare(page.examples.length,0);compare(owner.plays.length,0)
      compare(backend.pending.length,1,"Context changes never refetch automatically")
    }
    function test_failure_clears_busy_and_retry_requires_a_new_action() {
      make();click("kanji-examples-open");reply(0,false,null,"Authored catalogue failure")
      verify(!page.busy);compare(page.error,"Authored catalogue failure");compare(page.examples.length,0)
      wait(30);compare(backend.pending.length,1);compare(owner.plays.length,0)
      page.loadExamples();compare(backend.pending.length,2)
      reply(1,true,result());compare(page.examples.length,3)
    }
    function test_unrelated_state_refresh_preserves_disclosure_and_playback() {
      make();reveal();owner.audioContext="kanji_example";owner.audioParentSubjectId=100;owner.audioSubjectId=201;owner.audioState="playing"
      invalidate("state");verify(page.expanded);compare(page.examples.length,3);compare(owner.stops,0)
      compare(backend.pending.length,1);compare(owner.plays.length,0)
    }
    function test_wrong_parent_and_oversized_reply_are_rejected_data() {
      return [{tag:"wrong-parent",parent:true},{tag:"oversized",parent:false}]
    }
    function test_wrong_parent_and_oversized_reply_are_rejected(data) {
      make();click("kanji-examples-open");var value=result()
      if(data.parent)value.parent_subject_id=101
      else value.examples=words().concat([words()[0]])
      reply(0,true,value);compare(page.examples.length,0);verify(page.error.length>0);verify(!page.busy)
    }
    function test_empty_and_partial_catalogue_remain_honest() {
      make();click("kanji-examples-open")
      reply(0,true,{parent_subject_id:100,status:"empty",examples:[],complete:false,reason:"partial_catalogue"})
      compare(page.examples.length,0);verify(!page.busy);verify(!page.complete)
      verify(page.notice.length>0);compare(owner.plays.length,0)
    }
    function test_unavailable_context_cannot_fetch_even_when_called_directly() {
      owner.allowed=false;make();page.loadExamples();compare(backend.pending.length,0)
      verify(!page.contextAllowed);compare(owner.plays.length,0)
    }
    function test_selected_clip_displays_actual_recording_reading_and_stop_control() {
      make();reveal();owner.audioContext="kanji_example";owner.audioParentSubjectId=100;owner.audioSubjectId=201
      owner.audioState="playing";owner.audioExample={parent_subject_id:100,characters:"火山島",meaning:"Volcanic island",pronunciation:"カザン"};owner.audioNotice="Using another downloaded voice for this word."
      verify(text("カザン"));verify(!text("かざん"));verify(text("火山島"));verify(text("Volcanic island"));verify(!text("Volcano"));verify(text(owner.audioNotice))
      var stop=descendants(page).find(function(value){return value.objectName==="kanji-example-stop"&&value.visible})
      verify(stop!==undefined);stop.forceActiveFocus();keyClick(Qt.Key_Space);compare(owner.stops,1)
      verify(text("かざん"));compare(owner.plays.length,0)
    }
    function test_collapse_stops_only_this_parents_example_audio() {
      make();reveal()
      owner.audioContext="details";owner.audioSubjectId=201;owner.audioState="playing";page.collapse();compare(owner.stops,0)
      click("kanji-examples-open");reply(1,true,result())
      owner.audioContext="kanji_example";owner.audioParentSubjectId=999;owner.audioExample={parent_subject_id:999,pronunciation:"other"};page.collapse();compare(owner.stops,0)
      click("kanji-examples-open");reply(2,true,result())
      owner.audioContext="kanji_example";owner.audioParentSubjectId=100;owner.audioExample={parent_subject_id:100,pronunciation:"かざん"};page.collapse();compare(owner.stops,1)
    }
    function test_narrow_live_light_and_dark_text_is_complete_and_readable() {
      make();reveal()
      for(var colors of [["#fffdf5","#222222","#006699"],["#171925","#dfe4f3","#99ccff"]]) {
        Color.background=colors[0];Color.foreground=colors[1];Color.accent=colors[2]
        verify(waitForRendering(page));wait(20)
        for(var label of labels()) {
          verify(!label.truncated,"Complete: "+label.text)
          verify(label.contentWidth<=label.width+1,"Fits: "+label.text)
          if(label.surfaceColor!==undefined)verify(Theme.contrast(label.color,label.surfaceColor)>=4.5,"Contrast: "+label.text)
        }
        for(var id of [201,202,203]) {
          var action=item("kanji-example-play-"+id)
          verify(action.Accessible.name.length>0);verify(action.activeFocusOnTab)
        }
      }
      compare(owner.plays.length,0);compare(backend.pending.length,1)
    }
  }
}
'''


PANEL = r'''
import QtQuick
QtObject {
  id:root
  property var service:null
  property bool opened:true
  property string view:"study"
  property int navigationSequence:1
  property string contentAccess:"authored-access"
  property var session:null
  property var detail:null
  property var snapshot:({last_sync:"old",session_revision:1,state_revision:1,pending:0,attention:0})
  property int audioSequence:0
  property int audioSubjectId:-1
  property int audioParentSubjectId:-1
  property var audioExample:null
  property string audioContext:""
  property string audioState:""
  property string audioNotice:""
  property bool listenBusy:false
  property int listenSequence:0
  property var events:[]
  property int stops:0
  property QtObject player:QtObject {
    id:audio
    property string source:""
    function play(){root.events=root.events.concat([{uri:source,example:root.audioExample}])}
    function stop(){root.stops++}
  }
  __FUNCTIONS__
}
'''

PANEL_QML = r'''
import QtQuick
import QtTest
import "qml" as Kani
Rectangle {
  id:surface;width:500;height:1600
  property var page:null
  readonly property var parentWord:({id:100,type:"kanji",characters:"火"})
  readonly property var exampleWord:({subject_id:201,characters:"火山",pronunciation:"かざん",meaning:"Volcano",learned:true,cached:true})
  Component{id:component;Kani.KanjiExamples{width:290;controller:owner;subject:surface.parentWord}}
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property var pending:[]
    function request(method,args,callback){pending=pending.concat([{method:method,args:JSON.parse(JSON.stringify(args)),callback:callback}])}
  }
  PanelCore{id:owner;service:backend}
  TestCase {
    name:"KanjiExamplesPanel";when:windowShown
    function saved(){return {id:"saved-review",revision:7,phase:"feedback",part:"reading",subject:parentWord,feedback:{retry:false}}}
    function response(status){return {subject_id:201,status:status||"ready",uri:"file:///authored-inert-word.mp3",example:{parent_subject_id:100,characters:"火山",meaning:"Volcano",pronunciation:"かざん"}}}
    function reply(index,data){backend.pending[index].callback(true,data,"");wait(1)}
    function make(){page=component.createObject(surface);verify(page!==null);verify(waitForRendering(page));page.loadExamples();reply(0,{parent_subject_id:100,examples:[exampleWord],complete:true});compare(page.examples.length,1)}
    function play(){var action=findChild(page,"kanji-example-play-201");verify(action!==null&&action.enabled);action.forceActiveFocus();keyClick(Qt.Key_Space)}
    function init(){
      failOnWarning(/.*/);backend.ready=true;backend.locked=false;backend.pending=[]
      owner.opened=true;owner.view="study";owner.navigationSequence=1;owner.contentAccess="authored-access"
      owner.session=saved();owner.detail=null;owner.snapshot={last_sync:"old",session_revision:1,state_revision:1,pending:0,attention:0}
      owner.stopAudio();owner.events=[];owner.stops=0
    }
    function cleanup(){if(page)page.destroy();page=null;wait(1)}
    function test_actual_study_playback_is_anchored_and_selected_clip_precedes_play(){
      make();play();compare(backend.pending[1].method,"pronunciation")
      compare(backend.pending[1].args,{parent_subject_id:100,context:"kanji_example",origin_context:"study",session_id:"saved-review",revision:7,subject_id:201})
      compare(owner.audioParentSubjectId,100);reply(1,response())
      compare(owner.events,[{uri:"file:///authored-inert-word.mp3",example:response().example}])
    }
    function test_actual_details_playback_has_no_session_exemption(){
      owner.view="lookup";owner.detail=parentWord;make();play()
      compare(backend.pending[1].args,{parent_subject_id:100,context:"kanji_example",origin_context:"details",subject_id:201})
    }
    function test_actual_helper_refuses_unrevealed_or_unrelated_parent(){
      for(var mode of ["question","meaning-feedback","retry","meaning-lesson","other-parent","other-view"]){
        owner.session=saved();owner.view="study"
        if(mode==="question")owner.session=Object.assign(saved(),{phase:"question"})
        if(mode==="meaning-feedback")owner.session=Object.assign(saved(),{part:"meaning"})
        if(mode==="retry")owner.session=Object.assign(saved(),{feedback:{retry:true}})
        if(mode==="meaning-lesson")owner.session=Object.assign(saved(),{phase:"lesson",lesson_flow:{step:"meaning"}})
        if(mode==="other-parent")owner.session=Object.assign(saved(),{subject:{id:999}})
        if(mode==="other-view")owner.view="zen"
        compare(owner.kanjiExampleArgs(parentWord),null,mode)
        owner.playKanjiExample(exampleWord,parentWord);compare(backend.pending.length,0)
      }
    }
    function test_only_deliberate_play_downloads_and_failed_preparation_never_loops(){
      make();compare(backend.pending.length,1);play();reply(1,response("not_cached"))
      compare(backend.pending[2].method,"pronunciation_prepare");compare(backend.pending[2].args,backend.pending[1].args)
      reply(2,response("not_cached"));compare(owner.audioState,"failed");compare(owner.events.length,0)
      wait(30);compare(backend.pending.length,3);play();compare(backend.pending.length,4)
    }
    function test_wrong_ready_word_or_parent_never_plays_data(){return [{tag:"word",word:true},{tag:"parent",word:false}]}
    function test_wrong_ready_word_or_parent_never_plays(data){
      make();play();var value=response();if(data.word)value.subject_id=202;else value.example.parent_subject_id=999
      reply(1,value);compare(owner.events.length,0);compare(owner.audioState,"failed")
    }
    function test_mismatched_not_cached_reply_cannot_select_a_different_download(){
      make();play();var value=response("not_cached");value.subject_id=202;reply(1,value)
      compare(backend.pending.length,2);compare(owner.events.length,0);compare(owner.audioState,"failed")
    }
    function test_late_details_media_requires_the_same_open_parent_data(){
      return [{tag:"cached",prepare:false},{tag:"prepared",prepare:true}]
    }
    function test_late_details_media_requires_the_same_open_parent(data){
      owner.view="lookup";owner.detail=parentWord;make();play();var index=1
      if(data.prepare){reply(1,response("not_cached"));index=2}
      owner.detail={id:999,type:"kanji",characters:"水"};reply(index,response())
      compare(owner.events.length,0);compare(backend.pending.length,index+1)
    }
    function test_late_media_data(){
      var values=[]
      for(var stage of ["cached","prepare"])
        for(var edge of ["close","lock","restart","view","parent","session","revision","phase","access","sync","collapse"])
          values.push({tag:stage+"-"+edge,stage:stage,edge:edge})
      return values
    }
    function test_late_media(data){
      make();play();var index=1
      if(data.stage==="prepare"){reply(1,response("not_cached"));index=2}
      if(data.edge==="close")owner.opened=false
      if(data.edge==="lock")backend.locked=true
      if(data.edge==="restart")backend.ready=false
      if(data.edge==="view")owner.view="zen"
      if(data.edge==="parent")owner.session=Object.assign(saved(),{subject:{id:999}})
      if(data.edge==="session")owner.session=Object.assign(saved(),{id:"another-session"})
      if(data.edge==="revision")owner.session=Object.assign(saved(),{revision:8})
      if(data.edge==="phase")owner.session=Object.assign(saved(),{phase:"question"})
      if(data.edge==="access")owner.contentAccess="another-account"
      if(data.edge==="sync")owner.snapshot=Object.assign({},owner.snapshot,{last_sync:"new"})
      if(data.edge==="collapse")page.collapse()
      reply(index,response());compare(owner.events.length,0);compare(backend.pending.length,index+1)
    }
    function test_unrelated_snapshot_does_not_cancel_an_authorized_recording(){
      make();play();owner.snapshot=Object.assign({},owner.snapshot,{state_revision:2})
      reply(1,response());compare(owner.events.length,1);verify(page.expanded)
    }
  }
}
'''


def panel_adapter():
    source = (ROOT / "Panel.qml").read_text()
    functions = []
    for name in ("audioContextCurrent", "requestAudio", "kanjiExampleArgs", "playKanjiExample", "stopAudio"):
        match = re.search(r"(?ms)^  function " + name + r"\(.*?^  \}", source)
        if not match:
            raise AssertionError("Review Panel function boundary: " + name)
        functions.append(match.group(0))
    return PANEL.replace("__FUNCTIONS__", "\n".join(functions))


def build(directory, source):
    """Copy production UI into a disposable, non-hosted Qt fixture."""
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    shutil.copyfile(ROOT / "qml" / "KanjiExamples.qml", directory / "qml" / "KanjiExamples.qml")
    (directory / "tst_KanjiExamples.qml").write_text(source)


def run_fixture(directory):
    return subprocess.run(
        [str(RUNNER), "-input", str(directory), "-import", str(directory)],
        capture_output=True, text=True, errors="replace", timeout=45,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
             "QT_QUICK_CONTROLS_STYLE": "Basic"},
    )


@unittest.skipUnless(RUNNER.is_file() and (NATIVE / "Button.qml").is_file(), "Qt and native Omarchy controls required")
class KanjiExamplesUiTests(unittest.TestCase):
    def test_actual_kanji_examples_components(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-kanji-examples-ui-") as temporary:
            directory = Path(temporary)
            build(directory, QML)
            result = run_fixture(directory)
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)

    def test_actual_panel_example_playback_callbacks(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-kanji-examples-panel-") as temporary:
            directory = Path(temporary)
            build(directory, PANEL_QML)
            (directory / "PanelCore.qml").write_text(panel_adapter())
            result = run_fixture(directory)
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
