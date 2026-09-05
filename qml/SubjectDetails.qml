import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui as Ui

ColumnLayout {
  id: root
  required property var subject
  required property var controller
  property bool showMeaning: true
  property bool showReading: true
  property bool editable: false
  spacing: Style.space(12)
  Label { Layout.fillWidth:true; visible:root.showMeaning; text:root.subject ? root.subject.meanings.join(" · ") : ""; font.pixelSize:Style.font.title; color:Color.accent }
  Label { Layout.fillWidth:true; visible:root.showReading; text:root.subject ? root.subject.readings.map(function(r){return r.reading + (r.type ? " (" + r.type + ")" : "")}).join(" · ") : ""; font.family:"Noto Sans CJK JP" }
  Label { Layout.fillWidth:true; visible:root.showMeaning; text:root.subject ? root.subject.meaning_mnemonic : "" }
  Label { Layout.fillWidth:true; visible:root.showMeaning && text !== ""; text:root.subject ? root.subject.meaning_hint : ""; color:Color.muted }
  Label { Layout.fillWidth:true; visible:root.showReading; text:root.subject ? root.subject.reading_mnemonic : "" }
  Label { Layout.fillWidth:true; visible:root.showReading && text !== ""; text:root.subject ? root.subject.reading_hint : ""; color:Color.muted }
  RowLayout {
    visible: root.showReading && root.subject && root.subject.audio_available
    Action { text: "Play pronunciation"; enabled: root.subject && root.subject.audio.length > 0; onClicked: root.controller.play(root.subject) }
    Label { text: root.subject && root.subject.audio.length ? "Cached for offline use" : "Audio not cached yet"; color:Color.muted;font.pixelSize:Style.font.bodySmall }
  }
  Repeater {
    model: root.showMeaning && root.showReading && root.subject ? root.subject.sentences : []
    ColumnLayout {
      required property var modelData
      Layout.fillWidth: true
      Label { Layout.fillWidth:true;text:modelData.ja;font.family:"Noto Sans CJK JP" }
      Label { Layout.fillWidth:true;text:modelData.en;color:Color.muted;font.pixelSize:Style.font.bodySmall }
    }
  }
  Label { text:"Made from"; font.bold:true;visible:root.showMeaning && root.subject && root.subject.components.length > 0 }
  Flow {
    Layout.fillWidth:true;spacing:Style.space(6);visible:root.showMeaning
    Repeater { model:root.subject ? root.subject.components : []; Action { required property var modelData; text:modelData.characters + " · " + modelData.meaning; enabled:root.editable;onClicked:root.controller.showSubject(modelData.id) } }
  }
  Label { text:"Related subjects";font.bold:true;visible:root.editable && root.subject && root.subject.related.length > 0 }
  Flow {
    Layout.fillWidth:true;spacing:Style.space(6);visible:root.editable
    Repeater { model:root.subject ? root.subject.related : []; Action {required property var modelData;text:modelData.characters + " · " + modelData.meaning;onClicked:root.controller.showSubject(modelData.id)} }
  }
  ColumnLayout {
    Layout.fillWidth:true;visible:root.editable;spacing:Style.space(9)
    Label { text:"Your study material";font.bold:true }
    Label { Layout.fillWidth:true;text:root.subject && root.subject.material_pending ? "Your local edit is waiting to sync." : "Synonyms and notes synchronize with WaniKani. Separate synonyms with commas.";color:Color.muted;font.pixelSize:Style.font.bodySmall }
    Ui.TextField { id:synonyms;Layout.fillWidth:true;placeholderText:"Meaning synonyms, separated by commas";text:root.subject ? (root.subject.material.meaning_synonyms || []).join(", ") : "";Accessible.name:"Meaning synonyms" }
    Controls.TextArea {
      id:meaningNote;Layout.fillWidth:true;Layout.preferredHeight:Style.space(90)
      text:root.subject ? root.subject.material.meaning_note || "" : "";placeholderText:"Your meaning note"
      color:Color.foreground;placeholderTextColor:Color.muted;font.family:Style.font.family;font.pixelSize:Style.font.body;wrapMode:TextEdit.Wrap
      background:Rectangle {color:Qt.alpha(Color.foreground,0.04);border.color:meaningNote.activeFocus ? Color.accent : Color.muted;radius:Style.cornerRadius}
      Accessible.name:"Meaning note"
    }
    Controls.TextArea {
      id:readingNote;Layout.fillWidth:true;Layout.preferredHeight:Style.space(90)
      text:root.subject ? root.subject.material.reading_note || "" : "";placeholderText:"Your reading note"
      color:Color.foreground;placeholderTextColor:Color.muted;font.family:Style.font.family;font.pixelSize:Style.font.body;wrapMode:TextEdit.Wrap
      background:Rectangle {color:Qt.alpha(Color.foreground,0.04);border.color:readingNote.activeFocus ? Color.accent : Color.muted;radius:Style.cornerRadius}
      Accessible.name:"Reading note"
    }
    Action {
      text:"Save notes & synonyms";enabled:!root.controller.busy && root.subject && !root.subject.material_pending
      onClicked:root.controller.call("set_material",{subject_id:root.subject.id,values:{meaning_synonyms:synonyms.text.split(",").map(function(s){return s.trim()}).filter(function(s){return s.length>0}),meaning_note:meaningNote.text,reading_note:readingNote.text}},function(ok,data){if(ok) root.controller.detail=data})
    }
  }
}
