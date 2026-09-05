# Hear a kanji in vocabulary

Kanji reading and context steps offer **Show vocabulary recordings**. The same control appears after non-retry reading feedback and in a deliberately opened kanji detail. It never opens or plays automatically.

Each example is an original recording of a **whole vocabulary word** containing the kanji. Its complete written word, pronunciation and meaning stay together. A recording does not isolate a kanji sound, assign individual mora to characters, or claim to demonstrate every reading. A different downloaded voice can have a different accepted pronunciation; the displayed playback reading follows the clip actually selected.

Up to three examples are shown from a bounded check of the kanji's authoritative related-vocabulary links. Cached recordings and already learned words are preferred. An accessible word that has not been learned can still help introduce a new kanji; its card says **Vocabulary preview · not learned yet**. Preview and playback do not start that word's lesson or affect any learning schedule.

**Play whole word** uses the existing player and one-clip download path. It has loading, retry, offline availability, replay and stop states. Collapse, close, lock, account changes and navigation invalidate outstanding callbacks and stop this panel's recording. They do not start replacement audio. Unrelated status refreshes preserve the disclosed panel.

## Graded study protection

Automatic example selection excludes unfinished graded subjects, matching written aliases, protected whole-word readings and recording pronunciations, and unresolved graded submissions. Missing or malformed protection information withholds examples. Current subscription access, subject visibility and the relationship are checked before selection and again around media preparation.

While a kanji's reading is already visible in study, only that exact active occurrence in its saved queue is exempt from protection. Another unfinished graded occurrence or an unresolved graded submission for the parent withholds all of its suggested recordings. Ordinary kanji details receive no study exemption. The worker validates the exact session and revision; the UI cannot authorize an example by passing a vocabulary ID alone.

These examples are a read-only learning aid. They create no grade, answer correction, listening exposure, rating, assignment start or outbox operation. Closing does not modify the current lesson or review position.

## Worker interface

`kanji_examples` accepts `parent_subject_id` and `context` (`study` or `details`). Study also requires `session_id` and `revision`; details must not supply them. The bounded response contains `parent_subject_id`, `status`, `examples`, `complete` and `reason`. Each example has `subject_id`, `characters`, `pronunciation`, `meaning`, `learned` and `cached`.

`pronunciation` and `pronunciation_prepare` accept `context: "kanji_example"`, the vocabulary `subject_id`, `parent_subject_id`, and `origin_context`, with study identity fields only for a study origin. The existing optional `voice_actor_id` applies. A ready result's `example` describes the actual selected clip and its parent. These are private panel-to-worker operations; the agent helper does not expose an audio-playback command.

Automated verification uses independently authored subjects, local fixture clips, mock media transport and offscreen controls. Audible Japanese playback and hosted desktop interaction still require qualification on an unlocked desktop.
