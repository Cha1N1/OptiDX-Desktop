"""Read desktop Qt colors without letting app-owned palettes feed back into them."""
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QObject, QSettings, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def blend(first, second, amount):
    return QColor.fromRgbF(*[a * (1 - amount) + b * amount
                            for a,b in zip(first.getRgbF()[:3], second.getRgbF()[:3])])


def kde_palette(base, path):
    """Use KDE's actual Qt color groups even without a bundled KDE theme plugin."""
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    palette = QPalette(base)
    roles = {
        'Colors:Window': {'BackgroundNormal': QPalette.ColorRole.Window, 'ForegroundNormal': QPalette.ColorRole.WindowText},
        'Colors:View': {'BackgroundNormal': QPalette.ColorRole.Base, 'BackgroundAlternate': QPalette.ColorRole.AlternateBase,
                        'ForegroundNormal': QPalette.ColorRole.Text, 'ForegroundLink': QPalette.ColorRole.Link,
                        'ForegroundVisited': QPalette.ColorRole.LinkVisited, 'ForegroundInactive': QPalette.ColorRole.PlaceholderText},
        'Colors:Button': {'BackgroundNormal': QPalette.ColorRole.Button, 'ForegroundNormal': QPalette.ColorRole.ButtonText},
        'Colors:Selection': {'BackgroundNormal': QPalette.ColorRole.Highlight, 'ForegroundNormal': QPalette.ColorRole.HighlightedText},
        'Colors:Tooltip': {'BackgroundNormal': QPalette.ColorRole.ToolTipBase, 'ForegroundNormal': QPalette.ColorRole.ToolTipText},
    }
    def read(key):
        value = settings.value(key)
        if isinstance(value, (list, tuple)):
            try: return QColor(*[int(part) for part in value])
            except (ValueError, TypeError): return QColor()
        return QColor(str(value)) if value is not None else QColor()
    found = False
    for group, entries in roles.items():
        for key, role in entries.items():
            color = read(group + '/' + key)
            if color.isValid():
                palette.setColor(role, color)
                found = True
        inactive = read(group + '/ForegroundInactive')
        foreground = entries.get('ForegroundNormal')
        if foreground is not None and inactive.isValid():
            palette.setColor(QPalette.ColorGroup.Disabled, foreground, inactive)
    if found:
        window, text = palette.window().color(), palette.windowText().color()
        for role, amount in [(QPalette.ColorRole.Mid, .25), (QPalette.ColorRole.Midlight, .16),
                             (QPalette.ColorRole.Light, .12), (QPalette.ColorRole.Dark, .32)]:
            palette.setColor(role, blend(window, text, amount))
        palette.setColor(QPalette.ColorRole.Shadow, window.darker(130))
        palette.setColor(QPalette.ColorRole.Accent, palette.highlight().color())
    return palette


class SystemPalette(QObject):
    changed = Signal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.native = QPalette(app.palette())
        self.watcher = QFileSystemWatcher(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.refresh)
        self.kde_path = None
        if 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':'):
            self.kde_path = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'kdeglobals'
            if self.kde_path.parent.is_dir(): self.watcher.addPath(str(self.kde_path.parent))
            self.watch_file()
        self.watcher.fileChanged.connect(self.schedule)
        self.watcher.directoryChanged.connect(self.schedule)
        app.styleHints().colorSchemeChanged.connect(self.schedule)
        app.installEventFilter(self)
        self.current = self.palette()

    def watch_file(self):
        if self.kde_path and self.kde_path.is_file() and str(self.kde_path) not in self.watcher.files():
            self.watcher.addPath(str(self.kde_path))

    def schedule(self, *args):
        self.timer.start()

    def refresh(self):
        self.native = QPalette(self.app.palette())
        self.watch_file()  # KDE may atomically replace kdeglobals on a theme change.
        current = self.palette()
        if current != self.current:
            self.current = current
            self.changed.emit()

    def palette(self):
        return kde_palette(self.native, self.kde_path) if self.kde_path else QPalette(self.native)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self.schedule()
        return False


def system_palette_source():
    app = QApplication.instance()
    if not hasattr(app, '_optidx_system_palette'):
        app._optidx_system_palette = SystemPalette(app)
    return app._optidx_system_palette
