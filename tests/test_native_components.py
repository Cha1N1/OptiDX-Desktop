import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import unittest.mock
from unittest.mock import patch
import zipfile

from helpers import pe_fixture

from optidx_desktop import assets
from optidx_desktop.backend import load_backend
from optidx_desktop.components import (
    COMPONENTS,
    DLSS_ENABLER_FILE,
    INJECTED_SETTINGS,
    LEGACY_HOOKS,
    InstallContext,
    install_cyboman,
    install_dlss_enabler,
    selection_problems,
)
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository


class NativeComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / "game"
        self.target.mkdir()
        (self.target / "game.exe").write_bytes(pe_fixture())
        self.game = manual_game(self.target / "game.exe", "Game")
        self.repo = Repository(self.root / "data")
        self.tracked = []

    def tearDown(self):
        self.temp.cleanup()

    def context(self, allow_foreign=False):
        return InstallContext(
            self.game, self.repo, {}, allow_foreign=allow_foreign, track=self.tracked.append
        )

    def archive(self, members):
        path = self.root / ("payload-%d.zip" % len(list(self.root.glob("payload-*.zip"))))
        with zipfile.ZipFile(path, "w") as stream:
            for name, data in members.items():
                stream.writestr(name, data)
        return path

    @contextlib.contextmanager
    def release(self, tag, asset_name, archive, digest=""):
        releases = [
            {
                "tag_name": tag,
                "assets": [
                    {
                        "name": asset_name,
                        "browser_download_url": "https://example.test/" + asset_name,
                        "digest": digest,
                    }
                ],
            }
        ]
        with (
            patch("optidx_desktop.downloads.Client.releases", return_value=releases),
            patch("optidx_desktop.downloads.Client.fetch", return_value=archive) as fetch,
        ):
            yield fetch

    def test_dlss_enabler_is_ledger_owned_and_restores_foreign_original(self):
        existing = self.target / DLSS_ENABLER_FILE
        existing.parent.mkdir()
        existing.write_bytes(b"user enabler")
        archive = self.archive({"x64/dxgi.dll": pe_fixture() + b"enabler"})
        with self.release("dlss-enabler", "enabler.zip", archive):
            with self.assertRaisesRegex(assets.Conflict, "explicit replacement approval"):
                install_dlss_enabler(self.context())
            self.assertEqual(existing.read_bytes(), b"user enabler")
            install_dlss_enabler(self.context(allow_foreign=True))
        self.assertEqual(existing.read_bytes(), pe_fixture() + b"enabler")
        self.assertEqual(self.tracked, [DLSS_ENABLER_FILE])
        group = assets.state(self.target)["groups"]["component:dlss_enabler"]
        self.assertEqual(group["metadata"]["version"], "dlss-enabler")
        self.assertEqual(group["metadata"]["source"]["pattern"], r"^enabler\.zip$")
        from optidx_desktop.updates import check_updates

        client = unittest.mock.MagicMock()
        client.release_asset.return_value = {"version": "dlss-enabler", "updated_at": ""}
        result = check_updates(self.game, self.repo, {}, client)
        record = next(r for r in result["components"] if r["component"] == "component:dlss_enabler")
        self.assertFalse(record["update"])
        result = check_updates(
            self.game, self.repo, {"exclude_components": ["dlss_enabler"]}, client
        )
        self.assertFalse(
            any(r["component"] == "component:dlss_enabler" for r in result["components"])
        )
        assets.remove(self.target, "component:dlss_enabler")
        self.assertEqual(existing.read_bytes(), b"user enabler")

    def test_dlss_enabler_rejects_wrong_architecture_before_writing(self):
        archive = self.archive({"dxgi.dll": pe_fixture(bits=32)})
        with self.release("dlss-enabler", "enabler.zip", archive):
            with self.assertRaisesRegex(ValueError, "x64"):
                install_dlss_enabler(self.context())
        self.assertFalse((self.target / DLSS_ENABLER_FILE).exists())
        self.assertNotIn("component:dlss_enabler", assets.state(self.target)["groups"])

    def test_cyboman_installs_only_lossy_member_with_digest_and_provenance(self):
        dll = "amd_fidelityfx_upscaler_dx12.dll"
        archive = self.archive(
            {"lossy/" + dll: pe_fixture() + b"lossy", "exact/" + dll: pe_fixture() + b"exact"}
        )
        with self.release("dll-1", "fsr4.1.1-cyboman.zip", archive, "sha256:abc") as fetch:
            install_cyboman(self.context())
        fetch.assert_called_once_with("https://example.test/fsr4.1.1-cyboman.zip", "sha256:abc")
        self.assertEqual((self.target / "OptiScaler" / dll).read_bytes(), pe_fixture() + b"lossy")
        provenance = json.loads((self.target / "OptiScaler/.optidx-amd-release.json").read_text())
        self.assertEqual((provenance["tag"], provenance["variant"]), ("dll-1", "lossy"))
        self.assertIn("backend:amd_fsr", assets.state(self.target)["groups"])

    def test_cyboman_missing_member_keeps_existing_dll(self):
        dll = self.target / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll"
        dll.parent.mkdir()
        dll.write_bytes(b"previous")
        archive = self.archive({"exact/amd_fidelityfx_upscaler_dx12.dll": pe_fixture()})
        with self.release("dll-1", "fsr4.1.1-cyboman.zip", archive):
            with self.assertRaisesRegex(ValueError, "exactly one lossy"):
                install_cyboman(self.context(allow_foreign=True))
        self.assertEqual(dll.read_bytes(), b"previous")

    def test_pruning_unselected_native_component_restores_its_original(self):
        existing = self.target / DLSS_ENABLER_FILE
        existing.parent.mkdir()
        existing.write_bytes(b"user enabler")
        archive = self.archive({"dxgi.dll": pe_fixture()})
        module = load_backend()
        previous = Path.cwd()
        os.chdir(self.target)
        try:
            context = self.context(allow_foreign=True)
            context.track = module.track
            with self.release("dlss-enabler", "enabler.zip", archive):
                install_dlss_enabler(context)
            owners = module.owned_components()
            owners["dlss_enabler"].update(module.INSTALLED_FILES)
            module.COMPONENT_SELECTION = {"dlss_enabler"}
            module.write_component_manifest(owners)
            module.COMPONENT_SELECTION = set()
            module.PRUNE_COMPONENTS = True
            module.configure_ue_hdr = lambda *args: None
            with contextlib.redirect_stderr(io.StringIO()):
                module.install_selected_components()
        finally:
            os.chdir(previous)
        self.assertEqual(existing.read_bytes(), b"user enabler")
        self.assertNotIn("component:dlss_enabler", assets.state(self.target)["groups"])


