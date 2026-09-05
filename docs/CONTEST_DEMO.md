# Contest demonstration · about three minutes

Demonstrate the development release with its authored sample catalogue. Say “demo account” and “simulated offline” aloud, and keep the status labels visible. No account token or real review submission is needed. Check the current competition's published rules and deadline before recording a final submission.

## Prepare

Use the installed plugin and a normal desktop with an editor open. Start the demo:

```sh
omarchy-shell wanikani demo true
omarchy-shell wanikani settings
```

In Settings, choose **Reset demo progress** to prepare a fresh, five-subject queue. This discards only the demo's sessions, pending results, and preferences. Leave **Simulate offline in demo** off initially. Enable **Companion animation** and **Learned-kanji card on the desktop**. Keep **Reduce motion** on if preferred; the same workflow works without animation.

Record your current theme and choose a second installed theme:

```sh
wanikani_demo_theme=$(omarchy theme current)
omarchy theme list
```

Keep that terminal open for restoring the theme. Prepare the text `山` in the editor. The following are the authored demo answers; question order is shuffled:

| Subject | Meaning | Reading |
|---|---|---|
| 一 · radical | ground | No reading question |
| 山 · kanji | mountain | さん, entered as `san` |
| 川 · kanji | river | かわ, entered as `kawa` |
| 水 · vocabulary | water | みず, entered as `mizu` |
| ありがとう · kana vocabulary | thank you | No reading question |

## Record

1. **Start small, return to work · 0:00–0:35.** Click the crab to reveal the dashboard and its five due subjects. Start five reviews. Type a partial answer, press **Escape**, and type a few words in the editor. Press **Super+Alt+W** to resume the exact question and partial answer. Finish that subject with **Enter** to check and **Enter** to acknowledge feedback. Show **Expand**, then **Compact**, without changing the session.

2. **Save work offline · 0:35–1:30.** Open Settings and click **Simulate offline in demo**. This changes the demo-only `demo_offline` setting; it does not disable networking. Resume study and deliberately answer the remaining four subjects. Acknowledge every final feedback screen. Show the five-subject summary and the pending count. Say: “Each answer is saved locally; pending work cannot start another graded cycle.” Return to the editor with **Escape**.

3. **Look up from anywhere · 1:30–1:55.** Select `山` in the editor and press **Super+Alt+Shift+W**. Show the local matches, reading, meaning, and learning status. If the editor does not provide a primary selection, copy `山` first; lookup falls back to the clipboard. Lookup reads text only on this invocation. Press **Escape** to return.

4. **Follow the desktop theme · 1:55–2:15.** Open the dashboard. In the prepared terminal, apply the second theme using its exact name from the earlier list:

   ```sh
   omarchy theme set "Tokyo Night"
   ```

   Substitute another installed theme if Tokyo Night is already active or unavailable. Reopen the dashboard if needed and show its changed colors alongside the bar. No plugin-specific palette is selected.

5. **Confirm queued work · 2:15–2:35.** Open Settings and click **Reconnect demo & sync**. Show the pending count returning to zero and the dashboard's updated schedule. Say: “This is a fixture simulation. The live client reconciles account changes before sending, and keeps a lost-response write uncertain instead of blindly retrying it.”

6. **Let the desktop breathe · 2:35–3:00.** Press **Escape**, leave the pointer and keyboard still for ten seconds, and reveal the learned-kanji desktop card and crab. Activity dismisses the card. Open the gallery:

   ```sh
   omarchy-shell wanikani zen
   ```

   Finish with “Five reviews, then back to work.” If showing the automatic idle gallery, enable it in Settings and record the real idle interval as a separate optional shot. It closes before the existing screensaver deadline; do not change the machine's lock settings for the recording.

## Restore

In the same terminal, restore the starting theme:

```sh
omarchy theme set "$wanikani_demo_theme"
```

Leave simulated offline mode off and restore any ambient or motion preferences changed for the demonstration. The demo can remain available for exploration. To return to an already connected account, use `omarchy-shell wanikani demo false`.

This demonstration does not certify live-account reliability, cached audio, or the two-week daily-use release gate. Report those separately in the release notes once completed.

## Optional learning-feature cut

For a longer walkthrough, select `山が見えます。火山と山。` and invoke Lookup. Show **Words in your selection**, follow the mountain link, and return to the unchanged passage. The linked text follows the current theme; the trail uses the local WaniKani catalogue. After the five-review demo batch is complete, a freshly reset demo also provides a mountain/river comparison under **Tell them apart**. In Zen, choose **Quiet recall**, pause on the concealed word, then choose **Reveal** and **Next word**. These are learning aids; no extra graded work is submitted. Keep the authored-demo label visible.

## Rules recheck — September 4, 2026 Pacific

The [official news index](https://omarchy.org/news/) and [August 28 competition announcement](https://omarchy.org/news/2026/08/the-first-plugin-competition-winners/) were rechecked during implementation. They still announce future competitions without a next deadline. The [publishing guide](https://plugins.omarchy.org/publish.html) currently requires a public GitHub repository, valid root manifest, README/license, and safe install/removal before listing submission. This repository remains local and unsubmitted.
