"""Unsaved study-material input. Never consulted by grading or synchronization."""
import uuid

from .common import UserError


PREFIX = "material_editor_"
FIELDS = ("synonyms_text", "meaning_note", "reading_note")
LIMIT = 2000


def validate(values):
    if not isinstance(values, dict) or any(not isinstance(values.get(key), str) for key in FIELDS):
        raise UserError("Enter text for synonyms and notes.")
    if any(len(values[key]) > LIMIT for key in FIELDS):
        raise UserError("Keep each note and the synonym text within 2,000 characters.")
    return {key: values[key] for key in FIELDS}


def saved_values(material):
    material = material if isinstance(material, dict) else {}
    synonyms = material.get("meaning_synonyms", [])
    return {"synonyms_text": ", ".join(value for value in synonyms if isinstance(value, str)) if isinstance(synonyms, list) else "",
        "meaning_note": material.get("meaning_note") if isinstance(material.get("meaning_note"), str) else "",
        "reading_note": material.get("reading_note") if isinstance(material.get("reading_note"), str) else ""}


def material_values(raw):
    return {"meaning_synonyms": list(dict.fromkeys(value.strip() for value in raw["synonyms_text"].split(",") if value.strip())),
            "meaning_note": raw["meaning_note"], "reading_note": raw["reading_note"]}


def current_material(engine, subject_id):
    saved = engine.store.get("material_draft_" + str(subject_id))
    return saved if saved is not None else (engine.store.related("study_material", subject_id) or {}).get("data", {})


def record(engine, subject_id):
    value = engine.store.get(PREFIX + str(subject_id))
    if not isinstance(value, dict) or not isinstance(value.get("revision"), str):
        return None
    try:
        values = validate(value.get("values"))
    except UserError:
        return None
    return {"revision": value["revision"], "values": values}


def view(engine, subject_id, material):
    value = record(engine, subject_id)
    return {"editor_draft": value["values"] if value else None,
        "editor_revision": value["revision"] if value else None,
        "editor_dirty": bool(value and value["values"] != saved_values(material))}


def write(engine, subject_id, values):
    engine.ensure_access(engine.store.subject(subject_id))
    values = validate(values)
    key = PREFIX + str(subject_id)
    with engine.store.transaction():
        old = record(engine, subject_id)
        if values == saved_values(current_material(engine, subject_id)):
            engine.store.execute("DELETE FROM meta WHERE key=?", (key,))
            revision, dirty = None, False
        else:
            revision = old["revision"] if old and old["values"] == values else uuid.uuid4().hex
            engine.store.set(key, {"revision": revision, "values": values})
            dirty = True
    # Small durable acknowledgment; no subject data or dashboard snapshot.
    return {"subject_id": subject_id, "stored": True, "dirty": dirty, "revision": revision}


def discard(engine, subject_id, expected=None):
    engine.ensure_access(engine.store.subject(subject_id))
    if expected is not None:
        expected = validate(expected)
    with engine.store.transaction():
        old = record(engine, subject_id)
        if expected is None or old is None or old["values"] == expected:
            engine.store.execute("DELETE FROM meta WHERE key=?", (PREFIX + str(subject_id),))
        return engine.details(subject_id)


def clear_saved(engine, subject_id, submitted, expected):
    """Only an explicit save of this exact editor input can remove its draft.

    Callers without an expected raw editor value preserve unsaved input. A newer
    input (even whitespace or an unfinished comma) is not lost to an old Save.
    The caller owns the same transaction as the material outbox insertion.
    """
    if expected is None:
        return
    expected = validate(expected)
    old = record(engine, subject_id)
    if old and old["values"] == expected and material_values(expected) == submitted:
        engine.store.execute("DELETE FROM meta WHERE key=?", (PREFIX + str(subject_id),))
