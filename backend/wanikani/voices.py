"""Read-only voice choices derived from accessible cached pronunciation metadata.

The API documents voice_actor_id, voice_actor_name, and voice_description at
https://docs.api.wanikani.com/20170710/#pronunciation-audio-metadata-object-attributes
Names are never inferred from numeric IDs. This catalogue does not fetch audio
or claim that a metadata entry has already been downloaded for playback.
"""
import json
import unicodedata

from .common import plain


MAX_SUBJECTS = 12000
MAX_CLIPS = 65536
MAX_VOICES = 64


def _text(value, limit):
    value = plain(value) if isinstance(value, str) else ""
    value = "".join(" " if character.isspace() else character for character in value
        if character.isspace() or not unicodedata.category(character).startswith("C"))
    return " ".join(value.split())[:limit]


def catalogue(engine):
    # Project and aggregate in SQLite; no mnemonics, readings, URLs, or full
    # subject payloads enter the response. Bounds are explicit even for an
    # unexpectedly large catalogue, and incomplete results are labelled.
    row = engine.store.rows("""WITH subjects AS MATERIALIZED (
      SELECT json_extract(body,'$.data.pronunciation_audios') AS audios FROM resources
      WHERE kind IN ('vocabulary','kana_vocabulary')
        AND json_type(body,'$.data.level')='integer'
        AND json_extract(body,'$.data.level') BETWEEN 1 AND ?
        AND json_extract(body,'$.data.hidden_at') IS NULL
        AND json_type(body,'$.data.pronunciation_audios')='array'
      ORDER BY kind,CAST(id AS INTEGER) LIMIT ?
    ), clips AS MATERIALIZED (
      SELECT json_extract(a.value,'$.metadata.voice_actor_id') AS actor,
        json_type(a.value,'$.metadata.voice_actor_id') AS actor_type,
        CASE WHEN json_type(a.value,'$.metadata.voice_actor_name')='text'
          AND instr(json_extract(a.value,'$.metadata.voice_actor_name'),char(0))=0
          THEN substr(trim(json_extract(a.value,'$.metadata.voice_actor_name')),1,160) ELSE '' END AS name,
        CASE WHEN json_type(a.value,'$.metadata.voice_description')='text'
          AND instr(json_extract(a.value,'$.metadata.voice_description'),char(0))=0
          THEN substr(trim(json_extract(a.value,'$.metadata.voice_description')),1,240) ELSE '' END AS description
      FROM subjects, json_each(subjects.audios) a
      WHERE a.type='object' AND json_type(a.value,'$.url')='text'
        AND json_extract(a.value,'$.url') LIKE 'https://%'
      LIMIT ?
    ), actors AS (
      SELECT actor,MAX(name) AS name,MAX(description) AS description FROM clips
      WHERE actor_type='integer' AND actor BETWEEN 1 AND 10000 GROUP BY actor
    ) SELECT (SELECT COUNT(*) FROM subjects) AS subject_count,
      (SELECT COUNT(*) FROM clips) AS clip_count,
      (SELECT COUNT(*) FROM actors) AS actor_count,
      (SELECT json_group_array(json_object('id',actor,'name',name,'description',description))
        FROM (SELECT * FROM actors ORDER BY actor LIMIT ?)) AS choices""",
        (engine.max_level(), MAX_SUBJECTS + 1, MAX_CLIPS + 1, MAX_VOICES))[0]
    items = []
    for actor in json.loads(row["choices"]):
        name, description = _text(actor["name"], 80), _text(actor["description"], 160)
        items.append({"id": actor["id"], "name": name, "description": description,
            "label": name or "Voice " + str(actor["id"])})
    complete = row["subject_count"] <= MAX_SUBJECTS and row["clip_count"] <= MAX_CLIPS and row["actor_count"] <= MAX_VOICES
    preferred = engine.settings()["voice_actor_id"]
    return {"items": items, "complete": complete, "preferred_id": preferred,
        "preferred_available": any(actor["id"] == preferred for actor in items),
        "message": "" if complete else "Showing voices from part of the cached catalogue."}
