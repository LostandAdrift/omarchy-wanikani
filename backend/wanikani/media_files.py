"""Read-only availability checks for files owned by the media cache."""
import stat
from pathlib import Path


def available_file(directory, value):
    """Return a nonempty regular file directly inside this cache, or None.

    Stored paths are data. Do not follow symlinks or accept another directory,
    even when the external file exists. Decoding an image remains the native
    renderer's responsibility; byte presence cannot prove image validity.
    """
    if not isinstance(value, str):
        return None
    directory = Path(directory).absolute()
    path = Path(value)
    if not path.is_absolute() or path.parent != directory:
        return None
    try:
        info = path.stat(follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and info.st_size > 0:
            return path
    except (OSError, ValueError):
        pass
    return None
