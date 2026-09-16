from datetime import datetime, timezone
from pathlib import Path
import os
import re


# Matches the bounded account catalogue used by readiness and local practice.
MAX_REVIEW_SESSION = 12000


def session_queue_limit(session):
    """Only explicitly marked all-due review sessions exceed a normal batch."""
    return MAX_REVIEW_SESSION if session.get("mode") == "reviews" and session.get("all_reviews") is True else 20


def stamp(value=None):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z") if value is not None else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def state_home():
    return private_dir(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy/wanikani")


class UserError(Exception):
    def __init__(self, message, code="invalid_request"):
        super().__init__(message)
        self.code = code


def accessible_subject(subject, maximum):
    """Treat missing or malformed access metadata as unavailable content."""
    if not isinstance(subject, dict) or not isinstance(subject.get("data"), dict):
        return False
    data = subject["data"]
    level = data.get("level")
    return type(level) is int and 1 <= level <= maximum and data.get("hidden_at") is None


def plain(text):
    """API mnemonic tags are data, never executable QML/HTML."""
    return re.sub(r"<[^>]*>", "", str(text or ""))
