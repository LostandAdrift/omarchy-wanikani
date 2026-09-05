"""Read-only recovery pages use authored local data and never an account API."""
import json
import unittest
from unittest.mock import Mock, patch

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.common import UserError, stamp
from wanikani.recovery import STATES, catalogue, snapshot_summary
from wanikani.sync import Synchronizer
from worker import Worker


class RecoveryTests(EngineFixture, unittest.TestCase):
    def record(self, index, state="pending", kind="review", subject_id=2, created_at=None, detail="Saved locally", body=None):
        body = body if body is not None else {"errors": {"meaning": 2, "reading": 1},
            "account_id": "PRIVATE-ACCOUNT-MARKER", "baseline": {"private": "PRIVATE-BASELINE-MARKER"},
            "material": {"meaning_note": "PRIVATE-NOTE-MARKER", "meaning_synonyms": ["PRIVATE-SYNONYM-MARKER"]}}
        self.store.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)", (
            f"op-{index:06d}", kind, subject_id, state, json.dumps(body), created_at or stamp(NOW + index), detail))

    def test_empty_page_has_all_counts_and_no_next_page(self):
        page = catalogue(self.engine)
        self.assertEqual([], page["items"])
        self.assertEqual(dict.fromkeys(STATES, 0), page["counts"])
        self.assertEqual(0, page["open_total"])
        self.assertFalse(page["has_more"])
        self.assertIsNone(page["next_offset"])

    def test_snapshot_aggregates_beyond_capped_preview(self):
        with self.store.transaction():
            for index in range(140):
                self.record(index, STATES[index % len(STATES)])
        summary = self.engine.snapshot()
        self.assertEqual(dict.fromkeys(STATES, 20), summary["outbox_counts"])
        self.assertEqual(100, summary["outbox_total"])
        self.assertEqual(60, summary["pending"])
        self.assertEqual(60, summary["attention"])
        self.assertEqual(12, len(summary["outbox"]))
        self.assertTrue(summary["outbox_has_more"])
        self.assertEqual({"id", "kind", "subject_id", "state", "created_at", "detail"}, set(summary["outbox"][0]))

    def test_paging_is_stable_for_identical_timestamps(self):
        with self.store.transaction():
            for index in reversed(range(71)):
                self.record(index, created_at=stamp(NOW))
        pages = [catalogue(self.engine, offset=offset) for offset in (0, 30, 60)]
        self.assertEqual([30, 30, 11], [len(page["items"]) for page in pages])
        identifiers = [item["id"] for page in pages for item in page["items"]]
        self.assertEqual([f"op-{index:06d}" for index in range(71)], identifiers)
        self.assertEqual([30, 60, None], [page["next_offset"] for page in pages])
        self.assertEqual([True, True, False], [page["has_more"] for page in pages])

    def test_kind_and_state_filters_keep_global_counts(self):
        for index, state in enumerate(STATES):
            self.record(index, state, "lesson")
            self.record(index + 10, state, "review")
            self.record(index + 20, state, "material")
        page = catalogue(self.engine, state="attention", kind="lesson", limit=2)
        self.assertEqual(3, page["total"])
        self.assertEqual(["uncertain", "conflicted"], [item["state"] for item in page["items"]])
        self.assertEqual(dict.fromkeys(STATES, 3), page["counts"])
        self.assertEqual(15, page["open_total"])
        self.assertEqual(9, page["attention"])
        self.assertEqual(1, catalogue(self.engine, state="confirmed", kind="material")["total"])
        self.assertEqual(21, catalogue(self.engine, state="all")["total"])
        self.assertEqual([], catalogue(self.engine, offset=1000)["items"])

    def test_only_error_counts_leave_private_payloads(self):
        self.record(0)
        self.record(1, kind="lesson")
        self.record(2, kind="material")
        page = catalogue(self.engine)
        self.assertEqual({"meaning": 2, "reading": 1, "total": 3}, page["items"][0]["errors"])
        self.assertEqual(page["items"][0]["errors"], page["items"][1]["errors"])
        self.assertIsNone(page["items"][2]["errors"])
        self.assertNotIn("PRIVATE-", json.dumps(page))
        self.assertNotIn("body", page["items"][0])

    def test_invalid_error_counters_are_not_presented_as_grading_history(self):
        for index, errors in enumerate(({}, {"meaning": -1, "reading": 0}, {"meaning": "2", "reading": 1})):
            self.record(index, body={"errors": errors})
        self.assertTrue(all(item["errors"] is None for item in catalogue(self.engine)["items"]))

    def test_subject_labels_are_accessible_and_plain_text(self):
        self.record(0)
        subject = self.store.subject(2)
        subject["data"]["characters"] = "<b>山</b>"
        subject["data"]["meanings"][0]["meaning"] = "<i>mountain</i>"
        self.store.put(subject)
        item = catalogue(self.engine)["items"][0]["subject"]
        self.assertEqual("山", item["label"])
        self.assertEqual("mountain", item["meaning"])
        self.assertTrue(item["accessible"])
        self.assertFalse(item["spoilers_hidden"])

    def test_malformed_meanings_and_characters_never_crash_or_leak_raw_values(self):
        self.record(0)
        subject = self.store.subject(2)
        subject["data"]["characters"] = {"PRIVATE-MARKER": "not characters"}
        for meanings in (None, 123, "not a list", [{"meaning": "not accepted", "accepted_answer": 1}],
                [None, "text", {"meaning": {"PRIVATE-MARKER": "not meaning"}, "accepted_answer": True}]):
            with self.subTest(meanings=meanings):
                subject["data"]["meanings"] = meanings
                self.store.put(subject)
                result = catalogue(self.engine)["items"][0]["subject"]
                self.assertEqual("", result["meaning"])
                self.assertEqual("", result["characters"])
                self.assertNotIn("PRIVATE-MARKER", json.dumps(result))

    def test_restricted_hidden_and_missing_subjects_hide_all_content(self):
        restricted = self.store.subject(2)
        restricted["data"]["level"] = 4
        self.store.put(restricted)
        hidden = self.store.subject(3)
        hidden["data"]["hidden_at"] = stamp(NOW)
        self.store.put(hidden)
        user = self.store.get("user")
        user["data"]["subscription"].update(active=False, type="free", max_level_granted=3)
        self.store.set("user", user)
        for index, subject_id in enumerate((2, 3, 99999)):
            self.record(index, subject_id=subject_id, detail="PRIVATE-SUBJECT-MEANING")
        page = catalogue(self.engine)
        for item in page["items"]:
            self.assertFalse(item["subject"]["accessible"])
            for key in ("characters", "meaning", "type"):
                self.assertEqual("", item["subject"][key])
            self.assertIsNone(item["subject"]["level"])
            self.assertEqual("Subject " + str(item["subject_id"]), item["subject"]["label"])
        self.assertNotIn("PRIVATE-SUBJECT", json.dumps(page))
        self.assertNotIn("PRIVATE-SUBJECT", json.dumps(snapshot_summary(self.engine)))

    def test_incomplete_graded_session_hides_meanings_while_practice_is_active(self):
        graded = self.engine.start("reviews", 1)
        subject_id = graded["subject"]["id"]
        self.record(0, subject_id=subject_id, state="uncertain")
        self.engine.start("practice", 1, [16])
        item = catalogue(self.engine)["items"][0]["subject"]
        self.assertTrue(item["accessible"])
        self.assertTrue(item["spoilers_hidden"])
        self.assertEqual("", item["meaning"])
        self.assertTrue(item["characters"])

    def test_historical_sessions_are_not_loaded_when_reading_recovery(self):
        self.record(0)
        with self.store.transaction():
            for index in range(1000):
                self.store.execute("INSERT INTO sessions VALUES (?,?)", (str(index), "{}"))
        statements = []
        self.store.db.set_trace_callback(statements.append)
        try:
            catalogue(self.engine)
        finally:
            self.store.db.set_trace_callback(None)
        self.assertFalse(any("FROM sessions" in sql for sql in statements))

    def test_recovery_actions_never_offer_replay(self):
        for index, state in enumerate(STATES):
            self.record(index, state)
        pages = catalogue(self.engine, state="all")["items"]
        for item in pages:
            expected = ["refresh", "keep_remote"] if item["state"] in ("uncertain", "conflicted", "blocked") else ["refresh"] if item["state"] == "pending" else []
            self.assertEqual(expected, [action["id"] for action in item["actions"]])
        uncertain = next(item for item in pages if item["state"] == "uncertain")
        self.assertIn("automatic replay is disabled", uncertain["rationale"])
        self.assertIn("Refresh first", uncertain["actions"][-1]["description"])

    def test_demo_confirmation_never_claims_a_real_account_submission(self):
        self.engine.demo = True
        self.record(0, "confirmed")
        self.record(1, "pending")
        page = catalogue(self.engine, state="all")
        self.assertIn("Confirmed locally in demonstration mode", page["items"][0]["rationale"])
        self.assertIn("Nothing was sent to WaniKani", page["items"][0]["rationale"])
        self.assertEqual("Refresh demonstration results", page["items"][1]["actions"][0]["label"])

    def test_read_only_pages_do_not_change_outbox_or_emit_state(self):
        self.record(0, "uncertain")
        before = [tuple(row) for row in self.store.rows("SELECT * FROM outbox")]
        worker = Worker.__new__(Worker)
        worker.engine = self.engine
        worker.emit = Mock()
        worker.changed = Mock()
        with patch.object(self.store, "execute", side_effect=AssertionError("Recovery cannot write")):
            worker.handle({"v": 1, "id": "recovery-read", "method": "recovery", "args": {"state": "attention"}})
        self.assertEqual(before, [tuple(row) for row in self.store.rows("SELECT * FROM outbox")])
        worker.changed.assert_not_called()
        reply = worker.emit.call_args.args[0]
        self.assertEqual("recovery-read", reply["id"])
        self.assertEqual(1, reply["data"]["total"])
        self.assertEqual(0, self.store.rows("SELECT COUNT(*) FROM commands")[0][0])

    def test_existing_keep_remote_archives_and_preserves_record_without_mutation(self):
        self.record(0, "uncertain")
        sync = Synchronizer(self.engine, FakeApi(self.store), self.path.parent / "media")
        self.assertEqual(1, catalogue(self.engine)["total"])
        sync.resolve("op-000000", "keep_remote")
        self.assertEqual(0, catalogue(self.engine)["total"])
        archived = catalogue(self.engine, state="discarded")
        self.assertEqual(1, archived["total"])
        self.assertEqual([], archived["items"][0]["actions"])
        self.assertEqual([], sync.api.mutations)

    def test_invalid_filters_and_page_bounds_are_rejected(self):
        cases = ({"state": "retry"}, {"state": []}, {"kind": "unknown"}, {"kind": {}},
            {"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": "30"},
            {"offset": -1}, {"offset": 1000001}, {"offset": False}, {"offset": 1.5})
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(UserError):
                catalogue(self.engine, **arguments)


if __name__ == "__main__":
    unittest.main()
