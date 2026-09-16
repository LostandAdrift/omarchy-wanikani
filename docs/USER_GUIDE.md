# Using WaniKani for Omarchy

Start with a small session, finish the work you intended, and return to your desktop. The native interface follows your Omarchy theme and keeps lessons, reviews and local practice distinct.

This guide describes the **current repository source**. A source checkpoint passing automated or offscreen tests does not mean that checkpoint is installed. Check [verification](VERIFICATION.md) and the [overnight log](OVERNIGHT_WORK.md) for the installed revision and its actual checks. Later installation is currently deferred by the observed [shell lock/reload incident](LOCK_RELOAD_INCIDENT.md). Do not install, update, remove or reload the plugin while the desktop is locked or its lock state is unknown.

This remains a development client. Audible original Japanese playback, physical keyboard and IME use, desktop lifecycle/lock/suspend/Do Not Disturb checks, deliberate live lessons and reviews, and fourteen days of personal daily use still require qualification. See the [first-session checklist and daily-use log](DAILY_USE.md). Authored demonstrations and muted decoder tests do not establish those outcomes.

## Choose a session

Open the crab in the bar for **Today**. Reviews and Lessons have separate overview screens showing what is available and where any saved session will resume. Default study batches contain five subjects; the overview and Study settings let you choose a different size.

| Choose | What you do | What it changes |
| --- | --- | --- |
| **Reviews** | Recall subjects you have already learned. | Completed answers wait for WaniKani confirmation and its next schedule. |
| **Lessons** | Explore new subjects, then explicitly begin their quiz. | A completed quiz queues the assignment start. |
| **Practice** | Choose difficult, missed or learned subjects for an ungraded batch. | Local practice records; no WaniKani schedule change. |
| **Listen → Recall meaning** | Hear a familiar word, reveal it, then self-rate recall. | Its own saved session and local listening intervals. |
| **Listen → Type kana** | Hear a familiar recording and type its kana. | A separate saved draft, batch and local dictation intervals. |
| **Zen → Quiet recall** | Reveal learned words at your own pace. | No scores or submissions. |

An unfinished Review session and an unfinished Lesson session are saved independently. Switching modes preserves each question, answer draft, discovery step and error count. If an earlier start is still refreshing, your later study choice takes precedence; the older request cannot switch the active mode back. Explicit Reviews or Lessons actions resume their own mode. Generic Resume prefers saved graded work, then saved ungraded practice. Practice can coexist with paused graded work; it does not erase it.

The answer field receives keyboard focus when a question opens or resumes, and after advancing from feedback. You can type immediately; closing releases the panel’s keyboard focus.

**Escape** saves your place and returns to work. **Expand** changes the presentation without restarting. **Enter** checks an answer and, after feedback, advances. Holding Enter cannot check and immediately skip the feedback. **F1** opens keyboard help. **Ctrl+0** opens Type kana inside the panel when focus is outside a text field. Navigation shortcuts leave answer fields and IME composition alone, and focused controls scroll into view.

**Alt+1–7** selects the visible top row from left to right: Today, Reviews, Lessons, Listen, Progress, Lookup, and More. The numbers on each tab are reminders; hover shows the full shortcut. These shortcuts work while typing and retain the saved draft, but pause during Japanese IME composition or a pending study action. Reviews and Lessons open their overviews. Alt+7 toggles More and focuses its first option; Tab moves through those extra views. The older Ctrl navigation shortcuts still operate outside text fields.

The optional desktop integration supplies **Super+Alt+W** for study and **Super+Alt+Shift+W** for selection lookup when those bindings are free. Install or remove it under **Settings → Desktop**; occupied bindings and unrelated configuration are preserved. For command-line usage, see the [README](../README.md) and [command-line support](AGENT_SUPPORT.md). Press **F1** for the complete keyboard shortcut reference.

## Learn a lesson, then take its quiz

