# WaniKani for Omarchy

**Five reviews, then back to work.**

A native WaniKani study companion for Omarchy 4: lessons, reviews, offline sessions, selection lookup, an ambient kanji gallery, and a little crab. The interface follows your desktop theme. There is no browser wrapper, cloud backend, telemetry, or AI grading.

This is an independent community client, not a Tofugu product. **Version 0.1.0 is a development release.** Live-account qualification and two weeks of personal daily use are still pending before a contest-ready 1.0.

![Native dashboard in Tokyo Night, showing an authored demo account](docs/screenshots/dashboard-dark.png)

The same lookup follows [Tokyo Night](docs/screenshots/lookup-dark.png) and [Flexoki Light](docs/screenshots/lookup-light.png). See the [kanji gallery and companion](docs/screenshots/zen-dark.png). These are captures of the installed plugin, using independently authored demo content.

## Install

The current development installation is a Git clone of the local workspace repository. Its `origin` points to that workspace, not to a public GitHub repository. No public repository or contest submission has been published.

The repository root is a valid Omarchy plugin. To install a committed local checkout, run `omarchy plugin add /absolute/path/to/omarchy-wanikani --enable`. After publishing a reviewed copy to your Git host, use its repository URL in the same command. Keep private account state outside the repository; do not copy your state or keyring into a release.

Runtime requirements are Omarchy 4.0.2+, Quickshell 0.3.1+, Python 3.11+, Qt Multimedia, and a Japanese font (Noto Sans CJK JP recommended). `wl-paste` powers explicit selection lookup; `secret-tool` provides optional secure persistence.

Open the crab in your bar. Choose **Try the demo** to explore without an account, or open Settings to connect a WaniKani personal API token. Read-only tokens support lookup and progress; native study needs assignment-start and review-create permissions. Editing notes and synonyms also needs study-material create/update permissions. The token is passed over private process pipes and stored only in your desktop keyring when available. Session-only mode works when the keyring cannot store it.

Settings includes **Install shortcuts & launchers** and **Remove shortcuts & launchers**. From the installed plugin directory, the same optional setup is available with:

```sh
python3 tools/integrate.py check
python3 tools/integrate.py install
```

This adds Study and Lookup launchers and available shortcuts, backing up your bindings. It preserves shortcuts that are already occupied.

| Action | Shortcut / command |
|---|---|
| Study or resume | Super+Alt+W |
| Look up selected text | Super+Alt+Shift+W |
| Check / continue | Enter |
| Save and return to work | Escape |
| Dashboard | `omarchy-shell wanikani dashboard` |
| Reviews / lessons | `omarchy-shell wanikani reviews` / `omarchy-shell wanikani lessons` |
| Lookup / Zen | `omarchy-shell wanikani lookup` / `omarchy-shell wanikani zen` |
| Refresh / status | `omarchy-shell wanikani refresh` / `omarchy-shell wanikani status` |
| Settings / saved submissions | `omarchy-shell wanikani settings` / `omarchy-shell wanikani recovery` |
| Practice library / help | `omarchy-shell wanikani practice` / `omarchy-shell wanikani help` |
| Keyboard help | F1 |
| Panel navigation outside text fields | Ctrl+1 Today, Ctrl+2 Study, Ctrl+3 Lookup, Ctrl+4 Zen, Ctrl+5 Settings, Ctrl+6 Practice |
| Enter / leave demo | `omarchy-shell wanikani demo true` / `omarchy-shell wanikani demo false` |

Shell payloads also work: `omarchy-shell shell summon io.github.lostandadrift.wanikani '{"view":"reviews","limit":5}'`. Supported views: dashboard, reviews, lessons, practice, practice-library, resume, lookup, zen, settings, help, recovery. Direct practice accepts `subjects:[1,2]`; practice-library opens the selection view. Lookup accepts `selection:true` or `text:"山"`.

## How study works

Sessions contain five subjects by default. Lessons introduce the subjects before their quiz. Reviews test each required part; wrong answers retain their mistake counts until the subject is finished. Romaji converts to kana locally, and existing Japanese input methods are supported.

**Require exact meanings** in Settings disables automatic spelling tolerance while keeping accepted variants, saved synonyms, and distinct retryable input mistakes. Readings always require exact normalized kana. Conservative grading preserves quantities and negation, and incomplete answer data cannot enter study.

**I made a typo** is available only on the current incorrect feedback screen. Corrections are recorded locally. A finished subject enters the submission queue only after you acknowledge its last feedback screen. Already committed WaniKani progress is never retroactively overridden.

