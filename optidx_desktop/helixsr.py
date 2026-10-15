"""Remove only managed HelixSR assets and restore direct AMD upscaling."""
import hashlib
import os
import ntpath
from pathlib import Path, PurePosixPath

from .assets import atomic_bytes
from .backend import load_backend
from .backups import baseline_path
from .inspection import contained
from .storage import read_json


def _originals(game, repository, paths):
    baseline = read_json(baseline_path(game, repository), {})
    if not baseline:
        return {}
    folder = Path(baseline["snapshot"])
    saved = read_json(folder / "snapshot.json", {})
    if saved.get("target") != str(game.target.resolve()):
        raise ValueError("Backup belongs to a different game folder.")
    originals = {}
    for record in saved["files"]:
        if record["path"] not in paths or record["managed"]:
            continue
        data = contained(folder / "files", record["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Backup checksum mismatch: " + record["path"])
        originals[record["path"]] = (data, record["mode"])
    return originals


def remove(game, repository, preferences):
    module = load_backend()
    previous = Path.cwd()
    try:
        os.chdir(game.target)
        owners = module.owned_components()
    finally:
        os.chdir(previous)
    paths = owners["helixsr"]
    if not paths:
        raise ValueError("No OptiDX-managed HelixSR files were found. Unmanaged installations must be removed manually.")
    for relative in paths:
        parts = PurePosixPath(relative).parts
        if len(parts) < 3 or tuple(part.casefold() for part in parts[:2]) != ("optiscaler", "helixsr"):
            raise ValueError("Unexpected HelixSR-owned path: " + relative)
        path = contained(game.target, relative)
        if path.is_symlink():
            raise ValueError("Refusing to remove a managed symlink: " + relative)
    originals = _originals(game, repository, paths)
    ini = contained(game.target, "OptiScaler.ini")
    changes = {}
    if ini.is_file():
        text = ini.read_text(encoding="utf-8-sig")
        values = module.hdr_ini_values(text, "Libraries")
        def helix_path(value):
            value = ntpath.normpath(value.strip().strip('"').replace("/", "\\"))
            if value.startswith('\\\\?\\'):
                value = value[4:]
            candidates = {value.casefold()}
            drive, tail = ntpath.splitdrive(value)
            if drive.casefold() == 'z:':
                candidates.add(str(Path('/' + tail.lstrip('\\').replace('\\', '/')).resolve()).casefold())
            elif len(drive) == 2 and drive[1] == ':':
                prefix = Path(preferences.get('prefix') or game.prefix or '.')
                for base in (prefix, prefix / 'pfx'):
                    mapping = base / 'dosdevices' / drive.lower()
                    if mapping.is_dir():
                        candidates.add(str((mapping / tail.lstrip('\\').replace('\\', '/')).resolve()).casefold())
            for relative in paths:
                if not relative.lower().endswith(".dll"):
                    continue
                expected = {ntpath.normpath(relative).casefold(),
                            ntpath.normpath(module.proton_path(game.target / relative)).casefold(),
                            str((game.target / relative).resolve()).casefold()}
                if candidates & expected:
                    return True
            return False
        for key in ("FfxDx12Path", "FfxDx12SRPath", "NvngxPath", "NvngxDlssPath"):
            if helix_path(values.get(key.casefold(), "")):
                changes[key] = "auto"
        if "FfxDx12SRPath" in changes:
            lossy = contained(game.target, "OptiScaler/" + module.AMD_DLL_NAME)
            if not lossy.is_file():
                raise ValueError("Install the Cyboman lossy FSR component before restoring direct FSR4 routing.")
            changes["FfxDx12SRPath"] = module.proton_path(lossy)
        if changes:
            text = module.set_ini_values(text, "Libraries", changes)
    if ini.is_file() and changes:
        atomic_bytes(ini, text.encode("utf-8"), ini.stat().st_mode & 0o777)
    removed = []
    for relative in sorted(paths):
        path = contained(game.target, relative)
        if path.is_file():
            path.unlink()
            removed.append(relative)
        if relative in originals:
            data, mode = originals[relative]
            atomic_bytes(path, data, mode)
    owners["helixsr"] = set()
    recorded = read_json(game.target / module.COMPONENT_STATE, {})
    selected = set(recorded.get("selected", [key for key, files in owners.items() if files]))
    module.COMPONENT_SELECTION = selected - {"helixsr"}
    try:
        os.chdir(game.target)
        module.write_component_manifest(owners)
    finally:
        os.chdir(previous)
    return {"removed": removed, "restored": sorted(originals), "routing": changes}
