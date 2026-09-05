"""Original clip controls, spoiler timing, and mock-only focused downloads."""
import json
import threading
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW, UserError, stamp
from test_media_plan import MediaFixture, MIB
from test_media_sync import Response
from test_voices import audio
from wanikani.pronunciation import prepare, sample, status
from wanikani.sync import Synchronizer


class PronunciationTests(MediaFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.engine.connected = True
        self.engine.status = "connected"
        self.api = Mock()
        self.api.request.side_effect = AssertionError("Pronunciation must not refresh or write account resources")
        self.sync = Synchronizer(self.engine, self.api, self.media_dir)
        guard = patch("socket.create_connection", side_effect=AssertionError("Fixture tests must never open a real network connection"))
        guard.start()
        self.addCleanup(guard.stop)

    def sounds(self, subject_id=4, actor=17, entries=...):
        item = self.store.subject(subject_id)
        entries = entries if entries is not Ellipsis else [audio(actor=actor, suffix=str(subject_id) + ".mp3")]
        item["data"]["pronunciation_audios"] = entries
        self.store.put(item)
        return entries

    def only_due(self, subject_id):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != subject_id:
                assignment["data"]["available_at"] = stamp(NOW + 86400)
                self.store.put(assignment)

    def study_args(self, view=None):
        view = view or self.engine.session_view()
        return {"subject_id": view["subject"]["id"], "context": "study", "session_id": view["id"], "revision": view["revision"]}

    def request(self, response, **arguments):
        with patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response
            result = prepare(self.sync, **arguments)
            return result, factory.return_value.open

    def test_status_is_read_only_and_exposes_only_owned_cached_uri(self):
        sounds = self.sounds()
        self.assertEqual("not_cached", status(self.engine, 4)["status"])
        path = self.cached(sounds[0]["url"])
        before = list(self.store.db.iterdump())
        with patch.object(self.store, "execute", side_effect=AssertionError("Status must be read-only")):
            result = status(self.engine, 4)
        self.assertEqual(("ready", path.as_uri(), 17), (result["status"], result["uri"], result["voice_actor_id"]))
        self.assertNotIn("https:", json.dumps(result))
        self.assertEqual(before, list(self.store.db.iterdump()))
        path.unlink()
        outside = self.path.parent / "outside.mp3"
        outside.write_bytes(b"authored external bytes")
        path.symlink_to(outside)
        self.assertEqual("not_cached", status(self.engine, 4)["status"])

    def test_recording_type_and_malformed_metadata_are_explicit(self):
        self.assertEqual("no_recording", status(self.engine, 1)["status"])
        self.assertEqual("no_recording", status(self.engine, 2)["status"])
        for entries in (None, 17, {}, [None, True, "bad", {"url": "file:///private"}]):
            self.sounds(entries=entries)
            self.assertEqual("no_recording", status(self.engine, 4)["status"])
        sound = audio(actor=None)
        sound["metadata"] = "malformed"
        self.sounds(entries=[sound])
        self.assertEqual("not_cached", status(self.engine, 4)["status"])
        self.assertIsNone(status(self.engine, 4)["voice_actor_id"])

    def test_voice_selection_uses_requested_voice_and_truthful_fallback(self):
        first, second = audio(17, suffix="a.mp3"), audio(28, suffix="b.mp3")
        self.sounds(entries=[first, second])
        self.cached(second["url"])
        missing_preference = status(self.engine, 4, voice_actor_id=17)
        self.assertEqual(("ready", True, 28),
            (missing_preference["status"], missing_preference["voice_fallback"], missing_preference["voice_actor_id"]))
        self.assertEqual("not_cached", status(self.engine, 4, context="voice_test", voice_actor_id=17)["status"])
        chosen = status(self.engine, 4, voice_actor_id=28)
        self.assertEqual(("ready", False, 28), (chosen["status"], chosen["voice_fallback"], chosen["voice_actor_id"]))
        fallback = status(self.engine, 4, voice_actor_id=99)
        self.assertEqual(("ready", True, 28), (fallback["status"], fallback["voice_fallback"], fallback["voice_actor_id"]))
        self.engine.connected = False
        self.assertEqual("ready", status(self.engine, 4, voice_actor_id=17)["status"])
        self.assertEqual("offline", status(self.engine, 4, context="voice_test", voice_actor_id=17)["status"])
        self.engine.connected = True
        result, _ = self.request(Response(), subject_id=4, context="voice_test", voice_actor_id=17)
        self.assertEqual(("ready", False, 17), (result["status"], result["voice_fallback"], result["voice_actor_id"]))

    def test_review_audio_waits_for_reading_feedback(self):
        self.cached(self.sounds()[0]["url"])
        self.only_due(4)
        view = self.engine.start("reviews", 1)
        self.assertEqual("unrevealed", status(self.engine, **self.study_args(view))["reason"])
        view = self.engine.answer("water")
        self.assertEqual("unrevealed", status(self.engine, **self.study_args(view))["reason"])
        view = self.engine.advance()
        self.assertEqual("reading", view["part"])
        self.assertEqual("unrevealed", status(self.engine, **self.study_args(view))["reason"])
        view = self.engine.answer("wrong romaji")  # Retryable input is still an unanswered question.
        self.assertEqual("unrevealed", status(self.engine, **self.study_args(view))["reason"])
        view = self.engine.answer("かわ")
        self.assertEqual("ready", status(self.engine, **self.study_args(view))["status"])
        old = self.study_args(view)
        self.engine.advance()
        self.assertEqual("stale_session", status(self.engine, **old)["reason"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_lesson_discovery_audio_stops_at_the_unanswered_quiz(self):
        self.cached(self.sounds(7)[0]["url"])
        item = self.store.subject(7)
        item["data"]["lesson_position"] = 0
        self.store.put(item)
        view = self.engine.start("lessons", 1)
        self.assertEqual(7, view["subject"]["id"])
        self.assertEqual("ready", status(self.engine, **self.study_args(view))["status"])
        view = self.engine.lesson_next()
        self.assertEqual("unrevealed", status(self.engine, **self.study_args(view))["reason"])
        self.assertEqual("ready", status(self.engine, 7, context="details")["status"])

    def test_kana_vocabulary_can_play_after_its_only_question(self):
        self.cached(self.sounds(5)[0]["url"])
        self.only_due(5)
        view = self.engine.start("reviews", 1)
        self.assertEqual("unrevealed", status(self.engine, **self.study_args(view))["reason"])
        view = self.engine.answer("thank you")
        self.assertEqual("ready", status(self.engine, **self.study_args(view))["status"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_stale_mode_revision_and_access_never_return_uri(self):
        self.cached(self.sounds()[0]["url"])
        self.only_due(4)
        view = self.engine.start("reviews", 1)
        self.engine.answer("water")
        self.engine.advance()
        view = self.engine.answer("みず")
        arguments = self.study_args(view)
        for replacement in ({"session_id": "another"}, {"revision": True}, {"subject_id": 5}):
            result = status(self.engine, **{**arguments, **replacement})
            self.assertEqual("error", result["status"])
            self.assertIsNone(result["uri"])
        self.engine.start("lessons", 1)
        self.assertEqual("stale_session", status(self.engine, **arguments)["reason"])
        item = self.store.subject(4)
        item["data"]["hidden_at"] = stamp(NOW)
        self.store.put(item)
        self.assertEqual("access_restricted", status(self.engine, 4)["reason"])

    def test_prepare_downloads_only_one_clip_without_account_sync_or_grading(self):
        requested = self.sounds()[0]
        self.sounds(10)
        before_events = self.store.rows("SELECT COUNT(*) FROM events")[0][0]
        result, opened = self.request(Response(b"authored vocabulary recording"), subject_id=4)
        self.assertEqual("ready", result["status"])
        self.assertEqual(1, opened.call_count)
        self.assertEqual(requested["url"], opened.call_args.args[0].full_url)
        self.assertNotIn("Authorization", opened.call_args.args[0].headers)
        self.assertEqual([requested["url"]], [row[0] for row in self.store.rows("SELECT url FROM media")])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.assertEqual(before_events, self.store.rows("SELECT COUNT(*) FROM events")[0][0])
        self.assertIsNone(self.store.session())
        self.api.request.assert_not_called()
        self.assertFalse(self.sync.media_requested.is_set())

    def test_offline_and_demo_requests_never_attempt_download(self):
        self.sounds()
        for attribute, value in (("connected", False), ("status", "offline"), ("demo", True)):
            previous = getattr(self.engine, attribute)
            setattr(self.engine, attribute, value)
            result, opened = self.request(Response(), subject_id=4)
            self.assertEqual("offline", result["status"])
            opened.assert_not_called()
            setattr(self.engine, attribute, previous)

    def test_explicit_download_failure_does_not_create_hour_long_retry_block(self):
        self.sounds()
        for response in (Response(b"wrong mime", "text/html"), Response(b""), Response(b"truncated", length=100)):
            result, _ = self.request(response, subject_id=4)
            self.assertEqual(("error", "download_failed", None), (result["status"], result["reason"], result["uri"]))
        self.assertEqual([], self.store.rows("SELECT * FROM meta WHERE key LIKE 'media_retry_%'"))
        self.assertEqual("ready", self.request(Response(), subject_id=4)[0]["status"])

    def test_required_media_budget_is_preserved_before_network(self):
        self.sounds()
        required = self.url("required.svg")
        self.subject(1, images=[{"url": required}])
        existing = self.cached(required, 32 * MIB)
        result, opened = self.request(Response(), subject_id=4)
        self.assertEqual("budget", result["status"])
        opened.assert_not_called()
        self.assertTrue(existing.exists())
        self.assertEqual(32 * MIB, self.store.rows("SELECT SUM(size) FROM media")[0][0])

    def test_current_clip_can_replace_future_optional_audio_after_validation(self):
        for sid in range(100, 104):
            url = self.url(str(sid) + ".mp3")
            self.subject(sid, audio=[{"url": url}], characters="山", when=NOW + 7 * 86400)
            self.cached(url, 8 * MIB, used_at=sid)
        self.sounds()
        before = {row[0] for row in self.store.rows("SELECT url FROM media")}
        result, _ = self.request(Response(b"invalid", "text/html"), subject_id=4)
        self.assertEqual("error", result["status"])
        self.assertEqual(before, {row[0] for row in self.store.rows("SELECT url FROM media")})
        result, _ = self.request(Response(), subject_id=4)
        self.assertEqual("ready", result["status"])
        self.assertLessEqual(self.store.rows("SELECT SUM(size) FROM media")[0][0], 32 * MIB)

    def test_context_and_subscription_are_rechecked_after_download(self):
        self.sounds(7)
        item = self.store.subject(7)
        item["data"]["lesson_position"] = 0
        self.store.put(item)
        view = self.engine.start("lessons", 1)
        result, _ = self.request(Response(read_hook=self.engine.lesson_next), **self.study_args(view))
        self.assertEqual(("error", "stale_session", None), (result["status"], result["reason"], result["uri"]))
        self.sounds(4)
        item = self.store.subject(4)
        item["data"]["level"] = 4
        self.store.put(item)
        user = self.store.get("user")
        user["data"]["subscription"].update(type="recurring", period_ends_at=stamp(NOW + 10))
        self.store.set("user", user)
        result, _ = self.request(Response(read_hook=lambda: setattr(self.engine, "clock", lambda: NOW + 11)), subject_id=4)
        self.assertEqual(("error", "access_restricted", None), (result["status"], result["reason"], result["uri"]))

    def test_account_replacement_after_network_never_returns_old_audio(self):
        self.sounds()
        result, _ = self.request(Response(read_hook=lambda: self.store.set("account_id", "other-account")), subject_id=4)
        self.assertEqual(("error", "account_changed", None), (result["status"], result["reason"], result["uri"]))

    def test_voice_sample_excludes_paused_ids_written_aliases_and_known_readings(self):
        self.only_due(4)
        self.engine.start("reviews", 1)
        # Moon aliases the paused water glyph; forest has the same reading.
        for sid in (4, 7, 10, 12):
            self.cached(self.sounds(sid)[0]["url"])
            assignment = self.store.related("assignment", sid)
            assignment["data"]["started_at"] = stamp(NOW - 86400)
            self.store.put(assignment)
        alias = self.store.subject(7)
        alias["data"]["characters"] = "水"
        self.store.put(alias)
        homophone = self.store.subject(10)
        homophone["data"]["readings"] = [{"reading": "ミズ", "accepted_answer": True}]
        self.store.put(homophone)
        result = sample(self.engine, 17)
        self.assertEqual(("ready", 12), (result["status"], result["subject_id"]))
        for sid in (4, 7, 10):
            self.assertEqual("protected_sample", status(self.engine, sid, context="voice_test")["reason"])
        self.assertEqual("ready", status(self.engine, 4, context="details")["status"])

    def test_voice_sample_rechecks_protection_when_preparing(self):
        self.sounds()
        selected = sample(self.engine, 17)
        self.assertEqual(4, selected["subject_id"])
        self.only_due(4)
        self.engine.start("reviews", 1)
        result, opened = self.request(Response(), subject_id=4, context="voice_test", voice_actor_id=17)
        self.assertEqual("protected_sample", result["reason"])
        opened.assert_not_called()

    def test_voice_test_protects_kana_only_words_without_readings_arrays(self):
        self.only_due(5)
        self.engine.start("reviews", 1)
        self.sounds(10)
        word = self.store.subject(10)
        word["data"]["readings"] = [{"reading": "アリガトウ", "accepted_answer": True}]
        self.store.put(word)
        self.assertEqual("protected_sample", status(self.engine, 10, context="voice_test")["reason"])

    def test_voice_test_filters_unstarted_hidden_and_malformed_access(self):
        self.sounds(7)
        self.assertEqual("protected_sample", status(self.engine, 7, context="voice_test")["reason"])
        self.sounds(4)
        for level in (True, 0, -1, "1", None):
            word = self.store.subject(4)
            word["data"]["level"] = level
            self.store.put(word)
            self.assertEqual("access_restricted", status(self.engine, 4)["reason"])
            self.assertEqual("no_recording", sample(self.engine, 17)["status"])

    def test_cancelled_focused_download_retains_existing_cache(self):
        self.sounds()
        existing = self.cached(self.url("keep.mp3"))
        before = list(self.store.db.iterdump())
        with self.assertRaises(UserError):
            self.request(Response(read_hook=self.sync.cancelled.set), subject_id=4)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertTrue(existing.exists())
        self.assertFalse(self.sync.media_requested.is_set())
        self.assertIsNone(self.sync._media_plan)

    def test_media_lock_is_shared_and_foreground_request_yields_background_prefetch(self):
        other = Synchronizer(self.engine, self.api, self.media_dir)
        self.assertIs(self.sync.media_lock, other.media_lock)
        self.assertIs(self.sync.media_requested, other.media_requested)
        self.sounds()
        self.sync.media_requested.set()
        with patch.object(self.sync, "download_media") as download:
            result = self.sync.cache_media()
        self.assertFalse(result["complete"])
        download.assert_not_called()
        self.sync.media_requested.clear()
        arrived = threading.Event()
        result = []
        with patch("wanikani.sync.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response()
            with self.sync.media_lock:
                thread = threading.Thread(target=lambda: (result.append(prepare(other, 4)), arrived.set()))
                thread.start()
                self.assertTrue(self.sync.media_requested.wait(2))
                self.assertFalse(arrived.is_set())
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(arrived.is_set())
        self.assertEqual("ready", result[0]["status"])


if __name__ == "__main__":
    unittest.main()
