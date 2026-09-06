"""Actual Panel shortcuts/navigation with native Qt keys and inert IO.

The exact shortcut block and isTextEditor/navigate functions are copied into a
small Item. This exercises Qt Shortcut and real TextInput/TextEdit focus without
hosting Quickshell. Backend, audio and session persistence adapters are inert.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_lesson_flow_ui as foundation

ROOT = Path(__file__).resolve().parents[1]
RUNNER = foundation.RUNNER

QML = r'''
import QtQuick
import QtQuick.Window
import QtTest
import "qml" as Kani
Item {
  id:root;width:620;height:900
  property bool opened:true
  readonly property var focusedItem:frame.Window.activeFocusItem
  readonly property bool editingText:isTextEditor(focusedItem)
  property string view:"study"
  property var session:({id:"authored-reviews",revision:7,phase:"question",draft:"partly typed",errors:2})
  property var savedLessons:({id:"authored-lessons",revision:3,phase:"lesson",lesson_step:"context"})
  property var savedDictation:({id:"authored-dictation",phase:"question",draft:"やm",draft_cursor:2,heard:false})
  property var begins:[]
  property int audioStops:0
  property int listeningLoads:0
  property string listenPreparationNotice:""
  property int listenSequence:0
  property bool listenBusy:false
  property int navigationSequence:0
  property bool progressReturn:false
  property bool moreNavigation:false
  property var detail:null
  property string error:""
  property var service:backend
  QtObject {
    id:backend
    property bool ready:true
    property bool studying:true
    property int preparationCancels:0
    property var requests:[]
    function cancelListeningPreparation(){preparationCancels++}
    function request(method,args,callback){requests=requests.concat([{method:method,args:args}])}
  }
  function begin(mode){begins=begins.concat([mode])}
  function stopAudio(){audioStops++}
  function loadListening(){listeningLoads++}
  function focusContent(){}
  __FUNCTIONS__
  Item {
    id:frame;anchors.fill:parent
    Item {id:focusSink;width:20;height:20;activeFocusOnTab:true}
    TextInput {id:single;x:20;y:20;width:180;height:28;text:"Authored text"
      Item {id:editorChild;width:2;height:2;activeFocusOnTab:true}
    }
    TextEdit {id:multi;x:20;y:60;width:180;height:70;text:"Authored\nnotes"}
    __SHORTCUTS__
  }
  Component {id:helpComponent;Kani.ShortcutHelp {width:290;controller:helpOwner;navigationShortcutsEnabled:true;helpShortcutEnabled:true;returnView:"dictation"}}
  QtObject {id:helpOwner;property int closed:0;function closeHelp(){closed++}function navigate(view){throw new Error("Help must preserve its owner return")}function dismiss(){}}
  TestCase {
    name:"PanelShortcuts";when:windowShown
    property var help:null
    function init(){
      failOnWarning(/.*/);root.opened=true;root.view="study";root.begins=[];root.audioStops=0;root.listeningLoads=0
      root.navigationSequence=0;root.listenSequence=0;root.listenBusy=false;root.progressReturn=false;root.detail=null;root.error=""
      backend.ready=true;backend.studying=true;backend.preparationCancels=0;backend.requests=[]
      single.text="Authored text";multi.text="Authored\nnotes";helpOwner.closed=0
      focusSink.forceActiveFocus();wait(1);verify(!root.editingText)
    }
    function cleanup(){if(help)help.destroy();help=null;wait(1)}
    function ctrl(key){keyClick(key,Qt.ControlModifier);wait(1)}
    function saved(){return JSON.stringify([root.session,root.savedLessons,root.savedDictation])}
    function test_existing_number_mapping_and_new_zero_data(){return [
      {tag:"today",key:Qt.Key_1,view:"dashboard"},{tag:"study",key:Qt.Key_2,view:"study"},
      {tag:"lookup",key:Qt.Key_3,view:"lookup"},{tag:"zen",key:Qt.Key_4,view:"zen"},
      {tag:"settings",key:Qt.Key_5,view:"settings"},{tag:"practice",key:Qt.Key_6,view:"practice-library"},
      {tag:"meaning-listening",key:Qt.Key_7,view:"listen"},{tag:"progress",key:Qt.Key_8,view:"progress"},
      {tag:"activity",key:Qt.Key_9,view:"activity"},{tag:"kana-dictation",key:Qt.Key_0,view:"dictation"}]}
    function test_existing_number_mapping_and_new_zero(data){
      var before=saved();ctrl(data.key)
      if(data.view==="study")compare(root.begins,["resume"])
      else {compare(root.view,data.view);compare(root.begins,[])}
      compare(saved(),before)
    }
    function test_zero_uses_real_navigation_without_starting_or_playing_saved_work(){
      var before=saved();root.detail={id:990001};root.listenBusy=true;root.progressReturn=true
      ctrl(Qt.Key_0);compare(root.view,"dictation");compare(root.navigationSequence,1)
      compare(root.audioStops,1);compare(backend.preparationCancels,1);verify(backend.studying)
      verify(!root.listenBusy);verify(!root.progressReturn);compare(root.detail,null)
      compare(root.listeningLoads,0);compare(root.begins,[]);compare(backend.requests,[]);compare(saved(),before)
    }
    function test_text_inputs_and_nested_editor_focus_keep_shortcuts_inert_data(){return [{tag:"TextInput",editor:single},{tag:"TextEdit",editor:multi},{tag:"nested-editor-control",editor:editorChild}]}
    function test_text_inputs_and_nested_editor_focus_keep_shortcuts_inert(data){
      data.editor.forceActiveFocus();wait(1);verify(root.editingText)
      var before=saved(),a=single.text,b=multi.text
      for(var key of [Qt.Key_0,Qt.Key_1,Qt.Key_2,Qt.Key_7,Qt.Key_9])ctrl(key)
      compare(root.navigationSequence,0);compare(root.view,"study");compare(root.begins,[])
      compare(root.audioStops,0);compare(backend.requests,[]);compare(single.text,a);compare(multi.text,b);compare(saved(),before)
    }
    function test_closed_panel_never_activates_navigation(){
      root.opened=false;ctrl(Qt.Key_0);ctrl(Qt.Key_1);ctrl(Qt.Key_2);compare(root.navigationSequence,0)
      compare(root.begins,[]);compare(root.audioStops,0);compare(backend.requests,[])
      root.opened=true;ctrl(Qt.Key_0);compare(root.view,"dictation");compare(root.navigationSequence,1)
    }
    function test_zero_does_not_replace_plain_typing_or_held_key_release(){
      var shortcut=findChild(root,"dictation-navigation-shortcut");verify(shortcut!==null);verify(!shortcut.autoRepeat)
      keyClick(Qt.Key_0);compare(root.navigationSequence,0)
      keyPress(Qt.Key_0,Qt.ControlModifier);wait(80);compare(root.navigationSequence,1)
      keyRelease(Qt.Key_0,Qt.ControlModifier);wait(1);compare(root.navigationSequence,1)
      ctrl(Qt.Key_0);compare(root.navigationSequence,2)
    }
    function children(node){var values=[node];for(var child of node.children)values=values.concat(children(child));return values}
    function test_native_help_names_both_audio_routes_and_specific_settings_sections(){
      help=helpComponent.createObject(root);verify(help!==null);verify(waitForRendering(help))
      compare(help.navigationShortcuts.length,10);compare(help.navigationShortcuts[9],{key:"Ctrl+0",action:"Type kana"})
      var labels=children(help).filter(function(node){return node.visible&&typeof node.text==="string"})
      var text=labels.map(function(node){return node.text}).join(" ")
      verify(text.indexOf("Reviews test")>=0);verify(text.indexOf("Lessons introduce")>=0)
      for(var name of ["Settings → Audio","Settings → Reminders","Settings → Desktop","open panel"])verify(text.indexOf(name)>=0,name)
      for(var label of labels)if(label.textFormat!==undefined){verify(!label.truncated,label.text);verify(label.contentWidth<=label.width+1,label.text)}
      help.focusInput();keyClick(Qt.Key_Space);compare(helpOwner.closed,1);compare(root.navigationSequence,0)
    }
  }
}
'''


def build(directory):
    panel = (ROOT / "Panel.qml").read_text()
    def function(name):
        match = re.search(r"(?ms)^  function " + name + r"\(.*?(?=^  function )", panel)
        if not match:
            raise AssertionError("Panel function boundary changed: " + name)
        return match.group(0)
    start = panel.index('      Repeater {\n        model: ["dashboard", "study", "lookup"')
    end = panel.index('\n      ColumnLayout {', start)
    shortcuts = panel[start:end]
    if 'sequence: "Ctrl+0"' not in shortcuts:
        raise AssertionError("The new shortcut is missing from the actual navigation block")
    foundation.build(directory)
    (directory / "tst_LessonFlow.qml").unlink()
    shutil.copyfile(ROOT / "qml/ShortcutHelp.qml", directory / "qml/ShortcutHelp.qml")
    (directory / "tst_PanelShortcuts.qml").write_text(QML.replace("__FUNCTIONS__",function("isTextEditor")+function("navigate")).replace("__SHORTCUTS__",shortcuts))


@unittest.skipUnless(RUNNER.is_file() and (foundation.NATIVE / "Button.qml").is_file(), "Native Qt controls required")
class PanelShortcutsTests(unittest.TestCase):
    def test_source_shortcuts_native_keys_and_help(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-panel-shortcuts-") as temporary:
            directory = Path(temporary);build(directory)
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True,text=True,timeout=25,env={**os.environ,"QT_QPA_PLATFORM":"offscreen",
                    "QT_QPA_PLATFORMTHEME":"","QT_QUICK_CONTROLS_STYLE":"Basic","QML_DISABLE_DISK_CACHE":"1"})
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertNotIn("QWARN",result.stdout+result.stderr)


if __name__ == "__main__":
    unittest.main()
