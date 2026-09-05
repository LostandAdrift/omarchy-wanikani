"""Bounded, asynchronous checks of the content needed for offline study."""
import copy
import json
import threading
import time

from .common import UserError, epoch, stamp
from .engine import BUSY_STATES, SUBJECTS
from .grading import validate_subject_answers
from .media_files import available_file

GROUPS = ("reviews", "lessons", "upcoming_reviews")
MAX_SCHEDULE = 12000
CONTENT_BATCH = 128
SCHEDULE_FIELDS = """CAST(a.id AS INTEGER) AS assignment_id,
        json_extract(s.body,'$.data.level') AS level,
        json_extract(a.body,'$.data.started_at') AS started,
        json_extract(a.body,'$.data.burned_at') AS burned,
        json_extract(a.body,'$.data.available_at') AS available,
        json_extract(a.body,'$.data.unlocked_at') AS unlocked"""
SCHEDULE_KEYS = ("assignment_id", "level", "started", "burned", "available", "unlocked")


def empty_result():
    def group():
        return {"total": 0, "checked": 0, "ready": 0, "missing_text": 0,
            "missing_images": 0, "audio_total": 0, "audio_cached": 0, "total_complete": False}
    return {"complete": False, "checking": True, "checked_at": None,
        **{mode: group() for mode in GROUPS}, "message": "Checking offline availability…"}


def _assets(data, name):
    entries = data.get(name)
    return [item for item in entries if isinstance(item, dict) and isinstance(item.get("url"), str)] if isinstance(entries, list) else []


def _access_context(engine):
    subscription = engine.user().get("subscription", {})
    access = {key: subscription.get(key) for key in ("type", "max_level_granted", "period_ends_at")} if isinstance(subscription, dict) else subscription
    # JSON preserves distinctions such as true versus 1 in malformed grants.
    return (engine.store.get("account_id"), json.dumps(access, sort_keys=True),
        engine.clock_offset, engine.clock_untrusted)


def _access_changed(value):
    return {**empty_result(), "checking": False, "checked_at": value.get("checked_at"),
        "message": "Account access or the verified clock changed during the check. Refresh to check offline availability again."}


def _schedule(engine, now, maximum, stopped):
    """Project bounded identities once; classify exact timestamps in Python.

    julianday rounds near fractional-second boundaries, so it must not decide
    whether a review belongs to due-now or the next 24 hours. These indexed
    fields avoid reading subject mnemonics until the bounded content batches.
    """
    groups = {mode: [] for mode in GROUPS}
    if stopped():
        return groups, False
    horizon = now + 86400
    future_maximum = engine.max_level(horizon)
    subscription = engine.user().get("subscription", {})
    expiry = epoch(subscription.get("period_ends_at"))
    rows = engine.store.rows(f"""SELECT {SCHEDULE_FIELDS}
      FROM resources a INDEXED BY resource_assignment_schedule
      JOIN resources s INDEXED BY resource_search_identity ON s.kind IN {SUBJECTS}
        AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
      WHERE a.kind='assignment' AND json_type(s.body,'$.data.level')='integer'
        AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
        AND json_extract(s.body,'$.data.hidden_at') IS NULL
        AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
        AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER)
          AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})
      LIMIT ?""", (maximum, MAX_SCHEDULE + 1))
    complete = len(rows) <= MAX_SCHEDULE
    for row in rows[:MAX_SCHEDULE]:
        if stopped():
            return groups, False
        available, unlocked = epoch(row["available"]), epoch(row["unlocked"])
        identity = tuple(row[key] for key in SCHEDULE_KEYS)
        if row["started"] is None and unlocked is not None and unlocked <= now:
            groups["lessons"].append(identity)
        elif row["started"] and row["burned"] is None and available is not None:
            if available <= now:
                groups["reviews"].append(identity)
            elif available <= horizon:
                # An expiry inside the horizon can reduce the grant before
                # this review becomes due. Never promise unavailable content.
                grant = future_maximum if expiry is not None and available >= expiry else maximum
                if row["level"] <= grant:
                    groups["upcoming_reviews"].append(identity)
    for identifiers in groups.values():
        identifiers.sort(key=lambda identity: identity[0])
    return groups, complete


