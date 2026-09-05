"""Large local histories and interrupted page boundaries never use live APIs."""
import copy
import json
import tracemalloc
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.api import ApiError
from wanikani.common import UserError, stamp
from wanikani.engine import Engine, baseline
from wanikani.store import Store
from wanikani.sync import Synchronizer


class SyncScalingTests(EngineFixture, unittest.TestCase):
    def operation(self, index, state="pending", created_at=None):
        subject = copy.deepcopy(self.store.subject(2))
        subject["id"] = 1000 + index
        assignment = copy.deepcopy(self.store.resource("assignment", 102))
        assignment.update(id=10000 + index)
        assignment["data"]["subject_id"] = subject["id"]
        self.store.put(subject)
        self.store.put(assignment)
        body = {"account_id": "demo", "assignment_id": assignment["id"], "baseline": baseline(assignment),
            "completed_at": stamp(NOW), "errors": {"meaning": index % 3, "reading": index % 2}}
        self.store.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)", (
            f"op-{index:06d}", "review", subject["id"], state, json.dumps(body), created_at or stamp(NOW + index), "Saved locally"))
        return assignment

    def operations(self, count, state="pending"):
        with self.store.transaction():
            for index in reversed(range(count)):
                self.operation(index, state, stamp(NOW))

    def synchronizer(self):
        api = FakeApi(self.store)
        return Synchronizer(self.engine, api, self.path.parent / "media"), api

    def states(self):
        return {row["state"]: row["count"] for row in self.store.rows("SELECT state,COUNT(*) AS count FROM outbox GROUP BY state")}

    def test_fifty_thousand_queued_bodies_are_not_loaded_before_first_request(self):
        assignment = self.store.resource("assignment", 102)
        body = json.dumps({"account_id": "demo", "assignment_id": 102, "baseline": baseline(assignment),
            "completed_at": stamp(NOW), "errors": {"meaning": 1, "reading": 0},
            "local_note": "Independent authored fixture. " * 40})
        with self.store.transaction():
            self.store.db.executemany("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)", (
                (f"op-{index:06d}", "review", 2, "pending", body, stamp(NOW), "Saved locally") for index in range(50000)))
        original_rows = self.store.rows
        for state in ("pending", "uncertain"):
            with self.subTest(state=state):
                self.store.execute("UPDATE outbox SET state=?", (state,))
                sync, api = self.synchronizer()
                full_body_batches = []
                def observe(sql, args=()):
                    result = original_rows(sql, args)
                    if "FROM outbox" in sql and result and "body" in result[0].keys():
                        full_body_batches.append(len(result))
                    return result
                with patch.object(self.store, "rows", side_effect=observe), \
                        patch.object(api, "request", side_effect=ApiError(429, "Fixture quota exhausted")) as request:
                    tracemalloc.start()
                    try:
                        with self.assertRaises(ApiError):
                            sync.flush() if state == "pending" else sync.reconcile_uncertain()
                        _, peak = tracemalloc.get_traced_memory()
                    finally:
                        tracemalloc.stop()
                self.assertEqual([1], full_body_batches)
                self.assertLess(peak, 1024 * 1024, "A stopped pass must not allocate the accumulated queue")
                request.assert_called_once()
                self.assertEqual({state: 50000}, self.states())
                self.assertEqual([], api.mutations)

    def test_multiple_pages_preserve_creation_and_id_order_as_states_change(self):
        self.operations(63)
        sync, api = self.synchronizer()
        self.assertEqual(63, sync.flush())
        self.assertEqual(list(range(10000, 10063)), [entry[2]["review"]["assignment_id"] for entry in api.mutations])
        self.assertEqual({"confirmed": 63}, self.states())
        self.assertEqual(63, sync.progress["completed"])
        self.assertEqual(63, sync.progress["total"])

    def test_new_answers_wait_until_next_pass_even_with_an_earlier_timestamp(self):
        self.operations(51)
        sync, api = self.synchronizer()
        original = api.request
        appended = False
        def request(path, method="GET", data=None, etag=None):
            nonlocal appended
            if not appended:
                appended = True
                assignment = self.operation(999, created_at=stamp(NOW - 100))
                api.assignments[assignment["id"]] = assignment
            return original(path, method, data, etag)
        with patch.object(api, "request", side_effect=request):
            self.assertEqual(51, sync.flush())
        self.assertEqual({"confirmed": 51, "pending": 1}, self.states())
        self.assertEqual(1, sync.flush())
        self.assertEqual(10999, api.mutations[-1][2]["review"]["assignment_id"])

    def test_quota_at_second_page_stops_without_skipping_or_resending_on_refresh(self):
        self.operations(63)
        sync, api = self.synchronizer()
        original = api.request
        def limited(path, method="GET", data=None, etag=None):
            if method == "GET" and path == "assignments/10025":
                raise ApiError(429, "Fixture quota exhausted")
            return original(path, method, data, etag)
        with patch.object(api, "request", side_effect=limited), self.assertRaises(ApiError):
            sync.flush()
        self.assertEqual({"confirmed": 25, "pending": 38}, self.states())
        self.assertEqual(25, len(api.mutations))
        self.assertEqual(38, sync.flush())
        self.assertEqual(list(range(10000, 10063)), [entry[2]["review"]["assignment_id"] for entry in api.mutations])

    def test_lost_response_in_second_page_remains_uncertain_and_is_not_replayed(self):
        self.operations(63)
        sync, api = self.synchronizer()
        original = api.request
        def lose_response(path, method="GET", data=None, etag=None):
            if method == "POST" and len(api.mutations) == 25:
                api.error = ApiError(0, "Fixture response lost", uncertain=True)
            return original(path, method, data, etag)
        with patch.object(api, "request", side_effect=lose_response), self.assertRaises(ApiError):
            sync.flush()
        self.assertEqual({"confirmed": 25, "uncertain": 1, "pending": 37}, self.states())
        api.error = None
        sync.reconcile_uncertain()
        self.assertEqual(37, sync.flush())
        self.assertEqual({"confirmed": 62, "uncertain": 1}, self.states())
        assignments = [entry[2]["review"]["assignment_id"] for entry in api.mutations]
        self.assertEqual(list(range(10000, 10063)), assignments)

    def test_interruption_after_remote_acceptance_recovers_without_duplicate_second_page_write(self):
        self.operations(63)
        sync, api = self.synchronizer()
        original = sync.apply_result
        def interrupt(row, response):
            if row["id"] == "op-000025":
                raise KeyboardInterrupt("Fixture process interruption before durable confirmation")
            return original(row, response)
        with patch.object(sync, "apply_result", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            sync.flush()
        self.assertEqual({"confirmed": 25, "inflight": 1, "pending": 37}, self.states())
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.assertEqual({"confirmed": 25, "uncertain": 1, "pending": 37}, self.states())
        restarted = Synchronizer(self.engine, api, self.path.parent / "media")
        restarted.reconcile_uncertain()
        self.assertEqual(37, restarted.flush())
        self.assertEqual({"confirmed": 62, "conflicted": 1}, self.states())
        self.assertEqual(list(range(10000, 10063)), [entry[2]["review"]["assignment_id"] for entry in api.mutations])

    def test_uncertain_rows_with_unchanged_remote_state_are_checked_once_per_pass(self):
        self.operations(63, "uncertain")
        sync, api = self.synchronizer()
        with patch.object(api, "request", wraps=api.request) as request:
            sync.reconcile_uncertain()
        self.assertEqual(["assignments/" + str(index) for index in range(10000, 10063)],
            [call.args[0] for call in request.call_args_list])
        self.assertEqual({"uncertain": 63}, self.states())
        self.assertEqual([], api.mutations)
        self.assertEqual(0, sync.flush())

    def test_cancellation_between_pages_retains_all_unprocessed_work(self):
        self.operations(63)
        sync, api = self.synchronizer()
        original = sync.apply_result
        def cancel_after_first_page(row, response):
            result = original(row, response)
            if row["id"] == "op-000024":
                sync.cancelled.set()
            return result
        with patch.object(sync, "apply_result", side_effect=cancel_after_first_page), self.assertRaises(UserError):
            sync.flush()
        self.assertEqual({"confirmed": 25, "pending": 38}, self.states())
        sync.cancelled.clear()
        self.assertEqual(38, sync.flush())
        self.assertEqual(63, len(api.mutations))


if __name__ == "__main__":
    unittest.main()
