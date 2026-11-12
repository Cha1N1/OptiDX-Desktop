"""Optional tools, neural adapters, Vulkan effects and config editing."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..catalog import EXTRAS

from ..widgets import help_label, push, section


class OptionalToolsPage:
    def build_extras(self):
        from ..upscaler_ui import build

        build(self)
        self.remove_helix_button = push(
            "Remove HelixSR / restore previous AMD DLL", self.remove_helixsr
        )
        self.window.overview.add_maintenance_widget(self.remove_helix_button)
        helix_hint = help_label(
            "This removes managed HelixSR and restores the previous AMD upscaler DLL when a verified backup exists. It unchecks HelixSR for future updates. Simply unchecking a component leaves its files installed."
        )
        self.window.overview.add_maintenance_widget(helix_hint)
        layout = self.window.overview.add_section(
            "Component download sources and advanced detection"
        )
        layout.addWidget(
            help_label(
                "Choose download sources for checked OptiScaler and ReShade components. Installation uses these choices; this section has no separate installer."
            )
        )
        form = QFormLayout()
        self.combo(
            form,
            "reshade_channel",
            "ReShade channel",
            [
                (x.replace("_", " ").title(), x)
                for x in ["stable", "nightly", "custom", "legacy", "no_addons"]
            ],
        )
        self.line(form, "reshade_version", "Pinned ReShade version", "Used by Legacy")
        self.file_line(
            form,
            "reshade_custom",
            "Custom ReShade DLL / archive",
            "Packages (*.dll *.exe *.zip *.7z)",
        )
        self.combo(
            form,
            "optiscaler_channel",
            "OptiScaler channel",
            [
                ("Backend default", ""),
                ("Stable", "stable"),
                ("Nightly (configured fork)", "nightly"),
                ("Upstream nightly (custom upscalers)", "upstream_nightly"),
                ("Custom archive", "custom"),
            ],
        )
        self.line(form, "optiscaler_tag", "Pinned OptiScaler tag", "Optional")
        self.line(
            form,
            "optiscaler_repo",
            "OptiScaler GitHub repository",
            "Optional owner/repository override",
        )
        self.file_line(
            form, "optiscaler_custom", "Custom OptiScaler archive", "Archives (*.7z *.zip)"
        )
        layout.addLayout(form)
        compatibility = section(
            self.window.configuration_box,
            "Advanced: game compatibility / existing file handling",
            expanded=False,
        )
        compatibility.addWidget(
            help_label(
                "Per-game overrides used by component and optional-tool installers. Auto detect is recommended. Allow replacing files affects all installs in this game."
            )
        )
        form = QFormLayout()
        self.combo(
            form,
            "api_override",
            "Graphics API",
            [("Auto detect", "")]
            + [(x, x) for x in ["DX9", "DX10", "DX11", "DX12", "OpenGL", "Vulkan"]],
        )
        self.combo(
            form,
            "bits_override",
            "Architecture",
            [("Auto detect", ""), ("32-bit", "32"), ("64-bit", "64")],
        )
        self.combo(
            form,
            "proxy_override",
            "Injection filename",
            [("Automatic", "")]
            + [
                (x, x)
                for x in [
                    "dxgi.dll",
                    "d3d9.dll",
                    "opengl32.dll",
                    "winmm.dll",
                    "version.dll",
                    "winhttp.dll",
                ]
            ],
        )
        self.check(
            form,
            "allow_foreign",
            "Allow replacing existing foreign files (originals are backed up)",
        )
        self.line(form, "wiki_name", "RenoDX wiki matching name")
        self.check(
            form, "force_ue_extended", "Prefer generic UE-Extended over the named RenoDX mod"
        )
        compatibility.addLayout(form)
        config = section(
            self.window.configuration_box,
            "Advanced: edit INI / apply an OptiScaler configuration preset",
            expanded=False,
        )
        config.addWidget(push("Edit an installed component INI", self.config_editor))
        from ..templates import TEMPLATES

        self.gpu_template = QComboBox()
        labels = {
            "nvidia": "NVIDIA GPU",
            "amd-dlss": "AMD GPU · RHI DLSS preset",
            "amd-nodlss": "AMD GPU · RHI non-DLSS preset",
        }
        for key in TEMPLATES:
            gpu, channel = key.rsplit("-", 1)
            self.gpu_template.addItem(labels[gpu] + " · " + channel.title() + " configuration", key)
        config.addWidget(
            help_label(
                "Optional RHI OptiScaler.ini presets. GPU/DLSS names are RHI’s preset labels. Stable/Nightly identifies the configuration variant. Preview the INI before applying it. This does not download a DLSS DLL or change the selected component release. Applying a preset changes OptiScaler settings while preserving library paths and explicit frame-generation choices."
            )
        )
        config.addWidget(self.gpu_template)
        config.addWidget(push("Download / open this editable INI preset", self.open_template))
        config.addWidget(
            push(
                "Apply this preset to OptiScaler.ini",
                lambda: self.job("apply_template", {"id": self.gpu_template.currentData()}),
            )
        )
        layout = self.page("Optional tools")
        tools = layout
        layout.addWidget(
            help_label(
                "Each tool has its own install button. Checking components on Installation does not install these tools."
            )
        )
        self.extra_sources = {}
        for key, item in EXTRAS.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(item["label"]), 1)
            row.addWidget(
                push("Install " + item["label"], lambda checked=False, k=key: self.install_extra(k))
            )
            row.addWidget(
                push("Choose custom package", lambda checked=False, k=key: self.custom_extra(k))
            )
            row.addWidget(
                push(
                    "Remove",
                    lambda checked=False, k=key: self.job("remove_asset", {"group": "extra:" + k}),
                )
            )
            layout.addLayout(row)
        layout = section(layout, "Advanced package selection", expanded=False)
        form = QFormLayout()
        self.line(form, "ue_version", "UE version override", "e.g. 5.4; used for DOF eligibility")
        self.line(
            form,
            "reframework_asset",
            "RE Framework archive name",
            "Choose the build for your game, e.g. DD2.zip",
        )
        self.line(
            form,
            "extra_asset_pattern",
            "Extra release asset filter",
            "Optional exact filename / regular expression",
        )
        update_form = QFormLayout()
        self.line(
            update_form,
            "exclude_components_text",
            "Update exclusions",
            "Comma-separated group/component IDs",
        )
        self.window.overview.add_maintenance_layout(update_form)
        layout.addLayout(form)
        layout = section(tools, "Custom DXVK installation", expanded=False)
        layout.addWidget(push("Install DXVK translation DLLs", lambda: self.job("install_dxvk")))
        layout.addWidget(
            help_label(
                "Proton already provides DXVK; custom local DXVK is optional and requires native DLL overrides in the launch profile. Frame limiters are mutually exclusive."
            )
        )
        layout = section(tools, "Neural rendering pipelines", expanded=False)
        neural_form = QFormLayout()
        self.file_line(
            neural_form, "neural_consumer", "Custom neural consumer addon", "Addons (*.addon64)"
        )
        layout.addLayout(neural_form)
        self.neural_method = QComboBox()
        self.neural_method.addItems(
            ["DLSS5 Feeder", "ShortFuse DLSS tool", "DX11 neural rendering bridge"]
        )
        layout.addWidget(self.neural_method)
        layout.addWidget(push("Install selected neural rendering pipeline", self.automatic_neural))
        layout.addWidget(
            push("Install selected pipeline from a local package", self.import_pipeline)
        )
        layout.addWidget(
            help_label(
                "Automatic setup downloads the selected pipeline and its dependencies. A custom consumer addon is optional. Only one neural pipeline can be active at a time."
            )
        )
        packages = section(tools, "Prepared RTX 40 MFG package", expanded=False)
        packages.addWidget(
            push("Install RTX 40 MFG unlock from a local package…", self.import_other_pipeline)
        )
        tools.addStretch()

    def install_extra(self, key):
        source = self.extra_sources.get(key, {}).copy()
        if key == "reframework" and not source.get("path"):
            name = self.fields["reframework_asset"].text().strip()
            if not name:
                self.window.report_error(
                    "Choose the RE Framework archive name for this game first."
                )
                return
            import re

            source["pattern"] = "^" + re.escape(name) + "$"
        if self.fields["extra_asset_pattern"].text().strip():
            source["pattern"] = self.fields["extra_asset_pattern"].text().strip()
        self.job("deploy_extra", {"id": key, "source": source})

    def custom_extra(self, key):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Custom " + EXTRAS[key]["label"],
            str(Path.home()),
            "Packages (*.zip *.7z *.addon64 *.addon32 *.asi)",
        )
        if path:
            self.extra_sources[key] = {"path": path, "version": "Custom"}
            self.window.form_changed()
            self.window.save_profile()
            self.install_extra(key)

    def automatic_neural(self):
        method = self.neural_method.currentText()
        if method not in {"ShortFuse DLSS tool", "DX11 neural rendering bridge", "DLSS5 Feeder"}:
            self.window.report_error(
                "Automatic setup supports Feeder, ShortFuse and the DX11 bridge. Choose those methods or import a prepared package for the others."
            )
            return
        sources = (
            {"consumer": {"path": self.fields["neural_consumer"].text().strip()}}
            if self.fields["neural_consumer"].text().strip()
            else {}
        )
        self.job(
            "deploy_neural_tool",
            {
                "sources": sources,
                "method": {
                    "ShortFuse DLSS tool": "shortfuse",
                    "DX11 neural rendering bridge": "bridge",
                    "DLSS5 Feeder": "feeder",
                }[method],
            },
        )

    def import_other_pipeline(self):
        method = "RTX 40 MFG unlock"
        path, _ = QFileDialog.getOpenFileName(
            self.window, "Install " + method, str(Path.home()), "Packages (*.zip *.7z)"
        )
        if path:
            self.job("deploy_pipeline", {"path": path, "method": method})

    def import_pipeline(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Import " + self.neural_method.currentText(),
            str(Path.home()),
            "Packages (*.zip *.7z)",
        )
        if path:
            self.job("deploy_pipeline", {"path": path, "method": self.neural_method.currentText()})

    def vulkan_effects(self):
        game = self.window.selected
        if not game:
            return
        choices = ["cas", "dls", "fxaa", "smaa"] + [
            str(p.relative_to(game.target))
            for p in (game.target / "reshade-shaders/OptiDX").rglob("*.fx")
        ]
        effect, ok = QInputDialog.getItem(
            self.window,
            "Vulkan effect",
            "Select a builtin or an installed ReShade effect",
            choices,
            0,
            False,
        )
        if ok:

            def finished(data):
                profile = self.repository.preferences(game)
                self.repository.save_preferences(game, {**profile, "vkbasalt_config": data["path"]})
                if self.window.selected and self.window.selected.id == game.id:
                    self.fields["vkbasalt_config"].setText(data["path"])

            self.job("create_vkbasalt_config", {"effects": [effect]}, finished)

    def open_template(self):
        from ..runtime import open_url
        from PySide6.QtCore import QUrl

        self.job(
            "prepare_template",
            {"id": self.gpu_template.currentData()},
            lambda data: open_url(QUrl.fromLocalFile(data["path"]).toString()),
        )

    def config_editor(self):
        if not self.window.selected:
            return
        names = [
            "ReShade.ini",
            "OptiScaler.ini",
            "relimiter.ini",
            "DisplayCommander.ini",
            "dxvk.conf",
            "ReShadePreset.ini",
            "nvngx_dlssnr.ini",
        ]
        name, ok = QInputDialog.getItem(self.window, "Edit configuration", "File", names, 0, False)
        if not ok:
            return
        game = self.window.selected
        path = game.target / name
        current = path.read_bytes() if path.is_file() else b""
        from ..backend import load_backend
        from ..downloads import sha

        encoding = load_backend().hdr_ini_encoding(current)
        dialog = QDialog(self.window)
        dialog.setWindowTitle(name)
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setPlainText(current.decode(encoding))
        layout.addWidget(text)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            self.window.enqueue_feature(
                "edit_config",
                {"name": name, "text": text.toPlainText(), "before_sha256": sha(current)},
                game=game,
            )
