---
name: omarchy-wanikani
description: "Inspect and operate the installed WaniKani for Omarchy client: study status, cached learning recaps, learning views, explicit study starts, lookup, and recovery guidance through its CLI. Use for the learner's desktop client, not plugin development or general WaniKani API work."
---

# WaniKani for Omarchy

Help the learner use the existing native client through `tools/wanikani.py`. This optional playbook ships with the plugin; loading it does not install a skill globally or change the desktop.

## Locate the client

Use an explicitly supplied checkout when the user selects one. Otherwise prefer the installed plugin at `~/.config/omarchy/plugins/io.github.lostandadrift.wanikani/` (Omarchy 4.x). When this skill is still inside its repository, the directory two levels above it is another candidate. Resolve the actual path and parse `manifest.json`: require `id` to equal `io.github.lostandadrift.wanikani`, `schemaVersion` to equal `1`, and an existing `tools/wanikani.py` inside that same resolved repository. A directory name or Git remote alone does not establish identity. If neither candidate is valid, ask for the client's location; do not install or search private state to compensate.

Invoke `python3` and the verified helper path as separate arguments. Keep paths quoted if using a shell, and pass lookup text as a single argument without interpolating it into shell code. The helper controls the running shell even when executed from a checkout; a checkout's manifest version does not prove the installed version.

Start with `capabilities --json` when the helper's interface is unfamiliar. Read the verified repository's `docs/AGENT_SUPPORT.md` for detailed fields, exit codes, or compatibility questions ([bundled reference](../../docs/AGENT_SUPPORT.md)). Prefer its supported commands over raw shell IPC. Do not inspect keyring contents, tokens, SQLite, notes, or saved answers for ordinary client support.

## Match the requested action

Append these arguments to the verified helper command:

| Intent | Arguments | Effect |
|---|---|---|
| Check study or account status | `status --json` | Read cached, redacted aggregates. |
| Recap the last week or thirty days | `report --days 7 --json` / `report --days 30 --json` | Read one cached local calendar window through status; no fresh calculation. |
| Diagnose local availability | `doctor --json` | Read dependencies and shell/plugin accessibility; no repairs. |
| Show learning progress or local history | `open progress --json` / `open activity --json` | Open the requested view. |
| Invite the learner to study | `open review-overview --json` / `open lesson-overview --json` | Show a preflight; no session starts. |
| Start five reviews or lessons | `reviews --batch 5 --json` / `lessons --batch 5 --json` | Deliberately create or resume native study. |
| Resume saved study | `resume --json` | Use the client's saved-session rules. |
| Listen, practise, or inspect recovery | `open listen --json` / `open practice-library --json` / `open recovery --json` | Open controls; the learner takes the next action. |
| Show kana dictation | `open dictation --json` | Open Type kana; does not start practice, play audio or enter an answer. |
| Look up supplied Japanese | `lookup --json -- TEXT` | Use only the explicit text; at most 256 Unicode code points. |
| Look up the current selection | `lookup --selection --json` | Explicitly request selection, with clipboard fallback. |
| Synchronize completed work | `refresh --json` | May submit already completed pending work through normal reconciliation. |

Preserve existing user authorization. “Start five reviews” already authorizes that start; do not ask again. A status request alone does not authorize opening a study session or synchronizing. Opening `lookup` without `--selection` does not read the clipboard. Ordinary navigation also includes `dashboard`, `settings`, `help`, and `zen` as listed by capabilities.

Starting or resuming may refresh online and replay previously completed pending work. This playbook does not supply answers, acknowledge feedback, correct answers, or force a recovery replay. If the user asks about pending work, inspect aggregates or open Recovery; uncertain writes must not be blindly retried.

For missing listening audio, open `listen` and explain the native **Prepare recordings** action. It downloads up to five eligible recordings without starting study, playing audio, or revealing words. The learner can cancel and then choose when to start listening. The helper has no preparation, cancellation, playback, or listening-rating command; do not invent one or call the worker directly. See the bundled agent guide for partial-download and cache behavior.

Meaning recall and kana dictation are separate local skills with independently saved sessions and daily introductions. Dictation compares typed kana with the selected recording after playback; the learner owns Check, Continue, Skip and Undo. Do not send hearing acknowledgements, type answers or treat a player completion as proof that the learner heard the sound. Activity labels the two skills separately from account progress.

## Interpret results accurately

- Parse the versioned JSON envelope and check `ok`. Missing or `null` fields remain unknown, including listening availability; never replace them with zero.
- `pending` means saved locally, not confirmed by WaniKani. `attention` can overlap pending, so do not add the two as independent totals. `outbox_counts.confirmed` is the current status of this plugin's local operations, not all-device review history or a count confirmed today.
- Use `learning_progress.complete` before asserting a level requirement or threshold. With complete data, 24 passed of 27 required means three more are needed, even if the level contains 30 kanji. Do not infer missing progress fields from subject totals.
- Activity history is explicitly recorded on this device and can retain work from before resets. `report` exports only cached aggregates, while `open activity` shows the native detail. Do not bypass that boundary by reading SQLite.
- A requested recap uses `report --days 7 --json` (the default) or `--days 30`. Keep its `generated_at`, local date window and retained-records scope with the counts. Completed review cycles are not server confirmations; listening and dictation ratings remain separate local skills. `available:false` with `digest:null` is unknown, not zero. `complete` describes the aggregate calculation, not lifetime coverage; `stale:true` is known stale and `stale:null` is unknown freshness. Status/report do not recompute history, and an online status does not make the cached recap current. Never invoke `refresh` automatically to fill a missing or stale report; it may submit completed pending work. See [report definitions](../../docs/AGENT_SUPPORT.md#cached-learning-reports) for detailed metrics.
- Successful navigation or refresh means dispatch was accepted. It does not prove rendering, audible playback, finished synchronization, or completed study. After an action timeout, inspect status and the desktop before considering a retry; delivery may already have occurred.
- Cached `readiness` describes the last bounded offline check, not guaranteed current files. Keep required text/radical-image gaps separate from optional audio. `sync` is a cached stage; `cache` counts registered files and bytes. Doctor guidance is a suggestion to inspect native controls and performs no repair or refresh.
- Doctor does not test credentials, network access, speakers, or learning correctness. The manager's enabled flag can reflect bar placement while the service remains accessible; report both observations rather than declaring the client disabled from one flag.

Keep invitations proportionate to the user's request and current `studying`, `panel_open`, and reminder status. The helper creates no scheduler. For desktop reminder preferences, open Settings and use the native Study rhythm. An explicit request for a separate agent automation belongs to the host's supported automation workflow, not an invented CLI command. Distinguish implementation, automated checks, installation, and the learner's personally verified daily use in handoffs.
