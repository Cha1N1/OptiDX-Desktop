"""Verify moved installations before rebinding their marker and recovery scopes."""

import base64
import json
from pathlib import Path
import time

from . import assets
from .downloads import sha
from .inspection import contained, manifest_paths
from .storage import atomic_json, read_json


def relocate_installation(game, repository):
    target = game.target.resolve()
    marker = target / ".optidx-installed"
    if not marker.is_file():
        return False
    if marker.is_symlink():
        raise ValueError("Install marker must not be a symlink")
    before = marker.read_bytes()
    lines = before.decode("utf-8").splitlines(keepends=True)
    if not lines or Path(lines[0].strip()).resolve() == target:
        return False
    old = Path(lines[0].strip())
    if not old.is_absolute() or old.exists() or old.is_symlink():
        raise ValueError(
            "Previous install folder still exists or marker is invalid; automatic relocation is unsafe"
        )
    relative = target.relative_to(Path(game.root).resolve())
    if relative.parts and old.parts[-len(relative.parts) :] != relative.parts:
        raise ValueError(
            "Executable layout changed as well as the game path; automatic relocation cannot verify the old game root"
        )
    old_root = old
    for part in relative.parts:
        old_root = old_root.parent
    if old_root == Path(old_root.anchor):
        raise ValueError("Refusing an ambiguous previous game root")

    # A marker alone does not establish ownership. Verify the moved DLLs and
    # recovery blobs; configuration files may legitimately be saved by the game.
    anchors = 0
    for scope in {target, Path(game.root).resolve()}:
        ledger_path = scope / assets.LEDGER
        if ledger_path.is_symlink():
            raise ValueError("Moved ownership record must not be a symlink")
        for group in assets.state(scope)["groups"].values():
            for name, record in group["files"].items():
                path = contained(scope, name)
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Moved managed file is missing or linked: " + name)
                if path.suffix.lower() in {".dll", ".asi", ".addon", ".addon32", ".addon64"}:
                    if sha(path.read_bytes()) != record["sha256"]:
                        raise ValueError("Cannot verify moved managed binary: " + name)
                    anchors += 1
                original = record.get("original")
                if original:
                    if original.get("blob"):
                        blob = contained(scope, assets.ORIGINALS + "/" + original["blob"])
                        if blob.is_symlink():
                            raise ValueError("Moved original-file backup must not be linked")
                        data = blob.read_bytes()
                    else:
                        data = base64.b64decode(original["data"], validate=True)
                    if sha(data) != original["sha256"]:
                        raise ValueError("Moved original-file backup checksum mismatch: " + name)
    if not anchors:
        # Older Desktop installs predate the asset ledger, but recorded the
        # independently installed Cyboman DLL's hash and relative ownership.
        paths = set(manifest_paths(target))
        state_path = target / ".optidx-components.json"
        release_path = contained(target, "OptiScaler/.optidx-amd-release.json")
        if state_path.is_symlink() or release_path.is_symlink():
            raise ValueError("Legacy ownership records must not be linked")
        components = read_json(state_path, {})
        release = read_json(release_path, {})
        dll_name = "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
        owned = components.get("files", {}).get("amd_fsr", [])
        if dll_name in paths and dll_name in owned and release.get("sha256"):
            for name in paths:
                path = contained(target, name)
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Legacy managed file is missing or linked: " + name)
            if sha(contained(target, dll_name).read_bytes()) != release["sha256"]:
                raise ValueError("Cannot verify moved legacy Cyboman DLL")
            anchors += 1
    if not anchors:
        raise ValueError(
            "No verified managed binaries establish ownership of the moved installation"
        )

    base = repository.directory / "backups" / game.id
    from .backups import baseline_path

    pointer = read_json(baseline_path(game, repository), {})
    records = set(base.glob("*/snapshot.json")) | set(base.rglob("snapshot.json"))
    if pointer:
        folder = Path(pointer["snapshot"])
        folder.resolve().relative_to(base.resolve())
        records.add(folder / "snapshot.json")
    changes = []
    for record_path in sorted(records):
        record_path.resolve().relative_to(base.resolve())
        if record_path.is_symlink() or record_path.parent.is_symlink():
            raise ValueError("Relocation refuses linked recovery records")
        saved = read_json(record_path, {})
        root = saved.get("target")
        if (
            pointer
            and record_path == Path(pointer["snapshot"]) / "snapshot.json"
            and root not in {str(old), str(old_root), str(target), str(Path(game.root).resolve())}
        ):
            raise ValueError("Baseline does not belong to this moved installation")
        replacement = {str(old): str(target), str(old_root): str(Path(game.root).resolve())}.get(
            root
        )
        if replacement is None or replacement == root:
            continue
        # Rebind metadata only after verifying every retained recovery payload.
        if not isinstance(saved.get("files"), list):
            raise ValueError("Invalid moved recovery file list")
        for item in saved["files"]:
            source = contained(record_path.parent / "files", item["path"])
            if source.is_symlink() or sha(source.read_bytes()) != item["sha256"]:
                raise ValueError("Moved installation recovery checksum mismatch: " + item["path"])
        after = (json.dumps({**saved, "target": replacement}, indent=2) + "\n").encode()
        changes.append(
            (record_path, record_path.read_bytes(), after, record_path.stat().st_mode & 0o777)
        )
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    after_marker = (str(target) + newline + "".join(lines[1:])).encode()
    # Publish the marker last. An interrupted migration still has the old marker
    # and can finish rebinding any remaining old scopes on the next attempt.
    changes.append((marker, before, after_marker, marker.stat().st_mode & 0o777))
    journal = base / "relocations" / (str(time.time_ns()) + ".json")
    record = {
        "old_target": str(old),
        "target": str(target),
        "status": "prepared",
        "records": [
            {"path": str(path), "before": base64.b64encode(data).decode(), "mode": mode}
            for path, data, after, mode in changes
        ],
    }
    atomic_json(journal, record)
    try:
        for path, data, after, mode in changes:
            assets.atomic_bytes(path, after, mode)
    except Exception:
        # Originals remain in the durable journal even if rollback itself fails.
        for path, data, after, mode in reversed(changes):
            assets.atomic_bytes(path, data, mode)
        atomic_json(journal, {**record, "status": "rolled_back"})
        raise
    atomic_json(journal, {**record, "status": "complete"})
    return True
