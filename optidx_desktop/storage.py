import json
import os
from pathlib import Path
import tempfile


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
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Repository:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else data_dir()

    def games(self):
        from .models import Game
        return [Game.from_dict(g) for g in read_json(self.directory / "library.json", [])]

    def save_games(self, games):
        atomic_json(self.directory / "library.json", [g.to_dict() for g in games])

    def preferences(self, game):
        return read_json(self.directory / "profiles" / (game.id + ".json"), {})

    def save_preferences(self, game, preferences):
        atomic_json(self.directory / "profiles" / (game.id + ".json"), preferences)
