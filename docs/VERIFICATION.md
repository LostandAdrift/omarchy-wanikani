# Verification and release qualification

## September 5 overnight 0.2.1 source checkpoint

Frozen tree `83e71ea71f60c89e4549c3a4e93056ca2512ba90` passed **812 tests in 246.998 seconds** from `/tmp/wanikani-milestone-3-release-r2` (log `/tmp/wanikani-milestone-3-release-r2-tests.log`). The first archive found one hardcoded 0.2.0 footer expectation; the repaired test now compares the rendered version against the manifest. Runtime files are identical between those archives. This checkpoint adds deliberate preparation of up to five familiar recordings, cooperative cancellation and count-only progress, fresh post-download readiness, and the optional repository-bundled operating skill.

The preparation regressions cover exact cache limits changing during a read, retained files disappearing before completion, account/permission changes, shared cache ownership, responsive concurrent answers, bounded downloads and redacted messages. Preparation creates no listening session, exposure, rating or graded submission. Twenty-five component/adapter Qt outcomes cover deliberate-only actions, cancellation, busy/retry controls, worker restart and stale completion after closing/reopening or navigating away/back.

The same runtime passed manifest validation, **113 core Qt checks**, and static lint of 34 QML files with zero errors. The linter retains **463 warnings** from dynamic/host-bound references and style diagnostics; this is not a warning-free build. Logs and eight authored narrow light/dark preflight/progress/result captures are in `/home/martin/.cache/tmp/wanikani-milestone-3-static-qa-3f0oe8gy`. Those captures use actual Listening/Card/Label/Theme source with inert Basic buttons and palette/controller adapters; they establish layout, not installed-shell or audible playback behavior.

The read-only host check at approximately 09:29 UTC still returned `locked:true`, `pending:true`, `sessionLocked:false`, and `lock-pending: screen-stabilizing`. No unlock, idle configuration change, installation or shell restart was attempted. Installed production remains `e5cb4e6`. Full hosted qualification, audible Japanese playback and the fourteen-day daily-use gate remain outstanding.

## September 5 overnight 0.2.0 source checkpoint

The frozen release tree `a2152f8fa8866b2fbedfb2d1a8bc4e12686640e4` passed all **754 tests in 234.616 seconds** from `/tmp/wanikani-milestone-2-release-r2`. The first candidate found one outdated inert TextField fixture; it was repaired before the complete rerun. The same runtime files passed QML lint (exit 0/no errors), 113 core Qt checks, and manifest validation. This checkpoint includes separate lesson discovery, local listening, Study rhythm, local Activity, input palette/accessibility improvements and the documented JSON CLI.

Native run `/tmp/wanikani-overnight-milestone-2b` completed 51 captures before the final Activity/input/cache refinements. It verified lesson selection and preview, reminder draft/Apply, and listening start/autoplay/replay/reveal/local ratings/close-resume/recap. Locally generated one-second MP3 tones decoded at QA output volume zero. Replay retained the exposure revision, close/resume stayed silent, and listening preserved the exact fixture graded sessions, references and outbox. Root inspected front/reveal/recap, lesson selection and reminder captures at the existing 1.5 scale. No audible Japanese or physical input qualification is implied.

The later native run was interrupted by Omarchy's normal lock flow and removed its temporary plugin. Further hosted verification and installation/restart are deferred while locking or locked. The installed production revision remains `e5cb4e6`; this 0.2.0 checkpoint is source verification, not an installation claim. The fourteen-day daily-use and remaining live/device gates still apply. See [overnight tracking](OVERNIGHT_WORK.md) for subsequent work and installation evidence.

Tested on 2026-09-04. Version 0.1.0 is a development release. Fixture tests and desktop inspection do not establish live-account safety or complete the two-week daily-use gate. The original four-hour implementation used no real WaniKani token or graded submission. A later user-authorized live authentication check is recorded below; no real study result has been submitted by these checks.

## Environment

Omarchy 4.0.2-1, Quickshell 0.3.1, Python 3.14.7, Qt 6.11.2, Hyprland 0.56.2. Initial checks used three monitors at scale 1. During the improvement window the existing DP-2 configuration was observed at 3840×2160, rotated portrait, scale 1.5; DP-3 remained 3440×1440 and HDMI-A-1 2560×1440 at scale 1. The isolated hosted scenario also ran on DP-2 at its observed 1.5 scale, producing 1140-pixel captures for a 760-logical-pixel panel. No monitor setting was changed by this QA run. Native captures use Noto Sans CJK JP, Tokyo Night and Flexoki Light. The original Tokyo Night theme, wallpaper, top bar, and unrelated bindings were preserved.

## Automated results

