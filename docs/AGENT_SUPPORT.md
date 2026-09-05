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

The Progress view's **SRS explorer** drills into confirmed current Apprentice/Guru/etc. groups across levels. Native type/level/substage filters and pagination are preserved when returning from details. These cached counts can be partial and include protected subjects; a pending result does not predict its next stage. The helper opens Progress but does not export the private catalogue, raw detail records or notes. Use [the Explorer scope](SRS_EXPLORER.md) when interpreting the native view.

For account milestones, open Progress and choose **Level history**. It shows separate recorded visits and dated passing/burned milestones from the accessible account cache. Older history can be absent even after synchronization completes. **Activity** remains the separate record of work done in this client. The helper does not export individual history records or submit their private worker requests; see [history scope](LEVEL_HISTORY.md).

## Cached learning reports

Use `report` for an explicitly requested recap such as “How much did I practise this week?” It defaults to seven days and accepts only `--days 7` or `--days 30`:

```bash
python3 tools/wanikani.py report
python3 tools/wanikani.py report --days 7 --json
python3 tools/wanikani.py report --days 30 --json
```

Each invocation makes exactly one read-only `wanikani status` IPC call. It selects an already cached window from optional `status.learning_digest`; it does not request fresh history, query SQLite, contact WaniKani, scan media, open a view or begin study. The normal full-snapshot refreshes maintain this cache. Recent local work can be absent until one of those refreshes occurs, even when the shell responds immediately and the account is online.

The report covers **local calendar days**, including today only through its own `generated_at` timestamp. Its system timezone and `start_day`/`end_day` remain attached to the cached calculation; there is no caller-supplied timezone or date range. A day can contain 23 or 25 hours across daylight saving changes. The seven-day counts are a subset of the thirty-day counts.

- `subject_completions` counts acknowledged local review, lesson and ungraded practice cycles separately. Repeated cycles count again; answer parts do not. These counts do not establish server confirmation. Current `outbox_counts.confirmed` and current-level `learning_progress` remain separate status fields.
- `sessions_completed` counts deliberately finished batches. Listening and dictation have their own completed-batch counts and final surviving ratings: remembered/again/skipped for meaning listening, matched/again/skipped for kana dictation. Undo removes the corresponding local result; Skip is not a correct answer. Neither audio skill changes WaniKani SRS.
- `typo_corrections` counts local uses of the guarded correction action. It is not an inferred accuracy score. All metrics cover retained records on this device, including activity kept across account resets; another client's individual reviews are not reconstructed.

Successful JSON reports use the existing `wanikani-cli` version-1 envelope. `data.available:true` supplies `data.digest` with the metadata and just the selected `window`. Status itself can include both cached windows. An unsupported, missing or unavailable digest returns a successful read with this data:

```json
{"available":false,"reason":"unavailable","digest":null}
```

Unavailable counts are never replaced with zero. A supported empty history can return known zeros. `complete:true` means the supported aggregate fields were calculated successfully from retained records; it does not mean lifetime or account-wide coverage. `complete:false` marks an incomplete calculation. `stale:true` means the cache is known to be stale; `stale:null` means freshness is unknown. Even an explicitly supplied `stale:false` remains a cached observation, not a fresh read. The human report leads with **Recorded on this device · cached through …** and labels known stale, unknown freshness, incomplete and authored demo data.

The optional digest contains counts, dates, static scope labels and an opaque local `data_epoch` UUID. It exposes no account identity, subject IDs, meanings, readings, answers, notes, individual session/operation IDs or media locations. The helper validates required fields, dates, timezone, integer bounds and the two-window relationship, drops unknown extra fields and returns a generic `invalid_response` error for malformed or incompatible data. It never falls back to raw worker messages or private files.

A recap does not authorize automatic study or synchronization. Do not use `refresh` to obtain a newer report unless the user requests that synchronization: it may submit already completed pending work. An invitation based on the report can remain conversational; opening or starting a session follows the learner's request.

