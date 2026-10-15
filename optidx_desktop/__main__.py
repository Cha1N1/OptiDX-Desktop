import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .library import scan_library
from .storage import Repository


def main():
    if sys.argv[1:2] == ["--launch-profile"]:
        from .launch import run_profile
        command = sys.argv[3:]
        return run_profile(sys.argv[2], command[1:] if command[:1] == ["--"] else command)
    if sys.argv[1:2] == ["--backend"]:
        from .backend import load_backend
        from .runtime import external_environment
        module = load_backend()
        original_launch = module.launch_now
        def launch_game():
            clean = external_environment()
            import os
            os.environ.clear()
            os.environ.update(clean)
            original_launch()
        module.launch_now = launch_game
        module.main(sys.argv[2:])
        return 0
    parser = argparse.ArgumentParser(description="OptiDX Desktop: a Linux game mod manager")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--scan", action="store_true", help="Discover games, save the library, print JSON, and exit")
    parser.add_argument("--data-dir", help="Override app storage (useful for testing)")
    parser.add_argument("--screenshot", help="Save an offscreen preview and exit without scanning or modifying games")
    parser.add_argument("--runtime-info", action="store_true", help="Print Python/Qt bundle locations and exit")
    arguments = parser.parse_args()
    repository = Repository(arguments.data_dir)
    if arguments.runtime_info:
        import PySide6
        from PySide6.QtCore import QLibraryInfo
        from .runtime import python_executable
        print(json.dumps({"version": __version__, "python": sys.version.split()[0], "prefix": sys.prefix,
                          "interpreter": python_executable(), "pyside": PySide6.__file__,
                          "qt_plugins": QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath),
                          "application": __file__}, indent=2))
        return 0
    if arguments.scan:
        games, warnings = scan_library(cached=repository.games())
        repository.save_games(games)
        print(json.dumps({"games": [g.to_dict() for g in games], "warnings": warnings}, indent=2))
        return 0
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from .app import MainWindow
    except ImportError:
        print("Install PySide6: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    from .runtime import gui_arguments
    app = QApplication(gui_arguments(sys.argv[0]))
    app.setApplicationName("OptiDX Desktop")
    window = MainWindow(repository, auto_scan=not arguments.screenshot)
    window.show()
    if arguments.screenshot:
        def save():
            destination = Path(arguments.screenshot)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(destination)):
                print("Could not save preview", file=sys.stderr)
                app.exit(1)
            else:
                app.quit()
        QTimer.singleShot(250, save)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
