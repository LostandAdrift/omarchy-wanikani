#!/usr/bin/env python3
"""Isolated hosted QML QA. 'prepare' is local-only; 'run' installs a temporary plugin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

PRODUCTION_ID = "io.github.lostandadrift.wanikani"
QA_ID = re.compile(re.escape(PRODUCTION_ID) + r"\.qa\.[0-9a-f]{12}$")
RUNTIME_ROOTS = {"qml", "backend", "vendor", "assets"}
RUNTIME_FILES = {"manifest.json", "Service.qml", "Panel.qml", "LICENSE"}

# This wrapper exists only in the generated plugin. API and Secret Service are
# unavailable even if somebody opens Settings and leaves its fixture demo mode.
QA_WORKER = '''from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker

class NoAccountApi:
    def __init__(self, *args, **kwargs):
        pass
    def request(self, *args, **kwargs):
        raise worker.UserError("Native QA uses authored fixtures only; account access is disabled.")
    def collection(self, *args, **kwargs):
        raise worker.UserError("Native QA cannot access the network.")

class NoKeyring:
    may_have_written = False
    def get(self, *args):
        return None
    def set(self, *args):
        return False
    def delete(self, *args):
        return True

worker.Api = NoAccountApi
worker.Keyring = NoKeyring
if __name__ == "__main__":
    # The fixture path wins even if a caller omitted or replaced CLI arguments.
    sys.argv += ["--state-dir", QA_STATE]
    raise SystemExit(worker.main())
'''

# These methods are appended only to the generated Panel.qml. They invoke QML
# component actions and inspect actual rendered controls, not keyboard events.
QA_DRIVER = r'''
  property real qaWidth: 0
  property real qaHeight: 0
  property var qaCapture: ({})
  function qaItems() {
    var items = []
    function visit(item) {
      if (!item.visible) return
      if ((typeof item.clicked === "function" && typeof item.text === "string")
          || typeof item.inputMethodComposing === "boolean")
        items.push(item)
      for (var i = 0; i < item.children.length; i++) visit(item.children[i])
    }
    visit(frame)
    return items
  }
  function qaControl(selector) {
    var matches = qaItems().filter(function(item) {
      return (selector.text === undefined || item.text === selector.text)
        && (selector.placeholder === undefined || item.placeholderText === selector.placeholder)
        && (selector.editor !== true || typeof item.inputMethodComposing === "boolean")
    })
    if (selector.index === undefined && matches.length !== 1)
      throw new Error("Select exactly one QA control; matches=" + matches.length)
    var selected = matches[selector.index || 0]
    if (!selected) throw new Error("QA control not found")
    return selected
  }
  function qaSnapshot() {
    var controls = qaItems().map(function(item) {
      var point = item.mapToItem(frame, 0, 0)
      var ancestor = item
      while (ancestor && ancestor !== content.item) ancestor = ancestor.parent
      var viewportPoint = item.mapToItem(scroll, 0, 0)
      var inViewport = !ancestor || (viewportPoint.y >= -1 && viewportPoint.y + item.height <= scroll.height + 1)
      return {text: typeof item.text === "string" ? item.text : "",
        placeholder: item.placeholderText || "", enabled: item.enabled,
        focus: item.activeFocus, editor: typeof item.inputMethodComposing === "boolean",
        x: point.x, y: point.y, width: item.width, height: item.height,
        inFrame: point.y >= 0 && point.y + item.height <= frame.height,
        inViewport: inViewport}
    })
    return JSON.stringify({ready: !!(service && service.ready), opened: opened,
      view: view, busy: busy, error: error || (service ? service.error : ""),
      pageLoaded: content.status === Loader.Ready && content.item !== null,
      session: session, state: snapshot, capture: qaCapture, controls: controls,
      frame: {width: frame.width, height: frame.height},
      screen: {name: window.screen ? window.screen.name : "", pixelRatio: frame.Screen.devicePixelRatio},
      scroll: {y: scroll.contentItem.contentY || 0, height: scroll.height,
        contentHeight: scroll.contentItem.contentHeight || 0},
      evidence: "Hosted QML; QA actions are synthetic component calls, not native key events"})
  }
  function qaAction(encoded) {
    try {
      var action = JSON.parse(encoded)
      if (action.kind === "open") {
        var views = ["dashboard", "lessons", "reviews", "resume", "lookup", "practice-library", "settings", "zen", "help", "recovery"]
        if (views.indexOf(action.view) < 0) throw new Error("Unknown QA view")
        root.open(JSON.stringify({view: action.view, limit: action.limit || 3, text: action.text || ""}))
      } else if (action.kind === "close") {
        root.dismiss()
      } else if (action.kind === "help") {
        root.showHelp()
      } else if (action.kind === "backend") {
        var methods = ["draft", "answer", "advance", "correct", "lesson_next", "settings", "pin"]
        if (methods.indexOf(action.method) < 0) throw new Error("QA method is not allowed")
        if (["draft", "answer", "advance", "correct", "lesson_next"].indexOf(action.method) >= 0)
          root.studyAction(action.method, action.args || {})
        else root.call(action.method, action.args || {})
      } else if (action.kind === "activate" || action.kind === "focus" || action.kind === "edit") {
        var control = qaControl(action.selector || {})
        if (!control.enabled) throw new Error("QA control is disabled")
        if (action.kind === "activate") {
          if (typeof control.clicked !== "function") throw new Error("QA control is not a button")
          control.clicked()
        } else {
          control.forceActiveFocus(Qt.TabFocusReason)
          if (action.kind === "edit") {
            if (typeof control.inputMethodComposing !== "boolean" || control.readOnly)
              throw new Error("QA control is not editable")
            control.text = String(action.text || "")
            control.cursorPosition = control.text.length
            if (typeof control.textEdited === "function") control.textEdited()
          }
        }
      } else if (action.kind === "bounds") {
        root.qaWidth = action.width ? Math.max(320, Math.min(1600, Number(action.width))) : 0
        root.qaHeight = action.height ? Math.max(360, Math.min(1200, Number(action.height))) : 0
      } else if (action.kind === "scroll") {
        scroll.contentItem.contentY = Math.max(0, Math.min(
          scroll.contentItem.contentHeight - scroll.height, Number(action.y || 0)))
      } else if (action.kind === "capture") {
        var name = String(action.name || "capture")
        if (!/^[A-Za-z0-9_-]{1,80}$/.test(name)) throw new Error("Invalid capture name")
        root.qaCapture = {name: name, status: "pending"}
        var queued = frame.grabToImage(function(result) {
          root.qaCapture = {name: name, status: result.saveToFile(QA_ARTIFACTS + "/" + name + ".png") ? "saved" : "failed"}
        })
        if (!queued) root.qaCapture = {name: name, status: "failed"}
      } else throw new Error("Unknown QA action")
      return JSON.stringify({ok: true, synthetic: true})
    } catch (error) { return JSON.stringify({ok: false, error: String(error)}) }
  }
'''


def command(args, cwd=None, timeout=30):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError("The QA isolation seam changed: " + before)
    return text.replace(before, after, 1)


def replace_function(text, name, body):
    result, count = re.subn(r"^  function " + re.escape(name) + r"\([^\n]*\) \{\n.*?^  }",
                           lambda _: body, text, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError("The QA function seam changed: " + name)
    return result


def prepare(source, destination=None):
    source = source.resolve()
    root = Path(tempfile.mkdtemp(prefix="wanikani-native-qa-")) if destination is None else destination.resolve()
    if destination is not None:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
    root.chmod(0o700)
    repository, state, artifacts = [root / part for part in ("repository", "state", "artifacts")]
    for path in (repository, state, artifacts):
        path.mkdir(mode=0o700)
    tracked = command(["git", "ls-files", "-z"], cwd=source).split("\0")
    copied = []
    source_hashes = {}
    for name in tracked:
        relative = Path(name)
        if not name or relative.is_absolute() or ".." in relative.parts:
            continue
        if name not in RUNTIME_FILES and relative.parts[0] not in RUNTIME_ROOTS:
            continue
        original = source / relative
        if original.is_symlink() or any(parent.is_symlink() for parent in original.parents if parent != source.parent):
            raise RuntimeError("QA source must not contain symlinks: " + name)
        if not original.is_file() or original.suffix in (".sqlite3", ".log", ".pyc"):
            continue
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        copied.append(name)
        source_hashes[name] = hashlib.sha256(original.read_bytes()).hexdigest()
    if not all((repository / name).is_file() for name in ("manifest.json", "Service.qml", "Panel.qml", "backend/worker.py")):
        raise RuntimeError("Commit or stage the runtime files before preparing native QA.")
    tag = uuid.uuid4().hex[:12]
    plugin_id = PRODUCTION_ID + ".qa." + tag
    manifest = json.loads((repository / "manifest.json").read_text())
    manifest.update(id=plugin_id, name="WaniKani QA fixtures", kinds=["service", "panel"],
                    entryPoints={"service": "Service.qml", "panel": "Panel.qml"})
    manifest.pop("barWidget", None)
    write_json(repository / "manifest.json", manifest)
    service = (repository / "Service.qml").read_text().replace(PRODUCTION_ID, plugin_id)
    service = replace_once(service, 'property string stateDirectory: ""', 'property string stateDirectory: ' + json.dumps(str(state)))
    service = replace_once(service, '"backend/worker.py"', '"backend/qa_worker.py"')
    service = replace_once(service, 'target: "wanikani"', 'target: "wanikani-qa-' + tag + '"')
    (repository / "Service.qml").write_text(service)
    panel = (repository / "Panel.qml").read_text().replace(PRODUCTION_ID, plugin_id)
    panel = panel.replace('"omarchy-wanikani"', '"omarchy-wanikani-qa-' + tag + '"')
    panel = replace_once(panel, 'Style.space(root.expanded ? 1060 : 760)', '(root.qaWidth || Style.space(root.expanded ? 1060 : 760))')
    panel = replace_once(panel, 'Style.space(root.expanded ? 920 : 760)', '(root.qaHeight || Style.space(root.expanded ? 920 : 760))')
    panel = replace_function(panel, "readSelection", '  function readSelection() {\n    root.query = "山"\n    root.search(root.query)\n  }')
    panel = replace_function(panel, "desktopIntegration", '  function desktopIntegration(remove) {\n    integrationNotice = "Native QA never changes desktop shortcuts or launchers."\n  }')
    ending = panel.rfind("\n}")
    if ending < 0:
        raise RuntimeError("Could not find the QA panel root.")
    driver = QA_DRIVER.replace("QA_ARTIFACTS", json.dumps(str(artifacts)))
    (repository / "Panel.qml").write_text(panel[:ending] + "\n" + driver + panel[ending:])
    ambient = repository / "qml/Ambient.qml"
    ambient.write_text(ambient.read_text().replace("omarchy-wanikani-ambient", "omarchy-wanikani-qa-ambient-" + tag))
    settings = repository / "qml/Settings.qml"
    settings.write_text(settings.read_text().replace("Qt.openUrlExternally(", "false && Qt.openUrlExternally("))
    package = repository / "backend/wanikani/__init__.py"
    package.write_text(package.read_text().replace(PRODUCTION_ID, plugin_id))
    (repository / "backend/qa_worker.py").write_text(QA_WORKER.replace("QA_STATE", json.dumps(str(state))))
    write_json(state / "mode.json", {"mode": "demo"})
    # Run only the generated account-disabled worker against brand-new state.
    seeded = subprocess.run([sys.executable, "-B", str(repository / "backend/qa_worker.py"), "--state-dir", str(state)],
        input=json.dumps({"v": 1, "id": "seed", "method": "snapshot"}) + "\n", text=True, capture_output=True, timeout=15)
    messages = [json.loads(line) for line in seeded.stdout.splitlines()]
    if seeded.returncode or not any(m.get("id") == "seed" and m.get("data", {}).get("demo") for m in messages):
        raise RuntimeError("Could not initialize isolated demo fixtures.")
    run = {"v": 1, "id": plugin_id, "root": str(root), "repository": str(repository), "state": str(state),
           "artifacts": str(artifacts), "source_commit": command(["git", "rev-parse", "HEAD"], cwd=source),
           "source_files": copied, "source_hashes": source_hashes, "status": "prepared",
           "evidence": "Synthetic component actions; no native-key or IME claim"}
    write_json(repository / ".native-qa.json", {"id": plugin_id, "root": str(root)})
    command(["git", "init", "--quiet", "--initial-branch=qa"], cwd=repository)
    command(["git", "add", "."], cwd=repository)
    command(["git", "-c", "user.name=Native QA", "-c", "user.email=native-qa@localhost", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Isolated authored native QA fixture"], cwd=repository)
    command(["omarchy", "plugin", "validate", str(repository)])
    write_json(root / "run.json", run)
    return run


def load_run(path):
    path = path.resolve()
    run = json.loads(path.read_text())
    root = path.parent
    if run.get("v") != 1 or not QA_ID.fullmatch(run.get("id", "")) or run.get("root") != str(root):
        raise RuntimeError("Invalid native QA run record.")
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("The QA run directory must be private and owned by this user.")
    for part in ("repository", "state", "artifacts"):
        if run.get(part) != str(root / part) or (root / part).is_symlink():
            raise RuntimeError("The QA run contains an unsafe path.")
    expected = {"id": run["id"], "root": str(root)}
    if json.loads((root / "repository/.native-qa.json").read_text()) != expected:
        raise RuntimeError("The QA source marker does not match this run.")
    return run


def ipc(run, method, args=""):
    raw = command(["omarchy-shell", "shell", "call", run["id"], method, args], timeout=15)
    return json.loads(raw)


def action(run, data):
    result = ipc(run, "qaAction", json.dumps(data, ensure_ascii=False))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "QA action failed"))
    return result


def wait_snapshot(run, condition=lambda s: True, timeout=15):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = ipc(run, "qaSnapshot")
        except (RuntimeError, ValueError):
            last = None
        if last and last.get("ready") and not last.get("busy"):
            if last.get("error"):
                raise RuntimeError("The hosted QA panel reported: " + last["error"])
            if (not last.get("opened") or last.get("pageLoaded")) and condition(last):
                return last
        time.sleep(0.1)
    raise RuntimeError("Native QA did not reach the expected state: " + json.dumps(last, ensure_ascii=False)[:800])


def capture(run, name):
    action(run, {"kind": "capture", "name": name})
    snapshot = wait_snapshot(run, lambda s: s.get("capture", {}).get("name") == name and s["capture"].get("status") != "pending")
    if snapshot["capture"]["status"] != "saved":
        raise RuntimeError("Native panel capture failed: " + name)
    write_json(Path(run["artifacts"]) / (name + ".json"), snapshot)
    return snapshot


def smoke(run):
    for view in ("dashboard", "lessons", "help", "lookup", "practice-library", "settings", "zen", "recovery"):
        action(run, {"kind": "open", "view": view, "text": "山"})
        wait_snapshot(run, lambda s: s["opened"] and s["view"] == ("study" if view == "lessons" else view))
        capture(run, view)
    action(run, {"kind": "open", "view": "resume"})
    snapshot = wait_snapshot(run, lambda s: s.get("session") is not None)
    while snapshot["session"]["phase"] == "lesson":
        action(run, {"kind": "backend", "method": "lesson_next"})
        snapshot = wait_snapshot(run)
    capture(run, "lesson-quiz")
    action(run, {"kind": "backend", "method": "draft", "args": {"text": "saved fixture draft"}})
    wait_snapshot(run)
    action(run, {"kind": "close"})
    action(run, {"kind": "open", "view": "resume"})
    snapshot = wait_snapshot(run, lambda s: (s.get("session") or {}).get("draft") == "saved fixture draft")
    capture(run, "resume-draft")
    action(run, {"kind": "backend", "method": "answer", "args": {"text": "fixture mistake"}})
    wait_snapshot(run, lambda s: s["session"]["phase"] == "feedback")
    capture(run, "lesson-feedback")
    action(run, {"kind": "backend", "method": "settings", "args": {"demo_offline": True}})
    snapshot = wait_snapshot(run)
    # Complete only this generated account's independently authored lesson quiz.
    # Native account/network access is disabled by the generated worker.
    for _ in range(40):
        if snapshot["session"]["phase"] == "complete":
            break
        if snapshot["session"]["phase"] == "feedback":
            action(run, {"kind": "backend", "method": "advance"})
        else:
            subject = snapshot["session"]["subject"]
            answer = subject["meanings"][0] if snapshot["session"]["part"] == "meaning" else next(r["reading"] for r in subject["readings"] if r["accepted"])
            action(run, {"kind": "backend", "method": "answer", "args": {"text": answer}})
        snapshot = wait_snapshot(run)
    if snapshot["session"]["phase"] != "complete" or snapshot["state"]["pending"] != 3:
        raise RuntimeError("Fixture lessons did not produce three saved offline submissions.")
    capture(run, "lesson-complete-offline")
    action(run, {"kind": "open", "view": "recovery"})
    wait_snapshot(run, lambda s: s["view"] == "recovery" and any(c["text"] == "Waiting · 3" for c in s["controls"]))
    capture(run, "recovery-pending")
    action(run, {"kind": "backend", "method": "settings", "args": {"demo_offline": False}})
    wait_snapshot(run, lambda s: s["state"]["pending"] == 0 and any(c["text"] == "Confirmed · 3" for c in s["controls"]))
    action(run, {"kind": "activate", "selector": {"text": "Confirmed · 3"}})
    wait_snapshot(run)
    capture(run, "recovery-confirmed")
    action(run, {"kind": "open", "view": "settings"})
    action(run, {"kind": "bounds", "width": 540, "height": 650})
    wait_snapshot(run)
    capture(run, "settings-narrow")
    snapshot = ipc(run, "qaSnapshot")
    buttons = [c for c in snapshot["controls"] if c["enabled"] and not c["editor"] and c["text"]]
    if buttons:
        target = buttons[-1]["text"]
        action(run, {"kind": "focus", "selector": {"text": target}})
        wait_snapshot(run, lambda s: any(c["focus"] and c["text"] == target and c["inFrame"] and c["inViewport"]
                                        for c in s["controls"]), timeout=5)
        capture(run, "settings-focus-scroll")
    action(run, {"kind": "bounds"})


def cleanup(run):
    if not QA_ID.fullmatch(run.get("id", "")):
        raise RuntimeError("Refusing to remove a non-QA plugin ID.")
    target = Path.home() / ".config/omarchy/plugins" / run["id"]
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not (target / ".native-qa.json").is_file():
            raise RuntimeError("Refusing to remove a plugin without this QA run's marker.")
        expected = {"id": run["id"], "root": run["root"]}
        if json.loads((target / ".native-qa.json").read_text()) != expected:
            raise RuntimeError("The installed QA marker differs; nothing was removed.")
        command(["omarchy", "plugin", "remove", run["id"], "--yes"])
    run["status"] = "removed"
    write_json(Path(run["root"]) / "run.json", run)


def hosted(run, scenario="smoke", hold=False):
    run = load_run(Path(run["root"]) / "run.json")
    installed = Path.home() / ".config/omarchy/plugins" / run["id"]
    if installed.exists() or installed.is_symlink():
        raise RuntimeError("QA ID already exists; use cleanup before rerunning.")
    def interrupted(*_):
        raise KeyboardInterrupt()
    old_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        command(["omarchy", "plugin", "add", run["repository"], "--enable", "--yes"], timeout=45)
        run["status"] = "running"
        write_json(Path(run["root"]) / "run.json", run)
        wait_snapshot(run)
        if scenario == "smoke":
            smoke(run)
        if hold:
            print("QA remains open for manual checks. Press Enter here to remove it; captures stay private.", flush=True)
            input()
    finally:
        try:
            cleanup(run)
        finally:
            signal.signal(signal.SIGTERM, old_term)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
        sub.add_argument("--directory", type=Path)
        if name == "run":
            sub.add_argument("--scenario", choices=("smoke", "none"), default="smoke")
            sub.add_argument("--hold", action="store_true")
    for name in ("snapshot", "action", "capture", "cleanup"):
        sub = commands.add_parser(name)
        sub.add_argument("record", type=Path)
        if name == "action":
            sub.add_argument("json")
        if name == "capture":
            sub.add_argument("name")
    args = parser.parse_args()
    try:
        if args.command in ("prepare", "run"):
            run = prepare(args.source, args.directory)
            print(json.dumps({"record": str(Path(run["root"]) / "run.json"), "id": run["id"],
                              "repository": run["repository"], "artifacts": run["artifacts"]}), flush=True)
            if args.command == "run":
                hosted(run, args.scenario, args.hold)
        else:
            run = load_run(args.record)
            if args.command == "snapshot":
                print(json.dumps(ipc(run, "qaSnapshot"), ensure_ascii=False, indent=2))
            elif args.command == "action":
                print(json.dumps(action(run, json.loads(args.json))))
            elif args.command == "capture":
                capture(run, args.name)
                print(str(Path(run["artifacts"]) / (args.name + ".png")))
            else:
                cleanup(run)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
