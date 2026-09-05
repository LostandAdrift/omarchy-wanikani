# Lock ownership after a plugin reload

Incident observed **2026-09-05**, Omarchy **4.0.2-1**, Quickshell **0.3.1-1**. Hosted QA and installed updates were deferred. This record uses existing read-only lock status, projected monitor state, narrowly filtered Omarchy journal entries, and source inspection. It is not a recovery procedure or an upstream report.

## Observed evidence

All times below are UTC. The relevant shell entries share one process ID.

| Time | Evidence |
|---|---|
| 08:26:04.051 | Omarchy logged `lock-requested` and `lock-pending: screen-stabilizing`. |
| 08:26:04.576 | Omarchy logged `secure=true`: a lock preceded the later QA plugin reloads. |
| 08:44:03.183 | A local WaniKani QA plugin change triggered reload. Built-in IPC handlers then reported duplicate registrations. |
| 08:44:03.993 | The lock service logged `lock-stranded: recovering`, then requested/pending. |
| 08:44:20.727–08:44:21.550 | Further QA file-change reload entries and duplicate built-in handlers were followed by another stranded-lock recovery and requested/pending. |
| By 09:29 | Status still reported the 08:44:21.550 pending event. |

The inspected status was `locked:true`, `requested:true`, `pending:true`, `sessionLocked:false`, `secure:true`, `realScreens:3`, `passwordPam:true`, `fingerprint:false`, `authenticating:false`. All three valid monitors reported compositor `LOCK` and `dpmsStatus:false`. This establishes an actual compositor lock; it does not establish what the user could see or whether an older authentication surface survived.

## Source-backed explanation and limits

The installed [shell reload path](/usr/share/omarchy/shell/shell.qml:739) calls [unloadPluginServices](/usr/share/omarchy/shell/shell.qml:348), destroying all registered services, including `omarchy.lock`. A local plugin change therefore affects lock ownership, even though WaniKani's runtime only reads the lock service. Ordinary [plugin removal](/usr/share/omarchy/bin/omarchy-plugin-remove:117) also invokes the global rescan/reload; directory deletion additionally reaches the plugin watcher. The timestamps strongly associate this incident with QA lifecycle changes, but do not constitute a controlled reproduction or prove the exact surviving object graph.

Quickshell 0.3.1 exposes instance-owned `locked` and process-wide `secure` through different mechanisms. A replacement service can consequently observe `secure:true` without owning a lock. Its [requestSessionLock](/usr/share/omarchy/shell/plugins/lock/Service.qml:64) returns immediately on `secure`, leaving `pending` and its old “screen-stabilizing” label set. Three valid screens and this early return explain why waiting longer need not resolve it. See the versioned [WlSessionLock implementation](https://raw.githubusercontent.com/quickshell-mirror/quickshell/v0.3.1/src/wayland/session_lock.cpp) and [underlying manager implementation](https://raw.githubusercontent.com/quickshell-mirror/quickshell/v0.3.1/src/wayland/session_lock/session_lock.cpp).

Normal unlock is a concern, not a verified escape route. The replacement's password view exists inside its [lock surface](/usr/share/omarchy/shell/plugins/lock/Service.qml:264), which it has not acquired. Even successful authentication reaches [finishUnlock](/usr/share/omarchy/shell/plugins/lock/Service.qml:148), assigning `false` to its already-false instance lock; Quickshell's setter then does nothing to another manager's lock. Fingerprint authentication was unavailable in the observed status. An older surviving service/surface was not inspected, so this does not prove every possible authentication path is inaccessible. Quickshell documents the [compositor failsafe after destruction of a locker](https://quickshell.org/docs/v0.3.1/types/Quickshell.Wayland/WlSessionLock/); no display-color claim is made here.

No supported recovery procedure for this exact state was found in the inspected interfaces. The packaged [restart guard](/usr/share/omarchy/bin/omarchy-restart-shell:21) refuses a compositor-locked session when `secure` or `requested` is true; its orphan recovery branch therefore does not cover the observed state. No bypass, authentication attempt, unlock, restart, reload, screenshots, or idle/configuration changes were performed during the investigation.

## Project mitigation

The [native QA harness](../tools/native_qa.py) checks typed lock status **before installation and before cleanup removal**. Locked, locking, or unknown state defers the operation. Cleanup retains the marked temporary plugin and writes `cleanup-deferred` to its private run record for later explicit removal after the desktop is normally unlocked; it does not delete files or trigger a reload while locked. [Fixture tests](../tests/test_native_qa.py) cover these guards. These checks reduce lifecycle exposure; they are not an atomic lock reservation or a repair of Omarchy's reload mechanism. Further host verification remains gated, and the incident has not been published upstream.


## Follow-up · September 5, 14:32 UTC

A single read-only status check now reports `locked:true`, `requested:true`, `pending:false`, `sessionLocked:true`, `secure:true`, `realScreens:3`, with `lastEvent:"secure=true"` at `2026-09-05T11:45:30.316Z`. The current lock service therefore reports instance ownership again; the earlier `sessionLocked:false` mismatch is **not** the latest observed state. This is status evidence only. The transition was not observed, its cause is unknown, and no authentication or unlock was tested. Do not describe the desktop as currently proven stranded on the basis of the older observation.

The desktop is still locked, so installation and hosted lifecycle changes remain deferred. No unlock, reload, restart, configuration change or host screenshot accompanied this read. The earlier incident, its source explanation and the need to avoid plugin lifecycle changes while locked remain relevant; the current flags do not establish a released upstream fix or complete the lock/suspend qualification gate.
