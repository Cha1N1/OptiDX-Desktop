"""Original dark styling, a light preset, and actual desktop Qt palette colors."""
from pathlib import Path
import re

from PySide6.QtCore import QDir, QEvent, QObject, QTemporaryDir
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget


def configure_palette():
    app = QApplication.instance()
    if app.property('optidxThemeReady'):
        return
    from .system_palette import system_palette_source
    system_palette_source()  # Capture native colors before installing our consistent control style.
    # Fusion avoids mixing desktop-provided light popup frames with dark QSS.
    app.setStyle('Fusion')
    app.setProperty('optidxThemeReady', True)


CONTROL_STYLE = """
/* No platform scrollbar arrows or bright native popup frames. */
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; border: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 3px; border: none; }
QScrollBar::handle:vertical { background: #3b485a; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:horizontal { background: #3b485a; min-width: 28px; border-radius: 4px; }
QScrollBar::handle:hover { background: #5a7084; }
QScrollBar::handle:pressed { background: #75b8b2; }
QScrollBar::add-line, QScrollBar::sub-line { background: transparent; border: none; width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: #151b25; border: none; }
QComboBox { padding-right: 28px; selection-background-color: #263e41; }
QComboBox:hover { border-color: #53657c; }
QComboBox:on { border-color: #62a99f; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; background: transparent; }
QComboBox::down-arrow { image: url("__CHEVRON_ICON__"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #191f29; color: #dbe3ed; border: 1px solid #344155;
    border-radius: 6px; padding: 4px; outline: 0; selection-background-color: #263e41; selection-color: #c8fff5; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 3px 9px; border: none; border-radius: 4px; }
QComboBox QAbstractItemView::item:selected { background: #263e41; color: #c8fff5; }
QComboBoxPrivateContainer { background: #191f29; border: none; padding: 0; }
QMenu { background: #191f29; border: 1px solid #344155; border-radius: 6px; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 4px; }
QMenu::item:selected { background: #263e41; }
QMenu::separator { height: 1px; background: #344155; margin: 4px 7px; }
QToolTip { background: #232c3a; color: #dbe3ed; border: 1px solid #344155; padding: 6px; }
QPushButton:pressed, QToolButton:pressed { background: #1c2835; border-color: #75b8b2; }
QPushButton#primary:pressed { background: #4bb6a7; }
QPushButton:focus, QToolButton:focus { border: 1px solid #62a99f; }
QCheckBox:disabled { color: #6f7e91; }
QCheckBox::indicator:disabled { background: #1c222c; border-color: #293241; }
QListWidget { outline: 0; }
QListWidget::item:focus { border: 1px solid #436a6b; }
QLineEdit:disabled, QComboBox:disabled { color: #6f7e91; border-color: #293241; }
QPlainTextEdit:focus { border-color: #62a99f; }
QSpinBox { background: #151b25; color: #dbe3ed; border: 1px solid #344155; border-radius: 6px; padding: 6px; }
QGroupBox { border: 1px solid #293241; border-radius: 8px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
"""


# Canonical colors are the existing Original theme. Substitute each literal once
# so shared geometry and interaction states remain identical between themes.
DARK = {
    '#11151c': '#090c12', '#151b25': '#0d111a', '#191f29': '#121823',
    '#151b24': '#0d111a', '#202938': '#151d2a',
    '#75ded2': '#ffffff', '#62d6c4': '#ffffff', '#102522': '#090c12',
    '#8de6d9': '#ffffff', '#263e41': '#273246', '#315052': '#273246',
    '#c8fff5': '#ffffff', '#75b8b2': '#d4deed', '#62a99f': '#d4deed',
    '#4bb6a7': '#c3cede', '#436a6b': '#d4deed', '#253e3c': '#1c2534',
    '#698782': '#8793a6',
    '#232c3a': '#191f2b', '#232e3c': '#202838', '#303d50': '#293448',
    '#1c222c': '#141a25', '#1b2430': '#141c28', '#1c2835': '#1c2635',
}
LIGHT = {
    '#11151c': '#f2f4f6', '#dbe3ed': '#202a35', '#f0f6fc': '#15212c',
    '#94a3b8': '#596879', '#191f29': '#ffffff', '#293241': '#d1d9e0',
    '#75ded2': '#08796b', '#232c3a': '#e5e9ed', '#344155': '#bec9d3',
    '#232e3c': '#e8eef2', '#303d50': '#d7e1e8', '#64748b': '#667b8f',
    '#596577': '#75808c', '#1c222c': '#e5e9ed', '#62d6c4': '#087f70',
    '#102522': '#ffffff', '#8de6d9': '#066b5e', '#253e3c': '#d5e4e0',
    '#698782': '#627a74', '#f0a7ac': '#b32638', '#151b25': '#ffffff',
    '#202938': '#ffffff', '#315052': '#d3eee7', '#151b24': '#ffffff',
    '#263e41': '#d3eee7', '#c8fff5': '#12473d', '#53657c': '#7a8d9d',
    '#1b2430': '#e1e7ec', '#3b485a': '#a5b1bd', '#5a7084': '#778b9b',
    '#75b8b2': '#258b7e', '#62a99f': '#258b7e', '#1c2835': '#cdd9e1',
    '#4bb6a7': '#05594f', '#436a6b': '#258b7e', '#6f7e91': '#65717e',
}
THEMES = {'dark': DARK, 'light': LIGHT}


