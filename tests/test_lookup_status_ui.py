"""Actual Lookup/native controls and cached radical image; authored data only."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation

ROOT=Path(__file__).resolve().parents[1]
RUNNER=foundation.RUNNER
QML=r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/SubjectStatus.mjs" as SubjectStatus
import "qml/Theme.mjs" as Theme
Rectangle {
 id: surface;width:760;height:2200;color:Color.background
 property var page:null
 Component{id:component;Kani.Lookup{width:290;controller:owner}}
 QtObject{id:backend;property bool ready:true;property bool locked:false}
 QtObject{
  id:owner;property var service:backend;property bool opened:true
  property var detail:null;property var results:[];property string query:"";property bool queryTruncated:false
  property string searchType:"all";property string searchState:"all";property int searchSequence:0;property bool searching:false
  property bool progressReturn:false;property string contentAccess:"authored";property int navigationSequence:0;property string progressContext:"authored"
  property var calls:[]
  function search(text){calls=calls.concat([{method:"search",text:text}])}
  function showSubject(id){calls=calls.concat([{method:"details",id:id}])}
  function setSearchFilter(type,state){calls=calls.concat([{method:"filter"}])}
  function readSelection(){calls=calls.concat([{method:"selection"}])}
  function begin(){calls=calls.concat([{method:"start"}])}
 }
 TestCase{
  name:"LookupStatus";when:windowShown
  function state(stage,group,pending,attention){return {stage:stage,group:group,pending:pending===true,attention:attention===true}}
  function subject(value){return {id:2,type:"kanji",characters:"山",slug:"authored",level:1,images:[],meanings:["Authored mountain"],assignment:{},learning_status:value}}
  function descendants(node){var rows=[];for(var child of node.children)rows=rows.concat([child],descendants(child));return rows}
  function labels(){return descendants(page).filter(function(v){return v.visible&&typeof v.text==="string"&&v.textFormat!==undefined})}
  function statuses(){return descendants(page).filter(function(v){return v.objectName==="lookup-result-status"})}
  function make(){page=component.createObject(surface);verify(page!==null);wait(1);var ready=false;verify(page.grabToImage(function(image){ready=!!image}));tryVerify(function(){return ready});wait(1);owner.calls=[]}
  function init(){failOnWarning(/.*/);owner.opened=true;backend.ready=true;backend.locked=false;owner.detail=null;owner.results=[];owner.query="";owner.calls=[];owner.searchSequence=0;Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"}
  function cleanup(){if(page)page.destroy();page=null;wait(1)}
  function test_all_named_stages_and_safe_unknowns(){
   var expected=["Apprentice 1","Apprentice 2","Apprentice 3","Apprentice 4","Guru 1","Guru 2","Master","Enlightened","Burned"]
   var groups=["apprentice","apprentice","apprentice","apprentice","guru","guru","master","enlightened","burned"]
   for(var i=1;i<=9;i++){compare(SubjectStatus.stageName(i),expected[i-1]);compare(SubjectStatus.label(state(i,groups[i-1])),"Confirmed "+expected[i-1])}
   for(var value of [null,undefined,false,true,0,-1,10,"5",4.5,[],{}])compare(SubjectStatus.stageName(value),"")
   for(var value of [null,[],{},state("5","guru"),state(true,"apprentice"),state(5,"apprentice"),state(12,"unknown"),state("9","burned"),state(null,"lessons"),{stage:5,group:"guru",pending:"true",attention:false}])compare(SubjectStatus.label(value),"Progress unavailable")
   compare(SubjectStatus.label(state(0,"lessons")),"Lesson ready · not started")
   compare(SubjectStatus.label(state(null,"locked")),"Not started")
  }
  function test_confirmed_and_pending_labels_in_actual_result_and_detail(){
   owner.results=[subject(state(4,"apprentice",true))];make()
   compare(statuses()[0].text,"kanji · Level 1 · Waiting to sync · confirmed Apprentice 4")
   owner.results=[subject(state(4,"apprentice",false,true))];wait(1)
   compare(statuses()[0].text,"kanji · Level 1 · Needs attention · confirmed Apprentice 4")
   owner.detail=subject(state(0,"lessons",true));wait(1)
   compare(findChild(page,"lookup-detail-status").text,"kanji · Level 1 · Waiting to sync · lesson ready · not started")
   owner.detail=subject(null);wait(1);verify(findChild(page,"lookup-detail-status").text.endsWith("Progress unavailable"))
   compare(owner.calls,[])
  }
  function test_native_open_preserves_current_identity_and_lock_gate(){
   owner.results=[subject(state(5,"guru"))];make()
   var open=descendants(page).find(function(v){return v.accessibleName!==undefined&&v.text==="Open"})
   open.forceActiveFocus(Qt.TabFocusReason);keyClick(Qt.Key_Return);compare(owner.calls,[{method:"details",id:2}])
   owner.calls=[];backend.locked=true;verify(!open.enabled);keyClick(Qt.Key_Return);compare(owner.calls,[])
  }
  function test_projected_image_array_remains_real_array_through_repeater(){
   var radical=subject(state(1,"apprentice"));radical.type="radical";radical.characters="";radical.images=[Qt.resolvedUrl("radical.svg").toString()]
   owner.results=[radical];make()
   var image=findChild(page,"radicalImage");verify(image!==null);tryCompare(image,"status",Image.Ready)
   verify(image.source.toString().endsWith("radical.svg"));compare(owner.calls,[])
  }
  function test_status_has_no_raw_payload_interpolation_or_hidden_reads(){
   var value=state(7,"master");value.stage_name="PRIVATE NOTE";value.label="PRIVATE ANSWER";value.extra="PRIVATE TOKEN"
   owner.results=[subject(value)];make();verify(statuses()[0].text.endsWith("Confirmed Master"))
   verify(!labels().some(function(v){return v.text.indexOf("PRIVATE")>=0||v.text.indexOf("SRS ")>=0}))
   owner.opened=false;owner.results=[subject(state(4,"apprentice",true))];wait(30);compare(owner.calls,[])
  }
  function test_narrow_and_standard_metadata_wraps_on_actual_surface_data(){return [{tag:"narrow light",width:290,bg:"#fffdf5",fg:"#222222",accent:"#006699"},{tag:"standard dark",width:710,bg:"#171b27",fg:"#e0e6f8",accent:"#9cc7ff"}]}
  function test_narrow_and_standard_metadata_wraps_on_actual_surface(data){
   owner.results=[subject(state(8,"enlightened",false,true))];owner.results[0].type="kana_vocabulary"
   make();page.width=data.width;Color.background=data.bg;Color.foreground=data.fg;Color.accent=data.accent;wait(140)
   var label=statuses()[0];verify(!label.truncated);verify(label.contentWidth<=label.width+1);verify(label.width>=data.width-26)
   verify(Theme.contrast(label.color,label.surfaceColor)>=4.5)
   owner.detail=subject(state(8,"enlightened",false,true));wait(1);label=findChild(page,"lookup-detail-status")
   verify(!label.truncated);verify(label.contentWidth<=label.width+1);compare(owner.calls,[])
  }
 }
}
'''


def build(directory):
    foundation.build(directory)
    (directory/"tst_LessonFlow.qml").unlink()
    for name in ("Lookup.qml","SubjectStatus.mjs"):
        shutil.copyfile(ROOT/"qml"/name,directory/"qml"/name)
    (directory/"qml/ReadingTrail.qml").write_text("import QtQuick\nItem {property var controller}\n")
    (directory/"qml/SubjectDetails.qml").write_text("import QtQuick\nItem {property var controller;property var subject;property bool editable}\n")
    (directory/"tst_LookupStatus.qml").write_text(QML)


@unittest.skipUnless(RUNNER.is_file(),"Qt required")
class LookupStatusUiTests(unittest.TestCase):
    def test_actual_lookup_status_keyboard_and_cached_radical(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-lookup-status-") as temporary:
            directory=Path(temporary);build(directory)
            result=subprocess.run([str(RUNNER),"-input",str(directory),"-import",str(directory)],capture_output=True,text=True,timeout=35,
                env={**os.environ,"QT_QPA_PLATFORM":"offscreen","QT_QPA_PLATFORMTHEME":"","QT_QUICK_CONTROLS_STYLE":"Basic"})
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertNotIn("QWARN",result.stdout+result.stderr)


if __name__=="__main__":unittest.main()