## Optional agent playbook

The repository includes [skills/omarchy-wanikani/SKILL.md](../skills/omarchy-wanikani/SKILL.md) and its agent display metadata. It is an optional operating guide, not a plugin-development skill. An agent can read it directly from the repository to locate the installed client, check its manifest identity, use the bounded helper, and interpret local progress and recovery states.

Installing or updating the Omarchy plugin does not install the skill into an agent's global configuration. Point your agent to the playbook when you want this support; permanent registration is a separate, optional host action. Existing authorization carries through: “Start five reviews” authorizes that start, while “How many reviews are due?” calls for a status read. The playbook supplies no answers, requests no credentials, and does not inspect private account databases.

## Choose a surface or deliberately begin

Opening an overview does not start its study session:

```bash
python3 tools/wanikani.py open dashboard
python3 tools/wanikani.py open review-overview
python3 tools/wanikani.py open lesson-overview
python3 tools/wanikani.py open progress
python3 tools/wanikani.py open activity
python3 tools/wanikani.py open listen
python3 tools/wanikani.py open dictation
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

## Listening and recording preparation

`open listen` opens the native listening preflight. It does not play audio, prepare recordings, or begin a listening session. If familiar words need audio, the native **Prepare recordings** action downloads a bounded batch of up to five, using the account's accessible WaniKani recordings and the configured media budget. Progress shows counts without revealing the selected words. Preparation itself creates no listening session, records no exposure or rating, and submits no graded work.

The learner can cancel preparation without cancelling ordinary account synchronization. Cancellation is cooperative; a file already in progress may finish, and completed files remain cached. A failed or partial preparation leaves a visible result and ready recordings can still be used. The learner explicitly chooses when to start listening afterward. Preparation does not establish that the speakers work or that the selected voice has been heard.

`open dictation` shows the separate **Type kana** activity without starting practice or playing audio. Its typed input, pinned recording, playback-completion acknowledgement, checks, Continue, Skip and Undo are learner actions in the native UI. Local Activity reports dictation separately from meaning recall and WaniKani review history. There is no agent dictation-answer or hearing-acknowledgement action; do not imitate a learner or claim the player can prove that a person heard the output.

There is currently no CLI preparation, preparation-cancellation, playback, or listening-rating command. Use `open listen` for a request to show these controls; do not invent helper arguments or bypass the helper through raw worker messages. Aggregate `listening_due` is cached availability when supplied, not the preparation job's progress or proof of audible playback. An unavailable value stays `null`.

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

Status now includes optional cached operational sections. Reading them starts no new worker request, cache scan, download, or account synchronization. Older installed services leave unsupported sections and fields `null`.

| Section | Meaning |
|---|---|
| `versions` | Optional `plugin` from the loaded service's injected manifest and `worker` from its latest ready event. Each is a validated product version or `null`; worker exit clears its version. Older services may leave the whole section `null`. These are neither a Git revision nor proof that every nested QML component was reloaded. |
| `readiness` | Last-check `complete`, `checking`, and `checked_at`, with separate `reviews`, `lessons`, and `upcoming_reviews` groups. Each group reports `total`, `checked`, `ready`, required `missing_text`/`missing_images`, optional `audio_total`/`audio_cached`, and `total_complete`. Upcoming means the checked next 24 hours. |
| `sync` | Cached allowlisted `stage`, `active`, `completed`, and optional `total`. A stage count is not account-wide study history; unknown stages become `unknown`. No freeform error message is exposed. |
| `outbox_counts` | Current local counts for pending, in-flight, confirmed, conflicted, uncertain, blocked, and discarded operations. Confirmed is not a count confirmed today. |
| `cache` | Registered `files`, `bytes`, accessible catalogue `subjects`, and configured `limit_bytes`. These are cached metadata, not a new measurement of disk usage or audio playback. |
| `learning_digest` | Optional dated 7/30-day local learning aggregates. Its own `generated_at`, retained-records scope, completeness and stale/unknown freshness survive projection. See [cached learning reports](#cached-learning-reports); reading it starts no calculation. |

When `checking` is true, counts can describe the previous check. Incomplete totals are not proof that missing items do not exist. Even a complete check describes its `checked_at` timestamp; current access and study eligibility are rechecked when used. Missing optional pronunciation does not by itself block graded text reviews. These groups do not measure the separate familiar-word listening pool, and `listening_due` remains unknown.

Doctor's `healthy` flag continues to describe local transport availability. A separate `guidance` list contains stable codes and static suggested actions based on cached evidence: inspect uncertain work in Recovery, review account access in Settings, wait for an active synchronization or cache check, or inspect required/optional cache gaps. Guidance neither changes the exit code of a healthy transport nor executes a repair, opens a view, refreshes the account, downloads audio, or deletes files. An explicit account refresh may submit previously completed pending work, so it is never used as an automatic diagnostic probe.

When both product versions are known and differ, `runtime_version_mismatch` suggests an incomplete hot reload. It is separate from transport health and does not establish which version is newer. Wait until study is closed and the desktop is unlocked before a normal plugin update or shell restart; diagnostics never perform either action. Equal versions do not prove that all nested components are current, and a missing version is not replaced with zero or the helper's own version.

| Exit | Meaning | Next action |
|---|---|---|
| `0` | Read succeeded or dispatch accepted | Inspect returned status; do not infer asynchronous completion. |
| `2` | Invalid arguments | Read `capabilities --json` or `--help`. |
| `3` | Dependency or shell/plugin unavailable; doctor incomplete | Inspect `doctor --json`, then use normal Omarchy settings if a change is requested. |
| `4` | Invalid/incompatible reply or unsupported view | Update the helper and plugin together; inspect the installed revision. |
| `5` | Bounded IPC timeout | An action may already have been accepted. Check status and the desktop before retrying. |

Each IPC call has a five-second default timeout, adjustable to 1–15 seconds with `--timeout`. Status and report each make one IPC read; doctor makes at most three sequential IPC reads. Errors have stable `code`, `message`, `action`, and `delivery` fields; raw shell output and supplied arguments are never included. No failed action is automatically retried.

## Local shell contract

- `omarchy-shell wanikani status` returns a JSON object. The original five fields remain supported. Optional `schemaVersion: 1`, booleans, listening/level counts, and outbox-state counts are strictly typed and projected by the helper.
- Normal navigation uses `omarchy-shell shell summon io.github.lostandadrift.wanikani '<JSON>'`. The payload has a supported `view`, optional `limit`, or explicit lookup `text`/`selection`. The shell must answer `ok`; `unknown` is a failed dispatch.
- `omarchy-shell wanikani refresh` requests ordinary background synchronization. Its current acknowledgement is empty output; `ok` is also accepted.
- Doctor uses `omarchy-shell shell ping` and `omarchy-shell shell listPlugins`, then the status method above. No new privileged or generic IPC entry point is required.
- Report uses only the existing status method; there is no separate report IPC method or fresh-history request.

## Morning and daily tracking

Use `status --json` and `doctor --json` for the morning handoff alongside the tested source/installed revision in [overnight tracking](OVERNIGHT_WORK.md). Separate **implemented**, **automatically verified**, **installed**, and **personally confirmed**. Aggregate counts can guide an invitation to review, learn, or listen; they do not authorize an agent to complete study for the learner.

For a requested weekly or thirty-day recap, add `report --days 7 --json` or `report --days 30 --json` and retain its own timestamp and freshness label in the handoff. A successful cached report is not evidence that today's latest session was included.

The helper creates no cron job or Codex automation. Periodic user invitations belong to the native Study rhythm policy, with its shared budget and desktop suppression rules. Runtime progress remains in the private local store. The fourteen-day qualification log in [DAILY_USE.md](DAILY_USE.md), audible live vocabulary verification, and remaining native interaction gates require actual evidence; CLI success is not a substitute.
