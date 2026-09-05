# Implementation checkpoint

User authorized the complete researched plan on 2026-09-04 and resumed work after a Codex reset. An earlier verified milestone is installed locally; newer source can remain uninstalled. Continue from the factual status and remaining qualification gates below; do not redo completed setup or discard the saved study session.

## Accepted product

Full native WaniKani lessons/reviews, offline sessions, guarded current-answer typo correction, and five-subject batches. Active learner, quality before contest deadline. Theme-native QML with original crab companion, dashboard, lookup from selection/clipboard (no OCR), optional desktop/idle/Zen kanji. All native study/ambient/companion features are in scope.

## Environment and contract

- Repository: /home/martin/Documents/ChatGPT/Omarchy 2/omarchy-wanikani, branch codex/wanikani.
- Plugin ID io.github.lostandadrift.wanikani, kinds service/bar-widget/panel. One panel routes multiple views; do not declare separate panel+overlay and assume both load (shell chooses panel).
- Omarchy 4.0.2-1; Quickshell 0.3.1; Python 3.14; Qt 6.11.2. python3, secret-tool, gnome-keyring, wl-paste, Noto Sans CJK JP, Qt Multimedia installed. Qt tools at /usr/lib/qt6/bin.
- /usr/share/omarchy/shell/shell.qml injects `shell`, `manifest`, and matching `service` into panels. Services retrieved via shell.serviceFor(id). Bar widget gets `bar`, `settings`, and accesses bar.shell.
- Panel entry root exposes `open(payloadJson)`, `close()`, and `opened`. shell.summon queues payload and calls open; shell.hide calls close. keepLoaded true supported.
- Native `qs.Ui.BarWidget`, WidgetButton, TextField, Button, BorderSurface; `qs.Commons.Color`, Style, Border. Native PanelWindow follows emojis/Emojis.qml. Single shared service owns Python worker via stdin/stdout JSON; no second Quickshell process.
- Current bar top; idle screensaver 150s / lock 1800s. Idle service owns these; ambient must give way before deadline. shell.serviceFor('omarchy.lock').locked and notifications service DND available. Desktop notifications must set custom app name because default omarchy-action bypasses DND.
- Installed keys Super+Alt+W (study), Super+Alt+Shift+W (lookup), verified in live Hyprland bindings. The reversible integration helper preserves conflicts and unrelated configuration. No packaged-file edits.

## Backend requirements

Python stdlib SQLite worker, async network separated from responsive command handling, deterministic grading, local search, media caching, keyring storage, durable study sessions/outbox. Versioned JSON-line protocol with request IDs. Flush acknowledged local transactions before UI advance.

API v2 revision 20170710. User, subjects, assignments, study_materials, review_statistics, summary, resets, level_progressions, spaced_repetition_systems. HTTPS only, pagination and updated_after cursors, conditional requests, 60/min upper limit with response headers, backoff. Never use GET reviews for history (deprecated empty); POST reviews remains supported and returns unpersisted id=0 plus resources_updated. Lesson quizzes finish with PUT assignments/{id}/start, not a review POST.

Outbox pending/inflight/confirmed/conflicted/uncertain; operation UUIDs only deduplicate locally. Compare remote assignment before replay. Lost response -> uncertain, reconcile, never blind retry. External progress/reset wins, preserve local record. Offline once per pending assignment; no speculative subsequent SRS round or new unlocks. Auth, permissions, vacation (`current_vacation_started_at`), subscription max_level_granted/period_ends_at, resets, and clock changes need explicit handling.

Guarded correction only current feedback before Next. Count errors per part; only enqueue a subject after all required parts correct AND final feedback acknowledged. Persist draft/partial session. WanaKana handles input locally; backend grades accepted answers/synonyms/excluded meanings and retryable input mistakes. Readings exact after normalization, conservative meaning typo tolerance. Study notes/synonyms sync with conflict handling. Activity heatmap describes plugin-recorded activity, not all-device history.

## Desktop behavior

Dashboard counts/status, next 24h forecast, level progress, difficult items, local activity, 5-review action/resume. Native lessons include relationships, mnemonics, examples, audio, quiz. Study expand preserves session. Enter check/next; Esc save/close; no letter navigation hijacking input.

Lookup only reads selected/clipboard text on explicit request, local catalogue search; details show personal SRS/reading/audio. Notifications due transition, 2h minimum, 22-08 quiet hours, snooze, obey DND/lock/vacation/active study, no suppressed backlog. Ambient only learned items not due within 24h, optional desktop card and Zen, idle display 60s until just before OS screensaver; hide activity/lock/fullscreen/study. Original crab, no punitive mechanics; separate animation/reduced-motion/ambient settings.

## Distribution and verification

Normal omarchy plugin add/update/remove; reversible user launcher/keybinding setup; no source-generated state. Free software, own assets/demo fixtures, per-account content cache and access restrictions. Session-only token fallback if keyring fails. Disconnect, clear media, redacted diagnostics, explicit personal-data deletion.

