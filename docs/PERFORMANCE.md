# Native performance collection

`tools/profile_native.py` reads existing Linux `/proc` counters. It never enables, disables, restarts, opens, or changes the plugin or desktop. The default measurement is 45 seconds with observations every five seconds. It does not contact WaniKani, the keyring, or desktop IPC.

The [verification record](VERIFICATION.md) separates current measurements from release targets. One observed 45-second worker sample measured 0.0222% of one core, RSS 31.34 MiB, PSS 18.26 MiB, and private memory 16.60 MiB. A shared-shell baseline sequence was rejected after a shell restart; a later disabled/enabled pair remained too noisy to establish incremental QML cost. These are development observations, not certification of the combined idle target.

From the repository, collect a private JSON report:

```sh
wanikani_profile_dir=$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/wanikani-profile.XXXXXX")
python3 tools/profile_native.py sample --output "$wanikani_profile_dir/enabled-before.json"
```

The collector discovers the production worker at the installed plugin path or this repository's `backend/worker.py`, plus the Quickshell process using `${OMARCHY_PATH:-/usr/share/omarchy}/shell`. Generated QA workers and Quickshell IPC clients do not match. Ambiguous matches fail. For another layout, use `--worker-script /absolute/path/backend/worker.py` or `--shell-root /absolute/path/shell`. Known PIDs can be selected with `--worker-pid PID --shell-pid PID`; this measures those exact processes and skips command-line discovery when both are supplied.

Reports contain process IDs, process start ticks, timestamps, numeric counters, and fixed status messages. No command lines, environments, account state, tokens, usernames, or mapped-file paths are exported. `--output` writes at mode 0600, replacing an existing symlink without following its target. Without that option, JSON goes to standard output.

## Interpret one sample

- `worker` measures the Python worker alone. `shared_shell` measures the entire already running Omarchy shell, including every other plugin and native surface.
- `cpu_percent_one_core` uses the change in process user plus system CPU ticks divided by the actual observation interval. It excludes child processes and is not divided by the machine's core count. A multithreaded process can exceed 100%.
- `cpu_tick_resolution_percent_one_core` states one tick's measurement quantum. For 100 Hz counters over 45 seconds it is approximately 0.0222%. A zero reading means no tick increase was observed; it does not establish zero cost.
- RSS counts resident pages, including shared pages. PSS apportions shared pages. Private bytes sum private clean, dirty, and huge pages. Memory includes first, last, minimum, maximum, median, and the number of available observations.
- Memory prefers `smaps_rollup`, then `smaps` on older kernels. Permission failures and missing fields remain explicit. Approximate RSS can fall back to `stat`; unavailable PSS or private bytes stay `null`, never zero.
- Exits, zombies, PID reuse, restarts, or discovered process-set changes invalidate the sample. The collector does not silently switch to the replacement process. Events entirely between observations may be missed. A missing worker is recorded as `not_running`, which is expected for a disabled baseline.

Exit status is 0 for a completed valid report, 1 for an invalidated report, 2 for selection/input/read errors, and 130 for cancellation. Long captures are supported with `--seconds`; individual waits never exceed 30 seconds. The tool does not certify a performance target on its own.

## Estimate the contribution inside the shared shell

Use an enabled → disabled → enabled sequence with the same shell process. Close study first so its saved session is durable. Let synchronization and surface transitions settle before each capture. Keep theme, monitor arrangement, idle settings, other plugins, and desktop activity as consistent as possible. Record whether ambient surfaces were enabled; compare the same conditions in both enabled runs. The collector does not control these conditions.

1. Collect `enabled-before.json` using the command above.
2. Disable WaniKani with the normal Omarchy plugin controls. Do not restart the shell. Once it settles, collect the baseline:

   ```sh
   python3 tools/profile_native.py sample --output "$wanikani_profile_dir/disabled.json"
   ```

3. Re-enable WaniKani and let it settle. Confirm saved study still resumes, then close the panel and collect the final sample:

   ```sh
   python3 tools/profile_native.py sample --output "$wanikani_profile_dir/enabled-after.json"
   python3 tools/profile_native.py compare \
     "$wanikani_profile_dir/enabled-before.json" \
     "$wanikani_profile_dir/disabled.json" \
     "$wanikani_profile_dir/enabled-after.json" \
     --output "$wanikani_profile_dir/comparison.json"
   ```

The comparison requires a stable shared-shell PID and start time, valid samples, and a worker present only in the enabled samples. It reports both enabled-minus-disabled differences, their mean, and the spread between enabled runs. Memory differences use each sample's median. Negative differences remain visible.

This is an estimate of additional work and memory in the whole shell. Background activity, allocator retention after unloading, shared libraries, other plugins, and measurement overhead can dominate small differences. If enabled runs disagree materially, collect a longer or repeated sequence and retain the spread. Do not report shared-shell RSS as plugin memory or a noisy negative difference as a zero-cost result. Keep standalone worker measurements separate. Live desktop and two-week daily-use qualification remain separate release gates.

Parser, accounting, discovery, output-privacy, and restart checks use authored fixtures:

```sh
python3 -m unittest discover -s tests -p test_native_profile.py -v
```

## Avoiding unnecessary work

An authored 9,016-subject fixture measured one ambient catalogue response at a 30.178 ms median and 32.795 ms p95 across eight samples, returning 60 details and 56,875 JSON bytes. These timings measure the unchanged backend query; the service optimization avoids invoking it when no surface needs the result. Desktop/idle displays request only during their eligible visible interval. Manual Zen explicitly acquires demand, including with both automatic displays disabled. Reads coalesce for 25 ms with one request in flight, and periodic ambient refreshes run only while needed. Access invalidation remains immediate. The 30-capture hosted fixture run on DP-3 confirmed zero ambient requests across ordinary views and one request for opened Zen; its temporary plugin was removed.

Answer and lesson navigation can emit compact session updates, leaving catalogue summaries to full refreshes and explicit dashboard/Settings opening. Independent session and full-state revisions prevent delayed responses from undoing newer feedback or counters. Editor keystrokes use small durable acknowledgments without a full state event: 100 authored writes measured a 10.391 ms median, 10.586 ms p95, and a 96-byte acknowledgment, creating no submission operations. These measurements use fixture databases; they are separate from first-pixel latency or real-key input measurements.
