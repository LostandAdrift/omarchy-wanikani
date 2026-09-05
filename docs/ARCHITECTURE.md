# Architecture

The Omarchy manifest declares a service, bar widget, and one persistent panel. The shell owns the QML objects. The service owns one Python worker through private stdin/stdout pipes. Panel views share that worker and account state across monitors. No extra Quickshell process or daemon is installed.

## Protocol

Request: `{"v":1,"id":"unique-request-id","method":"answer","args":{"text":"mountain"}}`.

Response: `{"v":1,"id":"unique-request-id","ok":true,"data":{...}}`; errors use `ok:false,error:{code,message}`. Events are `ready`, `state`, `session`, `readiness`, and `sync_progress`. Session-only changes, offline availability, and synchronization progress can update independently without rebuilding the catalogue summary. Secrets are accepted only by `authenticate` and never echoed. Background synchronization has its own thread; local commands are serviced while HTTP is in progress.

Study mutation methods are `start`, `draft`, `answer`, `correct`, `advance`, `lesson_next`, and `finish`. Explicitly saving synonyms or notes uses `set_material`; `editor_draft` and `editor_discard` keep unsaved text local. `pin`, `settings`, `snooze`, and `ack_milestone` change local preferences or acknowledgments. Milestones arrive inside state snapshots; acknowledging one does not change account progress.

Read methods include `snapshot`, `session`, `search`, `details`, `ambient`, `practice_catalogue`, `recovery`, and `voices`. `readiness` retrieves or requests a local cache-availability refresh. Account and maintenance methods include `authenticate`, `disconnect`, `use_demo`, `sync`, `clear_cache`, `delete_data`, `resolve`, and `diagnostics`. The periodic `tick` checks wake/clock changes and schedules eligible background refreshes.

SQLite stores API resource snapshots, sessions, local events, command replies, synchronization cursors, and the submission queue. A reentrant lock serializes short transactions across the command and network threads. WAL and FULL synchronous mode protect the local acknowledgment boundary. The command effect and reply commit together so the same local request ID cannot increment errors or advance twice.

Duplicate replies retain the original session identity, revision and grading outcome. Their subject presentation is projected through current account access, notes and cached media before returning; an old command cannot display expired content or restore a removed note. Restricted views hide displayed answer text while retaining the durable session and original command record. Reprojection loads only the original reply's subject and never executes its handler again.

Native `practice_catalogue` requests use `readiness_scope:"page"`. Group membership, ordering and counts describe the current accessible catalogue; accepted-answer and image validation applies only to the displayed page. `page_ready` states that scope explicitly, while `ready_counts` and `ready_total` are null. The default `"all"` scope remains available for complete-library checks. Constructing a native page coalesces duplicate initial requests; no readiness cache can mask changed answers or missing image files.

The `session` event carries `{session,paused_graded,session_revision,session_epoch}`. Session saves advance a durable global revision, also exposed as `revision` on session-view replies. The service observes session replies before invoking their callbacks and ignores older session fields from later full or partial updates. Full snapshots have a separate `state_revision`, allocated at the beginning of their construction. An older full snapshot cannot roll back catalogue counts or account context, even when it read a newer session at the end; only a strictly newer same-account, same-epoch session can be accepted separately from that rejected catalogue.

Session ordering resets on an account/demo context change, using `[demo,username]`, or when a newer full snapshot establishes a new `session_epoch`. The durable epoch survives restarts and changes after explicit database deletion, allowing a demo reset with the same username to clear its old session safely. Partial events and RPC replies from an old epoch cannot restore deleted work. A changed access grant does not reset ordering, and all accepted subject content remains restricted to the current grant. Full-state sequence numbers restart with the worker; durable session revisions do not. The service's `applySnapshot` entry point applies these guards to both pushed events and explicitly requested snapshots.

## Study state machine

Lessons: presentation → quiz question → feedback → next question / completed subject.
Reviews and practice: question → feedback → next question / completed subject.

Each subject stores required parts, completed parts, and error counts independently. An incorrect answer increments the relevant count. A typo correction can decrement that one current error and marks feedback corrected. `advance` applies accepted feedback and creates the outbox item only after every required part is complete. `draft` is persisted during input. Hiding a panel does not finish a session.

Practice and graded sessions have independent saved state. Explicit practice can run while a graded session is paused; Resume prioritizes that graded session. Practice never creates submission operations and remains available for subjects with pending graded work.

## Unsaved study-material input

