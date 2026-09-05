# Overnight implementation and handoff

Started September 5, 2026, 07:05 UTC / 00:05 America/Los_Angeles.

## Goal and operating decisions

The user authorized sustained overnight implementation of [the learning upgrade plan](LEARNING_UPGRADE_PLAN.md), targeting a pristine native client by morning, with first-class Omarchy and agent support and useful tracking. A persistent Codex goal is active. The thread heartbeat `wanikani-overnight-continuation` provides a 30-minute continuation opportunity through 16:00 UTC.

Confirmed handoff: **September 5 at 09:00 America/Los_Angeles / 16:00 UTC**. The user chose **install verified milestones; restart only when study is closed**, and **both learning progress/suggestions and agent diagnostics/recovery/automation controls equally**. These answers supersede the initial 08:00 default in the persistent goal text. Keep computer and Codex running for local work; no change to system idle/lock ownership is authorized or needed.

No real WaniKani lessons or reviews are submitted by automated testing. Preserve the live account, saved sessions, credentials, and unrelated desktop configuration. No account data belongs in this log. Read-only live verification is authorized by prior onboarding, but fixture tests are the default. The fourteen-day daily-use gate remains outstanding.

## Work allocation

| Owner | Current bounded work | Owned files |
|---|---|---|
| Root | Integration, tracking, native QA and release | Panel.qml, Service.qml, Dashboard/Listening/help QML, worker/store adapters, docs and native harness |
| study_review | Input palette and accessibility polish | Study/Lookup/SubjectDetails/Settings/StudyRhythm QML and focused rendering tests |
| sync_review | Listening cache retention lifecycle fix | media_plan.py and focused lifecycle regression tests |
| packaging_review | Local insights backend complete; Activity UI | insights.py/tests frozen; new LearningActivity QML and rendering tests |

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

- 07:44 UTC: milestone **e5cb4e6** committed. Its isolated release archive passed **568 tests in 156.577 seconds**; 113 core Qt checks and static QML lint passed. Expanded native run `wanikani-overnight-milestone-1d` verified two of three required kanji passed using authored fixtures, plus all prior smoke steps; temporary plugin removed. A separate evolving-worktree suite ran while reminder source was being audited and is not release evidence.
- 07:46 UTC: installed **e5cb4e6** through ordinary `omarchy plugin update --yes`. Study was closed before update and rechecked before shell restart. The one unfinished live session's body fingerprint was identical before and after update. Post-restart account status returned online with pending0/attention0. No WaniKani errors appeared in the inspected new shell log. Listening/reminder/lesson-discovery/agent CLI work remains uncommitted and is not installed.

- 07:55 UTC worktree (not installed): root connected worker lesson catalogue/preview, local listening state/action/media, reminder preview/claim/configure, coarse meaningful-study timestamps, Service notification hydration/coalesced claims/deadlines, Settings rhythm editor, Listen route and Panel adapters, aggregate IPC status and compact More navigation. New listening backend has 23 focused tests including process death; reminder backend 42; lesson backend 82 related tests; rhythm editor 15 Qt checks; root rhythm worker 5 tests passed. Agent-owned new UI/CLI tests are still being completed. Source-derived Panel tests need their new listening properties/helpers included; native fixture harness needs Listen-specific scenario and audio fixtures before this milestone can install. No live listening/media or reminder notification has been exercised yet.

- 08:28 UTC worktree (not installed): native run **wanikani-overnight-milestone-2b** completed **51 captures**, including lesson filter/selection/recommended preview, reminder draft/Apply, and listening start/autoplay/replay/reveal/ratings/close-resume/recap. The QA player decoded locally generated one-second MP3 tones at volume zero. Replay did not count another exposure; listening preserved the exact graded session/reference/outbox tables. Temporary plugin removed. Root inspected front/reveal/recap, lesson selection and reminder captures at the existing 1.5 scale. Two harness assumptions were corrected first (filter labels include counts; autoplay already consumes first exposure before Replay). This verifies the muted playback path, not audible Japanese pronunciation. An independent audit found background cache trimming could evict the active listening recording; that bounded retention fix is in progress. Input palette/accessibility polish is also in progress. Installed source remains e5cb4e6.
- The lazy local-learning insights backend passed 28 authored tests including local-day/DST boundaries, Undo, reset retention, query plans and index recreation without study changes. Root's worker adapter adds 3 passing tests for read-only routing, non-forgeable suggestions and optional listening-clock failure. Activity UI is still being built. New version metadata is 0.2.0 development; do not call it installed until the next coherent milestone passes full verification.

## Morning report requirements

### Verified 0.2.0 source checkpoint

Frozen tree **a2152f8fa8866b2fbedfb2d1a8bc4e12686640e4** in `/tmp/wanikani-milestone-2-release-r2` passed **754 tests in 234.616s** (log `/tmp/wanikani-milestone-2-release-r2-tests.log`). Its prior archive had one outdated TextField fixture, fixed and rerun. Runtime QML lint returned exit 0/no errors; 113 core Qt checks and manifest validation passed. Activity backend finished 29 tests and component 14 Qt outcomes. Atomic listening status/view prevents a concurrent reset splitting the reply; its threaded negative-control test fails when the lock is removed. Listening cache retention protects current/undoable clips at bounded priority, and schedule/pending metadata filters prevent false-empty listening pools.

Native `2b` remains the last complete hosted run (51 captures). `2c` preparation stopped before install because formatter defaults changed a harness seam; repository formatter settings now preserve two-space/essential-semicolon conventions. `2d` entered the shell but capture stopped when Omarchy began its normal lock flow. The temporary plugin was removed. Further hosted QA and all shell restarts/installation are deferred while locking/locked; the harness now checks this before installing and panel summons during lock are rejected. No system idle/lock setting was changed. Installed source remains **e5cb4e6**, not 0.2.0.

