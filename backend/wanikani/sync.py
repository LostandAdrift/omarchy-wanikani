import hashlib
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from .api import ApiError, NoRedirect
from .common import UserError, epoch, private_dir, stamp
from .engine import baseline


COLLECTIONS = (
    ("subjects", "subjects"), ("assignments", "assignments"),
    ("study_materials", "study_materials"), ("review_statistics", "review_statistics"),
    ("level_progressions", "level_progressions"), ("spaced_repetition_systems", "spaced_repetition_systems"),
)


class Synchronizer:
    def __init__(self, engine, api, media_dir, changed=lambda: None):
        self.engine, self.api, self.store = engine, api, engine.store
        self.media_dir = private_dir(media_dir)
        self.lock = threading.Lock()
        self.changed = changed
        self.cancelled = threading.Event()

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise UserError("Synchronization stopped.", "cancelled")

    def run(self, full=False):
        if not self.lock.acquire(blocking=False):
            return False
        engine = self.engine
        engine.syncing = True
        self.changed()
        try:
            self.check_cancelled()
            user, _ = self.api.request("user")
            if user.get("id") != self.store.get("account_id"):
                raise UserError("The token belongs to a different account. Disconnect and remove local account data before switching.", "account_mismatch")
            self.store.set("user", user)
            engine.clock_offset = self.api.server_offset
            reset_before = self.store.get("reset_cursor")
            reset_now = stamp(engine.now())
            reset_params = {"updated_after": reset_before} if reset_before else {}
            for page in self.api.collection("resets", reset_params):
                for reset in page:
                    old = self.store.resource("reset", reset["id"])
                    self.store.put(reset)
                    if not old and reset_before and reset["data"].get("confirmed_at"):
                        self._invalidate_reset(reset)
                        full = True
            self.store.set("reset_cursor", reset_now)
            for endpoint, key in COLLECTIONS:
                self.check_cancelled()
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
                self.store.set("cursor_" + key, started)
                if endpoint == "subjects":
                    self.store.set("cached_max_level", engine.max_level())
            summary, etag = self.api.request("summary", etag=self.store.get("summary_etag"))
            if summary is not None:
                self.store.set("summary", summary)
                self.store.set("summary_etag", etag)
            self.reconcile_uncertain()
            if not engine.user().get("current_vacation_started_at") and abs(engine.clock_offset) <= 300:
                self.flush()
            engine.connected = True
            engine.status = "online"
            engine.message = ""
            self.store.set("last_sync", stamp(engine.now()))
            self.changed()
            self.cache_media()
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
            self.lock.release()
            self.changed()

    def _invalidate_reset(self, reset):
        target = int(reset["data"].get("target_level", 1))
        with self.store.transaction():
            for row in self.store.rows("SELECT * FROM outbox WHERE state IN ('pending','blocked','uncertain')"):
                subject = self.store.subject(row["subject_id"])
                if subject and subject["data"].get("level", 0) >= target:
                    self.state(row["id"], "conflicted", "WaniKani account reset; the local result was preserved but will not be submitted.")
            session = self.store.session()
            if session and session["phase"] != "complete" and session["mode"] != "practice":
                if any((self.store.subject(item["subject_id"]) or {"data": {}})["data"].get("level", 0) >= target for item in session["queue"]):
                    session["phase"] = "complete"
                    session["ended_at"] = stamp(self.engine.now())
                    session["invalidated"] = "Account reset"
                    self.store.save_session(session)

    def state(self, operation_id, state, message):
        self.store.execute("UPDATE outbox SET state=?,detail=? WHERE id=?", (state, message, operation_id))

    def fetch_assignment(self, body):
        resource, _ = self.api.request("assignments/" + str(body["assignment_id"]))
        self.store.put(resource)
        return resource

    def reconcile_uncertain(self):
        for row in self.store.rows("SELECT * FROM outbox WHERE state='uncertain'"):
            self.check_cancelled()
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
        for row in self.store.rows("SELECT * FROM outbox WHERE state='pending' ORDER BY created_at,id"):
            self.check_cancelled()
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
                self.apply_result(row, result)
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

    def apply_result(self, row, response):
        try:
            with self.store.transaction():
                if row["kind"] == "review":
                    updated = response.get("resources_updated", {})
                    assignment = updated.get("assignment")
                    statistic = updated.get("review_statistic")
                    if not assignment or assignment.get("object") != "assignment":
                        raise ValueError("Missing assignment")
                    body = json.loads(row["body"])
                    if assignment.get("id") != body["assignment_id"] or assignment.get("data", {}).get("subject_id") != row["subject_id"]:
                        raise ValueError("Mismatched assignment")
                    self.store.put(assignment)
                    if statistic:
                        self.store.put(statistic)
                else:
                    expected = "assignment" if row["kind"] == "lesson" else "study_material"
                    if response.get("object") != expected:
                        raise ValueError("Unexpected result")
                    if response.get("data", {}).get("subject_id") != row["subject_id"]:
                        raise ValueError("Mismatched subject")
                    self.store.put(response)
                self.state(row["id"], "confirmed", "Confirmed by WaniKani")
                if row["kind"] == "material":
                    self.store.set("material_draft_" + str(row["subject_id"]), None)
        except (ValueError, KeyError, TypeError):
            self.state(row["id"], "uncertain", "WaniKani replied, but confirmation could not be validated. Refresh before recovery.")

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
        rows = self.store.rows("""SELECT s.id FROM resources s LEFT JOIN resources a
          ON a.kind='assignment' AND json_extract(a.body,'$.data.subject_id')=CAST(s.id AS INTEGER)
          WHERE s.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
          ORDER BY CASE
            WHEN json_extract(a.body,'$.data.unlocked_at') IS NOT NULL AND json_extract(a.body,'$.data.started_at') IS NULL THEN 0
            WHEN julianday(json_extract(a.body,'$.data.available_at'))<=julianday(?) THEN 1
            WHEN json_extract(a.body,'$.data.started_at') IS NOT NULL THEN 2 ELSE 3 END,
          json_extract(a.body,'$.data.available_at'),json_extract(s.body,'$.data.level')""", (stamp(self.engine.now() + 86400),))
        downloaded = attempts = 0
        for row in rows:
            self.check_cancelled()
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
                else:
                    self.store.set(retry_key, self.engine.now() + 3600)
                if downloaded >= 40 or attempts >= 60:
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
