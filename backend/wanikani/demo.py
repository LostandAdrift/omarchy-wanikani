"""Independently authored sample material. Never exported to the real API."""
from .common import stamp


def populate(store, now):
    if store.get("demo_seeded"):
        return
    examples = [
        (1, "radical", "一", "ground", [], "A single horizontal line makes a place to stand."),
        (2, "kanji", "山", "mountain", ["さん"], "Picture three peaks rising from the page."),
        (3, "kanji", "川", "river", ["かわ"], "Three streams run alongside one another."),
        (4, "vocabulary", "水", "water", ["みず"], "A drink of water after a long walk."),
        (5, "kana_vocabulary", "ありがとう", "thank you", [], "A small phrase for a thoughtful gesture."),
        (6, "kanji", "日", "sun", ["にち"], "Light fills a little window."),
        (7, "vocabulary", "月", "moon", ["つき"], "The moon rises while the town gets quiet."),
        (8, "vocabulary", "火山", "volcano", ["かざん"], "Combine fire and mountain: a volcano."),
        (9, "kanji", "木", "tree", ["もく"], "A trunk, branches, and roots."),
        (10, "vocabulary", "森", "forest", ["もり"], "Many trees make a forest."),
        (11, "kanji", "雨", "rain", ["う"], "Raindrops fall beneath a cloud."),
        (12, "vocabulary", "空", "sky", ["そら"], "Look up at the open sky."),
        (13, "kanji", "海", "sea", ["かい"], "A wide expanse of water at the coast."),
        (14, "vocabulary", "花", "flower", ["はな"], "A flower opens in the morning light."),
        (15, "vocabulary", "星", "star", ["ほし"], "One bright point in the night sky."),
        (16, "vocabulary", "本", "book", ["ほん"], "A book is waiting beside your tea."),
    ]
    with store.transaction():
        store.set("user", {"id": "demo", "object": "user", "data": {"username": "Demo learner", "level": 3, "current_vacation_started_at": None, "subscription": {"active": True, "type": "lifetime", "max_level_granted": 60, "period_ends_at": None}}})
        for sid, kind, chars, gloss, readings, mnemonic in examples:
            level = 1 if sid <= 8 else 2
            store.put({"id": sid, "object": kind, "data_updated_at": stamp(now), "data": {
                "characters": chars, "slug": chars, "level": level, "hidden_at": None,
                "meanings": [{"meaning": gloss, "primary": True, "accepted_answer": True}],
                "readings": [{"reading": r, "primary": True, "accepted_answer": True, "type": "onyomi"} for r in readings],
                "meaning_mnemonic": mnemonic, "reading_mnemonic": "Say the reading aloud, then picture the word in a familiar place.",
                "component_subject_ids": [2] if sid == 8 else [], "amalgamation_subject_ids": [8] if sid == 2 else [],
                "visually_similar_subject_ids": [3] if sid == 2 else [2] if sid == 3 else [],
                "context_sentences": [{"ja": "山が見えます。", "en": "I can see a mountain."}] if sid == 2 else [],
                "pronunciation_audios": [], "character_images": [], "auxiliary_meanings": [], "lesson_position": sid,
            }})
            lesson = 6 <= sid <= 8
            future = sid >= 9
            store.put({"id": sid + 100, "object": "assignment", "data_updated_at": stamp(now), "data": {
                "subject_id": sid, "subject_type": kind, "srs_stage": 0 if lesson else 5 if future else 2,
                "unlocked_at": stamp(now - 86400 * 5), "started_at": None if lesson else stamp(now - 86400 * 4),
                "available_at": None if lesson else stamp(now + (86400 * 3 if sid >= 13 else 3600 * (sid - 8)) if future else now - 3600),
                "passed_at": stamp(now - 86400) if future else None, "burned_at": None, "hidden": False,
            }})
            store.put({"id": sid + 200, "object": "review_statistic", "data_updated_at": stamp(now), "data": {
                "subject_id": sid, "meaning_correct": 7, "meaning_incorrect": 3 if sid == 3 else 0,
                "reading_correct": 7, "reading_incorrect": 2 if sid == 4 else 0, "percentage_correct": 70 if sid in (3, 4) else 100,
                "hidden": False,
            }})
        store.set("account_id", "demo")
        store.set("demo_seeded", True)
        store.set("last_sync", stamp(now))
