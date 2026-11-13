from dataclasses import replace
from .pages import ProfilePage, InstallationPage, bind
from .inspection import InspectionCache
import json
from pathlib import Path

from PySide6.QtCore import (
    QThread,
    QTimer,
    QUrl,
    Qt,
    Signal,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .backend import COMPONENT_LABELS, FG_CHOICES, launch_options, selected_components
from .inspection import DIRECTX_INPUTS
from .library import manual_game, scan_library
from .storage import Repository
from .runtime import open_url

STYLE = """
QWidget { background: $window; color: $text; font-family: 'Noto Sans', sans-serif; font-size: 13px; }
QMainWindow { background: $window; }
QLabel#brand { font-size: 23px; font-weight: 700; color: $heading; }
QLabel#subtitle, QLabel#muted { color: $muted; }
QLabel#gameTitle { font-size: 26px; font-weight: 650; }
QFrame#card { background: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QWidget { background: transparent; }
QLabel#cardNumber { font-size: 25px; font-weight: 650; color: $accent; }
QPushButton { background: $button; border: 1px solid $strong_border; border-radius: 7px; padding: 9px 14px; }
QToolButton { background: $card; border: 0; border-radius: 5px; padding: 7px; text-align: left; }
QToolButton:hover { background: $hover; }
QPushButton:hover { background: $button_hover; border-color: $focus; }
QPushButton:disabled { color: $disabled_border; background: $disabled_surface; border-color: $border; }
QPushButton#primary { background: $primary; color: $primary_text; font-weight: 650; border-color: $primary; }
QPushButton#primary:hover { background: $primary_hover; }
QPushButton#primary:disabled { background: $primary_disabled; color: $primary_disabled_text; border-color: $primary_disabled; }
QPushButton#danger { color: $danger_text; }
QPushButton#danger:disabled { color: $disabled_border; }
QLineEdit, QComboBox, QPlainTextEdit { background: $input; border: 1px solid $strong_border; border-radius: 6px; padding: 8px; }
QLineEdit:focus, QComboBox:focus { border-color: $primary; }
QComboBox QAbstractItemView { background: $popup; selection-background-color: $popup_selection; }
QListWidget { background: $list; border: 1px solid $border; border-radius: 9px; padding: 5px; }
QListWidget::item { padding: 11px 9px; border-radius: 6px; margin: 2px; }
QListWidget::item:selected { background: $selection; color: $selected_text; }
QListWidget::item:hover { background: $hover; }
QTabWidget::pane { border: 1px solid $border; border-radius: 9px; padding: 12px; }
QTabBar::tab { padding: 10px 18px; color: $muted; background: $window; }
QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; }
QCheckBox { spacing: 9px; padding: 5px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $input_border; border-radius: 3px; background: $input; }
QCheckBox::indicator:checked { border-color: $primary; background: $primary; image: url("__CHECK_ICON__"); }
QScrollArea { border: none; }
QSplitter::handle { background: $window; }
QSplitter::handle:hover { background: $splitter_hover; border-radius: 5px; }
QStatusBar { color: $muted; border-top: 1px solid $border; }
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


from .jobs_ui import JobRunnerMixin
from .launch_ui import GameLaunchMixin
from .services_ui import AppUpdateThread, BackgroundServicesMixin  # noqa: F401


class MainWindow(
    WorkflowMixin,
    JobRunnerMixin,
    GameLaunchMixin,
    BackgroundServicesMixin,
    QMainWindow,
):
    def __init__(self, repository=None, auto_scan=True):
        super().__init__()
        self.repository = repository or Repository()
        self.games = self.repository.games()
        self.init_workflow()
        self.inspection_cache = InspectionCache()
        self.selected = None
        self.current_status, self.current_problems, self.action_state = None, [], {}
        self.queue = []
        self.process = None
        self.cancel_requested = False
        self.scanner = None
        self.active_game = None
        self.result = None
        self.launch_processes = {}
        self.launch_children = {}
        self.running_timer = QTimer(self)
        self.running_timer.setInterval(2000)
        self.running_timer.timeout.connect(self.poll_running_games)
        self.restore_running_games()
        self.quitting = False
        self.setWindowTitle("OptiDX Desktop — Linux game mod manager")
        self.resize(1220, 880)
        self.setMinimumSize(930, 740)
        self.setAcceptDrops(True)
        from .theme import ThemeController

        self.theme = ThemeController(self, STYLE)
        self.build_ui()
        self.features.load({})
        self.setup_workflow()
        from .motion import PageMotion

        self.page_motion = PageMotion(self.tabs)
        from .scrolling import SmoothScrolling

        self.smooth_scrolling = SmoothScrolling(self)
        self.configure_services()
        self.app_update_thread = None
        if auto_scan:
            QTimer.singleShot(0, self.scan)
            QTimer.singleShot(0, self.startup_maintenance)

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
        brand_row = QHBoxLayout()
        logo = QLabel()
        app_icon = QIcon(str(Path(__file__).parent / "assets/app.svg"))
        self.setWindowIcon(app_icon)
        logo.setPixmap(app_icon.pixmap(36, 36))
        brand_row.addWidget(logo)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        title.addLayout(brand_row)
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
        self.batch_button.setToolTip(
            "Update managed components and installed optional tools in games included in bulk updates."
        )
        header.addWidget(self.batch_button)
        header.addWidget(button("App settings", lambda: self.features.open_app_settings()))
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
        self.filter.addItems(
            [
                "All games",
                "Favourites",
                "Hidden",
                "Steam",
                "Heroic",
                "Lutris",
                "Bottles",
                "Manual",
                "Installed",
                "Updates available",
            ]
        )
        self.filter.currentTextChanged.connect(self.populate)
        left.addWidget(self.filter)
        self.sort = QComboBox()
        self.sort.addItems(["Display name", "Recently managed", "Updates first"])
        self.sort.currentTextChanged.connect(self.populate)
        left.addWidget(self.sort)
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
        self.launch_button.setToolTip(
            "Steam/Heroic games open through their launcher. Use Launch options to configure the managed wrapper."
        )
        game_heading.addWidget(button("Copy launch command", lambda: self.features.copy_wrapper()))
        game_heading.addWidget(self.launch_button)
        details.addLayout(game_heading)
        self.launch_hint = QLabel()
        self.launch_hint.setWordWrap(True)
        details.addWidget(self.launch_hint)
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
        self.overview = InstallationPage()
        overview = QVBoxLayout(self.overview)
        self.installation_box = overview
        self.overview.content = overview
        overview.addWidget(QLabel("Install components into this game"))
        self.install_summary = QLabel()
        self.install_summary.setWordWrap(True)
        overview.addWidget(self.install_summary)
        self.action_hint = QLabel()
        self.action_hint.setWordWrap(True)
        overview.addWidget(self.action_hint)
        self.install_button = button(
            "Install selected components", lambda: self.enqueue("install"), "primary"
        )
        overview.addWidget(self.install_button)
        self.component_labels = {}
        self.notes = QLabel("No game selected.")
        self.notes.setWordWrap(True)
        from .widgets import section

        status = section(overview, "Installed components and diagnostics", expanded=False)
        self.status_box = status
        for name in [
            "OptiScaler",
            "ReShade",
            "RenoDX",
            "Luma",
            "HelixSR",
            "AMD FSR",
            "DLSS Enabler",
        ]:
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
        maintenance = QVBoxLayout()
        overview.insertLayout(2, maintenance)
        self.maintenance_box = maintenance
        self.overview.maintenance = maintenance
        update_hint = QLabel(
            "Update refreshes selected components and previously installed optional tools. It does not install unchecked shader packs or new extras."
        )
        update_hint.setWordWrap(True)
        maintenance.addWidget(update_hint)
        self.update_button = button(
            "Update this game's managed setup", lambda: self.enqueue("update")
        )
        self.remove_button = button(
            "Remove all OptiDX-managed files / restore originals",
            lambda: self.enqueue("remove"),
            "danger",
        )
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
        maintenance.removeWidget(self.update_button)
        maintenance.removeWidget(self.remove_button)
        management_actions = QHBoxLayout()
        management_actions.addWidget(self.update_button)
        management_actions.addWidget(self.remove_button)
        installation_layout.addLayout(management_actions)
        self.tabs.addTab(installation_page, "Installation")
        settings = self.config_page = ProfilePage()
        settings_box = QVBoxLayout(settings)
        self.configuration_box = settings_box
        self.components = {}
        self.component_status_labels = {}
        component_card, component_box = card("Components to install")
        component_card.setMaximumWidth(720)
        component_columns = QHBoxLayout()
        component_columns.setSpacing(18)
        component_box.addLayout(component_columns)
        columns = []
        for _ in range(2):
            column = QVBoxLayout()
            column.setSpacing(12)
            column.setAlignment(Qt.AlignmentFlag.AlignTop)
            component_columns.addLayout(column, 1)
            columns.append(column)
        for index, (key, label) in enumerate(COMPONENT_LABELS.items()):
            checkbox = QCheckBox(label)
            if key == "helixsr":
                checkbox.setText("HelixSR (optional)")
                checkbox.setToolTip(
                    "Optional FFX backend. Leave unchecked for direct Cyboman lossy FSR4 and its preset controls."
                )
            checkbox.toggled.connect(self.refresh_install_summary)
            self.components[key] = bind(checkbox, "component:" + key)
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
            columns[index % 2].addWidget(cell, 0, Qt.AlignmentFlag.AlignTop)
        self.helixsr_picker = QWidget()
        helix_box = QVBoxLayout(self.helixsr_picker)
        helix_box.setContentsMargins(0, 6, 0, 4)
        helix_box.addWidget(QLabel("Locally built HelixSR FSR DLL"))
        helix_row = QHBoxLayout()
        self.helixsr_dll = QLineEdit()
        self.helixsr_dll.setPlaceholderText("Path to the built HelixSR DLL")
        self.helixsr_dll.setToolTip("Choose the standalone Windows x64 HelixSR FSR DLL.")
        self.helixsr_dll.setMinimumWidth(0)
        self.helixsr_dll.setMaximumWidth(200)
        self.helixsr_dll.setFixedHeight(32)
        self.helixsr_dll.textChanged.connect(self.refresh_install_summary)
        helix_row.addWidget(self.helixsr_dll, 1)
        helix_row.addWidget(button("Browse…", self.browse_helixsr))
        helix_row.addStretch()
        helix_box.addLayout(helix_row)
        self.components["helixsr"].parentWidget().layout().addWidget(self.helixsr_picker)
        self.helixsr_picker.hide()
        for key in ("helixsr", "amd_fsr"):
            self.components[key].toggled.connect(
                lambda checked, key=key: self.select_upscaler(key, checked)
            )
        self.prune_components = QCheckBox("Remove unchecked managed components")
        self.prune_components.setToolTip(
            "On installation/update, remove unchecked core components previously installed by OptiDX. Unrelated files are preserved."
        )
        self.prune_components.toggled.connect(self.refresh_install_summary)
        component_box.addWidget(self.prune_components)
        component_hint = QLabel(
            "RenoDX/Luma require ReShade; HelixSR requires OptiScaler. Installed dependencies can be reused."
        )
        component_hint.setWordWrap(True)
        component_hint.setObjectName("muted")
        component_box.addWidget(component_hint)
        component_row = QHBoxLayout()
        component_row.addWidget(component_card, 1)
        component_row.addStretch()
        overview.insertLayout(1, component_row)
        settings_box.addWidget(QLabel("Change installed configuration"))
        self.hdr = QCheckBox(
            "Write native HDR settings to Unreal Engine.ini (RenoDX native HDR path)"
        )
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
            self.fg[key] = bind(combo, "fg:" + key)
            form.addRow(title, combo)
        settings_box.addLayout(form)
        hint = QLabel(
            "Apply writes Engine.ini and the chosen OptiScaler frame-generation values. "
            "It does not download or install components. These settings are also applied when installing or updating components. "
            "Wine prefix is configured under Launch options."
        )
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
        bind(self.helixsr_dll, "helixsr_dll")
        bind(self.prune_components, "prune")
        bind(self.include_updates, "include")
        bind(self.hdr, "hdr")
        bind(self.prefix, "prefix")
        bind(self.config_dir, "config")
        from .feature_ui import Features

        self.features = Features(self)
        for combo in self.fg.values():
            combo.currentIndexChanged.connect(self.refresh_install_summary)
        overview.addStretch()
        self.refresh_install_summary()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText(
            "Installation output appears here. Scanning your library makes no changes to games."
        )
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
        self.draft_label = QLabel("Profile saved")
        self.draft_label.setWordWrap(True)
        self.draft_label.setToolTip(
            "Save stores profile choices. Install / Apply changes game files. Drafts are retained automatically."
        )
        profile_footer.addWidget(self.draft_label)
        profile_footer.addStretch()
        self.save_button = button("Save game profile", self.save_profile)
        profile_footer.addWidget(self.save_button)
        profile_footer.addWidget(button("Revert draft", self.revert_draft))
        details.addLayout(profile_footer)
        splitter.addWidget(right)
        splitter.setSizes([310, 850])
        layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.queue_label = QLabel("Ready")
        self.queue_label.setObjectName("muted")
        footer.addWidget(self.queue_label)
        footer.addStretch()
        self.stop_job_button = button("Cancel and roll back", self.cancel_current_job)
        self.stop_job_button.setToolTip(
            "Stop the running operation and restore the files it changed from its snapshot."
        )
        self.stop_job_button.setEnabled(False)
        footer.addWidget(self.stop_job_button)
        self.cancel_button = button("Clear queued jobs", self.clear_queue)
        self.cancel_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        self.app_update_button = button("", self.open_app_release)
        self.app_update_button.setToolTip("Open the release page to download the new AppImage.")
        self.app_update_button.hide()
        self.app_update_release = None
        footer.addWidget(self.app_update_button)
        platform = QApplication.platformName()
        backend_label = (
            "Wayland"
            if platform.startswith("wayland")
            else "X11 / XWayland" if platform == "xcb" else platform
        )
        version = self.display_backend_label = QLabel(f"Desktop {__version__}  ·  {backend_label}")
        version.setToolTip(
            f"Active Qt display backend: {platform}. QT_QPA_PLATFORM overrides automatic selection."
        )
        version.setObjectName("muted")
        footer.addWidget(version)
        layout.addLayout(footer)
        self.refresh_actions()

    def scroll_page(self, widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        return area

    def browse_helixsr(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose locally built HelixSR FSR DLL",
            self.helixsr_dll.text(),
            "Windows DLL (*.dll);;All files (*)",
        )
        if path:
            self.helixsr_dll.setText(path)

    def sync_upscaler_choices(self):
        key = "helixsr" if self.components["helixsr"].isChecked() else "amd_fsr"
        self.select_upscaler(key, self.components[key].isChecked())

    def select_upscaler(self, key, checked):
        other = "amd_fsr" if key == "helixsr" else "helixsr"
        if checked:
            self.components[other].setChecked(False)
        for name in ("helixsr", "amd_fsr"):
            opposite = "amd_fsr" if name == "helixsr" else "helixsr"
            blocked = self.components[opposite].isChecked()
            self.components[name].setEnabled(not blocked)
            label = "HelixSR" if opposite == "helixsr" else "Cyboman FSR"
            hint = (
                f"Unavailable while {label} is selected. Untick {label} to switch."
                if blocked
                else ""
            )
            self.components[name].setToolTip(hint)
            status = self.component_status_labels[name]
            status.setProperty("blocked_choice", hint)
        self.helixsr_picker.setVisible(self.components["helixsr"].isChecked())
        self.refresh_install_summary()

    def refresh_install_summary(self, *unused):
        if self.loading_form:
            return
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
            self.refresh_actions()
            self.install_button.setText(
                "Install selected components"
                if names
                else (
                    "Remove unchecked managed components"
                    if self.prune_components.isChecked()
                    else "Select components to install"
                )
            )

    def path_field(self, field):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field)

        def choose():
            path = QFileDialog.getExistingDirectory(
                self, "Choose folder", field.text() or str(Path.home())
            )
            if path:
                field.setText(path)

        layout.addWidget(button("Browse", choose))
        return widget

    def populate(self, *unused):
        selected_id = self.selected.id if self.selected else None
        text = self.search.text().casefold()
        filter_name = self.filter.currentText()
        self.list.blockSignals(True)
        # A failed refresh must never leave the library list silently disconnected.
        try:
            self.list.clear()
            installed_count = 0
            from .status import game_status

            statuses = {game.id: game_status(game, self.repository) for game in self.games}
            self.statuses = statuses
            profiles = {key: status.profile for key, status in statuses.items()}
            updates = {key: status.update for key, status in statuses.items()}
            for game in self.ordered_games(profiles, updates):
                status = statuses[game.id]
                profile = status.profile
                installed = status.installed
                installed_count += int(installed)
                if (
                    text
                    and text
                    not in (
                        game.title + " " + game.store + " " + profile.get("display_name", "")
                    ).casefold()
                ):
                    continue
                if filter_name == "Installed" and not installed:
                    continue
                if filter_name == "Hidden" and not profile.get("hidden"):
                    continue
                if filter_name != "Hidden" and profile.get("hidden"):
                    continue
                if filter_name == "Favourites" and not profile.get("favourite"):
                    continue
                update = status.update_available
                if filter_name == "Updates available" and not update:
                    continue
                if (
                    filter_name
                    not in {"All games", "Installed", "Favourites", "Hidden", "Updates available"}
                    and game.store != filter_name
                ):
                    continue
                suffix = " · Installed" if installed else ""
                if update:
                    suffix += " · Update available"
                if game.id in self.launch_processes:
                    suffix += " · Running"
                if not game.available:
                    suffix += " · Offline"
                if status.needs_attention:
                    suffix += " · Needs attention"
                item = QListWidgetItem(status.display_name + "\n" + game.store + suffix)
                item.setData(Qt.ItemDataRole.UserRole, game.id)
                self.list.addItem(item)
                if game.id == selected_id:
                    self.list.setCurrentItem(item)
        finally:
            self.list.blockSignals(False)
        self.stat_labels[0].setText(str(len(self.games)))
        self.stat_labels[1].setText(str(installed_count))
        from .constants import helixsr_directory

        helix = helixsr_directory()
        ready = (helix / "amd_fidelityfx_upscaler_dx12.dll").is_file()
        self.stat_labels[2].setText("Available" if ready else "Not prepared")
        if self.list.currentItem() is None and self.list.count():
            first = next(
                (i for i in range(self.list.count()) if "Installed" in self.list.item(i).text()), 0
            )
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

    def inspection(self, game):
        return self.inspection_cache.inspect(game)

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
        info = self.inspection(game)
        status = self.status_for(game)
        self.game_title.setText(status.display_name)
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
        notes += (
            "Existing mod files are backed up before changes. HelixSR uses a prepared local DLL."
        )
        if info["bits"] == 32:
            notes += "\n32-bit deployment supports ReShade and architecture-matched addons."
        from .inspection import foreign_dlls

        conflicts = foreign_dlls(game)
        if conflicts:
            notes += "\nExisting proxies: " + ", ".join(
                c["path"] + " (" + c["identity"] + ")" for c in conflicts
            )
        if info["manifest_error"]:
            notes += "\n" + info["manifest_error"]
        for error in dict.fromkeys(status.errors + tuple(info.get("record_errors", ()))):
            notes += "\nNeeds attention: " + error
        if status.errors:
            notes += (
                "\nManagement actions stay disabled until the record is repaired or removed;"
                " it is kept as evidence and never overwritten automatically."
            )
        self.notes.setText(notes)
        self.features.refresh()
        self.refresh_actions()
        self.refresh_workflow()

    def status_for(self, game):
        from .status import game_status

        return game_status(game, self.repository)

    def _load_profile(self):
        profile = self.status_for(self.selected).profile
        try:
            selected = selected_components(profile)
        except ValueError:
            selected = set()
        info = self.inspection(self.selected)
        if not profile and (
            info["bits"] == 32
            or (info["apis"] and not set(info["apis"]).intersection(DIRECTX_INPUTS | {"DX10"}))
        ):
            selected = {"reshade", "renodx"}
        for name, checkbox in self.components.items():
            checkbox.setChecked(name in selected)
        self.helixsr_dll.setText(profile.get("helixsr_dll", ""))
        self.prune_components.setChecked(profile.get("prune_components", False))
        self.hdr.setChecked(profile.get("native_hdr", True))
        self.include_updates.setChecked(profile.get("include_updates", True))
        self.prefix.setText(profile.get("prefix") or self.selected.prefix)
        self.config_dir.setText(profile.get("config_dir", ""))
        for key, combo in self.fg.items():
            combo.setCurrentIndex(max(combo.findData(profile.get(key, "")), 0))
        self.features.load(profile)

    def profile(self):
        return {
            "components": {name: box.isChecked() for name, box in self.components.items()},
            "prune_components": self.prune_components.isChecked(),
            "native_hdr": self.hdr.isChecked(),
            "include_updates": self.include_updates.isChecked(),
            "prefix": self.prefix.text().strip(),
            "config_dir": self.config_dir.text().strip(),
            "helixsr_dll": self.helixsr_dll.text().strip(),
            **{key: combo.currentData() for key, combo in self.fg.items()},
            **self.features.preferences(),
        }

    def save_profile(self):
        if self.selected:
            try:
                old = self.repository.preferences(self.selected)
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
        from .status import game_status

        for index, game in enumerate(games):
            chosen = game_status(game, self.repository).profile.get("executable")
            if chosen and Path(chosen).is_file():
                try:
                    Path(chosen).resolve().relative_to(Path(game.root).resolve())
                    games[index] = replace(game, executable=chosen)
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
        path, unused = QFileDialog.getOpenFileName(
            self, "Select game executable", str(Path.home()), "Windows games (*.exe *.EXE)"
        )
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
        path, unused = QFileDialog.getOpenFileName(
            self, "Choose actual game binary", self.selected.root, "Windows games (*.exe *.EXE)"
        )
        if path:
            try:
                Path(path).resolve().relative_to(Path(self.selected.root).resolve())
                updated = replace(self.selected, executable=str(Path(path).resolve()))
                self.games = [updated if game.id == updated.id else game for game in self.games]
                self.selected = updated
                profile = self.repository.preferences(self.selected)
                self.repository.save_preferences(
                    self.selected, {**profile, "executable": self.selected.executable}
                )
                self.repository.save_games(self.games)
                self.show_details()
            except ValueError:
                self.report_error("Choose an executable within this game's installation folder.")

    def refresh_actions(self):
        if self.loading_form or not hasattr(self, "stop_job_button"):
            return
        from .status import action_states, install_problems, launchable

        game = self.selected
        status = self.status_for(game) if game else None
        info = self.inspection(game) if game else {}
        chosen = {key for key, box in self.components.items() if box.isChecked()}
        problems = (
            install_problems(chosen, info.get("components", {}), self.helixsr_dll.text())
            if game
            else []
        )
        states = action_states(
            status,
            info,
            busy=self.process is not None,
            chosen=chosen,
            prune=self.prune_components.isChecked(),
            problems=problems,
            launchable=bool(game and launchable(game, status.profile)),
        )
        self.current_status, self.current_problems, self.action_state = status, problems, states
        for key, widget in (
            ("install", self.install_button),
            ("update", self.update_button),
            ("remove", self.remove_button),
            ("configure", self.apply_button),
            ("save", self.save_button),
            ("launch", self.launch_button),
        ):
            widget.setEnabled(states[key].enabled)
        self.batch_button.setEnabled(self.process is None)
        self.stop_job_button.setEnabled(self.process is not None and not self.cancel_requested)
        if hasattr(self, "features"):
            self.features.refresh_helix_action()
        self.render_workflow_status()

    def open_directory(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        open_url(QUrl.fromLocalFile(str(Path(path).resolve())).toString())

    def quit_app(self):
        self.quitting = True
        self.close()

    def open_folder(self):
        if self.selected:
            open_url(QUrl.fromLocalFile(str(self.selected.target)).toString())

    def copy_launch_options(self):
        from .runtime import ensure_launcher

        ensure_launcher()
        QApplication.clipboard().setText(launch_options(self.profile()))
        self.statusBar().showMessage(
            "Steam launch options copied. AppImage Heroic wrapper: the AppImage with --backend in its arguments.",
            7000,
        )

    def copy_report(self):
        if not self.selected:
            return
        from .diagnostics import report

        QApplication.clipboard().setText(
            json.dumps(report(self.selected, self.profile()), indent=2)
        )
        self.statusBar().showMessage("Diagnostic report copied", 4000)

    def report_error(self, message):
        QMessageBox.warning(self, "OptiDX Desktop", message)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.toLocalFile()
            .lower()
            .endswith(
                (".exe", ".addon", ".addon32", ".addon64", ".zip", ".7z", ".rar", ".ini", ".fx")
            )
            for url in event.mimeData().urls()
        ):
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
        elif self.process is not None or (self.scanner is not None and self.scanner.isRunning()):
            # Games run detached from this window and keep running after it closes.
            self.statusBar().showMessage(
                "Wait for the current operation to finish before closing", 5000
            )
            event.ignore()
        else:
            # App-wide filters would otherwise outlive this window until Qt
            # destroys it, slowing every event and touching half-deleted popups.
            from PySide6.QtWidgets import QApplication

            self.smooth_scrolling.detach()
            QApplication.instance().removeEventFilter(self.theme)
            event.accept()
