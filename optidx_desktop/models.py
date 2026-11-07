from dataclasses import asdict, dataclass, field
import copy
from typing import Callable
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class Game:
    id: str
    title: str
    store: str
    root: str
    executable: str = ""
    prefix: str = ""
    app_id: str = ""
    runner: str = ""
    launch_uri: str = ""
    launcher_kind: str = ""  # Native/Flatpak installation that supplied the game metadata.

    @property
    def target(self):
        return Path(self.executable).parent if self.executable else Path(self.root)

    @property
    def available(self):
        return Path(self.root).is_dir()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def game_id(store, key):
    return hashlib.sha256((store + ":" + str(key)).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class Job:
    game: Game
    action: str
    preferences: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    callback: Callable | None = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "preferences", copy.deepcopy(self.preferences))
        object.__setattr__(self, "options", copy.deepcopy(self.options))


def stable_game_id(game):
    if game.store == "Steam" and game.app_id:
        return game_id("Steam", game.app_id)
    if game.store == "Heroic" and game.app_id:
        return game_id(
            "Heroic", ":".join((game.launcher_kind or "native", game.runner, game.app_id))
        )
    return game.id
