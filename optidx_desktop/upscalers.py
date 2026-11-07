"""Selected-only custom upscalers for recent upstream OptiScaler builds."""

from pathlib import Path, PurePosixPath
import re
import struct

from . import assets
from .downloads import Client, archive_files, binary_member
from .inspection import contained, pe_info

CYBOMAN_REPO = "zgauthier2000/fsr4-shader-performance-overrides"
DLL = "amd_fidelityfx_upscaler_dx12.dll"
# Stable names are also OptiScaler menu entries. Keep them independent of versions.
VARIANTS = {
    "cyboman_exact": ("Cyboman Exact", "Cyboman-Exact", "ffx"),
    "cyboman_lossy": ("Cyboman Lossy (retrained, formerly Lossy2)", "Cyboman-Lossy", "ffx"),
    "cyboman_lossy2": ("Cyboman Lossy2 (older archives)", "Cyboman-Lossy2", "ffx"),
    "cyboman_lite_exact": ("Cyboman FSR 4.1.2 Lite Exact", "Cyboman-Lite-Exact", "ffx"),
    "cyboman_lite_lossy": ("Cyboman FSR 4.1.2 Lite Lossy", "Cyboman-Lite-Lossy", "ffx"),
    "helix_fsr4": ("HelixSR FSR 4", "HelixSR-FSR4", "ffx"),
    "helix_dlss": ("HelixSR DLSS 3.7 / Model E", "HelixSR-DLSS", "dlss"),
}
TARGETS = {
    "rx6000": "cyboman-rx6000",
    "rx7000": "cyboman-rx7000",
    "igpu_rdna2": "igpu-cyboman-rdna2",
    "igpu_rdna3": "igpu-cyboman-rdna3",
}


def selected(preferences):
    result = []
    for key in VARIANTS:
        value = preferences.get("upscaler_" + key, False)
        if not isinstance(value, bool):
            raise ValueError("Custom upscaler choices must be booleans")
        if value:
            result.append(key)
    return result


def supports_custom_upscalers(data):
    """Recognize the loader without depending on logging format arguments.

    CustomUpscalers became CustomProviders; its error text changed from a
    brace-format diagnostic to a printf diagnostic in the same capable build.
    """
    return b"Can't load custom upscaler" in data or (
        b"Dx12Upscaler=" in data and b"isn't an upscaler or a folder in" in data
    )


def require_custom_loader(game, preferences=None):
    """Check the installed code, rather than inferring capabilities from a tag."""
    from .channels import effective_api

    if effective_api(game, preferences or {}) not in {"DX12", "DXGI"}:
        raise ValueError("Custom upscaler deployment currently supports DX12 games only")
    if pe_info(game.executable)["machine"] != 0x8664:
        raise ValueError("Custom upscalers require a Windows x64 game executable")
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
            if supports_custom_upscalers(data):
                return
    raise ValueError(
        "Could not identify custom-upscaler support in the installed OptiScaler DLL. "
        "Use a current capable nightly build; older stable builds do not provide this loader."
    )


