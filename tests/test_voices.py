"""Pronunciation choices come from authored metadata, never guessed actor IDs."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from test_backend import EngineFixture, NOW
from wanikani.common import stamp
from wanikani.voices import catalogue
from worker import Worker


def audio(actor=17, name="Fixture voice", description="Fixture accent", suffix="sample.mp3"):
    return {"url": "https://files.wanikani.com/" + suffix, "content_type": "audio/mpeg", "metadata": {
        "voice_actor_id": actor, "voice_actor_name": name, "voice_description": description}}


class VoiceTests(EngineFixture, unittest.TestCase):
    def sounds(self, entries, subject_id=4):
        subject = self.store.subject(subject_id)
        subject["data"]["pronunciation_audios"] = entries
        self.store.put(subject)
        return subject

    def test_no_cached_metadata_creates_no_voice_choices(self):
        self.engine.set_settings({"voice_actor_id": 99})
        page = catalogue(self.engine)
        self.assertEqual([], page["items"])
        self.assertTrue(page["complete"])
        self.assertEqual(99, page["preferred_id"])
        self.assertFalse(page["preferred_available"])
        self.assertEqual(99, self.engine.settings()["voice_actor_id"])

    def test_actual_names_and_descriptions_are_deduplicated_across_formats_and_subjects(self):
        self.sounds([audio(suffix="one.mp3"), audio(suffix="one.ogg"), audio(28, "Second fixture voice", "Another accent")])
        self.sounds([audio(suffix="another-word.webm")], 5)
        page = catalogue(self.engine)
        self.assertEqual([17, 28], [item["id"] for item in page["items"]])
        self.assertEqual({"id": 17, "name": "Fixture voice", "description": "Fixture accent", "label": "Fixture voice"}, page["items"][0])
        self.assertNotIn("url", json.dumps(page))
        self.assertNotIn("sample.mp3", json.dumps(page))

    def test_existing_metadata_id_without_name_has_a_neutral_label(self):
        self.sounds([audio(37, None, None)])
        item = catalogue(self.engine)["items"][0]
        self.assertEqual("Voice 37", item["label"])
        self.assertEqual("", item["name"])
        self.assertEqual("", item["description"])

    def test_later_named_metadata_improves_an_unnamed_occurrence(self):
        self.sounds([audio(17, "", ""), audio(17, "Named fixture voice", "Described voice")])
        item = catalogue(self.engine)["items"][0]
        self.assertEqual("Named fixture voice", item["label"])
        self.assertEqual("Described voice", item["description"])

    def test_malformed_arrays_entries_and_metadata_are_ignored_safely(self):
        for entries in (None, 12, "not an array", {}, [None, "not JSON", 12, [], True],
                [{"url": None}, {"url": "https://files.wanikani.com/a", "metadata": "invalid"}]):
            with self.subTest(entries=entries):
                self.sounds(entries)
                self.assertEqual([], catalogue(self.engine)["items"])
        malformed = []
        for actor in (None, True, False, "1", 0, -1, 10001, [], {}):
            malformed.append(audio(actor, "Not a selectable voice"))
        self.sounds(malformed)
        self.assertEqual([], catalogue(self.engine)["items"])

    def test_names_without_actual_ids_or_audio_urls_do_not_fabricate_choices(self):
        entries = [audio(None, "A name alone"), audio(17), audio(28)]
        entries[1]["url"] = ""
        entries[2]["url"] = "file:///not-an-account-recording"
        self.sounds(entries)
        self.assertEqual([], catalogue(self.engine)["items"])

    def test_labels_strip_markup_controls_and_bound_length(self):
        self.sounds([audio(17, "<b>Fixture</b>\u202e voice", "<i>Accent</i>\n description")])
        item = catalogue(self.engine)["items"][0]
        self.assertEqual("Fixture voice", item["label"])
        self.assertEqual("Accent description", item["description"])
        self.sounds([audio(17, "名" * 1000, "Description " * 1000)])
        item = catalogue(self.engine)["items"][0]
        self.assertLessEqual(len(item["label"]), 80)
        self.assertLessEqual(len(item["description"]), 160)

    def test_embedded_null_metadata_does_not_misrepresent_a_truncated_name(self):
        self.sounds([audio(17, "Invalid\x00name", "Invalid\x00description")])
        item = catalogue(self.engine)["items"][0]
        self.assertEqual("Voice 17", item["label"])
        self.assertEqual("", item["description"])

    def test_hidden_restricted_and_invalid_level_sources_do_not_reveal_voice_names(self):
        self.sounds([audio(17, "Visible fixture voice")])
        for index, level in enumerate((4, 0, None, "1", True)):
            subject = copy.deepcopy(self.store.subject(4))
            subject["id"] = 2000 + index
            subject["data"].update(level=level, pronunciation_audios=[audio(30 + index, "PRIVATE-VOICE-MARKER")])
            self.store.put(subject)
        hidden = self.sounds([audio(50, "PRIVATE-VOICE-MARKER")], 5)
        hidden["data"]["hidden_at"] = stamp(NOW)
        self.store.put(hidden)
        user = self.store.get("user")
        user["data"]["subscription"].update(active=False, type="free", max_level_granted=3)
        self.store.set("user", user)
        page = catalogue(self.engine)
        self.assertEqual([17], [item["id"] for item in page["items"]])
        self.assertNotIn("PRIVATE-VOICE", json.dumps(page))

    def test_expired_subscription_rechecks_access_for_every_catalogue_request(self):
        subject = self.sounds([audio(17, "Premium fixture voice")])
        subject["data"]["level"] = 4
        self.store.put(subject)
        user = self.store.get("user")
        user["data"]["subscription"].update(active=True, type="recurring", max_level_granted=60, period_ends_at=stamp(NOW + 10))
        self.store.set("user", user)
        self.assertEqual(1, len(catalogue(self.engine)["items"]))
        self.engine.clock = lambda: NOW + 11
        self.assertEqual([], catalogue(self.engine)["items"])

    def test_downloaded_only_playback_preserves_preference_and_fallback(self):
        entries = [audio(17, "Preferred fixture voice", suffix="preferred.mp3"), audio(28, "Fallback fixture voice", suffix="fallback.mp3")]
        self.sounds(entries)
        self.engine.set_settings({"voice_actor_id": 17})
        self.assertTrue(catalogue(self.engine)["preferred_available"])
        self.assertEqual([], self.engine.details(4)["audio"])
        for index in (1, 0):
            path = self.path.parent / "media" / (str(index) + ".mp3")
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"authored placeholder; playback is not invoked")
            self.store.execute("INSERT INTO media VALUES (?,?,?,?)", (entries[index]["url"], str(path), path.stat().st_size, NOW))
            sounds = self.engine.details(4)["audio"]
            self.assertEqual(28 if index == 1 else 17, sounds[0]["actor"])
            self.assertTrue(all(sound["url"].startswith("file:") for sound in sounds))
        self.assertEqual(17, self.engine.settings()["voice_actor_id"])

    def test_explicit_bounds_report_partial_results_without_inventing_choices(self):
        self.sounds([audio(index, "Fixture " + str(index)) for index in range(1, 5)])
        with patch("wanikani.voices.MAX_CLIPS", 2), patch("wanikani.voices.MAX_VOICES", 1):
            page = catalogue(self.engine)
        self.assertFalse(page["complete"])
        self.assertEqual([1], [item["id"] for item in page["items"]])
        self.assertTrue(page["message"])

    def test_worker_catalogue_does_not_write_commands_or_emit_state(self):
        self.sounds([audio()])
        worker = Worker.__new__(Worker)
        worker.engine = self.engine
        worker.emit = Mock()
        worker.changed = Mock()
        with patch.object(self.store, "execute", side_effect=AssertionError("Voice lookup must be read-only")):
            worker.handle({"v": 1, "id": "voice-list", "method": "voices"})
        self.assertEqual("Fixture voice", worker.emit.call_args.args[0]["data"]["items"][0]["name"])
        worker.changed.assert_not_called()
        self.assertEqual(0, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])


if __name__ == "__main__":
    unittest.main()
