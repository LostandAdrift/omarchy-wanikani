"""Whole-word examples use authored catalogue/audio, never live learning IO."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW, UserError, stamp
from test_media_plan import MediaFixture
from test_media_sync import Response
from wanikani import kanji_examples, pronunciation
from wanikani.sync import Synchronizer


class KanjiExampleFixture(MediaFixture):
    def setUp(self):
        super().setUp()
        self.engine.connected = True
        self.engine.status = "online"
        self.api = Mock()
        self.api.request.side_effect = AssertionError("An example must not read or write account resources")
        self.sync = Synchronizer(self.engine, self.api, self.media_dir)
        self.guard = patch("socket.create_connection", side_effect=AssertionError("No live network in authored examples"))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def word(self, sid=101, characters="日語", reading="にちご", learned=False, cached=False, actor=1, level=1):
        item = copy.deepcopy(self.store.subject(7))
        item["id"] = sid
        clip = {"url": self.url(str(sid) + "-" + str(actor) + ".mp3"), "content_type": "audio/mpeg",
            "metadata": {"voice_actor_id": actor, "pronunciation": reading}}
        item["data"].update(characters=characters, level=level,
            meanings=[{"meaning": "authored example", "primary": True, "accepted_answer": True}],
            readings=[{"reading": reading, "primary": True, "accepted_answer": True}],
            pronunciation_audios=[clip], component_subject_ids=[6], amalgamation_subject_ids=[])
        self.store.put(item)
        assignment = copy.deepcopy(self.store.related("assignment", 6))
        assignment["id"] = sid + 10000
        assignment["data"].update(subject_id=sid, subject_type="vocabulary", started_at=stamp(NOW - 10) if learned else None,
            srs_stage=1 if learned else 0, available_at=stamp(NOW + 86400) if learned else None)
        self.store.put(assignment)
        parent = self.store.subject(6)
        parent["data"]["amalgamation_subject_ids"] = list(dict.fromkeys(parent["data"].get("amalgamation_subject_ids", []) + [sid]))
        self.store.put(parent)
        if cached:
            self.cached(clip["url"])
        return clip

    def study(self):
        view = self.engine.start("lessons", subjects=[6])
        return self.engine.command("show-parent-reading", "lesson_navigate",
            {"action": "next", "session_id": view["id"], "revision": view["revision"]})

    def page(self, view=None):
        return kanji_examples.catalogue(self.engine, {"parent_subject_id": 6, "context": "study" if view else "details",
            **({"session_id": view["id"], "revision": view["revision"]} if view else {})})

    def arguments(self, view=None, sid=101):
        return {"subject_id": sid, "context": "kanji_example", "parent_subject_id": 6,
            "origin_context": "study" if view else "details",
            **({"session_id": view["id"], "revision": view["revision"]} if view else {})}

    def prepare(self, response, view=None, sid=101):
        with patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response
            result = pronunciation.prepare(self.sync, **self.arguments(view, sid))
            return result, factory.return_value.open

    def protect(self, sid, ident="other-saved"):
        source = copy.deepcopy(self.store.session())
        source["id"] = ident
        source["mode"] = "reviews"
        source["phase"] = "question"
        source["index"] = 0
        source["queue"] = [{**source["queue"][0], "subject_id": sid, "done": False}]
        self.store.save_session(source, activate=False)


class KanjiExampleTests(KanjiExampleFixture, unittest.TestCase):
    def test_accessible_unlearned_words_are_readonly_full_word_examples(self):
        self.word()
        before = list(self.store.db.iterdump())
        page = self.page()
        self.assertEqual("available", page["status"])
        self.assertEqual([{"subject_id": 101, "characters": "日語", "pronunciation": "にちご",
            "meaning": "authored example", "learned": False, "cached": False}], page["examples"])
        self.assertEqual(before, list(self.store.db.iterdump()))
        for hidden in ("url", "uri", "mnemonic", "meaning_note", "account_id", "voice_actor"):
            self.assertNotIn(hidden, json.dumps(page))

    def test_ranking_precedes_three_item_limit_and_relation_scan_is_bounded(self):
        for sid, learned, cached in ((101, False, False), (102, True, False), (103, False, True), (104, True, True)):
            self.word(sid, learned=learned, cached=cached)
        self.assertEqual([104, 103, 102], [item["subject_id"] for item in self.page()["examples"]])
        with patch.object(kanji_examples, "MAX_RELATIONS", 2):
            page = self.page()
        self.assertFalse(page["complete"])
        self.assertEqual([102, 101], [item["subject_id"] for item in page["examples"]])

    def test_parent_is_exempt_only_in_its_exact_revealed_study_occurrence(self):
        self.word(characters="日", reading="にち", cached=True)
        view = self.engine.start("lessons", subjects=[6])
        self.assertEqual("unrevealed", self.page(view)["reason"])
        self.assertEqual("unrevealed", pronunciation.status(self.engine, **self.arguments(view))["reason"])
        view = self.study()
        self.assertEqual(101, self.page(view)["examples"][0]["subject_id"])
        self.assertEqual("ready", pronunciation.status(self.engine, **self.arguments(view))["status"])
        self.assertEqual([], self.page()["examples"], "Details gets no exemption for an active lesson")
        self.protect(6)
        self.assertEqual([], self.page(view)["examples"], "Another occurrence of the parent remains protected")
        self.assertEqual("protected_study", pronunciation.status(self.engine, **self.arguments(view))["reason"])

    def test_other_ids_written_aliases_readings_and_audio_aliases_remain_protected(self):
        self.word(cached=True)
        view = self.study()
        for kind in ("id", "glyph", "reading", "recording"):
            with self.subTest(kind=kind):
                item = copy.deepcopy(self.store.subject(4))
                if kind == "glyph":
                    item["data"]["characters"] = "日語"
                if kind == "reading":
                    item["data"]["readings"] = [{"reading": "にちご", "accepted_answer": True}]
                if kind == "recording":
                    item["data"]["pronunciation_audios"] = [{"metadata": {"pronunciation": "にちご"}}]
                self.store.put(item)
                self.protect(101 if kind == "id" else 4)
                self.assertEqual([], self.page(view)["examples"])
                self.assertEqual("protected_study", pronunciation.status(self.engine, **self.arguments(view))["reason"])
                self.store.execute("DELETE FROM sessions WHERE id='other-saved'")
                original = copy.deepcopy(self.store.subject(4))
                original["data"].update(characters="水", readings=[{"reading": "みず", "accepted_answer": True}], pronunciation_audios=[])
                self.store.put(original)

    def test_every_unresolved_graded_state_excludes_even_a_cached_example(self):
        self.word(cached=True)
        for state in ("pending", "inflight", "uncertain", "blocked", "conflicted"):
            with self.subTest(state=state):
                self.store.execute("INSERT OR REPLACE INTO outbox VALUES(?,?,?,?,?,?,?)", ("unresolved", "lesson", 101, state, "{}", stamp(NOW), ""))
                self.assertEqual([], self.page()["examples"])
                self.assertEqual("pending_study", pronunciation.status(self.engine, **self.arguments())["reason"])

    def test_duplicate_parent_withholds_compounds_with_different_whole_readings(self):
        self.word(cached=True)
        view = self.study()
        self.protect(6)
        self.assertEqual("protected_study", self.page(view)["reason"])
        self.assertEqual([], self.page(view)["examples"])
        self.assertEqual("protected_study", pronunciation.status(self.engine, **self.arguments(view))["reason"])

    def test_practice_parent_cannot_exempt_a_paused_graded_parent(self):
        self.word(cached=True)
        self.study()
        self.engine.start("practice", subjects=[6])
        self.engine.answer("sun")
        self.engine.advance()
        view = self.engine.answer("にち")
        self.assertEqual("protected_study", self.page(view)["reason"])
        self.assertEqual("protected_study", pronunciation.status(self.engine, **self.arguments(view))["reason"])

    def test_pending_parent_withholds_unresolved_compound_examples(self):
        self.word(cached=True)
        view = self.study()
        for state in ("pending", "inflight", "uncertain", "blocked", "conflicted"):
            self.store.execute("INSERT OR REPLACE INTO outbox VALUES(?,?,?,?,?,?,?)", ("parent-pending", "review", 6, state, "{}", stamp(NOW), ""))
            self.assertEqual("pending_study", self.page(view)["reason"])
            self.assertEqual("pending_study", pronunciation.status(self.engine, **self.arguments(view))["reason"])

    def test_missing_and_malformed_protected_subject_fail_closed(self):
        self.word(cached=True)
        view = self.study()
        self.protect(4)
        item = self.store.subject(4)
        item["data"]["readings"] = "PRIVATE malformed reading"
        self.store.put(item)
        page = self.page(view)
        self.assertEqual(("unavailable", "protected_study", []), (page["status"], page["reason"], page["examples"]))
        self.assertNotIn("PRIVATE", json.dumps(page))
        self.store.execute("DELETE FROM resources WHERE kind='vocabulary' AND id='4'")
        self.assertEqual("protected_study", self.page(view)["reason"])

    def test_unanswered_quiz_and_meaning_feedback_cannot_use_parent_exception(self):
        self.word(cached=True)
        view = self.study()
        view = self.engine.command("show-context", "lesson_navigate", {"action": "next", "session_id": view["id"], "revision": view["revision"]})
        view = self.engine.command("quiz", "lesson_navigate", {"action": "quiz", "session_id": view["id"], "revision": view["revision"]})
        self.assertEqual("unrevealed", self.page(view)["reason"])
        view = self.engine.answer("sun")
        self.assertEqual("unrevealed", self.page(view)["reason"])
        self.engine.advance()
        view = self.engine.answer("べつ")
        self.assertEqual("available", self.page(view)["status"])
        self.assertEqual("ready", pronunciation.status(self.engine, **self.arguments(view))["status"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_forged_or_removed_bidirectional_relation_is_rejected(self):
        self.word(cached=True)
        for change in ("parent", "word", "glyph"):
            self.word(cached=True)
            if change == "parent":
                parent = self.store.subject(6)
                parent["data"]["amalgamation_subject_ids"] = []
                self.store.put(parent)
            else:
                word = self.store.subject(101)
                word["data"]["component_subject_ids" if change == "word" else "characters"] = [] if change == "word" else "別語"
                self.store.put(word)
            with self.subTest(change=change):
                self.assertEqual([], self.page()["examples"])
                self.assertEqual("unrelated_example", pronunciation.status(self.engine, **self.arguments())["reason"])

    def test_wrong_parent_type_and_malformed_expired_or_hidden_access_are_unavailable(self):
        self.word(cached=True)
        self.assertEqual("unavailable", kanji_examples.catalogue(self.engine, {"parent_subject_id": 1, "context": "details"})["status"])
        original = self.store.subject(101)
        for patch_data in ({"level": 61}, {"level": "1"}, {"level": True}, {"hidden_at": stamp(NOW)}):
            word = copy.deepcopy(original)
            word["data"].update(patch_data)
            self.store.put(word)
            self.assertEqual([], self.page()["examples"])
            self.assertEqual("access_restricted", pronunciation.status(self.engine, **self.arguments())["reason"])
        self.store.put(original)
        assignment = self.store.related("assignment", 101)
        assignment["data"]["hidden"] = True
        self.store.put(assignment)
        self.assertEqual([], self.page()["examples"])

    def test_catalogue_rejects_empty_extra_and_forged_session_arguments(self):
        for args in ({}, {"parent_subject_id": 6}, {"parent_subject_id": True, "context": "details"},
                {"parent_subject_id": 6, "context": "details", "url": "https://private.invalid"},
                {"parent_subject_id": 6, "context": "details", "revision": 1},
                {"parent_subject_id": 6, "context": "study", "session_id": "x", "revision": True}):
            with self.subTest(args=args), self.assertRaises(UserError):
                kanji_examples.catalogue(self.engine, args)

    def test_chosen_clip_pronunciation_matches_cached_alternate_voice(self):
        preferred = self.word(actor=1)
        word = self.store.subject(101)
        word["data"]["readings"].append({"reading": "ひご", "accepted_answer": True})
        alternate = {"url": self.url("alternate.mp3"), "content_type": "audio/mpeg",
            "metadata": {"voice_actor_id": 2, "pronunciation": "ひご"}}
        word["data"]["pronunciation_audios"].append(alternate)
        self.store.put(word)
        self.cached(alternate["url"])
        result = pronunciation.status(self.engine, **self.arguments())
        self.assertTrue(result["voice_fallback"])
        self.assertEqual((2, "ひご"), (result["voice_actor_id"], result["example"]["pronunciation"]))
        self.assertEqual("ひご", self.page()["examples"][0]["pronunciation"])
        self.cached(preferred["url"])
        result = pronunciation.status(self.engine, **self.arguments())
        self.assertFalse(result["voice_fallback"])
        self.assertEqual("にちご", result["example"]["pronunciation"])

    def test_unsuitable_audio_metadata_never_guesses_the_word_reading(self):
        for pronunciation_value in (None, "", "incorrect latin", "PRIVATE\x00", "べつ"):
            clip = self.word(cached=True)
            word = self.store.subject(101)
            word["data"]["pronunciation_audios"][0]["metadata"]["pronunciation"] = pronunciation_value
            self.store.put(word)
            with self.subTest(value=pronunciation_value):
                self.assertEqual([], self.page()["examples"])
                self.assertEqual("no_recording", pronunciation.status(self.engine, **self.arguments())["reason"])

    def test_cached_offline_example_plays_and_missing_clip_never_contacts_network(self):
        self.word()
        self.engine.status = "offline"
        result, opened = self.prepare(Response())
        self.assertEqual("offline", result["status"])
        opened.assert_not_called()
        self.assertEqual("にちご", result["example"]["pronunciation"])
        self.word(cached=True)
        self.assertEqual("ready", pronunciation.status(self.engine, **self.arguments())["status"])

    def test_download_is_one_clip_without_any_session_or_account_progress_changes(self):
        clip = self.word()
        view = self.study()
        before = self.store.session()
        events = self.store.rows("SELECT COUNT(*) FROM events")[0][0]
        result, opened = self.prepare(Response(), view)
        self.assertEqual("ready", result["status"])
        self.assertEqual(clip["url"], opened.call_args.args[0].full_url)
        self.assertEqual(1, opened.call_count)
        self.assertEqual(before, self.store.session())
        self.assertEqual(events, self.store.rows("SELECT COUNT(*) FROM events")[0][0])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.api.request.assert_not_called()

    def test_parent_change_after_plan_but_before_network_prevents_download(self):
        self.word()
        view = self.study()
        from wanikani.media_plan import build
        def plan(*args):
            result = build(*args)
            self.engine.command("back-to-meaning", "lesson_navigate", {"action": "back", "session_id": view["id"], "revision": view["revision"]})
            return result
        with patch("wanikani.pronunciation.media_plan.build", side_effect=plan):
            result, opened = self.prepare(Response(), view)
        self.assertEqual("stale_session", result["reason"])
        opened.assert_not_called()
        self.assertIsNone(result["uri"])

    def test_relation_parent_revision_account_and_protection_rechecked_after_download(self):
        for change in ("relation", "revision", "account", "protection", "grant"):
            with self.subTest(change=change):
                self.store.execute("DELETE FROM sessions")
                self.store.execute("DELETE FROM commands")
                self.store.execute("DELETE FROM media")
                self.word()
                view = self.study()
                called = []
                def changed():
                    if called:
                        return
                    called.append(True)
                    if change == "relation":
                        item = self.store.subject(6)
                        item["data"]["amalgamation_subject_ids"] = []
                        self.store.put(item)
                    elif change == "revision":
                        self.engine.command("change-step", "lesson_navigate", {"action": "back", "session_id": view["id"], "revision": view["revision"]})
                    elif change == "account":
                        self.store.set("session_epoch", "new-authored-epoch")
                    elif change == "protection":
                        self.protect(101)
                    else:
                        item = self.store.subject(101)
                        item["data"]["level"] = 61
                        self.store.put(item)
                result, opened = self.prepare(Response(read_hook=changed), view)
                self.assertEqual(1, opened.call_count)
                self.assertEqual("error", result["status"])
                self.assertIsNone(result["uri"])
                self.assertNotIn("example", result)
                self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
                self.assertEqual([], self.store.rows("SELECT * FROM media"))
                self.assertEqual([], list(self.media_dir.glob("download-*.tmp")))

    def test_late_permission_loss_never_evicts_existing_optional_recordings(self):
        for sid in range(110, 114):
            clip = self.word(sid, learned=True)
            self.cached(clip["url"], size=8 * 1024 * 1024)
            assignment = self.store.related("assignment", sid)
            assignment["data"]["available_at"] = stamp(NOW + 86400 * 7)
            self.store.put(assignment)
        self.word()
        view = self.study()
        before = [tuple(row) for row in self.store.rows("SELECT * FROM media ORDER BY url")]
        paths = {path: path.stat().st_size for path in self.media_dir.iterdir()}
        result, _ = self.prepare(Response(read_hook=lambda: self.protect(101)), view)
        self.assertEqual("error", result["status"])
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM media ORDER BY url")])
        self.assertEqual(paths, {path: path.stat().st_size for path in self.media_dir.iterdir()})


if __name__ == "__main__":
    unittest.main()
