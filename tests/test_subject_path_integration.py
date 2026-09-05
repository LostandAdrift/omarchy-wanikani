"""Actual SubjectDetails/Study path wiring with the real Panel navigation method.

Only shell services and backend callbacks are inert authored adapters. Native
Omarchy buttons are copied unchanged. No host IPC, account or graded writes.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation

ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER

QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme
Rectangle {
  id: canvas
  width: 640
  height: 2800
  color: Color.background
  property var page: null
  Component {id: detailFactory;Kani.SubjectDetails {width:290;controller:owner;subject:owner.detail;editable:true}}
  Component {id: studyFactory;Kani.Study {width:290;controller:owner}}
  QtObject {
    id: service
    property bool ready:true
    property bool locked:false
    property bool animations:false
    property bool studying:false
    property var writes:[]
    signal snapshotChanged()
    function request(method,args,callback) {
      writes=writes.concat([{method:method,args:args}])
      throw new Error("The path must not perform backend work: "+method)
    }
  }
  Owner {id:owner;service:service}
  Item {id:focusSink}
  TestCase {
    name: "SubjectPathIntegration"
    when: windowShown
    function subject(id) {
      return {id:id||101,type:"vocabulary",characters:"火山",meanings:["Volcano"],
        readings:[{reading:"かざん",accepted:true}],level:1,slug:"authored-volcano",images:[],
        meaning_mnemonic:"Authored meaning.",meaning_hint:"",reading_mnemonic:"Authored reading.",reading_hint:"",
        sentences:[{ja:"火山があります。",en:"An authored example: there is a volcano."}],
        material:{meaning_synonyms:[],meaning_note:"",reading_note:""},
        components:[{id:1,characters:"火",meaning:"Fire"},{id:9007199254740991,characters:"山",meaning:"Mountain"}],
        related:[{id:2,characters:"火山島",meaning:"Volcanic island"}],visually_similar:[],audio:[],audio_available:false}
    }
    function lesson() {
      return {id:"authored-lessons",revision:7,mode:"lessons",phase:"lesson",part:"meaning",subject:subject(),
        draft:"",index:0,total:2,lesson_index:0,completed:0,feedback:null,errors:0,overrides:0,invalidated:"",finishing:false,
        lesson_flow:{step:"context",steps:[{id:"meaning",label:"Meaning"},{id:"reading",label:"Reading & audio"},{id:"context",label:"Context"}],
          position:3,total:3,can_back:true,can_next:true,can_quiz:false,next_label:"Next subject",adjusted:false}}
    }
    function make(study) {
      owner.detail=subject()
      owner.session=study?lesson():null
      owner.view=study?"study":"lookup"
      page=(study?studyFactory:detailFactory).createObject(canvas,{x:10,y:10})
      verify(page!==null);verify(waitForRendering(page));wait(1)
      return path()
    }
    function descendants(node) {
      var result=[]
      for(var child of node.children)result=result.concat([child],descendants(child))
      return result
    }
    function path() {var value=findChild(page,"wanikani-subject-path");verify(value!==null);return value}
    function controls(text) {return descendants(page).filter(function(v){return v.visible&&v.accessibleName!==undefined&&v.text===text})}
    function labels() {return descendants(page).filter(function(v){return v.visible&&v.textFormat!==undefined&&typeof v.text==="string"})}
    function toggle() {
      var buttons=controls("How this subject connects");compare(buttons.length,1)
      verify(buttons[0].Accessible.checkable);verify(!buttons[0].Accessible.checked)
      buttons[0].forceActiveFocus(Qt.TabFocusReason);keyClick(Qt.Key_Space)
      tryCompare(path(),"expanded",true);verify(buttons[0].Accessible.checked);wait(1)
    }
    function open(id) {
      var card=descendants(path()).find(function(v){return v.objectName==="wanikani-path-card"&&v.subjectId===id})
      verify(card!==undefined,"Requested card is present")
      var button=descendants(card).find(function(v){return v.accessibleName!==undefined&&v.text==="Open"})
      verify(button!==undefined,"An explicit Open control exists")
      button.forceActiveFocus(Qt.TabFocusReason);keyClick(Qt.Key_Return)
    }
    function init() {
      failOnWarning(/.*/)
      Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"
      service.ready=true;service.locked=false;service.studying=false;service.writes=[]
      owner.opened=true;owner.busy=false;owner.detail=null;owner.session=null;owner.error=""
      owner.contentAccess="authored-account";owner.pending=[];owner.actions=[];owner.plays=[]
      owner.progressReturn=false;owner.view="lookup";owner.navigationSequence=0;owner.searchSequence=0;owner.detailSequence=0
    }
    function cleanup() {if(page)page.destroy();page=null;wait(1)}
    function test_actual_lesson_context_is_readable_without_navigation_or_grading() {
      var value=make(true);verify(value.visible);verify(!value.expanded)
      var sessionBefore=JSON.stringify(owner.session)
      toggle();compare(controls("Open").length,0)
      verify(labels().some(function(v){return v.text==="Fire"}))
      verify(labels().some(function(v){return v.text==="Volcanic island"}))
      value.openSubject(1)
      compare(owner.pending.length,0);compare(owner.actions.length,0);compare(owner.plays.length,0);compare(service.writes.length,0)
      compare(JSON.stringify(owner.session),sessionBefore)
    }
    function test_context_and_concealment_gates_do_not_instantiate_hidden_path_answers() {
      var value=make(false);page.editable=false;page.section="meaning"
      verify(!value.visible);value.expanded=true;wait(1)
      compare(descendants(value).filter(function(v){return v.objectName==="wanikani-path-meaning"}).length,0)
      page.section="reading";verify(!value.visible)
      page.section="context";verify(value.visible);toggle()
      page.showReading=false;verify(!value.expanded);toggle()
      compare(value.related.length,0)
      compare(descendants(value).filter(function(v){return v.objectName==="wanikani-path-reading"}).length,0)
      compare(controls("Open").length,0)
      page.showMeaning=false;verify(!value.visible);wait(1)
      compare(descendants(value).filter(function(v){return v.objectName==="wanikani-path-meaning"}).length,0)
      compare(owner.pending.length,0);compare(service.writes.length,0)
    }
    function test_explicit_lookup_open_keeps_production_subject_navigation() {
      make(false);toggle();open(9007199254740991)
      compare(owner.pending.length,1);compare(owner.pending[0].method,"details")
      compare(owner.pending[0].args.subject_id,9007199254740991)
      owner.pending[0].callback(true,subject(9007199254740991))
      compare(owner.detail.id,9007199254740991);compare(owner.view,"lookup");verify(!path().expanded)
      compare(owner.actions.length,0);compare(service.writes.length,0)
    }
    function test_progress_origin_keeps_guarded_related_navigation() {
      make(false);owner.progressReturn=true;toggle();open(1)
      compare(owner.pending[0].method,"progress_details")
      owner.pending[0].callback(true,subject(1));verify(owner.progressReturn);compare(owner.detail.id,1)
    }
    function test_open_permission_data() {
      return [{tag:"closed",kind:"closed"},{tag:"locked",kind:"locked"},{tag:"unready",kind:"unready"},
        {tag:"readonly",kind:"readonly"},{tag:"meaning-hidden",kind:"meaning"},{tag:"reading-hidden",kind:"reading"}]
    }
    function test_open_permission(data) {
      var value=make(false);toggle()
      if(data.kind==="closed")owner.opened=false
      else if(data.kind==="locked")service.locked=true
      else if(data.kind==="unready")service.ready=false
      else if(data.kind==="readonly")page.editable=false
      else if(data.kind==="meaning")page.showMeaning=false
      else page.showReading=false
      value.openSubject(1);wait(1)
      compare(controls("Open").length,0);compare(owner.pending.length,0);compare(owner.actions.length,0)
    }
    function test_late_lookup_reply_does_not_cross_access_context() {
      make(false);toggle();open(1)
      owner.contentAccess="different-authored-account"
      owner.pending[0].callback(true,subject(1))
      compare(owner.detail.id,101);compare(owner.actions.length,0)
    }
    function test_narrow_context_text_fits_light_and_dark() {
      make(false);page.editable=false;page.section="context";toggle()
      for(var colors of [["#fffdf5","#222222","#006699"],["#171b27","#e0e6f8","#9cc7ff"]]) {
        Color.background=colors[0];Color.foreground=colors[1];Color.accent=colors[2]
        verify(waitForRendering(page));wait(20)
        for(var label of labels()) {
          verify(!label.truncated,"Complete: "+label.text)
          verify(label.contentWidth<=label.width+1,"Fits: "+label.text)
          if(label.surfaceColor!==undefined)verify(Theme.contrast(label.color,label.surfaceColor)>=4.5,"Contrast: "+label.text)
        }
      }
      compare(owner.pending.length,0);compare(owner.actions.length,0);compare(service.writes.length,0)
    }
    // CAPTURE_TEST
  }
}
'''

OWNER = '''import QtQuick
QtObject {
  id: root
  required property var service
  property bool opened:true
  property bool busy:false
  property bool searching:false
  property string view:"lookup"
  property string error:""
  property string contentAccess:"authored-account"
  property int searchSequence:0
  property int detailSequence:0
  property int navigationSequence:0
  property bool progressReturn:false
  property string progressContext:"authored-progress"
  property var detail:null
  property var session:null
  property var snapshot:({settings:{autoplay_lessons:false,autoplay_audio:false},pending:0,demo:true})
  property string audioContext:""
  property string audioState:""
  property string audioNotice:""
  property int audioSubjectId:-1
  property var pending:[]
  property var actions:[]
  property var plays:[]
  function call(method,args,callback){pending=pending.concat([{method:method,args:args,callback:callback}])}
  function navigate(view){root.view=view}
  function studyAction(method,args){actions=actions.concat([{method:method,args:args}])}
  function play(subject){plays=plays.concat([subject.id])}
  function stopAudio(){}
  function dismiss(){opened=false}
  function begin(){throw new Error("No automatic new study")}
'''


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    source = (ROOT / "Panel.qml").read_text()
    method = re.search(r"(?ms)^  function showSubject\(.*?(?=^  function )", source)
    if not method:
        raise AssertionError("Review the actual Panel.showSubject fixture boundary")
    (directory / "Owner.qml").write_text(OWNER + method.group(0) + "}\n")
    (directory / "tst_SubjectPathIntegration.qml").write_text(QML)


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Qt/native Button required")
class SubjectPathIntegrationTests(unittest.TestCase):
    def test_actual_details_lesson_lookup_and_narrow_context(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-subject-path-integration-") as temporary:
            directory = Path(temporary)
            build(directory)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=45,
                env={**os.environ, "QT_QPA_PLATFORM":"offscreen", "QT_QPA_PLATFORMTHEME":"", "QT_QUICK_CONTROLS_STYLE":"Basic"})
        output = process.stdout + process.stderr
        self.assertEqual(0, process.returncode, output)
        self.assertNotIn("QWARN", output)
        self.assertIn("14 passed", output)


if __name__ == "__main__":
    unittest.main()