def calculate(engine, cancelled=lambda: False, max_items=12000, budget_seconds=5, clock=time.monotonic):
    """Check small indexed batches, without holding a long SQLite transaction.

    Text/image readiness and optional pronunciation audio are distinct. The
    item/time limits also bound malformed or unexpectedly large catalogues;
    partial results explicitly retain checked and total counts.
    """
    store = engine.store
    media_dir = store.path.parent / "media"
    access_context = _access_context(engine)
    result = empty_result()
    result["checking"] = False
    now = engine.now()
    result["checked_at"] = stamp(now)
    maximum = engine.max_level(now)
    deadline = clock() + budget_seconds
    checked = 0
    def stopped():
        return cancelled() or clock() >= deadline

    groups, schedule_complete = _schedule(engine, now, maximum, stopped)
    for mode in GROUPS:
        result[mode].update(total=len(groups[mode]), total_complete=schedule_complete)
    complete = True
    for mode in GROUPS:
        counts = result[mode]
        for offset in range(0, len(groups[mode]), CONTENT_BATCH):
            if stopped() or checked >= max_items:
                complete = False
                break
            identities = groups[mode][offset:offset + min(CONTENT_BATCH, max_items - checked)]
            identifiers = [identity[0] for identity in identities]
            rows = store.rows(f"""SELECT {SCHEDULE_FIELDS},s.body,
                CASE WHEN d.body IS NOT NULL AND json_type(d.body)!='null'
                  THEN d.body ELSE json_extract(m.body,'$.data') END AS material
              FROM resources a INDEXED BY resource_numeric_id
              JOIN resources s INDEXED BY resource_numeric_id ON s.kind IN {SUBJECTS}
                AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
              LEFT JOIN resources m ON m.kind='study_material'
                AND CAST(json_extract(m.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
              LEFT JOIN meta d ON d.key='material_draft_'||s.id
              WHERE a.kind='assignment' AND CAST(a.id AS INTEGER) IN ({','.join('?' for _ in identifiers)})
                AND json_type(s.body,'$.data.level')='integer' AND json_extract(s.body,'$.data.level') BETWEEN 1 AND ?
                AND json_extract(s.body,'$.data.hidden_at') IS NULL
                AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
                AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER)
                  AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})
              ORDER BY CAST(a.id AS INTEGER)""", (*identifiers, maximum))
            if [tuple(row[key] for key in SCHEDULE_KEYS) for row in rows] != identities:
                # Eligibility may have changed during this background check.
                complete = False
                break
            subjects = [json.loads(row["body"]) for row in rows]
            urls = set()
            for subject in subjects:
                data = subject["data"]
                for asset in _assets(data, "character_images") + _assets(data, "pronunciation_audios"):
                    urls.add(asset["url"])
            cached = set()
            urls = list(urls)
            for media_offset in range(0, len(urls), 400):
                if stopped():
                    complete = False
                    break
                chunk = urls[media_offset:media_offset + 400]
                for asset in store.rows("SELECT url,path FROM media WHERE url IN (" + ",".join("?" for _ in chunk) + ")", chunk):
                    if available_file(media_dir, asset["path"]):
                        cached.add(asset["url"])
            if not complete:
                break
            for row, subject in zip(rows, subjects):
                if stopped() or checked >= max_items:
                    complete = False
                    break
                data = subject["data"]
                try:
                    validate_subject_answers(subject, json.loads(row["material"]) if row["material"] else None)
                    text_ok = True
                except UserError:
                    text_ok = False
                image_ok = bool(data.get("characters")) or any(a["url"] in cached for a in _assets(data, "character_images"))
                audio = _assets(data, "pronunciation_audios")
                counts["checked"] += 1
                counts["ready"] += int(text_ok and image_ok)
                counts["missing_text"] += int(not text_ok)
                counts["missing_images"] += int(not image_ok)
                counts["audio_total"] += int(bool(audio))
                counts["audio_cached"] += int(any(a.get("url") in cached for a in audio))
                checked += 1
            if not complete:
                break
        if counts["checked"] < counts["total"]:
            complete = False
        if not complete:
            break
    complete = complete and schedule_complete
    result["complete"] = complete
    if not complete:
        result["message"] = "Offline availability is partially checked. Counts describe the items checked; refresh to check again."
        if not schedule_complete:
            result["message"] += " Schedule totals are not yet known."
    elif any(result[m]["missing_images"] or result[m]["missing_text"] for m in GROUPS):
        result["message"] = "Some study items need required text or radical images. Refresh while online to cache them."
    elif any(result[m]["audio_cached"] < result[m]["audio_total"] for m in GROUPS):
        result["message"] = "Current and scheduled study items are ready offline. Some optional pronunciation audio is not cached."
    elif checked:
        result["message"] = "Current and scheduled study items are ready offline."
    else:
        result["message"] = "No eligible cached reviews or lessons are ready yet."
    if _access_context(engine) != access_context:
        return _access_changed(result)
    return result


class OfflineReadiness:
    """A single coalescing background check; get() only copies cached counts."""
    def __init__(self, engine, changed=lambda value: None):
        self.engine = engine
        self.changed = changed
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.value = empty_result()
        self.running = False
        self.again = False
        self.last_started = float("-inf")

    def get(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def stop(self):
        self.cancelled.set()

    def refresh(self, force=False):
        with self.lock:
            if self.cancelled.is_set():
                return
            if self.running:
                self.again = self.again or force
                return
            if not force and time.monotonic() - self.last_started < 60:
                return
            self.running = True
            self.last_started = time.monotonic()
            self.value = {**self.value, "checking": True}
        threading.Thread(target=self._run, daemon=True, name="wanikani-offline-readiness").start()

    def _run(self):
        while not self.cancelled.is_set():
            try:
                context = _access_context(self.engine)
                value = calculate(self.engine, self.cancelled.is_set)
                if _access_context(self.engine) != context:
                    value = _access_changed(value)
            except Exception:
                value = self.get()
                value.update(complete=False, checking=False,
                    message="Offline availability could not be checked. Refresh to try again.")
            with self.lock:
                if self.cancelled.is_set():
                    self.running = False
                    return
                self.value = value
                repeat = self.again
                self.again = False
                self.running = repeat
                if repeat:
                    self.last_started = time.monotonic()
            self.changed(copy.deepcopy(value))
            if not repeat:
                return
