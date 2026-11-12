"""Declarative core components and Desktop-native installers.

This is the single place for component labels, dependencies, exclusivity and
platform limits. Components with a native installer download through the shared
Desktop client, verify Windows PE architecture, and record ownership in the
Desktop asset ledger (with retained originals). The legacy backend manifest is
updated only as a compatibility export via ``module.track``.

Remaining legacy installers (OptiScaler archive download, HelixSR overlay,
RenoDX/Luma matching) are listed in ``LEGACY_HOOKS``; see
docs/ARCHITECTURE_MIGRATION.md for the migration stages.
"""

from dataclasses import dataclass, field
import json
import re
from pathlib import PurePosixPath
import tempfile

from . import assets
from .downloads import Client, archive_files, sha
from .inspection import compatible_binary

AMD_DLL = "amd_fidelityfx_upscaler_dx12.dll"
CYBOMAN_REPOSITORY = "zgauthier2000/fsr4-shader-performance-overrides"
CYBOMAN_ARCHIVE = "fsr4.1.1-cyboman.zip"
DLSS_ENABLER_REPOSITORY = "Cha1N1/dlss-enabler-bleeding-edge"
DLSS_ENABLER_FILE = "OptiScaler/dlss-enabler-headless.dll"
MEMBER_LIMIT = 128 * 1024 * 1024


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    detected: str  # Key in inspection's detected component map.
    requires: tuple = ()
    excludes: tuple = ()
    supports_32bit: bool = False
    legacy_graphics: bool = False  # DX9/OpenGL support through ReShade addons.
    needs_addons: bool = False  # Requires a ReShade channel with addon support.
    ledger_group: str = ""  # Asset ledger group recording this component's files.
    backend_hook: str = ""  # Legacy backend function this component's installer replaces.
    installer: object = field(default=None, compare=False, repr=False)


def _component(**values):
    return Component(**values)


COMPONENTS = {
    item.key: item
    for item in (
        _component(
            key="optiscaler",
            label="OptiScaler",
            detected="OptiScaler",
            ledger_group="backend:optiscaler",
        ),
        _component(
            key="reshade",
            label="ReShade",
            detected="ReShade",
            supports_32bit=True,
            legacy_graphics=True,
            ledger_group="channel:reshade",
        ),
        _component(
            key="renodx",
            label="RenoDX",
            detected="RenoDX",
            requires=("reshade",),
            supports_32bit=True,
            legacy_graphics=True,
            needs_addons=True,
        ),
        _component(
            key="luma",
            label="Luma",
            detected="Luma",
            requires=("reshade",),
            needs_addons=True,
        ),
        _component(
            key="amd_fsr",
            label="Cyboman FSR 4.1.1 · lossy",
            detected="AMD FSR",
            excludes=("helixsr",),
            ledger_group="backend:amd_fsr",
            backend_hook="install_amd_dll",
        ),
        _component(
            key="helixsr",
            label="HelixSR",
            detected="HelixSR",
            requires=("optiscaler",),
            excludes=("amd_fsr",),
        ),
        _component(
            key="dlss_enabler",
            label="DLSS Enabler",
            detected="DLSS Enabler",
            ledger_group="component:dlss_enabler",
            backend_hook="install_dlss_enabler",
        ),
    )
}
COMPONENT_LABELS = {key: item.label for key, item in COMPONENTS.items()}


def ledger_groups():
    """(component, ledger group) pairs used to prune unselected components."""
    return [(key, item.ledger_group) for key, item in COMPONENTS.items() if item.ledger_group]


