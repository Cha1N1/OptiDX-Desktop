"""Tray, download watching, update checks and startup maintenance."""

from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
)

from . import __version__
from .runtime import open_url


class AppUpdateThread(QThread):
    completed = Signal(object, str)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        from .app_updates import newer_release

        try:
            self.completed.emit(newer_release(self.directory), "")
        except (OSError, ValueError) as error:
            self.completed.emit(None, str(error))


class BackgroundServicesMixin:
    def check_all_updates(self):
        from .status import game_status

        games = [
            game
            for game in self.games
            if game.available
            and (status := game_status(game, self.repository)).installed
            and not status.errors
        ]
        for game in games:
            self.enqueue_feature("check_updates", game=game)

    def configure_services(self):
        from .storage import read_json

        self.service_settings = read_json(self.repository.directory / "settings.json", {})
        if not hasattr(self, "update_timer"):
            self.update_timer = QTimer(self)
            self.update_timer.timeout.connect(self.check_all_updates)
            self.watcher = QFileSystemWatcher(self)
            self.watcher.directoryChanged.connect(self.downloads_changed)
            self.watch_timer = QTimer(self)
            self.watch_timer.setSingleShot(True)
            self.watch_timer.timeout.connect(self.watch_ready)
            self.pending_downloads = {}
            self.tray = QSystemTrayIcon(QIcon(str(Path(__file__).parent / "assets/app.svg")), self)
            menu = QMenu(self)
            show = menu.addAction("Open OptiDX Desktop")
            show.triggered.connect(lambda: (self.show(), self.raise_(), self.activateWindow()))
            menu.addAction("Check updates").triggered.connect(self.check_all_updates)
            menu.addAction("Quit").triggered.connect(self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(
                lambda reason: (
                    self.show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
                )
            )
        if self.service_settings.get("background_checks"):
            self.update_timer.start(4 * 3600 * 1000)
        else:
            self.update_timer.stop()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        folder = Path(self.service_settings.get("watch_folder", str(Path.home() / "Downloads")))
        self.watch_seen = (
            {
                str(p): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in folder.glob("*")
                if p.is_file()
            }
            if folder.is_dir()
            else {}
        )
        if self.service_settings.get("watch_downloads") and folder.is_dir():
            self.watcher.addPath(str(folder))
        if self.service_settings.get("tray") and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            self.tray.hide()

    def startup_maintenance(self):
        """Prune stale download caches and optionally look for a newer app release."""
        from .usage import CACHE_MAX_AGE_DAYS, clean_download_caches

        try:
            clean_download_caches(self.repository, CACHE_MAX_AGE_DAYS)
        except OSError as error:
            self.log.appendPlainText("Download cache cleanup skipped: " + str(error))
        if self.service_settings.get("app_update_checks"):
            self.check_app_update(manual=False)

    def check_app_update(self, manual=True):
        if self.app_update_thread is not None and self.app_update_thread.isRunning():
            return
        self.app_update_thread = AppUpdateThread(self.repository.directory, self)
        self.app_update_thread.completed.connect(
            lambda release, error: self.app_update_finished(release, error, manual)
        )
        if manual:
            self.statusBar().showMessage("Checking for a newer OptiDX Desktop release…", 4000)
        self.app_update_thread.start()

    def app_update_finished(self, release, error, manual):
        self.app_update_release = release
        if release:
            self.app_update_button.setText(f"Desktop {release['version']} available")
            self.app_update_button.show()
            self.log.appendPlainText(
                f"OptiDX Desktop {release['version']} is available: {release['url']}"
            )
        else:
            self.app_update_button.hide()
        if manual:
            self.statusBar().showMessage(
                (
                    "Could not check for app updates: " + error
                    if error
                    else (
                        f"OptiDX Desktop {release['version']} is available"
                        if release
                        else f"OptiDX Desktop {__version__} is up to date"
                    )
                ),
                8000,
            )

    def open_app_release(self):
        if self.app_update_release:
            open_url(self.app_update_release["url"])

    def downloads_changed(self, directory):
        self.pending_downloads.clear()
        for path in Path(directory).glob("*"):
            if path.is_file() and path.suffix.lower() in {
                ".addon",
                ".addon32",
                ".addon64",
                ".ini",
                ".zip",
                ".7z",
            }:
                record = (path.stat().st_size, path.stat().st_mtime_ns)
                if self.watch_seen.get(str(path)) != record:
                    self.pending_downloads[str(path)] = record
        self.watch_timer.start(3000)

    def watch_ready(self):
        for name, record in self.pending_downloads.copy().items():
            path = Path(name)
            if path.is_file() and (path.stat().st_size, path.stat().st_mtime_ns) == record:
                self.watch_seen[name] = record
                self.log.appendPlainText("New mod/preset download available to import: " + name)
                if self.tray.isVisible():
                    self.tray.showMessage(
                        "Mod download detected", path.name + " — use Import addon / preset / shader"
                    )
            else:
                self.watch_timer.start(3000)
