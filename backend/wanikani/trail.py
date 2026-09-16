"""Exact, read-only catalogue links within a short passage of original text.

No query, answer, or session state is written. The response contains glyphs and
plain account status only. A partial catalogue/match budget is explicitly
reported; omitted material stays in the passage as unchanged, unlinked text.
"""
import json
import unicodedata

from .common import UserError, epoch, session_queue_limit


MAX_TEXT = 256
MAX_SUBJECTS = 12000
MAX_MATCHES = 60
MAX_SESSIONS = 128
CONTENT_BATCH = 128
TYPE_ORDER = {"vocabulary": 0, "kana_vocabulary": 1, "kanji": 2}


def _protected(engine):
    rows = engine.store.rows("""SELECT json_extract(body,'$.queue') AS queue,json_type(body,'$.queue') AS queue_type,
        json_extract(body,'$.mode') AS mode,json_type(body,'$.all_reviews') AS all_reviews
      FROM sessions INDEXED BY sessions_unfinished_graded
      WHERE json_extract(body,'$.phase')!='complete'
        AND json_extract(body,'$.mode')!='practice' LIMIT ?""", (MAX_SESSIONS + 1,))
    if len(rows) > MAX_SESSIONS:
        return None
    protected = set()
    for row in rows:
        if row["queue_type"] != "array":
            return None
        queue = json.loads(row["queue"])
        # All-due reviews protect their entire frozen stack, including entries
        # beyond the first batch. Unmarked oversized records still fail closed.
        limit = session_queue_limit({"mode": row["mode"], "all_reviews": row["all_reviews"] == "true"})
        if not isinstance(queue, list) or len(queue) > limit:
            return None
        for item in queue:
            if not isinstance(item, dict) or type(item.get("subject_id")) is not int:
                return None
            if item.get("done") is not True:
                protected.add(item["subject_id"])
    return protected


def _positions(text, characters):
    start = text.find(characters)
    while start >= 0:
        end = start + len(characters)
        # Keep combining marks and joined glyph sequences with their base.
        # We never normalize either string to manufacture a catalogue match.
        starts_glyph = not unicodedata.category(text[start]).startswith("M") and (not start or text[start - 1] != "\u200d")
        ends_glyph = end == len(text) or (not unicodedata.category(text[end]).startswith("M") and text[end] != "\u200d")
        if starts_glyph and ends_glyph:
            yield start
        start = text.find(characters, start + 1)


def _protected_characters(engine, protected, maximum, text_length):
    # A protected vocabulary record may sit beyond the catalogue budget while
    # its kanji alias is inside it. Resolve protection independently, still
    # bounded by the unfinished-session and twenty-subject queue limits.
    characters = set()
    ids = sorted(protected)
    for offset in range(0, len(ids), CONTENT_BATCH):
        batch = ids[offset:offset + CONTENT_BATCH]
        placeholders = ",".join("?" for _ in batch)
        rows = engine.store.rows(f"""SELECT json_extract(body,'$.data.characters') AS characters
          FROM resources INDEXED BY resource_numeric_id
          WHERE kind IN ('kanji','vocabulary','kana_vocabulary')
            AND CAST(id AS INTEGER) IN ({placeholders})
            AND json_type(body,'$.id')='integer' AND json_extract(body,'$.id')=CAST(id AS INTEGER)
            AND json_extract(body,'$.object')=kind
            AND json_type(body,'$.data.level')='integer'
            AND json_extract(body,'$.data.level') BETWEEN 1 AND ?
            AND json_extract(body,'$.data.hidden_at') IS NULL
            AND json_type(body,'$.data.characters')='text'
            AND length(json_extract(body,'$.data.characters')) BETWEEN 1 AND ?""",
            batch + [maximum, text_length])
        characters.update(row["characters"] for row in rows)
    return characters