- Python: **489 distinct tests verified**: the final combined run passed 486, followed by three new pending-status cases in the complete 18-test reading-trail module. The suite includes real subprocess interruption checks at persistence and submission boundaries.
- Qt: **112 core checks passed**, covering kana conversion, activation-repeat protection, desktop notification/ambient policy, Japanese prompt fitting and Unicode limits, image-radical accessibility, ambient demand, and ordered state/session/epoch handling. Python wrappers also exercise real comparison, notes, forecast and reading-trail components plus source-derived async lifecycle behavior. Qt totals include initialization and cleanup.
- Omarchy manifest validation passed.
- Both installed desktop launcher files passed `desktop-file-validate`; Hyprland reported no configuration errors.
- QML formatting and syntax checks completed. `qmllint` retains host-specific warnings for dynamically injected shell objects and registered Quickshell types; it is not a warning-free static build.

Reproduce the fixture checks from the repository:

```sh
python3 -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME= QT_QUICK_CONTROLS_STYLE=Basic /usr/lib/qt6/bin/qmltestrunner -input tests/qml
omarchy plugin validate .
python3 tools/benchmark.py
```

QML static checks use a temporary import root whose `qs` link points to `/usr/share/omarchy/shell`. Quickshell core modules are registered by the host executable on this installation, so plain `qmltestrunner` cannot load the full native plugin. Pure kana/policy tests run under QtTest; surface inspection runs inside the installed shell.

Python fixtures cover all four subject types, accepted and excluded meanings, synonyms, alternate readings, normalization, conservative typo handling, saved drafts, error counts, guarded corrections, lesson completion, independent practice, duplicate command IDs, transaction rollback, final-feedback acknowledgment, interrupted writes, uncertain responses, remote conflicts, permission failures, rate limits, subscription expiry/renewal, vacation, account reset invalidation, post-submission unlock refresh, bounded media downloads, sanitized diagnostics, and reversible desktop integration. Tests never generate graded answers on a live account.

Qt policy checks cover quiet-hour boundaries, persisted reminder intervals, snooze, suppression without backlog, lock/DND/study/fullscreen gates, and short or overlapping idle deadlines. These establish policy behavior, not end-to-end lock or notification delivery on every desktop.

## Native desktop results

| Area | Actual result |
|---|---|
| Installation and updates | Installed and updated through ordinary `omarchy plugin` commands from the local Git repository. No public remote or contest entry exists. |
| Worker lifecycle | Disabling stopped the worker; enabling started exactly one. Durable demo counts and session state were retained. |
| Hot reload | Durable state survived. On this host, nested QML occasionally stayed stale until `omarchy restart shell`; documented in the README. |
| Views | Dashboard, quick study, lessons/quiz, practice library, recovery, lookup, Settings, help, and Zen rendered in the running shell. Native dark/light captures are in docs/screenshots/. |
| Isolated lesson/recovery scenario | Temporary authored fixture plugin in the same shell: lesson introduction, quiz, wrong-answer feedback, exact draft close/resume, three offline lesson completions, pending recovery and demo confirmation passed. An additional run verified a clearly labeled fixture milestone preview, ungraded practice with exact graded-session restoration, and durable raw note drafts across close/reopen, discard, explicit offline Save, a newer unsaved edit, and demo confirmation. Narrow 540×650 layout and focused-control scrolling passed. Actions were synthetic component calls, not native key events; cleanup removed each temporary plugin. |
| Study keyboard | Romaji entry, Enter feedback, Escape closing, and resuming the saved question/draft were exercised. Full IME/cursor variants also have pure conversion fixtures; comprehensive installed-IME qualification remains pending. |
| Bar | All four positions were exercised on all three monitors; horizontal and vertical crab/count presentations inspected. Original top position restored. |
| Themes | Tokyo Night and Flexoki Light applied to live surfaces, then original theme and wallpaper restored. |
| Shortcuts and launchers | Both installed launchers validate. Super+Alt+W and Super+Alt+Shift+W appear in live Hyprland bindings; unrelated bindings preserved. Helper rollback/removal/conflict cases use isolated fixtures. |
| Ambient ownership | The existing stay-awake setting was preserved. Automatic idle gallery correctly stays disabled under that setting; real screensaver handoff was not forced. |
| Runtime log | No WaniKani-related TypeError, ReferenceError, or binding-loop messages in the final loaded build's inspected shell log. |

## Performance measurements

All measurements are local development observations, not a guarantee across machines. The shell was already running. Rows were collected at different development checkpoints and loads; they are not one controlled benchmark. Later dated evidence below records the methods and changes.

