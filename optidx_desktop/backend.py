"""Adapter around the desktop OptiDX backend. Each job uses a fresh process."""
import importlib.util
import os
from pathlib import Path
import shlex
import sys

from .inspection import DIRECTX_INPUTS, inspect_game, manifest_paths

BACKEND_PATH = Path(__file__).resolve().parents[1] / "backend/OptiDX.py"
ACTIONS = {"install", "update", "remove", "configure"}
COMPONENT_LABELS = {
    "optiscaler": "OptiScaler", "reshade": "ReShade", "renodx": "RenoDX",
    "luma": "Luma", "amd_fsr": "Cyboman FSR 4.1.1 · lossy", "helixsr": "HelixSR",
    "dlss_enabler": "DLSS Enabler",
}
LEGACY_COMPONENTS = {
    "full": {"optiscaler", "reshade", "renodx", "amd_fsr", "helixsr", "dlss_enabler"},
    "renodx": {"reshade", "renodx"}, "luma": {"reshade", "luma"},
}
DEFAULT_COMPONENTS = LEGACY_COMPONENTS["full"] - {"helixsr"}


def selected_components(preferences):
    values = preferences.get("components")
    if values is None:
        if "mode" not in preferences:
            return set(DEFAULT_COMPONENTS)
        mode = preferences.get("mode", "full")
        if mode not in LEGACY_COMPONENTS:
            raise ValueError("Unknown setup profile")
        return set(LEGACY_COMPONENTS[mode])
    if not isinstance(values, dict) or any(not isinstance(value, bool) for value in values.values()):
        raise ValueError("Component selection must contain boolean choices")
    unknown = set(values) - set(COMPONENT_LABELS)
    if unknown:
        raise ValueError("Unknown components: " + ", ".join(sorted(unknown)))
    return {name for name, value in values.items() if value}


def component_arguments(preferences):
    selected = selected_components(preferences)
    args = ["--components=" + (",".join(sorted(selected)) or "none")]
    if preferences.get("prune_components", False):
        args.append("--prune-components")
    return args
FG_CHOICES = {
    "Enabled": ["auto", "true", "false"],
    "FGInput": ["auto", "nofg", "dlssg", "nvngxfg", "fsrfg", "upscaler", "fsrfg30", "xefg"],
    "FGOutput": ["auto", "nofg", "xefg", "fsrfg", "dlssg"],
    "FGNvngxReplacement": ["auto", "None", "Nukems", "Arturs", "FFX", "Combo"],
}


