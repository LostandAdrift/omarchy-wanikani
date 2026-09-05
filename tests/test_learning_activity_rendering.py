"""Production Activity QML, fixture RPC and native-control substitutes only."""
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
import "qml"

Item {
  width: 700
  height: 2600
  QtObject {
    id: backend
    property bool ready: true
    property bool locked: false
    property var requests: []
    function request(method, args, callback) { requests = requests.concat([{method:method,args:args,callback:callback}]) }
  }
  QtObject {
    id: owner
    property var service: backend
    property bool opened: true
    property string contentAccess: "account-a"
    property var snapshot: ({state_revision:1,session_revision:1,max_level:60})
    property var routes: []
    property var subjects: []
    function navigate(view) { routes = routes.concat([view]) }
    function showSubject(id) { subjects = subjects.concat([id]) }
  }
  LearningActivity { id: page; controller: owner; width: 460 }
  TestCase {
    name: "LearningActivity"
    when: windowShown
    function metrics(number) {
      return {subject_completions:{reviews:number,lessons:2,practice:1},sessions_completed:{reviews:1,lessons:1,practice:0},
        listening_ratings:{remembered:2,again:1,skipped:1},listening_sessions_completed:1,typo_corrections:1}
    }
    function report() {
      var daily = []
      for (var i=1;i<=30;i++)
        daily.push(Object.assign({day:"2026-08-"+(i<10?"0":"")+i},metrics(i)))
      return {schema_version:1,scope:"recorded_on_this_device",demo:false,windows:{"7":metrics(7),"30":metrics(30)},daily:daily,
        current_submissions:{waiting:3,attention:1,confirmed:12,archived:0},
        difficulties:[{id:2,type:"kanji",level:2,label:"山",meaning_mistakes:1,reading_mistakes:2,can_open:true}],
        suggestions:[{code:"review_five",label:"Review five",reason:"Choose when to begin.",route:{view:"review-overview",limit:5},effect:"navigation_only"}]}
    }
    function init() {
      owner.opened=false
      page.visible=true
      backend.ready=true
      backend.locked=false
      owner.contentAccess="account-a"
      owner.snapshot={state_revision:1,session_revision:1,max_level:60}
      page.days=7
      page.width=460
      owner.routes=[]
      owner.subjects=[]
      backend.requests=[]
      owner.opened=true
    }
    function items(item) {
      var result=[item]
      for(var i=0;i<item.children.length;i++) result=result.concat(items(item.children[i]))
      return result
    }
    function action(text) {
      var found=items(page).filter(function(item){return item.objectName==="fixture-action"&&item.text===text})
      compare(found.length,1,text)
      return found[0]
    }
    function load(value) {
      tryVerify(function(){return backend.requests.length===1})
      compare(backend.requests[0].method,"learning_insights")
      compare(JSON.stringify(backend.requests[0].args),"{}")
      backend.requests[0].callback(true,value||report())
      verify(page.report!==null)
    }
    function test_dictation_counts_are_distinct_visible_and_included_in_daily_activity() {
      var value=report()
      var periods=[value.windows["7"],value.windows["30"]].concat(value.daily)
      for(var row of periods) {
        row.subject_completions={reviews:0,lessons:0,practice:0}
        row.listening_ratings={remembered:0,again:0,skipped:0}
        row.dictation_ratings={matched:3,again:1,skipped:1}
        row.dictation_sessions_completed=1
      }
      load(value)
      verify(!page.empty)
      compare(page.dayTotal(page.rows[0]),5)
      verify(page.dayText(page.rows[0]).indexOf("5 kana dictation results")>0)
      var summary=findChild(page,"dictationActivitySummary")
      verify(summary.visible)
      verify(summary.text.indexOf("3 matched the recording")>0)
      verify(summary.text.indexOf("1 to revisit")>0)
      verify(summary.text.indexOf("Undone results are excluded")>0)
    }
    function test_legacy_history_does_not_invent_dictation_and_malformed_additions_reject() {
      load()
      verify(!findChild(page,"dictationActivitySummary").visible)
      for(var invalid of [{matched:-1,again:0,skipped:0},{matched:"private",again:0,skipped:0},null]) {
        var value=report()
        value.windows["7"].dictation_ratings=invalid
        value.windows["7"].dictation_sessions_completed=1
        verify(!page.valid(value))
      }
      var missing=report()
      missing.windows["7"].dictation_ratings={matched:0,again:0,skipped:0}
      verify(!page.valid(missing))
    }
    function test_initial_read_is_lazy_and_period_switch_is_local() {
      compare(backend.requests.length,0)
      load()
      compare(page.rows.length,7)
      action("30 days").clicked()
      compare(page.rows.length,30)
      compare(page.totals.subject_completions.reviews,30)
      wait(180)
      compare(backend.requests.length,1)
    }
    function test_closed_locked_unready_and_invisible_do_no_reads() {
      owner.opened=false
      owner.snapshot={state_revision:2,session_revision:2}
      wait(180)
      compare(backend.requests.length,0)
      owner.opened=true
      backend.locked=true
      wait(180)
      compare(backend.requests.length,0)
      backend.locked=false
      backend.ready=false
      wait(180)
      compare(backend.requests.length,0)
      backend.ready=true
      page.visible=false
      wait(180)
      compare(backend.requests.length,0)
      page.visible=true
      tryVerify(function(){return backend.requests.length===1})
    }
    function test_close_and_reopen_rejects_old_reply_without_clearing_new_loading() {
      tryVerify(function(){return backend.requests.length===1})
      owner.opened=false
      owner.opened=true
      tryVerify(function(){return backend.requests.length===2})
      backend.requests[0].callback(true,report())
      compare(page.report,null)
      verify(page.loading)
      backend.requests[1].callback(true,report())
      verify(page.report!==null)
      verify(!page.loading)
    }
    function test_multiple_snapshot_changes_coalesce_and_clear_difficulties_immediately() {
      load()
      owner.snapshot={state_revision:2,session_revision:2}
      compare(page.report,null)
      owner.snapshot={state_revision:3,session_revision:3}
      owner.snapshot={state_revision:4,session_revision:4}
      tryVerify(function(){return backend.requests.length===2})
      backend.requests[1].callback(true,report())
      wait(180)
      compare(backend.requests.length,2)
    }
    function test_inflight_access_change_rejects_old_content_and_reads_once_after() {
      tryVerify(function(){return backend.requests.length===1})
      owner.contentAccess="account-b"
      backend.requests[0].callback(true,report())
      compare(page.report,null)
      tryVerify(function(){return backend.requests.length===2})
      var next=report()
      next.difficulties=[]
      backend.requests[1].callback(true,next)
      compare(page.report.difficulties.length,0)
    }
    function test_safe_routes_and_subject_buttons_use_current_report_only() {
      load()
      action("Open reviews").clicked()
      compare(JSON.stringify(owner.routes),'["review-overview"]')
      action("Open subject").clicked()
      compare(JSON.stringify(owner.subjects),'[2]')
      var stale=page.report.difficulties[0]
      owner.snapshot={state_revision:2,session_revision:2}
      page.openDifficulty(stale)
      compare(owner.subjects.length,1)
    }
    function test_empty_history_is_honest_and_current_confirmation_stays_separate() {
      var value=report()
      for(var key in value.windows) {
        value.windows[key]={subject_completions:{reviews:0,lessons:0,practice:0},sessions_completed:{reviews:0,lessons:0,practice:0},
          listening_ratings:{remembered:0,again:0,skipped:0},listening_sessions_completed:0,typo_corrections:0}
      }
      load(value)
      verify(findChild(page,"activityEmpty").visible)
      var text=findChild(page,"activitySubmissions").text
      verify(text.indexOf("3 waiting")>=0)
      verify(text.indexOf("12 confirmed")>=0)
      action("30 days").clicked()
      compare(findChild(page,"activitySubmissions").text,text)
    }
    function test_failed_read_has_explicit_retry_without_automatic_loop() {
      tryVerify(function(){return backend.requests.length===1})
      backend.requests[0].callback(false,null,"Authored read failure")
      compare(page.report,null)
      compare(findChild(page,"activityNotice").text,"Authored read failure")
      wait(180)
      compare(backend.requests.length,1)
      action("Refresh activity").clicked()
      tryVerify(function(){return backend.requests.length===2})
    }
    function test_malformed_reply_cannot_render_unbounded_or_unsafe_routes() {
      tryVerify(function(){return backend.requests.length===1})
      var value=report()
      value.suggestions[0].route.view="reviews"
      backend.requests[0].callback(true,value)
      compare(page.report,null)
      verify(page.notice.length>0)
      verify(!page.valid(Object.assign(report(),{daily:[]})))
      value=report()
      value.windows["7"].subject_completions.reviews=-1
      verify(!page.valid(value))
    }
    function test_days_are_available_as_plain_accessible_text() {
      load()
      var days=items(page).filter(function(item){return item.objectName==="activityDay"})
      compare(days.length,7)
      var text=items(days[0]).filter(function(item){return item.text!==undefined&&item.text.indexOf("2026-")===0})[0]
      verify(text!==undefined)
      compare(text.Accessible.name,text.text)
      verify(text.text.indexOf("listening ratings")>0)
    }
    function test_keyboard_focus_starts_with_period_control() {
      load()
      page.focusInput()
      tryVerify(function(){return action("7 days").activeFocus})
      keyClick(Qt.Key_Tab)
      verify(action("30 days").activeFocus)
    }
    function test_narrow_long_labels_wrap_without_widening_controls() {
      var value=report()
      value.difficulties[0].label="山川".repeat(50)
      value.suggestions[0].label="A longer readable suggestion for the learner ".repeat(3)
      value.suggestions[0].reason="Choose this at your own pace. ".repeat(6)
      page.width=320
      load(value)
      wait(30)
      for(var item of items(page)) {
        if(!item.visible||item.width<=0||item===page) continue
        var point=item.mapToItem(page,0,0)
        verify(point.x>=-1&&point.x+item.width<=321,String(item.text||item.objectName||item)+" exceeds 320px")
        if(item.paintedWidth!==undefined&&item.text&&item.textFormat!==undefined)
          verify(item.paintedWidth<=item.width+1,"Text clipped: "+item.text)
      }
      verify(action("Open reviews").width<=320)
      verify(action("Open subject").width<=320)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class LearningActivityRenderingTests(unittest.TestCase):
    def test_real_component_with_authored_rpc(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-learning-activity-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("LearningActivity.qml", "Label.qml", "Card.qml", "Theme.mjs"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text('import QtQuick.Controls\nButton {\n'
                ' objectName: "fixture-action"\n property bool selected: false\n'
                ' property string accessibleName: text\n property string accessibleHint: ""\n}\n')
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' function space(value) { return value }\n readonly property int cornerRadius: 12\n'
                ' readonly property var font: ({family:"Sans",body:14,bodySmall:12,title:20})\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' property color background: "#ffffff"\n property color foreground: "#202020"\n'
                ' property color accent: "#006699"\n property color urgent: "#990000"\n}\n')
            (directory / "tst_LearningActivity.qml").write_text(QML)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=35,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
