"""Versioned, lossless profile migrations and stable library identity adoption."""

from dataclasses import replace
from pathlib import Path
import copy
import shutil
import tempfile

PROFILE_VERSION = 1


def profile_components(value):
    from .backend import COMPONENT_LABELS, LEGACY_COMPONENTS

    if "components" not in value and "mode" in value:
        mode = value["mode"]
        if mode not in LEGACY_COMPONENTS:
            raise ValueError("Unknown legacy profile mode: " + str(mode))
        value["components"] = {name: name in LEGACY_COMPONENTS[mode] for name in COMPONENT_LABELS}
    return value


PROFILE_MIGRATIONS = [profile_components]


def migrate_profile(value):
    if not isinstance(value, dict):
        raise ValueError("Profile must be a JSON object")
    if not value:
        return {}
    value = copy.deepcopy(value)
    version = value.get("schema_version", 0)
    if type(version) is not int or not 0 <= version <= PROFILE_VERSION:
        raise ValueError("Unsupported profile schema version")
    for migration in PROFILE_MIGRATIONS[version:]:
        value = migration(value)
    value["schema_version"] = PROFILE_VERSION
    return value


def migrate_settings(value):
    if not isinstance(value, dict):
        raise ValueError("Settings must be a JSON object")
    value = dict(value)
    if value.get("theme") == "original":
        value["theme"] = "dark"
    return value


def migrate_library(repository, games):
    from .models import stable_game_id
    from .storage import atomic_json, read_json

    changed, result = {}, []
    for game in games:
        identity = stable_game_id(game)
        if identity != game.id:
            changed[game.id] = identity
            for directory in ("profiles", "updates"):
                old = repository.directory / directory / (game.id + ".json")
                new = old.with_name(identity + ".json")
                if old.exists():
                    record = read_json(old)
                    if new.exists() and read_json(new) != record:
                        raise ValueError(
                            "Conflicting records during library identity migration: " + str(new)
                        )
                    if not new.exists():
                        atomic_json(new, record)
            old = repository.directory / "backups" / game.id
            new = old.with_name(identity)
            if old.is_dir() and not new.exists():
                # Publish the complete recovery tree at once. Legacy evidence is retained.
                with tempfile.TemporaryDirectory(dir=old.parent, prefix=".identity-") as temporary:
                    staged = Path(temporary) / "tree"
                    if any(path.is_symlink() for path in old.rglob("*")):
                        raise ValueError("Symlink in recovery tree during identity migration")
                    shutil.copytree(old, staged, symlinks=True)
                    for record in [staged / "baseline.json", *staged.glob("*/snapshot.json")]:
                        if not record.is_file():
                            continue
                        value = read_json(record)

                        def remap(item):
                            if isinstance(item, str) and item.startswith(str(old) + "/"):
                                return str(new) + item[len(str(old)) :]
                            if isinstance(item, dict):
                                return {key: remap(v) for key, v in item.items()}
                            if isinstance(item, list):
                                return [remap(v) for v in item]
                            return item

                        atomic_json(record, remap(value))
                    staged.rename(new)
            game = replace(game, id=identity)
        result.append(game)
    if changed:
        for name in ("drafts.json", "workspace.json", "job-history.json"):
            path = repository.directory / name
            if not path.exists():
                continue

            def remap(item):
                if isinstance(item, str):
                    for old, new in changed.items():
                        prefix = str(repository.directory / "backups" / old)
                        if item.startswith(prefix + "/"):
                            return str(repository.directory / "backups" / new) + item[len(prefix) :]
                    return changed.get(item, item)
                if isinstance(item, dict):
                    return {changed.get(key, key): remap(v) for key, v in item.items()}
                if isinstance(item, list):
                    return [remap(v) for v in item]
                return item

            atomic_json(path, remap(read_json(path)))
        repository.save_games(result)
    return result
