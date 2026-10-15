"""Keep bundled tools inside the app and restore host environment when launching games."""
import os
from pathlib import Path
import subprocess
import sys
import shutil

ENV_KEYS = ("PATH", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONNOUSERSITE")


def python_executable():
    bundled = os.environ.get("OPTIDX_BUNDLED_PYTHON")
    return bundled if bundled and Path(bundled).is_file() else sys.executable


def external_environment():
    result = os.environ.copy()
    if not result.get("OPTIDX_APPIMAGE_CONTEXT"):
        return result
    for key in ENV_KEYS:
        if result.get("OPTIDX_ORIG_" + key + "_SET") == "1":
            result[key] = result.get("OPTIDX_ORIG_" + key, "")
        else:
            result.pop(key, None)
    for key in list(result):
        if key.startswith("OPTIDX_ORIG_") or key in {"OPTIDX_APPIMAGE_CONTEXT", "OPTIDX_BUNDLED_PYTHON", "APPDIR", "APPIMAGE", "OWD"}:
            result.pop(key, None)
    return result


def open_url(url):
    if os.environ.get("OPTIDX_APPIMAGE_CONTEXT"):
        subprocess.Popen(["xdg-open", url], env=external_environment(), start_new_session=True)
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))


def open_game_uri(game):
    """Use the packaged Heroic command without depending on desktop URI registration."""
    environment = external_environment()
    if game.store == "Heroic" and game.launch_uri.startswith("heroic://"):
        if game.launcher_kind == "flatpak":
            executable = shutil.which("flatpak", path=environment.get("PATH", os.defpath))
            if not executable:
                raise FileNotFoundError("This game belongs to Flatpak Heroic, but the flatpak command is unavailable. Refresh the library after changing Heroic installations.")
            subprocess.Popen([executable, "run", "com.heroicgameslauncher.hgl", "--no-gui", game.launch_uri],
                             env=environment, start_new_session=True)
            return
        executable = shutil.which("heroic", path=environment.get("PATH", os.defpath))
        if executable:
            subprocess.Popen([executable, "--no-gui", game.launch_uri], env=environment,
                             start_new_session=True)
            return
    # Retain desktop dispatch for Steam, Flatpak and custom URI handlers.
    open_url(game.launch_uri)


def appimage_arguments():
    """Keep copied wrappers usable when the GUI was started without FUSE."""
    return ['--appimage-extract-and-run'] if (os.environ.get('APPIMAGE_EXTRACT_AND_RUN') or
           '/appimage_extracted_' in os.environ.get('APPDIR','')) else []


def gui_arguments(program):
    """Prefer Wayland for this QApplication only; never alter launcher env."""
    arguments = [program]
    if not (os.environ.get('WAYLAND_DISPLAY') or
            os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'):
        return arguments
    override = os.environ.get('QT_QPA_PLATFORM', '')
    if not override:
        return arguments + ['-platform', 'wayland;xcb']
    platforms = [entry.strip() for entry in override.split(';')]
    names = [entry.partition(':')[0] for entry in platforms]
    native = [entry for entry, name in zip(platforms, names) if name.startswith('wayland')]
    if 'xcb' in names and native:
        # File managers may inherit xcb;wayland from their desktop session.
        # Move native choices before xcb, retaining plugin options and other
        # choices. A single explicit backend is always left alone.
        first_xcb = names.index('xcb')
        if all(index < first_xcb for index, name in enumerate(names) if name.startswith('wayland')):
            return arguments
        insertion = sum(not name.startswith('wayland') for name in names[:first_xcb])
        ordered = [entry for entry, name in zip(platforms, names) if not name.startswith('wayland')]
        ordered[insertion:insertion] = native
        if ordered != platforms:
            arguments += ['-platform', ';'.join(ordered)]
    return arguments