| Measurement | Result | Scope |
|---|---|---|
| Warm saved-study opening | Median 43 ms; p95 65 ms | Ten samples with 9,016 authored subjects, from synthetic panel-open to native render readback. Not first-pixel or physical-key certification. |
| Warm practice opening | Median 83.5 ms; p95 96 ms | Same final ten-sample native fixture run; one catalogue request per opening. Dashboard, lookup, Settings and Zen also remained below 200 ms in that run. |
| Durable answer plus advance | Median 11.36 ms; p95 12.69 ms | Latest 100-operation authored fixture run; includes both local transactions and strict cache validation. |
| Full-catalogue snapshot | Median 36.00 ms; p95 39.13 ms | Latest 9,016 authored fixture catalogue run with covered schedule/access queries; earlier 88.84 ms. |
| Ranked local search | Median 15.63 ms | Full Unicode/romaji/synonym ranking across the same catalogue. |
| Offline readiness, earlier worker baseline | 90.37 ms | 9,016-subject catalogue; checked 3,008 eligible items in a background pass. Later readiness also covers scheduled reviews; this earlier timing does not measure that extension. |
| Large local submission history | Snapshot summary 1.47 ms / 1,964 bytes; first page 2.40 ms | 50,000 authored outbox rows plus 10,000 completed sessions. Deep open page at offset 30,000 measured 11.71 ms. |
| Online pre-study transport model | 0.18 s versus previous 8.42 s | Nine mocked reads at 20 ms each; burst-aware pacing and deferred media. Not live network timing. |
| Idle worker CPU | 0.0222% of one core | Latest valid 45-second closed-panel sample. This does not measure incremental QML CPU in the existing shell. |
| Worker memory | RSS 31.34 MiB; PSS 18.26 MiB; private 16.60 MiB | Latest valid sample, measured separately from the existing shell. |
| Local note draft acknowledgment | Median 10.39 ms; p95 10.59 ms | Authored edits, immediate durable transactions, 96-byte acknowledgments; no submission before explicit Save. |
| Cached audio voice catalogue | 280 ms / 329-byte result | 9,016 authored subjects and 54,000 audio entries; runs only when opening or refreshing Settings. |

Hidden companion animations are disabled. The read-only profile helper detected an external shell restart during the first baseline sequence and rejected that sample. A later stable disabled/enabled pair measured shared-shell CPU at 6.27% and 5.07% respectively; this difference is background noise and cannot establish incremental plugin cost. Incremental QML memory and CPU still need a stable before/disabled/after comparison; the combined plugin idle-CPU target is not yet certified. See [performance profiling](PERFORMANCE.md).

## Remaining release gates

- Connect a token through native Settings. Deliberately complete real lessons and reviews, verify notes/synonyms, cached image radicals, audio, offline submissions, and reconciliation with a second client. Test read-only and session-only authentication on the actual keyring.
- Qualify real lesson/media presentation, the installed Japanese IME, full keyboard-only navigation, accessibility tooling, additional fractional scales and focus changes across monitors, actual DND delivery, suspend/reconnect, lock/unlock, and automatic ambient/screensaver handoff. Preserve the user's existing idle and lock settings.
- Complete an end-to-end uninstall/reinstall check on a disposable account/desktop; isolated helper removal tests already pass.
- Measure incremental shared-shell memory and average CPU with an isolated baseline and longer opening-latency samples.
- Use the client daily for **two weeks**, with no lost answers, unexplained progress changes, or desktop interference. Record dates, versions, and any recovery events.
- Recheck the next competition's published rules and deadline, record the [three-minute demonstration](CONTEST_DEMO.md), then publish and submit a reviewed repository.

The implementation and demonstration script are available now. These outstanding gates must be completed before calling the release a qualified daily client or contest-ready 1.0.

## Improvement-window evidence

The native fixture harness retains private PNGs and rendered-control snapshots under its printed temporary run directory. The successful 02:34 UTC run used `wanikani-native-qa-pic0tb6s`; it completed three authored lessons offline and showed their local demo confirmation. Its own plugin namespace produced no TypeError, ReferenceError or binding-loop messages. A prior QA-only font-size binding error was fixed before this run.

New regressions cover exact-meaning preference, numeric/negation grading, malformed cache data across all study surfaces, suspension-aware clock handling, rate-limit headers, paginated recovery, diagnostic symlink replacement and per-mode deletion, and desktop journal ownership. Diagnostics now use explicit aggregate fields in private `diagnostics-account.json` or `diagnostics-demo.json` files.

The 03:08 UTC hosted run `wanikani-native-qa-g04t9mw5` passed the expanded 26-capture scenario and removed its temporary plugin. Milestones are derived only from successfully reconciled account observations; first-sync baselines, resets, duplicate observations, stale acknowledgments and transaction interruption have authored regressions. Unsaved editor drafts never affect grading or create an outbox operation. Additional tests cover bounded queue scans with 50,000 rows, reset handling amid 50,000 completed sessions, accessible cached voice metadata, and a zero-level account grant that must not issue an unfiltered subject request.

### Fourth improvement checkpoint · 03:53 UTC

The `wanikani-native-qa-ny1oxipk` run passed 30 captures on DP-3 at scale 1 and removed its temporary plugin. Dashboard, lessons, lookup, practice and Settings issued zero ambient-catalogue requests; opening Zen issued one. The recap showed five pending authored reviews, refreshed all five to demo-confirmed after synchronization while closed, and offered ungraded practice of the missed item. Actual Reset demo progress changed the data epoch and cleared the saved session and retained lookup cache. No errors appeared in the inspected QA namespace.

The deterministic interaction soak passed 10 seeds × 500 steps: 5,000 authored interactions included 1,047 answers, 211 drafts, 233 restarts, 124 resumes, 137 duplicate commands, 54 resets, lost responses before/after mock acceptance, and other-client progress. Its independent oracle found no duplicate accepted operation/cycle, lost durable question, pending-subject reentry, or automatic uncertain replay. This is accelerated mock interaction coverage, not two weeks of real daily use.

