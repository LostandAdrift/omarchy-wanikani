# What comes next

The daily-use feedback reprioritized the next iteration around audible pronunciation, explicit reviews versus lessons, meaningful level progress, audio-led listening practice, periodic study reminders, and live support for every Omarchy theme. Follow [the learning upgrade plan](LEARNING_UPGRADE_PLAN.md) first. Listening and study rhythm are now core deliverables; the exploratory extensions below remain later proposals.

The current implementation covers the original native study workflow and adds a practice library, batch recaps, kanji comparisons, personal notes in lessons and feedback, a selectable review forecast, quiet recall, and a local reading trail. The next iteration should deepen the learning experience while preserving the short-session habit.

The first reading-trail edition below is implemented; the extensions and other directions remain proposals. Live-account qualification and the two-week daily-use log remain the immediate release work.

## 1. A reading trail from your desktop

The first edition turns an explicitly selected Japanese passage into a small local reading trail. It shows the original passage with matching WaniKani words highlighted; selecting a word opens its cached subject and learning status. It preserves exact text, supports overlapping alternatives, follows the theme, and returns to the same passage. A useful next step is letting the learner save unfamiliar matches to a practice selection without leaving the passage.

- Match Unicode text locally against the accessible catalogue, retaining source offsets and overlapping candidates. Do not imply that the catalogue is a complete Japanese dictionary or report a misleading whole-language comprehension percentage.
- Show why a word matched, distinguish kanji recognition from vocabulary recognition, and preserve the original text exactly. No OCR, translation request, or continuous clipboard monitoring.
- Reuse the existing guarded practice-selection contract. Hide answers belonging to unfinished graded work. Clear passage and detail caches on account/access changes.
- Implemented acceptance: selections up to 256 code points remain exact, overlapping vocabulary can be chosen deliberately, one-click lookup returns to the same passage, and the feature works offline with no external text transmission. The next acceptance gate is an explicit up-to-20-word practice selection with exact paused-session preservation.

## 2. Contrast practice for confusing kanji

Extend **Tell them apart** into an optional ungraded contrast session. Start with two accessible, cached kanji the learner chooses; alternate ordinary meaning/reading prompts and offer the comparison only after checking. A small personal distinction cue can help the learner remember the stroke or component that matters.

- Keep comparisons based on recorded relationships or an explicit user-selected pair. Do not invent authoritative stroke explanations from glyph appearance.
- Keep contrast mistakes local and separate from WaniKani progress. Preserve the exact paused graded session, its draft, and its error counts.
- Personal distinction cues stay local unless the learner explicitly chooses to save one into synchronized study notes.
- Acceptance: no pre-answer comparison spoilers, no graded submission, accessible side-by-side cards at narrow widths, and exact resume across closing/restart.

## 3. A lesson path you can see

Make subject relationships easier to understand through a small visual path: components → the current kanji → vocabulary that uses it. Keep large Japanese glyphs and a readable text alternative. Expand only the branch the learner chooses so a lesson remains focused.

- Use the cached component and amalgamation links already returned by WaniKani, applying current account access at every step.
- Open related content in a temporary inspector that returns to the same lesson position. A relationship must not replace or finish the study session.
- Do not show an unfinished review's hidden answer through the graph. Label unavailable content without downloading beyond account access.
- Acceptance: keyboard traversal, exact return to the lesson, no recursive catalogue loading, and useful behavior with missing or image-only radicals.

## Release order

Follow passes A–E in the learning upgrade plan: fix mode clarity and pronunciation, build useful progress, add listening and study rhythm, then deepen lessons and other practice. Apply theme and interaction polish throughout. Use deliberate real sessions to record recovery or desktop interference, and fix observed issues promptly. Reading-trail extensions follow those priorities. Keep performance checks focused on new visible delay; avoid spending the iteration on measurements when the learning UI needs attention.
