"""Original dark styling, a light preset, and actual desktop Qt palette colors."""

from pathlib import Path
from string import Template

from PySide6.QtCore import QDir, QEvent, QObject, QTemporaryDir
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget


def configure_palette():
    app = QApplication.instance()
    if app.property("optidxThemeReady"):
        return
    from .system_palette import system_palette_source

    system_palette_source()  # Capture native colors before installing our consistent control style.
    # Fusion avoids mixing desktop-provided light popup frames with dark QSS.
    app.setStyle("Fusion")
    app.setProperty("optidxThemeReady", True)


CONTROL_STYLE = """
/* No platform scrollbar arrows or bright native popup frames. */
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; border: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 3px; border: none; }
QScrollBar::handle:vertical { background: $scrollbar; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:horizontal { background: $scrollbar; min-width: 28px; border-radius: 4px; }
QScrollBar::handle:hover { background: $scrollbar_hover; }
QScrollBar::handle:pressed { background: $pressed_border; }
QScrollBar::add-line, QScrollBar::sub-line { background: transparent; border: none; width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: $input; border: none; }
QComboBox { padding-right: 28px; selection-background-color: $selection; }
QComboBox:hover { border-color: $input_border; }
QComboBox:on { border-color: $focus_border; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; background: transparent; }
QComboBox::down-arrow { image: url("__CHEVRON_ICON__"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $card; color: $text; border: 1px solid $strong_border;
    border-radius: 6px; padding: 4px; outline: 0; selection-background-color: $selection; selection-color: $selected_text; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 3px 9px; border: none; border-radius: 4px; }
QComboBox QAbstractItemView::item:selected { background: $selection; color: $selected_text; }
QComboBoxPrivateContainer { background: $card; border: none; padding: 0; }
QMenu { background: $card; border: 1px solid $strong_border; border-radius: 6px; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 4px; }
QMenu::item:selected { background: $selection; }
QMenu::separator { height: 1px; background: $strong_border; margin: 4px 7px; }
QToolTip { background: $button; color: $text; border: 1px solid $strong_border; padding: 6px; }
QPushButton:pressed, QToolButton:pressed { background: $pressed_surface; border-color: $pressed_border; }
QPushButton#primary:pressed { background: $primary_pressed; }
QPushButton:focus, QToolButton:focus { border: 1px solid $focus_border; }
QCheckBox:disabled { color: $disabled_text; }
QCheckBox::indicator:disabled { background: $disabled_surface; border-color: $border; }
QListWidget { outline: 0; }
QListWidget::item:focus { border: 1px solid $item_focus; }
QLineEdit:disabled, QComboBox:disabled { color: $disabled_text; border-color: $border; }
QPlainTextEdit:focus { border-color: $focus_border; }
QSpinBox { background: $input; color: $text; border: 1px solid $strong_border; border-radius: 6px; padding: 6px; }
QGroupBox { border: 1px solid $border; border-radius: 8px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
"""


