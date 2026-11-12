"""DLSS/Streamline DLL version selection and replacement."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from ..storage import read_json, atomic_json

from ..widgets import help_label, push, section


class GameDllPage:
    def build_versions(self):
        layout = self.page("Game DLLs")
        self.versions_layout = layout
        layout.addWidget(
            help_label(
                "Swap DLSS SR, RR, FG, neural rendering or Streamline. Select the actual DLL folder: Unreal games often keep these under Engine/Plugins. Original files are retained and can be restored."
            )
        )
        self.dll_paths = QPlainTextEdit()
        self.dll_paths.setReadOnly(True)
        self.dll_paths.setMaximumHeight(120)
        layout.addWidget(self.dll_paths)
        form = QFormLayout()
        self.dll_kind = QComboBox()
        for label, key in [
            ("DLSS Super Resolution", "dlss"),
            ("DLSS Ray Reconstruction", "dlssd"),
            ("DLSS Frame Generation", "dlssg"),
            ("DLSS Neural Rendering", "dlssnr"),
            ("Streamline", "streamline"),
        ]:
            self.dll_kind.addItem(label, key)
        self.dll_version = QComboBox()
        self.dll_version.setEditable(True)
        self.dll_kind.currentIndexChanged.connect(self.version_choices)
        self.dll_folder = QLineEdit()
        self.dll_folder.setPlaceholderText(
            "Relative to the game root; empty = selected executable folder"
        )
        form.addRow("Component", self.dll_kind)
        form.addRow("Version", self.dll_version)
        folder = QWidget()
        folder_row = QHBoxLayout(folder)
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.addWidget(self.dll_folder)
        folder_row.addWidget(push("Browse", self.choose_dll_folder))
        form.addRow("DLL folder", folder)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(push("Replace selected DLL with this version", self.swap))
        row.addWidget(push("Replace selected DLL from a local file", self.custom_dll))
        layout.addLayout(row)
        update_form = QFormLayout()
        self.check(
            update_form, "auto_update_dlss", "Use Latest for managed DLSS/Streamline during updates"
        )
        layout.addLayout(update_form)
        layout.addWidget(
            help_label(
                "Restore original DLLs from Installed tools. Replacing a DLL does not add DLSS GPU support."
            )
        )
        layout = section(layout, "Neural Rendering Cost Scaler", expanded=False)
        layout.addWidget(
            help_label(
                "Installs a proxy beside the selected Neural Rendering DLL. This is separate from replacing a DLSS version."
            )
        )
        form = QFormLayout()
        self.line(
            form, "nr_cost_scale", "NR Cost Scaler resolution scale", "Default 0.75; 0.25–2.0"
        )
        layout.addLayout(form)
        layout.addWidget(
            push(
                "Enable NR Cost Scaler in selected DLL folder",
                lambda: self.job("nr_cost_scaler", {"target_dir": self.dll_folder.text().strip()}),
            )
        )
        layout.addWidget(
            push(
                "Remove NR Cost Scaler / keep real NR DLL",
                lambda: self.job(
                    "nr_cost_scaler",
                    {"target_dir": self.dll_folder.text().strip(), "enabled": False},
                ),
            )
        )
        layout = section(
            self.versions_layout, "Shared DLL defaults and batch replacement", expanded=False
        )
        layout.addWidget(push("Replace this DLL in selected games…", self.batch_dll))
        layout.addWidget(push("Save these DLL choices as global defaults", self.save_dll_defaults))
        layout.addWidget(push("Load global DLL defaults", self.load_dll_defaults))
        layout.addStretch()

    def discover_dlls(self, game):
        from ..ui_tasks import discover_dlls

        self.dll_paths.setPlainText("Looking for existing DLSS/Streamline DLLs…")
        discover_dlls(self.window, game, self.dll_paths)

    def version_choices(self):
        current = self.dll_version.currentText()
        self.dll_version.clear()
        self.dll_version.addItem("Latest")
        manifest = read_json(self.repository.directory / "dlss-manifest.json", {})
        self.dll_version.addItems(
            [x["version"] for x in manifest.get(self.dll_kind.currentData(), [])]
        )
        if current:
            self.dll_version.setCurrentText(current)

    def choose_dll_folder(self):
        if not self.window.selected:
            return
        root = Path(self.window.selected.root).resolve()
        folder = QFileDialog.getExistingDirectory(self.window, "Choose DLL folder", str(root))
        if folder:
            try:
                self.dll_folder.setText(str(Path(folder).resolve().relative_to(root)))
            except ValueError:
                self.window.report_error("Select a directory inside this game installation")

    def swap(self):
        self.job(
            "swap_dll",
            {
                "kind": self.dll_kind.currentData(),
                "version": self.dll_version.currentText(),
                "target_dir": self.dll_folder.text().strip(),
            },
        )

    def custom_dll(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Custom DLL or package",
            str(Path.home()),
            "DLLs/archives (*.dll *.zip *.7z)",
        )
        if path:
            self.job(
                "swap_dll",
                {
                    "kind": self.dll_kind.currentData(),
                    "path": path,
                    "target_dir": self.dll_folder.text().strip(),
                },
            )

    def batch_dll(self):
        options = {
            "kind": self.dll_kind.currentData(),
            "version": self.dll_version.currentText(),
            "target_dir": self.dll_folder.text().strip(),
        }
        for game in self.games_picker():
            self.window.enqueue_feature("swap_dll", options, game=game)

    def save_dll_defaults(self):
        atomic_json(
            self.repository.directory / "dll-defaults.json",
            {"kind": self.dll_kind.currentData(), "version": self.dll_version.currentText()},
        )

    def load_dll_defaults(self):
        data = read_json(self.repository.directory / "dll-defaults.json", {})
        self.dll_kind.setCurrentIndex(max(self.dll_kind.findData(data.get("kind")), 0))
        self.dll_version.setCurrentText(data.get("version", "Latest"))
