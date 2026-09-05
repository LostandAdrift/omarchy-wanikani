# WaniKani for Omarchy

**Five reviews, then back to work.**

A native WaniKani study companion for Omarchy 4: lessons, reviews, offline sessions, selection lookup, an ambient kanji gallery, and a little crab. The interface follows your desktop theme. There is no browser wrapper, cloud backend, telemetry, or AI grading.

This is an independent community client, not a Tofugu product. Version 0.1.0 is a development release; real-account daily-use qualification is still required before a contest-ready 1.0.

## Install

Publish this repository to your Git host, then install its repository URL with `omarchy plugin add <repository-url> --enable`. The repository root is a valid Omarchy plugin. Runtime requirements are Omarchy 4.0.2+, Quickshell 0.3.1+, Python 3.11+, Qt Multimedia, and a Japanese font (Noto Sans CJK JP recommended). `wl-paste` powers explicit selection lookup; `secret-tool` provides optional secure persistence.

Open the crab in your bar. Choose **Try the demo** to explore without an account, or open Settings to connect a WaniKani personal API token. Read-only tokens support lookup and progress; native study needs assignment-start and review-create permissions. Editing notes and synonyms also needs study-material create/update permissions. The token is passed over private process pipes and stored only in your desktop keyring when available. Session-only mode works when the keyring cannot store it.

From the installed plugin directory, optionally run:

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
| Enter / leave demo | `omarchy-shell wanikani demo true` / `omarchy-shell wanikani demo false` |

Shell payloads also work: `omarchy-shell shell summon io.github.lostandadrift.wanikani '{"view":"reviews","limit":5}'`. Supported views: dashboard, reviews, lessons, practice, resume, lookup, zen, settings. Practice accepts an array of subject IDs. Lookup accepts `selection:true`.

## How study works

Sessions contain five subjects by default. Lessons introduce the subjects before their quiz. Reviews test each required part; wrong answers retain their mistake counts until the subject is finished. Romaji converts to kana locally, and existing Japanese input methods are supported.

**I made a typo** is available only on the current incorrect feedback screen. Corrections are recorded locally. A finished subject enters the submission queue only after you acknowledge its last feedback screen. Already committed WaniKani progress is never retroactively overridden.

Escape preserves the exact session, draft answer, and question. Expand changes the presentation without restarting. Practice is ungraded and never changes your account's schedule.

## Offline behavior and recovery

Subject text is cached for your accessible levels. Media is downloaded incrementally, with up to 40 new assets per sync and a configurable disk limit. Image-only radicals require their image before they can be quizzed. Audio availability is shown explicitly.

Cached lessons and due reviews work offline. Completed work stays pending until confirmed. A pending subject cannot enter another graded cycle, and subsequent scheduling/unlocks wait for WaniKani's response. Subscription access and known expiry dates still apply offline.

The API does not provide idempotency keys or retrievable individual review history. A timed-out submission is **uncertain**, never automatically retried. Refresh reconciles it against remote progress. When another client has changed the assignment, its state wins and the local answer remains recorded. Settings lets you keep remote progress and archive an unresolved local result. This recovery path deliberately offers no force-resubmit button.

Activity charts show only completed subjects and practice recorded by this plugin. They do not reconstruct your all-device review history.

## Desktop behavior

The bar shows due items, pending work, or the next-review countdown. Notifications are coalesced, with a default two-hour minimum and quiet hours of 22:00–08:00. They respect Do Not Disturb, lock, vacation, and study. Suppressed reminders are not replayed later.

Desktop and idle kanji displays are optional. They show learned subjects not due in the next day, stop on activity/fullscreen/study/lock, and give way before Omarchy's configured screensaver deadline. The plugin never owns or changes your system lock. Companion animation and reduced motion have separate controls.

## Your data

- State: `${XDG_STATE_HOME:-~/.local/state}/omarchy/wanikani/`
- Separate `account.sqlite3` and `demo.sqlite3`; demo results never reach WaniKani.
- Media is disposable; sessions, drafts, and pending submissions are durable SQLite transactions.
- Settings can disconnect, clear media, export redacted diagnostics, or explicitly remove local data. Deletion requires separate acknowledgment for unresolved work.
- No token is stored in source, shell.json, command arguments, or diagnostics.

## Update and remove

Use `omarchy plugin update io.github.lostandadrift.wanikani` for Git-installed copies. Plugin source contains no generated state.

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

See [verification](docs/VERIFICATION.md), [architecture](docs/ARCHITECTURE.md), and [implementation checkpoint](docs/IMPLEMENTATION.md). Automated tests use authored fixtures and mock API responses, never real graded submissions. WanaKana is bundled with its MIT notice; no npm installation is needed.

The release gate includes two weeks of personal daily use, checks across desktop configurations, and deliberately answered live lessons/reviews. Those are not replaced by passing automated tests.
