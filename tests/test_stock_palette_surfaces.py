"""Live stock-palette changes on actual learning components, with inert IO.

Reads installed colors.toml and native control-token functions. The shell's
stateful theme loaders and BorderSurface painter are excluded; native buttons,
inputs and the plugin's explicit focus indicators remain actual source.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest

import test_kanji_examples_ui as examples
import test_learning_progress_rendering as progress
import test_lesson_flow_ui as study
import test_listening_rendering as listening


ROOT = Path(__file__).resolve().parents[1]
THEMES = Path("/usr/share/omarchy/themes")
COMMONS = Path("/usr/share/omarchy/shell/Commons")
RUNNER = study.RUNNER


def palettes():
    result = []
    for path in sorted(THEMES.glob("*/colors.toml")):
        value = tomllib.loads(path.read_text())
        result.append({"tag": path.parent.name, "background": value["background"],
            "foreground": value["foreground"], "accent": value["accent"], "urgent": value["red"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result or [{"tag": "authored-light", "background": "#ffffff", "foreground": "#202020",
                      "accent": "#006699", "urgent": "#aa0000"},
                     {"tag": "authored-dark", "background": "#171925", "foreground": "#dfe4f3",
                      "accent": "#99ccff", "urgent": "#ffaaaa"}]


def pure_native_style(directory):
    source = (COMMONS / "Style.qml").read_text()
    tokens = source.split("  property var styleOverrides:", 1)[1].split(
        "  // ---------------------------------------------------------- spacing", 1)[0]
    (directory / "qs/Commons/Style.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
        'property int cornerRadius:6\nfunction space(value){return value}\n'
        'property var font:({family:"Sans",body:14,bodySmall:12,title:20,icon:16})\n'
        'property var spacing:({controlPaddingX:12,controlPaddingY:8,controlGap:6,inputPaddingY:8,md:8,controlHeight:34})\n'
        '  property var styleOverrides:' + tokens + '\n}\n')
    utility = (COMMONS / "Util.qml").read_text()
    functions = []
    for name in ("clamp", "clampAlpha", "alpha"):
        match = re.search(r"(?ms)^  function " + name + r"\(.*?^  \}", utility)
        if not match:
            raise AssertionError("Review native utility boundary: " + name)
        functions.append(match.group(0))
    (directory / "qs/Commons/Util.qml").write_text(
        'pragma Singleton\nimport QtQuick\nQtObject {\n' + '\n'.join(functions) + '\n}\n')
    module = directory / "qs/Commons/qmldir"
    module.write_text(module.read_text() + "singleton Util 1.0 Util.qml\n")


CHECKS = r'''
    function paletteData() {return __PALETTES__}
    function applyPalette(value) {
      Color.background=value.background;Color.foreground=value.foreground;Color.accent=value.accent;Color.urgent=value.urgent
      wait(140)
    }
    function paletteItems(node) {
      var items=[node]
      for(var child of node.children)items=items.concat(paletteItems(child))
      return items
    }
    function renderedUnder(node) {
      if(!node)return Color.background
      var under=renderedUnder(node.parent)
      if(node.kaniSurface!==undefined)return node.kaniSurface
      if(node.color!==undefined)return Theme.composite(node.color,under)
      return under
    }
    function checkText(node,tag) {
      var count=0
      for(var label of paletteItems(node)) {
        if(!label.visible || label.textFormat===undefined || label.color===undefined || typeof label.text!=="string" || !label.text)continue
        // A TextField paints its own background, while Text uses its parent.
        var surface=label.renderedSurface!==undefined?label.renderedSurface:renderedUnder(label.parent)
        var ratio=Theme.contrast(label.color,surface)
        verify(ratio>=4.5,tag+": text "+JSON.stringify(label.text)+" contrast "+ratio.toFixed(3)+" on "+surface)
        count++
      }
      verify(count>0,tag+": actual text visited")
    }
    function checkButtons(node,tag) {
      var buttons=paletteItems(node).filter(function(item){return item.visible&&item.enabled&&item.accessibleName!==undefined&&item.foreground!==undefined&&item.hasCursor!==undefined})
      verify(buttons.length>0,tag+": native buttons visited")
      var button=buttons[0]
      var selected=button.selected
      button.forceActiveFocus();wait(140)
      var ring=findChild(button,"wanikani-action-focus")
      verify(ring!==null&&ring.visible)
      var back=Theme.composite(button.color,renderedUnder(button.parent))
      verify(Theme.contrast(ring.border.color,back)>=3,tag+": explicit focus contrast")
      checkText(button,tag+" focused button")
      button.selected=true;wait(140);checkText(button,tag+" focused selected button")
      button.selected=selected
    }
'''

STUDY_TEST = r'''
    function test_live_palette_preserves_review_draft_and_saved_lesson_data(){return paletteData()}
    function test_live_palette_preserves_review_draft_and_saved_lesson(data){
      var value=state("meaning");value.mode="reviews";value.phase="question";value.draft="volcan";value.lesson_flow=null;value.completed=2;value.total=5
      make(value);var saved=JSON.stringify(owner.session);var input=item("study-answer")
      compare(input.text,"volcan");input.cursorPosition=3
      applyPalette(data);compare(input.text,"volcan");compare(input.cursorPosition,3);compare(JSON.stringify(owner.session),saved)
      checkText(page,data.tag+" review");checkButtons(page,data.tag+" review")
      var meter=item("study-completion-meter");var filled=meter.children[0]
      verify(meter.visible&&meter.height>0,data.tag+" completion meter has layout height")
      compare(meter.Accessible.role,Accessible.ProgressBar);compare(meter.Accessible.name,"2 of 5 subjects completed")
      verify(Math.abs(filled.width-meter.width*.4)<.01,data.tag+" actual completed proportion")
      verify(Theme.contrast(filled.color,meter.color)>=3,data.tag+" completed fill against remaining track")
      input.forceActiveFocus();input.selectAll()
      verify(Theme.contrast(input.color,input.renderedSurface)>=4.5,data.tag+" input text")
      verify(Theme.contrast(input.placeholderTextColor,input.renderedSurface)>=4.5,data.tag+" input placeholder")
      verify(Theme.contrast(input.selectedTextColor,Theme.composite(input.selectionColor,input.renderedSurface))>=4.5,data.tag+" selected input")
      compare(input.text,"volcan");compare(owner.actions.length,0);compare(backend.writes.length,0)
      page.destroy();page=null;wait(1);make(state("reading"));saved=JSON.stringify(owner.session)
      // Reverse through a contrasting baseline and back without replacing state.
      applyPalette({background:"#ffffff",foreground:"#202020",accent:"#006699",urgent:"#aa0000"});applyPalette(data)
      checkText(page,data.tag+" lesson");checkButtons(page,data.tag+" lesson")
      compare(JSON.stringify(owner.session),saved);compare(owner.actions.length,0);compare(owner.plays.length,0);compare(backend.writes.length,0)
    }
'''

EXAMPLES_TEST = r'''
    function test_live_palette_preserves_disclosed_examples_data(){return paletteData()}
    function test_live_palette_preserves_disclosed_examples(data){
      make();reveal();var saved=JSON.stringify(page.examples)
      applyPalette(data);checkText(page,data.tag+" examples");checkButtons(page,data.tag+" examples")
      verify(page.expanded);compare(JSON.stringify(page.examples),saved);compare(backend.pending.length,1);compare(owner.plays.length,0)
    }
'''

LISTEN_TEST = r'''
  TestCase {
    name:"StockPaletteListening";when:windowShown
    function init(){failOnWarning(/.*/);owner.service=service;owner.opened=true;owner.plays=0;owner.actions=[];owner.reloads=0;owner.snapshot={settings:{autoplay_listening:true}}}
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    __CHECKS__
    function test_live_palette_preserves_hidden_and_revealed_saved_listening_data(){return paletteData()}
    function test_live_palette_preserves_hidden_and_revealed_saved_listening(data){
      owner.listenSession=owner.question(0);screen=page.createObject(parent);verify(screen!==null);verify(waitForRendering(screen))
      var saved=JSON.stringify(owner.listenSession);applyPalette(data)
      checkText(screen,data.tag+" listening question");checkButtons(screen,data.tag+" listening question")
      compare(JSON.stringify(owner.listenSession),saved);verify(!findChild(screen,"listeningAnswer").active)
      owner.listenSession=owner.revealed();saved=JSON.stringify(owner.listenSession);wait(1)
      applyPalette({background:"#ffffff",foreground:"#202020",accent:"#006699",urgent:"#aa0000"});applyPalette(data)
      checkText(screen,data.tag+" listening answer");checkButtons(screen,data.tag+" listening answer")
      compare(JSON.stringify(owner.listenSession),saved);compare(owner.plays,0);compare(owner.actions.length,0);compare(owner.reloads,0)
    }
  }
}
'''

PROGRESS_TEST = r'''
  TestCase {
    name:"StockPaletteProgress";when:windowShown
    function init(){failOnWarning(/.*/);owner.service=service;owner.opened=true;service.requests=[];service.hold=false;owner.openedIds=[];owner.explored=0}
    function cleanup(){if(screen)screen.destroy();screen=null;wait(1)}
    __CHECKS__
    function test_live_palette_preserves_board_and_dashboard_target_data(){return paletteData()}
    function test_live_palette_preserves_board_and_dashboard_target(data){
      screen=pageComponent.createObject(parent);verify(screen!==null);tryVerify(function(){return screen.page.items.length===24})
      var saved=JSON.stringify(screen.page);var requests=service.requests.length
      applyPalette(data);checkText(screen,data.tag+" progress");checkButtons(screen,data.tag+" progress")
      var category=findChild(screen,"progress-group-apprentice");verify(category!==null)
      category.forceActiveFocus();wait(140)
      var categorySurface=Theme.composite(category.color,category.surfaceColor)
      for(var role of ["label","count"]){
        var categoryText=findChild(screen,"progress-group-"+role+"-apprentice")
        verify(Theme.contrast(categoryText.color,categorySurface)>=4.5,data.tag+" focused category "+role+" follows its actual native fill")
      }
      checkText(home,data.tag+" dashboard level target");checkButtons(home,data.tag+" dashboard level target")
      var meter=findChild(home,"levelPassingMeter");var filled=meter.children[0]
      var meterContrast=Theme.contrast(filled.color,meter.color)
      verify(meterContrast>=3,data.tag+" progress fill against remaining track "+meterContrast.toFixed(3)+" ("+filled.color+" / "+meter.color+")")
      compare(JSON.stringify(screen.page),saved);compare(service.requests.length,requests);compare(owner.openedIds.length,0);compare(owner.explored,0)
    }
  }
}
'''


def source_for(name):
    if name == "study":
        source = study.QML.split("    function test_", 1)[0] + CHECKS + STUDY_TEST + "\n  }\n}\n"
    elif name == "examples":
        source = examples.QML.split("    function test_", 1)[0] + CHECKS + EXAMPLES_TEST + "\n  }\n}\n"
    elif name == "listen":
        source = listening.QML.split("  TestCase {", 1)[0] + LISTEN_TEST.replace("__CHECKS__", CHECKS)
    else:
        source = progress.QML.split("  TestCase {", 1)[0] + PROGRESS_TEST.replace("__CHECKS__", CHECKS)
    if 'import "qml/Theme.mjs" as Theme' not in source:
        source = source.replace('import "qml" as Kani', 'import "qml" as Kani\nimport "qml/Theme.mjs" as Theme')
    return source.replace("__PALETTES__", json.dumps(palettes()))


def build(directory, name):
    study.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    for component in ("Listening", "LevelProgress", "Progress", "SrsExplorer", "LevelHistory"):
        shutil.copyfile(ROOT / "qml" / (component + ".qml"), directory / "qml" / (component + ".qml"))
    pure_native_style(directory)
    (directory / "tst_StockPalette.qml").write_text(source_for(name))


@unittest.skipUnless(RUNNER.is_file() and (COMMONS / "Style.qml").is_file(), "Installed native Qt controls required")
class StockPaletteSurfacesTests(unittest.TestCase):
    def check_surface(self, name):
        with tempfile.TemporaryDirectory(prefix="wanikani-stock-palettes-") as temporary:
            directory = Path(temporary)
            build(directory, name)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=45, env={**os.environ,
                    "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic"})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn("QWARN", output)

    def test_study_stock_palettes(self):
        self.check_surface("study")

    def test_listening_stock_palettes(self):
        self.check_surface("listen")

    def test_kanji_examples_stock_palettes(self):
        self.check_surface("examples")

    def test_progress_stock_palettes(self):
        self.check_surface("progress")


if __name__ == "__main__":
    unittest.main()
