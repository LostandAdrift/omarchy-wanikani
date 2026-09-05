import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from .common import private_dir
from .search import KINDS, fold


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
          CREATE INDEX IF NOT EXISTS resource_assignment_schedule ON resources(
            CAST(json_extract(body,'$.data.subject_id') AS INTEGER),
            json_extract(body,'$.data.started_at'),json_extract(body,'$.data.burned_at'),
            json_extract(body,'$.data.hidden'),json_extract(body,'$.data.available_at'),
            json_extract(body,'$.data.unlocked_at')) WHERE kind='assignment';
          DROP INDEX IF EXISTS resource_search_access;
          CREATE INDEX IF NOT EXISTS resource_search_identity ON resources(
            kind,CAST(id AS INTEGER),id,json_extract(body,'$.data.level'),json_extract(body,'$.data.hidden_at'),
            json_type(body,'$.data.level'))
            WHERE kind IN ('radical','kanji','vocabulary','kana_vocabulary');
          CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS sessions_unfinished_graded ON sessions(id)
            WHERE json_extract(body,'$.phase')!='complete' AND json_extract(body,'$.mode')!='practice';
          CREATE INDEX IF NOT EXISTS sessions_completed_at
            ON sessions(julianday(json_extract(body,'$.ended_at')))
            WHERE json_extract(body,'$.phase')='complete'
              AND json_extract(body,'$.mode') IN ('reviews','lessons','practice');
          CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject_id INTEGER NOT NULL,
            state TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '');
          CREATE INDEX IF NOT EXISTS outbox_state ON outbox(state,subject_id);
          CREATE INDEX IF NOT EXISTS outbox_created ON outbox(created_at,id);
          CREATE INDEX IF NOT EXISTS outbox_state_created ON outbox(state,created_at,id);
          CREATE INDEX IF NOT EXISTS outbox_kind_created ON outbox(kind,created_at,id);
          CREATE INDEX IF NOT EXISTS outbox_state_kind_created ON outbox(state,kind,created_at,id);
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, session_id TEXT, subject_id INTEGER,
            kind TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS events_study_window ON events(julianday(created_at),id)
            WHERE kind IN ('answer','correction');
          CREATE INDEX IF NOT EXISTS events_completion_time ON events(julianday(created_at),created_at)
            WHERE kind IN ('subject_complete','practice_complete');
          CREATE INDEX IF NOT EXISTS events_listening_window ON events(julianday(created_at),id)
            WHERE kind IN ('listening_result','listening_undo');
          CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS media (url TEXT PRIMARY KEY, path TEXT NOT NULL, size INTEGER NOT NULL, used_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS search_documents (
            kind TEXT NOT NULL, id TEXT NOT NULL, characters TEXT NOT NULL,
            meanings TEXT NOT NULL, readings TEXT NOT NULL,
            PRIMARY KEY(kind,id));
          CREATE INDEX IF NOT EXISTS search_characters ON search_documents(characters,kind,id);
          CREATE TRIGGER IF NOT EXISTS resources_search_delete AFTER DELETE ON resources
          BEGIN
            DELETE FROM search_documents WHERE kind=OLD.kind AND id=OLD.id;
          END;
        """)
        self.db.create_function("wk_fold", 1, fold, deterministic=True)
        # Keep strict level-type filtering covered by the catalogue index. An
        # older installation upgrades this derived structure atomically once;
        # a crash retains either complete version without touching study data.
        index_sql = self.rows("SELECT sql FROM sqlite_master WHERE name='resource_search_identity'")[0][0]
        if "json_type(body,'$.data.level')" not in index_sql:
            with self.transaction():
                self.execute("DROP INDEX resource_search_identity")
                self.execute("""CREATE INDEX resource_search_identity ON resources(
                  kind,CAST(id AS INTEGER),id,json_extract(body,'$.data.level'),json_extract(body,'$.data.hidden_at'),
                  json_type(body,'$.data.level'))
                  WHERE kind IN ('radical','kanji','vocabulary','kana_vocabulary')""")
        # Derived data contains account content too. The trigger covers bulk SQL
        # deletion, including delete_data, even outside the Store.put path.
        # Backfill only missing documents: old installations and a missing cache
        # table migrate once, while ordinary restarts reuse existing folded text.
        with self.transaction():
            if not self.get("session_epoch"):
                # A deliberate personal-data deletion may recreate an account
                # with the same username. Its old presentation revisions must
                # not keep a deleted session alive in the running shell.
                self.set("session_epoch", str(uuid.uuid4()))
            for row in self.rows("""SELECT r.body FROM resources r LEFT JOIN search_documents d
              ON d.kind=r.kind AND d.id=r.id
              WHERE r.kind IN ('radical','kanji','vocabulary','kana_vocabulary') AND d.id IS NULL"""):
                self._put_search_document(json.loads(row[0]))
            self._migrate_study_references()
            self.execute("PRAGMA user_version=2")
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
        values = (resource["object"], str(resource["id"]), json.dumps(resource, ensure_ascii=False))
        if resource["object"] in KINDS:
            with self.transaction():
                # Subject IDs are unique across all four catalogue types. A
                # server-side type change must replace its old searchable form.
                self.execute("""DELETE FROM resources WHERE id=? AND kind<>?
                  AND kind IN ('radical','kanji','vocabulary','kana_vocabulary')""", (values[1], values[0]))
                self.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?)", values)
                self._put_search_document(resource)
        else:
            self.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?)", values)

    def _put_search_document(self, resource):
        data = resource["data"]
        def text_values(name, key):
            entries = data.get(name)
            if not isinstance(entries, list):
                return []
            return [fold(item[key]) for item in entries
                if isinstance(item, dict) and isinstance(item.get(key), str)]
        # This derived index is for lookup, not answer acceptance. Preserve the
        # authoritative resource for an explicit content error during study,
        # while indexing only text values that can safely be shown/searched.
        meanings = text_values("meanings", "meaning")
        readings = text_values("readings", "reading")
        self.execute("INSERT OR REPLACE INTO search_documents VALUES (?,?,?,?,?)", (
            resource["object"], str(resource["id"]), fold(data.get("characters") if isinstance(data.get("characters"), str) else ""),
            json.dumps(meanings, ensure_ascii=False), json.dumps(readings, ensure_ascii=False)))

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

    def _migrate_study_references(self):
        """Adopt old saved sessions without changing their answers or position."""
        if self.get("study_mode_references") == 1:
            return
        candidates = []
        for key in ("active_session", "graded_session", "practice_session"):
            reference = self.get(key)
            session = self.session(reference) if isinstance(reference, str) else None
            if session and session.get("phase") != "complete":
                candidates.append(session)
        # Older versions kept only one graded pointer. An unfinished record
        # must survive migration even if that pointer no longer names it.
        candidates += [json.loads(row[0]) for row in self.rows("""SELECT body FROM sessions
          WHERE json_extract(body,'$.phase')!='complete' AND json_extract(body,'$.mode')!='practice'
          ORDER BY COALESCE(json_extract(body,'$.revision'),0) DESC,rowid DESC""")]
        for mode in ("reviews", "lessons", "practice"):
            key = mode + "_session" if mode != "practice" else "practice_session"
            reference = self.get(key)
            current = self.session(reference) if isinstance(reference, str) else None
            if current and current.get("mode") == mode and current.get("phase") != "complete":
                continue
            saved = next((session for session in candidates if session.get("mode") == mode), None)
            if saved:
                self.set(key, saved["id"])
        latest = next((session for session in candidates if session.get("mode") in ("reviews", "lessons")), None)
        if latest:
            self.set("graded_session", latest["id"])
        self.set("study_mode_references", 1)

    def save_session(self, session, activate=True):
        with self.transaction():
            revision = self.get("session_revision", 0)
            revision = revision if type(revision) is int and revision >= 0 else 0
            session["revision"] = revision + 1
            self.set("session_revision", session["revision"])
            self.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (session["id"], json.dumps(session, ensure_ascii=False)))
            reference = session["mode"] + "_session"
            if activate or not self.get(reference):
                self.set(reference, session["id"])
            if activate:
                self.set("active_session", session["id"])
                if session["mode"] in ("reviews", "lessons"):
                    self.set("graded_session", session["id"])

    def session(self, session_id=None):
        rows = self.rows("SELECT body FROM sessions WHERE id=?", (session_id or self.get("active_session"),))
        return json.loads(rows[0][0]) if rows else None

    def event(self, session_id, subject_id, kind, created_at, data):
        self.execute("INSERT INTO events(session_id,subject_id,kind,created_at,body) VALUES(?,?,?,?,?)", (session_id, subject_id, kind, created_at, json.dumps(data, ensure_ascii=False)))

    def close(self):
        with self.lock:
            self.db.close()
