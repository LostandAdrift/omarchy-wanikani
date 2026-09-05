"""Actual ReadingTrail QML with authored local replies and Qt-only controls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path('/usr/lib/qt6/bin/qmltestrunner')


def practice_contract():
    """Use the real read-only trail/preview projections on authored storage."""
    from test_trail_practice import TrailPracticeTests
    from wanikani.trail import reading_trail

    fixture = TrailPracticeTests()
    fixture.setUp()
    try:
        text = '  山と火山🌊\nありがとう。<b>&\t  '
        fixture.engine.start('practice', 2, [2, 3], replace_practice=True)
        fixture.engine.draft('PRIVATE EARLIER DRAFT')
        before = fixture.store.db.serialize()
        value = {'trail': reading_trail(fixture.engine, text), 'preview': fixture.preview(text, [8, 2])}
        if fixture.store.db.serialize() != before:
            raise AssertionError('Fixture preview must not mutate earlier practice')
        if 'PRIVATE' in json.dumps(value):
            raise AssertionError('Fixture projections must not expose the earlier draft')
        return value
    finally:
        fixture.tearDown()

QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
Rectangle {
  width: 500; height: 1800; color: "white"
  property var trail: null
  Component { id: trailComponent; Kani.ReadingTrail { width: 320; controller: owner } }
  QtObject {
    id: service
    property bool ready: true
    property bool locked: false
    property bool hold: false
    property bool protectedSubject: false
    property bool aliases: false
    property bool practiceCase: false
    property var practiceContract: __PRACTICE_CONTRACT__
    property var requests: []
    property var pending: []
    property var snapshot: ({last_sync: "fixture", session_revision: 1,max_level:60})
    function fixture(text) {
      if(practiceCase){if(text!==practiceContract.trail.text)throw new Error("Exact authored passage required");return practiceContract.trail}
      var at = text.indexOf("山")
      var segments = at < 0 ? [{text:text,subject_ids:[]}] : [
        {text:text.slice(0,at),subject_ids:[]},
        {text:"山",subject_ids:aliases ? [2,9] : [2]},
        {text:text.slice(at+1),subject_ids:[]}]
      var matches = at < 0 ? [] : [{id:2,characters:"山",type:"kanji",level:1,state:protectedSubject ? "Paused graded work" : "Learned",can_open:!protectedSubject}]
      if (aliases && at >= 0) matches.push({id:9,characters:"山",type:"vocabulary",level:1,state:"Not started",can_open:true})
      return {text:text,segments:segments.filter(function(segment){return segment.text.length>0}),matches:matches,truncated:false}
    }
    function request(method,args,callback) {
      requests=requests.concat([{method:method,args:args}])
      var data
      if(method==="reading_trail")data=fixture(args.text)
      else if(method==="trail_practice_preview"&&practiceCase){
        if(args.text!==practiceContract.preview.text||JSON.stringify(args.subject_ids)!==JSON.stringify(practiceContract.preview.subject_ids))throw new Error("Preview requires exact authored selection order")
        data=practiceContract.preview
      }else throw new Error("Only read-only trail and preview requests are allowed")
      if(hold) pending=pending.concat([{callback:callback,data:data}])
      else callback(true,data,"")
    }
    function reply() { var entry=pending[0];pending=pending.slice(1);entry.callback(true,entry.data,"") }
  }
  QtObject {
    id: owner
    property var service: null
    property bool opened: true
    property string view: "lookup"
    property string query: "山が見えます。"
    property string contentAccess: "fixture-account"
    property var detail: null
    property var openedIds: []
    property var trailPracticeSelection: ({})
    property int navigationSequence: 0
    property bool busy: false
    property var practiceStarts: []
    property var practiceResumes: []
    function beginTrailPractice(preview,replace) { practiceStarts=practiceStarts.concat([{preview:preview,replace:replace}]) }
    function begin(mode,limit) { practiceResumes=practiceResumes.concat([{mode:mode,limit:limit}]) }
    readonly property var snapshot: service ? service.snapshot : ({})
    function showSubject(id) { openedIds=openedIds.concat([id]);if(service.practiceCase)detail={id:id} }
  }
  TextEdit { id: plainProbe; visible: false; textFormat: TextEdit.RichText; text: trail ? trail.passageHtml() : "" }
  TestCase {
    name: "ReadingTrailRendering"; when: windowShown
    function make() { trail=trailComponent.createObject(parent);verify(trail!==null);return trail }
    function settle() { tryVerify(function(){return trail.report!==null},1000);verify(waitForRendering(trail)) }
    function spanLink() { return "span:"+trail.report.segments.findIndex(function(segment){return segment.text==="山"}) }
    function init() {
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;service.hold=false;service.protectedSubject=false;service.aliases=false
      service.practiceCase=false
      service.requests=[];service.pending=[];service.snapshot={last_sync:"fixture",session_revision:1,max_level:60}
      owner.service=service;owner.opened=true;owner.view="lookup";owner.query="山が見えます。";owner.contentAccess="fixture-account";owner.detail=null;owner.openedIds=[]
      owner.trailPracticeSelection={};owner.practiceStarts=[];owner.practiceResumes=[];owner.navigationSequence=0;owner.busy=false
      Color.accent="#006699"
    }
    function cleanup() { if(trail) trail.destroy();trail=null;wait(1) }
    function test_request_is_local_exact_and_debounced() {
      make();owner.query="山へ";wait(30);owner.query="山が見えます。";settle()
      compare(service.requests.length,1);compare(service.requests[0].method,"reading_trail")
      compare(service.requests[0].args.text,owner.query)
      wait(180);compare(service.requests.length,1)
    }
    function test_combined_practice_selection_survives_details_close_and_explicit_replacement() {
      function picker(){var value=findChild(trail,"reading-trail-practice");verify(value!==null);return value}
      function action(name){var button=findChild(trail,name);verify(button!==null&&button.visible&&button.enabled,name);button.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
      function ready(){tryVerify(function(){return picker().preview!==null&&!picker().loading},1000);verify(picker().canStart)}
      service.practiceCase=true;owner.query=service.practiceContract.trail.text
      service.snapshot={last_sync:"fixture",session_revision:1,max_level:60,session_epoch:service.practiceContract.preview.data_epoch}
      make();settle();verify(!picker().expanded)
      compare(service.requests.map(function(value){return value.method}),["reading_trail"])
      action("trail-practice-choose");action("trail-practice-word-8");action("trail-practice-word-2");ready()
      compare(owner.trailPracticeSelection,{schema:1,text:owner.query,ids:[8,2]})
      compare(picker().preview,service.practiceContract.preview);compare(owner.practiceStarts,[]);compare(owner.practiceResumes,[])
      var saved=JSON.stringify(owner.trailPracticeSelection),reads=service.requests.length
      trail.openSubject(8);compare(owner.openedIds,[8]);verify(owner.detail!==null);compare(trail.report,null)
      wait(180);compare(service.requests.length,reads);compare(JSON.stringify(owner.trailPracticeSelection),saved)
      owner.detail=null;settle();ready();compare(picker().currentIds,[8,2]);compare(JSON.stringify(owner.trailPracticeSelection),saved)
      owner.opened=false;reads=service.requests.length;wait(180);compare(service.requests.length,reads)
      trail.destroy();trail=null;wait(1);compare(JSON.stringify(owner.trailPracticeSelection),saved)
      owner.opened=true;make();settle();compare(picker().selectedIds,[8,2]);verify(!picker().expanded)
      reads=service.requests.length;wait(180);compare(service.requests.length,reads)
      action("trail-practice-choose");ready();compare(owner.practiceStarts,[])
      compare(findChild(trail,"trail-practice-start").text,"Start new practice")
      action("trail-practice-start")
      compare(owner.practiceStarts,[{preview:service.practiceContract.preview,replace:true}])
      compare(owner.practiceResumes,[]);verify(JSON.stringify(owner.practiceStarts).indexOf("PRIVATE")<0)
      verify(service.requests.every(function(value){return value.method==="reading_trail"||value.method==="trail_practice_preview"}))
    }
    function test_single_character_and_non_japanese_do_not_read() {
      owner.query="山";make();wait(170);compare(service.requests.length,0)
      owner.query="authored words";wait(170);compare(service.requests.length,0)
      owner.query="𠮷野";settle();compare(service.requests.length,1)
    }
    function test_closed_locked_unready_and_detail_views_do_not_read() {
      owner.opened=false;make();wait(170);compare(service.requests.length,0)
      service.ready=false;owner.opened=true;wait(170);compare(service.requests.length,0)
      service.ready=true;service.locked=true;wait(170);compare(service.requests.length,0)
      service.locked=false;owner.detail={id:2};wait(170);compare(service.requests.length,0)
      owner.detail=null;settle();compare(service.requests.length,1)
      owner.opened=false;compare(trail.report,null);owner.query="火山";wait(170);compare(service.requests.length,1)
      owner.opened=true;settle();compare(service.requests.length,2)
    }
    function test_stale_query_reply_cannot_restore_previous_passage() {
      service.hold=true;make()
      tryVerify(function(){return service.pending.length===1})
      owner.query="火山に行きます。";wait(170);compare(service.requests.length,1)
      service.reply();compare(trail.report,null)
      tryVerify(function(){return service.pending.length===1});compare(service.requests.length,2)
      service.reply();settle();compare(trail.report.text,owner.query)
    }
    function test_changed_service_owner_drops_old_reply_without_blocking_new_owner() {
      service.hold=true;make();tryVerify(function(){return service.pending.length===1})
      owner.service=null;owner.service=service
      tryVerify(function(){return service.pending.length===2})
      service.reply();compare(trail.report,null);verify(trail.fetching)
      service.reply();settle();compare(trail.report.text,owner.query)
    }
    function test_partial_sync_invalidates_links_without_a_new_last_sync() {
      make();settle();verify(trail.report.matches[0].can_open)
      service.protectedSubject=true
      service.snapshot={last_sync:"fixture",session_revision:1,max_level:60,state_revision:2,status:"offline",syncing:false}
      compare(trail.report,null);settle();compare(trail.report.matches[0].can_open,false)
    }
    function test_new_study_revision_invalidates_old_openable_reply() {
      service.hold=true;make();tryVerify(function(){return service.pending.length===1})
      service.protectedSubject=true;service.snapshot={last_sync:"fixture",session_revision:2}
      service.reply();compare(trail.report,null)
      tryVerify(function(){return service.pending.length===1});service.reply();settle()
      compare(trail.matches[0].can_open,false);trail.openSubject(2);compare(owner.openedIds.length,0)
    }
    function test_access_change_clears_existing_passage_and_late_reply() {
      make();settle();owner.contentAccess="new-account";compare(trail.report,null)
      service.hold=true;tryVerify(function(){return service.pending.length===1})
      owner.opened=false;service.reply();compare(trail.report,null);compare(owner.openedIds.length,0)
    }
    function test_links_are_membership_checked_and_protected_words_stay_inert() {
      make();settle();trail.activateLink("span:1evil");trail.activateLink("span:-1");trail.activateLink("span:999");trail.openSubject(999)
      compare(owner.openedIds.length,0);trail.activateLink(spanLink());compare(owner.openedIds[0],2)
      owner.openedIds=[];service.protectedSubject=true;service.snapshot={last_sync:"fixture",session_revision:2};settle()
      verify(trail.passageHtml().indexOf("href=")<0);trail.activateLink(spanLink());trail.openSubject(2);compare(owner.openedIds.length,0)
    }
    function test_ambiguous_alias_requires_explicit_choice() {
      service.protectedSubject=true;service.aliases=true;make();settle()
      trail.activateLink(spanLink());compare(owner.openedIds.length,0);compare(trail.selectedIds.length,2)
      trail.openSubject(2);compare(owner.openedIds.length,0);trail.openSubject(9);compare(owner.openedIds[0],9)
    }
    function test_exact_whitespace_unicode_and_html_are_preserved() {
      owner.query="  山\n\n 火山\t <b>literal & \"quoted\"</b> 𠮷 ";make();settle()
      var passage=findChild(trail,"reading-trail-passage");verify(passage!==null)
      compare(passage.Accessible.name,owner.query)
      // QTextDocument exposes rendered line breaks as Unicode separators.
      compare(plainProbe.getText(0,plainProbe.length).replace(/[\u2028\u2029]/g,"\n"),owner.query)
      verify(passage.contentHeight>=passage.font.pixelSize*3,"Newlines occupy separate rendered lines")
      verify(passage.text.indexOf("<b>literal")<0)
      verify(passage.text.indexOf("&lt;b&gt;")>=0)
      verify(passage.contentWidth<=passage.width+1);verify(passage.contentHeight<=passage.height+1)
    }
    function test_corrupt_reply_cannot_replace_selection() {
      service.hold=true;make();tryVerify(function(){return service.pending.length===1})
      service.pending[0].data.segments=[{text:"different selection",subject_ids:[2]}]
      service.reply();compare(trail.report,null);verify(trail.notice.length>0)
    }
    function test_malformed_reply_boundaries() {
      make();settle()
      var next=service.fixture(owner.query);next.segments=Array(513).fill({text:"",subject_ids:[]});verify(!trail.validReport(next,owner.query))
      next=service.fixture(owner.query);next.segments[0].subject_ids=Array(61).fill(2);verify(!trail.validReport(next,owner.query))
      next=service.fixture(owner.query);next.segments[0].subject_ids=[999];verify(!trail.validReport(next,owner.query))
      next=service.fixture(owner.query);next.segments[0].subject_ids=["2"];verify(!trail.validReport(next,owner.query))
      next=service.fixture(owner.query);next.segments.unshift({text:"",subject_ids:[]});verify(!trail.validReport(next,owner.query))
    }
    function test_links_follow_live_theme_accent_without_another_request() {
      make();settle();var passage=findChild(trail,"reading-trail-passage")
      verify(passage.text.indexOf('style="color:#006699"')>=0)
      Color.accent="#ffbb88";verify(waitForRendering(trail))
      verify(passage.text.indexOf('style="color:#ffbb88"')>=0)
      verify(passage.text.indexOf('#006699')<0)
      compare(service.requests.length,1)
      compare(plainProbe.getText(0,plainProbe.length),owner.query)
    }
    function test_eight_word_disclosure_preserves_all_ambiguous_choices() {
      make();settle()
      var next=service.fixture(owner.query)
      next.matches=[]
      for(var index=0;index<12;index++)
        next.matches.push({id:index+2,characters:"山",type:"kanji",level:1,state:"Learned",can_open:true})
      next.segments[0].subject_ids=next.matches.map(function(word){return word.id})
      trail.report=next
      verify(waitForRendering(trail))
      compare(trail.visibleMatches.length,8);verify(!trail.wordsExpanded)
      var more=findChild(trail,"reading-trail-more");verify(more.visible);compare(more.text,"Show all 12 words")
      more.clicked();compare(trail.visibleMatches.length,12);compare(more.text,"Show fewer words")
      more.clicked();compare(trail.visibleMatches.length,8)
      trail.activateLink(spanLink());compare(trail.visibleMatches.length,12);verify(!more.visible)
      trail.selectedIds=[];more.clicked();verify(trail.wordsExpanded)
      owner.query="山へ";verify(!trail.wordsExpanded);compare(trail.report,null);settle()
      trail.wordsExpanded=true;owner.contentAccess="new-access";verify(!trail.wordsExpanded)
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file(), 'QtTest runtime is not installed')
class ReadingTrailRenderingTests(unittest.TestCase):
    def test_actual_reading_trail_with_authored_responses(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-reading-trail-') as temporary:
            directory = Path(temporary)
            qml = directory / 'qml'
            qml.mkdir()
            for name in ('ReadingTrail.qml', 'TrailPractice.qml', 'Label.qml', 'Card.qml', 'UnicodeText.mjs', 'Theme.mjs'):
                shutil.copyfile(ROOT / 'qml' / name, qml / name)
            (qml / 'Action.qml').write_text('import QtQuick\nimport QtQuick.Controls\nButton {\n'
                ' property bool selected: false\n property string accessibleName: text\n property string accessibleHint: ""\n'
                ' property string tooltipText: ""\n property string fontFamily: "Sans"\n property int fontSize: 14\n'
                ' horizontalPadding: 8\n Accessible.name: accessibleName\n Accessible.ignored: !visible\n}\n')
            common = directory / 'qs' / 'Commons'
            common.mkdir(parents=True)
            (common / 'qmldir').write_text('module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n')
            (common / 'Style.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' function space(value) { return value }\n readonly property var font: ({family:"Sans",body:14,bodySmall:12,title:20})\n'
                ' readonly property int cornerRadius: 6\n}\n')
            (common / 'Color.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' readonly property color background: \"#ffffff\"\n readonly property color foreground: "#202020"\n property color accent: "#006699"\n}\n')
            (directory / 'tst_ReadingTrail.qml').write_text(QML.replace('__PRACTICE_CONTRACT__', json.dumps(practice_contract())))
            result = subprocess.run([str(RUNNER), '-input', str(directory), '-import', str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn('QWARN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
