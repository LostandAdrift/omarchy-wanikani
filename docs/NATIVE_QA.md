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

This uses ordinary `omarchy plugin add --enable` and captures dashboard, a labeled milestone preview, lessons, help, lookup, practice library, settings, Zen, and recovery. It then exercises a lesson quiz, saves/closes/resumes a fixture answer, shows wrong-answer feedback, completes three authored lessons offline, and inspects pending and demo-confirmed submissions. It also selects and finishes ungraded practice while retaining the exact paused graded question and draft, then checks a narrower settings layout and focused-control scrolling.

The editor scenario selects the authored mountain subject through lookup, types `peak,  partial,` and a note, closes/reopens and verifies the exact raw draft, then discards it. An explicit offline Save creates exactly one material operation. A newer draft remains separate while that operation waits, and survives simulated confirmation. The waits inspect native controls, durable command acknowledgments, and fixture state; changed text alone is not treated as proof of persistence.

The temporary plugin is removed in `finally`, including on ordinary failure, Ctrl+C, or SIGTERM. Native PNG captures and JSON focus/layout/session/detail snapshots remain in its private artifact directory.

Captures use the actual panel item's `grabToImage`; they do not capture unrelated desktop windows. A unique installation path bypasses the observed nested-QML cache issue without restarting the shell.

**Evidence boundary:** automatic actions call real QML component functions or signals and operate only on authored fixtures. They are synthetic actions. They do not establish native keyboard delivery, physical focus behavior, IME composition, selection ownership, monitor switching, or fractional scaling. The narrower layout is a logical-size stress check, not a monitor-scale change.

On 2026-09-05 at 03:08 UTC, run `wanikani-native-qa-g04t9mw5` completed all 26 captures, including the editor and paused-practice scenarios, and removed its temporary plugin without namespace errors. Milestone preview, newer pending editor draft, and practice selection were visually inspected. The captured frame was 1140 pixels wide at the already configured compositor scale of 1.5; no scaling configuration was edited. This is evidence for that existing display configuration and synthetic workflow, not comprehensive scale or physical-key/IME qualification. The same third-batch checkpoint passed 303 Python tests and 61 Qt checks; [verification](VERIFICATION.md) records later batches separately.

## Manual keyboard, IME, and monitor checks

For repeated native opening measurements, run:

```sh
python3 tools/native_qa.py run --scenario performance --samples 10
```

This scenario seeds 9,016 independently authored subjects and a saved five-subject review batch. It opens study, dashboard, lookup, Settings, Zen and Practice in rotating order, without answering study items. Each view is warmed once first. The private `artifacts/open-latency.json` report records source hashes, monitor/pixel ratio, per-view request counts, and individual timings; it does not retain images.

The timer starts inside the synthetic QML open action. `component_ready_ms` waits for the page loader, local requests and input preparation to settle; `render_capture_ms` includes a subsequent `grabToImage` render readback. The latter includes capture overhead and is not physical-key, IPC-launch, compositor-presentation or first-pixel latency. Polling overhead is recorded separately and excluded from those QML timestamps. A changed timing clock invalidates the run. The same temporary-plugin cleanup applies.

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

The expanded smoke also checks pending/confirmed batch recaps across a hidden synchronization, practices the missed fixture item, verifies no ambient requests before explicitly opening Zen, and invokes Reset demo progress in its isolated database. Reset must change the data epoch and clear retained session/search state. These actions never reset the installed production demo.
