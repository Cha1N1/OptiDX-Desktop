import contextlib
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from optidx_desktop.backend import load_backend, selected_components, component_arguments


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.module = load_backend()
        self.module.TMP_DIR = str(self.root / "work")
        Path(self.module.TMP_DIR).mkdir()
        self.module.HELIXSR_DIR = self.root / "prepared"
        self.module.HELIXSR_DIR.mkdir()
        for name in (self.module.AMD_DLL_NAME,):
            (self.module.HELIXSR_DIR / name).write_bytes(b"prepared")
        self.output = contextlib.redirect_stderr(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        os.chdir(self.previous)
        self.temporary.cleanup()

    def fake_stages(self):
        m = self.module
        calls = []
        stage_files = {
            "optiscaler": ["dxgi.dll", "OptiScaler.ini"], "reshade": [m.RESHADE_DLL_NAME],
            "renodx": ["renodx-test.addon64"], "luma": ["TestGame.addon"],
            "amd_fsr": ["OptiScaler/" + m.AMD_DLL_NAME],
            "helixsr": ["OptiScaler/" + m.AMD_DLL_NAME, "OptiScaler/" + m.HELIXSR_STATE],
            "dlss_enabler": ["OptiScaler/dlss-enabler-headless.dll"],
        }
        def stage(name):
            def install():
                calls.append(name)
                for relative in stage_files[name]:
                    path = Path(relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"MZ component" if path.suffix != ".ini" else b"[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n")
                    m.track(relative)
                m.MOD_FOUND = name in {"renodx", "luma"}
                return True
            return install
        for name, function in [("optiscaler", "install_optiscaler"), ("reshade", "install_reshade"),
                               ("renodx", "find_renodx_mod"), ("luma", "find_luma_mod"),
                               ("amd_fsr", "install_amd_dll"), ("helixsr", "install_helixsr"),
                               ("dlss_enabler", "install_dlss_enabler")]:
            setattr(m, function, stage(name))
        m.cache_fetch = lambda *args: ""
        m.fetch_payload = lambda *args: True
        m.amd_release_asset = lambda: {"browser_download_url": "https://example.test/fsr.zip"}
        m.dlss_enabler_url = lambda: "https://example.test/dlss.zip"
        m.optiscaler_urls = lambda: ["https://example.test/opti.zip"]
        m.configure_ue_hdr = lambda *args: None
        m.install_engine_fallback = lambda: None
        return calls, stage_files

    def test_selected_custom_helix_dll_is_copied_and_tracked(self):
        m = self.module
        source = self.root / 'prepared/custom-fsr.dll'
        source.write_bytes(b'HelixSR 1.7.0\x00custom build')
        m.HELIXSR_SOURCE_DLL = source
        Path('OptiScaler.ini').write_text('[Libraries]\n')
        self.assertTrue(m.install_helixsr())
        self.assertEqual(Path('OptiScaler/' + m.AMD_DLL_NAME).read_bytes(), source.read_bytes())
        self.assertFalse(Path('OptiScaler/HelixSR').exists())
        self.assertIn('OptiScaler/' + m.AMD_DLL_NAME, m.INSTALLED_FILES)

    def test_standalone_helix_source_accepts_x64_and_rejects_wrong_machine(self):
        from optidx_desktop.helixsr import local_source
        from test_core import pe_fixture
        source = self.root / 'prepared/custom.dll'
        source.write_bytes(pe_fixture(bits=32))
        with self.assertRaisesRegex(ValueError, 'x64'):
            local_source(str(source))
        source.write_bytes(pe_fixture())
        self.assertEqual(local_source(str(source)), source.resolve())
        self.assertFalse((source.parent / 'helixsr_weights.bin').exists())
        self.assertFalse((source.parent / 'helixsr_kernels.pak').exists())

    def test_direct_helix_migrates_legacy_and_restores_replaced_dll(self):
        from optidx_desktop.helixsr import remove
        from optidx_desktop.library import manual_game
        from optidx_desktop.storage import Repository
        from test_core import pe_fixture
        m = self.module
        exe = self.root / 'Game.exe'
        exe.write_bytes(pe_fixture())
        Path('OptiScaler.ini').write_text('[Libraries]\nFfxDx12Path=OptiScaler/HelixSR/helixsr.dll\nFfxDx12SRPath=OptiScaler/HelixSR/helixsr_upscaler.dll\n')
        Path('dxgi.dll').write_bytes(b'loader')
        legacy = Path('OptiScaler/HelixSR/helixsr.dll')
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'legacy')
        user = legacy.parent / 'user.txt'
        user.write_text('keep')
        target = Path('OptiScaler') / m.AMD_DLL_NAME
        target.write_bytes(b'previous AMD')
        owners = {name: set() for name in m.COMPONENT_NAMES}
        owners['amd_fsr'] = {target.as_posix()}
        owners['helixsr'] = {legacy.as_posix()}
        m.COMPONENT_SELECTION = {'helixsr'}
        m.write_component_manifest(owners)
        source = self.root / 'prepared/custom.dll'
        source.write_bytes(pe_fixture() + b'first build')
        m.HELIXSR_SOURCE_DLL = source
        m.install_selected_components()
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertFalse(legacy.exists())
        self.assertEqual(user.read_text(), 'keep')
        self.assertEqual(m.owned_components()['helixsr'], {
            target.as_posix(), 'OptiScaler/.optidx-helixsr.json', 'OptiScaler/.optidx-helixsr-original.bin'})
        self.assertFalse(m.component_present('amd_fsr'))
        from optidx_desktop.inspection import inspect_game
        detected = inspect_game(manual_game(exe, 'Example'))['components']
        self.assertTrue(detected['HelixSR'])
        self.assertFalse(detected['AMD FSR'])
        self.assertNotIn('OptiScaler/HelixSR/', Path('OptiScaler.ini').read_text())
        source.write_bytes(pe_fixture() + b'second build')
        m.install_selected_components()
        game = manual_game(exe, 'Example')
        with patch('optidx_desktop.helixsr.load_backend', return_value=m):
            remove(game, Repository(self.root / 'data'), {})
        self.assertEqual(target.read_bytes(), b'previous AMD')
        self.assertIn(target.as_posix(), m.owned_components()['amd_fsr'])
        self.assertFalse((target.parent / m.HELIXSR_STATE).exists())

    def test_direct_helix_rejects_damaged_original_backup(self):
        m = self.module
        Path('OptiScaler.ini').write_text('[Libraries]\n')
        Path('OptiScaler').mkdir()
        target = Path('OptiScaler') / m.AMD_DLL_NAME
        target.write_bytes(b'previous AMD')
        m.install_helixsr()
        before = target.read_bytes()
        Path('OptiScaler/.optidx-helixsr-original.bin').write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            m.install_helixsr()
        self.assertEqual(target.read_bytes(), before)
        from optidx_desktop.helixsr import remove
        from optidx_desktop.library import manual_game
        from optidx_desktop.storage import Repository
        exe = self.root / 'Game.exe'
        exe.write_bytes(b'fixture')
        owners = {name: set() for name in m.COMPONENT_NAMES}
        owners['helixsr'] = {target.as_posix(), 'OptiScaler/.optidx-helixsr.json', 'OptiScaler/.optidx-helixsr-original.bin'}
        m.COMPONENT_SELECTION = {'helixsr'}
        m.write_component_manifest(owners)
        with patch('optidx_desktop.helixsr.load_backend', return_value=m), self.assertRaisesRegex(ValueError, 'checksum'):
            remove(manual_game(exe, 'Example'), Repository(self.root / 'data'), {})
        self.assertEqual(target.read_bytes(), before)

    def test_all_component_combinations_respect_selection_and_dependencies(self):
        m = self.module
        calls, files = self.fake_stages()
        for bits in itertools.product([False, True], repeat=len(m.COMPONENT_NAMES)):
            selected = {name for name, enabled in zip(m.COMPONENT_NAMES, bits) if enabled}
            valid = bool(selected) and not {"helixsr", "amd_fsr"} <= selected and (not selected.intersection({"renodx", "luma"}) or "reshade" in selected) and (
                "helixsr" not in selected or "optiscaler" in selected)
            with self.subTest(selected=selected), tempfile.TemporaryDirectory(dir=self.root) as folder:
                os.chdir(folder)
                m.COMPONENT_SELECTION = selected
                m.INSTALLED_FILES = []
                calls.clear()
                if valid:
                    m.install_selected_components()
                    self.assertEqual(set(calls), selected)
                    self.assertTrue(all(m.component_present(name) for name in selected))
                    state = json.loads(Path(m.COMPONENT_STATE).read_text())
                    self.assertEqual(set(state["selected"]), selected)
                else:
                    with self.assertRaises(ValueError):
                        m.install_selected_components()
                    self.assertEqual(calls, [])
                os.chdir(self.root)

    def test_unchecked_components_are_preserved_until_explicit_pruning(self):
        m = self.module
        calls, files = self.fake_stages()
        m.COMPONENT_SELECTION = set(m.COMPONENT_NAMES) - {"helixsr"}
        m.install_selected_components()
        foreign = Path("UserTool.addon64")
        foreign.write_bytes(b"custom")
        m.COMPONENT_SELECTION = {"optiscaler"}
        m.install_selected_components()
        self.assertTrue(Path("renodx-test.addon64").exists())
        self.assertTrue(Path(m.RESHADE_DLL_NAME).exists())
        m.PRUNE_COMPONENTS = True
        m.install_selected_components()
        self.assertFalse(Path("renodx-test.addon64").exists())
        self.assertFalse(Path(m.RESHADE_DLL_NAME).exists())
        self.assertTrue(foreign.exists())
        self.assertTrue(Path("dxgi.dll").exists())

    def test_existing_dependencies_can_be_reused_without_reinstalling(self):
        m = self.module
        calls, files = self.fake_stages()
        Path(m.RESHADE_DLL_NAME).write_bytes(b"existing ReShade")
        m.COMPONENT_SELECTION = {"renodx"}
        m.install_selected_components()
        self.assertEqual(calls, ["renodx"])
        self.assertEqual(Path(m.RESHADE_DLL_NAME).read_bytes(), b"existing ReShade")

    def test_empty_prune_removes_owned_install_and_preserves_foreign_files(self):
        m = self.module
        self.fake_stages()
        m.COMPONENT_SELECTION = {"reshade"}
        m.install_selected_components()
        Path("UserTool.addon").write_bytes(b"user")
        m.COMPONENT_SELECTION = set()
        m.PRUNE_COMPONENTS = True
        m.install_selected_components()
        self.assertFalse(Path(m.MANIFEST).exists())
        self.assertFalse(Path(m.MARKER).exists())
        self.assertTrue(Path("UserTool.addon").exists())

    def test_disabled_dependencies_cannot_be_pruned_while_still_required(self):
        m = self.module
        self.fake_stages()
        m.COMPONENT_SELECTION = {"reshade", "renodx"}
        m.install_selected_components()
        m.COMPONENT_SELECTION = {"renodx"}
        m.PRUNE_COMPONENTS = True
        with self.assertRaisesRegex(ValueError, "Select reshade"):
            m.install_selected_components()
        self.assertTrue(Path(m.RESHADE_DLL_NAME).exists())

    def test_old_presets_migrate_and_new_profiles_forward_custom_choices(self):
        self.assertEqual(selected_components({"mode": "luma"}), {"luma", "reshade"})
        self.assertEqual(component_arguments({"components": {"amd_fsr": True, "helixsr": False}}),
                         ["--components=amd_fsr"])
        with self.assertRaises(ValueError):
            selected_components({"components": {"made_up": True}})

    def test_failed_component_is_reported_and_successful_files_remain_tracked(self):
        m = self.module
        self.fake_stages()
        m.COMPONENT_SELECTION = {"reshade", "amd_fsr"}
        m.install_amd_dll = lambda: False
        with self.assertRaisesRegex(RuntimeError, "amd_fsr"):
            m.install_selected_components()
        self.assertIn(m.RESHADE_DLL_NAME, Path(m.MANIFEST).read_text())

    def test_reshade_update_refreshes_its_standalone_proxy(self):
        m = self.module
        m.HAVE_7Z = True
        m.FORCE_UPDATE = True
        Path(m.RESHADE_DLL_NAME).write_bytes(b"old ReShade")
        Path(m.QUIRK_OPTISCALER_DLL).write_bytes(b"old ReShade")
        m.download_file = lambda *args: True
        def extract(archive, directory):
            Path(directory).mkdir()
            (Path(directory) / "ReShade64.dll").write_bytes(b"new ReShade")
            return True
        m.extract_archive = extract
        m.install_reshade()
        self.assertEqual(Path(m.RESHADE_DLL_NAME).read_bytes(), b"new ReShade")
        self.assertEqual(Path(m.QUIRK_OPTISCALER_DLL).read_bytes(), b"new ReShade")

    def test_update_does_not_report_success_when_selected_component_download_did_nothing(self):
        m = self.module
        self.fake_stages()
        m.COMPONENT_SELECTION = {"reshade"}
        m.install_selected_components()
        m.FORCE_UPDATE = True
        m.install_reshade = lambda: None
        with self.assertRaisesRegex(RuntimeError, "reshade"):
            m.install_selected_components()


class CybomanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.m = load_backend()
        self.m.TMP_DIR = str(self.root / "work")
        Path(self.m.TMP_DIR).mkdir()
        self.output = contextlib.redirect_stderr(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        os.chdir(self.previous)
        self.temporary.cleanup()

    def archive(self, content=True):
        archive = self.root / "fixture.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("exact/" + self.m.AMD_DLL_NAME, b"MZ exact")
            if content:
                z.writestr("lossy/" + self.m.AMD_DLL_NAME, b"MZ lossy")
            z.writestr("../../escape.txt", b"not extracted")
        return archive

    def configure_archive(self, archive, digest=""):
        self.m.AMD_RELEASE_ASSET = {"browser_download_url": "https://github.com/zgauthier2000/fsr4-shader-performance-overrides/releases/download/tag/fsr4.1.1-cyboman.zip",
                                   "release_tag": "tag", "digest": digest}
        self.m.download_file = lambda url, dest, tries: bool(shutil.copyfile(archive, dest))

    def test_latest_matching_asset_skips_unrelated_and_prerelease_entries(self):
        data = [{"tag_name": "timing-kit", "assets": []},
                {"tag_name": "preview", "prerelease": True, "assets": [{"name": self.m.AMD_ARCHIVE_NAME, "browser_download_url": "preview"}]},
                {"tag_name": "newest-dll", "assets": [{"name": self.m.AMD_ARCHIVE_NAME, "browser_download_url": "official"}]}]
        with patch.object(self.m, "cache_fetch", return_value="file") as fetch, patch.object(self.m, "load_json", return_value=data):
            self.m.FORCE_UPDATE = True
            self.assertEqual(self.m.amd_release_asset()["release_tag"], "newest-dll")
            self.m.amd_release_asset()
            fetch.assert_called_once_with(self.m.AMD_RELEASES_URL, "cyboman_releases.json", 0)

    def test_only_lossy_member_is_installed_with_release_provenance(self):
        archive = self.archive()
        self.configure_archive(archive, "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertTrue(self.m.install_amd_dll())
        self.assertEqual(Path("OptiScaler", self.m.AMD_DLL_NAME).read_bytes(), b"MZ lossy")
        self.assertFalse((self.root.parent / "escape.txt").exists())
        provenance = json.loads(Path("OptiScaler/.optidx-amd-release.json").read_text())
        self.assertEqual(provenance["variant"], "lossy")
        self.assertEqual(provenance["sha256"], hashlib.sha256(b"MZ lossy").hexdigest())

    def test_missing_lossy_member_keeps_existing_dll(self):
        self.configure_archive(self.archive(content=False))
        Path("OptiScaler").mkdir()
        old = Path("OptiScaler", self.m.AMD_DLL_NAME)
        old.write_bytes(b"MZ previous")
        self.assertFalse(self.m.install_amd_dll())
        self.assertEqual(old.read_bytes(), b"MZ previous")

    def test_bad_digest_keeps_existing_dll(self):
        self.configure_archive(self.archive(), "sha256:" + "0" * 64)
        Path("OptiScaler").mkdir()
        old = Path("OptiScaler", self.m.AMD_DLL_NAME)
        old.write_bytes(b"MZ previous")
        self.assertFalse(self.m.install_amd_dll())
        self.assertEqual(old.read_bytes(), b"MZ previous")


if __name__ == "__main__":
    unittest.main()
