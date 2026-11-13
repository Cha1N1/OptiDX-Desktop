"""Recover overwritten local files in addition to OptiDX's manifest-based removal."""

import hashlib
import os
from pathlib import Path
import shutil
import time

from .inspection import contained, manifest_paths
from .storage import atomic_json, read_json

PROXIES = {
    "dxgi.dll",
    "d3d12.dll",
    "d3d11.dll",
    "d3d9.dll",
    "winmm.dll",
    "version.dll",
    "dbghelp.dll",
    "wininet.dll",
    "winhttp.dll",
    "optiscaler.asi",
    "d3dcompiler_47.dll",
    "reshade64.dll",
    "reshade32.dll",
    "d3d12-reshade64.dll",
    "optiscaler.ini",
    "reshade.ini",
    "reshadepreset.ini",
    ".optidx-installed",
    ".optidx-files",
    ".optidx-ue-hdr.json",
}
PROXIES.update(
    {
        "opengl32.dll",
        "dinput8.dll",
        ".optidx-components.json",
        ".optidx-desktop-assets.json",
        ".optidx-desktop-versions.json",
        ".optidx-desktop-settings.json",
        ".optidx-desktop-loader.json",
        ".optidx-desktop-framegen.json",
        "relimiter.ini",
        "displaycommander.ini",
        "dxvk.conf",
    }
)


def relevant_files(root):
    root = Path(root)
    paths = set(manifest_paths(root))
    from .assets import state, ORIGINALS

    for group in state(root)["groups"].values():
        paths.update(group["files"])
    for p in root.iterdir():
        if p.is_file() and (
            p.name.lower() in PROXIES or p.name.lower().endswith((".addon64", ".addon32", ".addon"))
        ):
            paths.add(p.name)
    for p in (root / ORIGINALS).glob("*"):
        if p.is_file():
            paths.add(str(p.relative_to(root)))
    for p in (root / "OptiScaler").rglob("*"):
        if p.is_file():
            paths.add(str(p.relative_to(root)))
    from .catalog import DLSS_FILES, STREAMLINE_FILES

    known = set(DLSS_FILES.values()) | set(STREAMLINE_FILES)
    from .discovery import walk_files

    for p in walk_files(root):
        if p.name.lower() in known and not p.is_symlink():
            paths.add(str(p.relative_to(root)))
    return sorted(paths)


def snapshot(game, repository):
    root = game.target.resolve()
    managed = set(manifest_paths(root))
    from .assets import state

    for group in state(root)["groups"].values():
        managed.update(group["files"])
    folder = repository.directory / "backups" / game.id / str(time.time_ns())
    folder.mkdir(parents=True)
    records = []
    for relative in relevant_files(root):
        source = contained(root, relative)
        if not source.is_file():
            continue
        if source.is_symlink():
            raise ValueError(
                f"Replace the symlink with a regular file before managing {source.name}."
            )
        destination = folder / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        objects = repository.directory / "backups" / game.id / ".objects"
        objects.mkdir(parents=True, exist_ok=True)
        blob = objects / digest
        if blob.exists():
            if blob.is_symlink() or hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                raise ValueError("Backup object checksum mismatch")
        else:
            from .assets import atomic_bytes

            atomic_bytes(blob, data, 0o600)
        os.link(blob, destination)
        from .storage import sync_directory

        sync_directory(destination.parent)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise OSError(f"Backup verification failed: {relative}")
        records.append(
            {
                "path": relative,
                "sha256": digest,
                "mode": source.stat().st_mode & 0o777,
                "managed": relative in managed or relative.startswith(".optidx-"),
            }
        )
    atomic_json(folder / "snapshot.json", {"target": str(root), "files": records})
    return folder


def baseline_path(game, repository):
    base = repository.directory / "backups" / game.id
    target = str(game.target.resolve())
    scoped = base / "targets" / hashlib.sha256(target.encode()).hexdigest() / "baseline.json"
    if scoped.exists():
        return scoped
    # Verified relocation can rebind snapshot scopes without renaming pointers.
    for pointer in sorted(base.glob("targets/*/baseline.json")):
        value = read_json(pointer, {})
        if (
            value
            and read_json(Path(value["snapshot"]) / "snapshot.json", {}).get("target") == target
        ):
            return pointer
    legacy = base / "baseline.json"
    value = read_json(legacy, {})
    if value:
        saved = read_json(Path(value["snapshot"]) / "snapshot.json", {})
        if saved.get("target") != target:
            return scoped
    return legacy


