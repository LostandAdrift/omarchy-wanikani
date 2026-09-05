"""Actual Today dashboard, authored cache only, native buttons and theme tokens.

The first-page budget is a 500px content viewport, leaving the ordinary 760px
shell frame room for title/navigation. No installed shell or theme is changed.
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
RUNNER = foundation.RUNNER
QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme

Rectangle {
  id:surface;width:742;height:700;color:Color.background
  readonly property color kaniSurface:color
  property color kaniText:Color.foreground
  property var page:null
  Item {id:focusSink}
  Flickable {
    id:viewport;x:16;y:16;width:surface.width-32;height:500;clip:true
    contentWidth:width;contentHeight:page?page.height:0
  }
  Component {id:dashboard;Kani.Dashboard {width:viewport.width;controller:owner}}
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property bool animations:false
    property var requests:[]
    property var rhythm:[]
    function request(method,args){requests=requests.concat([{method:method,args:args}])}
    function configureRhythm(args){rhythm=rhythm.concat([args])}
  }
  QtObject {
    id:owner
    property var service:backend
    property bool opened:true
    property bool busy:false
    property var snapshot:({})
    property var begins:[]
    property var routes:[]
    property var calls:[]
    property var subjects:[]
    function begin(mode,limit,ids){begins=begins.concat([{mode:mode,limit:limit,ids:ids||null}])}
    function navigate(view){routes=routes.concat([view])}
    function call(method,args){calls=calls.concat([{method:method,args:args}])}
    function showSubject(id){subjects=subjects.concat([id])}
  }
  TestCase {
    name:"TodayDashboard";when:windowShown
    function current(){return {level:2,accessible:true,complete:true,total:30,passed:24,required:27,remaining:3,
      fraction:24/27,final_level:false,elapsed_days:4,pending:1,attention:0,message:"3 more kanji to pass to reach the level-up target."}}
    function snapshot(){return {username:"Authored learner",reviews:27,lessons:18,
      saved_sessions:{reviews:{completed:2,total:5},lessons:{completed:1,total:5}},vacation:false,demo:false,settings:{},
      milestone:null,message:"",syncing:false,now:1788550000,last_sync:"2026-09-05T10:00:00Z",learning_progress:current(),
      forecast:[],difficult:[],activity:[],pending:0,attention:0}}
    function make(width){surface.width=width+32;page=dashboard.createObject(viewport.contentItem);verify(page!==null);wait(1);verify(waitForRendering(page));viewport.contentY=0}
    function item(name){var result=findChild(page,name);verify(result!==null,name);return result}
    function change(values){owner.snapshot=Object.assign({},owner.snapshot,values);wait(1)}
    function level(values){change({learning_progress:Object.assign({},owner.snapshot.learning_progress,values)})}
    function firstPage(name){var node=item(name),top=node.mapToItem(page,0,0).y;verify(node.visible,name+" visible");verify(top>=0&&top+node.height<=viewport.height,name+" within initial500px: "+top+"–"+(top+node.height))}
    function click(name){var node=item(name);verify(node.visible&&node.enabled,name);node.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
    function text(value){var matches=paletteItems(page).filter(function(node){return node.visible&&node.text===value&&node.accessibleName!==undefined});compare(matches.length,1,value);return matches[0]}
    function noIO(){compare(backend.requests,[]);compare(backend.rhythm,[]);compare(owner.calls,[]);compare(owner.begins,[]);compare(owner.routes,[]);compare(owner.subjects,[])}
    function init(){
      failOnWarning(/.*/);owner.snapshot=snapshot();owner.busy=false;owner.opened=true
      owner.begins=[];owner.routes=[];owner.calls=[];owner.subjects=[];backend.requests=[];backend.rhythm=[]
      backend.ready=true;backend.locked=false;backend.animations=false
      Color.background="#fffdf5";Color.foreground="#202020";Color.accent="#006699";Color.urgent="#990000"
      surface.kaniText=Qt.binding(function(){return Color.foreground});surface.color=Qt.binding(function(){return Color.background})
      focusSink.forceActiveFocus()
    }
    function cleanup(){if(page)page.destroy();page=null;wait(1)}
    __CHECKS__
    function test_reviews_lessons_and_confirmed_target_fit_first_viewport_data(){return [{tag:"narrow",width:290},{tag:"medium",width:380},{tag:"columns",width:480},{tag:"standard",width:710}]}
    function test_reviews_lessons_and_confirmed_target_fit_first_viewport(data){
      make(data.width)
      for(var name of ["today-reviews-count","today-lessons-count","today-reviews-saved","today-lessons-saved",
          "today-reviews-begin","today-lessons-begin","today-level-heading","today-level-count","today-level-meter",
          "today-level-target","today-level-pending","today-level-explore"])firstPage(name)
      compare(item("today-reviews-count").text,"27 due");compare(item("today-lessons-count").text,"18 new")
      compare(item("today-reviews-saved").text,"Saved · 2 of 5 complete");compare(item("today-lessons-saved").text,"Saved · 1 of 5 complete")
      compare(item("today-level-count").text,"24 / 27");compare(item("today-level-meter").value,24/27)
      compare(item("today-level-target").text,"3 more kanji to pass for level-up.")
      verify(item("today-level-pending").text.indexOf("outside the confirmed count")>=0)
      noIO();wait(40);noIO()
    }
    function test_saved_modes_have_separate_native_keyboard_resume_actions(){
      make(290);click("today-reviews-begin");click("today-lessons-begin")
      compare(owner.begins,[{mode:"reviews",limit:5,ids:null},{mode:"lessons",limit:5,ids:null}])
      click("today-reviews-overview");click("today-lessons-overview");click("today-level-explore")
      compare(owner.routes,["review-overview","lesson-overview","progress"])
      compare(backend.requests,[]);compare(owner.calls,[])
    }
    function test_new_review_batches_and_deliberate_lesson_choice_keep_distinct_routes(){
      change({saved_sessions:{reviews:null,lessons:null}});make(290)
      compare(item("today-reviews-begin").text,"Review 5 →");compare(item("today-lessons-begin").text,"Choose lessons →")
      click("today-reviews-begin");click("today-lessons-begin")
      compare(owner.begins,[{mode:"reviews",limit:5,ids:null}]);compare(owner.routes,["lesson-overview"])
      change({reviews:0,lessons:0});verify(!item("today-reviews-begin").enabled);verify(!item("today-lessons-begin").enabled)
      verify(item("today-reviews-overview").enabled&&item("today-lessons-overview").enabled)
      change({saved_sessions:{reviews:{completed:0,total:5},lessons:{completed:0,total:3}}})
      verify(item("today-reviews-begin").enabled&&item("today-lessons-begin").enabled)
      compare(item("today-lessons-saved").text,"Saved · 0 of 3 complete")
    }
    function test_busy_and_vacation_states_remain_visible_and_keep_saved_work_resumable(){
      make(290);owner.busy=true;wait(1)
      verify(!item("today-reviews-begin").enabled);verify(!item("today-lessons-begin").enabled)
      owner.busy=false;change({vacation:true,saved_sessions:{reviews:null,lessons:null}})
      verify(!item("today-reviews-begin").enabled);verify(!item("today-lessons-begin").enabled)
      verify(item("today-reviews-saved").text.indexOf("Vacation")>=0);verify(item("today-vacation").visible)
      change({saved_sessions:{reviews:{completed:2,total:5},lessons:null}})
      verify(item("today-reviews-begin").enabled);verify(!item("today-lessons-begin").enabled)
      verify(item("today-reviews-saved").text.indexOf("vacation")>=0)
      click("today-reviews-begin");compare(owner.begins,[{mode:"reviews",limit:5,ids:null}])
    }
    function test_both_audio_modes_remain_explicit_and_never_autostart(){
      make(290);noIO();click("today-listen");click("today-dictation")
      compare(owner.routes,["listen","dictation"]);compare(owner.begins,[]);compare(owner.calls,[]);compare(backend.requests,[])
      owner.opened=false;page.visible=false;change({reviews:35});wait(40)
      compare(owner.routes,["listen","dictation"]);compare(backend.requests,[])
    }
    function test_partial_access_and_final_level_never_claim_zero_or_level61(){
      make(290);level({complete:false,required:null,fraction:null})
      compare(item("today-level-count").text,"—");compare(item("today-level-meter").value,0)
      compare(item("today-level-count-label").text,"Waiting for a complete sync");verify(item("today-level-explore").enabled)
      level({accessible:false});compare(item("today-level-count-label").text,"Progress unavailable");verify(!item("today-level-explore").enabled)
      change({learning_progress:Object.assign(current(),{level:60,final_level:true})})
      compare(item("today-level-heading").text,"Level 60 · Final level")
      compare(item("today-level-target").text,"3 more kanji to pass on this final level.")
      level({passed:27,fraction:1});compare(item("today-level-target").text,"Final level passing target reached.")
      verify(item("today-level-target").text.indexOf("61")<0);firstPage("today-level-count");noIO()
    }
    function test_demo_milestone_is_preserved_below_essential_counts_and_never_claims_live_confirmation(){
      change({demo:true,milestone:{id:"authored-milestone",level:3},learning_progress:Object.assign(current(),{passed:27,fraction:1})});make(290)
      firstPage("today-level-target");verify(item("today-milestone").visible)
      verify(item("today-milestone").mapToItem(page,0,0).y>item("today-level-target").mapToItem(page,0,0).y)
      compare(item("today-level-target").text,"Demo passing target reached.")
      verify(item("today-level-meter").Accessible.name.indexOf("confirmed locally in demo")>=0)
      verify(paletteItems(page).some(function(node){return node.visible&&node.text==="Demo milestone · Level 3"}))
      var dismiss=text("Dismiss");dismiss.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)
      compare(owner.calls,[{method:"ack_milestone",args:{id:"authored-milestone"}}]);compare(owner.begins,[])
    }
    function test_onboarding_remains_explicit_and_never_reads_account(){
      change({username:"",learning_progress:null,saved_sessions:{},reviews:0,lessons:0});make(290)
      verify(!item("today-reviews").visible);verify(!item("today-lessons").visible);verify(!item("today-level").visible)
      noIO();var connect=text("Connect WaniKani");connect.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)
      compare(owner.routes,["settings"]);compare(owner.calls,[])
      var demo=text("Try the demo");demo.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)
      compare(owner.calls,[{method:"use_demo",args:{enabled:true}}]);compare(backend.requests,[])
    }
    function test_malformed_optional_progress_remains_unavailable(){
      make(290)
      for(var value of [null,{},Object.assign(current(),{passed:true}),Object.assign(current(),{required:0}),Object.assign(current(),{fraction:NaN}),Object.assign(current(),{fraction:1.2})]){
        change({learning_progress:value});compare(item("today-level-count").text,"—");compare(item("today-level-meter").value,0)
      }
      noIO()
    }
    function test_unknown_or_damaged_saved_summary_routes_to_check_without_inventing_counts(){
      make(290)
      for(var value of [undefined,{},true,[],{completed:1,total:0},{completed:true,total:5},{completed:6,total:5},
          {completed:2,total:5,mode:"practice"},{completed:2,total:5,phase:"complete"},{completed:2,total:5,invalidated:"reset"}]){
        change({saved_sessions:{reviews:value,lessons:null}})
        compare(item("today-reviews-begin").text,"Check saved status →")
        compare(item("today-reviews-saved").text,"Saved session status needs a check.")
        verify(item("today-reviews-begin").Accessible.name.indexOf("reviews")>=0)
        verify(!item("today-reviews-overview").visible)
        click("today-reviews-begin");compare(owner.routes.slice(-1),["review-overview"])
      }
      change({saved_sessions:null});click("today-lessons-begin");compare(owner.routes.slice(-1),["lesson-overview"])
      compare(owner.begins,[]);compare(owner.calls,[]);compare(backend.requests,[])
    }
    function test_large_due_count_narrow_wrapping_does_not_clip_labels(){
      change({reviews:9999,lessons:999,saved_sessions:{reviews:null,lessons:null}});make(290)
      for(var label of paletteItems(page))if(label.visible&&typeof label.text==="string"&&label.textFormat!==undefined){verify(!label.truncated,label.text);verify(label.contentWidth<=label.width+1,"Fits: "+label.text)}
      firstPage("today-level-target");noIO()
    }
    function test_stock_palette_keeps_snapshot_focus_and_composited_contrast_data(){return paletteData()}
    function test_stock_palette_keeps_snapshot_focus_and_composited_contrast(data){
      make(290);var saved=JSON.stringify(owner.snapshot);applyPalette(data);checkText(page,data.tag+" Today")
      for(var name of ["today-reviews-begin","today-lessons-begin","today-level-explore"]){
        var button=item(name);button.forceActiveFocus();wait(140);var ring=findChild(button,"wanikani-action-focus")
        verify(ring.visible);verify(Theme.contrast(ring.border.color,Theme.composite(button.color,renderedUnder(button.parent)))>=3)
        checkText(button,data.tag+" focus "+name)
      }
      var meter=item("today-level-meter");verify(Theme.contrast(meter.children[0].color,meter.color)>=3)
      for(var label of paletteItems(page))if(label.visible&&typeof label.text==="string"&&label.textFormat!==undefined){verify(!label.truncated,label.text);verify(label.contentWidth<=label.width+1,"Fits: "+label.text)}
      firstPage("today-level-pending");compare(JSON.stringify(owner.snapshot),saved);noIO()
    }
    function test_custom_popup_foreground_and_background_are_composited(){
      make(290);surface.color="#eef0e8";surface.kaniText="#314438";Color.background="#171925";Color.foreground="#dfe4f3";Color.accent="#eeeeee";wait(140)
      checkText(page,"alternate popup surface");var meter=item("today-level-meter");verify(Theme.contrast(meter.children[0].color,meter.color)>=3);noIO()
    }
  }
}
'''


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    palettes.pure_native_style(directory)
    for name in ("Dashboard", "TodayLevel", "OfflineStatus", "Forecast", "Crab"):
        shutil.copyfile(ROOT / "qml" / (name + ".qml"), directory / "qml" / (name + ".qml"))
    shutil.copyfile(ROOT / "qml/ForecastModel.mjs", directory / "qml/ForecastModel.mjs")
    checks = palettes.CHECKS.replace("__PALETTES__", json.dumps(palettes.palettes()))
    (directory / "tst_Today.qml").write_text(QML.replace("__CHECKS__", checks))


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Qt and native Omarchy controls required")
class DashboardUiTests(unittest.TestCase):
    def test_actual_today_initial_view_and_explicit_actions(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-today-ui-") as temporary:
            directory = Path(temporary);build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=60, env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                    "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