def reading_trail(engine, text=""):
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise UserError("Use a passage of at most 256 characters.")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
        raise UserError("Use valid Unicode text for the reading trail.")
    result = {"text": text, "segments": [{"text": text, "subject_ids": []}] if text else [],
        "matches": [], "truncated": False}
    if not text:
        return result
    with engine.store.lock:
        maximum = engine.max_level()
        protected = _protected(engine)
        if protected is None:
            result["truncated"] = True
            return result
        # The covered metadata pass limits hydration even when the cache is
        # unexpectedly large. Raw character strings are required: folded search
        # documents could change codepoints and lose exact substring boundaries.
        identities = engine.store.rows("""SELECT kind,id FROM resources INDEXED BY resource_search_identity
          WHERE kind IN ('radical','kanji','vocabulary','kana_vocabulary') AND kind!='radical'
            AND json_type(body,'$.data.level')='integer'
            AND json_extract(body,'$.data.level') BETWEEN 1 AND ?
            AND json_extract(body,'$.data.hidden_at') IS NULL
          ORDER BY kind,CAST(id AS INTEGER),id LIMIT ?""", (maximum, MAX_SUBJECTS + 1))
        result["truncated"] = len(identities) > MAX_SUBJECTS
        candidates = []
        protected_characters = _protected_characters(engine, protected, maximum, len(text))
        for offset in range(0, min(len(identities), MAX_SUBJECTS), CONTENT_BATCH):
            batch = identities[offset:min(offset + CONTENT_BATCH, MAX_SUBJECTS)]
            placeholders = ",".join("?" for _ in batch)
            rows = engine.store.rows(f"""SELECT CAST(s.id AS INTEGER) AS id,s.kind AS type,
                json_extract(s.body,'$.data.characters') AS characters,
                json_extract(s.body,'$.data.level') AS level,
                (SELECT json_extract(a.body,'$.data.started_at') FROM resources a
                  WHERE a.kind='assignment' AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
                  ORDER BY a.id LIMIT 1) AS started_at
              FROM resources s WHERE s.kind IN ('kanji','vocabulary','kana_vocabulary')
                AND s.id IN ({placeholders})
                AND json_type(s.body,'$.id')='integer' AND json_extract(s.body,'$.id')=CAST(s.id AS INTEGER)
                AND CAST(s.id AS INTEGER)>0 AND json_extract(s.body,'$.object')=s.kind
                AND json_type(s.body,'$.data.characters')='text'
                AND length(json_extract(s.body,'$.data.characters')) BETWEEN 1 AND ?
                AND json_type(s.body,'$.data.level')='integer'
                AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
                AND json_extract(s.body,'$.data.hidden_at') IS NULL
                AND NOT EXISTS(SELECT 1 FROM resources a WHERE a.kind='assignment'
                  AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
                  AND COALESCE(json_extract(a.body,'$.data.hidden'),0)!=0)""",
                [row["id"] for row in batch] + [len(text), maximum])
            for row in rows:
                characters = row["characters"]
                if not characters.strip() or len(characters) > len(text):
                    continue
                positions = tuple(_positions(text, characters))
                if not positions:
                    continue
                candidates.append(({"id": row["id"], "characters": characters, "type": row["type"],
                    "level": row["level"], "state": "Learned" if epoch(row["started_at"]) is not None else "Not started",
                    "can_open": True}, positions))
        candidates.sort(key=lambda entry: (entry[1][0], -len(entry[0]["characters"]),
            TYPE_ORDER[entry[0]["type"]], entry[0]["id"]))
        result["truncated"] |= len(candidates) > MAX_MATCHES
        starts = {}
        seen = set()
        for item, positions in candidates:
            if item["id"] in seen:
                continue
            if len(result["matches"]) == MAX_MATCHES:
                break
            seen.add(item["id"])
            if item["characters"] in protected_characters:
                item["state"], item["can_open"] = "Paused graded work", False
            result["matches"].append(item)
            for start in positions:
                starts.setdefault(start, []).append(item)
        if result["matches"]:
            # Inspect only returned subject IDs and unresolved graded work.
            # Historical confirmations and personal-material edits do not
            # change a subject's study status in this read-only view.
            placeholders = ",".join("?" for _ in result["matches"])
            rows = engine.store.rows(f"""SELECT subject_id,
                MAX(CASE WHEN state IN ('uncertain','blocked','conflicted') THEN 2 ELSE 1 END) AS priority
              FROM outbox INDEXED BY outbox_state
              WHERE subject_id IN ({placeholders}) AND kind IN ('review','lesson')
                AND state IN ('pending','inflight','uncertain','blocked','conflicted')
              GROUP BY subject_id""", [item["id"] for item in result["matches"]])
            pending = {row["subject_id"]: row["priority"] for row in rows}
            for item in result["matches"]:
                if item["can_open"] and item["id"] in pending:
                    item["state"] = "Needs attention" if pending[item["id"]] == 2 else "Waiting to sync"
        segments = []
        position = 0
        while position < len(text):
            options = starts.get(position, [])
            if options:
                longest = max(len(item["characters"]) for item in options)
                aliases = sorted((item for item in options if len(item["characters"]) == longest),
                    key=lambda item: (TYPE_ORDER[item["type"]], item["id"]))
                segments.append({"text": text[position:position + longest], "subject_ids": [item["id"] for item in aliases]})
                position += longest
            else:
                if segments and not segments[-1]["subject_ids"]:
                    segments[-1]["text"] += text[position]
                else:
                    segments.append({"text": text[position], "subject_ids": []})
                position += 1
        # Every segment consumes at least one original codepoint, so the input
        # bound also keeps segments below the public 512-segment contract.
        result["segments"] = segments
        return result
