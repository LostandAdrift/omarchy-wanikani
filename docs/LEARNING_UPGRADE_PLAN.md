# A complete daily learning client

Proposal, September 5, 2026. This is a plan; it does not change the installed application or account settings.

Keep “five reviews, then back to work” as the quick action within a complete learning client. The home screen should answer three questions immediately: **What can I review? What can I learn? How is my level progressing?** Pronunciation should be part of studying, with a visible control and understandable status.

## What the current experience gets wrong

| Area | Confirmed finding | Consequence |
|---|---|---|
| Starting study | `Engine.start` restores any unfinished graded session before considering the requested mode. | Selecting lessons can resume reviews, or the reverse. Renaming buttons alone will not fix this. |
| Navigation | Reviews and lessons have passive count cards, one generic Study tab, and the lesson action says “Learn something new.” | The distinction is easy to miss before and during study. |
| Pronunciation | Playback exists for cached clips. Autoplay is off in the inspected local settings. Correct review feedback has no manual replay button, lessons have no autoplay, and playback errors have no useful display. | Existing audio support often feels absent. This inspection does not establish a broken system audio device. |
| Progress | The large Level card contains only a number. A five-pixel bar below the forecast counts kanji currently at Guru or above against all kanji. | It is visually buried and measures current retention, rather than the actual level-up requirement. |
| Personal subject information | Assignments, review statistics, level progressions, and SRS systems are cached, but much of that data is unused in the UI. | Learners cannot readily see the next review, exact stage, progress history, or remaining prerequisites. |

Source entry points: [study dispatch](../backend/wanikani/engine.py), [dashboard](../qml/Dashboard.qml), [study presentation](../qml/Study.qml), [subject details](../qml/SubjectDetails.qml), [voice choices](../qml/VoiceChoices.qml), and [audio player](../Panel.qml).