`editor_draft` accepts `subject_id` and `values:{synonyms_text,meaning_note,reading_note}`. Raw synonym text keeps spacing and unfinished commas; each field is limited to 2,000 Unicode characters. Every committed text change is sent immediately, without a debounce or close-time timer. Text composition remains owned by the native input control. Closing, navigating, and restarting do not discard a persisted draft.

The command returns only `{subject_id,stored,dirty,revision}` after the input and its small acknowledgment commit in SQLite. It emits no dashboard state event and starts no synchronization. Acknowledged edits are durable; an abrupt failure before acknowledgment can still lose that unacknowledged edit. Escape does not cancel requests already sent to the worker. Replaying the same local request ID returns its prior acknowledgment without overwriting a newer draft.

Unsaved input is stored under `material_editor_<subject_id>` in the current mode's database. It never becomes an accepted answer, a search synonym, or a submission operation. `details` exposes `editor_draft`, `editor_dirty`, and `editor_revision` separately from `material`; `material_draft_<subject_id>` retains its existing meaning of explicitly saved study material waiting to synchronize. A future editor draft may coexist with such pending material, while another Save remains blocked until the prior operation resolves.

`set_material` can include the exact raw `editor_draft` captured when Save was pressed. It inserts the material operation and clears the editor only if the current raw input still matches that expected value and normalizes to the submitted values. This happens in the same transaction. An older Save cannot erase newer typing, even a newly added comma or space. A failed Save keeps the draft. Callers that omit the expected raw input leave unsaved editor content alone.

`editor_discard` returns current saved/pending material in the subject detail response. Its optional `expected` raw input prevents an older Discard from deleting newer typing. It creates no submission and emits no dashboard refresh. Subject access checks cover reading, editing, and discarding; account and demo databases stay separate. Explicit data deletion removes these drafts and their recoverable SQLite pages along with the rest of that mode's personal data.

## Submission state machine

Pending → preflight GET → in-flight → confirmed.

Preflight conflicts preserve the result as conflicted. Permission failures are blocked; a newly supplied token allows a fresh permission check. A response lost after a send, malformed successful response, or restart with an in-flight row becomes uncertain. Uncertain writes never reenter the automatic send path. Remote changes become conflicts, not guessed acknowledgments. Explicit recovery archives the local operation and keeps remote progress.

The local operation ID is not sent as an assumed server idempotency mechanism. WaniKani remains authoritative for scheduling and unlocks; pending assignments cannot be reviewed again. Lesson completion uses assignment start, and review completion uses POST reviews. The returned review ID is not used as a persistence key because it may be zero.

After confirming writes, synchronization refreshes user, assignment, and summary resources so newly unlocked work becomes available immediately. Reset reconciliation atomically invalidates affected assignments and their cursors; partial collection downloads do not advance a cursor past unseen changes.

Collection pages commit in chunks of 128 resources, releasing the database lock and yielding between chunks so an answer can commit during a large import. Collection cursors still advance only after every page completes. A restart or interrupted page safely upserts its partial contents again. A reset conservatively invalidates unfinished graded work whose cached subject level is malformed or missing, preserving local answers and conflict records while accepting remote progress.

Offline media planning uses narrow catalogue projections and strict current access. Required active radical images rank first, followed by required images for due lessons/reviews and the next day, then pronunciation and future content. Existing equivalent images and cached fallback audio remain usable; equal-priority cached files win over new prefetch. Downloads obey both the per-file ceiling and available cache budget. Placement validates the download before evicting weaker files. Interrupted final files are reclaimed only when a complete plan identifies an exact generated filename in this cache directory. Incomplete or cancelled plans authorize no cleanup.

## Boundaries

Account and demo databases are separate. Credentials are validated against the bound account ID. HTTP authentication is restricted to api.wanikani.com/v2; redirects are disabled. Cached media is HTTPS from WaniKani/CloudFront and receives no token header. API text is rendered as plain text, never executable markup. Selection lookup is explicitly invoked and remains local.

The shell's lock and notification service supply desktop policy. Ambient layers have no input region. The gallery stops before the native idle deadline rather than replacing the screensaver or lock service.

Ambient catalogue work requires an eligible visible desktop/idle surface or a lease held by an opened Zen view. Zen releases its lease on close or destruction and works independently of automatic-display settings. Hidden surfaces and active study do not request the 60-subject ambient catalogue. The service coalesces visible invalidations for 25 ms, permits one request in flight, and refreshes at most through visible demand or the visible-only one-minute timer. Access changes immediately clear cached ambient content and invalidate older responses. Session-only events do not trigger notifications or ambient catalogue refreshes.
