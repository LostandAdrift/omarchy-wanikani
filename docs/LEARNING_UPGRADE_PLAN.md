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
| Reminders | The existing interval is a cooldown on due-count increases, not a recurring cadence. | An unchanged due pile receives no periodic invitation. |
| Theme contrast | Computed 76%-opacity foreground on stock base backgrounds falls below 4.5:1 in Rose Pine (3.81:1) and Catppuccin Latte (3.96:1); full foreground passes in both. | Following theme colors alone is insufficient when the plugin lowers text opacity. These are palette calculations, not native screenshot measurements. |

Source entry points: [study dispatch](../backend/wanikani/engine.py), [dashboard](../qml/Dashboard.qml), [study presentation](../qml/Study.qml), [subject details](../qml/SubjectDetails.qml), [voice choices](../qml/VoiceChoices.qml), and [audio player](../Panel.qml).

The user confirmed Tsurukame as their iPad client and the comparison benchmark. Its published feature set includes offline study, upcoming reviews, and current-level radical/kanji/vocabulary progress. The useful target is that learning clarity within Omarchy's native shell. [Developer's App Store listing](https://apps.apple.com/us/app/tsurukame-for-wanikani/id1367114761)

The follow-up makes **listening practice, periodic study reminders, and every-theme polish** core requirements. Audio means both pronunciation during ordinary study and learning to recognize words by ear. Anki is a useful interaction reference: audio can be the question, followed by answer reveal and a recall rating. Build that experience into this client; an Anki installation or deck synchronization is not required. [Anki media support](https://apps.ankiweb.net/), [Anki study controls](https://docs.ankiweb.net/studying.html)


## 1. Make reviews and lessons unmistakable

Use primary navigation **Today · Reviews · Lessons · Listen · Progress**. Keep Lookup, other Practice, Zen, Settings, and Help accessible as secondary destinations without squeezing the study controls. Compact panels may wrap or use a labeled More menu; reviews, lessons, listening, and progress stay directly visible. Keep the large review and lesson cards together, with a smaller **Listen 5** action beside the current-level summary so all three activities remain distinct.

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

Listening is now a core mode, detailed below. **Compare confusing kanji** remains a later practice extension. Existing ambient and companion features remain available; further ornamentation can wait until this daily workflow is qualified.

## 5. Train listening as a separate skill

**Listen 5** starts five distinct familiar vocabulary words. Show **Listening practice · Local progress** throughout, with the session position and a persistent replay control. This measures recognition by ear; it never completes a WaniKani lesson, changes an assignment's SRS stage, or clears its due-review count.

The first edition follows this sequence:

1. A neutral **What does this word mean?** prompt and a Play/Replay control. The written word, kana, meaning, related subjects, and revealing accessibility labels stay hidden. Starting a session may play the first clip when listening autoplay is enabled; opening a reminder or returning from suspend cannot start audio by itself.
2. The learner recalls the meaning mentally, replays freely, then selects **Reveal**. No countdown pressure and no recording are needed.
3. Reveal the word, kana, accepted meanings, the chosen voice, and relevant personal notes. **Got it** or **Again** records a local self-assessment; **Skip** changes no learning result. Show the proposed next listening interval before recording the choice. Rating and advancement are one durable transaction, and a current-rating undo is available before another answer is committed. Undo atomically restores the prior rating, interval, session position, reveal state, and any affected daily introduction budget; repeated rating/undo requests cannot apply twice.
4. A summary distinguishes words recalled, words to revisit, and skips. Offer another five or an immediate return to work. Closing or switching modes preserves the listening prompt/reveal state separately from saved lessons and reviews.

Japanese homophones make an isolated sound insufficient to identify one written word reliably. The MVP therefore uses self-assessed meaning recall, with known same-reading alternatives explained after reveal. It must never automatically mark a plausible homophone meaning wrong. A known ambiguity can be skipped without penalty; matching the cached catalogue does not prove uniqueness across Japanese. Avoid selecting identical-pronunciation cards together, and exclude known matching pronunciations of unfinished graded readings as well as their written aliases.

Start from learned, accessible vocabulary with usable audio. Select from saved listening words, eligible recent learning, and local listening mistakes. Default suggestions avoid WaniKani items due now or within 24 hours; an explicit include-due-soon preference can widen that pool. Always exclude every unfinished graded session's subjects and protected aliases from automatic practice, and recheck access/eligibility when starting or resuming. Empty and offline states explain which recordings or eligible subjects are missing. Never autoplay a locked, unauthorized, or newly excluded item.

Keep the active recording's pronunciation and answer metadata backend-only until reveal; the unrevealed view receives an opaque media handle and neutral controls. Recheck eligibility before every play, reveal, and rating, and after asynchronous media completion, including account resets and newly protected study items. Keep one player; stop playback on subject change, close, lock, mode switch, or output-device loss. Prefetch the next eligible clips, pin the active batch within the cache budget, and show a useful retry if a clip fails. Playback/replays alone never count as correct answers. Voice changes do not create duplicate learning items.

Listening progress is stored locally per account, subject, and practice skill. Use a small documented interval ladder for the first edition: successful recall schedules the next listening practice after 1, 3, 7, 14, then 30 days; **Again** resets to a short 10-minute retry. Keep the five-word batch bounded and do not force the learner to wait for a retry. **Skip**, playback failure, and replay do not change the interval. These are initial product defaults to tune through use, not a claim to implement Anki's FSRS or its retention estimates. Due listening words are prioritized inside the next chosen session; they never each generate a notification. Automatic batches introduce at most five previously unpracticed listening words per day by default, with deliberate extra practice available. Show local listening attempts and recall ratings separately from account-wide WaniKani accuracy.

Implementation must use an explicitly local practice modality or dedicated local session handlers. The current `Engine.advance` routes modes other than exactly `practice` toward lesson/review submission, so adding a bare `listening` mode there is unsafe. The current session projection exposes full subject details; introduce intentional unrevealed/revealed projections, including screen-reader output. Tests must prove listening cannot create an outbox operation.

Later listening extensions, after this flow works:

- **Type what you heard:** kana dictation checked against the actual played recording, with long vowels, small kana, particles, and alternate recordings covered by fixtures. This trains sound transcription separately from meaning recall.
- **Listen, repeat, compare:** play a recording and repeat aloud. An optional user-started temporary recording can support self-comparison later; no microphone is required for the first release and no automatic pronunciation score is implied.
- **Recognition gap:** identify words that are familiar in written practice but repeatedly missed by ear, using explicitly labeled local evidence. Offer a targeted five-word session rather than a misleading overall fluency score.
- **Context listening:** add sentence-level practice only when appropriate recordings and their usage rights are available. Vocabulary audio must not be presented as recorded example-sentence audio. Any future synthesis is explicitly labeled.

## 6. Fit study into the day

Add **Study rhythm** settings with three understandable choices: **When reviews become available**, **At chosen times**, or **Every N hours during a chosen window**. An optional preset suggests 10:00, 14:00, and 18:00 in the user's local timezone. Show the next reminder and its reason before saving. This is a product feature proposal; this planning update schedules no desktop or Codex reminders.

At each opportunity, create at most one native notification: **Take a Japanese break** with **Review 5** when due, **Listen 5** when eligible, and snooze/skip controls. Resolve the actions against current state when clicked. A caught-up account can receive a listening invitation when enabled; unavailable listening media does not create an empty session. Resume an unfinished session of the requested kind, preserving the mode distinction. Notifications never steal focus, reveal a study answer, or play vocabulary audio themselves.

Use one shared reminder policy for due transitions and timed invitations. Proposed defaults: a two-hour minimum between unsolicited reminders, at most three per local day, quiet hours 22:00–08:00, and no immediate nudge after recent study. Let the user choose review-only, listening-only, or both. Preserve existing explicit settings during migration and make the added limits visible. An explicit snooze schedules one replacement reminder, still subject to quiet hours, DND, lock, vacation, and work availability; it is not a new stream of prompts. Provide **Skip today** and a plainly labeled next-reminder preview.

Respect native Do Not Disturb, locking, fullscreen applications, active lessons/reviews/listening, vacation, and user snooze. Suppressed opportunities expire: unlock, wake, reconnect, or leaving DND never replays missed notifications. Account/auth/access trouble should use the existing attention state instead of repeated study invitations. Notification settings must describe reduced capabilities if the shell cannot expose actions or suppression state.

Persist the shared cooldown, daily count, schedule, and consumed reminder slots outside the source repository. Consume a slot durably before sending its notification; a crash may lose one invitation but must not duplicate it. Recompute future opportunities on timezone/DST/clock changes and resume; avoid duplicate local-time slots during autumn clock changes. Use the existing single service and a next-deadline timer, with event-based reevaluation. No separate daemon, system cron, or frequent background account polling is needed.

Reuse the plugin's native notification path with its explicit WaniKani app name. The installed generic `omarchy reminder` is a one-shot mechanism whose default `omarchy-action` notification identity bypasses DND, so chaining that command would violate this policy. Wait for the notifications service's settings to load before deciding whether startup reminders are allowed, and check its actual action capacity before fixing the final toast layout.

## 7. Make polish and all-theme support release requirements

Aim to exceed Tsurukame through clear interaction, desktop continuity, and visual consistency. Treat that as a quality target to demonstrate, not a superiority claim based on a mockup.

All surfaces must follow the active Omarchy theme live: bar, Today, lessons, reviews, listening, progress, lookup, dialogs, notifications, companion, and ambient scenes. Derive presentation from shared `qs.Commons.Color`, `Style`, `Border`, and native `qs.Ui` components. Centralize remaining semantic colors; never maintain a whitelist of supported theme names or freeze colors when a panel opens. Stock themes and arbitrary custom accents use the same path. Category/status labels remain explicit when palettes make their colors similar.

The installed shell already supports per-surface text/background roles and per-side or gradient borders through `Border.surfaceSpec` and `Ui.BorderSurface`. Use those contracts instead of flattening everything to the base palette and one border color. Live palette changes are already available through shared bindings; preserve them while extracting reusable study components.

Use a contrast-aware role layer for accent text, selected controls, disabled/read-only content, focus indicators, feedback, charts, and the crab's important details. Preserve the theme's character while falling back to readable neutral foreground/background combinations where needed. Test actual composited surfaces, including transparency and wallpaper. Set measurable targets of 4.5:1 for normal essential text and 3:1 for meaningful controls and focus indicators. These adopt WCAG contrast guidance as engineering targets for the native app; they are not a claim of full WCAG conformance. [Text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [Control contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

Polish includes a consistent type/spacing scale, legible Japanese glyphs, readable line lengths, predictable keyboard focus, obvious primary actions, and stable layouts during sync and answer feedback. Give loading, empty, offline, retry, read-only, vacation, and permission states useful wording and an appropriate next action. Keep technical status subordinate while study is healthy. Honor reduced motion, stop hidden animations, and retain exact context on every close/reopen or compact/full transition.

The visual qualification matrix includes every installed stock palette, representative custom and deliberately low-contrast palettes, live changes with a partially typed answer, compact/full panels, four bar orientations, multiple monitors, 100/125/150/200% scaling, keyboard-only navigation, Japanese IME, screen-reader labels, long content, and failed audio. No unexplained focus loss, clipped text, invisible controls, audio continuing after close, or theme-change loss of study state is acceptable. Keep performance profiling targeted at visible regressions; polish is part of every implementation pass.

## Implementation order and acceptance

| Pass | Deliverable | Acceptance gate |
|---|---|---|
| A — Study clarity and working audio | Explicit review/lesson routes and headers, safe saved-session selection, visible replay, voice test, current-clip download and error states | Lesson actions never return reviews or vice versa. Switching both ways and restarting preserve exact drafts/errors. Real cached vocabulary is audible after safe feedback and never leaks an unanswered reading. |
| B — Learning dashboard and progress | Actionable Today cards, proper level-up meter, level board, SRS names, personal subject status | Learner sees due work, new lessons, and remaining level requirements without scrolling. Passing counts match confirmed assignments; reset, partial sync, and pending work stay honest. |
| C — Listening and study rhythm | Listen 5, deliberate reveal/self-rating, local listening intervals/history, unified due/timed reminders and suppression | Listening creates no WaniKani writes; no hidden answers leak through labels; crash/restart preserves ratings exactly; missing media causes no false failure. Schedule tests cover cooldowns, DND, lock, vacation, resume, DST, stale actions, and no backlog. |
| D — Complete lesson experience | Batch preview, structured discovery, explicit quiz transition, clear summaries | A five-subject lesson batch is comprehensible by keyboard alone and returns to its exact place after closing. Reviews and lessons stay visually distinct on narrow and expanded surfaces. |
| E — Deeper practice | Dictation, optional self-comparison, contrast practice, recognition gaps, progression history polish | Each skill has honest local metrics and no graded side effects; the learner can return to paused graded work exactly. |

Reuse the current worker, native components, account cache, and outbox. Keep summary queries cheap and load level/subject details on demand. Retain the existing warm-open and answer-latency targets, but only profile new visible delays; the main work is learning UI and correctness.

Verification should combine documented API-shape fixtures, session migration/restart cases, real-component interaction tests, and short deliberate checks on the connected account. Native visual QA covers compact/expanded panels, keyboard focus, both themes, and existing monitor scales. Live verification only submits study that the user deliberately completes. Finish with the existing [fourteen-day daily-use log](DAILY_USE.md).

The next implementation milestone remains **passes A and B**, immediately followed by **C**. Listening and study rhythm are core deliverables rather than speculative extras. Apply the theme, interaction, and accessibility gates throughout all passes, then qualify the combined client through daily use.
