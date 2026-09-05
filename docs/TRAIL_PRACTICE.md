# Practise words from your desktop

Implemented and source-verified in milestone 0.2.8: 1098 combined Python tests and 126 core Qt checks passed; installation is deferred. See VERIFICATION.md and OVERNIGHT_WORK.md for the exact qualification and installed revision. This document is not a release claim.

The reading trail already finds exact WaniKani catalogue matches in explicitly selected Japanese. Add a deliberate next step: choose up to twenty of those words for ungraded practice, then return to the same passage. This connects desktop lookup to learning without treating the catalogue as a translator or sending the passage to a server.

## Interaction

“Choose words to practise” opens native selection controls below the passage. The learner chooses words; a local preview reports cached readiness and any unavailable items. Meanings and readings remain absent from that preview. The primary action starts only the selected words after validation, without changing WaniKani scheduling. It never auto-starts from a clipboard read or report.

An existing ungraded session has a separate Resume action. Starting a different selection explicitly replaces that active practice reference; the interface explains this before its Start new practice action. Saved lessons and reviews, including their drafts and errors, remain exact. A Back to passage action returns from this practice session to the original text and chosen words. Selection and return context remain in the panel's memory across closing, details and view changes, and clear on account/content changes. They are not stored in diagnostics or a new passage database.

## Boundaries

- Accept at most 256 Unicode code points and one to twenty unique positive safe subject IDs. IDs must still be exact matches in the current local trail; reject unrelated or silently truncated selections.
- Recheck accessible subject content and every unresolved graded queue's IDs and written aliases. A malformed protection record withholds the new trail action. Completed work waiting for synchronization can still be practised independently, with its waiting/attention status visible.
- Preview is read-only. Start repeats validation in the same SQLite transaction as the existing practice start and durable command acknowledgement. Check the expected data epoch and saved-practice revision so a stale preview cannot replace a different session.
- A local request ID deduplicates this local transaction. It provides no WaniKani server idempotency, and this feature creates no WaniKani writes.
- Keep existing deliberately selected generic practice policy unchanged. This new passage-driven entry has its own stricter match/protection validation. A static origin marker keeps those guards on its saved session and duplicate command replies, including later resume/answers. Only the bounded selected IDs are checked after creation; the original passage is not retained in the session or journal.
- Drop stale presentation callbacks after query, account, study, worker, navigation or lock changes. A durable result that finishes after closing remains resumable; a late response cannot reopen the panel.
- No automatic audio, network call, clipboard polling, new timer service, global shortcut, microphone or filesystem export is added.

## Verification

Use authored passages and mock/inert transports. Cover exact Unicode and overlaps, duplicates and unrelated IDs, hidden/expired content, missing required text, malformed protection, same-glyph aliases, pending graded work, no retained passage in the command reply, account/data and saved-practice races, duplicate request replay, crash rollback/commit, and exact graded-session/outbox preservation. Exercise actual native selection controls at narrow widths, selected-state accessibility, delayed previews, keyboard navigation, close/detail return and live theme changes. Hosted qualification remains subject to the desktop lock incident and later personal use.
