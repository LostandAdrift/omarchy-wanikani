"""Actual SubjectPath and native buttons, with inert shell theme adapters."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_theme_rendering as foundation


ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER


QML = r'''
import QtQuick
import QtQuick.Layouts
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme

Rectangle {
  id: canvas
  width: 600
  height: 1800
  color: Color.background
  Kani.SubjectPath {
    id: path
    x: 10
    y: 10
    width: 290
    subject: null
    onRequestSubject: function(subjectId) { testCase.requests.push(subjectId) }
  }
  Item { id: focusSink; width: 1; height: 1 }
  TestCase {
    id: testCase
    name: "SubjectPath"
    when: windowShown
    property var requests: []
    function fixture(type) {
      return {id:100,type:type || "kanji",characters:"山",meanings:["authored mountain meaning"],
        readings:[{reading:"さん",accepted:true},{reading:"unaccepted reading",accepted:false}],
        components:[{id:101,characters:"一",meaning:"authored one"},{id:102,characters:"丨",meaning:"authored line"}],
        related:[{id:103,characters:"火山",meaning:"authored volcano"},{id:104,characters:"山道",meaning:"authored path"}]}
    }
    function descendants(node) {
      var result = []
      for (var child of node.children) result = result.concat([child], descendants(child))
      return result
    }
    function named(name) {return descendants(path).filter(function(node){return node.objectName===name})}
    function labels() {return descendants(path).filter(function(node){return node.text!==undefined && node.textFormat!==undefined})}
    function action(text) {
      var matches=descendants(path).filter(function(node){return node.accessibleName!==undefined && node.text===text})
      compare(matches.length,1,"One native action: "+text)
      return matches[0]
    }
    function open() {
      action("How this subject connects").clicked()
      tryCompare(path,"expanded",true)
      verify(waitForRendering(path))
    }
    function init() {
      failOnWarning(/.*/)
      Color.background="#171925";Color.foreground="#f3f5f7";Color.accent="#8aaaff"
      path.width=290;path.editable=false;path.openEnabled=false;path.showMeaning=true;path.showReading=true
      path.subject=fixture()
      requests=[]
      focusSink.forceActiveFocus()
    }
    function test_collapsed_summary_creates_no_path_answer_labels() {
      compare(path.visible,true)
      compare(path.expanded,false)
      compare(named("wanikani-path-card").length,0)
      compare(named("wanikani-path-meaning").length,0)
      verify(action("How this subject connects").accessibleName.indexOf("2 components and 2 related subjects")>=0)
      compare(requests.length,0)
    }
    function test_readonly_cards_are_content_not_disabled_buttons() {
      open()
      compare(named("wanikani-path-card").length,5)
      compare(named("wanikani-path-meaning").length,5)
      compare(named("wanikani-path-reading").length,1)
      compare(descendants(path).filter(function(node){return node.accessibleName!==undefined && node.text==="Open"}).length,0)
      path.openSubject(101)
      compare(requests.length,0)
      verify(labels().some(function(node){return node.text==="Radicals in this kanji"}))
      verify(labels().some(function(node){return node.text==="Words using this kanji"}))
      verify(!labels().some(function(node){return node.text.indexOf("unaccepted reading")>=0}))
    }
    function test_concealment_never_instantiates_hidden_parts_or_downstream_rows() {
      path.showReading=false
      open()
      compare(named("wanikani-path-reading").length,0)
      compare(named("wanikani-path-card").length,3)
      verify(!labels().some(function(node){return node.text.indexOf("authored volcano")>=0 || node.text==="火山"}))
      path.showMeaning=false
      compare(path.visible,false)
      tryCompare(path,"expanded",false)
      tryVerify(function(){return named("wanikani-path-meaning").length===0})
      path.showReading=true
      compare(path.visible,false)
      compare(named("wanikani-path-reading").length,0)
    }
    function test_request_requires_current_projection_and_explicit_open_permission() {
      path.editable=true
      open()
      path.openSubject(101)
      compare(requests.length,0)
      path.openEnabled=true
      var buttons=descendants(path).filter(function(node){return node.accessibleName==="Open 一"})
      tryVerify(function(){return descendants(path).some(function(node){return node.accessibleName==="Open 一"})})
      buttons=descendants(path).filter(function(node){return node.accessibleName==="Open 一"})
      buttons[0].clicked()
      compare(requests,[101])
      path.openSubject(999)
      path.openSubject("102")
      path.openSubject(100)
      compare(requests,[101])
      var changed=fixture();changed.components=[{id:102,characters:"丨",meaning:"line"}]
      path.subject=changed
      open()
      path.openSubject(101)
      compare(requests,[101])
      path.openEnabled=false
      path.openSubject(102)
      compare(requests,[101])
      path.openEnabled=true;path.showReading=false;open()
      path.openSubject(102)
      compare(requests,[101])
    }
    function test_native_keyboard_disclosure_and_open() {
      var toggle=action("How this subject connects")
      verify(toggle.Accessible.checkable);verify(!toggle.Accessible.checked)
      toggle.forceActiveFocus(Qt.TabFocusReason)
      keyClick(Qt.Key_Space)
      tryCompare(path,"expanded",true)
      verify(toggle.Accessible.checked)
      compare(requests.length,0)
      path.editable=true;path.openEnabled=true
      tryVerify(function(){return descendants(path).some(function(node){return node.accessibleName==="Open 一"})})
      var target=descendants(path).filter(function(node){return node.accessibleName==="Open 一"})[0]
      target.forceActiveFocus(Qt.TabFocusReason)
      keyClick(Qt.Key_Return)
      compare(requests,[101])
      verify(findChild(target,"wanikani-action-focus").visible)
    }
    function test_large_safe_integer_signal_keeps_exact_identity() {
      var value=fixture();value.components=[{id:9007199254740991,characters:"一",meaning:"authored large ID"}]
      path.subject=value;path.editable=true;path.openEnabled=true
      open()
      var target=descendants(path).filter(function(node){return node.accessibleName==="Open 一"})[0]
      target.clicked()
      compare(requests,[9007199254740991])
    }
    function test_types_data() {
      return [{tag:"radical",type:"radical",up:"Components",down:"Kanji using this radical",current:"This radical"},
        {tag:"vocabulary",type:"vocabulary",up:"Kanji in this word",down:"Related subjects",current:"This word"},
        {tag:"kana vocabulary",type:"kana_vocabulary",up:"Components",down:"Related subjects",current:"This word"},
        {tag:"unknown",type:"unfamiliar",up:"Components",down:"Related subjects",current:"This subject"}]
    }
    function test_types(data) {
      path.subject=fixture(data.type)
      open()
      compare(path.componentLabel,data.up);compare(path.relatedLabel,data.down);compare(path.currentLabel,data.current)
    }
    function test_empty_malformed_and_duplicate_lists_are_bounded() {
      for(var value of [null,{},[],{id:1,components:[],related:[]},{id:1,components:{},related:"bad"}]) {
        path.subject=value
        compare(path.visible,false)
        compare(path.expanded,false)
      }
      var value=fixture()
      value.components=[null,{},[],{id:true},{id:"101"},{id:-1},{id:100},{id:101,characters:"一"},{id:101,characters:"other"}]
      value.related=[]
      path.subject=value
      compare(path.components.length,1)
      open()
      compare(named("wanikani-path-card").length,2)
      value=fixture();value.components=[]
      for(var i=0;i<60;i++)value.related.push({id:200+i,characters:"山",meaning:"authored "+i})
      path.subject=value
      compare(path.related.length,30)
      open()
      compare(named("wanikani-path-card").length,5)
      action("Show all 30 related subjects").clicked()
      tryVerify(function(){return named("wanikani-path-card").length===31})
      action("Show fewer related subjects").clicked()
      tryVerify(function(){return named("wanikani-path-card").length===5})
      path.subject=fixture()
      compare(path.expanded,false);compare(path.allRelated,false)
    }
    function test_missing_glyphs_and_markup_are_literal_without_media() {
      var value=fixture("radical");value.characters="";value.images=["https://example.invalid/not-loaded.png"]
      value.components=[];value.related=[{id:105,characters:"◇",meaning:"<b>literal</b>",images:["https://example.invalid/not-loaded.png"]}]
      path.subject=value
      open()
      verify(labels().some(function(node){return node.text==="Image radical\nNot shown in this path"}))
      verify(labels().some(function(node){return node.text==="Glyph unavailable\nNot shown in this path"}))
      var literal=named("wanikani-path-meaning").filter(function(node){return node.text==="<b>literal</b>"})
      compare(literal.length,1);compare(literal[0].textFormat,Text.PlainText)
      compare(named("wanikani-path-reading").length,0)
      verify(!descendants(path).some(function(node){return node.sourceSize!==undefined}))
      compare(path.text("山".repeat(255)+"𠮷"+"extra",256),"山".repeat(255)+"𠮷")
    }
    function test_palette_and_narrow_geometry_data() {return __PALETTES__}
    function test_palette_and_narrow_geometry(data) {
      Color.background=data.background;Color.foreground=data.foreground;Color.accent=data.accent
      var value=fixture();value.related[1].characters="𠮷野山の長いことば";value.related[1].meaning="An independently authored longer meaning that should wrap inside its card."
      path.subject=value
      open()
      wait(140)
      verify(path.implicitHeight<1000,"bounded initial path at 290px")
      for(var card of named("wanikani-path-card")) {
        verify(card.width>100 && card.width<=290,data.tag+" card width")
        for(var label of descendants(card).filter(function(node){return node.textFormat!==undefined && node.visible && node.text.length>0})) {
          var position=label.mapToItem(card,0,0)
          verify(position.x>=-1 && position.x+label.width<=card.width+1,data.tag+" label width")
          verify(position.y>=-1 && position.y+label.height<=card.height+1,data.tag+" label height: "+label.text)
          verify(label.contentWidth<=label.width+2,data.tag+" full glyph fit")
          verify(Theme.contrast(label.color,card.color)>=4.5,data.tag+" text contrast")
          compare(label.Accessible.name,label.text)
        }
      }
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file() and foundation.NATIVE_BUTTON.is_file(), "Installed native Qt controls required")
class SubjectPathTests(unittest.TestCase):
    def test_native_path_projection_keyboard_and_palettes(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-subject-path-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("SubjectPath.qml", "JapaneseText.qml", "Label.qml", "Card.qml", "Action.qml",
                    "ActivationGuard.qml", "Theme.mjs", "UnicodeText.mjs"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Color 1.0 Color.qml\nsingleton Style 1.0 Style.qml\nsingleton Border 1.0 Border.qml\n")
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                'property color background:"#171925";property color foreground:"#f3f5f7";property color accent:"#8aaaff";\n'
                'property var tooltip:({background:"#ffffff",text:"#111111",border:"#111111"})\n}\n')
            (common / "Style.qml").write_text(foundation.STYLE)
            (common / "Border.qml").write_text(foundation.BORDER)
            ui = directory / "qs" / "Ui"
            ui.mkdir()
            (ui / "qmldir").write_text("module qs.Ui\nButton 1.0 Button.qml\nBorderSurface 1.0 BorderSurface.qml\n")
            shutil.copyfile(foundation.NATIVE_BUTTON, ui / "Button.qml")
            (ui / "BorderSurface.qml").write_text('import QtQuick\nRectangle {property var borderSpec:({});\n'
                'property real leftPadding:0;property real rightPadding:0;property real topPadding:0;property real bottomPadding:0}\n')
            (directory / "tst_SubjectPath.qml").write_text(QML.replace("__PALETTES__", json.dumps(foundation.palettes())))
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=35,
                env={**os.environ, "QT_QPA_PLATFORM":"offscreen", "QT_QPA_PLATFORMTHEME":"", "QT_QUICK_CONTROLS_STYLE":"Basic"})
            output = result.stdout + result.stderr
            self.assertEqual(0, result.returncode, output)
            self.assertNotIn("QWARN", output, output)


if __name__ == "__main__":
    unittest.main()
