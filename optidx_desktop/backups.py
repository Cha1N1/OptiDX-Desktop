"""Recover overwritten local files in addition to OptiDX's manifest-based removal."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time

from .inspection import contained, manifest_paths
from .storage import atomic_json, read_json

PROXIES = {"dxgi.dll", "d3d12.dll", "d3d11.dll", "d3d9.dll", "winmm.dll", "version.dll", "dbghelp.dll",
           "wininet.dll", "winhttp.dll", "optiscaler.asi", "d3dcompiler_47.dll", "reshade64.dll",
           "reshade32.dll", "d3d12-reshade64.dll", "optiscaler.ini", "reshade.ini", "reshadepreset.ini",
           ".optidx-installed", ".optidx-files", ".optidx-ue-hdr.json"}
PROXIES.update({"opengl32.dll", "dinput8.dll", ".optidx-components.json", ".optidx-desktop-assets.json",
                ".optidx-desktop-versions.json", ".optidx-desktop-settings.json", ".optidx-desktop-loader.json", "relimiter.ini", "displaycommander.ini", "dxvk.conf"})


def relevant_files(root):
    root = Path(root)
    paths = set(manifest_paths(root))
    from .assets import state, ORIGINALS
    for group in state(root)["groups"].values():
        paths.update(group["files"])
    for p in root.iterdir():
        if p.is_file() and (p.name.lower() in PROXIES or p.name.lower().endswith((".addon64", ".addon32", ".addon"))):
            paths.add(p.name)
    for p in (root / ORIGINALS).glob("*"):
        if p.is_file():
            paths.add(str(p.relative_to(root)))
    for p in (root / "OptiScaler").rglob("*"):
        if p.is_file():
            paths.add(str(p.relative_to(root)))
    from .catalog import DLSS_FILES, STREAMLINE_FILES
    known = set(DLSS_FILES.values()) | set(STREAMLINE_FILES)
    for p in root.rglob("*.dll"):
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
            raise ValueError(f"Replace the symlink with a regular file before managing {source.name}.")
        destination = folder / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise OSError(f"Backup verification failed: {relative}")
        records.append({"path": relative, "sha256": digest, "mode": source.stat().st_mode & 0o777,
                        "managed": relative in managed or relative.startswith(".optidx-")})
    atomic_json(folder / "snapshot.json", {"target": str(root), "files": records})
    return folder


def baseline_path(game, repository):
    return repository.directory / "backups" / game.id / "baseline.json"


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
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(source, temporary)
            os.chmod(temporary, record["mode"])
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    pointer.unlink()


def rollback_snapshot(root, folder):
    """Restore the operation snapshot and remove newly tracked deployment files."""
    from .assets import atomic_bytes
    saved = read_json(Path(folder) / 'snapshot.json', {})
    if saved.get('target') != str(Path(root).resolve()):
        raise ValueError('Rollback snapshot belongs to another folder')
    records = {r['path']: r for r in saved['files']}
    sources = {}
    for name, record in records.items():
        source = contained(Path(folder) / 'files', name)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Rollback snapshot checksum mismatch: ' + name)
        sources[name] = data
    # A failed backend may have written a malformed manifest; recover known files
    # without accepting unsafe entries from it.
    try:
        current = relevant_files(root)
    except ValueError:
        current = [p.name for p in Path(root).iterdir() if p.is_file() and p.name.lower() in PROXIES]
    for name in set(current) - set(records):
        path = contained(root, name)
        if path.is_file() and not path.is_symlink():
            path.unlink()
    for name, record in records.items():
        atomic_bytes(contained(root, name), sources[name], record['mode'])


def root_snapshot(game, repository):
    """DLL swaps can target engine subfolders outside the executable directory."""
    if game.target.resolve() == Path(game.root).resolve():
        return None
    from dataclasses import replace
    return snapshot(replace(game, executable=''), repository)


def external_config_snapshot(game, preferences):
    """Remember existing UE configuration before the backend's journaled edit."""
    from .backend import load_backend, configure_environment
    paths = {Path(r['path']) for r in read_json(game.target / '.optidx-ue-hdr.json', {}).get('files', [])}
    if preferences.get('config_dir'):
        paths.add(Path(preferences['config_dir']) / 'Engine.ini')
    module = load_backend()
    old_env = os.environ.copy()
    try:
        configure_environment(game, preferences)
        state = read_json(game.target / '.optidx-ue-hdr.json', {})
        path = module.resolve_ue_hdr_config(game.target, state)
        if path:
            paths.add(Path(path))
    finally:
        os.environ.clear(); os.environ.update(old_env)
    return {str(path.resolve()): (path.read_bytes(), path.stat().st_mode & 0o777) if path.is_file() else None
            for path in paths}


