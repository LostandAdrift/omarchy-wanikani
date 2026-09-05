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
from wanikani.api import Api, ApiError, validate_user
from wanikani.common import UserError, private_dir, stamp, state_home
from wanikani.credentials import Keyring
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani.sync import Synchronizer


class Worker:
    def __init__(self, directory, emit):
        self.directory = private_dir(directory)
        self.emit = emit
        self.keyring = Keyring()
        self.job_lock = threading.Lock()
        self.last_attempt = 0
        self.last_clock = time.time()
        self.last_monotonic = time.monotonic()
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
        if hasattr(self, "engine"):
            self.engine.store.close()
        store = Store(self.directory / ("demo.sqlite3" if demo else "account.sqlite3"))
        self.engine = Engine(store, demo=demo)
        modefile = self.directory / "mode.json"
        modefile.write_text(json.dumps({"mode": "demo" if demo else "account"}))
        modefile.chmod(0o600)

    def changed(self):
        if not self.stopping:
            self.emit({"v": 1, "event": "state", "data": self.engine.snapshot()})

    def configure_sync(self, token):
        self.token = token
        self.engine.connected = True
        self.sync = Synchronizer(self.engine, Api(token), self.directory / "media", self.changed)

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

    def job(self, request_id, fn):
        if not self.job_lock.acquire(blocking=False):
            if request_id is not None:
                self.reply_error(request_id, UserError("Synchronization is already running. Your saved work is safe.", "busy"))
            return
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
                self.job_lock.release()
                self.changed()
        threading.Thread(target=run, daemon=True, name="wanikani-network").start()

    def reply_error(self, rid, error):
        self.emit({"v": 1, "id": rid, "ok": False, "error": {"code": error.code, "message": str(error)}})

    def authenticate(self, args):
        if self.engine.demo:
            raise UserError("Leave the demo before connecting an account.")
        token = str(args.get("token", "")).strip()
        if not token or len(token) > 512 or any(c.isspace() for c in token):
            raise UserError("Enter a valid personal API token.")
        api = Api(token)
        user, _ = api.request("user")
        validate_user(user)
        account = self.engine.store.get("account_id")
        if account and account != user.get("id"):
            raise UserError("Local study data belongs to another account. Remove that account's local data before switching.", "account_mismatch")
        self.engine.store.set("account_id", user["id"])
        self.engine.store.set("user", user)
        if self.engine.store.get("settings") is None:
            preferences = user["data"].get("preferences", {})
            self.engine.set_settings({"autoplay_audio": bool(preferences.get("reviews_autoplay_audio", False))})
        remember = bool(args.get("remember", True))
        may_exist = self.credential_may_exist()
        # Disable automatic restoration before touching the keyring so a crash
        # during a switch to session-only authentication cannot restore old auth.
        self.engine.store.set("credential_storage", "session")
        saved = False
        if remember:
            self.engine.store.set("credential_may_exist", True)
            saved = self.keyring.set(user["id"], token)
            may_exist = may_exist or self.keyring.may_have_written
        # An older credential must not silently reconnect a session-only login.
        # The persisted storage mode remains authoritative if the keyring is
        # temporarily unavailable while clearing that previous credential.
        cleared_previous = saved or not may_exist or self.keyring.delete(user["id"])
        with self.engine.store.transaction():
            self.engine.store.set("credential_storage", "keyring" if saved else "session")
            self.engine.store.set("credential_may_exist", bool(saved or (may_exist and not cleared_previous)))
        self.configure_sync(token)
        # A newly supplied credential may repair a definite permission denial;
        # uncertain operations are never returned to pending here.
        self.engine.store.execute("UPDATE outbox SET state='pending',detail='Rechecking with new credentials' WHERE state='blocked'")
        self.sync.run()
        return {"connected": True, "remembered": saved, "credential_cleanup_needed": not cleared_previous}

    def handle(self, request):
        if not isinstance(request, dict) or request.get("v") != 1:
            raise UserError("Unsupported protocol version.")
        rid = str(request.get("id", ""))[:160]
        method = request.get("method")
        args = request.get("args", {})
        if not rid or not isinstance(args, dict):
            raise UserError("Invalid request envelope.")
        if method == "authenticate":
            self.job(rid, lambda: self.authenticate(args))
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
        elif method == "start" and self.sync and not self.job_lock.locked() and time.time() - self.last_attempt > 60:
            def prepare():
                self.last_attempt = time.time()
                self.sync.run()
                return self.engine.command(rid, method, args)
            self.job(rid, prepare)
            return
        elif method == "tick":
            now, monotonic = time.time(), time.monotonic()
            clock_change = abs((now - self.last_clock) - (monotonic - self.last_monotonic)) > 30
            if clock_change and not self.engine.demo:
                self.engine.clock_untrusted = True
                self.engine.status = "clock_changed"
                self.engine.message = "The clock changed or the computer woke. Refresh to verify the time before graded study."
            self.last_clock, self.last_monotonic = now, monotonic
            interval = 60 if self.engine.status == "offline" else 300
            if self.sync and not self.job_lock.locked() and (clock_change or now - self.last_attempt >= interval):
                self.last_attempt = now
                self.job(None, lambda: self.sync.run())
            result = {"alive": True}
        elif method == "snapshot":
            result = self.engine.snapshot()
        elif method == "search":
            result = self.engine.search(args.get("text", ""))
        elif method == "details":
            result = self.engine.details(int(args["subject_id"]))
        elif method == "ambient":
            result = self.engine.ambient()
        elif method == "session":
            result = self.engine.session_view()
        elif method in ("use_demo", "disconnect", "delete_data", "clear_cache", "resolve"):
            if self.job_lock.locked():
                raise UserError("Wait for the current synchronization to finish before changing account state.", "busy")
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
            snapshot = self.engine.snapshot()
            result = {"version": VERSION, "python": sys.version.split()[0], "protocol": 1,
                "demo": self.engine.demo, "status": snapshot["status"], "pending": snapshot["pending"],
                "attention": snapshot["attention"], "schema": self.engine.store.rows("PRAGMA user_version")[0][0], "cache": snapshot["cache"]}
            destination = self.directory / "diagnostics.json"
            destination.write_text(json.dumps(result, indent=2) + "\n")
            destination.chmod(0o600)
            result["path"] = str(destination)
        else:
            result = self.engine.command(rid, method, args)
        self.emit({"v": 1, "id": rid, "ok": True, "data": result})
        if method not in ("snapshot", "draft", "search", "details", "ambient", "session", "tick", "diagnostics"):
            self.changed()
        if method in ("advance", "set_material") and self.sync and not self.job_lock.locked():
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
        if worker.sync:
            worker.sync.cancelled.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
