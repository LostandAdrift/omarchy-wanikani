#!/usr/bin/env python3
"""Developer-only warm stdio benchmark using 9,016 authored demo subjects.

Runs the real worker entry point in private temporary directories. A bootstrap
blocks network, keyring and subprocess access inside each worker. No production
test flag, live account, native shell or existing user state is used.

Each operation and a following draft/session command are written together. The
second response exposes work performed *after* the first response, which an
answer-only timer misses. Preparation and readiness settling are outside the
warm measurements; readiness started by the measured operation remains active.

    python3 tools/benchmark_worker.py --samples 30 --compare-ref 9d5ebc9
"""
import argparse
from collections import Counter, deque
import io
import json
import math
from pathlib import Path
import queue
import sqlite3
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from wanikani.command_codec import decode_text
SUBJECT_COUNT = 9016
TIMEOUT = 30

# The guards exist only in this developer-created child process. Even an
# accidental future account path fails before touching a transport or helper.
GUARDS = r'''
import socket
import subprocess
import urllib.request
def forbidden(*args, **kwargs):
    raise AssertionError("Developer benchmark forbids network/keyring/subprocess access")
socket.socket = forbidden
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
urllib.request.urlopen = forbidden
subprocess.Popen = forbidden
'''

BUILD_FIXTURE = GUARDS + r'''
import copy
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(sys.argv[1]) / "backend"))
from wanikani.common import stamp
from wanikani.demo import populate
from wanikani.store import Store
directory = Path(sys.argv[2])
directory.mkdir(mode=0o700)
(directory / "mode.json").write_text('{"mode":"demo"}')
(directory / "mode.json").chmod(0o600)
store = Store(directory / "demo.sqlite3")
now = time.time()
populate(store, now)
subject = store.subject(4)
assignment = store.related("assignment", 4)
with store.transaction():
    # Only clones are due, so every measured review has meaning + reading.
    for sid in range(1, 17):
        existing = store.related("assignment", sid)
        if existing["data"].get("started_at"):
            existing["data"]["available_at"] = stamp(now + 86400 * 7)
            store.put(existing)
    for sid in range(100, 9100):
        item = copy.deepcopy(subject)
        item["id"] = sid
        item["data"]["level"] = sid % 60 + 1
        item["data"]["meaning_mnemonic"] = "Independently authored sample mnemonic. " * 20
        store.put(item)
        current = copy.deepcopy(assignment)
        current["id"] = sid + 10000
        current["data"]["subject_id"] = sid
        current["data"]["available_at"] = stamp(now - 60 if sid % 3 == 0 else now + sid * 60)
        store.put(current)
store.close()
'''

RUN_WORKER = GUARDS + r'''
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / "backend"))
import worker
from wanikani.credentials import Keyring
Keyring.get = forbidden
Keyring.set = forbidden
Keyring.delete = forbidden
sys.argv = ["worker.py", "--state-dir", sys.argv[2]]
raise SystemExit(worker.main())
'''


def statistics_ms(values):
    ordered = sorted(values)
    return {"median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 3),
        "min_ms": round(ordered[0], 3), "max_ms": round(ordered[-1], 3),
        "samples": len(ordered)}


