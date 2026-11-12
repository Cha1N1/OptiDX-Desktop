import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from optidx_desktop.library import manual_game
from optidx_desktop.status import action_states, game_status, install_problems
from optidx_desktop.storage import Repository


class StatusModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.games = []
        for name in ("Alpha", "Bravo"):
            folder = self.root / name
            folder.mkdir()
            (folder / (name + ".exe")).write_bytes(b"MZ")
            self.games.append(manual_game(folder / (name + ".exe"), name))
        self.repo = Repository(self.root / "data")
        self.repo.save_games(self.games)

    def tearDown(self):
        self.temp.cleanup()

    def corrupt_ledger(self, game):
        (game.target / ".optidx-desktop-assets.json").write_text("{broken")

    def test_corrupt_ledger_is_isolated_and_preserved(self):
        self.corrupt_ledger(self.games[1])
        healthy, broken = (game_status(game, self.repo) for game in self.games)
        self.assertFalse(healthy.errors)
        self.assertTrue(broken.needs_attention)
        self.assertIn(".optidx-desktop-assets.json", broken.errors[0])
        # Evidence is never rewritten by a status read.
        self.assertEqual(
            (self.games[1].target / ".optidx-desktop-assets.json").read_text(), "{broken"
        )

    def test_management_actions_blocked_for_unreadable_records(self):
        self.corrupt_ledger(self.games[0])
        status = game_status(self.games[0], self.repo)
        states = action_states(
            status,
            {"executable_exists": True, "apis": ["DX12"]},
            busy=False,
            chosen={"optiscaler"},
            prune=False,
            problems=[],
            launchable=False,
        )
        for action in ("install", "update", "remove", "configure"):
            self.assertFalse(states[action].enabled)
            self.assertIn("Unreadable record", states[action].reason)

    def test_corrupt_profile_disables_save_without_overwriting(self):
        path = self.repo.directory / "profiles" / (self.games[0].id + ".json")
        path.parent.mkdir(parents=True)
        path.write_text("{bad")
        status = game_status(self.games[0], self.repo)
        self.assertTrue(status.profile_error)
        states = action_states(
            status,
            {"executable_exists": True},
            busy=False,
            chosen=set(),
            prune=False,
            problems=[],
            launchable=False,
        )
        self.assertFalse(states["save"].enabled)
        self.assertEqual(path.read_text(), "{bad")

    def test_dependency_and_exclusive_rules(self):
        problems = install_problems({"renodx", "helixsr", "amd_fsr"}, {}, "")
        self.assertTrue(any(p.startswith("RenoDX requires") for p in problems))
        self.assertTrue(any(p.startswith("HelixSR requires") for p in problems))
        self.assertTrue(any("not both" in p for p in problems))
        self.assertIn("Choose the locally built HelixSR FSR DLL", problems)
        self.assertEqual(install_problems({"renodx"}, {"ReShade": True}), [])


class CorruptRecordStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_starts_and_marks_only_the_affected_game(self):
        from optidx_desktop.app import MainWindow

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            games = []
            for name in ("Alpha", "Bravo"):
                (root / name).mkdir()
                (root / name / "game.exe").write_bytes(b"MZ")
                games.append(manual_game(root / name / "game.exe", name))
            (games[1].target / ".optidx-desktop-assets.json").write_text("{broken")
            repo = Repository(root / "data")
            repo.save_games(games)
            profile = repo.directory / "profiles" / (games[0].id + ".json")
            profile.parent.mkdir(parents=True)
            profile.write_text("{bad")
            window = MainWindow(repo, auto_scan=False)
            try:
                self.assertEqual(window.list.count(), 2)
                self.assertFalse(window.list.signalsBlocked())
                texts = [window.list.item(i).text() for i in range(2)]
                self.assertTrue(all("Needs attention" in text for text in texts))
                for row, game in enumerate(sorted(games, key=lambda g: g.title)):
                    window.list.setCurrentRow(row)
                    self.assertFalse(window.install_button.isEnabled())
                    self.assertIn("Needs attention", window.notes.text())
                window.list.setCurrentRow(0)  # Alpha: unreadable profile
                self.assertFalse(window.save_button.isEnabled())
                window.list.setCurrentRow(1)  # Bravo: profile is readable
                self.assertTrue(window.save_button.isEnabled())
                self.assertEqual(profile.read_text(), "{bad")
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
