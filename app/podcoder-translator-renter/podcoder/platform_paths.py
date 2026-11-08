"""Shared desktop data directory; no dependency on the current working directory."""
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    explicit = os.environ.get("PODCODER_STATE_DIR") or os.environ.get("SIMKOSI_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "SimkoSI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SimkoSI"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "SimkoSI"