Full snapshots now have a sequence allocated before their reads, separate from durable session revisions and the data epoch. Threaded regressions reproduce a delayed old snapshot carrying the newest session but stale due/pending counts. QML checks reject those old counts, preserve newer answers, hide expired content, and prevent deleted same-name demo sessions from reappearing. Ordinary question actions emit compact session events. The batch recap stays outside the active question path and measured 0.88 ms with 50,000 historical sessions/outbox records.

Real Python-worker stdio measurements use 9,016 authored subjects, blocked network/keyring access and 30 samples per operation. They include a second immediately queued command to expose work performed after the answer response. These are sequential development observations, with brief unrelated fixture work overlapping part of the first comparison; no rendered-QML latency or controlled-certification claim is made.

| Worker operation | Previous response / following-command delay | Latest response / following-command delay |
|---|---|---|
| Check answer | 9.60 / 150.34 ms | 8.63 / 10.21 ms |
| Resume | 9.76 / 154.85 ms | 8.37 / 9.03 ms |
| Advance required part | 9.33 / 182.06 ms | 8.43 / 10.50 ms |
| New cached review, one subject | 132.26 / 14.32 ms before bounded selection | 18.80 / 9.05 ms after bounded selection |

Latest answer-response p95 was 11.38 ms. The new-review pair took 27.95 ms median / 39.11 ms p95. Completing a subject still triggers a full local summary/readiness update: the following-command delay was 49.63 ms median / 61.06 ms p95. A separate five-subject regression proves only the five selected assignments and their subjects are materialized. Candidate shuffling still ranges over all eligible identities and continues past unavailable cached content.

Reproduce with `python3 tools/benchmark_worker.py --samples 30 --compare-ref 9d5ebc9` and `python3 tools/soak.py --seeds 10 --steps 500`. Historical full results and current timings should not be mixed as if collected under identical load.

### Fifth improvement checkpoint · September 5, 04:23 UTC

The assembled batch passes **429 Python tests and 93 Qt checks**, plus manifest validation and whitespace checks. The 30-capture native fixture run `wanikani-native-qa-tx1ymwt5` passed and removed its temporary plugin; its inspected namespace had no errors. New recap and practice screenshots in `docs/screenshots` contain only that authored fixture.

Collection imports now commit 128 resources at a time. An isolated five-sample prototype measured a competing answer at 14.3 ms median instead of 53.2 ms while importing a 1,000-subject page; page import itself took 85.7 ms instead of 40.5 ms. The tradeoff gives foreground study room to finish its durable transaction. Tests cover cancellation and actual process exits inside/between chunks, retained old cursors, idempotent reimport and another-client progress arriving after a local completion.

Media tests cover required-image retention, usable alternate images/voices, strict actual byte budgets, malformed assets, budget skips without network backoff, MIME/truncation errors, cancellation, database/eviction failures, duplicate paths and crash leftovers. A subprocess exits after final-file rename but before its database insert; the next complete plan reclaims the orphan safely. No live media or account connection was used.

Malformed subject-level access is rejected consistently across study, search, counts, practice and offline availability. The covering index upgrades atomically once. Separate process-exit probes after dropping and recreating the old index retained a complete index and exact saved session/epoch across restart. Reset tests preserve local work as explicit conflicts when affected subject levels are missing or malformed. Duplicate-command tests retain the original effect/revision while refreshing its presentation through current access and notes, including a 10,000-command indexed lookup.

The five-subject worker benchmark ran 30 sessions / 150 authored reviews. Median new-start response was 18.1 ms and answer response 9.9 ms. Its durable command journal held 870 replies / 1.41 MB of UTF-8 response data; these records are intentionally retained for deduplication. Further storage-size work is planned without dropping command IDs.

The final soak passed 20 seeds × 500 steps: 10,000 interactions, 2,135 answers, 399 drafts, 417 restarts, 261 durable resumes, 304 duplicate commands, 109 resets, and lost responses before/after mock acceptance. Its independent oracle found no lost durable state, duplicate accepted cycle/operation or automatic uncertain replay. Access-redacted duplicate replies kept their original outcomes.

Final native opening run `wanikani-native-qa-mikbrsk8` measured ten samples per view with 9,016 authored subjects and removed its temporary plugin. Practice used exactly one catalogue request and rendered in 83.5 ms median / 96 ms p95; saved study measured 43 / 65 ms. Dashboard, lookup, Settings and Zen also stayed below 200 ms in all collected render-readback observations. There were no errors in its inspected namespace. These are synthetic open-to-render-capture measurements, not first-pixel or physical-key certification.

### Sixth improvement checkpoint · September 5, 05:06 UTC

The final combined Python run passed **468 tests**; the late comparison-rendering wrapper passed separately, bringing verified Python coverage to **469 tests**. The wrapper exercises 22 real-component Qt results, including malformed data, accessible hidden answers, accepted readings, and narrow text layout. Core QML tests pass **107 checks**. Separate Forecast surface tests pass five checks, including keyboard selection and scrolling the selected-hour detail into view. Native-control adapters used by offscreen tests are explicitly fixtures; they do not replace hosted-shell verification.

