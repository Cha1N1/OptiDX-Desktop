import contextlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from helpers import pe_fixture
from optidx_desktop import assets, upscalers
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository
from optidx_desktop.worker import _run_job


def exported_dll(kind="ffx", bits=64):
    names = (
        ["ffxCreateContext", "ffxDestroyContext", "ffxConfigure", "ffxQuery", "ffxDispatch"]
        if kind == "ffx"
        else [
            "NVSDK_NGX_D3D12_Init",
            "NVSDK_NGX_D3D12_CreateFeature",
            "NVSDK_NGX_D3D12_EvaluateFeature",
            "NVSDK_NGX_D3D12_ReleaseFeature",
        ]
    )
    data = bytearray(pe_fixture(bits=bits))
    # Fixture section maps RVA 0x1000 to raw offset 512.
    struct.pack_into("<II", data, 0x98 + (112 if bits == 64 else 96), 0x1100, 40)
    struct.pack_into("<I", data, 768 + 24, len(names))
    struct.pack_into("<I", data, 768 + 32, 0x1140)
    offset = 900
    for i, name in enumerate(names):
        struct.pack_into("<I", data, 832 + i * 4, 0x1000 + offset - 512)
        encoded = name.encode() + b"\0"
        data[offset : offset + len(encoded)] = encoded
        offset += len(encoded)
    return bytes(data)


class UpscalerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        target = self.root / "game"
        target.mkdir()
        exe = target / "Game.exe"
        exe.write_bytes(pe_fixture())
        self.game = manual_game(exe)
        self.repo = Repository(self.root / "data")
        (target / "dxgi.dll").write_bytes(pe_fixture() + b"Can't load custom upscaler {} from {}")
        (target / "OptiScaler.ini").write_bytes(b"[Upscalers]\r\nDx12Upscaler=auto\r\n")
        self.archive = self.root / "cyboman.zip"
        with zipfile.ZipFile(self.archive, "w") as z:
            for variant in ("exact", "lossy", "lossy2"):
                z.writestr(
                    "package/" + variant + "/" + upscalers.DLL, exported_dll() + variant.encode()
                )
        self.prefs = {"upscaler_cyboman_archive": str(self.archive), "upscaler_cyboman_lossy": True}

    def test_only_checked_variants_deploy_and_direct_install_stays_intact(self):
        direct = self.game.target / "OptiScaler" / upscalers.DLL
        direct.parent.mkdir()
        direct.write_bytes(b"existing direct upscaler")
        upscalers.deploy(self.game, self.repo, self.prefs)
        custom = self.game.target / "OptiScaler/custom"
        self.assertEqual([p.name for p in custom.iterdir()], ["Cyboman-Lossy"])
        self.assertEqual(direct.read_bytes(), b"existing direct upscaler")
        from optidx_desktop.features import run_feature

        with self.assertRaisesRegex(ValueError, "Use Remove"):
            run_feature(
                self.game,
                "toggle_asset",
                {},
                self.repo,
                {"group": "upscaler:cyboman_lossy", "enabled": False},
            )
        self.assertNotEqual(
            assets.state(self.game.target)["groups"]["upscaler:cyboman_lossy"]["metadata"].get(
                "enabled"
            ),
            False,
        )
        upscalers.deploy(self.game, self.repo, {**self.prefs, "upscaler_cyboman_exact": True})
        self.assertEqual(len(list(custom.iterdir())), 2)
        upscalers.deploy(self.game, self.repo, self.prefs)
        self.assertTrue((custom / "Cyboman-Exact").exists())

    def test_prune_removes_only_managed_variants_and_resets_selected_default(self):
        upscalers.deploy(self.game, self.repo, {**self.prefs, "upscaler_cyboman_exact": True})
        foreign = self.game.target / "OptiScaler/custom/MyVariant/ffx/user.dll"
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(b"user")
        ini = self.game.target / "OptiScaler.ini"
        ini.write_bytes(b"\xef\xbb\xbf[Upscalers]\r\nDx12Upscaler=Cyboman-Exact\r\n; keep\r\n")
        upscalers.deploy(self.game, self.repo, self.prefs, prune=True)
        self.assertFalse(
            any(
                "Cyboman-Exact" in n
                for n in assets.state(self.game.target)["groups"]
                .get("upscaler:cyboman_exact", {})
                .get("files", {})
            )
        )
        self.assertEqual(foreign.read_bytes(), b"user")
        self.assertEqual(
            ini.read_bytes(), b"\xef\xbb\xbf[Upscalers]\r\nDx12Upscaler=auto\r\n; keep\r\n"
        )

    def test_dx11_input_is_not_advertised_as_custom_dx12_support(self):
        Path(self.game.executable).write_bytes(pe_fixture(imports=("d3d11.dll",)))
        with self.assertRaisesRegex(ValueError, "DX12 games only"):
            upscalers.deploy(self.game, self.repo, self.prefs)

    def test_refactored_custom_provider_diagnostics_are_not_rejected(self):
        for diagnostic in (
            b"Can't load custom upscaler {} from {}",
            b"Can't load custom upscaler %s",
            b"CustomProviders::ResolveDx12Upscaler Dx12Upscaler={} isn't an upscaler or a folder in {}",
        ):
            with self.subTest(diagnostic=diagnostic):
                (self.game.target / "dxgi.dll").write_bytes(pe_fixture() + diagnostic)
                upscalers.require_custom_loader(self.game, self.prefs)
        self.assertFalse(upscalers.supports_custom_upscalers(pe_fixture()))

    def test_old_loader_and_wrong_machine_rejected(self):
        (self.game.target / "dxgi.dll").write_bytes(pe_fixture())
        with self.assertRaisesRegex(ValueError, "custom-upscaler support"):
            upscalers.deploy(self.game, self.repo, self.prefs)
        with self.assertRaisesRegex(ValueError, "x64"):
            upscalers.checked_dll(exported_dll(bits=32), "ffx")
        arm = bytearray(exported_dll())
        struct.pack_into("<H", arm, 0x84, 0xAA64)
        with self.assertRaisesRegex(ValueError, "x64"):
            upscalers.checked_dll(bytes(arm), "ffx")

    def test_all_inputs_checked_before_any_game_writes(self):
        prefs = {
            **self.prefs,
            "upscaler_helix_dlss": True,
            "upscaler_helix_dlss_dll": str(self.root / "missing.dll"),
        }
        with self.assertRaisesRegex(ValueError, "prepared local"):
            upscalers.deploy(self.game, self.repo, prefs)
        self.assertFalse((self.game.target / "OptiScaler/custom").exists())

    def test_helix_interfaces_are_distinct(self):
        ffx = self.root / "fsr.dll"
        ngx = self.root / "helixsr.dll"
        ffx.write_bytes(exported_dll())
        ngx.write_bytes(exported_dll("dlss"))
        prefs = {
            "upscaler_helix_fsr4": True,
            "upscaler_helix_dlss": True,
            "upscaler_helix_fsr4_dll": str(ffx),
            "upscaler_helix_dlss_dll": str(ngx),
        }
        upscalers.deploy(self.game, self.repo, prefs)
        self.assertTrue(
            (self.game.target / "OptiScaler/custom/HelixSR-DLSS/dlss/nvngx.dll").exists()
        )
        with self.assertRaisesRegex(ValueError, "required dlss"):
            upscalers.checked_dll(ffx.read_bytes(), "dlss")

    def test_unsafe_archive_and_ambiguous_variant_rejected(self):
        for members in [
            ("../lossy/" + upscalers.DLL,),
            ("a/lossy/" + upscalers.DLL, "b/lossy/" + upscalers.DLL),
        ]:
            with zipfile.ZipFile(self.archive, "w") as z:
                for name in members:
                    z.writestr(name, exported_dll())
            with self.assertRaises(ValueError):
                upscalers.deploy(self.game, self.repo, self.prefs)
        self.assertFalse((self.game.target / "OptiScaler/custom").exists())

    def test_external_edits_and_case_collisions_are_preserved(self):
        upscalers.deploy(self.game, self.repo, self.prefs)
        path = self.game.target / "OptiScaler/custom/Cyboman-Lossy/ffx" / upscalers.DLL
        path.write_bytes(b"external edit")
        with self.assertRaises(assets.Conflict):
            upscalers.deploy(self.game, self.repo, self.prefs)
        self.assertEqual(path.read_bytes(), b"external edit")
        path.parent.parent.rename(path.parent.parent.with_name("cyboman-lossy"))
        with self.assertRaises(assets.Conflict):
            upscalers.deploy(self.game, self.repo, self.prefs)

    def test_failed_multi_variant_job_rolls_back_files_and_ledger(self):
        original = assets.deploy

        def fail_second(root, group, files, metadata=None, *args, **kwargs):
            if group == "upscaler:cyboman_lossy":
                raise OSError("late failure")
            return original(root, group, files, metadata, *args, **kwargs)

        request = {
            "game": self.game.to_dict(),
            "action": "deploy_upscalers",
            "preferences": {**self.prefs, "upscaler_cyboman_exact": True},
        }
        with (
            patch.object(assets, "deploy", side_effect=fail_second),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(OSError, "late failure"):
                _run_job(request, self.repo.directory)
        self.assertFalse(assets.state(self.game.target)["groups"])
        self.assertFalse(list((self.game.target / "OptiScaler/custom").rglob("*.dll")))

    def test_obsolete_lossy2_rejected_before_any_download(self):
        preferences = {"upscaler_cyboman_lossy2": True, "upscaler_cyboman_target": "rx6000"}
        with patch.object(upscalers.Client, "release_asset") as download:
            with self.assertRaisesRegex(ValueError, "Choose Cyboman Lossy"):
                upscalers.deploy(self.game, self.repo, preferences)
            download.assert_not_called()
        self.assertFalse((self.game.target / "OptiScaler/custom").exists())
        self.assertFalse(upscalers.legacy_lossy2_source({"upscaler_cyboman_tag": "dll-2026-10-29"}))
        self.assertTrue(upscalers.legacy_lossy2_source({"upscaler_cyboman_tag": "dll-2026-10-22"}))

    def test_new_release_lite_variants_and_warning_retention(self):
        with zipfile.ZipFile(self.archive, "w") as z:
            for folder in ("exact", "lossy", "4.1.2l-exact", "4.1.2l-lossy"):
                z.writestr(folder + "/" + upscalers.DLL, exported_dll())
                z.writestr(folder + "/WARNING.txt", "Upstream picture tradeoffs")
        prefs = {**self.prefs, "upscaler_cyboman_lite_lossy": True}
        upscalers.deploy(self.game, self.repo, prefs)
        custom = self.game.target / "OptiScaler/custom"
        self.assertEqual(
            sorted(p.name for p in custom.iterdir()), ["Cyboman-Lite-Lossy", "Cyboman-Lossy"]
        )
        self.assertEqual(
            (custom / "Cyboman-Lite-Lossy/WARNING.txt").read_text(), "Upstream picture tradeoffs"
        )
        with self.assertRaisesRegex(ValueError, "Lossy2 is absent"):
            upscalers.deploy(self.game, self.repo, {**prefs, "upscaler_cyboman_lossy2": True})
        self.assertEqual(len(assets.state(self.game.target)["groups"]), 2)

    def test_updates_reuse_installed_hardware_pin_and_respect_exclusions(self):
        from optidx_desktop.features import update_features, update_groups

        upscalers.deploy(self.game, self.repo, self.prefs)
        ledger = assets.state(self.game.target)
        ledger["groups"]["upscaler:cyboman_lossy"]["metadata"].update(
            {
                "source": {"repo": upscalers.CYBOMAN_REPO, "tag": "dll-2026-10-29"},
                "target": "rx6000",
            }
        )
        from optidx_desktop.storage import atomic_json

        atomic_json(self.game.target / assets.LEDGER, ledger)
        preferences = {"upscaler_cyboman_target": "rx7000", "upscaler_prune": True}
        with patch.object(upscalers, "deploy") as deploy:
            update_features(self.game, self.repo, preferences, "upscaler:cyboman_lossy")
            effective = deploy.call_args.args[2]
            self.assertEqual(effective["upscaler_cyboman_target"], "rx6000")
            self.assertEqual(effective["upscaler_cyboman_tag"], "dll-2026-10-29")
            self.assertNotIn("prune", deploy.call_args.kwargs)
            deploy.reset_mock()
            excluded = {**preferences, "exclude_components": ["upscaler:cyboman_lossy"]}
            update_features(self.game, self.repo, excluded)
            deploy.assert_not_called()
            self.assertNotIn("upscaler:cyboman_lossy", update_groups(self.game, excluded))

    def test_optiscaler_update_preserves_independently_owned_custom_dll(self):
        from optidx_desktop.core_payload import install_optiscaler_payload

        upscalers.deploy(self.game, self.repo, self.prefs)
        path = self.game.target / "OptiScaler/custom/Cyboman-Lossy/ffx" / upscalers.DLL
        before = path.read_bytes()
        with patch(
            "optidx_desktop.core_payload.archive_files",
            return_value={"OptiScaler.dll": pe_fixture()},
        ):
            install_optiscaler_payload(
                self.game.target, "unused.7z", 64, "dxgi.dll", allow_foreign=True
            )
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("upscaler:cyboman_lossy", assets.state(self.game.target)["groups"])
        self.assertNotIn(
            str(path.relative_to(self.game.target)),
            assets.state(self.game.target)["groups"]["backend:optiscaler"]["files"],
        )

    def test_official_upstream_channel_ignores_configured_fork(self):
        from optidx_desktop.backend import load_backend
        from optidx_desktop.channels import configure_backend

        module = load_backend()
        release = {
            "browser_download_url": "https://example.com/upstream.7z",
            "version": "nightly-20261029",
            "repository": "optiscaler/OptiScaler-nightly",
        }
        with patch("optidx_desktop.channels.Client.release_asset", return_value=release) as fetch:
            configure_backend(
                module,
                self.game,
                self.repo,
                {"optiscaler_channel": "upstream_nightly", "optiscaler_repo": "other/fork"},
            )
            self.assertEqual(module.optiscaler_urls(), [release["browser_download_url"]])
            self.assertEqual(fetch.call_args.args[0], "optiscaler/OptiScaler-nightly")
            self.assertEqual(fetch.call_args.args[2], "nightly")

    def test_malformed_exports_do_not_pass_interface_validation(self):
        malformed = bytearray(exported_dll())
        struct.pack_into("<I", malformed, 768 + 24, 0xFFFFFFFF)
        for data in (b"MZ", bytes(malformed), exported_dll()[:900]):
            with self.assertRaises(ValueError):
                upscalers.checked_dll(data, "ffx")

    def test_hardware_release_patterns_do_not_match_other_targets(self):
        import re

        pattern = upscalers.cyboman_pattern("rx6000")
        self.assertRegex("fsr4.1.2-cyboman-rx6000-2026-10-29.7z", pattern)
        self.assertIsNone(re.search(pattern, "fsr4.1.2-cyboman-rx7000-2026-10-29.7z"))
        self.assertIsNone(re.search(pattern, "fsr4-timing-kit-windows-2026-10-29.7z"))
        with self.assertRaisesRegex(ValueError, "hardware"):
            upscalers.cyboman_pattern("")
