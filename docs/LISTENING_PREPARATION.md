# Prepare five recordings

Implemented source contract for the bounded recording-preparation feature after the 0.2.0 checkpoint. The existing listening session, pronunciation player and media cache remain the foundation. Source and installed verification are recorded separately in [the overnight log](OVERNIGHT_WORK.md).

## Learner experience

The Listen preflight offers **Prepare five recordings** when familiar words are eligible but their recordings are missing. Preparation fills a batch of up to five distinct eligible words, counting usable cached recordings toward that target. For example: **2 ready · 3 recordings can be downloaded**. It does not download five additional words when a usable batch already exists.

Show count-only progress, a Cancel action and a short result. After preparation, refresh the preflight and offer **Listen to five** (or the smaller available number). This second explicit action starts practice. Preparation never plays audio, reveals the selected words, creates or replaces a listening session, introduces a word into the daily allowance, records exposure, rates recall or submits WaniKani work.

An unfinished listening session keeps its existing Resume action. Do not prepare a replacement batch while it is unfinished. Repairing a particular saved session's missing recordings is separate scope; the existing unavailable-card/Skip behavior remains available.

Explain the actual limiting condition: offline, cache budget, no eligible familiar words, today's new-word allowance used, or an incomplete catalogue check. An incomplete check reports only the candidates found; it must not claim that no eligible words exist. A failed or cancelled attempt requires another deliberate action. Opening Listen, receiving a reminder, reopening the panel or reconnecting does not start a download or playback.

## Selection and authorization

Reuse the listening selector rather than introducing a second learning policy. The only difference is that preparation may select a known recording whose file is not cached yet. Existing session creation must continue to require usable cached audio.

- Vocabulary and kana vocabulary must be learned, visible, valid and within the current account grant. Require one valid current assignment, valid answer resources and a supported recording with valid pronunciation metadata.
- Apply the existing default exclusion for reviews due now or within 24 hours; honor the explicit include-due-soon preference. Burned words remain eligible under the existing scheduling rules.
- Exclude unresolved lesson/review work and every unfinished graded session's subject IDs, exact glyph aliases and protected sounds. Validate every reading which a later reveal could expose, not only the selected clip. Malformed protection data fails closed.
- Preserve existing local scheduling, due-first ordering, pinned/recent preferences and the daily introduction allowance. Do not offer preparation as an implicit extra-practice override. Deduplicate both subject IDs and normalized sounds.
- Prefer an already usable cached recording, including another recorded voice, over downloading an uncached preferred voice. Voice preference selects among otherwise eligible recordings; it cannot override protection or access.
- Select media URLs only from that user's cached subject resources. Validate the media host, format and metadata. IPC accepts no caller-supplied subjects, URLs, filesystem paths or authorization headers.

Use the current bounded listening scan: at most 12,000 metadata candidates and 256 hydrated eligible candidates, with cheap schedule exclusions applied before consuming the hydration budget. Stop after enough authorized distinct candidates are selected. Carry the existing honest `complete` result through the preflight. No scan is added to answer/advance processing or periodic full snapshots; preparation availability belongs to the visible Listen preflight.

Capture account identity, durable session epoch, reset generation and current subscription/grant context, voice selection and cache limit. The existing listening `_context()` covers identity, epoch and reset; preparation must additionally compare the grant/type/expiry and effective access. Recheck current eligibility under the store lock before every clip and after each network read. Graded sessions, assignments, outbox and the clock may change while the network runs even when account switches are gated. Stop on an invalidated context; a stale result never supplies subject content or playable media to the UI.

## Interfaces

Private candidate descriptors stay inside the backend. These helpers are implemented in the listening and listening-preparation modules.

```python
# listening.py: shared, read-only authorization and local scheduling boundary.
def preparation_candidates(engine, limit=5):
    # Return internal context, selected descriptors and a neutral summary.
    # Descriptors include subject_id and selected clip URL only for backend use.
    # Do not weaken the cached-file requirement of existing _eligible callers.
    ...

# listening_preparation.py: visible-preflight information; no writes/network.
def availability(engine):
    # Return ready, needs_download, complete, reason, message; all counts <= 5.
    ...

# listening_preparation.py: one explicitly requested, bounded cache operation.
def prepare(sync, *, cancelled=lambda: False, progress=lambda value: None):
    # Select again authoritatively; never trust an earlier preflight response.
    # Return a neutral summary, never descriptors, subject text or media URIs.
    ...
```