The final hosted run `wanikani-native-qa-083h6_3f` passed **34 captures** and removed its temporary plugin. It covered the original study/offline/recap/editor workflow plus personal notes in the lesson, a sun/eye comparison, comparison answers and control bounds at 460 logical pixels, quiet recall/reveal/next, and unrevealed recall after reopening. Dashboard, lesson comparison, narrow comparison and quiet recall were visually inspected. The new header/footer sizing keeps controls within narrow panels; forecast selection now reveals its detail. Its inspected shell namespace contained zero errors or warnings. The host was on DP-2 at the user's existing Hyprland scale of 1.5; the Qt screen property reported 2, while a 760-logical-pixel capture was 1,140 pixels wide. No monitor setting was changed.

The sixth correctness soak passed **10 seeds × 500 steps**: 1,051 answers, 84 guarded corrections, 210 drafts, 232 restarts, 124 durable resumes, 136 duplicate commands, 53 resets, 10 lost-after and seven lost-before responses. It included 140 accepted local operations and 86 other-client reviews. The oracle found no lost durable state, duplicate accepted assignment cycle, or automatic uncertain replay. This remains simulated coverage, not real daily-use qualification.

New command replies can use lossless versioned compression while keeping every request ID. Legacy text replies remain readable. Tests interrupt actual processes after encoding, after insertion and after commit, and reject corrupt/oversized compressed envelopes without re-running the original effect. There is no new throughput claim; additional performance work was canceled when the user redirected the iteration toward UI and learning features.

Upcoming offline readiness checks exact rolling 24-hour boundaries and account access at the scheduled review time. Changed grant, expiry or clock context invalidates an obsolete ready result. Shared media availability rejects empty/missing files and paths outside the owned cache; native image decoding tries cached alternatives and blocks forward study if none can render. Previous lesson and close remain available. Hidden Recovery, Practice and voice pages do not refresh, lookup cancels delayed searches on Enter/close, and late feedback cannot start hidden audio.

The new learning surfaces remain read-only: personal notes show only for the relevant answer part; similar-kanji cards omit inaccessible and unfinished graded subjects; quiet recall never records a grade or changes the review schedule. Live token/media verification, physical IME and desktop qualification, and the two-week daily-use gate remain outstanding.

### Seventh improvement checkpoint · September 5, 05:32 UTC

The final combined Python suite passed **486 tests** in 131.05 seconds. Three additional pending-work status cases then passed in the full **18-test reading-trail module**, for **489 distinct verified Python tests**. The reading-trail rendering wrapper passed again after final theme/disclosure polish (15 Qt checks); notes exercise nine Qt results and the Panel async wrapper 18. Core Qt passed **112 checks**. Manifest validation and whitespace checks passed.

The local reading trail preserves up to 256 Unicode code points exactly, links catalogue words without fetching translation, and shows overlapping alternatives in occurrence order. It uses bounded indexed reads, handles combining sequences, validates access and paused graded subjects, and labels pending or uncertain work explicitly. The first eight word buttons stay compact; the rest are available on demand. Tests cover exact rich-text round trips, links that follow a changed theme, closed/locked pages, late responses, and direct-word navigation. Ordinary deliberate catalogue lookup remains available.

Qt 6.11's JavaScript `Array.from` split supplementary characters in this host. A small explicit code-point walker now preserves rare kanji at search and note limits. Actual note controls retain the complete 2,000th character. Panel details and selection reads also reject replies after close, navigation, changed queries or account access, and preserve the original selected whitespace.

The final release run `wanikani-native-qa-qrqd4f_o` passed **36 native captures**, including opening a passage word, visiting Help, returning to that same detail and then the original passage. It completed the existing offline lesson/recovery, practice/graded-resume, editor, recap, narrow layout, comparison and quiet-recall scenario. Its temporary plugin was removed and its inspected namespace had **zero errors or warnings**. The final runtime files match the captured source hashes. A preceding reset-only boolean warning was fixed and verified with both an offscreen reset fixture and this hosted run. The user’s existing DP-2 scale of 1.5 was preserved.

The verified runtime checkpoint `38a902e` was installed through `omarchy plugin update`, followed by the documented shell restart. Source and installed commits matched; the pre-update saved production demo session remained byte-for-byte identical. Host process inspection confirmed exactly one WaniKani worker. The installed namespace had no warnings/errors, Hyprland reported no configuration errors, and no temporary QA plugins remained. Status was demo, nine due reviews, three lessons, zero pending and zero attention. These are authored demo counts, not live account progress.

## First live authentication fix · September 5, 2026 UTC

The user reported that a newly created token could not connect and explicitly authorized using it. A read-only GET to WaniKani accepted the copied token; the plugin then rejected the successful response. The original parser and fixtures incorrectly expected a top-level user ID. WaniKani's [documented user envelope](https://docs.api.wanikani.com/20170710/#user-data-structure) puts the UUID in `data.id`.

