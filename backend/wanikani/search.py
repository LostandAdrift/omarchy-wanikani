"""Ranked local catalogue lookup; query text is never persisted or transmitted."""
import unicodedata

from .common import UserError, stamp


KINDS = ("radical", "kanji", "vocabulary", "kana_vocabulary")
STATES = ("all", "learned", "due", "saved")


def fold(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in value)


def lookup(engine, text, limit=30, filters=None, reading_query=None):
    query = fold(str(text)[:256])
    kana = fold(str(reading_query or "")[:256])
    # The optional frontend conversion is only a reading search hint. It never
    # replaces the original English meaning query or participates in grading.
    if not kana or any(not ("ぁ" <= c <= "ゖ" or c in "ーゝゞ") for c in kana):
        kana = query
    filters = filters or {}
    if not isinstance(filters, dict):
        raise UserError("Choose a valid catalogue filter.")
    kind, state = filters.get("type", "all"), filters.get("state", "all")
    if kind not in ("all",) + KINDS or state not in STATES:
        raise UserError("Choose a valid catalogue filter.")
    if not query and kind == "all" and state == "all":
        return []
    try:
        limit = max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        raise UserError("Choose a valid result limit.") from None
    values = {"query": query, "kana": kana, "type": kind, "state": state,
        "level": engine.max_level(), "now": stamp(engine.now()), "limit": limit}
    # Catalogue text was folded transactionally at ingestion. Rank BEFORE
    # limiting the catalogue, and join authoritative rows for access/status. This
    # prevents an exact match disappearing behind 150 earlier partial matches.
    # instr is literal; percent/underscore/backslash never become wildcards.
    with engine.store.lock:
        rows = engine.store.rows("""
          WITH entries AS (
            SELECT s.id, s.kind, document.characters, document.meanings, document.readings,
              json_extract(a.body,'$.data.started_at') AS started_at,
              json_extract(a.body,'$.data.burned_at') AS burned_at,
              json_extract(a.body,'$.data.available_at') AS available_at,
              COALESCE(json_extract(a.body,'$.data.hidden'),0) AS assignment_hidden,
              CASE WHEN d.body IS NOT NULL AND json_type(d.body)!='null' THEN
                CASE WHEN json_type(d.body,'$.meaning_synonyms')='array'
                  THEN json_extract(d.body,'$.meaning_synonyms') ELSE '[]' END
                ELSE CASE WHEN json_type(m.body,'$.data.meaning_synonyms')='array'
                  THEN json_extract(m.body,'$.data.meaning_synonyms') ELSE '[]' END END AS synonyms
            FROM resources s INDEXED BY resource_search_identity
            JOIN search_documents document ON document.kind=s.kind AND document.id=s.id
            LEFT JOIN resources a ON :state IN ('learned','due') AND a.kind='assignment'
              AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
            LEFT JOIN resources m ON m.kind='study_material'
              AND CAST(json_extract(m.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
            LEFT JOIN meta d ON d.key='material_draft_' || s.id
            WHERE s.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
              AND json_extract(s.body,'$.data.hidden_at') IS NULL
              AND json_extract(s.body,'$.data.level')<=:level
              AND (:type='all' OR s.kind=:type)
          ), matched AS MATERIALIZED (
            SELECT *,
              COALESCE((SELECT MIN(CASE WHEN value=:query THEN 1 ELSE 5 END)
                FROM json_each(entries.meanings)
                WHERE type='text' AND instr(value,:query)>0),99) AS meaning_rank,
              COALESCE((SELECT MIN(CASE WHEN value IN (:query,:kana) THEN 2 ELSE 6 END)
                FROM json_each(entries.readings)
                WHERE type='text' AND (instr(value,:query)>0 OR instr(value,:kana)>0)),99) AS reading_rank,
              COALESCE((SELECT MIN(CASE WHEN wk_fold(value)=:query THEN 1 ELSE 5 END)
                FROM json_each(entries.synonyms) WHERE type='text' AND instr(wk_fold(value),:query)>0),99) AS synonym_rank,
              CASE WHEN :state='saved' THEN EXISTS(
                SELECT 1 FROM json_each(COALESCE((SELECT body FROM meta WHERE key='pinned_subjects'),'[]'))
                WHERE CAST(value AS INTEGER)=CAST(entries.id AS INTEGER)) ELSE 0 END AS pinned,
              CASE WHEN :state='due' THEN EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(entries.id AS INTEGER)
                AND o.kind IN ('review','lesson') AND o.state IN ('pending','inflight','uncertain','blocked','conflicted')) ELSE 0 END AS pending
            FROM entries
          ), ranked AS (
            SELECT *, MIN(meaning_rank, reading_rank, synonym_rank,
              CASE WHEN characters=:query THEN 0
                WHEN length(characters)>0 AND instr(:query,characters)>0 THEN 3
                WHEN instr(characters,:query)>0 THEN 4 ELSE 99 END) AS rank
            FROM matched
          )
          SELECT id, rank, pending FROM ranked
          WHERE (:query='' OR rank<99)
            AND (:state='all' OR (:state='saved' AND pinned)
              OR (:state='learned' AND started_at IS NOT NULL AND assignment_hidden=0)
              OR (:state='due' AND started_at IS NOT NULL AND burned_at IS NULL
                AND assignment_hidden=0 AND julianday(available_at)<=julianday(:now) AND NOT pending))
          ORDER BY rank, CASE WHEN :query='' THEN 0 ELSE -length(characters) END,
            CASE kind WHEN 'vocabulary' THEN 0 WHEN 'kana_vocabulary' THEN 1 WHEN 'kanji' THEN 2 ELSE 3 END,
            CAST(id AS INTEGER)
          LIMIT :limit
        """, values)
        pending_subjects = {row[0] for row in engine.store.rows("""SELECT subject_id FROM outbox
          WHERE kind IN ('review','lesson') AND state IN ('pending','inflight','uncertain','blocked','conflicted')""")}
        result = []
        for row in rows:
            detail = engine.details(int(row["id"]), False)
            detail["pending"] = int(row["id"]) in pending_subjects
            detail["match"] = "exact" if row["rank"] <= 2 else "in_selection" if row["rank"] == 3 else "related"
            result.append(detail)
        return result
