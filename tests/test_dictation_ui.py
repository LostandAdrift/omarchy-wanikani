"""Actual dictation surface and native input; inert local-practice adapter."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import test_kanji_examples_ui as native
import test_stock_palette_surfaces as palettes


ROOT = Path(__file__).resolve().parents[1]
QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml"
import "qml/Theme.mjs" as Theme
Item {
  width: 700; height: 2300
  QtObject { id: backend; property bool ready:true; property bool locked:false }
  QtObject {
    id: owner
    property var service:backend
    property var dictation:core
    property bool opened:true
    property string view:"dictation"
    property var routes:[]
    function navigate(value) { routes=routes.concat([value]) }
    function dismiss() { opened=false }
  }
  QtObject {
    id:core
    property var session:null
    property var status:({available:2,new_remaining:5,complete:true,message:"Authored cached recordings"})
    property string error:""
    property string draftError:""
    property string mediaNotice:""
    property bool loading:false
    property bool actionBusy:false
    property bool mediaBusy:false
    property bool heardBusy:false
    property bool audioRecovering:false
    property bool playing:false
    readonly property bool active:owner.opened&&backend.ready&&!backend.locked
    readonly property bool heard:!!session&&session.heard===true
    readonly property bool canCheck:active&&heard&&!actionBusy&&!mediaBusy&&!heardBusy&&!audioRecovering
    property var events:[]
    function start() { events=events.concat([{action:"start"}]);session=test.front() }
    function refresh() { events=events.concat([{action:"refresh"}]) }
    function play() { events=events.concat([{action:"play"}]);playing=!playing }
    function check(text) { events=events.concat([{action:"check",text:text}]) }
    function advance() { events=events.concat([{action:"continue"}]) }
    function skip() { events=events.concat([{action:"skip"}]) }
    function undo() { events=events.concat([{action:"undo"}]) }
    function saveDraft(text,cursor,preedit) { events=events.concat([{action:"draft",text:text,cursor:cursor,preedit:preedit}]) }
  }
  Dictation {id:page;controller:owner;width:290}
  TestCase {
    id:test;name:"DictationNativeSurface";when:windowShown
    function front() {return {id:"authored",revision:1,phase:"question",index:0,total:2,media_handle:"opaque",heard:false,draft:"やm",draft_cursor:2,preedit:"",draft_revision:1,input_error:"",feedback:null,subject:null,summary:{matched:0,again:0,skipped:0},undo_available:false,local_only:true,intervals:null}}
    function revealed(matched) {return Object.assign(front(),{phase:"feedback",heard:true,feedback:{matched:matched,submitted:matched?"やま":"やも",recorded:"やま",message:"Compare with this exact authored recording."},subject:{id:1,type:"vocabulary",characters:"山",meanings:["Authored mountain"],pronunciation:"やま",voice:"Authored voice",material:{}},intervals:{matched_days:1,again_minutes:10}})}
    function item(name) {var found=findChild(page,name);verify(found!==null,name);return found}
    function settle() {wait(30)}
    function init() {
      owner.opened=false;backend.ready=true;backend.locked=false;owner.routes=[]
      core.session=null;core.events=[];core.error="";core.draftError="";core.mediaNotice=""
      core.loading=false;core.actionBusy=false;core.mediaBusy=false;core.heardBusy=false;core.audioRecovering=false;core.playing=false
      core.status={available:2,new_remaining:5,complete:true,message:"Authored cached recordings"}
      Color.background="#fffdf5";Color.foreground="#222";Color.accent="#006699";Color.urgent="#990000"
      page.width=290;owner.opened=true;settle()
    }
    function test_open_is_silent_and_start_play_check_are_explicit() {
      compare(core.events.length,0)
      item("dictationStart").clicked();settle()
      compare(core.events[0].action,"start")
      compare(core.events.length,1)
      verify(item("dictationAnswer").visible)
      verify(!item("dictationCheck").enabled)
      compare(item("dictationAnswer").text,"やm")
      item("dictationPlay").clicked()
      compare(core.events[1].action,"play")
      core.session=Object.assign({},core.session,{heard:true,revision:2});settle()
      verify(item("dictationCheck").enabled)
    }
    function test_active_question_keeps_native_answer_controls_in_narrow_first_viewport() {
      verify(item("dictation-introduction-title").visible)
      verify(item("dictation-introduction-copy").visible)
      core.session=front();settle()
      verify(!item("dictation-introduction-title").visible)
      verify(!item("dictation-introduction-copy").visible)
      for(var name of ["dictationPlay","dictationAnswer","dictationCheck"]) {
        var control=item(name),top=control.mapToItem(page,0,0).y
        verify(control.visible,name)
        verify(top>=0&&top+control.height<=480,name+" fits first 480px: "+top+"–"+(top+control.height))
      }
      compare(core.events.length,0)
      compare(item("dictationAnswer").text,"やm")
      verify(item("dictationPlay").activeFocus)
      core.session=null;settle()
      verify(item("dictation-introduction-title").visible)
      verify(item("dictation-introduction-copy").visible)
      compare(core.events.length,0)
    }
    function test_terminal_n_and_live_romaji_save_current_utf16_cursor() {
      core.session=Object.assign(front(),{heard:true,draft:"",draft_cursor:0});settle()
      var input=item("dictationAnswer")
      input.text="kann";input.cursorPosition=4;input.textEdited();settle()
      compare(input.text,"かん")
      input.text="san";input.cursorPosition=3;input.textEdited();settle()
      compare(input.text,"さn")
      core.events=[];page.submit()
      compare(core.events.length,1)
      compare(core.events[0].action,"check");compare(core.events[0].text,"さん")
      verify(!input.inputMethodComposing)
    }
    function test_drafts_and_cursor_survive_media_ack_and_theme_change() {
      core.session=front();settle()
      var input=item("dictationAnswer")
      input.text="きょう";input.cursorPosition=1;input.textEdited();settle()
      core.events=[]
      core.session=Object.assign({},core.session,{revision:2,heard:true,draft:"OLD",draft_cursor:0});settle()
      compare(input.text,"きょう");compare(input.cursorPosition,1)
      Color.background="#171925";Color.foreground="#dfe4f3";Color.accent="#99ccff";settle()
      compare(input.text,"きょう");compare(input.cursorPosition,1)
      compare(core.events.length,0)
      verify(Theme.contrast(input.color,input.renderedSurface)>=4.5)
    }
    function test_revealed_metadata_is_not_created_before_feedback() {
      core.session=front();settle()
      var labels=allItems(page).filter(function(x){return typeof x.text==="string"&&x.visible})
      verify(!labels.some(function(x){return x.text.indexOf("Authored mountain")>=0}))
      core.session=revealed(false);settle()
      labels=allItems(page).filter(function(x){return typeof x.text==="string"&&x.visible})
      verify(labels.some(function(x){return x.text.indexOf("Authored mountain")>=0}))
      verify(item("dictationContinue").visible)
      item("dictationContinue").clicked();compare(core.events.slice(-1)[0].action,"continue")
      core.session=Object.assign(front(),{unavailable:"Recording unavailable",media_handle:null});settle()
      verify(!allItems(page).some(function(x){return x.visible&&typeof x.text==="string"&&x.text.indexOf("Authored mountain")>=0}))
    }
    function test_unavailable_current_card_can_offer_safe_undo_and_current_account_start() {
      core.status={available:2,saved:null}
      core.session=Object.assign(front(),{unavailable:"Current recording unavailable",media_handle:null,undo_available:true});settle()
      verify(item("dictationUndo").visible);verify(item("dictationCurrentAccount").visible)
      item("dictationUndo").clicked();compare(core.events.slice(-1)[0].action,"undo")
      item("dictationSkip").clicked();compare(core.events.slice(-1)[0].action,"skip")
    }
    function test_completion_has_distinct_results_and_return_to_work() {
      core.session=Object.assign(front(),{phase:"complete",index:2,media_handle:null,summary:{matched:1,again:0,skipped:1},undo_available:true});settle()
      verify(item("dictationSummary").text.indexOf("1 matched the recording")>=0)
      verify(item("dictationAnother").visible)
      item("dictationDone").clicked();verify(!owner.opened)
    }
    function test_feedback_space_collapses_when_complete_or_unavailable() {
      core.session=revealed(false);settle()
      var expanded=page.implicitHeight
      verify(item("dictationFeedback").visible)
      core.session=Object.assign(front(),{phase:"complete",index:2,media_handle:null,summary:{matched:1,again:0,skipped:1}});settle()
      verify(!item("dictationFeedback").visible)
      verify(page.implicitHeight<expanded-100,"A completed batch must not retain the old feedback height")
      verify(item("dictationDone").activeFocus)
      core.session=revealed(false);settle()
      core.session=Object.assign(front(),{unavailable:"Recording unavailable",media_handle:null});settle()
      verify(!item("dictationFeedback").visible)
      verify(page.implicitHeight<expanded-100)
    }
    function test_saved_preedit_is_a_notice_not_a_claim_to_restore_the_ime() {
      core.session=Object.assign(front(),{preedit:"ま"});settle()
      compare(page.restoredPreedit,"ま")
      verify(!item("dictationAnswer").inputMethodComposing)
      compare(item("dictationAnswer").text,"やm")
    }
    function allItems(node) {var result=[node];for(var child of node.children)result=result.concat(allItems(child));return result}
    function test_narrow_light_and_dark_feedback_fit_and_remain_readable_data() {return __PALETTES__}
    function test_narrow_light_and_dark_feedback_fit_and_remain_readable(data) {
      Color.background=data.background;Color.foreground=data.foreground;Color.accent=data.accent
      core.session=revealed(false);settle()
      for(var node of allItems(page)) {
        if(!node.visible||typeof node.text!=="string"||!node.text||node.textFormat===undefined||node.color===undefined)continue
        var surface=node.renderedSurface!==undefined?node.renderedSurface:Theme.surface(node.parent,Color.background)
        verify(Theme.contrast(node.color,surface)>=4.5,node.text)
        verify(node.width<=page.width,node.text+": width "+node.width)
      }
    }
  }
}
'''


def build(directory):
    colors = palettes.palettes() + [
        {"tag": "authored-low-contrast", "background": "#888888", "foreground": "#888888", "accent": "#888888"},
        {"tag": "authored-white", "background": "#ffffff", "foreground": "#ffffff", "accent": "#ffffff"},
        {"tag": "authored-black", "background": "#000000", "foreground": "#000000", "accent": "#000000"}]
    native.build(directory, QML.replace("__PALETTES__", json.dumps(colors)))
    shutil.copy(ROOT / "qml" / "Dictation.qml", directory / "qml" / "Dictation.qml")
    palettes.pure_native_style(directory)


@unittest.skipUnless(native.RUNNER.is_file(), "Qt runner required")
class DictationUiTests(unittest.TestCase):
    def test_actual_dictation_surface_and_native_input(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-dictation-ui-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = native.run_fixture(directory)
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
