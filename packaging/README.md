# AppImage build

The AppImage contains the desktop package, its backend, Python, PyYAML, PySide6/Qt (Wayland/X11/offscreen plugins), curl, unzip, and 7-Zip. Prepared HelixSR network files and personal library/profile data are not bundled.

The current build bundles its own dynamic loader and C runtime. Python and bundled native tools execute through that private loader; it does not export a bundled `LD_LIBRARY_PATH`. Graphics-driver libraries are supplied by the host desktop. Before launching an external launcher or game, the original PATH, Python, and Qt environment is restored. Wayland, HDR, and prefix variables are retained.

## Build locally

Requirements: Linux x86_64, Python/PySide6/PyYAML, `appimagetool`, `ldd`, curl, unzip, and 7z. The current script supports distro-installed Python/Qt and discovers Qt's plugin path through `QLibraryInfo`.

```bash
python3 -B packaging/build_appimage.py --runtime-file /path/to/official/runtime-x86_64
```

Use the official runtime from [AppImage/type2-runtime](https://github.com/AppImage/type2-runtime/releases). When an existing local type-2 AppImage is available, its runtime executable can be reused without including any of that app's payload:

```bash
python3 -B packaging/build_appimage.py --runtime-source /path/to/existing.AppImage
```

This local build used the static runtime extracted from an existing ML4W AppImage because shell networking was unavailable. The runtime filename, size, and SHA-256 are recorded in `BUILD_INFO.json` inside the package. For a distribution build, prefer a pinned official runtime and record its provenance.

Output:

```text
dist/OptiDX-Desktop-0.3.4-x86_64.AppImage
dist/OptiDX-Desktop-0.3.4-x86_64.AppImage.sha256
```

The unpacked AppDir and runtime build files live under `build/`. Third-party license files from installed packages are included under `usr/share/licenses`. Build/runtime versions and host graphics-library names are recorded in `usr/share/optidx-desktop/BUILD_INFO.json`.

## Use

```bash
chmod +x OptiDX-Desktop-0.3.4-x86_64.AppImage
./OptiDX-Desktop-0.3.4-x86_64.AppImage
```

On systems without usable FUSE:

```bash
./OptiDX-Desktop-0.3.4-x86_64.AppImage --appimage-extract-and-run
```

Your existing `~/.local/share/optidx-desktop` profiles, `~/.cache/optidx` downloads, and `~/.local/share/optidx/helixsr` prepared files are reused. Keep the AppImage at a stable path if using it as a game wrapper.

Steam: **Copy launch options** emits a command using the persistent AppImage path and `--backend`, rather than a temporary mount path. Heroic: select the AppImage as the wrapper executable and put `--backend` followed by the desired backend flags in its arguments field. The GUI's normal Launch button still asks Steam/Heroic to launch their game directly.

## Checks

```bash
./dist/OptiDX-Desktop-0.3.4-x86_64.AppImage --appimage-extract-and-run --runtime-info
QT_QPA_PLATFORM=offscreen ./dist/OptiDX-Desktop-0.3.4-x86_64.AppImage --appimage-extract-and-run --screenshot /tmp/optidx-appimage.png
./dist/OptiDX-Desktop-0.3.4-x86_64.AppImage --appimage-extract-and-run --backend --help
cd dist
sha256sum -c OptiDX-Desktop-0.3.4-x86_64.AppImage.sha256
```

This initial AppImage is built with the current CachyOS/Arch runtime packages and tested locally. Other distributions and older CPU targets have not been validated; cross-distribution testing should precede advertising broad compatibility.

## Display backend

On Wayland sessions the GUI prefers native Wayland, with Qt's `xcb` fallback.
Single-backend `QT_QPA_PLATFORM` overrides are respected. Inherited fallback
lists such as Nemo’s `xcb;wayland` are reordered to prefer Wayland on Wayland
sessions. Plugin options and other fallback choices are retained. The footer reports the active
backend; copied diagnostics includes `qt_platform`. Selection affects only the
GUI, not the environment passed to games or launchers. Restart an existing window
with the rebuilt AppImage to apply it. For explicit testing:

```bash
QT_QPA_PLATFORM=wayland ./dist/OptiDX-Desktop-0.3.4-x86_64.AppImage --appimage-extract-and-run
```

Qt platform selection references: [Qt QPA](https://doc.qt.io/qt-6/qpa.html) and
[QGuiApplication](https://doc.qt.io/qt-6/qguiapplication.html).