def exports(data):
    """Read bounded PE export names without loading or executing the DLL."""
    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[:2] != b"MZ" or data[pe : pe + 4] != b"PE\0\0":
            raise ValueError("Invalid PE header")
        machine, count = struct.unpack_from("<HH", data, pe + 4)
        size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        if machine != 0x8664 or struct.unpack_from("<H", data, optional)[0] != 0x20B:
            raise ValueError("Upscaler DLL must be Windows x64")
        if not 1 <= count <= 96 or size < 120:
            raise ValueError("Invalid PE section table")
        sections = [
            struct.unpack_from("<IIII", data, optional + size + i * 40 + 8) for i in range(count)
        ]

        def offset(rva, length):
            for virtual_size, start, raw_size, raw in sections:
                delta = rva - start
                if 0 <= delta and delta + length <= raw_size and raw + delta + length <= len(data):
                    return raw + delta
            raise ValueError("Invalid PE export address")

        rva = struct.unpack_from("<I", data, optional + 112)[0]
        table = offset(rva, 40)
        names_count = struct.unpack_from("<I", data, table + 24)[0]
        names_rva = struct.unpack_from("<I", data, table + 32)[0]
        if names_count > 65536:
            raise ValueError("Too many PE exports")
        names = offset(names_rva, names_count * 4)
        result = set()
        for i in range(names_count):
            address = struct.unpack_from("<I", data, names + i * 4)[0]
            name = offset(address, 1)
            end = data.find(b"\0", name, min(name + 256, len(data)))
            if end == -1:
                raise ValueError("Invalid PE export name")
            result.add(data[name:end].decode("ascii"))
        return result
    except (struct.error, UnicodeError, IndexError) as error:
        raise ValueError("Invalid upscaler PE export table") from error


def checked_dll(data, kind):
    if not 0 < len(data) <= 128 * 1024 * 1024:
        raise ValueError("Upscaler DLL exceeds size limit")
    if kind not in {"ffx", "dlss"}:
        raise ValueError("Unknown upscaler interface")
    names = exports(data)
    required = (
        {"ffxCreateContext", "ffxDestroyContext", "ffxConfigure", "ffxQuery", "ffxDispatch"}
        if kind == "ffx"
        else {
            "NVSDK_NGX_D3D12_Init",
            "NVSDK_NGX_D3D12_CreateFeature",
            "NVSDK_NGX_D3D12_EvaluateFeature",
            "NVSDK_NGX_D3D12_ReleaseFeature",
        }
    )
    if not required <= names:
        raise ValueError("DLL does not expose the required " + kind + " upscaler interface")
    return data


def cyboman_pattern(target):
    if target not in TARGETS:
        raise ValueError("Choose the Cyboman hardware target before downloading")
    return r"^fsr[\d.]+-" + re.escape(TARGETS[target]) + r"-\d{4}-\d{2}-\d{2}(?:[.\w-]*)\.7z$"


def legacy_lossy2_source(preferences):
    """Older Lossy2 is explicit; the current retrained DLL is named Lossy."""
    if preferences.get("upscaler_cyboman_archive", "").strip():
        return True
    tag = preferences.get("upscaler_cyboman_tag", "").strip()
    match = re.fullmatch(r"dll-(\d{4}-\d{2}-\d{2})(?:[.\w-]*)", tag)
    return bool(match and match[1] < "2026-10-29")


