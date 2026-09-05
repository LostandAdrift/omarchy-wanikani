# Frozen-source verification

`tools/verify.py` runs the required automated checks against one **explicit, trusted local Git commit or tree**. It creates an independent archive; uncommitted checkout changes and private untracked files are excluded. It does not install the plugin, contact the running shell, reload the desktop, submit answers, prepare recordings, or publish results.

From the repository:

```bash
python3 tools/verify.py --revision HEAD
```

For another local checkout or a frozen tree ID:

```bash
python3 tools/verify.py --repository /path/to/omarchy-wanikani --revision <exact-tree-id>
```

`--revision` has no implicit default. The runner resolves it once using Git's `--end-of-options` handling and records its full object hash and tree hash. It accepts commit and tree objects; use `tag-name^{commit}` to peel an annotated tag. Shell expansion remains the caller's responsibility: quote revision expressions when needed. The runner uses subprocess argument arrays without a shell.

The invoking verifier can be newer than the selected revision. `runner_source` records the path and SHA-256 of the verifier loaded for this run, explicitly outside the new archive. The selected tree and tracked blob hashes describe the **plugin under test**, not an assertion that the invoking tool came from that tree.

## Private artifacts and unchanged source

By default, each invocation creates a new `0700` directory under `/tmp`. `--output-parent /existing/external/path` changes its parent, never an existing report or source directory. Output inside the source checkout, a directory beneath a plugin manifest, an installed Omarchy plugin path, or a path with symlink components is rejected. An inherited `TMPDIR` does not choose the archive location.

The directory contains:

| Artifact | Meaning |
| --- | --- |
| `source/` | Frozen extracted tree, owner-readable only; executable Git files retain owner execute permission. |
| `source.tar` | Original Git archive. |
| `tracked-blobs.json` | Expected Git blob hash and executable flag for every tracked file. |
| `report.json` | Structured status, provenance, timing, stage results, and integrity checks. |
| `python.log`, `manifest.log`, `qmllint.log`, `core_qt.log` | Private complete output for stages that started. |
| `qmllint.json` | Explicit JSON diagnostics outside the source archive. |
| `environment/`, `imports/` | Disposable private test state and the read-only `qs` import link. |

Git links, hardlinks, submodules, unsafe paths, duplicate archive members, and non-regular archived files are rejected. All member paths are checked before extraction. Each extracted file must match its tracked Git blob hash. The runner checks hashes, readonly permissions, executable flags, and the absence of extra source paths before testing, after every stage, and at the end. A changed archive fails the run and stops remaining stages.

Git `export-ignore` or `export-subst` attributes cannot silently change what was tested: omitted or rewritten tracked files fail the initial hash check. The runner does not alter those attributes or the checkout to make them pass.

Artifacts remain available on success, failure, timeout, or cancellation. There is no automatic cleanup, overwrite, or retry. To remove an old run, first review the reported path, make only that run's readonly `source` directories writable, then delete that specific private directory using ordinary file tools. Never apply a recursive permission change to the checkout or a shared temporary parent.

## Fixed required stages

The working directory for each stage is `source/`:

1. `python -B -m unittest discover -s tests -v`, using the invoking Python interpreter.
2. `omarchy plugin validate <archive>`, the installed read-only manifest validator.
3. Installed Qt `qmllint --ignore-settings --json <external-report> -I <private-imports>`, covering tracked root and `qml/` runtime QML files. No `--fix` or generated configuration is used.
4. Installed Qt `qmltestrunner -input <archive>/tests/qml -import <private-imports>` for the core Qt tests.

The import directory contains `qs -> /usr/share/omarchy/shell`. This link is outside the archive and only makes the installed type contract available. The tool records missing executables, missing shell imports, or missing test inputs as nonpassing stages. It does not fetch or install dependencies.

All stages use offscreen Qt with the Basic controls style. `HOME`, XDG config/data/state/cache/runtime paths, and the test `TMPDIR` point to private external directories. Python bytecode and user-site loading are disabled. The environment is built from an allowlist rather than copying the desktop environment: session bus, display, Wayland, Hyprland, PipeWire/PulseAudio endpoints, tokens, Python startup options, and opt-in flags such as `WANIKANI_DECODER_QA` are absent. New inherited QA flags are omitted by default too. The normal executable `PATH` remains available for installed test dependencies.

**This is environment isolation, not a security sandbox.** Only run trusted source. Python tests are executable code running as the invoking user; the runner cannot prevent a malicious test from opening a socket or reaching an absolute host path. The plugin's normal test suite uses authored fixtures and mock transports. Opt-in decoder, hosted desktop, live-account, and daily-use qualification remain separate activities; this runner does not claim those gates passed.

## Results and cancellation

Standard output prints only the outcome, resolved revision, archive path, and report path. Detailed logs stay private. Exit codes are:

| Code | Meaning |
| --- | --- |
| `0` | All four required stages completed successfully and both integrity boundaries passed. Inspect recorded skips and lint warnings. |
| `1` | A stage failed, timed out, lacked a dependency/input, produced incomplete evidence, or changed the archive. |
| `2` | Arguments, revision resolution, or private output preparation failed before a run could be established. |
| `130` | The run was cancelled. |

`report.json` schema version 1 includes the plugin version, exact revision/tree, verifier provenance, UTC start/finish times, and every required stage. Each stage records status, exit code, duration, summary, missing tools, and its log/argv when started. Stages after cancellation remain `not_run`. Stages that fail normally do not suppress independent later checks unless source integrity changed.

Python summaries distinguish tests, skips, failures, errors, expected failures, unexpected successes, and the final `OK`/`FAILED` outcome. Zero executed checks, all-skipped Python tests, missing summaries, and `FAILED` with exit code zero cannot pass. Expected failures remain explicit as `passed_with_expected_failures`. Core Qt requires a substantive passed check beyond initialization/cleanup and records totals/skips separately. Lint JSON must cover every requested runtime QML file; its information, warning, and error counts are distinct. Existing dynamic shell-property warnings are visible as `passed_with_warnings`, not described as a warning-free build. Skipped tests are `passed_with_skips`; they are never implied to have run.

`--timeout` sets the maximum per stage, from 1 to 7200 seconds; the default is 1800. Ctrl+C or SIGTERM terminates the runner's current stage process group, escalates to SIGKILL if it does not stop, verifies the archive, and preserves the final report. It never targets an installed shell or worker. A forced kill of the verifier itself can leave the last report marked `running`; treat that as incomplete, retain the artifacts, and start a new run rather than converting it into a pass.

## Verification of the runner

`tests/test_verification_runner.py` uses tiny temporary Git repositories, inert stage executables, and owned disposable subprocesses. It checks frozen versus uncommitted bytes, archive path rejection, symlinks/hardlinks, omitted tracked files, executable-bit changes, hostile revision argument handling, environment isolation, missing tools, misleading success exits, warning/skip counts, cancellation, and timeouts. It does not invoke the full plugin suite, installed shell, real account, or hosted native QA.
