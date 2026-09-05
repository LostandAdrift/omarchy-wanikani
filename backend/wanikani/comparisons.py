"""Small, read-only comparison cards from WaniKani's visual-similarity links."""
from .common import accessible_subject


def for_subject(engine, subject):
    ids = subject["data"].get("visually_similar_subject_ids")
    if subject["object"] != "kanji" or not isinstance(ids, list) or not ids:
        return []
    from .practice import _sessions
    protected, _ = _sessions(engine)
    maximum = engine.max_level()
    seen = {subject["id"]}
    output = []
    for sid in ids[:60]:
        if type(sid) is not int or sid in seen or sid in protected:
            continue
        seen.add(sid)
        item = engine.store.subject(sid)
        if not accessible_subject(item, maximum) or item["object"] != "kanji":
            continue
        data = item["data"]
        characters = data.get("characters")
        if not isinstance(characters, str) or not characters.strip():
            continue
        meanings = data.get("meanings")
        readings = data.get("readings")
        meanings = [m["meaning"] for m in meanings if isinstance(m, dict)
            and m.get("accepted_answer") is True and isinstance(m.get("meaning"), str)
            and m["meaning"].strip()] if isinstance(meanings, list) else []
        readings = [{"reading": r["reading"], "type": r.get("type", ""), "accepted": True}
            for r in readings if isinstance(r, dict) and r.get("accepted_answer") is True
            and isinstance(r.get("reading"), str) and r["reading"].strip()] if isinstance(readings, list) else []
        if not meanings or not readings:
            continue
        output.append({"id": sid, "characters": characters, "meanings": meanings,
            "readings": readings, "level": data["level"]})
        if len(output) == 8:
            break
    return output
