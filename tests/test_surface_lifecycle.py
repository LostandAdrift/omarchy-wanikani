"""Exercise actual QML behavior with inert controls/services, without a shell.

Quickshell types need its running host. These fixtures copy each production
component's behavior prefix unchanged, remove presentation-only imports/styles,
and supply small input/glyph/audio stubs. They do not claim native keys or IME.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path('/usr/lib/qt6/bin/qmltestrunner')


def build_surfaces(directory):
    for name in ('Recovery', 'Practice', 'VoiceChoices', 'Lookup', 'Study'):
        original = (ROOT / 'qml' / (name + '.qml')).read_text()
        source = original.split('\n  Label {', 1)[0]
        if source == original:
            raise AssertionError('Review behavior fixture boundary for ' + name)
        source = re.sub(r'^import (?:qs\..*|"../vendor/.*)\n', '', source, flags=re.M)
        source = re.sub(r'^  (?:spacing:|readonly property color subjectColor:).*\n', '', source, flags=re.M)
        if name in ('Practice', 'Lookup'):
            source += '\n  QtObject { id: searchField; property string text: root.controller.query || ""; function forceActiveFocus() {} }\n'
            source += '  property alias searchText: searchField.text\n'
            timer = re.search(r'(?ms)^  Timer \{\n    id: searchDelay.*?^  \}', original)
            if not timer:
                raise AssertionError('The search timer must be included in the behavior fixture')
            source += timer.group(0) + '\n'
        if name == 'Study':
            source = source.replace('import QtQuick\n', 'import QtQuick\nimport "WanaKana.mjs" as Kana\n', 1)
            source += '''
  QtObject { id: input; property string text: ""; property int cursorPosition: 0; property bool inputMethodComposing: false; function forceActiveFocus() {} }
  QtObject { id: subjectCard; function forceActiveFocus() {} }
  QtObject { id: returnToWork; function forceActiveFocus() {} }
  QtObject { id: subjectGlyph; property bool displayReady: true; property bool displayLoading: false }
  property alias glyphReady: subjectGlyph.displayReady
  property alias answerText: input.text
'''
        (directory / (name + 'Core.qml')).write_text(source + '}\n')
    panel = (ROOT / 'Panel.qml').read_text()
    def function(name):
        match = re.search(r'(?ms)^  function ' + name + r'\(.*?(?=^  function )', panel)
        if not match:
            raise AssertionError('Review Panel behavior fixture boundary for ' + name)
        return match.group(0)
    (directory / 'PanelCore.qml').write_text('''import QtQuick
import "WanaKana.mjs" as Kana
import "UnicodeText.mjs" as UnicodeText
Item {
 id: root
 required property var service
 property bool opened: true
 property string view: "lookup"
 property string query: ""
 property bool queryTruncated: false
 property var detail: null
 property var results: []
 property string searchType: "all"
 property string searchState: "all"
 property int searchSequence: 0
 property bool searching: false
 property var session: null
 property int audioSequence: 0
 property int navigationSequence: 0
 property string contentAccess: "fixture"
 property string audioContext: ""
 property int audioSubjectId: -1
 property string audioState: ""
 property string audioNotice: ""
 readonly property int playCount: audio.count
 QtObject { id: audio; property var source; property int count: 0; function play() { count++ } function stop() {} }
''' + function('audioContextCurrent') + function('requestAudio') + function('play') + function('testVoice') + function('stopAudio') + function('search') + function('refreshSearch') + '}\n')
    shutil.copyfile(ROOT / 'vendor/WanaKana.mjs', directory / 'WanaKana.mjs')
    shutil.copyfile(ROOT / 'qml/UnicodeText.mjs', directory / 'UnicodeText.mjs')
    shutil.copyfile(ROOT / 'qml/Theme.mjs', directory / 'Theme.mjs')
    shutil.copyfile(ROOT / 'tests/fixtures/SurfaceLifecycle.qml', directory / 'tst_SurfaceLifecycle.qml')


class SurfaceLifecycleTests(unittest.TestCase):
    def test_source_derived_qml_lifecycle(self):
        if not RUNNER.is_file():
            self.skipTest('QtTest runner is not installed')
        with tempfile.TemporaryDirectory(prefix='wanikani-surface-tests-') as temporary:
            directory = Path(temporary)
            build_surfaces(directory)
            result = subprocess.run([str(RUNNER), '-input', str(directory)], capture_output=True, text=True, timeout=40,
                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QPA_PLATFORMTHEME': '', 'QT_QUICK_CONTROLS_STYLE': 'Basic'})
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertNotIn('QWARN', output, output)
        self.assertRegex(output, r'Totals: \d+ passed, 0 failed', output)


if __name__ == '__main__':
    unittest.main()