class Bridge:
    """Observe complete stdout lines from one owned worker subprocess."""
    def __init__(self, source, directory):
        self.process = subprocess.Popen([sys.executable, "-u", "-c", RUN_WORKER,
            str(source), str(directory)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.lines = queue.Queue()
        self.stderr = deque(maxlen=20)
        self.sequence = 0
        self.events = Counter()
        self.readers = [threading.Thread(target=self.read_stdout, daemon=True),
            threading.Thread(target=self.read_stderr, daemon=True)]
        for reader in self.readers:
            reader.start()

    def read_stdout(self):
        try:
            for line in self.process.stdout:
                # Timestamp reception before decoding the JSON payload.
                self.lines.put((time.perf_counter_ns(), json.loads(line)))
        except Exception as error:
            self.lines.put((time.perf_counter_ns(), {"reader_error": str(error)}))
        finally:
            self.lines.put((time.perf_counter_ns(), {"eof": True}))

    def read_stderr(self):
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())

    def receive(self, deadline):
        try:
            received, message = self.lines.get(timeout=max(.001, deadline - time.monotonic()))
        except queue.Empty as error:
            raise RuntimeError("Timed out waiting for worker; stderr: " + "\n".join(self.stderr)) from error
        if message.get("eof") or message.get("reader_error"):
            raise RuntimeError("Worker stopped or emitted invalid JSON; stderr: " + "\n".join(self.stderr))
        if "event" in message:
            self.events[message["event"]] += 1
        return received, message

    def wait_started(self):
        # main emits an initial full state and the completed demo startup job
        # emits a second. Wait for both, then exclude initial readiness warming.
        deadline = time.monotonic() + TIMEOUT
        while self.events["state"] < 2:
            self.receive(deadline)
        self.settle_readiness()

    def request(self, method, args=None):
        self.sequence += 1
        return {"v": 1, "id": "benchmark-" + str(self.sequence),
            "method": method, "args": args or {}}

    def pair(self, method, args=None, fence="session", fence_args=None):
        requests = [self.request(method, args), self.request(fence, fence_args)]
        serialized = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            for item in requests)
        started = time.perf_counter_ns()
        self.process.stdin.write(serialized)
        self.process.stdin.flush()
        wanted = {item["id"] for item in requests}
        responses = {}
        deadline = time.monotonic() + TIMEOUT
        while len(responses) < 2:
            received, message = self.receive(deadline)
            if message.get("id") in wanted:
                if not message.get("ok"):
                    raise RuntimeError("Fixture command failed: " + json.dumps(message, ensure_ascii=False))
                responses[message["id"]] = (received, message.get("data"))
        first, value = responses[requests[0]["id"]]
        second, _ = responses[requests[1]["id"]]
        if second < first:
            raise AssertionError("Sequential local worker replies arrived out of order")
        return value, {"response": (first - started) / 1e6,
            "pipeline_drain": (second - first) / 1e6,
            "total_pair": (second - started) / 1e6}

    def command(self, method, args=None):
        # A cheap session fence drains any synchronous after-response state
        # event before the next preparation/measurement begins.
        return self.pair(method, args)[0]

    def settle_readiness(self):
        deadline = time.monotonic() + TIMEOUT
        while self.command("readiness").get("checking"):
            if time.monotonic() >= deadline:
                raise RuntimeError("Readiness did not settle for the authored warm fixture")
            time.sleep(.025)

    def close(self):
        self.process.stdin.close()
        try:
            code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            raise RuntimeError("Owned benchmark worker did not exit cleanly on stdin EOF")
        finally:
            for reader in self.readers:
                reader.join(timeout=2)
            self.process.stdout.close()
            self.process.stderr.close()
        if code:
            raise RuntimeError("Worker exited with code " + str(code) + ": " + "\n".join(self.stderr))


