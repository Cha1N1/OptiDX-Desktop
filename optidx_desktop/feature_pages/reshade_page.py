"""ReShade shaders, effects, addons and presets."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import assets
from ..catalog import catalogs

from ..widgets import help_label, push, section


class ReShadeContentPage:
    def build_assets(self):
        layout = self.page("ReShade content")
        layout.addWidget(
            help_label(
                "Add effects and addons to an existing ReShade installation. Each action below installs only the named content."
            )
        )
        tabs = QTabWidget()
        layout.addWidget(tabs)

        def tab(name):
            page = QWidget()
            box = QVBoxLayout(page)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(page)
            tabs.addTab(area, name)
            return box

        shaders = tab("Shader packs")
        self.shader_list = QListWidget()
        self.shader_list.setMinimumHeight(220)
        shaders.addWidget(self.shader_list)
        row = QHBoxLayout()
        row.addWidget(push("Install checked shader packs", self.install_shaders))
        row.addWidget(push("Choose effects from a pack", self.choose_effects))
        shaders.addLayout(row)
        advanced = section(shaders, "Remove packs / export a bundle", expanded=False)
        advanced.addWidget(push("Remove unchecked managed shader packs", self.prune_shaders))
        advanced.addWidget(push("Export shader/preset bundle", self.export_bundle))
        imports = tab("Addons & presets")
        imports.addWidget(QLabel("Download an addon from the catalog"))
        self.addon_catalog = QComboBox()
        imports.addWidget(self.addon_catalog)
        imports.addWidget(
            push(
                "Install this catalog addon",
                lambda: self.job("deploy_catalog_addon", {"id": self.addon_catalog.currentData()}),
            )
        )
        imports.addWidget(QLabel("Install a file from your import library"))
        self.asset_library = QComboBox()
        imports.addWidget(self.asset_library)
        imports.addWidget(
            push(
                "Install this imported item",
                lambda: self.job("deploy_asset", {"id": self.asset_library.currentData()}),
            )
        )
        library = section(imports, "Add files to the import library", expanded=False)
        library.addWidget(
            help_label(
                "Importing stores a copy in the app library. Use Install this imported item to copy it into this game."
            )
        )
        library.addWidget(push("Import addon / preset / shader file", self.import_dialog))
        library.addWidget(push("Import from HTTPS URL", self.import_url_dialog))
        imports.addStretch()
        display = tab("ReShade settings")
        display.addWidget(
            help_label(
                "These controls edit ReShade.ini or the selected preset. They do not install ReShade or any shader pack."
            )
        )
        form = QFormLayout()
        self.line(form, "screenshot_path", "Screenshot folder")
        self.line(form, "reshade_hotkey", "Overlay hotkey", "e.g. 36,0,0,0 (Home)")
        self.line(form, "peak_nits", "Preset peak brightness (nits)", "Optional; 80–10000")
        display.addLayout(form)
        display.addWidget(push("Apply ReShade configuration", lambda: self.job("apply_display")))
        display.addStretch()
        managed = self.page("Installed tools")
        managed.addWidget(
            help_label(
                "Optional tools, shader packs and DLL replacements already managed in this game. Removing a group restores its original files. Core components are removed from Installation."
            )
        )
        self.managed = QListWidget()
        self.managed.setMinimumHeight(160)
        managed.addWidget(self.managed)
        row = QHBoxLayout()
        row.addWidget(push("Enable selected addon", lambda: self.toggle(True)))
        row.addWidget(push("Disable selected addon", lambda: self.toggle(False)))
        row.addWidget(push("Remove selected group / restore originals", self.remove_group))
        managed.addLayout(row)
        managed.addStretch()

    def load_shader_choices(self, selected):
        from PySide6.QtCore import QSignalBlocker

        _blocker = QSignalBlocker(self.shader_list)
        self.shader_list.clear()
        for key, pack in sorted(
            catalogs(self.repository).items(), key=lambda p: p[1]["label"].casefold()
        ):
            item = QListWidgetItem(pack["label"])
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked
            )
            self.shader_list.addItem(item)

    def import_dialog(self, path=""):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self.window,
                "Import asset",
                str(Path.home() / "Downloads"),
                "Mods/presets (*.addon *.addon32 *.addon64 *.ini *.fx *.zip *.7z *.rar)",
            )
        if not path:
            return
        kind = (
            "preset"
            if Path(path).suffix.lower() == ".ini"
            else "shader" if Path(path).suffix.lower() == ".fx" else "addon"
        )
        if Path(path).suffix.lower() in {".zip", ".7z", ".rar"}:
            kind, ok = QInputDialog.getItem(
                self.window, "Package type", "Contents", ["addon", "shader"], 0, False
            )
            if not ok:
                return
        self.job("import_asset", {"path": path, "kind": kind}, lambda data: self.refresh())

    def import_url_dialog(self):
        url, ok = QInputDialog.getText(
            self.window, "Import URL", "HTTPS URL to an addon, archive or preset"
        )
        if ok and url.strip():
            kind, accepted = QInputDialog.getItem(
                self.window, "Asset type", "Contents", ["addon", "preset", "shader"], 0, False
            )
            if accepted:
                self.job(
                    "import_url", {"url": url.strip(), "kind": kind}, lambda data: self.refresh()
                )

    def install_shaders(self):
        if not self.window.selected:
            return
        selected = {
            self.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.shader_list.count())
            if self.shader_list.item(i).checkState() == Qt.CheckState.Checked
        }
        catalog = catalogs(self.repository)
        installed = (
            set(assets.state(self.window.selected.target)["groups"])
            if self.window.selected
            else set()
        )
        ordered = []
        visiting = set()

        def visit(key):
            if key in ordered:
                return
            if key in visiting:
                raise ValueError("Shader dependency cycle: " + key)
            visiting.add(key)
            for dependency in catalog[key].get("requires", []):
                if dependency in selected:
                    visit(dependency)
                elif "shader:" + dependency not in installed:
                    raise ValueError("Select or install the required shader pack: " + dependency)
            visiting.remove(key)
            ordered.append(key)

        try:
            for key in sorted(selected):
                visit(key)
        except (KeyError, ValueError) as error:
            self.window.report_error(str(error))
            return
        self.job("deploy_shaders", {"ids": ordered})

    def choose_effects(self):
        item = self.shader_list.currentItem()
        game = self.window.selected
        if not item or not game:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        from ..models import Game

        game = Game.from_dict(game.to_dict())

        def finished(data):
            if (
                self.window.selected
                and self.window.selected.id == game.id
                and self.window.selected.target == game.target
            ):
                self.effect_picker(data, game)
            else:
                self.window.statusBar().showMessage(
                    "Effect selection cancelled because the selected game changed", 5000
                )

        self.job("shader_files", {"id": key}, finished)

    def effect_picker(self, data, game=None):
        game = game or self.window.selected
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Choose effects · " + data["id"])
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        for name in data["files"]:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            choices.addItem(item)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            selected = [
                choices.item(i).text()
                for i in range(choices.count())
                if choices.item(i).checkState() == Qt.CheckState.Checked
            ]
            self.window.enqueue_feature(
                "deploy_shader", {"id": data["id"], "selected": selected}, game=game
            )

    def prune_shaders(self):
        if not self.window.selected:
            return
        selected = {
            self.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.shader_list.count())
            if self.shader_list.item(i).checkState() == Qt.CheckState.Checked
        }
        for group in assets.state(self.window.selected.target)["groups"]:
            if group.startswith("shader:") and group.split(":", 1)[1] not in selected:
                self.job("remove_asset", {"group": group})

    def toggle(self, enabled):
        item = self.managed.currentItem()
        if item:
            self.job("toggle_asset", {**item.data(Qt.ItemDataRole.UserRole), "enabled": enabled})

    def remove_group(self):
        item = self.managed.currentItem()
        if item:
            self.job("remove_asset", item.data(Qt.ItemDataRole.UserRole))
