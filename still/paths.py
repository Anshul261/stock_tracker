"""Where Still keeps its private data on this computer."""
from pathlib import Path
import os
import sys


def data_dir() -> Path:
    """Per-user app data folder, private to the current user. STILL_DATA_DIR overrides it."""
    override = os.environ.get("STILL_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home()) / "Still"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Still"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "still"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass  # Windows: rely on the per-user profile's inherited permissions.
    return base
