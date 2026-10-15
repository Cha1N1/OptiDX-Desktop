import codecs
import json
from pathlib import Path
import re
import sys

from PySide6.QtCore import QProcess, QThread, QTimer, QUrl, Qt, Signal, QFileSystemWatcher
from PySide6.QtGui import QDesktopServices, QIcon, QAction
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget, QSystemTrayIcon, QMenu)

from . import __version__
from .backend import BACKEND_PATH, COMPONENT_LABELS, FG_CHOICES, launch_options, selected_components
from .inspection import DIRECTX_INPUTS, inspect_game
from .library import manual_game, scan_library
from .storage import Repository
from .runtime import open_url, open_game_uri, python_executable

STYLE = """
QWidget { background: #11151c; color: #dbe3ed; font-family: 'Noto Sans', sans-serif; font-size: 13px; }
QMainWindow { background: #11151c; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #f0f6fc; }
QLabel#subtitle, QLabel#muted { color: #94a3b8; }
QLabel#gameTitle { font-size: 26px; font-weight: 650; }
QFrame#card { background: #191f29; border: 1px solid #293241; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QWidget { background: transparent; }
QLabel#cardNumber { font-size: 25px; font-weight: 650; color: #75ded2; }
QPushButton { background: #232c3a; border: 1px solid #344155; border-radius: 7px; padding: 9px 14px; }
QToolButton { background: #191f29; border: 0; border-radius: 5px; padding: 7px; text-align: left; }
QToolButton:hover { background: #232e3c; }
QPushButton:hover { background: #303d50; border-color: #64748b; }
QPushButton:disabled { color: #596577; background: #1c222c; border-color: #293241; }
QPushButton#primary { background: #62d6c4; color: #102522; font-weight: 650; border-color: #62d6c4; }
QPushButton#primary:hover { background: #8de6d9; }
QPushButton#primary:disabled { background: #253e3c; color: #698782; border-color: #253e3c; }
QPushButton#danger { color: #f0a7ac; }
QLineEdit, QComboBox, QPlainTextEdit { background: #151b25; border: 1px solid #344155; border-radius: 6px; padding: 8px; }
QLineEdit:focus, QComboBox:focus { border-color: #62d6c4; }
QComboBox QAbstractItemView { background: #202938; selection-background-color: #315052; }
QListWidget { background: #151b24; border: 1px solid #293241; border-radius: 9px; padding: 5px; }
QListWidget::item { padding: 11px 9px; border-radius: 6px; margin: 2px; }
QListWidget::item:selected { background: #263e41; color: #c8fff5; }
QListWidget::item:hover { background: #232e3c; }
QTabWidget::pane { border: 1px solid #293241; border-radius: 9px; padding: 12px; }
QTabBar::tab { padding: 10px 18px; color: #94a3b8; background: #11151c; }
QTabBar::tab:selected { color: #75ded2; border-bottom: 2px solid #75ded2; }
QCheckBox { spacing: 9px; padding: 5px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #53657c; border-radius: 3px; background: #151b25; }
QCheckBox::indicator:checked { border-color: #62d6c4; background: #62d6c4; image: url("__CHECK_ICON__"); }
QScrollArea { border: none; }
QSplitter::handle { background: #11151c; }
QSplitter::handle:hover { background: #1b2430; border-radius: 5px; }
QStatusBar { color: #94a3b8; border-top: 1px solid #293241; }
"""


class ScanThread(QThread):
    completed = Signal(object, object)

    def __init__(self, cached, parent=None):
        super().__init__(parent)
        self.cached = cached

    def run(self):
        games, warnings = scan_library(cached=self.cached)
        self.completed.emit(games, warnings)


def button(text, callback, name=""):
    result = QPushButton(text)
    result.setObjectName(name)
    result.clicked.connect(callback)
    return result


def card(title):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    heading = QLabel(title)
    heading.setStyleSheet("font-weight: 650; font-size: 14px;")
    layout.addWidget(heading)
    return frame, layout


from .qol import WorkflowMixin


