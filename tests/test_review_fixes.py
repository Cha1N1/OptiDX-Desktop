"""Integration regressions from the October 16 source review."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from helpers import pe_fixture
from optidx_desktop import assets
from optidx_desktop.backend import load_backend
from optidx_desktop.backups import (
    snapshot,
    finish_snapshots,
    cleanup_completed_snapshots,
    baseline_path,
)
from optidx_desktop.core_payload import install_optiscaler_payload
from optidx_desktop.features import update_features
from optidx_desktop.models import Game
from optidx_desktop.storage import Repository, atomic_json, read_json
from optidx_desktop.worker import run_job


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target = self.root / "game"
        self.target.mkdir()
        self.exe = self.target / "game.exe"
        self.exe.write_bytes(pe_fixture())
        self.game = Game("review", "Review", "Manual", str(self.target), str(self.exe))
        self.repo = Repository(self.root / "data")
        self.repo.save_games([self.game])

    def tearDown(self):
        self.temporary.cleanup()

    def test_executable_folder_change_keeps_originals_separate(self):
        from dataclasses import replace
        from optidx_desktop.backups import remember_baseline, restore_originals, prune_snapshots

        first = self.target / "dxgi.dll"
        first.write_bytes(b"first original")
        old = snapshot(self.game, self.repo)
        remember_baseline(self.game, self.repo, old)
        other = self.target / "renderer"
        other.mkdir()
        exe = other / "game.exe"
        exe.write_bytes(pe_fixture())
        game = replace(self.game, executable=str(exe))
        dll = other / "dxgi.dll"
        dll.write_bytes(b"second original")
        current = snapshot(game, self.repo)
        remember_baseline(game, self.repo, current)
        first.write_bytes(b"first managed")
        dll.write_bytes(b"second managed")
        prune_snapshots(game, self.repo, 0)
        self.assertTrue((old / "snapshot.json").exists())
        self.assertTrue((current / "snapshot.json").exists())
        restore_originals(game, self.repo)
        self.assertEqual(dll.read_bytes(), b"second original")
        self.assertEqual(first.read_bytes(), b"first managed")
        restore_originals(self.game, self.repo)
        self.assertEqual(first.read_bytes(), b"first original")

    def test_core_update_preserves_externally_saved_optiscaler_ini(self):
        archive = self.package({"OptiScaler.dll": pe_fixture(), "OptiScaler.ini": b"default"})
        install_optiscaler_payload(self.target, archive, 64, "dxgi.dll")
        ini = self.target / "OptiScaler.ini"
        saved = b"[Upscalers]\r\nDx12Upscaler=Cyboman-Lossy\r\n"
        ini.write_bytes(saved)
        install_optiscaler_payload(self.target, archive, 64, "dxgi.dll")
        self.assertEqual(ini.read_bytes(), saved)
        (self.target / "dxgi.dll").write_bytes(b"changed binary")
        with self.assertRaisesRegex(assets.Conflict, "edited outside"):
            install_optiscaler_payload(self.target, archive, 64, "dxgi.dll")

    def package(self, files):
        archive = self.root / "package.7z"
        with zipfile.ZipFile(archive, "w") as stream:
            for name, data in files.items():
                stream.writestr(name, data)
        return archive

    def test_real_core_installer_preflights_foreign_nested_files_and_retains_originals(self):
        module = load_backend()
        module.TMP_DIR = str(self.root / "work")
        Path(module.TMP_DIR).mkdir()
        module.HAVE_7Z = True
        module.GAME_BITS = 64
        module.QUIRK_OPTISCALER_DLL = "dxgi.dll"
        module.optiscaler_urls = lambda: ["https://example.test/package"]
        archive = self.package({"OptiScaler.dll": pe_fixture(), "support/settings.cfg": b"package"})

        def download(url, destination, tries):
            Path(destination).write_bytes(archive.read_bytes())
            return True

        module.download_file = download
        (self.target / "support").mkdir()
        original = self.target / "support/settings.cfg"
        original.write_bytes(b"user")
        (self.target / "d3dcompiler_47.dll").write_bytes(b"existing")
        before = Path.cwd()
        try:
            os.chdir(self.target)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(assets.Conflict):
                module.install_optiscaler()
            self.assertEqual(original.read_bytes(), b"user")
            self.assertFalse((self.target / "dxgi.dll").exists())
            module.ALLOW_FOREIGN = True
            with contextlib.redirect_stderr(io.StringIO()):
                module.install_optiscaler()
            self.assertIn("support/settings.cfg", module.INSTALLED_FILES)
            assets.remove(self.target, "backend:optiscaler")
            self.assertEqual(original.read_bytes(), b"user")
        finally:
            os.chdir(before)

    def legacy_core(self):
        (self.target / ".optidx-installed").write_text(str(self.target) + "\n")
        (self.target / ".optidx-files").write_text("dxgi.dll\n")
        (self.target / "dxgi.dll").write_bytes(pe_fixture())
        atomic_json(
            self.target / ".optidx-components.json",
            {"version": 1, "files": {"optiscaler": ["Licenses", "OptiScaler", "dxgi.dll"]}},
        )

    def test_legacy_directory_overlap_updates_license_and_vendor_dll_with_recovery(self):
        self.legacy_core()
        license = self.target / "Licenses/FidelityFX_v2_LICENSE.md"
        library = self.target / "OptiScaler/libxess.dll"
        for path, data in [(license, b"previous license"), (library, pe_fixture() + b"old")]:
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        user = self.target / "OptiScaler/user-notes.txt"
        user.write_bytes(b"personal notes")
        package = self.package(
            {
                "OptiScaler.dll": pe_fixture(),
                "Licenses/FidelityFX_v2_LICENSE.md": b"new license",
                "OptiScaler/libxess.dll": pe_fixture() + b"new",
            }
        )
        install_optiscaler_payload(self.target, package, 64, "dxgi.dll")
        self.assertEqual(license.read_bytes(), b"new license")
        self.assertEqual(library.read_bytes(), pe_fixture() + b"new")
        self.assertEqual(user.read_bytes(), b"personal notes")
        assets.remove(self.target, "backend:optiscaler")
        self.assertEqual(license.read_bytes(), b"previous license")
        self.assertEqual(library.read_bytes(), pe_fixture() + b"old")

    def test_legacy_directory_claim_does_not_bypass_custom_or_foreign_protection(self):
        self.legacy_core()
        path = self.target / "OptiScaler/custom/User/ffx/user.dll"
        path.parent.mkdir(parents=True)
        path.write_bytes(pe_fixture() + b"user")
        package = self.package(
            {
                "OptiScaler.dll": pe_fixture(),
                "OptiScaler/custom/User/ffx/user.dll": pe_fixture() + b"package",
            }
        )
        with self.assertRaises(assets.Conflict):
            install_optiscaler_payload(self.target, package, 64, "dxgi.dll")
        self.assertEqual(path.read_bytes(), pe_fixture() + b"user")
        (self.target / ".optidx-components.json").unlink()
        foreign = self.target / "Licenses/license.txt"
        foreign.parent.mkdir()
        foreign.write_bytes(b"foreign")
        with self.assertRaises(assets.Conflict):
            install_optiscaler_payload(
                self.target,
                self.package({"OptiScaler.dll": pe_fixture(), "Licenses/license.txt": b"new"}),
                64,
                "dxgi.dll",
            )

    def test_legacy_independent_amd_dll_is_preserved_during_core_update(self):
        self.legacy_core()
        name = "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
        atomic_json(
            self.target / ".optidx-components.json",
            {
                "version": 1,
                "files": {"optiscaler": ["OptiScaler", "Licenses", "dxgi.dll"], "amd_fsr": [name]},
            },
        )
        dll = self.target / name
        dll.parent.mkdir()
        dll.write_bytes(pe_fixture() + b"Cyboman")
        install_optiscaler_payload(
            self.target,
            self.package({"OptiScaler.dll": pe_fixture(), name: pe_fixture() + b"upstream"}),
            64,
            "dxgi.dll",
        )
        self.assertEqual(dll.read_bytes(), pe_fixture() + b"Cyboman")
        self.assertNotIn(name, assets.state(self.target)["groups"]["backend:optiscaler"]["files"])

    def test_modern_edited_vendor_dll_is_not_adopted_as_legacy(self):
        self.legacy_core()
        name = "OptiScaler/libxess.dll"
        assets.deploy(self.target, "backend:optiscaler", {name: pe_fixture()})
        (self.target / name).write_bytes(pe_fixture() + b"external edit")
        with self.assertRaises(assets.Conflict):
            install_optiscaler_payload(
                self.target,
                self.package({"OptiScaler.dll": pe_fixture(), name: pe_fixture() + b"update"}),
                64,
                "dxgi.dll",
            )

    def test_core_rejects_incompatible_ambiguous_and_unsafe_archives_before_writes(self):
        invalid = [
            {"OptiScaler.dll": pe_fixture(bits=32)},
            {"OptiScaler.dll": pe_fixture()[:0x84] + b"\x64\xaa" + pe_fixture()[0x86:]},
            {"OptiScaler.dll": b"MZ invalid"},
            {"OptiScaler.dll": pe_fixture(), "OptiScaler-other.dll": pe_fixture()},
            {"OptiScaler.dll": pe_fixture(), "../escape.cfg": b"bad"},
            {"OptiScaler.dll": pe_fixture(), "Data/a.cfg": b"a", "data/b.cfg": b"b"},
        ]
        for files in invalid:
            with self.subTest(files=list(files)), self.assertRaises(ValueError):
                install_optiscaler_payload(self.target, self.package(files), 64, "dxgi.dll")
            self.assertFalse((self.target / "dxgi.dll").exists())

    def test_core_preserves_existing_ini_and_rejects_linked_support_folder(self):
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(b"[Libraries]\nFfxDx12SRPath=custom\n")
        archive = self.package({"OptiScaler.dll": pe_fixture(), "OptiScaler.ini": b"[Libraries]\n"})
        install_optiscaler_payload(self.target, archive, 64, "dxgi.dll")
        self.assertIn(b"custom", ini.read_bytes())
        destination = self.target / "linked"
        destination.symlink_to(self.target / "support", target_is_directory=True)
        (self.target / "support").mkdir()
        archive = self.package({"OptiScaler.dll": pe_fixture(), "linked/settings.cfg": b"bad"})
        with self.assertRaises(assets.Conflict):
            install_optiscaler_payload(self.target, archive, 64, "dxgi.dll")
        self.assertFalse((self.target / "support/settings.cfg").exists())

    def test_late_worker_failure_restores_previously_untracked_payload_original(self):
        original = self.target / "settings.cfg"
        original.write_bytes(b"user settings")
        archive = self.package(
            {"OptiScaler.dll": pe_fixture(), "settings.cfg": b"package settings"}
        )

        def fail(*args):
            install_optiscaler_payload(self.target, archive, 64, "dxgi.dll", allow_foreign=True)
            raise OSError("late inspection failure")

        with (
            patch("optidx_desktop.worker.execute_backend", side_effect=fail),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(OSError, "late inspection failure"),
        ):
            run_job({"game": self.game.to_dict(), "action": "install"}, self.repo.directory)
        self.assertEqual(original.read_bytes(), b"user settings")
        self.assertFalse((self.target / "dxgi.dll").exists())
        self.assertFalse((self.target / assets.LEDGER).exists())

    def test_rollback_keeps_a_previously_missing_managed_file_missing(self):
        from optidx_desktop.backups import rollback_snapshot

        original = self.target / "settings.cfg"
        original.write_bytes(b"foreign original")
        assets.deploy(self.target, "test", {"settings.cfg": b"managed"}, allow_foreign=True)
        original.unlink()
        before = snapshot(self.game, self.repo)
        assets.deploy(self.target, "test", {"settings.cfg": b"new managed"})
        rollback_snapshot(self.target, before)
        self.assertFalse(original.exists())
        self.assertIn("test", assets.state(self.target)["groups"])

    def test_real_uninstall_failure_keeps_manifest_and_worker_rolls_back(self):
        dll = self.target / "dxgi.dll"
        dll.write_bytes(b"managed")
        manifest = self.target / ".optidx-files"
        manifest.write_text("dxgi.dll\n")
        original_remove = os.remove

        def remove(path, *args, **kwargs):
            if Path(path) == dll:
                raise PermissionError("simulated failure")
            return original_remove(path, *args, **kwargs)

        with (
            patch("os.remove", side_effect=remove),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaisesRegex(OSError, "Removal incomplete"):
                run_job({"game": self.game.to_dict(), "action": "remove"}, self.repo.directory)
        self.assertEqual(dll.read_bytes(), b"managed")
        self.assertEqual(manifest.read_text(), "dxgi.dll\n")

    def test_prune_direct_helix_restores_original(self):
        module = load_backend()
        module.TMP_DIR = str(self.root / "work")
        Path(module.TMP_DIR).mkdir()
        source = self.root / "helix.dll"
        source.write_bytes(pe_fixture())
        module.HELIXSR_SOURCE_DLL = source
        (self.target / "OptiScaler").mkdir()
        amd = self.target / "OptiScaler" / module.AMD_DLL_NAME
        amd.write_bytes(b"foreign-original")
        (self.target / "OptiScaler.ini").write_text("[Libraries]\n")
        before = Path.cwd()
        try:
            os.chdir(self.target)
            module.COMPONENT_SELECTION = {"helixsr"}
            with contextlib.redirect_stderr(io.StringIO()):
                module.install_helixsr()
                owners = module.owned_components()
                owners["helixsr"].update(module.INSTALLED_FILES)
                module.write_component_manifest(owners)
                module.COMPONENT_SELECTION = set()
                module.PRUNE_COMPONENTS = True
                module.install_selected_components()
            self.assertEqual(amd.read_bytes(), b"foreign-original")
            self.assertFalse((amd.parent / module.HELIXSR_STATE).exists())
        finally:
            os.chdir(before)

    def test_dxvk_and_standalone_reshade_worker_updates_use_their_installers(self):
        for group, function in [
            ("extra:dxvk", "install_dxvk"),
            ("channel:reshade", "install_reshade"),
        ]:
            with self.subTest(group=group):
                atomic_json(
                    self.target / assets.LEDGER,
                    {
                        "version": 1,
                        "groups": {
                            group: {"files": {}, "metadata": {"source": {"path": "/local/package"}}}
                        },
                    },
                )
                with (
                    patch("optidx_desktop.channels." + function) as install,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    run_job({"game": self.game.to_dict(), "action": "update"}, self.repo.directory)
                self.assertEqual(install.call_count, 1)
                with patch("optidx_desktop.channels." + function) as install:
                    update_features(self.game, self.repo, {"exclude_components": [group]})
                install.assert_not_called()

    def test_snapshot_cleanup_refuses_running_jobs_and_preserves_baseline_originals(self):
        import fcntl
        import hashlib
        from optidx_desktop.backups import remember_baseline

        dll = self.target / "dxgi.dll"
        dll.write_bytes(b"original")
        folder = snapshot(self.game, self.repo)
        remember_baseline(self.game, self.repo, folder)
        lock_dir = self.repo.directory / "locks"
        lock_dir.mkdir()
        key = hashlib.sha256(str(self.target.resolve()).encode()).hexdigest()
        with (lock_dir / (key + ".lock")).open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "running"):
                cleanup_completed_snapshots(self.repo)
        self.assertTrue(folder.exists())
        dll.write_bytes(b"managed")
        self.assertEqual(cleanup_completed_snapshots(self.repo), 1)
        saved = Path(read_json(baseline_path(self.game, self.repo), {})["snapshot"])
        self.assertEqual((saved / "files/dxgi.dll").read_bytes(), b"original")

    def test_source_launcher_works_from_game_directory(self):
        profile = self.repo.directory / "profiles/review.json"
        atomic_json(profile, {})
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        entry = Path(__file__).resolve().parents[1] / "launcher.py"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(entry),
                "--profile",
                str(profile),
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(7)",
            ],
            cwd=self.target,
            env=env,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 7, result.stderr.decode())

    def test_snapshot_retention_defaults_off_but_originals_and_rollback_survive(self):
        dll = self.target / "dxgi.dll"
        dll.write_bytes(b"original")

        def install(*args):
            dll.write_bytes(b"managed")
            (self.target / ".optidx-files").write_text("dxgi.dll\n")
            return {}

        with (
            patch("optidx_desktop.worker.execute_backend", side_effect=install),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run_job({"game": self.game.to_dict(), "action": "install"}, self.repo.directory)
        base = self.repo.directory / "backups" / self.game.id
        self.assertEqual(list(base.glob("[0-9]*/snapshot.json")), [])
        original_folder = Path(read_json(baseline_path(self.game, self.repo), {})["snapshot"])
        self.assertEqual((original_folder / "files/dxgi.dll").read_bytes(), b"original")

        def fail(*args):
            dll.write_bytes(b"partial")
            raise OSError("job failed")

        with (
            patch("optidx_desktop.worker.execute_backend", side_effect=fail),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(OSError, "job failed"),
        ):
            run_job({"game": self.game.to_dict(), "action": "install"}, self.repo.directory)
        self.assertEqual(dll.read_bytes(), b"managed")
        self.assertEqual(list(base.glob("[0-9]*/snapshot.json")), [])

    def test_compact_baseline_omits_untouched_dlls_and_verifies_alternate_original(self):
        from optidx_desktop.backups import compact_baseline, remember_baseline

        untouched = self.target / "nvngx_dlss.dll"
        untouched.write_bytes(b"untouched large runtime")
        replaced = self.target / "dxgi.dll"
        replaced.write_bytes(b"foreign original")
        folder = snapshot(self.game, self.repo)
        remember_baseline(self.game, self.repo, folder)
        assets.deploy(self.target, "test", {"dxgi.dll": b"managed"}, allow_foreign=True)
        record = assets.state(self.target)["groups"]["test"]["files"]["dxgi.dll"]["original"]
        blob = self.target / assets.ORIGINALS / record["blob"]
        blob.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            compact_baseline(self.game, self.repo)
        self.assertEqual(
            Path(read_json(baseline_path(self.game, self.repo), {})["snapshot"]), folder
        )
        blob.write_bytes(b"foreign original")
        compact_baseline(self.game, self.repo)
        saved = Path(read_json(baseline_path(self.game, self.repo), {})["snapshot"])
        self.assertEqual(read_json(saved / "snapshot.json", {})["files"], [])
        self.assertEqual(blob.read_bytes(), b"foreign original")

    def test_opt_in_retention_is_bounded_and_cleanup_keeps_recovery_data(self):
        atomic_json(
            self.repo.directory / "settings.json", {"retain_backups": True, "backup_limit": 2}
        )
        for index in range(4):
            folder = snapshot(self.game, self.repo)
            finish_snapshots(self.game, self.repo, [folder])
        base = self.repo.directory / "backups" / self.game.id
        self.assertEqual(len(list(base.glob("[0-9]*/snapshot.json"))), 2)
        interrupted = snapshot(self.game, self.repo)
        saved = read_json(interrupted / "snapshot.json", {})
        atomic_json(interrupted / "snapshot.json", {**saved, "operation_status": "active"})
        manual = snapshot(self.game, self.repo)
        finish_snapshots(self.game, self.repo, [manual], "manual_recovery")
        self.assertEqual(cleanup_completed_snapshots(self.repo), 2)
        self.assertTrue(interrupted.exists())
        self.assertTrue(manual.exists())


class LifecycleReviewTests(unittest.TestCase):
    setUp = ReviewFixTests.setUp
    tearDown = ReviewFixTests.tearDown
    package = ReviewFixTests.package

    def test_failed_transfer_keeps_original_owner_and_recovery_blob(self):
        name = "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
        path = self.target / name
        path.parent.mkdir()
        path.write_bytes(b"foreign")
        assets.deploy(self.target, "backend:optiscaler", {name: b"core"}, allow_foreign=True)
        before = (self.target / assets.LEDGER).read_bytes()
        with patch("optidx_desktop.assets.atomic_json", side_effect=OSError("ledger write failed")):
            with self.assertRaisesRegex(OSError, "ledger write failed"):
                assets.deploy(
                    self.target,
                    "backend:amd_fsr",
                    {name: b"AMD"},
                    transfer_from="backend:optiscaler",
                )
        self.assertEqual(path.read_bytes(), b"core")
        self.assertEqual((self.target / assets.LEDGER).read_bytes(), before)
        assets.remove(self.target, "backend:optiscaler")
        self.assertEqual(path.read_bytes(), b"foreign")

    def test_later_operation_merges_new_original_into_compact_baseline(self):
        from optidx_desktop.backups import remember_baseline, restore_originals

        dll = self.target / "dxgi.dll"
        dll.write_bytes(b"first original")
        first = snapshot(self.game, self.repo)
        remember_baseline(self.game, self.repo, first)
        finish_snapshots(self.game, self.repo, [first])
        later = snapshot(self.game, self.repo)
        dll.write_bytes(b"backend replacement")
        (self.target / ".optidx-files").write_text("dxgi.dll\n")
        finish_snapshots(self.game, self.repo, [later])
        third = snapshot(self.game, self.repo)
        dll.write_bytes(b"updated replacement")
        finish_snapshots(self.game, self.repo, [third])
        dll.unlink()
        restore_originals(self.game, self.repo)
        self.assertEqual(dll.read_bytes(), b"first original")

    def test_prune_reshade_restores_proxy_and_does_not_update_removed_group(self):
        module = load_backend()
        proxy = self.target / "dxgi.dll"
        proxy.write_bytes(b"foreign")
        assets.deploy(self.target, "channel:reshade", {"dxgi.dll": b"reshade"}, allow_foreign=True)
        previous = Path.cwd()
        try:
            os.chdir(self.target)
            owners = {k: set() for k in module.COMPONENT_NAMES}
            owners["reshade"] = {"dxgi.dll"}
            module.COMPONENT_SELECTION = {"reshade"}
            module.write_component_manifest(owners)
            module.COMPONENT_SELECTION = set()
            module.PRUNE_COMPONENTS = True
            module.install_selected_components()
        finally:
            os.chdir(previous)
        self.assertEqual(proxy.read_bytes(), b"foreign")
        self.assertNotIn("channel:reshade", assets.state(self.target)["groups"])
        with patch("optidx_desktop.channels.install_reshade") as install:
            update_features(self.game, self.repo, {})
        install.assert_not_called()

    def test_core_amd_transfer_repeat_update_and_original_restore(self):
        module = load_backend()
        name = "OptiScaler/" + module.AMD_DLL_NAME
        dll = self.target / name
        dll.parent.mkdir()
        dll.write_bytes(b"foreign AMD")
        core = self.package({"OptiScaler.dll": pe_fixture(), name: pe_fixture() + b"core"})
        install_optiscaler_payload(self.target, core, 64, "dxgi.dll", allow_foreign=True)
        amd = self.root / "amd.zip"
        with zipfile.ZipFile(amd, "w") as stream:
            stream.writestr("lossy/" + module.AMD_DLL_NAME, pe_fixture() + b"AMD")
        module.TMP_DIR = str(self.root / "work")
        Path(module.TMP_DIR).mkdir()
        module.amd_release_asset = lambda: {
            "browser_download_url": "https://example.test/amd",
            "release_tag": "test",
        }

        def download(url, target, tries):
            Path(target).write_bytes(amd.read_bytes())
            return True

        module.download_file = download
        previous = Path.cwd()
        try:
            os.chdir(self.target)
            for _ in range(2):
                self.assertTrue(module.install_amd_dll())
                install_optiscaler_payload(self.target, core, 64, "dxgi.dll")
                self.assertEqual(dll.read_bytes(), pe_fixture() + b"AMD")
        finally:
            os.chdir(previous)
        self.assertNotIn(name, assets.state(self.target)["groups"]["backend:optiscaler"]["files"])
        assets.remove(self.target, "backend:optiscaler")
        assets.remove(self.target, "backend:amd_fsr")
        self.assertEqual(dll.read_bytes(), b"foreign AMD")

    def test_legacy_amd_migration_verifies_replacement_and_retains_original(self):
        from optidx_desktop.core_payload import reconcile_amd_ownership

        name = "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
        assets.deploy(self.target, "backend:optiscaler", {name: b"core"})
        dll = self.target / name
        dll.write_bytes(b"AMD")
        atomic_json(self.target / ".optidx-components.json", {"files": {"amd_fsr": [name]}})
        atomic_json(
            self.target / "OptiScaler/.optidx-amd-release.json", {"sha256": assets.sha(b"AMD")}
        )
        dll.write_bytes(b"edited")
        with self.assertRaises(assets.Conflict):
            reconcile_amd_ownership(self.target)
        self.assertIn(name, assets.state(self.target)["groups"]["backend:optiscaler"]["files"])
        dll.write_bytes(b"AMD")
        reconcile_amd_ownership(self.target)
        self.assertIn(name, assets.state(self.target)["groups"]["backend:amd_fsr"]["files"])


if __name__ == "__main__":
    unittest.main()
