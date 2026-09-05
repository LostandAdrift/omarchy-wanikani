import hashlib
import http.client
import json
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from .api import ApiError, NoRedirect, user_id, validate_user
from .common import UserError, epoch, private_dir, stamp
from .engine import baseline
from . import media_plan, milestones


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

    def _store_page(self, page):
        # Large API pages must leave room for foreground answer transactions.
        # Each chunk is durable, while the collection cursor is advanced only
        # after all pages finish. An interrupted refresh safely upserts again.
        for offset in range(0, len(page), 128):
            self.check_cancelled()
            with self.store.transaction():
                for resource in page[offset:offset + 128]:
                    self.store.put(resource)
            # Yield only after committing and releasing the Store lock.
            time.sleep(0)
            self.check_cancelled()

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
            if user_id(user) != self.store.get("account_id"):
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
                    self._store_page(page)
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
        if user_id(user) != self.store.get("account_id"):
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
            self._store_page(page)
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
            levels = {}
            def cached_level(subject_id):
                if subject_id not in levels:
                    subject = self.store.subject(subject_id)
                    data = subject.get("data") if isinstance(subject, dict) else None
                    level = data.get("level") if isinstance(data, dict) else None
                    levels[subject_id] = level if type(level) is int and 1 <= level <= 60 else None
                return levels[subject_id]
            for row in self.store.rows("SELECT id,subject_id FROM outbox WHERE state IN ('pending','blocked','uncertain')"):
                level = cached_level(row["subject_id"])
                if level is None:
                    self.state(row["id"], "conflicted", "WaniKani account reset; this subject's cached level could not be verified. The local result was preserved and will not be submitted.")
                elif level >= target:
                    self.state(row["id"], "conflicted", "WaniKani account reset; the local result was preserved but will not be submitted.")
            for session_row in self.store.rows("""SELECT body FROM sessions
                WHERE json_extract(body,'$.phase')!='complete' AND json_extract(body,'$.mode')!='practice'"""):
                session = json.loads(session_row["body"])
                if session["phase"] == "complete" or session["mode"] == "practice":
                    continue
                if any(cached_level(item["subject_id"]) is None or cached_level(item["subject_id"]) >= target for item in session["queue"]):
                    session["phase"] = "complete"
                    session["ended_at"] = stamp(self.engine.now())
                    session["invalidated"] = "Account reset"
                    self.store.save_session(session, activate=False)
            # A collection refresh only upserts returned rows. Assignments
            # removed by a reset will never reappear in that response, so remove
            # affected cached progress before fetching the replacement state.
            # Missing/malformed levels cannot establish that a subject survived
            # the reset. Preserve local work, but require fresh remote progress.
            self.store.execute("""DELETE FROM resources AS progress WHERE kind IN ('assignment','review_statistic')
              AND NOT EXISTS(SELECT 1 FROM resources AS subject INDEXED BY resource_search_identity
                WHERE subject.kind IN ('radical','kanji','vocabulary','kana_vocabulary')
                  AND CAST(subject.id AS INTEGER)=CAST(json_extract(progress.body,'$.data.subject_id') AS INTEGER)
                  AND json_type(subject.body,'$.data.level')='integer'
                  AND json_extract(subject.body,'$.data.level') BETWEEN 1 AND ?)""", (min(60, target - 1),))
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
        deadline = time.monotonic() + 8
        self.report("media", "Caching images and optional pronunciation audio")
        plan = media_plan.build(self.engine, self.media_dir, deadline, self.cancelled.is_set, clock=time.monotonic)
        self.check_cancelled()
        if not plan.complete:
            self.report("media", "Media planning will continue on the next refresh")
            return {"downloaded": 0, "attempts": 0, "skipped_budget": 0, "complete": False}
        hints = getattr(self, "_media_size_hints", {})
        self._media_size_hints = {url: size for url, size in hints.items() if url in plan.candidates and url not in plan.cached}
        self._media_plan = plan
        downloaded = attempts = 0
        skipped = 0
        try:
            # Recover completed or temporary files left by an interrupted old
            # media job before this job creates any temporary file of its own.
            if not self._remove_media(plan.orphans, plan):
                return {"downloaded": 0, "attempts": 0, "skipped_budget": 0, "complete": False}
            for candidate in plan.downloads:
                self.check_cancelled()
                if time.monotonic() >= deadline:
                    break
                url = candidate.url
                admission = plan.admission(url, self._media_size_hints.get(url))
                if admission.status != "ready":
                    skipped += int(admission.status == "skipped_budget")
                    continue
                retry_key = "media_retry_" + hashlib.sha256(url.encode()).hexdigest()
                retry_at = self.store.get(retry_key, 0)
                if type(retry_at) in (int, float) and retry_at > self.engine.now():
                    continue
                attempts += 1
                outcome = self.download_media(url)
                if outcome is True or outcome == "downloaded":
                    downloaded += 1
                    self.report("media", "Caching images and optional pronunciation audio", downloaded)
                elif outcome is False or outcome == "failed":
                    self.store.set(retry_key, self.engine.now() + 3600)
                elif outcome == "skipped_budget":
                    skipped += 1
                if downloaded >= 40 or attempts >= 60 or time.monotonic() >= deadline:
                    break
            self.check_cancelled()
            cleaned = self.trim_media()
            return {"downloaded": downloaded, "attempts": attempts, "skipped_budget": skipped, "complete": cleaned}
        finally:
            self._media_plan = None

    def download_media(self, url):
        plan = getattr(self, "_media_plan", None)
        if not plan or not plan.complete or not media_plan.valid_url(url):
            return "failed"
        self._media_size_hints = getattr(self, "_media_size_hints", {})
        admission = plan.admission(url)
        if admission.status != "ready":
            return "skipped_budget" if admission.status == "skipped_budget" else "cached" if admission.status == "cached" else "failed"
        temporary = None
        # No Authorization header is attached to media or redirected elsewhere.
        try:
            self.check_cancelled()
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "Omarchy-WaniKani/0.1"}), timeout=10) as response:
                mime = response.headers.get_content_type()
                extension = media_plan.MIMES[plan.candidates[url].kind].get(mime)
                if not extension:
                    return "failed"
                hint = media_plan._length_hint(response.headers.get("Content-Length"))
                admission = plan.admission(url, hint)
                if admission.status == "skipped_budget":
                    self._media_size_hints[url] = hint
                    return "skipped_budget"
                if admission.status != "ready":
                    return "failed"
                self.check_cancelled()
                data = response.read(admission.max_bytes + 1)
                self.check_cancelled()
                decision = plan.placement(url, len(data))
                if decision.status == "skipped_budget":
                    self._media_size_hints[url] = len(data)
                    return "skipped_budget"
                if decision.status != "accepted" or (hint is not None and len(data) < hint):
                    return "failed"
                dest = self.media_dir / (hashlib.sha256(url.encode()).hexdigest() + extension)
                if any(item.path == dest for item in plan.cached.values()):
                    # Corrupt metadata must not let a new URL overwrite a
                    # different registered asset at its generated filename.
                    return "failed"
                # A unique exclusive temporary file cannot follow a stale
                # symlink. The final atomic replace does not follow one either.
                with tempfile.NamedTemporaryFile(dir=self.media_dir, prefix="download-", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                self.check_cancelled()
                temporary.replace(dest)
                temporary = None
                now = time.time()
                try:
                    self.store.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?)", (url, str(dest), len(data), now))
                    plan.remember(url, dest, now)
                except BaseException:
                    dest.unlink(missing_ok=True)
                    self.store.execute("DELETE FROM media WHERE url=? AND path=?", (url, str(dest)))
                    raise
                if self.cancelled.is_set():
                    self._remove_media((plan.cached[url],), plan)
                    self.check_cancelled()
                if not self._remove_media(decision.evictions, plan):
                    # Failure to reclaim space cannot leave a new file above
                    # the user's limit. Existing undeletable media stays intact.
                    self._remove_media((plan.cached[url],), plan)
                    return "failed"
                self._media_size_hints.pop(url, None)
                return "downloaded"
        except (OSError, ValueError, http.client.HTTPException):
            return "failed"
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def trim_media(self):
        plan = getattr(self, "_media_plan", None) or media_plan.build(self.engine, self.media_dir,
            cancelled=self.cancelled.is_set, clock=time.monotonic)
        self.check_cancelled()
        if not plan.complete:
            return False
        for url in plan.cleanup_metadata:
            self.store.execute("DELETE FROM media WHERE url=?", (url,))
        if not self._remove_media(plan.orphans, plan):
            return False
        return self._remove_media(plan.evictions(), plan)

    def _remove_media(self, entries, plan):
        removed = set()
        for entry in entries:
            # Recheck immediately before unlinking; never follow stored paths
            # outside this cache or delete symlink targets.
            current = media_plan._owned_file(plan.directory, entry.url, str(entry.path), allow_empty=not entry.registered)
            if current and current.path not in removed:
                try:
                    current.path.unlink()
                    removed.add(current.path)
                except OSError:
                    return False
            if entry.registered:
                self.store.execute("DELETE FROM media WHERE url=? AND path=?", (entry.url, str(entry.path)))
            plan.forget(entry.url)
        return True

    def clear_media(self):
        for row in self.store.rows("SELECT path FROM media"):
            path = Path(row[0])
            if path.parent == self.media_dir:
                path.unlink(missing_ok=True)
        self.store.execute("DELETE FROM media")