Runtime fix `ddff7e1` centralizes account identity validation for authentication, keyring storage, synchronization and milestones. The original API envelope is stored unchanged. Malformed nested or contradictory identities reject before touching saved work or credentials; unambiguous legacy fixture/cache identities remain readable. **104 related tests passed**, including 12 new regressions using the documented response shape and account-mismatch preservation checks.

After installation, an exclusive one-time connection probe used the authorized copied token in memory and the normal Secret Service pipe. That probe prohibited non-GET API requests. Authentication, account catalogue synchronization and secure keyring storage succeeded. The regular shell worker was re-enabled, restored the saved credential and reported online with no pending or attention state. Settings was opened for the user. The account database contained zero graded sessions and zero submission records after this check. No raw token, account response, private notes or credentials were added to this repository.

This establishes live authentication, keyring restoration and initial read synchronization on the tested account. It does not establish real graded submission/media playback behavior or replace the two-week personal-use gate.

## Guided lessons checkpoint · September 5, 09:50 UTC

Version **0.2.2**, frozen runtime tree `749fa5f6c731a2f0b17c0af9208cb3d8844a84bf`, was exported to `/tmp/wanikani-milestone-4-release`. The combined suite passed **843 tests in 247.524s**; log `/tmp/wanikani-milestone-4-release-tests.log`. Manifest validation and 113 core Qt checks passed. All 34 runtime QML files linted with zero errors and **468 warnings** (not a warning-free qualification).

New coverage exercises durable guided lesson steps, duplicate command reprojection, disappearing optional content, guarded quiz entry, and exact lesson autoplay ownership. Actual component wrappers cover keyboard navigation, final quiz focus, kanji reading, kana-vocabulary sound, image radicals, context comparisons and narrow light/dark layouts. Operational status uses cached values with strict nested validation and clear separation of required offline content from optional recordings. Native harness unit tests prove cleanup retains its owned marker/files when locked or unknown and makes no removal call.

Final archive artifacts and lint summary are in `/home/martin/.cache/tmp/wanikani-milestone-4-static-qa-le36fehr`. Root inspected `guided-captures/light-meaning.png` and `guided-captures/dark-context.png`. Six earlier component captures are in `/home/martin/.cache/tmp/wanikani-guided-lessons-qa-_4jgg6sa`; final archive captures include the later header wrapping and removal of empty quiz progress during discovery. These render actual Study/SubjectDetails and native controls against inert account and shell-color adapters. They are not hosted-shell, physical-input or audible-audio evidence.

One bounded fixture benchmark with 9,016 authored subjects ran concurrently with the full suite: snapshot median/p95 **24.505/24.856 ms** (eight samples), search **15.473/15.591 ms** (eight), answer+advance **20.790/21.085 ms** (100). These backend observations do not establish IPC latency, native opening, idle CPU or memory targets.

The expanded native lesson scenario is prepared but unexecuted. Hosted verification and production installation remain deferred: the compositor is locked and the shell's lock ownership is inconsistent after plugin reload. Read-only source inspection suggests normal unlock may be stranded. No system lock configuration or authentication was changed. Both installation and cleanup now refuse locking/locked/unknown state. Installed source remains **e5cb4e6**; this checkpoint is source verification only, and the two-week daily-use gate remains outstanding.

## Kanji vocabulary audio checkpoint · September 5, 10:14 UTC

Version **0.2.3**, frozen tree `a3896729ee5c7cc6e78596f2f07ef734c1f62112` in `/tmp/wanikani-milestone-5-release`, passed **873 tests in 253.952s**; log `/tmp/wanikani-milestone-5-release-tests.log`. Manifest validation, all 113 core Qt checks and archive identity checks passed (218 tracked files). All 35 runtime QML files linted with zero errors and 481 warnings. These include an existing layout-managed Study progress-bar height warning, without an established visual failure; this is not a warning-free build.

New audio tests cover bounded bidirectional vocabulary relationships, whole-word readings, alternate voices, accessible unlearned previews, every unresolved graded state, exact parent-queue exemptions, duplicate/practice parent protection and stale account/session/relationship/protection during media IO. The existing downloader permission callback now revalidates before/after IO and placement. Revoked permission creates no new media row/file and does not evict existing clips. Source-derived actual Panel callbacks reject a changed parent even if a malformed presentation reuses its session ID/revision. Disclosure is silent, playback is explicit, retry never loops, and unrelated state-only refreshes preserve open examples. Version diagnostics have strict values, clear worker identity on exit and add no queries.

Artifact report: `/home/martin/.cache/tmp/wanikani-0.2.3-component-qa-hlk5u8fb/REPORT.md`. Eight 320px viewport captures use the actual 290px component, native button source and inert shell/IO adapters. Light/dark states cover collapsed, three cards, selected actual reading with Stop/fallback notice and pending-study explanation. All were inspected by the QA agent; root independently inspected `light-three-examples.png` and `dark-selected-recording.png`. Text and controls fit. This does not verify audible Japanese, physical input, hosted scrolling or compositor geometry.

