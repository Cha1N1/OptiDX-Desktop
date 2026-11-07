"""Compact, checkable custom-upscaler picker for the Installation page."""

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QMenu, QPushButton, QWidgetAction
from .pages import bind
from .upscalers import VARIANTS, legacy_lossy2_source


def build(features):
    layout = features.window.overview.add_section("OptiScaler custom upscalers")
    hint = QLabel(
        "Tick only the variants you want in OptiScaler/custom. Requires upstream nightly "
        "20261029 or newer with custom-upscaler support (DX12). Install OptiScaler first. "
        "Choose a variant in its in-game menu after restarting the game. "
        "These actions are separate from the direct FSR component above."
    )
    hint.setWordWrap(True)
    layout.addWidget(hint)
    picker = QPushButton("Choose custom upscalers ▾")
    picker.setObjectName("customUpscalerPicker")
    menu = QMenu(picker)
    checks = []
    for key, (label, folder, kind) in VARIANTS.items():
        check = bind(QCheckBox(label), "feature:upscaler_" + key)
        check.setContentsMargins(12, 3, 12, 3)
        features.fields["upscaler_" + key] = check
        action = QWidgetAction(menu)
        action.setDefaultWidget(check)
        menu.addAction(action)
        checks.append(check)
    picker.setMenu(menu)

    install = None
    problem = QLabel()
    problem.setWordWrap(True)

    def refresh(*unused):
        count = sum(check.isChecked() for check in checks)
        picker.setText(f"Choose custom upscalers ({count} selected) ▾")
        if "upscaler_cyboman_archive" not in features.fields:
            return
        legacy = features.fields["upscaler_cyboman_lossy2"]
        available = legacy_lossy2_source(
            {
                "upscaler_cyboman_archive": features.fields["upscaler_cyboman_archive"].text(),
                "upscaler_cyboman_tag": features.fields["upscaler_cyboman_tag"].text(),
            }
        )
        # Retain a saved choice visibly so it can be unticked; do not silently
        # change the user's algorithm or leave a disabled checked box stuck.
        legacy.setEnabled(available or legacy.isChecked())
        legacy.setToolTip(
            "For current downloads choose Cyboman Lossy. Older Lossy2 needs an older pinned release or local archive."
        )
        blocked = legacy.isChecked() and not available
        problem.setText(
            "Untick older Lossy2 and choose Cyboman Lossy (retrained, formerly Lossy2), or select an older archive/release."
            if blocked
            else ""
        )
        problem.setVisible(blocked)
        if install is not None:
            install.setEnabled(not blocked)

    features.refresh_upscaler_picker = refresh
    menu.aboutToShow.connect(refresh)
    refresh()
    for check in checks:
        check.toggled.connect(refresh)
    layout.addWidget(picker)
    form = QFormLayout()
    features.combo(
        form,
        "upscaler_cyboman_target",
        "Cyboman hardware target",
        [
            ("Choose your GPU family…", ""),
            ("Radeon RX 6000", "rx6000"),
            ("Radeon RX 7000", "rx7000"),
            ("RDNA2 iGPU / Steam Deck", "igpu_rdna2"),
            ("RDNA3 / 3.5 iGPU and other GPUs", "igpu_rdna3"),
        ],
    )
    features.line(
        form,
        "upscaler_cyboman_tag",
        "Pinned Cyboman release (optional)",
        "Latest matching hardware archive by default",
    )
    features.file_line(
        form, "upscaler_cyboman_archive", "Cyboman archive (optional)", "Archives (*.7z *.zip)"
    )
    features.file_line(
        form, "upscaler_helix_fsr4_dll", "Prepared HelixSR FSR 4 DLL", "Windows DLL (*.dll)"
    )
    features.file_line(
        form, "upscaler_helix_dlss_dll", "Prepared HelixSR DLSS DLL", "Windows DLL (*.dll)"
    )
    layout.addLayout(form)
    layout.addWidget(problem)
    for key in ("upscaler_cyboman_archive", "upscaler_cyboman_tag"):
        features.fields[key].textChanged.connect(refresh)
    note = QLabel(
        "Cyboman: downloads one archive for your hardware; copies only checked variants. "
        "Today’s Lossy is retrained Lossy2; older Lossy2 needs an older/local archive. "
        "Lossy delays brightening; Lite Lossy can alter foliage and particles. "
        "Cyboman excludes RX 9000 and online games. Warning files are retained. "
        "A local archive overrides the download. HelixSR: choose DLLs built by its local "
        "setup, not the unprepared ZIP DLLs. No network/model compilation runs at game launch."
    )
    note.setWordWrap(True)
    layout.addWidget(note)
    prune = bind(
        QCheckBox("Remove unchecked managed custom upscalers during this action"),
        "feature:upscaler_prune",
    )
    features.fields["upscaler_prune"] = prune
    layout.addWidget(prune)
    install = QPushButton("Install / update checked custom upscalers")
    install.setObjectName("installCustomUpscalers")
    install.clicked.connect(lambda: features.job("deploy_upscalers"))
    layout.addWidget(install)
    remove = QPushButton("Remove all managed custom upscalers")
    remove.clicked.connect(lambda: features.job("remove_upscalers"))
    layout.addWidget(remove)
    refresh()
