# Local kana dictation · implementation contract

Dictation is a separate native view reachable from Listen. Existing meaning recall stays **Listen 5** with its own saved session; **Type what you heard** starts or resumes an independent five-word dictation batch. Both reuse the one panel audio player. This feature is cached-audio only, has no microphone, transcription service, network AI, graded command, or additional reminder stream.

## Learner flow

1. Play the current opaque recording. Only the current attempt's `PlayingState` followed by `EndOfMedia` acknowledgment permits Check. A previously completed hearing stays valid for replays of that exact pinned clip; replay, interruption and decode failure never record a miss. Resuming a question remains silent.
2. Type romaji or kana. WanaKana performs composition-aware live conversion; terminal `n` is finalized only for Check. The UI rejects Check while the IME is composing. Every committed edit is durably saved with a UTF-16 cursor. An optional separate preedit snapshot preserves text intent, not native IME candidate state.
3. Check includes the final text. Empty or non-kana input stays retryable without revealing the answer. Valid kana creates durable feedback, showing **Your kana** and **Recorded kana**. Neither intervals nor completed-result counts change yet.
4. Continue atomically records **Matched the recording** or **To revisit** and advances. The successful interval ladder is 1, 3, 7, 14 and 30 days; To revisit is 10 minutes. Skip works before or after feedback, including an unavailable recording, and changes no interval. A possible different kana spelling can be skipped without a correctness result.
5. Undo restores only the immediately preceding committed result, its feedback, prior local interval and summary. It expires when a subsequent result or Skip is committed. There is no typo override in this edition. Close, navigation and restart preserve the question/draft/feedback.

Comparison uses the exact chosen clip's metadata pronunciation, normalized for Unicode compatibility and hiragana/katakana. Small kana, doubled consonants and long-vowel spelling remain significant. No general `おう/おお`, `えい/ええ`, particle-spelling or homophone-meaning equivalence is inferred. Feedback describes matching a recording's kana label, not overall listening accuracy or uniqueness of a Japanese word. Alternate subject readings are not accepted unless they are the selected clip's pronunciation.

## State and selection

New `dictation_*` meta keys store the active pointer, bounded sessions, per-word intervals and per-day introductions. Context contains account identity, data epoch, reset generation and demo/account mode. Existing `listening_*` state is never migrated or replaced. Each skill has its own explicitly labeled allowance of **five newly introduced words per local day**; this is not a combined five-word allowance. First media delivery consumes a dictation introduction once, before playback; a device failure can conservatively consume that exposure slot but cannot count as a wrong answer. Undo does not refund a word that was already heard.

Only learned, accessible vocabulary/kana vocabulary with owned cached audio is eligible. Reuse the listening schedule/access/graded-protection policy and bounded pool, with an explicit internal card-key provider so dictation reads its own intervals. All unfinished graded sessions' IDs, written aliases, accepted readings and recording sounds remain protected. Pending/uncertain graded work remains excluded. Other ungraded practice sessions are preserved independently; they are not converted into graded protection locks or modified by dictation. Switching activities is deliberate.

A queue freezes at most five subject IDs, exact URLs, canonical clip pronunciations and opaque handles. Voice changes cannot switch an in-progress recording. Revalidate context, eligibility and the exact clip before play, hearing acknowledgment, Check, Continue, Undo and answer projection. Missing/restricted/protected content yields an unavailable front without answer data; Skip or an explicit replacement session remains possible. Reset/account changes preserve the old local record but cannot expose or resume it as current work.

The media planner retains both bounded audio-practice queues and their immediately undoable recordings, without raising the cache ceiling or outranking required study images.

## Exported backend interface

```python
status(engine) -> dict
view(engine) -> dict | None
command(engine, operation_id: str, action: str, args: dict | None = None) -> dict
media(engine, handle: str) -> dict
draft(engine, session_id: str, handle: str, text: str, cursor: int,
      preedit: str = "") -> dict
```

`command` receives action-specific arguments **without an `action` key**. Unknown keys, invalid types (including booleans as integers), oversized text, mismatched session/revision and malformed handles are rejected. Worker adapters strip/validate the public action field before calling the module. All mutations use existing Store transactions and local metadata-only command journal entries, never `Engine.command`, `Engine.advance`, `sessions`, `resources` or `outbox` writes.

Native worker methods:

