"""Actual local-listening layout; authored neutral/revealed states, no audio device."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani

Rectangle {
  width: 720; height: 2200; color: Color.background
  property var screen: null
  Component { id: page; Kani.Listening { width: 350; controller: owner } }
  QtObject { id: service; property bool ready: true; property bool locked: false }
  QtObject {
    id: owner
    property var service: null
    property bool opened: true
    property string contentAccess: "authored-account"
    property var snapshot: ({settings:{autoplay_listening:false}})
    property var listenSession: null
    property var listenStatus: ({available:5,new_remaining:5,complete:true,settings:{avoid_due_24h:true},saved:null})
    property bool listenBusy: false
    property string listenError: ""
    property string audioContext: ""
    property string audioState: ""
    property string audioNotice: ""
    property int reloads: 0
    property int plays: 0
    property int stops: 0
    property var actions: []
    function question(index) {
      return {id:"authored-listening",revision:index+1,index:index,total:2,phase:"question",media_handle:"opaque-"+index,
        subject:null,summary:{remembered:index,again:0,skipped:0},intervals:null,undo_available:index>0}
    }
    function answer() {
      return {id:101,type:"vocabulary",characters:"山",pronunciation:"やま",meanings:["Mountain", "Authored <b>literal</b>"],
        voice:"Authored fixture voice",readings:[{reading:"やま",accepted:true}],
        material:{meaning_note:"Private authored meaning note",reading_note:"Private authored reading note"},
        alternatives:[{characters:"山別",meanings:["A different authored meaning"]}],
        ambiguity_note:"Other Japanese words may share this sound. Skip if uncertain."}
    }
    function revealed() {
      var value=question(0);value.phase="revealed";value.subject=answer();value.intervals={remembered_days:1,again_minutes:10};return value
    }
    function listenAction(action,args) {
      actions=actions.concat([{action:action,args:args}])
      if(action==="settings") {
        var status=JSON.parse(JSON.stringify(listenStatus));status.settings=args;listenStatus=status;return
      }
      if(action==="start") { if(!listenSession||listenSession.phase==="complete")listenSession=question(0);return }
      if(action==="reveal") { listenSession=revealed();return }
      if(action==="rate"||action==="skip") {
        if(listenSession.index===0)listenSession=question(1)
        else listenSession={id:"authored-listening",revision:7,index:2,total:2,phase:"complete",media_handle:null,subject:null,
          summary:{remembered:1,again:1,skipped:0},intervals:null,undo_available:true}
      }
      if(action==="undo")listenSession=revealed()
    }
    function loadListening() { reloads++ }
    function playListening() {
      plays++;audioContext="listening";audioState="playing";audioNotice="Original recording ready offline"
      var value=JSON.parse(JSON.stringify(listenSession));value.revision++;listenSession=value
    }
    function stopAudio() { stops++;audioContext="";audioState="";audioNotice="" }
    function close() { opened=false }
  }
  TestCase {
    name: "ListeningRendering"; when: windowShown
    function make() { screen=page.createObject(parent);verify(screen!==null);verify(waitForRendering(screen));return screen }
    function descendants(item) {
      var output=[]
      for(var i=0;i<item.children.length;++i){output.push(item.children[i]);output=output.concat(descendants(item.children[i]))}
      return output
    }
    function texts() { return descendants(screen).filter(function(item){return item.text!==undefined && item.visible}) }
    function click(name) { var control=findChild(screen,name);verify(control!==null,name);verify(control.enabled,name);control.clicked() }
    function test_context_recovery_and_reload_have_visible_actions() {
      owner.listenSession={id:"old-context",revision:1,index:0,total:2,phase:"question",media_handle:null,subject:null,
        unavailable:"Start a new local session.",summary:{remembered:0,again:0,skipped:0}}
      make()
      verify(findChild(screen,"listeningNewContext").visible)
      click("listeningNewContext");compare(owner.actions[0].action,"start")
      owner.listenError="This listening card changed. Reload it."
      verify(findChild(screen,"listeningReload").visible)
      click("listeningReload");compare(owner.reloads,1)
    }
    function init() {
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;owner.service=service;owner.opened=true;owner.contentAccess="authored-account"
      owner.snapshot={settings:{autoplay_listening:false}}
      owner.listenSession=null;owner.listenStatus={available:5,new_remaining:5,complete:true,settings:{avoid_due_24h:true},saved:null}
      owner.listenBusy=false;owner.listenError="";owner.audioContext="";owner.audioState="";owner.audioNotice=""
      owner.actions=[];owner.plays=0;owner.stops=0;owner.reloads=0
      Color.background="#ffffff";Color.foreground="#202020";Color.accent="#006699"
    }
    function cleanup() { if(screen)screen.destroy();screen=null;wait(1) }
    function test_home_requires_deliberate_start_and_explains_local_progress() {
      make();compare(owner.actions.length,0);compare(owner.plays,0)
      verify(texts().some(function(item){return item.text.indexOf("LOCAL PROGRESS")>=0}))
      click("listeningStart");compare(owner.actions[0].action,"start");compare(owner.plays,0)
      compare(findChild(screen,"listeningPosition").text,"WORD 1 OF 2")
    }
    function test_front_contains_no_answer_or_accessibility_hints() {
      owner.listenSession=owner.question(0);make()
      verify(!findChild(screen,"listeningAnswer").active)
      tryVerify(function(){return findChild(screen,"listeningCharacters")===null})
      var visible=texts().map(function(item){return item.text+" "+item.Accessible.name}).join(" ")
      for(var hint of ["山","やま","Mountain","Private authored","101"])
        verify(visible.indexOf(hint)<0,"No hidden hint: "+hint)
      compare(findChild(screen,"listeningPlay").accessibleName,"Play recording")
    }
    function test_replay_never_rates_or_reveals_and_failure_has_retry() {
      owner.listenSession=owner.question(0);make();click("listeningPlay");compare(owner.plays,1)
      compare(owner.listenSession.phase,"question");compare(owner.actions.length,0)
      click("listeningPlay");compare(owner.plays,2);compare(owner.actions.length,0)
      owner.audioState="failed";owner.audioNotice="Playback failed. Retry."
      compare(findChild(screen,"listeningPlay").text,"Retry recording")
      click("listeningPlay");compare(owner.plays,3);compare(owner.actions.length,0)
    }
    function test_explicit_stop_cancels_loading_and_reloads_its_durable_revision() {
      owner.listenSession=owner.question(0);make();click("listeningPlay")
      verify(findChild(screen,"listeningStop").visible)
      click("listeningStop");compare(owner.stops,1);compare(owner.reloads,0)
      owner.audioContext="listening";owner.audioState="loading";owner.listenBusy=true
      verify(findChild(screen,"listeningStop").enabled)
      click("listeningStop");compare(owner.stops,2);compare(owner.reloads,1)
      compare(owner.actions.length,0);compare(owner.listenSession.phase,"question")
    }
    function test_reveal_shows_literal_notes_ambiguity_and_next_interval() {
      owner.listenSession=owner.question(0);make();click("listeningReveal")
      tryVerify(function(){return findChild(screen,"listeningCharacters")!==null})
      compare(findChild(screen,"listeningCharacters").text,"山")
      compare(findChild(screen,"listeningReading").text,"やま")
      compare(findChild(screen,"listeningRemembered").text,"Got it · 1 day")
      compare(findChild(screen,"listeningAgain").text,"Again · 10 minutes")
      verify(texts().some(function(item){return item.text.indexOf("Private authored meaning note")>=0}))
      verify(texts().some(function(item){return item.text.indexOf("山別 · A different authored meaning")>=0}))
      verify(texts().every(function(item){return item.renderType!==Text.NativeRendering || item.textFormat===Text.PlainText}))
      click("listeningRemembered");compare(owner.actions[1].args.rating,"remembered")
      compare(owner.listenSession.index,1);verify(!findChild(screen,"listeningAnswer").active)
    }
    function test_missing_media_keeps_skip_without_false_rating() {
      var value=owner.question(0);value.media_handle=null;value.unavailable="Recording is unavailable offline.";owner.listenSession=value;make()
      verify(!findChild(screen,"listeningPlay").enabled);verify(!findChild(screen,"listeningReveal").enabled)
      click("listeningSkip");compare(owner.actions[0].action,"skip")
      verify(owner.actions.every(function(action){return action.action!=="rate"}))
    }
    function test_explicit_start_can_autoplay_but_resume_and_wake_are_quiet() {
      owner.snapshot={settings:{autoplay_listening:true}};make();click("listeningStart")
      tryCompare(owner,"plays",1)
      owner.opened=false;wait(5);compare(owner.stops,1);owner.opened=true;wait(20);compare(owner.plays,1)
      service.locked=true;service.locked=false;wait(20);compare(owner.plays,1)
      screen.destroy();screen=null;make();wait(20);compare(owner.plays,1)
    }
    function test_autoplay_is_cancelled_when_closed_before_deferred_action() {
      owner.snapshot={settings:{autoplay_listening:true}};make();click("listeningStart");owner.opened=false
      wait(20);compare(owner.plays,0)
    }
    function test_failed_action_cannot_arm_later_background_audio() {
      owner.snapshot={settings:{autoplay_listening:true}};make()
      screen.autoplayArmed=true;owner.listenBusy=true;owner.listenBusy=false;owner.listenError="Authored failed action"
      owner.listenSession=owner.question(1);wait(20);compare(owner.plays,0)
    }
    function test_play_supports_native_keyboard_activation() {
      owner.listenSession=owner.question(0);make()
      var button=findChild(screen,"listeningPlay");button.forceActiveFocus()
      keyClick(Qt.Key_Space);compare(owner.plays,1);compare(owner.actions.length,0)
    }
    function test_new_question_stops_old_clip_and_closed_answer_is_absent() {
      owner.listenSession=owner.question(0);make();click("listeningPlay");compare(owner.plays,1)
      owner.listenSession=owner.question(1);compare(owner.stops,1)
      owner.listenSession=owner.revealed();tryVerify(function(){return findChild(screen,"listeningCharacters")!==null})
      service.locked=true;verify(!findChild(screen,"listeningAnswer").active)
      tryVerify(function(){return findChild(screen,"listeningCharacters")===null})
      verify(!findChild(screen,"listeningPlay").enabled)
    }
    function test_empty_fresh_budget_and_due_soon_preference_are_explicit() {
      owner.listenStatus={available:0,new_remaining:0,complete:true,settings:{avoid_due_24h:true},saved:null};make()
      verify(!findChild(screen,"listeningStart").enabled)
      verify(findChild(screen,"listeningAvailability").text.indexOf("Today's five")>=0)
      click("listeningDuePreference");compare(owner.actions[0].args.avoid_due_24h,false)
      click("listeningDuePreference");compare(owner.actions[1].args.avoid_due_24h,true)
    }
    function test_recap_undo_and_return_to_work_are_native_actions() {
      owner.listenSession=owner.question(1);make();click("listeningSkip")
      compare(findChild(screen,"listeningSummary").text,"1 recalled · 1 to revisit · 0 skipped")
      click("listeningFinalUndo");compare(owner.actions[1].action,"undo")
      owner.listenSession=owner.question(1);click("listeningSkip");click("listeningDone");verify(!owner.opened)
    }
    function test_narrow_light_and_dark_palettes_keep_plain_readable_text() {
      owner.listenSession=owner.revealed();make();screen.width=290
      tryVerify(function(){return findChild(screen,"listeningCharacters")!==null});verify(waitForRendering(screen))
      var label=findChild(screen,"listeningReading");var before=String(label.color)
      Color.background="#121212";Color.foreground="#eeeeee";Color.accent="#b5e3ff"
      tryVerify(function(){return String(label.color)!==before});wait(20)
      for(var item of texts()) {
        if(item.renderType!==Text.NativeRendering)continue
        verify(item.contentWidth<=item.width+1,"Fits: "+item.text)
        verify(!item.truncated,"Complete: "+item.text)
      }
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class ListeningRenderingTests(unittest.TestCase):
    def test_actual_listening_component(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-listening-ui-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("Listening.qml", "Card.qml", "Label.qml", "Theme.mjs"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text('import QtQuick\nimport QtQuick.Controls\nButton {\n'
                'property bool selected: false\nproperty string accessibleName: text\n'
                'property color surfaceColor: "white"\nproperty color textColor: "black"\n'
                'Accessible.name: accessibleName\nAccessible.ignored: !visible\n}\n')
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                'function space(value) { return value }\nreadonly property var font: ({family:"Sans",body:14,bodySmall:12,title:20})\n'
                'readonly property int cornerRadius: 6\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                'property color background: "#ffffff"\nproperty color foreground: "#202020"\n'
                'property color accent: "#006699"\nproperty color urgent: "#a90000"\n}\n')
            (directory / "tst_Listening.qml").write_text(QML)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=45,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertNotIn("QWARN", process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
