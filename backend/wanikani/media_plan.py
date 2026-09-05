"""Bounded media selection and budget decisions, without filesystem mutations.

``build`` reads one settings/access snapshot, indexed schedule fields, and asset
projections in groups of 128 subjects. A complete plan exposes ordered missing
``downloads`` and separate ``cleanup_metadata`` URLs for absent/unowned files.

For each download, call ``admission(url, content_length)`` and read at most
``max_bytes + 1`` bytes. Content-Length is only an early rejection hint. After
validating the MIME and actual bytes, ``placement(url, actual_size)`` proposes
weaker cached files to evict. Neither call changes files, rows, or the plan.
Only after successful persistence should the caller ``remember`` the new file
and ``forget`` successfully removed entries. A failed download leaves existing
media intact. ``skipped_budget`` is distinct from a network failure.

``evictions`` also enforces a reduced user limit without unlimited pinning.
Incomplete/cancelled plans never authorize downloads, eviction, or cleanup.
The caller retains its eight-second, 40-success and 60-attempt limits; supply
the same monotonic deadline here so planning counts toward that budget.
"""
import json
import math
import re
import stat
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .common import epoch


MAX_FILE_BYTES = 8 * 1024 * 1024
PROJECTION_BATCH = 128
MAX_SUBJECTS = 12000
SUBJECTS = "('radical','kanji','vocabulary','kana_vocabulary')"
UNREFERENCED = (4, 0, 0)
MIMES = {
    "image": {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg"},
    "audio": {"audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/webm": ".webm"},
}
OWNED_NAME = re.compile(r"(?:[0-9a-f]{64}\.(?:svg|png|jpg|mp3|ogg|m4a|webm)(?:\.tmp)?|download-[a-z0-9_]{8}\.tmp)\Z")


@dataclass(frozen=True)
class Candidate:
    url: str
    subject_id: int
    kind: str
    priority: tuple
    order: tuple


@dataclass(frozen=True)
class CachedFile:
    url: str
    path: Path
    size: int
    used_at: float
    registered: bool = True


@dataclass(frozen=True)
class Admission:
    status: str
    max_bytes: int = 0


@dataclass(frozen=True)
class Placement:
    status: str
    evictions: tuple = ()


def valid_url(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False
    if any(character.isspace() or ord(character) < 32 for character in value):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and not parsed.fragment
            and (host == "wanikani.com" or host.endswith(".wanikani.com") or host.endswith(".cloudfront.net")))
    except ValueError:
        return False


def assets(value):
    return [item for item in value if isinstance(item, dict) and valid_url(item.get("url"))] if isinstance(value, list) else []


def _owned_file(directory, url, value, used_at=0, allow_empty=False):
    if not isinstance(value, str):
        return None
    path = Path(value)
    if path.parent != directory:
        return None
    try:
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_size <= 0 and not allow_empty):
            return None
    except (OSError, ValueError):
        return None
    if type(used_at) not in (int, float) or not math.isfinite(used_at):
        used_at = 0
    # File size is authoritative when stale metadata understates disk usage.
    return CachedFile(url, path, info.st_size, used_at)


def _length_hint(value):
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and value and value.isascii() and value.isdecimal():
        return int(value) if len(value) <= 20 else MAX_FILE_BYTES + 1
    return None