def rollback_external_config(game, before):
    import base64
    from .assets import atomic_bytes
    for record in read_json(game.target / '.optidx-ue-hdr.json', {}).get('files', []):
        name = str(Path(record['path']).resolve())
        if name not in before:
            before[name] = (base64.b64decode(record['before']), record['mode']) if record['existed'] else None
    for name, value in before.items():
        path = Path(name)
        if value is None:
            path.unlink(missing_ok=True)
        else:
            atomic_bytes(path, *value)


def verify_snapshot(folder, game):
    """Validate a retained snapshot in this game's root or executable scope."""
    folder = Path(folder)
    saved = read_json(folder / 'snapshot.json', {})
    target = Path(saved.get('target', '')).resolve()
    if target not in {game.target.resolve(), Path(game.root).resolve()}:
        raise ValueError('Backup belongs to a different game folder')
    records = saved.get('files')
    if not isinstance(records, list):
        raise ValueError('Invalid backup file list')
    recorded = {record['path'] for record in records}
    from .assets import state
    currently_owned = set(manifest_paths(target))
    for group in state(target)['groups'].values():
        currently_owned.update(group['files'])
    # A retained newer journal would describe files from a different setup.
    # Require explicit component removal instead of silently losing its undo data.
    journals = {'.optidx-files', '.optidx-components.json', '.optidx-desktop-assets.json',
                '.optidx-desktop-versions.json', '.optidx-desktop-settings.json',
                '.optidx-desktop-loader.json', '.optidx-ue-hdr.json'}
    currently_owned.update(name for name in journals if (target / name).is_file())
    orphaned = currently_owned - recorded
    if orphaned:
        raise ValueError('Restore would discard ownership of newer managed files. Remove their managed components first: ' + ', '.join(sorted(orphaned)))
    seen = set()
    for record in records:
        name = record['path']
        if name.casefold() in seen:
            raise ValueError('Duplicate backup filename: ' + name)
        seen.add(name.casefold())
        source = contained(folder / 'files', name)
        destination = contained(target, name)
        if source.is_symlink() or destination.is_symlink():
            raise ValueError('Backup restore refuses symlinks: ' + name)
        if hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Backup checksum mismatch: ' + name)
        # Avoid creating a second Windows spelling beside a later user file.
        current = target
        for part in Path(name).parts:
            if current.is_symlink():
                raise ValueError('Restore refuses linked folders: ' + name)
            if current.is_dir() and any(child.name.casefold() == part.casefold() and child.name != part for child in current.iterdir()):
                raise ValueError('Existing path uses different capitalization: ' + name)
            current = current / part
        if destination.exists() and not destination.is_file():
            raise ValueError('Restore refuses a directory: ' + name)
    return saved


def restore_snapshot_files(folder, game):
    """Restore only verified recorded files; retain newer unrecorded files."""
    from .assets import atomic_bytes
    saved = verify_snapshot(folder, game)
    for record in saved['files']:
        atomic_bytes(contained(saved['target'], record['path']),
                     contained(Path(folder) / 'files', record['path']).read_bytes(), record['mode'])
    return saved
