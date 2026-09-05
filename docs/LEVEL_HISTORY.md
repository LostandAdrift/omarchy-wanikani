# Your path through the levels

Open **Progress → Level history** for a timeline of cached account milestones. **Subjects & unlocks** returns to the level board with its chosen level, type and page preserved. History reads only when its tab is open. Refresh history rereads the local cache; the existing **Refresh account** action synchronizes it with WaniKani.

Each recorded visit remains separate, including visits to the same level after a reset. Expand **Show dates** for the unlock, first lesson, passing, all-subjects-burned and ended-visit timestamps. Passing the level and burning every assignment are different milestones. The API may lack older records even when synchronization is complete. These meanings and the historical limitation follow the [WaniKani level-progression reference](https://docs.api.wanikani.com/20170710/#level-progressions).

The duration begins at the recorded unlock and ends at passing, or at the end of an unpassed visit. Only a verified latest unfinished visit for the current account level can show time through the current check. Later reset records, incomplete synchronization, uncertain clocks and ambiguous dates prevent an old unfinished visit from growing indefinitely.

Durations are elapsed calendar time, including vacation and breaks. Bars scale to the longest visit on the displayed page, and each label identifies its endpoint. There is no completion forecast. Missing, future, malformed or out-of-order dates remain unknown; the UI explains incomplete records and does not invent durations.

## Scope and private state

This is account-level metadata supplied by WaniKani, separate from **Activity**, which records work done in this client. It does not reconstruct individual review history from another app. Recorded milestones above a reset level or a later subscription content limit remain visible as historical account metadata; this view exposes no subject content, answers, notes or credentials.

Pages contain twelve visits. The backend uses the existing resource index to inspect at most 1,001 projected rows, then orders up to 1,000 records by their validated dates. A larger history is explicitly a limited window selected by resource IDs, not a claim to contain every chronologically latest visit. “Recorded visit N” counts only the available window and stays consistent across its pages.

The read-only worker method `level_history` accepts only integer `offset` and `limit` (1–50). Its response distinguishes local `cache_complete` from `history_complete`, which is always false. `unavailable` has no confident count. No history request creates a session, a grade, a submission, a media check or an API job. Stale replies after closing, account changes or worker replacement cannot populate the reopened view.

Fresh demos include six independently authored visits to illustrate progress and a reset. Existing demo databases are preserved; the user can explicitly reset the demo to see the new fixture. The native client installation never changes a live account to create demonstration history.

Verification uses authored metadata, indexed-query and database-preservation checks, actual offscreen controls, keyboard navigation and installed stock palettes. Hosted scrolling, physical input and daily use still require qualification.
