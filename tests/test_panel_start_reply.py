"""Actual start/call callbacks with authored delayed replies and inert navigation."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path('/usr/lib/qt6/bin/qmltestrunner')
QML = r'''
import QtQuick
import QtTest
Item {
  id:root; width:320; height:300
  property bool opened:true
  property string view:"dashboard"
  property int navigationSequence:0
  property string contentAccess:"authored-account"
  property var service:backend
  property var snapshot:({settings:{batch_size:5},session:null,paused_graded:false,reviews:5})
  property var session:null
  property bool busy:false
  property string error:""
  property int focuses:0
  function navigate(value){view=value;navigationSequence++}
  function focusContent(){focuses++}
  __FUNCTIONS__
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property var pending:[]
    function request(method,args,callback){pending=pending.concat([{method:method,args:args,callback:callback}])}
  }
  QtObject {id:replacement;property bool ready:true;property bool locked:false}
  TestCase {
    name:"PanelStartReply";when:windowShown
    function init(){
      root.opened=true;root.view="dashboard";root.navigationSequence=0;root.contentAccess="authored-account"
      root.service=backend;root.session=null;root.busy=false;root.error="";root.focuses=0
      backend.ready=true;backend.locked=false;backend.pending=[]
      root.snapshot={settings:{batch_size:5},session:null,paused_graded:false,reviews:137}
    }
    function answer(index,value){backend.pending[index].callback(true,value,"");wait(1)}
    function test_current_explicit_start_keeps_mode_and_focus(){
      root.begin("lessons",3,[11,12,13]);compare(backend.pending.length,1)
      compare(backend.pending[0].method,"start");compare(backend.pending[0].args.mode,"lessons")
      compare(backend.pending[0].args.subjects,[11,12,13])
      answer(0,{id:"authored-lessons",mode:"lessons",phase:"lesson",draft:""})
      compare(root.session.id,"authored-lessons");compare(root.focuses,1)
    }
    function test_all_preference_and_explicit_batch_are_distinct(){
      root.snapshot={settings:{review_all:true,batch_size:10},session:null,paused_graded:false,reviews:137}
      root.begin("reviews");verify(backend.pending[0].args.all_reviews)
      root.begin("reviews",5);verify(!backend.pending[1].args.all_reviews);compare(backend.pending[1].args.limit,5)
      root.begin("reviews",10,undefined,false,true);verify(backend.pending[2].args.all_reviews)
      root.begin("lessons");verify(!backend.pending[3].args.all_reviews)
      root.begin("resume");verify(backend.pending[4].args.all_reviews)
    }
    function test_stale_start_never_replaces_new_view_or_refocuses_data(){return [
      {tag:"navigate-away"},{tag:"navigate-away-and-back"},{tag:"closed"},
      {tag:"account"},{tag:"replacement-service"},{tag:"unready"},{tag:"locked"}]}
    function test_stale_start_never_replaces_new_view_or_refocuses(data){
      root.begin("reviews")
      switch(data.tag){
        case "navigate-away":root.navigate("lookup");break
        case "navigate-away-and-back":root.navigate("lookup");root.navigate("study");break
        case "closed":root.opened=false;break
        case "account":root.contentAccess="new-account";break
        case "replacement-service":root.service=replacement;break
        case "unready":backend.ready=false;break
        case "locked":backend.locked=true;break
      }
      root.session={id:"current-sentinel",draft:"retained",errors:2}
      var before=JSON.stringify(root.session),view=root.view
      answer(0,{id:"old-reviews",mode:"reviews",draft:"old"})
      compare(JSON.stringify(root.session),before);compare(root.view,view);compare(root.focuses,0)
    }
    function test_later_start_owns_visible_reply_even_if_old_callback_arrives_last(){
      root.begin("reviews");root.begin("lessons")
      answer(1,{id:"latest-lessons",mode:"lessons",draft:"retained",errors:0})
      var before=JSON.stringify(root.session)
      answer(0,{id:"earlier-reviews",mode:"reviews",draft:""})
      compare(JSON.stringify(root.session),before);compare(root.focuses,1)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), 'QtTest required')
class PanelStartReplyTests(unittest.TestCase):
    def test_actual_start_callbacks_preserve_current_navigation(self):
        source = (ROOT / 'Panel.qml').read_text()
        functions = []
        for name in ('begin', 'call'):
            match = re.search(r'(?ms)^  function ' + name + r'\(.*?(?=^  function )', source)
            self.assertIsNotNone(match)
            functions.append(match.group(0))
        with tempfile.TemporaryDirectory(prefix='wanikani-start-reply-') as temporary:
            directory = Path(temporary)
            (directory / 'tst_Start.qml').write_text(QML.replace('__FUNCTIONS__', '\n'.join(functions)))
            result = subprocess.run([str(RUNNER), '-input', str(directory)], capture_output=True,
                text=True, timeout=20, env={**os.environ, 'QT_QPA_PLATFORM':'offscreen',
                'QT_QPA_PLATFORMTHEME':'', 'QT_QUICK_CONTROLS_STYLE':'Basic'})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn('QWARN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
