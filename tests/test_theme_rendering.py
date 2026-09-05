"""Real shared QML components and installed native Button, with inert shell adapters.

No shell is launched and no theme/configuration is changed. The optional stock
palette matrix reads colors.toml only; synthetic cases run on every platform.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
NATIVE_BUTTON = Path("/usr/share/omarchy/shell/Ui/Button.qml")

QML = r'''
import QtQuick
import QtTest
import qs.Commons
import "qml"
import "qml/Theme.mjs" as Theme

Item {
  width: 600
  height: 500
  Label { id: label; text: "Essential text" }
  Label { id: muted; y: 30; text: "Secondary text"; secondary: true }
  Card {
    id: card; y: 60; width: 200; height: 60
    Label { id: cardLabel; text: "Card content"; surfaceColor: card.color }
  }
  SubjectGlyph { id: glyph; x: 260; width: 180; height: 120; subject: ({id:1,characters:"火山",images:[]}); pixelSize: 72 }
  Action { id: action; y: 160; text: "Review 5"; onClicked: testCase.clicks += 1 }
  Rectangle {
    id: alternateSurface; y: 240; width: 580; height: 230
    color: "#112233"
    readonly property color kaniSurface: color
    property color kaniText: "#eeccaa"
    Item {
      Label { id: inheritedLabel; text: "Surface text" }
      Card {
        id: nestedCard; y: 30; width: 180; height: 160
        Label { id: nestedLabel; text: "Nested surface"; secondary: true }
        SubjectGlyph { id: nestedGlyph; y: 25; width: 180; height: 120; subject: ({id:2,characters:"山",images:[]}) }

      }
      SubjectGlyph { id: inheritedGlyph; x: 200; width: 170; height: 160; subject: ({id:3,characters:"かな",images:[]}) }
      SubjectGlyph { id: imageGlyph; x: 400; width: 120; height: 120;
        subject: ({id:4,slug:"Authored radical",characters:null,images:[Qt.resolvedUrl("radical.svg")]}) }
    }
  }
  Item { id: focusSink; y: 300; width: 1; height: 1 }
  TestCase {
    id: testCase
    name: "ThemeFoundation"
    when: windowShown
    property int clicks: 0
    property var palettes: __PALETTES__
    function init() {
      Color.background = "#faf4ed"
      Color.foreground = "#575279"
      Color.accent = "#56949f"
      alternateSurface.color = "#112233"
      alternateSurface.kaniText = "#eeccaa"
      glyph.surfaceColor = Qt.binding(function () { return Theme.surface(glyph.parent, Color.background) })
      glyph.glyphTextColor = Qt.binding(function () { return Theme.foreground(glyph.parent, Color.foreground) })
      label.textColor = Qt.binding(function () { return Color.foreground })
      label.surfaceColor = Qt.binding(function () { return Color.background })
      action.enabled = true
      action.selected = false
      action.hasCursor = false
      clicks = 0
      focusSink.forceActiveFocus()
    }
    function test_palette_roles_data() { return palettes }
    function test_palette_roles(data) {
      Color.background = data.background
      Color.foreground = data.foreground
      Color.accent = data.accent
      verify(Theme.contrast(label.color, Color.background) >= 4.5, data.tag + " primary")
      verify(Theme.contrast(findChild(glyph,"subject-japanese-text").color,Color.background)>=4.5,data.tag+" Japanese prompt")
      verify(Theme.contrast(muted.color, Color.background) >= 4.5, data.tag + " secondary")
      verify(Theme.contrast(action.foreground, Color.background) >= 4.5, data.tag + " action")
      verify(Theme.contrast(action.accent, Color.background) >= 4.5, data.tag + " accent")
      verify(Theme.contrast(cardLabel.color, card.color) >= 4.5, data.tag + " card")
      action.enabled = false
      compare(action.opacity, 1)
      verify(Theme.contrast(action.foreground, Color.background) >= 4.5, data.tag + " disabled")
      verify(Theme.contrast(Theme.indicator(Color.accent, card.color, Color.foreground), card.color) >= 3)
    }
    function test_nested_surface_roles_follow_live_override() {
      compare(String(inheritedLabel.surfaceColor), String(alternateSurface.color))
      compare(String(inheritedLabel.textColor), "#eeccaa")
      compare(String(nestedLabel.surfaceColor), String(nestedCard.kaniSurface))
      verify(Theme.contrast(nestedLabel.color, nestedCard.kaniSurface) >= 4.5)
      alternateSurface.color="#f0eedd"
      compare(String(inheritedLabel.surfaceColor), "#f0eedd")
      verify(Theme.contrast(inheritedLabel.color, alternateSurface.color) >= 4.5)
      verify(Theme.contrast(nestedLabel.color, nestedCard.kaniSurface) >= 4.5)
      alternateSurface.color="#112233"
    }
    function test_glyph_inherits_actual_popup_and_card_roles_live() {
      var inheritedText=findChild(inheritedGlyph,"subject-japanese-text")
      var nestedText=findChild(nestedGlyph,"subject-japanese-text")
      compare(String(inheritedGlyph.surfaceColor),String(alternateSurface.kaniSurface))
      compare(String(inheritedGlyph.glyphTextColor),String(alternateSurface.kaniText))
      compare(String(nestedGlyph.surfaceColor),String(nestedCard.kaniSurface))
      compare(String(nestedGlyph.glyphTextColor),String(nestedCard.kaniText))
      for(var colors of [["#ffffff","#eeeeee"],["#111111","#181818"],["#123455","#eedddd"]]) {
        alternateSurface.color=colors[0]
        alternateSurface.kaniText=colors[1]
        // Deliberately make the global palette wrong for this popup.
        Color.foreground=colors[0]
        verify(Theme.contrast(inheritedText.color,alternateSurface.kaniSurface)>=4.5)
        verify(Theme.contrast(nestedText.color,nestedCard.kaniSurface)>=4.5)
        compare(inheritedText.text,"かな")
        compare(nestedText.text,"山")
      }
      verify(waitForRendering(inheritedGlyph))
    }
    function test_glyph_explicit_roles_follow_live_base_palette_without_losing_override() {
      glyph.surfaceColor="#fff5ee"
      glyph.glyphTextColor="#eedddd"
      var text=findChild(glyph,"subject-japanese-text")
      verify(Theme.contrast(text.color,glyph.surfaceColor)>=4.5)
      Color.background="#080808"
      Color.foreground="#ffffff"
      verify(Theme.contrast(text.color,glyph.surfaceColor)>=4.5)
      compare(String(glyph.glyphTextColor),"#eedddd")
      glyph.glyphTextColor="#002244"
      compare(String(text.color),"#002244")
      compare(text.Accessible.name,"火山")
    }
    function test_radical_white_backing_and_neutral_alt_are_unchanged() {
      tryVerify(function () { return imageGlyph.displayReady })
      var image=findChild(imageGlyph,"radicalImage")
      verify(image!==null)
      compare(String(image.parent.color),"#ffffff")
      alternateSurface.color="#000000"
      alternateSurface.kaniText="#000000"
      compare(String(image.parent.color),"#ffffff")
      compare(image.Accessible.name,"Radical Authored radical")
      imageGlyph.revealLabel=false
      compare(image.Accessible.name,"Radical image, subject 4")
      imageGlyph.revealLabel=true
    }
    function test_good_colors_are_preserved() {
      compare(Theme.readable("#002244", "#ffffff", "#000000"), "#002244")
      compare(Theme.readable("#eeeeee", "#111111", "#ffffff"), "#eeeeee")
      compare(Theme.contrast("#000000", "#ffffff"), 21)
      compare(Theme.contrast("#123456", "#123456"), 1)
    }
    function test_opacity_regressions_and_composition() {
      verify(Theme.contrast(Qt.alpha(Color.foreground, .76), Color.background) < 4.5)
      verify(Theme.contrast(Theme.secondary(Color.foreground, Color.background), Color.background) >= 4.5)
      compare(Theme.composite(Qt.rgba(1, 1, 1, .5), "#000000"), "#808080")
      compare(Theme.composite("#80ffffff", "#000000"), "#808080")
      compare(Theme.composite("transparent", "#aabbcc"), "#aabbcc")
      var surface = Theme.composite(Qt.rgba(1, 1, 1, .8), "#101010")
      var text = Theme.readable(Qt.rgba(.7, .7, .7, .5), surface, "#222222")
      verify(Theme.contrast(text, surface) >= 4.5)
    }
    function test_actual_surface_override_survives_live_palette_change() {
      label.surfaceColor = "#fff5ee"
      label.textColor = "#eedddd"
      verify(Theme.contrast(label.color, label.surfaceColor) >= 4.5)
      Color.background = "#080808"
      Color.foreground = "#ffffff"
      verify(Theme.contrast(label.color, label.surfaceColor) >= 4.5)
      verify(Theme.contrast(muted.color, Color.background) >= 4.5)
      Color.background = "#ffffff"
      Color.foreground = "#000000"
      verify(Theme.contrast(muted.color, Color.background) >= 4.5)
      verify(Theme.contrast(cardLabel.color, card.color) >= 4.5)
    }
    function test_focus_outline_and_disabled_guard() {
      action.forceActiveFocus()
      var ring = findChild(action, "wanikani-action-focus")
      verify(ring !== null)
      verify(ring.visible)
      verify(Theme.contrast(ring.border.color, Theme.composite(action.color, action.surfaceColor)) >= 3)
      Color.accent = Color.background
      verify(Theme.contrast(ring.border.color, Theme.composite(action.color, action.surfaceColor)) >= 3)
      keyClick(Qt.Key_Return)
      compare(clicks, 1)
      action.enabled = false
      verify(!ring.visible)
      keyClick(Qt.Key_Return)
      compare(clicks, 1)
      mouseClick(action)
      compare(clicks, 1)
    }
    function test_native_selected_and_hover_style_stays_owned_by_shell() {
      action.selected = true
      tryCompare(action, "color", Qt.alpha(Color.foreground, .18))
      action.hasCursor = true
      tryCompare(action, "color", Qt.alpha(Color.foreground, .08))
      compare(action.radius, Style.cornerRadius)
      compare(action.fontFamily, Style.font.family)
    }
  }
}
'''

STYLE = '''pragma Singleton
import QtQuick
QtObject {
  property int cornerRadius: 6
  function space(value) { return value }
  property int normalBorderWidth: 1
  property var font: ({family:"Sans",body:14,icon:16,bodySmall:12})
  property var spacing: ({controlPaddingX:12,controlPaddingY:8,controlGap:6})
  function selectedStateColor(foreground, accent) { return Color.foreground }
  function focusFillFor(foreground, accent) { return Qt.alpha(Color.foreground,.08) }
  function hoverFillFor(foreground, accent) { return Qt.alpha(Color.foreground,.08) }
  function selectedFillFor(foreground, accent) { return Qt.alpha(Color.foreground,.18) }
  function pressedFillFor(foreground, accent) { return Qt.alpha(Color.foreground,.22) }
}
'''
BORDER = '''pragma Singleton
import QtQuick
QtObject {
  function none() { return {} }
  function top(spec) { return 1 }
  function right(spec) { return 1 }
  function bottom(spec) { return 1 }
  function left(spec) { return 1 }
  function controlSpec(state, foreground, accent) { return {} }
  function controlHasWidth(state) { return false }
  function localOrSurfaceSpec(a,b,c,d,e) { return {} }
}
'''


def palettes():
    values = [
        {"tag": "low contrast dark", "background": "#111111", "foreground": "#141414", "accent": "#181818"},
        {"tag": "low contrast light", "background": "#ffffff", "foreground": "#eeeeee", "accent": "#fafafa"},
        {"tag": "middle gray", "background": "#777777", "foreground": "#777777", "accent": "#777777"},
        {"tag": "saturated accent", "background": "#ffff00", "foreground": "#ffff88", "accent": "#ff00ff"},
    ]
    for path in sorted(Path("/usr/share/omarchy/themes").glob("*/colors.toml")):
        data = tomllib.loads(path.read_text())
        values.append({"tag": path.parent.name, "background": data["background"],
            "foreground": data["foreground"], "accent": data["accent"]})
    return values


@unittest.skipUnless(RUNNER.is_file() and NATIVE_BUTTON.is_file(), "Installed Qt and native Omarchy Button required")
class ThemeRenderingTests(unittest.TestCase):
    def test_contrast_roles_and_native_controls(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-theme-") as temporary:
            directory = Path(temporary)
            qml = directory / "qml"
            qml.mkdir()
            for name in ("Label.qml", "Card.qml", "Action.qml", "ActivationGuard.qml", "Theme.mjs", "SubjectGlyph.qml", "JapaneseText.qml", "RadicalImage.qml"):
                shutil.copyfile(ROOT / "qml" / name, qml / name)
            shutil.copyfile(ROOT / "tests/qml/fixtures/radical.svg", directory / "radical.svg")
            common = directory / "qs" / "Commons"
            common.mkdir(parents=True)
            (common / "qmldir").write_text("module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\nsingleton Border 1.0 Border.qml\n")
            (common / "Color.qml").write_text('pragma Singleton\nimport QtQuick\nQtObject {\n'
                ' property color background: "#faf4ed"\n property color foreground: "#575279"\n'
                ' property color accent: "#56949f"\n property var tooltip: ({background:"#fff",text:"#000",border:"#000"})\n}\n')
            (common / "Style.qml").write_text(STYLE)
            (common / "Border.qml").write_text(BORDER)
            ui = directory / "qs" / "Ui"
            ui.mkdir()
            (ui / "qmldir").write_text("module qs.Ui\nButton 1.0 Button.qml\nBorderSurface 1.0 BorderSurface.qml\n")
            shutil.copyfile(NATIVE_BUTTON, ui / "Button.qml")
            (ui / "BorderSurface.qml").write_text('import QtQuick\nRectangle {\n'
                ' property var borderSpec: ({})\n property real leftPadding: 0\n property real rightPadding: 0\n'
                ' property real topPadding: 0\n property real bottomPadding: 0\n}\n')
            (directory / "tst_Theme.qml").write_text(QML.replace("__PALETTES__", json.dumps(palettes())))
            result = subprocess.run([str(RUNNER), "-input", str(directory), "-import", str(directory)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                    "QT_QUICK_CONTROLS_STYLE": "Basic"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("QWARN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
