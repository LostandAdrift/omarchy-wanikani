"""Mock-only downloads, byte limits, cancellation, and cache retention."""
import hashlib
import http.client
import io
import os
import sqlite3
import subprocess
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from test_backend import NOW, UserError
from test_media_plan import MediaFixture, MIB
from wanikani.media_plan import MAX_FILE_BYTES
from wanikani.sync import Synchronizer


class Response:
    def __init__(self, data=b"authored media", mime="audio/mpeg", length=None, error=None, read_hook=lambda: None):
        self.data = io.BytesIO(data)
        self.headers = Message()
        self.headers["Content-Type"] = mime
        if length is not None:
            self.headers["Content-Length"] = str(length)
        self.error, self.read_hook = error, read_hook
        self.read_limits = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        self.read_limits.append(limit)
        self.read_hook()
        if self.error:
            raise self.error
        return self.data.read(limit)


class MediaSyncTests(MediaFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sync = Synchronizer(self.engine, object(), self.media_dir)

    def run_response(self, response):
        with patch("wanikani.sync.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response
            result = self.sync.cache_media()
            return result, factory.return_value.open

    def future_cache(self):
        for sid in range(100, 104):
            url = self.url(str(sid) + ".mp3")
            self.subject(sid, audio=[{"url": url}], characters="山", when=NOW + 7 * 86400)
            self.cached(url, 8 * MIB, used_at=sid)

    def test_success_replaces_only_weaker_media_after_validated_download(self):
        self.future_cache()
        incoming = self.url("required.svg")
        self.subject(1, images=[{"url": incoming}])
        self.active([1])
        result, opened = self.run_response(Response(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"))
        self.assertEqual(1, result["downloaded"])
        self.assertEqual(1, opened.call_count)
        request = opened.call_args.args[0]
        self.assertNotIn("Authorization", request.headers)
        cached = {row["url"]: row for row in self.store.rows("SELECT * FROM media")}
        self.assertIn(incoming, cached)
        self.assertNotIn(self.url("100.mp3"), cached)
        self.assertLessEqual(sum(row["size"] for row in cached.values()), 32 * MIB)
        self.assertTrue(Path(cached[incoming]["path"]).is_file())
        self.assertEqual([], list(self.media_dir.glob("*.tmp")))

    def test_budget_skip_has_no_network_failure_backoff_or_repeated_partial_download(self):
        required, incoming = self.url("required.svg"), self.url("future.mp3")
        self.subject(1, images=[{"url": required}])
        original = self.cached(required, 31 * MIB)
        self.subject(2, audio=[{"url": incoming}], characters="山", when=NOW + 7 * 86400)
        response = Response(b"a" * (MIB + 2))
        result, opened = self.run_response(response)
        self.assertEqual(1, result["skipped_budget"])
        self.assertEqual([MIB + 1], response.read_limits)
        self.assertEqual([], self.store.rows("SELECT * FROM meta WHERE key LIKE 'media_retry_%'"))
        self.assertTrue(original.exists())
        second, opened = self.run_response(Response(b"unused"))
        self.assertEqual(0, second["attempts"])
        self.assertEqual(0, opened.call_count)
        self.assertEqual(1, second["skipped_budget"])

    def test_declared_budget_hint_can_skip_before_body_and_larger_limit_reopens_admission(self):
        required, incoming = self.url("required.svg"), self.url("future.mp3")
        self.subject(1, images=[{"url": required}])
        self.cached(required, 31 * MIB)
        self.subject(2, audio=[{"url": incoming}], characters="山", when=NOW + 7 * 86400)
        response = Response(b"unused", length=2 * MIB)
        first, _ = self.run_response(response)
        self.assertEqual(1, first["skipped_budget"])
        self.assertEqual([], response.read_limits)
        self.engine.set_settings({"cache_limit_mb": 64})
        second, _ = self.run_response(Response(b"a" * (2 * MIB), length=2 * MIB))
        self.assertEqual(1, second["downloaded"])
        self.assertNotIn(incoming, self.sync._media_size_hints)

    def test_understated_length_does_not_bypass_actual_eight_megabyte_cap(self):
        self.subject(2, audio=[{"url": self.url("large.mp3")}], characters="山")
        response = Response(b"a" * (MAX_FILE_BYTES + 2), length=1)
        result, _ = self.run_response(response)
        self.assertEqual(0, result["downloaded"])
        self.assertEqual([MAX_FILE_BYTES + 1], response.read_limits)
        self.assertEqual([], self.store.rows("SELECT * FROM media"))

    def test_wrong_mime_empty_or_truncated_media_never_evict_existing_files(self):
        self.future_cache()
        self.subject(1, images=[{"url": self.url("required.svg")}])
        before = {row["url"]: row["path"] for row in self.store.rows("SELECT * FROM media")}
        cases = [Response(b"wrong kind", "audio/mpeg"), Response(b"", "image/svg+xml"),
            Response(b"short", "image/svg+xml", length=100),
            Response(mime="image/svg+xml", error=http.client.IncompleteRead(b"short", 100))]
        for response in cases:
            with self.subTest(response=response):
                self.store.execute("DELETE FROM meta WHERE key LIKE 'media_retry_%'")
                result, _ = self.run_response(response)
                self.assertEqual(0, result["downloaded"])
                self.assertEqual(before, {row["url"]: row["path"] for row in self.store.rows("SELECT * FROM media")})
                self.assertTrue(all(Path(path).exists() for path in before.values()))

    def test_cancelled_read_never_persists_or_evicts(self):
        self.future_cache()
        self.subject(1, images=[{"url": self.url("required.svg")}])
        before = list(self.store.db.iterdump())
        with self.assertRaises(UserError):
            self.run_response(Response(b"<svg/>", "image/svg+xml", read_hook=self.sync.cancelled.set))
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual([], list(self.media_dir.glob("*.tmp")))
        self.assertIsNone(self.sync._media_plan)

    def test_expired_planning_budget_cannot_trim_an_overfull_cache(self):
        path = self.cached(self.url("large-old.mp3"), 40 * MIB)
        before = list(self.store.db.iterdump())
        ticks = iter((0, 9))
        with patch("wanikani.sync.time.monotonic", side_effect=lambda: next(ticks, 9)), \
                patch.object(self.sync, "download_media") as download:
            result = self.sync.cache_media()
        self.assertFalse(result["complete"])
        download.assert_not_called()
        self.assertTrue(path.exists())
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_failed_database_persistence_removes_only_the_new_file(self):
        self.future_cache()
        incoming = self.url("required.svg")
        self.subject(1, images=[{"url": incoming}])
        before = {row["url"]: row["path"] for row in self.store.rows("SELECT * FROM media")}
        execute = self.store.execute

        def failing_insert(sql, args=()):
            if sql.startswith("INSERT OR REPLACE INTO media"):
                raise sqlite3.OperationalError("Authored disk persistence failure")
            return execute(sql, args)

        with patch.object(self.store, "execute", side_effect=failing_insert), self.assertRaises(sqlite3.OperationalError):
            self.run_response(Response(b"<svg/>", "image/svg+xml"))
        self.assertEqual(before, {row["url"]: row["path"] for row in self.store.rows("SELECT * FROM media")})
        self.assertTrue(all(Path(path).exists() for path in before.values()))
        self.assertFalse((self.media_dir / (hashlib.sha256(incoming.encode()).hexdigest() + ".svg")).exists())

    def test_eviction_failure_cannot_leave_the_new_download_above_the_limit(self):
        self.future_cache()
        incoming = self.url("required.svg")
        self.subject(1, images=[{"url": incoming}])
        blocked = Path(self.store.rows("SELECT path FROM media WHERE url=?", (self.url("100.mp3"),))[0][0])
        unlink = Path.unlink

        def deny_one(path, *args, **kwargs):
            if path == blocked:
                raise PermissionError("Authored undeletable cache fixture")
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=deny_one):
            result, _ = self.run_response(Response(b"<svg/>", "image/svg+xml"))
        self.assertEqual(0, result["downloaded"])
        self.assertEqual(32 * MIB, self.store.rows("SELECT SUM(size) FROM media")[0][0])
        self.assertEqual([], self.store.rows("SELECT * FROM media WHERE url=?", (incoming,)))

    def test_trim_cleans_unowned_metadata_without_touching_external_or_symlink_files(self):
        outside = self.path.parent / "external.fixture"
        outside.write_bytes(b"preserved")
        link = self.media_dir / "link.fixture"
        link.symlink_to(outside)
        for index, path in enumerate((outside, link)):
            self.store.execute("INSERT INTO media VALUES(?,?,?,?)", ("invalid-" + str(index), str(path), 40 * MIB, NOW))
        self.sync.trim_media()
        self.assertEqual([], self.store.rows("SELECT * FROM media"))
        self.assertTrue(outside.exists())
        self.assertTrue(link.is_symlink())

    def test_success_and_attempt_limits_remain_bounded(self):
        with self.store.transaction():
            for sid in range(100, 170):
                self.subject(sid, audio=[{"url": self.url(str(sid) + ".mp3")}], characters="山")
        for succeeds, count in ((True, 40), (False, 60)):
            self.store.execute("DELETE FROM meta WHERE key LIKE 'media_retry_%'")
            with patch("wanikani.sync.time.monotonic", return_value=0), \
                    patch.object(self.sync, "download_media", return_value=succeeds) as download:
                result = self.sync.cache_media()
            self.assertEqual(count, download.call_count)
            self.assertEqual(count, result["attempts"])
            self.assertEqual(count if succeeds else 0, result["downloaded"])

    def test_process_crash_after_atomic_replace_recovers_owned_orphan_before_next_download(self):
        self.future_cache()
        incoming = self.url("crash-required.svg")
        self.subject(1, images=[{"url": incoming}])
        source = """
import os, sys
from pathlib import Path
from unittest.mock import patch
from test_backend import NOW, Engine, Store
from test_media_sync import Response
from wanikani.sync import Synchronizer
store = Store(Path(sys.argv[1]))
sync = Synchronizer(Engine(store, clock=lambda: NOW), object(), Path(sys.argv[2]))
replace = Path.replace
def crash_after_replace(path, target):
    replace(path, target)
    os._exit(73)
with patch('wanikani.sync.urllib.request.build_opener') as opener, patch.object(Path, 'replace', new=crash_after_replace):
    opener.return_value.open.return_value = Response(b'<svg>authored crash fixture</svg>', 'image/svg+xml')
    sync.cache_media()
"""
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(root / "backend"), str(root / "tests")))}
        child = subprocess.run([sys.executable, "-c", source, str(self.path), str(self.media_dir)],
            env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(73, child.returncode, child.stderr)
        orphan = self.media_dir / (hashlib.sha256(incoming.encode()).hexdigest() + ".svg")
        self.assertTrue(orphan.exists())
        self.assertEqual([], self.store.rows("SELECT * FROM media WHERE url=?", (incoming,)))
        self.assertEqual(32 * MIB, self.store.rows("SELECT SUM(size) FROM media")[0][0])
        plan = self.plan()
        self.assertEqual([orphan], [item.path for item in plan.orphans])
        self.assertGreater(sum(item.size for item in plan.cached.values()), 32 * MIB)
        replacement = b"<svg>authored replacement</svg>"
        result, opened = self.run_response(Response(replacement, "image/svg+xml"))
        self.assertEqual(1, opened.call_count)
        self.assertEqual(1, result["downloaded"])
        self.assertEqual(replacement, orphan.read_bytes())
        self.assertEqual((), self.plan().orphans)
        self.assertLessEqual(sum(path.stat().st_size for path in self.media_dir.iterdir()), 32 * MIB)

    def test_orphan_cleanup_only_removes_exact_generated_regular_files_after_complete_plan(self):
        owned = [self.media_dir / ("a" * 64 + ".svg"), self.media_dir / ("b" * 64 + ".mp3.tmp"),
            self.media_dir / "download-a1b2c3d4.tmp"]
        for path in owned:
            path.write_bytes(b"authored orphan")
        owned[-1].write_bytes(b"")
        arbitrary = self.media_dir / "personal-photo.png"
        arbitrary.write_bytes(b"unrelated file")
        external = self.path.parent / ("c" * 64 + ".svg")
        external.write_bytes(b"outside cache")
        link = self.media_dir / ("d" * 64 + ".svg")
        link.symlink_to(external)
        ticks = iter((0, 9))
        with patch("wanikani.sync.time.monotonic", side_effect=lambda: next(ticks, 9)):
            result = self.sync.cache_media()
        self.assertFalse(result["complete"])
        self.assertTrue(all(path.exists() for path in owned))
        self.assertTrue(self.sync.trim_media())
        self.assertTrue(all(not path.exists() for path in owned))
        self.assertEqual(b"unrelated file", arbitrary.read_bytes())
        self.assertEqual(b"outside cache", external.read_bytes())
        self.assertTrue(link.is_symlink())

    def test_undeletable_orphan_stops_admission_instead_of_hiding_physical_bytes(self):
        orphan = self.media_dir / ("e" * 64 + ".mp3")
        orphan.write_bytes(b"authored undeletable orphan")
        self.subject(1, images=[{"url": self.url("required.svg")}])
        with patch.object(Path, "unlink", side_effect=PermissionError("Authored cleanup failure")):
            result, opened = self.run_response(Response(b"<svg/>", "image/svg+xml"))
        self.assertFalse(result["complete"])
        opened.assert_not_called()
        self.assertTrue(orphan.exists())


if __name__ == "__main__":
    unittest.main()
