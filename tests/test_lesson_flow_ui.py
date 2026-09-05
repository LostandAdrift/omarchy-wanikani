"""Actual guided Study/SubjectDetails with native keys and inert audio/backend.

Installed Button/TextField source is copied unchanged. Shell theme services,
decorations and IO are authored fixtures; this is not hosted-shell verification.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_theme_rendering as foundation


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
NATIVE = Path("/usr/share/omarchy/shell/Ui")

QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme

Rectangle {
  id: surface; width:640;height:3000;color:Color.background
  property var page:null
  Item {id: focusSink}
  Component {id: study;Kani.Study {width:380;controller:owner}}
  QtObject {
    id: backend
    property bool ready:true
    property bool locked:false
    property bool animations:false
    property var writes:[]
    signal snapshotChanged()
    function request(method,args,callback) {
      writes=writes.concat([{method:method,args:args}])
      if(callback)callback(false,null,"Authored fixture has no network")
    }
  }
  QtObject {
    id: owner
    property var service:backend
    property bool opened:true
    property bool busy:false
    property string error:""
    property string contentAccess:"authored-account"
    property var detail:null
    property var session:null
    property var snapshot:({settings:{autoplay_lessons:true,autoplay_audio:false},pending:0,demo:true})
    property string audioContext:""
    property string audioState:""
    property string audioNotice:""
    property int audioSubjectId:-1
    property var actions:[]
    property var plays:[]
    property int stops:0
    function studyAction(method,args) {actions=actions.concat([{method:method,args:args}]);busy=true}
    function play(subject) {plays=plays.concat([subject.id])}
    function stopAudio() {stops++}
    function dismiss() {opened=false}
    function begin() {throw new Error("No automatic new study")}
    function call() {throw new Error("No automatic IO")}
    function showSubject() {throw new Error("Lesson relationship chips must stay read-only")}
  }
  TestCase {
    name:"LessonFlowUi";when:windowShown
    function word(kind) {
      var result={id:101,type:kind||"vocabulary",level:1,characters:"火山",slug:"authored-volcano",images:[],
        meanings:["Volcano"],readings:[{reading:"かざん",accepted:true}],
        meaning_mnemonic:"Authored meaning mnemonic.",meaning_hint:"Authored meaning hint.",
        reading_mnemonic:"Authored reading mnemonic.",reading_hint:"Authored reading hint.",
        material:{meaning_synonyms:[],meaning_note:"Private authored meaning note.",reading_note:"Private authored reading note."},
        sentences:[{ja:"火山があります。",en:"There is a volcano."}],components:[{id:1,characters:"火",meaning:"Fire"}],
        related:[{id:2,characters:"火山島",meaning:"Volcanic island"}],visually_similar:[],audio_available:true,audio:[{uri:"file:///inert.mp3"}]}
      if(kind==="kana_vocabulary") {
        result.characters="おはよう";result.meanings=["Good morning"];result.readings=[]
        result.reading_mnemonic="";result.reading_hint="";result.material.reading_note=""
      }
      if(kind==="kanji") {result.audio_available=false;result.audio=[]}
      if(kind==="radical") {
        result.characters=null;result.slug="authored-radical";result.images=[Qt.resolvedUrl("radical.svg")]
        result.meanings=["An authored shape"];result.readings=[];result.reading_mnemonic="";result.reading_hint=""
        result.material.reading_note="";result.sentences=[];result.components=[];result.related=[]
        result.audio_available=false;result.audio=[]
      }
      return result
    }
    function state(step,kind,last) {
      var subject=word(kind)
      var steps=kind==="radical"?[{id:"meaning",label:"Meaning"}]:[
        {id:"meaning",label:"Meaning"},{id:"reading",label:kind==="kana_vocabulary"?"Sound":kind==="kanji"?"Reading":"Reading & audio"},
        {id:"context",label:"Context"}]
      var position=steps.findIndex(function(value){return value.id===step})
      var end=position===steps.length-1
      return {id:"authored-lessons",revision:7,mode:"lessons",phase:"lesson",part:"meaning",subject:subject,
        draft:"",index:0,total:2,lesson_index:last?1:0,completed:0,feedback:null,errors:0,overrides:0,invalidated:"",finishing:false,
        lesson_flow:{step:step,steps:steps,position:position+1,total:steps.length,
          can_back:position>0||last===true,can_next:!end||!last,can_quiz:end&&last===true,
          next_label:!end?"Next: "+steps[position+1].label:!last?"Next subject":"",adjusted:false}}
    }
    function make(value) {
      owner.session=value||state("meaning")
      page=study.createObject(surface);verify(page!==null);verify(waitForRendering(page));wait(1)
      tryVerify(function(){return page.questionKey!==""})
      return page
    }
    function item(name) {var value=findChild(page,name);verify(value!==null,name);return value}
    function descendants(root) {
      var all=[]
      for(var child of root.children){all.push(child);all=all.concat(descendants(child))}
      return all
    }
    function texts() {return descendants(page).filter(function(value){return value.visible&&typeof value.text==="string"})}
    function text(value) {return texts().some(function(item){return item.text===value})}
    function setStep(step,kind,last) {
      var next=state(step,kind,last);next.revision=owner.session.revision+1;owner.session=next;owner.busy=false
      tryVerify(function(){return page.lessonSection===step});wait(1)
    }
    function click(name) {var button=item(name);verify(button.enabled&&button.visible,name);button.forceActiveFocus();keyClick(Qt.Key_Space)}
    function init() {
      failOnWarning(/.*/)
      Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"
      backend.ready=true;backend.locked=false;backend.writes=[]
      owner.opened=true;owner.busy=false;owner.error="";owner.contentAccess="authored-account"
      owner.snapshot={settings:{autoplay_lessons:true,autoplay_audio:false},pending:0,demo:true}
      owner.session=null;owner.actions=[];owner.plays=[];owner.stops=0
    }
    function cleanup() {if(page)page.destroy();page=null;wait(1)}
    function test_meaning_reading_context_show_only_the_selected_section() {
      make();verify(item("subject-meaning-heading").visible);verify(item("subject-meaning-note").visible)
      verify(!item("subject-reading-heading").visible);verify(!item("subject-context-heading").visible)
      verify(text("Authored meaning mnemonic."));verify(!text("Authored reading mnemonic."));verify(!text("Play pronunciation"))
      verify(!text("How this subject connects"));compare(backend.writes.length,0)
      setStep("reading");verify(!item("subject-meaning-heading").visible);verify(item("subject-reading-heading").visible)
      verify(item("subject-reading-note").visible);verify(!item("subject-meaning-note").visible)
      verify(text("Authored reading mnemonic."));verify(text("Play pronunciation"));verify(!text("There is a volcano."))
      setStep("context");verify(!item("subject-meaning-heading").visible);verify(!item("subject-reading-heading").visible)
      verify(item("subject-context-heading").visible);verify(text("There is a volcano."))
      var path=item("wanikani-subject-path");verify(path.visible);verify(!path.expanded)
      var disclosure=texts().find(function(item){return item.accessibleName!==undefined && item.text==="How this subject connects"})
      disclosure.forceActiveFocus();keyClick(Qt.Key_Space);tryCompare(path,"expanded",true)
      verify(text("Kanji in this word"));verify(text("Related subjects"))
      verify(text("Fire"));verify(text("Volcanic island"))
      verify(!texts().some(function(item){return item.accessibleName!==undefined && item.text==="Open"}))
      verify(!text("Play pronunciation"));compare(owner.plays.length,0);compare(backend.writes.length,0)
    }
    function test_empty_comparison_is_absent_from_context() {
      make(state("context"));verify(!item("wanikani-lookalikes").visible)
      verify(!texts().some(function(value){return value.text.indexOf("Tell them apart")>=0}))
    }
    function test_available_comparison_is_only_in_context_and_stays_local() {
      var value=state("meaning","kanji")
      value.subject.visually_similar=[{id:102,characters:"大",meanings:["Big"],readings:[{reading:"だい",accepted:true}]}]
      make(value);verify(!item("wanikani-lookalikes").visible)
      value=JSON.parse(JSON.stringify(owner.session));value.revision++;value.lesson_flow=state("context","kanji").lesson_flow
      owner.session=value;wait(1)
      verify(item("wanikani-lookalikes").visible);verify(text("Tell them apart · 1"))
      var control=texts().find(function(item){return item.text==="Tell them apart · 1"})
      control.forceActiveFocus();keyClick(Qt.Key_Space)
      verify(item("wanikani-lookalikes").expanded)
      compare(backend.writes.length,0);compare(owner.actions.length,0);compare(owner.plays.length,0)
    }
    function test_kana_sound_step_has_playback_without_fake_reading_question() {
      make(state("reading","kana_vocabulary"))
      verify(text("2 · Sound"));verify(text("Play pronunciation"));verify(!item("subject-reading-heading").visible)
      verify(!item("subject-meaning-heading").visible);verify(!item("study-answer").visible)
      compare(owner.plays.length,0)
    }
    function test_image_radical_has_no_reading_step_and_waits_for_its_image() {
      make(state("meaning","radical",true));tryVerify(function(){return page.promptReady})
      verify(item("radicalImage").visible);verify(item("subject-meaning-heading").visible)
      verify(!item("subject-reading-heading").visible);verify(!text("Play pronunciation"))
      compare(owner.session.lesson_flow.steps.length,1);verify(item("lesson-start-quiz").visible)
      compare(owner.plays.length,0)
    }
    function test_step_actions_send_current_session_and_revision_and_do_not_quiz_implicitly() {
      make();click("lesson-next")
      compare(owner.actions,[{method:"lesson_navigate",args:{action:"next",session_id:"authored-lessons",revision:7}}])
      setStep("reading");click("lesson-previous")
      compare(owner.actions[1],{method:"lesson_navigate",args:{action:"back",session_id:"authored-lessons",revision:8}})
      setStep("context",null,true);verify(!item("lesson-next").visible);verify(item("lesson-start-quiz").visible)
      page.nextLesson(false);compare(owner.actions.length,2)
      click("lesson-start-quiz");compare(owner.actions[2],{method:"lesson_navigate",args:{action:"quiz",session_id:"authored-lessons",revision:9}})
      compare(backend.writes.length,0)
    }
    function test_enter_advances_step_and_final_focus_requires_explicit_quiz() {
      make();page.focusInput();keyClick(Qt.Key_Return)
      compare(owner.actions[0].args.action,"next")
      setStep("context",null,true);page.focusInput();verify(item("lesson-start-quiz").activeFocus)
      compare(owner.actions.length,1);keyClick(Qt.Key_Return)
      compare(owner.actions[1].args.action,"quiz")
    }
    function test_resume_reading_is_silent_and_deliberate_next_plays_once() {
      make(state("reading"));compare(owner.plays.length,0)
      owner.opened=false;owner.opened=true;page.restoreInput();wait(1);compare(owner.plays.length,0)
      setStep("meaning");click("lesson-next");setStep("reading")
      compare(owner.plays,[101]);page.restoreInput();wait(1);compare(owner.plays,[101])
      click("lesson-next");setStep("context");compare(owner.plays,[101])
    }
    function test_kanji_discovery_and_feedback_do_not_request_ordinary_recordings() {
      make(state("meaning","kanji"));click("lesson-next");setStep("reading","kanji");compare(owner.plays.length,0)
      owner.snapshot={settings:{autoplay_lessons:true,autoplay_audio:true},pending:0,demo:true}
      focusSink.forceActiveFocus()
      owner.session=Object.assign({},owner.session,{phase:"feedback",part:"reading",feedback:{correct:true,retry:false,message:"Correct reading.",accepted:["かざん"]}})
      wait(1);compare(owner.plays.length,0);compare(backend.writes.length,0)
    }
    function test_disabled_autoplay_and_failed_navigation_never_play() {
      make();owner.snapshot={settings:{autoplay_lessons:false,autoplay_audio:false},pending:0,demo:true}
      click("lesson-next");setStep("reading");compare(owner.plays.length,0)
      owner.snapshot={settings:{autoplay_lessons:true,autoplay_audio:false},pending:0,demo:true}
      setStep("meaning");click("lesson-next");owner.error="Authored stale revision"
      setStep("reading");compare(owner.plays.length,0)
    }
    function test_late_navigation_after_closed_or_locked_surface_is_silent() {
      make();click("lesson-next");owner.opened=false;setStep("reading");compare(owner.plays.length,0)
      owner.opened=true;page.restoreInput();compare(owner.plays.length,0)
      setStep("meaning");click("lesson-next");backend.locked=true;setStep("reading");compare(owner.plays.length,0)
      backend.locked=false;page.restoreInput();compare(owner.plays.length,0)
    }
    function test_unrelated_session_replacement_cannot_use_old_autoplay_intent() {
      make();click("lesson-next")
      var other=state("reading");other.id="another-saved-lesson";other.revision=8;owner.session=other;owner.busy=false
      wait(1);compare(owner.plays.length,0)
    }
    function test_changed_subject_or_account_cannot_use_old_autoplay_intent_data() {
      return [{tag:"different-subject",subject:true},{tag:"different-access",subject:false}]
    }
    function test_changed_subject_or_account_cannot_use_old_autoplay_intent(data) {
      make();click("lesson-next")
      var other=state("reading");other.revision=8
      if(data.subject)other.subject.id=202
      else owner.contentAccess="another-account-grant"
      owner.session=other;owner.busy=false
      wait(1);compare(owner.plays.length,0)
    }
    function test_closed_unready_locked_busy_and_question_actions_are_inert() {
      make()
      for(var reason of ["closed","unready","locked","busy","question"]) {
        focusSink.forceActiveFocus()
        owner.opened=true;backend.ready=true;backend.locked=false;owner.busy=false;owner.session=state("meaning")
        if(reason==="closed")owner.opened=false
        if(reason==="unready")backend.ready=false
        if(reason==="locked")backend.locked=true
        if(reason==="busy")owner.busy=true
        if(reason==="question")owner.session=Object.assign(state("meaning"),{phase:"question"})
        page.nextLesson(false);page.nextLesson(true);page.navigateLesson("quiz")
        compare(owner.actions.length,0,reason)
      }
    }
    function test_missing_image_blocks_forward_but_permits_available_back() {
      var value=state("meaning","radical",true);value.subject.images=[];make(value)
      verify(!page.promptReady);verify(!item("lesson-start-quiz").enabled)
      page.navigateLesson("quiz");compare(owner.actions.length,0)
      click("lesson-previous");compare(owner.actions[0].args.action,"back")
    }
    function test_unavailable_subject_back_uses_current_identity() {
      var value=state("meaning",null,true);value.subject=null;value.restricted=true;owner.session=value
      page=study.createObject(surface);verify(waitForRendering(page));wait(1)
      click("lesson-unavailable-back")
      compare(owner.actions[0],{method:"lesson_navigate",args:{action:"back",session_id:"authored-lessons",revision:7}})
    }
    function test_adjusted_step_is_explained_and_does_not_autoplay() {
      var value=state("reading");value.lesson_flow.adjusted=true;make(value)
      verify(texts().some(function(item){return item.text.indexOf("nearest available step")>=0}))
      compare(owner.plays.length,0)
    }
    function test_narrow_live_light_dark_layout_keeps_complete_text() {
      make(state("context",null,true));page.width=290
      for(var colors of [["#fffdf5","#222222","#006699"],["#171b27","#e0e6f8","#9cc7ff"]]) {
        Color.background=colors[0];Color.foreground=colors[1];Color.accent=colors[2]
        verify(waitForRendering(page));wait(20)
        for(var label of texts()) {
          if(label.renderType!==Text.NativeRendering)continue
          verify(!label.truncated,"Complete: "+label.text)
          verify(label.contentWidth<=label.width+1,"Fits: "+label.text)
          if(label.surfaceColor!==undefined)verify(Theme.contrast(label.color,label.surfaceColor)>=4.5,"Contrast: "+label.text)
        }
      }
      compare(owner.actions.length,0);compare(owner.plays.length,0)
    }
  }
}
'''


def build(directory):
    qml = directory / "qml"
    qml.mkdir()
    for name in ("Study", "SubjectDetails", "SubjectPath", "Pronunciation", "KanjiExamples", "Lookalikes", "Label", "Card", "Action",
                 "ActivationGuard", "SubjectGlyph", "JapaneseText", "RadicalImage"):
        shutil.copyfile(ROOT / "qml" / (name + ".qml"), qml / (name + ".qml"))
    for name in ("Theme.mjs", "UnicodeText.mjs"):
        shutil.copyfile(ROOT / "qml" / name, qml / name)
    for name, properties in {"Crab": "property bool animate;property bool celebrating",
                             "SessionRecap": "property var controller;property var session"}.items():
        (qml / (name + ".qml")).write_text("import QtQuick\nItem {" + properties + "}\n")
    vendor = directory / "vendor"
    vendor.mkdir()
    shutil.copyfile(ROOT / "vendor" / "WanaKana.mjs", vendor / "WanaKana.mjs")
    shutil.copyfile(ROOT / "tests" / "qml" / "fixtures" / "radical.svg", directory / "radical.svg")
    common = directory / "qs" / "Commons"
    common.mkdir(parents=True)
    (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\nsingleton Border 1.0 Border.qml\n")
    style = foundation.STYLE.replace("controlGap:6", "controlGap:6,inputPaddingY:8,md:8,controlHeight:34")
    style = style.replace("bodySmall:12", "bodySmall:12,title:20")
    style = style.replace("  function selectedStateColor", "  function controlFill(focused,hot,foreground,accent) {return Qt.alpha(foreground,focused?.12:.04)}\n"
        "  function selectionFillFor(foreground,accent) {return Qt.alpha(accent,.65)}\n  function selectedStateColor")
    (common / "Style.qml").write_text(style)
    (common / "Border.qml").write_text(foundation.BORDER)
    (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {property color background:"#fffdf5";'
        'property color foreground:"#222222";property color accent:"#006699";property color urgent:"#990000";'
        'property var tooltip:({background:"#fff",text:"#000",border:"#000"})}\n')
    ui = directory / "qs" / "Ui"
    ui.mkdir()
    (ui / "qmldir").write_text("module qs.Ui\nButton 1.0 Button.qml\nTextField 1.0 TextField.qml\nBorderSurface 1.0 BorderSurface.qml\n")
    for name in ("Button", "TextField"):
        shutil.copyfile(NATIVE / (name + ".qml"), ui / (name + ".qml"))
    (ui / "BorderSurface.qml").write_text("import QtQuick\nRectangle {property var borderSpec:({});property real leftPadding:0;property real rightPadding:0;property real topPadding:0;property real bottomPadding:0}\n")
    (directory / "tst_LessonFlow.qml").write_text(QML)


@unittest.skipUnless(RUNNER.is_file() and (NATIVE / "Button.qml").is_file(), "Qt and native Omarchy controls required")
class LessonFlowUiTests(unittest.TestCase):
    def test_actual_guided_lesson_components(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-lesson-flow-ui-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, errors="replace", timeout=45,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
