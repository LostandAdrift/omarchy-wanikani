"""Reset reconciliation skips historical session bodies at realistic scale."""
import copy
import json
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.common import stamp
from wanikani.sync import Synchronizer


class ResetHistoryTests(EngineFixture, unittest.TestCase):
    def test_fifty_thousand_completed_sessions_do_not_load_during_reset(self):
        graded = self.engine.start("reviews", 2)
        self.engine.draft("saved graded answer")
        other = copy.deepcopy(self.store.session())
        other["id"] = "another-paused-graded-session"
        self.store.save_session(other, activate=False)
        practice = self.engine.start("practice", 1, [3])
        self.engine.draft("saved practice answer")
        def historical_rows():
            for index in range(50000):
                session_id = "completed-" + str(index)
                body = {"id": session_id, "mode": "reviews", "phase": "complete", "queue": [],
                    "draft": "Independently authored historical fixture. " * 20, "completed": 0,
                    "ended_at": stamp(NOW - 86400), "invalidated": "Historical fixture"}
                yield session_id, json.dumps(body)
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO sessions VALUES(?,?)", historical_rows())
        predicate = "json_extract(body,'$.phase')!='complete' AND json_extract(body,'$.mode')!='practice'"
        plan = self.store.rows("EXPLAIN QUERY PLAN SELECT body FROM sessions WHERE " + predicate)
        self.assertTrue(any("sessions_unfinished_graded" in row[3] for row in plan), [tuple(row) for row in plan])
        original_rows = self.store.rows
        session_allocations = []
        def rows(sql, args=()):
            result = original_rows(sql, args)
            if "FROM sessions" in sql:
                session_allocations.append(len(result))
            return result
        sync = Synchronizer(self.engine, FakeApi(self.store), Path(self.temp.name) / "media")
        tracemalloc.start()
        try:
            with patch.object(self.store, "rows", side_effect=rows):
                sync._invalidate_reset({"id": 990001, "object": "reset", "data": {"target_level": 1}})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual([2], session_allocations)
        self.assertLess(peak, 2 * 1024 * 1024)
        for session_id in (graded["id"], other["id"]):
            saved = self.store.session(session_id)
            self.assertEqual("complete", saved["phase"])
            self.assertEqual("Account reset", saved["invalidated"])
            self.assertEqual("saved graded answer", saved["draft"])
        current = self.engine.session_view()
        self.assertEqual(practice["id"], current["id"])
        self.assertEqual("question", current["phase"])
        self.assertEqual("saved practice answer", current["draft"])
        self.assertEqual(50003, self.store.rows("SELECT COUNT(*) FROM sessions")[0][0])


if __name__ == "__main__":
    unittest.main()
