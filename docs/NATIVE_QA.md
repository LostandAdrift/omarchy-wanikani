# Isolated native QA

`tools/native_qa.py` prepares a separate authored fixture account and temporarily installs its native QML surfaces in the existing Omarchy shell. It never starts another Quickshell process. The user's WaniKani account, demo database, keyring, shortcuts, launchers, and bar placement are not copied or edited.

The generated plugin has a unique `.qa.<random>` ID, separate service IPC and layer namespaces, a private fixture state directory, and only `service` and `panel` kinds. Its worker rejects all account API access and replaces Secret Service with an inert stub. In this generated copy, selection lookup uses `山`, external account links are inert, and desktop integration actions do nothing. Other page/control source comes from the tracked runtime files in the current working tree. The source commit and copied filenames are recorded; uncommitted edits to tracked files are included.

## Review before installing

```sh
python3 tools/native_qa.py prepare
```

This only creates a private temporary directory and validates its generated manifest. It prints the `run.json` record, fixture repository, and artifact location. Inspect `repository/Service.qml`, `repository/Panel.qml`, and `repository/backend/qa_worker.py` there. No shell plugin is installed by `prepare`.

## Run the hosted smoke scenario

```sh
python3 tools/native_qa.py run
```

This uses ordinary `omarchy plugin add --enable` and captures dashboard, lessons, help, lookup, practice library, settings, and Zen. It then shows a lesson quiz, saves/closes/resumes a fixture draft, shows wrong-answer feedback, completes three authored lessons offline, inspects pending and demo-confirmed submissions, and checks a narrower settings layout and focused-control scrolling. The temporary plugin is removed in `finally`, including on ordinary failure, Ctrl+C, or SIGTERM. Native PNG captures and JSON focus/layout/session snapshots remain in its private artifact directory.

Captures use the actual panel item's `grabToImage`; they do not capture unrelated desktop windows. A unique installation path bypasses the observed nested-QML cache issue without restarting the shell.

**Evidence boundary:** automatic actions call real QML component functions or signals and operate only on authored fixtures. They are synthetic actions. They do not establish native keyboard delivery, physical focus behavior, IME composition, selection ownership, monitor switching, or fractional scaling. The narrower layout is a logical-size stress check, not a monitor-scale change.

## Manual keyboard, IME, and monitor checks

```sh
python3 tools/native_qa.py run --scenario none --hold
```

The command prints a run record and stays alive until Enter is pressed in its terminal. In another terminal, substitute that exact record path:

```sh
python3 tools/native_qa.py action /tmp/wanikani-native-qa-EXAMPLE/run.json '{"kind":"open","view":"lessons"}'
python3 tools/native_qa.py snapshot /tmp/wanikani-native-qa-EXAMPLE/run.json
python3 tools/native_qa.py capture /tmp/wanikani-native-qa-EXAMPLE/run.json manual-lessons
```

Use the keyboard normally while the fixture panel is focused: Tab/Shift+Tab, Enter/Space, F1, Escape, editing/cursor keys, and the configured navigation keys outside text fields. Try Japanese composition and pasted kana. Move focus to another monitor and reopen the QA panel to inspect its actual placement and pixel ratio. Record what was physically exercised in a separate note; a JSON focus snapshot alone does not prove keyboard delivery.

Additional generated-driver actions include `help`, `close`, `scroll` with `y`, `bounds` with logical `width`/`height`, and `activate`/`focus` with an exact control-text selector. An `edit` action can set a uniquely selected editor's text, but remains a synthetic edit. The driver is appended only to the temporary QA Panel; production exposes no automatic-answer IPC.

## Recovery and cleanup

If the process is killed without running `finally`, or the shell was unavailable during removal:

```sh
python3 tools/native_qa.py cleanup /tmp/wanikani-native-qa-EXAMPLE/run.json
```

Cleanup validates the private run directory, unique plugin ID, and installed QA marker before using the normal plugin manager. It refuses to remove a different plugin. It preserves the fixture source, state, screenshots, and snapshots for debugging. Remove that temporary directory separately when its evidence is no longer needed. No full shell configuration is restored, so unrelated desktop edits made during QA are preserved.
