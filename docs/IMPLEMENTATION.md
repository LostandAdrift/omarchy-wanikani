# Implementation checkpoint

User authorized the complete researched plan on 2026-09-04. They warned that a Codex reset is incoming. Continue implementation autonomously; the work is not complete.

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
- Proposed free keys Super+Alt+W (study), Super+Alt+Shift+W (lookup); inspect before installation. Preserve existing config. No packaged-file edits.

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

Test graders, all types, kana inputs, correction timing, crash persistence boundaries, duplicate messages, lost responses, another-device changes/resets, token/subscription/vacation/rate-limit/offline. QML lint and runtime visual QA. Test bar orientations, themes, scales, monitor/focus, lock/DND/lifecycle where feasible. Targets warm open <=200ms, grade <=50ms, idle CPU <0.5% core. Two weeks personal daily use is an external release gate, not something the agent can falsely complete now.

## Status · 2026-09-04

- Implemented QML service/widget/panel, native dashboard/study/lessons/lookup/settings/Zen/ambient/crab. One Python worker, SQLite, account keyring, deterministic grading, durable outbox, cache and recovery. WanaKana 5.3.1 bundled with MIT notice and provenance.
- Installed through `omarchy plugin add` from this local Git repository. Installed origin points here; updates use the normal manager. No public Git remote or publication yet.
- Shortcuts and Study/Lookup launchers installed with reversible helper. Existing bindings preserved; Hyprland config validation clean.
- Authored demo only. No real token accessed, no live WaniKani writes.
- 40 Python tests passed, including 12 actual subprocess crash boundaries. 11 Qt kana checks passed. Manifest validates. Native dashboard and review surfaces rendered in the running shell.
- Full fixture catalogue: 9,016 subjects, dashboard snapshot median ~93 ms, search ~3 ms, answer-and-advance ~12 ms. Numeric JSON indexes are essential; without them SQLite chose quadratic joins.
- Shell hot reload retained durable demo state but left nested QML components stale; a full shell restart picked up visual changes. Document this installed-host limitation. Do not edit packaged shell code.
- Still finishing final desktop QA, screenshots, current changes, remaining edge tests, and documentation. Do not declare task complete until those are done. Two weeks personal use, live account/audio, suspend/lock/idle handoff remain explicit release qualification gates.
- Current demo has a partially completed first five-review session; preserve it for resume checks. State is private, outside source.

## Sources

- https://docs.api.wanikani.com/20170710/
- https://omarchy.org/manual/shell-plugins/
- https://plugins.omarchy.org/develop.html
- https://plugins.omarchy.org/publish.html
- https://github.com/WaniKani/WanaKana
- https://github.com/davidsansome/tsurukame/blob/master/ios/AnswerChecker.swift
- https://knowledge.wanikani.com/wanikani/common-mistakes/
