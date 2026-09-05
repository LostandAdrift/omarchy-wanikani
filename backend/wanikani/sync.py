import hashlib
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from .api import ApiError, NoRedirect, validate_user
from .common import UserError, epoch, private_dir, stamp
from .engine import baseline
from . import milestones


COLLECTIONS = (
    ("subjects", "subjects"), ("assignments", "assignments"),
    ("study_materials", "study_materials"), ("review_statistics", "review_statistics"),
    ("level_progressions", "level_progressions"), ("spaced_repetition_systems", "spaced_repetition_systems"),
)


class Synchronizer:
    def __init__(self, engine, api, media_dir, changed=lambda: None, progress=lambda value: None):
        self.engine, self.api, self.store = engine, api, engine.store
        self.media_dir = private_dir(media_dir)
        self.lock = threading.Lock()
        self.changed = changed
        self.progress_changed = progress
        self.progress = {"stage": "idle", "message": "", "completed": 0, "total": None, "active": False}
        self.cancelled = threading.Event()

    def report(self, stage, message, completed=0, total=None, active=True):
        self.progress = {"stage": stage, "message": message, "completed": completed, "total": total, "active": active}
        # Presentation callbacks must never alter the submission outcome.
        try:
            self.progress_changed(dict(self.progress))
        except Exception:
            pass

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise UserError("Synchronization stopped.", "cancelled")

    def run(self, full=False, for_study=False):
        if not self.lock.acquire(blocking=False):
            return False
        engine = self.engine
        engine.syncing = True
        succeeded = False
        self.report("account", "Checking account access")
        self.changed()
        try:
            self.check_cancelled()
            user, _ = self.api.request("user")
            validate_user(user)
            if user.get("id") != self.store.get("account_id"):
                raise UserError("The token belongs to a different account. Disconnect and remove local account data before switching.", "account_mismatch")
            self.store.set("user", user)
            engine.clock_offset = self.api.server_offset
            engine.clock_untrusted = abs(engine.clock_offset) > 300
            self.store.execute("UPDATE outbox SET state='pending' WHERE state='blocked' AND detail='This subject is outside current subscription access.'")
            reset_before = self.store.get("reset_cursor")
            reset_now = stamp(engine.now() - 2)
            reset_params = {"updated_after": reset_before} if reset_before else {}
            self.report("resets", "Checking account resets")
            for page in self.api.collection("resets", reset_params):
                for reset in page:
                    with self.store.transaction():
                        old = self.store.resource("reset", reset["id"])
                        # Confirmation may arrive as an update to a reset we
                        # already cached while it was still unconfirmed.
                        confirmed = reset["data"].get("confirmed_at")
                        if confirmed and not (old or {}).get("data", {}).get("confirmed_at"):
                            self._invalidate_reset(reset)
                            full = True
                        # Persist observation together with invalidation: a
                        # crash cannot acknowledge the reset without applying it.
                        self.store.put(reset)
            self.store.set("reset_cursor", reset_now)
            for endpoint, key in COLLECTIONS:
                self.check_cancelled()
                if endpoint == "subjects" and engine.max_level() == 0:
                    # An empty levels parameter can mean an unfiltered
                    # catalogue. No content grant means no subject request.
                    self.store.set("cached_max_level", 0)
                    continue
                label = {"subjects": "Caching subject catalogue", "assignments": "Refreshing lessons and reviews",
                    "study_materials": "Refreshing personal study material", "review_statistics": "Refreshing learning statistics",
                    "level_progressions": "Refreshing level progress", "spaced_repetition_systems": "Refreshing review schedules"}[endpoint]
                fetched = 0
                self.report(endpoint, label)
                since = None if full else self.store.get("cursor_" + key)
                if endpoint == "subjects" and engine.max_level() > self.store.get("cached_max_level", 0):
                    since = None
                started = stamp(engine.now() - 2)  # overlap removes pagination/update boundary gaps
                params = {"updated_after": since} if since else {}
                if endpoint == "subjects":
                    params["levels"] = ",".join(str(n) for n in range(1, engine.max_level() + 1))
                for page in self.api.collection(endpoint, params):
                    self.check_cancelled()
                    with self.store.transaction():
                        for resource in page:
                            self.store.put(resource)
                    fetched += len(page)
                    self.report(endpoint, label, fetched)
                self.store.set("cursor_" + key, started)
                if endpoint == "subjects":
                    self.store.set("cached_max_level", engine.max_level())
            self.report("summary", "Refreshing the review forecast")
            summary, etag = self.api.request("summary", etag=self.store.get("summary_etag"))
            if summary is not None:
                self.store.set("summary", summary)
                self.store.set("summary_etag", etag)
            self.reconcile_uncertain()
            if not engine.user().get("current_vacation_started_at") and abs(engine.clock_offset) <= 300:
                if self.flush():
                    self.refresh_after_writes()
            engine.connected = True
            engine.status = "online"
            engine.message = ""
            if engine.clock_untrusted:
                engine.status = "clock_changed"
                engine.message = "The system clock differs from WaniKani. Correct it before graded study or submission."
            self.store.set("last_sync", stamp(engine.now()))
            self.changed()
            # Account/reset/catalogue/material checks and outbox reconciliation
            # still precede online study. Media prefetch can wait for the next
            # background refresh; missing required images stay unavailable.
            if not for_study:
                self.cache_media()
            milestones.observe(engine)
            succeeded = True
            return True
        except ApiError as error:
            engine.status = "offline" if error.status == 0 else error.code
            if error.status == 401:
                engine.connected = False
            engine.message = str(error)
            return False
        except UserError as error:
            engine.status = error.code
            engine.message = str(error)
            return False
        except Exception:
            engine.status = "sync_error"
            engine.message = "Synchronization stopped on an unexpected response. Saved answers were retained; refresh to reconcile."
            return False
        finally:
            engine.syncing = False
            self.report("complete" if succeeded else engine.status,
                engine.message or ("Account refreshed" if succeeded else "Synchronization paused"), active=False)
            self.lock.release()
            self.changed()

    def refresh_after_writes(self):
        """Fetch unlocks once after confirmed writes, without replaying work."""
        self.check_cancelled()
        self.report("unlocks", "Checking newly unlocked lessons and account progress")
        user, _ = self.api.request("user")
        validate_user(user)
        if user.get("id") != self.store.get("account_id"):
            raise UserError("The account changed while refreshing progress. Saved results were retained.", "account_mismatch")
        self.store.set("user", user)
        self.engine.clock_offset = self.api.server_offset
        self.engine.clock_untrusted = abs(self.engine.clock_offset) > 300
        since = self.store.get("cursor_assignments")
        started = stamp(self.engine.now() - 2)
        complete = False
        fetched = 0
        for index, page in enumerate(self.api.collection("assignments", {"updated_after": since} if since else {})):
            self.check_cancelled()
            with self.store.transaction():
                for resource in page:
                    self.store.put(resource)
            fetched += len(page)
            self.report("unlocks", "Checking newly unlocked lessons and account progress", fetched)
            # Limit this follow-up to four pages. If exceptionally many items
            # changed, keep the old cursor so the next regular sync catches all.
            if index >= 3:
                break
        else:
            complete = True
        if complete:
            self.store.set("cursor_assignments", started)
        self.check_cancelled()
        summary, etag = self.api.request("summary", etag=self.store.get("summary_etag"))
        if summary is not None:
            self.store.set("summary", summary)
            self.store.set("summary_etag", etag)

    def _invalidate_reset(self, reset):
        target = int(reset["data"].get("target_level", 1))
        with self.store.transaction():
            milestones.invalidate_reset(self.engine)
            for row in self.store.rows("SELECT id,subject_id FROM outbox WHERE state IN ('pending','blocked','uncertain')"):
                subject = self.store.subject(row["subject_id"])
                if subject and subject["data"].get("level", 0) >= target:
                    self.state(row["id"], "conflicted", "WaniKani account reset; the local result was preserved but will not be submitted.")
            for session_row in self.store.rows("""SELECT body FROM sessions
                WHERE json_extract(body,'$.phase')!='complete' AND json_extract(body,'$.mode')!='practice'"""):
                session = json.loads(session_row["body"])
                if session["phase"] == "complete" or session["mode"] == "practice":
                    continue
                if any((self.store.subject(item["subject_id"]) or {"data": {}})["data"].get("level", 0) >= target for item in session["queue"]):
                    session["phase"] = "complete"
                    session["ended_at"] = stamp(self.engine.now())
                    session["invalidated"] = "Account reset"
                    self.store.save_session(session, activate=False)
            # A collection refresh only upserts returned rows. Assignments
            # removed by a reset will never reappear in that response, so remove
            # affected cached progress before fetching the replacement state.
            self.store.execute("""DELETE FROM resources WHERE kind IN ('assignment','review_statistic')
              AND CAST(json_extract(body,'$.data.subject_id') AS INTEGER) IN
              (SELECT CAST(id AS INTEGER) FROM resources WHERE kind IN
                ('radical','kanji','vocabulary','kana_vocabulary')
                AND json_extract(body,'$.data.level')>=?)""", (target,))
            self.store.execute("DELETE FROM resources WHERE kind='level_progression'")
            for _, key in COLLECTIONS:
                self.store.set("cursor_" + key, None)
            self.store.set("summary_etag", None)

    def state(self, operation_id, state, message):
        self.store.execute("UPDATE outbox SET state=?,detail=? WHERE id=?", (state, message, operation_id))

    def fetch_assignment(self, body):
        resource, _ = self.api.request("assignments/" + str(body["assignment_id"]))
        if (not isinstance(resource, dict) or resource.get("object") != "assignment"
                or resource.get("id") != body["assignment_id"]
                or resource.get("data", {}).get("subject_id") != body["baseline"].get("subject_id")):
            raise ApiError(0, "WaniKani returned an unexpected assignment. Saved work was retained.")
        self.store.put(resource)
        return resource

    def _outbox_window(self, state):
        # The rowid cutoff captures work present at the beginning of this pass.
        # Newly saved answers wait for the next pass, including answers whose
        # wall-clock timestamp sorts before the current page after a clock edit.
        row = self.store.rows("SELECT COUNT(*) AS total,COALESCE(MAX(rowid),0) AS cutoff FROM outbox WHERE state=?", (state,))[0]
        return row["total"], row["cutoff"]

    def _outbox_rows(self, state, cutoff):
        previous = None
        while True:
            self.check_cancelled()
            after = " AND (created_at,id)>(?,?)" if previous else ""
            parameters = (state, cutoff, *previous) if previous else (state, cutoff)
            candidates = self.store.rows("SELECT id,created_at FROM outbox WHERE state=? AND rowid<=?" + after +
                " ORDER BY created_at,id LIMIT 25", parameters)
            if not candidates:
                return
            for candidate in candidates:
                self.check_cancelled()
                previous = (candidate["created_at"], candidate["id"])
                # Only materialize the body about to be processed. A quota or
                # transport failure must not allocate every later answer/note.
                rows = self.store.rows("SELECT * FROM outbox WHERE id=? AND state=? AND rowid<=?",
                    (candidate["id"], state, cutoff))
                if rows:
                    yield rows[0]

    def reconcile_uncertain(self):
        total, cutoff = self._outbox_window("uncertain")
        self.report("reconcile", "Checking interrupted submissions", 0, total)
        for index, row in enumerate(self._outbox_rows("uncertain", cutoff)):
            self.check_cancelled()
            self.report("reconcile", "Checking interrupted submissions", index, total)
            body = json.loads(row["body"])
            if row["kind"] == "material":
                material = self.fetch_material(row["subject_id"])
                actual = (material or {}).get("data", {})
                if all(actual.get(k) == v for k, v in body["values"].items()):
                    self.state(row["id"], "confirmed", "The desired study material is present on WaniKani.")
                    self.store.set("material_draft_" + str(row["subject_id"]), None)
                elif actual != body.get("baseline", {}):
                    self.state(row["id"], "conflicted", "Study material changed remotely; review the edit before resolving.")
                continue
            try:
                remote = self.fetch_assignment(body)
            except ApiError as error:
                if error.status == 404:
                    self.state(row["id"], "conflicted", "The remote assignment no longer exists.")
                    continue
                raise
            if baseline(remote) != body["baseline"]:
                # We cannot prove which client performed the write. Do not call
                # this our confirmation, and never replay it onto a later SRS cycle.
                self.state(row["id"], "conflicted", "Remote progress changed. Kept the remote result; the local result will not be replayed.")
            else:
                self.state(row["id"], "uncertain", "Remote progress still matches the original state. The request may have been interrupted; automatic retry is disabled.")

    def fetch_material(self, subject_id):
        found = None
        for page in self.api.collection("study_materials", {"subject_ids": str(subject_id)}):
            for item in page:
                self.store.put(item)
                found = item
        return found

    def flush(self):
        if self.engine.user().get("current_vacation_started_at"):
            raise UserError("Vacation mode is active. Saved work will wait for synchronization.", "vacation")
        if self.engine.clock_untrusted or abs(self.engine.clock_offset) > 300:
            raise UserError("Refresh to verify the system clock before submitting saved work.", "clock_changed")
        confirmed = 0
        total, cutoff = self._outbox_window("pending")
        processed = 0
        self.report("submitting", "Checking and sending saved work", 0, total)
        for index, row in enumerate(self._outbox_rows("pending", cutoff)):
            self.check_cancelled()
            self.report("submitting", "Checking and sending saved work", index, total)
            processed = index + 1
            body = json.loads(row["body"])
            if body.get("account_id") != self.store.get("account_id"):
                self.state(row["id"], "conflicted", "Account mismatch. This result will not be submitted.")
                continue
            try:
                self.engine.ensure_access(self.store.subject(row["subject_id"]))
            except UserError:
                self.state(row["id"], "blocked", "This subject is outside current subscription access.")
                continue
            if row["kind"] == "material":
                existing = self.fetch_material(row["subject_id"])
                data = (existing or {}).get("data", {})
                original = body.get("baseline", {})
                keys = ("meaning_synonyms", "meaning_note", "reading_note")
                if any(data.get(k) != original.get(k) for k in keys):
                    self.state(row["id"], "conflicted", "Study material changed on another client. Your draft is preserved.")
                    continue
                method = "PUT" if existing else "POST"
                path = "study_materials/" + str(existing["id"]) if existing else "study_materials"
                payload = {"study_material": dict(body["values"])}
                if not existing:
                    payload["study_material"]["subject_id"] = row["subject_id"]
            else:
                try:
                    remote = self.fetch_assignment(body)
                except ApiError as error:
                    if error.status == 404:
                        self.state(row["id"], "conflicted", "The remote assignment no longer exists. The local result was retained.")
                        continue
                    raise
                if baseline(remote) != body["baseline"]:
                    self.state(row["id"], "conflicted", "Progress changed on another client. Kept its result without submitting this stale result.")
                    continue
                if row["kind"] == "lesson":
                    method, path = "PUT", "assignments/" + str(body["assignment_id"]) + "/start"
                    payload = {"assignment": {"started_at": body["completed_at"]}}
                else:
                    method, path = "POST", "reviews"
                    payload = {"review": {"assignment_id": body["assignment_id"], "incorrect_meaning_answers": body["errors"]["meaning"],
                        "incorrect_reading_answers": body["errors"]["reading"], "created_at": body["completed_at"]}}
            # Committed before touching the network. Any crash from here until
            # confirmation recovers as uncertain, including malformed 2xx replies.
            self.state(row["id"], "inflight", "Sending to WaniKani")
            try:
                result, _ = self.api.request(path, method, payload)
                confirmed += bool(self.apply_result(row, result))
            except ApiError as error:
                if error.uncertain:
                    self.state(row["id"], "uncertain", "The response was lost. Refresh to check remote progress; this request will not be automatically retried.")
                elif error.status in (401, 403):
                    self.state(row["id"], "blocked", str(error))
                elif error.status == 429:
                    self.state(row["id"], "pending", str(error))
                else:
                    self.state(row["id"], "conflicted", str(error))
                if error.status in (0, 401, 403, 429) or error.status >= 500:
                    raise
            except Exception:
                self.state(row["id"], "uncertain", "Confirmation was interrupted. Refresh to reconcile; automatic retry is disabled.")
                raise
        self.report("submitting", "Saved work checked", processed, total)
        return confirmed

    def apply_result(self, row, response):
        try:
            with self.store.transaction():
                body = json.loads(row["body"])
                if not isinstance(response, dict):
                    raise ValueError("Unexpected result")
                if row["kind"] == "review":
                    updated = response.get("resources_updated", {})
                    assignment = updated.get("assignment")
                    statistic = updated.get("review_statistic")
                    if not assignment or assignment.get("object") != "assignment":
                        raise ValueError("Missing assignment")
                    if assignment.get("id") != body["assignment_id"] or assignment.get("data", {}).get("subject_id") != row["subject_id"]:
                        raise ValueError("Mismatched assignment")
                    if baseline(assignment) == body["baseline"]:
                        raise ValueError("Progress was not updated")
                    self.store.put(assignment)
                    if statistic:
                        if statistic.get("object") != "review_statistic" or statistic.get("data", {}).get("subject_id") != row["subject_id"]:
                            raise ValueError("Mismatched statistic")
                        self.store.put(statistic)
                else:
                    expected = "assignment" if row["kind"] == "lesson" else "study_material"
                    if response.get("object") != expected:
                        raise ValueError("Unexpected result")
                    if response.get("data", {}).get("subject_id") != row["subject_id"]:
                        raise ValueError("Mismatched subject")
                    if row["kind"] == "lesson" and (response.get("id") != body["assignment_id"] or not response["data"].get("started_at")):
                        raise ValueError("Lesson was not started")
                    self.store.put(response)
                self.state(row["id"], "confirmed", "Confirmed by WaniKani")
                if row["kind"] == "material":
                    self.store.set("material_draft_" + str(row["subject_id"]), None)
            return True
        except (ValueError, KeyError, TypeError):
            self.state(row["id"], "uncertain", "WaniKani replied, but confirmation could not be validated. Refresh before recovery.")
            return False

    def resolve(self, operation_id, action):
        rows = self.store.rows("SELECT * FROM outbox WHERE id=?", (operation_id,))
        if not rows or rows[0]["state"] not in ("uncertain", "conflicted", "blocked"):
            raise UserError("This result does not need recovery.")
        row = rows[0]
        if action != "keep_remote":
            raise UserError("Refresh to reconcile, or keep remote progress and archive the local result.")
        # Recovery deliberately offers no force-resubmit: without server
        # idempotency this could double-grade a later review opportunity.
        with self.store.transaction():
            self.state(operation_id, "discarded", "Archived locally by user; remote progress kept")
            if row["kind"] == "material":
                self.store.set("material_draft_" + str(row["subject_id"]), None)
        return {"resolved": True}

    def cache_media(self):
        # Bounded incremental prefetch: eligible current/upcoming study first.
        # Account controls wait for this worker job, so stop starting downloads
        # after eight seconds. An already-running request keeps its 10s timeout.
        deadline = time.monotonic() + 8
        self.report("media", "Caching images and optional pronunciation audio")
        rows = self.store.rows("""SELECT s.id FROM resources s LEFT JOIN resources a
          ON a.kind='assignment' AND CAST(json_extract(a.body,'$.data.subject_id') AS INTEGER)=CAST(s.id AS INTEGER)
          WHERE s.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
          ORDER BY CASE
            WHEN json_extract(a.body,'$.data.unlocked_at') IS NOT NULL AND json_extract(a.body,'$.data.started_at') IS NULL THEN 0
            WHEN julianday(json_extract(a.body,'$.data.available_at'))<=julianday(?) THEN 1
            WHEN json_extract(a.body,'$.data.started_at') IS NOT NULL THEN 2 ELSE 3 END,
          json_extract(a.body,'$.data.available_at'),json_extract(s.body,'$.data.level')""", (stamp(self.engine.now() + 86400),))
        downloaded = attempts = 0
        for row in rows:
            self.check_cancelled()
            if time.monotonic() >= deadline:
                break
            subject = self.store.subject(row[0])
            try:
                self.engine.ensure_access(subject)
            except UserError:
                continue
            data = subject["data"]
            assets = data.get("character_images", [])[:1]
            sounds = data.get("pronunciation_audios", [])
            preferred = self.engine.settings()["voice_actor_id"]
            sounds = sorted(sounds, key=lambda s: s.get("metadata", {}).get("voice_actor_id") != preferred)
            assets += sounds[:1]
            for asset in assets:
                if time.monotonic() >= deadline:
                    self.trim_media()
                    return
                url = asset.get("url", "")
                cached = self.store.rows("SELECT path FROM media WHERE url=?", (url,))
                if cached and Path(cached[0][0]).is_file():
                    continue
                retry_key = "media_retry_" + hashlib.sha256(url.encode()).hexdigest()
                if self.store.get(retry_key, 0) > self.engine.now():
                    continue
                attempts += 1
                if self.download_media(url):
                    downloaded += 1
                    self.report("media", "Caching images and optional pronunciation audio", downloaded)
                else:
                    self.store.set(retry_key, self.engine.now() + 3600)
                if downloaded >= 40 or attempts >= 60 or time.monotonic() >= deadline:
                    self.trim_media()
                    return
        self.trim_media()

    def download_media(self, url):
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if not (host == "wanikani.com" or host.endswith(".wanikani.com") or host.endswith(".cloudfront.net")):
            return False
        # No Authorization header is attached to media or redirected elsewhere.
        try:
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "Omarchy-WaniKani/0.1"}), timeout=10) as response:
                mime = response.headers.get_content_type()
                extension = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/webm": ".webm"}.get(mime)
                if not extension:
                    return False
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    return False
                dest = self.media_dir / (hashlib.sha256(url.encode()).hexdigest() + extension)
                temporary = dest.with_suffix(dest.suffix + ".tmp")
                temporary.write_bytes(data)
                temporary.chmod(0o600)
                temporary.replace(dest)
                self.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)", (url, str(dest), len(data), time.time()))
                return True
        except (OSError, ValueError):
            return False

    def trim_media(self):
        rows = self.store.rows("SELECT * FROM media ORDER BY used_at")
        total = sum(row["size"] for row in rows)
        limit = self.engine.settings()["cache_limit_mb"] * 1024 * 1024
        for row in rows:
            if total <= limit:
                break
            Path(row["path"]).unlink(missing_ok=True)
            self.store.execute("DELETE FROM media WHERE url=?", (row["url"],))
            total -= row["size"]

    def clear_media(self):
        for row in self.store.rows("SELECT path FROM media"):
            path = Path(row[0])
            if path.parent == self.media_dir:
                path.unlink(missing_ok=True)
        self.store.execute("DELETE FROM media")
