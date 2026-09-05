#!/usr/bin/env python3
"""Reversible per-user launcher and Hyprland integration. Never replaces a binding."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ID = "io.github.lostandadrift.wanikani"
START = "-- BEGIN " + ID
END = "-- END " + ID
BLOCK = re.compile(r"\n?" + re.escape(START) + r"\n.*?" + re.escape(END) + r"\n?", re.S)
SHORTCUTS = [("SUPER + ALT + W", 72, "resume", "WaniKani study"),
             ("SUPER + ALT + SHIFT + W", 73, "lookup", "WaniKani selection lookup")]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def binding_line(key, action, label):
    return f'o.bind("{key}", "{label}", "omarchy-shell wanikani {action}")'


def live_conflict(live, text, key, mask, action, label):
    """Lua bindings hide their command behind a numeric __lua callback ID.

    Trust its description only alongside the exact command in our marked block.
    A duplicate live binding or an unmarked namesake remains a conflict.
    """
    matches = [b for b in live if str(b.get("key", "")).upper() == "W"
               and b.get("modmask") == mask]
    owned = any(binding_line(key, action, label) in block.splitlines()
                for block in BLOCK.findall(text))
    if not matches:
        return False
    if not owned or len(matches) != 1:
        return True
    binding = matches[0]
    return not (binding.get("arg") == "omarchy-shell wanikani " + action
                or (binding.get("dispatcher") == "__lua"
                    and binding.get("description") == label))


def apply_bindings(bindings, updated, original, runtime):
    if updated == original:
        return
    existed = bindings.exists()
    bindings.parent.mkdir(parents=True, exist_ok=True)
    bindings.write_text(updated)
    if not runtime:
        return
    try:
        subprocess.run(["hyprctl", "reload"], check=True, timeout=8)
        errors = subprocess.check_output(["hyprctl", "configerrors"], timeout=8).decode().strip()
        if errors and errors not in ("ok", "[]"):
            raise RuntimeError("Hyprland reported configuration errors: " + errors)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        if existed:
            bindings.write_text(original)
        else:
            bindings.unlink(missing_ok=True)
        subprocess.run(["hyprctl", "reload"], timeout=8, check=False)
        raise RuntimeError("Bindings restored; desktop integration was not applied. " + str(error)) from error


def integrate(home, source, remove=False, runtime=True):
    state = home / ".local/state/omarchy/wanikani"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = state / "integration.json"
    previous = json.loads(journal.read_text()) if journal.exists() else {"files": {}}
    bindings = home / ".config/hypr/bindings.lua"
    text = bindings.read_text() if bindings.exists() else ""
    cleaned = BLOCK.sub("\n", text)
    messages = []
    # Older installs saved the backup path without the original bytes. Migrate
    # even when every key is occupied, or removal is the first operation.
    backup_path = Path(previous.get("bindings_backup", ""))
    if "bindings_original" not in previous and backup_path.is_file():
        previous["bindings_original"] = backup_path.read_text()
    if remove:
        if cleaned != text:
            original = previous.get("bindings_original")
            updated = original if original is not None and digest(text) == previous.get("bindings_installed") else cleaned
            apply_bindings(bindings, updated, text, runtime)
        for path, expected in previous.get("files", {}).items():
            item = Path(path)
            if item.exists() and digest(item.read_text()) == expected:
                item.unlink()
                messages.append("Removed " + str(item))
            elif item.exists():
                messages.append("Preserved edited file " + str(item))
        journal.unlink(missing_ok=True)
    else:
        live = []
        if runtime:
            try:
                live = json.loads(subprocess.check_output(["hyprctl", "binds", "-j"], timeout=5))
            except (OSError, subprocess.SubprocessError, ValueError):
                messages.append("Could not inspect live bindings; shortcuts skipped. Launcher entries remain available.")
                live = None
        existing = set()
        for key in re.findall(r'o\.bind\(\s*["\']([^"\']+)', cleaned):
            existing.add(tuple(sorted(p.strip().upper() for p in key.split("+"))))
        lines = []
        for key, mask, action, label in SHORTCUTS:
            occupied = tuple(sorted(p.strip() for p in key.split("+"))) in existing
            if live is not None:
                occupied = occupied or live_conflict(live, text, key, mask, action, label)
            if occupied or live is None:
                messages.append("Preserved existing shortcut / skipped " + key)
            else:
                lines.append(binding_line(key, action, label))
        if lines:
            bindings.parent.mkdir(parents=True, exist_ok=True)
            if text and not previous.get("bindings_backup"):
                backup = state / ("bindings-before-" + str(int(time.time())) + ".lua")
                backup.write_text(text)
                previous["bindings_backup"] = str(backup)
            previous.setdefault("bindings_original", text)
            updated = cleaned.rstrip() + "\n\n" + START + "\n" + "\n".join(lines) + "\n" + END + "\n"
            apply_bindings(bindings, updated, text, runtime)
            previous["bindings_installed"] = digest(updated)
        applications = home / ".local/share/applications"
        applications.mkdir(parents=True, exist_ok=True)
        owned = previous.get("files", {})
        for action, name in [("resume", "WaniKani Study"), ("lookup", "WaniKani Lookup")]:
            destination = applications / f"{ID}.{action}.desktop"
            entry = f"[Desktop Entry]\nType=Application\nName={name}\nComment=Five reviews, then back to work\nExec=omarchy-shell wanikani {action}\nIcon={source / 'assets/wanikani.svg'}\nTerminal=false\nCategories=Education;Languages;\nKeywords=Japanese;Kanji;Lessons;Reviews;WaniKani;\n"
            if destination.exists() and str(destination) not in owned and destination.read_text() != entry:
                messages.append("Preserved existing launcher " + str(destination))
                continue
            if destination.exists() and str(destination) in owned and digest(destination.read_text()) != owned[str(destination)]:
                messages.append("Preserved edited launcher " + str(destination))
                continue
            destination.write_text(entry)
            owned[str(destination)] = digest(entry)
            messages.append("Installed " + str(destination))
        previous["files"] = owned
        journal.write_text(json.dumps(previous, indent=2) + "\n")
        journal.chmod(0o600)
    return messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "remove", "check"])
    args = parser.parse_args()
    if args.action == "check":
        required = ["python3", "omarchy-shell", "wl-paste"]
        optional = ["secret-tool", "hyprctl"]
        missing = [tool for tool in required if not shutil.which(tool)]
        for tool in required + optional:
            print(tool + ": " + (shutil.which(tool) or "missing"))
        return bool(missing)
    for message in integrate(Path.home(), Path(__file__).resolve().parents[1], remove=args.action == "remove"):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
