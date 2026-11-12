"""Linux launch profile controls and wrapper copying."""

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QPlainTextEdit,
)

from ..launch import DRS_CHOICES, hdr_outputs, wrapper_options

from ..widgets import help_label, push, section


class LaunchOptionsPage:
    def build_launch(self):
        layout = self.page("Launch options")
        self.launch_layout = layout
        layout.addWidget(
            help_label(
                "For Steam, copy the launch command below into the game’s Launch Options. These settings then apply when you press Play. Launch game opens Steam/Heroic with their existing settings; manual Wine/Proton launches use this profile directly."
            )
        )
        form = QFormLayout()
        form.addRow("Wine / Proton prefix", self.window.path_field(self.window.prefix))
        self.combo(
            form,
            "runner_kind",
            "Manual runner type",
            [(x, x) for x in ["wine", "proton", "umu", "bottles"]],
        )
        self.file_line(form, "runner_command", "Runner command", "All files (*)")
        self.line(form, "launch_arguments", "Game launch arguments")
        self.file_line(
            form, "launch_executable", "Launch executable override", "Windows executables (*.exe)"
        )
        self.check(form, "PROTON_ENABLE_WAYLAND", "Request Proton native Wayland")
        self.check(form, "PROTON_ENABLE_HDR", "Request Proton HDR")
        self.check(form, "PROTON_ENABLE_NGX_UPDATER", "Enable the Proton NGX snippet updater")
        self.check(form, "DXVK_NVAPI_VKREFLEX", "Enable installed DXVK-NVAPI Vulkan Reflex layer")
        self.check(form, "dxvk_native_overrides", "Prefer custom local DXVK DLLs")
        self.check(form, "gamescope", "Launch inside Gamescope")
        self.line(form, "gamescope_arguments", "Gamescope options", "e.g. -f --hdr-enabled -r 120")
        self.check(form, "vkbasalt", "Enable installed vkBasalt Vulkan effects")
        self.line(form, "vkbasalt_config", "vkBasalt configuration file")
        self.check(form, "auto_hdr", "Enable HDR for the game and restore it on exit (KDE Plasma)")
        self.line(form, "hdr_output", "KDE display name", "e.g. DP-1")
        layout.addLayout(form)
        layout.addWidget(push("Detect HDR displays", self.detect_hdr))
        layout.addWidget(push("Create vkBasalt shader configuration", self.vulkan_effects))
        layout = section(layout, "Advanced: NVIDIA / DXVK driver overrides", expanded=False)
        layout.addWidget(
            help_label(
                "Windows RTX HDR, Smooth Motion, driver ReBAR/power management and Windows global NVIDIA profiles have no implemented Linux equivalent. DLSS/MFG overrides below use DXVK-NVAPI; support depends on the installed runner and NVIDIA GPU."
            )
        )
        form = QFormLayout()
        for key, values in DRS_CHOICES.items():
            widget = QComboBox()
            widget.addItem("Keep current", "")
            for value in values:
                widget.addItem(
                    (
                        str(int(value) + 1) + "x"
                        if key.endswith(("MULTI_FRAME_COUNT", "MULTI_FRAME_COUNT_MAX"))
                        else value
                    ),
                    value,
                )
            self.drs[key] = widget
            form.addRow(key.removeprefix("NGX_").replace("_", " ").title(), widget)
        self.line(form, "dlss_sr_scale", "DLSS SR render scale (%)", "33–100; empty = unchanged")
        self.line(form, "dlss_rr_scale", "DLSS RR render scale (%)", "33–100; empty = unchanged")
        self.line(form, "mfg_target", "Dynamic MFG target FPS")
        self.combo(
            form,
            "dxvk_vsync",
            "DXVK VSync override",
            [("Keep current", ""), ("Off", "0"), ("On", "1")],
        )
        self.line(form, "fps_limit", "DXVK frame-rate limit", "Optional positive FPS")
        self.combo(
            form,
            "gl_vsync",
            "NVIDIA OpenGL VSync",
            [("Keep current", ""), ("Off", "0"), ("On", "1")],
        )
        self.combo(
            form,
            "gl_gsync",
            "NVIDIA OpenGL G-Sync allowed",
            [("Keep current", ""), ("Off", "0"), ("On", "1")],
        )
        self.line(
            form,
            "gl_shader_cache_mb",
            "NVIDIA OpenGL shader cache (MiB)",
            "Optional; affects OpenGL, not DXVK/VKD3D",
        )
        layout.addLayout(form)
        self.environment = QPlainTextEdit()
        self.environment.setPlaceholderText(
            'Additional per-game environment as JSON, e.g. {"DXVK_FRAME_RATE": "120"}'
        )
        self.environment.setMaximumHeight(100)
        layout.addWidget(self.environment)
        self.launch_layout.addWidget(
            push("Copy Steam launch command for this profile", self.copy_wrapper)
        )
        layout.addStretch()

    def detect_hdr(self):
        try:
            outputs = hdr_outputs()
            self.window.report_error(
                "\n".join(
                    o["name"] + (" · HDR enabled" if o["enabled"] else " · HDR disabled")
                    for o in outputs
                )
                or "Automatic display HDR switching is available through KDE Plasma/kscreen-doctor. No supported display adapter was detected."
            )
        except Exception as e:
            self.window.report_error(str(e))

    def copy_wrapper(self):
        if not self.window.selected:
            return
        if self.window.save_profile() is False:
            return
        from PySide6.QtWidgets import QApplication

        path = self.repository.directory / "profiles" / (self.window.selected.id + ".json")
        from ..runtime import ensure_launcher

        ensure_launcher()
        QApplication.clipboard().setText(wrapper_options(path))
        self.window.statusBar().showMessage(
            "Managed launch options copied; paste them into Steam to apply the launch profile", 7000
        )
