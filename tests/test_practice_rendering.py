"""Production practice cards, native controls, authored local catalogue only."""
import os
from pathlib import Path
import shutil
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
  id:canvas;width:640;height:2400;color:Color.background
  property var page:null
  Component{id:factory;Kani.Practice{width:290;controller:owner}}
  QtObject {
    id:worker
    property bool ready:true
    property bool locked:false
    property var requests:[]
    property var catalogue:null
    signal snapshotChanged()
    function request(method,args,callback) {
      if(method!=="practice_catalogue")throw new Error("Unexpected backend action: "+method)
      requests=requests.concat([{method:method,args:args}])
      callback(true,JSON.parse(JSON.stringify(catalogue)),"")
    }
  }
  QtObject {
    id:owner
    property var service:worker
    property bool opened:true
    property bool busy:false
    property string contentAccess:"authored-account"
    property var snapshot:({last_sync:"fixture-sync"})
    property var actions:[]
    property var graded:({id:"authored-paused-review",draft:"private authored draft",index:2,errors:1})
    function begin(mode,limit,ids,explicit) {actions=actions.concat([{mode:mode,limit:limit,ids:ids,explicit:explicit}])}
  }
  TestCase {
    name:"PracticeRendering"
    when:windowShown
    function item(id,patch) {
      return Object.assign({id:id||1,type:"vocabulary",characters:"火山",meaning:"Volcano",slug:"Authored volcano",
        level:1,learned:true,srs_stage:2,ready:true,cache_note:"",pending_graded:false,spoilers_hidden:false,
        reasons:[{code:"recent_mistakes",label:"Recent mistakes: 2 meaning · 1 reading"}],images:[]},patch||{})
    }
    function library(items) {
      return {items:items||[item()],counts:{suggested:1,saved:1,learned:1,mistakes:1},ready_counts:{},
        total:(items||[item()]).length,ready_total:1,selection_limit:20,mistake_days:14,has_more:false,offset:0,limit:30,
        readiness_scope:"page",page_ready:1,saved_practice:{completed:1,total:5},graded_paused:true}
    }
    function make(items,width) {
      worker.catalogue=library(items)
      page=factory.createObject(canvas,{x:10,y:10,width:width||290})
      verify(page!==null);tryVerify(function(){return worker.requests.length===1&&!page.loading});verify(waitForRendering(page));wait(1)
    }
    function descendants(node) {var all=[];for(var child of node.children)all=all.concat([child],descendants(child));return all}
    function cards() {return descendants(page).filter(function(v){return v.objectName==="practice-subject-card"})}
    function child(name,index) {var value=findChild(cards()[index||0],"practice-subject-"+name);verify(value!==null,name);return value}
    function controls(text) {return descendants(page).filter(function(v){return v.visible&&v.accessibleName!==undefined&&v.text===text})}
    function labels() {return descendants(page).filter(function(v){return v.visible&&v.textFormat!==undefined&&typeof v.text==="string"})}
    function press(button) {verify(button.visible&&button.enabled);button.forceActiveFocus(Qt.TabFocusReason);keyClick(Qt.Key_Space)}
    function init() {
      failOnWarning(/.*/)
      worker.ready=true;worker.locked=false;worker.requests=[];worker.catalogue=null
      owner.opened=true;owner.busy=false;owner.actions=[];owner.contentAccess="authored-account"
      Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"
    }
    function cleanup() {if(page)page.destroy();page=null;wait(1)}
    function test_full_width_metadata_and_explicit_native_selection_data() {
      return [290,460].map(function(width){return {tag:String(width),width:width}})
    }
    function test_full_width_metadata_and_explicit_native_selection(data) {
      make(undefined,data.width)
      var status=child("status"),reasons=child("reasons"),meaning=child("meaning"),button=child("select")
      verify(status.width>=cards()[0].width-25);verify(reasons.width>=cards()[0].width-25)
      verify(meaning.width>150);compare(status.text,"vocabulary · Level 1 · Apprentice 2")
      verify(button.Accessible.checkable);verify(!button.Accessible.checked)
      var before=status.width,graded=JSON.stringify(owner.graded)
      press(button);compare(page.selectedIds,[1]);verify(button.Accessible.checked);compare(button.text,"Selected ✓")
      compare(status.width,before);compare(owner.actions.length,0);compare(JSON.stringify(owner.graded),graded)
      verify(findChild(button,"wanikani-action-focus").visible)
      keyClick(Qt.Key_Tab);verify(!button.activeFocus)
      press(controls("Practice selected · 1")[0])
      compare(owner.actions,[{mode:"practice",limit:1,ids:[1],explicit:true}])
      compare(worker.requests.length,1);compare(JSON.stringify(owner.graded),graded)
    }
    function test_named_stages_preserve_pending_and_unknown_states() {
      make([item(1,{srs_stage:0,learned:true,pending_graded:true,
        reasons:[{code:"pending_graded",label:"Graded result waiting for synchronization or recovery"}]}),
        item(2,{srs_stage:0,learned:false}),item(3,{srs_stage:"4"}),item(4,{srs_stage:9})])
      verify(child("status",0).text.indexOf("No confirmed SRS stage yet")>=0)
      compare(child("reasons",0).text,"Graded result waiting for synchronization or recovery")
      verify(child("status",1).text.indexOf("Lesson not started")>=0)
      verify(child("status",2).text.indexOf("SRS stage unavailable")>=0)
      verify(child("status",3).text.indexOf("Burned")>=0)
      compare(owner.actions.length,0)
    }
    function test_protected_meaning_stays_hidden_without_changing_manual_practice_policy() {
      make([item(1,{meaning:"Private answer must stay hidden",spoilers_hidden:true})])
      compare(child("meaning").text,"Meaning hidden during your graded session")
      verify(labels().every(function(label){return label.text.indexOf("Private answer")<0&&label.Accessible.name.indexOf("Private answer")<0}))
      press(child("select"));compare(page.selectedIds,[1]);compare(owner.actions.length,0)
    }
    function test_unavailable_content_blocks_add_but_allows_removing_previous_selection() {
      make([item(1,{ready:false,cache_note:"Required content is not available offline."})])
      verify(!child("select").enabled);verify(labels().some(function(label){return label.text==="Required content is not available offline."}))
      page.selectedIds=[1];verify(child("select").enabled);press(child("select"));compare(page.selectedIds,[])
      page.loading=true;verify(!cards()[0].enabled);compare(owner.actions.length,0)
    }
    function test_selection_survives_group_change_and_saved_resume_is_explicit() {
      make();press(child("select"));worker.catalogue=library([item(2)])
      page.chooseGroup("saved")
      tryVerify(function(){return worker.requests.length===2&&!page.loading});compare(page.selectedIds,[1]);compare(page.group,"saved")
      press(controls("Resume practice")[0]);compare(owner.actions.length,1);compare(owner.actions[0].mode,"practice")
      compare(owner.actions[0].explicit,undefined);compare(page.selectedIds,[1])
    }
    function test_empty_library_has_help_and_no_automatic_start() {
      make([]);compare(cards().length,0);compare(owner.actions.length,0)
      verify(labels().some(function(label){return label.text.indexOf("No suggested subjects yet")===0}))
      verify(!controls("Select subjects to practice")[0].enabled)
      verify(!controls("Add five from this page")[0].enabled)
    }
    function test_image_radical_keeps_cached_glyph_and_selection() {
      make([item(7,{type:"radical",characters:"",slug:"Authored shape",meaning:"Authored shape",images:[String(Qt.resolvedUrl("radical.svg"))]})])
      var glyph=child("glyph");tryVerify(function(){return glyph.displayReady})
      var image=findChild(glyph,"radicalImage")
      verify(image.visible);compare(image.status,Image.Ready);compare(String(image.source),String(Qt.resolvedUrl("radical.svg")))
      press(child("select"));compare(page.selectedIds,[7])
      worker.catalogue=library([]);owner.contentAccess="another-authored-account"
      tryVerify(function(){return cards().length===0});compare(page.selectedIds,[])
    }
    function test_light_dark_metadata_and_controls_fit_when_selected_data() {
      return [290,460].map(function(width){return {tag:String(width),width:width}})
    }
    function test_light_dark_metadata_and_controls_fit_when_selected(data) {
      make([item(1,{characters:"取り扱い",meaning:"An authored longer meaning for the compact card"})],data.width)
      press(child("select"))
      for(var colors of [["#fffdf5","#222222","#006699"],["#171b27","#e0e6f8","#9cc7ff"]]) {
        Color.background=colors[0];Color.foreground=colors[1];Color.accent=colors[2]
        verify(waitForRendering(page));wait(20)
        for(var label of descendants(cards()[0]).filter(function(v){return v.visible&&v.textFormat!==undefined&&typeof v.text==="string"})) {
          verify(!label.truncated,"Complete: "+label.text)
          verify(label.contentWidth<=label.width+1,"Fits: "+label.text)
          if(label.surfaceColor!==undefined)verify(Theme.contrast(label.color,label.surfaceColor)>=4.5,"Readable: "+label.text)
        }
        for(var control of descendants(page).filter(function(v){return v.visible&&v.accessibleName!==undefined})) {
          var point=control.mapToItem(page,0,0)
          verify(point.x>=-.5&&point.x+control.width<=page.width+.5,"Fits control: "+control.text)
        }
      }
      compare(owner.actions.length,0)
    }
    // CAPTURE_TEST
  }
}
'''


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    for name in ("Practice.qml", "SubjectStatus.mjs"):
        shutil.copyfile(ROOT / "qml" / name, directory / "qml" / name)
    (directory / "tst_PracticeRendering.qml").write_text(QML)


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Qt/native controls required")
class PracticeRenderingTests(unittest.TestCase):
    def test_actual_practice_cards_and_keyboard(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-practice-rendering-") as temporary:
            directory=Path(temporary);build(directory)
            result=subprocess.run([str(RUNNER),"-input",str(directory),"-import",str(directory)],
                capture_output=True,text=True,timeout=45,
                env={**os.environ,"QT_QPA_PLATFORM":"offscreen","QT_QPA_PLATFORMTHEME":"","QT_QUICK_CONTROLS_STYLE":"Basic"})
        output=result.stdout+result.stderr
        self.assertEqual(0,result.returncode,output)
        self.assertNotIn("QWARN",output)
        self.assertIn("12 passed",output)


if __name__=="__main__":
    unittest.main()