| Method | Exact request |
| --- | --- |
| `dictation_state` | `{}` |
| `dictation` start | `{action:"start"}`; optional `replace:bool` explicitly replaces only dictation |
| `dictation` heard | `{action:"heard", session_id, revision, handle, playback_token}` |
| `dictation` check | `{action:"check", session_id, revision, text}` |
| `dictation` continue/skip/undo | `{action, session_id, revision}` |
| `dictation_media` | `{handle}` |
| `dictation_draft` | `{session_id, handle, text, cursor}`; optional `preedit:string` |

`dictation_state` atomically projects `{status,session}` under the Store lock. `command` returns `{duplicate,session}`; duplicate operation IDs project the current safe state without reexecuting or replaying saved answer bodies. `media` returns `{handle,uri,voice,playback_token,session_id,revision}`; the worker adds `session:view(engine)` in the same lock. URI and pronunciation selection are backend-owned; callers cannot provide a URL or expected answer.

An active session view contains `{id,revision,phase,index,total,started_at,prompt,media_handle,heard,draft,draft_cursor,preedit,draft_revision,input_error,feedback,subject,summary,undo_available,local_only,intervals}`. `phase` is `question`, `feedback` or `complete`. Before feedback, `subject` and `feedback` are null, and no subject ID, word, expected kana or revealing accessible label is returned. Unavailability clears answer, draft and media projections while retaining the private durable record. Summary keys are `matched`, `again` and `skipped`.

Feedback is `{matched,submitted,recorded,message}` with the actual pinned canonical pronunciation. The revealed subject includes bounded word, meanings, pronunciation and voice labels plus safe personal material. Intervals are `{matched_days,again_minutes}`. Status contains count-only eligibility, availability, new remaining allowance, saved-session summary, settings, completeness and a static explanation; local dictation history is not account-wide WaniKani history.

Draft writes do not increment the structural session revision, issue commands-table rows, emit full-state events or replace current UI input from an acknowledgment. They increment a separate `draft_revision` and return `{saved,session_id,handle,draft_revision}`. The current opaque handle and question phase reject delayed writes for a previous card. Check atomically saves its final text and feedback, so checking need not wait for each earlier edit acknowledgment. Worker input order preserves rapid successive edits. UTF-16 cursor boundaries may not split a surrogate pair.

## Native lifecycle contract

Panel owns separate dictation state/request generation and `audioContext:"dictation"`. Every callback compares navigation, data/access context, current card and request generations before changing UI or playing sound. A current player `EndOfMedia` sends the opaque token once; stale ends from replaced/closed/stopped audio cannot mark another question heard. Apply the returned durable session revision before enabling Check. End-of-media confirms player completion, not human hearing or output-device audibility.

Stop on close, locking, mode or subject change, new graded protection and access invalidation. Sync start/end and terminal status changes revalidate the view even when a partial sync fails without advancing last_sync; unrelated snapshot sequence changes do not interrupt a clip. Loading/cancelled media replies may already have recorded exposure, so reload the safe authoritative local view before another action. Returning, unlocking, reconnecting or loading state never autoplays. First-edition playback remains explicit.

## Verification boundary and ownership

Backend scope: new dictation module/tests, minimal shared listening pool hook, bounded media pinning. Worker/Panel/QML integration is separate. Required authored tests cover no graded writes, exact clip/alternate reading, long vowels/small kana, per-skill budget, current completion acknowledgment, draft/check/commit/undo crash boundaries, operation replay, account/reset/grant/protected aliases, missing media, both saved skill sessions and cache priority. Native tests use the real input/player adapters with inert media or authored local clips; they must not claim physical IME restoration or live-account/audio qualification.

## Local activity and decoder qualification

Activity shows separate dictation matched/to-revisit/skipped counts and completed batches for the last 7 or 30 local days. Check alone is not activity; Continue is the durable result boundary. Immediate Undo excludes the original result and completed-batch count until Continue commits again. Retained work before resets remains local activity, while account/data-epoch boundaries stay separate. Counts never export drafts, expected kana, media handles or account-wide accuracy.

The default automated suite uses inert player signals. The additional fixture-only real Qt MP3 check requires accessible desktop audio IPC and opt-in:

```sh
WANIKANI_DECODER_QA=1 python3 -m unittest discover -s tests -p test_dictation_decoder.py -v
```

It generates a short tone and uses AudioOutput at volume zero. This establishes the observed player signal path, not audible Japanese, physical IME input or whether a person heard a recording. In a restricted sandbox the audio IPC can block, so this check is explicitly skipped unless enabled; never treat that skip as successful decoder qualification.
