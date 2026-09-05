"""Required offline images, bounded admission, and malformed media fixtures."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW, stamp
from wanikani.media_plan import build, valid_url, MAX_FILE_BYTES, PROJECTION_BATCH, UNREFERENCED


MIB = 1024 * 1024


class MediaFixture(EngineFixture):
    def setUp(self):
        super().setUp()
        self.media_dir = self.path.parent / "media"
        self.media_dir.mkdir()
        self.engine.set_settings({"cache_limit_mb": 32})

    def url(self, name):
        return "https://cdn.wanikani.com/authored-" + name

    def cached(self, url, size=512, used_at=1, reported_size=None):
        path = self.media_dir / (hashlib.sha256(url.encode()).hexdigest() + ".fixture")
        # Sparse files give the planner real byte sizes without a heavy I/O test.
        with path.open("wb") as stream:
            stream.truncate(size)
        self.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)",
            (url, str(path), size if reported_size is None else reported_size, used_at))
        return path

    def subject(self, sid, images=None, audio=None, characters="", when=NOW - 1, lesson=False, level=1):
        item = copy.deepcopy(self.store.subject(sid) or self.store.subject(1))
        item["id"] = sid
        item["data"].update(character_images=images or [], pronunciation_audios=audio or [],
            characters=characters, level=level)
        self.store.put(item)
        assignment = copy.deepcopy(self.store.related("assignment", sid) or self.store.related("assignment", 1))
        assignment["id"] = sid + 50000
        assignment["data"].update(subject_id=sid, available_at=stamp(when),
            started_at=None if lesson else stamp(NOW - 86400), unlocked_at=stamp(NOW - 86400),
            burned_at=None, hidden=False)
        # Keep one assignment per authored subject to make priority assertions explicit.
        self.store.execute("DELETE FROM resources WHERE kind='assignment' AND CAST(json_extract(body,'$.data.subject_id') AS INTEGER)=?", (sid,))
        self.store.put(assignment)
        return item

    def active(self, ids):
        self.store.save_session({"id": "authored-active", "mode": "reviews", "phase": "question", "index": 0,
            "queue": [{"subject_id": sid, "done": False} for sid in ids]})

    def plan(self, **kwargs):
        return build(self.engine, self.media_dir, **kwargs)


class MediaPlanTests(MediaFixture, unittest.TestCase):
    def test_build_is_read_only_and_prefers_a_cached_alternate_radical_image(self):
        preferred, alternate = self.url("preferred.svg"), self.url("alternate.png")
        self.subject(1, images=[{"url": preferred}, {"url": alternate}])
        self.cached(alternate)
        self.active([1])
        before = list(self.store.db.iterdump())
        plan = self.plan()
        self.assertTrue(plan.complete)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertNotIn(preferred, plan.candidates)
        self.assertIn(alternate, plan.candidates)
        self.assertEqual((0, 0, 0), plan.priority(alternate))
        self.assertEqual((), plan.downloads)

    def test_preferred_audio_keeps_cached_fallback_until_success(self):
        preferred, alternate = self.url("voice-one.mp3"), self.url("voice-two.mp3")
        self.subject(2, audio=[{"url": alternate, "metadata": {"voice_actor_id": 2}},
            {"url": preferred, "metadata": {"voice_actor_id": 1}}], characters="山")
        cached = self.cached(alternate)
        plan = self.plan()
        self.assertEqual([preferred], [item.url for item in plan.downloads])
        self.assertLess(plan.priority(preferred), plan.priority(alternate))
        self.assertEqual("accepted", plan.placement(preferred, 400).status)
        self.assertTrue(cached.exists())
        self.assertNotIn(preferred, plan.cached)

    def test_missing_preferred_voice_uses_existing_valid_fallback(self):
        first, cached = self.url("first.mp3"), self.url("cached.mp3")
        self.subject(2, audio=[{"url": first, "metadata": None},
            {"url": cached, "metadata": {"voice_actor_id": 2}}], characters="山")
        self.cached(cached)
        plan = self.plan()
        self.assertEqual({cached}, set(plan.candidates))
        self.assertEqual((), plan.downloads)

    def test_malformed_assets_and_metadata_cannot_abort_planning(self):
        original = self.store.subject(2)
        valid = self.url("valid.mp3")
        changes = [
            {"character_images": None}, {"character_images": 17}, {"character_images": [None, 4, "bad"]},
            {"pronunciation_audios": None}, {"pronunciation_audios": 17},
            {"pronunciation_audios": [None, 4, "bad", {"url": None}]},
            {"pronunciation_audios": [{"url": valid, "metadata": None}]},
            {"pronunciation_audios": [{"url": valid, "metadata": "bad"}]},
            {"pronunciation_audios": [{"url": valid, "metadata": {"voice_actor_id": []}}]},
        ]
        for fields in changes:
            with self.subTest(fields=fields):
                item = copy.deepcopy(original)
                item["data"].update(fields)
                self.store.put(item)
                self.assertTrue(self.plan().complete)

    def test_invalid_first_asset_does_not_hide_later_valid_asset(self):
        valid = self.url("usable.svg")
        self.subject(1, images=[{"url": None}, {"url": "http://wanikani.com/insecure.svg"}, {"url": valid}])
        self.assertEqual([valid], [item.url for item in self.plan().downloads])

    def test_only_supported_account_media_urls_are_candidates(self):
        for value in (None, 3, "", "https://wanikani.com:bad/file", "https://wanikani.com:444/file",
                "https://wanikani.com.evil.example/file", "https://user:password@wanikani.com/file",
                "http://wanikani.com/file", "file:///tmp/file", "https://wanikani.com/has space",
                "https://wanikani.com/line\nbreak", "https://wanikani.com/file#fragment"):
            with self.subTest(value=value):
                self.assertFalse(valid_url(value))
        for value in (self.url("valid.svg"), "https://wanikani.com/file", "https://example.cloudfront.net/audio.mp3?version=2"):
            self.assertTrue(valid_url(value))

    def test_hidden_and_inaccessible_media_cannot_be_prefetched_or_protected(self):
        urls = [self.url(str(sid) + ".svg") for sid in (1, 2, 3, 4)]
        for sid, url in zip((1, 2, 3, 4), urls):
            self.subject(sid, images=[{"url": url}], level=4 if sid == 4 else 1)
            self.cached(url)
        item = self.store.subject(2)
        item["data"]["hidden_at"] = stamp(NOW)
        self.store.put(item)
        assignment = self.store.related("assignment", 3)
        assignment["data"]["hidden"] = True
        self.store.put(assignment)
        user = self.store.get("user")
        user["data"]["subscription"]["type"] = "recurring"
        user["data"]["subscription"]["period_ends_at"] = stamp(NOW - 1)
        self.store.set("user", user)
        plan = self.plan()
        self.assertEqual({urls[0]}, set(plan.candidates))
        self.assertTrue(all(plan.priority(url) == UNREFERENCED for url in urls[1:]))
        user["data"]["subscription"]["max_level_granted"] = 0
        self.store.set("user", user)
        self.assertEqual({}, self.plan().candidates)

    def test_boolean_zero_negative_or_text_levels_are_never_accessible(self):
        url = self.url("restricted.svg")
        for level in (True, False, 0, -1, "1", 1.0, None):
            with self.subTest(level=level):
                self.subject(1, images=[{"url": url}], level=level)
                self.assertNotIn(url, self.plan().candidates)

    def test_pending_graded_subject_is_still_available_for_active_practice_media(self):
        url = self.url("pending.svg")
        self.subject(1, images=[{"url": url}])
        self.store.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)",
            ("authored-pending", "review", 1, "pending", "{}", stamp(NOW), "fixture"))
        self.active([1])
        plan = self.plan()
        self.assertEqual((0, 0, 0), plan.priority(url))
        self.assertEqual("ready", plan.admission(url).status)

    def test_current_required_images_beat_current_audio_and_future_prefetch(self):
        current_image, current_audio, future = (self.url(name) for name in ("current.svg", "current.mp3", "future.mp3"))
        self.subject(1, images=[{"url": current_image}], lesson=True)
        self.subject(2, audio=[{"url": current_audio}], characters="山")
        self.subject(3, audio=[{"url": future}], characters="川", when=NOW + 7 * 86400)
        plan = self.plan()
        self.assertLess(plan.priority(current_image), plan.priority(current_audio))
        self.assertLess(plan.priority(current_audio), plan.priority(future))

    def test_full_cache_rejects_equal_priority_future_admission_without_churn(self):
        for sid in range(100, 105):
            url = self.url(str(sid) + ".mp3")
            self.subject(sid, audio=[{"url": url}], characters="山", when=NOW + 7 * 86400)
            if sid < 104:
                self.cached(url, 8 * MIB, used_at=sid)
        plan = self.plan()
        incoming = self.url("104.mp3")
        self.assertEqual("skipped_budget", plan.admission(incoming).status)
        self.assertEqual("skipped_budget", plan.placement(incoming, 1).status)
        self.assertEqual((), plan.evictions())
        self.assertTrue(all(item.path.exists() for item in plan.cached.values()))

    def test_validated_stronger_download_can_replace_weaker_cache_only_after_success(self):
        for sid in range(100, 104):
            url = self.url(str(sid) + ".mp3")
            self.subject(sid, audio=[{"url": url}], characters="山", when=NOW + 7 * 86400)
            self.cached(url, 8 * MIB, used_at=sid)
        incoming = self.url("required.svg")
        self.subject(1, images=[{"url": incoming}])
        self.active([1])
        plan = self.plan()
        self.assertEqual(MAX_FILE_BYTES, plan.admission(incoming).max_bytes)
        decision = plan.placement(incoming, 128 * 1024)
        self.assertEqual("accepted", decision.status)
        self.assertEqual([self.url("100.mp3")], [item.url for item in decision.evictions])
        self.assertTrue(all(item.path.exists() for item in decision.evictions))
        self.assertNotIn(incoming, plan.cached)
        stored = self.cached(incoming, 128 * 1024)
        plan.remember(incoming, stored, NOW)
        for item in decision.evictions:
            plan.forget(item.url)
        self.assertLessEqual(sum(item.size for item in plan.cached.values()), plan.limit_bytes)

    def test_strict_limit_still_applies_when_all_images_are_required(self):
        urls = []
        for sid in range(100, 105):
            url = self.url(str(sid) + ".svg")
            urls.append(url)
            self.subject(sid, images=[{"url": url}])
            self.cached(url, 8 * MIB, used_at=sid)
        self.active(list(range(100, 105)))
        plan = self.plan()
        self.assertEqual([urls[-1]], [item.url for item in plan.evictions()])
        remaining = sum(item.size for url, item in plan.cached.items() if url != urls[-1])
        self.assertEqual(plan.limit_bytes, remaining)

    def test_shared_url_inherits_the_strongest_subject_priority(self):
        shared = self.url("shared.svg")
        self.subject(1, images=[{"url": shared}])
        self.subject(2, images=[{"url": shared}], when=NOW + 7 * 86400)
        self.active([1])
        plan = self.plan()
        self.assertEqual((0, 0, 0), plan.priority(shared))
        self.assertEqual(1, len(plan.candidates))

    def test_shared_owned_file_is_charged_once_and_cannot_be_evicted_through_a_weaker_alias(self):
        strong, alias = self.url("required.svg"), self.url("stale-alias.svg")
        self.subject(1, images=[{"url": strong}])
        shared = self.cached(strong, 8 * MIB)
        self.store.execute("INSERT INTO media VALUES(?,?,?,?)", (alias, str(shared), 8 * MIB, 0))
        self.active([1])
        for sid in range(100, 104):
            url = self.url(str(sid) + ".mp3")
            self.subject(sid, audio=[{"url": url}], characters="山", when=NOW + 7 * 86400)
            if sid < 103:
                self.cached(url, 8 * MIB, used_at=sid)
        plan = self.plan()
        self.assertEqual((), plan.evictions())
        self.assertEqual("skipped_budget", plan.admission(self.url("103.mp3")).status)
        self.assertTrue(shared.exists())

    def test_content_length_never_authorizes_an_oversized_actual_body(self):
        url = self.url("incoming.mp3")
        self.subject(2, audio=[{"url": url}], characters="山")
        plan = self.plan()
        self.assertEqual(MAX_FILE_BYTES, plan.admission(url, "1").max_bytes)
        self.assertEqual("too_large", plan.placement(url, MAX_FILE_BYTES + 1).status)
        for hint in (-1, "bad", "-1", [], {}, True, "１２"):
            self.assertEqual("ready", plan.admission(url, hint).status)
        self.assertEqual("too_large", plan.admission(url, str(MAX_FILE_BYTES + 1)).status)
        for size in (True, -1, 0, "100", None):
            self.assertEqual("invalid", plan.placement(url, size).status)

    def test_actual_budget_cap_is_smaller_than_eight_megabytes_when_needed(self):
        cached, incoming = self.url("existing.svg"), self.url("incoming.mp3")
        self.subject(1, images=[{"url": cached}])
        self.cached(cached, 31 * MIB)
        self.subject(2, audio=[{"url": incoming}], characters="山")
        plan = self.plan()
        self.assertEqual(MIB, plan.admission(incoming).max_bytes)
        self.assertEqual("skipped_budget", plan.admission(incoming, MIB + 1).status)
        self.assertEqual("skipped_budget", plan.placement(incoming, MIB + 1).status)

    def test_inventory_uses_real_sizes_and_never_authorizes_unowned_or_symlink_deletion(self):
        url = self.url("real.mp3")
        self.cached(url, 8 * MIB, reported_size=1)
        outside = self.path.parent / "outside.fixture"
        outside.write_bytes(b"leave this file alone")
        symlink = self.media_dir / "link.fixture"
        symlink.symlink_to(outside)
        directory = self.media_dir / "directory.fixture"
        directory.mkdir()
        bad_paths = [outside, symlink, directory, self.media_dir / "missing.fixture"]
        for index, path in enumerate(bad_paths):
            self.store.execute("INSERT INTO media VALUES(?,?,?,?)", ("invalid-" + str(index), str(path), MIB, NOW))
        plan = self.plan()
        self.assertEqual(8 * MIB, plan.cached[url].size)
        self.assertEqual({"invalid-" + str(index) for index in range(4)}, set(plan.cleanup_metadata))
        self.assertFalse(any(item.path in bad_paths for item in plan.evictions()))
        self.assertTrue(outside.exists())
        self.assertTrue(symlink.is_symlink())

    def test_partial_or_cancelled_plan_cannot_authorize_destructive_work(self):
        url = self.url("pending.svg")
        self.subject(1, images=[{"url": url}])
        self.cached(self.url("oversized.mp3"), 40 * MIB)
        for args in ({"cancelled": lambda: True}, {"deadline": 0, "clock": lambda: 1}):
            plan = self.plan(**args)
            self.assertFalse(plan.complete)
            self.assertEqual((), plan.downloads)
            self.assertEqual((), plan.evictions())
            self.assertEqual((), plan.cleanup_metadata)
            self.assertEqual("unavailable", plan.admission(url).status)
            self.assertEqual("unavailable", plan.placement(url, 1).status)

    def test_projection_batches_and_preferences_are_bounded(self):
        with self.store.transaction():
            for sid in range(100, 370):
                self.subject(sid, audio=[{"url": self.url(str(sid) + ".mp3")}], characters="山")
        original = self.store.rows
        sizes = []

        def trace(sql, args=()):
            if "AS assets" in sql:
                sizes.append(len(args))
            return original(sql, args)

        with patch.object(self.engine, "settings", wraps=self.engine.settings) as settings, \
                patch.object(self.engine, "max_level", wraps=self.engine.max_level) as maximum, \
                patch.object(self.store, "rows", side_effect=trace), \
                patch.object(self.store, "subject", side_effect=AssertionError("No full subject decoding")):
            plan = self.plan()
        self.assertTrue(plan.complete)
        self.assertGreater(len(sizes), 1)
        self.assertTrue(all(0 < size <= PROJECTION_BATCH for size in sizes))
        self.assertEqual(1, settings.call_count)
        self.assertEqual(1, maximum.call_count)


if __name__ == "__main__":
    unittest.main()
