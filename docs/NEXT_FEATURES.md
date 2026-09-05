# What comes next

The current implementation covers the original native study workflow and adds a practice library, batch recaps, kanji comparisons, personal notes in lessons and feedback, a selectable review forecast, and quiet recall. The next iteration should deepen the learning experience while preserving the short-session habit.

These are proposed features, not shipped capabilities. Live-account qualification and the two-week daily-use log remain the immediate release work.

## 1. A reading trail from your desktop

Turn an explicitly selected Japanese passage into a small local reading trail. Show the original passage with matching WaniKani words highlighted; selecting a word opens its cached subject and learning status. Let the learner save unfamiliar matches to a practice selection without leaving the passage.

- Match Unicode text locally against the accessible catalogue, retaining source offsets and overlapping candidates. Do not imply that the catalogue is a complete Japanese dictionary or report a misleading whole-language comprehension percentage.
- Show why a word matched, distinguish kanji recognition from vocabulary recognition, and preserve the original text exactly. No OCR, translation request, or continuous clipboard monitoring.
- Reuse the existing guarded practice-selection contract. Hide answers belonging to unfinished graded work. Clear passage and detail caches on account/access changes.
- Acceptance: long selections remain usable, overlapping vocabulary can be chosen deliberately, one-click lookup returns to the same passage, and the entire feature works offline with no external text transmission.

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

First use the installed client for deliberate real lessons and reviews and record any recovery or desktop interference. Fix those observed issues before starting a larger feature. Then build the reading trail as the strongest new desktop demonstration, followed by contrast practice and the lesson path. Keep performance checks focused on any new user-visible delay; avoid spending the iteration on measurements when the learning UI needs attention.
