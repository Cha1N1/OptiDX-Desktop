"""Optional frame-generation tools for upstream OptiScaler.

These replace what the retired Cha1N1/OptiScaler fork bundled (MFGUnlocker.asi,
XeFGUnlock.asi). Each tool is an independent optional install recorded in the
Desktop asset ledger as ``extra:<key>``:

* MFG Unlocker: an OptiScaler ASI plugin in ``OptiScaler/plugins``.
* XeMFG XMX, dlssg-to-xefg and ANR FG: custom DLSSG (FG Nvngx replacement)
  providers in ``OptiScaler/custom/<name>/dlssg``, the layout upstream
  OptiScaler's CustomProviders loader scans.

Only provider trees are copied; bundled installer scripts and packages that ship
their own OptiScaler build are never used.
"""

from pathlib import Path, PurePosixPath

from . import assets
from .catalog import FRAMEGEN_TOOLS as TOOLS
from .downloads import archive_files, binary_member
from .inspection import contained, inspect_game
from .storage import atomic_json, read_json

JOURNAL = ".optidx-desktop-framegen.json"
MFG_TARGET = "OptiScaler/plugins/MFGUnlocker.asi"
# Kept in user hands after the first install: a refresh keeps local edits.
CONFIG_SUFFIXES = (".ini",)
PROVIDER_SETTINGS = ("FGInput", "FGNvngxReplacement")

PROVIDER_FOLDERS = {
    item["folder"].casefold(): key for key, item in TOOLS.items() if item["kind"] == "fg_provider"
}


def supports_custom_framegen(data):
    """Upstream CustomProviders diagnostic for FGNvngxReplacement folders."""
    return b"isn't a replacement or a folder with dlssg in" in data


def installed_optiscaler(game):
    """Bytes of the installed OptiScaler proxy DLL that has the custom FG loader."""
    if not (game.target / "OptiScaler.ini").is_file() or not inspect_game(game)["components"].get(
        "OptiScaler"
    ):
        raise ValueError("Install OptiScaler before this frame-generation tool")
    for name in (
        "dxgi.dll",
        "winmm.dll",
        "version.dll",
        "d3d12.dll",
        "d3d11.dll",
        "winhttp.dll",
        "dbghelp.dll",
        "wininet.dll",
        "dinput8.dll",
        "OptiScaler.dll",
    ):
        path = contained(game.target, name)
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if supports_custom_framegen(data):
                return data
    return b""


def _single(name, data):
    return {PurePosixPath(name).name: data}


def _files(path, metadata):
    """Archive members, or one direct DLL/ASI file."""
    data = Path(path).read_bytes()
    if data[:2] == b"MZ":
        from urllib.parse import unquote, urlparse

        name = Path(path).name
        if not name.lower().endswith((".dll", ".asi")):
            name = Path(unquote(urlparse(metadata.get("url", "")).path)).name
        return _single(name, data)
    return archive_files(path)


def mfg_unlocker_files(files):
    names = [
        n
        for n in files
        if PurePosixPath(n).name.casefold() in {"mfgunlocker.dll", "mfgunlocker.asi"}
    ]
    if len(names) != 1:
        raise ValueError("Package must contain exactly one MFGUnlocker.dll")
    data = binary_member(files, PurePosixPath(names[0]).name, 64)
    return {MFG_TARGET: data}


def _dlssg_base(name):
    """The archive folder named dlssg that contains this member, if any."""
    parts = PurePosixPath(name).parts
    folders = [part.casefold() for part in parts[:-1]]
    return PurePosixPath(*parts[: folders.index("dlssg") + 1]) if "dlssg" in folders else None


def provider_files(files, folder):
    """Map one provider tree to OptiScaler/custom/<folder>/dlssg/."""
    bases = {base for base in map(_dlssg_base, files) if base is not None}
    if len(bases) > 1:
        raise ValueError("Package contains several dlssg provider folders")
    prefix = "OptiScaler/custom/" + folder + "/dlssg/"
    if bases:
        base = bases.pop()
        result = {
            prefix + PurePosixPath(n).relative_to(base).as_posix(): data
            for n, data in files.items()
            if PurePosixPath(n).is_relative_to(base)
        }
    else:
        # A bare provider DLL (dlssg-to-xefg): take it and its licence only.
        dlls = [n for n in files if n.lower().endswith(".dll")]
        if len(dlls) != 1:
            raise ValueError("Package must contain exactly one provider DLL")
        parent = PurePosixPath(dlls[0]).parent
        result = {prefix + PurePosixPath(dlls[0]).name: files[dlls[0]]}
        for n, data in files.items():
            if PurePosixPath(n).parent == parent and PurePosixPath(n).stem.casefold() in {
                "license",
                "licence",
                "notice",
            }:
                result[prefix + PurePosixPath(n).name] = data
    dlls = [n for n in result if PurePosixPath(n).parent == PurePosixPath(prefix.rstrip("/"))]
    dlls = [n for n in dlls if n.lower().endswith(".dll")]
    standard = [n for n in dlls if PurePosixPath(n).name.casefold() == "nvngx_dlssg.dll"]
    main = standard or dlls
    if len(main) != 1:
        raise ValueError("Package must contain one provider DLL in its dlssg folder")
    from .upscalers import exports

    data = binary_member({main[0]: result[main[0]]}, PurePosixPath(main[0]).name, 64)
    if not any(name.startswith("NVSDK_NGX_D3D12_") for name in exports(data)):
        raise ValueError("Provider DLL does not export the nvngx_dlssg D3D12 interface")
    return result


