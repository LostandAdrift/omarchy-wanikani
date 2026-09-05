# SRS Explorer backend

The Explorer turns cached current SRS groups into subject lists across accessible levels. It reuses the Progress distribution's canonical assignment classification. Confirmed Apprentice/Guru/etc. retention is separate from first passing, level-up progress, local practice results and pending submissions. No level-up or burn date is predicted.

This document specifies the implemented read-only backend. Native tabs, category buttons and navigation are integrated separately; this file does not claim hosted UI verification.

## Interface

```python
catalogue(engine, group="apprentice", subject_type=None, level=None,
          stage=None, order="level", offset=0, limit=24)
guarded_details(engine, subject_id)
```

Suggested worker routes are `srs_catalogue` and `progress_details`. Requests accept only the named catalogue arguments, or exactly `{subject_id}` for details. Unknown worker keys must be rejected by the adapter. Groups are `locked`, `lessons`, `apprentice`, `guru`, `master`, `enlightened`, `burned` and `unknown`. Subject type is null or radical/kanji/vocabulary/kana_vocabulary. Level is null (all accessible levels) or an accessible integer 1–60. Stage is null or a numeric stage belonging to the group: Apprentice 1–4, Guru 5–6, Master 7, Enlightened 8, Burned 9. Stage zero is not a selectable refinement. Order is `level` or `next_review`; offset is 0–12,000, page size 1–60. Booleans do not count as integers.

The page includes:

- Echoed filters, `offset`, `limit`, `total`, `has_more`, `next_offset`.
- `total_complete`: the bounded metadata window has no missing/ambiguous identities. `complete` additionally requires valid known assignment states, collection markers and a complete page projection. A missing sync cursor is partial cached progress, not zero account progress.
- `protection_complete`: every unfinished graded queue could be checked. If false, all automatic cards have their answers hidden and opening disabled.
- `items`: existing Progress cards (`id`, `type`, `level`, `characters`, `meaning`, `can_open`, `spoilers_hidden`, `status`). Prerequisite arrays are empty; this list does not expand the level-board graph.
- `levels:[{level,count}]`, filtered by group/type/stage before the exact level filter.
- `stages:[{stage,label,count}]`, filtered by group/type/level before the exact stage filter. Applicable zero-count stages remain present; labels include the exact Apprentice/Guru substage.
- `last_sync`, `source:"cached_wanikani"` and an explicit confirmed-assignment scope label.

## Interpretation and bounds

At most 12,001 scalar metadata rows are projected through existing numeric identity and assignment indexes. The first 12,000 are classified with `progress._status`, filtered and sorted before pagination. Only the selected page projects bounded characters/meaning content; no full subject, mnemonic, personal note or audio body is read for list rendering. There is no new persistent index, cache or schema migration.

Next-review sorting uses only a valid cached assignment date, with undated subjects last and stable level/ID/type ties. Pending/attention overlays do not advance subjects into an anticipated SRS group. The UI should show the waiting/attention label and explain that new scheduling follows server confirmation. First passing can remain recorded while a subject is currently Apprentice.

A valid burned timestamp establishes the canonical Burned group even if its cached numeric stage disagrees. The original stage and date remain unchanged, exact-stage facets count only their actual stages, and `complete` becomes false. The Explorer never manufactures stage 9 to hide an inconsistent cache or to make facet counts match the whole group.

Counters include protected subjects, but their meaning and prerequisite answers stay hidden and their open controls are disabled. All unfinished saved graded sessions and matching glyph aliases are checked independently of list pagination. Deliberate manual Lookup retains its existing policy.

`guarded_details` separately validates cached account identity, current subscription access, assignment identity, graded IDs and glyph aliases under one Store lock before asking Engine for the ordinary detail projection. A list's earlier `can_open` flag cannot authorize a later reveal. Expired/mismatched accounts and malformed protection fail closed. Cached authenticated account data remains useful offline; a connected network is not required. Demo data uses its explicit isolated mode.

That same strict unfinished-session protection filters the returned components, related subjects and comparison cards. In particular, malformed truthy completion flags do not release those automatic answers. The manual Lookup projection and its policy remain unchanged.

## Native integration contract

Use a dedicated Explorer component. Category buttons should have native keyboard activation and visible focus. Preserve group/type/level/substage/page when returning from details. Do not fetch the catalogue-wide Progress overview again for every page change in the same cache context. A new account/sync/access/reset/protection generation invalidates content immediately. Hidden, closed, locked and unready views perform no work; only the owning request generation may clear a loading flag.

No endpoint edits assignments, sessions, pending submissions, local history or private material. Fixture verification covers classification parity, filters/facets before pagination, partial caches, pending work, protection/access races, malformed rows and bounded page-only content projection. Live account and native visual qualification are separate gates.

## Backend verification

The 21 Explorer cases, 22 existing Progress cases and 13 worker adapter cases pass together. The fixtures verify a duplicate identity spanning the catalogue limit, a real threaded account-change barrier during detail projection, guarded relationship/comparison answers, inconsistent Burned facets, unchanged SQLite write counts, and page-only bounded content queries using the existing `resource_search_identity` and `resource_subject` indexes. No performance campaign or live-account interaction was used for these checks.

```sh
PYTHONPATH=backend:tests python3 -B -m unittest test_srs_explorer test_learning_progress test_srs_worker -v
```
