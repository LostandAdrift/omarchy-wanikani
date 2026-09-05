"""Exercise the actual lesson/review overview with authored data and inert IO."""
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
  width: 720
  height: 4800
  QtObject {
    id: backend
    property bool ready: true
    property bool locked: false
    property bool hold: false
    property var requests: []
    property var pending: []
    property var snapshot: ({})
    property var cards: []
    function result(method, args) {
      var counts = {radical:0,kanji:0,vocabulary:0,kana_vocabulary:0}
      cards.forEach(function (card) { counts[card.type]++ })
      if (method === "lesson_catalogue") {
        var all = cards.filter(function (card) { return args.subject_type === "all" || card.type === args.subject_type })
        return {items:all.slice(args.offset,args.offset+args.limit),counts:counts,total:all.length,
          subject_type:args.subject_type,offset:args.offset,limit:args.limit,has_more:args.offset+args.limit<all.length,
          next_offset:args.offset+args.limit<all.length?args.offset+args.limit:null,complete:true,message:"",saved_session:null}
      }
      var selected = args.subject_ids ? args.subject_ids.map(function (id) { return cards.filter(function (card) { return card.id === id })[0] })
        : cards.filter(function (card) { return card.ready }).slice(0,args.limit)
      return {batch:selected,counts:counts,complete:true,resume_required:false,saved_session:null,message:""}
    }
    function request(method,args,callback) {
      requests = requests.concat([{method:method,args:args}])
      var reply = result(method,args)
      if (hold)
        pending = pending.concat([{callback:callback,reply:reply}])
      else
        Qt.callLater(function () { callback(true,reply,"") })
    }
  }
  QtObject {
    id: owner
    property var service: backend
    property var snapshot: backend.snapshot
    property bool opened: false
    property bool busy: false
    property string contentAccess: "authored-account"
    property var starts: []
    property var routes: []
    function begin(mode,limit,ids) { starts = starts.concat([{mode:mode,limit:limit,ids:ids}]) }
    function navigate(route) { routes = routes.concat([route]) }
  }
  StudyOverview { id: screen; controller: owner; mode: "lessons"; width: 460 }
  TestCase {
    name: "LessonOverview"
    when: windowShown
    function card(id, type, ready) {
      return {id:id,type:type || "vocabulary",characters:type === "radical" ? null : id === 1 ? "火山" : "山",
        meanings:[id === 1 ? "volcano" : "Authored lesson " + id],images:[],level:1,ready:ready !== false,
        cache_note:ready === false?"Required radical image is not cached":"Ready offline",prerequisites:[]}
    }
    function baseSnapshot() {
      return {max_level:3,lessons:30,reviews:17,vacation:false,status:"ready",last_sync:"one",session_epoch:"one",
        session_revision:0,pending:0,attention:0,saved_sessions:{reviews:null,lessons:null,practice:null}}
    }
    function init() {
      owner.opened = false
      for (var i = 0; i < backend.pending.length; i++) backend.pending[i].callback(false,null,"discarded")
      backend.pending = []
      backend.hold = false
      backend.ready = true
      backend.locked = false
      backend.cards = []
      for (var id = 1; id <= 30; id++)
        backend.cards = backend.cards.concat([card(id,["vocabulary","kanji","radical","kana_vocabulary"][(id-1)%4],id!==3)])
      backend.snapshot = baseSnapshot()
      owner.contentAccess = "authored-account"
      owner.busy = false
      owner.starts = []
      owner.routes = []
      screen.visible = true
      screen.mode = "lessons"
      screen.width = 460
      screen.subjectType = "all"
      screen.batch = 5
      screen.invalidate(true)
      backend.requests = []
      owner.opened = true
    }
    function cleanup() { owner.opened = false }
    function settle() { tryVerify(function () { return !screen.dirty && !screen.fetching && !screen.loading }) }
    function previewSettled() { tryVerify(function () { return !screen.previewing && !screen.previewFetching }) }
    function items(parent) {
      var result = [parent]
      for (var i = 0; i < parent.children.length; i++) result = result.concat(items(parent.children[i]))
      return result
    }
    function action(text) {
      var matches = items(screen).filter(function (item) { return item.objectName === "fixture-action" && item.text === text && item.visible })
      compare(matches.length,1,text)
      return matches[0]
    }
    function test_readonly_catalogue_and_explicit_counts() {
      settle()
      compare(backend.requests.length,1)
      compare(backend.requests[0].method,"lesson_catalogue")
      compare(backend.requests[0].args.limit,12)
      compare(screen.catalogue.items.length,12)
      compare(screen.selectedIds.length,0)
      verify(!findChild(screen,"start-selected-lessons").enabled)
      action("Radicals · 7")
      action("Kanji · 8")
      action("Vocabulary · 8")
      action("Kana vocabulary · 7")
      compare(owner.starts.length,0)
    }
    function test_cached_image_radical_uses_original_catalogue_array() {
      var radical = card(91,"radical",true)
      radical.images = [String(Qt.resolvedUrl("radical.svg"))]
      backend.cards = [radical]
      settle()
      var image = findChild(screen,"radicalImage")
      verify(image !== null)
      tryCompare(image,"status",Image.Ready)
      compare(String(image.source),String(Qt.resolvedUrl("radical.svg")))
      var reads = backend.requests.length
      action("Add to lessons").clicked()
      previewSettled()
      compare(screen.selectedIds,[91])
      compare(owner.starts.length,0)
      compare(backend.requests.length,reads+1)
      verify(backend.requests.every(function (request) { return request.method !== "media" }))
      backend.cards = [card(92,"radical",false)]
      screen.loadPage(0)
      settle()
      var missing = findChild(screen,"radicalImage")
      verify(missing !== null)
      compare(String(missing.source),"")
      compare(missing.status,Image.Null)
      verify(!action("Add to lessons").enabled)
      compare(owner.starts.length,0)
    }
    function test_recommended_preview_then_separate_start() {
      settle()
      action("Preview recommended").clicked()
      previewSettled()
      compare(screen.selectedIds,[1,2,4,5,6])
      compare(owner.starts.length,0)
      var button = findChild(screen,"start-selected-lessons")
      verify(button.enabled)
      button.forceActiveFocus()
      keyClick(Qt.Key_Space)
      compare(owner.starts.length,1)
      compare(owner.starts[0].mode,"lessons")
      compare(owner.starts[0].ids,[1,2,4,5,6])
      compare(owner.starts[0].limit,5)
    }
    function test_selection_order_pagination_and_debounced_validation() {
      settle()
      screen.toggleSubject(backend.cards[1])
      screen.toggleSubject(backend.cards[0])
      previewSettled()
      compare(backend.requests.filter(function (request) { return request.method === "lesson_preview" }).length,1)
      compare(screen.selectedIds,[2,1])
      action("More lessons").clicked()
      settle()
      compare(screen.offset,12)
      screen.toggleSubject(screen.catalogue.items[0])
      previewSettled()
      compare(screen.selectedIds,[2,1,13])
      screen.startLessons()
      compare(owner.starts[0].ids,[2,1,13])
      action("Radicals · 7").clicked()
      settle()
      compare(screen.offset,0)
      verify(screen.catalogue.items.every(function (item) { return item.type === "radical" }))
      compare(screen.selectedIds,[2,1,13])
    }
    function test_unavailable_image_and_twenty_subject_bound() {
      settle()
      screen.toggleSubject(backend.cards[2])
      compare(screen.selectedIds.length,0)
      for (var i = 0; i < backend.cards.length; i++) screen.toggleSubject(backend.cards[i])
      compare(screen.selectedIds.length,20)
      previewSettled()
      screen.startLessons()
      compare(owner.starts[0].ids.length,20)
      screen.toggleSubject(screen.selectedItems[0])
      compare(screen.selectedIds.length,19)
      verify(!screen.previewReady)
      screen.clearSelection()
      compare(screen.selectedIds.length,0)
      verify(!screen.previewReady)
    }
    function test_saved_lesson_replaces_chooser_without_reads() {
      owner.opened = false
      backend.requests = []
      backend.snapshot = Object.assign({},baseSnapshot(),{saved_sessions:{reviews:{id:"r"},lessons:{id:"l",phase:"feedback",completed:1,total:5},practice:null}})
      owner.opened = true
      wait(230)
      compare(backend.requests.length,0)
      verify(!findChild(screen,"start-selected-lessons").visible)
      action("Resume lessons →").clicked()
      compare(owner.starts.length,1)
      compare(owner.starts[0].mode,"lessons")
      verify(owner.starts[0].ids === undefined)
    }
    function test_preview_race_finds_saved_lesson() {
      settle()
      backend.hold = true
      screen.queuePreview(true)
      tryVerify(function () { return backend.pending.length === 1 })
      backend.pending[0].callback(true,{resume_required:true,saved_session:{id:"saved",phase:"lesson",completed:0,total:5}},"")
      compare(screen.saved.id,"saved")
      compare(screen.selectedIds.length,0)
      verify(!screen.previewReady)
      action("Resume lessons →")
    }
    function test_hidden_closed_locked_unready_do_not_read_or_accept_late_preview() {
      settle()
      for (var state of ["hidden","closed","locked","unready"]) {
        backend.hold = true
        screen.queuePreview(true)
        tryVerify(function () { return backend.pending.length > 0 })
        var request = backend.pending[backend.pending.length-1]
        if (state === "hidden") screen.visible = false
        if (state === "closed") owner.opened = false
        if (state === "locked") backend.locked = true
        if (state === "unready") backend.ready = false
        var count = backend.requests.length
        screen.loadPage(0)
        screen.queuePreview(true)
        request.callback(true,request.reply,"")
        wait(200)
        compare(backend.requests.length,count)
        compare(screen.selectedIds.length,0)
        backend.hold = false
        backend.pending = []
        screen.visible = true
        owner.opened = true
        backend.locked = false
        backend.ready = true
        settle()
      }
    }
    function test_account_and_graded_context_invalidate_old_cards() {
      settle()
      backend.hold = true
      screen.queuePreview(true)
      tryVerify(function () { return backend.pending.length === 1 })
      var request = backend.pending[0]
      owner.contentAccess = "different-account"
      compare(screen.catalogue.items.length,0)
      request.callback(true,request.reply,"")
      compare(screen.selectedIds.length,0)
      backend.hold = false
      settle()
      screen.toggleSubject(backend.cards[0])
      previewSettled()
      backend.snapshot = Object.assign({},backend.snapshot,{session_revision:1})
      compare(screen.selectedIds.length,0)
      compare(screen.catalogue.items.length,0)
    }
    function test_reopen_revalidates_preserved_selection() {
      settle()
      screen.toggleSubject(backend.cards[0])
      previewSettled()
      verify(screen.previewReady)
      owner.opened = false
      compare(screen.selectedIds,[1])
      verify(!screen.previewReady)
      var count = backend.requests.length
      wait(220)
      compare(backend.requests.length,count)
      owner.opened = true
      settle()
      previewSettled()
      verify(screen.previewReady)
      compare(screen.selectedIds,[1])
      compare(backend.requests.length,count+2)
    }
    function test_stale_selection_and_malformed_catalogue_are_rejected() {
      settle()
      backend.hold = true
      screen.queuePreview(true)
      tryVerify(function () { return backend.pending.length === 1 })
      var old = backend.pending[0]
      screen.toggleSubject(backend.cards[1])
      old.callback(true,old.reply,"")
      compare(screen.selectedIds,[2])
      tryVerify(function () { return backend.pending.length === 2 })
      backend.pending[1].callback(true,backend.pending[1].reply,"")
      verify(screen.previewReady)
      screen.loadPage(0)
      tryVerify(function () { return backend.pending.length === 3 })
      backend.pending[2].callback(true,{offset:0,subject_type:"all",items:[],counts:null},"")
      compare(screen.catalogue.items.length,0)
      verify(screen.notice.indexOf("could not be loaded")>=0)
      backend.pending = []
    }
    function test_failed_preview_keeps_selection_but_cannot_start() {
      settle()
      backend.hold = true
      screen.toggleSubject(backend.cards[0])
      tryVerify(function () { return backend.pending.length === 1 })
      backend.pending[0].callback(false,null,"This lesson is now locked")
      compare(screen.selectedIds,[1])
      compare(screen.selectionNotice,"This lesson is now locked")
      verify(!screen.previewReady)
      screen.startLessons()
      compare(owner.starts.length,0)
    }
    function test_reviews_keep_batch_flow_and_independent_resume() {
      owner.opened = false
      screen.mode = "reviews"
      backend.requests = []
      owner.opened = true
      wait(230)
      compare(backend.requests.length,0)
      action("10").clicked()
      action("Review 10 subjects →").clicked()
      compare(owner.starts[0].mode,"reviews")
      compare(owner.starts[0].limit,10)
      backend.snapshot = Object.assign({},baseSnapshot(),{saved_sessions:{reviews:{id:"review",completed:2,total:5,phase:"question"},lessons:{id:"lesson"},practice:null}})
      action("Resume reviews →").clicked()
      compare(owner.starts[1].mode,"reviews")
    }
    function test_clock_vacation_and_busy_prevent_start() {
      settle()
      screen.queuePreview(true)
      previewSettled()
      backend.snapshot = Object.assign({},backend.snapshot,{status:"clock_changed"})
      screen.startLessons()
      compare(owner.starts.length,0)
      backend.snapshot = Object.assign({},backend.snapshot,{status:"ready",vacation:true})
      screen.startLessons()
      compare(owner.starts.length,0)
      backend.snapshot = Object.assign({},backend.snapshot,{vacation:false})
      owner.busy = true
      screen.startLessons()
      compare(owner.starts.length,0)
    }
    function test_narrow_layout_data() { return [{tag:"320px",width:320},{tag:"460px",width:460}] }
    function test_narrow_layout(data) {
      backend.cards = [Object.assign(card(1),{characters:"わたしのながいれんしゅうことば",meanings:["A deliberately lengthy authored meaning for wrapping"],
        prerequisites:[{characters:"火",state:"Paused graded work",can_open:false}]}),card(2,"radical",false)]
      screen.width = data.width
      settle()
      screen.toggleSubject(backend.cards[0])
      previewSettled()
      verify(waitForRendering(screen))
      for (var item of items(screen)) {
        if (!item.visible || !item.width || !item.height) continue
        var point = item.mapToItem(screen,0,0)
        verify(point.x >= -1 && point.x+item.width <= screen.width+1,
          String(item.objectName || item.text || item)+" exceeds "+screen.width+"px")
      }
      compare(owner.routes.length,0)
      verify(items(screen).every(function (item) { return !item.text || item.text !== "Open 火" }))
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), "QtTest runtime is not installed")
class LessonOverviewRenderingTests(unittest.TestCase):
    def test_actual_lesson_and_review_overview(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-lesson-overview-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("StudyOverview.qml", "Label.qml", "Card.qml", "Theme.mjs", "SubjectGlyph.qml", "JapaneseText.qml", "RadicalImage.qml"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            (qml / "Action.qml").write_text('import QtQuick.Controls\nButton {\n'
                ' objectName: "fixture-action"\n property bool selected: false\n'
                ' property string accessibleName: text\n property string accessibleHint: ""\n}\n')
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n")
            (common / "Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' function space(value) { return value }\n readonly property int cornerRadius: 8\n'
                ' readonly property var font: ({family:"Sans",body:14,bodySmall:12,title:20})\n}\n')
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' property color background: "#ffffff"\n property color foreground: "#202020"\n'
                ' property color accent: "#006699"\n property color urgent: "#990000"\n}\n')
            shutil.copyfile(ROOT / "tests/qml/fixtures/radical.svg", directory / "radical.svg")
            (directory / "tst_LessonOverview.qml").write_text(QML)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=45,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
