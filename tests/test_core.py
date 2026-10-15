import contextlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from optidx_desktop.backend import bind_target, execute_backend, launch_options, load_backend, validate_game
from optidx_desktop.backups import remember_baseline, restore_originals, snapshot
from optidx_desktop.inspection import inspect_game, manifest_paths, pe_info
from optidx_desktop.library import manual_game, scan_library, vdf_parse
from optidx_desktop.models import Game, game_id
from optidx_desktop.storage import Repository, atomic_json


def pe_fixture(imports=("d3d12.dll",), bits=64):
    data = bytearray(2048)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664 if bits == 64 else 0x14c, 1)
    optional_size = 240 if bits == 64 else 224
    struct.pack_into("<H", data, 0x94, optional_size)
    struct.pack_into("<H", data, 0x98, 0x20b if bits == 64 else 0x10b)
    struct.pack_into("<II", data, 0x98 + (112 if bits == 64 else 96) + 8, 0x1000, 20 * (len(imports) + 1))
    section = 0x98 + optional_size
    struct.pack_into("<IIII", data, section + 8, 1024, 0x1000, 1024, 512)
    for i, name in enumerate(imports):
        offset = 768 + 64 * i
        struct.pack_into("<IIIII", data, 512 + 20 * i, 0, 0, 0, 0x1000 + offset - 512, 0)
        encoded = name.encode() + b"\0"
        data[offset:offset + len(encoded)] = encoded
    return bytes(data)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.binary = self.root / "Game/Binaries/Win64"
        self.binary.mkdir(parents=True)
        self.executable = self.binary / "Actual-Win64-Shipping.exe"
        self.executable.write_bytes(pe_fixture())
        self.game = manual_game(self.executable, "Actual Game")
        self.repository = Repository(self.root / "data")

    def tearDown(self):
        self.temporary.cleanup()

    def test_pe_header_import_detection_and_malformed_binary(self):
        info = pe_info(self.executable)
        self.assertEqual(info["bits"], 64)
        self.assertEqual(info["apis"], ["DX12"])
        self.executable.write_bytes(b"not a PE d3d11.dll")
        self.assertEqual(pe_info(self.executable)["apis"], [])

    def test_manual_unreal_root_and_component_inspection(self):
        self.assertEqual(Path(self.game.root), self.binary.parent.parent)
        self.assertEqual(inspect_game(self.game)["engine"], "Unreal")
        (self.binary / "renodx-ue-extended.addon64").write_bytes(b"addon")
        self.assertTrue(inspect_game(self.game)["components"]["RenoDX"])

    def test_delayed_direct3d_import_is_detected_beside_fallback_opengl(self):
        data = bytearray(pe_fixture(("opengl32.dll",)))
        struct.pack_into("<II", data, 0x98 + 112 + 13 * 8, 0x1000 + 600, 64)
        struct.pack_into("<IIIIIIII", data, 512 + 600, 1, 0x1000 + 750, 0, 0, 0, 0, 0, 0)
        data[512 + 750:512 + 750 + 11] = b"d3d12.dll\0\0"
        self.executable.write_bytes(data)
        self.assertEqual(pe_info(self.executable)["apis"], ["DX12", "OpenGL"])

    def test_vdf_nested_and_escaped_paths(self):
        self.assertEqual(vdf_parse('"libraryfolders" { "0" { "path" "C:\\\\Steam" } }')
                         ["libraryfolders"]["0"]["path"], "C:\\Steam")

    def test_steam_external_library_selects_shipping_binary_and_prefix(self):
        steam = self.home / ".local/share/Steam/steamapps"
        steam.mkdir(parents=True)
        library = self.root / "External Steam Library"
        game = library / "steamapps/common/MyGame/Binaries/Win64"
        game.mkdir(parents=True)
        (game / "MyGame-Win64-Shipping.exe").write_bytes(pe_fixture())
        (steam / "libraryfolders.vdf").write_text('"libraryfolders" { "1" { "path" "' + str(library) + '" } }')
        (library / "steamapps/appmanifest_123.acf").write_text(
            '"AppState" { "appid" "123" "name" "My Game" "installdir" "MyGame" }')
        games, warnings = scan_library(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(len(games), 1)
        self.assertTrue(games[0].executable.endswith("Shipping.exe"))
        self.assertEqual(games[0].launch_uri, "steam://rungameid/123")
        self.assertTrue(games[0].prefix.endswith("compatdata/123/pfx"))

    def test_heroic_discovery_remembers_which_installation_owns_the_game(self):
        config = self.home / '.var/app/com.heroicgameslauncher.hgl/config/heroic'
        atomic_json(config / 'sideload_apps/library.json', {'games': [{'app_name': 'test',
                    'title': 'Flatpak game', 'install_path': str(self.binary)}]})
        games, warnings = scan_library(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(games[0].launcher_kind, 'flatpak')
        self.assertEqual(Game.from_dict(games[0].to_dict()).launcher_kind, 'flatpak')

    def test_heroic_sideload_and_epic_profiles(self):
        heroic = self.home / ".config/heroic"
        atomic_json(heroic / "sideload_apps/library.json", {"games": [{"title": "Actual Game", "app_name": "myid",
                     "folder_name": self.game.root, "install": {"executable": str(self.executable)}}]})
        atomic_json(heroic / "GamesConfig/myid.json", {"myid": {"winePrefix": "/my/prefix"}})
        games, warnings = scan_library(self.home)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].prefix, "/my/prefix")
        self.assertEqual(games[0].runner, "sideload")
        self.assertIn("appName=myid", games[0].launch_uri)

    def test_cache_preserves_unplugged_game(self):
        cached = Game("offline", "Offline Game", "Steam", str(self.root / "unplugged"))
        games, warnings = scan_library(self.home, [cached])
        self.assertEqual(games, [cached])
        self.assertFalse(games[0].available)

    def test_malformed_store_does_not_block_other_store(self):
        heroic = self.home / ".config/heroic"
        atomic_json(heroic / "sideload_apps/library.json", {"games": None})
        games, warnings = scan_library(self.home, [self.game])
        self.assertEqual(games, [self.game])
        self.assertTrue(warnings)

    def test_paths_cannot_escape_manifest_or_follow_outside_symlink(self):
        (self.binary / ".optidx-files").write_text("../../outside.dll\n")
        with self.assertRaises(ValueError):
            validate_game(self.game)
        (self.binary / ".optidx-files").write_text("escape.dll\n")
        (self.binary / "escape.dll").symlink_to(self.root / "outside.dll")
        with self.assertRaises(ValueError):
            manifest_paths(self.binary)

    def test_marker_cannot_redirect_operation(self):
        (self.binary / ".optidx-installed").write_text(str(self.root) + "\nv2.1.2\n")
        with self.assertRaises(ValueError):
            validate_game(self.game)

    def test_verified_backup_restores_foreign_dll_and_permissions(self):
        original = self.binary / "dxgi.dll"
        original.write_bytes(b"other mod")
        original.chmod(0o640)
        folder = snapshot(self.game, self.repository)
        remember_baseline(self.game, self.repository, folder)
        original.write_bytes(b"OptiScaler")
        restore_originals(self.game, self.repository)
        self.assertEqual(original.read_bytes(), b"other mod")
        self.assertEqual(original.stat().st_mode & 0o777, 0o640)

    def test_updates_keep_first_backup_and_do_not_restore_managed_files(self):
        original = self.binary / "dxgi.dll"
        original.write_bytes(b"original")
        managed = self.binary / "renodx-test.addon64"
        managed.write_bytes(b"managed")
        (self.binary / ".optidx-files").write_text(managed.name + "\n")
        folder = snapshot(self.game, self.repository)
        remember_baseline(self.game, self.repository, folder)
        original.write_bytes(b"first install")
        remember_baseline(self.game, self.repository, snapshot(self.game, self.repository))
        original.unlink()
        managed.unlink()
        restore_originals(self.game, self.repository)
        self.assertEqual(original.read_bytes(), b"original")
        self.assertFalse(managed.exists())

    def test_tampered_backup_is_not_restored(self):
        (self.binary / "dxgi.dll").write_bytes(b"original")
        folder = snapshot(self.game, self.repository)
        remember_baseline(self.game, self.repository, folder)
        (folder / "files/dxgi.dll").write_bytes(b"bad backup")
        with self.assertRaises(ValueError):
            restore_originals(self.game, self.repository)

    def test_exact_binary_adapter_preserves_title_and_never_launches(self):
        module = load_backend()
        calls = []
        def install(args):
            calls.append(args)
            self.assertTrue(module.detect_game())
            self.assertEqual(module.GAME_EXE, str(self.executable))
            self.assertEqual(module.GAME_NAME, "Actual Game")
            (self.binary / ".optidx-files").write_text("renodx-test.addon64\n")
        module.main = install
        with patch.dict(os.environ, {"WINEPREFIX": "/wrong/prefix"}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            execute_backend(self.game, "update", {"mode": "renodx", "native_hdr": False, "prefix": "/right/prefix"}, module)
            self.assertEqual(os.environ["WINEPREFIX"], "/right/prefix")
        self.assertEqual(calls, [["--components=renodx,reshade", "--update", "--no-ue-hdr"]])
        with self.assertRaises(RuntimeError):
            module.launch_now()

    def test_backend_reports_no_install_instead_of_success(self):
        module = load_backend()
        module.main = lambda args: None
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, "No installation"):
            execute_backend(self.game, "install", {}, module)

    def test_adapter_cleanup_preserves_unrelated_addons(self):
        foreign = self.binary / "OtherTool.addon"
        foreign.write_bytes(b"user addon")
        managed = self.binary / "renodx-old.addon64"
        managed.write_bytes(b"old managed addon")
        (self.binary / ".optidx-files").write_text(managed.name + "\n")
        module = load_backend()
        bind_target(module, self.game)
        module.cleanup_stale()
        self.assertTrue(foreign.exists())
        self.assertFalse(managed.exists())

    def test_unsupported_api_does_not_run_backend(self):
        self.executable.write_bytes(pe_fixture(("d3d9.dll",)))
        module = load_backend()
        with patch.object(module, "main") as run, self.assertRaisesRegex(ValueError, "DX11/DX12"):
            execute_backend(self.game, "install", {}, module)
        run.assert_not_called()

    def test_settings_preserve_comments_and_existing_values(self):
        ini = self.binary / "OptiScaler.ini"
        ini.write_text("; user\n[FrameGen]\nFGInput=dlssg\nFGOutput=auto\n[Other]\nX=4\n")
        module = load_backend()
        module.configure_ue_hdr = lambda directory: None
        with patch.dict(os.environ, {}, clear=True):
            execute_backend(self.game, "configure", {"FGOutput": "xefg"}, module)
        text = ini.read_text()
        self.assertIn("; user", text)
        self.assertIn("FGInput=dlssg", text)
        self.assertIn("FGOutput=xefg", text)
        self.assertIn("X=4", text)

    def test_worker_failure_is_structured_and_makes_no_game_changes(self):
        request = {"game": self.game.to_dict(), "action": "install"}
        request["game"]["executable"] = str(self.root / "missing.exe")
        result = subprocess.run([sys.executable, "-B", "-m", "optidx_desktop.worker", "--request", json.dumps(request),
                                 "--data-dir", str(self.repository.directory)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        event = json.loads(result.stdout.splitlines()[-1])
        self.assertFalse(event["ok"])
        self.assertEqual(list(self.binary.iterdir()), [self.executable])

    def test_launch_options_quote_script_path_and_keep_forwarding(self):
        command = launch_options({"native_hdr": False, "mode": "luma"})
        self.assertIn("--components=luma,reshade", command)
        self.assertIn("--no-ue-hdr", command)
        self.assertTrue(command.endswith(" %command%"))


if __name__ == "__main__":
    unittest.main()