Test graders, all types, kana inputs, correction timing, crash persistence boundaries, duplicate messages, lost responses, another-device changes/resets, token/subscription/vacation/rate-limit/offline. QML lint and runtime visual QA. Test bar orientations, themes, scales, monitor/focus, lock/DND/lifecycle where feasible. Targets warm open <=200 ms, grade <=50 ms, idle CPU <0.5% core. Two weeks personal daily use is an external release gate, not something the agent can falsely complete now.

## Current handoff state · September 5, 15:56 UTC

This section supersedes earlier dated development notes. This records the overnight implementation for the user's confirmed **09:00 America/Los_Angeles (16:00 UTC)** handoff. Agent support and learning tracking have equal priority. The user permits installation of verified milestones and shell restart only with study closed; a fully unlocked desktop is also required by the observed host lifecycle issue below.

- **Source:** version 0.2.13, frozen tree `d6e9088361eb4905cdb72cc1909998ac801e867c` on `codex/wanikani`. Its exact frozen runtime passed 1153 Python tests in 226.565 seconds, with one opt-in audio-device check skipped, plus 126 core Qt checks. Manifest is valid; 43 runtime QML files lint with zero errors and 568 retained warnings. See [verification](VERIFICATION.md) for exact trees, archive paths, captures and scope.
- **Installed:** `e5cb4e6`, an earlier verified overnight milestone. Installation uses the ordinary plugin manager and pulls committed source from this local repository. No public remote, listing or contest submission has been published. Later source checkpoints are **not installed**.
- **Desktop blocker:** a plugin lifecycle reload earlier stranded the tested shell's lock service ownership. At 14:32 UTC, the service again reported an owned secure lock; the transition was not observed. The final 15:56 read-only check confirmed the same state and unchanged installed revision. The compositor is still locked. Do not unlock, reload/restart the shell, install/update/remove plugins, remove watched plugin files or take host screenshots as automated verification while this state persists. Source development and isolated offscreen fixtures remain available. Read [the incident](LOCK_RELOAD_INCIDENT.md); normal unlock has not been tested after that status change. No authentication or lock configuration has been changed.
- **Account:** the user-authorized token parsing fix and secure keyring restoration succeeded. Live read synchronization works. No automated live answers or graded submissions were made. Do not retrieve or expose the token again; keep account state and exact saved study sessions private and intact.
- **Implemented learning flows:** distinct saved Reviews/Lessons, lesson selection and guided discovery, original pronunciation and kanji vocabulary examples, cached meaning listening, separate cached kana dictation, visible level passing, a guarded SRS explorer, level visit history, local Activity, configurable Study rhythm, and passage-to-practice selection with exact return. See the README and linked feature guides for their behavior.
- **Agent support:** `tools/wanikani.py` offers documented bounded status, doctor, open and explicit start actions. Seven/thirty-day learning reports read cached allowlisted aggregates with their own timestamp and stale/unknown status. The optional repository playbook is not installed globally. Never use agents to answer live questions or force an uncertain submission.
- **Performance:** earlier authored native render-readback samples were within the 200 ms opening target; backend answer checks were within 50 ms in measured fixtures. These are scoped observations, not certification of every later source checkpoint. Do not spend extended time benchmarking while useful UI polish remains.
- **Remaining release gates:** resolve the host lock incident, inspect/install the current verified source while unlocked and study closed, audible original Japanese playback, real IME and physical keyboard use, desktop lifecycle/lock/suspend/DND qualification, and fourteen days of deliberate personal daily use. Automated tests and muted synthetic decoder checks do not replace these gates.

The visual subject relationship path, shorter README, detailed user guide and authored component tour are now source-qualified. Compact Practice/Lookup cards and cached radical rendering are also source-qualified. The final asynchronous start-order fix is also qualified: a superseded preflight cannot activate the wrong mode, and stale callbacks cannot restore an older visible question. No further feature work is pending in this checkout. The exact-tree developer verifier, compact Today, sectioned Settings and five-skill local recap are already source-qualified. Check Git status and [the overnight log](OVERNIGHT_WORK.md) before continuing; preserve concurrent changes and do not infer installed state from source HEAD. The local workspace's `WANIKANI_MORNING_HANDOFF.md` is a private draft until the actual handoff.

## Sources

- https://docs.api.wanikani.com/20170710/
- https://omarchy.org/manual/shell-plugins/
- https://plugins.omarchy.org/develop.html
- https://plugins.omarchy.org/publish.html
- https://github.com/WaniKani/WanaKana
- https://github.com/davidsansome/tsurukame/blob/master/ios/AnswerChecker.swift
- https://knowledge.wanikani.com/wanikani/common-mistakes/


Historical implementation and installation checkpoints are preserved in [VERIFICATION.md](VERIFICATION.md) and [OVERNIGHT_WORK.md](OVERNIGHT_WORK.md). Their dated claims apply to those checkpoints, not automatically to the currently installed source.
