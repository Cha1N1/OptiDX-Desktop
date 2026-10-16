#!/usr/bin/env python3
"""Build a Python/Qt AppDir from installed runtimes, then package it with appimagetool."""
import argparse
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
HOST_LIBRARIES = ("libGL.so", "libGLX.so", "libGLdispatch.so", "libEGL.so", "libOpenGL.so",
                  "libvulkan.so", "libdrm", "libgbm.so")


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=True)


def ignored(directory, names):
    return {name for name in names if name in {"__pycache__", "site-packages", "test", "tests", "idlelib", "tkinter", "ensurepip"}
            or name.startswith("_tkinter.") or name.endswith((".pyc", ".pyi", ".a"))}


def dependencies(path):
    result = subprocess.run(["ldd", str(path)], capture_output=True, text=True)
    if "not found" in result.stdout:
        raise RuntimeError(f"Missing build dependencies for {path}: {result.stdout}")
    for line in result.stdout.splitlines():
        match = re.search(r"=> (/\S+)", line) or re.search(r"^\s*(/\S+)", line)
        if match:
            yield Path(match.group(1))


def runtime_from_image(source, destination):
    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if data[:4] != b"\x7fELF" or data[8:11] != b"AI\x02":
            raise ValueError("Runtime source is not a type-2 AppImage")
        offset = data.find(b"hsqs")
        while offset >= 0:
            if offset + 96 < len(data) and struct.unpack_from("<HH", data, offset + 28) == (4, 0):
                break
            offset = data.find(b"hsqs", offset + 4)
        if offset < 0:
            raise ValueError("AppImage has no valid SquashFS header")
        runtime = data[:offset]
        if b"APPIMAGE_EXTRACT_AND_RUN" not in runtime:
            raise ValueError("Runtime source does not support extract-and-run")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(runtime)
        destination.chmod(0o755)
    return {"source_name": source.name, "sha256": hashlib.sha256(runtime).hexdigest(),
            "upstream": "https://github.com/AppImage/type2-runtime", "bytes": len(runtime)}


