"""Actual fallback lock parsing, coalesced IO and delayed panel-open guards."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNNER=Path('/usr/lib/qt6/bin/qmltestrunner')
QML=r'''
import QtQuick
import QtTest
Item {
 id: root
 property var service: backend
 property string lastOpenResult: "idle"
 property int openSequence: 0
 property bool opened: false
 property int listenSequence: 0
 property bool listenBusy: false
 property int navigationSequence: 0
 property var accepted: []
 function stopAudio() {}
 function openChecked(payload) {opened=true;accepted=accepted.concat([payload])}
 __FUNCTIONS__
 QtObject {
  id:backend
  property var lockService:null
  property bool panelOpen:false
  property bool studying:false
  property var pending:[]
  function checkDesktop(callback){pending=pending.concat([callback])}
 }
 DesktopLock {id:state;active:false}
 TestCase {
  name:"DesktopLock";when:windowShown
  function unlocked(){return {locked:false,requested:false,pending:false,sessionLocked:false,secure:false}}
  function probe(){return findChild(state,"desktop-lock-probe")}
  function answer(value,code){probe().stdout.text=JSON.stringify(value);probe().running=false;probe().exited(code||0,0)}
  function init(){
   failOnWarning(/.*/);state.active=false;state.finish("",false);state.callbacks=[]
   root.service=backend;root.openSequence=0;root.opened=false;root.accepted=[];backend.pending=[];backend.lockService=null
  }
  function test_unknown_and_failed_reads_keep_locked(){
   verify(state.locked);state.active=true;answer(unlocked(),1);verify(state.locked);verify(!state.known)
   state.check();probe().stdout.text="not json";probe().running=false;probe().exited(0,0);verify(state.locked)
  }
  function test_all_five_flags_must_be_explicit_booleans(){
   state.active=true
   for(var name of Object.keys(unlocked())){
    var value=unlocked();delete value[name];state.check();answer(value);verify(state.locked);verify(!state.known)
    value=unlocked();value[name]="false";state.check();answer(value);verify(state.locked);verify(!state.known)
    value=unlocked();value[name]=true;state.check();answer(value);verify(state.locked);verify(state.known)
   }
   state.check();answer(unlocked());verify(state.known);verify(!state.locked)
  }
  function test_checks_coalesce_and_callbacks_are_once_only(){
   state.active=true;var replies=[]
   state.check(function(ok){replies.push(ok)});state.check(function(ok){replies.push(ok)})
   verify(probe().running);answer(unlocked());compare(replies,[true,true]);compare(state.callbacks.length,0)
   state.check();answer({});compare(replies.length,2);verify(state.locked)
   compare(probe().command,["timeout","--kill-after=1s","3s","omarchy-shell","lock","status"])
  }
  function test_disable_and_oversized_reply_fail_closed(){
   state.active=true;answer(unlocked());verify(!state.locked)
   state.finish(" ".repeat(4097),true);verify(state.locked)
   state.active=false;var allowed=true;state.check(function(ok){allowed=ok});verify(!allowed);verify(state.locked)
  }
  function test_open_waits_for_successful_lock_check(){
   root.open("dashboard");verify(!root.opened);compare(backend.pending.length,1)
   backend.pending[0](true);verify(root.opened);compare(root.accepted,["dashboard"])
  }
  function test_denied_open_does_not_show_panel(){
   root.open("dashboard");backend.pending[0](false);verify(!root.opened);compare(root.accepted,[])
  }
  function test_closed_replaced_or_superseded_requests_do_not_reopen_data(){return [{tag:"close"},{tag:"service"},{tag:"new-request"}]}
  function test_closed_replaced_or_superseded_requests_do_not_reopen(data){
   root.open("old")
   if(data.tag==="close")root.close()
   if(data.tag==="service")root.service=null
   if(data.tag==="new-request")root.open("latest")
   backend.pending[0](true);compare(root.accepted,[])
   if(data.tag==="new-request"){backend.pending[1](true);compare(root.accepted,["latest"])}
  }
  function test_legacy_shell_uses_live_service(){
   backend.lockService={locked:false};root.open("legacy");compare(root.accepted,["legacy"]);compare(backend.pending,[])
  }
 }
}
'''

@unittest.skipUnless(RUNNER.is_file(),'QtTest required')
class DesktopLockTests(unittest.TestCase):
    def test_actual_fallback_and_open_guards(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-desktop-lock-') as tmp:
            p=Path(tmp);(p/'io').mkdir()
            (p/'io/Process.qml').write_text('import QtQuick\nItem {property var command;property bool running:false;property var stdout;property var stderr;signal exited(int code,int status)}')
            (p/'io/StdioCollector.qml').write_text('import QtQuick\nQtObject {property string text:""}')
            (p/'DesktopLock.qml').write_text((ROOT/'qml/DesktopLock.qml').read_text().replace('import Quickshell.Io','import "io"'))
            shutil.copyfile(ROOT/'qml/LockStatus.mjs',p/'LockStatus.mjs')
            source=(ROOT/'Panel.qml').read_text()
            functions='\n'.join(re.search(r'(?ms)^  function '+name+r'\(.*?(?=^  function )',source).group(0) for name in ('open','close'))
            (p/'tst_DesktopLock.qml').write_text(QML.replace('__FUNCTIONS__',functions))
            r=subprocess.run([str(RUNNER),'-input',str(p)],capture_output=True,text=True,timeout=20,env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertNotIn('QWARN',r.stdout+r.stderr)
