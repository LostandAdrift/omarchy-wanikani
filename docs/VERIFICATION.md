# Verification and release qualification

Development release: 0.1.0. Keep this record factual; passing fixture tests does not establish live-account safety or two weeks of daily use.

## Automated

- Python: `python3 -m unittest discover -s tests -v`.
- Manifest: `omarchy plugin validate .`.
- Kana: `QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME= QT_QUICK_CONTROLS_STYLE=Basic /usr/lib/qt6/bin/qmltestrunner -input tests/qml/tst_Kana.qml`.
- QML static checks require a temporary import root whose `qs` link points to `/usr/share/omarchy/shell`; invoke qmllint with `-I <temporary-root>`.
- Quickshell modules are statically registered by the host executable on this installation. Native shell surfaces must be validated in the hosted plugin; plain qmltestrunner cannot load the Quickshell core plugin. Kana tests do run under ordinary QtTest.

Python cases cover deterministic grading, exclusions/synonyms, alternate readings, normalization, saved drafts, error counts, corrections, duplicate command IDs, transactional rollback, feedback acknowledgment, lesson submission type, ungraded practice, offline pending exclusions, expiry/vacation, note drafts, interrupted writes, remote conflicts, malformed success, permissions, rate limits, reset invalidation, and safe recovery.

## Desktop matrix

Record actual outcomes for: install/enable/reload/disable/remove; opening/resuming every view; keyboard entry/cursor/composition/Enter/Escape; all bar positions; theme changes; scale factors; multi-monitor focus; screenshots; suspend/resume; DND; lock; screensaver handoff; audio output.

Performance targets: warm surface open <=200ms; local grading <=50ms; idle worker plus incremental shell CPU <0.5% of one core. Report measured values and workload, not assumptions.

## Before 1.0 / contest entry

- Connect a real token through the native setup screen and complete deliberately answered lessons/reviews.
- Confirm pending work against WaniKani after going offline and returning online; exercise a second client.
- Use as the daily client for two weeks, with no unexplained progress changes or lost answers.
- Verify the next contest's published dates/rules, prepare screenshots and a short demo, then submit the public repository.

No automated test may manufacture graded answers on a real account.