def build(args):
    if platform.machine() != "x86_64":
        raise RuntimeError("This packaging target is x86_64")
    tool = shutil.which("appimagetool")
    if not tool:
        raise RuntimeError("Install appimagetool before building")
    from PySide6.QtCore import QLibraryInfo
    import PySide6
    version_ns = {}
    exec((ROOT / "optidx_desktop/__init__.py").read_text(), version_ns)
    version = version_ns["__version__"]
    destination = Path(args.output).resolve() if args.output else ROOT / "dist"
    destination.mkdir(parents=True, exist_ok=True)
    appdir = ROOT / "build/OptiDX-Desktop.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    appdir.mkdir(parents=True)
    python_name = f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib = appdir / "usr/lib"
    site = lib / python_name / "site-packages"
    site.mkdir(parents=True)
    print("Bundling Python and Qt", flush=True)
    copy(Path(sys.executable).resolve(), appdir / "usr/bin/python3.real")
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(stdlib, lib / python_name, dirs_exist_ok=True, ignore=ignored)
    pyside = Path(PySide6.__file__).parent
    target = site / "PySide6"
    target.mkdir()
    for name in ["__init__.py", "_config.py", "_git_pyside_version.py"]:
        if (pyside / name).exists():
            copy(pyside / name, target / name)
    for name in ["support"]:
        shutil.copytree(pyside / name, target / name, ignore=ignored)
    for module in ["QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg", "QtDBus", "QtTest"]:
        file = Path(importlib.util.find_spec("PySide6." + module).origin)
        copy(file, target / file.name)
    import yaml
    shutil.copytree(Path(yaml.__file__).parent, site / "yaml", ignore=ignored)
    import shiboken6
    shutil.copytree(Path(shiboken6.__file__).parent, site / "shiboken6", ignore=ignored)
    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    choices = {
        "platforms": ["libqwayland.so", "libqxcb.so", "libqoffscreen.so", "libqminimal.so"],
        "imageformats": ["libqsvg.so", "libqjpeg.so", "libqico.so", "libqgif.so", "libqwebp.so"],
        "platformthemes": ["libqxdgdesktopportal.so"],
        "wayland-decoration-client": ["libbradient.so"],
        "wayland-shell-integration": ["libxdg-shell.so", "libwl-shell-plugin.so"],
        "wayland-graphics-integration-client": ["libqt-plugin-wayland-egl.so", "libshm-emulation-server.so"],
        "xcbglintegrations": ["libqxcb-glx-integration.so", "libqxcb-egl-integration.so"],
    }
    for category, names in choices.items():
        for name in names:
            source = plugins / category / name
            if source.is_file():
                copy(source, lib / "qt6/plugins" / category / name)
    copy(Path("/usr/lib64/ld-linux-x86-64.so.2"), lib / "ld-linux-x86-64.so.2")
    # External tools use the private loader too; no bundled library search path
    # leaks to Steam, Heroic, Proton, or the game.
    tool_sources = []
    for name in ["curl", "unzip", "7z"]:
        executable = shutil.which(name)
        if not executable:
            raise RuntimeError("Missing build tool: " + name)
        source = Path(executable).resolve()
        if name == "7z" and source.read_bytes()[:4] != b"\x7fELF":
            match = re.search(r"exec\s+(\S+)", source.read_text())
            if not match:
                raise RuntimeError("Cannot locate the real 7z executable")
            source = Path(match.group(1).strip('"'))
        tool_sources.append(source)
        copy(source, appdir / "usr/bin" / (name + ".real"))
        if name == "7z" and (source.parent / "7z.so").exists():
            copy(source.parent / "7z.so", appdir / "usr/bin/7z.so")
        wrapper = appdir / "usr/bin" / name
        copy(ROOT / "packaging/tool-wrapper.sh", wrapper)
        wrapper.chmod(0o755)
    seeds = [p for p in appdir.rglob("*") if p.is_file() and p.read_bytes()[:4] == b"\x7fELF"]
    seeds += [p for name in ["libnss_dns.so.2", "libnss_files.so.2", "libnss_compat.so.2", "libresolv.so.2"]
              if (p := Path("/usr/lib") / name).exists()]
    copied = set()
    original_files = set()
    excluded = set()
    pending = list(seeds)
    print("Collecting shared libraries", flush=True)
    while pending:
        source = pending.pop()
        for dependency in dependencies(source):
            if dependency.name.startswith(HOST_LIBRARIES):
                excluded.add(dependency.name)
                continue
            if dependency.name in copied:
                continue
            copied.add(dependency.name)
            original_files.add(dependency.resolve())
            copy(dependency, lib / dependency.name)
            pending.append(dependency)
    for seed in seeds:
        if seed.parent == Path("/usr/lib"):
            copy(seed, lib / seed.name)
    data = appdir / "usr/share/optidx-desktop"
    data.mkdir(parents=True)
    for name in ["optidx_desktop", "backend"]:
        shutil.copytree(ROOT / name, data / name, ignore=ignored)
    for name in ["LICENSE", "README.md", "RELEASE_NOTES.md"]:
        copy(ROOT / name, data / name)
    for document in (ROOT / "docs").glob("*.md"):
        copy(document, data / "docs" / document.name)
    shutil.copytree(ROOT / "packaging", data / "packaging", ignore=ignored)
    for name in ["requirements.txt", "run.sh", "launcher.py", "install-desktop.sh"]:
        copy(ROOT / name, data / name)
    for certificates in [Path("/etc/ssl/certs/ca-certificates.crt"), Path("/etc/ssl/cert.pem")]:
        if certificates.is_file():
            copy(certificates, data / "certificates.pem")
            break
    wrapper = appdir / "usr/bin/python3"
    wrapper.write_text((ROOT / "packaging/python-wrapper.sh").read_text().replace("@PYTHON@", python_name))
    wrapper.chmod(0o755)
    copy(ROOT / "packaging/apprun.sh", appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)
    launcher = appdir / "usr/bin/optidx-desktop"
    launcher.write_text('#!/bin/bash\nset -euo pipefail\napp_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)\nexec "$app_root/AppRun" "$@"\n')
    launcher.chmod(0o755)
    copy(ROOT / "packaging/optidx-desktop.desktop", appdir / "optidx-desktop.desktop")
    copy(ROOT / "packaging/optidx-desktop.svg", appdir / "optidx-desktop.svg")
    (appdir / ".DirIcon").symlink_to("optidx-desktop.svg")
    copy(ROOT / "packaging/optidx-desktop.desktop", appdir / "usr/share/applications/optidx-desktop.desktop")
    copy(ROOT / "packaging/optidx-desktop.svg", appdir / "usr/share/icons/hicolor/scalable/apps/optidx-desktop.svg")
    (appdir / "usr/bin/qt.conf").write_text("[Paths]\nPrefix=..\nPlugins=lib/qt6/plugins\nLibraries=lib\n")
    licenses = appdir / "usr/share/licenses"
    licenses.mkdir(parents=True)
    if shutil.which("pacman"):
        sources = list(original_files) + tool_sources + [Path(sys.executable).resolve(), pyside / "__init__.py", Path(yaml.__file__)]
        packages = subprocess.run(["pacman", "-Qoq", *map(str, sources)], capture_output=True, text=True)
        for package in sorted(set(packages.stdout.splitlines())):
            directory = Path("/usr/share/licenses") / package
            if directory.is_dir():
                shutil.copytree(directory, licenses / package, ignore=ignored)
        common = Path("/usr/share/licenses/common")
        if common.is_dir():
            shutil.copytree(common, licenses / "common", ignore=ignored)
    runtime_record = None
    runtime_file = Path(args.runtime_file).resolve() if args.runtime_file else None
    if runtime_file:
        runtime_record = {"source_name": runtime_file.name, "sha256": hashlib.sha256(runtime_file.read_bytes()).hexdigest(),
                          "bytes": runtime_file.stat().st_size, "upstream": "https://github.com/AppImage/type2-runtime"}
    if args.runtime_source:
        runtime_file = ROOT / "build/runtime-x86_64"
        runtime_record = runtime_from_image(Path(args.runtime_source).resolve(), runtime_file)
    (licenses / "AppImage-runtime-NOTICE.txt").write_text(
        "AppImage type-2 runtime. Copyright (c) 2004-23 probonopd. MIT license.\n"
        "Runtime source and full license: https://github.com/AppImage/type2-runtime\n"
        "https://github.com/AppImage/type2-runtime/blob/main/LICENSE\n"
        "Includes musl libc, libfuse, squashfuse, zstd, and zlib; their license links are in the runtime LICENSE.\n")
    manifest = {"version": version, "architecture": "x86_64", "python": sys.version.split()[0],
                "qt": QLibraryInfo.version().toString(), "pyside": PySide6.__version__,
                "build_platform": platform.platform(), "private_loader": True,
                "bundled_libraries": sorted(copied), "host_graphics_libraries": sorted(excluded),
                "runtime": runtime_record, "compression": args.compression}
    (data / "BUILD_INFO.json").write_text(json.dumps(manifest, indent=2) + "\n")
    image = destination / f"OptiDX-Desktop-{version}-x86_64.AppImage"
    pending_image = destination / ("." + image.name + ".pending")
    pending_image.unlink(missing_ok=True)
    command = [tool, "--no-appstream", "--comp", args.compression]
    if runtime_file:
        command += ["--runtime-file", str(runtime_file)]
    command += [str(appdir), str(pending_image)]
    environment = os.environ.copy()
    environment.update(ARCH="x86_64", VERSION=version)
    print("Building " + image.name, flush=True)
    subprocess.run(command, env=environment, check=True)
    os.replace(pending_image, image)
    image.chmod(0o755)
    checksum = hashlib.sha256(image.read_bytes()).hexdigest()
    image.with_name(image.name + ".sha256").write_text(checksum + "  " + image.name + "\n")
    print(f"Built {image} ({image.stat().st_size / 1048576:.1f} MiB)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    parser.add_argument("--compression", choices=("gzip", "xz"), default="gzip",
                        help="SquashFS compression (default: gzip for faster startup)")
    parser.add_argument("--runtime-file", help="Official AppImage type-2 runtime binary")
    parser.add_argument("--runtime-source", help="Local type-2 AppImage to reuse its runtime executable only")
    build(parser.parse_args())