class MediaPlan:
    def __init__(self, directory, limit_bytes):
        self.directory = directory
        self.limit_bytes = limit_bytes
        self.complete = False
        self.checked_subjects = 0
        self.cached = {}
        self.candidates = {}
        self.priorities = {}
        self._cleanup = []

    @property
    def cleanup_metadata(self):
        return tuple(self._cleanup) if self.complete else ()

    @property
    def orphans(self):
        return tuple(item for item in self.cached.values() if not item.registered) if self.complete else ()

    @property
    def downloads(self):
        if not self.complete:
            return ()
        return tuple(sorted((candidate for url, candidate in self.candidates.items() if url not in self.cached),
            key=lambda candidate: (candidate.priority, candidate.order, candidate.url)))

    def priority(self, url):
        return self.priorities.get(url, UNREFERENCED)

    def _files(self):
        # A stale database can associate multiple URLs with one owned file.
        # Charge it once, protect its strongest reference, and evict all aliases
        # together so removing a weaker alias cannot break an active image.
        by_path = {}
        for item in self.cached.values():
            by_path.setdefault(item.path, []).append(item)
        return [(min(self.priority(item.url) for item in items), max(item.used_at for item in items),
            max(item.size for item in items), tuple(sorted(items, key=lambda item: item.url)))
            for items in by_path.values()]

    def admission(self, url, content_length=None):
        if not self.complete or url not in self.candidates:
            return Admission("unavailable")
        if url in self.cached:
            return Admission("cached")
        priority = self.priority(url)
        # Existing equally useful files win. Prefetch cannot rotate a full
        # category through download/eviction on each synchronization pass.
        reserved = sum(size for rank, _, size, _ in self._files() if rank <= priority)
        allowance = min(MAX_FILE_BYTES, max(0, self.limit_bytes - reserved))
        hint = _length_hint(content_length)
        if hint is not None and hint > MAX_FILE_BYTES:
            return Admission("too_large")
        if not allowance or (hint is not None and hint > allowance):
            return Admission("skipped_budget")
        return Admission("ready", allowance)

    def placement(self, url, actual_size):
        admission = self.admission(url)
        if admission.status != "ready":
            return Placement(admission.status)
        if type(actual_size) is not int or actual_size <= 0:
            return Placement("invalid")
        if actual_size > MAX_FILE_BYTES:
            return Placement("too_large")
        if actual_size > admission.max_bytes:
            return Placement("skipped_budget")
        files = self._files()
        remaining = sum(size for _, _, size, _ in files) + actual_size
        weaker = [group for group in files if group[0] > self.priority(url)]
        weaker.sort(key=lambda group: (tuple(-part for part in group[0]), group[1], str(group[3][0].path)))
        evictions = []
        for _, _, size, items in weaker:
            if remaining <= self.limit_bytes:
                break
            evictions.extend(items)
            remaining -= size
        return Placement("accepted", tuple(evictions))

    def evictions(self):
        if not self.complete:
            return ()
        kept, used = set(), 0
        files = self._files()
        for _, _, size, items in sorted(files, key=lambda group: (group[0], -group[1], str(group[3][0].path))):
            if used + size <= self.limit_bytes:
                kept.add(items[0].path)
                used += size
        ordered = sorted(files, key=lambda group: (tuple(-part for part in group[0]), group[1], str(group[3][0].path)))
        return tuple(item for _, _, _, items in ordered if items[0].path not in kept for item in items)

    def remember(self, url, path, used_at):
        item = _owned_file(self.directory, url, str(path), used_at)
        if not item or self.placement(url, item.size).status != "accepted":
            raise ValueError("Only a successfully stored, admitted media file can be remembered.")
        self.cached[url] = item

    def forget(self, url):
        self.cached.pop(url, None)

    def _retain(self, url, priority):
        self.priorities[url] = min(self.priorities.get(url, UNREFERENCED), priority)

    def _candidate(self, url, subject_id, kind, priority, due):
        self._retain(url, priority)
        candidate = Candidate(url, subject_id, kind, priority, (due, subject_id))
        previous = self.candidates.get(url)
        if previous is None or (candidate.priority, candidate.order) < (previous.priority, previous.order):
            self.candidates[url] = candidate


def _active_subjects(store):
    active = {}
    references = [store.get(name) for name in ("active_session", "graded_session", "practice_session", "reviews_session", "lessons_session")]
    for context, reference in enumerate(references):
        session = store.session(reference) if isinstance(reference, str) else None
        if not session or session.get("phase") == "complete":
            continue
        queue = session.get("queue")
        if not isinstance(queue, list):
            continue
        current = session.get("index", 0)
        current = current if type(current) is int and current >= 0 else 0
        for index, entry in enumerate(queue[:20]):
            if not isinstance(entry, dict) or entry.get("done") is True or type(entry.get("subject_id")) is not int:
                continue
            position = index - current if index >= current else 20 + index
            subject_id = entry["subject_id"]
            active[subject_id] = min(active.get(subject_id, (99, 99)), (context, position))
    return active


def _schedule(row, now):
    due, unlocked = epoch(row["available"]), epoch(row["unlocked"])
    if row["burned"] is None and due is not None and due <= now:
        category = 0
    elif row["started"] is None and unlocked is not None and unlocked <= now:
        category = 1
    elif row["burned"] is None and due is not None and due <= now + 86400:
        category = 2
    else:
        category = 3
    return category, due if due is not None else float("inf")