The lesson overview lists confirmed unlocked subjects with separate radical, kanji, vocabulary and kana-vocabulary counts. Browse its pages, preview the recommended order, or choose **1–20 subjects** yourself. Recommended order follows level and WaniKani's lesson order. The preview shows required cached-content readiness; previewing does not start study. An existing saved lesson always resumes its original selection and position.

Discovery follows **Meaning → Reading or Sound → Context**, using only applicable steps. Meaning includes the mnemonic, hints and your saved meaning note. Kanji and vocabulary have Reading; kana vocabulary with audio has Sound and does not acquire a reading quiz. Radicals have no reading step. Context appears when usable examples, relationships or comparisons are available.

Previous and Next move through steps and subjects. After the last applicable step, **Start lesson quiz** is a separate action. There is no countdown or required reading time. Closing saves the exact step; reopening stays silent. See [guided lessons](GUIDED_LESSONS.md).

**How this subject connects** expands the cached components, current subject and related words into readable cards. Lesson Context stays in place; explicit Open actions are available in Lookup. Missing glyphs are labeled and the view is partial. See [subject connections](SUBJECT_PATH.md). **Tell them apart** opens a comparison of similar kanji using WaniKani's [visual-similarity links](https://docs.api.wanikani.com/20170710/#kanji). Inaccessible subjects and unfinished graded answers are withheld from these automatic comparisons. The comparison never changes a grade. [Authored lesson comparison](screenshots/comparison-dark.png)

## Answer reviews and lesson quizzes

A subject counts as finished only after all its required question parts are complete. Wrong answers keep their per-part error counts. Romaji converts to kana locally through bundled WanaKana; you can also use Japanese input. Large Japanese prompts fit the available width without truncating long vocabulary, and image radicals keep their meaning hidden until the appropriate reveal.

Reading answers require exact normalized kana. Meaning grading accepts the subject's allowed answers and saved personal synonyms, with conservative spelling tolerance that preserves quantities and negation. **Settings → Study → Require exact meanings** turns off that tolerance while retaining accepted variants, synonyms and distinct retryable input mistakes. Incomplete answer data cannot enter study.

**I made a typo** is available only for the current incorrect feedback before advancing. The correction is recorded locally. A completed subject enters the submission queue only when you acknowledge its final feedback; already committed WaniKani progress cannot be retroactively changed. Feedback exposes only the part you just answered, with the relevant personal note where available.

Choose **A batch** or **All due · N** on the Reviews overview. This choice is remembered for Today and the next default review start, and can also be changed in Settings → Study. An explicit batch start still uses that batch size. All due includes eligible cached subjects due when the new session starts after its normal refresh; missing content, pending work and inaccessible subjects remain excluded. New arrivals do not extend the saved stack. Lessons remain separate batches.

The review header shows completed subjects out of the session total. All-due sessions also show how many remain. Escape pauses the entire stack with its exact draft and mistakes. **Finish this batch** ends after the current group of five, leaving untouched reviews due for another session. Changing the default never reshapes an unfinished saved session.

At the end, **Review this session** shows recorded mistakes and each subject's current local submission status. Large recaps have Previous/Next controls with twenty subjects per page. **Practice items to revisit** opens ungraded practice of missed items on that page; guarded typo corrections are excluded. Another session is optional. [Authored batch recap](screenshots/recap-dark.png)

The **Practice** library groups saved difficult items, recent local mistakes and learned subjects. Compact cards show familiar SRS stage names and give the selection reason its own line. Choose up to twenty, or add five at a time. Cards explain why each item appears and whether required content is available offline. Graded answers remain concealed on protected library cards. Starting an explicitly different practice selection keeps the earlier local record and paused lessons/reviews; it replaces only the active ungraded practice reference. [Authored compact practice selection](screenshots/practice-component-dark.png)

## Hear original pronunciation

