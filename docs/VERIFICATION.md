# Verification and release qualification

Tested on 2026-09-04. Version 0.1.0 is a development release. Fixture tests and desktop inspection do not establish live-account safety or complete the two-week daily-use gate. No real WaniKani token was accessed and no real study result was submitted during this work.

## Environment

Omarchy 4.0.2-1, Quickshell 0.3.1, Python 3.14.7, Qt 6.11.2, Hyprland 0.56.2. Initial checks used three monitors at scale 1. During the improvement window the existing DP-2 configuration was observed at 3840×2160, rotated portrait, scale 1.5; DP-3 remained 3440×1440 and HDMI-A-1 2560×1440 at scale 1. The isolated hosted scenario also ran on DP-2 at its observed 1.5 scale, producing 1140-pixel captures for a 760-logical-pixel panel. No monitor setting was changed by this QA run. Native captures use Noto Sans CJK JP, Tokyo Night and Flexoki Light. The original Tokyo Night theme, wallpaper, top bar, and unrelated bindings were preserved.

## Automated results

- Python: **357 tests passed**, including the original **12 real subprocess crash boundaries** and four additional milestone transaction crash checks.
- Qt: **93 checks passed**, covering kana conversion, activation-repeat protection, desktop notification/ambient policy, full Japanese prompt fitting, image-radical accessibility labels, ambient demand, and ordered state/session/epoch handling (Qt totals include initialization and cleanup).
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

All measurements are local development observations, not a guarantee across machines. The shell was already running.

| Measurement | Result | Scope |
|---|---|---|
| Warm study opening | 73.9 ms | One sample from IPC invocation to a visible compositor layer; does not instrument first-pixel rendering. |
| Other warm views | Dashboard 82.3 ms; lookup 59.8 ms; Zen 64.2 ms; Settings 62.6 ms | Same method, one sample per view. All below the 200 ms target in this run. |
| Durable answer plus advance | Median 11.36 ms; p95 12.69 ms | Latest 100-operation authored fixture run; includes both local transactions and strict cache validation. |
| Full-catalogue snapshot | Median 36.00 ms; p95 39.13 ms | Latest 9,016 authored fixture catalogue run with covered schedule/access queries; earlier 88.84 ms. |
| Ranked local search | Median 15.63 ms | Full Unicode/romaji/synonym ranking across the same catalogue. |
| Practice / offline readiness | Practice 93.79 ms; searched practice 99.54 ms; readiness 90.37 ms | Same catalogue; readiness checked 3,008 eligible items in a background pass. |
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

Final native opening run `wanikani-native-qa-mikbrsk8` measured ten samples per view with9,016 authored subjects and removed its temporary plugin. Practice used exactly one catalogue request and rendered in83.5ms median /96ms p95; saved study measured43/65ms. Dashboard, lookup, Settings and Zen also stayed below200ms in all collected render-readback observations. There were no errors in its inspected namespace. These are synthetic open-to-render-capture measurements, not first-pixel or physical-key certification.

### Sixth improvement checkpoint · September 5, 05:06 UTC

The final combined Python run passed **468 tests**; the late comparison-rendering wrapper passed separately, bringing verified Python coverage to **469 tests**. The wrapper exercises 22 real-component Qt results, including malformed data, accessible hidden answers, accepted readings, and narrow text layout. Core QML tests pass **107 checks**. Separate Forecast surface tests pass five checks, including keyboard selection and scrolling the selected-hour detail into view. Native-control adapters used by offscreen tests are explicitly fixtures; they do not replace hosted-shell verification.

The final hosted run `wanikani-native-qa-083h6_3f` passed **34 captures** and removed its temporary plugin. It covered the original study/offline/recap/editor workflow plus personal notes in the lesson, a sun/eye comparison, comparison answers and control bounds at 460 logical pixels, quiet recall/reveal/next, and unrevealed recall after reopening. Dashboard, lesson comparison, narrow comparison and quiet recall were visually inspected. The new header/footer sizing keeps controls within narrow panels; forecast selection now reveals its detail. Its inspected shell namespace contained zero errors or warnings. The host was on DP-2 at the user's existing Hyprland scale of 1.5; the Qt screen property reported 2, while a 760-logical-pixel capture was 1,140 pixels wide. No monitor setting was changed.

The sixth correctness soak passed **10 seeds × 500 steps**: 1,051 answers, 84 guarded corrections, 210 drafts, 232 restarts, 124 durable resumes, 136 duplicate commands, 53 resets, 10 lost-after and seven lost-before responses. It included 140 accepted local operations and 86 other-client reviews. The oracle found no lost durable state, duplicate accepted assignment cycle, or automatic uncertain replay. This remains simulated coverage, not real daily-use qualification.

New command replies can use lossless versioned compression while keeping every request ID. Legacy text replies remain readable. Tests interrupt actual processes after encoding, after insertion and after commit, and reject corrupt/oversized compressed envelopes without re-running the original effect. There is no new throughput claim; additional performance work was canceled when the user redirected the iteration toward UI and learning features.

Upcoming offline readiness checks exact rolling 24-hour boundaries and account access at the scheduled review time. Changed grant, expiry or clock context invalidates an obsolete ready result. Shared media availability rejects empty/missing files and paths outside the owned cache; native image decoding tries cached alternatives and blocks forward study if none can render. Previous lesson and close remain available. Hidden Recovery, Practice and voice pages do not refresh, lookup cancels delayed searches on Enter/close, and late feedback cannot start hidden audio.

The new learning surfaces remain read-only: personal notes show only for the relevant answer part; similar-kanji cards omit inaccessible and unfinished graded subjects; quiet recall never records a grade or changes the review schedule. Live token/media verification, physical IME and desktop qualification, and the two-week daily-use gate remain outstanding.