def build(engine, media_dir, deadline=None, cancelled=lambda: False, clock=time.monotonic):
    store = engine.store
    settings, maximum, now = engine.settings(), engine.max_level(), engine.now()
    limit = settings.get("cache_limit_mb", 256)
    limit = int(limit) if type(limit) in (int, float) and math.isfinite(limit) and 32 <= limit <= 1024 else 32
    plan = MediaPlan(Path(media_dir).absolute(), limit * 1024 * 1024)
    preferred = settings.get("voice_actor_id", 1)
    preferred = preferred if type(preferred) is int and preferred > 0 else 1
    deadline = clock() + 8 if deadline is None else deadline

    def stopped():
        return cancelled() or clock() >= deadline

    if stopped():
        return plan
    for row in store.rows("SELECT url,path,used_at FROM media"):
        if stopped():
            return plan
        item = _owned_file(plan.directory, row["url"], row["path"], row["used_at"])
        if item:
            plan.cached[item.url] = item
        else:
            plan._cleanup.append(row["url"])
    registered_paths = {item.path for item in plan.cached.values()}
    try:
        for path in plan.directory.iterdir():
            if stopped():
                return plan
            if path in registered_paths or not OWNED_NAME.fullmatch(path.name):
                continue
            item = _owned_file(plan.directory, "orphan:" + path.name, str(path), allow_empty=True)
            if item:
                plan.cached[item.url] = CachedFile(item.url, item.path, item.size, item.used_at, False)
    except OSError:
        return plan
    active = _active_subjects(store)
    rows = store.rows("""SELECT CAST(s.id AS INTEGER) AS id,json_extract(s.body,'$.data.level') AS level,
      json_extract(a.body,'$.data.started_at') AS started,json_extract(a.body,'$.data.unlocked_at') AS unlocked,
      json_extract(a.body,'$.data.available_at') AS available,json_extract(a.body,'$.data.burned_at') AS burned
      FROM resources s INDEXED BY resource_search_identity
      LEFT JOIN resources a INDEXED BY resource_assignment_schedule
        ON a.kind='assignment' AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
      WHERE s.kind IN """ + SUBJECTS + """ AND json_type(s.body,'$.data.level')='integer'
        AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
        AND json_extract(s.body,'$.data.hidden_at') IS NULL
        AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0 LIMIT ?""", (maximum, MAX_SUBJECTS + 1))
    if len(rows) > MAX_SUBJECTS or stopped():
        return plan
    schedules = {}
    for row in rows:
        if type(row["level"]) is int and 1 <= row["level"] <= maximum and row["id"] > 0:
            schedules[row["id"]] = min(schedules.get(row["id"], (99, float("inf"))), _schedule(row, now))
    identifiers = list(schedules)
    for offset in range(0, len(identifiers), PROJECTION_BATCH):
        if stopped():
            return plan
        chunk = identifiers[offset:offset + PROJECTION_BATCH]
        projections = store.rows("""SELECT CAST(id AS INTEGER) AS id,
          json_extract(body,'$.data.character_images','$.data.pronunciation_audios','$.data.characters') AS assets
          FROM resources INDEXED BY resource_numeric_id WHERE kind IN """ + SUBJECTS
          + " AND CAST(id AS INTEGER) IN (" + ",".join("?" for _ in chunk) + ")", chunk)
        for row in projections:
            if stopped():
                return plan
            images, sounds, characters = json.loads(row["assets"])
            images, sounds = assets(images), assets(sounds)
            subject_id = row["id"]
            category, due = schedules[subject_id]
            if images and not (isinstance(characters, str) and characters.strip()):
                # A usable cached alternate already satisfies offline study.
                selected = next((item for item in images if item["url"] in plan.cached), images[0])
                priority = (0, *active[subject_id]) if subject_id in active else (1, category, 0) if category < 3 else (3, 0, 0)
                plan._candidate(selected["url"], subject_id, "image", priority, due)
            if sounds:
                def actor(item):
                    metadata = item.get("metadata")
                    value = metadata.get("voice_actor_id") if isinstance(metadata, dict) else None
                    return value if type(value) is int and value > 0 else None

                preferred_sound = next((item for item in sounds if actor(item) == preferred), None)
                cached_sound = next((item for item in sounds if item["url"] in plan.cached), None)
                selected = preferred_sound or cached_sound or sounds[0]
                priority = (2, 0, 0) if subject_id in active else (2, category + 1, 0) if category < 3 else (3, 0, 0)
                plan._candidate(selected["url"], subject_id, "audio", priority, due)
                if cached_sound and cached_sound is not selected:
                    plan._retain(cached_sound["url"], (*priority[:2], 1))
            plan.checked_subjects += 1
    plan.complete = not stopped()
    return plan