def keep_local_configs(game, group, files):
    """Retain user-edited provider configuration (for example nr_fg.ini)."""
    previous = assets.state(game.target)["groups"].get(group, {}).get("files", {})
    for name in previous:
        if name in files and name.lower().endswith(CONFIG_SUFFIXES):
            path = contained(game.target, name)
            if path.is_file() and not path.is_symlink():
                files[name] = path.read_bytes()
                assets.accept_config_edit(game.target, name)
    return files


def _ini(game):
    from .backend import load_backend

    module = load_backend()
    ini = game.target / "OptiScaler.ini"
    data = ini.read_bytes()
    encoding = module.hdr_ini_encoding(data)
    return module, ini, data.decode(encoding), encoding


def select_provider(game, key):
    """Point OptiScaler's FG Nvngx replacement at a newly installed provider."""
    module, ini, text, encoding = _ini(game)
    current = module.hdr_ini_values(text, "FrameGen")
    values = {"FGInput": "nvngxfg", "FGNvngxReplacement": TOOLS[key]["folder"]}
    journal = read_json(game.target / JOURNAL, {})
    journal["extra:" + key] = {
        name: {"original": current.get(name.casefold()), "applied": value}
        for name, value in values.items()
    }
    atomic_json(game.target / JOURNAL, journal)
    assets.atomic_bytes(
        ini,
        module.edit_hdr_ini(text, "FrameGen", values).encode(encoding),
        ini.stat().st_mode & 0o777,
    )
    assets.accept_config_edit(game.target, "OptiScaler.ini")


def restore_provider(game, group):
    """Undo a provider's INI choice only while it is still the active provider.

    A removed provider that is no longer active hands its own original values
    to the provider that was installed on top of it, so later removals never
    point OptiScaler at a provider folder that is gone.
    """
    path = game.target / JOURNAL
    journal = read_json(path, {})
    record = journal.pop(group, None)
    key = group.split(":", 1)[1]
    if record and key in TOOLS and (game.target / "OptiScaler.ini").is_file():
        module, ini, text, encoding = _ini(game)
        current = module.hdr_ini_values(text, "FrameGen")
        folder = TOOLS[key]["folder"]
        if current.get("fgnvngxreplacement", "").casefold() == folder.casefold():
            changes = {
                name: (
                    "auto"
                    if PROVIDER_FOLDERS.get(str(item["original"] or "").casefold())
                    else item["original"]
                )
                for name, item in record.items()
                if current.get(name.casefold()) == item["applied"]
            }
            assets.atomic_bytes(
                ini,
                module.edit_hdr_ini(text, "FrameGen", changes).encode(encoding),
                ini.stat().st_mode & 0o777,
            )
            assets.accept_config_edit(game.target, "OptiScaler.ini")
        else:
            for other in journal.values():
                replaced = other.get("FGNvngxReplacement", {})
                if str(replaced.get("original") or "").casefold() == folder.casefold():
                    for name, item in record.items():
                        if name in other:
                            other[name]["original"] = item["original"]
    if journal:
        atomic_json(path, journal)
    else:
        path.unlink(missing_ok=True)
    prune_empty(game.target / "OptiScaler/custom", TOOLS.get(key, {}).get("folder"))


def prune_empty(custom, folder):
    """Remove a provider's now empty folders so OptiScaler stops listing it."""
    if not folder:
        return
    top = custom / folder
    if top.is_symlink() or not top.is_dir():
        return
    for directory in sorted(
        (p for p in top.rglob("*") if p.is_dir() and not p.is_symlink()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        if not any(directory.iterdir()):
            directory.rmdir()
    if not any(top.iterdir()):
        top.rmdir()
    if custom.is_dir() and not custom.is_symlink() and not any(custom.iterdir()):
        custom.rmdir()


def deploy(game, repository, key, item, preferences, path, metadata):
    """Install one tool from an already resolved package path."""
    bits = int(preferences.get("bits_override") or inspect_game(game)["bits"] or 64)
    if bits != 64:
        raise ValueError(item["label"] + " requires a 64-bit game")
    optiscaler = installed_optiscaler(game)
    group = "extra:" + key
    fresh = group not in assets.state(game.target)["groups"]
    files = _files(path, metadata)
    if item["kind"] == "mfg_asi":
        prepared = mfg_unlocker_files(files)
    else:
        from .channels import effective_api

        api = effective_api(game, preferences)
        if api not in item["apis"]:
            raise ValueError(item["label"] + " does not support " + api + " games")
        if not supports_custom_framegen(optiscaler):
            raise ValueError(
                "The installed OptiScaler has no custom frame-generation providers. "
                "Update to a current upstream nightly first."
            )
        prepared = keep_local_configs(game, group, provider_files(files, item["folder"]))
    result = assets.deploy(
        game.target,
        group,
        prepared,
        {**metadata, "kind": item["kind"], "label": item["label"]},
        preferences.get("allow_foreign", False),
        # Older fork packages shipped MFGUnlocker.asi as part of OptiScaler.
        transfer_from="backend:optiscaler" if item["kind"] == "mfg_asi" else None,
    )
    from .channels import loader_settings

    if item["kind"] == "mfg_asi":
        loader_settings(game, {"LoadAsiPlugins": "true"})
    elif fresh:
        select_provider(game, key)
    return result
