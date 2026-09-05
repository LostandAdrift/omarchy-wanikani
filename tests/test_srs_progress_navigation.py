"""Native parent tab/category flow with actual Explorer and inert account IO."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_learning_progress_rendering as progress
import test_lesson_flow_ui as foundation
import test_srs_explorer_ui as explorer
import test_stock_palette_surfaces as palettes


ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER

TESTS = r'''
  TestCase {
    name:"SrsProgressNavigation";when:windowShown
    function init(){
      failOnWarning(/.*/)
      service.ready=true;service.locked=false;service.hold=false;service.requests=[];service.pending=[]
      service.snapshot={level:2,max_level:60,last_sync:"fixture",session_revision:1,session_epoch:"fixture",pending:0,attention:0,syncing:false,status:"online"}
      owner.service=service;owner.opened=true;owner.contentAccess="authored-account";owner.openedIds=[];owner.progressNavigation={}
      Color.background="#ffffff";Color.foreground="#202020";Color.accent="#006699"
    }
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    function make(){screen=pageComponent.createObject(parent);verify(screen!==null);wait(1)}
    function item(name){var found=findChild(screen,name);verify(found!==null,name);return found}
    function click(name){var button=item(name);verify(button.visible&&button.enabled,name);button.forceActiveFocus();keyClick(Qt.Key_Space);wait(1)}
    function srs(){return item("srs-explorer")}
    function settleBoard(){tryVerify(function(){return screen.page.items.length>0&&!screen.loading})}
    function settleExplorer(){tryVerify(function(){return !!srs().page&&!srs().loading});verify(waitForRendering(screen))}
    function test_category_opens_the_matching_cross_level_group(){
      make();settleBoard();click("progress-group-guru");settleExplorer()
      compare(screen.section,"explorer");compare(srs().group,"guru")
      compare(service.requests.map(function(r){return r.method}),["progress","level_board","srs_catalogue"])
      verify(item("progress-group-guru").Accessible.name.indexOf("3 subjects")>=0)
    }
    function test_exact_explorer_selection_survives_parent_destruction(){
      make();settleBoard();click("progress-explorer-tab");settleExplorer()
      click("srs-refine");click("srs-type-vocabulary");settleExplorer();click("srs-stage-4");settleExplorer()
      click("srs-levels");click("srs-level-2");settleExplorer();click("srs-review-order");settleExplorer()
      click("srs-next");settleExplorer();click("srs-open-25");compare(owner.openedIds,[25])
      var saved=JSON.stringify(owner.progressNavigation)
      screen.destroy();screen=null;wait(1);service.requests=[]
      make();settleExplorer();compare(screen.section,"explorer")
      compare(service.requests,[{method:"srs_catalogue",args:{group:"apprentice",subject_type:"vocabulary",level:2,stage:4,order:"next_review",offset:24,limit:24}}])
      compare(JSON.stringify(owner.progressNavigation),saved)
    }
    function test_hidden_explorer_stays_idle_and_return_keeps_filters(){
      make();settleBoard();click("progress-group-guru");settleExplorer()
      srs().chooseType("vocabulary");settleExplorer();srs().chooseStage(6);settleExplorer()
      click("progress-subjects-tab");settleBoard();var reads=service.requests.length
      wait(30);compare(service.requests.length,reads)
      click("progress-explorer-tab");settleExplorer()
      compare(srs().subjectType,"vocabulary");compare(srs().stage,6)
      compare(service.requests.slice(reads).map(function(r){return r.method}),["srs_catalogue"])
    }
    function test_account_switch_rejects_old_page_and_drops_restored_level(){
      owner.progressNavigation={schema:1,section:"explorer",selected_level:0,subject_type:"",offset:0,
        explorer:{group:"guru",subject_type:"vocabulary",level:10,stage:6,order:"level",offset:24}}
      service.hold=true;make();tryVerify(function(){return service.pending.length===1})
      service.snapshot=Object.assign({},service.snapshot,{max_level:3,session_epoch:"another-account"})
      owner.contentAccess="another-account";compare(srs().page,null)
      service.reply();compare(srs().page,null);service.hold=false
      settleExplorer();verify(srs().level===null||srs().level<=3);compare(srs().offset,0)
      verify(srs().rows.every(function(row){return row.level<=3}))
    }
  }
}
'''


def source():
    prefix = progress.QML.split("  TestCase {", 1)[0]
    helpers = re.search(r"(?s)    function stageLabel\(stage\).*?(?=    function request\()", explorer.QML).group(0)
    helpers = helpers.replace("function data(args)", "function srsData(args)")
    prefix = prefix.replace("    function data(method,args) {", helpers + '\n    function data(method,args) {\n      if(method==="srs_catalogue")return srsData(args)')
    prefix = prefix.replace("    property bool malformed: false", "    property bool malformed: false\n    property bool empty:false\n    property bool unknownProtection:false\n    property bool protectedCard:false\n    property bool partial:false")
    return prefix + TESTS


def build(directory):
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    for name in ("Progress", "SrsExplorer", "LevelHistory", "LevelProgress"):
        shutil.copyfile(ROOT / "qml" / (name + ".qml"), directory / "qml" / (name + ".qml"))
    palettes.pure_native_style(directory)
    (directory / "tst_SrsProgressNavigation.qml").write_text(source())


@unittest.skipUnless(RUNNER.is_file(), "QtTest required")
class SrsProgressNavigationTests(unittest.TestCase):
    def test_parent_navigation_and_native_category_actions(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-srs-navigation-") as temporary:
            directory = Path(temporary)
            build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=40,
                env={**os.environ, "QT_QPA_PLATFORM":"offscreen", "QT_QPA_PLATFORMTHEME":"", "QT_QUICK_CONTROLS_STYLE":"Basic"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
