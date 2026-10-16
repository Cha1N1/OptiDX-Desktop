import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog, QListWidget
from optidx_desktop.app import MainWindow
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository, atomic_json, read_json
from optidx_desktop.backups import snapshot, verify_snapshot, restore_snapshot_files


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        target = self.root / 'game'
        target.mkdir()
        exe = target / 'game.exe'
        exe.write_bytes(b'exe')
        self.game = manual_game(exe, 'Zebra')
        other = self.root / 'other'
        other.mkdir()
        (other / 'other.exe').write_bytes(b'exe')
        self.other = manual_game(other / 'other.exe', 'Alpha')
        self.repo = Repository(self.root / 'data')
        self.repo.save_games([self.game, self.other])
        self.window = MainWindow(self.repo, auto_scan=False)
        self.select(self.game)

    def select(self, game):
        for row in range(self.window.list.count()):
            if self.window.list.item(row).data(256) == game.id:
                self.window.list.setCurrentRow(row)
                return

    def tearDown(self):
        self.window.queue.clear()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_invalid_draft_survives_switch_filter_and_restart(self):
        self.window.features.environment.setPlainText('{unfinished')
        self.window.prefix.setText('/draft/prefix')
        self.select(self.other)
        self.assertNotEqual(self.window.prefix.text(), '/draft/prefix')
        self.select(self.game)
        self.assertEqual(self.window.features.environment.toPlainText(), '{unfinished')
        self.window.filter.setCurrentText('Steam')
        self.window.filter.setCurrentText('All games')
        self.select(self.game)
        self.assertEqual(self.window.prefix.text(), '/draft/prefix')
        self.window.save_workspace()
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertEqual(another.selected.id, self.game.id)
            self.assertEqual(another.features.environment.toPlainText(), '{unfinished')
        finally:
            another.close(); another.deleteLater()
        self.assertFalse((self.repo.directory / 'profiles' / (self.game.id + '.json')).exists())
        self.window.revert_draft()
        self.assertNotEqual(self.window.features.environment.toPlainText(), '{unfinished')

    def test_save_clears_draft_and_dependencies_explain_block(self):
        for box in self.window.components.values(): box.setChecked(False)
        self.window.components['helixsr'].setChecked(True)
        self.assertFalse(self.window.install_button.isEnabled())
        self.assertIn('OptiScaler', self.window.action_hint.text())
        dll = self.root / 'helixsr.dll'
        dll.write_bytes(b'fixture')
        self.window.helixsr_dll.setText(str(dll))
        self.window.components['optiscaler'].setChecked(True)
        self.assertTrue(self.window.install_button.isEnabled())
        self.window.stash_draft()
        self.window.save_profile()
        self.assertNotIn(self.game.id, read_json(self.repo.directory / 'drafts.json', {}))

    def test_helix_picker_excludes_cyboman_and_path_survives_switch(self):
        self.window.components['amd_fsr'].setChecked(False)
        self.window.components['helixsr'].setChecked(True)
        self.assertFalse(self.window.components['amd_fsr'].isEnabled())
        self.assertIn('untick HelixSR', self.window.component_status_labels['amd_fsr'].text())
        self.assertLessEqual(self.window.helixsr_dll.maximumWidth(), 200)
        self.assertFalse(self.window.helixsr_picker.isHidden())
        self.window.helixsr_dll.setText('/build/HelixSR/custom.dll')
        self.select(self.other)
        self.select(self.game)
        self.assertTrue(self.window.components['helixsr'].isChecked())
        self.assertEqual(self.window.helixsr_dll.text(), '/build/HelixSR/custom.dll')
        self.window.components['helixsr'].setChecked(False)
        self.window.components['amd_fsr'].setChecked(True)
        self.assertFalse(self.window.components['helixsr'].isEnabled())
        self.assertTrue(self.window.helixsr_picker.isHidden())

    def test_startup_restores_filtered_library_and_draft(self):
        self.repo.save_preferences(self.game, {'favourite': True})
        atomic_json(self.repo.directory / 'workspace.json', {
            'search': 'Zebra', 'filter': 'Favourites', 'sort': 'Updates first',
            'selected': self.game.id, 'page': 'Recovery'})
        atomic_json(self.repo.directory / 'drafts.json', {
            self.game.id: {'prefix': '/saved/draft/prefix'}})
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertEqual(another.list.count(), 1)
            self.assertEqual(another.selected.id, self.game.id)
            self.assertEqual(another.prefix.text(), '/saved/draft/prefix')
            self.assertEqual(another.tabs.tabText(another.tabs.currentIndex()), 'Recovery')
            another.search.clear()
            another.filter.setCurrentText('All games')
            self.assertEqual(another.list.count(), 2)
        finally:
            another.close()
            another.deleteLater()

    def test_helix_picker_does_not_stretch_cyboman_or_delay_dlss(self):
        self.window.resize(1800, 1000)
        self.window.show()
        self.window.components['amd_fsr'].setChecked(False)
        self.app.processEvents()
        cyboman = self.window.components['amd_fsr'].parentWidget()
        dlss = self.window.components['dlss_enabler'].parentWidget()
        before = cyboman.height()
        self.window.components['helixsr'].setChecked(True)
        self.app.processEvents()
        self.assertLessEqual(cyboman.height(), before + 25)
        self.assertLessEqual(cyboman.parentWidget().width(), 720)
        self.assertLess(dlss.y(), self.window.components['helixsr'].parentWidget().geometry().bottom())

    def test_individual_queue_removal_does_not_change_active_job(self):
        self.window.start_next = lambda: None
        self.window.enqueue('install')
        self.select(self.other)
        self.window.enqueue('install')
        self.window.poll_workflow()
        self.window.pending_jobs.setCurrentRow(0)
        self.window.remove_pending_job()
        self.assertEqual(len(self.window.queue), 1)
        self.assertEqual(self.window.queue[0][0].id, self.other.id)

    def test_sort_and_workspace_restore(self):
        self.repo.save_preferences(self.game, {'display_name': 'Aardvark'})
        self.window.populate()
        self.assertIn('Aardvark', self.window.list.item(0).text())
        self.select(self.game)
        self.window.navigation.setCurrentRow(self.window.navigation.count() - 1)
        self.window.save_workspace()
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertEqual(another.navigation.currentItem().text(), 'Recovery')
            self.assertEqual(another.selected.id, self.game.id)
        finally:
            another.close(); another.deleteLater()

    def test_bulk_preview_cancel_and_unchecked_games_do_not_queue(self):
        (self.game.target / '.optidx-files').write_text('')
        self.window.start_next = lambda: None
        with patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            self.window.batch_update()
        self.assertFalse(self.window.queue)
        def accept(dialog):
            listing = dialog.findChild(QListWidget)
            self.assertIn('Skipped: No managed installation', listing.item(0).text())
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog, 'exec', accept):
            self.window.batch_update()
        self.assertEqual([q[0].id for q in self.window.queue], [self.game.id])

    def test_backup_verification_rejects_corruption_other_target_and_case_collision(self):
        dll = self.game.target / 'dxgi.dll'
        dll.write_bytes(b'original')
        folder = snapshot(self.game, self.repo)
        verify_snapshot(folder, self.game)
        with self.assertRaises(ValueError): verify_snapshot(folder, self.other)
        dll.unlink()
        (self.game.target / 'DXGI.dll').write_bytes(b'new')
        with self.assertRaises(ValueError): verify_snapshot(folder, self.game)
        (self.game.target / 'DXGI.dll').unlink()
        (folder / 'files/dxgi.dll').write_bytes(b'corrupt')
        with self.assertRaises(ValueError): restore_snapshot_files(folder, self.game)
        self.assertFalse(dll.exists())

    def test_restore_worker_preserves_new_files_and_takes_recovery_snapshot(self):
        from optidx_desktop.worker import run_job
        dll = self.game.target / 'dxgi.dll'
        dll.write_bytes(b'old')
        folder = snapshot(self.game, self.repo)
        dll.write_bytes(b'new')
        unrelated = self.game.target / 'custom.addon64'
        unrelated.write_bytes(b'user')
        run_job({'game': self.game.to_dict(), 'action': 'restore_snapshot', 'options': {'snapshot': str(folder)}}, self.repo.directory)
        self.assertEqual(dll.read_bytes(), b'old')
        self.assertEqual(unrelated.read_bytes(), b'user')
        retained = list((self.repo.directory / 'backups' / self.game.id).glob('*/snapshot.json'))
        self.assertEqual(len(retained), 2)
        self.assertTrue(any((p.parent / 'files/dxgi.dll').read_bytes() == b'new' for p in retained))

    def test_restore_refuses_to_orphan_newer_owned_files(self):
        dll = self.game.target / 'dxgi.dll'
        dll.write_bytes(b'old')
        folder = snapshot(self.game, self.repo)
        (self.game.target / 'new.addon64').write_bytes(b'managed')
        atomic_json(self.game.target / '.optidx-desktop-assets.json', {
            'version': 1, 'groups': {'new': {'files': {'new.addon64': {}}, 'metadata': {}}}})
        with self.assertRaisesRegex(ValueError, 'ownership of newer managed files'):
            restore_snapshot_files(folder, self.game)
        self.assertTrue((self.game.target / 'new.addon64').exists())

    def test_restore_refuses_newer_journal_even_when_files_overlap(self):
        dll = self.game.target / 'dxgi.dll'
        dll.write_bytes(b'original')
        folder = snapshot(self.game, self.repo)
        dll.write_bytes(b'managed')
        (self.game.target / '.optidx-files').write_text('dxgi.dll\n')
        with self.assertRaisesRegex(ValueError, 'ownership of newer managed files'):
            restore_snapshot_files(folder, self.game)
        self.assertEqual(dll.read_bytes(), b'managed')

    def test_fsr_status_and_log_open_use_existing_files(self):
        folder = self.game.target / 'OptiScaler'
        folder.mkdir()
        (folder / 'amd_fidelityfx_upscaler_dx12.dll').write_bytes(b'fsr')
        self.window.refresh_workflow()
        self.assertIn('Detected', self.window.component_status_labels['amd_fsr'].text())
        log = self.root / 'operation.log'
        log.write_text('output')
        with patch('optidx_desktop.runtime.open_url') as opened:
            self.window.open_history_path(str(log))
        self.assertTrue(opened.called)
        self.assertTrue(log.is_file())

    def test_interrupted_history_remains_inspectable_after_restart(self):
        atomic_json(self.repo.directory / 'job-history.json', [{
            'game_id': self.game.id, 'game': self.game.title, 'action': 'install',
            'started': 100, 'result': 'Running', 'log': '/tmp/example.log', 'backups': []}])
        another = MainWindow(self.repo, auto_scan=False)
        try:
            self.assertIn('Interrupted', another.jobs.item(0).text())
            self.assertIn('/tmp/example.log', another.job_details.toPlainText())
        finally:
            another.close(); another.deleteLater()

    def test_restore_worker_rolls_back_write_failure(self):
        from optidx_desktop.worker import run_job
        dll = self.game.target / 'dxgi.dll'
        dll.write_bytes(b'old')
        folder = snapshot(self.game, self.repo)
        dll.write_bytes(b'new')
        def fail_restore(folder, game):
            dll.write_bytes(b'partial')
            raise OSError('simulated restore failure')
        with patch('optidx_desktop.backups.restore_snapshot_files', fail_restore):
            with self.assertRaisesRegex(OSError, 'simulated restore failure'):
                run_job({'game': self.game.to_dict(), 'action': 'restore_snapshot', 'options': {'snapshot': str(folder)}}, self.repo.directory)
        self.assertEqual(dll.read_bytes(), b'new')