class ComponentContractTests(unittest.TestCase):
    def test_every_overridden_backend_attribute_still_exists(self):
        module = load_backend()
        missing = [name for name in LEGACY_HOOKS if not hasattr(module, name)]
        self.assertEqual(missing, [])
        source = Path(module.__file__).read_text()
        for name in INJECTED_SETTINGS:
            self.assertIn(f'globals().get("{name}"', source)

    def test_configure_backend_routes_migrated_components_to_native_installers(self):
        from optidx_desktop.channels import configure_backend

        module = load_backend()
        legacy = {key: getattr(module, COMPONENTS[key].backend_hook) for key in ("amd_fsr",)}
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "game"
            target.mkdir()
            (target / "game.exe").write_bytes(pe_fixture())
            game = manual_game(target / "game.exe", "Game")
            configure_backend(module, game, Repository(Path(temp) / "data"), {})
        for key, function in legacy.items():
            self.assertIsNot(getattr(module, COMPONENTS[key].backend_hook), function)
        self.assertEqual(
            module.install_dlss_enabler.__qualname__, "attach_native.<locals>.make.<locals>.run"
        )

    def test_rules_are_declared_once(self):
        problems = selection_problems({"luma", "amd_fsr", "helixsr"}, bits=32, api="DX9")
        self.assertIn("Luma requires selected or installed ReShade", problems)
        self.assertTrue(any("not both" in p for p in problems))
        self.assertTrue(any("64-bit" in p for p in problems))
        self.assertTrue(any("DX11/DX12" in p for p in problems))
        self.assertEqual(selection_problems({"renodx"}, {"ReShade": True}, api="DX9"), [])


if __name__ == "__main__":
    unittest.main()
