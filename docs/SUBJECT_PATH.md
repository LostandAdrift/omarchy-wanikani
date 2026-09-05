# How this subject connects

`qml/SubjectPath.qml` presents relationships already supplied with a subject. It is integrated into the current `SubjectDetails` source for the next development milestone, replacing the Made from and Related subjects button rows. This change is not installed on the desktop yet. It does not implement the later temporary lesson inspector, change a lesson step, navigate a study queue, or provide a complete Japanese dependency graph.

The collapsed disclosure shows how many components and related subjects are available in this view. Opening it presents components above the current subject, then related subjects below, with labeled downward arrows. Four cards per group appear initially; an explicit Show all control reveals up to thirty supplied rows. Read-only lessons use ordinary readable cards rather than disabled buttons.

Group labels follow supported WaniKani relationships: radicals in a kanji, kanji in a vocabulary word, kanji using a radical, or words using a kanji. Unsupported or unspecified combinations use Components and Related subjects. The component adds no stroke explanation, etymology, prerequisite inference, unlock date or comprehension claim.

## Input and disclosure contract

The component takes `subject`, `showMeaning`, `showReading`, `editable`, and `openEnabled`. `expanded` defaults to false. Subject or answer-visibility changes collapse the path and its group disclosures. No diagram is shown when there are no permitted projected relatives.

The current subject uses its supplied ID, type, characters, accepted meanings and accepted readings. Each relative uses only its projected positive safe integer `id`, `characters` and primary `meaning`. The existing backend projection does not include relatives' recordings, images or readings. Duplicate, invalid and self-referential rows are omitted; input is bounded to the projection's first thirty rows per group. Display text preserves whole Unicode code points and renders markup literally.

Counts describe this filtered projection. The backend may have excluded inaccessible, uncached or protected subjects and capped the original relation IDs; no completeness metadata is available here. A zero count does not establish that the subject has no relationships on WaniKani. This is a partial view of cached account content, not a replacement catalogue or an independent access check.

Meaning labels are created only when `showMeaning` is true. Current-subject reading labels are created only when `showReading` is true. Inactive loaders keep concealed answer labels out of the object tree. As in the current relationship presentation, upstream components require meaning visibility, and downstream subjects require both meaning and reading visibility. If the only permitted relation groups are empty, the entire disclosure is absent.

## Optional navigation

`editable` and `openEnabled` both default to false. A relative's Open button exists only when both are true and both answer parts are exposed. Activation rechecks that the requested ID still belongs to the current eligible projection and that the component is visible and expanded, then emits `requestSubject(id)`. The current-subject card does not offer a redundant Open action.

The component itself has no controller imports, backend calls, clipboard reads, media operations, timers, continuous animations or network requests. The caller owns any later navigation and its current account/access/graded-work checks. Opening the disclosure itself emits no subject request. Lesson read-only use has no subject-navigation actions, even though the disclosure remains keyboard accessible.

`SubjectDetails` shows the path only in its all-content or Context section, using its existing meaning/reading visibility flags. It enables Open only for an editable view whose panel is open and service is ready and unlocked. The signal uses the existing `Panel.showSubject` route, preserving ordinary lookup navigation and the guarded detail route when the user arrived from Progress. Changing the selected subject collapses the path. No lesson action, grade, queue change, note edit or pronunciation request occurs when a learner expands it.

## Native presentation and fallback

The path uses the existing native Action, Label, Card and JapaneseText components with live theme bindings. Meaning and Japanese text use contrast-aware surface roles; arrows also have spoken text alternatives. Native Enter/Space activation and visible focus work on disclosure and explicitly enabled Open controls. The disclosure exposes native accessibility checkable/checked state, alongside its available-group counts. The two-column related cards wrap at 290px width, and longer meanings and glyphs wrap or fit their cards.

This edition deliberately renders no images. An image-only radical is labeled Image radical; an unavailable relative glyph gets an explicit Glyph unavailable placeholder. Neither pretends that a generic diamond is the actual radical. It does not infer or fetch a missing picture, use a remote image URL, or play audio. Existing radical rendering elsewhere remains the source of the real cached image.

`tests/test_subject_path.py` exercises the production component and installed native Button with inert shell/theme adapters. Coverage includes the empty/collapsed path, concealment without instantiated labels, malformed/bounded rows, stale-ID activation guards, explicit read-only behavior, native Qt keyboard events, literal markup, supplementary Japanese characters and narrow geometry across the installed stock palettes plus authored low-contrast colors. These are component/offscreen checks, not hosted desktop or screen-reader speech qualification.

The integrated fixture in `tests/test_subject_path_integration.py` copies the actual Study, SubjectDetails and SubjectPath components plus the production `Panel.showSubject` method. It checks read-only lesson Context, answer concealment, explicit lookup navigation, Progress-origin navigation, stale access replies, closed/locked/unready guards, and large safe integer IDs without truncation. Its light/dark layout checks use a 290px component. Related editor, pronunciation, lifecycle and theme fixtures also include the real path dependency. Offscreen integrated Context captures have source SHA-256 provenance; their neutral shell adapters and authored examples do not establish installed-shell or live-account behavior.
