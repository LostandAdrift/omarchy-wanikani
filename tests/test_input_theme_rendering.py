"""Actual learning pages and installed native inputs under custom popup palettes.

Backend, audio, notification and unrelated presentation adapters are inert.
Native TextField, NumberField and Button are copied without modifications.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_theme_rendering as foundation

ROOT=Path(__file__).resolve().parents[1]
RUNNER=Path('/usr/lib/qt6/bin/qmltestrunner')
NATIVE=Path('/usr/share/omarchy/shell/Ui')

QML=r'''
import QtQuick
import QtTest
import qs.Commons
import "qml" as Kani
import "qml/Theme.mjs" as Theme
Rectangle {
  id: surface
  width:700;height:4800
  color:"#ffffff"
  readonly property color kaniSurface: color
  property color kaniText:"#222222"
  property var page:null
  Component { id: settingsPage; Kani.Settings { width:460;controller:owner } }
  Component { id: studyPage; Kani.Study { width:460;controller:owner } }
  Component { id: lookupPage; Kani.Lookup { width:460;controller:owner } }
  Component { id: detailsPage; Kani.SubjectDetails { width:460;controller:owner;subject:owner.subject;editable:true } }
  Component { id: rhythmPage; Kani.StudyRhythm { width:460;controller:owner } }
  QtObject {
    id: backend
    property bool ready:true
    property bool locked:false
    property bool animations:false
    property var snapshot:({})
    property var writes:[]
    property var rhythm:({config:{enabled:true,mode:"times",target:"both",times:["10:00","14:00","18:00"],
      interval_hours:2,window_start:"08:00",window_end:"22:00",quiet_start:"22:00",quiet_end:"08:00",
      minimum_interval_seconds:7200,daily_limit:3,recent_study_seconds:1800},next_at:null,reason:"Authored reminder"})
    function request(method,args,callback) { writes=writes.concat([{method:method,args:args}]);if(callback)callback(true,{dirty:true},"") }
    function saveSettings(values) { writes=writes.concat([{method:"settings",args:values}]) }
    function previewRhythm(patch,callback) { if(callback)callback(true,rhythm,"") }
    function configureRhythm(patch,callback) { if(callback)callback(true,rhythm,"") }
  }
  QtObject {
    id: owner
    property var service:backend
    property bool opened:true
    property bool busy:false
    property var snapshot:backend.snapshot
    property var subject:({})
    property var session:({})
    property var detail:null
    property string contentAccess:"authored"
    property string query:""
    property bool queryTruncated:false
    property string searchType:"all"
    property string searchState:"all"
    property bool searching:false
    property int searchSequence:0
    property var results:[]
    property string error:""
    property string audioContext:""
    property string audioState:""
    property int audioSubjectId:-1
    property string audioNotice:""
    property string integrationNotice:""
    property var actions:[]
    function search(text) { query=text }
    function setSearchFilter(type,state) { searchType=type;searchState=state }
    function studyAction(method,args) { actions=actions.concat([{method:method,args:args}]) }
    function call(method,args,callback) { if(callback)callback(false,null) }
    function stopAudio() {}
    function play(subject) {}
    function begin() {}
    function navigate() {}
    function dismiss() {}
  }
  TestCase {
    name:"InputTheme";when:windowShown
    function init() {
      surface.color="#ffffff";surface.kaniText="#222222"
      Color.background="#111111";Color.foreground="#ffffff";Color.accent="#aaaaaa"
      owner.opened=true;owner.busy=false;owner.detail=null;owner.query="";owner.actions=[]
      owner.searchType="all";owner.searchState="all";owner.searching=false
      backend.writes=[]
      backend.snapshot={connected:true,demo:false,username:"Authored",credential_storage:"session",syncing:false,
        settings:{batch_size:5,cache_limit_mb:256,autoplay_audio:false,autoplay_lessons:false,autoplay_listening:true},
        pending:0,attention:0,outbox_total:0,cache:{subjects:5,files:0,bytes:0}}
      owner.subject={id:1,type:"vocabulary",characters:"火山",level:1,images:[],meanings:["Volcano"],
        readings:[{reading:"かざん",type:"onyomi"}],material:{meaning_synonyms:[],meaning_note:"",reading_note:""},
        components:[],related:[],sentences:[],meaning_mnemonic:"",meaning_hint:"",reading_mnemonic:"",reading_hint:"",audio_available:false}
      owner.session={id:"authored-session",mode:"reviews",phase:"question",part:"meaning",revision:1,subject:owner.subject,
        draft:"",index:0,total:5,completed:0,lesson_index:0,feedback:null,summary:{},finishing:false,invalidated:"",errors:0,overrides:0}
    }
    function cleanup() { if(page){page.destroy();page=null};wait(0) }
    function make(component) { page=component.createObject(surface);verify(page!==null);verify(waitForRendering(page));return page }
    function allItems(parent) {
      var result=[parent]
      for(var i=0;i<parent.children.length;i++)result=result.concat(allItems(parent.children[i]))
      return result
    }
    function field(name) { var item=findChild(page,name);verify(item!==null,name);return item }
    function palettes() { return [["#ffffff","#eeeeee"],["#111111","#181818"],["#777777","#777777"],["#123455","#eedddd"]] }
    function keyClicks(text) { for(var character of text) keyClick(character) }
    function contrast(input) {
      compare(String(input.surfaceColor),String(surface.kaniSurface))
      verify(Theme.contrast(input.color,input.renderedSurface)>=4.5,"Entered text contrast")
      verify(Theme.contrast(input.placeholderTextColor,input.renderedSurface)>=4.5,"Placeholder contrast")
      verify(Theme.contrast(input.selectedTextColor,Theme.composite(input.selectionColor,input.renderedSurface))>=4.5,"Selected text contrast")
    }
    function checkColors(fields) {
      for(var colors of palettes()) {
        surface.color=colors[0];surface.kaniText=colors[1];Color.foreground=colors[0]
        for(var input of fields) {
          input.forceActiveFocus();contrast(input)
          input.selectAll();contrast(input)
        }
      }
    }
    function test_study_native_input_keeps_typing_accept_and_readonly_feedback() {
      make(studyPage)
      var input=field("study-answer")
      checkColors([input])
      input.forceActiveFocus()
      keyClicks("volcano")
      compare(input.text,"volcano")
      keyClick(Qt.Key_Return)
      compare(owner.actions.length,1)
      compare(owner.actions[0],{method:"answer",args:{text:"volcano"}})
      owner.session=Object.assign({},owner.session,{phase:"feedback",feedback:{correct:true,accepted:["Volcano"],message:"Correct",retry:false}})
      wait(0)
      verify(input.readOnly)
      input.forceActiveFocus();keyClicks("extra")
      compare(input.text,"")
    }
    function test_lookup_filters_announce_checked_state() {
      make(lookupPage)
      checkColors([field("lookup-search")])
      var filters=allItems(page).filter(function(item){return item.text==="Kanji"&&item.accessibleHint==="Filter catalogue by subject type"})
      compare(filters.length,1)
      var kanji=filters[0]
      verify(kanji.Accessible.checkable)
      verify(!kanji.Accessible.checked)
      kanji.forceActiveFocus();keyClick(Qt.Key_Space)
      compare(owner.searchType,"kanji")
      verify(kanji.Accessible.checked)
    }
    function test_editor_text_and_note_selection_follow_actual_popup() {
      make(detailsPage)
      var synonym=field("subject-synonyms")
      var meaning=field("editor-meaning-note")
      var reading=field("editor-reading-note")
      checkColors([synonym,meaning,reading])
      meaning.forceActiveFocus();keyClicks("An authored note")
      compare(meaning.text,"An authored note")
      verify(backend.writes.some(function(write){return write.method==="editor_draft"&&write.args.values.meaning_note==="An authored note"}))
      verify(Theme.contrast(meaning.background.border.color,meaning.renderedSurface)>=3)
      compare(meaning.Accessible.name,"Meaning note")
    }
    function test_settings_inputs_field_names_and_local_listening_autoplay() {
      make(settingsPage)
      page.showDeletion=true
      checkColors([field("settings-token"),field("settings-delete-confirmation")])
      compare(field("settings-token").echoMode,TextInput.Password)
      compare(field("settings-batch-size").field.Accessible.name,"Subjects in each study batch")
      compare(field("settings-cache-limit").field.Accessible.name,"Media cache limit in megabytes")
      var toggles=allItems(page).filter(function(item){return item.accessibleName==="Autoplay new listening prompts"})
      compare(toggles.length,1)
      verify(toggles[0].Accessible.checked)
      toggles[0].forceActiveFocus();keyClick(Qt.Key_Space)
      compare(backend.writes[0],{method:"settings",args:{autoplay_listening:false}})
      verify(allItems(page).some(function(item){return typeof item.text==="string"&&item.text.indexOf("Resuming a saved session")>=0}))
      verify(allItems(page).some(function(item){return typeof item.text==="string"&&item.text.indexOf(@VERSION@)>=0}))
      compare(owner.actions.length,0)
    }
    function test_rhythm_times_windows_quiet_fields_and_numbers() {
      make(rhythmPage)
      page.extra=true
      checkColors([field("rhythm-times"),field("rhythm-window-start"),field("rhythm-window-end"),field("rhythm-quiet-start"),field("rhythm-quiet-end")])
      compare(field("rhythm-interval").field.Accessible.name,"Hours between daytime opportunities")
      compare(field("rhythm-daily-limit").field.Accessible.name,"Maximum reminders per local day")
      compare(field("rhythm-minimum-gap").field.Accessible.name,"Minimum minutes between unsolicited reminders")
    }
  }
}
'''


@unittest.skipUnless(RUNNER.is_file() and (NATIVE/'TextField.qml').is_file(),'Qt and native Omarchy input controls required')
class InputThemeRenderingTests(unittest.TestCase):
    def test_actual_inputs_under_alternate_popup_palettes(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-input-theme-') as temporary:
            directory=Path(temporary);qml=directory/'qml';qml.mkdir()
            for name in ('Study','Lookup','SubjectDetails','Settings','StudyRhythm','Label','Card','Action','ActivationGuard','SubjectGlyph','JapaneseText','RadicalImage'):
                content=(ROOT/'qml'/(name+'.qml')).read_text().replace('import Quickshell\n','')
                (qml/(name+'.qml')).write_text(content)
            for name in ('Theme.mjs','UnicodeText.mjs'):
                shutil.copyfile(ROOT/'qml'/name,qml/name)
            vendor=directory/'vendor';vendor.mkdir();shutil.copyfile(ROOT/'vendor/WanaKana.mjs',vendor/'WanaKana.mjs')
            for name,properties in {
                'Crab':'property bool animate:false;property bool celebrating:false',
                'SessionRecap':'property var controller;property var session',
                'Pronunciation':'property var controller;property var subject',
                'KanjiExamples':'property var controller;property var subject',
                'Lookalikes':'property var subject;property bool showMeaning;property bool showReading',
                'ReadingTrail':'property var controller',
                'VoiceChoices':'property var controller',
                'OfflineStatus':'property var controller'}.items():
                (qml/(name+'.qml')).write_text('import QtQuick\nItem {'+properties+'}\n')
            common=directory/'qs/Commons';common.mkdir(parents=True)
            (common/'qmldir').write_text('module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\nsingleton Border 1.0 Border.qml\n')
            style=foundation.STYLE.replace('controlGap:6','controlGap:6,inputPaddingY:8,md:8,controlHeight:34,numberFieldWidth:100')
            style=style.replace('bodySmall:12','bodySmall:12,title:20')
            style=style.replace('  function selectedStateColor', '''  function controlFill(focused,hot,foreground,accent) { return Qt.alpha(foreground,focused?.12:.04) }
  function selectionFillFor(foreground,accent) { return Qt.alpha(accent,.65) }
  function selectedStateColor''')
            (common/'Style.qml').write_text(style)
            (common/'Border.qml').write_text(foundation.BORDER)
            (common/'Color.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject {property color background:"#111111";property color foreground:"#ffffff";property color accent:"#aaa";property color urgent:"#900";property var tooltip:({background:"#fff",text:"#000",border:"#000"})}\n')
            ui=directory/'qs/Ui';ui.mkdir()
            (ui/'qmldir').write_text('module qs.Ui\nButton 1.0 Button.qml\nTextField 1.0 TextField.qml\nNumberField 1.0 NumberField.qml\nBorderSurface 1.0 BorderSurface.qml\n')
            for name in ('Button','TextField','NumberField'):
                shutil.copyfile(NATIVE/(name+'.qml'),ui/(name+'.qml'))
            (ui/'BorderSurface.qml').write_text('import QtQuick\nRectangle {property var borderSpec:({});property real leftPadding:0;property real rightPadding:0;property real topPadding:0;property real bottomPadding:0}\n')
            version=json.loads((ROOT/'manifest.json').read_text())["version"]
            (directory/'tst_InputTheme.qml').write_text(QML.replace('@VERSION@',json.dumps(version)))
            result=subprocess.run([str(RUNNER),'-input',str(directory),'-import',str(directory)],capture_output=True,text=True,timeout=35,
                env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
        output=result.stdout+result.stderr
        self.assertEqual(result.returncode,0,output)
        self.assertNotIn('QWARN',output)


if __name__=='__main__':
    unittest.main()
