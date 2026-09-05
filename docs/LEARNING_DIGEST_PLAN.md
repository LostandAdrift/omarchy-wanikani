# Cached learning digest for agents

**Implemented in the 0.2.7 source milestone; not installed.** `backend/wanikani/learning_digest.py`, Worker, Service and CLI implement the aggregate contract below. Source verification is recorded in VERIFICATION.md; the installed revision is tracked separately in OVERNIGHT_WORK.md. No timer or automation is part of the digest.

## Why this is worth building

The helper currently answers “What is due?” and “Is this client ready?” through `status` and `doctor`. Its aggregate level meter also explains the remaining requirement for the current level. The new cached report also answers “How much did I practise this week?” and distinguishes completed reviews, learned lessons, meaning listening and kana dictation over a local date window.

Native Activity already has those definitions and counts. Reuse its aggregation rather than invent a second learning report or ask an agent to read the private database. The existing `learning_insights` worker response is unsuitable for direct export: it includes subject difficulty cards, and its adapter also requests a full snapshot and the listening pool. An aggregate digest needs neither of those reads.

The useful workflow is an explicitly requested weekly recap or morning handoff: read cached learning totals, explain their timestamp and scope, then optionally invite the learner to open the existing Activity, Reviews or Listening view. This adds no reminder stream and no automatic study action.

## Preferred design: optional cached status section

Add optional `learning_digest` to the existing worker full snapshot, Service status projection and helper status projection. Compute both 7- and 30-day windows in one aggregate pass. Keep it entirely outside the compact session event, answer, draft, playback and rating response paths.

Refresh at existing startup, explicit full dashboard/snapshot and completed account-sync boundaries. Reusing a native Activity read to refresh this cache is a future option; it is not part of this implementation. Do not add background polling, refresh the account when status is read, or turn an unavailable digest into an automatic synchronization action.

The snapshot producer owns the cache. Service status and CLI status only serialize their last accepted value. The whole section is `null` before a successful calculation, after account/data-context invalidation, or when unsupported. Calculation failure must not hide the ordinary status result or replace unknown history with zero.

Keep account identity internal. Bind the cache to the exact account, demo flag, durable data epoch and worker generation; discard late results after any of those changes. The public `data_epoch` is the existing opaque local data epoch, never an account ID, username, path or token. A reset within a retained account database does not erase the learning that happened before it. Explicit data deletion or account-store replacement invalidates the old digest, even when the display name remains the same.

`generated_at` always describes the digest itself. The surrounding snapshot may be newer. Do not overwrite this timestamp when reserializing the same cached result. Local study after that timestamp is not included until a permitted refresh boundary; status must never describe the digest as current just because the shell answered successfully. A small in-memory dirty flag marks potentially newer local work without triggering recomputation on answer or rating paths. Successful history-changing replies carry an internal `learning_after_revision` bound read from the worker’s existing full-snapshot sequence after the durable result. A later accepted full snapshot can clear that bound only if it began after the mutation. Older concurrent snapshots, subscription-only access changes and out-of-order replies cannot erase that evidence. Worker/data-domain changes reset the bound; old-generation callbacks are ignored, and missing or invalid bounds retain the stale label conservatively. Midnight/timezone changes also make the old windows stale until recomputed.

## Lean data contract

Implemented backend shape for `status.learning_digest`, using the existing Activity metric names:

```text
{
  schema_version: 1,
  scope: "recorded_on_this_device",
  freshness: "cached",
  generated_at: ISO-8601 timestamp,
  data_epoch: opaque local epoch,
  demo: boolean,
  timezone: system IANA zone or "system-local",
  complete: boolean,
  stale: boolean | null,
  coverage: "retained_local_records",
  includes_retained_pre_reset_activity: true,
  windows: {
    "7": Window,
    "30": Window
  }
}

Window = {
  days: 7 | 30,
  start_day: "YYYY-MM-DD",
  end_day: "YYYY-MM-DD",
  subject_completions: { reviews: Count, lessons: Count, practice: Count },
  sessions_completed: { reviews: Count, lessons: Count, practice: Count },
  listening_ratings: { remembered: Count, again: Count, skipped: Count },
  listening_sessions_completed: Count,
  dictation_ratings: { matched: Count, again: Count, skipped: Count },
  dictation_sessions_completed: Count,
  typo_corrections: Count
}
```

