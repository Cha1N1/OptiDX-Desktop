"""Preflight complete backend payloads using Desktop ownership and PE validation."""

from pathlib import Path, PurePosixPath
import re

from . import assets
from .downloads import archive_files, binary_member
from .inspection import contained, manifest_paths
from .storage import read_json, atomic_json


def reconcile_amd_ownership(root):
    """Migrate the old dual record only when Cyboman provenance verifies bytes."""
    root = Path(root)
    name = "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
    ledger = assets.state(root)
    source = ledger["groups"].get("backend:optiscaler", {}).get("files", {})
    owners = read_json(root / ".optidx-components.json", {}).get("files", {})
    if name not in source or name not in owners.get("amd_fsr", []):
        return
    from .downloads import sha

    release = read_json(root / "OptiScaler/.optidx-amd-release.json", {})
    path = contained(root, name)
    if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != release.get("sha256"):
        raise assets.Conflict("Cannot verify existing Cyboman replacement: " + name)
    target = ledger["groups"].setdefault(
        "backend:amd_fsr", {"files": {}, "metadata": {"kind": "backend", "component": "amd_fsr"}}
    )
    if name in target["files"]:
        raise assets.Conflict("Conflicting AMD ownership records")
    target["files"][name] = {**source.pop(name), "sha256": release["sha256"]}
    atomic_json(root / assets.LEDGER, ledger)


def legacy_core_overlaps(root, prepared, proxy):
    """Adopt only package members beneath explicitly recorded legacy folders.

    Old installers recorded directory names rather than their children. Keep
    originals for these overlaps instead of treating the whole directory as owned.
    """
    if "backend:optiscaler" in assets.state(root)["groups"]:
        return set()
    marker = root / ".optidx-installed"
    if not marker.is_file() or marker.is_symlink() or proxy not in manifest_paths(root):
        return set()
    record = read_json(root / ".optidx-components.json", {})
    owned = record.get("files", {}).get("optiscaler", [])
    if record.get("version") != 1 or not isinstance(owned, list):
        return set()
    directories = set(owned).intersection({"Licenses", "OptiScaler"})
    return {
        name
        for name in prepared
        if any(name.startswith(directory + "/") for directory in directories)
        and not name.casefold().startswith(("optiscaler/custom/", "optiscaler/helixsr/"))
        and contained(root, name).is_file()
    }


def install_optiscaler_payload(root, archive, bits, proxy, extra_copies="", allow_foreign=False):
    root = Path(root)
    reconcile_amd_ownership(root)
    if proxy not in {
        "dxgi.dll",
        "d3d9.dll",
        "opengl32.dll",
        "d3d11.dll",
        "d3d12.dll",
        "winmm.dll",
        "version.dll",
        "winhttp.dll",
        "dbghelp.dll",
        "wininet.dll",
        "dinput8.dll",
    }:
        raise ValueError("Unsupported OptiScaler proxy filename")
    files = archive_files(archive)
    candidates = [
        name for name in files if re.fullmatch(r"optiscaler.*\.dll", PurePosixPath(name).name, re.I)
    ]
    compatible = []
    for name in candidates:
        try:
            binary_member({name: files[name]}, PurePosixPath(name).name, bits)
            compatible.append(name)
        except ValueError:
            continue
    if len(compatible) != 1:
        raise ValueError("Expected exactly one compatible OptiScaler DLL")
    selected = compatible[0]
    amd_owned = assets.state(root)["groups"].get("backend:amd_fsr", {}).get("files", {})
    legacy = read_json(root / ".optidx-components.json", {}).get("files", {})
    protected = {
        path for component, paths in legacy.items() if component != "optiscaler" for path in paths
    }
    parent = PurePosixPath(selected).parent
    prepared = {}
    for name, data in files.items():
        member = PurePosixPath(name)
        try:
            relative = member.relative_to(parent).as_posix()
        except ValueError:
            continue
        if relative in amd_owned or relative in protected:
            continue
        if name in candidates:
            if name != selected:
                continue
            relative = proxy
        elif member.suffix.lower() in {".dll", ".asi", ".exe", ".addon", ".addon32", ".addon64"}:
            binary_member({name: data}, member.name, bits)
        if relative.casefold() == "optiscaler.ini" and (root / "OptiScaler.ini").is_file():
            relative = "OptiScaler.ini"
            data = (root / relative).read_bytes()
        if relative.casefold().startswith(".optidx-") or any(
            part.casefold().startswith(".optidx-") for part in Path(relative).parts
        ):
            raise ValueError("Payload contains reserved ownership metadata")
        if relative in prepared:
            raise ValueError("Ambiguous OptiScaler payload filename")
        prepared[relative] = data
    for extra in filter(None, (name.strip() for name in extra_copies.split(","))):
        contained(root, extra)
        if Path(extra).name != extra or not extra.lower().endswith(".dll"):
            raise ValueError("Invalid extra proxy filename")
        prepared[extra] = files[selected]
    if "OptiScaler.ini" not in prepared and not (root / "OptiScaler.ini").exists():
        prepared["OptiScaler.ini"] = (
            b"[Upscalers]\nDx11Upscaler=auto\nDx12Upscaler=auto\n[FrameGen]\nEnabled=auto\n[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n[Plugins]\nLoadReshade=true\n"
        )
    # Keep previously managed support files when the new archive omits them;
    # their explicit removal remains part of component removal.
    old = assets.state(root)["groups"].get("backend:optiscaler", {})
    for name in old.get("files", {}):
        if name not in prepared and contained(root, name).is_file():
            prepared[name] = contained(root, name).read_bytes()
    # OptiScaler and users legitimately save this mutable configuration. The
    # payload above preserves its exact bytes; accept only this known config,
    # leaving binary integrity checks intact.
    ini = root / "OptiScaler.ini"
    if ini.is_file() and not ini.is_symlink():
        assets.accept_config_edit(root, "OptiScaler.ini")
    assets.deploy(
        root,
        "backend:optiscaler",
        prepared,
        {"kind": "backend", "component": "optiscaler"},
        allow_foreign,
        replace_unmanaged=legacy_core_overlaps(root, prepared, proxy),
    )
    return prepared
