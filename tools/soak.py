#!/usr/bin/env python3
"""Developer-only deterministic interaction soak. Never use an account token.

Example: python3 tools/soak.py --seeds 10 --steps 500
All subjects are independently authored demo fixtures. A private temporary SQLite
database, virtual clock, and stateful in-memory remote exercise production study
and synchronization code. The mock's four-hour schedule is deliberately simple;
this is interaction/recovery testing, not a WaniKani scheduling emulator. Network
and subprocess calls are blocked. Failed seeds retain their full authored trace
under test-results/soak (override with --failure-dir).
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import traceback
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from wanikani.api import ApiError
from wanikani.common import UserError, epoch, stamp
from wanikani.demo import populate
from wanikani.engine import Engine
from wanikani.store import Store
from wanikani.sync import Synchronizer

START = 1788550000
OPEN_STATES = ("pending", "inflight", "uncertain", "blocked", "conflicted")


class ProcessInterruption(BaseException):
    """Simulated loss of the process after acceptance, before local commit."""


class MockRemote:
    def __init__(self, harness):
        self.harness = harness
        store = harness.store
        self.user = copy.deepcopy(store.get("user"))
        self.subjects = {subject["id"]: subject for kind in ("radical", "kanji", "vocabulary", "kana_vocabulary") for subject in store.all(kind)}
        self.assignments = {item["id"]: item for item in store.all("assignment")}
        self.resets = []
        self.online = self.authenticated = self.write_allowed = True
        self.next_fault = None
        self.server_offset = 0
        self.version = 0
        self.generation = 0
        self.cycles = Counter()
        self.accepted_cycles = set()
        self.accepted_operations = set()
        self.accepted_payloads = set()
        self.violation = None

    def check(self, condition, message):
        if not condition:
            self.violation = message
            raise AssertionError(message)

    def guard(self):
        if not self.online:
            raise ApiError(0, "Authored mock is offline")
        if not self.authenticated:
            raise ApiError(401, "Authored token is revoked")

    def due(self):
        return [item for item in self.assignments.values() if item["data"].get("started_at")
            and not item["data"].get("burned_at") and (epoch(item["data"].get("available_at")) or float("inf")) <= self.harness.now]

    def accept(self, assignment, kind, payload, operation=None):
        aid = assignment["id"]
        cycle = (self.generation, aid, self.cycles[aid], kind)
        self.check(cycle not in self.accepted_cycles, "The remote accepted the same assignment cycle twice")
        if operation:
            self.check(operation not in self.accepted_operations, "A local operation was accepted twice")
            self.check(operation not in self.harness.ever_uncertain, "An uncertain local operation was automatically replayed")
            fingerprint = (self.generation, aid, kind, json.dumps(payload, sort_keys=True))
            self.check(fingerprint not in self.accepted_payloads, "The same graded payload was accepted twice")
            self.accepted_payloads.add(fingerprint)
            self.accepted_operations.add(operation)
        self.accepted_cycles.add(cycle)
        self.cycles[aid] += 1
        data = assignment["data"]
        data["srs_stage"] = 1 if kind == "lesson" else min(8, data["srs_stage"] + 1)
        if kind == "lesson":
            data["started_at"] = payload["assignment"]["started_at"]
        data["available_at"] = stamp(self.harness.now + 14400)
        assignment["data_updated_at"] = stamp(self.harness.now)
        self.version += 1
        self.harness.counts["accepted_" + (kind if operation else "other_client")] += 1

    def request(self, path, method="GET", data=None, etag=None):
        self.guard()
        if method == "GET":
            if path == "user":
                return copy.deepcopy(self.user), None
            if path == "summary":
                tag = "fixture-" + str(self.version)
                return (None if etag == tag else {"object": "report", "data": {}}), tag
            if path.startswith("assignments/"):
                assignment = self.assignments.get(int(path.split("/")[1]))
                if not assignment:
                    raise ApiError(404, "Authored assignment was removed")
                return copy.deepcopy(assignment), None
            self.check(False, "Unexpected mock GET: " + path)
        self.check(path == "reviews" or path.endswith("/start"), "Unexpected mock mutation: " + path)
        if not self.write_allowed:
            raise ApiError(403, "Authored token lacks write permission")
        kind = "review" if path == "reviews" else "lesson"
        aid = data["review"]["assignment_id"] if kind == "review" else int(path.split("/")[1])
        assignment = self.assignments.get(aid)
        if not assignment:
            raise ApiError(404, "Authored assignment was removed")
        operation = self.harness.inflight_operation()
        self.check(operation not in self.harness.ever_uncertain, "An uncertain operation reached another mutation attempt")
        fault, self.next_fault = self.next_fault, None
        if fault:
            self.harness.counts["fault_" + fault] += 1
        if fault == "quota":
            raise ApiError(429, "Authored quota exhausted")
        if fault == "lost_before":
            raise ApiError(0, "Authored response lost before acceptance", uncertain=True)
        if self.user["data"].get("current_vacation_started_at"):
            raise ApiError(422, "Authored account is on vacation")
        if (kind == "review" and assignment not in self.due()) or (kind == "lesson" and assignment["data"].get("started_at")):
            raise ApiError(422, "Authored assignment is not ready for this operation")
        self.accept(assignment, kind, data, operation)
        if fault == "lost_after":
            raise ApiError(0, "Authored response lost after acceptance", uncertain=True)
        if fault == "process_after":
            raise ProcessInterruption()
        response = {"object": "review", "id": 0, "resources_updated": {"assignment": assignment}} if kind == "review" else assignment
        return copy.deepcopy(response), None

    def collection(self, endpoint, params=None):
        self.guard()
        params = params or {}
        values = {"subjects": list(self.subjects.values()), "assignments": list(self.assignments.values()),
            "resets": self.resets, "study_materials": [], "review_statistics": [],
            "level_progressions": [], "spaced_repetition_systems": []}
        self.check(endpoint in values, "Unexpected mock collection: " + endpoint)
        items = values[endpoint]
        if endpoint == "subjects" and "levels" in params:
            levels = {int(level) for level in params["levels"].split(",")}
            items = [item for item in items if item["data"]["level"] in levels]
        if params.get("updated_after"):
            after = epoch(params["updated_after"])
            items = [item for item in items if (epoch(item.get("data_updated_at")) or START) >= after]
        for index in range(0, len(items), 7):
            yield copy.deepcopy(items[index:index + 7])

    def reset(self, target):
        self.generation += 1
        self.version += 1
        self.resets.append({"id": self.generation, "object": "reset", "data_updated_at": stamp(self.harness.now),
            "data": {"target_level": target, "confirmed_at": stamp(self.harness.now)}})
        for aid, assignment in list(self.assignments.items()):
            if self.subjects[assignment["data"]["subject_id"]]["data"]["level"] < target:
                continue
            del self.assignments[aid]
            assignment["id"] = aid + 10000
            assignment["data"].update(started_at=None, available_at=None, srs_stage=0,
                passed_at=None, burned_at=None, unlocked_at=stamp(self.harness.now))
            assignment["data_updated_at"] = stamp(self.harness.now)
            self.assignments[assignment["id"]] = assignment


class Harness:
    def __init__(self, seed, directory):
        self.seed, self.rng = seed, random.Random(seed)
        self.now = START
        self.path = Path(directory) / "authored.sqlite3"
        self.store = Store(self.path)
        populate(self.store, self.now)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.remote = MockRemote(self)
        self.sync = Synchronizer(self.engine, self.remote, Path(directory) / "media")
        self.trace = []
        self.counts = Counter()
        self.ever_uncertain = set()
        self.deadlines = {}
        self.commands = []
        self.sequence = 0
        self.acknowledged_parts = set()

    def inflight_operation(self):
        rows = self.store.rows("SELECT id FROM outbox WHERE state='inflight'")
        self.remote.check(len(rows) == 1, "Mutation lacks exactly one durable in-flight record")
        return rows[0]["id"]

    def session_bodies(self):
        return {row["id"]: row["body"] for row in self.store.rows("SELECT * FROM sessions")}

    def restart(self):
        before = self.session_bodies()
        pointers = [self.store.get(key) for key in ("active_session", "graded_session", "practice_session")]
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: self.now)
        self.sync = Synchronizer(self.engine, self.remote, self.path.parent / "media")
        assert before == self.session_bodies(), "Restart changed a saved question, draft, answer part, or error count"
        assert pointers == [self.store.get(key) for key in ("active_session", "graded_session", "practice_session")], "Restart changed the session references"
        self.counts["restarts"] += 1

    def command(self, method, args=None):
        self.sequence += 1
        request = ("soak-command-" + str(self.sequence), method, args or {})
        before = self.session_bodies()
        active = self.store.session()
        prior_outbox = {row["id"] for row in self.store.rows("SELECT id FROM outbox")}
        busy_subjects = {row["subject_id"] for row in self.store.rows("SELECT subject_id FROM outbox WHERE state IN ('pending','inflight','uncertain','blocked','conflicted')")}
        event_count = self.store.rows("SELECT COUNT(*) FROM events")[0][0]
        self.trace[-1].update(command=method, args=args or {})
        try:
            result = self.engine.command(*request)
        except UserError as error:
            assert before == self.session_bodies(), "Rejected command changed durable session state"
            assert event_count == self.store.rows("SELECT COUNT(*) FROM events")[0][0], "Rejected command recorded an answer"
            self.counts["rejected_" + error.code] += 1
            self.trace[-1]["rejected"] = error.code
            return None
        if method != "advance":
            assert prior_outbox == {row["id"] for row in self.store.rows("SELECT id FROM outbox")}, "A subject was submitted before final feedback acknowledgement"
        elif active and active["phase"] == "feedback" and active["feedback"]["correct"]:
            entry = active["queue"][active["index"]]
            self.acknowledged_parts.add((active["id"], entry["subject_id"], active["part"]))
        if method == "start" and result["id"] not in before and result["mode"] != "practice":
            assert not busy_subjects.intersection(item["subject_id"] for item in self.store.session()["queue"]), "New graded session included an unresolved subject"
        self.commands.append((*request, result))
        self.counts[method] += 1
        return result

    def study(self):
        session = self.store.session()
        if not session or session["phase"] == "complete":
            mode = self.rng.choices(("reviews", "lessons", "practice"), (5, 3, 2))[0]
            args = {"mode": mode, "limit": self.rng.randint(1, 5)}
            if mode == "practice":
                args["subjects"] = self.rng.sample(range(1, 17), args["limit"])
            self.command("start", args)
            return
        phase = session["phase"]
        if phase == "lesson":
            self.command("lesson_next", {"back": self.rng.random() < 0.1})
        elif phase == "feedback":
            if not session["feedback"]["correct"] and self.rng.random() < 0.4:
                self.command("correct")
            else:
                self.command("advance")
        else:
            choice = self.rng.random()
            if choice < 0.15:
                self.command("draft", {"text": self.rng.choice(("mo", "か", "partly typed", ""))})
                return
            if choice < 0.2:
                self.command("correct")  # A late correction must be rejected.
                return
            entry = session["queue"][session["index"]]
            subject = self.store.subject(entry["subject_id"])
            part = session["part"]
            if choice < 0.3:
                answer, kind = "", "retry"
            elif choice < 0.47:
                answer, kind = ("zzzzzzzz" if part == "meaning" else "ぬぬぬぬ"), "wrong"
            else:
                answer = next(item[part] for item in subject["data"]["meanings" if part == "meaning" else "readings"] if item["accepted_answer"])
                kind = "correct"
            result = self.command("answer", {"text": answer})
            if result:
                self.counts["answer_" + kind] += 1
                if kind == "retry":
                    saved = self.store.session()
                    assert saved["phase"] == "question" and saved["queue"] == session["queue"], "Retryable input changed completed parts or errors"
                else:
                    saved = self.store.session()
                    expected = entry["errors"][part] + (1 if kind == "wrong" else 0)
                    assert saved["queue"][saved["index"]]["errors"][part] == expected, "Grading changed the wrong error count"
                    assert result["feedback"]["correct"] == (kind == "correct"), "Authored answer was unexpectedly graded"

    def synchronize(self):
        self.remote.next_fault = self.rng.choices((None, "quota", "lost_before", "lost_after", "process_after"), (70, 8, 8, 8, 6))[0]
        self.trace[-1]["fault"] = self.remote.next_fault
        try:
            self.sync.run(for_study=True)
        except ProcessInterruption:
            self.restart()
            self.counts["process_interruptions"] += 1
        assert self.engine.status != "sync_error", "Synchronization stopped on an unexpected response"
        self.counts["sync"] += 1

    def heal(self, step):
        for key, deadline in list(self.deadlines.items()):
            if step < deadline:
                continue
            del self.deadlines[key]
            if key in ("online", "authenticated", "write_allowed"):
                setattr(self.remote, key, True)
            elif key == "vacation":
                self.remote.user["data"]["current_vacation_started_at"] = None
            elif key == "subscription":
                self.remote.user["data"]["subscription"]["max_level_granted"] = 60
            self.remote.version += 1

    def step(self, index):
        self.heal(index)
        action = self.rng.choices(("study", "sync", "restart", "resume", "practice", "replay", "time", "offline", "other", "vacation", "permission", "subscription", "reset", "recover"),
            (58, 12, 4, 3, 3, 3, 4, 2, 3, 1, 1, 1, 1, 4))[0]
        self.trace.append({"step": index, "time": stamp(self.now), "action": action})
        self.counts["action_" + action] += 1
        if action == "study":
            self.study()
        elif action == "sync":
            self.synchronize()
        elif action == "restart":
            self.restart()
        elif action == "resume":
            graded = self.store.session(self.store.get("graded_session")) if self.store.get("graded_session") else None
            expected = graded if graded and graded["phase"] != "complete" else self.store.session()
            saved = copy.deepcopy(expected)
            result = self.command("start", {"mode": "resume"})
            if result and saved and saved["phase"] != "complete":
                # Resuming legitimately advances the UI's durable revision.
                # The learning state itself must remain exactly unchanged.
                current = self.store.session()
                assert {key: value for key, value in current.items() if key != "revision"} == {
                    key: value for key, value in saved.items() if key != "revision"
                }, "Close/resume changed the exact question, partial answers, or draft"
                self.counts["durable_resumes"] += 1
        elif action == "practice":
            self.command("start", {"mode": "practice", "limit": 2, "subjects": self.rng.sample(range(1, 17), 2)})
        elif action == "replay" and self.commands:
            rid, method, args, expected = self.rng.choice(self.commands[-5:])
            before = self.session_bodies()
            events = self.store.rows("SELECT COUNT(*) FROM events")[0][0]
            assert self.engine.command(rid, method, args) == expected, "Replayed request changed its durable reply"
            assert before == self.session_bodies() and events == self.store.rows("SELECT COUNT(*) FROM events")[0][0], "Duplicate request repeated its effect"
            self.counts["duplicate_commands"] += 1
        elif action == "time":
            self.now += self.rng.choice((300, 14400, 86400))
        elif action in ("offline", "permission", "vacation", "subscription"):
            key = {"offline": "online", "permission": self.rng.choice(("authenticated", "write_allowed")), "vacation": "vacation", "subscription": "subscription"}[action]
            self.deadlines[key] = index + self.rng.randint(3, 15)
            if key in ("online", "authenticated", "write_allowed"):
                setattr(self.remote, key, False)
            elif key == "vacation":
                self.remote.user["data"]["current_vacation_started_at"] = stamp(self.now)
            else:
                self.remote.user["data"]["subscription"]["max_level_granted"] = 1
            self.trace[-1]["scenario"] = key
        elif action == "other" and not self.remote.user["data"].get("current_vacation_started_at"):
            accessible = [assignment for assignment in self.remote.due() if
                self.remote.subjects[assignment["data"]["subject_id"]]["data"]["level"] <= self.remote.user["data"]["subscription"]["max_level_granted"]]
            if accessible:
                self.remote.accept(self.rng.choice(accessible), "review", {}, None)
        elif action == "reset":
            target = self.rng.choice((1, 2))
            self.remote.reset(target)
            self.trace[-1]["target_level"] = target
        elif action == "recover":
            self.synchronize()
            if self.engine.status == "online":
                rows = self.store.rows("SELECT id FROM outbox WHERE state IN ('uncertain','conflicted','blocked') ORDER BY created_at,id")
                if rows:
                    self.sync.resolve(self.rng.choice(rows)["id"], "keep_remote")
                    self.counts["explicit_archives"] += 1
        self.assert_invariants()

    def assert_invariants(self):
        assert not self.remote.violation, self.remote.violation
        rows = self.store.rows("SELECT * FROM outbox")
        self.ever_uncertain.update(row["id"] for row in rows if row["state"] == "uncertain")
        blocked_subjects = {row["subject_id"] for row in rows if row["kind"] in ("review", "lesson") and row["state"] in OPEN_STATES}
        for mode in ("reviews", "lessons"):
            assert not blocked_subjects.intersection(subject["id"] for _, subject in self.engine.assignments(mode)), "Pending work entered another graded cycle"
        for row in rows:
            body = json.loads(row["body"])
            session = self.store.session(body["session_id"])
            assert session and session["mode"] != "practice", "Practice created a graded submission"
            entry = next(item for item in session["queue"] if item["subject_id"] == row["subject_id"])
            assert entry["done"] and all(entry["parts"].values()), "Submission preceded completing and acknowledging all question parts"
            kind = self.remote.subjects[row["subject_id"]]["object"]
            required = ("meaning", "reading") if kind in ("kanji", "vocabulary") else ("meaning",)
            assert all((session["id"], row["subject_id"], part) in self.acknowledged_parts for part in required), "A required question part has no observed feedback acknowledgement"
            assert body["errors"] == entry["errors"], "Submitted error counts diverged from the durable session"
            if row["state"] == "confirmed":
                assert row["id"] in self.remote.accepted_operations, "Local progress was confirmed without mock remote acceptance"


def run_seed(seed, steps=300, failure_dir=None):
    with tempfile.TemporaryDirectory(prefix="wanikani-soak-") as directory, ExitStack() as guards:
        study_random, identifiers = random.Random(seed ^ 0x5A17), random.Random(seed ^ 0x1D5)
        guards.enter_context(patch("wanikani.engine.random.SystemRandom", return_value=study_random))
        guards.enter_context(patch("wanikani.engine.uuid.uuid4", side_effect=lambda: uuid.UUID(int=identifiers.getrandbits(128))))
        attempts = []
        def blocked(*args, **kwargs):
            attempts.append("external I/O attempted")
            raise AssertionError("The developer soak cannot use network or subprocesses")
        for target in ("socket.socket", "socket.create_connection", "socket.getaddrinfo", "urllib.request.urlopen", "subprocess.Popen"):
            guards.enter_context(patch(target, side_effect=blocked))
        harness = Harness(seed, directory)
        try:
            for step in range(steps):
                harness.step(step)
                assert not attempts, "The developer soak tried external I/O"
            report = {"seed": seed, "steps": steps, "passed": True, "fixture_only": True, "counts": dict(sorted(harness.counts.items())),
                "accepted_operations": len(harness.remote.accepted_operations),
                "trace_sha256": hashlib.sha256(json.dumps(harness.trace, sort_keys=True).encode()).hexdigest()}
        except Exception as error:
            report = {"seed": seed, "steps": len(harness.trace), "passed": False, "fixture_only": True, "error": str(error),
                "traceback": traceback.format_exc(), "counts": dict(sorted(harness.counts.items())), "trace": harness.trace,
                "failure_state": {"session": harness.store.session(),
                    "outbox": [dict(row) for row in harness.store.rows("SELECT id,kind,subject_id,state,detail FROM outbox ORDER BY created_at,id")],
                    "remote_assignments": list(harness.remote.assignments.values()),
                    "accepted_operations": sorted(harness.remote.accepted_operations)}}
            if failure_dir:
                destination = Path(failure_dir)
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = destination / ("seed-" + str(seed) + "-failure.json")
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                report["failure_trace"] = str(path.resolve())
        finally:
            harness.store.close()
        return report


def bounded_number(maximum):
    def parse(value):
        number = int(value)
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError("Choose a value between 1 and " + str(maximum))
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=0, help="First deterministic seed (default: 0)")
    parser.add_argument("--seeds", type=bounded_number(100), default=3)
    parser.add_argument("--steps", type=bounded_number(5000), default=300)
    parser.add_argument("--failure-dir", type=Path, default=Path("test-results/soak"))
    args = parser.parse_args()
    failed = 0
    for seed in range(args.seed, args.seed + args.seeds):
        result = run_seed(seed, args.steps, args.failure_dir)
        print(json.dumps({key: value for key, value in result.items() if key not in ("trace", "traceback", "failure_state")}, ensure_ascii=False), flush=True)
        failed += not result["passed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