# Semantic QSS tokens keep color choices independent of widget geometry.
DEFAULT_COLORS = {
    "window": "#11151c",
    "text": "#dbe3ed",
    "heading": "#f0f6fc",
    "muted": "#94a3b8",
    "card": "#191f29",
    "border": "#293241",
    "accent": "#75ded2",
    "button": "#232c3a",
    "strong_border": "#344155",
    "hover": "#232e3c",
    "button_hover": "#303d50",
    "focus": "#64748b",
    "disabled_border": "#596577",
    "disabled_surface": "#1c222c",
    "primary": "#62d6c4",
    "primary_text": "#102522",
    "primary_hover": "#8de6d9",
    "primary_disabled": "#253e3c",
    "primary_disabled_text": "#698782",
    "danger_text": "#f0a7ac",
    "input": "#151b25",
    "popup": "#202938",
    "popup_selection": "#315052",
    "list": "#151b24",
    "selection": "#263e41",
    "selected_text": "#c8fff5",
    "input_border": "#53657c",
    "splitter_hover": "#1b2430",
    "scrollbar": "#3b485a",
    "scrollbar_hover": "#5a7084",
    "pressed_border": "#75b8b2",
    "focus_border": "#62a99f",
    "pressed_surface": "#1c2835",
    "primary_pressed": "#4bb6a7",
    "item_focus": "#436a6b",
    "disabled_text": "#6f7e91",
}
DARK = {
    "window": "#090c12",
    "input": "#0d111a",
    "card": "#121823",
    "list": "#0d111a",
    "popup": "#151d2a",
    "accent": "#ffffff",
    "primary": "#ffffff",
    "primary_text": "#090c12",
    "primary_hover": "#ffffff",
    "selection": "#273246",
    "popup_selection": "#273246",
    "selected_text": "#ffffff",
    "pressed_border": "#d4deed",
    "focus_border": "#d4deed",
    "primary_pressed": "#c3cede",
    "item_focus": "#d4deed",
    "primary_disabled": "#1c2534",
    "primary_disabled_text": "#8793a6",
    "button": "#191f2b",
    "hover": "#202838",
    "button_hover": "#293448",
    "disabled_surface": "#141a25",
    "splitter_hover": "#141c28",
    "pressed_surface": "#1c2635",
}
LIGHT = {
    "window": "#f2f4f6",
    "text": "#202a35",
    "heading": "#15212c",
    "muted": "#596879",
    "card": "#ffffff",
    "border": "#d1d9e0",
    "accent": "#08796b",
    "button": "#e5e9ed",
    "strong_border": "#bec9d3",
    "hover": "#e8eef2",
    "button_hover": "#d7e1e8",
    "focus": "#667b8f",
    "disabled_border": "#75808c",
    "disabled_surface": "#e5e9ed",
    "primary": "#087f70",
    "primary_text": "#ffffff",
    "primary_hover": "#066b5e",
    "primary_disabled": "#d5e4e0",
    "primary_disabled_text": "#627a74",
    "danger_text": "#b32638",
    "input": "#ffffff",
    "popup": "#ffffff",
    "popup_selection": "#d3eee7",
    "list": "#ffffff",
    "selection": "#d3eee7",
    "selected_text": "#12473d",
    "input_border": "#7a8d9d",
    "splitter_hover": "#e1e7ec",
    "scrollbar": "#a5b1bd",
    "scrollbar_hover": "#778b9b",
    "pressed_border": "#258b7e",
    "focus_border": "#258b7e",
    "pressed_surface": "#cdd9e1",
    "primary_pressed": "#05594f",
    "item_focus": "#258b7e",
    "disabled_text": "#65717e",
}
DARK = {**DEFAULT_COLORS, **DARK}
LIGHT = {**DEFAULT_COLORS, **LIGHT}
THEMES = {"dark": DARK, "light": LIGHT}


def resolved_theme(mode):
    # Compatibility with the short-lived four-choice appearance settings.
    return mode if isinstance(mode, str) and mode in {*THEMES, "system"} else "dark"


def system_colors(palette):
    from .system_palette import blend

    role = QPalette.ColorRole
    color = lambda key: palette.color(key).name()
    window, button, text, accent = (
        palette.color(key) for key in (role.Window, role.Button, role.WindowText, role.Highlight)
    )
    muted = palette.color(role.PlaceholderText).name()
    disabled = palette.color(QPalette.ColorGroup.Disabled, role.Text).name()
    border = palette.color(role.Mid).name()
    return {
        "window": color(role.Window),
        "text": color(role.WindowText),
        "heading": color(role.WindowText),
        "muted": muted,
        "card": color(role.AlternateBase),
        "border": border,
        "accent": color(role.Link),
        "button": color(role.Button),
        "strong_border": border,
        "hover": blend(button, accent, 0.12).name(),
        "button_hover": blend(button, accent, 0.20).name(),
        "focus": color(role.Highlight),
        "disabled_border": disabled,
        "disabled_surface": color(role.Button),
        "primary": color(role.Highlight),
        "primary_text": color(role.HighlightedText),
        "primary_hover": blend(accent, text, 0.12).name(),
        "primary_disabled": color(role.Button),
        "primary_disabled_text": disabled,
        "danger_text": "#f0a7ac" if window.lightness() < 128 else "#b32638",
        "input": color(role.Base),
        "popup": color(role.Base),
        "popup_selection": color(role.Highlight),
        "list": color(role.Base),
        "selection": color(role.Highlight),
        "selected_text": color(role.HighlightedText),
        "input_border": border,
        "splitter_hover": blend(window, accent, 0.12).name(),
        "scrollbar": blend(window, text, 0.38).name(),
        "scrollbar_hover": blend(window, text, 0.55).name(),
        "pressed_border": color(role.Highlight),
        "focus_border": color(role.Highlight),
        "pressed_surface": blend(button, accent, 0.28).name(),
        "primary_pressed": blend(accent, window, 0.15).name(),
        "item_focus": color(role.Highlight),
        "disabled_text": disabled,
    }


