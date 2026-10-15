import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from optidx_desktop.backend import load_backend, selected_components
from optidx_desktop.backups import remember_baseline, snapshot
from optidx_desktop.library import manual_game
from optidx_desktop.storage import Repository, atomic_json, read_json
from optidx_desktop.worker import run_job
from test_core import pe_fixture


class HelixRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target = self.root / 'Example Game/Binaries/Win64'
        self.target.mkdir(parents=True)
        exe = self.target / 'Example.exe'
        exe.write_bytes(pe_fixture(('d3d12.dll',)))
        self.game = manual_game(exe, 'Example Game')
        self.repository = Repository(self.root / 'data')
        self.module = load_backend()
        self.helix = ['OptiScaler/HelixSR/' + name for name in
                      ['helixsr.dll', 'helixsr_upscaler.dll', 'helixsr_weights.bin',
                       'helixsr_kernels.pak', 'amd_fidelityfx_upscaler_dx12.amd.dll',
                       'helixsr.ini', '.optidx-helixsr.json']]
        self.other = ['dxgi.dll', 'd3d12-ReShade64.dll', 'renodx-game.addon64',
                      'OptiScaler/amd_fidelityfx_upscaler_dx12.dll', 'OptiScaler/dlss-enabler-headless.dll']
        for relative in self.helix + self.other:
            p = self.target / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'MZ fixture ' + relative.encode())
        # Generated logs and user files are not part of the component manifest.
        (self.target / 'OptiScaler/HelixSR/helixsr.log').write_text('user log')
        (self.target / 'OptiScaler/HelixSR/user-notes.txt').write_text('keep')
        self.ini = self.target / 'OptiScaler.ini'
        self.ini.write_text('; keep comment\n[Upscalers]\nDx12Upscaler=ffx\n[Libraries]\n'
                            'FfxDx12Path=' + self.module.proton_path(self.target / self.helix[0]) + '\n'
                            'FfxDx12SRPath=' + self.module.proton_path(self.target / self.helix[1]) + '\n'
                            'NvngxPath=auto\n[FrameGen]\nFGOutput=xefg\n')
        owners = {'helixsr': self.helix, 'optiscaler': ['dxgi.dll', 'OptiScaler.ini'],
                  'reshade': ['d3d12-ReShade64.dll'], 'renodx': ['renodx-game.addon64'],
                  'amd_fsr': ['OptiScaler/amd_fidelityfx_upscaler_dx12.dll'],
                  'dlss_enabler': ['OptiScaler/dlss-enabler-headless.dll']}
        atomic_json(self.target / '.optidx-components.json',
                    {'version': 1, 'selected': list(owners), 'files': owners})
        (self.target / '.optidx-files').write_text('\n'.join(self.helix + self.other + ['OptiScaler.ini', '.optidx-components.json']) + '\n')
        (self.target / '.optidx-installed').write_text(str(self.target) + '\n')
        self.preferences = {'components': {key: True for key in owners}, 'native_hdr': False,
                            'environment': {'DXVK_HUD': 'fps'}}
        self.repository.save_preferences(self.game, self.preferences)

    def tearDown(self):
        self.temporary.cleanup()

    def run_remove(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return run_job({'game': self.game.to_dict(), 'action': 'remove_helixsr',
                            'preferences': self.preferences}, self.repository.directory)

    def test_new_defaults_exclude_helix_but_existing_choices_are_preserved(self):
        self.assertIn('amd_fsr', selected_components({}))
        self.assertNotIn('helixsr', selected_components({}))
        self.assertIn('helixsr', selected_components({'mode': 'full'}))
        self.assertIn('helixsr', selected_components(self.preferences))

    def test_targeted_worker_removal_preserves_other_mods_and_restores_direct_lossy(self):
        before = {p: (self.target / p).read_bytes() for p in self.other}
        with patch('optidx_desktop.downloads.Client.fetch', side_effect=AssertionError('Removal must not download')):
            self.run_remove()
        self.assertTrue(all(not (self.target / p).exists() for p in self.helix))
        self.assertEqual(before, {p: (self.target / p).read_bytes() for p in self.other})
        self.assertEqual((self.target / 'OptiScaler/HelixSR/user-notes.txt').read_text(), 'keep')
        self.assertEqual((self.target / 'OptiScaler/HelixSR/helixsr.log').read_text(), 'user log')
        text = self.ini.read_text()
        self.assertIn('; keep comment', text)
        self.assertIn('FGOutput=xefg', text)
        self.assertIn('FfxDx12Path=auto', text)
        self.assertIn('FfxDx12SRPath=' + self.module.proton_path(self.target / self.other[3]), text)
        state = read_json(self.target / '.optidx-components.json', {})
        self.assertEqual(state['files']['helixsr'], [])
        self.assertNotIn('helixsr', state['selected'])
        self.assertNotIn('OptiScaler/HelixSR/', (self.target / '.optidx-files').read_text())
        profile = self.repository.preferences(self.game)
        self.assertFalse(profile['components']['helixsr'])
        self.assertTrue(profile['components']['renodx'])
        self.assertEqual(profile['environment'], {'DXVK_HUD': 'fps'})
        self.assertTrue((self.target / '.optidx-installed').exists())

    def test_legacy_manifest_is_adopted_for_targeted_removal(self):
        (self.target / '.optidx-components.json').unlink()
        self.run_remove()
        self.assertFalse((self.target / self.helix[0]).exists())
        self.assertTrue((self.target / 'd3d12-ReShade64.dll').exists())

    def test_missing_lossy_rejects_removal_before_changing_files_or_profile(self):
        (self.target / self.other[3]).unlink()
        before = self.ini.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Install the Cyboman'):
            self.run_remove()
        self.assertEqual(self.ini.read_bytes(), before)
        self.assertTrue((self.target / self.helix[0]).exists())
        self.assertTrue(self.repository.preferences(self.game)['components']['helixsr'])

    def test_unrelated_custom_library_override_is_preserved(self):
        text = self.ini.read_text()
        text = self.module.set_ini_values(text, 'Libraries', {'FfxDx12SRPath': 'Z:\\custom\\my-upscaler.dll'})
        self.ini.write_text(text)
        self.run_remove()
        self.assertIn('FfxDx12SRPath=Z:\\custom\\my-upscaler.dll', self.ini.read_text())

    def test_wine_drive_mapping_and_dot_relative_paths_are_reconnected(self):
        prefix = self.root / 'prefix'
        (prefix / 'dosdevices').mkdir(parents=True)
        (prefix / 'dosdevices/s:').symlink_to(self.root, target_is_directory=True)
        self.preferences['prefix'] = str(prefix)
        text = self.module.set_ini_values(self.ini.read_text(), 'Libraries', {
            'FfxDx12Path': 'S:\\Example Game\\Binaries\\Win64\\OptiScaler\\HelixSR\\helixsr.dll',
            'FfxDx12SRPath': '.\\OptiScaler\\HelixSR\\helixsr_upscaler.dll'})
        self.ini.write_text(text)
        self.run_remove()
        self.assertIn('FfxDx12Path=auto', self.ini.read_text())
        self.assertIn('FfxDx12SRPath=' + self.module.proton_path(self.target / self.other[3]), self.ini.read_text())

    def test_late_inspection_failure_does_not_commit_profile_removal(self):
        before = self.ini.read_bytes()
        with patch('optidx_desktop.inspection.inspect_game', side_effect=RuntimeError('inspection failed')):
            with self.assertRaisesRegex(RuntimeError, 'inspection failed'):
                self.run_remove()
        self.assertEqual(self.ini.read_bytes(), before)
        self.assertTrue(all((self.target / p).is_file() for p in self.helix))
        self.assertTrue(self.repository.preferences(self.game)['components']['helixsr'])

    def test_removal_preserves_component_choices_saved_while_job_was_running(self):
        original = self.module.write_component_manifest
        def write_and_save_new_choices(owners):
            original(owners)
            current = self.repository.preferences(self.game)
            current['components']['reshade'] = False
            self.repository.save_preferences(self.game, current)
        self.module.write_component_manifest = write_and_save_new_choices
        with patch('optidx_desktop.helixsr.load_backend', return_value=self.module):
            self.run_remove()
        self.assertFalse(self.repository.preferences(self.game)['components']['helixsr'])
        self.assertFalse(self.repository.preferences(self.game)['components']['reshade'])

    def test_original_helix_file_is_restored_without_restoring_other_mods(self):
        # An unmanaged file existed before the original Desktop installation.
        path = self.target / self.helix[0]
        path.write_bytes(b'prior user file')
        (self.target / '.optidx-files').write_text('')
        baseline = snapshot(self.game, self.repository)
        remember_baseline(self.game, self.repository, baseline)
        path.write_bytes(b'MZ managed replacement')
        (self.target / '.optidx-files').write_text('\n'.join(self.helix + self.other + ['OptiScaler.ini']))
        self.run_remove()
        self.assertEqual(path.read_bytes(), b'prior user file')
        self.assertTrue((self.target / 'renodx-game.addon64').exists())
        self.assertTrue((self.repository.directory / 'backups' / self.game.id / 'baseline.json').exists())

    def test_failed_manifest_write_rolls_back_deleted_files_and_routing(self):
        before = {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob('*') if p.is_file()}
        self.module.write_component_manifest = lambda owners: (_ for _ in ()).throw(OSError('injected write failure'))
        with patch('optidx_desktop.helixsr.load_backend', return_value=self.module):
            with self.assertRaisesRegex(OSError, 'injected write failure'):
                self.run_remove()
        after = {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob('*') if p.is_file()}
        self.assertEqual(after, before)
        self.assertTrue(self.repository.preferences(self.game)['components']['helixsr'])

    def test_invalid_ownership_cannot_remove_another_component(self):
        state = read_json(self.target / '.optidx-components.json', {})
        state['files']['helixsr'].append('renodx-game.addon64')
        atomic_json(self.target / '.optidx-components.json', state)
        with self.assertRaisesRegex(ValueError, 'Unexpected HelixSR-owned path'):
            self.run_remove()
        self.assertTrue((self.target / 'renodx-game.addon64').exists())
        self.assertTrue((self.target / self.helix[0]).exists())


if __name__ == '__main__':
    unittest.main()