def resolved_theme(mode):
    # Compatibility with the short-lived four-choice appearance settings.
    return mode if isinstance(mode, str) and mode in {*THEMES, 'system'} else 'dark'


def system_colors(palette):
    from .system_palette import blend
    role = QPalette.ColorRole
    color = lambda key: palette.color(key).name()
    window, button, text, accent = (palette.color(key) for key in (role.Window, role.Button, role.WindowText, role.Highlight))
    muted = palette.color(role.PlaceholderText).name()
    disabled = palette.color(QPalette.ColorGroup.Disabled, role.Text).name()
    border = palette.color(role.Mid).name()
    return {
        '#11151c': color(role.Window), '#dbe3ed': color(role.WindowText), '#f0f6fc': color(role.WindowText),
        '#94a3b8': muted, '#191f29': color(role.AlternateBase), '#293241': border,
        '#75ded2': color(role.Link), '#232c3a': color(role.Button), '#344155': border,
        '#232e3c': blend(button, accent, .12).name(), '#303d50': blend(button, accent, .20).name(),
        '#64748b': color(role.Highlight), '#596577': disabled, '#1c222c': color(role.Button),
        '#62d6c4': color(role.Highlight), '#102522': color(role.HighlightedText),
        '#8de6d9': blend(accent, text, .12).name(), '#253e3c': color(role.Button), '#698782': disabled,
        '#f0a7ac': '#f0a7ac' if window.lightness() < 128 else '#b32638',
        '#151b25': color(role.Base), '#202938': color(role.Base), '#315052': color(role.Highlight),
        '#151b24': color(role.Base), '#263e41': color(role.Highlight), '#c8fff5': color(role.HighlightedText),
        '#53657c': border, '#1b2430': blend(window, accent, .12).name(),
        '#3b485a': blend(window, text, .38).name(), '#5a7084': blend(window, text, .55).name(),
        '#75b8b2': color(role.Highlight), '#62a99f': color(role.Highlight),
        '#1c2835': blend(button, accent, .28).name(), '#4bb6a7': blend(accent, window, .15).name(),
        '#436a6b': color(role.Highlight), '#6f7e91': disabled,
    }


