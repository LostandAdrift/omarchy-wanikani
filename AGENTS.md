# WaniKani for Omarchy

Native Omarchy 4.0.2 / Quickshell 0.3.1 plugin. Read docs/IMPLEMENTATION.md before continuing work.

- Never modify packaged files in /usr/share/omarchy. Reuse qs.Commons and qs.Ui.
- No real WaniKani mutations in automated tests. Use demo data and mock transports.
- A local UUID is not server idempotency. Never automatically retry an uncertain write.
- Persist answers before advancing. Preserve incomplete sessions and error counts on close/crash.
- Keep secrets out of source, shell.json, process arguments, logs, and diagnostic exports.
- Run `python3 -m unittest discover -s tests -v` and `omarchy plugin validate .`.
- Use /usr/lib/qt6/bin/qmllint and qmltestrunner for QML with the installed shell import path.
- Do not claim live-account testing or the two-week daily-use release gate has passed without evidence.