Vocabulary recordings have visible Play/Replay, Stop, download and error states. An explicitly requested clip can download without blocking answer handling. In **Settings → Audio**, choose a voice from accessible cached material and use **Test selected voice** for a safe learned sample. The test is deliberate; leaving Audio stops its sample.

If the preferred clip is missing offline but another recording is cached, that alternate stays usable. Missing voice metadata does not discard the saved preference. Playback stops when its surface, subject, account or study question changes.

Audio settings are independent:

- **Autoplay pronunciation after review readings** applies after the reading is revealed.
- **Autoplay pronunciation while learning lessons** can play on deliberate navigation into the current subject's Reading/Sound step. Reopening a saved step stays silent.
- **Autoplay new listening prompts** follows an explicit Start or rating action in local meaning listening. Resume, reopening and background updates remain silent. Kana dictation always requires explicit playback.

Kanji pages offer **Hear this kanji in a word** during Reading/Context and appropriate reading feedback. Open it to see up to three whole-vocabulary examples, then play a chosen recording. Each shows the written word, actual pronunciation, meaning and offline availability; new vocabulary is labeled as a preview. Protected graded items stay out. This does not start lessons or change grades. See [kanji audio examples](KANJI_AUDIO.md).

## Practise meaning by ear

In **Listen → Recall meaning**, start or resume a batch of up to five familiar words with cached WaniKani recordings. The prompt hides the written word and answers. Play and replay, recall a meaning, then **Reveal word** before choosing **Got it** or **Again**. The reveal shows the word, meanings, pronunciation and available ambiguity information.

This skill has its own local intervals: successes progress through 1, 3, 7, 14 and 30 days; Again makes the word due in ten minutes. It never submits a WaniKani review or changes your level. Skip changes no interval. Undo can revise the immediately preceding local rating, but hearing or revealing a new word still consumes its introduction allowance.

There are **five newly introduced meaning-listening words per local day**; returning local words follow their intervals. Words in unfinished graded work, their protected readings and unresolved graded submissions are excluded. By default, WaniKani reviews due within the next 24 hours are also excluded. **Include due-soon words** changes that preference explicitly. Closing preserves the listening session, and returning is silent.

If familiar words are eligible but recordings are missing, **Prepare recordings** prepares a batch of up to five, counting already usable clips toward that number. Count-only progress keeps the words hidden. Preparation respects access and the media budget, and neither starts practice nor plays audio nor consumes introductions. **Cancel preparation** stops further downloads; completed files remain available. Start listening separately afterward.

An unfinished listening session keeps its Resume action instead of being replaced by preparation. Offline, budget, daily-allowance and incomplete-catalogue limits are explained in the view. A partial check is not proof that no other words exist. Preparation is offered in native Listen; a command-line helper can open the view but cannot initiate that download. See [recording preparation](LISTENING_PREPARATION.md).

## Type what you heard

**Listen → Type kana** is a separate five-word activity with its own saved draft and five-new-words daily allowance. It uses familiar cached recordings and does not use a microphone or transcription service.

1. Play the recording. Check becomes available after the current player reports completed playback; that signal cannot establish whether your output device was audible. Stopping or a decode failure is not a wrong answer.
2. Type romaji or kana. Committed edits and the cursor are saved. Check waits while the IME is composing and finalizes terminal `n`. A saved preedit note preserves text intent, not the native IME candidate window.
3. Check valid kana to reveal **Your kana** and **Recorded kana**. Empty or non-kana input is retryable without revealing the answer. Check alone changes no interval or completed-result count.
4. Continue records **Matched the recording** or **To revisit** and advances. The local intervals are 1/3/7/14/30 days for matches and ten minutes for revisits. Skip changes no interval and records no correctness result, including after feedback or for an unavailable recording.

The comparison uses the exact selected recording's kana metadata after normalization. Small kana, doubled consonants and long-vowel spelling matter; different homophones or alternative subject readings are not inferred to match that clip. You may Skip a plausible alternative spelling without a correctness result. This describes matching recorded kana, not an overall listening-accuracy score.

