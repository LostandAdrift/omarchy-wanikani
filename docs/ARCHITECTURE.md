# Architecture

The Omarchy manifest declares a service, bar widget, and one persistent panel. The shell owns the QML objects. The service owns one Python worker through private stdin/stdout pipes. Panel views share that worker and account state across monitors. No extra Quickshell process or daemon is installed.

## Protocol

Request: `{"v":1,"id":"unique-request-id","method":"answer","args":{"text":"mountain"}}`.

Response: `{"v":1,"id":"unique-request-id","ok":true,"data":{...}}`; errors use `ok:false,error:{code,message}`. Events are `ready` and `state`. Secrets are accepted only by `authenticate` and never echoed. Background synchronization has its own thread; local commands are serviced while HTTP is in progress.

Study mutation methods are `start`, `draft`, `answer`, `correct`, `advance`, `lesson_next`, `finish`; note edits use `set_material`. Read methods include `snapshot`, `session`, `search`, `details`, and `ambient`. Account methods include `authenticate`, `disconnect`, `use_demo`, `sync`, `clear_cache`, `delete_data`, `resolve`, and `diagnostics`.

SQLite stores API resource snapshots, sessions, local events, command replies, synchronization cursors, and the submission queue. A reentrant lock serializes short transactions across the command and network threads. WAL and FULL synchronous mode protect the local acknowledgment boundary. The command effect and reply commit together so the same local request ID cannot increment errors or advance twice.

## Study state machine

Lessons: presentation → quiz question → feedback → next question / completed subject.
Reviews and practice: question → feedback → next question / completed subject.

Each subject stores required parts, completed parts, and error counts independently. An incorrect answer increments the relevant count. A typo correction can decrement that one current error and marks feedback corrected. `advance` applies accepted feedback and creates the outbox item only after every required part is complete. `draft` is persisted during input. Hiding a panel does not finish a session.

## Submission state machine

Pending → preflight GET → in-flight → confirmed.

Preflight conflicts preserve the result as conflicted. Permission failures are blocked; a newly supplied token allows a fresh permission check. A response lost after a send, malformed successful response, or restart with an in-flight row becomes uncertain. Uncertain writes never reenter the automatic send path. Remote changes become conflicts, not guessed acknowledgments. Explicit recovery archives the local operation and keeps remote progress.

The local operation ID is not sent as an assumed server idempotency mechanism. WaniKani remains authoritative for scheduling and unlocks; pending assignments cannot be reviewed again. Lesson completion uses assignment start, and review completion uses POST reviews. The returned review ID is not used as a persistence key because it may be zero.

## Boundaries

Account and demo databases are separate. Credentials are validated against the bound account ID. HTTP authentication is restricted to api.wanikani.com/v2; redirects are disabled. Cached media is HTTPS from WaniKani/CloudFront and receives no token header. API text is rendered as plain text, never executable markup. Selection lookup is explicitly invoked and remains local.

The shell's lock and notification service supply desktop policy. Ambient layers have no input region. The gallery stops before the native idle deadline rather than replacing the screensaver or lock service.
