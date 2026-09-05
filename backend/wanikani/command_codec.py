"""Lossless, versioned storage for large durable command acknowledgments.

Legacy TEXT and small replies keep their exact JSON text. New large replies may
use a SQLite BLOB: WKJR, version byte 1, unsigned big-endian raw UTF-8 length,
then one zlib stream. This is storage compression, not encryption or pruning.
"""
import json
import struct
import zlib


MAGIC = b"WKJR\x01"
HEADER_BYTES = len(MAGIC) + 4
THRESHOLD = 1024
MIN_SAVING = 64
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_COMPRESSED_BYTES = MAX_RAW_BYTES


class UnreadableReply(ValueError):
    """A durable ID exists, but its saved reply cannot be safely decoded."""


def encode_text(text):
    """Preserve exact JSON text, compressing only when clearly beneficial."""
    raw = text.encode("utf-8")
    if not THRESHOLD <= len(raw) <= MAX_RAW_BYTES:
        return text
    payload = zlib.compress(raw, 1)
    encoded = MAGIC + struct.pack(">I", len(raw)) + payload
    return encoded if len(encoded) <= len(raw) - MIN_SAVING else text


def encode(value):
    return encode_text(json.dumps(value, ensure_ascii=False))


def decode_text(value):
    """Return original text; never use an unbounded decompression or flush."""
    if isinstance(value, str):
        return value
    if (not isinstance(value, bytes) or len(value) < HEADER_BYTES
            or not value.startswith(MAGIC) or len(value) - HEADER_BYTES > MAX_COMPRESSED_BYTES):
        raise UnreadableReply("The saved command reply has an unsupported format.")
    expected = struct.unpack(">I", value[len(MAGIC):HEADER_BYTES])[0]
    if not 0 < expected <= MAX_RAW_BYTES:
        raise UnreadableReply("The saved command reply exceeds its decoding limits.")
    try:
        stream = zlib.decompressobj()
        raw = stream.decompress(value[HEADER_BYTES:], expected + 1)
        if len(raw) != expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
            raise UnreadableReply("The saved command reply is incomplete or invalid.")
        return raw.decode("utf-8")
    except (UnicodeError, zlib.error):
        raise UnreadableReply("The saved command reply is invalid.") from None


def decode(value):
    try:
        return json.loads(decode_text(value))
    except (ValueError, TypeError, RecursionError):
        # Never include JSON contents, decompressor errors or personal notes in
        # an exception. The caller retains the ID and must not rerun the effect.
        raise UnreadableReply("The saved command reply cannot be read safely.") from None
