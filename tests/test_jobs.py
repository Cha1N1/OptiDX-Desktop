import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import contextlib
import fcntl
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from optidx_desktop.errors import GameBusy
from optidx_desktop.history import trim_history
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository
from optidx_desktop.worker import run_job

ROOT = Path(__file__).resolve().parents[1]


class JobProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name) / "game"
        self.target.mkdir()
        (self.target / "game.exe").write_bytes(b"MZ")
        self.game = manual_game(self.target / "game.exe", "Game")
        self.repo = Repository(Path(self.temp.name) / "data")

    def tearDown(self):
        self.temp.cleanup()

    def test_cancelled_worker_rolls_back_and_reports_structured_result(self):
        (self.target / "dxgi.dll").write_bytes(b"original")
        code = """
import sys, time
from unittest.mock import patch
from optidx_desktop.worker import main
def slow(game, *args):
    (game.target / 'dxgi.dll').write_bytes(b'partial')
    print('{"event": "ready"}', file=sys.__stdout__, flush=True)
    time.sleep(30)
with patch('optidx_desktop.worker.execute_backend', side_effect=slow):
    sys.argv = ['worker', '--data-dir', sys.argv[1]]
    raise SystemExit(main())
"""
        request = json.dumps({"game": self.game.to_dict(), "action": "install"})
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", code, str(self.repo.directory)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=ROOT,
        )
        process.stdin.write(request)
        process.stdin.close()
        events = []
        for line in process.stdout:
            events.append(json.loads(line))
            if events[-1]["event"] == "ready":
                process.terminate()
        process.wait(timeout=20)
        process.stdout.close()
        self.assertEqual(process.returncode, 1)
        recovery = [e for e in events if e["event"] == "recovery"]
        self.assertEqual(recovery[0]["state"], "rolled_back")
        result = events[-1]
        self.assertEqual(result["event"], "result")
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["error_type"], "JobInterrupted")
        self.assertEqual((self.target / "dxgi.dll").read_bytes(), b"original")

    def test_busy_game_lock_reports_a_clear_error(self):
        key = hashlib.sha256(str(self.target.resolve()).encode()).hexdigest()
        locks = self.repo.directory / "locks"
        locks.mkdir(parents=True)
        with (locks / (key + ".lock")).open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaisesRegex(GameBusy, "Another OptiDX operation"):
                with contextlib.redirect_stdout(io.StringIO()):
                    run_job({"game": self.game.to_dict(), "action": "install"}, self.repo.directory)

    def test_structured_recovery_state_is_protected_regardless_of_wording(self):
        logs = self.repo.directory / "logs"
        logs.mkdir(parents=True)
        records = []
        for index, state in enumerate(("manual", None, None)):
            path = logs / f"{index}.log"
            path.write_text("output")
            record = {"result": "Failed: reworded message", "log": str(path)}
            if state:
                record["recovery_state"] = state
            records.append(record)
        retained = trim_history(records, self.repo.directory, 1)
        self.assertEqual(len(retained), 2)
        self.assertEqual(retained[0].get("recovery_state"), "manual")


class TokenArgumentTests(unittest.TestCase):
    def test_github_token_is_sent_on_stdin_not_in_arguments(self):
        from optidx_desktop.downloads import Client

        calls = []

        def fake_run(command, **options):
            calls.append((command, options))
            Path(command[command.index("-o") + 1]).write_bytes(b"[]")
            return subprocess.CompletedProcess(command, 0, "", "")

        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"GITHUB_TOKEN": "secret-token"}),
            patch("optidx_desktop.downloads.subprocess.run", side_effect=fake_run),
        ):
            Client(temp).fetch("https://api.github.com/repos/a/b/releases")
            Client(temp).fetch("https://example.com/file.zip")
        (api_command, api_options), (other_command, other_options) = calls
        self.assertNotIn("secret-token", " ".join(api_command))
        self.assertIn("Authorization: Bearer secret-token", api_options["input"])
        self.assertEqual(other_options["input"], "")

    def test_curl_reads_header_from_stdin_config(self):
        import http.server
        import threading

        seen = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            result = subprocess.run(
                ["curl", "--config", "-", "-fsS", f"http://127.0.0.1:{server.server_port}/"],
                input='header = "Authorization: Bearer secret-token"\n',
                capture_output=True,
                text=True,
                timeout=10,
            )
        finally:
            thread.join(10)
            server.server_close()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(seen["auth"], "Bearer secret-token")


class CancelButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_terminates_and_history_records_rollback(self):
        from optidx_desktop.app import MainWindow

        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(Repository(Path(temp) / "data"), auto_scan=False)
            try:
                self.assertFalse(window.stop_job_button.isEnabled())
                process = MagicMock()
                window.process = process
                window.job_log = io.StringIO()
                window.job_callback = None
                window.current_history = {
                    "game": "Game",
                    "action": "install",
                    "result": "Running",
                    "started": time.time(),
                }
                window.history.append(window.current_history)
                window.refresh_actions()
                self.assertTrue(window.stop_job_button.isEnabled())
                window.cancel_current_job(confirm=False)
                process.terminate.assert_called_once()
                self.assertFalse(window.stop_job_button.isEnabled())
                window.current_history.update(recovery_state="rolled_back")
                window.result = {"event": "result", "ok": False, "cancelled": True}
                with (
                    patch.object(window, "read_stdout"),
                    patch.object(window, "read_stderr"),
                    patch.object(window, "start_next"),
                ):
                    window.job_finished(1)
                self.assertEqual(window.history[-1]["result"], "Cancelled: changes rolled back")
                self.assertIsNone(window.process)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


class DetachedLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_running_game_survives_window_close_and_is_tracked_after_restart(self):
        from PySide6.QtGui import QCloseEvent
        from helpers import wait_until
        from optidx_desktop.app import MainWindow

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "game"
            target.mkdir()
            (target / "game.exe").write_bytes(b"MZ")
            game = manual_game(target / "game.exe", "Game")
            repo = Repository(Path(temp) / "data")
            repo.save_games([game])
            marker = Path(temp) / "finished"
            window = MainWindow(repo, auto_scan=False)
            window.start_game_process(
                game,
                sys.executable,
                [
                    "-c",
                    f"import time, pathlib; time.sleep(1.5); pathlib.Path({str(marker)!r}).touch()",
                ],
            )
            self.assertIn(game.id, window.launch_processes)
            event = QCloseEvent()
            window.closeEvent(event)
            self.assertTrue(event.isAccepted())
            window.deleteLater()
            self.app.processEvents()
            # A new window keeps the running indicator for the detached game.
            second = MainWindow(repo, auto_scan=False)
            try:
                self.assertIn(game.id, second.launch_processes)
                self.assertTrue(wait_until(lambda: marker.exists(), 8000))
                self.assertTrue(wait_until(lambda: not second.launch_processes, 6000))
                self.assertIn("exited", second.log.toPlainText())
            finally:
                second.close()
                second.deleteLater()
                self.app.processEvents()


class StorageAndAppUpdateTests(unittest.TestCase):
    def test_cache_cleanup_keeps_recent_and_protected_data(self):
        from optidx_desktop.usage import clean_download_caches, usage

        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"XDG_CACHE_HOME": str(Path(temp) / "cache")}),
        ):
            repo = Repository(Path(temp) / "data")
            downloads = repo.directory / "downloads"
            payloads = Path(temp) / "cache/optidx/payloads"
            for folder in (downloads, payloads, repo.directory / "backups/game"):
                folder.mkdir(parents=True)
            old, fresh = downloads / "old", payloads / "fresh"
            old.write_bytes(b"x" * 100)
            fresh.write_bytes(b"y" * 50)
            backup = repo.directory / "backups/game/original"
            backup.write_bytes(b"z" * 10)
            os.link(backup, repo.directory / "backups/game/linked")
            os.utime(old, (0, 0))
            sizes = {label: size for label, path, size, disposable in usage(repo)}
            self.assertEqual(sizes["Backups and verified originals"], 10)
            self.assertEqual(clean_download_caches(repo, 30), (1, 100))
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertEqual(clean_download_caches(repo, 0), (1, 50))
            self.assertTrue(backup.exists())

    def test_cache_cleanup_waits_for_running_jobs(self):
        from optidx_desktop.usage import clean_download_caches

        with tempfile.TemporaryDirectory() as temp:
            repo = Repository(Path(temp) / "data")
            (repo.directory / "locks").mkdir(parents=True)
            (repo.directory / "downloads").mkdir()
            (repo.directory / "downloads/payload").write_bytes(b"x")
            with (repo.directory / "locks/job.lock").open("w") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                self.assertIsNone(clean_download_caches(repo, 0))
            self.assertTrue((repo.directory / "downloads/payload").exists())

    def test_app_update_reports_only_newer_stable_releases(self):
        from optidx_desktop.app_updates import UPDATE_INFORMATION, newer_release

        client = MagicMock()
        client.metadata.return_value = {
            "tag_name": "v0.4.0",
            "html_url": "https://github.com/Cha1N1/OptiDX-Desktop/releases/tag/v0.4.0",
        }
        self.assertEqual(
            newer_release("/unused", "0.3.6", client),
            {"version": "0.4.0", "url": client.metadata.return_value["html_url"]},
        )
        self.assertIsNone(newer_release("/unused", "0.4.0", client))
        self.assertIsNone(newer_release("/unused", "0.10.0", client))
        client.metadata.return_value = {"tag_name": "v9.0", "prerelease": True}
        self.assertIsNone(newer_release("/unused", "0.3.6", client))
        client.metadata.return_value = {"tag_name": "v9.0", "html_url": "https://evil.test/"}
        self.assertTrue(
            newer_release("/unused", "0.3.6", client)["url"].startswith(
                "https://github.com/Cha1N1/OptiDX-Desktop/"
            )
        )
        build = (ROOT / "packaging/build_appimage.py").read_text()
        self.assertIn(UPDATE_INFORMATION.split("|", 1)[1], build.replace('"\n    "', ""))


if __name__ == "__main__":
    unittest.main()
