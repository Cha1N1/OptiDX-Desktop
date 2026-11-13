"""JSON-lines job protocol. Stdout is structured; OptiDX logs stay on stderr."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import signal
import threading
from pathlib import Path
import sys
import traceback

from .backend import execute_backend
from .errors import CorruptRecord, GameBusy, ManualRecoveryRequired
from .backups import baseline_path, remember_baseline, restore_originals, snapshot
from .models import Game
from .storage import Repository


def emit(kind, **values):
    print(json.dumps({"event": kind, **values}), flush=True)


def restore_record(path, before):
    from .assets import atomic_bytes

    if before is None:
        path.unlink(missing_ok=True)
    else:
        atomic_bytes(path, *before)


def _run_job(request, directory=None):
    game = Game.from_dict(request["game"])
    action = request["action"]
    preferences = dict(request.get("preferences", {}))
    repository = Repository(directory)
    preferences["_data_dir"] = str(repository.directory)
    key = hashlib.sha256(str(Path(game.root).resolve()).encode()).hexdigest()
    locks = repository.directory / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / (key + ".lock")).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GameBusy(
                "Another OptiDX operation is using this game. Try again when it finishes."
            ) from error
        from .backend import validate_game

        if action not in {
            "refresh_catalogs",
            "import_asset",
            "import_url",
            "prepare_template",
            "list_releases",
        }:
            validate_game(game, allow_moved=True)
        from .features import FEATURE_ACTIONS, run_feature, update_features

        if action in {
            "check_updates",
            "refresh_catalogs",
            "list_releases",
            "shader_files",
            "import_asset",
            "import_url",
            "prepare_template",
        }:
            with contextlib.redirect_stdout(sys.stderr):
                data = run_feature(
                    game, action, preferences, repository, request.get("options", {})
                )
            emit("result", ok=True, data=data)
            return data
        from .relocation import relocate_installation

        if relocate_installation(game, repository):
            emit(
                "progress",
                message="Verified moved installation; rebound install marker and recovery paths",
            )
        validate_game(game)
        if action == "restore_snapshot":
            from .backups import verify_snapshot

            selected_snapshot = Path(request.get("options", {}).get("snapshot", "")).resolve()
            backup_root = (repository.directory / "backups" / game.id).resolve()
            if selected_snapshot.parent != backup_root:
                raise ValueError("Select a retained backup for this game")
            verify_snapshot(selected_snapshot, game)
        emit("progress", message="Backing up existing mod files")
        folder = snapshot(game, repository)
        from .backups import (
            root_snapshot,
            rollback_snapshot,
            external_config_snapshot,
            rollback_external_config,
        )

        root_folder = root_snapshot(game, repository)
        from .storage import atomic_json, read_json

        for backup_folder in (folder, root_folder):
            if backup_folder:
                metadata = read_json(backup_folder / "snapshot.json", {})
                atomic_json(
                    backup_folder / "snapshot.json",
                    {
                        **metadata,
                        "action": action,
                        "game": game.title,
                        "operation_status": "active",
                    },
                )
        external_before = (
            {} if action == "restore_snapshot" else external_config_snapshot(game, preferences)
        )
        baseline = baseline_path(game, repository)
        baseline_before = (
            (baseline.read_bytes(), baseline.stat().st_mode & 0o777) if baseline.is_file() else None
        )
        profile_commit = None
        emit("backup", path=str(folder))
        if root_folder:
            emit("backup", path=str(root_folder))
        emit("progress", message=f"Running {action} for {game.title}")
        try:
            if action in {"install", "update", "configure", "update_group"}:
                remember_baseline(game, repository, folder)
            with contextlib.redirect_stdout(sys.stderr):
                if action == "restore_snapshot":
                    from .backups import restore_snapshot_files

                    restore_snapshot_files(selected_snapshot, game)
                    from .inspection import inspect_game

                    state = inspect_game(game)
                    data = None
                elif action in FEATURE_ACTIONS:
                    data = run_feature(
                        game, action, preferences, repository, request.get("options", {})
                    )
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
                        (game.target / ".optidx-desktop-framegen.json").unlink(missing_ok=True)
                        from .features import remove_all_assets

                        remove_all_assets(game)
                    if action == "update" and not request.get("options", {}).get("core_only"):
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
                    profile_commit = (
                        path,
                        (
                            (path.read_bytes(), path.stat().st_mode & 0o777)
                            if path.is_file()
                            else None
                        ),
                    )
                    repository.save_preferences(
                        game,
                        {
                            **current,
                            "components": {key: key in enabled for key in COMPONENT_LABELS},
                        },
                    )
        except Exception as error:
            # Attempt independent recoveries even if one location is unavailable.
            recoveries = (
                []
                if action == "restore_snapshot"
                else [("UE configuration", lambda: rollback_external_config(game, external_before))]
            )
            if root_folder:
                recoveries.append(
                    ("game root", lambda: rollback_snapshot(Path(game.root), root_folder))
                )
            recoveries.append(
                ("game binary folder", lambda: rollback_snapshot(game.target, folder))
            )
            recoveries.append(
                ("backup metadata", lambda: restore_record(baseline, baseline_before))
            )
            if profile_commit is not None:
                recoveries.append(("game profile", lambda: restore_record(*profile_commit)))
            errors = []
            for name, restore in recoveries:
                try:
                    restore()
                except Exception as rollback_error:
                    errors.append(name + ": " + str(rollback_error))
            from .backups import finish_snapshots

            if errors:
                finish_snapshots(game, repository, (folder, root_folder), "manual_recovery")
                message = f"{error}; rollback requires manual recovery: {'; '.join(errors)}"
                emit("recovery", state="manual", message=message)
                raise ManualRecoveryRequired(message) from error
            # Do not delete a selected restore source while handling its failure.
            finish_snapshots(game, repository, (folder, root_folder), "rolled_back")
            message = "Failed operation rolled back; snapshot retention follows app settings"
            emit("recovery", state="rolled_back", message=message)
            emit("progress", message=message)
            raise
        from .backups import finish_snapshots

        try:
            finish_snapshots(game, repository, (folder, root_folder))
        except (OSError, ValueError) as error:
            emit(
                "progress",
                message="Operation completed; snapshot cleanup needs attention: " + str(error),
            )
        emit("result", ok=True, state=state, data=data)
        return state


class JobInterrupted(InterruptedError):
    pass


@contextlib.contextmanager
def rollback_on_signals():
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {}

    def interrupted(number, frame):
        # A second graceful cancellation must not interrupt recovery writes.
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        raise JobInterrupted("Operation interrupted by signal " + str(number))

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def run_job(request, directory=None):
    with rollback_on_signals():
        if request["action"] != "update":
            return _run_job(request, directory)
        from .features import update_groups

        game = Game.from_dict(request["game"])
        preferences = request.get("preferences", {})
        groups = update_groups(game, preferences)
        operations = []
        if (game.target / ".optidx-files").exists():
            operations.append(
                (
                    "core setup",
                    {**request, "options": {**request.get("options", {}), "core_only": True}},
                )
            )
        operations.extend(
            (group, {**request, "action": "update_group", "options": {"group": group}})
            for group in groups
        )
        errors, completed, state = [], [], None
        for label, operation in operations:
            try:
                state = _run_job(operation, directory)
                completed.append(label)
            except (JobInterrupted, GameBusy, ManualRecoveryRequired, CorruptRecord):
                # Never continue after cancellation, incomplete recovery or corruption.
                raise
            except Exception as error:
                errors.append(label + ": " + str(error))
                emit("progress", message=errors[-1])
        if errors and not completed:
            raise RuntimeError("; ".join(errors))
        from .inspection import inspect_game

        state = inspect_game(game)
        emit("result", ok=True, state=state, data={"completed": completed, "errors": errors})
        return state


def main():
    parser = argparse.ArgumentParser()
    # The request normally arrives on stdin: profiles may hold secret environment
    # values, and command lines are readable by other local users via /proc.
    parser.add_argument("--request", help="JSON request (default: read from stdin)")
    parser.add_argument("--data-dir")
    arguments = parser.parse_args()
    try:
        request = arguments.request if arguments.request is not None else sys.stdin.read()
        run_job(json.loads(request), arguments.data_dir)
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        emit(
            "result",
            ok=False,
            error=str(error),
            error_type=type(error).__name__,
            cancelled=isinstance(error, JobInterrupted),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
