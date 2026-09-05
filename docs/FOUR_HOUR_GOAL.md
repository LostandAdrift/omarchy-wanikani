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

## Constraints

- Preserve the existing saved demo session, unrelated desktop settings, original theme and bar position.
- Real WaniKani authentication belongs in native Settings. Automated study uses fixtures and mock APIs only.
- Do not silently retry uncertain API writes or manufacture real study completions.
- No public publication or contest submission has been requested.
- Two weeks of personal daily use, live account/media and disruptive native desktop checks remain qualification gates; never claim they happened.

## Checkpoints

- 01:43 UTC: Goal started. Original development implementation already installed at commit 19a9e31; 83 Python tests and 44 Qt checks passed. Final audit found session-only cleanup and lesson relationship issues, now being fixed. Native screenshots and factual verification documentation are being added.

- 01:46 UTC: Credential cleanup supports missing keyring/session-only mode and explicit deletion; retry UI remains available. Lessons show related subjects. All 89 Python tests pass. Next parallel work: practice library, accessible keyboard help, offline readiness; parent improving lookup and native integration.

- 02:06 UTC: First improvement batch implemented: native practice library, ranked Unicode/romaji/synonym lookup with filters, asynchronous offline readiness and sync stages, F1/navigation help, focus scrolling, held-activation guard, and authoritative immediate resume. 140 Python tests/49 Qt checks pass. Search16ms median across9016subjects, answer+advance11ms. Hosted QA is next; a disposable fixture harness is being prepared. Further audits found numeric-grading/malformed-answer risks and avoidable rate-pacing/media delays, queued for the next batch.

- 02:38 UTC: Second batch verified: strict/safe grading and cache validation, subscription access, burst-aware rate pacing, suspend/reconnect handling, paginated recovery, and privacy/setup hardening. 234 Python tests and 49 Qt checks; hosted fixture lessons, saved draft, three offline completions and recovery passed at observed 1.5 monitor scale. Preparing a committed installed checkpoint. Next: shared-shell profiling and confirmed account-level milestone UI.
