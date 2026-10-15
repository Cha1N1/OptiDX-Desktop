"""JSON-lines job protocol. Stdout is structured; OptiDX logs stay on stderr."""
import argparse
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import traceback

from .backend import execute_backend
from .backups import baseline_path, remember_baseline, restore_originals, snapshot
from .models import Game
from .storage import Repository, data_dir


def emit(kind, **values):
    print(json.dumps({"event": kind, **values}), flush=True)


def restore_record(path, before):
    from .assets import atomic_bytes
    if before is None:
        path.unlink(missing_ok=True)
    else:
        atomic_bytes(path, *before)


def run_job(request, directory=None):
    game = Game.from_dict(request["game"])
    action = request["action"]
    preferences = dict(request.get("preferences", {}))
    repository = Repository(directory)
    preferences["_data_dir"] = str(repository.directory)
    key = hashlib.sha256(str(Path(game.root).resolve()).encode()).hexdigest()
    locks = repository.directory / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / (key + ".lock")).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from .backend import validate_game
        if action not in {"refresh_catalogs", "import_asset", "import_url", "prepare_template", "list_releases"}:
            validate_game(game)
        from .features import FEATURE_ACTIONS, run_feature, update_features
        if action in {"check_updates", "refresh_catalogs", "list_releases", "shader_files", "import_asset", "import_url", "prepare_template"}:
            with contextlib.redirect_stdout(sys.stderr):
                data = run_feature(game, action, preferences, repository, request.get("options", {}))
            emit("result", ok=True, data=data)
            return data
        if action == 'restore_snapshot':
            from .backups import verify_snapshot
            selected_snapshot = Path(request.get('options', {}).get('snapshot', '')).resolve()
            backup_root = (repository.directory / 'backups' / game.id).resolve()
            if selected_snapshot.parent != backup_root:
                raise ValueError('Select a retained backup for this game')
            verify_snapshot(selected_snapshot, game)
        emit("progress", message="Backing up existing mod files")
        folder = snapshot(game, repository)
        from .backups import root_snapshot, rollback_snapshot, external_config_snapshot, rollback_external_config
        root_folder = root_snapshot(game, repository)
        from .storage import atomic_json, read_json
        for backup_folder in (folder, root_folder):
            if backup_folder:
                metadata = read_json(backup_folder / 'snapshot.json', {})
                atomic_json(backup_folder / 'snapshot.json', {**metadata, 'action': action, 'game': game.title})
        external_before = {} if action == "restore_snapshot" else external_config_snapshot(game, preferences)
        baseline = baseline_path(game, repository)
        baseline_before = (baseline.read_bytes(), baseline.stat().st_mode & 0o777) if baseline.is_file() else None
        profile_commit = None
        emit("backup", path=str(folder))
        if root_folder:
            emit("backup", path=str(root_folder))
        emit("progress", message=f"Running {action} for {game.title}")
        try:
            if action not in {"remove", "remove_asset", "restore_dll", "remove_helixsr", "restore_snapshot"}:
                remember_baseline(game, repository, folder)
            with contextlib.redirect_stdout(sys.stderr):
                if action == 'restore_snapshot':
                    from .backups import restore_snapshot_files
                    restore_snapshot_files(selected_snapshot, game)
                    from .inspection import inspect_game
                    state = inspect_game(game)
                    data = None
                elif action in FEATURE_ACTIONS:
                    data = run_feature(game, action, preferences, repository, request.get("options", {}))
                    from .inspection import inspect_game
                    state = inspect_game(game)
                else:
                    if action != "update" or (game.target / ".optidx-files").exists():
                        state = execute_backend(game, action, preferences)
                    else:
                        from .inspection import inspect_game
                        state = inspect_game(game)
                    if action == "remove":
                        from .features import restore_display
                        restore_display(game)
                        from .channels import restore_loader_settings
                        restore_loader_settings(game)
                        (game.target / ".optidx-desktop-versions.json").unlink(missing_ok=True)
                        from .features import remove_all_assets
                        remove_all_assets(game)
                    if action == "update":
                        update_features(game, repository, preferences)
                    data = None
                if action == "remove":
                    restore_originals(game, repository)
                    from .inspection import inspect_game
                    state = inspect_game(game)
                if action == "remove_helixsr":
                    # Commit only after file changes and inspection succeed.
                    # Read fresh choices so a long job does not overwrite edits
                    # saved by the GUI while it was running.
                    from .backend import COMPONENT_LABELS, selected_components
                    current = repository.preferences(game)
                    enabled = selected_components(current or preferences) - {"helixsr"}
                    path = repository.directory / "profiles" / (game.id + ".json")
                    profile_commit = (path, (path.read_bytes(), path.stat().st_mode & 0o777) if path.is_file() else None)
                    repository.save_preferences(game, {**current, "components": {key: key in enabled for key in COMPONENT_LABELS}})
        except Exception as error:
            # Attempt independent recoveries even if one location is unavailable.
            recoveries = [] if action == 'restore_snapshot' else [('UE configuration', lambda: rollback_external_config(game, external_before))]
            if root_folder:
                recoveries.append(('game root', lambda: rollback_snapshot(Path(game.root), root_folder)))
            recoveries.append(('game binary folder', lambda: rollback_snapshot(game.target, folder)))
            recoveries.append(('backup metadata', lambda: restore_record(baseline, baseline_before)))
            if profile_commit is not None:
                recoveries.append(('game profile', lambda: restore_record(*profile_commit)))
            errors = []
            for name, restore in recoveries:
                try:
                    restore()
                except Exception as rollback_error:
                    errors.append(name + ': ' + str(rollback_error))
            if errors:
                raise RuntimeError(f"{error}; rollback requires manual recovery: {'; '.join(errors)}") from error
            emit("progress", message="Failed operation rolled back; verified snapshots retained")
            raise
        emit("result", ok=True, state=state, data=data)
        return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--data-dir")
    arguments = parser.parse_args()
    try:
        run_job(json.loads(arguments.request), arguments.data_dir)
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        emit("result", ok=False, error=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