def selection_problems(
    selected, detected=None, *, bits=64, api="", reshade_channel="", dependencies=True
):
    """Problems with a component selection, in a stable order.

    ``detected`` maps inspection labels to presence, so an existing dependency
    can be reused without being reselected.
    """
    detected = detected or {}
    selected = set(selected)
    problems = []
    for key in COMPONENTS if dependencies else ():
        if key not in selected:
            continue
        item = COMPONENTS[key]
        for dependency in item.requires:
            if dependency not in selected and not detected.get(COMPONENTS[dependency].detected):
                problems.append(
                    f"{item.label} requires selected or installed {COMPONENTS[dependency].label}"
                )
    for key in COMPONENTS:
        for other in COMPONENTS[key].excludes:
            if (
                key in selected
                and other in selected
                and list(COMPONENTS).index(key) < list(COMPONENTS).index(other)
            ):
                problems.append(
                    f"Choose {COMPONENTS[key].label} or {COMPONENTS[other].label}, not both"
                )
    if bits == 32 and any(not COMPONENTS[key].supports_32bit for key in selected):
        problems.append(
            "32-bit games support ReShade/RenoDX; Luma and upscaler components require 64-bit."
        )
    if api in {"Vulkan", "DX8"} and selected:
        problems.append(
            "Use the Linux Vulkan controls or configure a translation layer before DLL deployment."
        )
    if api in {"DX9", "OpenGL"} and any(not COMPONENTS[key].legacy_graphics for key in selected):
        problems.append(
            "Selected upscaler components require DX11/DX12; DX9/OpenGL supports ReShade and "
            "matching RenoDX addons."
        )
    if reshade_channel == "no_addons" and any(COMPONENTS[key].needs_addons for key in selected):
        problems.append("Choose a ReShade channel with addon support for RenoDX/Luma.")
    return problems


@dataclass
class InstallContext:
    """Everything a native installer needs; no backend globals are read."""

    game: object
    repository: object
    preferences: dict
    refresh: bool = False
    allow_foreign: bool = False
    track: object = None  # Legacy manifest export callback.

    @property
    def root(self):
        return self.game.target

    def client(self):
        return Client(self.repository.directory)

    def record(self, paths):
        if self.track:
            for path in paths:
                self.track(path)
        return paths


def _release_asset(client, repository, choose, refresh):
    for release in client.releases(repository, refresh):
        if release.get("draft") or release.get("prerelease"):
            continue
        for asset in release.get("assets", []):
            if choose(asset.get("name", "")) and asset.get("browser_download_url"):
                return release, asset
    return None, None


def _download(client, asset):
    return client.fetch(asset["browser_download_url"], asset.get("digest") or "")


def install_cyboman(context):
    """Install only the lossy DLL from the official Cyboman archive."""
    from .core_payload import reconcile_amd_ownership

    client = context.client()
    release, asset = _release_asset(
        client, CYBOMAN_REPOSITORY, lambda name: name == CYBOMAN_ARCHIVE, context.refresh
    )
    if not asset:
        raise ValueError("No published Cyboman release contains " + CYBOMAN_ARCHIVE)
    files = archive_files(_download(client, asset))
    members = [
        name
        for name in files
        if PurePosixPath(name).parts[-2:] == ("lossy", AMD_DLL)
        and 0 < len(files[name]) <= MEMBER_LIMIT
    ]
    if len(members) != 1:
        raise ValueError("Archive must contain exactly one lossy/" + AMD_DLL)
    data = files[members[0]]
    _require_x64(data, "Cyboman lossy DLL")
    root = context.root
    target = "OptiScaler/" + AMD_DLL
    reconcile_amd_ownership(root)
    assets.deploy(
        root,
        "backend:amd_fsr",
        {target: data},
        {"kind": "backend", "component": "amd_fsr", "version": release.get("tag_name", "")},
        context.allow_foreign,
        transfer_from="backend:optiscaler",
    )
    record = "OptiScaler/.optidx-amd-release.json"
    assets.atomic_bytes(
        root / record,
        (
            json.dumps(
                {
                    "repository": CYBOMAN_REPOSITORY,
                    "tag": release.get("tag_name", "unknown"),
                    "asset": CYBOMAN_ARCHIVE,
                    "variant": "lossy",
                    "url": asset["browser_download_url"],
                    "sha256": sha(data),
                }
            )
            + "\n"
        ).encode(),
    )
    return context.record([target, record])


