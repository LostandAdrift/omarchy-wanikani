"""Lossless mixed-format replies and process crashes at their atomic boundary."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import Mock, patch
import zlib

from test_backend import Engine, EngineFixture, NOW, Store, UserError, populate, stamp
from wanikani import command_codec as codec


class CommandCodecTests(unittest.TestCase):
    def test_large_unicode_reply_round_trips_exact_json_text(self):
        text = json.dumps({"subject": {"characters": "山", "mnemonic": "Authored 日本語. " * 300},
            "feedback": {"answer": "さん", "correct": False}, "revision": 123,
            "session_epoch": "fixture-epoch"}, ensure_ascii=False, indent=2) + "\n"
        encoded = codec.encode_text(text)
        self.assertIsInstance(encoded, bytes)
        self.assertTrue(encoded.startswith(codec.MAGIC))
        self.assertLessEqual(len(encoded), len(text.encode("utf-8")) - codec.MIN_SAVING)
        self.assertEqual(text, codec.decode_text(encoded))
        self.assertEqual(json.loads(text), codec.decode(encoded))

    def test_small_legacy_and_above_cap_text_stay_unchanged(self):
        text = '{ "saved" : true }\n'
        self.assertEqual(text, codec.encode_text(text))
        self.assertEqual(text, codec.decode_text(text))
        self.assertEqual({"saved": True}, codec.decode(text))
        large = json.dumps({"authored": "sample " * 500})
        with patch.object(codec, "MAX_RAW_BYTES", 1024):
            self.assertEqual(large, codec.encode_text(large))
        self.assertEqual(large, codec.decode_text(large))

    def test_no_savings_keeps_valid_legacy_json(self):
        text = json.dumps({"authored": "sample " * 500})
        compress = zlib.compress
        # A valid uncompressed DEFLATE stream models a payload with no savings.
        with patch.object(codec.zlib, "compress", side_effect=lambda raw, level: compress(raw, 0)):
            self.assertEqual(text, codec.encode_text(text))

    def test_invalid_versions_lengths_streams_and_utf8_fail_without_content_in_error(self):
        encoded = codec.encode({"AUTHORED_PRIVATE_NOTE": "secret fixture " * 200})
        malformed = [b"WKJR", b"WKJR\x02" + encoded[5:], encoded[:-1], encoded + b"trailing",
            encoded + encoded, encoded[:-1] + bytes([encoded[-1] ^ 255]),
            codec.MAGIC + struct.pack(">I", 0) + zlib.compress(b"{}"),
            codec.MAGIC + struct.pack(">I", codec.MAX_RAW_BYTES + 1) + zlib.compress(b"{}"),
            codec.MAGIC + struct.pack(">I", 1000) + zlib.compress(b"{}"),
            codec.MAGIC + struct.pack(">I", 2) + zlib.compress(b"\xff\xfe"),
            '{"AUTHORED_PRIVATE_NOTE": "malformed', None]
        for value in malformed:
            with self.subTest(kind=type(value).__name__), self.assertRaises(codec.UnreadableReply) as error:
                codec.decode(value)
            self.assertNotIn("AUTHORED_PRIVATE_NOTE", str(error.exception))
        with patch.object(codec, "MAX_COMPRESSED_BYTES", 1), \
                patch.object(codec.zlib, "decompressobj", side_effect=AssertionError("Decoder ignored input bound")), \
                self.assertRaises(codec.UnreadableReply):
            codec.decode(encoded)

    def test_false_size_bomb_has_bounded_output_allocation(self):
        bomb = codec.MAGIC + struct.pack(">I", 1) + zlib.compress(b"x" * (16 * 1024 * 1024))
        tracemalloc.start()
        try:
            with self.assertRaises(codec.UnreadableReply):
                codec.decode(bomb)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)


class JournalFormatTests(EngineFixture, unittest.TestCase):
    def make_large_subject(self):
        item = self.store.subject(2)
        item["data"]["meaning_mnemonic"] = "Independently authored compression fixture. " * 200
        self.store.put(item)

    def test_mixed_text_blob_and_small_ack_survive_restart_without_migration(self):
        self.make_large_subject()
        first = self.engine.command("blob-start", "start", {"mode": "practice", "subjects": [2], "limit": 1})
        self.engine.command("small-draft", "draft", {"text": "kept draft"})
        self.store.execute("INSERT INTO commands VALUES(?,?)", ("legacy-start", json.dumps(first, ensure_ascii=False)))
        before = {row["id"]: row["body"] for row in self.store.rows("SELECT * FROM commands")}
        self.assertIsInstance(before["blob-start"], bytes)
        self.assertIsInstance(before["legacy-start"], str)
        self.assertIsInstance(before["small-draft"], str)
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        with patch.object(self.engine, "start", side_effect=AssertionError("Duplicate start ran again")):
            for rid in ("blob-start", "legacy-start"):
                self.assertEqual(first, self.engine.command(rid, "start", {"mode": "lessons"}))
        self.assertEqual("kept draft", self.store.session()["draft"])
        self.assertEqual(before, {row["id"]: row["body"] for row in self.store.rows("SELECT * FROM commands")})

    def test_encoder_failure_rolls_back_answer_event_revision_and_reply_together(self):
        self.make_large_subject()
        self.engine.start("practice", 1, [2])
        before = list(self.store.db.iterdump())
        with patch.object(codec.zlib, "compress", side_effect=OSError("Authored compressor interruption")), \
                self.assertRaises(OSError):
            self.engine.command("interrupted-answer", "answer", {"text": "wrong"})
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_unreadable_saved_reply_never_reexecutes_or_deletes_its_id(self):
        self.engine.start("practice", 1, [2])
        broken = codec.MAGIC + struct.pack(">I", 99) + b"AUTHORED_PRIVATE_NOTE"
        self.store.execute("INSERT INTO commands VALUES(?,?)", ("recorded-command", broken))
        before = list(self.store.db.iterdump())
        with patch.object(self.engine, "answer", side_effect=AssertionError("Unreadable ID was rerun")):
            for _ in range(2):
                with self.assertRaises(UserError) as error:
                    self.engine.command("recorded-command", "answer", {"text": "wrong"})
                self.assertEqual("reply_unavailable", error.exception.code)
                self.assertNotIn("AUTHORED_PRIVATE_NOTE", str(error.exception))
                self.assertIn("Close and resume", str(error.exception))
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual("question", self.engine.command("safe-resume", "start", {"mode": "resume"})["phase"])


CRASH = r'''
import os, sys
from pathlib import Path
from wanikani.store import Store
from wanikani.engine import Engine
from wanikani import command_codec
path, boundary = Path(sys.argv[1]), sys.argv[2]
store = Store(path)
engine = Engine(store, clock=lambda: 1788550000)
if boundary == 'encoded':
    original = command_codec.encode
    def encode(value):
        result = original(value)
        os._exit(77 if isinstance(result, bytes) else 78)
    command_codec.encode = encode
if boundary == 'inserted':
    original = store.execute
    def execute(sql, args=()):
        result = original(sql, args)
        if sql.startswith('INSERT INTO commands'):
            os._exit(77 if isinstance(args[1], bytes) else 78)
        return result
    store.execute = execute
engine.command('crash-advance', 'advance', {})
os._exit(77)
'''


class CompressedReplyCrashTests(unittest.TestCase):
    def test_process_crashes_during_encoding_insertion_and_after_commit(self):
        root = Path(__file__).resolve().parents[1]
        for boundary in ("encoded", "inserted", "committed"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "fixture.sqlite3"
                store = Store(path)
                populate(store, NOW)
                for assignment in store.all("assignment"):
                    if assignment["data"]["subject_id"] not in (1, 2):
                        assignment["data"]["available_at"] = stamp(NOW + 86400)
                        store.put(assignment)
                item = store.subject(2)
                item["data"]["meaning_mnemonic"] = "Authored large crash-boundary mnemonic. " * 200
                store.put(item)
                engine = Engine(store, clock=lambda: NOW)
                shuffle = Mock(shuffle=lambda rows: rows.sort(key=lambda row: int(row["subject_id"])))
                with patch("wanikani.engine.random.SystemRandom", return_value=shuffle):
                    engine.start("reviews", 2)
                engine.answer("ground")
                original_session = store.session()
                store.close()
                process = subprocess.run([sys.executable, "-B", "-c", CRASH, str(path), boundary],
                    env={**os.environ, "PYTHONPATH": str(root / "backend")}, capture_output=True, timeout=10)
                self.assertEqual(77, process.returncode, process.stderr.decode())
                store = Store(path)
                engine = Engine(store, clock=lambda: NOW)
                try:
                    if boundary != "committed":
                        self.assertEqual(original_session, store.session())
                        self.assertEqual([], store.rows("SELECT * FROM commands"))
                        self.assertEqual([], store.rows("SELECT * FROM outbox"))
                        engine.command("crash-advance", "advance", {})
                    before = list(store.db.iterdump())
                    with patch.object(engine, "advance", side_effect=AssertionError("Committed subject advanced twice")):
                        reply = engine.command("crash-advance", "advance", {})
                    self.assertEqual(("question", 1), (reply["phase"], reply["completed"]))
                    self.assertEqual(2, reply["subject"]["id"])
                    self.assertIsInstance(store.rows("SELECT body FROM commands")[0][0], bytes)
                    self.assertEqual(1, store.rows("SELECT COUNT(*) FROM outbox")[0][0])
                    self.assertEqual(1, store.rows("SELECT COUNT(*) FROM events WHERE kind='subject_complete'")[0][0])
                    self.assertEqual(before, list(store.db.iterdump()))
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
