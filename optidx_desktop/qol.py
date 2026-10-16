"""Desktop workflow helpers; profile drafts never deploy game files."""
from datetime import datetime
import copy
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer, QByteArray, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QVBoxLayout, QWidget)

from .storage import atomic_json, read_json


def stamp(value):
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M')


class WorkflowMixin:
    def init_workflow(self):
        self.drafts = read_json(self.repository.directory / 'drafts.json', {})
        self.clean_form = None
        self.loading_form = False
        self.history = read_json(self.repository.directory / 'job-history.json', [])
        self.current_history = None
        # A process that died with the desktop must not look successful.
        for record in self.history:
            if record['result'] == 'Running':
                record['result'] = 'Interrupted; inspect log and backups before retrying'
        self.workspace = read_json(self.repository.directory / 'workspace.json', {})

    def setup_workflow(self):
        from .app import button
        self.sort = QComboBox()
        self.sort.addItems(['Display name', 'Recently managed', 'Updates first'])
        self.sort.currentTextChanged.connect(self.populate)
        self.search.parentWidget().layout().insertWidget(2, self.sort)
        old_hint = self.profile_footer.takeAt(0).widget()
        old_hint.hide()
        old_hint.deleteLater()
        self.draft_label = QLabel('Profile saved')
        self.draft_label.setWordWrap(True)
        self.draft_label.setToolTip('Save stores profile choices. Install / Apply changes game files. Drafts are retained automatically.')
        self.profile_footer.insertWidget(0, self.draft_label)
        self.profile_footer.addWidget(button('Revert draft', self.revert_draft))
        self.launch_hint = QLabel()
        self.launch_hint.setWordWrap(True)
        self.details_layout.insertWidget(1, self.launch_hint)
        self.game_heading.insertWidget(1, button('Copy launch command', self.features.copy_wrapper))
        self.action_hint = QLabel()
        self.action_hint.setWordWrap(True)
        self.installation_box.insertWidget(2, self.action_hint)
        page = QWidget()
        layout = QVBoxLayout(page)
        self.jobs = QListWidget()
        self.jobs.currentRowChanged.connect(self.job_selected)
        layout.addWidget(self.jobs)
        self.job_details = QPlainTextEdit()
        self.job_details.setReadOnly(True)
        layout.addWidget(self.job_details)
        row = QHBoxLayout()
        row.addWidget(button('Open selected log', self.open_job_log))
        row.addWidget(button('Open selected backups', self.open_job_backup))
        layout.addLayout(row)
        self.pending_jobs = QListWidget()
        layout.addWidget(QLabel('Queued operations (the active operation always finishes)'))
        layout.addWidget(self.pending_jobs)
        layout.addWidget(button('Remove selected queued job', self.remove_pending_job))
        self.tabs.addTab(page, 'Job history')
        self.navigation.addItem('Job history')
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel('Backups for this game. Restore copies recorded files only; newer files remain.'))
        self.backup_list = QListWidget()
        layout.addWidget(self.backup_list)
        self.backup_details = QPlainTextEdit()
        self.backup_details.setReadOnly(True)
        layout.addWidget(self.backup_details)
        self.backup_list.currentRowChanged.connect(self.describe_backup)
        layout.addWidget(button('Verify selected backup', self.verify_backup))
        layout.addWidget(button('Restore recorded files…', self.restore_backup))
        self.tabs.addTab(page, 'Recovery')
        self.navigation.addItem('Recovery')
        for shortcut, callback in [('Ctrl+F', self.search.setFocus), ('Ctrl+S', self.save_profile),
                                   ('Ctrl+R', self.scan)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        state = self.workspace
        # Restore all controls before inspecting games or loading a profile.
        controls = (self.search, self.filter, self.sort)
        blocked = [control.blockSignals(True) for control in controls]
        self.search.setText(state.get('search', ''))
        self.filter.setCurrentText(state.get('filter', 'All games'))
        self.sort.setCurrentText(state.get('sort', 'Display name'))
        for control, previous in zip(controls, blocked):
            control.blockSignals(previous)
        if state.get('geometry'):
            self.restoreGeometry(QByteArray.fromHex(state['geometry'].encode()))
        if state.get('splitter'):
            self.splitter.setSizes(state['splitter'])
        self.populate()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == state.get('selected'):
                self.list.setCurrentRow(i)
                break
        page_index = next((i for i in range(self.tabs.count()) if self.tabs.tabText(i) == state.get('page')), 0)
        self.tabs.setCurrentIndex(page_index)
        self.workflow_timer = QTimer(self)
        self.workflow_timer.timeout.connect(self.poll_workflow)
        self.workflow_timer.start(350)
        for index in range(self.navigation.count()):
            self.navigation.item(index).setToolTip(self.navigation.item(index).text())
        self.refresh_history()
        self.refresh_workflow()

    def form_widgets(self):
        return {**{'component:' + k: v for k, v in self.components.items()},
                **{'fg:' + k: v for k, v in self.fg.items()},
                **{'feature:' + k: v for k, v in self.features.fields.items()},
                **{'drs:' + k: v for k, v in self.features.drs.items()},
                'helixsr_dll': self.helixsr_dll, 'prune': self.prune_components, 'hdr': self.hdr, 'include': self.include_updates,
                'prefix': self.prefix, 'config': self.config_dir, 'environment': self.features.environment,
                'dll_kind': self.features.dll_kind, 'dll_version': self.features.dll_version,
                'dll_folder': self.features.dll_folder}

    def capture_form(self):
        result = {}
        for key, widget in self.form_widgets().items():
            if isinstance(widget, QCheckBox): value = widget.isChecked()
            elif isinstance(widget, QComboBox): value = widget.currentText()
            elif isinstance(widget, QPlainTextEdit): value = widget.toPlainText()
            else: value = widget.text()
            result[key] = value
        result['shaders'] = [self.features.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
                             for i in range(self.features.shader_list.count())
                             if self.features.shader_list.item(i).checkState() == Qt.CheckState.Checked]
        result['extra_sources'] = copy.deepcopy(self.features.extra_sources)
        return result

    def apply_draft(self, values):
        for key, widget in self.form_widgets().items():
            if key not in values: continue
            value = values[key]
            if isinstance(widget, QCheckBox): widget.setChecked(value)
            elif isinstance(widget, QComboBox): widget.setCurrentText(value)
            elif isinstance(widget, QPlainTextEdit): widget.setPlainText(value)
            else: widget.setText(value)
        self.features.load_shader_choices(values.get('shaders', []))
        self.features.extra_sources = copy.deepcopy(values.get('extra_sources', {}))

    def stash_draft(self):
        if self.loading_form or not self.selected or self.clean_form is None: return
        values = self.capture_form()
        if values != self.clean_form:
            self.drafts[self.selected.id] = values
        else:
            self.drafts.pop(self.selected.id, None)
        atomic_json(self.repository.directory / 'drafts.json', self.drafts)

    def load_profile(self):
        self.loading_form = True
        try:
            self._load_profile()
            self.clean_form = self.capture_form()
            if self.selected.id in self.drafts:
                self.apply_draft(self.drafts[self.selected.id])
        finally:
            self.loading_form = False

    def revert_draft(self):
        if not self.selected: return
        self.drafts.pop(self.selected.id, None)
        atomic_json(self.repository.directory / 'drafts.json', self.drafts)
        self.load_profile()
        self.refresh_workflow()

    def poll_workflow(self):
        dirty = bool(self.selected) and self.capture_form() != self.clean_form
        self.draft_label.setText('Unsaved changes · draft retained' if dirty else 'Profile saved')
        if dirty and self.drafts.get(self.selected.id) != self.capture_form(): self.stash_draft()
        pending_row = self.pending_jobs.currentRow()
        self.pending_jobs.clear()
        self.pending_jobs.addItems([f'{action}: {game.title}' for game, action, *_ in self.queue])
        if self.queue: self.pending_jobs.setCurrentRow(max(0, min(pending_row, len(self.queue) - 1)))

    def save_workspace(self):
        self.stash_draft()
        atomic_json(self.repository.directory / 'workspace.json', {
            'geometry': bytes(self.saveGeometry().toHex()).decode(), 'splitter': self.splitter.sizes(),
            'selected': self.selected.id if self.selected else None, 'search': self.search.text(),
            'filter': self.filter.currentText(), 'sort': self.sort.currentText(),
            'page': self.tabs.tabText(self.tabs.currentIndex())})

    def ordered_games(self):
        if not hasattr(self, 'sort'): return self.games
        def key(game):
            name = (self.repository.preferences(game).get('display_name') or game.title).casefold()
            if self.sort.currentText() == 'Recently managed':
                return (-max((r['started'] for r in self.history if r['game_id'] == game.id), default=0), name)
            if self.sort.currentText() == 'Updates first':
                return (not read_json(self.repository.directory / 'updates' / (game.id + '.json'), {}).get('update_available'), name)
            return (name,)
        return sorted(self.games, key=key)

    def dependency_problems(self, info):
        chosen = {k for k, w in self.components.items() if w.isChecked()}
        found = info.get('components', {})
        problems = []
        for component, dependency, label in [('renodx','reshade','ReShade'), ('luma','reshade','ReShade'), ('helixsr','optiscaler','OptiScaler')]:
            installed_label = {'reshade': 'ReShade', 'optiscaler': 'OptiScaler'}[dependency]
            if component in chosen and dependency not in chosen and not found.get(installed_label):
                problems.append(f'{self.components[component].text()} requires selected or installed {label}')
        if 'helixsr' in chosen and hasattr(self, 'helixsr_dll'):
            path = Path(self.helixsr_dll.text()).expanduser()
            if not self.helixsr_dll.text().strip() or not path.is_file():
                problems.append('Choose the locally built HelixSR FSR DLL')
        return problems

    def refresh_workflow_status(self):
        if not hasattr(self, 'action_hint'): return
        from .inspection import inspect_game
        info = inspect_game(self.selected) if self.selected else {}
        problems = self.dependency_problems(info)
        reason = ('Choose a game.' if not self.selected else 'Another operation is running.' if self.process else
                  'Select an existing executable in Installation → diagnostics.' if not info.get('executable_exists') else
                  '; '.join(problems))
        if not reason and not self.install_button.isEnabled(): reason = 'Select a component or use a supported graphics API.'
        hints = [reason] if reason else []
        if not self.update_button.isEnabled(): hints.append('Update unavailable: ' + (reason or 'no managed installation found.'))
        if not self.remove_button.isEnabled(): hints.append('Removal unavailable: ' + (reason or 'no managed installation found.'))
        if not self.launch_button.isEnabled(): hints.append('Launch unavailable: ' + (reason or 'configure a runner in Launch options.'))
        self.action_hint.setText('\n'.join(hints))
        self.install_button.setToolTip(reason or 'Install the selected core components.')
        if problems: self.install_button.setEnabled(False)
        self.update_button.setToolTip('Update the managed setup.' if self.update_button.isEnabled() else reason or 'No managed installation found.')
        self.remove_button.setToolTip('Restore originals and remove managed files.' if self.remove_button.isEnabled() else reason or 'No managed installation found.')
        self.launch_button.setToolTip('Launch with the route shown above.' if self.launch_button.isEnabled() else reason or 'Configure a runner in Launch options.')
        updates = read_json(self.repository.directory / 'updates' / ((self.selected.id if self.selected else '') + '.json'), {})
        available = {r['component'] for r in updates.get('components', []) if r.get('update')}
        from .backend import COMPONENT_LABELS
        for key, box in self.components.items():
            statuses = ['Selected' if box.isChecked() else 'Unselected', 'Detected' if info.get('components', {}).get('AMD FSR' if key == 'amd_fsr' else COMPONENT_LABELS[key]) else 'Not detected']
            if key in available: statuses.append('Update available')
            if key in {'renodx','luma','helixsr'} and any(box.text() in p for p in problems): statuses.append('Dependency missing')
            if key in {'helixsr', 'amd_fsr'}:
                opposite = 'amd_fsr' if key == 'helixsr' else 'helixsr'
                if self.components[opposite].isChecked():
                    label = 'HelixSR' if opposite == 'helixsr' else 'Cyboman FSR'
                    statuses = [f'Unavailable · untick {label} to switch']
            self.component_status_labels[key].setText(' · '.join(statuses))
        game = self.selected
        if game:
            route = f'{game.launcher_kind or "default"} {game.store}' if game.launch_uri else 'Bottles CLI' if game.store == 'Bottles' else 'saved manual runner'
            text = f'Launches through {route}.'
            if not game.launch_uri and game.store != 'Bottles' and not self.repository.preferences(game).get('runner_command'):
                text = 'Manual launch: configure a runner in Launch options.'
            if game.launch_uri: text += ' Managed environment/HDR settings require the copied profile wrapper in your launcher.'
            self.launch_hint.setText(text)
        else: self.launch_hint.clear()

    def refresh_workflow(self):
        self.refresh_workflow_status()
        if not hasattr(self, 'backup_list'): return
        self.backup_list.clear()
        if self.selected:
            for folder in sorted((self.repository.directory / 'backups' / self.selected.id).glob('*'), reverse=True):
                saved = read_json(folder / 'snapshot.json', {})
                if not saved: continue
                item = QListWidgetItem(f'{stamp(folder.stat().st_mtime)} · {saved.get("action", "Earlier operation")} · {Path(saved["target"]).name} · {len(saved["files"])} files')
                item.setData(Qt.ItemDataRole.UserRole, str(folder))
                self.backup_list.addItem(item)
        if self.backup_list.count(): self.backup_list.setCurrentRow(0)
        else: self.backup_details.setPlainText('No backups recorded for this game.')

    def refresh_history(self):
        if not hasattr(self, 'jobs'): return
        selected = self.jobs.currentRow()
        self.jobs.clear()
        for record in reversed(self.history):
            self.jobs.addItem(f'{stamp(record["started"])} · {record["game"]} · {record["action"]} · {record["result"]}')
        if self.jobs.count(): self.jobs.setCurrentRow(max(0, selected))
        atomic_json(self.repository.directory / 'job-history.json', self.history)

    def selected_job(self):
        row = self.jobs.currentRow()
        return list(reversed(self.history))[row] if row >= 0 else {}

    def job_selected(self, *args):
        record = self.selected_job()
        self.job_details.setPlainText('\n'.join(f'{k}: {v}' for k,v in record.items()))

    def open_job_log(self):
        value = self.selected_job().get('log')
        if value: self.open_history_path(value)

    def open_job_backup(self):
        value = self.selected_job().get('backups', [])
        if value: self.open_history_path(value[0])

    def open_history_path(self, value):
        from .runtime import open_url
        path = Path(value)
        if not path.exists():
            self.report_error('This saved log or backup is no longer available: ' + str(path))
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
            saved = read_json(Path(item.data(Qt.ItemDataRole.UserRole)) / 'snapshot.json', {})
            self.backup_details.setPlainText('Verification: not checked\nTarget: ' + saved.get('target', '') + '\n' + '\n'.join(r['path'] for r in saved.get('files', [])))

    def verify_backup(self):
        item = self.backup_list.currentItem()
        if not item or not self.selected: return None
        from .backups import verify_snapshot
        folder = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            saved = verify_snapshot(folder, self.selected)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.backup_details.setPlainText('Verification failed: ' + str(error))
            return None
        self.backup_details.setPlainText(f'Verified {len(saved["files"])} files.\nTarget: {saved["target"]}\n' + '\n'.join(r['path'] for r in saved['files']))
        return folder, saved

    def restore_backup(self):
        if self.process: self.report_error('Wait for the current operation to finish.'); return
        verified = self.verify_backup()
        if not verified: return
        folder, saved = verified
        answer = QMessageBox.question(self, 'Restore recorded files', f'Restore {len(saved["files"])} recorded files to {saved["target"]}?\nExisting recorded files will be overwritten. Newer unrecorded files, external HDR configuration and saved profiles remain unchanged. A fresh recovery snapshot is taken first.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.enqueue_feature('restore_snapshot', {'snapshot': str(folder)})

    def batch_update(self):
        from .assets import state
        dialog = QDialog(self)
        dialog.setWindowTitle('Review bulk updates')
        dialog.resize(740, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Updates use saved profiles. Unsaved drafts are retained separately.'))
        choices = QListWidget()
        layout.addWidget(choices)
        candidates = []
        from .backend import COMPONENT_LABELS, selected_components
        for game in self.ordered_games():
            profile = self.repository.preferences(game)
            installed = (game.target / '.optidx-files').is_file() or any(state(root)['groups'] for root in {game.target, Path(game.root)})
            reason = 'Drive unavailable' if not game.available else 'No managed installation' if not installed else 'Excluded in profile' if not profile.get('include_updates', True) else ''
            extras = sorted({group for root in {game.target, Path(game.root)} for group in state(root)['groups']}) if game.available else []
            components = [COMPONENT_LABELS[k] for k in selected_components(profile)]
            item = QListWidgetItem(game.title + '\n' + ('Skipped: ' + reason if reason else 'Core: ' + ', '.join(components) + '; installed groups: ' + ', '.join(extras) + '; exclusions: ' + ', '.join(profile.get('exclude_components', []))))
            if not reason:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                candidates.append((item, game, profile))
            choices.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Queue selected updates')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        from .models import Game
        for item, game, profile in candidates:
            if item.checkState() == Qt.CheckState.Checked:
                self.queue.append((Game.from_dict(game.to_dict()), 'update', profile, {}, None))
        self.start_next()
