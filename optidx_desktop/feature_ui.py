"""Native controls for shaders, addons, versions and Linux launch profiles."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import assets
from .pages import ProfilePage, bind
from .catalog import addon_catalog
from .storage import read_json


from .feature_pages.reshade_page import ReShadeContentPage
from .feature_pages.dll_page import GameDllPage
from .feature_pages.tools_page import OptionalToolsPage
from .feature_pages.launch_page import LaunchOptionsPage
from .feature_pages.settings_page import ProfileSettingsPage
from .widgets import help_label, push, section  # noqa: F401  (re-exported)


class Features(
    ReShadeContentPage,
    GameDllPage,
    OptionalToolsPage,
    LaunchOptionsPage,
    ProfileSettingsPage,
):
    def __init__(self, window):
        self.window = window
        self.repository = window.repository
        self.fields = {}
        self.drs = {}
        self.shader_checks = {}
        self.build_assets()
        self.build_versions()
        self.build_extras()
        self.build_launch()
        self.build_library_settings()
        for key, widget in self.drs.items():
            bind(widget, "drs:" + key)
        for key in ("environment", "dll_kind", "dll_version", "dll_folder"):
            bind(getattr(self, key), key if key != "environment" else "environment")

    def page(self, name):
        widget = ProfilePage()
        layout = QVBoxLayout(widget)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        self.window.tabs.addTab(area, name)
        return layout

    def combo(self, form, key, label, values):
        widget = QComboBox()
        for text, value in values:
            widget.addItem(text, value)
        self.fields[key] = bind(widget, "feature:" + key)
        form.addRow(label, widget)
        return widget

    def line(self, form, key, label, placeholder=""):
        widget = QLineEdit()
        widget.setPlaceholderText(placeholder)
        self.fields[key] = bind(widget, "feature:" + key)
        form.addRow(label, widget)
        return widget

    def file_line(self, form, key, label, pattern):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit()
        self.fields[key] = bind(field, "feature:" + key)
        row.addWidget(field)

        def choose():
            path, _ = QFileDialog.getOpenFileName(
                self.window, label, field.text() or str(Path.home()), pattern
            )
            if path:
                field.setText(path)

        row.addWidget(push("Browse", choose))
        form.addRow(label, widget)
        return field

    def check(self, form, key, label):
        widget = QCheckBox(label)
        self.fields[key] = bind(widget, "feature:" + key)
        form.addRow(widget)
        return widget

    def preferences(self):
        values = {}
        for key, widget in self.fields.items():
            values[key] = (
                widget.isChecked()
                if isinstance(widget, QCheckBox)
                else (
                    widget.currentData() if isinstance(widget, QComboBox) else widget.text().strip()
                )
            )
        from .launch import environment_overrides

        values["environment"] = environment_overrides(
            json.loads(self.environment.toPlainText() or "{}")
        )
        values["drs"] = {k: w.currentData() for k, w in self.drs.items() if w.currentData()}
        values["shader_packs"] = [
            self.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.shader_list.count())
            if self.shader_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        values["exclude_components"] = [
            v.strip() for v in values.pop("exclude_components_text", "").split(",") if v.strip()
        ]
        values["extra_sources"] = self.extra_sources
        values["dll_kind"] = self.dll_kind.currentData()
        values["dll_version"] = self.dll_version.currentText()
        values["dll_folder"] = self.dll_folder.text().strip()
        # Unchecked optional launch controls preserve the launcher's defaults.
        for key in (
            "PROTON_ENABLE_WAYLAND",
            "PROTON_ENABLE_HDR",
            "DXVK_NVAPI_VKREFLEX",
            "PROTON_ENABLE_NGX_UPDATER",
        ):
            if not values[key]:
                values[key] = None
        return values

    def load(self, profile):
        for key, widget in self.fields.items():
            value = profile.get(key, "")
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(widget.findData(value), 0))
            else:
                widget.setText(str(value))
        self.fields["exclude_components_text"].setText(
            ",".join(profile.get("exclude_components", []))
        )
        self.environment.setPlainText(json.dumps(profile.get("environment", {}), indent=2))
        for key, widget in self.drs.items():
            widget.setCurrentIndex(max(widget.findData(profile.get("drs", {}).get(key, "")), 0))
        self.extra_sources = profile.get("extra_sources", {}).copy()
        self.dll_kind.setCurrentIndex(max(self.dll_kind.findData(profile.get("dll_kind")), 0))
        self.version_choices()
        self.dll_version.setCurrentText(profile.get("dll_version", "Latest"))
        self.dll_folder.setText(profile.get("dll_folder", ""))
        self.load_shader_choices(profile.get("shader_packs", []))
        self.refresh_upscaler_picker()

    def refresh(self):
        self.refresh_helix_action()
        self.addon_catalog.clear()
        for key, item in addon_catalog(self.repository).items():
            self.addon_catalog.addItem(item["label"], key)
        self.asset_library.clear()
        for key, item in read_json(self.repository.directory / "assets.json", {}).items():
            self.asset_library.addItem(item["label"] + " · " + item["kind"], key)
        self.managed.clear()
        game = self.window.selected
        if game:
            scopes = {str(game.target): "target", str(game.root): "root"}
            for root, scope in scopes.items():
                try:
                    groups = assets.state(root)["groups"]
                except (OSError, ValueError):
                    continue  # Reported once in the diagnostics notes.
                for key, record in groups.items():
                    if key.startswith("backend:"):
                        continue
                    item = QListWidgetItem(
                        key + " · " + str(record["metadata"].get("version", "Custom"))
                    )
                    item.setData(Qt.ItemDataRole.UserRole, {"group": key, "scope": scope})
                    self.managed.addItem(item)
            self.discover_dlls(game)
            info = read_json(self.repository.directory / "updates" / (game.id + ".json"), {})
            self.update_info.setPlainText(
                json.dumps(info, indent=2) if info else "No update check recorded yet."
            )
        self.version_choices()

    def refresh_helix_action(self):
        game = self.window.selected
        managed = False
        if game:
            from .inspection import manifest_paths

            try:
                record = read_json(game.target / ".optidx-components.json", {})
                files = record.get("files", {}).get("helixsr", [])
                managed = bool(files) or any(
                    path.casefold().startswith("optiscaler/helixsr/")
                    for path in manifest_paths(game.target)
                )
            except ValueError:
                managed = False
        self.remove_helix_button.setEnabled(managed and self.window.process is None)

    def remove_helixsr(self):
        game = self.window.selected
        if not game:
            return

        def finished(data):
            if self.window.selected and self.window.selected.id == game.id:
                self.window.components["helixsr"].setChecked(False)

        self.job("remove_helixsr", callback=finished)

    def job(self, action, options=None, callback=None):
        if callback is None and action == "refresh_catalogs":

            def callback(data):
                selected = [
                    self.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.shader_list.count())
                    if self.shader_list.item(i).checkState() == Qt.CheckState.Checked
                ]
                self.load_shader_choices(selected)
                self.refresh()

        self.window.form_changed()
        self.window.enqueue_feature(action, options or {}, callback)
