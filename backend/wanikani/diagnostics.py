"""Explicit aggregate-only diagnostics, kept separate for demo and account state."""
import json
import os
import sys
import tempfile
from pathlib import Path

from . import VERSION


STATUSES = frozenset(("demo", "disconnected", "offline", "online", "clock_changed",
    "unauthorized", "forbidden", "rate_limited", "api_error", "sync_error",
    "account_mismatch", "cancelled", "vacation", "invalid_request"))


def count(value):
    return value if type(value) is int and value >= 0 else 0


def export(directory, demo, snapshot, schema):
    """Do not copy nested snapshot objects: they can gain private fields later."""
    cache = snapshot.get("cache", {})
    if not isinstance(cache, dict):
        cache = {}
    status = snapshot.get("status")
    report = {"version": VERSION, "python": sys.version.split()[0], "protocol": 1,
        "demo": bool(demo), "status": status if isinstance(status, str) and status in STATUSES else "unknown",
        "pending": count(snapshot.get("pending")), "attention": count(snapshot.get("attention")),
        "schema": count(schema), "cache": {key: count(cache.get(key)) for key in ("files", "bytes", "subjects")}}
    mode = "demo" if demo else "account"
    destination = Path(directory) / f"diagnostics-{mode}.json"
    # Replace an existing link, never follow it. An interruption leaves the last
    # complete report intact; restrictive permissions apply before any write.
    descriptor, temporary = tempfile.mkstemp(prefix=f".diagnostics-{mode}-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {**report, "path": str(destination)}


def clear(directory, demo):
    """Delete only reports owned by this mode, including interrupted exports."""
    directory = Path(directory)
    mode = "demo" if demo else "account"
    (directory / f"diagnostics-{mode}.json").unlink(missing_ok=True)
    for temporary in directory.glob(f".diagnostics-{mode}-*.tmp"):
        if temporary.is_file() or temporary.is_symlink():
            temporary.unlink(missing_ok=True)
    legacy = directory / "diagnostics.json"
    if legacy.is_symlink():
        legacy.unlink()  # The old owned name is removed without reading its target.
    elif legacy.is_file():
        try:
            report = json.loads(legacy.read_text())
            legacy_demo = isinstance(report, dict) and report.get("demo") is True
        except (OSError, ValueError):
            legacy_demo = False
        if legacy_demo == bool(demo):
            legacy.unlink()
