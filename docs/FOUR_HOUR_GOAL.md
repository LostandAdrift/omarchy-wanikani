# Four-hour improvement goal

User explicitly requested persistent work for four hours, including new features and improvements after the original implementation is complete.

- Start: 2026-09-05 01:43 UTC / September 4, 18:43 America/Los_Angeles.
- End: 2026-09-05 05:43 UTC / September 4, 22:43 America/Los_Angeles.
- Persistent goal created in Codex. Keep it active for this work window; finish useful work, verify and checkpoint as it progresses. A context reset does not cancel it.
- No token budget was requested or set.

## Working priorities

1. Finish final credential cleanup and lesson-relationship fixes, tests, docs and installed checkpoint from the original plan.
2. Make frequent short sessions better: deliberate practice selection, useful mistake review, clear feedback and keyboard access.
3. Improve local lookup and subject exploration without contacting external translation services.
4. Explain offline readiness and synchronization status in useful learner-facing terms; strengthen fault and lifecycle tests.
5. Polish native surfaces and accessibility, measure shared-shell overhead, and prepare repeatable release QA tools.

Choose improvements based on inspected code and observed behavior. Keep batches reviewable. Do not add novelty that compromises study reliability or distracts from returning to work.

## Performance emphasis

The user additionally emphasized performance during the active window: make the plugin as fast and responsive as possible. Prioritize measured hot-path latency, unnecessary catalogue/history scans, UI refresh work, startup/warm opening, and idle overhead. Preserve transactional answer durability and synchronization safety; do not trade them for optimistic progress. New recap work must stay lazy and outside active question/typing paths.

Later steering: do not spend too much time on performance while UI and useful features remain. The user encouraged creative freedom. The sixth batch therefore canceled further timing work and shifted to lesson notes, kanji comparison cards, an interactive forecast, quiet recall, and native layout polish. See [next feature proposals](NEXT_FEATURES.md) for concrete follow-on directions.

## Constraints

- Preserve the existing saved demo session, unrelated desktop settings, original theme and bar position.
- Real WaniKani authentication belongs in native Settings. Automated study uses fixtures and mock APIs only.
- Do not silently retry uncertain API writes or manufacture real study completions.
- No public publication or contest submission has been requested.
- Two weeks of personal daily use, live account/media and disruptive native desktop checks remain qualification gates; never claim they happened.

## Checkpoints

- 01:43 UTC: Goal started. Original development implementation already installed at commit 19a9e31; 83 Python tests and 44 Qt checks passed. Final audit found session-only cleanup and lesson relationship issues, now being fixed. Native screenshots and factual verification documentation are being added.

- 01:46 UTC: Credential cleanup supports missing keyring/session-only mode and explicit deletion; retry UI remains available. Lessons show related subjects. All 89 Python tests pass. Next parallel work: practice library, accessible keyboard help, offline readiness; parent improving lookup and native integration.

- 02:06 UTC: First improvement batch implemented: native practice library, ranked Unicode/romaji/synonym lookup with filters, asynchronous offline readiness and sync stages, F1/navigation help, focus scrolling, held-activation guard, and authoritative immediate resume. 140 Python tests/49 Qt checks pass. Search 16 ms median across 9,016 subjects, answer plus advance 11 ms. Hosted QA is next; a disposable fixture harness is being prepared. Further audits found numeric-grading/malformed-answer risks and avoidable rate-pacing/media delays, queued for the next batch.

- 02:38 UTC: Second batch verified: strict/safe grading and cache validation, subscription access, burst-aware rate pacing, suspend/reconnect handling, paginated recovery, and privacy/setup hardening. 234 Python tests and 49 Qt checks; hosted fixture lessons, saved draft, three offline completions and recovery passed at observed 1.5 monitor scale. Preparing a committed installed checkpoint. Next: shared-shell profiling and confirmed account-level milestone UI.

- 03:10 UTC: Third batch passed 303 Python tests and 61 Qt checks. Native 26-capture fixture run verified milestone preview, independent practice/graded resume, and unsaved note drafts through offline Save and reconnect. Added accessible Japanese text fitting and named cached audio voices; queue/reset scans remain bounded with large histories. Stable worker sample averaged 0.0222% of one core; shared-shell attribution remains unqualified. Next: randomized long-session soak and long-history profiling, then richer completed-session recaps.

- 03:53 UTC: Fourth checkpoint: 357 Python tests, 93 Qt checks, 30 native fixture captures passed. Session/epoch/full-snapshot ordering prevents stale answers/counters and deleted-state revival; compact question events and on-demand ambient remove repeated scans. Covered schedule queries reduced the full catalogue snapshot to about 36 ms; bounded new-review selection measured 18.8 ms response median in the one-subject stdio benchmark. 5,000 randomized mock interactions passed. Next: preserve required offline media under cache pressure, bound database locks during API imports, then repeat native/performance qualification and install final checkpoints through the remaining window.

- 04:23 UTC: Fifth batch passes 429 Python tests, 93 Qt checks and 30 native captures. Required media is retained under strict budgets; 128-resource imports leave room for answer transactions; malformed-level resets/access and duplicate-reply presentation are safe. Native timing with 9,016 subjects found saved study at 45.5 ms median through render readback and a 234 ms Practice bottleneck. Practice now validates displayed pages only and coalesces opening requests; measured backend page checks are 40.6 ms Suggested / 55.6 ms Learned. Final native Practice opening is 83.5 ms median with one request; saved study 43 ms. Ten thousand randomized interactions passed, including 417 restarts and 304 duplicate commands. Next: publish the local checkpoint, show tomorrow’s offline readiness with expiry-aware access, and reduce duplicate command-response storage losslessly without deleting deduplication IDs. Keep working until 05:43 UTC.

- 05:06 UTC: Sixth batch adds personal notes during lessons/feedback, large side-by-side kanji comparisons, an interactive review forecast, quiet ungraded recall in Zen, and narrow-panel layout fixes. It also finishes expiry-aware next-day readiness, damaged radical-image guards, hidden-page/audio fixes, and lossless command journal storage. Verified 468 full-suite Python tests plus one late rendering wrapper, 107 core Qt checks and five Forecast surface checks. The final 34-capture native workflow passed on the existing DP-2 scale 1.5; temporary fixture removed, zero namespace warnings. Another 5,000 randomized interactions passed. Additional timing work was canceled in favor of UI, as requested. Preparing the local install checkpoint; keep working until 05:43 UTC.

- 05:32 UTC: Seventh batch adds a local selected-text reading trail with exact passage preservation, theme-aware word links, eight-button disclosure, overlapping matches and pending-work labels. Native 36-capture workflow passed. Verified 489 distinct Python tests and 112 core Qt checks, including rare-kanji limits and delayed detail/clipboard navigation guards. Final log review found one transient offline-status boolean warning during reset; fixing it before the final installed checkpoint. Daily-use qualification guidance and final packaging checks are in progress.

- 05:36 UTC: Final seventh-batch native run passed all 36 captures, including Help→word detail→original passage, with zero namespace errors/warnings and exact runtime source hashes. Manifest, Markdown links and whitespace checks passed. Added a private-use fourteen-day qualification log and updated the contest demonstration and next-feature proposals. Preparing the final installed checkpoint; the original demo session digest was recorded before the update.
