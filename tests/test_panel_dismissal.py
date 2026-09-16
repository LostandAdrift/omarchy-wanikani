"""Exercise the production outside-click wiring with an inert compositor grab."""
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
 id: root
 property bool opened: true
 property var snapshot: ({settings:{}})
 __PREFERENCE__
 property int openSequence: 0
 property string lastOpenResult: "idle"
 property int listenSequence: 0
 property bool listenBusy: false
 property int navigationSequence: 0
 property string pluginId: "authored-plugin"
 property var service: backend
 property var shell: host
 property var session: ({draft:"ろく",errors:1,phase:"feedback",revision:4})
 property int stops: 0
 function stopAudio(){stops++}
 QtObject {id:backend;property bool panelOpen:true;property bool studying:true}
 QtObject {id:host;property int hides:0;function hide(id){hides++}}
 Item {id:window}
 __FUNCTIONS__
 __GRAB__
 TestCase {
  name:"ClickAway";when:windowShown
  function init(){failOnWarning(/.*/);root.opened=true;root.snapshot={settings:{}};backend.panelOpen=true;backend.studying=true;host.hides=0;root.stops=0}
  function test_compositor_clear_closes_without_advancing_or_discarding(){
   verify(grab.active);compare(grab.windows,[window]);var saved=JSON.stringify(root.session)
   grab.cleared();verify(!root.opened);verify(!backend.panelOpen);verify(!backend.studying)
   compare(host.hides,1);compare(root.stops,1);compare(JSON.stringify(root.session),saved)
   grab.cleared();compare(host.hides,1)
  }
  function test_opt_out_ignores_grab_release_and_background_click(){
   root.snapshot={settings:{close_on_outside_click:false}};verify(!grab.active)
   grab.cleared();root.dismissOutside();verify(root.opened);compare(host.hides,0)
   root.dismiss();verify(!root.opened);compare(host.hides,1)
  }
  function test_hidden_surface_never_keeps_a_grab(){root.opened=false;verify(!grab.active);grab.cleared();compare(host.hides,0)}
  function test_switching_back_on_rearms(){root.snapshot={settings:{close_on_outside_click:false}};root.snapshot={settings:{close_on_outside_click:true}};verify(grab.active);root.dismissOutside();verify(!root.opened)}
 }
}
'''

class ClickAwayTests(unittest.TestCase):
    @unittest.skipUnless(RUNNER.is_file(), 'QtTest required')
    def test_actual_grab_and_dismissal_functions(self):
        source = (ROOT/'Panel.qml').read_text()
        functions = '\n'.join(re.search(r'(?ms)^  function '+name+r'\(.*?(?=^  function )', source).group() for name in ('close','dismiss','dismissOutside'))
        preference = re.search(r'^  readonly property bool closeOnOutsideClick:.*$', source, re.M).group()
        grab = re.search(r'    HyprlandFocusGrab \{.*?\n    \}', source, re.S).group().replace('HyprlandFocusGrab {','FakeGrab {\n      id: grab')
        with tempfile.TemporaryDirectory(prefix='wanikani-click-away-') as tmp:
            p=Path(tmp)
            (p/'FakeGrab.qml').write_text('import QtQuick\nQtObject {property bool active:false;property var windows:[];signal cleared()}')
            (p/'tst_ClickAway.qml').write_text(QML.replace('__PREFERENCE__',preference).replace('__FUNCTIONS__',functions).replace('__GRAB__',grab))
            result=subprocess.run([str(RUNNER),'-input',tmp],capture_output=True,text=True,timeout=20,env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':''})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