class ThemeController(QObject):
    def __init__(self, window, base_style):
        super().__init__(window)
        configure_palette()
        self.window = window
        self.base_style = base_style
        from .storage import atomic_json, read_json

        settings_path = window.repository.directory / "settings.json"
        from .migrations import migrate_settings

        previous_settings = read_json(settings_path, {})
        settings = migrate_settings(previous_settings)
        mode = settings.get("theme", "dark")
        self.mode = resolved_theme(mode)
        if settings != previous_settings:
            atomic_json(settings_path, settings)
        self.effective = None
        from .system_palette import system_palette_source

        self.system_source = system_palette_source()
        self.system_source.changed.connect(self.system_changed)
        self.icon_directory = QTemporaryDir(
            str(Path(QDir.tempPath()) / "optidx-theme-icons-XXXXXX")
        )
        if not self.icon_directory.isValid():
            raise OSError("Could not create a temporary theme icon directory")
        QApplication.instance().installEventFilter(self)
        self.apply()

    def set_mode(self, mode):
        self.mode = resolved_theme(mode)
        self.apply()

    def system_changed(self):
        if self.mode == "system":
            self.apply()

    def apply(self):
        effective = resolved_theme(self.mode)
        native_palette = self.system_source.palette() if effective == "system" else None
        colors = system_colors(native_palette) if native_palette is not None else THEMES[effective]

        def recolor(text):
            return Template(text).substitute(colors)

        palette = QPalette()
        for role, color in {
            QPalette.ColorRole.Window: "window",
            QPalette.ColorRole.WindowText: "text",
            QPalette.ColorRole.Base: "input",
            QPalette.ColorRole.AlternateBase: "card",
            QPalette.ColorRole.Text: "text",
            QPalette.ColorRole.Button: "button",
            QPalette.ColorRole.ButtonText: "text",
            QPalette.ColorRole.Highlight: "selection",
            QPalette.ColorRole.HighlightedText: "selected_text",
            QPalette.ColorRole.ToolTipBase: "button",
            QPalette.ColorRole.ToolTipText: "text",
            QPalette.ColorRole.Light: "strong_border",
            QPalette.ColorRole.Midlight: "border",
            QPalette.ColorRole.Mid: "border",
            QPalette.ColorRole.Dark: "window",
            QPalette.ColorRole.Shadow: "window",
            QPalette.ColorRole.Link: "accent",
        }.items():
            palette.setColor(role, QColor(colors[color]))
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
            QPalette.ColorRole.WindowText,
        ):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled_text"]))
        if native_palette is not None:
            palette = native_palette
        self.effective = effective
        self.palette = palette
        self.window.setPalette(palette)
        for widget in self.window.findChildren(QWidget):
            if widget.isWindow():
                widget.setPalette(palette)
        assets = Path(__file__).parent / "assets"
        suffix = "-light" if effective == "light" else ""
        sheet = recolor(
            self.base_style
            + CONTROL_STYLE
            + '\nQLabel[detected="true"] { color: $accent; }\nQLabel[detected="false"] { color: $disabled_text; }'
        )
        sheet = sheet.replace("__CHECK_ICON__", str(assets / ("check" + suffix + ".svg")))
        sheet = sheet.replace("__CHEVRON_ICON__", str(assets / ("chevron" + suffix + ".svg")))
        if effective == "system":
            import hashlib

            icon_colors = (palette.highlightedText().color().name(), palette.text().color().name())
            for token, stroke, drawing in [
                ("__CHECK_ICON__", icon_colors[0], '<path d="M3 8.2 6.5 11.5 13 4.5"/>'),
                ("__CHEVRON_ICON__", icon_colors[1], '<path d="m3 6 5 5 5-5"/>'),
            ]:
                svg = (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><g fill="none" stroke="'
                    + stroke
                    + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                    + drawing
                    + "</g></svg>"
                )
                path = Path(self.icon_directory.path()) / (
                    hashlib.sha256(svg.encode()).hexdigest() + ".svg"
                )
                if not path.exists():
                    path.write_text(svg)
                original = str(
                    assets / ("check.svg" if token == "__CHECK_ICON__" else "chevron.svg")
                )
                sheet = sheet.replace(original, str(path))

            def native(role):
                return palette.color(role).name()

            sheet += (
                "\nQLineEdit, QPlainTextEdit, QComboBox, QListWidget, QComboBox QAbstractItemView { color: "
                + native(QPalette.ColorRole.Text)
                + "; }"
            )
            sheet += (
                "\nQPushButton, QToolButton { color: "
                + native(QPalette.ColorRole.ButtonText)
                + "; }"
            )
            sheet += (
                "\nQPushButton#primary { color: "
                + native(QPalette.ColorRole.HighlightedText)
                + "; }"
            )
            sheet += (
                "\nQToolTip { background: "
                + native(QPalette.ColorRole.ToolTipBase)
                + "; color: "
                + native(QPalette.ColorRole.ToolTipText)
                + "; }"
            )
            sheet += (
                "\nQComboBox QAbstractItemView::item:selected, QListWidget::item:selected { color: "
                + native(QPalette.ColorRole.HighlightedText)
                + "; }"
            )
        self.window.setStyleSheet(sheet)

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
            and self.window.isAncestorOf(watched)
        ):
            watched.setPalette(self.palette)
        return False
