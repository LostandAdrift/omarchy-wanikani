# Fourteen days of personal use

**Qualification is pending.** Copy this template into private notes. Blank cells and demo sessions do not qualify live-account reliability. Keep tokens, answers, and personal notes out of shared reports.

Record the installed revision separately from the tested source revision. Features described in the current checkout may not yet be installed; [overnight tracking](OVERNIGHT_WORK.md) records that distinction. Installation and hosted checks are currently deferred by the [lock/reload incident](LOCK_RELOAD_INCIDENT.md). Perform restart/update portions only after that issue is cleared, with the desktop unlocked and study closed. Agents may help inspect status and open requested views; the learner supplies all live answers, ratings, and playback checks.

## First session

Keep an existing working account connection. Token replacement and session-only restart checks are separate, deliberate authentication exercises; they are not needed to try a new plugin version.

- [ ] Rehearse in **Try the demo**: five reviews, Escape/resume, Lookup, and simulated offline/reconnect. Confirm the saved question and draft return.
- [ ] Check the connected account name, level, review count and accessible Lookup content against WaniKani. If connecting for the first time, a read-only token is sufficient for this check.
- [ ] Connect study permissions: assignment starts and review creation; study-material create/update for notes and synonyms. Choose meaning strictness, audio/voice, cache size, reminders, and ambient settings.
- [ ] Check offline readiness and sync freshness; required images and optional audio are separate. Deliberately complete up to five **real due subjects**, acknowledge final feedback, and inspect **Saved submissions**. Submit only answers you intend to commit; use demo or ungraded practice for fault experiments.
- [ ] After the audio features are installed, deliberately play an original vocabulary recording and verify audible Japanese and the displayed voice/pronunciation. In **Listen**, reveal before choosing Got it or Again. In **Type kana**, finish the current recording, type an answer, inspect feedback, then Continue. Check replay, Stop, silent reopen, draft resume, Skip and immediate Undo. Decoder tests and CLI dispatch do not establish audible output or human hearing; these local skills must not change WaniKani's schedule.

## Optional authentication exercise

Use this only when deliberately qualifying authentication, with the desktop fully unlocked and study closed. Preserve pending data. Clear **Remember securely in the desktop keyring** for session-only authentication; Settings should report session storage. After a normal plugin restart, cached state should remain and token re-entry should be required. Resolve any older-token removal notice, then restore your preferred credential storage. Do not put the token in a report or ask an agent to retrieve it.

## Daily record

Use `R/L/P` for completed reviews/lessons/practice. Record meaning-listening and kana-dictation results separately under Audio; do not combine them with WaniKani confirmations. Each audio skill has its own five-new-word daily allowance. Mode: online, offline, read-only, or demo; include session-only/keyring when relevant. Record pending counts before/after and any attention state. Write `none` for a checked problem-free field; `not tested` for an unused feature.

| Day / date | Installed version / commit | Mode | Completed R/L/P | Audio: listening / dictation | Pending start → end | Recovery / discrepancy | Desktop interference |
|---|---|---|---|---|---|---|---|
| 1 / | | | | | | | |
| 2 / | | | | | | | |
| 3 / | | | | | | | |
| 4 / | | | | | | | |
| 5 / | | | | | | | |
| 6 / | | | | | | | |
| 7 / | | | | | | | |
| 8 / | | | | | | | |
| 9 / | | | | | | | |
| 10 / | | | | | | | |
| 11 / | | | | | | | |
| 12 / | | | | | | | |
| 13 / | | | | | | | |
| 14 / | | | | | | | |

During ordinary use, cover lessons, partial-answer resume, typo correction, notes/synonyms, image radicals, audio, and offline/reconnect. Record keyboard/IME, selection lookup, theme/monitor changes, suspend/resume, lock, Do Not Disturb, and ambient/screensaver behavior as encountered. Preserve desktop settings. Plugin charts describe local activity only.

If progress looks wrong, keep local data and note the time/version. Open **Saved submissions** to inspect the record first. Its **Refresh remote progress** action synchronizes the account and may submit already completed pending work; choose it only when you intend that synchronization. Uncertain results are never blindly resent. **Keep remote & archive** archives the local result after its confirmation; check the remote assignment first. Export redacted diagnostics for problems and preserve pending work.

For a requested weekly recap, `python3 tools/wanikani.py report --days 7 --json` reads cached local aggregates only. Keep the report's own calculation timestamp, local date range and stale/unknown label alongside the daily record. It can omit a session finished after that timestamp; unavailable totals are not zero, and completed local cycles are not proof of server confirmation. See [report scope](AGENT_SUPPORT.md#cached-learning-reports).

After fourteen days, investigate every discrepancy. Lost answers, unexplained progress, or desktop interference require fixes and further qualification. Record **pending / needs work / daily-use gate passed**, with dates and evidence. Other [release gates](VERIFICATION.md#remaining-release-gates) still apply.
