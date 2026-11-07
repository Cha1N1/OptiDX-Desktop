"""Pruned file traversal shared by discovery and operation backups."""

import os
from pathlib import Path

SKIP = {
    ".git",
    ".cache",
    "__pycache__",
    "reshade-shaders",
    "screenshots",
    "logs",
    "shadercache",
    "shader_cache",
    "_commonredist",
}


def walk_files(root):
    for folder, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name.casefold() not in SKIP
            and not name.startswith(".optidx")
            and not (Path(folder) / name).is_symlink()
        )
        for name in sorted(files):
            path = Path(folder) / name
            if not path.is_symlink():
                yield path
