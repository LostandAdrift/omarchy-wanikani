from datetime import datetime, timezone
from pathlib import Path
import os
import re


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


def plain(text):
    """API mnemonic tags are data, never executable QML/HTML."""
    return re.sub(r"<[^>]*>", "", str(text or ""))
