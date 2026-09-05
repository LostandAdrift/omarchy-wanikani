import json
import sqlite3
import threading
from contextlib import contextmanager
from .common import private_dir


class Store:
    def __init__(self, path):
        private_dir(path.parent)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=FULL;
          PRAGMA foreign_keys=ON;
          PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS resources (
            kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
            PRIMARY KEY(kind,id));
          CREATE INDEX IF NOT EXISTS resource_subject ON resources(kind,json_extract(body,'$.data.subject_id'));
          CREATE INDEX IF NOT EXISTS resource_subject_numeric ON resources(kind,CAST(json_extract(body,'$.data.subject_id') AS INTEGER));
          CREATE INDEX IF NOT EXISTS resource_numeric_id ON resources(kind,CAST(id AS INTEGER));
          CREATE INDEX IF NOT EXISTS resource_level ON resources(kind,json_extract(body,'$.data.level'));
          CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject_id INTEGER NOT NULL,
            state TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '');
          CREATE INDEX IF NOT EXISTS outbox_state ON outbox(state,subject_id);
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, session_id TEXT, subject_id INTEGER,
            kind TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS media (url TEXT PRIMARY KEY, path TEXT NOT NULL, size INTEGER NOT NULL, used_at REAL NOT NULL);
          PRAGMA user_version=1;
        """)
        # A process disappearing between HTTP send and commit has an unknown outcome.
        self.execute("UPDATE outbox SET state='uncertain',detail='Interrupted while sending; check remote progress before recovery.' WHERE state='inflight'")

    @contextmanager
    def transaction(self):
        with self.lock:
            nested = self.db.in_transaction
            if not nested:
                self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                if not nested:
                    self.db.execute("COMMIT")
            except BaseException:
                if not nested and self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def execute(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    def rows(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def get(self, key, default=None):
        rows = self.rows("SELECT body FROM meta WHERE key=?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set(self, key, value):
        self.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def put(self, resource):
        if not isinstance(resource, dict) or "id" not in resource or not isinstance(resource.get("data"), dict):
            raise ValueError("Malformed API resource")
        self.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?)", (resource["object"], str(resource["id"]), json.dumps(resource, ensure_ascii=False)))

    def resource(self, kind, rid):
        rows = self.rows("SELECT body FROM resources WHERE kind=? AND id=?", (kind, str(rid)))
        return json.loads(rows[0][0]) if rows else None

    def subject(self, rid):
        rows = self.rows("SELECT body FROM resources WHERE kind IN ('radical','kanji','vocabulary','kana_vocabulary') AND id=?", (str(rid),))
        return json.loads(rows[0][0]) if rows else None

    def related(self, kind, subject_id):
        rows = self.rows("SELECT body FROM resources WHERE kind=? AND json_extract(body,'$.data.subject_id')=?", (kind, subject_id))
        return json.loads(rows[0][0]) if rows else None

    def all(self, kind):
        return [json.loads(r[0]) for r in self.rows("SELECT body FROM resources WHERE kind=?", (kind,))]

    def save_session(self, session):
        self.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (session["id"], json.dumps(session, ensure_ascii=False)))
        self.set("active_session", session["id"])

    def session(self):
        rows = self.rows("SELECT body FROM sessions WHERE id=?", (self.get("active_session"),))
        return json.loads(rows[0][0]) if rows else None

    def event(self, session_id, subject_id, kind, created_at, data):
        self.execute("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)", (session_id, subject_id, kind, created_at, json.dumps(data, ensure_ascii=False)))

    def close(self):
        with self.lock:
            self.db.close()