def benchmark(source, directory, samples, label, batch_size=5):
    subprocess.run([sys.executable, "-c", BUILD_FIXTURE, str(source), str(directory)],
        check=True, capture_output=True, text=True, timeout=60)
    bridge = Bridge(source, directory)
    measurements = {name: [] for name in ("new_review_start", "resume", "draft", "check",
        "feedback_advance", "final_subject_advance")}
    if batch_size > 1:
        measurements["subject_advance"] = []
    fences = {name: "draft" for name in measurements}
    fences["final_subject_advance"] = "session"
    try:
        bridge.wait_started()
        for index in range(samples):
            bridge.settle_readiness()
            def measure(name, method, args=None):
                result, elapsed = bridge.pair(method, args, fences[name], {"text": "w"})
                measurements[name].append(elapsed)
                return result
            view = measure("new_review_start", "start", {"mode": "reviews", "limit": batch_size})
            if view["phase"] != "question" or view["subject"]["type"] != "vocabulary" or view["total"] != batch_size:
                raise AssertionError("Fixture requires a fresh two-part vocabulary review")
            view = measure("resume", "start", {"mode": "resume"})
            measure("draft", "draft", {"text": "wa"})
            view = measure("check", "answer", {"text": view["subject"]["meanings"][0]})
            if not view["feedback"]["correct"]:
                raise AssertionError("Authored meaning was not accepted")
            view = measure("feedback_advance", "advance")
            if view["phase"] != "question" or view["part"] != "reading" or view["completed"]:
                raise AssertionError("Nonfinal feedback advance did not preserve the subject")
            reading = next(item["reading"] for item in view["subject"]["readings"] if item["accepted"])
            view = bridge.command("answer", {"text": reading})
            if not view["feedback"]["correct"]:
                raise AssertionError("Authored reading was not accepted")
            view = measure("final_subject_advance" if batch_size == 1 else "subject_advance", "advance")
            if view["completed"] != 1 or (batch_size > 1 and view["phase"] != "question"):
                raise AssertionError("Final feedback did not complete exactly one subject")
            # Keep all five subjects in the same durable session. Complete the
            # middle subjects outside the timing samples, then separately time
            # the last subject's feedback acknowledgment and session summary.
            for completed in range(1, batch_size):
                if view["phase"] != "question" or view["part"] != "meaning" or view["completed"] != completed:
                    raise AssertionError("Batch advanced to an unexpected question")
                bridge.command("answer", {"text": view["subject"]["meanings"][0]})
                view = bridge.command("advance")
                if view["phase"] != "question" or view["part"] != "reading":
                    raise AssertionError("Authored batch meaning was not accepted")
                reading = next(item["reading"] for item in view["subject"]["readings"] if item["accepted"])
                view = bridge.command("answer", {"text": reading})
                if not view["feedback"]["correct"]:
                    raise AssertionError("Authored batch reading was not accepted")
                view = (measure("final_subject_advance", "advance") if completed + 1 == batch_size
                    else bridge.command("advance"))
            if view["phase"] != "complete" or view["completed"] != batch_size:
                raise AssertionError("The entire authored batch was not completed")
            if (index + 1) % 10 == 0 or index + 1 == samples:
                print(f"{label}: {index + 1}/{samples} samples", file=sys.stderr, flush=True)
        bridge.settle_readiness()
        result = {"source": label, "batch_size": batch_size, "operations": {name: {"queued_command": fences[name],
            **{field: statistics_ms([sample[field] for sample in values])
                for field in ("response", "pipeline_drain", "total_pair")}}
            for name, values in measurements.items()}, "observed_events": dict(bridge.events),
            "completed_authored_reviews": samples * batch_size}
    finally:
        bridge.close()
    # Read only our disposable fixture after the worker has closed. This makes
    # retained response cost visible without reading any user account data.
    with sqlite3.connect((directory / "demo.sqlite3").as_uri() + "?mode=ro", uri=True) as database:
        count = total = maximum = stored = compressed = 0
        for body, in database.execute("SELECT body FROM commands"):
            logical = len(decode_text(body).encode("utf-8"))
            count += 1
            total += logical
            maximum = max(maximum, logical)
            stored += len(body.encode("utf-8")) if isinstance(body, str) else len(body)
            compressed += isinstance(body, bytes)
    result["command_journal"] = {"rows": count, "response_bytes": total,
        "stored_bytes": stored, "compressed_rows": compressed,
        "largest_response_bytes": maximum, "bytes_per_completed_subject": round(total / (samples * batch_size), 1),
        "stored_bytes_per_completed_subject": round(stored / (samples * batch_size), 1)}
    return result


def archived_source(ref, directory):
    commit = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], cwd=ROOT,
        capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    result = subprocess.run(["git", "archive", "--format=tar", commit, "backend"], cwd=ROOT,
        capture_output=True, check=True, timeout=20)
    directory.mkdir()
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        archive.extractall(directory, filter="data")
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=5,
        help="Subjects per durable review session, from 1 to 20 (default 5)")
    parser.add_argument("--compare-ref", help="Optional local git commit/ref, read with git archive")
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("--samples must be between 1 and 100")
    if not 1 <= args.batch_size <= 20:
        parser.error("--batch-size must be between 1 and 20")
    with tempfile.TemporaryDirectory(prefix="wanikani-worker-benchmark-") as temporary:
        directory = Path(temporary)
        results = [benchmark(ROOT, directory / "current-state", args.samples, "current working tree", args.batch_size)]
        if args.compare_ref:
            archived = directory / "baseline-source"
            commit = archived_source(args.compare_ref, archived)
            results.append(benchmark(archived, directory / "baseline-state", args.samples, commit, args.batch_size))
        print(json.dumps({"fixture_only": True, "subjects": SUBJECT_COUNT,
            "initial_due_reviews": 3000, "mode": "demo", "batch_size": args.batch_size,
            "network_keyring_subprocess_blocked_in_worker": True,
            "measurement": "Complete stdout-line reception; paired commands written together. Warm preparation and readiness settling excluded.",
            "completion_operations": "subject_advance completes the first subject and keeps studying (batch>1); final_subject_advance completes the last subject and the session.",
            "scope": "Worker protocol only; excludes QML rendering. Sequential runs remain sensitive to other host load.",
            "results": results}, indent=2))


if __name__ == "__main__":
    main()
