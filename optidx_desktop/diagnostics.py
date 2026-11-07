import hashlib
import os
import re
import shutil

from . import __version__
from .backend import BACKEND_PATH, load_backend
from .inspection import inspect_game


def redact(value):
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if re.search(r"TOKEN|KEY|SECRET|PASS", str(key), re.I)
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def report(game, preferences=None):
    from PySide6.QtGui import QGuiApplication

    platform = (
        QGuiApplication.platformName() if QGuiApplication.instance() else "GUI not initialized"
    )
    return {
        "desktop_version": __version__,
        "qt_platform": platform,
        "backend_version": load_backend().SCRIPT_VERSION,
        "backend_sha256": hashlib.sha256(BACKEND_PATH.read_bytes()).hexdigest(),
        "game": game.to_dict(),
        "state": inspect_game(game),
        "preferences": redact(preferences or {}),
        "tools": {name: shutil.which(name) for name in ["curl", "unzip", "7z", "7za", "7zz"]},
        "session": {
            key: os.environ.get(key) for key in ["XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"]
        },
    }