Undo restores the immediately preceding committed result, feedback and interval until another result or Skip is committed. It does not refund an introduction already exposed. First media delivery can conservatively consume a new-word slot even if a device subsequently fails. Replay and resume retain the same recording; neither changes it to another voice. Opening, returning and reconnecting do not autoplay. See [dictation details](DICTATION_PLAN.md).

## Understand progress and activity

Today uses a saved seven-day recap, so its date window and calculation time may lag Activity. “Latest activity not checked” means freshness is unknown. Open Activity for a current local report.

**Progress → Subjects & unlocks** shows confirmed first passing toward the current level's 90% kanji requirement, pending work separately, current SRS distribution and a paged level board with prerequisites and known review times. Missing or ambiguous account data is labeled rather than counted as confident progress. Unrevealed graded subjects remain protected.

Choose an SRS group or open **SRS explorer** to browse across accessible levels. Refine by type, level and exact stage; order by level or confirmed next-review time. **Back to progress** restores filters and page after details or notes. A pending review keeps its confirmed stage until synchronization; a local result does not predict the next one. Partial cached totals are marked. Explorer and History use compact current-level context so the selected view stays near its tabs. See [SRS explorer](SRS_EXPLORER.md).

**Level history** shows account milestones and separate recorded visits after resets. Expand **Show dates** for unlock, first lesson, passing, all-subjects-burned and ended-visit dates where supplied. Passing and burning all subjects are different milestones. Durations include calendar breaks and vacation, use explained endpoints and stay unknown for unreliable dates. Older API history may be absent even after complete synchronization; there is no completion forecast. Refresh history rereads the local cache, while Refresh account synchronizes it. [Level-history scope](LEVEL_HISTORY.md)

**Activity** reports the last seven or thirty local calendar days of completed subjects/batches, meaning-listening self-ratings, kana-dictation results and typo corrections. Submission confirmations and attention states remain separate. Retained records before an account reset still describe work done here. These counts do not reconstruct individual reviews from other devices. Suggestions open an overview without starting study.