Extend the existing `listen_state.status` with `preparation: {ready, needs_download, complete, reason, message}` while preserving current fields. This object distinguishes preparation coverage from the existing cached-pool `complete` field. `reason` is an explicit state such as `ready`, `needs_download`, `saved_session`, `offline`, `no_candidates`, `daily_limit` or `incomplete`; numbers alone cannot describe the empty state.

Add worker `listen_prepare` with an empty arguments object. Its ordinary request ID receives the final response; the same opaque request ID identifies count-only progress and cancellation as `job_id`. A matching `listen_prepare_cancel({job_id})` stops this preparation only. Reject unknown arguments rather than silently allowing future arbitrary media selection. Example final response:

```json
{
  "status": "partial",
  "downloaded": 2,
  "already_cached": 1,
  "failed": 0,
  "skipped_budget": 2,
  "cancelled": false,
  "complete": true,
  "reason": "budget"
}
```

Here `complete` means the selected bounded preparation pass finished without cancellation, expiry or an incomplete plan; it does not mean all five recordings are ready. `status` is `ready`, `partial`, `cancelled` or `unavailable`. Count each selected word once; no failure count is inferred for unattempted words. Before reporting `ready`, the backend rechecks that selected authorized recordings still exist. Download counts remain historical operation counts if another cache owner trimmed files after placement. The UI obtains fresh readiness after completion instead of treating `downloaded` as current study permission.

## Existing helpers and ownership

| Existing source and signature | Reuse and limit |
| --- | --- |
| `listening.status(engine)` / `listening.view(engine)` | Keep existing cached readiness and saved-session projection. Preparation readiness is added only by the visible `listen_state` adapter. |
| `listening._pool(engine, context, settings, subject_ids=None)` / `_eligible(engine, subject_id, protection, settings, clip_url=None, pronunciation=None)` | Shared private policy. Existing callers require a usable cached file; only preparation opts into the explicit `require_cached=False` path. Do not duplicate its assignment, sound protection and outbox checks in the new module. |
| `listening.media(engine, handle)` | **Do not call.** It durably records exposure before returning a playable URI; cache preparation is not hearing a word. |
| `pronunciation.status(engine, subject_id, context="details", session_id=None, revision=None, voice_actor_id=None)` | Existing explicit lookup/study status only. Details authorization deliberately permits more than automatic listening. It is not the preparation eligibility gate. |
| `pronunciation.sample(engine, voice_actor_id=None)` | Learned/unprotected voice test selection, but not the full listening schedule/outbox policy. It is not the preparation selector. |
| `pronunciation.prepare(sync, subject_id, context="details", session_id=None, revision=None, voice_actor_id=None)` | Reuse its focused-cache transaction pattern. Do not call it five times: that rebuilds five plans, uses the wrong selection boundary and returns playable subject-specific data. |
| `media_plan.build(engine, media_dir, deadline=None, cancelled=lambda: False, clock=time.monotonic)` | Build once, after acquiring media ownership. It validates cache inventory, entitlement, priorities and the strict user budget. Incomplete plans authorize no destructive cleanup or downloads. |
| `media_plan.valid_url(value)` / `media_files.available_file(directory, value)` | Public URL allowlist and owned, nonempty, regular non-symlink file checks. `media_plan.assets(value)` alone does not validate pronunciation eligibility or MIME. |
| `MediaPlan.admission(url, content_length=None)` / `placement(url, actual_size)` | Public non-mutating admission and weaker-file eviction decisions. Actual bytes enforce the budget and 8 MiB file cap; Content-Length is only an untrusted hint. |
| `Synchronizer.download_media(url)` | Serialized, validated transport and atomic file/metadata placement. It requires an attached complete `_media_plan`; it is not a standalone arbitrary-URL downloader. |
| `Synchronizer.cache_media()` / `trim_media()` / `clear_media()` | Already share the per-Store reentrant media lock. Leave automatic prefetch and its failure backoff separate from this explicit operation. |
| `Worker.prepare_pronunciation(request_id, args)` | Existing asynchronous audio-job lifecycle: one recording job, responsive answers, redacted errors and readiness refresh. Reuse this ownership pattern; do not use the general account-sync `job()` wrapper. |

