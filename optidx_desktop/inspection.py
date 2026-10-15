import mmap
from pathlib import Path
import struct

from .storage import read_json

API_IMPORTS = {"d3d8.dll": "DX8", "d3d9.dll": "DX9", "d3d10.dll": "DX10",
               "d3d10_1.dll": "DX10", "d3d11.dll": "DX11", "d3d12.dll": "DX12",
               "dxgi.dll": "DXGI", "vulkan-1.dll": "Vulkan", "opengl32.dll": "OpenGL"}
DIRECTX_INPUTS = {"DX11", "DX12", "DXGI"}


def pe_info(path):
    """Read PE headers/imports; do not execute the binary or infer APIs from arbitrary strings."""
    info = {"bits": None, "machine": None, "apis": [], "imports": []}
    try:
        with open(path, "rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data[:2] != b"MZ":
                return info
            pe = struct.unpack_from("<I", data, 0x3c)[0]
            if data[pe:pe + 4] != b"PE\0\0":
                return info
            machine, sections = struct.unpack_from("<HH", data, pe + 4)
            opt_size = struct.unpack_from("<H", data, pe + 20)[0]
            optional = pe + 24
            magic = struct.unpack_from("<H", data, optional)[0]
            if magic not in (0x10b, 0x20b):
                return info
            if (opt_size < (112 if magic == 0x20b else 96) or not 1 <= sections <= 96 or
                    optional + opt_size + sections * 40 > len(data) or
                    (machine == 0x14c and magic != 0x10b) or
                    (machine in {0x8664, 0xaa64} and magic != 0x20b)):
                return info
            info["machine"] = machine
            info["bits"] = {0x8664: 64, 0x14c: 32, 0xaa64: 64}.get(machine)
            directories = optional + (112 if magic == 0x20b else 96)
            import_rva = struct.unpack_from("<I", data, directories + 8)[0]
            table = optional + opt_size
            mapping = []
            for n in range(min(sections, 96)):
                virtual_size, rva, size, offset = struct.unpack_from("<IIII", data, table + n * 40 + 8)
                mapping.append((rva, max(virtual_size, size), offset, size))

            def offset_for(address):
                for rva, span, offset, raw_size in mapping:
                    if rva <= address < rva + span and address - rva < raw_size:
                        return offset + address - rva
                return None

            descriptors = offset_for(import_rva) if import_rva else None
            def add_import(address):
                offset = offset_for(address)
                if offset is not None:
                    name = data[offset:offset + 256].split(b"\0", 1)[0].decode("ascii", errors="ignore").lower()
                    if name and name not in info["imports"]:
                        info["imports"].append(name)
            if descriptors is not None:
                for n in range(512):
                    descriptor = struct.unpack_from("<IIIII", data, descriptors + n * 20)
                    if not any(descriptor):
                        break
                    add_import(descriptor[3])
            # Modern engines frequently delay-load Direct3D. Static imports alone
            # can misleadingly show only the engine's fallback OpenGL path.
            if opt_size >= (directories - optional) + 14 * 8:
                delay_rva = struct.unpack_from("<I", data, directories + 13 * 8)[0]
                delayed = offset_for(delay_rva) if delay_rva else None
                if delayed is not None:
                    image_base = struct.unpack_from("<Q" if magic == 0x20b else "<I", data,
                                                    optional + (24 if magic == 0x20b else 28))[0]
                    for n in range(512):
                        descriptor = struct.unpack_from("<IIIIIIII", data, delayed + n * 32)
                        if not any(descriptor):
                            break
                        address = descriptor[1] if descriptor[0] & 1 else descriptor[1] - image_base
                        add_import(address)
            info["apis"] = sorted({API_IMPORTS[n] for n in info["imports"] if n in API_IMPORTS})
    except (OSError, ValueError, struct.error):
        pass
    return info


def compatible_binary(path, bits):
    """Bitness alone cannot distinguish x64 from ARM64 Windows payloads."""
    return bits in (32, 64) and pe_info(path)["machine"] == {32: 0x14c, 64: 0x8664}[bits]


def contained(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid managed path: {relative}")
    path = Path(root) / relative
    try:
        path.resolve().relative_to(Path(root).resolve())
    except ValueError:
        raise ValueError(f"Managed path leaves the game folder: {relative}")
    return path


def manifest_paths(root):
    root = Path(root)
    manifest = root / ".optidx-files"
    if not manifest.is_file():
        return []
    result = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line:
            contained(root, line)
            result.append(line)
    return result


def inspect_game(game):
    root = game.target
    info = pe_info(game.executable) if game.executable else {"bits": None, "apis": [], "imports": []}
    ancestors = [root] + list(root.parents)[:3]
    low = str(root).lower().replace("\\", "/")
    engine = "Unreal" if "/binaries/" in low or any((p / "Engine").is_dir() for p in ancestors) else "Unknown"
    if (root / "UnityPlayer.dll").exists() or (root / "GameAssembly.dll").exists():
        engine = "Unity"
    if (root / "re_chunk_000.pak").exists():
        engine = "RE Engine"
    try:
        managed = manifest_paths(root)
        manifest_error = ""
    except (OSError, ValueError) as error:
        managed, manifest_error = [], str(error)
    files = {p.name for p in root.glob("*") if p.is_file()} if root.is_dir() else set()
    has = lambda names: bool(files.intersection(names))
    components = {
        "OptiScaler": (root / "OptiScaler.ini").is_file(),
        "ReShade": has({"d3d12-ReShade64.dll", "ReShade64.dll", "ReShade32.dll"}),
        "RenoDX": any(n.lower().startswith("renodx") and ".addon" in n.lower() for n in files),
        "Luma": any(("luma" in n.lower() and ".addon" in n.lower()) or n.lower().endswith(".addon") for n in files),
        "HelixSR": any((root / "OptiScaler/HelixSR" / name).is_file()
                       for name in ["helixsr.dll", "amd_fidelityfx_dx12.dll"]),
        "AMD FSR": (root / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll").is_file(),
        "DLSS Enabler": (root / "OptiScaler/dlss-enabler-headless.dll").is_file(),
    }
    hdr = read_json(root / ".optidx-ue-hdr.json", {})
    ownership = read_json(root / ".optidx-components.json", {}).get("files", {})
    for name, key in [("RenoDX", "renodx"), ("Luma", "luma")]:
        for path in ownership.get(key, []):
            try:
                if contained(root, path).is_file() and ".addon" in Path(path).suffix.lower():
                    components[name] = True
            except ValueError:
                pass
    return {**info, "engine": engine, "components": components, "managed": managed,
            "installed": bool(managed), "hdr": hdr.get("status", "Unmanaged"),
            "manifest_error": manifest_error, "available": game.available,
            "target": str(root), "executable_exists": bool(game.executable and Path(game.executable).is_file())}


def foreign_dlls(game):
    """Identify conflicting proxies without guessing from filenames alone."""
    from .assets import state
    try:
        tracked=set(manifest_paths(game.target))
    except (ValueError,OSError):
        return []
    for item in state(game.target)['groups'].values():tracked.update(item['files'])
    records=[]
    for name in ['dxgi.dll','d3d9.dll','opengl32.dll','dinput8.dll','winmm.dll','version.dll','winhttp.dll']:
        path=game.target/name
        if not path.is_file() or name in tracked:continue
        with path.open('rb') as stream:data=stream.read(8*1024*1024)
        identity=next((label for label in ['OptiScaler','ReShade','DXVK','Special K','ENB','REFramework']
                       if label.encode() in data or label.encode('utf-16-le') in data),'Unknown DLL')
        records.append({'path':name,'identity':identity,'symlink':path.is_symlink()})
    return records


def unreal_version(game):
    root=Path(game.root)
    candidates=[root/'Engine/Build/Build.version',root/'Build.version']
    for path in candidates:
        data=read_json(path,{})
        if isinstance(data.get('MajorVersion'),int) and isinstance(data.get('MinorVersion'),int):
            return str(data['MajorVersion'])+'.'+str(data['MinorVersion'])
    try:
        import re
        with Path(game.executable).open('rb') as stream, mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            match=re.search(rb'\+\+UE[45]\+Release-([45]\.\d+)',data)
            if match:return match[1].decode()
    except (OSError,ValueError):pass
    return ''


def file_version(path):
    """Read the Windows fixed-file-info version; never load a DLL."""
    try:
        with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            offset=data.find(b'\xbd\x04\xef\xfe\x00\x00\x01\x00')
            if offset < 0:return ''
            major_minor, build_revision=struct.unpack_from('<II',data,offset+8)
            return '.'.join(str(n) for n in [major_minor>>16,major_minor&0xffff,build_revision>>16,build_revision&0xffff])
    except (OSError,ValueError,struct.error):return ''
