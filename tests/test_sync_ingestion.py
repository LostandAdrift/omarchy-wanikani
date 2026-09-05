"""Bounded collection writes leave durable foreground study room to proceed."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.common import UserError, stamp
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani.sync import Synchronizer


def subjects(count=1000):
    """Independent catalogue text; these resources never reach a live API."""
    return [{"id": 10000 + index, "object": "vocabulary", "data_updated_at": stamp(NOW), "data": {
        "characters": "山道", "slug": "fixture-" + str(index), "level": 2, "hidden_at": None,
        "meanings": [{"meaning": "authored trail " + str(index), "primary": True, "accepted_answer": True}],
        "readings": [{"reading": "やまみち", "primary": True, "accepted_answer": True}],
        "meaning_mnemonic": "A quiet path crosses the mountain.",
        "reading_mnemonic": "Read the sign and remember the sound.",
        "component_subject_ids": [2], "amalgamation_subject_ids": [], "auxiliary_meanings": [],
        "context_sentences": [], "pronunciation_audios": [], "character_images": [], "lesson_position": index,
    }} for index in range(count)]


def assignments(count=129, first_id=20000):
    return [{"id": first_id + index, "object": "assignment", "data_updated_at": stamp(NOW), "data": {
        "subject_id": 10000 + index, "subject_type": "vocabulary", "srs_stage": 1,
        "unlocked_at": stamp(NOW - 86400), "started_at": stamp(NOW - 3600),
        "available_at": stamp(NOW + 14400), "burned_at": None, "hidden": False,
    }} for index in range(count)]


class PageApi(FakeApi):
    def __init__(self, store, pages):
        super().__init__(store)
        self.pages = pages
        self.calls = []
        self.after_page = lambda endpoint, index: None

    def collection(self, endpoint, params=None):
        self.calls.append((endpoint, dict(params or {})))
        for index, page in enumerate(self.pages.get(endpoint, [])):
            yield copy.deepcopy(page)
            self.after_page(endpoint, index)


def crash_child(directory, boundary):
    store = Store(directory / "state.sqlite3")
    populate(store, NOW)
    engine = Engine(store, clock=lambda: NOW)
    store.set("cursor_subjects", stamp(NOW - 600))
    store.set("cached_max_level", 60)
    engine.start("practice", 1, [1])
    sync = Synchronizer(engine, PageApi(store, {"subjects": [subjects()]}), directory / "media")
    if boundary == "inside":
        original = store.put
        def put(resource):
            original(resource)
            if resource["id"] == 10160:
                os._exit(73)
        store.put = put
    def yield_after_commit(seconds):
        assert seconds == 0 and not store.db.in_transaction
        engine.draft("saved between collection chunks")
        engine.answer("incorrect authored fixture answer")
        if boundary == "between":
            os._exit(73)
    with patch("wanikani.sync.time.sleep", side_effect=yield_after_commit):
        sync.run(for_study=True)
    raise AssertionError("The requested persistence boundary was not reached")


class CollectionIngestionTests(EngineFixture, unittest.TestCase):
    def sync(self, pages):
        api = PageApi(self.store, pages)
        return Synchronizer(self.engine, api, Path(self.temp.name) / "media"), api

    def count(self):
        return self.store.rows("SELECT COUNT(*) FROM resources WHERE CAST(id AS INTEGER)>=10000")[0][0]

    def old_cursor(self):
        self.store.set("cursor_subjects", stamp(NOW - 600))
        self.store.set("cached_max_level", 60)

    def test_foreground_thread_saves_before_collection_cursor_advances(self):
        self.old_cursor()
        self.engine.start("practice", 1, [1])
        sync, api = self.sync({"subjects": [subjects(257)]})
        observed, errors = [], []
        def yield_after_commit(seconds):
            self.assertEqual(0, seconds)
            self.assertFalse(self.store.db.in_transaction)
            count = self.count()
            def foreground():
                try:
                    self.engine.draft("chunk " + str(count))
                except BaseException as error:
                    errors.append(error)
            task = threading.Thread(target=foreground, daemon=True)
            task.start()
            task.join(2)
            self.assertFalse(task.is_alive(), "The import retained the Store lock while yielding")
            observed.append((count, self.store.get("cursor_subjects")))
        with patch("wanikani.sync.time.sleep", side_effect=yield_after_commit):
            self.assertTrue(sync.run(for_study=True))
        self.assertFalse(errors)
        self.assertEqual([(128, stamp(NOW - 600)), (256, stamp(NOW - 600)), (257, stamp(NOW - 600))], observed)
        self.assertEqual("chunk 257", self.engine.session_view()["draft"])
        self.assertEqual(stamp(NOW - 2), self.store.get("cursor_subjects"))
        self.assertEqual([], api.mutations)

    def test_cancel_during_yield_keeps_old_cursor_and_only_committed_chunk(self):
        self.old_cursor()
        sync, _ = self.sync({"subjects": [subjects(257)]})
        with patch("wanikani.sync.time.sleep", side_effect=lambda _: sync.cancelled.set()):
            self.assertFalse(sync.run(for_study=True))
        self.assertEqual(128, self.count())
        self.assertEqual(stamp(NOW - 600), self.store.get("cursor_subjects"))
        self.assertEqual("cancelled", self.engine.status)

    def test_cancel_on_final_chunk_does_not_acknowledge_collection(self):
        self.old_cursor()
        sync, _ = self.sync({"subjects": [subjects(3)]})
        with patch("wanikani.sync.time.sleep", side_effect=lambda _: sync.cancelled.set()):
            self.assertFalse(sync.run(for_study=True))
        self.assertEqual(3, self.count())
        self.assertEqual(stamp(NOW - 600), self.store.get("cursor_subjects"))

    def test_later_page_failure_retains_old_cursor_and_completed_page(self):
        self.old_cursor()
        sync, api = self.sync({"subjects": [subjects(150), subjects(200)]})
        def fail(endpoint, index):
            raise OSError("Authored page-request interruption")
        api.after_page = fail
        self.assertFalse(sync.run(for_study=True))
        self.assertEqual(150, self.count())
        self.assertEqual(stamp(NOW - 600), self.store.get("cursor_subjects"))

    def test_invalid_resource_rolls_back_only_its_chunk(self):
        self.old_cursor()
        page = subjects(200)
        page[160]["data"] = None
        sync, _ = self.sync({"subjects": [page]})
        self.assertFalse(sync.run(for_study=True))
        self.assertEqual(128, self.count())
        self.assertEqual(128, self.store.rows("SELECT COUNT(*) FROM search_documents WHERE CAST(id AS INTEGER)>=10000")[0][0])
        self.assertEqual(stamp(NOW - 600), self.store.get("cursor_subjects"))

    def test_followup_assignments_yield_without_advancing_cursor_early(self):
        self.store.set("cursor_assignments", stamp(NOW - 600))
        sync, _ = self.sync({"assignments": [assignments()]})
        counts = []
        def yield_after_commit(seconds):
            self.assertFalse(self.store.db.in_transaction)
            self.assertEqual(stamp(NOW - 600), self.store.get("cursor_assignments"))
            counts.append(self.count())
        with patch("wanikani.sync.time.sleep", side_effect=yield_after_commit):
            sync.refresh_after_writes()
        self.assertEqual([128, 129], counts)
        self.assertEqual(stamp(NOW - 2), self.store.get("cursor_assignments"))

    def test_followup_page_limit_preserves_old_cursor(self):
        self.store.set("cursor_assignments", stamp(NOW - 600))
        pages = [assignments(2, 20000 + page * 2) for page in range(5)]
        sync, _ = self.sync({"assignments": pages})
        sync.refresh_after_writes()
        self.assertEqual(8, self.count())
        self.assertEqual(stamp(NOW - 600), self.store.get("cursor_assignments"))

    def test_followup_cancellation_keeps_committed_assignments_and_old_cursor(self):
        self.store.set("cursor_assignments", stamp(NOW - 600))
        sync, _ = self.sync({"assignments": [assignments()]})
        with patch("wanikani.sync.time.sleep", side_effect=lambda _: sync.cancelled.set()):
            with self.assertRaises(UserError) as caught:
                sync.refresh_after_writes()
        self.assertEqual("cancelled", caught.exception.code)
        self.assertEqual(128, self.count())
        self.assertEqual(stamp(NOW - 600), self.store.get("cursor_assignments"))

    def test_answer_between_chunks_is_reconciled_against_later_remote_progress(self):
        for assignment in self.store.all("assignment"):
            if assignment["data"]["subject_id"] != 1:
                assignment["data"]["available_at"] = stamp(NOW + 14400)
                self.store.put(assignment)
        remote = copy.deepcopy(self.store.resource("assignment", 101))
        remote["data"]["srs_stage"] += 1
        remote["data"]["available_at"] = stamp(NOW + 14400)
        sync, api = self.sync({"assignments": [assignments(128) + [remote]]})
        api.assignments[101] = remote
        completed = []
        def yield_after_commit(seconds):
            if completed:
                return
            view = self.engine.start("reviews", 1)
            self.assertEqual(1, view["subject"]["id"])
            self.engine.answer(self.correct_answer(view))
            completed.append(self.engine.advance())
            self.assertEqual("pending", self.store.rows("SELECT state FROM outbox")[0][0])
        with patch("wanikani.sync.time.sleep", side_effect=yield_after_commit):
            self.assertTrue(sync.run(for_study=True))
        self.assertEqual(1, completed[0]["completed"])
        self.assertEqual("complete", self.engine.session_view()["phase"])
        self.assertEqual("conflicted", self.store.rows("SELECT state FROM outbox")[0][0])
        self.assertEqual(remote, self.store.resource("assignment", 101))
        self.assertEqual([], api.mutations)

    def test_process_exit_between_or_inside_chunks_preserves_answers_and_safe_retry(self):
        for boundary in ("between", "inside"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                child = subprocess.run([sys.executable, "-B", __file__, "--crash-child", str(path), boundary],
                    capture_output=True, timeout=10)
                self.assertEqual(73, child.returncode, child.stderr.decode())
                store = Store(path / "state.sqlite3")
                try:
                    engine = Engine(store, clock=lambda: NOW)
                    self.assertEqual(stamp(NOW - 600), store.get("cursor_subjects"))
                    self.assertEqual(128, store.rows("SELECT COUNT(*) FROM resources WHERE CAST(id AS INTEGER)>=10000")[0][0])
                    self.assertEqual(128, store.rows("SELECT COUNT(*) FROM search_documents WHERE CAST(id AS INTEGER)>=10000")[0][0])
                    session = engine.session_view()
                    self.assertEqual("feedback", session["phase"])
                    self.assertEqual(1, session["errors"])
                    self.assertEqual("incorrect authored fixture answer", session["feedback"]["answer"])
                    self.assertEqual(3, session["revision"])
                    original_epoch = session["session_epoch"]
                    page = subjects()
                    page[0]["data"]["meanings"][0]["meaning"] = "replacement trail after retry"
                    api = PageApi(store, {"subjects": [page]})
                    sync = Synchronizer(engine, api, path / "media")
                    self.assertTrue(sync.run(for_study=True))
                    self.assertEqual(stamp(NOW - 2), store.get("cursor_subjects"))
                    self.assertEqual(1000, store.rows("SELECT COUNT(*) FROM resources WHERE CAST(id AS INTEGER)>=10000")[0][0])
                    self.assertEqual("replacement trail after retry", store.subject(10000)["data"]["meanings"][0]["meaning"])
                    self.assertIn("replacement trail after retry", store.rows("SELECT meanings FROM search_documents WHERE id='10000'")[0][0])
                    self.assertEqual(original_epoch, engine.session_view()["session_epoch"])
                    self.assertEqual(3, engine.session_view()["revision"])
                    self.assertEqual([], api.mutations)
                    self.assertEqual([], store.rows("SELECT * FROM outbox"))
                    parameters = next(params for endpoint, params in api.calls if endpoint == "subjects")
                    self.assertEqual(stamp(NOW - 600), parameters["updated_after"])
                finally:
                    store.close()


if __name__ == "__main__":
    if "--crash-child" in sys.argv:
        crash_child(Path(sys.argv[2]), sys.argv[3])
    else:
        unittest.main()
