# Verification and release qualification

Tested on 2026-09-04. Version 0.1.0 is a development release. Fixture tests and desktop inspection do not establish live-account safety or complete the two-week daily-use gate. No real WaniKani token was accessed and no real study result was submitted during this work.

## Environment

Omarchy 4.0.2-1, Quickshell 0.3.1, Python 3.14.7, Qt 6.11.2, Hyprland 0.56.2. Three monitors: 1440×2560 portrait, 3440×1440, and 2560×1440, all at scale 1. Native captures use Noto Sans CJK JP, Tokyo Night and Flexoki Light. The original Tokyo Night theme, wallpaper, top bar, and unrelated bindings were preserved.

## Automated results

- Python: **140 tests passed**, including **12 real subprocess crash boundaries**.
- Qt: **49 checks passed**, covering kana conversion, activation-repeat protection, and desktop notification/ambient policy (Qt totals include initialization and cleanup).
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
| Views | Dashboard, quick study, lookup, Settings, and Zen rendered in the running shell. Native dark/light captures are in docs/screenshots/. |
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
| Durable answer plus advance | Median 11.3 ms; p95 13.4 ms | 100 operations on a fixture database; includes both local transactions. Below the 50 ms feedback target in this run. |
| Full-catalogue snapshot | Median 91.4 ms; p95 93.3 ms | 9,016 authored fixture subjects, eight samples. An earlier run measured a 120.6 ms median. |
| Local search | Median 2.3 ms; p95 2.3 ms | Same catalogue, eight samples. |
| Idle worker CPU | 0.0% of one core at process-tick resolution | 45 seconds with the panel closed. This does not measure incremental QML CPU in the existing shell. |
| Worker memory | RSS 30.2 MiB; PSS 17.7 MiB | Isolated worker process, measured separately from the existing shell. |

Hidden companion animations are disabled. Incremental QML memory and CPU inside the shared shell still need an isolated baseline comparison; the combined plugin idle-CPU target is not yet certified.

## Remaining release gates

- Connect a token through native Settings. Deliberately complete real lessons and reviews, verify notes/synonyms, cached image radicals, audio, offline submissions, and reconciliation with a second client. Test read-only and session-only authentication on the actual keyring.
- Exercise native lesson presentation end to end, the installed Japanese IME, full keyboard-only navigation, accessibility tooling, fractional scaling, focus changes across monitors, actual DND delivery, suspend/reconnect, lock/unlock, and automatic ambient/screensaver handoff. Preserve the user's existing idle and lock settings.
- Complete an end-to-end uninstall/reinstall check on a disposable account/desktop; isolated helper removal tests already pass.
- Measure incremental shared-shell memory and average CPU with an isolated baseline and longer opening-latency samples.
- Use the client daily for **two weeks**, with no lost answers, unexplained progress changes, or desktop interference. Record dates, versions, and any recovery events.
- Recheck the next competition's published rules and deadline, record the [three-minute demonstration](CONTEST_DEMO.md), then publish and submit a reviewed repository.

The implementation and demonstration script are available now. These outstanding gates must be completed before calling the release a qualified daily client or contest-ready 1.0.
