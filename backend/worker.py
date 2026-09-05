#!/usr/bin/env python3
"""Private, versioned JSON-lines bridge owned by the Omarchy plugin service."""
import argparse
import fcntl
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from wanikani import VERSION
from wanikani.api import Api, ApiError, RequestBudget, elapsed_clock, user_id, validate_user
from wanikani.common import UserError, epoch, private_dir, stamp, state_home
from wanikani.credentials import Keyring
from wanikani import diagnostics
from wanikani.engine import Engine
from wanikani.readiness import OfflineReadiness
from wanikani.store import Store
from wanikani.sync import Synchronizer


class Worker:
    def __init__(self, directory, emit):
        self.directory = private_dir(directory)
        self.emit = emit
        self.keyring = Keyring()
        self.request_budget = RequestBudget()
        self.job_lock = threading.Lock()
        self.audio_job_lock = threading.Lock()
        self.preparation_lock = threading.Lock()
        self.preparation_job = None
        self.account_job = False
        self.snapshot_lock = threading.Lock()
        self.snapshot_sequence = 0
        self.last_attempt = 0
        self.last_clock = time.time()
        self.last_monotonic = time.monotonic()
        self.last_elapsed = elapsed_clock()
        self.sync = None
        self.token = None
        self.stopping = False
        mode = "account"
        try:
            mode = json.loads((directory / "mode.json").read_text()).get("mode", mode)
        except (OSError, ValueError):
            pass
        self.select_mode(mode == "demo")

    def select_mode(self, demo):
        self.sync = None
        self.token = None
        self.sync_progress = {"stage": "idle", "message": "", "completed": 0, "total": None, "active": False}
        if hasattr(self, "readiness"):
            self.readiness.stop()
        if hasattr(self, "engine"):
            self.engine.store.close()
        store = Store(self.directory / ("demo.sqlite3" if demo else "account.sqlite3"))
        self.engine = Engine(store, demo=demo)
        readiness = OfflineReadiness(self.engine)
        readiness.changed = lambda value: self.readiness_changed(readiness, value)
        self.readiness = readiness
        modefile = self.directory / "mode.json"
        modefile.write_text(json.dumps({"mode": "demo" if demo else "account"}))
        modefile.chmod(0o600)

    def snapshot(self):
        # Allocate before reading. A concurrent newer snapshot can finish first;
        # its catalogue counts must not be replaced by this older read later.
        with self.snapshot_lock:
            self.snapshot_sequence += 1
            revision = self.snapshot_sequence
        engine = self.engine
        with engine.store.lock:
            digest_context = (engine.demo, engine.store.get("account_id"), engine.store.get("session_epoch"))
        value = engine.snapshot()
        from wanikani.progress import current_level
        value["learning_progress"] = current_level(engine)
        # Count local activity only at this existing full-refresh boundary.
        # Session-only answers, drafts and audio ratings never call this path.
        # Its dated local history is separate from the account counters above.
        value["learning_digest"] = self.learning_digest(engine, digest_context, value)
        value["state_revision"] = revision
        value["readiness"] = self.readiness.get()
        value["sync_progress"] = dict(self.sync_progress)
        self.readiness.refresh()
        return value

    def learning_digest(self, engine, expected, snapshot):
        try:
            from wanikani.learning_digest import project
            with engine.store.lock:
                current = (engine.demo, engine.store.get("account_id"), engine.store.get("session_epoch"))
                if (engine is not self.engine or current != expected
                        or snapshot.get("session_epoch") != current[2]
                        or snapshot.get("demo") is not bool(current[0])):
                    return None
                return project(engine)
        except Exception:
            # Optional totals cannot break status or emit private exception
            # text. An unavailable aggregate is never fabricated zero activity.
            return None

    def readiness_changed(self, source, value):
        if not self.stopping and source is self.readiness:
            self.emit({"v": 1, "event": "readiness", "data": value})

    def report_progress(self, value):
        self.sync_progress = dict(value)
        if not self.stopping:
            self.emit({"v": 1, "event": "sync_progress", "data": value})

    def changed(self, refresh_readiness=False):
        if not self.stopping:
            if refresh_readiness:
                self.readiness.refresh(force=True)
            self.emit({"v": 1, "event": "state", "data": self.snapshot()})

    def session_changed(self):
        # Answer/lesson navigation changes only the durable session. Publishing
        # a catalogue snapshot here makes the next queued keystroke wait behind
        # unrelated forecast, difficult-item and cache scans.
        if not self.stopping:
            self.emit({"v": 1, "event": "session", "data": self.engine.session_state()})

    def configure_sync(self, token):
        self.token = token
        self.engine.connected = True
        self.sync = Synchronizer(self.engine, Api(token, limiter=self.request_budget), self.directory / "media",
            lambda: self.changed(refresh_readiness=True), self.report_progress)

    def startup(self):
        if self.engine.demo:
            return
        if self.engine.store.get("credential_storage") in ("session", "disconnected"):
            return
        token = self.keyring.get(self.engine.store.get("account_id"))
        if token:
            self.engine.store.set("credential_may_exist", True)
            self.configure_sync(token)
            self.sync.run()

    def credential_may_exist(self):
        known = self.engine.store.get("credential_may_exist")
        if known is not None:
            return bool(known)
        # Migrate prior storage modes conservatively when they refer to a saved
        # credential. Fresh session-only accounts never require Secret Service.
        return self.engine.store.get("credential_storage") in ("keyring", "disconnected")

    def resumable_start(self, args):
        mode = args.get("mode", "reviews")
        if mode == "practice":
            return True  # Ungraded local study never needs a network preflight.
        return self.engine.saved_session(mode) is not None

    def job(self, request_id, fn, account=False):
        if not self.job_lock.acquire(blocking=False):
            if request_id is not None:
                self.reply_error(request_id, UserError("Synchronization is already running. Your saved work is safe.", "busy"))
            return
        self.account_job = account
        def run():
            try:
                value = fn()
                if request_id is not None:
                    self.emit({"v": 1, "id": request_id, "ok": True, "data": value})
            except UserError as error:
                if request_id is not None:
                    self.reply_error(request_id, error)
                else:
                    self.engine.message = str(error)
            except Exception:
                # Never include exception repr/traceback: transports and input
                # may contain secrets. Durable state supports safe diagnosis.
                if request_id is not None:
                    self.reply_error(request_id, UserError("The operation could not be completed. Your saved work was retained.", "internal_error"))
            finally:
                self.account_job = False
                self.job_lock.release()
                self.changed(refresh_readiness=True)
        threading.Thread(target=run, daemon=True, name="wanikani-network").start()

    def prepare_pronunciation(self, request_id, args):
        """Fetch an explicitly requested clip without blocking answers or API reads."""
        arguments = self.pronunciation_args(args)
        if not self.audio_job_lock.acquire(blocking=False):
            self.reply_error(request_id, UserError("Another recording is downloading. Try again shortly.", "busy"))
            return
        engine = self.engine
        try:
            synchronizer = self.sync or Synchronizer(engine, None, self.directory / "media")
        except Exception:
            self.audio_job_lock.release()
            raise
        def run():
            try:
                from wanikani.pronunciation import prepare
                value = prepare(synchronizer, **arguments)
                if not self.stopping:
                    self.emit({"v": 1, "id": request_id, "ok": True, "data": value})
            except UserError as error:
                if not self.stopping:
                    self.reply_error(request_id, error)
            except Exception:
                if not self.stopping:
                    self.reply_error(request_id, UserError("The recording could not be prepared. Try again when connected.", "audio_error"))
            finally:
                self.audio_job_lock.release()
                if not self.stopping and self.engine is engine:
                    self.readiness.refresh(force=True)
        try:
            threading.Thread(target=run, daemon=True, name="wanikani-pronunciation").start()
        except Exception:
            self.audio_job_lock.release()
            raise

    @staticmethod
    def pronunciation_args(args):
        allowed = {"subject_id", "context", "session_id", "revision", "voice_actor_id"}
        if args.get("context") == "kanji_example":
            allowed |= {"parent_subject_id", "origin_context"}
            required = {"subject_id", "context", "parent_subject_id", "origin_context"}
            if args.get("origin_context") == "study":
                required |= {"session_id", "revision"}
            if not required <= set(args):
                raise UserError("Choose the kanji's current whole-word recording context.")
        if not args or set(args) - allowed:
            raise UserError("Choose only the supported pronunciation options.")
        result = {"subject_id": args.get("subject_id"), "context": args.get("context", "details"),
            "session_id": args.get("session_id"), "revision": args.get("revision"),
            "voice_actor_id": args.get("voice_actor_id")}
        if args.get("context") == "kanji_example":
            result.update(parent_subject_id=args["parent_subject_id"], origin_context=args["origin_context"])
        return result

    def prepare_listening(self, request_id):
        """Explicit cache preparation shares media ownership, never study state."""
        if self.account_job:
            raise UserError("Wait for account connection before preparing recordings.", "busy")
        if not self.audio_job_lock.acquire(blocking=False):
            self.reply_error(request_id, UserError("Another recording is downloading. Try again shortly.", "busy"))
            return
        engine = self.engine
        cancelled = threading.Event()
        job = (request_id, cancelled)
        try:
            synchronizer = self.sync or Synchronizer(engine, None, self.directory / "media")
            with self.preparation_lock:
                self.preparation_job = job
        except Exception:
            self.audio_job_lock.release()
            raise

        def progress(value):
            if not self.stopping:
                # Job progress is neutral aggregate data. It never carries a
                # subject, URL, recording handle or account identifier.
                safe = self.preparation_result({"status": "preparing", **value})
                self.emit({"v": 1, "event": "listening_preparation", "data": {"job_id": request_id, **safe}})

        def release():
            with self.preparation_lock:
                if self.preparation_job is job:
                    self.preparation_job = None
            self.audio_job_lock.release()

        def run():
            try:
                from wanikani.listening_preparation import prepare
                progress({"status": "preparing", "downloaded": 0, "already_cached": 0, "failed": 0,
                    "skipped_budget": 0, "cancelled": False, "complete": False})
                value = self.preparation_result(prepare(synchronizer,
                    cancelled=lambda: self.stopping or cancelled.is_set(), progress=progress))
                if not self.stopping:
                    self.emit({"v": 1, "id": request_id, "ok": True, "data": value})
            except UserError as error:
                if not self.stopping:
                    self.reply_error(request_id, error)
            except Exception:
                if not self.stopping:
                    self.reply_error(request_id, UserError("The recordings could not be prepared. Try again when connected.", "audio_error"))
            finally:
                release()
                if not self.stopping and self.engine is engine:
                    self.readiness.refresh(force=True)
        try:
            threading.Thread(target=run, daemon=True, name="wanikani-listening-cache").start()
        except Exception:
            release()
            raise

    @staticmethod
    def preparation_result(value):
        counts = ("downloaded", "already_cached", "failed", "skipped_budget")
        statuses = ("preparing", "ready", "partial", "cancelled", "unavailable")
        reasons = ("", "ready", "needs_download", "saved_session", "offline", "no_candidates", "daily_limit",
            "incomplete", "budget", "cancelled", "permission_changed", "download_failed", "cache_cleanup")
        if (not isinstance(value, dict) or value.get("status") not in statuses
                or value.get("reason", "") not in reasons
                or any(type(value.get(key, 0)) is not int or not 0 <= value.get(key, 0) <= 5 for key in counts)
                or sum(value.get(key, 0) for key in counts) > 5
                or any(type(value.get(key, False)) is not bool for key in ("cancelled", "complete"))):
            raise UserError("The recording preparation returned an unreadable result. Check availability before trying again.", "audio_error")
        return {"status": value["status"], "reason": value.get("reason", ""),
            **{key: value.get(key, 0) for key in counts},
            "cancelled": value.get("cancelled", False), "complete": value.get("complete", False)}

    def cancel_listening_preparation(self, job_id=None):
        with self.preparation_lock:
            job = self.preparation_job
            matches = bool(job and (job_id is None or job[0] == job_id))
            if matches:
                job[1].set()
            return matches

    def reply_error(self, rid, error):
        self.emit({"v": 1, "id": rid, "ok": False, "error": {"code": error.code, "message": str(error)}})

    def authenticate(self, args):
        if self.engine.demo:
            raise UserError("Leave the demo before connecting an account.")
        token = str(args.get("token", "")).strip()
        if not token or len(token) > 512 or any(c.isspace() for c in token):
            raise UserError("Enter a valid personal API token.")
        api = Api(token, limiter=self.request_budget)
        user, _ = api.request("user")
        validate_user(user)
        identity = user_id(user)
        account = self.engine.store.get("account_id")
        if account and account != identity:
            raise UserError("Local study data belongs to another account. Remove that account's local data before switching.", "account_mismatch")
        self.engine.store.set("account_id", identity)
        self.engine.store.set("user", user)
        if self.engine.store.get("settings") is None:
            preferences = user["data"].get("preferences", {})
            self.engine.set_settings({"autoplay_audio": bool(preferences.get("reviews_autoplay_audio", False)),
                "autoplay_lessons": bool(preferences.get("lessons_autoplay_audio", False))})
        remember = bool(args.get("remember", True))
        may_exist = self.credential_may_exist()
        # Disable automatic restoration before touching the keyring so a crash
        # during a switch to session-only authentication cannot restore old auth.
        self.engine.store.set("credential_storage", "session")
        saved = False
        if remember:
            self.engine.store.set("credential_may_exist", True)
            saved = self.keyring.set(identity, token)
            may_exist = may_exist or self.keyring.may_have_written
        # An older credential must not silently reconnect a session-only login.
        # The persisted storage mode remains authoritative if the keyring is
        # temporarily unavailable while clearing that previous credential.
        cleared_previous = saved or not may_exist or self.keyring.delete(identity)
        with self.engine.store.transaction():
            self.engine.store.set("credential_storage", "keyring" if saved else "session")
            self.engine.store.set("credential_may_exist", bool(saved or (may_exist and not cleared_previous)))
        self.configure_sync(token)
        # A newly supplied credential may repair a definite permission denial;
        # uncertain operations are never returned to pending here.
        self.engine.store.execute("UPDATE outbox SET state='pending',detail='Rechecking with new credentials' WHERE state='blocked'")
        self.sync.run()
        return {"connected": True, "remembered": saved, "credential_cleanup_needed": not cleared_previous}

    def rhythm_context(self, args):
        context = args.get("context", {})
        if not isinstance(context, dict):
            raise UserError("Study reminders need desktop context.")
        value = self.engine.snapshot()
        from wanikani import listening
        try:
            listen_count = listening.status(self.engine)["available"]
        except Exception:
            # An optional listening-cache aggregate cannot disable review
            # reminders or prevent changing their schedule.
            listen_count = 0
        # Desktop flags come from the shared shell services. Account access,
        # work counts and time remain owned by this worker.
        return {**context, "now": self.engine.now(), "demo": self.engine.demo,
            "account_ready": bool(self.engine.connected and value.get("username") and self.engine.max_level() > 0
                and self.engine.status in ("online", "offline", "rate_limited", "demo")),
            "vacation": value.get("vacation", False), "clock_untrusted": bool(self.engine.clock_untrusted or abs(self.engine.clock_offset) > 300),
            "review_count": value.get("reviews", 0), "listen_count": listen_count,
            "next_review_at": epoch(value.get("next_reviews_at")),
            "last_study_at": self.engine.store.get("last_study_at", 0)}

    def note_study_activity(self, method):
        if method in ("start", "answer", "advance", "lesson_next", "lesson_navigate", "listen", "listen_media", "dictation", "dictation_media"):
            now = self.engine.now()
            # A thirty-second observation is enough for gentle reminder
            # suppression; avoid a second journal flush on every keystroke.
            try:
                previous = self.engine.store.get("last_study_at", 0)
                if type(previous) not in (int, float) or now - previous >= 30:
                    self.engine.store.set("last_study_at", now)
            except Exception:
                # Reminder housekeeping cannot turn a durably accepted answer
                # into an apparent failure after its study transaction commits.
                pass

    def command(self, rid, method, args):
        result = self.engine.command(rid, method, args)
        self.note_study_activity(method)
        return result

    def handle(self, request):
        if not isinstance(request, dict) or request.get("v") != 1:
            raise UserError("Unsupported protocol version.")
        rid = str(request.get("id", ""))[:160]
        method = request.get("method")
        args = request.get("args", {})
        if not rid or not isinstance(args, dict):
            raise UserError("Invalid request envelope.")
        previous_session = self.engine.store.session() if method == "advance" else None
        if method == "authenticate":
            if self.audio_job_lock.locked():
                raise UserError("Wait for the recording download before changing account state.", "busy")
            self.job(rid, lambda: self.authenticate(args), account=True)
            return
        if method == "sync":
            if self.engine.demo:
                self.engine.confirm_demo()
            elif self.sync:
                self.last_attempt = time.time()
                self.job(rid, lambda: {"synced": self.sync.run(bool(args.get("full")))})
                return
            else:
                raise UserError("Connect your account in Settings.", "disconnected")
            result = {"synced": True}
        elif method == "start" and self.sync and not self.resumable_start(args) and not self.job_lock.locked() and time.time() - self.last_attempt > 60:
            def prepare():
                self.last_attempt = time.time()
                self.sync.run(for_study=True)
                return self.command(rid, method, args)
            self.job(rid, prepare)
            return
        elif method == "tick":
            now, monotonic, elapsed = time.time(), time.monotonic(), elapsed_clock()
            # Linux monotonic time excludes suspend; boottime includes it. A
            # wake asks for refresh but does not invalidate offline study time.
            clock_change = abs((now - self.last_clock) - (elapsed - self.last_elapsed)) > 30
            woke = (elapsed - self.last_elapsed) - (monotonic - self.last_monotonic) > 30
            if clock_change and not self.engine.demo:
                self.engine.clock_untrusted = True
                self.engine.status = "clock_changed"
                self.engine.message = "The system clock changed. Refresh to verify the time before graded study."
            self.last_clock, self.last_monotonic, self.last_elapsed = now, monotonic, elapsed
            interval = 60 if self.engine.status in ("offline", "rate_limited") else 300
            if self.sync and not self.job_lock.locked() and (clock_change or woke or now - self.last_attempt >= interval):
                self.last_attempt = now
                self.job(None, lambda: self.sync.run())
            result = {"alive": True, "woke": woke, "clock_change": clock_change}
        elif method == "snapshot":
            result = self.snapshot()
        elif method == "readiness":
            self.readiness.refresh(force=bool(args.get("refresh")))
            result = self.readiness.get()
        elif method == "search":
            result = self.engine.search(args.get("text", ""), args.get("limit", 30), args.get("filters"), args.get("reading_query"))
        elif method == "reading_trail":
            from wanikani.trail import reading_trail
            result = reading_trail(self.engine, args.get("text", ""))
        elif method == "practice_catalogue":
            from wanikani.practice import catalogue
            result = catalogue(self.engine, group=args.get("group", "suggested"), query=args.get("query", ""),
                offset=args.get("offset", 0), limit=args.get("limit", 30), readiness_scope=args.get("readiness_scope", "all"))
        elif method == "recovery":
            from wanikani.recovery import catalogue
            result = catalogue(self.engine, state=args.get("state", "open"), kind=args.get("kind", "all"),
                offset=args.get("offset", 0), limit=args.get("limit", 30))
        elif method == "level_history":
            from wanikani.level_history import catalogue
            if set(args) - {"offset", "limit"}:
                raise UserError("Choose only a page of cached level history.")
            result = catalogue(self.engine, offset=args.get("offset", 0), limit=args.get("limit", 20))
        elif method == "kanji_examples":
            from wanikani.kanji_examples import catalogue
            result = catalogue(self.engine, args)
        elif method == "pronunciation":
            from wanikani.pronunciation import status
            result = status(self.engine, **self.pronunciation_args(args))
        elif method == "pronunciation_sample":
            from wanikani.pronunciation import sample
            result = sample(self.engine, args.get("voice_actor_id"))
        elif method == "pronunciation_prepare":
            # Authentication changes the account grant, so finish it before
            # opening a new media job. Ordinary synchronization can coexist.
            if self.account_job:
                raise UserError("Wait for account connection before downloading pronunciation.", "busy")
            self.prepare_pronunciation(rid, args)
            return
        elif method == "voices":
            from wanikani.voices import catalogue
            result = catalogue(self.engine)
        elif method in ("rhythm_preview", "rhythm_claim", "rhythm_configure"):
            from wanikani import reminders
            context = self.rhythm_context(args)
            if method == "rhythm_preview":
                result = reminders.preview(self.engine, context, args.get("patch"))
            elif method == "rhythm_claim":
                result = reminders.claim(self.engine, context)
            else:
                result = reminders.configure(self.engine, args.get("patch", {}), context)
        elif method == "lesson_catalogue":
            from wanikani.lessons import catalogue
            result = catalogue(self.engine, subject_type=args.get("subject_type", "all"),
                offset=args.get("offset", 0), limit=args.get("limit", 30))
        elif method == "lesson_preview":
            from wanikani.lessons import preview
            result = preview(self.engine, subject_ids=args.get("subject_ids"), limit=args.get("limit", 5))
        elif method == "listen_state":
            from wanikani import listening
            with self.engine.store.lock:
                try:
                    status = listening.status(self.engine)
                except UserError as error:
                    status = {"available": 0, "due": 0, "new_remaining": None, "saved": None,
                        "settings": {}, "complete": False, "local_only": True, "message": str(error)}
                try:
                    from wanikani.listening_preparation import availability
                    status["preparation"] = availability(self.engine)
                except Exception:
                    # An optional preflight failure must not block a cached
                    # listening session that is otherwise safe to resume.
                    status["preparation"] = {"ready": min(5, status["available"]), "needs_download": 0,
                        "complete": False, "reason": "unavailable", "message": "Recording preparation could not be checked. Reload to try again."}
                result = {"status": status, "session": listening.view(self.engine)}
        elif method == "listen_prepare":
            if args:
                raise UserError("Recording preparation takes no subject, URL or other arguments.")
            self.prepare_listening(rid)
            return
        elif method == "listen_prepare_cancel":
            if set(args) != {"job_id"} or not isinstance(args["job_id"], str) or not 1 <= len(args["job_id"]) <= 160:
                raise UserError("Choose the current recording preparation to cancel.")
            result = {"cancelled": self.cancel_listening_preparation(args["job_id"])}
        elif method == "listen":
            from wanikani import listening
            result = listening.command(self.engine, rid, args.get("action"), args)
            if args.get("action") in ("start", "reveal", "rate"):
                self.note_study_activity(method)
        elif method == "listen_media":
            from wanikani import listening
            with self.engine.store.lock:
                result = listening.media(self.engine, args.get("handle"))
                result["session"] = listening.view(self.engine)
            self.note_study_activity(method)
        elif method == "dictation_state":
            from wanikani import dictation
            if args:
                raise UserError("Dictation status takes no arguments.", "invalid_request")
            with self.engine.store.lock:
                try:
                    status = dictation.status(self.engine)
                except UserError as error:
                    status = {"available": 0, "due": 0, "new_remaining": None, "new_limit": 5,
                        "saved": None, "settings": {}, "complete": False, "local_only": True, "message": str(error)}
                result = {"status": status, "session": dictation.view(self.engine)}
        elif method == "dictation":
            from wanikani import dictation
            arguments = dict(args)
            action = arguments.pop("action", None)
            result = dictation.command(self.engine, rid, action, arguments)
            if action in ("start", "heard", "check", "continue"):
                self.note_study_activity(method)
        elif method == "dictation_media":
            from wanikani import dictation
            if set(args) != {"handle"}:
                raise UserError("Choose only the current dictation recording handle.", "invalid_request")
            with self.engine.store.lock:
                result = dictation.media(self.engine, args["handle"])
                result["session"] = dictation.view(self.engine)
            self.note_study_activity(method)
        elif method == "dictation_draft":
            from wanikani import dictation
            if not {"session_id", "handle", "text", "cursor"} <= set(args) or set(args) - {"session_id", "handle", "text", "cursor", "preedit"}:
                raise UserError("Use only the current dictation draft fields.", "invalid_request")
            result = dictation.draft(self.engine, args["session_id"], args["handle"], args["text"], args["cursor"], args.get("preedit", ""))
        elif method == "srs_catalogue":
            from wanikani.srs_explorer import catalogue
            if set(args) - {"group", "subject_type", "level", "stage", "order", "offset", "limit"}:
                raise UserError("Choose only the cached SRS explorer filters.", "invalid_request")
            result = catalogue(self.engine, group=args.get("group", "apprentice"),
                subject_type=args.get("subject_type"), level=args.get("level"), stage=args.get("stage"),
                order=args.get("order", "level"), offset=args.get("offset", 0), limit=args.get("limit", 24))
        elif method == "progress_details":
            from wanikani.srs_explorer import guarded_details
            if set(args) != {"subject_id"}:
                raise UserError("Choose one subject from current cached progress.", "invalid_request")
            result = guarded_details(self.engine, args["subject_id"])
        elif method == "progress":
            from wanikani.progress import overview
            result = overview(self.engine)
        elif method == "learning_insights":
            from wanikani import insights, listening
            value = self.engine.snapshot()
            availability = {"reviews": value.get("reviews", 0), "lessons": value.get("lessons", 0)}
            try:
                availability["listening"] = listening.status(self.engine)["available"]
            except Exception:
                # Clock/access restrictions on optional listening cannot hide
                # the learner's already-recorded local activity.
                pass
            result = insights.overview(self.engine, availability=availability)
        elif method == "level_board":
            from wanikani.progress import level_board
            result = level_board(self.engine, level=args.get("level"), subject_type=args.get("subject_type"),
                offset=args.get("offset", 0), limit=args.get("limit", 60))
        elif method == "subject_status":
            from wanikani.progress import subject_status
            result = subject_status(self.engine, args.get("subject_id"))
        elif method == "session_report":
            from wanikani.session_report import report
            result = report(self.engine, args.get("session_id"))
        elif method == "details":
            result = self.engine.details(int(args["subject_id"]))
        elif method == "ambient":
            result = self.engine.ambient()
        elif method == "session":
            result = self.engine.session_view()
        elif method in ("use_demo", "disconnect", "delete_data", "clear_cache", "resolve"):
            if self.job_lock.locked() or self.audio_job_lock.locked():
                raise UserError("Wait for synchronization and recording downloads to finish before changing account state.", "busy")
            if method == "use_demo":
                self.select_mode(bool(args.get("enabled", True)))
                if not self.engine.demo:
                    self.job(None, self.startup)
                result = {"demo": self.engine.demo}
            elif method == "disconnect":
                may_exist = self.credential_may_exist()
                self.sync = None
                self.token = None
                self.engine.connected = False
                self.engine.status = "disconnected"
                self.engine.store.set("credential_storage", "disconnected")
                self.engine.store.set("credential_may_exist", may_exist)
                if may_exist and not self.keyring.delete(self.engine.store.get("account_id")):
                    self.changed()
                    raise UserError("Disconnected. A saved token may remain in the keyring; unlock it and disconnect again to remove it.")
                self.engine.store.set("credential_may_exist", False)
                result = {"disconnected": True}
            elif method == "clear_cache":
                cleaner = self.sync or Synchronizer(self.engine, None, self.directory / "media")
                cleaner.clear_media()
                result = {"cleared": True}
            elif method == "delete_data":
                if args.get("confirmation") != "DELETE":
                    raise UserError("Type DELETE to remove local account data.")
                pending = self.engine.store.rows("SELECT COUNT(*) FROM outbox WHERE state NOT IN ('confirmed','discarded')")[0][0]
                if pending and not args.get("discard_pending"):
                    raise UserError("Resolve pending work first, or explicitly choose to discard it.")
                cleanup_needed = (not self.engine.demo and self.credential_may_exist()
                    and not self.keyring.delete(self.engine.store.get("account_id")))
                self.sync = None
                self.token = None
                self.engine.connected = False
                with self.engine.store.transaction():
                    for table in ("meta", "resources", "sessions", "outbox", "events", "commands"):
                        self.engine.store.execute("DELETE FROM " + table)
                cleaner = self.sync or Synchronizer(self.engine, None, self.directory / "media")
                cleaner.clear_media()
                # DELETE alone leaves personal data in free SQLite pages and
                # the WAL. Compact and truncate after explicit deletion.
                self.engine.store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.engine.store.execute("VACUUM")
                self.engine.store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                diagnostics.clear(self.directory, self.engine.demo)
                self.select_mode(self.engine.demo)
                if not self.engine.demo:
                    self.engine.store.set("credential_storage", "disconnected")
                    self.engine.store.set("credential_may_exist", False)
                result = {"deleted": True, "credential_cleanup_needed": bool(cleanup_needed)}
                if cleanup_needed:
                    result["warning"] = "Local data was deleted. A saved token may remain in the keyring; remove the WaniKani for Omarchy credential after unlocking it. Automatic reconnect is disabled."
                    self.engine.message = result["warning"]
            else:
                resolver = self.sync or Synchronizer(self.engine, None, self.directory / "media")
                result = resolver.resolve(args["id"], args.get("action", "keep_remote"))
        elif method == "diagnostics":
            result = diagnostics.export(self.directory, self.engine.demo, self.engine.snapshot(),
                self.engine.store.rows("PRAGMA user_version")[0][0])
        else:
            result = self.command(rid, method, args)
        reply = {"v": 1, "id": rid, "ok": True, "data": result}
        if (method in ("correct", "advance", "finish")
                or method == "listen" and args.get("action") in ("rate", "skip", "undo")
                or method == "dictation" and args.get("action") in ("continue", "skip", "undo")):
            # The successful local result is durable. A snapshot already
            # started at or below this sequence may predate that mutation;
            # only a later-started snapshot can clear the digest's stale marker.
            with self.snapshot_lock:
                reply["learning_after_revision"] = self.snapshot_sequence
        self.emit(reply)
        session_only = method in ("answer", "correct", "finish", "lesson_next", "lesson_navigate", "start")
        if method == "advance" and previous_session:
            current = self.engine.store.session()
            session_only = bool(current and current["id"] == previous_session["id"]
                and current["completed"] == previous_session["completed"])
        if session_only:
            self.session_changed()
        elif method not in ("snapshot", "readiness", "draft", "editor_draft", "editor_discard", "search", "reading_trail", "practice_catalogue", "recovery", "voices", "pronunciation", "pronunciation_sample", "kanji_examples", "rhythm_preview", "rhythm_claim", "rhythm_configure", "lesson_catalogue", "lesson_preview", "listen_state", "listen_prepare_cancel", "listen", "listen_media", "dictation_state", "dictation", "dictation_media", "dictation_draft", "progress", "srs_catalogue", "progress_details", "learning_insights", "level_history", "level_board", "subject_status", "session_report", "details", "ambient", "session", "tick", "diagnostics"):
            self.changed(refresh_readiness=method in ("advance", "settings", "resolve", "clear_cache", "disconnect", "delete_data", "use_demo"))
        if (method in ("advance", "set_material") and self.sync and not self.job_lock.locked()
                and self.engine.store.rows("SELECT 1 FROM outbox WHERE state='pending' LIMIT 1")):
            self.last_attempt = time.time()
            self.job(None, lambda: self.sync.run())


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args()
    directory = private_dir(args.state_dir) if args.state_dir else state_home()
    lock = open(directory / "worker.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("WaniKani worker already owns this state directory.", file=sys.stderr)
        return 2
    output_lock = threading.Lock()
    def emit(value):
        with output_lock:
            try:
                sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                pass
    worker = Worker(directory, emit)
    emit({"v": 1, "event": "ready", "data": {"version": VERSION}})
    worker.changed()
    worker.job(None, worker.startup)
    try:
        while True:
            line = sys.stdin.readline(1024 * 1024 + 1)
            if not line:
                break
            if len(line) > 1024 * 1024:
                break
            request = None
            try:
                request = json.loads(line)
                worker.handle(request)
            except UserError as error:
                worker.reply_error(str(request.get("id", "")) if isinstance(request, dict) else "", error)
            except (ValueError, TypeError, KeyError):
                worker.reply_error(str(request.get("id", "")) if isinstance(request, dict) else "", UserError("Malformed request."))
            except Exception:
                worker.reply_error(str(request.get("id", "")) if isinstance(request, dict) else "", UserError("An internal operation failed; saved work was retained.", "internal_error"))
    finally:
        worker.stopping = True
        worker.cancel_listening_preparation()
        worker.readiness.stop()
        if worker.sync:
            worker.sync.cancelled.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
