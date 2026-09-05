"""Source-derived Panel callbacks: commit in place and preserve passage return."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_listening_panel import function

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path('/usr/lib/qt6/bin/qmltestrunner')
QML = r'''
import QtQuick
import QtTest
Item {
  PanelCore {id:panel}
  QtObject {id:other;property bool ready:true;property bool locked:false}
  TestCase {
    name:"TrailPracticePanel"
    function preview(){return {text:panel.query,data_epoch:panel.sessionEpoch,can_start:true,
      subject_ids:[2,4],saved_practice:{present:false,revision:null}}}
    function result(){return {id:"authored-practice",mode:"practice",phase:"question",revision:8}}
    function reply(ok,data){panel.pending[panel.pending.length-1](ok,data||result())}
    function init(){
      failOnWarning(/.*/)
      panel.opened=true;panel.view="lookup";panel.detail=null;panel.busy=false
      panel.service=panel.defaultService;panel.defaultService.ready=true;panel.defaultService.locked=false
      panel.query="山と水。";panel.sessionEpoch="01234567-89ab-4cde-8fab-0123456789ab";panel.contentAccess="authored-account"
      panel.navigationSequence=1;panel.trailPracticeSequence=0;panel.session=null
      panel.trailPracticeSelection=({});panel.trailPracticeReturn=null;panel.calls=[];panel.pending=[];panel.navigations=[];panel.focuses=0
    }
    function test_start_waits_for_durable_reply_without_losing_passage(){
      var value=preview();panel.beginTrailPractice(value,false)
      compare(panel.view,"lookup");compare(panel.query,"山と水。");compare(panel.calls.length,1)
      compare(panel.calls[0].method,"trail_practice_start")
      compare(JSON.stringify(panel.calls[0].args),JSON.stringify({text:"山と水。",subject_ids:[2,4],
        expected_data_epoch:panel.sessionEpoch,expected_saved_practice_revision:null,replace_existing:false}))
      value.subject_ids.push(999)
      compare(panel.calls[0].args.subject_ids.length,2)
      reply(true);compare(panel.view,"study");compare(panel.session.id,"authored-practice")
      compare(panel.trailPracticeSelection.text,"山と水。");compare(panel.trailPracticeSelection.ids.length,2)
      tryCompare(panel,"focuses",1)
    }
    function test_replacement_is_explicit_and_preserves_expected_revision(){
      var value=preview();value.saved_practice={present:true,revision:17}
      panel.beginTrailPractice(value,true)
      compare(panel.calls[0].args.expected_saved_practice_revision,17)
      compare(panel.calls[0].args.replace_existing,true)
    }
    function test_invalid_or_unavailable_entry_never_dispatches_data(){
      return ["closed","wrongview","detail","busy","unready","locked","noowner","missing","passage","epoch","notready","empty","large"].map(function(value){return {tag:value,kind:value}})
    }
    function test_invalid_or_unavailable_entry_never_dispatches(data){
      var value=preview()
      switch(data.kind){
        case "closed":panel.opened=false;break
        case "wrongview":panel.view="progress";break
        case "detail":panel.detail={id:2};break
        case "busy":panel.busy=true;break
        case "unready":panel.defaultService.ready=false;break
        case "locked":panel.defaultService.locked=true;break
        case "noowner":panel.service=null;break
        case "missing":value=null;break
        case "passage":value.text="火山";break
        case "epoch":value.data_epoch="old-epoch";break
        case "notready":value.can_start=false;break
        case "empty":value.subject_ids=[];break
        case "large":value.subject_ids=Array.from({length:21},function(_,i){return i+1});break
      }
      panel.beginTrailPractice(value,false);compare(panel.calls.length,0)
    }
    function test_late_result_cannot_reopen_or_replace_new_context_data(){
      return ["closed","navigation","query","account","owner","locked","unready","detail","superseded"].map(function(value){return {tag:value,kind:value}})
    }
    function test_late_result_cannot_reopen_or_replace_new_context(data){
      panel.beginTrailPractice(preview(),false)
      switch(data.kind){
        case "closed":panel.opened=false;break
        case "navigation":panel.navigate("dashboard");break
        case "query":panel.query="別の文";break
        case "account":panel.contentAccess="different-account";break
        case "owner":panel.service=other;break
        case "locked":panel.defaultService.locked=true;break
        case "unready":panel.defaultService.ready=false;break
        case "detail":panel.detail={id:9};break
        case "superseded":panel.trailPracticeSequence++;break
      }
      reply(true);verify(panel.view!=="study");compare(panel.session,null);compare(panel.trailPracticeReturn,null)
    }
    function test_failed_start_keeps_selection_and_passage_in_place(){
      panel.trailPracticeSelection={schema:1,text:panel.query,ids:[2,4]}
      panel.beginTrailPractice(preview(),true);reply(false)
      compare(panel.view,"lookup");compare(panel.query,"山と水。")
      compare(panel.trailPracticeSelection.ids.length,2);compare(panel.trailPracticeReturn,null)
    }
    function test_back_to_passage_is_navigation_only_and_keeps_exact_session(){
      panel.beginTrailPractice(preview(),false);reply(true)
      panel.session={id:"authored-practice",mode:"practice",phase:"feedback",draft:"saved kana",errors:{reading:1}}
      var original=JSON.stringify(panel.session),calls=panel.calls.length
      panel.returnToTrail();compare(panel.view,"lookup");compare(panel.query,"山と水。")
      compare(JSON.stringify(panel.session),original);compare(panel.calls.length,calls)
      compare(panel.trailPracticeSelection.ids.length,2)
    }
    function test_an_unrelated_or_graded_session_cannot_claim_the_old_passage(){
      panel.trailPracticeReturn={session_id:"authored-practice",text:"山と水。"};panel.view="study"
      panel.session={id:"another",mode:"practice"};panel.returnToTrail();compare(panel.view,"study")
      panel.session={id:"authored-practice",mode:"reviews"};panel.returnToTrail();compare(panel.view,"study")
      compare(panel.calls.length,0)
    }
  }
}
'''


def build(directory):
    source = (ROOT / 'Panel.qml').read_text()
    methods = '\n'.join(function(source, name) for name in ('beginTrailPractice', 'returnToTrail'))
    (directory / 'PanelCore.qml').write_text('''import QtQuick
Item {
 id:root
 property bool opened:true
 property string view:"lookup"
 property var detail:null
 property bool busy:false
 property var service:defaultService
 property alias defaultService:defaultService
 property string query:""
 property string sessionEpoch:""
 property string contentAccess:""
 property int navigationSequence:0
 property int trailPracticeSequence:0
 property var trailPracticeSelection:({})
 property var trailPracticeReturn:null
 property var session:null
 property var calls:[]
 property var pending:[]
 property var navigations:[]
 property int focuses:0
 QtObject {id:defaultService;property bool ready:true;property bool locked:false}
 function call(method,args,callback){calls=calls.concat([{method:method,args:args}]);pending=pending.concat([callback])}
 function navigate(next){view=next;detail=null;navigationSequence++;navigations=navigations.concat([next])}
 function search(text){query=text}
 function focusContent(){focuses++}
''' + methods + '\n}\n')
    (directory / 'tst_TrailPracticePanel.qml').write_text(QML)


@unittest.skipUnless(RUNNER.is_file(), 'QtTest required')
class TrailPracticePanelTests(unittest.TestCase):
    def test_actual_panel_start_and_passage_return_callbacks(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-trail-panel-') as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(RUNNER), '-input', str(directory), '-import', str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn('QWARN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
