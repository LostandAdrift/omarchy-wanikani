"""The actual recap pages large authored sessions with native action controls."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation

QML = r'''
import QtQuick
import QtTest
import "qml" as Kani
Item {
 width:360;height:4000
 QtObject {
  id:backend
  signal snapshotChanged()
  property var requests:[]
  function request(method,args,callback){
   requests=requests.concat([args]);var items=[]
   for(var i=args.offset;i<Math.min(45,args.offset+20);i++)items.push({subject:{id:i+1,label:"山",meaning:"Authored mountain",accessible:true,spoilers_hidden:false},done:true,errors:{total:0},state:"pending",status_label:"Saved",practice_ready:true})
   Qt.callLater(function(){callback(true,{mode:"reviews",offset:args.offset,total:45,has_more:args.offset+20<45,items:items,mistake_ids:[],practice_ids:items.map(function(x){return x.subject.id})},"")})
  }
 }
 QtObject {
  id:owner
  property var service:backend
  property bool opened:true
  property bool busy:false
  property string contentAccess:"authored"
  property var snapshot:({})
  property var starts:[]
  function begin(mode,limit,ids,replace){starts=starts.concat([{mode:mode,limit:limit,ids:ids}])}
  function navigate(view){}
  function showSubject(id){}
 }
 Kani.SessionRecap {id:recap;width:360;controller:owner;session:({id:"large-authored",phase:"complete"})}
 TestCase {
  name:"LargeSessionRecap";when:windowShown
  function test_pages_keep_practice_bounded_and_use_keyboard(){
   failOnWarning(/.*/)
   tryVerify(function(){return recap.report!==null})
   recap.expanded=true
   compare(recap.report.items.length,20);compare(recap.report.practice_ids.length,20)
   var next=findChild(recap,"recap-next-page"),previous=findChild(recap,"recap-previous-page")
   verify(next.enabled);verify(!previous.enabled)
   next.forceActiveFocus();keyClick(Qt.Key_Return)
   tryCompare(recap,"loading",false);compare(recap.report.offset,20)
   compare(recap.report.items.length,20);verify(previous.enabled)
   next.forceActiveFocus();keyClick(Qt.Key_Return)
   tryCompare(recap,"loading",false);compare(recap.report.offset,40)
   compare(recap.report.items.length,5);verify(!next.enabled)
   recap.practice(recap.report.practice_ids)
   compare(owner.starts[0].limit,5);compare(owner.starts[0].ids,[41,42,43,44,45])
   previous.forceActiveFocus();keyClick(Qt.Key_Return)
   tryCompare(recap,"loading",false);compare(recap.report.offset,20)
   compare(backend.requests.map(function(x){return x.offset}),[0,20,40,20])
  }
 }
}
'''


class SessionRecapUiTests(unittest.TestCase):
    @unittest.skipUnless(foundation.RUNNER.is_file(), "Qt required")
    def test_paged_recap_with_real_actions(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-paged-recap-") as temporary:
            directory = Path(temporary)
            foundation.build(directory)
            (directory / "tst_LessonFlow.qml").unlink()
            shutil.copyfile(foundation.ROOT / "qml/SessionRecap.qml", directory / "qml/SessionRecap.qml")
            (directory / "tst_Recap.qml").write_text(QML)
            result = subprocess.run([str(foundation.RUNNER), "-input", temporary, "-import", temporary],
                capture_output=True, text=True, timeout=30, env={**os.environ, "QT_QPA_PLATFORM":"offscreen",
                    "QT_QPA_PLATFORMTHEME":"", "QT_QUICK_CONTROLS_STYLE":"Basic"})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
