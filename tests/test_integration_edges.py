"""Desktop integration runs against a temporary home and mocked Hyprland only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from integrate import ID, START, SHORTCUTS, digest, integrate


class IntegrationEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bindings = self.home / ".config/hypr/bindings.lua"
        self.bindings.parent.mkdir(parents=True)
        self.original = '-- My bindings\no.bind("SUPER + B", "Browser", "browser")\n'
        self.bindings.write_text(self.original)
        self.journal = self.home / ".local/state/omarchy/wanikani/integration.json"

    def hyprland(self, live, errors=b""):
        def output(command, **_):
            if command == ["hyprctl", "binds", "-j"]:
                return json.dumps(live).encode()
            if command == ["hyprctl", "configerrors"]:
                return errors
            raise AssertionError(command)
        self.addCleanup(patch.stopall)
        patch("integrate.subprocess.check_output", side_effect=output).start()
        return patch("integrate.subprocess.run").start()

    def lua_bindings(self):
        return [{"key": "W", "modmask": mask, "dispatcher": "__lua",
                 "arg": str(index), "description": label}
                for index, (_, mask, _, label) in enumerate(SHORTCUTS, start=701)]

    def test_reinstall_recognizes_own_marked_lua_callbacks(self):
        integrate(self.home, ROOT, runtime=False)
        installed = self.bindings.read_text()
        self.hyprland(self.lua_bindings())
        messages = integrate(self.home, ROOT)
        self.assertEqual(installed, self.bindings.read_text())
        self.assertFalse(any("skipped" in message for message in messages))
        self.assertEqual(1, installed.count(START))
        integrate(self.home, ROOT, remove=True)
        self.assertEqual(self.original, self.bindings.read_text())

    def test_matching_description_without_marked_source_is_not_ownership(self):
        self.hyprland(self.lua_bindings())
        integrate(self.home, ROOT)
        self.assertEqual(self.original, self.bindings.read_text())

    def test_other_live_callback_sharing_a_key_is_preserved(self):
        integrate(self.home, ROOT, runtime=False)
        live = self.lua_bindings()
        live.append({"key": "W", "modmask": 72, "dispatcher": "__lua",
                     "arg": 999, "description": "Existing user action"})
        self.hyprland(live)
        messages = integrate(self.home, ROOT)
        self.assertNotIn("wanikani resume", self.bindings.read_text())
        self.assertIn("wanikani lookup", self.bindings.read_text())
        self.assertTrue(any("skipped SUPER + ALT + W" in message for message in messages))

    def test_legacy_backup_migrates_when_no_new_lines_are_added(self):
        integrate(self.home, ROOT, runtime=False)
        previous = json.loads(self.journal.read_text())
        previous.pop("bindings_original")
        self.journal.write_text(json.dumps(previous))
        self.hyprland([{"key": "W", "modmask": mask, "description": "Another action"}
                       for _, mask, _, _ in SHORTCUTS])
        integrate(self.home, ROOT)
        migrated = json.loads(self.journal.read_text())
        self.assertEqual(self.original, migrated["bindings_original"])

    def test_legacy_backup_is_restored_when_removal_is_first_action(self):
        integrate(self.home, ROOT, runtime=False)
        previous = json.loads(self.journal.read_text())
        previous.pop("bindings_original")
        self.journal.write_text(json.dumps(previous))
        integrate(self.home, ROOT, remove=True, runtime=False)
        self.assertEqual(self.original, self.bindings.read_text())

    def test_invalid_reload_restores_bindings_before_writing_launchers_or_journal(self):
        self.hyprland([], errors=b"configuration error in test fixture")
        with self.assertRaisesRegex(RuntimeError, "Bindings restored"):
            integrate(self.home, ROOT)
        self.assertEqual(self.original, self.bindings.read_text())
        self.assertFalse(self.journal.exists())
        self.assertEqual([], list(self.home.glob(".local/share/applications/*.desktop")))

    def test_failed_live_inspection_preserves_bindings_but_installs_launchers(self):
        with patch("integrate.subprocess.check_output", side_effect=subprocess.TimeoutExpired("hyprctl", 5)):
            integrate(self.home, ROOT)
        self.assertEqual(self.original, self.bindings.read_text())
        self.assertEqual(2, len(list(self.home.glob(".local/share/applications/*.desktop"))))

    def test_foreign_launcher_is_never_claimed_or_removed(self):
        launcher = self.home / ".local/share/applications" / f"{ID}.lookup.desktop"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("[Desktop Entry]\nName=My own launcher\n")
        integrate(self.home, ROOT, runtime=False)
        self.assertNotIn(str(launcher), json.loads(self.journal.read_text())["files"])
        integrate(self.home, ROOT, remove=True, runtime=False)
        self.assertEqual("[Desktop Entry]\nName=My own launcher\n", launcher.read_text())


if __name__ == "__main__":
    unittest.main()
