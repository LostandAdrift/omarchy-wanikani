"""Real preparation UI and source-derived IPC; no host, audio device or network."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_listening_panel as panel_fixture
import test_listening_rendering as rendering


ROOT, RUNNER = panel_fixture.ROOT, panel_fixture.RUNNER


ADAPTER = r'''
import QtQuick
import QtTest
Item {
  ServiceCore { id: backend }
  PanelCore { id: panel; service: backend }
  TestCase {
    name: "ListeningPreparationAdapter"
    function base() { return {demo:false,username:"authored",max_level:3,session_epoch:"one",session_revision:0,
      state_revision:1,last_sync:"same",pending:0,attention:0,settings:{autoplay_listening:true}} }
    function result() { return {status:"ready",reason:"ready",downloaded:3,already_cached:2,failed:0,skipped_budget:0,complete:true,cancelled:false} }
    function finalReply(id,ok,data) { backend.receive(JSON.stringify({v:1,id:id,ok:ok,data:data,error:ok?null:{message:"Authored preparation failure"}})) }
    function progress(id,count) { backend.receive(JSON.stringify({v:1,event:"listening_preparation",data:{job_id:id,downloaded:count,already_cached:0,failed:0,skipped_budget:0}})) }
    function methods() { return backend.writes.map(function(value){return value.method}) }
    function init() {
      failOnWarning(/.*/)
      panel.opened=false;backend.ready=false;backend.locked=false
      backend.callbacks={};backend.requestContexts={};backend.pendingCount=0
      backend.listeningPreparationJobId="";backend.listeningPreparationProgress=null;backend.listeningPreparationCancelling=false
      backend.snapshot=base();backend.ready=true;panel.view="listen";panel.opened=true
      wait(0)
      backend.writes=[];backend.callbacks={};backend.requestContexts={};backend.pendingCount=0
      panel.listenBusy=false;panel.listenSession=null;panel.listenStatus={available:2};panel.listenPreparationNotice=""
      panel.audioEvents=[];panel.audioContext="";panel.audioState="";panel.audioNotice=""
    }
    function cleanup() { panel.opened=false;backend.ready=false;backend.callbacks={};backend.listeningPreparationJobId="";wait(0) }
    function test_opening_and_readiness_never_prepare_or_play() {
      wait(30)
      compare(backend.writes.length,0);compare(panel.audioEvents.length,0)
      backend.receive(JSON.stringify({v:1,event:"readiness",data:{ready:true}}))
      wait(30)
      verify(methods().every(function(method){return method==="listen_state"}))
      compare(panel.audioEvents.length,0)
    }
    function test_explicit_action_uses_empty_arguments_and_count_only_progress() {
      panel.prepareListening()
      var job=backend.listeningPreparationJobId
      verify(job.length>0);compare(methods(),["listen_prepare"]);compare(backend.writes[0].args,{})
      progress("different-job",4);compare(backend.listeningPreparationProgress.downloaded,0)
      progress(job,2);compare(backend.listeningPreparationProgress.downloaded,2)
      compare(panel.audioEvents.length,0);compare(panel.listenSession,null)
      finalReply(job,true,result())
      compare(backend.listeningPreparationJobId,"")
      verify(panel.listenPreparationNotice.indexOf("3 recordings saved")>=0)
      compare(methods(),["listen_prepare","listen_state"])
      compare(panel.audioEvents.length,0);compare(panel.listenSession,null)
      progress(job,5);compare(backend.listeningPreparationProgress.downloaded,3)
    }
    function test_cancel_is_one_matching_job_request_and_keeps_busy_until_final_reply() {
      panel.prepareListening();var job=backend.listeningPreparationJobId
      backend.cancelListeningPreparation();backend.cancelListeningPreparation();panel.prepareListening()
      compare(methods(),["listen_prepare","listen_prepare_cancel"])
      compare(backend.writes[1].args,{job_id:job});verify(backend.listeningPreparationCancelling)
      compare(backend.listeningPreparationJobId,job)
      finalReply(backend.writes[1].id,true,{cancelled:true})
      compare(backend.listeningPreparationJobId,job)
      finalReply(job,true,Object.assign(result(),{status:"cancelled",reason:"cancelled",cancelled:true,complete:false}))
      compare(backend.listeningPreparationJobId,"");verify(!backend.listeningPreparationCancelling)
      verify(panel.listenPreparationNotice.indexOf("Preparation stopped")>=0)
      compare(panel.audioEvents.length,0)
    }
    function test_failed_preparation_releases_controls_and_requires_another_deliberate_action() {
      panel.prepareListening();var job=backend.listeningPreparationJobId
      finalReply(job,false,null);compare(backend.listeningPreparationJobId,"")
      compare(panel.listenPreparationNotice,"Authored preparation failure")
      compare(methods(),["listen_prepare","listen_state"])
      finalReply(backend.writes[1].id,true,{status:{available:2},session:null})
      wait(30);compare(methods(),["listen_prepare","listen_state"])
      panel.prepareListening();compare(methods(),["listen_prepare","listen_state","listen_prepare"])
      compare(panel.audioEvents.length,0)
    }
    function test_late_completion_data() {
      return ["close","navigation","lock","account","restart"].map(function(edge){return {tag:edge,edge:edge}})
    }
    function test_late_completion(data) {
      panel.prepareListening();var job=backend.listeningPreparationJobId
      if(data.edge==="close")panel.close()
      if(data.edge==="navigation")panel.navigate("zen")
      if(data.edge==="lock")backend.locked=true
      if(data.edge==="account")backend.snapshot=Object.assign(base(),{username:"other",session_epoch:"two"})
      if(data.edge==="restart")backend.restartWorker()
      var before=methods().filter(function(method){return method==="listen_state"}).length
      progress(job,4)
      if(data.edge==="account"||data.edge==="restart")compare(backend.listeningPreparationProgress,null)
      finalReply(job,true,result());wait(0)
      compare(panel.listenPreparationNotice,"");compare(panel.audioEvents.length,0)
      verify(methods().every(function(method){return ["listen_prepare","listen_prepare_cancel","listen_state"].indexOf(method)>=0}))
      if(data.edge!=="account")compare(methods().filter(function(method){return method==="listen_state"}).length,before)
      if(["close","navigation","lock","account"].indexOf(data.edge)>=0)
        compare(methods().filter(function(method){return method==="listen_prepare_cancel"}).length,1)
      if(data.edge!=="restart")compare(backend.listeningPreparationJobId,"")
      if(data.edge==="restart") {
        backend.receive(JSON.stringify({v:1,event:"ready"}));wait(0)
        compare(backend.listeningPreparationJobId,"")
        compare(methods().filter(function(method){return method==="listen_prepare"}).length,1)
      }
    }
    function test_previous_visit_completion_cannot_overwrite_reopened_listen_data() {
      return [{tag:"close-reopen",navigation:false},{tag:"navigate-away-and-back",navigation:true}]
    }
    function test_previous_visit_completion_cannot_overwrite_reopened_listen(data) {
      panel.prepareListening();var job=backend.listeningPreparationJobId
      if(data.navigation) {
        panel.navigate("zen");panel.navigate("listen");wait(0)
        var read=backend.writes[backend.writes.length-1]
        compare(read.method,"listen_state");finalReply(read.id,true,{status:{available:2},session:null})
      } else {panel.close();panel.opened=true;panel.view="listen"}
      panel.listenPreparationNotice="New visit notice"
      var before=backend.writes.length
      finalReply(job,true,result());wait(0)
      compare(panel.listenPreparationNotice,"New visit notice")
      compare(backend.writes.length,before)
      compare(panel.audioEvents.length,0)
    }
    function test_old_completion_cannot_release_a_newer_job_after_worker_restart() {
      panel.prepareListening();var old=backend.listeningPreparationJobId
      backend.restartWorker();backend.receive(JSON.stringify({v:1,event:"ready"}));wait(0)
      panel.listenBusy=false;panel.prepareListening();var current=backend.listeningPreparationJobId
      verify(current!==old);verify(current.length>0)
      progress(old,5);finalReply(old,true,result())
      compare(backend.listeningPreparationJobId,current)
      compare(backend.listeningPreparationProgress.downloaded,0)
      compare(panel.audioEvents.length,0)
    }
    function test_hidden_locked_unready_and_busy_actions_are_inert() {
      for(var edge of ["closed","navigation","locked","unready","busy"]) {
        backend.ready=true;backend.locked=false;panel.opened=true;panel.view="listen";panel.listenBusy=false
        if(edge==="closed")panel.opened=false
        if(edge==="navigation")panel.view="zen"
        if(edge==="locked")backend.locked=true
        if(edge==="unready")backend.ready=false
        if(edge==="busy")panel.listenBusy=true
        backend.writes=[];panel.prepareListening()
        compare(backend.writes.length,0,edge)
      }
    }
  }
}
'''


VISUAL_TESTS = r'''
  TestCase {
    name: "ListeningPreparationRendering";when:windowShown
    function ready() { return {available:2,new_remaining:5,complete:true,saved:null,settings:{avoid_due_24h:true},
      preparation:{ready:2,needs_download:3,complete:true,reason:"needs_download",message:"Three recordings can be prepared."}} }
    function descendants(item) {
      var output=[]
      for(var child of item.children){output.push(child);output=output.concat(descendants(child))}
      return output
    }
    function visibleTexts() { return descendants(screen).filter(function(item){return item.text!==undefined&&item.visible}) }
    function make() {screen=page.createObject(parent);verify(screen!==null);verify(waitForRendering(screen))}
    function button(name) {var control=findChild(screen,name);verify(control!==null,name);return control}
    function init() {
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;service.listeningPreparationJobId="";service.listeningPreparationProgress=null
      service.listeningPreparationCancelling=false;service.cancelCount=0
      owner.service=service;owner.opened=true;owner.listenBusy=false;owner.listenSession=null;owner.listenStatus=ready()
      owner.listenError="";owner.listenPreparationNotice="";owner.plays=0;owner.actions=[];owner.prepares=0
      owner.audioContext="";owner.audioState="";owner.audioNotice="";owner.snapshot={settings:{autoplay_listening:true}}
      Color.background="#ffffff";Color.foreground="#202020";Color.accent="#006699"
    }
    function cleanup() {if(screen)screen.destroy();screen=null;wait(1)}
    function test_preflight_is_visible_and_never_automatically_downloads_or_plays() {
      make();wait(30);compare(owner.prepares,0);compare(owner.plays,0);compare(owner.actions.length,0)
      verify(button("listeningPrepare").visible);compare(button("listeningPrepare").text,"Prepare 5 recordings")
      verify(button("listeningPrepare").accessibleHint.indexOf("without starting study or playing audio")>=0)
      button("listeningPrepare").clicked();compare(owner.prepares,1)
      compare(owner.plays,0);compare(owner.actions.length,0)
    }
    function test_single_ready_word_and_missing_recording_use_truthful_singular_labels() {
      owner.listenStatus=Object.assign(ready(),{available:1,
        preparation:{ready:0,needs_download:1,complete:true,reason:"needs_download"}})
      make()
      compare(button("listeningStart").text,"Listen to 1 word")
      compare(button("listeningPrepare").text,"Prepare 1 recording")
      owner.listenSession={id:"authored-done",revision:4,index:1,total:1,phase:"complete",subject:null,
        summary:{remembered:1,again:0,skipped:0},undo_available:false}
      compare(button("listeningAnother").text,"Listen to 1 more")
      compare(owner.plays,0);compare(owner.actions.length,0)
    }
    function test_count_progress_cancel_and_busy_state_use_native_controls() {
      make();button("listeningPrepare").clicked()
      verify(!button("listeningPrepare").visible);verify(button("listeningPrepareCancel").visible)
      verify(!button("listeningStart").enabled);verify(!button("listeningDuePreference").enabled)
      service.listeningPreparationProgress={downloaded:1,already_cached:2}
      compare(button("listeningPrepareProgress").text.indexOf("1 saved · 2 already cached"),0)
      button("listeningPrepareCancel").forceActiveFocus();keyClick(Qt.Key_Space)
      compare(service.cancelCount,1);compare(button("listeningPrepareCancel").text,"Stopping…")
      verify(!button("listeningPrepareCancel").enabled)
      compare(owner.plays,0);compare(owner.actions.length,0)
    }
    function test_success_is_a_notice_and_fresh_explicit_start_even_with_autoplay_setting() {
      make();button("listeningPrepare").clicked()
      service.listeningPreparationJobId="";service.listeningPreparationProgress={downloaded:3,already_cached:2}
      owner.listenStatus=Object.assign(ready(),{available:5,preparation:{ready:5,needs_download:0,reason:"ready",complete:true}})
      owner.listenPreparationNotice="3 recordings saved. Start listening when you choose."
      wait(30);compare(owner.plays,0);compare(owner.actions.length,0)
      verify(button("listeningStart").enabled);verify(!button("listeningPrepare").visible)
      verify(button("listeningPrepareNotice").visible)
      button("listeningStart").clicked();compare(owner.actions[0].action,"start")
    }
    function test_cancelled_or_failed_attempt_can_be_retried_only_deliberately() {
      make();button("listeningPrepare").clicked();service.listeningPreparationJobId=""
      owner.listenPreparationNotice="Preparation stopped. Recordings already saved remain available."
      wait(30);compare(owner.prepares,1);verify(button("listeningPrepare").enabled)
      button("listeningPrepare").clicked();compare(owner.prepares,2);compare(owner.plays,0)
    }
    function test_saved_session_and_offline_preserve_their_existing_actions() {
      owner.listenStatus=Object.assign(ready(),{saved:{id:"saved",phase:"question"}});make()
      verify(!button("listeningPrepare").visible);compare(button("listeningStart").text,"Resume listening")
      screen.destroy();screen=null;owner.listenStatus=ready()
      owner.listenStatus.preparation.reason="offline";make()
      verify(button("listeningPrepare").visible);verify(!button("listeningPrepare").enabled)
      verify(button("listeningStart").enabled,"Cached listening remains usable offline")
    }
    function test_locked_or_busy_preparation_never_arms_front_audio() {
      make();owner.listenBusy=true;verify(!button("listeningPrepare").enabled)
      owner.listenBusy=false;service.locked=true;verify(!button("listeningPrepare").enabled)
      owner.listenSession=owner.question(0);wait(30);compare(owner.plays,0)
      verify(!findChild(screen,"listeningAnswer").active)
    }
    function test_narrow_light_and_dark_progress_remains_legible_and_complete() {
      make();screen.width=290;button("listeningPrepare").clicked()
      service.listeningPreparationProgress={downloaded:2,already_cached:1};service.listeningPreparationCancelling=true
      verify(waitForRendering(screen));var label=button("listeningPrepareProgress");var before=String(label.color)
      Color.background="#101010";Color.foreground="#eeeeee";Color.accent="#c4eaff"
      tryVerify(function(){return String(label.color)!==before});wait(20)
      for(var item of visibleTexts()) {
        if(item.renderType!==Text.NativeRendering)continue
        verify(item.contentWidth<=item.width+1,"Fits: "+item.text)
        verify(!item.truncated,"Complete: "+item.text)
      }
    }
  }
'''


def build_adapter(directory):
    panel_fixture.build(directory)
    (directory / "tst_ListeningPanel.qml").unlink()
    panel = (directory / "PanelCore.qml").read_text()
    production_panel = (ROOT / "Panel.qml").read_text()
    (directory / "PanelCore.qml").write_text(panel.rsplit("}", 1)[0]
        + panel_fixture.function(production_panel, "prepareListening") + "\n}\n")
    source = (ROOT / "Service.qml").read_text()
    handlers = "\n".join(re.search(r"(?ms)^  on" + name + r"Changed: \{.*?^  \}", source).group(0)
        for name in ("Locked", "ContentAccess"))
    access = re.search(r"(?m)^  readonly property string contentAccess:.*$", source).group(0)
    exited = re.search(r"(?ms)^    onExited: \{(.*?)^    \}", source).group(1)
    methods = "\n".join(panel_fixture.function(source, name) for name in
        ("ordering", "applySnapshot", "applySession", "request", "productVersion", "receive", "prepareListening", "cancelListeningPreparation"))
    (directory / "ServiceCore.qml").write_text('''import QtQuick
import "SessionState.mjs" as SessionState
import "LearningDigest.mjs" as LearningDigest
Item {
 id: root
 property bool ready: false
 property var workerVersion: null
 property bool locked: false
 property bool studying: false
 property bool panelOpen: false
 property var snapshot: ({})
 property var stateOrder: SessionState.initial()
 property bool learningDigestHydrated: false
 property bool learningDigestDirty: false
 property double learningDigestBarrier: -1
 property int learningDigestGeneration: 0
 property var callbacks: ({})
 property var requestContexts: ({})
 property int pendingCount: 0
 property int sequence: 0
 property string epochId: "authored-worker"
 property string error: ""
 property int restartAttempts: 0
 property var ambientItems: []
 property var rhythm: null
 property var writes: []
 property string listeningPreparationJobId: ""
 property string listeningPreparationContext: ""
 property var listeningPreparationProgress: null
 property bool listeningPreparationCancelling: false
 function considerNotification() {}
 function refreshAmbient() {}
 QtObject { id: worker; function write(line) { root.writes=root.writes.concat([JSON.parse(line)]) } }
 QtObject { id: restartTimer; function restart() {} }
''' + access + "\n" + handlers + "\n" + methods + "\nfunction restartWorker() {" + exited + "\n}\n}\n")
    shutil.copyfile(ROOT / "qml/LearningDigest.mjs", directory / "LearningDigest.mjs")
    (directory / "tst_Preparation.qml").write_text(ADAPTER)


def build_visual(directory):
    qml = directory / "qml"
    qml.mkdir()
    for name in ("Listening.qml", "Card.qml", "Label.qml", "Theme.mjs"):
        shutil.copyfile(ROOT / "qml" / name, qml / name)
    (qml / "Action.qml").write_text('import QtQuick\nimport QtQuick.Controls\nButton {\n'
        'property bool selected: false\nproperty string accessibleName: text\nproperty string accessibleHint: ""\n'
        'property color surfaceColor: "white"\nproperty color textColor: "black"\n'
        'Accessible.name: accessibleName\nAccessible.description: accessibleHint\nAccessible.ignored: !visible\n}\n')
    common = directory / "qs" / "Commons"
    common.mkdir(parents=True)
    (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
    (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
        'function space(value) { return value }\nreadonly property var font: ({family:"Sans",body:14,bodySmall:12,title:20})\n'
        'readonly property int cornerRadius: 6\n}\n')
    (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
        'property color background: "#ffffff"\nproperty color foreground: "#202020"\n'
        'property color accent: "#006699"\nproperty color urgent: "#a90000"\n}\n')
    prefix = rendering.QML.split("  TestCase {", 1)[0]
    prefix = prefix.replace('property bool listeningPreparationCancelling: false',
        '''property bool listeningPreparationCancelling: false
    property int cancelCount: 0
    function cancelListeningPreparation() {cancelCount++;listeningPreparationCancelling=true}''')
    prefix = prefix.replace('function loadListening() { reloads++ }', '''property int prepares: 0
    function prepareListening() {prepares++;service.listeningPreparationJobId="authored-job";service.listeningPreparationCancelling=false}
    function loadListening() { reloads++ }''')
    (directory / "tst_PreparationRendering.qml").write_text(prefix + VISUAL_TESTS + "\n}\n")


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class ListeningPreparationUiTests(unittest.TestCase):
    def run_fixture(self, builder):
        with tempfile.TemporaryDirectory(prefix="wanikani-listening-preparation-ui-") as temporary:
            directory = Path(temporary)
            builder(directory)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, errors="replace", timeout=45,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
            output = process.stdout + process.stderr
        self.assertEqual(0, process.returncode, output)
        self.assertNotIn("QWARN", output)

    def test_source_derived_preparation_adapters(self):
        self.run_fixture(build_adapter)

    def test_actual_preparation_component(self):
        self.run_fixture(build_visual)


if __name__ == "__main__":
    unittest.main()
