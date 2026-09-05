# Agent and command-line support

Run the Python standard-library helper from this checkout. It controls the existing Omarchy shell; it does not install anything, start a daemon, change desktop settings, or open an account connection itself. No arguments print capabilities without contacting the shell.

```bash
python3 tools/wanikani.py capabilities --json
python3 tools/wanikani.py status --json
python3 tools/wanikani.py doctor --json
```

Every `--json` result is one JSON object on standard output:

```json
{"protocol":"wanikani-cli","version":1,"command":"status","ok":true,"data":{"status":"online","reviews":42,"lessons":18,"pending":2,"attention":1},"error":null}
```

That is a shortened, authored example. Actual status also includes supported aggregate flags and counts; unavailable fields are `null`, never assumed zero. Unknown keys and freeform account messages are removed. The helper does not expose tokens, account names, subject details, saved answers, notes, media paths, or raw SQLite access. Lookup text is not echoed in responses; explicitly supplied text travels as one JSON argument to local shell IPC.

When supplied by the installed service, `learning_progress` reports the current level's `passed`, `required`, and `remaining` counts with completeness and pending/attention flags. For example, 24 passed of 27 required means three more are needed; incomplete cache data leaves the requirement unknown. `saved_sessions` exposes only review/lesson/practice presence. `panel_open` and `studying` describe native UI state. `reminders` exposes its suppression status, next opportunity, and remaining daily budget. Optional `last_sync` and `next_reviews_at` are validated ISO timestamps. These fields support both learning suggestions and an operational handoff without exposing personal study content.

## Choose a surface or deliberately begin

Opening an overview does not start its study session:

```bash
python3 tools/wanikani.py open dashboard
python3 tools/wanikani.py open review-overview
python3 tools/wanikani.py open lesson-overview
python3 tools/wanikani.py open progress
python3 tools/wanikani.py open activity
python3 tools/wanikani.py open listen
python3 tools/wanikani.py open practice-library
```

Other supported destinations are `lookup`, `settings`, `recovery`, `help`, and `zen`. `open lookup` only opens the lookup surface; it does not read the selection or clipboard. Explicit lookup preserves supplied whitespace and supplementary Japanese characters, with a 256-code-point limit:

```bash
python3 tools/wanikani.py lookup '山が見えます。火山と山。'
python3 tools/wanikani.py lookup --selection
```

`--selection` requests the native selection lookup, with clipboard fallback. No clipboard is inspected by the Python helper itself.

Begin or resume only when the user intends to study:

```bash
python3 tools/wanikani.py reviews --batch 5
python3 tools/wanikani.py lessons --batch 5
python3 tools/wanikani.py resume
```

The optional batch is a whole number from 1 to 20. Omitting it uses the plugin preference. Beginning study creates or restores durable local session state and can refresh online, including normal replay of previously completed pending work. Reviews and lessons use the native mode selection and saved-session rules. The CLI supplies no answers and acknowledges no feedback. It has no grading, automatic study, correction, forced-recovery, credential, or generic worker-command interface.

## Synchronization and recovery

```bash
python3 tools/wanikani.py refresh --json
python3 tools/wanikani.py status --json
python3 tools/wanikani.py open recovery
```

Refresh is an explicit synchronization action. It can send **already completed pending work** through the ordinary reconciliation and submission queue. It is not a read-only network check. An uncertain write is never blindly replayed; a conflict or uncertain result belongs in the native recovery UI.

`pending` is saved local work awaiting processing, not confirmed WaniKani progress. `attention` records need inspection and can overlap pending. Optional `outbox_counts.confirmed` describes confirmations recorded by this plugin, not account-wide review history. A successful command reports dispatch acceptance. It does not establish that the window rendered, sound played, a study item completed, or background synchronization finished.

## Diagnostics and errors

Doctor checks executable presence, `shell ping`, the matching plugin inventory entry, and the aggregate `wanikani status` response. It performs no repairs. Optional `secret-tool` or `wl-paste` absence is reported without treating the entire client as broken. The manager's enabled flag can describe bar placement for this plugin; direct service accessibility is checked separately.

Doctor does not inspect keyring contents, validate an API token, probe the network, test speakers, read the database, or establish account correctness. Its output is suitable for a redacted local handoff. Keep any separately collected personal learning records private.

| Exit | Meaning | Next action |
|---|---|---|
| `0` | Read succeeded or dispatch accepted | Inspect returned status; do not infer asynchronous completion. |
| `2` | Invalid arguments | Read `capabilities --json` or `--help`. |
| `3` | Dependency or shell/plugin unavailable; doctor incomplete | Inspect `doctor --json`, then use normal Omarchy settings if a change is requested. |
| `4` | Invalid/incompatible reply or unsupported view | Update the helper and plugin together; inspect the installed revision. |
| `5` | Bounded IPC timeout | An action may already have been accepted. Check status and the desktop before retrying. |

Each IPC call has a five-second default timeout, adjustable to 1–15 seconds with `--timeout`. Doctor makes at most three sequential IPC reads. Errors have stable `code`, `message`, `action`, and `delivery` fields; raw shell output and supplied arguments are never included. No failed action is automatically retried.

## Local shell contract

- `omarchy-shell wanikani status` returns a JSON object. The original five fields remain supported. Optional `schemaVersion: 1`, booleans, listening/level counts, and outbox-state counts are strictly typed and projected by the helper.
- Normal navigation uses `omarchy-shell shell summon io.github.lostandadrift.wanikani '<JSON>'`. The payload has a supported `view`, optional `limit`, or explicit lookup `text`/`selection`. The shell must answer `ok`; `unknown` is a failed dispatch.
- `omarchy-shell wanikani refresh` requests ordinary background synchronization. Its current acknowledgement is empty output; `ok` is also accepted.
- Doctor uses `omarchy-shell shell ping` and `omarchy-shell shell listPlugins`, then the status method above. No new privileged or generic IPC entry point is required.

## Morning and daily tracking

Use `status --json` and `doctor --json` for the morning handoff alongside the tested source/installed revision in [overnight tracking](OVERNIGHT_WORK.md). Separate **implemented**, **automatically verified**, **installed**, and **personally confirmed**. Aggregate counts can guide an invitation to review, learn, or listen; they do not authorize an agent to complete study for the learner.

The helper creates no cron job or Codex automation. Periodic user invitations belong to the native Study rhythm policy, with its shared budget and desktop suppression rules. Runtime progress remains in the private local store. The fourteen-day qualification log in [DAILY_USE.md](DAILY_USE.md), audible live vocabulary verification, and remaining native interaction gates require actual evidence; CLI success is not a substitute.