def load_backend():
    spec = importlib.util.spec_from_file_location("optidx_snapshot", BACKEND_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_game(game):
    path = Path(game.executable).resolve() if game.executable else None
    if not path or not path.is_file() or path.suffix.lower() != ".exe":
        raise ValueError("Choose an existing Windows game executable before installing.")
    path.relative_to(Path(game.root).resolve())
    manifest_paths(game.target)
    marker = game.target / ".optidx-installed"
    if marker.is_file():
        recorded = marker.read_text(encoding="utf-8").splitlines()
        if recorded and Path(recorded[0]).resolve() != game.target.resolve():
            raise ValueError("The install marker points to another folder. Select that game's actual binary first.")


def configure_environment(game, preferences):
    prefix = preferences.get("prefix", "").strip() or game.prefix
    # A UI-launched job must not inherit unrelated Steam/Heroic IDs or prefix variables.
    for key in ["STEAM_COMPAT_DATA_PATH", "WINEPREFIX", "SteamAppId", "SteamGameId", "SteamAppID",
                "HEROIC_APP_NAME", "HEROIC_APP_TITLE", "LUTRIS_GAME_NAME", "LUTRIS_GAME_SLUG",
                "BOTTLES_GAME_NAME", "BOTTLE_NAME", "OPTIDX_UE_CONFIG_DIR"]:
        os.environ.pop(key, None)
    if prefix:
        os.environ["WINEPREFIX"] = prefix
    if game.store == "Steam":
        os.environ["SteamAppId"] = game.app_id
    os.environ["HEROIC_APP_TITLE"] = game.title
    if preferences.get("config_dir"):
        os.environ["OPTIDX_UE_CONFIG_DIR"] = preferences["config_dir"]


def bind_target(module, game, preferences=None):
    """Use the exact binary selected in the UI instead of rescoring siblings."""
    info = inspect_game(game)
    preferences = preferences or {}

    def detect():
        module.GAME_EXE = game.executable
        module.GAME_DIR = str(game.target.resolve())
        module.GAME_NAME = module.GAME_DISPLAY = game.title
        module.GAME_KEY = module.norm(game.title)
        module.GAME_BITS = int(preferences.get("bits_override") or info["bits"] or module.detect_exe_bitness(game.executable))
        module.GAME_IS_UE = info["engine"] == "Unreal"
        module.GAME_IS_UNITY = info["engine"] == "Unity"
        module.STEAM_APPID = game.app_id if game.store == "Steam" else ""
        module.LAUNCHER_TITLE = game.title
        module.add_candidate_title(game.title)
        module.add_candidate_title(module.extract_pe_product_name(game.executable))
        module.add_candidate_title(Path(game.executable).stem)
        module.info(f"Desktop selected: {game.title} ({game.executable})")
        return True

    module.detect_game = detect
    module.START_DIR = str(game.target.resolve())

    def cleanup_owned_addons():
        # The launch script clears all addons when changing mods. A library manager
        # must retain unrelated addons installed by the user or another tool.
        for relative in manifest_paths(game.target):
            path = game.target / relative
            if path.is_file() and path.suffix.lower() in {".addon", ".addon32", ".addon64"}:
                path.unlink()
    module.cleanup_stale = cleanup_owned_addons


def apply_settings(module, game, preferences):
    ini = game.target / "OptiScaler.ini"
    if not ini.is_file():
        return
    values = {key: preferences[key] for key in FG_CHOICES
              if preferences.get(key)}
    for key, value in values.items():
        if value not in FG_CHOICES[key]:
            raise ValueError(f"Unsupported {key} value: {value}")
    if values:
        text = module.set_ini_values(ini.read_text(encoding="utf-8"), "FrameGen", values)
        module.atomic_write(ini, text.encode("utf-8"), ini.stat().st_mode & 0o777)


def execute_backend(game, action, preferences, module=None):
    if action not in ACTIONS:
        raise ValueError("Unknown operation")
    effective = dict(preferences)
    if action == "update" and preferences.get("exclude_components"):
        selected = selected_components(preferences) - set(preferences["exclude_components"])
        effective["components"] = {name: name in selected for name in COMPONENT_LABELS}
        effective["prune_components"] = False
        if not selected:
            return inspect_game(game)
    arguments = component_arguments(effective)
    validate_game(game)
    if action in {"install", "update"}:
        info = inspect_game(game)
        from .channels import effective_api
        api = effective_api(game, preferences)
        selected = selected_components(preferences)
        from .assets import state
        if "optiscaler" in selected and any(item.get("metadata", {}).get("kind") == "neural" for root in {game.target, Path(game.root)} for item in state(root)["groups"].values()):
            raise ValueError("Remove the managed neural consumer before installing stock OptiScaler; both intercept NGX calls.")
        if int(preferences.get("bits_override") or info["bits"] or 64) == 32 and selected - {"reshade", "renodx"}:
            raise ValueError("32-bit games support ReShade/RenoDX; Luma and upscaler components require 64-bit.")
        if api in {"Vulkan", "DX8"}:
            raise ValueError("Use the Linux Vulkan controls or configure a translation layer before DLL deployment.")
        if api in {"DX9", "OpenGL"} and selected - {"reshade", "renodx"}:
            raise ValueError("Selected upscaler components require DX11/DX12; DX9/OpenGL supports ReShade and matching RenoDX addons.")
        if preferences.get("reshade_channel") == "no_addons" and selected.intersection({"renodx", "luma"}):
            raise ValueError("Choose a ReShade channel with addon support for RenoDX/Luma.")
    configure_environment(game, preferences)
    module = module or load_backend()
    if action in {"install", "update"} and "helixsr" in selected_components(effective):
        if "amd_fsr" in selected_components(effective):
            raise ValueError("Choose HelixSR or Cyboman lossy FSR, not both")
        from .helixsr import local_source
        source = local_source(effective.get("helixsr_dll", ""))
        module.HELIXSR_SOURCE_DLL = source
        module.HELIXSR_DIR = source.parent
    bind_target(module, game, preferences)
    from .channels import configure_backend
    from .storage import Repository
    configure_backend(module, game, Repository(preferences.get("_data_dir")), preferences)
    # Never execute a game from a mod-management job.
    def forbidden_launch():
        raise RuntimeError("Backend attempted to launch a game during a management job")
    module.launch_now = forbidden_launch
    previous = Path.cwd()
    try:
        os.chdir(game.target)
        if action == "configure":
            module.DISABLE_UE_HDR = not preferences.get("native_hdr", True)
            module.configure_ue_hdr(game.target)
        elif action == "remove":
            if (game.target / module.MANIFEST).exists() and not module.uninstall_dir(str(game.target)):
                raise RuntimeError("OptiDX could not complete removal; backups were retained")
            marker = game.target / module.MARKER
            if marker.exists():
                marker.unlink()
        else:
            args = list(arguments)
            if action == "update":
                args.append("--update")
            if not preferences.get("native_hdr", True):
                args.append("--no-ue-hdr")
            try:
                module.main(args)
            except SystemExit as error:
                if error.code not in (None, 0):
                    raise RuntimeError(f"OptiDX exited with code {error.code}") from error
            if not (game.target / module.MANIFEST).is_file() and not getattr(module, "CUSTOM_SETUP_COMPLETED", False):
                raise RuntimeError("No installation was recorded. Check the backend log for download or dependency failures.")
        if action in {"install", "update"}:
            from .channels import record_installed_versions
            record_installed_versions(module, game, preferences)
        if action != "remove":
            apply_settings(module, game, preferences)
        return inspect_game(game)
    finally:
        os.chdir(previous)
        if getattr(module, "TMP_DIR", None):
            import shutil
            shutil.rmtree(module.TMP_DIR, ignore_errors=True)


def launch_options(preferences=None):
    preferences = preferences or {}
    image = os.environ.get("APPIMAGE")
    from .runtime import appimage_arguments
    args = [str(Path(image).resolve()), *appimage_arguments(), "--backend"] if image else [sys.executable, str(BACKEND_PATH)]
    args += component_arguments(preferences)
    if not preferences.get("native_hdr", True):
        args.append("--no-ue-hdr")
    return shlex.join(args) + " %command%"
