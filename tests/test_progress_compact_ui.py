"""Narrow native Progress tabs keep useful controls visible and state intact."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import test_level_history_ui as history
import test_srs_progress_navigation as foundation


TESTS = r'''
  TestCase {
    name:"CompactProgressUi";when:windowShown
    function init(){
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;service.hold=false;service.requests=[];service.pending=[]
      service.snapshot={level:2,max_level:60,last_sync:"fixture",session_revision:1,session_epoch:"fixture",pending:0,attention:0,syncing:false,status:"online",learning_progress:service.current()}
      owner.service=service;owner.opened=true;owner.contentAccess="authored-account";owner.openedIds=[];owner.progressNavigation={}
      Color.background="#fffdf5";Color.foreground="#202020";Color.accent="#006699"
    }
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    function make(){screen=pageComponent.createObject(parent);verify(screen!==null);wait(1)}
    function item(name){var found=findChild(screen,name);verify(found!==null,name);return found}
    function click(name){var button=item(name);verify(button.visible&&button.enabled,name);button.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
    function srs(){return item("srs-explorer")}
    function board(){tryVerify(function(){return screen.page.items.length>0&&!screen.loading})}
    function explorer(){tryVerify(function(){return !!srs().page&&!srs().loading});wait(1)}
    function withinViewport(node){var top=node.mapToItem(surface,0,0).y;verify(top>=0&&top+node.height<=surface.height,node.objectName+" within the first narrow viewport: "+top)}
    __CHECKS__
    function test_explorer_groups_are_visible_without_scrolling_past_full_level_card(){
      make();board();verify(item("progress-full-level").visible);verify(!item("progress-compact-level").visible)
      var originalTabTop=item("progress-explorer-tab").mapToItem(surface,0,0).y
      click("progress-explorer-tab");explorer()
      verify(!item("progress-full-level").visible);verify(item("progress-compact-level").visible)
      verify(item("progress-explorer-tab").mapToItem(surface,0,0).y<=originalTabTop-120,"Explorer gives the learner at least120px more working space")
      withinViewport(item("srs-group-guru"));withinViewport(item("srs-refresh"));withinViewport(item("srs-refine"))
      compare(item("progress-compact-level-target").text,"Level 2 · 24 / 27 required kanji passed")
      verify(item("progress-compact-level-pending").text.indexOf("1 waiting to sync")>=0)
      verify(item("srs-group-apprentice").activeFocus,"Tab selection transfers keyboard focus to the selected SRS group")
      compare(service.requests.map(function(value){return value.method}),["progress","level_board","srs_catalogue"])
      click("progress-subjects-tab");board();verify(item("progress-full-level").visible);verify(!item("progress-compact-level").visible)
    }
    function test_history_actions_and_first_record_are_visible_without_extra_scroll(){
      make();board();click("progress-history-tab");tryVerify(function(){return item("history-dates-16").visible});wait(1)
      withinViewport(item("history-refresh"));withinViewport(item("history-duration-16"));withinViewport(item("history-dates-16"))
      verify(item("history-refresh").activeFocus)
      compare(service.requests.map(function(value){return value.method}),["progress","level_board","level_history"])
      click("history-dates-16");verify(item("history-dates-16").activeFocus)
      var reads=service.requests.length;wait(20);compare(service.requests.length,reads)
    }
    function test_compact_views_preserve_exact_explorer_selection_across_tabs_and_recreation(){
      make();board();click("progress-group-guru");explorer();click("srs-refine");click("srs-type-vocabulary");explorer()
      click("srs-stage-6");explorer();click("srs-levels");click("srs-level-2");explorer();click("srs-review-order");explorer();click("srs-next");explorer()
      var selected=JSON.stringify(srs().selectionState());click("progress-history-tab");tryVerify(function(){return service.requests.slice(-1)[0].method==="level_history"})
      var reads=service.requests.length;wait(20);compare(service.requests.length,reads)
      click("progress-explorer-tab");explorer();compare(JSON.stringify(srs().selectionState()),selected)
      click("srs-open-25");compare(owner.openedIds,[25]);var saved=JSON.stringify(owner.progressNavigation)
      screen.destroy();screen=null;wait(1);service.requests=[];make();explorer()
      compare(JSON.stringify(owner.progressNavigation),saved);compare(JSON.stringify(srs().selectionState()),selected)
      compare(service.requests,[{method:"srs_catalogue",args:{group:"guru",subject_type:"vocabulary",level:2,stage:6,order:"next_review",offset:24,limit:24}}])
      compare(item("progress-compact-level-target").text,"Level 2 · 24 / 27 required kanji passed")
    }
    function test_incomplete_inaccessible_and_final_level_context_stays_honest(){
      owner.progressNavigation={schema:1,section:"explorer",explorer:{group:"guru",offset:24}};make();explorer()
      service.snapshot=Object.assign({},service.snapshot,{learning_progress:Object.assign(service.current(),{complete:false,passed:null,required:null,fraction:null})});wait(1)
      verify(item("progress-compact-level-target").text.indexOf("Waiting for a complete sync")>=0)
      verify(item("progress-compact-level-target").text.indexOf("0 /")<0)
      service.snapshot=Object.assign({},service.snapshot,{learning_progress:Object.assign(service.current(),{accessible:false})});wait(1)
      verify(item("progress-compact-level-target").text.indexOf("Progress unavailable")>=0)
      service.snapshot=Object.assign({},service.snapshot,{learning_progress:Object.assign(service.current(),{level:60,final_level:true,pending:0,attention:2})});wait(1)
      verify(item("progress-compact-level-target").text.indexOf("Level 60 · Final level")===0)
      verify(item("progress-compact-level-pending").text.indexOf("2 need attention")>=0)
      withinViewport(item("srs-refine"))
    }
    function test_live_palette_preserves_compact_state_and_native_focus_data(){return paletteData()}
    function test_live_palette_preserves_compact_state_and_native_focus(data){
      owner.progressNavigation={schema:1,section:"explorer",explorer:{group:"guru",offset:24}};make();explorer()
      var saved=JSON.stringify(owner.progressNavigation),page=JSON.stringify(srs().page),reads=service.requests.length
      applyPalette(data);checkText(item("progress-compact-level"),data.tag+" current level")
      var tab=item("progress-explorer-tab");tab.forceActiveFocus();wait(140)
      verify(tab.Accessible.checked);var ring=findChild(tab,"wanikani-action-focus");verify(ring.visible)
      verify(Theme.contrast(ring.border.color,Theme.composite(tab.color,renderedUnder(tab.parent)))>=3)
      checkText(tab,data.tag+" active native tab")
      compare(JSON.stringify(owner.progressNavigation),saved);compare(JSON.stringify(srs().page),page);compare(service.requests.length,reads)
      withinViewport(item("srs-refine"))
      for(var label of paletteItems(item("progress-compact-level")))
        if(label.visible&&typeof label.text==="string"&&label.textFormat!==undefined){verify(!label.truncated);verify(label.contentWidth<=label.width+1)}
    }
  }
}
'''


def build(directory):
    foundation.build(directory)
    prefix = foundation.source().split("  TestCase {", 1)[0]
    prefix = prefix.replace('import "qml" as Kani', 'import "qml" as Kani\nimport "qml/Theme.mjs" as Theme')
    prefix = prefix.replace('width: 800; height: 2400; color: Color.background',
        'id:surface;width:322;height:720;color:Color.background;clip:true\n  readonly property color kaniSurface:color')
    prefix = prefix.replace('Kani.Progress { width: 380; controller: owner }',
        'Kani.Progress {x:16;y:16;width:290;controller:owner}')
    prefix = re.sub(r'^  Kani.LevelProgress \{.*?\}\n', '', prefix, flags=re.M)
    prefix = prefix.replace('    function current() {', history.HISTORY_DATA + '\n    function current() {')
    prefix = prefix.replace('    function data(method,args) {',
        '    function data(method,args) {\n      if(method==="level_history")return history(args)')
    checks = foundation.palettes.CHECKS.replace('__PALETTES__', json.dumps(foundation.palettes.palettes()))
    (directory / 'tst_SrsProgressNavigation.qml').write_text(prefix + TESTS.replace('__CHECKS__', checks))


@unittest.skipUnless(foundation.RUNNER.is_file(), "QtTest required")
class CompactProgressUiTests(unittest.TestCase):
    def test_native_compact_context_and_narrow_navigation(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-compact-progress-') as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(foundation.RUNNER), '-input', str(directory), '-import', str(directory)],
                capture_output=True, text=True, timeout=45, env={**os.environ, 'QT_QPA_PLATFORM':'offscreen',
                    'QT_QPA_PLATFORMTHEME':'', 'QT_QUICK_CONTROLS_STYLE':'Basic'})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn('QWARN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
