"""Cached five-skill Today recap; native rendering with no worker/history IO."""
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
  id:surface;width:742;height:1100;color:Color.background
  readonly property color kaniSurface:color
  property color kaniText:Color.foreground
  property var page:null
  readonly property string epoch:"01234567-89ab-cdef-0123-456789abcdef"
  readonly property string otherEpoch:"ffffffff-ffff-ffff-ffff-ffffffffffff"
  Component {id:component;Kani.TodayActivity {x:16;y:16;width:surface.width-32;controller:owner}}
  QtObject {
    id:backend
    property bool ready:true
    property bool locked:false
    property bool learningDigestHydrated:true
    property bool learningDigestDirty:false
    property var calls:[]
    function request(method,args){calls=calls.concat([{method:method,args:args}])}
    function configureRhythm(args){calls=calls.concat([{method:"rhythm",args:args}])}
  }
  QtObject {id:oldBackend;property bool ready:true;property bool locked:false}
  QtObject {
    id:owner
    property var service:backend
    property bool opened:true
    property var snapshot:({})
    property var routes:[]
    property var actions:[]
    function navigate(view){routes=routes.concat([view])}
    function call(method,args){actions=actions.concat([{method:method,args:args}])}
    function begin(mode,limit,ids){actions=actions.concat([{mode:mode,limit:limit,ids:ids}])}
  }
  TestCase {
    name:"TodayActivity";when:windowShown
    function copy(value){return JSON.parse(JSON.stringify(value))}
    function window(days,end){
      var start=new Date(end+"T12:00:00Z");start.setUTCDate(start.getUTCDate()-(days-1))
      return {days:days,start_day:start.toISOString().slice(0,10),end_day:end,
        subject_completions:{reviews:27,lessons:4,practice:8},sessions_completed:{reviews:5,lessons:1,practice:2},
        listening_ratings:{remembered:5,again:2,skipped:1},listening_sessions_completed:2,
        dictation_ratings:{matched:6,again:3,skipped:2},dictation_sessions_completed:3,typo_corrections:1}
    }
    function raw(){
      var now=new Date();now.setUTCMilliseconds(0)
      var end=now.toISOString().slice(0,10)
      return {schema_version:1,scope:"recorded_on_this_device",freshness:"cached",generated_at:now.toISOString(),data_epoch:epoch,
        demo:false,timezone:"UTC",complete:true,stale:false,coverage:"retained_local_records",includes_retained_pre_reset_activity:true,
        windows:{"7":window(7,end),"30":window(30,end)}}
    }
    function state(value){return {demo:false,session_epoch:epoch,status:"online",learning_digest:value}}
    function make(width){surface.width=width+32;page=component.createObject(surface);verify(page!==null);wait(1);var rendered=false;verify(page.grabToImage(function(image){rendered=!!image}));tryVerify(function(){return rendered})}
    function item(name){var node=findChild(page,name);verify(node!==null,name);return node}
    function replace(value){owner.snapshot=state(value);wait(1)}
    function visibleText(){return paletteItems(page).filter(function(node){return node.visible&&typeof node.text==="string"&&node.textFormat!==undefined}).map(function(node){return node.text}).join("\n")}
    function noIO(){compare(backend.calls,[]);compare(owner.actions,[]);compare(owner.routes,[])}
    function unavailable(){compare(page.digest,null);compare(page.totals,null);verify(!item("today-activity-written").visible,"Written counts hidden");verify(!item("today-activity-listening").visible,"Listening ratings hidden");verify(!item("today-activity-dictation").visible,"Dictation results hidden");verify(!item("today-activity-window").visible,"Date window hidden");verify(!item("today-activity-calculated").visible,"Calculation timestamp hidden");compare(item("today-activity-cache").text,"A saved seven-day recap isn’t available yet.")}
    function init(){
      failOnWarning(/.*/);owner.service=backend;owner.opened=true;owner.routes=[];owner.actions=[]
      backend.ready=true;backend.locked=false;backend.learningDigestHydrated=true;backend.learningDigestDirty=false;backend.calls=[]
      owner.snapshot=state(raw());Color.background="#fffdf5";Color.foreground="#202020";Color.accent="#006699";Color.urgent="#990000"
      surface.color=Qt.binding(function(){return Color.background});surface.kaniText=Qt.binding(function(){return Color.foreground})
    }
    function cleanup(){if(page)page.destroy();page=null;wait(1)}
    __CHECKS__
    function test_five_skills_cycles_ratings_and_skips_are_separate_data(){return [{tag:"narrow",width:290},{tag:"standard",width:710}]}
    function test_five_skills_cycles_ratings_and_skips_are_separate(data){
      make(data.width);verify(page.digest!==null)
      compare(item("today-activity-reviews").text,"Reviews 27");compare(item("today-activity-lessons").text,"Lessons 4");compare(item("today-activity-practice").text,"Practice 8")
      compare(item("today-activity-listening-results").text,"5 remembered · 2 Again · 1 skipped")
      compare(item("today-activity-dictation-results").text,"6 matched · 3 Again · 2 skipped")
      verify(visibleText().indexOf("Finished written study")>=0);verify(visibleText().indexOf("your ratings")>=0);verify(visibleText().indexOf("recording matches")>=0)
      verify(visibleText().indexOf("Other devices are not included")>=0);verify(visibleText().indexOf("after a reset")>=0)
      var original=owner.snapshot.learning_digest
      compare(item("today-activity-window").text,original.windows["7"].start_day+" – "+original.windows["7"].end_day+" · UTC")
      verify(item("today-activity-calculated").text.endsWith(" UTC"))
      compare(item("today-activity-calculated").Accessible.name,"Calculated "+original.generated_at+". Reporting calendar: UTC.")
      compare(page.digest.stale,null);compare(item("today-activity-cache").text,"Saved recap · latest activity not checked.")
      verify(page.height<520,"A five-skill recap remains a compact narrow card")
      noIO();wait(50);noIO()
    }
    function test_known_zero_is_distinct_from_missing_history(){
      var value=raw()
      for(var period of ["7","30"]){var row=value.windows[period];for(var key of ["subject_completions","sessions_completed","listening_ratings","dictation_ratings"])for(var name of Object.keys(row[key]))row[key][name]=0;for(var name of ["listening_sessions_completed","dictation_sessions_completed","typo_corrections"])row[name]=0}
      replace(value);make(290)
      compare(item("today-activity-reviews").text,"Reviews 0");compare(item("today-activity-listening-results").text,"0 remembered · 0 Again · 0 skipped")
      compare(item("today-activity-dictation-results").text,"0 matched · 0 Again · 0 skipped")
      replace(null);unavailable();verify(visibleText().indexOf("Reviews 0")<0);noIO()
    }
    function test_calculation_zone_and_exact_source_remain_distinct_from_reporting_calendar(){
      var value=raw();value.generated_at="2026-09-05T12:00:00.123456+05:30";value.timezone="Asia/Kolkata"
      value.windows={"7":window(7,"2026-09-05"),"30":window(30,"2026-09-05")};replace(value);make(290)
      verify(page.digest!==null);compare(item("today-activity-calculated").text,"Calculated 5 Sep 2026, 06:30:00 UTC")
      compare(item("today-activity-calculated").Accessible.name,"Calculated 2026-09-05T12:00:00.123456+05:30. Reporting calendar: Asia/Kolkata.")
      compare(item("today-activity-window").text,"2026-08-30 – 2026-09-05 · Asia/Kolkata")
      compare(page.digest.generated_at,value.generated_at);noIO()
    }
    function test_partial_and_known_stale_flags_preserve_exact_calculation_and_counts(){
      make(290);var original=JSON.stringify(page.totals),timestamp=item("today-activity-calculated").text
      backend.learningDigestDirty=true;compare(page.digest.stale,true);compare(item("today-activity-cache").text,"Saved recap · needs updating.")
      compare(JSON.stringify(page.totals),original);compare(item("today-activity-calculated").text,timestamp)
      backend.learningDigestDirty=false;var value=raw();value.complete=false;replace(value)
      compare(item("today-activity-cache").text,"Partial saved recap · latest activity not checked.");compare(item("today-activity-reviews").text,"Reviews 27")
      value.stale=true;replace(copy(value));compare(item("today-activity-cache").text,"Partial saved recap · needs updating.")
      verify(item("today-activity-cache").mapToItem(page,0,0).y<item("today-activity-written").mapToItem(page,0,0).y)
      noIO()
    }
    function test_clock_jump_and_old_calendar_window_mark_cache_stale_without_rewriting_dates(){
      make(290);var original=owner.snapshot.learning_digest.generated_at
      owner.snapshot=Object.assign({},owner.snapshot,{status:"clock_changed"});compare(page.digest.stale,true);compare(page.digest.generated_at,original)
      var value=raw(),then=new Date(Date.now()-2*86400000);value.generated_at=then.toISOString()
      value.windows={"7":window(7,value.generated_at.slice(0,10)),"30":window(30,value.generated_at.slice(0,10))};replace(value)
      compare(page.digest.stale,true);compare(page.digest.generated_at,value.generated_at);compare(page.totals.end_day,value.windows["7"].end_day)
      noIO()
    }
    function test_absent_readiness_hydration_dirty_or_clock_metadata_is_unavailable(){
      make(290);backend.ready=false;unavailable();backend.ready=true;verify(page.digest!==null)
      backend.learningDigestHydrated=false;unavailable();backend.learningDigestHydrated=true;verify(page.digest!==null)
      owner.service=oldBackend;unavailable();owner.service=backend;verify(page.digest!==null)
      for(var service of [{ready:true,learningDigestHydrated:true},{ready:true,learningDigestDirty:false},{learningDigestHydrated:true,learningDigestDirty:false},null]){owner.service=service;unavailable()}
      owner.service=backend
      var missing=state(raw());delete missing.status;owner.snapshot=missing;unavailable()
      noIO()
    }
    function test_worker_restart_account_epoch_and_demo_change_hide_old_totals(){
      make(290);backend.learningDigestHydrated=false;unavailable()
      backend.ready=false;backend.ready=true;unavailable();backend.learningDigestHydrated=true;verify(page.digest!==null)
      owner.snapshot=Object.assign({},owner.snapshot,{session_epoch:otherEpoch});unavailable()
      var changed=raw();changed.data_epoch=otherEpoch;owner.snapshot={demo:false,session_epoch:otherEpoch,status:"online",learning_digest:changed};verify(page.digest!==null)
      owner.snapshot=Object.assign({},owner.snapshot,{demo:true});unavailable()
      changed.demo=true;owner.snapshot={demo:true,session_epoch:otherEpoch,status:"online",learning_digest:copy(changed)}
      verify(page.digest!==null);compare(item("today-activity-scope").text,"Demo · recorded on this device")
      noIO()
    }
    function test_closed_or_hidden_page_has_no_retained_projection_or_activity_requests(){
      make(290);var original=JSON.stringify(owner.snapshot);page.visible=false;compare(page.digest,null);wait(30);noIO()
      page.visible=true;verify(page.digest!==null);owner.opened=false;compare(page.digest,null);verify(!item("today-activity-explore").enabled)
      owner.opened=true;verify(page.digest!==null);backend.locked=true;unavailable();verify(!item("today-activity-explore").enabled)
      backend.locked=false;verify(page.digest!==null);verify(item("today-activity-explore").enabled)
      compare(JSON.stringify(owner.snapshot),original);noIO()
    }
    function test_explore_is_one_explicit_native_keyboard_navigation_only(){
      make(290);noIO();var action=item("today-activity-explore");action.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)
      compare(owner.routes,["activity"]);compare(owner.actions,[]);compare(backend.calls,[])
      replace(null);action.forceActiveFocus();keyClick(Qt.Key_Return);wait(1)
      compare(owner.routes,["activity","activity"]);compare(owner.actions,[]);compare(backend.calls,[])
    }
    function test_private_extras_never_enter_projection_rendering_or_accessible_text(){
      var value=raw();value.answer="PRIVATE ANSWER";value.username="PRIVATE ACCOUNT";value.token="PRIVATE TOKEN"
      value.windows["7"].subject_completions.note="PRIVATE NOTE";value.windows["7"].dictation_ratings.expected_kana="PRIVATE KANA"
      value.windows["7"].audio_url="PRIVATE URL";value.windows["30"].meaning="PRIVATE MEANING";replace(value);make(290)
      verify(page.digest!==null);verify(JSON.stringify(page.digest).indexOf("PRIVATE")<0);verify(visibleText().indexOf("PRIVATE")<0)
      for(var node of paletteItems(page))verify(String(node.Accessible.name||"").indexOf("PRIVATE")<0)
      noIO()
    }
    function test_malformed_contract_counts_dates_and_missing_audio_skill_fail_closed(){
      make(290)
      for(var change of [function(v){v.schema_version=2},function(v){delete v.windows["7"].dictation_ratings},function(v){v.windows["7"].listening_ratings.skipped=true},
          function(v){v.windows["7"].subject_completions.reviews=-1},function(v){v.windows["7"].subject_completions.reviews=28},
          function(v){v.windows["7"].start_day="2026-02-31"},function(v){v.generated_at="PRIVATE ERROR"},function(v){v.data_epoch="PRIVATE ACCOUNT"}]){
        var value=raw();change(value);replace(value);unavailable();verify(visibleText().indexOf("PRIVATE")<0)
      }
      noIO()
    }
    function test_maximum_safe_counters_wrap_without_clipping_or_merging_skips(){
      var value=raw()
      for(var period of ["7","30"])for(var metric of ["subject_completions","listening_ratings","dictation_ratings"])for(var key of Object.keys(value.windows[period][metric]))value.windows[period][metric][key]=9007199254740991
      replace(value);make(290);verify(page.digest!==null)
      for(var node of paletteItems(page))if(node.visible&&typeof node.text==="string"&&node.textFormat!==undefined){verify(!node.truncated,node.text);verify(node.contentWidth<=node.width+1,"Fits: "+node.text)}
      verify(item("today-activity-dictation-results").text.indexOf("9007199254740991 skipped")>=0);noIO()
    }
    function test_stock_palette_keeps_cached_totals_and_composited_native_focus_data(){return paletteData()}
    function test_stock_palette_keeps_cached_totals_and_composited_native_focus(data){
      make(290);var original=JSON.stringify(owner.snapshot);applyPalette(data);checkText(page,data.tag+" cached activity")
      var action=item("today-activity-explore");action.forceActiveFocus();wait(140);var ring=findChild(action,"wanikani-action-focus")
      verify(ring.visible);verify(Theme.contrast(ring.border.color,Theme.composite(action.color,renderedUnder(action.parent)))>=3)
      for(var node of paletteItems(page))if(node.visible&&typeof node.text==="string"&&node.textFormat!==undefined){verify(!node.truncated,node.text);verify(node.contentWidth<=node.width+1,"Fits: "+node.text)}
      compare(JSON.stringify(owner.snapshot),original);noIO()
    }
    function test_alternate_popup_surface_uses_actual_composited_text(){
      make(290);surface.color="#eef0e8";surface.kaniText="#314438";Color.background="#171925";Color.foreground="#dfe4f3";Color.accent="#eeeeee";wait(140)
      checkText(page,"alternate popup");noIO()
    }
  }
}
'''


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    palettes.pure_native_style(directory)
    for name in ("TodayActivity.qml", "LearningDigest.mjs"):
        shutil.copyfile(ROOT / "qml" / name, directory / "qml" / name)
    checks = palettes.CHECKS.replace("__PALETTES__", json.dumps(palettes.palettes()))
    (directory / "tst_TodayActivity.qml").write_text(QML.replace("__CHECKS__", checks))


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Native Qt controls required")
class TodayActivityUiTests(unittest.TestCase):
    def test_actual_cached_activity_projection_native_layout_and_actions(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-today-activity-") as temporary:
            directory = Path(temporary);build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=50, env={**os.environ, "TZ": "UTC", "QT_QPA_PLATFORM": "offscreen",
                    "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
