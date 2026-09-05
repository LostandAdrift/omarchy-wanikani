"""Actual Panel listening callbacks against inert audio and worker adapters."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path('/usr/lib/qt6/bin/qmltestrunner')


def function(source, name):
    match = re.search(r'(?ms)^  function ' + re.escape(name) + r'\(.*?^  \}', source)
    if not match:
        raise AssertionError('Review function boundary: ' + name)
    return match.group(0)


QML = r'''
import QtQuick
import QtTest
Item {
  ServiceCore { id: backend }
  PanelCore { id: panel; service: backend }
  TestCase {
    name: "ListeningPanel"
    function snapshot(revision) {
      return {demo:false,username:"authored",max_level:3,session_epoch:"authored-epoch",session_revision:0,
        state_revision:revision,last_sync:"same",pending:0,attention:0,settings:{autoplay_listening:true}}
    }
    function session(revision,phase) {
      return {id:"listen-one",revision:revision,phase:phase||"question",index:0,media_handle:"opaque-fixture",
        subject:phase==="revealed"?{id:1,characters:"火山",readings:["かざん"],meanings:["volcano"]}:null}
    }
    function media(revision) {
      return {handle:"opaque-fixture",uri:"file:///authored-inert-recording.mp3",session:session(revision),voice:"Authored voice"}
    }
    function init() {
      panel.close()
      backend.pending = []
      backend.ready = true
      backend.locked = false
      backend.snapshot = snapshot(1)
      backend.stateOrder = backend.initialOrder(backend.snapshot)
      panel.view = "listen"
      panel.listenSession = session(1)
      panel.listenStatus = {available:5}
      panel.listenError = ""
      panel.listenBusy = false
      panel.audioSource = ""
      panel.audioEvents = []
      panel.opened = true
      wait(0)
      backend.pending = []
      panel.listenBusy = false
      panel.listenSession = session(1)
    }
    function cleanup() { panel.close(); wait(0) }
    function reply(index,ok,data,error) { backend.pending[index].callback(ok,data,error||"") }
    function test_media_revision_is_applied_before_uri_and_play() {
      panel.playListening()
      verify(panel.listenBusy)
      compare(backend.pending[0].method,"listen_media")
      compare(backend.pending[0].args.handle,"opaque-fixture")
      reply(0,true,media(2))
      verify(!panel.listenBusy)
      compare(panel.listenSession.revision,2)
      compare(panel.audioEvents.length,2)
      compare(panel.audioEvents[0],{action:"source",revision:2})
      compare(panel.audioEvents[1],{action:"play",revision:2})
      panel.listenAction("reveal")
      compare(backend.pending[1].args.session_id,"listen-one")
      compare(backend.pending[1].args.revision,2)
    }
    function test_cancel_media_recovers_busy_and_rejects_late_audio() {
      panel.playListening()
      panel.stopAudio()
      reply(0,true,media(2))
      compare(panel.audioEvents.length,0)
      verify(!panel.listenBusy,"Cancelling a media request must release its busy state")
      panel.playListening()
      compare(backend.pending.length,2)
    }
    function test_summon_during_lock_cannot_open_or_start_study() {
      backend.locked=true
      panel.open('{"view":"reviews","limit":5}')
      verify(!panel.opened)
      verify(!backend.panelOpen)
      verify(!backend.studying)
      compare(backend.pending.length,0)
      compare(panel.audioEvents.length,0)
    }
    function test_failure_requires_explicit_retry_without_automatic_queries() {
      panel.playListening()
      reply(0,false,null,"Authored media failure")
      verify(!panel.listenBusy)
      compare(panel.audioState,"failed")
      compare(panel.audioNotice,"Authored media failure")
      wait(50)
      compare(backend.pending.length,1)
      compare(panel.audioEvents.length,0)
      panel.playListening()
      compare(backend.pending.length,2)
    }
    function test_mismatched_handle_is_not_played() {
      panel.playListening()
      var stale=media(2);stale.handle="different"
      reply(0,true,stale)
      verify(!panel.listenBusy)
      compare(panel.listenSession.revision,1)
      compare(panel.audioEvents.length,0)
      compare(panel.audioState,"failed")
    }
    function test_late_reply_data() {
      var cases=[]
      for (var action of ["media","reveal"])
        for (var edge of ["close","navigation","lock","account","accepted-state","restart"])
          cases.push({tag:action+"-"+edge,action:action,edge:edge})
      return cases
    }
    function test_late_reply(data) {
      if (data.action==="media") panel.playListening()
      else panel.listenAction("reveal")
      var pending=backend.pending[0]
      if (data.edge==="close") panel.close()
      if (data.edge==="navigation") panel.navigate("zen")
      if (data.edge==="lock") backend.locked=true
      if (data.edge==="account") backend.applySnapshot(Object.assign(snapshot(2),{username:"second"}))
      if (data.edge==="accepted-state") backend.applySnapshot(snapshot(2))
      if (data.edge==="restart") backend.ready=false
      pending.callback(true,data.action==="media"?media(2):{session:session(2,"revealed")},"")
      compare(panel.audioEvents.length,0)
      verify(!panel.listenSession || panel.listenSession.phase!=="revealed")
      verify(!panel.listenBusy)
      if (data.edge==="restart") backend.ready=true
      wait(0)
      compare(panel.audioEvents.length,0)
      // Visible state invalidation can request one new read, never another play/reveal.
      verify(backend.pending.slice(1).every(function (request) { return request.method==="listen_state" }))
      if (!panel.opened || panel.view!=="listen") compare(backend.pending.length,1)
    }
    function test_rejected_old_full_state_does_not_cancel_current_media() {
      backend.applySnapshot(snapshot(3))
      wait(0)
      backend.pending=[]
      panel.listenBusy=false
      panel.listenSession=session(1)
      panel.playListening()
      backend.applySnapshot(snapshot(2))
      reply(0,true,media(2))
      compare(panel.audioEvents.length,2)
      compare(panel.listenSession.revision,2)
    }
    function test_load_is_coalesced_and_resume_never_autoplays() {
      panel.loadListening()
      panel.loadListening()
      compare(backend.pending.length,1)
      reply(0,true,{status:{available:4},session:session(4)})
      verify(!panel.listenBusy)
      compare(panel.listenSession.revision,4)
      compare(panel.audioEvents.length,0)
      wait(20)
      compare(backend.pending.length,1)
    }
    function test_hidden_gates_all_listening_entry_points() {
      for (var edge of ["closed","different-page","unready","locked"]) {
        panel.close()
        backend.ready=true;backend.locked=false;panel.view="listen";panel.opened=true
        if(edge==="closed")panel.opened=false
        if(edge==="different-page")panel.view="zen"
        if(edge==="unready")backend.ready=false
        if(edge==="locked")backend.locked=true
        backend.pending=[]
        panel.loadListening();panel.listenAction("start");panel.playListening()
        wait(0)
        compare(backend.pending.length,0)
      }
    }
    function test_action_failure_recovers_and_completed_session_refreshes_once() {
      panel.listenAction("reveal")
      reply(0,false,null,"Authored save failure")
      compare(panel.listenError,"Authored save failure")
      verify(!panel.listenBusy)
      wait(0)
      compare(backend.pending.length,1)
      panel.listenAction("skip")
      reply(1,true,{session:session(3,"complete")})
      wait(0)
      compare(backend.pending.length,3)
      compare(backend.pending[2].method,"listen_state")
      reply(2,true,{status:{available:0},session:session(3,"complete")})
      wait(0)
      compare(backend.pending.length,3)
    }
  }
}
'''


def build(directory):
    panel=(ROOT/'Panel.qml').read_text()
    service=(ROOT/'Service.qml').read_text()
    bindings = '\n'.join(re.search(r'(?m)^  '+re.escape(prefix)+'.*$',panel).group(0) for prefix in
        ('readonly property string listenContext:', 'onListenContextChanged:', 'readonly property string contentAccess:'))
    access = re.search(r'(?ms)^  onContentAccessChanged: \{.*?^  \}',panel).group(0)
    connections = re.search(r'(?ms)^  Connections \{\n    target: root.service.*?^  \}',panel).group(0)
    (directory/'PanelCore.qml').write_text('''import QtQuick
Item {
 id: root
 required property var service
 property bool opened: false
 property string view: "listen"
 readonly property var snapshot: service.snapshot
 property var listenSession: null
 property var listenStatus: null
 property bool listenBusy: false
 property string listenError: ""
 property string listenPreparationNotice: ""
 property int listenSequence: 0
 property int navigationSequence: 0
 property bool moreNavigation: false
 property var detail: null
 property bool progressReturn: false
 property var progressNavigation: ({})
 property var session: null
 property string error: ""
 property string observedSync: ""
 property var helpReturnDetail: null
 property var results: []
 property int searchSequence: 0
 property bool searching: false
 property string query: ""
 property var shell: null
 property string pluginId: "authored"
 property int audioSequence: 0
 property string audioContext: ""
 property int audioSubjectId: -1
 property int audioParentSubjectId: -1
 property var audioExample: null
 property string audioState: ""
 property string audioNotice: ""
 property var audioEvents: []
 property alias audioSource: audio.source
 function focusContent() {}
 function refreshSearch() {}
 function search(value) {}
 QtObject {
   id: audio
   property string source: ""
   onSourceChanged: if (source) root.audioEvents = root.audioEvents.concat([{action:"source",revision:root.listenSession.revision}])
   function play() { root.audioEvents = root.audioEvents.concat([{action:"play",revision:root.listenSession.revision}]) }
   function stop() {}
 }
''' + bindings+'\n'+access+'\n'+connections+'\n'+'\n'.join(function(panel,name) for name in
        ('open','close','dismiss','navigate','stopAudio','invalidateListening','listenCurrent','loadListening','listenAction','playListening'))+'\n}\n')
    (directory/'ServiceCore.qml').write_text('''import QtQuick
import "SessionState.mjs" as SessionState
Item {
 id: root
 property bool ready: true
 property bool locked: false
 property bool studying: false
 property bool panelOpen: false
 property var snapshot: ({})
 property var stateOrder: SessionState.initial()
 property var pending: []
 property var ambientItems: []
 function initialOrder(value) { return SessionState.full(SessionState.initial(),value) }
 function request(method,args,callback) { pending=pending.concat([{method:method,args:args,callback:callback}]) }
 function considerNotification() {}
 function refreshAmbient() {}
'''+'\n'.join(function(service,name) for name in ('ordering','applySnapshot'))+'\n}\n')
    shutil.copyfile(ROOT/'qml/SessionState.mjs',directory/'SessionState.mjs')
    (directory/'tst_ListeningPanel.qml').write_text(QML)


@unittest.skipUnless(RUNNER.is_file(), 'QtTest runtime is not installed')
class ListeningPanelTests(unittest.TestCase):
    def test_source_derived_listening_adapter(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-listening-panel-') as temporary:
            directory=Path(temporary)
            build(directory)
            result=subprocess.run([str(RUNNER),'-input',str(directory)],capture_output=True,text=True,timeout=30,
                env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
        output=result.stdout+result.stderr
        self.assertEqual(result.returncode,0,output)
        self.assertNotIn('QWARN',output)


if __name__=='__main__':
    unittest.main()
