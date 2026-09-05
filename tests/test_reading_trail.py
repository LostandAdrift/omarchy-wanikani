import copy
import json
import threading
import unittest
from unittest.mock import Mock, patch

from test_backend import EngineFixture, NOW, UserError, stamp
from wanikani.trail import reading_trail
from worker import Worker


class ReadingTrailTests(EngineFixture, unittest.TestCase):
    def add(self, sid, characters, kind="vocabulary", level=1, **values):
        item = copy.deepcopy(self.store.subject(4))
        item.update(id=sid, object=kind)
        item["data"].update(characters=characters, level=level, **values)
        self.store.put(item)
        return item

    def check_passage(self, text):
        result = reading_trail(self.engine, text)
        self.assertEqual(text, result["text"])
        self.assertEqual(text, "".join(segment["text"] for segment in result["segments"]))
        self.assertLessEqual(len(result["segments"]), 512)
        self.assertLessEqual(len(result["matches"]), 60)
        ids = {item["id"] for item in result["matches"]}
        self.assertEqual(len(ids), len(result["matches"]))
        for segment in result["segments"]:
            self.assertTrue(segment["text"])
            self.assertTrue(set(segment["subject_ids"]) <= ids)
            for sid in segment["subject_ids"]:
                self.assertEqual(segment["text"], next(item["characters"] for item in result["matches"] if item["id"] == sid))
        return result

    def test_exact_passage_mixed_types_emoji_whitespace_markup_and_repeat(self):
        text = '  山と火山🌊\nありがとう、山。<a href="x">&  '
        result = self.check_passage(text)
        self.assertEqual([2, 8, 5], [item["id"] for item in result["matches"]])
        self.assertEqual(["kanji", "vocabulary", "kana_vocabulary"], [item["type"] for item in result["matches"]])
        self.assertEqual([[2], [8], [5], [2]], [segment["subject_ids"] for segment in result["segments"] if segment["subject_ids"]])
        self.assertFalse(result["truncated"])

    def test_longest_greedy_segments_keep_overlapping_matches(self):
        self.add(1001, "火", "kanji")
        self.add(1002, "山川")
        result = self.check_passage("火山川")
        self.assertEqual([8, 1001, 1002, 2, 3], [item["id"] for item in result["matches"]])
        self.assertEqual([{"text": "火山", "subject_ids": [8]}, {"text": "川", "subject_ids": [3]}], result["segments"])

    def test_same_span_aliases_prefer_vocabulary_and_stay_stable(self):
        self.add(1001, "山")
        self.add(1002, "山", "kana_vocabulary")
        result = self.check_passage("山山")
        self.assertEqual([1001, 1002, 2], [item["id"] for item in result["matches"]])
        self.assertEqual([[1001, 1002, 2], [1001, 1002, 2]], [segment["subject_ids"] for segment in result["segments"]])
        self.assertEqual(result, reading_trail(self.engine, "山山"))

    def test_unicode_codepoints_are_exact_and_visible_glyphs_not_split(self):
        self.add(1001, "𠮷", "kanji")
        self.add(1002, "か", "kana_vocabulary")
        self.add(1003, "が", "kana_vocabulary")
        self.add(1004, "日", "vocabulary")
        text = "𠮷😺か\u3099 が 日\U000e0100 か 日"
        result = self.check_passage(text)
        linked = [segment["text"] for segment in result["segments"] if segment["subject_ids"]]
        self.assertEqual(["𠮷", "が", "か", "日"], linked)
        self.assertNotIn("か\u3099", linked)
        # Exact decomposed catalogue strings may match as a complete glyph.
        self.add(1005, "か\u3099", "kana_vocabulary")
        result = self.check_passage(text)
        self.assertIn({"text": "か\u3099", "subject_ids": [1005]}, result["segments"])

    def test_empty_unmatched_input_and_bounds_do_not_change_text(self):
        self.assertEqual({"text": "", "segments": [], "matches": [], "truncated": False}, reading_trail(self.engine, ""))
        self.assertEqual([], self.check_passage("x" * 256)["matches"])
        self.check_passage("𠮷" * 256)
        for text in ("x" * 257, "𠮷" * 257, None, 42, [], "\ud800"):
            with self.subTest(text=repr(text)[:30]), self.assertRaises(UserError):
                reading_trail(self.engine, text)

    def test_hidden_malformed_and_out_of_grant_are_skipped(self):
        original = copy.deepcopy(self.store.subject(2))
        for field, value in (("level", True), ("level", False), ("level", 0), ("level", -1),
                ("level", "1"), ("level", 1.0), ("level", None), ("level", 61),
                ("hidden_at", False), ("hidden_at", "hidden"), ("characters", None),
                ("characters", []), ("characters", 7), ("characters", "")):
            with self.subTest(field=field, value=value):
                item = copy.deepcopy(original)
                item["data"][field] = value
                self.store.put(item)
                self.assertEqual([], self.check_passage("山")["matches"])
        self.store.put(original)
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 0
        self.store.set("user", user)
        self.assertEqual([], self.check_passage("山")["matches"])

    def test_expiry_missing_assignments_and_plain_status(self):
        self.add(1001, "夕日", level=4)
        result = self.check_passage("山 日 夕日")
        self.assertEqual("Learned", result["matches"][0]["state"])
        self.assertEqual("Not started", next(item["state"] for item in result["matches"] if item["id"] == 6))
        self.assertEqual("Not started", next(item["state"] for item in result["matches"] if item["id"] == 1001))
        user = self.store.get("user")
        user["data"]["subscription"].update(type="recurring", period_ends_at=stamp(NOW))
        self.store.set("user", user)
        self.assertNotIn(1001, [item["id"] for item in self.check_passage("夕日")["matches"]])

    def test_radicals_and_hidden_assignments_are_excluded(self):
        self.assertEqual([], self.check_passage("一")["matches"])
        assignment = self.store.related("assignment", 2)
        assignment["data"]["hidden"] = True
        self.store.put(assignment)
        self.assertEqual([], self.check_passage("山")["matches"])

    def test_paused_graded_subjects_and_same_glyph_aliases_cannot_open(self):
        self.add(1001, "山")
        self.engine.start("reviews", 5)
        self.engine.draft("kept answer")
        self.engine.start("practice", 1, [13])
        result = self.check_passage("山 火山 海")
        for item in result["matches"]:
            if item["id"] in (2, 1001):
                self.assertFalse(item["can_open"])
                self.assertEqual("Paused graded work", item["state"])
            else:
                self.assertTrue(item["can_open"])
        self.assertTrue(all(set(item) == {"id", "characters", "type", "level", "state", "can_open"} for item in result["matches"]))
        self.assertNotIn("kept answer", json.dumps(result))

    def test_completed_and_pending_work_can_open_without_any_mutation(self):
        self.complete(limit=5)
        before = list(self.store.db.iterdump())
        with patch.object(self.store, "execute", side_effect=AssertionError("Reading trail must be read-only")):
            result = self.check_passage("山 川 水 ありがとう")
        self.assertTrue(all(item["can_open"] for item in result["matches"]))
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_protected_alias_outside_catalogue_budget_still_hides_included_alias(self):
        self.add(1001, "山")
        self.engine.start("reviews", 1)
        session = self.store.session()
        session["queue"][0]["subject_id"] = 1001
        self.store.save_session(session)
        with patch("wanikani.trail.MAX_SUBJECTS", 2):
            result = self.check_passage("山")
        self.assertTrue(result["truncated"])
        self.assertEqual([2], [item["id"] for item in result["matches"]])
        self.assertFalse(result["matches"][0]["can_open"])
        self.assertEqual("Paused graded work", result["matches"][0]["state"])

    def test_offline_lesson_and_review_status_waits_for_sync(self):
        self.complete("lessons", 1)
        self.complete("reviews", 5)
        result = self.check_passage("日 山 川 水 ありがとう")
        self.assertTrue(all(item["state"] == "Waiting to sync" for item in result["matches"]))
        self.assertTrue(all(item["can_open"] for item in result["matches"]))
        self.assertIsNone(self.store.related("assignment", 6)["data"]["started_at"])
        before = list(self.store.db.iterdump())
        with patch.object(self.store, "execute", side_effect=AssertionError("Pending labels must be read-only")):
            self.check_passage("日 山")
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_submission_status_priorities_and_non_graded_operations(self):
        self.complete("lessons", 1)
        for state, expected in (("pending", "Waiting to sync"), ("inflight", "Waiting to sync"),
                ("uncertain", "Needs attention"), ("blocked", "Needs attention"),
                ("conflicted", "Needs attention"), ("confirmed", "Not started"), ("discarded", "Not started")):
            with self.subTest(state=state):
                self.store.execute("UPDATE outbox SET state=?", (state,))
                item = self.check_passage("日")["matches"][0]
                self.assertEqual(expected, item["state"])
                self.assertTrue(item["can_open"])
        self.store.execute("UPDATE outbox SET kind='material',state='uncertain'")
        self.assertEqual("Not started", self.check_passage("日")["matches"][0]["state"])
        self.store.execute("UPDATE outbox SET kind='lesson',state='pending'")
        self.store.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)",
            ("authored-attention", "review", 6, "uncertain", "{}", stamp(NOW), ""))
        self.assertEqual("Needs attention", self.check_passage("日")["matches"][0]["state"])

    def test_paused_protection_wins_over_pending_and_attention_status(self):
        self.add(1001, "山")
        self.engine.start("reviews", 5)
        for sid, state in ((2, "uncertain"), (1001, "pending")):
            self.store.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)",
                ("authored-" + str(sid), "review", sid, state, "{}", stamp(NOW), ""))
        result = self.check_passage("山")
        self.assertTrue(all(item["state"] == "Paused graded work" for item in result["matches"]))
        self.assertFalse(any(item["can_open"] for item in result["matches"]))

    def test_match_and_catalogue_bounds_keep_omitted_original_text(self):
        for sid in range(1000, 1070):
            self.add(sid, "山")
        result = self.check_passage("山。山")
        self.assertTrue(result["truncated"])
        self.assertEqual(60, len(result["matches"]))
        self.assertEqual(list(range(1000, 1060)), result["segments"][0]["subject_ids"])
        with patch("wanikani.trail.MAX_SUBJECTS", 2), patch("wanikani.trail.CONTENT_BATCH", 1):
            result = self.check_passage("山 川 海")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["matches"]), 2)

    def test_incomplete_protection_scan_or_malformed_session_withholds_links(self):
        self.engine.start("reviews", 1)
        with patch("wanikani.trail.MAX_SESSIONS", 0):
            result = self.check_passage("山")
        self.assertTrue(result["truncated"])
        self.assertEqual([], result["matches"])
        for queue in ("malformed", None, True, 7, {}, [True]):
            with self.subTest(queue=queue):
                session = self.store.session()
                session["queue"] = queue
                self.store.save_session(session)
                result = self.check_passage("山")
                self.assertTrue(result["truncated"])
                self.assertEqual([], result["matches"])

    def test_worker_route_is_read_only_and_emits_only_one_reply(self):
        worker = Worker.__new__(Worker)
        worker.engine = self.engine
        worker.emit = Mock()
        worker.changed = Mock()
        with patch.object(self.store, "execute", side_effect=AssertionError("Trail dispatch must be read-only")):
            worker.handle({"v": 1, "id": "authored-trail", "method": "reading_trail", "args": {"text": "山"}})
        worker.emit.assert_called_once()
        self.assertEqual("山", worker.emit.call_args.args[0]["data"]["text"])
        worker.changed.assert_not_called()
        self.assertEqual(0, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])

    def test_access_and_hydration_share_the_store_lock(self):
        observed = []
        original = self.store.rows
        def rows(sql, args=()):
            acquired = []
            def contender():
                held = self.store.lock.acquire(blocking=False)
                acquired.append(held)
                if held:
                    self.store.lock.release()
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join()
            observed.extend(acquired)
            return original(sql, args)
        with patch.object(self.store, "rows", side_effect=rows):
            self.check_passage("山")
        self.assertTrue(observed)
        self.assertFalse(any(observed))


if __name__ == "__main__":
    unittest.main()