Every `Count` is a nonnegative safe integer. `complete` means that the supported aggregate fields were calculated successfully from retained local records through `generated_at`; it is not a claim that this database contains all past learning or all WaniKani activity. A supported empty history produces known zeros with that coverage label. Unavailable or unsupported fields stay unknown rather than becoming zeros. If a future version adds a skill, old clients must not treat its absence as a measured zero.

The final local day includes only activity through `generated_at`, not a completed 24-hour day. The 7-day window is a subset of the 30-day window. Both use the same calculation instant and real local-midnight boundaries, including 23- and 25-hour DST days. Caller-supplied timezone, timestamps, account IDs, arbitrary ranges and SQL are outside the interface.

No daily grid, subject ID, glyph, reading, meaning, note, answer, difficulty card, operation ID, session ID, media URL or freeform account message enters this section. The optional epoch above identifies the local data generation only. Do not include a fluency score, streak, guessed retention estimate or aggregate account accuracy.

### What the counts mean

- Subject completions are acknowledged local cycles, not unique subjects, answer parts or confirmed remote submissions. A word reviewed twice contributes two cycles. Reviews, lessons and ungraded practice remain separate.
- Completed sessions are deliberately completed batches, including “finish this batch”. Paused or reset-interrupted batches are not completed sessions.
- Listening ratings are final surviving local self-assessments; dictation ratings concern matching the played recording. Later Undo removes the corresponding result from its original day and can remove a completed local batch. Skip is explicit and is not a correct answer. Neither skill changes WaniKani SRS.
- Typo corrections count local uses of “I made a typo”; they are not inferred typos or an account accuracy adjustment.
- Earlier acknowledged work retained across an account reset remains local activity. Deletion/replacement removes the underlying history. The aggregate cannot reconstruct another client's individual reviews.

Keep current account-cache information in its existing status sections: `learning_progress`, due counts and `last_sync`. Keep current operation state in `outbox_counts`, `pending` and `attention`. These are separate from the digest's dated local activity. In particular, `outbox_counts.confirmed` is a current retained count, not “confirmed this week”, and local completed review counts must never be narrated as server confirmations.

## CLI surface

The helper provides one convenience command:

```sh
python3 tools/wanikani.py report --days 7 --json
python3 tools/wanikani.py report --days 30 --json
```

It performs exactly the existing read-only `wanikani status` IPC call and projects the chosen cached window. Default to 7 days; accept only integer 7 or 30. Retain the current `wanikani-cli` envelope/version, redacted errors, response-size bound and subprocess timeout. Capabilities describe the effect as a cached read, without network access, UI opening or account refresh.

A successful projection includes the digest metadata and just the requested `window`. An unavailable section returns `available:false`, `reason:"unavailable"`, `digest:null`; it does not return zero counts. Malformed or incompatible aggregate data uses the existing invalid-response error. The helper ignores unknown keys through an explicit allowlist. It never falls back to raw worker messages, SQLite, keyring access or a full native Activity response.

In human-readable output, lead with “Recorded on this device · cached through …”. If stale is known, say so. An agent can use the current status sections separately for a study invitation, but an invitation does not start or complete study unless the user asks. No generated file or scheduled job is required.

An explicit existing `refresh` still synchronizes the account and may submit already completed pending work. It is not a harmless way to obtain a fresher report and must not become an automatic report fallback. A fresh local-only report command can be considered later if cached reporting proves insufficient.

## Cost observation and alternative

A single fixture-only observation of the existing count helpers took **4.066 ms**. The authored database contained 16,500 events: 15,000 old answer records, 1,200 recent subject completions, and 300 listening/dictation results; it also contained 240 completed graded/practice batches and 60 local audio batches. All four aggregation helpers ran for 30 local days under one Store lock, using 9 reads including the two small epoch metadata reads. The largest SQL result contained 90 aggregate rows. The read made zero SQLite changes. No subject bodies, difficulty calculations, full snapshot or listening-pool query was requested.

