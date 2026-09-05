# Guided lesson discovery

Lesson discovery uses a short path through each subject: **Meaning → Reading or Sound → Context**. The native quiz is a separate, explicit action after the last applicable step of the batch. This feature deepens the existing lesson chooser; it does not change WaniKani grading or submission rules.

## Learner flow

- Meaning includes the meaning mnemonic, hints and personal meaning note.
- Kanji and vocabulary have a Reading step. Vocabulary includes its original recording when available. Kana vocabulary with supplied audio has a Sound step; it does not acquire an invented reading quiz. Radicals have no reading step.
- Context appears only when the currently accessible projection contains usable examples, components, related subjects or comparisons. Empty and protected relationships do not manufacture an empty step.
- Previous returns through the steps and then to the previous subject. Next moves through applicable steps and then to the next subject. The final button is **Start lesson quiz**.
- Closing or switching study modes keeps the subject and step. Reopening stays silent. With lesson autoplay enabled, deliberate navigation into the same subject's Reading/Sound step can play its recording; the playback intent is tied to that session, subject, revision and account context.
- The path has a readable text alternative and theme-aware current-step indication. Keyboard focus reaches the explicit quiz action. There is no countdown or mandatory time on a page.

The subject's visible glyph remains central throughout discovery. Section filtering is presentation organization, not a replacement for backend content and spoiler authorization. Lookup and feedback retain their existing full or answer-part views.

## Durable state and protocol

The existing lesson session gains an optional `lesson_step` string. There is no database schema migration. Legacy sessions without it start at Meaning; merely projecting the view does not rewrite stored work. The existing `mode: lessons` and `phase: lesson` remain unchanged until quiz entry.

`lesson_navigate` accepts exactly:

```json
{"action":"next","session_id":"CURRENT_LOCAL_SESSION","revision":7}
```

Supported actions are `next`, `back` and `quiz`. A mismatched session/revision, extra arguments or an unavailable transition fails before changing state. The ordinary command journal commits the transition and reply together; replaying a local request does not repeat the move. This is local navigation, not an account write or a server idempotency promise.

During discovery, `session.lesson_flow` contains bounded navigation metadata: `step`, ordered `steps` with `id`/`label`, one-based `position`, step `total`, `can_back`, `can_next`, `can_quiz`, `next_label` and `adjusted`. It is null outside discovery. The worker emits the compact session update and a coarse study-activity observation; it performs no catalogue scan or account refresh for navigation.

The backend derives applicable sections from current authorized subject details. If an optional section disappears, the visible path falls back to the nearest preceding step with an explanation. Forward movement and quiz entry require usable current study content. Back may leave a subject whose required image or access was lost, while still validating the destination. The final quiz action validates its first prompt and does not start an assignment or enqueue a completion.

The existing `lesson_next` interface remains available for compatibility. Native guided controls use the stricter new interface. Lessons are submitted only after the existing quiz has completed all required answer parts and the final feedback is acknowledged.

## Verification scope

Authored backend fixtures cover every subject type, legacy state, exact restart/mode-switch restoration, optional content changing, access/image loss, stale commands, duplicate replies, and real process exits before and after a committed transition. The actual QML wrapper covers focused sections, comparison visibility, keyboard flow, explicit quiz entry, autoplay intent and narrow light/dark layouts with inert account/audio adapters.

The hosted QA scenario also includes focused Meaning, Reading and Context captures, silent close/resume and the explicit quiz action. It may run only when the desktop is unlocked. Check [verification](VERIFICATION.md) and [overnight tracking](OVERNIGHT_WORK.md) for which source and installed checkpoints actually passed; a prepared scenario is not a completed native test.
