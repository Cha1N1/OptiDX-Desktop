import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from PySide6.QtTest import QTest
from optidx_desktop.system_palette import SystemPalette, kde_palette, system_palette_source
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from optidx_desktop.app import MainWindow
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository, atomic_json, read_json
from optidx_desktop.theme import DARK, LIGHT, resolved_theme


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'game.exe').write_bytes(b'exe')
        self.game = manual_game(root / 'game.exe', 'Example')
        self.repo = Repository(root / 'data')
        self.repo.save_games([self.game])
        self.source = system_palette_source()
        self.source.timer.stop()
        self.saved_native = QPalette(self.source.native)
        self.saved_kde_path = self.source.kde_path
        self.source.kde_path = None
        self.window = MainWindow(self.repo, auto_scan=False)

    def tearDown(self):
        self.window.close(); self.window.deleteLater(); self.app.processEvents()
        self.source.timer.stop()
        self.source.native = self.saved_native
        self.source.kde_path = self.saved_kde_path
        self.temp.cleanup()

    def choose(self, mode):
        combo = self.window.features.theme_choice
        combo.setCurrentIndex(combo.findData(mode))
        self.app.processEvents()

    def test_default_dark_uses_navy_colors_and_unknown_values_are_safe(self):
        self.assertEqual(self.window.theme.mode, 'dark')
        self.assertEqual(self.window.theme.effective, 'dark')
        self.assertEqual(self.window.palette().color(QPalette.ColorRole.Window).name(), '#090c12')
        self.assertEqual(resolved_theme('invalid'), 'dark')
        self.assertEqual(resolved_theme([]), 'dark')

    def test_choice_persists_without_saving_game_drafts_or_deploying(self):
        self.window.features.environment.setPlainText('{unfinished')
        before = self.window.capture_form()
        self.choose('light')
        self.assertEqual(read_json(self.repo.directory / 'settings.json')['theme'], 'light')
        self.assertEqual(self.window.capture_form(), before)
        self.assertFalse(self.repo.preferences(self.game))
        self.assertFalse(self.window.queue)
        self.assertEqual(sorted(p.name for p in self.game.target.iterdir()), ['data', 'game.exe'])
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertEqual(another.theme.effective, 'light')
            self.assertEqual(another.features.theme_choice.currentData(), 'light')
        finally:
            another.close(); another.deleteLater()

    def test_general_settings_preserve_theme_and_unknown_settings(self):
        self.choose('light')
        self.choose('dark')
        saved = read_json(self.repo.directory / 'settings.json')
        atomic_json(self.repo.directory / 'settings.json', {**saved, 'future_setting': 'retain'})
        self.window.features.reduce_motion.setChecked(True)
        self.window.features.save_app_settings()
        saved = read_json(self.repo.directory / 'settings.json')
        self.assertEqual(saved['theme'], 'dark')
        self.assertEqual(saved['future_setting'], 'retain')
        self.assertTrue(saved['reduce_motion'])

    def test_system_uses_native_palette_and_updates_without_affecting_forced_modes(self):
        native = QPalette(self.app.palette())
        native.setColor(QPalette.ColorRole.Window, QColor('#35214b'))
        native.setColor(QPalette.ColorRole.Text, QColor('#efdbff'))
        native.setColor(QPalette.ColorRole.Highlight, QColor('#b787ef'))
        native.setColor(QPalette.ColorRole.HighlightedText, QColor('#1f1030'))
        self.source.native = native
        self.choose('system')
        self.assertEqual(self.window.theme.effective, 'system')
        self.assertTrue(Path(self.window.theme.icon_directory.path()).is_absolute())
        self.assertEqual(self.window.palette().color(QPalette.ColorRole.Window).name(), '#35214b')
        self.assertIn('background: #b787ef', self.window.styleSheet())
        self.assertIn('color: #efdbff', self.window.styleSheet())
        native.setColor(QPalette.ColorRole.Highlight, QColor('#d45e91'))
        self.source.native = native
        self.source.changed.emit()
        self.assertIn('background: #d45e91', self.window.styleSheet())
        self.choose('dark')
        before = self.window.styleSheet()
        self.source.changed.emit()
        self.assertEqual(self.window.theme.effective, 'dark')
        self.assertEqual(self.window.styleSheet(), before)

    def test_legacy_original_migrates_and_only_three_choices_remain(self):
        atomic_json(self.repo.directory / 'settings.json', {'theme': 'original', 'future': True})
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertEqual(another.theme.mode, 'dark')
            self.assertEqual(another.features.theme_choice.count(), 3)
            self.assertEqual(read_json(self.repo.directory / 'settings.json'), {'theme': 'dark', 'future': True})
            self.assertEqual(another.palette().color(QPalette.ColorRole.Window).name(), '#090c12')
        finally:
            another.close(); another.deleteLater()

    def test_preset_changes_do_not_overwrite_the_application_native_palette(self):
        before = QPalette(self.app.palette())
        self.choose('light'); self.choose('dark'); self.choose('system')
        self.assertEqual(self.app.palette(), before)

    def test_kde_colors_support_rgb_values_and_live_atomic_replacement(self):
        from unittest.mock import patch
        root = Path(self.temp.name) / 'config'
        root.mkdir()
        path = root / 'kdeglobals'
        path.write_text('[Colors:Window]\nBackgroundNormal=21,15,34\nForegroundNormal=#efdfff\n[Colors:Selection]\nBackgroundNormal=#ba8aff\nForegroundNormal=#241132\n')
        palette = kde_palette(self.app.palette(), path)
        self.assertEqual(palette.window().color().name(), '#150f22')
        self.assertEqual(palette.highlight().color().name(), '#ba8aff')
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE', 'XDG_CONFIG_HOME': str(root)}):
            source = SystemPalette(self.app)
        changes = []
        source.changed.connect(lambda: changes.append(True))
        try:
            replacement = root / 'replacement'
            replacement.write_text('[Colors:Window]\nBackgroundNormal=#f0e2ff\n')
            replacement.replace(path)
            QTest.qWait(300)
            self.assertTrue(changes)
            self.assertEqual(source.palette().window().color().name(), '#f0e2ff')
            self.assertIn(str(path), source.watcher.files())
            count = len(changes)
            source.refresh()
            self.assertEqual(len(changes), count)
        finally:
            source.timer.stop(); source.deleteLater()

    def test_light_popup_and_diagnostics_use_light_palette_and_icons(self):
        self.window.show(); self.choose('light')
        self.window.filter.showPopup(); self.app.processEvents()
        palette = self.window.filter.view().palette()
        self.assertEqual(palette.color(QPalette.ColorRole.Text).name(), '#202a35')
        self.assertIn('check-light.svg', self.window.styleSheet())
        self.assertIn('chevron-light.svg', self.window.styleSheet())
        self.assertIn('color: #08796b', self.window.styleSheet())
        self.window.filter.hidePopup()
        self.choose('dark')
        self.assertNotIn('check-light.svg', self.window.styleSheet())

    def test_theme_body_and_muted_text_have_readable_contrast(self):
        def luminance(color):
            rgb = QColor(color).getRgbF()[:3]
            linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
            return sum(c * weight for c, weight in zip(linear, [.2126, .7152, .0722]))
        for colors in [{}, DARK, LIGHT]:
            for foreground in ['#dbe3ed', '#94a3b8']:
                for background in ['#11151c', '#191f29', '#151b25']:
                    a,b = sorted([luminance(colors.get(foreground,foreground)), luminance(colors.get(background,background))])
                    self.assertGreaterEqual((b + .05) / (a + .05), 4.5)