The entirely local native preparation produced 80 runtime files, 17 authored subjects and 3 generated one-second tone clips from an identical private source tree. Its record remains **prepared**, never installed, run or cleaned through shell IPC. All hosted verification and production installation remain deferred because of the documented lock ownership incident. Installed source remains **e5cb4e6**.

## Level history and palette checkpoint · September 5, 10:43 UTC

Frozen version **0.2.4**, tree `715e78cd0355f4c0c0a75593c30f55e7c5fbba61`, passed **907 tests in 345.706s**; `/tmp/wanikani-milestone-6-release-r2-tests.log`. All 227 tracked archive files were checked against that tree before the final run. Manifest passes; 113 core Qt checks pass; 36 runtime QML files lint with zero errors, 496 warnings and four informational diagnostics. A prior lint invocation misdirected its JSON output into archive BarWidget.qml; it was immediately restored from the exact tree and independently verified. The prior full run overlapped that incident and is deliberately not release evidence. No repository/index/installed file changed in the incident.

History coverage includes bounded indexed reads with 50,000 authored resources, strict timestamp ordering and offsets, access/reset scope, honest partial results, worker read-only isolation and native pagination/restart/large-integer identity cases. The actual component history wrapper passes 50 Qt outcomes. Fresh demos have six independently authored progression visits; existing seeded state is untouched.

Static artifacts: `/home/martin/.cache/tmp/wanikani-milestone-6-static-qa-9ab2k_w_/README.md`. Four 290px-content captures use actual Progress/LevelHistory/native controls with inert IO and shell adapters; six Qt outcomes pass, no QWARN, measured text contrast at least 4.5 and representative focus contrast at least 3. Root inspected light-demo-six-visits.png and dark-partial-history.png. These full-height offscreen views do not establish hosted scrolling or physical input.

The stock matrix in `/home/martin/.cache/tmp/wanikani-stock-palette-qa-mn_mbg1e` covers 88 component/palette cases plus eight lifecycle outcomes. All 22 installed palettes exercise study input/draft/selection/lesson, listening hidden/revealed, kanji examples and progress. Meter fixes bring Miasma and Rose Pine to 3.008647 and 3.027383 respectively against their actual tracks. A later focused Study matrix plus lifecycle pass verified layout height, accessible two-of-five label, proportional fill and contrast in 30.584s. No installed theme was changed.

No hosted verification or production install occurred; installed source remains **e5cb4e6** because of the documented secure-lock ownership incident. Audible playback, real IME, suspend/lock handoff and fourteen-day daily use remain qualification gates.


## 11:45 UTC · cached kana dictation verified

Version **0.2.5**, final frozen tree `6f3a86831a082ca4a3dbb957ad163f98c682abd3` in `/tmp/wanikani-milestone-7-release-r2`, passed **954 tests in 370.645s**, with one explicitly opt-in audio-device test skipped; log `/tmp/wanikani-milestone-7-release-r2-tests.log`. Manifest validation and all 38 runtime QML lint checks passed with zero errors, 519 retained warnings and four informational findings. The 113 core Qt checks passed against the prior freeze and were reused: its only runtime difference is the separately reverified Dictation.qml layout/focus correction. All 237 tracked archive blobs were verified and protected read-only before the final run.

Type kana now offers a separate five-word cached dictation batch, explicit original-recording playback, durable text/cursor drafts, exact kana checking, atomic feedback/Continue, Skip and immediate Undo. Each recording is pinned to its exact pronunciation. Only the current player attempt entering PlayingState then EndOfMedia can acknowledge playback; this does not establish that a person heard it. Closed, locked, changed-account, changed-source and partial-sync contexts reject stale replies. Local intervals and separately labeled activity never change WaniKani graded work. The five-new-word daily allowance remains separate from meaning listening, and previously introduced skipped words remain available.

Focused coverage includes 30 backend dictation tests, eight worker route/atomic-reply checks, six new insights tests, 27 actual Qt state checks, native input across all 22 stock palettes plus three authored low-contrast palettes, and actual Activity integration. A separately opted-in generated-MP3 Qt test passed four outcomes at output volume zero after authorized audio IPC access. It is decoder/playback-state evidence, not audible Japanese, human hearing or physical IME qualification.

Final narrow captures and a focus scenario passed eight Qt outcomes with zero QWARN in 3.632s. Root inspected `dark-complete.png` and `light-unavailable.png` in `/home/martin/.cache/tmp/wanikani-milestone-7-r2-static-qa-m3fjb_ud/dictation-captures`; the inactive feedback loader no longer reserves an empty block. New cards focus Play or input as appropriate, while a late heard acknowledgement preserves deliberate focus on Skip. The final geometry/input wrapper is included in the combined suite.

This is source verification only. Installed source remains **e5cb4e6**; no host install, shell reload, cleanup or screenshot was attempted. The known lock-ownership incident and the two-week personal-use gate remain outstanding. Next work is a read-only cross-level SRS explorer with guarded subject details and preserved navigation. Continue to the confirmed 09:00 local handoff.


