"""Queued management jobs: worker processes, structured events, cancellation."""

import codecs
from .models import Job
import json
from pathlib import Path
import re

from PySide6.QtCore import (
    QProcess,
    QTimer,
)
from PySide6.QtWidgets import (
    QMessageBox,
)

from .runtime import python_executable


class JobRunnerMixin:
    def enqueue(self, action):
        if not self.selected:
            return
        if self.save_profile() is False:
            return
        preferences = self.saved_preferences(self.selected)
        if preferences is None:
            return
        self.queue.append(Job(self.selected, action, preferences))
        self.start_next()

    def saved_preferences(self, game):
        """Strict profile read for queued jobs; reports instead of raising in Qt slots."""
        try:
            return self.repository.preferences(game)
        except (OSError, ValueError) as error:
            self.report_error(f"{game.title}: {error}")
            return None

    def enqueue_feature(self, action, options=None, callback=None, game=None):
        from .models import Game

        if action in {"refresh_catalogs", "import_asset", "import_url", "prepare_template"}:
            game = Game("global", "Library", "Global", str(self.repository.directory))
        else:
            game = game or self.selected
        if not game:
            return
        if game == self.selected and self.save_profile() is False:
            return
        preferences = self.saved_preferences(game)
        if preferences is None:
            return
        self.queue.append(Job(game, action, preferences, options or {}, callback))
        self.start_next()

    def start_next(self):
        self.refresh_pending_jobs()
        self.cancel_button.setEnabled(bool(self.queue))
        if self.process is not None or not self.queue:
            return
        job = self.queue.pop(0)
        self.refresh_pending_jobs()
        game, action, preferences, options = job.game, job.action, job.preferences, job.options
        self.job_callback = job.callback
        self.active_game = game
        self.result = None
        self.stdout_buffer = ""
        self.stdout_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.stderr_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.log.appendPlainText(f"\n{action.upper()} · {game.title}")
        self.tabs.setCurrentWidget(self.log)
        self.queue_label.setText(f"{action.title()}: {game.title} · {len(self.queue)} queued")
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        process.readyReadStandardOutput.connect(self.read_stdout)
        process.readyReadStandardError.connect(self.read_stderr)
        process.finished.connect(self.job_finished)
        process.errorOccurred.connect(self.process_error)
        request = json.dumps(
            {
                "game": game.to_dict(),
                "action": action,
                "preferences": preferences,
                "options": options,
            }
        )
        log_dir = self.repository.directory / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        import time

        log_path = log_dir / f"{time.time_ns()}-{game.id}.log"
        self.job_log = log_path.open("w+", encoding="utf-8")
        self.current_history = {
            "game_id": game.id,
            "game": game.title,
            "action": action,
            "started": time.time(),
            "result": "Running",
            "log": str(log_path),
            "backups": [],
            "recovery": "No recovery reported",
        }
        self.history.append(self.current_history)
        self.refresh_history()
        process.start(
            python_executable(),
            [
                "-B",
                "-u",
                "-m",
                "optidx_desktop.worker",
                "--data-dir",
                str(self.repository.directory),
            ],
        )
        # Send the request privately instead of exposing it in the process arguments.
        process.write(request.encode("utf-8"))
        process.closeWriteChannel()
        self.refresh_actions()

    def read_stdout(self):
        if not self.process:
            return
        self.stdout_buffer += self.stdout_decoder.decode(
            bytes(self.process.readAllStandardOutput())
        )
        while "\n" in self.stdout_buffer:
            line, self.stdout_buffer = self.stdout_buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                self.log.appendPlainText(line)
                continue
            if event["event"] == "progress":
                self.queue_label.setText(event["message"])
            elif event["event"] == "recovery":
                if self.current_history is not None:
                    self.current_history["recovery"] = event["message"]
                    self.current_history["recovery_state"] = event["state"]
            elif event["event"] == "backup":
                self.log.appendPlainText("Backup: " + event["path"])
                if self.current_history is not None:
                    self.current_history["backups"].append(event["path"])
            elif event["event"] == "result":
                self.result = event

    def read_stderr(self):
        if not self.process:
            return
        text = self.stderr_decoder.decode(bytes(self.process.readAllStandardError()))
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(text)
        from .history import write_log

        write_log(self.job_log, text)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.log.appendPlainText("Could not start the backend process")
            self.job_finished(1)

    def job_finished(self, code, status=None):
        if self.process is None:
            return
        self.read_stdout()
        self.read_stderr()
        ok = code == 0 and self.result and self.result.get("ok")
        result = self.result or {}
        if ok:
            message = "Completed"
        elif result.get("cancelled") or (self.cancel_requested and not result):
            message = "Cancelled: " + (
                "changes rolled back"
                if self.current_history
                and self.current_history.get("recovery_state") == "rolled_back"
                else result.get("error", "the worker stopped before reporting a result")
            )
        else:
            message = "Failed: " + result.get("error", f"Backend exited with code {code}")
        self.cancel_requested = False
        self.log.appendPlainText(message)
        self.job_log.write("\n" + message + "\n")
        self.job_log.close()
        self.queue_label.setText(message)
        if self.current_history is not None:
            import time

            self.current_history.update(result=message, finished=time.time())
            if result.get("error_type") == "ManualRecoveryRequired":
                self.current_history["recovery_state"] = "manual"
                self.current_history["recovery"] = message
            self.refresh_history()
        self.process.deleteLater()
        self.process = None
        callback = self.job_callback
        if ok and callback:
            try:
                callback(self.result.get("data"))
            except Exception as error:
                self.log.appendPlainText("Could not display job result: " + str(error))
        if ok and self.result.get("data") is not None:
            errors = (
                self.result["data"].get("errors", [])
                if isinstance(self.result["data"], dict)
                else []
            )
            for error in errors:
                self.log.appendPlainText(error)
        self.inspection_cache.clear()
        self.populate()
        self.show_details()
        self.refresh_actions()
        QTimer.singleShot(0, self.start_next)

    def cancel_current_job(self, confirm=True):
        """Ask the worker to stop; its signal handler rolls back through the snapshot."""
        if self.process is None or self.cancel_requested:
            return
        if confirm:
            answer = QMessageBox.question(
                self,
                "Cancel operation",
                "Stop the running operation? Files it already changed are restored from its "
                "snapshot. Queued jobs stay queued.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.cancel_requested = True
        self.queue_label.setText("Cancelling; rolling back changes…")
        self.stop_job_button.setEnabled(False)
        self.process.terminate()

    def clear_queue(self):
        self.queue.clear()
        self.refresh_pending_jobs()
        self.cancel_button.setEnabled(False)
        self.statusBar().showMessage("Queued jobs cleared; the current job will finish", 5000)