This was one warm authored-fixture observation, not a device-wide performance qualification or a worst-case bound. It supports the cached-status approach for the next bounded implementation. Derive the 7-day totals from the same 30-day daily aggregates; do not run a second history scan.

If representative long-history qualification later makes full refreshes visibly slow, retain the last valid aggregate and move its calculation off the foreground snapshot path. A fresh on-demand ticket/result IPC handshake could provide exact request-time reports, but would add expiry, polling, concurrency, shutdown and late-account-response states. That complexity is not justified by the observation above and is not the initial proposal. There should be no new synchronous wait inside the QML event loop in either design.

## Verification and ownership boundary

Implementation should share the existing activity aggregation helpers and time-window logic. It must not call the current `learning_insights` adapter just to discard its private cards afterward. A common aggregate projection can feed Native Activity and the digest while leaving Native Activity's richer, lazy rendering unchanged.

Required focused checks:

1. Digest counts equal the corresponding native Activity windows on authored fixtures, including repeated subject cycles, finish-this-batch, partial/reset sessions, corrections, listening/dictation Undo, future-dated events and local DST boundaries.
2. Unknown/unsupported sections remain unknown; legitimate empty local history produces zero. Validate date windows, integer bounds, both audio skill schemas and safe static scope values. Inject private extra fields at worker, Service and CLI boundaries and prove they never reach CLI output.
3. Account switching, same-name demo reset, deletion, worker restart and out-of-order full snapshots cannot resurrect another data generation's digest. Ordinary account reset keeps the documented retained activity. Stale cached windows retain their original timestamp.
4. Full refresh boundaries can update the digest; status/doctor/report, answer/draft/session-only replies, playback and ratings do not trigger history recomputation. Optional aggregation failure does not break ordinary status or claim zero learning. Test this through source-derived Service and Worker adapters.
5. The helper makes one bounded status call, handles older installed services, validates `--days`, and has no network, raw worker, UI, refresh, grading or recovery side effects. Mock all transport.
6. Use existing history indexes and projected aggregates; assert no answer/note bodies are returned and no SQLite writes occur. Broaden timing only if a visible regression or representative-history failure appears.

## Backend implementation boundary

```python
learning_digest.project(engine, *, timezone=None, now=None)
```

The project function reuses Activity's four aggregate helpers under one Store lock. It calculates the 30 local days once, then derives both windows. Runtime callers omit the two test seams and use the system clock/timezone. It does not call rich `insights.overview`, Engine snapshot/details, subject/difficulty projections, listening-pool eligibility or current outbox aggregation.

It validates the cached user envelope and exact account-ID type/value before reading history. Explicit demo mode requires its `demo` identity and either no stored account stamp or a matching `demo` stamp. Only a canonical UUID may be exported as `data_epoch`; arbitrary stored text is unavailable. An untrusted clock or known clock offset over five minutes also makes the digest unavailable. Missing/invalid account, epoch, clock or aggregate values raise `UserError` with code `learning_digest_unavailable` and static text. They do not become an empty successful report, and SQL/account exception details are not returned. A successful projection returns `complete:true` and `stale:false`; the transport owns subsequent cache freshness.

Focused fixture checks cover UTC/local midnight, both DST transitions, exact generated timestamps, native Activity count parity, real local listening/dictation Continue and Undo, partial/reset batches, account/data isolation, safe UUIDs, strict count bounds, private-field allowlists, existing history indexes, no SQLite writes and a real threaded account-change barrier. Root owns Worker/Service/CLI integration and installed verification; SRS Explorer qualification and the earlier release checkpoint remain separate.

The combined digest/Activity/dictation-insight run passed 53 tests. After the final stricter demo-stamp check, all 18 digest tests passed again. Source compilation and diff checks passed. These are authored backend fixtures; they establish no installed CLI, live-account, audio or native-rendering outcome.
