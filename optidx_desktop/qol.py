"""Desktop workflow helpers; profile drafts never deploy game files."""

from datetime import datetime
import copy
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QByteArray, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .storage import atomic_json, read_json


def stamp(value):
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


class WorkflowMixin:
    def init_workflow(self):
        self.drafts = read_json(self.repository.directory / "drafts.json", {})
        self.clean_form = None
        self.loading_form = False
        self.history = read_json(self.repository.directory / "job-history.json", [])
        self.current_history = None
        # A process that died with the desktop must not look successful.
        for record in self.history:
            if record["result"] == "Running":
                record["result"] = "Interrupted; inspect log and backups before retrying"
                record["recovery_state"] = "interrupted"
        self.workspace = read_json(self.repository.directory / "workspace.json", {})

    def setup_workflow(self):
        from .app import button

        page = QWidget()
        layout = QVBoxLayout(page)
        self.jobs = QListWidget()
        self.jobs.currentRowChanged.connect(self.job_selected)
        layout.addWidget(self.jobs)
        self.job_details = QPlainTextEdit()
        self.job_details.setReadOnly(True)
        layout.addWidget(self.job_details)
        row = QHBoxLayout()
        row.addWidget(button("Open selected log", self.open_job_log))
        row.addWidget(button("Open selected backups", self.open_job_backup))
        layout.addLayout(row)
        self.pending_jobs = QListWidget()
        layout.addWidget(QLabel("Queued operations (the active operation always finishes)"))
        layout.addWidget(self.pending_jobs)
        layout.addWidget(button("Remove selected queued job", self.remove_pending_job))
        self.tabs.addTab(page, "Job history")
        self.navigation.addItem("Job history")
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel("Backups for this game. Restore copies recorded files only; newer files remain.")
        )
        self.backup_list = QListWidget()
        layout.addWidget(self.backup_list)
        self.backup_details = QPlainTextEdit()
        self.backup_details.setReadOnly(True)
        layout.addWidget(self.backup_details)
        self.backup_list.currentRowChanged.connect(self.describe_backup)
        layout.addWidget(button("Verify selected backup", self.verify_backup))
        layout.addWidget(button("Restore recorded files…", self.restore_backup))
        self.tabs.addTab(page, "Recovery")
        self.navigation.addItem("Recovery")
        for shortcut, callback in [
            ("Ctrl+F", self.search.setFocus),
            ("Ctrl+S", self.save_profile),
            ("Ctrl+R", self.scan),
        ]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        state = self.workspace
        # Restore all controls before inspecting games or loading a profile.
        controls = (self.search, self.filter, self.sort)
        blocked = [control.blockSignals(True) for control in controls]
        self.search.setText(state.get("search", ""))
        self.filter.setCurrentText(state.get("filter", "All games"))
        self.sort.setCurrentText(state.get("sort", "Display name"))
        for control, previous in zip(controls, blocked):
            control.blockSignals(previous)
        if state.get("geometry"):
            self.restoreGeometry(QByteArray.fromHex(state["geometry"].encode()))
        if state.get("splitter"):
            self.splitter.setSizes(state["splitter"])
        self.populate()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == state.get("selected"):
                self.list.setCurrentRow(i)
                break
        page_index = next(
            (i for i in range(self.tabs.count()) if self.tabs.tabText(i) == state.get("page")), 0
        )
        self.tabs.setCurrentIndex(page_index)
        self.workflow_timer = QTimer(self)
        self.workflow_timer.timeout.connect(self.poll_workflow)
        self.workflow_timer.setSingleShot(True)
        self.workflow_timer.setInterval(500)
        for page in self.profile_pages():
            for widget in page.controls():
                signal = (
                    widget.toggled
                    if isinstance(widget, QCheckBox)
                    else (
                        widget.currentTextChanged
                        if isinstance(widget, QComboBox)
                        else widget.textChanged
                    )
                )
                signal.connect(self.form_changed)
        self.features.shader_list.itemChanged.connect(self.form_changed)
        for index in range(self.navigation.count()):
            self.navigation.item(index).setToolTip(self.navigation.item(index).text())
        self.refresh_history()
        self.refresh_workflow()

    def profile_pages(self):
        from .pages import ProfilePage

        return self.findChildren(ProfilePage)

    def form_changed(self, *args):
        if not self.loading_form and hasattr(self, "workflow_timer"):
            self.workflow_timer.start()

    def capture_form(self):
        result = {}
        for page in self.profile_pages():
            result.update(page.collect())
        result["shaders"] = [
            self.features.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.features.shader_list.count())
            if self.features.shader_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        result["extra_sources"] = copy.deepcopy(self.features.extra_sources)
        return result

    def apply_draft(self, values):
        for page in self.profile_pages():
            page.load(values)
        self.features.load_shader_choices(values.get("shaders", []))
        self.features.extra_sources = copy.deepcopy(values.get("extra_sources", {}))
        self.features.refresh_upscaler_picker()

    def stash_draft(self, values=None):
        if self.loading_form or not self.selected or self.clean_form is None:
            return
        values = self.capture_form() if values is None else values
        if values != self.clean_form:
            self.drafts[self.selected.id] = values
        else:
            self.drafts.pop(self.selected.id, None)
        atomic_json(self.repository.directory / "drafts.json", self.drafts)

    def load_profile(self):
        from PySide6.QtCore import QSignalBlocker

        self.workflow_timer.stop() if hasattr(self, "workflow_timer") else None
        self.loading_form = True
        blockers = [
            QSignalBlocker(widget) for page in self.profile_pages() for widget in page.controls()
        ]
        blockers.append(QSignalBlocker(self.features.shader_list))
        try:
            self._load_profile()
            self.sync_upscaler_choices()
            self.clean_form = self.capture_form()
            if self.selected.id in self.drafts:
                self.apply_draft(self.drafts[self.selected.id])
                self.sync_upscaler_choices()
        finally:
            del blockers
            self.loading_form = False
        self.refresh_install_summary()
        self.refresh_actions()
        self.poll_workflow() if hasattr(self, "draft_label") else None

    def revert_draft(self):
        if not self.selected:
            return
        self.drafts.pop(self.selected.id, None)
        atomic_json(self.repository.directory / "drafts.json", self.drafts)
        self.load_profile()
        self.refresh_workflow()

    def poll_workflow(self):
        values = self.capture_form()
        dirty = bool(self.selected) and values != self.clean_form
        self.draft_label.setText("Unsaved changes · draft retained" if dirty else "Profile saved")
        if self.selected and (
            self.drafts.get(self.selected.id) != values
            if dirty
            else self.selected.id in self.drafts
        ):
            self.stash_draft(values)
        self.refresh_workflow_status()
        self.refresh_pending_jobs()

    def refresh_pending_jobs(self):
        if not hasattr(self, "pending_jobs"):
            return
        pending_row = self.pending_jobs.currentRow()
        self.pending_jobs.clear()
        self.pending_jobs.addItems([f"{job.action}: {job.game.title}" for job in self.queue])
        if self.queue:
            self.pending_jobs.setCurrentRow(max(0, min(pending_row, len(self.queue) - 1)))

    def save_workspace(self):
        self.stash_draft()
        atomic_json(
            self.repository.directory / "workspace.json",
            {
                "geometry": bytes(self.saveGeometry().toHex()).decode(),
                "splitter": self.splitter.sizes(),
                "selected": self.selected.id if self.selected else None,
                "search": self.search.text(),
                "filter": self.filter.currentText(),
                "sort": self.sort.currentText(),
                "page": self.tabs.tabText(self.tabs.currentIndex()),
            },
        )

    def ordered_games(self, profiles=None, updates=None):
        if not hasattr(self, "sort"):
            return self.games
        if profiles is None or updates is None:
            from .status import game_status

            statuses = {game.id: game_status(game, self.repository) for game in self.games}
            profiles = {key: status.profile for key, status in statuses.items()}
            updates = {key: status.update for key, status in statuses.items()}

        def key(game):
            name = (profiles[game.id].get("display_name") or game.title).casefold()
            if self.sort.currentText() == "Recently managed":
                return (
                    -max(
                        (r["started"] for r in self.history if r["game_id"] == game.id), default=0
                    ),
                    name,
                )
            if self.sort.currentText() == "Updates first":
                return (
                    not updates[game.id].get("update_available"),
                    name,
                )
            return (name,)

        return sorted(self.games, key=key)

    def refresh_workflow_status(self):
        # Availability is computed by the Qt-free status model in refresh_actions.
        self.refresh_actions()

    def render_workflow_status(self):
        if not hasattr(self, "action_hint"):
            return
        states = self.action_state
        problems = self.current_problems
        info = self.inspection(self.selected) if self.selected else {}
        reason = states["install"].reason
        hints = [reason] if reason else []
        for key, label in (("update", "Update"), ("remove", "Removal"), ("launch", "Launch")):
            if not states[key].enabled:
                hints.append(f"{label} unavailable: {states[key].reason}")
        if not states["save"].enabled and self.selected:
            hints.append(states["save"].reason)
        self.action_hint.setText("\n".join(dict.fromkeys(hints)))
        self.install_button.setToolTip(reason or "Install the selected core components.")
        self.update_button.setToolTip(states["update"].reason or "Update the managed setup.")
        self.remove_button.setToolTip(
            states["remove"].reason or "Restore originals and remove managed files."
        )
        self.launch_button.setToolTip(
            states["launch"].reason or "Launch with the route shown above."
        )
        updates = self.current_status.update if self.current_status else {}
        available = {r["component"] for r in updates.get("components", []) if r.get("update")}
        from .components import COMPONENT_LABELS, COMPONENTS

        for key, box in self.components.items():
            statuses = [
                "Selected" if box.isChecked() else "Unselected",
                (
                    "Detected"
                    if info.get("components", {}).get(COMPONENTS[key].detected)
                    else "Not detected"
                ),
            ]
            if key in available:
                statuses.append("Update available")
            if key in {"renodx", "luma", "helixsr"} and any(
                p.startswith(COMPONENT_LABELS[key] + " requires") for p in problems
            ):
                statuses.append("Dependency missing")
            if key in {"helixsr", "amd_fsr"}:
                opposite = "amd_fsr" if key == "helixsr" else "helixsr"
                if self.components[opposite].isChecked():
                    label = "HelixSR" if opposite == "helixsr" else "Cyboman FSR"
                    statuses = [f"Unavailable · untick {label} to switch"]
            self.component_status_labels[key].setText(" · ".join(statuses))
        game = self.selected
        if game:
            route = (
                f'{game.launcher_kind or "default"} {game.store}'
                if game.launch_uri
                else "Bottles CLI" if game.store == "Bottles" else "saved manual runner"
            )
            text = f"Launches through {route}."
            from .status import launchable

            if not launchable(game, self.current_status.profile):
                text = "Manual launch: configure a runner in Launch options."
            if game.launch_uri:
                text += " Managed environment/HDR settings require the copied profile wrapper in your launcher."
            self.launch_hint.setText(text)
        else:
            self.launch_hint.clear()

    def refresh_workflow(self):
        self.refresh_workflow_status()
        if not hasattr(self, "backup_list"):
            return
        self.backup_list.clear()
        if self.selected:
            for folder in sorted(
                (self.repository.directory / "backups" / self.selected.id).glob("*"), reverse=True
            ):
                if not folder.name.isdigit():
                    continue
                saved = read_json(folder / "snapshot.json", {})
                if not saved:
                    continue
                item = QListWidgetItem(
                    f'{stamp(folder.stat().st_mtime)} · {saved.get("action", "Earlier operation")} · {Path(saved["target"]).name} · {len(saved["files"])} files'
                )
                item.setData(Qt.ItemDataRole.UserRole, str(folder))
                self.backup_list.addItem(item)
        if self.backup_list.count():
            self.backup_list.setCurrentRow(0)
        else:
            self.backup_details.setPlainText("No backups recorded for this game.")

    def refresh_history(self):
        if not hasattr(self, "jobs"):
            return
        from .history import trim_history

        self.history = trim_history(self.history, self.repository.directory)
        selected = self.jobs.currentRow()
        self.jobs.clear()
        for record in reversed(self.history):
            self.jobs.addItem(
                f'{stamp(record["started"])} · {record["game"]} · {record["action"]} · {record["result"]}'
            )
        if self.jobs.count():
            self.jobs.setCurrentRow(max(0, selected))
        atomic_json(self.repository.directory / "job-history.json", self.history)

    def selected_job(self):
        row = self.jobs.currentRow()
        return list(reversed(self.history))[row] if row >= 0 else {}

    def job_selected(self, *args):
        record = self.selected_job()
        self.job_details.setPlainText("\n".join(f"{k}: {v}" for k, v in record.items()))

    def open_job_log(self):
        value = self.selected_job().get("log")
        if value:
            self.open_history_path(value)

    def open_job_backup(self):
        value = self.selected_job().get("backups", [])
        if value:
            self.open_history_path(value[0])

    def open_history_path(self, value):
        from .runtime import open_url

        path = Path(value)
        if not path.exists():
            self.report_error("This saved log or backup is no longer available: " + str(path))
            return
        open_url(QUrl.fromLocalFile(str(path.resolve())).toString())

    def remove_pending_job(self):
        row = self.pending_jobs.currentRow()
        if 0 <= row < len(self.queue):
            self.queue.pop(row)
            self.poll_workflow()
            self.cancel_button.setEnabled(bool(self.queue))

    def describe_backup(self, *args):
        item = self.backup_list.currentItem()
        if item:
            saved = read_json(Path(item.data(Qt.ItemDataRole.UserRole)) / "snapshot.json", {})
            self.backup_details.setPlainText(
                "Verification: not checked\nTarget: "
                + saved.get("target", "")
                + "\n"
                + "\n".join(r["path"] for r in saved.get("files", []))
            )

    def verify_backup(self):
        item = self.backup_list.currentItem()
        if not item or not self.selected:
            return None
        from .backups import verify_snapshot

        folder = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            saved = verify_snapshot(folder, self.selected)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.backup_details.setPlainText("Verification failed: " + str(error))
            return None
        self.backup_details.setPlainText(
            f'Verified {len(saved["files"])} files.\nTarget: {saved["target"]}\n'
            + "\n".join(r["path"] for r in saved["files"])
        )
        return folder, saved

    def restore_backup(self):
        if self.process:
            self.report_error("Wait for the current operation to finish.")
            return
        verified = self.verify_backup()
        if not verified:
            return
        folder, saved = verified
        answer = QMessageBox.question(
            self,
            "Restore recorded files",
            f'Restore {len(saved["files"])} recorded files to {saved["target"]}?\nExisting recorded files will be overwritten. Newer unrecorded files, external HDR configuration and saved profiles remain unchanged. A fresh recovery snapshot is taken first.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.enqueue_feature("restore_snapshot", {"snapshot": str(folder)})

    def batch_update(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Review bulk updates")
        dialog.resize(740, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel("Updates use saved profiles. Unsaved drafts are retained separately.")
        )
        choices = QListWidget()
        layout.addWidget(choices)
        candidates = []
        from .backend import COMPONENT_LABELS, selected_components

        from .status import game_status

        for game in self.ordered_games():
            status = game_status(game, self.repository)
            profile = status.profile
            reason = (
                "Drive unavailable"
                if not game.available
                else (
                    "Needs attention: " + status.errors[0]
                    if status.errors
                    else (
                        "No managed installation"
                        if not status.installed
                        else (
                            "Excluded in profile"
                            if not profile.get("include_updates", True)
                            else ""
                        )
                    )
                )
            )
            extras = status.group_names()
            try:
                components = [COMPONENT_LABELS[k] for k in selected_components(profile)]
            except ValueError as error:
                components, reason = [], reason or str(error)
            item = QListWidgetItem(
                game.title
                + "\n"
                + (
                    "Skipped: " + reason
                    if reason
                    else "Core: "
                    + ", ".join(components)
                    + "; installed groups: "
                    + ", ".join(extras)
                    + "; exclusions: "
                    + ", ".join(profile.get("exclude_components", []))
                )
            )
            if not reason:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                candidates.append((item, game, profile))
            choices.addItem(item)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Queue selected updates")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        from .models import Job

        for item, game, profile in candidates:
            if item.checkState() == Qt.CheckState.Checked:
                self.queue.append(Job(game, "update", profile))
        self.start_next()