def install_dlss_enabler(context):
    """Install the DLSS Enabler proxy as OptiScaler's headless enabler DLL."""
    client = context.client()
    releases = client.releases(DLSS_ENABLER_REPOSITORY, context.refresh)
    pinned = [r for r in releases if r.get("tag_name") == "dlss-enabler"]
    release = asset = None
    for candidate in pinned + [r for r in releases if r not in pinned]:
        if candidate.get("draft"):
            continue
        for item in candidate.get("assets", []):
            name = item.get("name", "").lower()
            if (
                name.endswith(".zip")
                and not any(word in name for word in ("debug", "symbol", "pdb", "source", "src"))
                and item.get("browser_download_url")
            ):
                release, asset = candidate, item
                break
        if asset:
            break
    if not asset:
        raise ValueError("No DLSS Enabler release archive found")
    files = archive_files(_download(client, asset))
    members = sorted(
        (name for name in files if PurePosixPath(name).name.lower() in {"dxgi.dll", "version.dll"}),
        key=lambda name: (PurePosixPath(name).name.lower() != "dxgi.dll", name),
    )
    if not members:
        raise ValueError("DLSS Enabler proxy DLL (dxgi.dll/version.dll) not found in the archive")
    data = files[members[0]]
    _require_x64(data, "DLSS Enabler DLL")
    assets.deploy(
        context.root,
        "component:dlss_enabler",
        {DLSS_ENABLER_FILE: data},
        {
            "kind": "component",
            "component": "dlss_enabler",
            "version": release.get("tag_name", ""),
            "updated_at": asset.get("updated_at", ""),
            # Update checks re-resolve this exact asset on the same moving tag.
            "source": {
                "repo": DLSS_ENABLER_REPOSITORY,
                "pattern": "^" + re.escape(asset.get("name", "")) + "$",
                "channel": "nightly",
                "tag": release.get("tag_name", ""),
            },
        },
        context.allow_foreign,
    )
    return context.record([DLSS_ENABLER_FILE])


def _require_x64(data, label):
    with tempfile.NamedTemporaryFile() as stream:
        stream.write(data)
        stream.flush()
        if not compatible_binary(stream.name, 64):
            raise ValueError(label + " is not a Windows x64 DLL")


NATIVE_INSTALLERS = {"amd_fsr": install_cyboman, "dlss_enabler": install_dlss_enabler}

# Legacy backend attributes Desktop still replaces at runtime. A contract test
# keeps this list honest; shrink it as components migrate to native installers.
LEGACY_HOOKS = (
    "GAME_EXE",
    "GAME_DIR",
    "GAME_NAME",
    "GAME_DISPLAY",
    "GAME_KEY",
    "GAME_BITS",
    "GAME_IS_UE",
    "GAME_IS_UNITY",
    "STEAM_APPID",
    "LAUNCHER_TITLE",
    "START_DIR",
    "HELIXSR_SOURCE_DLL",
    "HELIXSR_DIR",
    "RESHADE_DLL_NAME",
    "RESHADE_LEGACY_DLL_NAME",
    "QUIRK_OPTISCALER_DLL",
    "DISABLE_UE_HDR",
    "detect_game",
    "cleanup_stale",
    "launch_now",
    "optiscaler_urls",
    "download_file",
    "fetch_payload",
    "install_engine_fallback",
    "install_reshade",
    "install_optiscaler",
    "resolve_game_quirks",
    "find_renodx_mod",
    *(item.backend_hook for item in COMPONENTS.values() if item.backend_hook),
)


# Settings Desktop injects that the script reads with globals().get(...).
INJECTED_SETTINGS = ("ALLOW_FOREIGN",)


def attach_native(module, game, repository, preferences):
    """Route migrated components to native installers inside the legacy flow."""

    def make(key):
        def run():
            context = InstallContext(
                game,
                repository,
                preferences,
                refresh=bool(getattr(module, "FORCE_UPDATE", False)),
                allow_foreign=bool(preferences.get("allow_foreign", False)),
                track=module.track,
            )
            NATIVE_INSTALLERS[key](context)
            module.success(f"Installed {COMPONENT_LABELS[key]}")
            return True

        return run

    for key, installer in NATIVE_INSTALLERS.items():
        hook = COMPONENTS[key].backend_hook
        if not callable(getattr(module, hook, None)):
            raise RuntimeError("Backend no longer provides " + hook)
        setattr(module, hook, make(key))
