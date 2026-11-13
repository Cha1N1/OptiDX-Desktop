"""Optional frame-generation tools, the built-in OptiDX preset and fork retirement."""

from pathlib import Path
import tempfile
import unittest
import zipfile

from helpers import pe_fixture
from test_upscalers import exported_dll
from optidx_desktop import assets
from optidx_desktop.channels import optiscaler_source
from optidx_desktop.features import deploy_extra, run_feature
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository

CAPABLE = pe_fixture() + b"FGNvngxReplacement={} isn't a replacement or a folder with dlssg in {}"
ANR = "OptiScaler/custom/Apex Neural Rendering FG/dlssg/"
XMX = "OptiScaler/custom/XeMFG XMX/dlssg/"


class FrameGenToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "game"
        self.target.mkdir()
        (self.target / "Game.exe").write_bytes(pe_fixture())
        self.game = manual_game(self.target / "Game.exe")
        self.repo = Repository(self.root / "data")
        (self.target / "dxgi.dll").write_bytes(CAPABLE)
        self.ini = self.target / "OptiScaler.ini"
        self.ini.write_bytes(
            b"[FrameGen]\r\nFGInput=dlssg\r\nFGOutput=xefg\r\nFGNvngxReplacement=auto\r\n"
            b"[Plugins]\r\nLoadAsiPlugins=auto\r\n"
        )

    def zip(self, name, files):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, data in files.items():
                archive.writestr(member, data)
        return path

    def anr(self, config=b"path = auto\n"):
        return self.zip(
            "anr.zip",
            {
                "README.txt": b"readme",
                "install.sh": b"#!/bin/sh\n",
                "Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll": exported_dll("dlss"),
                "Apex Neural Rendering FG/dlssg/nr_fg.ini": config,
                "Apex Neural Rendering FG/dlssg/kernels/pack.nrx": b"kernels",
            },
        )

    def xmx(self):
        return self.zip(
            "xmx.zip",
            {
                "XeMFG XMX/dlssg/dlssg_to_xefg_intel_is_better.dll": exported_dll("dlss"),
                "XeMFG XMX/dlssg/xefg_mfg_programs/programs.tsv": b"programs",
            },
        )

    def install(self, key, path, **preferences):
        return deploy_extra(
            self.game, self.repo, key, {"api_override": "DX12", **preferences}, {"path": str(path)}
        )

    def framegen(self):
        from optidx_desktop.backend import load_backend

        return load_backend().hdr_ini_values(self.ini.read_text(), "FrameGen")

    def test_provider_installs_only_its_tree_and_removal_restores_ini(self):
        self.install("anr_fg", self.anr())
        self.assertTrue((self.target / ANR / "nvngx_dlssg.dll").is_file())
        self.assertTrue((self.target / ANR / "kernels/pack.nrx").is_file())
        # Bundled installer scripts are never deployed.
        self.assertFalse(
            any(p.name in {"install.sh", "README.txt"} for p in self.target.rglob("*"))
        )
        values = self.framegen()
        self.assertEqual(values["fginput"], "nvngxfg")
        self.assertEqual(values["fgnvngxreplacement"], "Apex Neural Rendering FG")
        self.assertEqual(values["fgoutput"], "xefg")

        run_feature(self.game, "remove_asset", {}, self.repo, {"group": "extra:anr_fg"})
        self.assertFalse((self.target / ANR).exists())
        values = self.framegen()
        self.assertEqual((values["fginput"], values["fgnvngxreplacement"]), ("dlssg", "auto"))
        self.assertFalse((self.target / ".optidx-desktop-framegen.json").exists())

    def test_refresh_keeps_edited_provider_config_and_later_menu_choice(self):
        self.install("anr_fg", self.anr())
        (self.target / ANR / "nr_fg.ini").write_bytes(b"path = coopmat\n")
        text = self.ini.read_text().replace(
            "FGNvngxReplacement=Apex Neural Rendering FG", "FGNvngxReplacement=FFX"
        )
        self.ini.write_text(text)
        assets.accept_config_edit(self.target, "OptiScaler.ini")

        self.install("anr_fg", self.anr(b"path = auto\nnew = 1\n"))
        self.assertEqual((self.target / ANR / "nr_fg.ini").read_bytes(), b"path = coopmat\n")
        self.assertEqual(self.framegen()["fgnvngxreplacement"], "FFX")
        # The user's later choice is not undone by removal either.
        run_feature(self.game, "remove_asset", {}, self.repo, {"group": "extra:anr_fg"})
        self.assertEqual(self.framegen()["fgnvngxreplacement"], "FFX")

    def test_stacked_providers_never_restore_a_removed_provider(self):
        self.install("anr_fg", self.anr())
        self.install("xemfg_xmx", self.xmx())
        self.assertEqual(self.framegen()["fgnvngxreplacement"], "XeMFG XMX")
        run_feature(self.game, "remove_asset", {}, self.repo, {"group": "extra:anr_fg"})
        self.assertEqual(self.framegen()["fgnvngxreplacement"], "XeMFG XMX")
        self.assertEqual(self.framegen()["fginput"], "nvngxfg")
        run_feature(self.game, "remove_asset", {}, self.repo, {"group": "extra:xemfg_xmx"})
        # Removing the inactive provider first leaves the active choice alone.
        values = self.framegen()
        self.assertEqual(values["fgnvngxreplacement"], "auto")
        self.assertEqual(values["fginput"], "dlssg")
        self.assertFalse((self.target / "OptiScaler/custom").exists())

    def test_bare_provider_dll_gets_a_dlssg_folder(self):
        package = self.zip(
            "plain.zip",
            {"dlssg_to_xefg_intel_is_better.dll": exported_dll("dlss"), "LICENSE": b"GPL"},
        )
        self.install("dlssg_to_xefg", package)
        folder = self.target / "OptiScaler/custom/dlssg-to-xefg/dlssg"
        self.assertEqual(
            sorted(p.name for p in folder.iterdir()),
            ["LICENSE", "dlssg_to_xefg_intel_is_better.dll"],
        )

    def test_provider_preflight_rejections_change_nothing(self):
        before = self.ini.read_bytes()
        not_ngx = self.zip("bad.zip", {"XeMFG XMX/dlssg/x.dll": exported_dll("ffx")})
        with self.assertRaisesRegex(ValueError, "nvngx_dlssg"):
            self.install("xemfg_xmx", not_ngx)
        with self.assertRaisesRegex(ValueError, "Vulkan"):
            self.install("xemfg_xmx", self.xmx(), api_override="Vulkan")
        with self.assertRaisesRegex(ValueError, "64-bit"):
            self.install("xemfg_xmx", self.xmx(), bits_override="32")
        (self.target / "dxgi.dll").write_bytes(pe_fixture() + b"OptiScaler 0.9.4")
        with self.assertRaisesRegex(ValueError, "custom frame-generation"):
            self.install("anr_fg", self.anr())
        self.assertEqual(self.ini.read_bytes(), before)
        self.assertFalse((self.target / "OptiScaler/custom").exists())
        self.assertNotIn("extra:anr_fg", assets.state(self.target)["groups"])

    def test_mfg_unlocker_adopts_fork_bundled_plugin_and_enables_asi_loading(self):
        old = pe_fixture() + b"fork MFGUnlocker"
        plugin = self.target / "OptiScaler/plugins/MFGUnlocker.asi"
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(old)
        ledger = assets.state(self.target)
        ledger["groups"]["backend:optiscaler"] = {
            "files": {
                "OptiScaler/plugins/MFGUnlocker.asi": {"sha256": assets.sha(old), "original": None}
            },
            "metadata": {"kind": "backend"},
        }
        from optidx_desktop.storage import atomic_json

        atomic_json(self.target / assets.LEDGER, ledger)
        new = pe_fixture() + b"MFGUnlocker v1.7.1"
        self.install("mfg_unlocker", self.zip("mfg.zip", {"MFGUnlocker.dll": new}))
        self.assertEqual(plugin.read_bytes(), new)
        groups = assets.state(self.target)["groups"]
        self.assertNotIn(
            "OptiScaler/plugins/MFGUnlocker.asi", groups["backend:optiscaler"]["files"]
        )
        self.assertIn("LoadAsiPlugins=true", self.ini.read_text())
        run_feature(self.game, "remove_asset", {}, self.repo, {"group": "extra:mfg_unlocker"})
        self.assertFalse(plugin.exists())

    def test_mfg_unlocker_does_not_silently_replace_an_unmanaged_plugin(self):
        plugin = self.target / "OptiScaler/plugins/MFGUnlocker.asi"
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(pe_fixture() + b"user copy")
        with self.assertRaises(assets.Conflict):
            self.install("mfg_unlocker", self.zip("mfg.zip", {"MFGUnlocker.dll": pe_fixture()}))
        self.assertEqual(plugin.read_bytes(), pe_fixture() + b"user copy")

    def test_mfg_unlocker_requires_optiscaler(self):
        self.ini.unlink()
        with self.assertRaisesRegex(ValueError, "Install OptiScaler"):
            self.install("mfg_unlocker", self.zip("mfg.zip", {"MFGUnlocker.dll": pe_fixture()}))

    def test_builtin_preset_sets_fork_defaults_and_keeps_other_settings(self):
        self.ini.write_text(
            "[Upscalers]\nDx12Upscaler=auto\nDx11Upscaler=fsr22\n[FrameGen]\nFGInput=auto\n"
            "[XeFG]\nInterpolationCount=auto\n[Libraries]\nOptiDllPath=keep\n"
        )
        run_feature(self.game, "apply_template", {}, self.repo, {"id": "optidx"})
        from optidx_desktop.backend import load_backend

        module = load_backend()
        text = self.ini.read_text()
        self.assertEqual(module.hdr_ini_values(text, "Upscalers")["dx12upscaler"], "ffx")
        self.assertEqual(module.hdr_ini_values(text, "Upscalers")["dx11upscaler"], "fsr22")
        self.assertEqual(module.hdr_ini_values(text, "FrameGen")["fginput"], "dlssg")
        self.assertEqual(module.hdr_ini_values(text, "FrameGen")["fgoutput"], "xefg")
        self.assertEqual(module.hdr_ini_values(text, "XeFG")["interpolationcount"], "5")
        self.assertEqual(module.hdr_ini_values(text, "Libraries")["optidllpath"], "keep")


