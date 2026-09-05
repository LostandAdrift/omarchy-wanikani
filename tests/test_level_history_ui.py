"""Actual level-history and Progress tabs with native controls and inert IO."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_learning_progress_rendering as progress
import test_lesson_flow_ui as foundation
import test_stock_palette_surfaces as palettes


ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER


HISTORY_DATA = r'''
    function visit(id,state) {
      var value={id:id,level:3,attempt_label:"Recorded visit "+id,state:state||"passed",label:"Level passed",
        elapsed_seconds:176400,elapsed_to:"passed",elapsed_days:2,date_status:"known",date_notice:"",
        created_at:"2026-09-01T12:00:00Z",unlocked_at:"2026-09-01T12:00:00Z",started_at:"2026-09-01T13:00:00Z",
        passed_at:"2026-09-03T13:00:00Z",completed_at:null,abandoned_at:null}
      if(state==="all_burned"){value.label="All assignments burned";value.completed_at="2026-09-04T14:00:00Z"}
      if(state==="abandoned"){
        value.label="Abandoned visit";value.passed_at=null;value.abandoned_at="2026-09-02T12:00:00Z";value.elapsed_seconds=86400;value.elapsed_to="abandoned"
      }
      if(state==="unknown"){
        value.label="Recorded status unknown";value.passed_at=null;value.elapsed_seconds=null;value.elapsed_to=null;value.date_status="partial"
        value.date_notice="Recorded dates need a refresh; elapsed time is unknown."
      }
      return value
    }
    function history(args) {
      return {status:"available",source:"WaniKani level progressions",offset:args.offset,limit:12,total:16,
        has_more:args.offset===0,next_offset:args.offset===0?12:null,cache_complete:true,history_complete:false,
        partial:false,truncated:false,reason:"ready",message:"WaniKani may not supply your full history. Calendar time includes vacations and pauses.",
        items:args.offset===0?[visit(16),visit(15,"all_burned"),visit(14,"abandoned"),visit(13,"unknown")]:[visit(4)]}
    }
'''

TESTS = r'''
  TestCase {
    name:"LevelHistoryUi";when:windowShown
    function init(){
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;service.hold=false;service.requests=[];service.pending=[]
      service.snapshot={demo:false,level:3,max_level:60,last_sync:"old",session_epoch:"authored",session_revision:1,pending:0,attention:0,vacation:false}
      owner.service=service;owner.opened=true;owner.contentAccess="authored-account";owner.openedIds=[]
      Color.background="#fffdf5";Color.foreground="#222222";Color.accent="#006699"
    }
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    function make(){screen=historyComponent.createObject(parent);verify(screen!==null);wait(1);return screen}
    function settle(){tryVerify(function(){return !!screen.report&&!screen.loading});verify(waitForRendering(screen))}
    function descendants(node){var all=[];for(var child of node.children){all.push(child);all=all.concat(descendants(child))};return all}
    function labels(){return descendants(screen).filter(function(item){return item.visible&&item.renderType===Text.NativeRendering&&typeof item.text==="string"})}
    function text(value){return labels().some(function(item){return item.text===value})}
    function item(name){var found=findChild(screen,name);verify(found!==null,name);return found}
    function click(name){var button=item(name);verify(button.visible&&button.enabled,name);button.forceActiveFocus();keyClick(Qt.Key_Space)}
    function reply(ok,data,message){var entry=service.pending[0];service.pending=service.pending.slice(1);entry.callback(ok,data||entry.data,message||"");wait(1)}
    function test_current_progress_does_not_read_history_until_explicit_tab(){
      screen=pageComponent.createObject(parent);verify(screen!==null)
      tryVerify(function(){return screen.page.items.length===24});compare(service.requests.map(function(r){return r.method}),["progress","level_board"])
      click("progress-history-tab");tryVerify(function(){return service.requests.length===3})
      compare(service.requests[2],{method:"level_history",args:{offset:0,limit:12}})
      verify(screen.historyOpen);wait(30);compare(service.requests.length,3)
      click("progress-subjects-tab");wait(20)
      verify(!screen.historyOpen);verify(service.requests.slice(3).every(function(r){return r.method!=="level_history"}))
    }
    function test_exact_readonly_page_size_and_navigation(){
      make();settle();compare(service.requests,[{method:"level_history",args:{offset:0,limit:12}}])
      click("history-older");settle();compare(service.requests[1],{method:"level_history",args:{offset:12,limit:12}})
      verify(!item("history-older").enabled);verify(item("history-newer").enabled)
      click("history-newer");settle();compare(service.requests[2].args,{offset:0,limit:12})
      compare(owner.openedIds.length,0)
    }
    function test_meaning_of_passing_burning_abandonment_and_unknown_duration(){
      make();settle();verify(text("Level passed"));verify(text("All assignments burned"));verify(text("Abandoned visit"));verify(text("Recorded status unknown"))
      compare(item("history-duration-16").text,"2 days 1h to passing")
      compare(item("history-duration-15").text,"2 days 1h to passing")
      compare(item("history-duration-14").text,"1 day before this visit ended")
      compare(item("history-duration-13").text,"Duration unavailable")
      verify(!item("history-duration-meter-13").visible)
      verify(text("Recorded dates need a refresh; elapsed time is unknown."))
      verify(labels().some(function(item){return item.text.indexOf("calendar time includes breaks and vacation")>=0}))
    }
    function test_native_dates_disclosure_keeps_milestones_distinct_and_full(){
      make();settle();verify(!text("First lesson started"));click("history-dates-15")
      compare(screen.expandedId,15);verify(text("Kanji passing target reached"));verify(text("All subjects burned"));verify(text("Visit ended"))
      compare(screen.dateText("2026-09-04T14:00:00Z"),"4 Sep 2026, 14:00");verify(text("4 Sep 2026, 14:00"))
      compare(screen.dateText(null),"Not recorded");compare(screen.dateText("bad"),"Not recorded")
      click("history-dates-15");compare(screen.expandedId,-1);verify(!text("All subjects burned"));compare(service.requests.length,1)
    }
    function test_safe_integer_resource_id_preserves_date_disclosure(){
      service.hold=true;make();compare(service.pending.length,1)
      var value=service.pending[0].data;value.items[0].id=4294967301
      reply(true,value);settle();click("history-dates-4294967301")
      compare(screen.expandedId,4294967301);verify(text("First lesson started"))
      click("history-dates-4294967301");compare(screen.expandedId,-1)
    }
    function test_hidden_closed_locked_unready_never_read_data(){return ["hidden","closed","locked","unready"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_hidden_closed_locked_unready_never_read(data){
      if(data.edge==="closed")owner.opened=false
      if(data.edge==="locked")service.locked=true
      if(data.edge==="unready")service.ready=false
      screen=historyComponent.createObject(parent,{visible:data.edge!=="hidden"});verify(screen!==null);wait(30)
      screen.fetch();compare(service.requests.length,0);compare(screen.report,null)
    }
    function test_late_reply_data(){return ["closed","hidden","locked","access","sync","epoch","vacation","level"].map(function(edge){return {tag:edge,edge:edge}})}
    function test_late_reply(data){
      service.hold=true;make();tryCompare(service,"requests",[{method:"level_history",args:{offset:0,limit:12}}])
      if(data.edge==="closed")owner.opened=false
      if(data.edge==="hidden")screen.visible=false
      if(data.edge==="locked")service.locked=true
      if(data.edge==="access")owner.contentAccess="other-account"
      if(data.edge==="sync")service.snapshot=Object.assign({},service.snapshot,{last_sync:"new"})
      if(data.edge==="epoch")service.snapshot=Object.assign({},service.snapshot,{session_epoch:"new"})
      if(data.edge==="vacation")service.snapshot=Object.assign({},service.snapshot,{vacation:true})
      if(data.edge==="level")service.snapshot=Object.assign({},service.snapshot,{level:4})
      reply(true);compare(screen.report,null);compare(screen.expandedId,-1)
      compare(service.requests.length,["closed","hidden","locked"].indexOf(data.edge)>=0?1:2)
    }
    function test_access_change_resets_page_and_dates_before_next_reply(){
      make();settle();click("history-older");settle();click("history-dates-4");service.hold=true;owner.contentAccess="other-account"
      compare(screen.offset,0);compare(screen.expandedId,-1);compare(screen.report,null)
      tryVerify(function(){return service.pending.length===1});compare(service.pending[0].args.offset,0)
    }
    function test_failure_releases_loading_and_retry_is_explicit(){
      service.hold=true;make();reply(false,null,"Authored history failure");verify(!screen.loading);compare(screen.error,"Authored history failure")
      wait(30);compare(service.requests.length,1);click("history-refresh");compare(service.requests.length,2)
    }
    function test_worker_restart_releases_unanswered_request_without_old_reply(){
      service.hold=true;make();compare(service.pending.length,1)
      service.ready=false;service.ready=true;wait(1)
      tryVerify(function(){return service.requests.length===2},300)
      var old=service.pending[0];service.pending=service.pending.slice(1);old.callback(true,old.data,"");wait(1)
      compare(screen.report,null);reply(true);verify(screen.report!==null)
    }
    function test_wrong_page_and_malformed_row_are_not_rendered_data(){return [{tag:"page",page:true},{tag:"row",page:false}]}
    function test_wrong_page_and_malformed_row_are_not_rendered(data){
      service.hold=true;make();var value=service.history({offset:0})
      if(data.page)value.offset=12;else value.items=[null]
      reply(true,value);compare(screen.report,null);verify(screen.error.length>0);verify(!screen.loading)
    }
    function test_demo_source_cannot_be_presented_as_a_real_account(){
      service.hold=true;make();var value=service.history({offset:0});value.source="Authored demo level progressions"
      reply(true,value);compare(screen.report,null);verify(screen.error.length>0)
    }
    function test_destroyed_view_discards_a_late_read_without_more_requests(){
      service.hold=true;make();screen.destroy();screen=null;wait(1);reply(true)
      compare(service.requests.length,1)
    }
    function test_unavailable_account_notice_and_demo_source_are_honest_data(){return [{tag:"unavailable",demo:false},{tag:"demo",demo:true}]}
    function test_unavailable_account_notice_and_demo_source_are_honest(data){
      service.hold=true;service.snapshot=Object.assign({},service.snapshot,{demo:data.demo});make();var value=service.history({offset:0})
      if(data.demo)value.source="Authored demo level progressions"
      else {value.status="unavailable";value.items=[];value.total=null;value.has_more=false;value.next_offset=null;value.cache_complete=false;value.partial=true;value.message="Cached account identity could not be verified. Older history may be missing."}
      reply(true,value);verify(screen.report!==null);compare(screen.error,"");verify(text(value.message))
    }
    __PALETTE_CHECKS__
    function test_narrow_live_stock_palettes_data(){return paletteData()}
    function test_narrow_live_stock_palettes(data){
      make();screen.width=290;settle();click("history-dates-15");var saved=JSON.stringify(screen.report);var reads=service.requests.length
      applyPalette(data);checkText(screen,data.tag+" history");checkButtons(screen,data.tag+" history")
      for(var label of labels()){verify(!label.truncated,label.text);verify(label.contentWidth<=label.width+1,"Fits: "+label.text)}
      for(var id of [16,15,14]){var meter=item("history-duration-meter-"+id);verify(Theme.contrast(meter.children[0].color,meter.color)>=3,data.tag+" calendar duration")}
      compare(JSON.stringify(screen.report),saved);compare(service.requests.length,reads);compare(screen.expandedId,15)
    }
  }
}
'''


def source():
    prefix = progress.QML.split("  TestCase {", 1)[0]
    prefix = prefix.replace('import "qml" as Kani', 'import "qml" as Kani\nimport "qml/Theme.mjs" as Theme')
    prefix = prefix.replace('  QtObject {\n    id: service',
        '  Component { id: historyComponent; Kani.LevelHistory { width:380; controller:owner } }\n  QtObject {\n    id: service', 1)
    prefix = prefix.replace('    function data(method,args) {', HISTORY_DATA + '\n    function data(method,args) {\n      if(method==="level_history")return history(args)')
    checks = palettes.CHECKS.replace("__PALETTES__", palettes.json.dumps(palettes.palettes()))
    return prefix + TESTS.replace("__PALETTE_CHECKS__", checks)


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    for name in ("Progress", "SrsExplorer", "LevelHistory", "LevelProgress"):
        shutil.copyfile(ROOT / "qml" / (name + ".qml"), directory / "qml" / (name + ".qml"))
    palettes.pure_native_style(directory)
    (directory / "tst_LevelHistory.qml").write_text(source())


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Qt and native controls required")
class LevelHistoryUiTests(unittest.TestCase):
    def test_actual_level_history_and_lazy_progress_tab(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-level-history-ui-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=40, env={**os.environ,
                    "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic",
                    "TZ": "UTC", "LC_ALL": "C.UTF-8"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)


if __name__ == "__main__":
    unittest.main()
