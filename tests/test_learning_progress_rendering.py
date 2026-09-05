"""Real progress layouts with authored asynchronous replies and native Qt controls."""
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
  width: 800; height: 2400; color: Color.background
  property var screen: null
  Component { id: pageComponent; Kani.Progress { width: 380; controller: owner } }
  Kani.LevelProgress { id: home; x: 410; width: 350; progress: service.current(); onExplore: owner.explored++ }
  QtObject {
    id: service
    property bool ready: true
    property bool locked: false
    property bool hold: false
    property bool protectedWord: false
    property bool malformed: false
    property var requests: []
    property var pending: []
    property var snapshot: ({level: 2, max_level: 60, last_sync: "fixture", session_revision: 1, session_epoch: "fixture", pending: 0, attention: 0})
    function current() {
      return {level:2,accessible:true,complete:true,total:30,passed:24,required:27,remaining:3,fraction:24/27,
        final_level:false,elapsed_days:4,pending:1,attention:0,message:"3 more kanji to pass to reach the level-up target."}
    }
    function status(stage) {
      return {stage:stage,stage_name:"Apprentice "+stage,group:"apprentice",label:"Apprentice "+stage,
        next_review_at:"2026-09-05T18:00:00Z",due:false,passed:false,pending:false,attention:false}
    }
    function card(id,level,type,nested) {
      var blocked=protectedWord && !nested
      return {id:id,level:level,type:type,characters:nested?"土":"山",meaning:blocked?"":"Authored <b>literal</b> word "+id,
        can_open:!blocked,spoilers_hidden:blocked,status:status(3),required:nested,
        prerequisites:nested||blocked?[]:[card(9000,1,"radical",true)],prerequisites_complete:true}
    }
    function data(method,args) {
      if(method==="progress") return {current:current(),last_sync:"2026-09-05T12:00:00Z",
        distribution:{complete:true,total:11,groups:[{key:"apprentice",label:"Apprentice",count:8},{key:"guru",label:"Guru",count:3}]}}
      var items=[]
      for(var i=0;i<Math.min(args.limit,50-args.offset);++i) items.push(card(args.offset+i+1,args.level,args.subject_type||"kanji",false))
      return {level:args.level,subject_type:args.subject_type,offset:args.offset,limit:args.limit,total:50,total_complete:true,complete:true,
        items:malformed?[null]:items,has_more:args.offset+args.limit<50,next_offset:args.offset+args.limit<50?args.offset+args.limit:null}
    }
    function request(method,args,callback) {
      requests=requests.concat([{method:method,args:args}])
      var entry={method:method,args:args,callback:callback,data:data(method,args)}
      if(hold) pending=pending.concat([entry]); else callback(true,entry.data,"")
    }
    function reply() { var entry=pending[0];pending=pending.slice(1);entry.callback(true,entry.data,"") }
  }
  QtObject {
    id: owner
    property var service: null
    property bool opened: true
    property string contentAccess: "authored-account"
    property var openedIds: []
    property int explored: 0
    readonly property var snapshot: service ? service.snapshot : ({})
    property var progressNavigation: ({})
    function showProgressSubject(id) { openedIds=openedIds.concat([id]) }
    function call(method,args,callback) { if(method!=="sync") throw new Error("Unexpected mutation"); if(callback)callback(true,{}) }
  }
  TestCase {
    name: "LearningProgressRendering"; when: windowShown
    function make() { screen=pageComponent.createObject(parent);verify(screen!==null);return screen }
    function settle() { tryVerify(function(){return screen.page.items.length>0 && !screen.loading},1000);verify(waitForRendering(screen)) }
    function descendants(item) {
      var items=[]
      for(var i=0;i<item.children.length;++i){items.push(item.children[i]);items=items.concat(descendants(item.children[i]))}
      return items
    }
    function labels(item) { return descendants(item).filter(function(child){return child.renderType===Text.NativeRendering && child.text!==undefined}) }
    function init() {
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;service.hold=false;service.protectedWord=false;service.malformed=false
      service.requests=[];service.pending=[]
      service.snapshot={level:2,max_level:60,last_sync:"fixture",session_revision:1,session_epoch:"fixture",pending:0,attention:0}
      owner.service=service;owner.opened=true;owner.contentAccess="authored-account";owner.openedIds=[];owner.explored=0;owner.progressNavigation=({})
      Color.background="#ffffff";Color.foreground="#202020";Color.accent="#006699"
      home.progress=service.current();home.width=350
    }
    function cleanup() { if(screen) screen.destroy();screen=null;wait(1) }
    function test_home_card_uses_required_threshold_and_separates_pending() {
      compare(findChild(home,"levelProgressCount").text,"24 / 27")
      compare(findChild(home,"levelPassingMeter").value,24/27)
      verify(findChild(home,"levelPendingProgress").text.indexOf("1 waiting to sync")>=0)
      findChild(home,"exploreLevel").clicked();compare(owner.explored,1)
      var next=service.current();next.passed=27;next.fraction=1;home.progress=next
      compare(findChild(home,"levelPassingMeter").value,1)
    }
    function test_incomplete_access_and_final_level_remain_honest() {
      var next=service.current();next.complete=false;next.required=null;next.fraction=null;home.progress=next
      compare(findChild(home,"levelProgressCount").text,"—")
      compare(findChild(home,"levelPassingMeter").value,0)
      next=service.current();next.accessible=false;home.progress=next
      verify(!findChild(home,"exploreLevel").enabled)
      next=service.current();next.level=60;next.final_level=true;home.progress=next
      verify(findChild(home,"levelProgressHeading").text.indexOf("Final level")>=0)
    }
    function test_initial_page_has_one_pair_of_readonly_requests() {
      make();settle();compare(service.requests.length,2)
      compare(service.requests[0].method,"progress");compare(service.requests[1].method,"level_board")
      compare(service.requests[1].args.limit,24);compare(screen.page.items.length,24)
      wait(30);compare(service.requests.length,2)
      verify(labels(screen).some(function(item){return item.text==="Authored <b>literal</b> word 1" && item.textFormat===Text.PlainText}))
      verify(labels(screen).some(function(item){return item.text.indexOf("土 · Next review")===0}))
    }
    function test_type_level_and_page_navigation_load_expected_bounded_queries() {
      make();settle();screen.chooseType("radical");settle()
      compare(screen.page.subject_type,"radical");compare(screen.page.items[0].type,"radical")
      screen.changePage(24);settle();compare(screen.page.offset,24);compare(screen.page.items[0].id,25)
      screen.chooseLevel(1);settle();compare(screen.page.level,1);compare(screen.page.offset,0)
      screen.openSubject(1);screen.openSubject(9000);compare(owner.openedIds,[1,9000])
      screen.openSubject(99999);compare(owner.openedIds.length,2)
    }
    function test_filter_and_page_changes_reuse_the_same_overview() {
      make();settle();screen.chooseType("vocabulary");settle()
      screen.changePage(24);settle();screen.chooseLevel(1);settle()
      compare(service.requests.map(function(request){return request.method}),["progress","level_board","level_board","level_board","level_board"])
      service.snapshot=Object.assign({},service.snapshot,{syncing:true,status:"syncing"})
      settle();compare(service.requests.slice(-2).map(function(request){return request.method}),["progress","level_board"])
    }
    function test_old_reply_cannot_clear_newer_loading_or_overwrite_its_page() {
      make();settle();service.hold=true
      screen.chooseType("radical");tryVerify(function(){return service.pending.length===1})
      screen.chooseType("vocabulary");tryVerify(function(){return service.pending.length===2})
      verify(screen.loading);service.reply();verify(screen.loading);compare(screen.page.items.length,0)
      service.reply();settle();compare(screen.page.subject_type,"vocabulary")
    }
    function test_saved_board_selection_restores_after_detail_view_is_destroyed() {
      make();settle();screen.chooseLevel(1);settle();screen.chooseType("radical");settle()
      screen.changePage(24);settle();var saved=JSON.stringify(owner.progressNavigation)
      screen.destroy();screen=null;wait(1);service.requests=[]
      make();settle();compare(screen.page.offset,24);compare(screen.page.subject_type,"radical");compare(screen.page.level,1)
      compare(JSON.stringify(owner.progressNavigation),saved)
      compare(service.requests.map(function(request){return request.method}),["progress","level_board"])
    }
    function test_protected_subjects_have_no_answer_text_or_open_action() {
      service.protectedWord=true;make();settle()
      verify(screen.page.items.every(function(item){return !item.can_open && item.meaning===""}))
      screen.openSubject(1);compare(owner.openedIds.length,0)
      verify(!labels(screen).some(function(item){return item.text.indexOf("Authored <b>")>=0}))
      verify(labels(screen).some(function(item){return item.text==="Answer kept for your saved session"}))
    }
    function test_late_overview_after_close_cannot_request_board_or_publish() {
      service.hold=true;make();tryCompare(service,"pending",service.pending,10)
      tryVerify(function(){return service.pending.length===1});owner.opened=false
      service.reply();wait(20);compare(service.requests.length,1);compare(screen.overview,null);compare(screen.page.items.length,0)
      service.hold=false;owner.opened=true;settle();compare(service.requests.length,3)
    }
    function test_late_board_after_filter_change_is_discarded_and_followed_once() {
      service.hold=true;make();tryVerify(function(){return service.pending.length===1});service.reply()
      compare(service.pending.length,1);compare(service.pending[0].method,"level_board")
      screen.chooseType("vocabulary");service.reply();compare(screen.page.items.length,0)
      service.hold=false;settle();compare(screen.page.subject_type,"vocabulary")
      compare(service.requests.length,3)
    }
    function test_access_and_saved_session_changes_clear_answers_immediately() {
      make();settle();service.hold=true
      owner.contentAccess="different-account";compare(screen.page.items.length,0)
      tryVerify(function(){return service.pending.length===1});service.hold=false;service.reply();settle()
      service.protectedWord=true
      service.snapshot=Object.assign({},service.snapshot,{session_revision:2})
      compare(screen.page.items.length,0);settle();verify(screen.page.items[0].spoilers_hidden)
    }
    function test_locked_and_unready_surface_performs_no_reads() {
      service.locked=true;make();wait(30);compare(service.requests.length,0)
      service.ready=false;service.locked=false;wait(30);compare(service.requests.length,0)
      service.ready=true;settle();compare(service.requests.length,2)
    }
    function test_malformed_reply_is_rejected_without_creating_cards() {
      service.malformed=true;make();tryVerify(function(){return screen.notice.length>0})
      compare(screen.page.items.length,0);verify(!screen.loading)
    }
    function test_long_narrow_content_and_live_palette_change() {
      make();settle();screen.width=320;home.width=300;verify(waitForRendering(screen))
      var before=findChild(home,"levelProgressHeading").color.toString()
      Color.background="#151515";Color.foreground="#dddddd";Color.accent="#777777"
      verify(waitForRendering(home));verify(findChild(home,"levelProgressHeading").color.toString()!==before)
      for(var i=0;i<labels(home).length;++i) {
        var text=labels(home)[i]
        if(!text.visible||!text.text.length)continue
        verify(text.contentWidth<=text.width+1,"Home text fits: "+text.text)
        verify(!text.truncated,"Home text is complete")
      }
      verify(labels(screen).every(function(item){return !item.visible || !item.text.length || item.textFormat===Text.PlainText}))
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class LearningProgressRenderingTests(unittest.TestCase):
    def test_actual_progress_components(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-progress-ui-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("LevelProgress.qml", "Progress.qml", "SrsExplorer.qml", "JapaneseText.qml", "LevelHistory.qml", "Card.qml", "Label.qml", "Theme.mjs"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text('import QtQuick\nimport QtQuick.Controls\nButton {\n'
                'property bool selected: false\nproperty string accessibleName: text\n'
                'property color surfaceColor: "white"\nproperty color color: "transparent"\nproperty color textColor: "black"\n'
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
            (directory / "tst_Progress.qml").write_text(QML)
            process = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=45,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertNotIn("QWARN", process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