After a batch, **Review this batch** shows each subject’s recorded mistakes and current local submission status. **Practice items to revisit** starts ungraded practice of missed items; guarded typo corrections are excluded. Back to work remains the primary action.

See the native [batch recap](docs/screenshots/recap-dark.png) and [practice selection](docs/screenshots/practice-dark.png), captured with authored demo subjects.

Escape preserves the exact session, draft answer, and question. Expand changes the presentation without restarting. Practice is ungraded and never changes your account's schedule. You can practice independently while a graded session is paused; Resume returns to that saved graded session first.

Japanese prompts fit the available space without cutting off long vocabulary. Image radicals keep their meaning hidden until the appropriate reveal.

Lessons group the meaning, reading, and example sentences clearly. Saved personal notes appear beside the relevant mnemonic, including after a mistake. Feedback shows only the part you just answered.

**Tell them apart** opens a side-by-side comparison of similar kanji, with large characters and the relevant meanings or readings. It uses WaniKani’s [visual-similarity links](https://docs.api.wanikani.com/20170710/#kanji); inaccessible content and subjects in unfinished graded work stay out of the comparison. This is a study aid and never changes your grades.

See the native [lesson comparison](docs/screenshots/comparison-dark.png) and [quiet recall](docs/screenshots/quiet-recall-dark.png), captured with independently authored fixtures.

The **Practice** library groups saved difficult items, recent mistakes, and learned subjects. Choose up to twenty, or add five at a time. It shows why each subject appears and whether required content is cached. An explicitly selected practice session keeps earlier local records and the paused graded session intact. Current graded answers remain hidden on library cards.

Lookup accepts romaji readings as well as Japanese, meanings, and personal synonyms. Type and progress filters narrow the accessible catalogue. Exact matches rank first; longer selections surface known words contained in the text. Lookup never sends selections to a translation service.

**Words in your selection** turns a short Japanese passage into a local reading trail. Select a highlighted word or a word button to inspect it, then return to the same passage. Overlapping vocabulary remains available as separate matches. The trail preserves spaces, newlines, and rare kanji; selections longer than 256 characters show a clear limit notice. Eight word buttons appear initially, with a control to show the rest. Pending and uncertain work have explicit status labels. Trail links keep unfinished graded subjects closed; ordinary deliberate catalogue lookup remains available. See the [native reading trail](docs/screenshots/reading-trail-dark.png), captured with an authored passage.

Notes and synonym drafts survive closing, navigation, and restart, including unfinished commas. **Save notes & synonyms** applies them to study and queues synchronization; **Discard draft** restores the saved version. Unsaved synonyms never count as answers. You can keep drafting while an earlier save waits to sync, and a delayed Save or Discard cannot erase newer input.

**F1** opens keyboard help. Navigation shortcuts leave text fields and IME composition alone, focused controls scroll into view, and holding Enter cannot check an answer and immediately skip its feedback.

## Offline behavior and recovery

Subject text is cached for your accessible levels. Media is downloaded incrementally, with up to 40 new assets per sync and a configurable disk limit. Image-only radicals require their image before they can be quizzed. Audio availability is shown explicitly.

When the media cache is full, required images for active study and upcoming work take priority over optional audio and distant subjects. Existing usable images and voice clips stay available while replacements download. The Practice library checks the displayed page's offline availability and labels that count, keeping large learned catalogues responsive.

Settings lists pronunciation voices from the accessible cached catalogue. A preferred voice uses its downloaded clip when available, falling back to another downloaded voice for that word. Missing voice metadata does not discard your preference.

The dashboard and Settings show offline readiness for reviews due now, lessons, and reviews scheduled in the next 24 hours. Required text/images are checked separately from optional audio, including whether subscription access will cover each scheduled review. Availability checks run in the background, and synchronization reports its current stage. Resuming saved work reads the latest durable question and draft immediately. New online study refreshes account state first and defers optional media downloads. Reconnection triggers a coalesced refresh through the shell’s shared networking service; ordinary suspend does not invalidate the offline clock.

Cached lessons and due reviews work offline. Completed work stays pending until confirmed. A pending subject cannot enter another graded cycle, and subsequent scheduling/unlocks wait for WaniKani's response. Subscription access and known expiry dates still apply offline.

The API does not provide idempotency keys or retrievable individual review history. A timed-out submission is **uncertain**, never automatically retried. Refresh reconciles it against remote progress. When another client has changed the assignment, its state wins and the local answer remains recorded. The **Saved submissions** page shows paginated local records, error counts, and the reason a result is waiting or needs attention. Filter reviews, lessons, or note edits; inspect confirmed and archived records separately. An explicit recovery action lets you keep remote progress and archive an unresolved local result. This recovery path deliberately offers no force-resubmit button.

Activity charts show only completed subjects and practice recorded by this plugin. They do not reconstruct your all-device review history.

Demo Settings includes **Simulate offline in demo**, **Reconnect demo & sync**, and **Reset demo progress**. This exercises pending submissions using authored fixtures without changing the computer's network connection or contacting WaniKani. It is a demonstration aid; real network recovery is tested separately with a mock API and must still be qualified on a live account.

## Desktop behavior

The bar shows due items, pending work, or the next-review countdown. Notifications are coalesced, with a default two-hour minimum and quiet hours of 22:00–08:00. They respect Do Not Disturb, lock, vacation, and study. Suppressed reminders are not replayed later.

The dashboard offers a small, dismissible celebration when synchronization confirms a new account level. The first connection establishes a baseline; local offline results do not invent milestones. Companion animation respects reduced motion.

**Plan your next break** lets you inspect each hour of the next day’s cached review schedule. Hover, tap, or use the arrow keys to see the local time, reviews arriving in that hour, and the cumulative upcoming total. Reviews already due remain separate.

Desktop and idle kanji displays are optional. The desktop card appears after ten seconds without activity. They show learned subjects not due in the next day, stop on activity/fullscreen/study/lock, and give way before Omarchy's configured screensaver deadline. Automatic idle gallery display respects Omarchy's stay-awake mode and disables itself when the configured interval is too short. The plugin never owns or changes your system lock. Companion animation and reduced motion have separate controls.

Manual Zen works with both automatic displays switched off. Ambient catalogue requests run only while a display or an opened Zen view needs them; study and hidden surfaces avoid that background work.

Zen’s optional **Quiet recall** hides the meaning and reading until you reveal them. Take as long as you like, then move to another learned word. There are no scores or submissions, and automatic advance pauses while recalling.

## Your data

- State: `${XDG_STATE_HOME:-~/.local/state}/omarchy/wanikani/`
- Separate `account.sqlite3` and `demo.sqlite3`; demo results never reach WaniKani.
- Media is disposable; sessions, drafts, and pending submissions are durable SQLite transactions.
- Settings can disconnect, clear media, export redacted diagnostics, or explicitly remove local data. Deletion requires separate acknowledgment for unresolved work.
- No token is stored in source, shell.json, command arguments, or diagnostics.

## Update and remove

Use `omarchy plugin update io.github.lostandadrift.wanikani` for Git-installed copies. This development installation pulls committed changes from its local workspace origin. A future public installation will pull from its published origin. Plugin source contains no generated account state.

On the tested host, hot reload retained durable session state but sometimes kept nested QML components stale. If an update leaves old visuals visible, close the panel and run `omarchy restart shell`; the worker restores the saved session when the shell returns.

Before removing the plugin, remove the optional desktop integration:

```sh
python3 tools/integrate.py remove
omarchy plugin remove io.github.lostandadrift.wanikani
```

Integration removal only removes owned, unchanged launchers and the marked shortcut block. Account data remains until explicitly deleted in Settings. Resolve pending work before deleting local data.

## Development and release qualification

```sh
python3 -m unittest discover -s tests -v
omarchy plugin validate .
```

See [isolated native QA](docs/NATIVE_QA.md), [verification](docs/VERIFICATION.md), [read-only performance profiling](docs/PERFORMANCE.md), [architecture](docs/ARCHITECTURE.md), the [contest demonstration](docs/CONTEST_DEMO.md), and the [implementation checkpoint](docs/IMPLEMENTATION.md). Automated tests use authored fixtures and mock API responses, never real graded submissions. WanaKana is bundled with its MIT notice; no npm installation is needed.

The release gate includes two weeks of personal daily use, checks across desktop configurations, and deliberately answered live lessons/reviews. Those are not replaced by passing automated tests.

Use the [first-session checklist and fourteen-day log](docs/DAILY_USE.md) to record that qualification.

Planned extensions include practice selections directly from the reading trail, contrast practice, and a visual lesson path. Their scope and acceptance criteria are in [next feature proposals](docs/NEXT_FEATURES.md).
