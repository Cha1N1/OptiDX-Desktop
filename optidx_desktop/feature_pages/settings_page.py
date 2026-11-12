"""Game profile sharing plus app-wide settings and storage."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import assets
from ..catalog import game_data
from ..storage import read_json, atomic_json

from ..widgets import help_label, push, section


class ProfileSettingsPage:
    def build_library_settings(self):
        layout = self.page("Game profile")
        form = QFormLayout()
        self.check(form, "favourite", "Favourite this game")
        self.check(form, "hidden", "Hide this game from the normal library")
        self.line(form, "display_name", "Display name override")
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(push("Export game profile", self.export_profile))
        row.addWidget(push("Import game profile", self.import_profile))
        row.addWidget(push("Reset game overrides", self.reset_profile))
        layout.addLayout(row)
        layout.addWidget(push("Check updates for this game", lambda: self.job("check_updates")))
        layout = section(
            layout, "Share this profile / apply settings to other games", expanded=False
        )
        layout.addWidget(push("Save as shared profile", self.save_named_profile))
        layout.addWidget(push("Apply shared profile to selected games", self.batch_profile))
        layout.addWidget(push("Batch apply HDR/FG/display settings", self.batch_settings))
        self.update_info = QPlainTextEdit()
        self.update_info.setReadOnly(True)
        self.update_info.setMaximumHeight(130)
        layout.addWidget(self.update_info)
        self.app_dialog = QDialog(self.window)
        self.app_dialog.setWindowTitle("OptiDX Desktop — app settings")
        self.app_dialog.resize(680, 640)
        # Settings outgrow small screens; keep every section reachable.
        dialog_layout = QVBoxLayout(self.app_dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        dialog_layout.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.addWidget(
            help_label("Library-wide settings. These controls do not install files into any game.")
        )
        layout.addWidget(
            push("Refresh shader / addon / DLL catalogs", lambda: self.job("refresh_catalogs"))
        )
        layout.addWidget(push("Check updates for all managed games", self.window.check_all_updates))
        self.retain_backups = QCheckBox("Keep operation snapshots after jobs (off by default)")
        self.backup_limit = QSpinBox()
        self.backup_limit.setRange(1, 50)
        self.backup_limit.setSuffix(" snapshots per game")
        self.app_background = QCheckBox("Check for updates every 4 hours while the app is running")
        self.reduce_motion = QCheckBox(
            "Reduce motion (disable animations and accelerated smooth scrolling)"
        )
        self.app_tray = QCheckBox("Keep the app in the system tray when closing")
        self.watch_downloads = QCheckBox("Watch a folder for newly downloaded addons and presets")
        self.watch_folder = QLineEdit()
        self.watch_folder.setPlaceholderText(str(Path.home() / "Downloads"))
        settings = read_json(self.repository.directory / "settings.json", {})
        self.theme_choice = QComboBox()
        self.theme_choice.setToolTip(
            "Dark keeps the original navy/teal look. System uses the actual desktop Qt palette, including accent and selection colors."
        )
        for label, key in [("Dark", "dark"), ("Light", "light"), ("System", "system")]:
            self.theme_choice.addItem(label, key)
        self.theme_choice.setCurrentIndex(
            max(0, self.theme_choice.findData(self.window.theme.mode))
        )
        theme_form = QFormLayout()
        theme_form.addRow("Appearance (applies immediately)", self.theme_choice)
        layout.addLayout(theme_form)
        self.theme_choice.currentIndexChanged.connect(self.change_theme)
        self.retain_backups.setChecked(settings.get("retain_backups", False))
        self.backup_limit.setValue(max(1, min(50, int(settings.get("backup_limit", 3)))))
        self.backup_limit.setEnabled(self.retain_backups.isChecked())
        self.retain_backups.toggled.connect(self.backup_limit.setEnabled)
        self.reduce_motion.setChecked(settings.get("reduce_motion", False))
        self.app_background.setChecked(settings.get("background_checks", False))
        self.app_tray.setChecked(settings.get("tray", False))
        self.watch_downloads.setChecked(settings.get("watch_downloads", False))
        self.watch_folder.setText(settings.get("watch_folder", str(Path.home() / "Downloads")))
        for widget in [
            self.app_background,
            self.app_tray,
            self.watch_downloads,
            self.watch_folder,
            self.reduce_motion,
        ]:
            layout.addWidget(widget)
        layout.addWidget(self.retain_backups)
        layout.addWidget(self.backup_limit)
        layout.addWidget(
            help_label(
                "Rollback stays automatic during jobs. Verified originals stay available for removal. Interrupted jobs requiring recovery are retained."
            )
        )
        self.app_update_checks = QCheckBox(
            "Check GitHub for new OptiDX Desktop releases at startup (never installs anything)"
        )
        self.app_update_checks.setChecked(settings.get("app_update_checks", False))
        layout.addWidget(self.app_update_checks)
        layout.addWidget(push("Check for an app update now", self.window.check_app_update))
        storage = section(layout, "Storage", expanded=False)
        # One short line per category; word wrapping clips inside animated sections.
        self.storage_summary = QLabel()
        self.storage_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        storage.addWidget(self.storage_summary)
        storage.addWidget(
            help_label(
                "Download caches are re-fetched when needed; entries unused for 30 days are "
                "removed automatically at startup. Backups, verified originals and imports are "
                "never deleted by cache cleanup."
            )
        )
        storage_row = QHBoxLayout()
        storage_row.addWidget(push("Refresh usage", self.refresh_storage))
        storage_row.addWidget(push("Clear download caches…", self.clear_caches))
        storage.addLayout(storage_row)
        storage.addWidget(push("Delete completed operation snapshots…", self.cleanup_backups))
        layout.addWidget(push("Save app settings", self.save_app_settings))
        layout.addWidget(
            push(
                "Open app data / backups",
                lambda: self.window.open_directory(self.repository.directory),
            )
        )
        layout.addWidget(
            push(
                "Open custom imports",
                lambda: self.window.open_directory(self.repository.directory / "custom"),
            )
        )
        self.window.status_box.addWidget(push("PCGamingWiki search for this game", self.pcgw))
        self.window.status_box.addWidget(push("Show compatibility notes for this game", self.notes))
        layout.addWidget(
            help_label(
                "Imports and background checks do not automatically modify game folders. Your install/update queue remains under your control."
            )
        )
        layout.addWidget(push("Close app settings", self.app_dialog.accept))
        layout.addStretch()

    def change_theme(self, *args):
        mode = self.theme_choice.currentData()
        settings = read_json(self.repository.directory / "settings.json", {})
        atomic_json(self.repository.directory / "settings.json", {**settings, "theme": mode})
        self.window.theme.set_mode(mode)

    def save_app_settings(self):
        atomic_json(
            self.repository.directory / "settings.json",
            {
                **read_json(self.repository.directory / "settings.json", {}),
                "background_checks": self.app_background.isChecked(),
                "tray": self.app_tray.isChecked(),
                "watch_downloads": self.watch_downloads.isChecked(),
                "watch_folder": self.watch_folder.text().strip(),
                "reduce_motion": self.reduce_motion.isChecked(),
                "retain_backups": self.retain_backups.isChecked(),
                "backup_limit": self.backup_limit.value(),
                "app_update_checks": self.app_update_checks.isChecked(),
            },
        )
        self.window.configure_services()
        self.window.statusBar().showMessage("App settings saved", 4000)

    def open_app_settings(self):
        self.refresh_storage()
        self.app_dialog.exec()

    def refresh_storage(self):
        from ..usage import human, usage

        rows = usage(self.repository)
        self.storage_summary.setText(
            "\n".join(
                f"{label}: {human(size)}" + (" · disposable" if disposable else "")
                for label, path, size, disposable in rows
            )
            + f"\nTotal: {human(sum(row[2] for row in rows))}"
        )

    def clear_caches(self):
        from PySide6.QtWidgets import QMessageBox
        from ..usage import clean_download_caches, human

        if self.window.process is not None:
            self.window.report_error("Finish the running job before clearing download caches.")
            return
        answer = QMessageBox.question(
            self.window,
            "Clear download caches",
            "Delete all cached downloads? Components are downloaded again the next time a "
            "job needs them. Backups, originals, imports and profiles are not affected.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = clean_download_caches(self.repository, 0)
        if result is None:
            self.window.report_error("A job is running. Finish it before clearing caches.")
            return
        self.refresh_storage()
        self.window.statusBar().showMessage(
            f"Removed {result[0]} cached downloads ({human(result[1])})", 6000
        )

    def cleanup_backups(self):
        if self.window.process is not None:
            self.window.report_error("Finish the running job before cleaning snapshots.")
            return
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self.window,
            "Delete completed snapshots",
            "Delete completed operation snapshots for all library games? Original-file recovery data and interrupted jobs are kept.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            from ..backups import cleanup_completed_snapshots

            count = cleanup_completed_snapshots(self.repository)
            self.refresh_storage()
            self.window.refresh_workflow()
            self.window.statusBar().showMessage(f"Deleted {count} completed snapshots", 6000)
        except (OSError, ValueError) as error:
            self.window.report_error(str(error))

    def export_profile(self):
        if not self.window.selected:
            return
        try:
            profile = self.window.profile()
            path, _ = QFileDialog.getSaveFileName(
                self.window,
                "Export profile",
                self.window.selected.title + ".json",
                "Profiles (*.json)",
            )
            if path:
                atomic_json(path, {"format": "optidx-profile-v1", "preferences": profile})
        except (ValueError, TypeError, OSError) as error:
            self.window.report_error(str(error))

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window, "Import profile", str(Path.home()), "Profiles (*.json)"
        )
        if not path or not self.window.selected:
            return
        try:
            data = read_json(path, {})
            if data.get("format") != "optidx-profile-v1" or not isinstance(
                data.get("preferences"), dict
            ):
                raise ValueError("Invalid OptiDX profile")
            from ..backend import selected_components

            selected_components(data["preferences"])
            self.repository.save_preferences(self.window.selected, data["preferences"])
            self.window.load_profile()
        except Exception as e:
            self.window.report_error(str(e))

    def reset_profile(self):
        if self.window.selected:
            self.repository.save_preferences(self.window.selected, {})
            self.window.load_profile()

    def save_named_profile(self):
        try:
            profile = self.window.profile()
            name, ok = QInputDialog.getText(self.window, "Shared profile", "Name")
            if ok and name.strip():
                data = read_json(self.repository.directory / "shared-profiles.json", {})
                data[name.strip()] = profile
                atomic_json(self.repository.directory / "shared-profiles.json", data)
        except (ValueError, TypeError, OSError) as error:
            self.window.report_error(str(error))

    def games_picker(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Select games")
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        for game in self.window.games:
            if not game.available or not game.executable:
                continue
            item = QListWidgetItem(game.title)
            item.setData(Qt.ItemDataRole.UserRole, game.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            choices.addItem(item)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if not dialog.exec():
            return []
        selected = {
            choices.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(choices.count())
            if choices.item(i).checkState() == Qt.CheckState.Checked
        }
        return [g for g in self.window.games if g.id in selected]

    def batch_profile(self):
        profiles = read_json(self.repository.directory / "shared-profiles.json", {})
        name, ok = QInputDialog.getItem(
            self.window, "Shared profile", "Choose profile", list(profiles), 0, False
        )
        if ok and name in profiles:
            # Machine/game-specific paths and names never transfer between games.
            excluded = {
                "upscaler_helix_fsr4_dll",
                "upscaler_helix_dlss_dll",
                "upscaler_cyboman_archive",
                "upscaler_cyboman_target",
                "prefix",
                "config_dir",
                "executable",
                "launch_executable",
                "display_name",
                "hidden",
                "favourite",
                "runner_command",
                "runner_kind",
                "hdr_output",
                "dll_folder",
                "vkbasalt_config",
                "reframework_asset",
                "ue_version",
                "wiki_name",
                "launch_arguments",
                "extra_sources",
                "api_override",
                "bits_override",
                "proxy_override",
                "environment",
            }
            common = {k: v for k, v in profiles[name].items() if k not in excluded}
            for game in self.games_picker():
                old = self.repository.preferences(game)
                self.repository.save_preferences(game, {**old, **common})
            self.window.load_profile()

    def batch_settings(self):
        for game in self.games_picker():
            self.window.enqueue_feature("configure", game=game)
            self.window.enqueue_feature("apply_display", game=game)

    def export_bundle(self):
        if not self.window.selected:
            return
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export shader/preset bundle", "optidx-shaders.zip", "ZIP (*.zip)"
        )
        if not path:
            return
        import zipfile

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for group in assets.state(self.window.selected.target)["groups"].values():
                if group["metadata"].get("kind") in {"shader", "preset"}:
                    for name in group["files"]:
                        file = self.window.selected.target / name
                        if file.is_file():
                            z.write(file, name)
            z.writestr(
                "optidx-profile.json",
                json.dumps(
                    {"format": "optidx-profile-v1", "preferences": self.window.profile()}, indent=2
                ),
            )

    def pcgw(self):
        if self.window.selected:
            from urllib.parse import quote
            from ..runtime import open_url

            open_url(
                "https://www.pcgamingwiki.com/w/index.php?search="
                + quote(self.window.selected.title)
            )

    def notes(self):
        if self.window.selected:
            self.window.report_error(
                json.dumps(game_data(self.repository, self.window.selected.title), indent=2)
            )