Tsurukame is the comparison client pending confirmation of the iPad app's name. Its published feature set includes offline study, upcoming reviews, and current-level radical/kanji/vocabulary progress. The useful target is that learning clarity within Omarchy's native shell. [Developer's App Store listing](https://apps.apple.com/us/app/tsurukame-for-wanikani/id1367114761)

“Voice” is provisionally interpreted as pronunciation playback. If it also means speaking answers, add a separate speech-input design after confirming that preference; the current plan does not introduce a microphone or speech-recognition service.

## 1. Make reviews and lessons unmistakable

Use primary navigation **Today · Reviews · Lessons · Progress**. Keep Lookup, Practice, Zen, Settings, and Help accessible as secondary destinations without squeezing the study controls. Compact panels may wrap or use a labeled More menu; reviews, lessons, and progress stay directly visible.

On Today, place two large actionable cards together:

- **Reviews — recall what you've learned.** Due count, explicit **Review 5** action, and an **Open reviews** destination for a larger session. Offer batches of 5, 10, or 20, plus an option to work through currently due items in successive resumable batches; finish-this-batch always remains available. Keep each durable batch bounded.
- **Lessons — learn new subjects.** Available count and **Choose lessons**. Show the proposed batch before learning: radicals, kanji, and vocabulary, with their levels. **Learn these 5** begins discovery; **Start lesson quiz** is a separate explicit transition.

The study header always names the activity and phase: **Reviews · Reading · 2/5 subjects**, **Lessons · Learn · 2/5**, or **Lessons · Quiz · 2/5**. Subject colors identify radical/kanji/vocabulary; they must not be the only way to identify reviews versus lessons.

Keep distinct saved lesson and review sessions. Starting or resuming one kind must never silently select the other. Show a contextual **Resume reviews** or **Resume lessons** banner with the saved position. Switching preserves both drafts and error counts; practice remains independent. The shortcut can resume the most recently used graded session, with its mode immediately visible, and defaults to five reviews when there is nothing to resume.

This requires an explicit backend session-selection change, including a safe migration of the existing saved-session reference. Maintain current assignment-cycle exclusion and submission safeguards across every saved session.

## 2. Make pronunciation dependable and obvious

Use WaniKani's original recordings as the default source. Its recordings are for vocabulary; standalone radicals and kanji do not have equivalent supplied audio. For a kanji, offer **Hear this reading in vocabulary** through a suitable accessible word. Do not silently substitute synthesized speech or imply a radical has a Japanese pronunciation. [WaniKani audio guide](https://knowledge.wanikani.com/wanikani/audio/)

Put a labeled speaker/replay control next to the reading in lesson discovery and revealed review feedback, including correct feedback. Offer separate **Autoplay in lessons** and **Autoplay after review readings** preferences, a named voice selector, **Test voice**, and a discoverable replay shortcut checked against the existing desktop/IME bindings. Preserve an explicitly chosen off preference; make the choice clear on first use.

Audio states must distinguish **Ready**, **Downloading**, **Unavailable offline**, **No recording**, and **Playback failed · Retry**. A click while online should fetch the current permitted clip immediately and cache it, instead of requiring the learner to wait for a whole-account refresh. Prefetch the active batch with the existing media budget and access rules; retain cached alternatives when a preferred voice cannot play.

Playback must never reveal an unanswered reading early in reviews or lesson quizzes. Enable it when that answer is already revealed; lesson discovery can play immediately. “Autoplay in lessons” applies to discovery, not to an unanswered quiz prompt. Stop on close, lock, activity switch, or subject change. A late download must not play over the next question. Validate audible output on the actual machine using a deliberately chosen cached vocabulary clip, including replay and output-device changes; placeholder media tests cannot establish playback.

## 3. Put meaningful progress on the home screen

Move a substantial **Current level** card above the forecast. Example data: **Level 12 · 24 of 27 required kanji passed · 3 more to advance**. Include elapsed calendar time on the level and **Explore this level**. Keep pending completions visually separate from confirmed passing.

The actual level-up threshold is 90% of the level's kanji, rounded up to a whole subject. Count confirmed passing timestamps, not just current SRS stage; a later demotion must not erase recorded first passing. Use the complete eligible catalogue for the denominator and server-confirmed level progressions as the authority. An incomplete sync should say the level is still loading, rather than manufacture a confident percentage. [Level-up guide](https://knowledge.wanikani.com/wanikani/getting-started/level-up/), [API level progressions](https://docs.api.wanikani.com/20170710/#level-progressions)

The Progress view should contain:

- A **level board** with separate radicals, kanji, and vocabulary sections. Tiles show characters and states such as Locked, Lesson ready, Apprentice 1–4, Passed, or Waiting to sync. Selecting a tile reveals its detail with spoiler protection for every unfinished saved lesson/review session, including paused subjects and matching glyph aliases. These automatic progress links do not redefine the existing deliberate manual catalogue lookup policy.
- **What unlocks next**, showing the actual missing radical or kanji prerequisites and their known next review times. Explain vocabulary's role in learning readings in context; do not imply it is unimportant because it does not directly trigger level-up.
- A familiar **Apprentice / Guru / Master / Enlightened / Burned** distribution, with clickable subject lists. Keep current retention separate from level passing. [SRS guide](https://knowledge.wanikani.com/wanikani/srs-stages/)
- **Your history**, showing account-level durations from `level_progressions`, with reset attempts distinct, plus separately labeled activity recorded by this plugin. Keep lessons, reviews, and ungraded practice separate. Individual review history from another client cannot be reconstructed from the API.

Subject details should name the SRS stage, next scheduled review, lesson date, first passing date, and meaning/reading accuracy with answer counts. Derive aggregate accuracy from those counts, not an average of per-subject percentages. Account-wide review statistics and plugin-local history must retain their different scopes. [API review statistics](https://docs.api.wanikani.com/20170710/#review-statistics)

Do not promise a level-up date in the first release. A later **earliest possible** estimate requires the actual prerequisite graph and SRS intervals, with clear assumptions about correct and on-time answers. Handle level 60, vacation, resets, subscription restrictions, and partial sync explicitly.

## 4. Make lessons feel like learning

Give lesson discovery a consistent sequence: **Meaning → Reading and audio → Examples and relationships → Quiz**. For each step, show the current subject, position, and a short indication of what comes next. Skip inapplicable steps for radicals and kana vocabulary.

Keep personal notes, mnemonics, examples, and related subjects accessible without an endless undifferentiated page. Offer a lesson batch preview and WaniKani-style progression order by default. Show the selected content before committing to a quiz. Completion names what happened: **5 lessons learned; waiting to sync** versus **5 reviews completed**.

After these foundations, add two optional practice tools: **Listen and recognize** using cached recordings, and **Compare confusing kanji** after answering. Both stay ungraded and preserve paused lessons/reviews. Existing ambient and companion features remain available; further ornamentation can wait until this daily workflow is qualified.

## Implementation order and acceptance

| Pass | Deliverable | Acceptance gate |
|---|---|---|
| A — Study clarity and working audio | Explicit review/lesson routes and headers, safe saved-session selection, visible replay, voice test, current-clip download and error states | Lesson actions never return reviews or vice versa. Switching both ways and restarting preserve exact drafts/errors. Real cached vocabulary is audible after safe feedback and never leaks an unanswered reading. |
| B — Learning dashboard and progress | Actionable Today cards, proper level-up meter, level board, SRS names, personal subject status | Learner sees due work, new lessons, and remaining level requirements without scrolling. Passing counts match confirmed assignments; reset, partial sync, and pending work stay honest. |
| C — Complete lesson experience | Batch preview, structured discovery, explicit quiz transition, clear summaries | A five-subject lesson batch is comprehensible by keyboard alone and returns to its exact place after closing. Reviews and lessons stay visually distinct on narrow and expanded surfaces. |
| D — Deeper practice | Listening practice, contrast practice, progression history polish | Practice changes no WaniKani schedule; the learner can return to paused graded work exactly. |

Reuse the current worker, native components, account cache, and outbox. Keep summary queries cheap and load level/subject details on demand. Retain the existing warm-open and answer-latency targets, but only profile new visible delays; the main work is learning UI and correctness.

Verification should combine documented API-shape fixtures, session migration/restart cases, real-component interaction tests, and short deliberate checks on the connected account. Native visual QA covers compact/expanded panels, keyboard focus, both themes, and existing monitor scales. Live verification only submits study that the user deliberately completes. Finish with the existing [fourteen-day daily-use log](DAILY_USE.md).

The next implementation milestone should be **passes A and B**. They directly address the reported experience and establish the structure for improved lessons and practice.
