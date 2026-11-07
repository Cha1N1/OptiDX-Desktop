import contextlib
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helpers import pe_fixture
from optidx_desktop import assets
from optidx_desktop.backend import validate_game
from optidx_desktop.backups import snapshot, remember_baseline, restore_originals
from optidx_desktop.models import Game
from optidx_desktop.relocation import relocate_installation
from optidx_desktop.storage import Repository, read_json
from optidx_desktop.worker import _run_job


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "old-game"
        self.target = self.install / "Binaries/Win64"
        self.target.mkdir(parents=True)
        exe = self.target / "Game.exe"
        exe.write_bytes(pe_fixture())
        self.game = Game(
            "same-steam-id", "Moved game", "Steam", str(self.install), str(exe), app_id="123"
        )
        self.repo = Repository(self.root / "data")
        (self.target / "dxgi.dll").write_bytes(b"original DLL")
        self.baseline = snapshot(self.game, self.repo)
        remember_baseline(self.game, self.repo, self.baseline)
        assets.deploy(
            self.target, "backend:optiscaler", {"dxgi.dll": pe_fixture()}, allow_foreign=True
        )
        (self.target / ".optidx-files").write_text("dxgi.dll\n")
        (self.target / ".optidx-installed").write_text(str(self.target) + "\nvfixture\n")
        self.history = snapshot(self.game, self.repo)
        moved = self.root / "new-game"
        self.install.rename(moved)
        self.moved = replace(
            self.game, root=str(moved), executable=str(moved / "Binaries/Win64/Game.exe")
        )

    def test_rebind_preserves_original_recovery_and_payload_hashes(self):
        payload = (self.history / "files/.optidx-installed").read_bytes()
        self.assertTrue(relocate_installation(self.moved, self.repo))
        validate_game(self.moved)
        for folder in (self.baseline, self.history):
            self.assertEqual(read_json(folder / "snapshot.json")["target"], str(self.moved.target))
        self.assertEqual((self.history / "files/.optidx-installed").read_bytes(), payload)
        self.assertFalse(relocate_installation(self.moved, self.repo))
        assets.remove(self.moved.target, "backend:optiscaler")
        restore_originals(self.moved, self.repo)
        self.assertEqual((self.moved.target / "dxgi.dll").read_bytes(), b"original DLL")

    def test_copy_or_wrong_binary_is_not_automatically_adopted(self):
        self.target.mkdir(parents=True)
        with self.assertRaises(ValueError):
            relocate_installation(self.moved, self.repo)
        with self.assertRaises(ValueError):
            validate_game(self.moved, allow_moved=True)
        self.assertEqual(
            (self.moved.target / ".optidx-installed").read_text().splitlines()[0], str(self.target)
        )

    def test_modified_binary_or_corrupt_recovery_blocks_relocation(self):
        dll = self.moved.target / "dxgi.dll"
        original = dll.read_bytes()
        dll.write_bytes(b"external edit")
        with self.assertRaisesRegex(ValueError, "managed binary"):
            relocate_installation(self.moved, self.repo)
        dll.write_bytes(original)
        (self.history / "files/.optidx-installed").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "recovery checksum"):
            relocate_installation(self.moved, self.repo)
        self.assertEqual(read_json(self.baseline / "snapshot.json")["target"], str(self.target))

    def test_marker_alone_cannot_claim_moved_installation(self):
        (self.moved.target / assets.LEDGER).unlink()
        with self.assertRaisesRegex(ValueError, "No verified managed binaries"):
            relocate_installation(self.moved, self.repo)

    def test_metadata_write_failure_restores_all_records(self):
        marker = self.moved.target / ".optidx-installed"
        before = {
            p: p.read_bytes()
            for p in [marker, self.baseline / "snapshot.json", self.history / "snapshot.json"]
        }
        original = assets.atomic_bytes
        failed = False

        def fail_once(path, data, mode=0o644):
            nonlocal failed
            if Path(path) == marker and not failed:
                failed = True
                raise OSError("marker write failed")
            return original(path, data, mode)

        with patch.object(assets, "atomic_bytes", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "marker write failed"):
                relocate_installation(self.moved, self.repo)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertTrue(relocate_installation(self.moved, self.repo))

    def test_worker_rebinds_before_update_and_keeps_move_after_failed_job(self):
        with (
            patch(
                "optidx_desktop.worker.execute_backend", side_effect=RuntimeError("update failed")
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "update failed"):
                _run_job(
                    {"game": self.moved.to_dict(), "action": "update", "preferences": {}},
                    self.repo.directory,
                )
        validate_game(self.moved)
        self.assertEqual(
            read_json(self.baseline / "snapshot.json")["target"], str(self.moved.target)
        )
        self.assertTrue(
            list((self.repo.directory / "backups" / self.game.id / "relocations").glob("*.json"))
        )

    def test_interrupted_rebind_finishes_target_and_root_scopes(self):
        from optidx_desktop.storage import atomic_json

        root = Path(self.moved.root)
        assets.deploy(root, "dll:fixture", {"root.dll": pe_fixture()})
        root_history = snapshot(replace(self.moved, executable=""), self.repo)
        root_record = read_json(root_history / "snapshot.json")
        atomic_json(root_history / "snapshot.json", {**root_record, "target": self.game.root})
        # A crash after one metadata write leaves the old marker available.
        baseline = read_json(self.baseline / "snapshot.json")
        atomic_json(self.baseline / "snapshot.json", {**baseline, "target": str(self.moved.target)})
        relocate_installation(self.moved, self.repo)
        self.assertEqual(read_json(root_history / "snapshot.json")["target"], self.moved.root)
        self.assertEqual(
            read_json(self.history / "snapshot.json")["target"], str(self.moved.target)
        )
        validate_game(self.moved)

    def test_linked_recovery_folder_cannot_redirect_migration(self):
        base = self.repo.directory / "backups" / self.game.id
        outside = self.root / "unrelated"
        outside.mkdir()
        record = outside / "snapshot.json"
        from optidx_desktop.storage import atomic_json

        atomic_json(record, {"target": str(self.target), "files": []})
        (base / "linked").symlink_to(outside, target_is_directory=True)
        before = record.read_bytes()
        with self.assertRaises(ValueError):
            relocate_installation(self.moved, self.repo)
        self.assertEqual(record.read_bytes(), before)

    def test_legacy_install_without_asset_ledger_uses_recorded_cyboman_hash(self):
        from optidx_desktop.downloads import sha
        from optidx_desktop.storage import atomic_json
        import shutil

        target = self.moved.target
        (target / assets.LEDGER).unlink()
        dll = target / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
        dll.parent.mkdir()
        dll.write_bytes(pe_fixture())
        name = str(dll.relative_to(target))
        (target / ".optidx-files").write_text("dxgi.dll\n" + name + "\n")
        atomic_json(
            target / ".optidx-components.json", {"version": 1, "files": {"amd_fsr": [name]}}
        )
        atomic_json(dll.parent / ".optidx-amd-release.json", {"sha256": sha(dll.read_bytes())})
        shutil.rmtree(self.repo.directory / "backups" / self.game.id)
        self.assertTrue(relocate_installation(self.moved, self.repo))
        validate_game(self.moved)
        self.assertFalse((target / assets.LEDGER).exists())

    def test_read_only_job_does_not_rewrite_marker(self):
        marker = self.moved.target / ".optidx-installed"
        before = marker.read_bytes()
        with (
            patch("optidx_desktop.features.run_feature", return_value={}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            _run_job({"game": self.moved.to_dict(), "action": "check_updates"}, self.repo.directory)
        self.assertEqual(marker.read_bytes(), before)
