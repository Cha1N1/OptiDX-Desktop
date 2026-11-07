import json
import os
from pathlib import Path
import tempfile
import time
import warnings


def data_dir():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "optidx-desktop"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_directory(path):
    """Persist a replacement's directory entry as well as its file contents."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path, default=None, *, strict=True):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as error:
        if strict:
            raise ValueError(f"Cannot read JSON record {path}: {error}") from error
        # Only disposable caches may opt into recovery. Never discard evidence.
        if isinstance(error, ValueError):
            saved = path.with_name(path.name + f".corrupt-{time.time_ns()}")
            path.replace(saved)
            warnings.warn(f"Corrupt cache preserved at {saved}", RuntimeWarning)
        return default


class Repository:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else data_dir()

    def games(self):
        from .models import Game
        from .migrations import migrate_library

        return migrate_library(
            self, [Game.from_dict(g) for g in read_json(self.directory / "library.json", [])]
        )

    def save_games(self, games):
        atomic_json(self.directory / "library.json", [g.to_dict() for g in games])

    def preferences(self, game):
        from .migrations import migrate_profile

        return migrate_profile(read_json(self.directory / "profiles" / (game.id + ".json"), {}))

    def save_preferences(self, game, preferences):
        from .migrations import migrate_profile, PROFILE_VERSION

        value = migrate_profile(preferences)
        atomic_json(
            self.directory / "profiles" / (game.id + ".json"),
            {**value, "schema_version": PROFILE_VERSION},
        )