def remember_baseline(game, repository, folder):
    pointer = baseline_path(game, repository)
    if not pointer.exists():
        atomic_json(pointer, {"snapshot": str(folder)})


def restore_originals(game, repository):
    pointer = baseline_path(game, repository)
    baseline = read_json(pointer, {})
    if not baseline:
        return
    folder = Path(baseline["snapshot"])
    saved = read_json(folder / "snapshot.json", {})
    if saved.get("target") != str(game.target.resolve()):
        raise ValueError("Backup belongs to a different game folder.")
    # Never reintroduce an earlier OptiDX-managed installation after uninstall.
    for record in saved["files"]:
        if record["managed"]:
            continue
        source = contained(folder / "files", record["path"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Backup checksum mismatch: {record['path']}")
        destination = contained(game.target, record["path"])
        if destination.is_file() and destination.suffix.lower() == ".ini":
            # Managed configuration keys are undone by their journals. Keep
            # subsequent unrelated edits instead of replacing the whole INI.
            continue
        from .assets import atomic_bytes

        atomic_bytes(destination, source.read_bytes(), record["mode"])
    pointer.unlink()


def rollback_snapshot(root, folder):
    """Restore the operation snapshot and remove newly tracked deployment files."""
    from .assets import atomic_bytes

    saved = read_json(Path(folder) / "snapshot.json", {})
    if saved.get("target") != str(Path(root).resolve()):
        raise ValueError("Rollback snapshot belongs to another folder")
    records = {r["path"]: r for r in saved["files"]}
    sources = {}
    for name, record in records.items():
        source = contained(Path(folder) / "files", name)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Rollback snapshot checksum mismatch: " + name)
        sources[name] = data
    # A failed backend may have written a malformed manifest; recover known files
    # without accepting unsafe entries from it.
    try:
        current = relevant_files(root)
    except ValueError:
        current = [
            p.name for p in Path(root).iterdir() if p.is_file() and p.name.lower() in PROXIES
        ]
    # A payload can replace a previously untracked support file that was not in
    # the broad pre-operation snapshot. Its new asset record retains the original.
    # Restore those originals before deleting the new ledger and backup blobs.
    from .assets import state, restore_file, LEDGER

    previous_assets = read_json(Path(folder) / "files" / LEDGER, {"groups": {}})
    previously_owned = {
        name for group in previous_assets["groups"].values() for name in group["files"]
    }
    restored = set()
    try:
        current_groups = state(root)["groups"]
    except ValueError:
        current_groups = {}
    for group in current_groups.values():
        for name, record in group["files"].items():
            if name not in records and name not in previously_owned and record.get("original"):
                restore_file(contained(root, name), record, root)
                restored.add(name)
    for name in set(current) - set(records) - restored:
        path = contained(root, name)
        if path.is_file() and not path.is_symlink():
            path.unlink()
    for name, record in records.items():
        atomic_bytes(contained(root, name), sources[name], record["mode"])


def root_snapshot(game, repository):
    """DLL swaps can target engine subfolders outside the executable directory."""
    if game.target.resolve() == Path(game.root).resolve():
        return None
    from dataclasses import replace

    return snapshot(replace(game, executable=""), repository)


def external_config_snapshot(game, preferences):
    """Remember existing UE configuration before the backend's journaled edit."""
    from .backend import load_backend, configure_environment, backend_scope

    paths = {
        Path(r["path"]) for r in read_json(game.target / ".optidx-ue-hdr.json", {}).get("files", [])
    }
    if preferences.get("config_dir"):
        paths.add(Path(preferences["config_dir"]) / "Engine.ini")
    module = load_backend()
    with backend_scope():
        configure_environment(game, preferences)
        state = read_json(game.target / ".optidx-ue-hdr.json", {})
        path = module.resolve_ue_hdr_config(game.target, state)
        if path:
            paths.add(Path(path))
    return {
        str(path.resolve()): (
            (path.read_bytes(), path.stat().st_mode & 0o777) if path.is_file() else None
        )
        for path in paths
    }


def rollback_external_config(game, before):
    import base64
    from .assets import atomic_bytes

    for record in read_json(game.target / ".optidx-ue-hdr.json", {}).get("files", []):
        name = str(Path(record["path"]).resolve())
        if name not in before:
            before[name] = (
                (base64.b64decode(record["before"]), record["mode"]) if record["existed"] else None
            )
    for name, value in before.items():
        path = Path(name)
        if value is None:
            path.unlink(missing_ok=True)
        else:
            atomic_bytes(path, *value)


def verify_snapshot(folder, game):
    """Validate a retained snapshot in this game's root or executable scope."""
    folder = Path(folder)
    saved = read_json(folder / "snapshot.json", {})
    target = Path(saved.get("target", "")).resolve()
    if target not in {game.target.resolve(), Path(game.root).resolve()}:
        raise ValueError("Backup belongs to a different game folder")
    records = saved.get("files")
    if not isinstance(records, list):
        raise ValueError("Invalid backup file list")
    recorded = {record["path"] for record in records}
    from .assets import state

    currently_owned = set(manifest_paths(target))
    for group in state(target)["groups"].values():
        currently_owned.update(group["files"])
    # A retained newer journal would describe files from a different setup.
    # Require explicit component removal instead of silently losing its undo data.
    journals = {
        ".optidx-files",
        ".optidx-components.json",
        ".optidx-desktop-assets.json",
        ".optidx-desktop-versions.json",
        ".optidx-desktop-settings.json",
        ".optidx-desktop-loader.json",
        ".optidx-desktop-framegen.json",
        ".optidx-ue-hdr.json",
    }
    currently_owned.update(name for name in journals if (target / name).is_file())
    orphaned = currently_owned - recorded
    if orphaned:
        raise ValueError(
            "Restore would discard ownership of newer managed files. Remove their managed components first: "
            + ", ".join(sorted(orphaned))
        )
    seen = set()
    for record in records:
        name = record["path"]
        if name.casefold() in seen:
            raise ValueError("Duplicate backup filename: " + name)
        seen.add(name.casefold())
        source = contained(folder / "files", name)
        destination = contained(target, name)
        if source.is_symlink() or destination.is_symlink():
            raise ValueError("Backup restore refuses symlinks: " + name)
        if hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Backup checksum mismatch: " + name)
        # Avoid creating a second Windows spelling beside a later user file.
        current = target
        for part in Path(name).parts:
            if current.is_symlink():
                raise ValueError("Restore refuses linked folders: " + name)
            if current.is_dir() and any(
                child.name.casefold() == part.casefold() and child.name != part
                for child in current.iterdir()
            ):
                raise ValueError("Existing path uses different capitalization: " + name)
            current = current / part
        if destination.exists() and not destination.is_file():
            raise ValueError("Restore refuses a directory: " + name)
    return saved


def restore_snapshot_files(folder, game):
    """Restore only verified recorded files; retain newer unrecorded files."""
    from .assets import atomic_bytes

    saved = verify_snapshot(folder, game)
    for record in saved["files"]:
        atomic_bytes(
            contained(saved["target"], record["path"]),
            contained(Path(folder) / "files", record["path"]).read_bytes(),
            record["mode"],
        )
    return saved


def compact_baseline(game, repository, operation_folder=None):
    """Retain only verified foreign originals; never retain a whole setup for baseline."""
    pointer = baseline_path(game, repository)
    value = read_json(pointer, {})
    if not value:
        return
    source_folder = Path(value["snapshot"])
    saved = read_json(source_folder / "snapshot.json", {})
    if saved.get("target") != str(game.target.resolve()):
        raise ValueError("Baseline belongs to a different game folder")
    destination = pointer.parent / "originals"
    already_compact = source_folder.resolve() == destination.resolve()
    if already_compact and operation_folder is None:
        return
    candidates = {r["path"]: (r, source_folder) for r in saved["files"]}
    if operation_folder is not None:
        operation = read_json(Path(operation_folder) / "snapshot.json", {})
        if operation.get("target") != saved["target"]:
            raise ValueError("Operation snapshot belongs to a different game folder")
        for record in operation["files"]:
            candidates.setdefault(record["path"], (record, Path(operation_folder)))
    from .assets import state

    groups = state(game.target)["groups"]
    owned = set(manifest_paths(game.target))
    asset_originals = {}
    for group in groups.values():
        owned.update(group["files"])
        asset_originals.update(
            {name: record.get("original") for name, record in group["files"].items()}
        )
    records = []
    for record, source in candidates.values():
        if record["managed"]:
            continue
        name = record["path"]
        if already_compact and source == source_folder:
            records.append(record)
            continue
        original = asset_originals.get(name)
        if original and original.get("sha256") == record["sha256"]:
            # Verify the alternate recovery copy before dropping the snapshot copy.
            import base64
            from .assets import ORIGINALS

            data = (
                contained(game.target, ORIGINALS + "/" + original["blob"]).read_bytes()
                if original.get("blob")
                else base64.b64decode(original["data"], validate=True)
            )
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Original recovery blob checksum mismatch: " + name)
            continue
        current = contained(game.target, name)
        changed = (
            not current.is_file()
            or hashlib.sha256(current.read_bytes()).hexdigest() != record["sha256"]
        )
        if changed or name in owned:
            records.append(record)
    for record in records:
        source = contained(candidates[record["path"]][1] / "files", record["path"])
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Baseline checksum mismatch: " + record["path"])
        from .assets import atomic_bytes

        atomic_bytes(contained(destination / "files", record["path"]), data, record["mode"])
    atomic_json(destination / "snapshot.json", {**saved, "files": records, "purpose": "originals"})
    atomic_json(pointer, {"snapshot": str(destination)})


def finish_snapshots(game, repository, folders, status="complete"):
    """Discard rollback copies by default; retain bounded history only on opt-in."""
    for folder in filter(None, folders):
        path = Path(folder) / "snapshot.json"
        saved = read_json(path, {})
        atomic_json(path, {**saved, "operation_status": status})
    if status == "manual_recovery":
        return
    if status == "complete":
        target_folder = next(
            (
                folder
                for folder in folders
                if folder
                and read_json(Path(folder) / "snapshot.json", {}).get("target")
                == str(game.target.resolve())
            ),
            None,
        )
        compact_baseline(game, repository, target_folder)
    settings = read_json(repository.directory / "settings.json", {})
    limit = (
        max(1, min(50, int(settings.get("backup_limit", 3))))
        if settings.get("retain_backups", False)
        else 0
    )
    if limit:
        prune_snapshots(game, repository, limit)
    else:
        protected = read_json(baseline_path(game, repository), {}).get("snapshot")
        protected = Path(protected).resolve() if protected else None
        for folder in filter(None, folders):
            if Path(folder).resolve() != protected:
                shutil.rmtree(folder)
    if status == "complete" and not baseline_path(game, repository).exists():
        originals = baseline_path(game, repository).parent / "originals"
        if originals.is_dir() and not originals.is_symlink():
            shutil.rmtree(originals)

    collect_backup_objects(repository, game)


def prune_snapshots(game, repository, limit=0):
    """Delete completed history only; baseline and interrupted operations survive."""
    base = repository.directory / "backups" / game.id
    protected = {
        Path(value["snapshot"]).resolve()
        for pointer in [base / "baseline.json", *base.glob("targets/*/baseline.json")]
        if (value := read_json(pointer, {})).get("snapshot")
    }
    recovery_paths = {
        str(Path(path).resolve())
        for item in read_json(repository.directory / "job-history.json", [])
        if item.get("recovery_state") in {"manual", "interrupted"}
        or item.get("result", "").startswith(("Running", "Interrupted"))
        or "manual recovery" in item.get("result", "")  # records before recovery_state
        for path in item.get("backups", [])
    }
    candidates = []
    for folder in base.iterdir() if base.is_dir() else []:
        if folder.is_symlink() or not folder.is_dir() or not folder.name.isdigit():
            continue
        saved = read_json(folder / "snapshot.json", {})
        if (
            not saved
            or folder.resolve() in protected
            or (not saved.get("operation_status") and str(folder.resolve()) in recovery_paths)
        ):
            continue
        if saved.get("operation_status") in {"active", "manual_recovery"}:
            continue
        candidates.append(folder)
    removed = 0
    for folder in sorted(candidates, key=lambda p: int(p.name), reverse=True)[limit:]:
        shutil.rmtree(folder)
        removed += 1
    collect_backup_objects(repository, game)
    return removed


def cleanup_completed_snapshots(repository):
    """Explicit app-wide cleanup with the same process locks used by jobs."""
    import fcntl
    from contextlib import ExitStack

    with ExitStack() as stack:
        locks = repository.directory / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        games = repository.games()
        paths = set(locks.glob("*.lock"))
        paths.update(
            locks / (hashlib.sha256(str(Path(game.root).resolve()).encode()).hexdigest() + ".lock")
            for game in games
        )
        for path in sorted(paths):
            lock = stack.enter_context(path.open("a"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("A job is running. Finish it before cleaning snapshots.")
        removed = 0
        for game in games:
            compact_baseline(game, repository)
            removed += prune_snapshots(game, repository, 0)
        collect_backup_objects(repository)
    return removed


def collect_backup_objects(repository, game=None):
    roots = (
        [repository.directory / "backups" / game.id / ".objects"]
        if game
        else (repository.directory / "backups").glob("*/.objects")
    )
    for root in roots:
        for blob in root.glob("*"):
            if blob.is_file() and not blob.is_symlink() and blob.stat().st_nlink == 1:
                blob.unlink()