class OptiScalerSourceTests(unittest.TestCase):
    def test_retired_fork_resolves_to_upstream(self):
        fork = {"repository": "Cha1N1/OptiScaler", "channel": "nightly"}
        self.assertEqual(optiscaler_source({}), ("optiscaler/OptiScaler-nightly", "nightly"))
        self.assertEqual(optiscaler_source({}, fork), ("optiscaler/OptiScaler-nightly", "nightly"))
        self.assertEqual(
            optiscaler_source({"optiscaler_repo": "cha1n1/OptiScaler"}),
            ("optiscaler/OptiScaler-nightly", "nightly"),
        )
        self.assertEqual(
            optiscaler_source({"optiscaler_channel": "upstream_nightly", "optiscaler_repo": "a/b"}),
            ("optiscaler/OptiScaler-nightly", "nightly"),
        )

    def test_explicit_choices_and_channel_specific_records_are_kept(self):
        self.assertEqual(
            optiscaler_source({"optiscaler_channel": "nightly", "optiscaler_repo": "other/fork"}),
            ("other/fork", "nightly"),
        )
        stable = {"repository": "optiscaler/OptiScaler", "channel": "stable"}
        self.assertEqual(optiscaler_source({}, stable), ("optiscaler/OptiScaler", "stable"))
        # A recorded stable repository is not reused after switching to nightly.
        self.assertEqual(
            optiscaler_source({"optiscaler_channel": "nightly"}, stable),
            ("optiscaler/OptiScaler-nightly", "nightly"),
        )


if __name__ == "__main__":
    unittest.main()
