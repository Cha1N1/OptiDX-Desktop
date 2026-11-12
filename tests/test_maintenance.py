"""Regression coverage for the current-source maintenance review."""

import codecs
import contextlib
from dataclasses import FrozenInstanceError, replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from helpers import pe_fixture
from optidx_desktop import assets
from optidx_desktop.backend import backend_scope, load_backend
from optidx_desktop.backups import snapshot, rollback_snapshot, finish_snapshots
from optidx_desktop.diagnostics import redact
from optidx_desktop.downloads import Client, archive_files, sha
from optidx_desktop.features import edit_config
from optidx_desktop.history import trim_history
from optidx_desktop.launch import hdr_session, run_profile
from optidx_desktop.models import Game, Job, game_id, stable_game_id
from optidx_desktop.storage import Repository, atomic_json, read_json
from optidx_desktop.worker import run_job


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target = self.root / "game"
        self.target.mkdir()
        self.exe = self.target / "game.exe"
        self.exe.write_bytes(pe_fixture())
        self.game = Game("fixture", "Fixture", "Manual", str(self.target), str(self.exe))
        self.repo = Repository(self.root / "data")

    def tearDown(self):
        self.temporary.cleanup()

    def test_corrupt_ownership_is_preserved_and_blocks_deployment(self):
        path = self.target / assets.LEDGER
        path.write_bytes(b"{broken")
        with self.assertRaisesRegex(ValueError, "Cannot read JSON record"):
            assets.deploy(self.target, "new", {"example.dll": b"new"})
        self.assertEqual(path.read_bytes(), b"{broken")
        self.assertFalse((self.target / "example.dll").exists())
        atomic_json(path, {"version": 1, "groups": {}})
        with patch("optidx_desktop.storage.os.fsync", wraps=os.fsync) as fsync:
            atomic_json(path, {"version": 1, "groups": {}})
        self.assertEqual(fsync.call_count, 2)

    def test_disposable_corrupt_cache_is_quarantined(self):
        path = self.root / "cache.json"
        path.write_bytes(b"{broken")
        with self.assertWarns(RuntimeWarning):
            self.assertEqual(read_json(path, {}, strict=False), {})
        self.assertEqual(next(self.root.glob("cache.json.corrupt-*")).read_bytes(), b"{broken")
        self.assertEqual(read_json(self.root / "missing", {}), {})

    def test_backend_retries_never_disable_tls(self):
        module = load_backend()
        output = self.root / "payload"
        calls = []

        def curl(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return SimpleNamespace(returncode=22)
            Path(command[command.index("-o") + 1]).write_bytes(b"payload")
            return SimpleNamespace(returncode=0)

        with patch.object(module.subprocess, "run", side_effect=curl):
            self.assertTrue(module.fetch("https://example.test/payload", str(output), 2))
        self.assertTrue(all("-k" not in command for command in calls))
        self.assertTrue(all("--proto-redir" in command for command in calls))

    def test_backend_checks_registered_digest_on_cached_payload(self):
        module = load_backend()
        module.CACHE_DIR = self.root / "cache"
        url = module.register_asset(
            {
                "browser_download_url": "https://example.test/mod",
                "digest": "sha256:" + sha(b"expected"),
            }
        )

        def fetch(url, destination, tries):
            Path(destination).write_bytes(b"wrong")
            return True

        with patch.object(module, "fetch", side_effect=fetch):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                module.fetch_payload(url, str(self.root / "out"))
        self.assertFalse((self.root / "out").exists())

    def test_quirks_accept_equals_and_whitespace_formats(self):
        for separator in (" = ", " "):
            module = load_backend()
            module.USER_QUIRKS_CONF = self.root / "quirks"
            module.USER_QUIRKS_CONF.write_text("mygame" + separator + "optiscaler_dll=d3d12.dll\n")
            module.CANDIDATE_TITLES = ["mygame"]
            with contextlib.redirect_stderr(io.StringIO()):
                module.resolve_game_quirks()
            self.assertEqual(module.QUIRK_OPTISCALER_DLL, "d3d12.dll")

    def test_prefix_matching_requires_executable_origin_coverage_and_uniqueness(self):
        module = load_backend()

        def row(title):
            return (title, "", "", "", title, title, "addon64", "https://example.test/mod", False)

        self.assertIsNone(
            module.match_candidates(
                ["dark"], [row("darksouls")], 99999, fallback_candidates=["dark"]
            )
        )
        self.assertIsNone(module.match_candidates(["longtitle"], [row("longtitleone")], 99999))
        self.assertIsNone(
            module.match_candidates(
                ["longtitle"],
                [row("longtitle1"), row("longtitle2")],
                99999,
                fallback_candidates=["longtitle"],
            )
        )
        self.assertEqual(
            module.match_candidates(
                ["longtitle"], [row("longtitle1")], 99999, fallback_candidates=["longtitle"]
            )["slug"],
            "longtitle1",
        )

    def test_editor_preserves_bom_endian_and_newlines(self):
        for bom, encoding in [
            (codecs.BOM_UTF16_BE, "utf-16-be"),
            (codecs.BOM_UTF16_LE, "utf-16-le"),
            (codecs.BOM_UTF8, "utf-8"),
            (b"", "utf-8"),
        ]:
            path = self.target / "ReShade.ini"
            before = bom + "[GENERAL]\r\nName=old\r\n".encode(encoding)
            path.write_bytes(before)
            edit_config(
                self.game,
                {"name": path.name, "before_sha256": sha(before), "text": "[GENERAL]\nName=new\n"},
            )
            self.assertEqual(path.read_bytes(), bom + "[GENERAL]\r\nName=new\r\n".encode(encoding))

    def test_launch_survives_invalid_environment_and_deferred_hdr(self):
        path = self.root / "profile.json"
        atomic_json(
            path, {"environment": {"bad-name": "bad"}, "auto_hdr": True, "hdr_output": "DP-1"}
        )
        with (
            patch(
                "optidx_desktop.launch.finish_deferred_hdr", side_effect=OSError("broken journal")
            ),
            patch("optidx_desktop.launch.hdr_session", side_effect=BlockingIOError("busy")),
            contextlib.redirect_stderr(io.StringIO()) as log,
        ):
            self.assertEqual(run_profile(path, [sys.executable, "-c", "raise SystemExit(7)"]), 7)
        self.assertIn("Automatic HDR skipped", log.getvalue())
        self.assertIn("Deferred HDR", log.getvalue())

    def test_hdr_restores_only_after_last_user_on_each_display(self):
        current = [101]
        live = {101: "first", 202: "second"}
        with (
            patch("optidx_desktop.launch.data_dir", return_value=self.repo.directory),
            patch("optidx_desktop.launch.os.getpid", side_effect=lambda: current[0]),
            patch("optidx_desktop.launch._process_token", side_effect=live.get),
            patch(
                "optidx_desktop.launch.hdr_outputs",
                return_value=[{"name": "DP-1", "enabled": False, "capable": True}],
            ),
            patch("optidx_desktop.launch.set_hdr") as hdr,
        ):
            hdr_session("DP-1", True)
            current[0] = 202
            hdr_session("DP-1", True)
            current[0] = 101
            hdr_session("DP-1", False)
            self.assertEqual(hdr.call_count, 1)
            current[0] = 202
            hdr_session("DP-1", False)
            self.assertEqual(
                [call.args for call in hdr.call_args_list], [("DP-1", True), ("DP-1", False)]
            )

    def test_downloader_auth_is_api_only_and_deadline_detects_stalls(self):
        client = Client(self.repo.directory)
        calls = []

        def curl(command, **kwargs):
            calls.append(command + [kwargs.get("input", "")])
            Path(command[command.index("-o") + 1]).write_bytes(b"{}")
            return SimpleNamespace(returncode=0)

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "fixture-secret"}),
            patch("optidx_desktop.downloads.subprocess.run", side_effect=curl),
        ):
            client.fetch("https://api.github.com/repos/example/test")
            client.fetch("https://example.test/mod")
        # The token travels on curl's stdin config (last item), never as an argument.
        self.assertIn("Authorization: Bearer fixture-secret", calls[0][-1])
        self.assertFalse(any("fixture-secret" in part for part in calls[0][:-1]))
        self.assertFalse(any("fixture-secret" in part for part in calls[1]))
        self.assertNotIn("--max-time", calls[0])
        self.assertIn("--speed-time", calls[0])

    def test_verified_stale_metadata_is_available_after_network_failure(self):
        client = Client(self.repo.directory)
        url = "https://example.test/metadata"
        path = client.directory / sha(url.encode())
        path.write_bytes(b'{"version":1}')
        atomic_json(path.with_suffix(".json"), {"sha256": sha(path.read_bytes()), "time": 0})
        with (
            patch.object(client, "fetch", side_effect=OSError("offline")),
            self.assertWarns(RuntimeWarning),
        ):
            self.assertEqual(client.metadata(url), {"version": 1})
        path.write_bytes(b'{"version":2}')
        with (
            patch.object(client, "fetch", side_effect=OSError("offline")),
            self.assertRaises(OSError),
        ):
            client.metadata(url)

    def test_archive_preflight_rejects_traversal_before_extracting(self):
        path = self.root / "bad.7z"
        path.write_bytes(b"not a zip")
        with patch(
            "optidx_desktop.downloads.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout="----------\nPath = ../escape\nSize = 3\n"
            ),
        ) as run:
            with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
                archive_files(path)
        self.assertEqual(run.call_count, 1)

    def test_solid_archive_extracts_all_members_once(self):
        import shutil

        program = next(
            (shutil.which(name) for name in ("7z", "7za", "7zz") if shutil.which(name)), None
        )
        if not program:
            self.skipTest("7-Zip is unavailable")
        source = self.root / "pack"
        source.mkdir()
        for name in ("one.fx", "two.fx", "three.fx"):
            (source / name).write_bytes(b"shader content")
        path = self.root / "pack.7z"
        subprocess.run(
            [program, "a", "-ms=on", str(path), "."], cwd=source, check=True, capture_output=True
        )
        with patch("optidx_desktop.downloads.subprocess.run", wraps=subprocess.run) as run:
            files = archive_files(path)
        self.assertEqual(len(files), 3)
        self.assertEqual(sum(call.args[0][1] == "x" for call in run.call_args_list), 1)

    def test_stable_identity_migrates_profiles_drafts_and_recovery(self):
        old = replace(self.game, id=game_id("Steam", self.target), store="Steam", app_id="123")
        self.repo.save_games([old])
        self.repo.save_preferences(old, {"mode": "renodx", "environment": {"USER_CHOICE": "keep"}})
        self.target.joinpath("dxgi.dll").write_bytes(b"original")
        assets.deploy(self.target, "config", {"recovery.json": b'{"keep":"exact bytes"}'})
        folder = snapshot(old, self.repo)
        atomic_json(
            self.repo.directory / "backups" / old.id / "baseline.json", {"snapshot": str(folder)}
        )
        atomic_json(self.repo.directory / "drafts.json", {old.id: {"prefix": "/unfinished"}})
        atomic_json(self.repo.directory / "workspace.json", {"selected": old.id})
        new = self.repo.games()[0]
        self.assertEqual(new.id, game_id("Steam", "123"))
        self.assertEqual(stable_game_id(replace(new, root="/moved")), new.id)
        self.assertTrue(self.repo.preferences(new)["components"]["renodx"])
        self.assertEqual(read_json(self.repo.directory / "workspace.json")["selected"], new.id)
        self.assertIn(new.id, read_json(self.repo.directory / "drafts.json"))
        baseline = read_json(self.repo.directory / "backups" / new.id / "baseline.json")
        self.assertTrue(Path(baseline["snapshot"]).is_dir())
        self.assertEqual(
            (Path(baseline["snapshot"]) / "files/recovery.json").read_bytes(),
            b'{"keep":"exact bytes"}',
        )
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.repo.games(), [new])

    def test_games_are_immutable_and_jobs_capture_nested_preferences(self):
        with self.assertRaises(FrozenInstanceError):
            self.game.executable = "another.exe"
        preferences = {"environment": {"CHOICE": "original"}}
        job = Job(self.game, "install", preferences)
        preferences["environment"]["CHOICE"] = "changed"
        self.assertEqual(job.preferences["environment"]["CHOICE"], "original")

    def test_backend_scope_restores_environment_and_working_directory(self):
        before = Path.cwd(), dict(os.environ)
        with self.assertRaises(RuntimeError), backend_scope(self.target):
            os.environ["OPTIDX_FIXTURE_ONLY"] = "temporary"
            raise RuntimeError("failure")
        self.assertEqual((Path.cwd(), dict(os.environ)), before)

    def test_optional_update_failure_rolls_back_only_its_group(self):
        for group in ("shader:bad", "shader:good"):
            assets.deploy(self.target, group, {group.split(":")[1] + ".fx": b"old"})

        def update(game, action, preferences, repository, options):
            group = options["group"]
            assets.deploy(game.target, group, {group.split(":")[1] + ".fx": b"new"})
            if group == "shader:bad":
                raise OSError("dead shader URL")

        with (
            patch("optidx_desktop.features.run_feature", side_effect=update),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            run_job({"game": self.game.to_dict(), "action": "update"}, self.repo.directory)
        self.assertEqual((self.target / "bad.fx").read_bytes(), b"old")
        self.assertEqual((self.target / "good.fx").read_bytes(), b"new")
        final = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(final["data"]["completed"], ["shader:good"])
        self.assertIn("dead shader URL", final["data"]["errors"][0])

    def test_sigterm_during_write_rolls_back_before_exit(self):
        (self.target / "dxgi.dll").write_bytes(b"original")
        code = """
import os, signal, sys
from pathlib import Path
from unittest.mock import patch
from optidx_desktop.worker import run_job, JobInterrupted
import json
request = json.loads(sys.argv[1])
def broken(game, *args):
    (game.target / 'dxgi.dll').write_bytes(b'partial')
    os.kill(os.getpid(), signal.SIGTERM)
try:
    with patch('optidx_desktop.worker.execute_backend', side_effect=broken):
        run_job(request, sys.argv[2])
except JobInterrupted:
    raise SystemExit(9)
"""
        request = {"game": self.game.to_dict(), "action": "install"}
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, json.dumps(request), str(self.repo.directory)],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual((self.target / "dxgi.dll").read_bytes(), b"original")

    def test_backup_payloads_share_content_without_sharing_live_game_files(self):
        original = self.target / "dxgi.dll"
        original.write_bytes(b"original")
        first, second = snapshot(self.game, self.repo), snapshot(self.game, self.repo)
        one, two = first / "files/dxgi.dll", second / "files/dxgi.dll"
        self.assertEqual(one.stat().st_ino, two.stat().st_ino)
        self.assertNotEqual(one.stat().st_ino, original.stat().st_ino)
        original.write_bytes(b"changed")
        rollback_snapshot(self.target, first)
        self.assertEqual(original.read_bytes(), b"original")
        finish_snapshots(self.game, self.repo, (first, second))
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_history_retention_keeps_recovery_and_redaction_is_recursive(self):
        logs = self.repo.directory / "logs"
        logs.mkdir(parents=True)
        records = []
        for index, result in enumerate(("Interrupted", "Completed", "Completed", "Running")):
            path = logs / f"{index}.log"
            path.write_text("output")
            records.append({"result": result, "log": str(path)})
        retained = trim_history(records, self.repo.directory, 1)
        self.assertEqual(
            [record["result"] for record in retained], ["Interrupted", "Completed", "Running"]
        )
        self.assertFalse((logs / "1.log").exists())
        self.assertEqual(
            redact(
                {
                    "environment": {"API_TOKEN": "secret", "normal": "visible"},
                    "nested": [{"password": "hidden"}],
                }
            ),
            {
                "environment": {"API_TOKEN": "[REDACTED]", "normal": "visible"},
                "nested": [{"password": "[REDACTED]"}],
            },
        )
