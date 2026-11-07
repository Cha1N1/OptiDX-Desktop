"""Cheap backend path defaults; importing these never executes the backend."""

import os
from pathlib import Path


def helixsr_directory():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "optidx/helixsr"
