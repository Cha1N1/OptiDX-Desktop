import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from optidx_desktop.app import MainWindow
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        binary = self.root / "Example Game/Binaries/Win64"
        binary.mkdir(parents=True)
        exe = binary / "Example-Win64-Shipping.exe"
        exe.write_bytes(b"exe")
        self.game = manual_game(exe, "Example Game")
        self.repository = Repository(self.root / "data")
        self.repository.save_games([self.game])
        self.window = MainWindow(self.repository, auto_scan=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_select_profile_and_filter_without_mutating_game(self):
        self.assertEqual(self.window.selected.title, "Example Game")
        self.assertTrue(self.window.install_button.isEnabled())
        self.assertFalse(self.window.components["helixsr"].isChecked())
        self.window.hdr.setChecked(False)
        self.window.save_profile()
        self.assertFalse(self.repository.preferences(self.game)["native_hdr"])
        self.window.filter.setCurrentText("Steam")
        self.assertEqual(self.window.list.count(), 0)
        self.assertEqual(len(list(self.game.target.iterdir())), 1)

    def test_real_qprocess_failure_updates_activity_and_finishes_cleanly(self):
        # Invalid manifest is rejected before snapshots or backend installation.
        (self.game.target / ".optidx-files").write_text("../../escape.dll\n")
        self.window.enqueue("update")
        deadline = time.monotonic() + 8
        while self.window.process is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.window.process)
        self.assertIn("Failed:", self.window.log.toPlainText())
        self.assertIn("Invalid managed path", self.window.log.toPlainText())
        self.assertFalse((self.root / "escape.dll").exists())

    def test_custom_component_choices_round_trip_without_forcing_a_preset(self):
        for box in self.window.components.values():
            box.setChecked(False)
        self.window.components["amd_fsr"].setChecked(True)
        self.window.components["reshade"].setChecked(True)
        self.window.prune_components.setChecked(True)
        self.window.save_profile()
        self.window.load_profile()
        selected = {key for key, box in self.window.components.items() if box.isChecked()}
        self.assertEqual(selected, {"amd_fsr", "reshade"})
        self.assertTrue(self.repository.preferences(self.game)["prune_components"])

    def test_install_action_is_scoped_to_its_page_and_reports_selection(self):
        from PySide6.QtCore import Qt, QPoint, QRect
        self.window.show()
        self.window.resize(930, 740)
        self.app.processEvents()
        self.assertTrue(self.window.tabs.rect().contains(QRect(
            self.window.install_button.mapTo(self.window.tabs, QPoint(0, 0)),
            self.window.install_button.size())))
        for box in self.window.components.values():
            box.setChecked(False)
        self.assertFalse(self.window.install_button.isEnabled())
        self.window.components["reshade"].setChecked(True)
        self.window.hdr.setChecked(False)
        summary = self.window.install_summary.text()
        self.assertIn("Will install: ReShade.", summary)
        self.assertNotIn("Also applies:", summary)
        self.assertTrue(self.window.install_button.isEnabled())
        # Choosing shader packs must not turn the component button into a
        # shader installer. Each click submits a distinct worker operation.
        self.window.features.shader_list.item(0).setCheckState(Qt.CheckState.Checked)
        self.window.start_next = lambda: None
        self.window.install_button.click()
        game, action, profile, options, callback = self.window.queue.pop()
        self.assertEqual(action, "install")
        self.assertEqual({k for k, value in profile["components"].items() if value}, {"reshade"})
        self.assertEqual(options, {})
        self.window.tabs.setCurrentIndex(2)
        self.app.processEvents()
        self.assertFalse(self.window.install_button.isVisible())
        self.window.features.install_shaders()
        self.assertEqual(self.window.queue[0][1], "deploy_shader")
        self.window.queue.clear()
        self.assertEqual(len(list(self.game.target.iterdir())), 1)

    def test_library_and_details_do_not_touch_after_resize_or_splitter_restore(self):
        from PySide6.QtCore import QPoint
        self.window.show()
        for width, height in [(1220, 880), (930, 740), (2000, 1100)]:
            self.window.resize(width, height)
            self.window.splitter.setSizes([width // 3, width * 2 // 3])
            self.app.processEvents()
            search_right = self.window.search.mapTo(self.window, QPoint(self.window.search.width(), 0)).x()
            title_left = self.window.game_title.mapTo(self.window, QPoint(0, 0)).x()
            nav_right = self.window.navigation.mapTo(self.window, QPoint(self.window.navigation.width(), 0)).x()
            panel_left = self.window.tabs.mapTo(self.window, QPoint(0, 0)).x()
            self.assertGreaterEqual(title_left - search_right, 16)
            self.assertGreaterEqual(panel_left - nav_right, 8)
            self.assertGreater(self.window.splitter.handle(1).width(), 0)

    def test_navigation_tracks_activity_and_gpu_presets_are_configuration(self):
        self.window.show()
        self.app.processEvents()
        self.window.tabs.setCurrentWidget(self.window.log)
        self.assertEqual(self.window.navigation.currentItem().text(), "Activity")
        self.window.navigation.setCurrentRow(1)
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        preset = self.window.features.gpu_template
        self.assertTrue(self.window.tabs.widget(1).isAncestorOf(preset))
        self.assertFalse(preset.isVisible())  # Advanced INI presets start closed.
        self.assertIn("configuration", preset.itemText(0))
        self.assertFalse(self.window.overview.isAncestorOf(self.window.features.app_background))
        self.assertTrue(self.window.features.app_dialog.isAncestorOf(self.window.features.app_background))
        self.assertEqual(len(list(self.game.target.iterdir())), 1)

    def test_library_actions_do_not_save_or_validate_game_overrides(self):
        self.window.features.environment.setPlainText("unfinished JSON")
        self.window.start_next = lambda: None
        self.window.features.job("refresh_catalogs")
        game, action, profile, options, callback = self.window.queue.pop()
        self.assertEqual(game.id, "global")
        self.assertEqual(action, "refresh_catalogs")
        self.assertEqual(profile, {})
        callback({})
        self.assertEqual(self.window.features.environment.toPlainText(), "unfinished JSON")
        self.assertFalse((self.repository.directory / 'profiles' / (self.game.id + '.json')).exists())

    def test_queued_action_keeps_its_original_executable(self):
        self.window.start_next = lambda: None
        original = self.window.selected.executable
        self.window.enqueue_feature('apply_display')
        self.window.selected.executable = str(self.root / 'another.exe')
        self.assertEqual(self.window.queue[0][0].executable, original)
        self.window.queue.clear()

    def test_late_shader_picker_cannot_deploy_to_a_newly_selected_game(self):
        features = self.window.features
        features.shader_list.setCurrentRow(0)
        with patch.object(features, 'job') as job, patch.object(features, 'effect_picker') as picker:
            features.choose_effects()
            callback = job.call_args.args[2]
            from dataclasses import replace
            self.window.selected = replace(self.window.selected, id='other')
            callback({'id': 'pack', 'files': []})
            picker.assert_not_called()

    def test_late_vkbasalt_result_saves_only_the_originating_game(self):
        features = self.window.features
        origin = self.window.selected
        from dataclasses import replace
        other = replace(origin, id='other')
        with patch('optidx_desktop.feature_ui.QInputDialog.getItem', return_value=('cas', True)), \
                patch.object(features, 'job') as job:
            features.vulkan_effects()
        callback = job.call_args.args[2]
        self.window.selected = other
        features.fields['vkbasalt_config'].setText('/other/config')
        callback({'path': '/origin/config'})
        self.assertEqual(self.repository.preferences(origin)['vkbasalt_config'], '/origin/config')
        self.assertNotIn('vkbasalt_config', self.repository.preferences(other))
        self.assertEqual(features.fields['vkbasalt_config'].text(), '/other/config')

    def test_shared_profile_preserves_game_specific_paths_and_packages(self):
        from dataclasses import replace
        from optidx_desktop.storage import atomic_json
        other = replace(self.window.selected, id='other')
        private = {'dll_folder': 'Own/Plugin', 'vkbasalt_config': '/own/config', 'reframework_asset': 'Own.zip',
                   'prefix': '/own/prefix', 'environment': {'WINEPREFIX': '/own/prefix'}}
        self.repository.save_preferences(other, private)
        shared = {**private, 'dll_folder': 'Foreign/Plugin', 'reframework_asset': 'WrongGame.zip',
                  'environment': {'WINEPREFIX': '/foreign/prefix'}, 'peak_nits': '1000'}
        atomic_json(self.repository.directory / 'shared-profiles.json', {'Shared': shared})
        with patch('optidx_desktop.feature_ui.QInputDialog.getItem', return_value=('Shared', True)), \
                patch.object(self.window.features, 'games_picker', return_value=[other]):
            self.window.features.batch_profile()
        saved = self.repository.preferences(other)
        self.assertTrue(all(saved[key] == value for key, value in private.items()))
        self.assertEqual(saved['peak_nits'], '1000')

    def test_invalid_environment_is_rejected_when_saving_instead_of_at_launch(self):
        self.window.features.environment.setPlainText('["not an object"]')
        with patch.object(self.window, 'report_error') as error:
            self.assertFalse(self.window.save_profile())
        self.assertIn('JSON object', error.call_args.args[0])
        self.window.features.environment.setPlainText('{"PROTON_ENABLE_WAYLAND": false}')
        self.assertEqual(self.window.features.preferences()['environment']['PROTON_ENABLE_WAYLAND'], '0')
        self.window.features.environment.setPlainText('[]')
        with patch.object(self.window, 'report_error') as error:
            self.window.features.export_profile()
            self.window.features.save_named_profile()
        self.assertEqual(error.call_count, 2)

    def test_expanded_profile_restores_channels_dll_choices_and_linux_controls(self):
        features=self.window.features
        features.fields['reshade_channel'].setCurrentIndex(features.fields['reshade_channel'].findData('nightly'))
        features.fields['api_override'].setCurrentIndex(features.fields['api_override'].findData('DX11'))
        features.fields['dlss_sr_scale'].setText('75')
        features.environment.setPlainText('{"DXVK_HUD":"fps"}')
        features.dll_kind.setCurrentIndex(features.dll_kind.findData('dlssnr'))
        features.dll_version.setCurrentText('310.8.0')
        features.dll_folder.setText('Engine/Plugins/DLSS')
        features.drs['NGX_DLSSG_MULTI_FRAME_COUNT'].setCurrentIndex(features.drs['NGX_DLSSG_MULTI_FRAME_COUNT'].findData('2'))
        self.window.save_profile();self.window.load_profile()
        profile=self.repository.preferences(self.game)
        self.assertEqual(profile['reshade_channel'],'nightly')
        self.assertEqual(profile['environment'],{'DXVK_HUD':'fps'})
        self.assertEqual(profile['drs']['NGX_DLSSG_MULTI_FRAME_COUNT'],'2')
        self.assertEqual(features.dll_kind.currentData(),'dlssnr')
        self.assertEqual(features.dll_version.currentText(),'310.8.0')
        self.assertEqual(features.dll_folder.text(),'Engine/Plugins/DLSS')

    def test_real_worker_import_and_addon_deployment_updates_the_library(self):
        from test_core import pe_fixture
        (self.game.target/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        path=self.root/'custom.addon64';path.write_bytes(pe_fixture())
        self.window.enqueue_feature('import_asset',{'path':str(path),'kind':'addon'})
        def finish():
            deadline=time.monotonic()+8
            while (self.window.process is not None or self.window.queue) and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(0.01)
            self.assertIsNone(self.window.process)
            self.assertTrue(self.window.result['ok'])
        finish()
        key=self.window.result['data']['id']
        self.assertGreater(self.window.features.asset_library.count(),0)
        self.window.enqueue_feature('deploy_asset',{'id':key})
        finish()
        self.assertTrue((self.game.target/'custom.addon64').exists())
        self.assertGreater(self.window.features.managed.count(),0)

    def test_helix_removal_button_runs_a_targeted_job_and_updates_the_profile(self):
        from optidx_desktop.backend import load_backend
        from optidx_desktop.storage import atomic_json
        module = load_backend()
        relative = 'OptiScaler/HelixSR/helixsr.dll'
        helix = self.game.target / relative
        helix.parent.mkdir(parents=True)
        helix.write_bytes(b'MZ HelixSR')
        lossy = self.game.target / 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'
        lossy.write_bytes(b'MZ lossy')
        (self.game.target / 'OptiScaler.ini').write_text('[Libraries]\nFfxDx12SRPath=' + module.proton_path(helix) + '\n')
        (self.game.target / '.optidx-files').write_text(relative + '\nOptiScaler/amd_fidelityfx_upscaler_dx12.dll\n')
        atomic_json(self.game.target / '.optidx-components.json', {'files': {'helixsr': [relative]}, 'selected': ['helixsr', 'amd_fsr']})
        self.window.components['helixsr'].setChecked(True)
        self.window.save_profile()
        self.window.features.refresh()
        self.assertTrue(self.window.features.remove_helix_button.isEnabled())
        self.window.features.remove_helix_button.click()
        deadline = time.monotonic() + 8
        while self.window.process is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.window.process)
        self.assertTrue(self.window.result['ok'])
        self.assertFalse(helix.exists())
        self.assertEqual(lossy.read_bytes(), b'MZ lossy')
        self.assertFalse(self.window.components['helixsr'].isChecked())
        self.assertFalse(self.repository.preferences(self.game)['components']['helixsr'])
        self.assertFalse(self.window.features.remove_helix_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