def prepare(repository, preferences, keys, refresh=False):
    """Prepare every requested DLL before writing anything to a game."""
    if "cyboman_lossy2" in keys and not legacy_lossy2_source(preferences):
        raise ValueError(
            "Choose Cyboman Lossy (retrained, formerly Lossy2) for current downloads. The older Lossy2 entry requires an older pinned release or local archive."
        )
    client = Client(repository.directory)
    package = None
    package_metadata = {}
    if any(key.startswith("cyboman_") for key in keys):
        local = preferences.get("upscaler_cyboman_archive", "")
        if local:
            path = Path(local).expanduser()
            package_metadata = {"source": {"path": str(path.resolve())}, "version": "Local"}
        else:
            target = preferences.get("upscaler_cyboman_target", "")
            pattern = cyboman_pattern(target)
            release = client.release_asset(
                CYBOMAN_REPO,
                pattern,
                tag=preferences.get("upscaler_cyboman_tag", ""),
                refresh=refresh,
            )
            path = client.fetch(release["browser_download_url"], release.get("digest", ""), refresh)
            package_metadata = {
                **release,
                "source": {
                    "repo": CYBOMAN_REPO,
                    "pattern": pattern,
                    "tag": preferences.get("upscaler_cyboman_tag", ""),
                },
                "target": target,
            }
        package = archive_files(path)
    prepared = {}
    for key in keys:
        if key not in VARIANTS:
            raise ValueError("Unknown custom upscaler: " + key)
        label, folder, kind = VARIANTS[key]
        metadata = dict(package_metadata)
        notes = {}
        if key.startswith("cyboman_"):
            variant = {
                "cyboman_lite_exact": "4.1.2l-exact",
                "cyboman_lite_lossy": "4.1.2l-lossy",
            }.get(key, key.removeprefix("cyboman_"))
            candidates = {
                name: data
                for name, data in package.items()
                if PurePosixPath(name).parts[-2:] == (variant, DLL)
            }
            if len(candidates) != 1:
                raise ValueError(
                    "Requested variant is missing or ambiguous: "
                    + variant
                    + "/"
                    + DLL
                    + ". Choose a release or local archive containing this variant. Lossy2 is absent from newer releases."
                )
            data = binary_member(candidates, DLL, 64)
            member = PurePosixPath(next(iter(candidates)))
            warning = package.get(str(member.parent / "WARNING.txt"))
            if warning is not None:
                if len(warning) > 65536:
                    raise ValueError("Upscaler warning file exceeds size limit")
                notes[f"OptiScaler/custom/{folder}/WARNING.txt"] = warning
        else:
            value = preferences.get("upscaler_" + key + "_dll", "")
            path = Path(value).expanduser() if value else None
            if path is None or not path.is_file() or path.suffix.lower() != ".dll":
                raise ValueError("Choose the prepared local " + label + " DLL")
            if path.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("Local upscaler DLL exceeds size limit")
            data = path.read_bytes()
            metadata = {"source": {"path": str(path.resolve())}, "version": "Local"}
        name = "nvngx.dll" if kind == "dlss" else DLL
        relative = f"OptiScaler/custom/{folder}/{kind}/{name}"
        prepared[key] = (
            {relative: checked_dll(data, kind), **notes},
            {
                **metadata,
                "kind": "upscaler",
                "variant": key,
                "label": label,
            },
        )
    return prepared


def deploy(game, repository, preferences, keys=None, prune=False, refresh=False):
    require_custom_loader(game, preferences)
    keys = selected(preferences) if keys is None else keys
    if not keys and not prune:
        raise ValueError("Tick at least one custom upscaler")
    prepared = prepare(repository, preferences, keys, refresh)
    # Per-group writes are reversible; the worker snapshot covers the whole job.
    for key, (files, metadata) in prepared.items():
        assets.deploy(game.target, "upscaler:" + key, files, metadata)
    removed = []
    if prune:
        for group in list(assets.state(game.target)["groups"]):
            if group.startswith("upscaler:") and group.split(":", 1)[1] not in keys:
                remove_variant(game, group)
                removed.append(group)
    return {"installed": list(prepared), "removed": removed}


def remove_variant(game, group):
    key = group.removeprefix("upscaler:")
    if group != "upscaler:" + key or key not in VARIANTS:
        raise ValueError("Unknown managed upscaler group")
    # Refuse to leave a saved custom selection pointing at a removed folder.
    ini = contained(game.target, "OptiScaler.ini")
    if ini.is_file():
        from .backend import load_backend
        from .textfiles import encode_edited

        module = load_backend()
        data = ini.read_bytes()
        values = module.hdr_ini_values(data.decode(module.hdr_ini_encoding(data)), "Upscalers")
        if values.get("dx12upscaler", "").casefold() == VARIANTS[key][1].casefold():
            text = (
                data.decode(module.hdr_ini_encoding(data)).replace("\r\n", "\n").replace("\r", "\n")
            )
            edited = module.set_ini_values(text, "Upscalers", {"Dx12Upscaler": "auto"})
            assets.atomic_bytes(ini, encode_edited(data, edited), ini.stat().st_mode & 0o777)
            assets.accept_config_edit(game.target, "OptiScaler.ini")
    assets.remove(game.target, group)