class ThemeController(QObject):
    def __init__(self, window, base_style):
        super().__init__(window)
        configure_palette()
        self.window = window
        self.base_style = base_style
        from .storage import atomic_json, read_json
        settings_path = window.repository.directory / 'settings.json'
        settings = read_json(settings_path, {})
        mode = settings.get('theme', 'dark')
        self.mode = resolved_theme(mode)
        if mode == 'original':
            atomic_json(settings_path, {**settings, 'theme': 'dark'})
        self.effective = None
        from .system_palette import system_palette_source
        self.system_source = system_palette_source()
        self.system_source.changed.connect(self.system_changed)
        self.icon_directory = QTemporaryDir(str(Path(QDir.tempPath()) / 'optidx-theme-icons-XXXXXX'))
        if not self.icon_directory.isValid():
            raise OSError('Could not create a temporary theme icon directory')
        QApplication.instance().installEventFilter(self)
        self.apply()

    def set_mode(self, mode):
        self.mode = resolved_theme(mode)
        self.apply()

    def system_changed(self):
        if self.mode == 'system': self.apply()

    def apply(self):
        effective = resolved_theme(self.mode)
        native_palette = self.system_source.palette() if effective == 'system' else None
        colors = system_colors(native_palette) if native_palette is not None else THEMES[effective]
        def recolor(text):
            return re.sub(r'#[0-9a-fA-F]{6}', lambda match: colors.get(match.group().lower(), match.group()), text)
        palette = QPalette()
        for role, color in {
            QPalette.ColorRole.Window: '#11151c', QPalette.ColorRole.WindowText: '#dbe3ed',
            QPalette.ColorRole.Base: '#151b25', QPalette.ColorRole.AlternateBase: '#191f29',
            QPalette.ColorRole.Text: '#dbe3ed', QPalette.ColorRole.Button: '#232c3a',
            QPalette.ColorRole.ButtonText: '#dbe3ed', QPalette.ColorRole.Highlight: '#263e41',
            QPalette.ColorRole.HighlightedText: '#c8fff5', QPalette.ColorRole.ToolTipBase: '#232c3a',
            QPalette.ColorRole.ToolTipText: '#dbe3ed', QPalette.ColorRole.Light: '#344155',
            QPalette.ColorRole.Midlight: '#293241', QPalette.ColorRole.Mid: '#293241',
            QPalette.ColorRole.Dark: '#11151c', QPalette.ColorRole.Shadow: '#11151c',
            QPalette.ColorRole.Link: '#75ded2',
        }.items():
            palette.setColor(role, QColor(colors.get(color, color)))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors.get('#6f7e91', '#6f7e91')))
        if native_palette is not None:
            palette = native_palette
        self.effective = effective
        self.palette = palette
        self.window.setPalette(palette)
        for widget in self.window.findChildren(QWidget):
            if widget.isWindow(): widget.setPalette(palette)
        assets = Path(__file__).parent / 'assets'
        suffix = '-light' if effective == 'light' else ''
        sheet = recolor(self.base_style + CONTROL_STYLE + '\nQLabel[detected="true"] { color: #75ded2; }\nQLabel[detected="false"] { color: #6f7e91; }')
        sheet = sheet.replace('__CHECK_ICON__', str(assets / ('check' + suffix + '.svg')))
        sheet = sheet.replace('__CHEVRON_ICON__', str(assets / ('chevron' + suffix + '.svg')))
        if effective == 'system':
            import hashlib
            icon_colors = (palette.highlightedText().color().name(), palette.text().color().name())
            for token, stroke, drawing in [
                    ('__CHECK_ICON__', icon_colors[0], '<path d="M3 8.2 6.5 11.5 13 4.5"/>'),
                    ('__CHEVRON_ICON__', icon_colors[1], '<path d="m3 6 5 5 5-5"/>')]:
                svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><g fill="none" stroke="' + stroke + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + drawing + '</g></svg>'
                path = Path(self.icon_directory.path()) / (hashlib.sha256(svg.encode()).hexdigest() + '.svg')
                if not path.exists(): path.write_text(svg)
                original = str(assets / ('check.svg' if token == '__CHECK_ICON__' else 'chevron.svg'))
                sheet = sheet.replace(original, str(path))
            def native(role): return palette.color(role).name()
            sheet += '\nQLineEdit, QPlainTextEdit, QComboBox, QListWidget, QComboBox QAbstractItemView { color: ' + native(QPalette.ColorRole.Text) + '; }'
            sheet += '\nQPushButton, QToolButton { color: ' + native(QPalette.ColorRole.ButtonText) + '; }'
            sheet += '\nQPushButton#primary { color: ' + native(QPalette.ColorRole.HighlightedText) + '; }'
            sheet += '\nQToolTip { background: ' + native(QPalette.ColorRole.ToolTipBase) + '; color: ' + native(QPalette.ColorRole.ToolTipText) + '; }'
            sheet += '\nQComboBox QAbstractItemView::item:selected, QListWidget::item:selected { color: ' + native(QPalette.ColorRole.HighlightedText) + '; }'
        self.window.setStyleSheet(sheet)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and
                watched.isWindow() and self.window.isAncestorOf(watched)):
            watched.setPalette(self.palette)
        return False
