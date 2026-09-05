"""Actual Settings sections, native controls and intact local drafts, with inert IO.

The theme loader, border painter, network, keyring, audio and desktop actions are
inert. Native Button, TextField and NumberField source is copied unchanged.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation
import test_stock_palette_surfaces as palettes


ROOT = Path(__file__).resolve().parents[1]
QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme
Rectangle {
  id:surface;width:322;height:760;color:Color.background
  readonly property color kaniSurface:color
  property var page:null
  Flickable {
    id:scroll;x:16;y:16;width:290;height:728;clip:true
    contentWidth:width;contentHeight:page?page.height:0
  }
  Component {id:component;Kani.Settings {width:scroll.width;controller:owner}}
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property var requests:[]
    property var pending:[]
    property var writes:[]
    property var previews:[]
    property var configurations:[]
    property var rhythm:null
    function request(method,args,callback) {
      if(method!=="voices" && method!=="readiness")throw new Error("Unexpected Settings read: "+method)
      requests=requests.concat([{method:method,args:args}])
      if(callback)pending=pending.concat([{method:method,callback:callback}])
    }
    function saveSettings(values){writes=writes.concat([values])}
    function previewRhythm(values,callback){previews=previews.concat([{values:values,callback:callback}])}
    function configureRhythm(values,callback){configurations=configurations.concat([{values:values,callback:callback}])}
  }
  QtObject {
    id:owner
    property var service:backend
    property bool opened:true
    property bool busy:false
    property var snapshot:({})
    property string contentAccess:"authored-account"
    property string integrationNotice:""
    property string audioContext:""
    property string audioState:""
    property string audioNotice:""
    property var calls:[]
    property var navigation:[]
    property var integrations:[]
    property var samples:[]
    property int stops:0
    function call(method,args,callback){calls=calls.concat([{method:method,args:args,callback:callback}])}
    function navigate(view){navigation=navigation.concat([view])}
    function desktopIntegration(remove){integrations=integrations.concat([remove])}
    function testVoice(id){samples=samples.concat([id]);audioContext="voice_test";audioState="loading"}
    function stopAudio(){stops++;audioContext="";audioState=""}
  }
  TestCase {
    name:"SettingsSections";when:windowShown
    function defaults(connected){return {connected:connected,demo:false,username:connected?"Authored learner":"",
      credential_storage:"session",syncing:false,credential_cleanup_needed:false,last_sync:"2026-09-05T12:00:00Z",
      settings:{batch_size:5,cache_limit_mb:256,voice_actor_id:1,autoplay_audio:false,autoplay_lessons:false,
        autoplay_listening:true,strict_meanings:false,companion_animation:true,reduced_motion:false,desktop_card:false,idle_gallery:false},
      outbox_total:2,pending:1,attention:1,cache:{subjects:15,files:4,bytes:1024}}}
    function rhythm(){return {config:{enabled:true,mode:"times",target:"both",times:["10:00","14:00","18:00"],
      interval_hours:2,window_start:"08:00",window_end:"22:00",quiet_start:"22:00",quiet_end:"08:00",
      minimum_interval_seconds:7200,daily_limit:3,recent_study_seconds:1800},next_at:null,reason:"Authored reminder settings",next_reason:""}}
    function make(){page=component.createObject(scroll.contentItem);verify(page!==null);wait(1);verify(waitForRendering(page))}
    function item(name){var found=findChild(page,name);verify(found!==null,name);return found}
    function allItems(node){var result=[node];for(var child of node.children)result=result.concat(allItems(child));return result}
    function action(text){var result=allItems(page).filter(function(value){return value.accessibleName!==undefined&&value.text===text});compare(result.length,1,text);return result[0]}
    function activate(control){verify(control.visible&&control.enabled);control.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
    function section(name){activate(item("settings-section-"+name));compare(page.section,name)}
    function type(text){for(var character of text)keyClick(character)}
    function voices(){return {items:[{id:1,label:"Authored voice",description:"A recorded vocabulary sample"}],message:""}}
    function voiceReply(index,ok){var entry=backend.pending[index];backend.pending=backend.pending.slice(0,index).concat(backend.pending.slice(index+1));entry.callback(ok!==false,voices(),"Authored failure");wait(1)}
    function init(){
      failOnWarning(/.*/);backend.ready=true;backend.locked=false;backend.requests=[];backend.pending=[];backend.writes=[];backend.previews=[];backend.configurations=[];backend.rhythm=rhythm()
      owner.opened=true;owner.busy=false;owner.snapshot=defaults(true);owner.contentAccess="authored-account";owner.integrationNotice=""
      owner.calls=[];owner.navigation=[];owner.integrations=[];owner.samples=[];owner.stops=0;owner.audioContext="";owner.audioState="";owner.audioNotice=""
      scroll.contentY=0;Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699";Color.urgent="#990000"
    }
    function cleanup(){if(page)page.destroy();page=null;wait(1)}
    function test_connected_opens_compact_study_with_no_reads_or_mutations(){
      make();compare(page.section,"study");wait(200);compare(backend.requests,[])
      verify(item("settings-group-study").visible);verify(!item("settings-group-audio").visible)
      verify(item("settings-section-study").Accessible.checked);verify(item("settings-section-audio").Accessible.checkable)
      page.focusInput();verify(item("settings-batch-size").field.activeFocus)
      verify(page.height<scroll.height,"Default study settings fit the narrow viewport")
      compare(backend.writes,[]);compare(owner.calls,[]);compare(owner.samples,[]);compare(backend.configurations,[])
    }
    function test_unconnected_account_default_and_initial_auth_context(){
      owner.snapshot=defaults(false);make();compare(page.section,"account");page.focusInput();verify(item("settings-token").activeFocus)
      compare(item("settings-token").echoMode,TextInput.Password)
      owner.snapshot=defaults(true);wait(1);compare(page.section,"study")
      section("audio");owner.snapshot=Object.assign({},owner.snapshot,{pending:2});wait(1);compare(page.section,"audio")
    }
    function test_all_groups_stay_alive_and_preserve_uncommitted_local_drafts(){
      make();var groups=page.sectionNames.map(function(name){return item("settings-group-"+name)})
      section("account");var token=item("settings-token");token.forceActiveFocus();type("AUTHORED-UNSAVED-TOKEN");token.cursorPosition=5;page.remember=false
      section("data");activate(action("Remove local account data…"));var confirmation=item("settings-delete-confirmation")
      confirmation.forceActiveFocus();type("DELE");confirmation.cursorPosition=2;page.discardPending=true
      section("reminders");var rhythm=item("wanikani-study-rhythm");var times=item("rhythm-times")
      times.forceActiveFocus();times.selectAll();type("09:30, partial,");verify(rhythm.dirty);rhythm.extra=true
      for(var name of page.sectionNames){section(name);wait(1)}
      compare(token.text,"AUTHORED-UNSAVED-TOKEN");compare(token.cursorPosition,5);verify(!page.remember)
      compare(confirmation.text,"DELE");compare(confirmation.cursorPosition,2);verify(page.showDeletion);verify(page.discardPending)
      compare(rhythm.timesText,"09:30, partial,");verify(rhythm.dirty);verify(rhythm.extra)
      for(var i=0;i<page.sectionNames.length;i++)compare(item("settings-group-"+page.sectionNames[i]),groups[i])
      owner.opened=false;wait(200);owner.opened=true;wait(1);compare(confirmation.text,"DELE");compare(rhythm.timesText,"09:30, partial,")
      compare(backend.writes,[]);compare(backend.configurations,[]);compare(owner.calls,[]);compare(owner.samples,[])
    }
    function test_audio_only_reads_when_visible_and_late_read_cannot_play(){
      make();wait(180);compare(backend.requests,[]);section("audio")
      tryVerify(function(){return backend.pending.length===1});compare(backend.requests[0].method,"voices")
      section("study");voiceReply(0);wait(180);compare(item("settings-voices").voices,[]);compare(owner.samples,[])
      owner.snapshot=Object.assign({},owner.snapshot,{last_sync:"2026-09-05T13:00:00Z"});wait(200);compare(backend.requests.length,1)
      section("audio");tryVerify(function(){return backend.pending.length===1});voiceReply(0);compare(item("settings-voices").voices.length,1)
      compare(owner.samples,[]);compare(backend.writes,[])
    }
    function test_leaving_audio_cancels_its_sample_but_preserves_other_playback(){
      make();section("audio");tryVerify(function(){return backend.pending.length===1});voiceReply(0)
      activate(action("Test selected voice"));compare(owner.samples,[1]);compare(owner.audioContext,"voice_test")
      section("study");compare(owner.stops,1);compare(owner.audioContext,"")
      section("audio");owner.audioContext="study";owner.audioState="playing";section("desktop");compare(owner.stops,1);compare(owner.audioState,"playing")
    }
    function test_closing_locking_and_hidden_parent_stop_only_owned_voice_data(){return ["close","lock","hidden","restart"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_closing_locking_and_hidden_parent_stop_only_owned_voice(data){
      make();section("audio");tryVerify(function(){return backend.pending.length===1});voiceReply(0)
      activate(action("Test selected voice"))
      if(data.edge==="close")owner.opened=false
      else if(data.edge==="lock")backend.locked=true
      else if(data.edge==="hidden")page.visible=false
      else backend.ready=false
      wait(1);compare(owner.stops,1);verify(!item("settings-voices").active)
    }
    function test_hidden_reminder_draft_stops_preview_and_restarts_without_saving(){
      make();section("reminders");var rhythm=item("wanikani-study-rhythm");rhythm.editTimes("09:30, 15:00")
      section("study");wait(240);compare(backend.previews,[]);verify(rhythm.dirty)
      section("reminders");tryVerify(function(){return backend.previews.length===1})
      section("audio");backend.previews[0].callback(true,Object.assign({},backend.rhythm,{reason:"STALE PREVIEW"}),"")
      wait(1);compare(rhythm.draftPreview,null);compare(rhythm.timesText,"09:30, 15:00");compare(backend.configurations,[])
    }
    function test_existing_explicit_actions_keep_their_exact_contract(){
      make();section("audio");activate(allItems(page).filter(function(value){return value.accessibleName==="Autoplay new listening prompts"})[0]);compare(backend.writes,[{autoplay_listening:false}])
      section("desktop");activate(action("Install shortcuts & launchers"));activate(action("Remove shortcuts & launchers"));compare(owner.integrations,[false,true])
      section("data");activate(action("Open saved submissions · 2 open"));compare(owner.navigation,["recovery"])
      activate(action("Remove local account data…"));verify(!action("Delete local data").enabled)
      var confirmation=item("settings-delete-confirmation");confirmation.forceActiveFocus();type("DELETE");page.discardPending=true;activate(action("Delete local data"))
      compare(owner.calls.length,1);compare(owner.calls[0].method,"delete_data");compare(owner.calls[0].args,{confirmation:"DELETE",discard_pending:true})
      owner.calls[0].callback(true,{credential_cleanup_needed:true,warning:"Authored cleanup warning"});wait(1)
      verify(!page.showDeletion);compare(confirmation.text,"");compare(page.notice,"Authored cleanup warning")
    }
    function test_navigation_focus_is_current_and_hidden_groups_cannot_receive_tab(){
      make();section("account");verify(item("settings-token").activeFocus)
      section("study");verify(item("settings-batch-size").field.activeFocus)
      var before=page.section;page.selectSection("invalid");compare(page.section,before)
      page.selectSection("account");page.selectSection("study");wait(1);verify(item("settings-batch-size").field.activeFocus)
      for(var i=0;i<12;i++){keyClick(Qt.Key_Tab);wait(1);verify(!item("settings-token").activeFocus);verify(!item("settings-delete-confirmation").activeFocus)}
    }
    __CHECKS__
    function test_narrow_sections_live_light_and_dark_data(){return [paletteData()[0],paletteData().find(function(value){return value.tag==="flexoki-light"})||paletteData()[1]]}
    function test_narrow_sections_live_light_and_dark(data){
      make();section("account");item("settings-token").text="AUTHORED-DRAFT";applyPalette(data)
      for(var name of page.sectionNames){
        section(name);wait(180);if(backend.pending.length)voiceReply(0)
        checkText(page,data.tag+" "+name)
        var button=item("settings-section-"+name);button.forceActiveFocus();wait(140)
        var ring=findChild(button,"wanikani-action-focus");verify(ring.visible);verify(Theme.contrast(ring.border.color,Theme.composite(button.color,renderedUnder(button.parent)))>=3)
        for(var value of allItems(page)){
          if(!value.visible||!value.enabled||value.width<=0||value.accessibleName===undefined && value.Accessible.role!==Accessible.CheckBox)continue
          var point=value.mapToItem(page,0,0);verify(point.x>=-1&&point.x+value.width<=page.width+1,data.tag+" overflow "+value.accessibleName)
        }
      }
      compare(item("settings-token").text,"AUTHORED-DRAFT");compare(backend.writes,[]);compare(owner.calls,[]);compare(owner.samples,[])
    }
    function test_live_stock_palette_changes_keep_draft_and_voice_controls_data(){return paletteData()}
    function test_live_stock_palette_changes_keep_draft_and_voice_controls(data){
      make();section("account");item("settings-token").text="AUTHORED-UNSAVED-DRAFT";item("settings-token").cursorPosition=4
      applyPalette(data);checkText(page,data.tag+" account")
      section("audio");tryVerify(function(){return backend.pending.length===1});voiceReply(0)
      checkText(page,data.tag+" audio")
      var selected=item("settings-section-audio");selected.forceActiveFocus();wait(140)
      var ring=findChild(selected,"wanikani-action-focus");verify(ring.visible)
      verify(Theme.contrast(ring.border.color,Theme.composite(selected.color,renderedUnder(selected.parent)))>=3)
      section("account");compare(item("settings-token").text,"AUTHORED-UNSAVED-DRAFT");compare(item("settings-token").cursorPosition,4)
      compare(backend.writes,[]);compare(owner.samples,[])
    }
  }
}
'''


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    for name in ("Settings", "VoiceChoices", "StudyRhythm", "OfflineStatus"):
        source = (ROOT / "qml" / (name + ".qml")).read_text().replace("import Quickshell\n", "")
        (directory / "qml" / (name + ".qml")).write_text(source)
    ui = directory / "qs/Ui"
    shutil.copyfile(foundation.NATIVE / "NumberField.qml", ui / "NumberField.qml")
    module = ui / "qmldir"
    module.write_text(module.read_text() + "NumberField 1.0 NumberField.qml\n")
    palettes.pure_native_style(directory)
    style = directory / "qs/Commons/Style.qml"
    style.write_text(style.read_text().replace("controlHeight:34", "controlHeight:34,numberFieldWidth:100"))
    checks = palettes.CHECKS.replace("__PALETTES__", json.dumps(palettes.palettes()))
    (directory / "tst_SettingsSections.qml").write_text(QML.replace("__CHECKS__", checks))


@unittest.skipUnless(foundation.RUNNER.is_file() and (foundation.NATIVE / "NumberField.qml").is_file(), "Qt and native Omarchy controls required")
class SettingsSectionsUiTests(unittest.TestCase):
    def test_actual_native_sections_drafts_and_hidden_audio(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-settings-sections-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(foundation.RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=70, env={**os.environ,
                    "QT_QPA_PLATFORM":"offscreen", "QT_QPA_PLATFORMTHEME":"", "QT_QUICK_CONTROLS_STYLE":"Basic"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