The 0.2.0 checkpoint was committed as **91e65ec**. Recording preparation and the optional repository-bundled agent playbook form the next independent checkpoint. Preparation must cache only, without exposing words, starting practice, counting an exposure or submitting study. Follow docs/LISTENING_PREPARATION.md and continue until the 09:00 confirmed handoff.

Report implemented and installed features separately, exact commit/revision, concise verification evidence, any live checks actually performed, remaining gaps and any desktop state restored. Include how to open Reviews, Lessons, Listen, Progress and agent status. Retain honest media/device/accessibility and daily-use qualification limits. Pause the overnight continuation at the handoff; do not silently extend the overnight window.

## 09:29 UTC · recording preparation source verified

Version **0.2.1**, frozen tree `83e71ea71f60c89e4549c3a4e93056ca2512ba90`, passed **812 tests in 246.998s** after replacing a hardcoded prior-version footer fixture. Required manifest validation and 113 core Qt checks passed; 34 runtime QML files linted with zero errors and 463 retained warnings. Eight narrow light/dark preparation captures use actual presentation with inert control/palette adapters, not hosted shell or audible verification. See VERIFICATION.md for paths and scope.

This adds explicit preparation of up to five eligible recordings with progress/cancel, shared media-budget ownership, account and cache-limit rechecks, neutral worker projections, fresh readiness, and the optional local agent playbook. Preparation never starts practice or audio and never records exposure, ratings or graded work. Navigation-sequence guards prevent a previous visit's completion affecting reopened Listen. The installed runtime remains **e5cb4e6**: Omarchy still reports its same pending lock, so no install/restart is attempted.

Next uncommitted work is guided Meaning→Reading/Sound→Context lesson discovery with durable steps and explicit quiz entry, plus cached operational readiness diagnostics through the existing status/doctor interface. This work stays outside the 0.2.1 checkpoint index until independently verified. Continue toward the confirmed 09:00 local handoff.

## 09:50 UTC · guided lessons and operational diagnostics verified

The prior 0.2.1 source checkpoint is commit **a138584**. Version **0.2.2**, frozen runtime tree `749fa5f6c731a2f0b17c0af9208cb3d8844a84bf` in `/tmp/wanikani-milestone-4-release`, passed **843 tests in 247.524s**, manifest validation and 113 core Qt checks. QML lint found zero errors with 468 retained warnings. Guided lesson discovery now keeps the exact Meaning→Reading/Sound→Context step, exposes separate quiz entry, and anchors optional reading autoplay to the initiating session, subject, revision and access context. Status/doctor projects cached offline readiness, synchronization, cache and outbox diagnostics without extra queries.

Final-archive narrow light/dark guided lesson captures were inspected using actual study/detail components and inert shell adapters. The prepared hosted scenario was not run. A bounded authored-catalogue benchmark observed answer+advance median 20.790 ms / p95 21.085 ms under concurrent fixture load; it does not certify native opening, idle CPU or live performance. See VERIFICATION.md for artifact paths.

**Desktop incident:** read-only compositor inspection confirms all three monitors are locked. Shell status remains `secure=true`, `requested=true`, `pending=true`, `sessionLocked=false`. Source inspection links this mismatch to global plugin reload replacing the lock service while the old compositor lock remains secure; normal password/fingerprint unlock through the replacement service may fail. No supported recovery procedure was found, and no unlock, restart, further plugin lifecycle mutation or screenshot is attempted. QA cleanup now checks lock state as strictly as installation and defers removal while locked or unknown, since removal also reloads services. The incident requires explicit morning handoff; installed source remains **e5cb4e6**.

Next source work: explicit whole-vocabulary audio examples for kanji and cached plugin/worker version identity. Continue offscreen implementation and tests until the confirmed 09:00 local handoff.

## 10:14 UTC · whole-word kanji audio verified

Guided lessons/operational readiness were committed as **0769eb6**. Version **0.2.3**, frozen tree `a3896729ee5c7cc6e78596f2f07ef734c1f62112` in `/tmp/wanikani-milestone-5-release`, passed **873 tests in 253.952s**. Manifest validation and 113 core Qt checks passed; all35 runtime QML files linted with zero errors and481 retained warnings. Eight offscreen kanji-audio captures and a wholly local native-harness preparation passed; none were hosted or installed.

Kanji reading/context/feedback/detail now offers explicit whole-vocabulary recordings, learned/preview labels, actual selected pronunciation, offline state and one-player controls. The exact active parent occurrence is the only study exemption; another graded parent occurrence or unresolved parent submission withholds all suggestions. Independent review caught stale-parent playback and post-download permission changes; regressions verify no late playback, cache placement or eviction after authorization loss. Cached status also identifies plugin/worker versions and explains known mismatches without extra queries or automatic restart.

The lock incident is recorded in [LOCK_RELOAD_INCIDENT.md](LOCK_RELOAD_INCIDENT.md). Native lifecycle guards now require all lock indicators, including process-wide secure, to be explicitly false. Installed source remains **e5cb4e6**; no host mutations occurred in this checkpoint. Root inspected the light three-example and dark selected-recording captures.

Next source work is a cached account level-history timeline with separate recorded visits, and a stock-palette qualification pass. The palette matrix identified two existing level-meter contrast failures (Miasma/Rose Pine); the one-line correction is outside the0.2.3 archive and will ship with its own verified checkpoint. Continue until09:00local; audible media, host qualification and fourteen-day daily use remain unfulfilled gates.