class MainWindow(WorkflowMixin, QMainWindow):
    def __init__(self, repository=None, auto_scan=True):
        super().__init__()
        self.repository = repository or Repository()
        self.init_workflow()
        self.games = self.repository.games()
        self.selected = None
        self.queue = []
        self.process = None
        self.scanner = None
        self.active_game = None
        self.result = None
        self.launch_processes = {}
        self.quitting = False
        self.setWindowTitle("OptiDX Desktop — Linux game mod manager")
        self.resize(1220, 880)
        self.setMinimumSize(930, 740)
        self.setAcceptDrops(True)
        from .theme import ThemeController
        self.theme = ThemeController(self, STYLE)
        self.build_ui()
        self.features.load({})
        self.populate()
        self.setup_workflow()
        from .motion import PageMotion
        self.page_motion = PageMotion(self.tabs)
        from .scrolling import SmoothScrolling
        self.smooth_scrolling = SmoothScrolling(self)
        self.configure_services()
        if auto_scan:
            QTimer.singleShot(0, self.scan)

    def build_ui(self):
        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(24, 20, 24, 14)
        layout.setSpacing(18)
        header = QHBoxLayout()
        title = QVBoxLayout()
        brand = QLabel("OptiDX Desktop")
        brand.setObjectName("brand")
        title.addWidget(brand)
        subtitle = QLabel("HDR, upscaling and game mods on Linux.")
        subtitle.setObjectName("subtitle")
        title.addWidget(subtitle)
        header.addLayout(title)
        header.addStretch()
        self.refresh_button = button("Refresh library", self.scan)
        header.addWidget(self.refresh_button)
        self.add_button = button("+ Add game", self.add_game)
        header.addWidget(self.add_button)
        self.batch_button = button("Update all games", self.batch_update)
        self.batch_button.setToolTip("Update managed components and installed optional tools in games included in bulk updates.")
        header.addWidget(self.batch_button)
        header.addWidget(button("App settings", lambda: self.features.app_dialog.exec()))
        layout.addLayout(header)
        stats = QHBoxLayout()
        self.stat_labels = []
        for label in ["Games in your library", "Managed installations", "Prepared HelixSR"]:
            frame = QWidget()
            box = QHBoxLayout(frame)
            box.setContentsMargins(0, 0, 12, 0)
            box.addWidget(QLabel(label))
            value = QLabel("—")
            value.setObjectName("cardNumber")
            box.addWidget(value)
            stats.addWidget(frame)
            self.stat_labels.append(value)
        layout.addLayout(stats)
        splitter = self.splitter = QSplitter()
        splitter.setHandleWidth(20)
        splitter.setChildrenCollapsible(False)
        sidebar = QWidget()
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your games…")
        self.search.textChanged.connect(self.populate)
        left.addWidget(self.search)
        self.filter = QComboBox()
        self.filter.addItems(["All games", "Favourites", "Hidden", "Steam", "Heroic", "Lutris", "Bottles", "Manual", "Installed", "Updates available"])
        self.filter.currentTextChanged.connect(self.populate)
        left.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.currentItemChanged.connect(self.select_item)
        left.addWidget(self.list)
        hint = QLabel("Drop a game .exe here to add it.")
        hint.setObjectName("muted")
        left.addWidget(hint)
        splitter.addWidget(sidebar)
        right = QWidget()
        details = self.details_layout = QVBoxLayout(right)
        details.setContentsMargins(4, 0, 0, 0)
        details.setSpacing(10)
        self.game_title = QLabel("Choose a game")
        self.game_title.setObjectName("gameTitle")
        self.game_title.setWordWrap(True)
        game_heading = self.game_heading = QHBoxLayout()
        game_heading.setSpacing(8)
        game_heading.addWidget(self.game_title, 1)
        self.launch_button = button("Launch game", self.launch, "primary")
        self.launch_button.setToolTip("Steam/Heroic games open through their launcher. Use Launch options to configure the managed wrapper.")
        game_heading.addWidget(self.launch_button)
        details.addLayout(game_heading)
        self.badges = QLabel("Scan your Steam and Heroic libraries, or add an executable.")
        self.badges.setObjectName("muted")
        self.badges.setWordWrap(True)
        details.addWidget(self.badges)
        self.path = QLabel("")
        self.path.setObjectName("muted")
        self.path.setWordWrap(True)
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.addWidget(self.path)
        self.tabs = QTabWidget()
        self.overview = QWidget()
        overview = QVBoxLayout(self.overview)
        self.installation_box = overview
        overview.addWidget(QLabel("Install components into this game"))
        self.install_summary = QLabel()
        self.install_summary.setWordWrap(True)
        overview.addWidget(self.install_summary)
        self.install_button = button("Install selected components", lambda: self.enqueue("install"), "primary")
        overview.addWidget(self.install_button)
        self.component_labels = {}
        self.notes = QLabel("No game selected.")
        self.notes.setWordWrap(True)
        from .feature_ui import section
        status = section(overview, "Installed components and diagnostics", expanded=False)
        self.status_box = status
        for name in ["OptiScaler", "ReShade", "RenoDX", "Luma", "HelixSR", "AMD FSR", "DLSS Enabler"]:
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            row.addStretch()
            value = QLabel("—")
            row.addWidget(value)
            status.addLayout(row)
            self.component_labels[name] = value
        status.addWidget(self.notes)
        utilities = QHBoxLayout()
        utilities.addWidget(button("Open game folder", self.open_folder))
        utilities.addWidget(button("Copy diagnostics", self.copy_report))
        status.addLayout(utilities)
        status.addWidget(button("Change installation executable", self.change_executable))
        maintenance = section(overview, "Update or remove this game's setup", expanded=False)
        self.maintenance_box = maintenance
        update_hint = QLabel("Update refreshes selected components and previously installed optional tools. It does not install unchecked shader packs or new extras.")
        update_hint.setWordWrap(True)
        maintenance.addWidget(update_hint)
        self.update_button = button("Update this game's managed setup", lambda: self.enqueue("update"))
        self.remove_button = button("Remove all OptiDX-managed files / restore originals", lambda: self.enqueue("remove"), "danger")
        maintenance.addWidget(self.update_button)
        maintenance.addWidget(self.remove_button)
        self.include_updates = QCheckBox("Include this game in Update all managed games")
        self.include_updates.setChecked(True)
        maintenance.addWidget(self.include_updates)
        installation_page = QWidget()
        installation_layout = self.installation_layout = QVBoxLayout(installation_page)
        overview.removeWidget(self.install_summary)
        overview.removeWidget(self.install_button)
        installation_layout.addWidget(self.scroll_page(self.overview), 1)
        installation_layout.addWidget(self.install_summary)
        installation_layout.addWidget(self.install_button)
        self.tabs.addTab(installation_page, "Installation")
        settings = QWidget()
        settings_box = QVBoxLayout(settings)
        self.configuration_box = settings_box
        self.components = {}
        self.component_status_labels = {}
        component_card, component_box = card("Components to install")
        component_grid = QGridLayout()
        component_box.addLayout(component_grid)
        for index, (key, label) in enumerate(COMPONENT_LABELS.items()):
            checkbox = QCheckBox(label)
            if key == "helixsr":
                checkbox.setText("HelixSR (optional)")
                checkbox.setToolTip("Optional FFX backend. Leave unchecked for direct Cyboman lossy FSR4 and its preset controls.")
            checkbox.toggled.connect(self.refresh_install_summary)
            self.components[key] = checkbox
            cell = QWidget()
            cell_box = QVBoxLayout(cell)
            cell_box.setContentsMargins(0, 0, 0, 0)
            cell_box.setSpacing(0)
            cell_box.addWidget(checkbox)
            status_label = QLabel()
            status_label.setWordWrap(True)
            status_label.setObjectName("muted")
            cell_box.addWidget(status_label)
            self.component_status_labels[key] = status_label
            component_grid.addWidget(cell, index // 2, index % 2)
        self.prune_components = QCheckBox("Remove unchecked managed components")
        self.prune_components.setToolTip("On installation/update, remove unchecked core components previously installed by OptiDX. Unrelated files are preserved.")
        self.prune_components.toggled.connect(self.refresh_install_summary)
        component_box.addWidget(self.prune_components)
        component_hint = QLabel("RenoDX/Luma require ReShade; HelixSR requires OptiScaler. Installed dependencies can be reused.")
        component_hint.setWordWrap(True)
        component_hint.setObjectName("muted")
        component_box.addWidget(component_hint)
        overview.insertWidget(1, component_card)
        settings_box.addWidget(QLabel("Change installed configuration"))
        self.hdr = QCheckBox("Write native HDR settings to Unreal Engine.ini (RenoDX native HDR path)")
        self.hdr.toggled.connect(self.refresh_install_summary)
        self.hdr.setChecked(True)
        form = QFormLayout()
        form.addRow(self.hdr)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("Detected prefix, or choose a Wine/Proton prefix")
        self.config_dir = QLineEdit()
        self.config_dir.setPlaceholderText("Optional: existing Saved/Config/Windows folder")
        form.addRow("UE config folder", self.path_field(self.config_dir))
        self.fg = {}
        for key, title in [
            ("Enabled", "Frame generation"),
            ("FGInput", "Frame generation input"),
            ("FGOutput", "Frame generation output"),
            ("FGNvngxReplacement", "Nvngx replacement"),
        ]:
            combo = QComboBox()
            combo.addItem("Keep current", "")
            for choice in FG_CHOICES[key]:
                combo.addItem(choice, choice)
            self.fg[key] = combo
            form.addRow(title, combo)
        settings_box.addLayout(form)
        hint = QLabel("Apply writes Engine.ini and the chosen OptiScaler frame-generation values. "
                      "It does not download or install components. These settings are also applied when installing or updating components. "
                      "Wine prefix is configured under Launch options.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        settings_box.addWidget(hint)
        settings_buttons = QHBoxLayout()
        self.apply_button = button("Apply Unreal HDR + OptiScaler FG settings", self.apply_profile)
        settings_buttons.addWidget(self.apply_button)
        settings_box.addLayout(settings_buttons)
        settings_box.addStretch()
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings)
        self.tabs.addTab(settings_scroll, "HDR / config")
        from .feature_ui import Features
        self.features = Features(self)
        for combo in self.fg.values():
            combo.currentIndexChanged.connect(self.refresh_install_summary)
        overview.addStretch()
        self.refresh_install_summary()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Installation output appears here. Scanning your library makes no changes to games.")
        self.log.setStyleSheet("font-family: monospace; font-size: 12px;")
        self.tabs.addTab(self.log, "Activity")
        page_row = QHBoxLayout()
        page_row.setSpacing(12)
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(156)
        self.navigation.setStyleSheet("QListWidget::item { padding: 8px 9px; }")
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.addItems([self.tabs.tabText(index) for index in range(self.tabs.count())])
        self.tabs.tabBar().hide()
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.navigation.setCurrentRow)
        self.navigation.setCurrentRow(0)
        page_row.addWidget(self.navigation)
        page_row.addWidget(self.tabs, 1)
        details.addLayout(page_row, 1)
        profile_footer = self.profile_footer = QHBoxLayout()
        profile_footer.setSpacing(8)
        saved_hint = QLabel("Save keeps this game’s choices. Install / Apply writes game files.")
        saved_hint.setWordWrap(True)
        profile_footer.addWidget(saved_hint)
        profile_footer.addStretch()
        self.save_button = button("Save game profile", self.save_profile)
        profile_footer.addWidget(self.save_button)
        details.addLayout(profile_footer)
        splitter.addWidget(right)
        splitter.setSizes([310, 850])
        layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.queue_label = QLabel("Ready")
        self.queue_label.setObjectName("muted")
        footer.addWidget(self.queue_label)
        footer.addStretch()
        self.cancel_button = button("Clear queued jobs", self.clear_queue)
        self.cancel_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        platform = QApplication.platformName()
        backend_label = 'Wayland' if platform.startswith('wayland') else 'X11 / XWayland' if platform == 'xcb' else platform
        version = self.display_backend_label = QLabel(f"Desktop {__version__}  ·  {backend_label}")
        version.setToolTip(f"Active Qt display backend: {platform}. QT_QPA_PLATFORM overrides automatic selection.")
        version.setObjectName("muted")
        footer.addWidget(version)
        layout.addLayout(footer)
        self.refresh_actions()

    def scroll_page(self, widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        return area

    def refresh_install_summary(self, *unused):
        if not hasattr(self, "components"):
            return
        names = [COMPONENT_LABELS[key] for key, box in self.components.items() if box.isChecked()]
        text = "Will install: " + (", ".join(names) if names else "no components selected") + "."
        settings = []
        if hasattr(self, "hdr") and self.hdr.isChecked():
            settings.append("Unreal native HDR")
        if hasattr(self, "fg") and any(combo.currentData() for combo in self.fg.values()):
            settings.append("OptiScaler frame generation")
        if settings:
            text += " Also applies: " + ", ".join(settings) + "."
        if self.prune_components.isChecked():
            text += " Removes unchecked managed components."
        text += " Shader packs, optional tools and DLL replacements have their own buttons."
        self.install_summary.setText(text)
        if hasattr(self, "install_button"):
            exists = bool(self.selected and self.selected.executable and Path(self.selected.executable).is_file())
            info = inspect_game(self.selected) if self.selected else {}
            supported = not info.get("apis") or bool(set(info["apis"]).intersection(DIRECTX_INPUTS | {"DX9", "DX10", "OpenGL"}))
            self.install_button.setEnabled((bool(names) or self.prune_components.isChecked()) and exists and supported and self.process is None)
            self.refresh_workflow_status()
            self.install_button.setText("Install selected components" if names else "Remove unchecked managed components" if self.prune_components.isChecked() else "Select components to install")

    def path_field(self, field):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field)
        def choose():
            path = QFileDialog.getExistingDirectory(self, "Choose folder", field.text() or str(Path.home()))
            if path:
                field.setText(path)
        layout.addWidget(button("Browse", choose))
        return widget

    def populate(self, *unused):
        selected_id = self.selected.id if self.selected else None
        text = self.search.text().casefold()
        filter_name = self.filter.currentText()
        self.list.blockSignals(True)
        self.list.clear()
        installed_count = 0
        for game in self.ordered_games():
            from .storage import read_json
            profile = self.repository.preferences(game)
            installed = (game.target / ".optidx-files").is_file() or bool(read_json(game.target / ".optidx-desktop-assets.json", {}).get("groups")) or bool(read_json(Path(game.root) / ".optidx-desktop-assets.json", {}).get("groups"))
            installed_count += int(installed)
            if text and text not in (game.title + " " + game.store + " " + profile.get("display_name", "")).casefold():
                continue
            if filter_name == "Installed" and not installed:
                continue
            if filter_name == "Hidden" and not profile.get("hidden"):
                continue
            if filter_name != "Hidden" and profile.get("hidden"):
                continue
            if filter_name == "Favourites" and not profile.get("favourite"):
                continue
            update = read_json(self.repository.directory / "updates" / (game.id + ".json"), {}).get("update_available")
            if filter_name == "Updates available" and not update:
                continue
            if filter_name not in {"All games", "Installed", "Favourites", "Hidden", "Updates available"} and game.store != filter_name:
                continue
            suffix = " · Installed" if installed else ""
            if update:
                suffix += " · Update available"
            if game.id in self.launch_processes:
                suffix += " · Running"
            if not game.available:
                suffix += " · Offline"
            item = QListWidgetItem((profile.get("display_name") or game.title) + "\n" + game.store + suffix)
            item.setData(Qt.ItemDataRole.UserRole, game.id)
            self.list.addItem(item)
            if game.id == selected_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.stat_labels[0].setText(str(len(self.games)))
        self.stat_labels[1].setText(str(installed_count))
        from .backend import load_backend
        helix = load_backend().HELIXSR_DIR
        ready = all((helix / n).is_file() and (helix / n).stat().st_size > 0
                    for n in ["amd_fidelityfx_dx12.dll", "helixsr_weights.bin", "helixsr_kernels.pak"])
        self.stat_labels[2].setText("Available" if ready else "Not prepared")
        if self.list.currentItem() is None and self.list.count():
            first = next((i for i in range(self.list.count()) if "Installed" in self.list.item(i).text()), 0)
            self.list.setCurrentRow(first)
        elif not self.list.count():
            self.stash_draft()
            self.selected = None
            self.game_title.setText("No matching games")
            self.badges.setText("Change your filter or add a game executable.")
            self.path.clear()
            self.notes.setText("No game selected.")
            for label in self.component_labels.values():
                label.setText("—")
            self.refresh_actions()

    def select_item(self, item, previous=None):
        if item is None:
            return
        self.stash_draft()
        self.selected = next(g for g in self.games if g.id == item.data(Qt.ItemDataRole.UserRole))
        self.load_profile()
        self.show_details()

    def show_details(self):
        game = self.selected
        if not game:
            return
        info = inspect_game(game)
        self.game_title.setText(self.repository.preferences(game).get("display_name") or game.title)
        apis = " / ".join(info["apis"]) or "API not identified"
        bits = f"{info['bits']}-bit" if info["bits"] else "Architecture unknown"
        self.badges.setText(f"{game.store}  ·  {info['engine']}  ·  {apis}  ·  {bits}")
        self.path.setText(str(game.target))
        for name, value in info["components"].items():
            self.component_labels[name].setText("Detected" if value else "Not installed")
            self.component_labels[name].setProperty("detected", bool(value))
            self.component_labels[name].style().unpolish(self.component_labels[name])
            self.component_labels[name].style().polish(self.component_labels[name])
        notes = f"{len(info['managed'])} tracked files. UE HDR: {info['hdr']}.\n"
        if not info["executable_exists"]:
            notes += "No Windows executable found. Use Add game to select the actual binary.\n"
        notes += "Existing mod files are backed up before changes. HelixSR weights are prepared outside game launch."
        if info["bits"] == 32:
            notes += "\n32-bit deployment supports ReShade and architecture-matched addons."
        from .inspection import foreign_dlls
        conflicts = foreign_dlls(game)
        if conflicts:
            notes += '\nExisting proxies: ' + ', '.join(c['path'] + ' (' + c['identity'] + ')' for c in conflicts)
        if info["manifest_error"]:
            notes += "\n" + info["manifest_error"]
        self.notes.setText(notes)
        self.features.refresh()
        self.refresh_actions()
        self.refresh_workflow()

    def _load_profile(self):
        profile = self.repository.preferences(self.selected)
        selected = selected_components(profile)
        info = inspect_game(self.selected)
        if not profile and (info["bits"] == 32 or (info["apis"] and not set(info["apis"]).intersection(DIRECTX_INPUTS | {"DX10"}))):
            selected = {"reshade", "renodx"}
        for name, checkbox in self.components.items():
            checkbox.setChecked(name in selected)
        self.prune_components.setChecked(profile.get("prune_components", False))
        self.hdr.setChecked(profile.get("native_hdr", True))
        self.include_updates.setChecked(profile.get("include_updates", True))
        self.prefix.setText(profile.get("prefix") or self.selected.prefix)
        self.config_dir.setText(profile.get("config_dir", ""))
        for key, combo in self.fg.items():
            combo.setCurrentIndex(max(combo.findData(profile.get(key, "")), 0))
        self.features.load(profile)

    def profile(self):
        return {"components": {name: box.isChecked() for name, box in self.components.items()},
                "prune_components": self.prune_components.isChecked(), "native_hdr": self.hdr.isChecked(),
                "include_updates": self.include_updates.isChecked(), "prefix": self.prefix.text().strip(),
                "config_dir": self.config_dir.text().strip(),
                **{key: combo.currentData() for key, combo in self.fg.items()}, **self.features.preferences()}

    def save_profile(self):
        if self.selected:
            old = self.repository.preferences(self.selected)
            try:
                self.repository.save_preferences(self.selected, {**old, **self.profile()})
            except (ValueError, TypeError) as error:
                self.report_error(str(error))
                return False
            self.clean_form = self.capture_form()
            self.drafts.pop(self.selected.id, None)
            from .storage import atomic_json
            atomic_json(self.repository.directory / "drafts.json", self.drafts)
            self.statusBar().showMessage("Game profile saved", 4000)
            return True

    def apply_profile(self):
        self.enqueue("configure")

    def scan(self):
        if self.scanner is not None and self.scanner.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.queue_label.setText("Scanning Steam, Heroic, Lutris and Bottles libraries…")
        self.scanner = ScanThread(self.games, self)
        self.scanner.completed.connect(self.scanned)
        self.scanner.start()

    def scanned(self, games, warnings):
        for game in games:
            chosen = self.repository.preferences(game).get("executable")
            if chosen and Path(chosen).is_file():
                try:
                    Path(chosen).resolve().relative_to(Path(game.root).resolve())
                    game.executable = chosen
                except ValueError:
                    pass
        self.games = games
        self.repository.save_games(games)
        self.populate()
        self.refresh_button.setEnabled(True)
        self.queue_label.setText(f"Found {len(games)} games")
        for warning in warnings:
            self.log.appendPlainText(warning)
        self.refresh_actions()

    def add_game(self):
        path, unused = QFileDialog.getOpenFileName(self, "Select game executable", str(Path.home()), "Windows games (*.exe *.EXE)")
        if path:
            self.add_path(path)

    def add_path(self, path):
        try:
            game = manual_game(path)
            self.games = [g for g in self.games if g.id != game.id] + [game]
            self.games.sort(key=lambda g: g.title.casefold())
            self.repository.save_games(self.games)
            self.selected = game
            self.populate()
            self.load_profile()
            self.show_details()
        except Exception as error:
            self.report_error(str(error))

    def change_executable(self):
        if not self.selected:
            return
        path, unused = QFileDialog.getOpenFileName(self, "Choose actual game binary", self.selected.root,
                                                  "Windows games (*.exe *.EXE)")
        if path:
            try:
                Path(path).resolve().relative_to(Path(self.selected.root).resolve())
                self.selected.executable = str(Path(path).resolve())
                profile = self.repository.preferences(self.selected)
                self.repository.save_preferences(self.selected, {**profile, "executable": self.selected.executable})
                self.repository.save_games(self.games)
                self.show_details()
            except ValueError:
                self.report_error("Choose an executable within this game's installation folder.")

    def enqueue(self, action):
        if not self.selected:
            return
        if self.save_profile() is False:
            return
        from .models import Game
        self.queue.append((Game.from_dict(self.selected.to_dict()), action, self.repository.preferences(self.selected), {}, None))
        self.start_next()

    def enqueue_feature(self, action, options=None, callback=None, game=None):
        from .models import Game
        if action in {"refresh_catalogs", "import_asset", "import_url", "prepare_template"}:
            game = Game("global", "Library", "Global", str(self.repository.directory))
        else:
            game = game or self.selected
        if not game:
            return
        if game == self.selected and self.save_profile() is False:
            return
        self.queue.append((Game.from_dict(game.to_dict()), action, self.repository.preferences(game), options or {}, callback))
        self.start_next()

    def start_next(self):
        self.cancel_button.setEnabled(bool(self.queue))
        if self.process is not None or not self.queue:
            return
        game, action, preferences, options, self.job_callback = self.queue.pop(0)
        self.active_game = game
        self.result = None
        self.stdout_buffer = ""
        self.stdout_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.stderr_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.log.appendPlainText(f"\n{action.upper()} · {game.title}")
        self.tabs.setCurrentWidget(self.log)
        self.queue_label.setText(f"{action.title()}: {game.title} · {len(self.queue)} queued")
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        process.readyReadStandardOutput.connect(self.read_stdout)
        process.readyReadStandardError.connect(self.read_stderr)
        process.finished.connect(self.job_finished)
        process.errorOccurred.connect(self.process_error)
        request = json.dumps({"game": game.to_dict(), "action": action, "preferences": preferences, "options": options})
        log_dir = self.repository.directory / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        import time
        log_path = log_dir / f"{time.time_ns()}-{game.id}.log"
        self.job_log = log_path.open("w", encoding="utf-8")
        self.current_history = {"game_id": game.id, "game": game.title, "action": action,
                                "started": time.time(), "result": "Running", "log": str(log_path), "backups": [],
                                "recovery": "No recovery reported"}
        self.history.append(self.current_history)
        self.refresh_history()
        process.start(python_executable(), ["-B", "-u", "-m", "optidx_desktop.worker", "--request", request,
                                      "--data-dir", str(self.repository.directory)])
        self.refresh_actions()

    def read_stdout(self):
        if not self.process:
            return
        self.stdout_buffer += self.stdout_decoder.decode(bytes(self.process.readAllStandardOutput()))
        while "\n" in self.stdout_buffer:
            line, self.stdout_buffer = self.stdout_buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                self.log.appendPlainText(line)
                continue
            if event["event"] == "progress":
                self.queue_label.setText(event["message"])
                if self.current_history is not None and "rolled back" in event["message"]:
                    self.current_history["recovery"] = event["message"]
            elif event["event"] == "backup":
                self.log.appendPlainText("Backup: " + event["path"])
                if self.current_history is not None:
                    self.current_history["backups"].append(event["path"])
            elif event["event"] == "result":
                self.result = event

    def read_stderr(self):
        if not self.process:
            return
        text = self.stderr_decoder.decode(bytes(self.process.readAllStandardError()))
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(text)
        self.job_log.write(text)
        self.job_log.flush()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.log.appendPlainText("Could not start the backend process")
            self.job_finished(1)

    def job_finished(self, code, status=None):
        if self.process is None:
            return
        self.read_stdout()
        self.read_stderr()
        ok = code == 0 and self.result and self.result.get("ok")
        message = "Completed" if ok else "Failed: " + (self.result or {}).get("error", f"Backend exited with code {code}")
        self.log.appendPlainText(message)
        self.job_log.write("\n" + message + "\n")
        self.job_log.close()
        self.queue_label.setText(message)
        if self.current_history is not None:
            import time
            self.current_history.update(result=message, finished=time.time())
            if "manual recovery" in message:
                self.current_history["recovery"] = message
            self.refresh_history()
        self.process.deleteLater()
        self.process = None
        callback = self.job_callback
        if ok and callback:
            try:
                callback(self.result.get("data"))
            except Exception as error:
                self.log.appendPlainText('Could not display job result: ' + str(error))
        if ok and self.result.get("data") is not None:
            errors = self.result["data"].get("errors", []) if isinstance(self.result["data"], dict) else []
            for error in errors:
                self.log.appendPlainText(error)
        self.populate()
        self.show_details()
        self.refresh_actions()
        QTimer.singleShot(0, self.start_next)

    def clear_queue(self):
        self.queue.clear()
        self.cancel_button.setEnabled(False)
        self.statusBar().showMessage("Queued jobs cleared; the current job will finish", 5000)

    def refresh_actions(self):
        busy = self.process is not None
        exists = bool(self.selected and self.selected.executable and Path(self.selected.executable).is_file())
        from .assets import state
        installed = bool(self.selected and ((self.selected.target / ".optidx-files").is_file() or
                         any(state(root)["groups"] for root in {self.selected.target, Path(self.selected.root)})))
        info = inspect_game(self.selected) if self.selected else {}
        supported = not info.get("apis") or bool(set(info["apis"]).intersection(DIRECTX_INPUTS | {"DX9", "DX10", "OpenGL"}))
        self.install_button.setEnabled(exists and supported and not busy and (any(box.isChecked() for box in self.components.values()) or self.prune_components.isChecked()))
        self.update_button.setEnabled(exists and supported and not busy and installed)
        self.remove_button.setEnabled(exists and not busy and installed)
        self.apply_button.setEnabled(exists and not busy)
        self.save_button.setEnabled(bool(self.selected))
        self.launch_button.setEnabled(bool(self.selected and (self.selected.launch_uri or self.selected.store == "Bottles" or self.repository.preferences(self.selected).get("runner_command"))) and not busy)
        self.batch_button.setEnabled(not busy)
        if hasattr(self, "features"):
            self.features.refresh_helix_action()
        self.refresh_workflow_status()

    def launch(self):
        if self.selected and self.selected.launch_uri:
            try:
                open_game_uri(self.selected)
            except OSError as error:
                self.report_error(f"Could not start {self.selected.store}: {error}")
        elif self.selected:
            self.launch_manual()

    def launch_manual(self):
        game = self.selected
        if game.id in self.launch_processes:
            return
        try:
            if self.save_profile() is False:
                return
            from .launch import runner_command
            import os
            profile = self.repository.preferences(game)
            command = runner_command(game, profile)
            path = self.repository.directory / "profiles" / (game.id + ".json")
            if game.store == "Bottles" and not profile.get("runner_command"):
                profile["runner_kind"] = "bottles"
                self.repository.save_preferences(game, profile)
            process = QProcess(self)
            process.setWorkingDirectory(str(game.target))
            image = os.environ.get("APPIMAGE")
            program = image or python_executable()
            from .runtime import appimage_arguments
            arguments = [*appimage_arguments(), "--launch-profile", str(path), "--", *command] if image else ["-B", "-m", "optidx_desktop.launch", "--profile", str(path), "--", *command]
            process.finished.connect(lambda code, status, g=game: self.launch_finished(g, code))
            process.errorOccurred.connect(lambda error, g=game: self.launch_finished(g, 1) if error == QProcess.ProcessError.FailedToStart else None)
            process.readyReadStandardError.connect(lambda p=process: self.log.appendPlainText(bytes(p.readAllStandardError()).decode(errors="replace")))
            self.launch_processes[game.id] = process
            process.start(program, arguments)
            self.populate()
        except Exception as error:
            self.report_error(str(error))

    def launch_finished(self, game, code):
        process = self.launch_processes.pop(game.id, None)
        if process:
            process.deleteLater()
            self.log.appendPlainText(f"{game.title} exited with code {code}")
            self.populate()

    def open_directory(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        open_url(QUrl.fromLocalFile(str(Path(path).resolve())).toString())

    def check_all_updates(self):
        from .assets import state
        for game in self.games:
            if game.available and ((game.target / ".optidx-files").is_file() or any(state(r)["groups"] for r in {game.target, Path(game.root)})):
                self.enqueue_feature("check_updates", game=game)

    def configure_services(self):
        from .storage import read_json
        import os
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
            self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if self.service_settings.get("background_checks"):
            self.update_timer.start(4 * 3600 * 1000)
        else:
            self.update_timer.stop()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        folder = Path(self.service_settings.get("watch_folder", str(Path.home() / "Downloads")))
        self.watch_seen = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.glob("*") if p.is_file()} if folder.is_dir() else {}
        if self.service_settings.get("watch_downloads") and folder.is_dir():
            self.watcher.addPath(str(folder))
        if self.service_settings.get("tray") and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            self.tray.hide()

    def downloads_changed(self, directory):
        self.pending_downloads.clear()
        for path in Path(directory).glob("*"):
            if path.is_file() and path.suffix.lower() in {".addon", ".addon32", ".addon64", ".ini", ".zip", ".7z"}:
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
                    self.tray.showMessage("Mod download detected", path.name + " — use Import addon / preset / shader")
            else:
                self.watch_timer.start(3000)

    def quit_app(self):
        self.quitting = True
        self.close()

    def open_folder(self):
        if self.selected:
            open_url(QUrl.fromLocalFile(str(self.selected.target)).toString())

    def copy_launch_options(self):
        QApplication.clipboard().setText(launch_options(self.profile()))
        self.statusBar().showMessage("Steam launch options copied. AppImage Heroic wrapper: the AppImage with --backend in its arguments.", 7000)

    def copy_report(self):
        if not self.selected:
            return
        from .diagnostics import report
        QApplication.clipboard().setText(json.dumps(report(self.selected, self.profile()), indent=2))
        self.statusBar().showMessage("Diagnostic report copied", 4000)

    def report_error(self, message):
        QMessageBox.warning(self, "OptiDX Desktop", message)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.toLocalFile().lower().endswith((".exe", ".addon", ".addon32", ".addon64", ".zip", ".7z", ".rar", ".ini", ".fx")) for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(".exe"):
                self.add_path(url.toLocalFile())
            elif url.isLocalFile():
                self.features.import_dialog(url.toLocalFile())
        event.acceptProposedAction()

    def closeEvent(self, event):
        self.save_workspace()
        if not self.quitting and hasattr(self, "tray") and self.tray.isVisible():
            self.hide()
            event.ignore()
        elif self.process is not None or self.launch_processes or (self.scanner is not None and self.scanner.isRunning()):
            self.statusBar().showMessage("Wait for the current operation to finish before closing", 5000)
            event.ignore()
        else:
            event.accept()