## 12:32 UTC · SRS explorer and guarded navigation verified

Version **0.2.6**, final frozen tree `9628ca4019617778c18df9e6a3954c461f73f706` in `/tmp/wanikani-milestone-8-release-r2`, passed **991 tests in 410.102s**, with the one opt-in audio-device check skipped. Log: `/tmp/wanikani-milestone-8-release-r2-tests.log`. All 245 tracked blobs were verified against the frozen tree and protected read-only before testing. The first run exposed a missing property in the source-derived Panel test fixture; correcting that fixture was the only change between the two freezes. The final full run includes that correction.

Unchanged-runtime static checks from the first freeze remain applicable: manifest valid; **113 core Qt checks** pass; **39 runtime QML files** lint with zero errors, 527 warnings and three informational findings. This is not a warning-free build. The SRS explorer browses eight confirmed groups across the accessible catalogue, with subject type, level, substage, ordering and paging. Pending work does not predict SRS advancement. Guarded subject details and related links preserve paused-study protection, while returning to Progress restores the exact section, filters and page. Partial caches and inconsistent assignment metadata stay explicitly incomplete.

Final integrated artifacts: `/home/martin/.cache/tmp/wanikani-milestone-8-static-qa-vmbn7kd5/README.md`. Three narrow capture scenarios passed five Qt outcomes with zero QWARN in 2.049s using actual Progress, LevelProgress, SrsExplorer and native controls with inert IO. Root inspected `light-distribution-focus.png` and `dark-refined-explorer.png`; text fits and focused distribution buttons use their actual composited fill for contrast. The returned-explorer scenario verifies Guru/vocabulary/level 2/stage 6/date order/page 24 restoration. These offscreen checks do not establish hosted scrolling or physical keyboard behavior. Focused coverage also includes all 22 stock palettes, protected detail callbacks, asynchronous catalogue ownership and strict worker arguments.

Installed source remains **e5cb4e6**. No host install, shell reload, cleanup, screenshot, unlock or live graded action occurred. The lock-ownership incident still prevents installation and hosted qualification. The next separate milestone adds cached aggregate seven/thirty-day learning reports for agents without placing history work on answer-entry paths. Continue to the confirmed 09:00 local handoff; the fourteen-day personal-use gate remains outstanding.


## 13:04 UTC · cached learning reports and compact Progress verified

Version **0.2.7**, final frozen tree `dc0db16b9b1ae17c481bc405858187bb18604134` in `/tmp/wanikani-milestone-9-release-r3`, passed **1050 tests in 421.705s**, with one opt-in audio-device check skipped. Log: `/tmp/wanikani-milestone-9-release-r3-tests.log`. All 255 tracked blobs were checked against the tree and protected read-only. An earlier run was invoked with the repository as its working directory and is not release evidence. The next archive-directory run exposed one reminder-adapter fixture missing the newly referenced cache-hydration property; the final freeze differs only by that fixture property and passes the complete suite.

The new `report --days 7|30` command reads one bounded status response and returns strictly allowlisted local learning aggregates. It retains the digest's own calculation timestamp, local-calendar window, account data epoch, retained-records scope and stale/unknown label. Reviews, lessons, ungraded practice, meaning listening, kana dictation and typo corrections stay separate. Missing reports stay unavailable, not zero. Status does not refresh the account, open study, read private content or calculate history; existing full snapshot boundaries calculate both windows together. Authored tests include real native-count parity, both DST transitions, Undo, account/epoch isolation and no history computation on answer/draft/audio paths.

Independent review found a late full snapshot could erase known audio-result staleness. Successful relevant worker replies now carry an internal bound from the existing full-snapshot sequence, captured after the durable result. Only a later-started full snapshot can clear that bound. There are no extra database reads, sequence increments, events or changed result-data shapes on this path. Actual Service tests cover reversed reply order, a newer full snapshot arriving first, restart, changed account/epoch, access-only changes and invalid metadata.

Static evidence is reused from the identical runtime in the first freeze: manifest valid; **126 core Qt checks pass**; **39 QML files** lint with zero errors, 528 warnings and three informational findings. Logs and exact-source proof: `/home/martin/.cache/tmp/wanikani-milestone-9-static-qa-x59_0ry5/README.md`. Compact Progress keeps the full overview on Subjects & unlocks and a short confirmed-level context on SRS/History; the first explorer subject or history record is reachable within a narrow viewport. Selected tabs/filters expose native checked state. Five related wrappers cover all 22 stock palettes and exact filter/page restoration. Root inspected both 322×720 captures in `/home/martin/.cache/tmp/wanikani-compact-progress-captures-7qvqn9ag`; thirteen actual component/helper files match the frozen runtime. This is component/offscreen qualification, not hosted input or scrolling.

Installed source remains **e5cb4e6**. No installation, shell reload, cleanup, host screenshot, unlock or live graded action occurred. The lock-ownership incident and fourteen-day personal-use gate remain outstanding. Separate uncommitted work is now the reading-trail-to-practice flow, with explicit word selection, atomic validation, saved-session protection and return to the passage. Continue to 09:00 local.