For the same distinction in a cached command-line recap, use the documented [learning reports](AGENT_SUPPORT.md#cached-learning-reports). Reports carry their own calculation time and stale/unknown status; reading a report does not refresh the account or start a session.

## Look up a word or practise from a passage

Lookup labels use named SRS stages from cached confirmed assignments. Waiting or attention flags are shown separately; an unfinished local result never predicts the next stage. Missing or invalid progress stays unavailable.

Invoke lookup to read the current selection, falling back to clipboard text. It does not poll your clipboard. You can also type Japanese, romaji readings, meanings or saved personal synonyms. Type/progress filters narrow the accessible catalogue; exact matches rank first and longer selections surface known words contained in the text. This is local WaniKani catalogue search, with no screenshot OCR or general translation service.

**Words in your selection** preserves the passage's spaces, newlines and rare kanji while linking matched words. The passage is limited to **256 Unicode code points**, with an explicit notice for longer input. Eight word buttons appear initially; show the rest as needed. Overlapping vocabulary remains available as separate matches. Open a highlighted word or button, inspect it and return to the same passage. Waiting and uncertain work have explicit labels. Trail links keep unfinished graded subjects closed; ordinary deliberate catalogue lookup retains its own policy. [Authored reading trail](screenshots/reading-trail-dark.png)

**Choose words to practise** lets you select 1–20 current matches. A read-only preview checks required content without exposing meanings/readings. Start validates the selection again; completed work waiting to sync remains eligible for this independent ungraded practice. If another practice session is saved, choose **Resume earlier practice** or explicitly **Start new practice**. Lessons, reviews, drafts and error counts remain intact.

**Back to passage** returns to the exact text and chosen words. That passage/selection context stays in panel memory across closing and details, and clears on account/content changes; it is not a durable passage library. The saved practice retains the selected subjects, not the passage. See [practice from a passage](TRAIL_PRACTICE.md).

Personal note and synonym drafts are different: they survive navigation, close and restart, including unfinished commas. **Save notes & synonyms** applies the material to study and queues synchronization; **Discard draft** restores the saved version. Unsaved synonyms are never accepted answers. You can keep drafting while an older save waits, and a delayed Save/Discard cannot erase newer input.

## Find the right setting

Settings uses compact section buttons. Account is the initial choice without a connection; Study is the initial choice when connected or in demo. Entering a section focuses its first relevant control. Switching sections keeps unfinished token, reminder and deletion-confirmation input alive in the panel; this does not promise persistence of those settings-form drafts across a worker or shell restart.

| Section | Controls |
| --- | --- |
| **Account** | Connect/replace token, secure remembering, disconnect/token-removal retry, enter/leave demo and demo simulation/reset. |
| **Study** | Batch size and exact meaning grading. |
| **Audio** | Voice selection/test, separate review, lesson and meaning-listening autoplay preferences. |
| **Reminders** | Study rhythm target, timing, quiet hours and schedule preview/apply. |
| **Desktop** | Companion animation, reduced motion, optional desktop/idle displays, shortcut and launcher integration. |
| **Storage** | Offline readiness, cache size/limit, refresh cached material, clear downloaded media and diagnostic export. |
| **Data** | Saved submissions/recovery and explicit local-data deletion. |

Hidden Audio does not fetch voice choices or keep its test playing. Reminder drafts remain unapplied until you use the schedule's Apply action. Ordinary study/audio toggles retain their immediate-setting behavior.

## Work offline and recover submissions

Accessible subject text is cached; media downloads incrementally, with up to forty new assets per sync and a configurable disk ceiling. Required images for active study and upcoming work take precedence over optional audio and distant subjects. Usable existing images and voice clips remain while replacements download. Image-only radicals need a cached image before quiz entry. The Practice library checks the displayed page's readiness and labels its scope.

Today and **Settings → Storage** show separate readiness for due-now reviews, lessons and reviews scheduled in the next 24 hours. Required text/images and optional audio are counted separately; scheduled readiness also considers known subscription expiry. These checks run in the background and incomplete checks are labeled. Synchronization shows its current stage.

Resuming saved work reads its durable question and draft immediately. New online study refreshes account state first and defers optional media downloads. Reconnection coalesces a refresh through the shared networking service; ordinary suspend does not by itself invalidate the offline clock. A detected uncertain clock may require account refresh before graded study.

Cached lessons and due reviews can be completed offline within your subscription access. Their results remain **pending**, and the same subject cannot enter another graded cycle while waiting. New scheduling and unlocks require WaniKani confirmation; known content-access expiry still applies offline.

If a submission loses its response, it becomes **uncertain**. WaniKani provides neither server idempotency keys nor retrievable individual review history, so the plugin does not automatically replay an uncertain write. Refresh reconciles remote assignment state. If another client progressed or reset the subject, remote progress wins while the local answer record remains.

Open **Settings → Data → Saved submissions** to inspect paginated results, error counts and reasons for waiting/attention. Filter review, lesson or note edits, and inspect confirmed or archived records separately. An explicit recovery action keeps remote progress and archives an unresolved local result; there is no force-resubmit button. Resolve pending work before considering local-data deletion.

In demo, **Simulate offline in demo**, **Reconnect demo & sync** and **Reset demo progress** use independently authored fixtures. They neither change the computer's network connection nor contact WaniKani. Demo is useful for exploring pending states, but it does not qualify real network recovery or live study.

## Plan desktop study breaks

The bar shows due items, pending work or the next-review countdown. Today's **Plan your next break** graph shows the next 24 hours of the cached schedule. Hover, tap or use arrow keys to inspect the local interval, reviews arriving in that hour and cumulative upcoming total. Already-due reviews remain separate.

Under **Settings → Reminders**, Study rhythm offers due-review reminders, chosen local times or intervals within a daytime window. Choose reviews, listening or both, preview, then apply. Defaults share a two-hour minimum, three reminders per day and quiet hours of **22:00–08:00**. Snooze or skip today without rewriting the schedule. Invitations share a budget and respect Do Not Disturb, lock, fullscreen, vacation and active study. Suppressed reminders are not replayed as a backlog.

A small dismissible celebration marks a level increase confirmed by synchronization. First connection establishes the baseline; offline results cannot invent a milestone. The companion has no hunger, penalty or streak-loss mechanic.

Desktop and idle kanji displays are optional. The desktop card appears after ten seconds without activity. Both use learned subjects not due in the next day, hide on activity/fullscreen/study/lock and yield before Omarchy's configured screensaver. Idle display respects stay-awake and disables itself if the configured interval is too short. These displays do not own or change the system lock; that design boundary does not remove the separately documented shell reload issue.

Manual **Zen** works with both automatic displays off. **Quiet recall** hides meanings/readings until Reveal, with no timing, score or submission; automatic advance pauses while recalling. Ambient content is requested only for a display or open Zen view that needs it. Companion animation and reduced motion have independent controls. [Authored quiet recall](screenshots/quiet-recall-dark.png)

## Account access and your data

Connect in **Settings → Account** using a WaniKani personal API token. A read-only token supports lookup and progress. Native lessons/reviews need assignment-start and review-create permissions; synchronized notes/synonyms need study-material create/update permissions. The token travels over private process pipes and can be remembered with the desktop keyring. Session-only authentication is available when secure storage is unavailable.

If the interface reports that an older saved token still needs removal, unlock the keyring and use Disconnect/Retry token removal. A local-data deletion can succeed while keyring cleanup fails; follow its explicit warning instead of assuming the credential was removed.

- Durable state lives under `${XDG_STATE_HOME:-~/.local/state}/omarchy/wanikani/` in separate `account.sqlite3` and `demo.sqlite3` databases. Demo results never reach WaniKani.
- Media is disposable. Sessions, drafts and pending submissions use durable SQLite transactions. **Clear downloaded media** does not mean delete saved study.
- **Export diagnostics** produces the documented redacted diagnostic file, excluding the token, answers, notes and username. No token belongs in source, `shell.json`, process arguments or diagnostics.
- **Remove local account data…** affects the selected mode's local account cache, history and sessions. In account mode it also requests credential cleanup. Type `DELETE` and separately acknowledge discarding unresolved submissions if applicable. It does not delete your WaniKani account.
- Plugin removal leaves local account data until explicitly deleted. The optional integration remover removes only owned, unchanged launchers and its marked shortcut block.

Installation and removal instructions live in the [README](../README.md). Keep source separate from private state and never copy account databases or keyring contents into a release. The project has no telemetry, cloud backend or AI grading; account synchronization and media downloads still use the network.


## Review keyboard and desktop behavior

Reviews explicitly label **MEANING · Answer in English** and **READING · Type the pronunciation**. Reading input converts romaji to kana. Enter checks an answer and then continues from feedback; it never automatically acknowledges feedback. The action row stays below the scrolling explanation. **Alt+P** plays an available recording after checking a reading, including incorrect readings; meaning questions do not reveal vocabulary pronunciation. **Alt+D** focuses the explanation, where Enter continues. These shortcuts pause during IME composition, and playback pauses while saving, locked, closed, or already loading audio.

A visible **Settings** button opens the existing categorized settings page. Under **Desktop → Window behavior**, **Close when clicking outside** defaults to On and includes clicks on another monitor. Pointer movement alone does not dismiss the panel. Turn it Off to keep the panel visible while another application receives input. Escape and Close always dismiss. The preference is stored with local settings, survives restart/update, and leaves saved questions, drafts, feedback and error counts intact.
