# Overnight implementation and handoff

Started September 5, 2026, 07:05 UTC / 00:05 America/Los_Angeles.

## Goal and operating decisions

The user authorized sustained overnight implementation of [the learning upgrade plan](LEARNING_UPGRADE_PLAN.md), targeting a pristine native client by morning, with first-class Omarchy and agent support and useful tracking. A persistent Codex goal is active. The thread heartbeat `wanikani-overnight-continuation` provides a 30-minute continuation opportunity through 16:00 UTC.

Confirmed handoff: **September 5 at 09:00 America/Los_Angeles / 16:00 UTC**. The user chose **install verified milestones; restart only when study is closed**, and **both learning progress/suggestions and agent diagnostics/recovery/automation controls equally**. These answers supersede the initial 08:00 default in the persistent goal text. Keep computer and Codex running for local work; no change to system idle/lock ownership is authorized or needed.

No real WaniKani lessons or reviews are submitted by automated testing. Preserve the live account, saved sessions, credentials, and unrelated desktop configuration. No account data belongs in this log. Read-only live verification is authorized by prior onboarding, but fixture tests are the default. The fourteen-day daily-use gate remains outstanding.

## Work allocation

| Owner | Current bounded work | Owned files |
|---|---|---|
| Root | Audio/worker/UI integration, tracking, overall native QA and release | Panel.qml, Service.qml, Study/Dashboard/Settings QML, backend/worker.py, later integration edits |
| study_review | Audio adapter verification completed; independent reminder policy audit | reminders.py and reminder tests during audit |
| sync_review | Progress backend/UI completed; local listening backend | new listening.py and listening tests |
| packaging_review | Theme/reminder foundations completed; study-rhythm settings component | new StudyRhythm.qml and rendering test |

Agents share this checkout. Confirm their status and file ownership before taking over an edit. Integrate bounded changes, run focused tests, then the required whole-suite/manifest/native checks. Commit coherent verified milestones; do not claim installation until the installed revision and runtime are checked.

## Sequence

1. Separate saved lesson/review modes; make visible entry points and headers explicit. Implement reliable replay, lesson/review autoplay choices, useful audio states, and voice testing.
2. Add actionable Today cards, confirmed level-up progress, a browsable level board, familiar SRS names and personal status.
3. Implement local-only Listen 5 with careful unrevealed/revealed projections, durable ratings and interval history; unify due-based and periodic reminders.
4. Deepen lesson discovery, keyboard/focus flow, themes, accessibility and empty/error states. Add documented agent/CLI/IPC actions and redacted diagnostics/health and learning tracking.
5. Use remaining time for high-value finished improvements, focused regression fixes, native polish and a self-contained morning handoff. Performance work is targeted to visible regressions, not a separate optimization campaign.

## Checkpoints

- Start: source `65d2ffe`, branch `codex/wanikani`, clean checkout. Installed runtime last confirmed `ddff7e1`; intervening changes were planning documents only.
- Baseline from preceding turn: 501 Python tests passed in 131.732 seconds; manifest validation and diff whitespace checks passed. These establish the prior implementation, not acceptance of the planned upgrades.
- 07:10 UTC: persistent goal and continuation created. Three bounded implementation agents started. Session interfaces agreed: per-mode saved references with safe legacy migration, `Engine.saved_session(mode)`, and compact `saved_sessions` summaries. Root must update worker resume selection plus recovery/media protection adapters after integration.

- 07:35 UTC: integrated independently saved review/lesson sessions, explicit overview routes, async one-clip pronunciation and voice tests, level passing/board, and contrast-aware inherited surface roles with native popup borders. First full suite ran 587 tests; five fixture failures identified (new session summary shape, audio fixture stubs, child Python import path), with fixes underway. These were not installed.
- Native isolated runs `wanikani-overnight-milestone-1b` and `1c` passed existing and expanded smoke scenarios in the running shell. Temporary QA plugins removed. Added overview/progress narrow-layout checks; screenshots inspected at the existing DP-2 fractional scale. Only authored data was graded. QML lint returned exit 0/no errors; 113 core Qt checks passed. User's production study surface was closed; no production restart performed.

## Morning report requirements

Report implemented and installed features separately, exact commit/revision, concise verification evidence, any live checks actually performed, remaining gaps and any desktop state restored. Include how to open Reviews, Lessons, Listen, Progress and agent status. Retain honest media/device/accessibility and daily-use qualification limits. Pause the overnight continuation at the handoff; do not silently extend the overnight window.
