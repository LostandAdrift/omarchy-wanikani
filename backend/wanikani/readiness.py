"""Bounded, asynchronous checks of the content needed for offline study."""
import copy
import json
import threading
import time
from pathlib import Path

from .common import UserError, stamp
from .engine import BUSY_STATES, SUBJECTS
from .grading import validate_subject_answers


def empty_result():
    def group():
        return {"total": 0, "checked": 0, "ready": 0, "missing_text": 0,
            "missing_images": 0, "audio_total": 0, "audio_cached": 0}
    return {"complete": False, "checking": True, "checked_at": None,
        "reviews": group(), "lessons": group(), "message": "Checking offline availability…"}


def _assets(data, name):
    entries = data.get(name)
    return [item for item in entries if isinstance(item, dict) and isinstance(item.get("url"), str)] if isinstance(entries, list) else []


def calculate(engine, cancelled=lambda: False, max_items=12000, budget_seconds=5, clock=time.monotonic):
    """Check small indexed batches, without holding a long SQLite transaction.

    Text/image readiness and optional pronunciation audio are distinct. The
    item/time limits also bound malformed or unexpectedly large catalogues;
    partial results explicitly retain checked and total counts.
    """
    store = engine.store
    result = empty_result()
    result["checking"] = False
    result["checked_at"] = stamp(engine.now())
    maximum, now = engine.max_level(), stamp(engine.now())
    deadline = clock() + budget_seconds
    checked = 0
    complete = True
    for mode in ("reviews", "lessons"):
        result[mode]["total"] = engine.assignments(mode, count_only=True)
    for mode in ("reviews", "lessons"):
        counts = result[mode]
        last_id = 0
        eligibility = """json_extract(a.body,'$.data.started_at') IS NULL
          AND julianday(json_extract(a.body,'$.data.unlocked_at'))<=julianday(?)""" if mode == "lessons" else """
          json_extract(a.body,'$.data.started_at') IS NOT NULL
          AND json_extract(a.body,'$.data.burned_at') IS NULL
          AND julianday(json_extract(a.body,'$.data.available_at'))<=julianday(?)"""
        while counts["checked"] < counts["total"]:
            if cancelled() or checked >= max_items or clock() >= deadline:
                complete = False
                break
            rows = store.rows(f"""SELECT CAST(a.id AS INTEGER) AS assignment_id,s.body,
                CASE WHEN d.body IS NOT NULL AND json_type(d.body)!='null'
                  THEN d.body ELSE json_extract(m.body,'$.data') END AS material
              FROM resources a JOIN resources s INDEXED BY resource_numeric_id ON s.kind IN {SUBJECTS}
                AND CAST(s.id AS INTEGER)=CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)
              LEFT JOIN resources m ON m.kind='study_material'
                AND CAST(json_extract(m.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
              LEFT JOIN meta d ON d.key='material_draft_'||s.id
              WHERE a.kind='assignment' AND CAST(a.id AS INTEGER)>?
                AND json_extract(s.body,'$.data.level')<=?
                AND json_extract(s.body,'$.data.hidden_at') IS NULL
                AND COALESCE(json_extract(a.body,'$.data.hidden'),0)=0
                AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.subject_id=CAST(s.id AS INTEGER)
                  AND o.kind IN ('review','lesson') AND o.state IN {BUSY_STATES})
                AND {eligibility}
              ORDER BY CAST(a.id AS INTEGER) LIMIT ?""", (last_id, maximum, now, min(128, max_items - checked)))
            if not rows:
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
            for offset in range(0, len(urls), 400):
                if cancelled() or clock() >= deadline:
                    complete = False
                    break
                chunk = urls[offset:offset + 400]
                for asset in store.rows("SELECT url,path FROM media WHERE url IN (" + ",".join("?" for _ in chunk) + ")", chunk):
                    if Path(asset["path"]).is_file():
                        cached.add(asset["url"])
            if not complete:
                break
            for row, subject in zip(rows, subjects):
                if cancelled() or checked >= max_items or clock() >= deadline:
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
                last_id = row["assignment_id"]
            if not complete:
                break
        if not complete:
            break
    result["complete"] = complete
    if not complete:
        result["message"] = "Offline availability is partially checked. Counts describe the items checked; refresh to check again."
    elif any(result[m]["missing_images"] or result[m]["missing_text"] for m in ("reviews", "lessons")):
        result["message"] = "Some study items need required text or radical images. Refresh while online to cache them."
    elif any(result[m]["audio_cached"] < result[m]["audio_total"] for m in ("reviews", "lessons")):
        result["message"] = "Cached reviews and lessons are ready offline. Some optional pronunciation audio is not cached."
    elif checked:
        result["message"] = "Cached reviews and lessons are ready offline."
    else:
        result["message"] = "No eligible cached reviews or lessons are ready yet."
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
                value = calculate(self.engine, self.cancelled.is_set)
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