The focused batch executor keeps cache transaction ownership inside the synchronizer. Existing pronunciation preparation retains its established behavior; the new listening caller does not manipulate private plan fields or cleanup helpers:

```python
# sync.py: focused executor, internal callers only.
def prepare_recordings(self, candidates, *, permitted,
                       cancelled=lambda: False, progress=lambda value: None):
    # candidates is bounded to five backend-created descriptors.
    # permitted(candidate) rechecks the caller's own current authorization.
    # Build one plan, focus selected audio, download once per missing clip.
    ...
```

This helper must not invent authorization. Listening provides its strict `permitted` check; existing pronunciation retains its own explicit context checks if migrated onto the helper. The `MediaPlan.focus_audio(url, subject_id, now)` method wraps the existing private priority update and rejects incomplete plans and invalid descriptors. Keep cleanup/temporary plan attachment inside the synchronizer and restore the previous plan in `finally`.

## Media, cancellation and lifecycle

The worker owns one asynchronous preparation thread under the existing `audio_job_lock`. Authentication, account/demo switches, disconnect, data deletion and cache clearing remain gated while it runs. Avoid the account API job lock: routine answers remain responsive and media retrieval does not refresh the account or flush the outbox. Do not put preparation into the durable study command journal or emit full snapshot events for each clip.

Set `sync.media_requested` while waiting for/holding the shared per-Store `media_lock` so automatic prefetch yields. Acquire the media lock before building the single plan. Do not hold the store lock during network IO. Use job-specific neutral progress rather than overwriting the account synchronization progress object.

Focus chosen audio at the existing deliberate-pronunciation priority `(1, 3, 0)`: below active/current required radical images and ahead of optional prefetch. Retain equal-priority valid files stably. Honor the configured byte limit even if it cannot hold five clips. Validate a new download before evicting weaker files; cancellation, invalid MIME, rejected URLs and failed downloads preserve existing recordings. Only owned cache files can be deleted. Interrupted complete files use the existing orphan cleanup; never delete arbitrary paths or another active job's temporary file.

Keep one eight-second soft preparation pass, including plan construction, with no more than five download attempts. Check the deadline and cancellation before each new clip. An already running read uses the existing bounded file size and ten-second socket timeout; the eight-second pass is not a promised hard end-to-end deadline. No automatic per-clip retries and no one-hour network-failure backoff for budget skips. Partial success remains useful on the next explicit attempt.

Closing, locking, changing view or explicitly cancelling sets a **per-job** cancellation event. Do not set `Synchronizer.cancelled` for a panel cancellation: that event can stop unrelated account synchronization. A running network read may finish; do not begin another. Validated retained files may remain cached, but cancellation never starts playback or commits listening state. Recheck authorization before placement where possible and after IO, and never publish a stale content-bearing result.

The QML adapter guards the job ID, navigation sequence, visible route, lock state, worker readiness and account/access context. Late progress or completion may release local busy state but cannot reopen a view, initiate another request, reveal words or play audio. A worker restart abandons the job; durable valid files remain, and a fresh preflight can discover them. Preparation is never automatically restarted.

## Minimal implementation and verification

1. Share listening eligibility/selection for cached and preparable recordings without changing existing cached-session semantics. Add `availability()` and focused fixtures first.
2. Extract the focused cache executor; preserve existing pronunciation behavior and tests. Add the new preparation module with a fixed batch bound and per-job cancellation.
3. Add the worker audio-job adapter and neutral progress/cancel messages. Keep account guards, lock cleanup on thread-start failure and minimal readiness refresh.
4. Add the visible preflight action, count-only progress and explicit post-download Listen action. Preparation must ignore the autoplay preference because it is not a practice action.

Use authored fixtures and a mock transport. Verify cached alternate voice fallback, more than 256 due-soon words preceding eligible future words, distinct sounds, daily allowance, unfinished review/lesson aliases, pending and uncertain graded work, malformed resources, grant expiry and changed assignments/protection during IO. Prove preparation leaves session rows, local introductions/ratings, study events and the outbox unchanged. Exercise strict budget/no-churn, rejected URL/MIME, oversized and interrupted responses, one plan per batch, cancellation before/after a read, lock/thread-start failures, late UI replies, restart and a responsive answer while a recording is fetching. No live account submissions, playback, token access or desktop notification is needed for these checks.
