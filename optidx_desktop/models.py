from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path


@dataclass
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
