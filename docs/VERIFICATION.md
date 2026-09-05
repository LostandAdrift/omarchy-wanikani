# Verification and release qualification

Tested on 2026-09-04. Version 0.1.0 is a development release. Fixture tests and desktop inspection do not establish live-account safety or complete the two-week daily-use gate. No real WaniKani token was accessed and no real study result was submitted during this work.

## Environment

Omarchy 4.0.2-1, Quickshell 0.3.1, Python 3.14.7, Qt 6.11.2, Hyprland 0.56.2. Initial checks used three monitors at scale 1. During the improvement window the existing DP-2 configuration was observed at 3840×2160, rotated portrait, scale 1.5; DP-3 remained 3440×1440 and HDMI-A-1 2560×1440 at scale 1. The isolated hosted scenario also ran on DP-2 at its observed 1.5 scale, producing 1140-pixel captures for a 760-logical-pixel panel. No monitor setting was changed by this QA run. Native captures use Noto Sans CJK JP, Tokyo Night and Flexoki Light. The original Tokyo Night theme, wallpaper, top bar, and unrelated bindings were preserved.

## Automated results

- Python: **303 tests passed**, including the original **12 real subprocess crash boundaries** and four additional milestone transaction crash checks.
- Qt: **61 checks passed**, covering kana conversion, activation-repeat protection, desktop notification/ambient policy, full Japanese prompt fitting, and image-radical accessibility labels (Qt totals include initialization and cleanup).
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
| Full-catalogue snapshot | Median 88.84 ms | Latest 9,016 authored fixture catalogue run. |
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
