"""Native review body, pinned actions and keyboard behavior with authored IO."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_lesson_flow_ui as foundation

ROOT=Path(__file__).resolve().parents[1]
HEAD=foundation.QML[:foundation.QML.index('  TestCase {')]
HEAD=HEAD.replace('import QtQuick\n','import QtQuick\nimport QtQuick.Layouts\nimport QtQuick.Controls as Controls\n',1)
HEAD=HEAD.replace('width:640;height:3000','width:756;height:690')
HEAD=HEAD.replace('Kani.Study {width:380;controller:owner}','Kani.Study {width:scroll.availableWidth;controller:owner;dockActions:true}')
LAYOUT=r'''
 ColumnLayout {
  anchors.fill:parent;anchors.margins:20;spacing:14
  Kani.Label {text:"WaniKani · Reviews";font.pixelSize:22}
  Controls.ScrollView {
   id:scroll;Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
   contentHeight:page?page.height:0
   Controls.ScrollBar.vertical.policy:Controls.ScrollBar.AlwaysOn
  }
  Loader {id:footer;Layout.fillWidth:true;sourceComponent:page?page.reviewActions:null}
 }
'''
WORD=foundation.QML[foundation.QML.index('    function word('):foundation.QML.index('    function state(')]
CASES=r'''
 TestCase {
  name:"ReviewWorkspace";when:windowShown
 __WORD__
 function state(part,phase){return {id:"authored-reviews",revision:1,mode:"reviews",phase:phase||"question",part:part||"reading",subject:word(),draft:"",index:0,total:5,lesson_index:0,completed:4,feedback:phase==="feedback"?{correct:false,accepted:["かざん"],message:"Not quite. Review the reading, then try again.",retry:false}:null,errors:1,overrides:0,invalidated:"",finishing:false}}
 function make(value){owner.session=value;page=study.createObject(scroll.contentItem);verify(page!==null);verify(waitForRendering(page));tryVerify(function(){return footer.item!==null})}
 function input(){return findChild(page,"study-answer")}
 function playButton(){return findChild(footer.item,"study-play-pronunciation")}
 function init(){failOnWarning(/.*/);surface.width=756;surface.height=690;backend.ready=true;backend.locked=false;backend.writes=[];owner.opened=true;owner.busy=false;owner.plays=[];owner.actions=[];owner.audioState="";owner.snapshot={settings:{autoplay_lessons:false,autoplay_audio:false},pending:0,demo:true};Color.background="#1a1b26";Color.foreground="#c0caf5";Color.accent="#7aa2f7"}
 function cleanup(){footer.sourceComponent=null;if(page)page.destroy();page=null;footer.sourceComponent=Qt.binding(function(){return page?page.reviewActions:null});wait(1)}
 function test_question_cues_and_audio_do_not_reveal_answer(){
  make(state("meaning"));tryCompare(input(),"activeFocus",true)
  verify(findChild(page,"study-question-cue").text.indexOf("English")>=0)
  keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays,[]);verify(!playButton().enabled)
  owner.session=state("reading");wait(1);verify(findChild(page,"study-question-cue").text.indexOf("pronunciation")>=0)
  for(var c of "kazan")keyClick(c);compare(input().text,"かざn")
 }
 function test_audio_shortcut_feedback_and_suppression(){
  make(state("reading","feedback"));tryCompare(input(),"activeFocus",true)
  verify(playButton().visible&&playButton().enabled);keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays,[101]);compare(owner.actions,[])
  owner.busy=true;keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays.length,1);owner.busy=false
  backend.locked=true;keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays.length,1);backend.locked=false
  owner.audioState="loading";keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays.length,1);owner.audioState=""
  owner.session=Object.assign({},owner.session,{feedback:{correct:false,retry:true,accepted:[],message:"Try kana"}});keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays.length,1)
  owner.session=state("meaning","feedback");keyClick(Qt.Key_P,Qt.AltModifier);compare(owner.plays.length,1)
 }
 function test_pinned_controls_survive_long_explanation_and_small_width(){
  var value=state("reading","feedback");value.subject.reading_mnemonic="An authored explanation. ".repeat(100);make(value)
  for(var size of [756,360]){
   surface.width=size;wait(5);var before=footer.mapToItem(surface,0,0).y
   scroll.contentItem.contentY=Math.max(0,scroll.contentHeight-scroll.availableHeight);wait(1)
   compare(footer.mapToItem(surface,0,0).y,before);verify(footer.y+footer.height<=surface.height-20+1)
   verify(playButton().visible);verify(playButton().width<=footer.width)
  }
 }
 function test_details_keyboard_and_next_answer_focus(){
  make(state("reading","feedback"));tryCompare(input(),"activeFocus",true)
  keyClick(Qt.Key_D,Qt.AltModifier);verify(findChild(page,"study-details-heading").activeFocus)
  owner.session=state("meaning");tryCompare(input(),"activeFocus",true)
  keyClick("v");compare(input().text,"v");keyClick(Qt.Key_Return);compare(owner.actions[0],{method:"answer",args:{text:"v"}})
 }
 function test_all_due_total_and_remaining_are_visible_at_narrow_width(){
  var value=state("reading");value.all_reviews=true;value.total=137;value.completed=23
  make(value);surface.width=360;wait(10)
  compare(findChild(page,"study-session-total").text,"23 / 137 subjects")
  compare(findChild(page,"study-reviews-remaining").text,"114 left in this session")
  verify(findChild(page,"study-reviews-remaining").visible)
  owner.session=Object.assign({},value,{finishing:true,total:25})
  compare(findChild(page,"study-reviews-remaining").text,"2 left before this batch ends")
 }
 function test_capture_authored_feedback(){
  make(state("reading","feedback"));wait(30)
  var dir=__CAPTURE__;if(dir){grabImage(surface).save(dir+"/review-dark.png");Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699";wait(30);grabImage(surface).save(dir+"/review-light.png")}
 }
 }
}
'''

def build(directory):
    import json
    foundation.build(directory)
    (directory/'tst_LessonFlow.qml').unlink()
    (directory/'tst_ReviewWorkspace.qml').write_text(HEAD+LAYOUT+CASES.replace('__WORD__',WORD).replace('__CAPTURE__',json.dumps(os.environ.get('WANIKANI_REVIEW_CAPTURE_DIR',''))))

class ReviewWorkspaceTests(unittest.TestCase):
    @unittest.skipUnless(foundation.RUNNER.is_file(),'Qt required')
    def test_production_review_and_pinned_actions(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-review-workspace-') as tmp:
            p=Path(tmp);build(p)
            r=subprocess.run([str(foundation.RUNNER),'-input',tmp,'-import',tmp],capture_output=True,text=True,timeout=30,env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
