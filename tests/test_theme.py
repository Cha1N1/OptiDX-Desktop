import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import tempfile
import unittest

from pathlib import Path
from optidx_desktop.system_palette import system_palette_source
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
from optidx_desktop.app import MainWindow
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository, atomic_json, read_json


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "game.exe").write_bytes(b"exe")
        self.game = manual_game(root / "game.exe", "Example")
        self.repo = Repository(root / "data")
        self.repo.save_games([self.game])
        self.source = system_palette_source()
        self.source.timer.stop()
        self.saved_native = QPalette(self.source.native)
        self.saved_kde_path = self.source.kde_path
        self.source.kde_path = None
        self.window = MainWindow(self.repo, auto_scan=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.source.timer.stop()
        self.source.native = self.saved_native
        self.source.kde_path = self.saved_kde_path
        self.temp.cleanup()

    def choose(self, mode):
        combo = self.window.features.theme_choice
        combo.setCurrentIndex(combo.findData(mode))
        self.app.processEvents()

    def test_choice_persists_without_saving_game_drafts_or_deploying(self):
        self.window.features.environment.setPlainText("{unfinished")
        before = self.window.capture_form()
        self.choose("light")
        self.assertEqual(read_json(self.repo.directory / "settings.json")["theme"], "light")
        self.assertEqual(self.window.capture_form(), before)
        self.assertFalse(self.repo.preferences(self.game))
        self.assertFalse(self.window.queue)
        self.assertEqual(sorted(p.name for p in self.game.target.iterdir()), ["data", "game.exe"])
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertEqual(another.theme.effective, "light")
            self.assertEqual(another.features.theme_choice.currentData(), "light")
        finally:
            another.close()
            another.deleteLater()

    def test_general_settings_preserve_theme_and_unknown_settings(self):
        self.choose("light")
        self.choose("dark")
        saved = read_json(self.repo.directory / "settings.json")
        atomic_json(self.repo.directory / "settings.json", {**saved, "future_setting": "retain"})
        self.window.features.reduce_motion.setChecked(True)
        self.window.features.save_app_settings()
        saved = read_json(self.repo.directory / "settings.json")
        self.assertEqual(saved["theme"], "dark")
        self.assertEqual(saved["future_setting"], "retain")
        self.assertTrue(saved["reduce_motion"])
