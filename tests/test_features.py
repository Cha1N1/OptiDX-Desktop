import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from test_core import pe_fixture
from optidx_desktop import assets
from optidx_desktop.backups import snapshot, rollback_snapshot
from optidx_desktop.catalog import catalogs
from optidx_desktop.channels import prepare_reshade, effective_api, install_dxvk
from optidx_desktop.downloads import archive_files, binary_member, Client, sha
from optidx_desktop.features import import_asset, deploy_custom, shader_layout, swap_dll, apply_display, run_feature
from optidx_desktop.launch import profile_environment, run_profile, runner_command, DRS_CHOICES
from optidx_desktop.library import manual_game, scan_library
from optidx_desktop.storage import Repository, atomic_json
from optidx_desktop.worker import run_job


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / 'Game/Binaries/Win64'
        self.binary.mkdir(parents=True)
        self.exe = self.binary / 'Game.exe'
        self.exe.write_bytes(pe_fixture())
        self.game = manual_game(self.exe, 'Game')
        self.repo = Repository(self.root / 'data')

    def tearDown(self):
        self.temp.cleanup()

    def zip(self, files, name='payload.zip'):
        path=self.root/name
        with zipfile.ZipFile(path,'w') as z:
            for key,value in files.items():z.writestr(key,value)
        return path

    def test_import_and_enable_disable_addon_round_trip(self):
        source=self.root/'test.addon64';source.write_bytes(pe_fixture())
        item=import_asset(self.repo,source)
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        deploy_custom(self.game,self.repo,item,{})
        group='custom:'+item['id']
        assets.toggle_addon(self.binary,group,False)
        self.assertFalse((self.binary/'test.addon64').exists())
        self.assertTrue((self.binary/'test.addon64.disabled').exists())
        assets.toggle_addon(self.binary,group,True)
        assets.remove(self.binary,group)
        self.assertFalse((self.binary/'test.addon64').exists())

    def test_addon_requires_reshade_and_checks_architecture(self):
        path=self.root/'mod.addon32';data=bytearray(pe_fixture(bits=32));path.write_bytes(data)
        item=import_asset(self.repo,path)
        with self.assertRaisesRegex(ValueError,'ReShade'):deploy_custom(self.game,self.repo,item,{})
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        with self.assertRaisesRegex(ValueError,'architecture'):deploy_custom(self.game,self.repo,item,{})

    def test_foreign_file_preserved_without_explicit_replacement(self):
        (self.binary/'mod.dll').write_bytes(b'original')
        with self.assertRaises(assets.Conflict):assets.deploy(self.binary,'x',{'mod.dll':b'new','added.fx':b'fx'})
        self.assertFalse((self.binary/'added.fx').exists())
        self.assertEqual((self.binary/'mod.dll').read_bytes(),b'original')
        assets.deploy(self.binary,'x',{'mod.dll':b'new'},allow_foreign=True)
        assets.deploy(self.binary,'x',{'mod.dll':b'newer'})
        assets.remove(self.binary,'x')
        self.assertEqual((self.binary/'mod.dll').read_bytes(),b'original')

    def test_modified_managed_files_and_cross_group_collisions_are_rejected(self):
        assets.deploy(self.binary,'x',{'mod.dll':b'new'})
        with self.assertRaises(assets.Conflict):assets.deploy(self.binary,'y',{'MOD.dll':b'other'})
        (self.binary/'mod.dll').write_bytes(b'user edit')
        with self.assertRaises(assets.Conflict):assets.remove(self.binary,'x')
        self.assertEqual((self.binary/'mod.dll').read_bytes(),b'user edit')

    def test_failed_deploy_rolls_back_originals_and_new_files(self):
        original=assets.atomic_bytes
        (self.binary/'a.dll').write_bytes(b'original')
        counter=[0]
        def failing(path,data,mode=0o644):
            counter[0]+=1
            if counter[0]==2:raise OSError('disk full')
            return original(path,data,mode)
        with patch('optidx_desktop.assets.atomic_bytes',side_effect=failing),self.assertRaises(OSError):
            assets.deploy(self.binary,'x',{'a.dll':b'new','b.dll':b'new'},allow_foreign=True)
        self.assertEqual((self.binary/'a.dll').read_bytes(),b'original')
        self.assertFalse((self.binary/'b.dll').exists())
        self.assertFalse((self.binary/assets.LEDGER).exists())

    def test_archive_paths_links_duplicates_and_crc_are_checked(self):
        for name in ['../escape.dll','C:/escape.dll','/escape.dll','a\\..\\escape.dll']:
            with self.subTest(name=name),self.assertRaises(ValueError):archive_files(self.zip({name:b'bad'}))
        path=self.root/'links.zip'
        with zipfile.ZipFile(path,'w') as z:
            info=zipfile.ZipInfo('link');info.external_attr=(0o120777<<16);z.writestr(info,'../escape')
        with self.assertRaises(ValueError):archive_files(path)
        with self.assertRaisesRegex(ValueError,'Duplicate'):archive_files(self.zip({'File.fx':b'a','file.fx':b'b'}))
        self.assertFalse((self.root/'escape.dll').exists())

    def test_binary_members_select_architecture_and_reject_duplicates(self):
        x32=bytearray(pe_fixture(bits=32))
        files={'x64/nvngx_dlss.dll':pe_fixture(),'x32/nvngx_dlss.dll':bytes(x32)}
        self.assertEqual(binary_member(files,'nvngx_dlss.dll',64),pe_fixture())
        files['duplicate/nvngx_dlss.dll']=pe_fixture()
        with self.assertRaises(ValueError):binary_member(files,'nvngx_dlss.dll')

    def test_shader_selection_preserves_include_files_textures_and_licenses(self):
        prepared=shader_layout({'repo/Shaders/A.fx':b'a','repo/Shaders/B.fx':b'b','repo/Shaders/common.fx h'.replace(' ',''):b'header',
                               'repo/Textures/LUT.png':b'png','repo/LICENSE':b'license'},'pack',['A.fx'])
        self.assertTrue(any(n.endswith('A.fx') for n in prepared))
        self.assertFalse(any(n.endswith('B.fx') for n in prepared))
        self.assertTrue(any(n.endswith('common.fxh') for n in prepared))
        self.assertTrue(any(n.endswith('LUT.png') for n in prepared))
        self.assertTrue(any(n.endswith('LICENSE') for n in prepared))

    def test_dlss_swap_in_engine_folder_restores_original_after_multiple_versions(self):
        folder=Path(self.game.root)/'Engine/Plugins/DLSS';folder.mkdir(parents=True)
        original=folder/'nvngx_dlss.dll';original.write_bytes(pe_fixture()+b'original')
        path=self.zip({'nvngx_dlss.dll':pe_fixture()+b'v1'})
        swap_dll(self.game,self.repo,'dlss','',str(folder.relative_to(self.game.root)),str(path))
        newer=self.zip({'nvngx_dlss.dll':pe_fixture()+b'v2'},'new.zip')
        swap_dll(self.game,self.repo,'dlss','',str(folder.relative_to(self.game.root)),str(newer))
        group=next(iter(assets.state(self.game.root)['groups']))
        assets.remove(self.game.root,group)
        self.assertEqual(original.read_bytes(),pe_fixture()+b'original')
        with self.assertRaises(ValueError):swap_dll(self.game,self.repo,'dlss','','../../outside',str(path))

    def test_reshade_custom_dx9_and_32bit_select_correct_proxy(self):
        data=bytearray(pe_fixture(('d3d9.dll',),bits=32))
        self.exe.write_bytes(data)
        path=self.root/'ReShade32.dll';path.write_bytes(data)
        files,metadata=prepare_reshade(self.game,self.repo,{'reshade_channel':'custom','reshade_custom':str(path),'bits_override':'32','components':{}})
        self.assertEqual(set(files),{'ReShade32.dll','d3d9.dll'})
        self.assertEqual(metadata['bits'],32)

    def test_reshade_coexistence_uses_d3d_prefixed_name_without_overwriting_optiscaler(self):
        path=self.root/'ReShade64.dll';path.write_bytes(pe_fixture())
        files,_=prepare_reshade(self.game,self.repo,{'reshade_channel':'custom','reshade_custom':str(path),'components':{'optiscaler':True}})
        self.assertEqual(set(files),{'d3d12-ReShade64.dll'})

    def test_display_settings_merge_existing_ini_without_losing_user_values(self):
        ini=self.binary/'ReShade.ini';ini.write_text('[GENERAL]\nEffectSearchPaths=.\\mine\n[renodx-preset1]\nOther=keep\n')
        shaders=self.binary/'reshade-shaders/OptiDX/pack/Shaders';shaders.mkdir(parents=True)
        apply_display(self.game,{'peak_nits':'1000','screenshot_path':'/tmp/screens'})
        text=ini.read_text()
        self.assertIn('Other=keep',text);self.assertIn('.\\mine',text);self.assertIn('ToneMapPeakNits=1000',text)
        with self.assertRaises(ValueError):apply_display(self.game,{'peak_nits':1})

    def test_environment_overrides_use_documented_drs_values_and_preserve_host(self):
        self.assertEqual(DRS_CHOICES['NGX_DLSSG_MULTI_FRAME_COUNT'],['1','2','3','4','5'])
        env=profile_environment({'drs':{'NGX_DLSSG_MULTI_FRAME_COUNT':'2'},'dlss_sr_scale':'75','PROTON_ENABLE_WAYLAND':True}, {'PATH':'/usr/bin','CUSTOM':'keep'})
        self.assertEqual(env['DXVK_NVAPI_DRS_NGX_DLSSG_MULTI_FRAME_COUNT'],'2')
        self.assertEqual(env['DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE'],'CUSTOM')
        self.assertEqual(env['CUSTOM'],'keep')
        with self.assertRaises(ValueError):profile_environment({'dlss_sr_scale':20},{})
        with self.assertRaises(ValueError):profile_environment({'environment':{'bad-name':'x'}},{})

    def test_launch_profile_executes_argv_without_shell_and_returns_exit_status(self):
        path=self.root/'profile.json';atomic_json(path,{'environment':{'OPTIDX_TEST':'value with spaces'},'launch_arguments':'"literal;argument"'})
        out=self.root/'result.json'
        code='import os,sys,json,pathlib;pathlib.Path(sys.argv[1]).write_text(json.dumps([os.environ["OPTIDX_TEST"],sys.argv[2:]]));sys.exit(7)'
        self.assertEqual(run_profile(path,[sys.executable,'-c',code,str(out)]),7)
        self.assertEqual(json.loads(out.read_text()),['value with spaces',['literal;argument']])

    def test_manual_runner_does_not_duplicate_arguments(self):
        command=runner_command(self.game,{'runner_kind':'proton','runner_command':'"/tmp/proton with spaces"','launch_arguments':'-dx11'})
        self.assertEqual(command,['/tmp/proton with spaces','run',self.game.executable])

    def test_kde_hdr_restore_runs_after_failed_game_exit(self):
        path=self.root/'profile.json';atomic_json(path,{'auto_hdr':True,'hdr_output':'DP-1'})
        with patch('optidx_desktop.launch.hdr_outputs',return_value=[{'name':'DP-1','enabled':False}]),patch('optidx_desktop.launch.set_hdr') as hdr,patch('optidx_desktop.launch.data_dir',return_value=self.root/'data'):
            self.assertEqual(run_profile(path,[sys.executable,'-c','raise SystemExit(3)']),3)
            self.assertEqual([c.args for c in hdr.call_args_list],[('DP-1',True),('DP-1',False)])

    def test_snapshot_rollback_removes_new_managed_files_and_restores_modes(self):
        (self.binary/'dxgi.dll').write_bytes(b'original');(self.binary/'dxgi.dll').chmod(0o444)
        folder=snapshot(self.game,self.repo)
        assets.deploy(self.binary,'x',{'new.addon64':pe_fixture()})
        (self.binary/'dxgi.dll').chmod(0o644);(self.binary/'dxgi.dll').write_bytes(b'new')
        rollback_snapshot(self.binary,folder)
        self.assertEqual((self.binary/'dxgi.dll').read_bytes(),b'original')
        self.assertEqual((self.binary/'dxgi.dll').stat().st_mode&0o777,0o444)
        self.assertFalse((self.binary/'new.addon64').exists())
        self.assertFalse((self.binary/assets.LEDGER).exists())

    def test_worker_rolls_back_partial_backend_failure(self):
        (self.binary/'dxgi.dll').write_bytes(b'original')
        (self.binary/'.optidx-files').write_text('dxgi.dll\n')
        def broken(*unused):
            (self.binary/'dxgi.dll').write_bytes(b'broken')
            (self.binary/'renodx-new.addon64').write_bytes(pe_fixture())
            raise RuntimeError('failed download')
        with patch('optidx_desktop.worker.execute_backend',side_effect=broken),contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'failed download'):
            run_job({'game':self.game.to_dict(),'action':'update','preferences':{}},str(self.repo.directory))
        self.assertEqual((self.binary/'dxgi.dll').read_bytes(),b'original')
        self.assertFalse((self.repo.directory/'backups'/self.game.id/'baseline.json').exists())

    def test_failed_uninstall_restores_the_baseline_pointer_for_retry(self):
        original = self.binary / 'dxgi.dll'
        original.write_bytes(b'original')
        from optidx_desktop.backups import remember_baseline, baseline_path
        remember_baseline(self.game, self.repo, snapshot(self.game, self.repo))
        pointer = baseline_path(self.game, self.repo)
        before = pointer.read_bytes()
        original.write_bytes(b'managed')
        (self.binary / '.optidx-files').write_text('dxgi.dll\n')
        with patch('optidx_desktop.worker.execute_backend', return_value={}), \
                patch('optidx_desktop.inspection.inspect_game', side_effect=RuntimeError('late failure')), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'late failure'):
            run_job({'game': self.game.to_dict(), 'action': 'remove', 'preferences': {}}, str(self.repo.directory))
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual(original.read_bytes(), b'managed')

    def test_external_rollback_failure_does_not_skip_game_file_recovery(self):
        path = self.binary / 'dxgi.dll'
        path.write_bytes(b'original')
        def broken(*unused):
            path.write_bytes(b'broken')
            raise RuntimeError('install failed')
        with patch('optidx_desktop.worker.execute_backend', side_effect=broken), \
                patch('optidx_desktop.backups.rollback_external_config', side_effect=OSError('prefix unavailable')), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'UE configuration: prefix unavailable'):
            run_job({'game': self.game.to_dict(), 'action': 'install', 'preferences': {}}, str(self.repo.directory))
        self.assertEqual(path.read_bytes(), b'original')
        self.assertFalse((self.repo.directory/'backups'/self.game.id/'baseline.json').exists())

    def test_arm64_dlls_are_not_accepted_as_x64_payloads(self):
        data = bytearray(pe_fixture())
        struct.pack_into('<H', data, 0x84, 0xaa64)
        with self.assertRaisesRegex(ValueError, 'architecture'):
            binary_member({'nvngx_dlss.dll': bytes(data)}, 'nvngx_dlss.dll', 64)
        payloads = {'arm64/nvngx_dlss.dll': bytes(data), 'x64/nvngx_dlss.dll': pe_fixture()}
        self.assertEqual(binary_member(payloads, 'nvngx_dlss.dll', 64), pe_fixture())
        malformed = bytearray(pe_fixture())
        struct.pack_into('<H', malformed, 0x98, 0)
        with self.assertRaisesRegex(ValueError, 'architecture'):
            binary_member({'nvngx_dlss.dll': bytes(malformed)}, 'nvngx_dlss.dll', 64)

    def test_windows_case_collisions_do_not_create_competing_dlls_or_directories(self):
        path = self.binary / 'NVNGX_DLSS.dll'
        path.write_bytes(b'original')
        with self.assertRaisesRegex(assets.Conflict, 'capitalization'):
            assets.deploy(self.binary, 'case', {'nvngx_dlss.dll': b'new'}, allow_foreign=True)
        self.assertEqual(path.read_bytes(), b'original')
        self.assertFalse((self.binary / 'nvngx_dlss.dll').exists())
        with self.assertRaisesRegex(assets.Conflict, 'capitalization'):
            assets.deploy(self.binary, 'case', {'Textures/a.dds': b'a', 'textures/b.dds': b'b'})
        self.assertFalse((self.binary / 'Textures').exists())

    def test_lutris_and_bottles_discovery_are_read_only(self):
        home=self.root/'home';db=home/'.local/share/lutris/pga.db';db.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(db)) as c:
            c.execute('CREATE TABLE games(id INTEGER,name TEXT,installed INTEGER,directory TEXT,configpath TEXT,runner TEXT)')
            c.execute('INSERT INTO games VALUES(1,?,1,?,?,?)',('Lutris Game',str(self.binary),'game','wine'))
        # Commit fixtures before closing the connection.
            c.commit()
        cfg=home/'.config/lutris/games/game.yml';cfg.parent.mkdir(parents=True)
        cfg.write_text('game:\n  exe: '+str(self.exe)+'\n  prefix: '+str(self.root/'prefix')+'\n')
        bottle=home/'.local/share/bottles/bottles/Test';bottle.mkdir(parents=True)
        (bottle/'bottle.yml').write_text('Name: Test\nExternal_Programs:\n  game:\n    name: Bottle Game\n    path: '+str(self.exe)+'\n')
        games,warnings=scan_library(home)
        self.assertFalse(warnings)
        self.assertEqual({g.store for g in games},{'Lutris','Bottles'})
        self.assertEqual(len(list(self.binary.iterdir())),1)

    def test_custom_catalog_and_cached_rhi_overrides_merge(self):
        atomic_json(self.repo.directory/'remote-manifest.json',{'shaderPacks':{'CrosireMaster':{'disabled':True},'Test':{'kind':'DirectUrl','url':'https://example.com/pack.zip','displayName':'Test pack'}}})
        catalog=catalogs(self.repo)
        self.assertNotIn('CrosireMaster',catalog)
        self.assertEqual(catalog['Test']['url'],'https://example.com/pack.zip')

    def test_digest_mismatch_rejects_cached_download(self):
        client=Client(self.repo.directory);url='https://example.com/file'
        path=client.directory/sha(url.encode());path.write_bytes(b'payload')
        atomic_json(path.with_suffix('.json'),{'sha256':sha(b'payload')})
        with self.assertRaisesRegex(ValueError,'SHA-256'):client.fetch(url,'0'*64)

    def test_release_selection_handles_pinned_and_nightly_assets(self):
        client=Client(self.repo.directory)
        rows=[{'tag_name':'nightly','prerelease':True,'assets':[{'name':'OptiScaler.7z','browser_download_url':'https://x/n'}]},
              {'tag_name':'v1','assets':[{'name':'OptiScaler.7z','browser_download_url':'https://x/s'}]}]
        with patch.object(client,'releases',return_value=rows):
            self.assertEqual(client.release_asset('a/b',r'\.7z$')['version'],'v1')
            self.assertEqual(client.release_asset('a/b',r'\.7z$','nightly')['version'],'nightly')
            self.assertEqual(client.release_asset('a/b',r'\.7z$',tag='v1')['version'],'v1')

    def test_original_dll_backup_is_a_compact_verified_blob(self):
        (self.binary/'mod.dll').write_bytes(b'original')
        assets.deploy(self.binary,'x',{'mod.dll':b'updated'},allow_foreign=True)
        record=assets.state(self.binary)['groups']['x']['files']['mod.dll']['original']
        self.assertIn('blob',record)
        self.assertNotIn('data',record)
        (self.binary/assets.ORIGINALS/record['blob']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):assets.remove(self.binary,'x')
        self.assertEqual((self.binary/'mod.dll').read_bytes(),b'updated')

    def test_backend_owned_dll_does_not_become_a_fake_original(self):
        (self.binary/'dxgi.dll').write_bytes(b'old managed')
        (self.binary/'.optidx-files').write_text('dxgi.dll\n')
        assets.deploy(self.binary,'x',{'dxgi.dll':b'updated'})
        self.assertIsNone(assets.state(self.binary)['groups']['x']['files']['dxgi.dll']['original'])
        assets.remove(self.binary,'x')
        self.assertFalse((self.binary/'dxgi.dll').exists())

    def test_display_undo_keeps_later_user_settings(self):
        from optidx_desktop.features import restore_display
        ini=self.binary/'ReShade.ini';ini.write_text('[renodx-preset1]\nToneMapPeakNits=600\nOther=old\n')
        apply_display(self.game,{'peak_nits':'1000'})
        ini.write_text(ini.read_text()+'UserSetting=keep\n')
        restore_display(self.game)
        self.assertIn('ToneMapPeakNits=600',ini.read_text())
        self.assertIn('UserSetting=keep',ini.read_text())

    def test_editor_refuses_concurrent_edits_and_path_traversal(self):
        from optidx_desktop.features import edit_config
        path=self.binary/'OptiScaler.ini';path.write_text('[FrameGen]\nEnabled=auto\n')
        before=sha(path.read_bytes());path.write_text('[FrameGen]\nEnabled=false\n')
        with self.assertRaises(assets.Conflict):edit_config(self.game,{'name':'OptiScaler.ini','before_sha256':before,'text':'[FrameGen]\nEnabled=true'})
        with self.assertRaises(ValueError):edit_config(self.game,{'name':'../other.ini','before_sha256':before,'text':''})
        self.assertIn('false',path.read_text())

    def test_dependent_shader_pack_cannot_lose_its_dependency(self):
        assets.deploy(self.binary,'shader:base',{'reshade-shaders/base.fx':b'base'},{'source':{}})
        assets.deploy(self.binary,'shader:dependent',{'reshade-shaders/other.fx':b'other'},{'source':{'requires':['base']}})
        with self.assertRaisesRegex(ValueError,'dependent'):run_feature(self.game,'remove_asset',{},self.repo,{'group':'shader:base'})
        self.assertTrue((self.binary/'reshade-shaders/base.fx').exists())

    def test_excluded_backend_components_are_not_updated_or_pruned(self):
        from optidx_desktop.backend import execute_backend,load_backend
        module=load_backend()
        with patch.object(module,'main') as main:
            execute_backend(self.game,'update',{'components':{'reshade':True},'exclude_components':['reshade'],'prune_components':True},module)
            main.assert_not_called()

    def test_update_checks_detect_changed_moving_tags_and_respect_exclusions(self):
        from optidx_desktop.updates import check_updates
        assets.deploy(self.binary,'extra:relimiter',{'test.addon64':pe_fixture()}, {'version':'latest','updated_at':'old','source':{'repo':'a/b','pattern':r'\.addon64$'}})
        client=Client(self.repo.directory)
        with patch.object(client,'release_asset',return_value={'version':'latest','updated_at':'new'}):
            info=check_updates(self.game,self.repo,{},client)
            self.assertTrue(info['update_available'])
            info=check_updates(self.game,self.repo,{'exclude_components':['extra:relimiter']},client)
            self.assertFalse(info['update_available'])

    def test_dxvk_custom_package_selects_correct_architecture(self):
        files={'dxvk/x64/d3d11.dll':pe_fixture(),'dxvk/x64/dxgi.dll':pe_fixture()}
        package=self.zip(files)
        result=install_dxvk(self.game,self.repo,{'api_override':'DX11'},{'source':{'path':str(package)}})
        self.assertTrue((self.binary/'d3d11.dll').is_file())
        self.assertIn('extra:dxvk',result['groups'])

    def test_raw_extra_addon_keeps_the_upstream_filename(self):
        from optidx_desktop.features import deploy_extra
        package=self.root/'cached-hash';package.write_bytes(pe_fixture())
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        with patch('optidx_desktop.features.payload',return_value=(package,{'version':'1','url':'https://example.com/zzz_display_commander.addon64'})):
            deploy_extra(self.game,self.repo,'display_commander',{})
        self.assertTrue((self.binary/'zzz_display_commander.addon64').exists())

    def test_mutually_exclusive_limiters_are_rejected_before_writes(self):
        from optidx_desktop.features import deploy_extra
        assets.deploy(self.binary,'extra:relimiter',{'limiter.addon64':pe_fixture()},{})
        with self.assertRaisesRegex(ValueError,'other frame limiter'):deploy_extra(self.game,self.repo,'display_commander',{})

    def test_dof_fix_rejects_unknown_or_newer_unreal_versions(self):
        from optidx_desktop.features import deploy_extra
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        for version in ['', '4.27','5.7']:
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'5.0'):
                deploy_extra(self.game,self.repo,'dof_fix',{'ue_version':version})

    def test_vulkan_config_is_saved_in_app_data_and_requires_valid_effects(self):
        from optidx_desktop.features import create_vkbasalt_config
        before=list(self.binary.iterdir())
        result=create_vkbasalt_config(self.game,self.repo,{'effects':['cas','fxaa']})
        self.assertIn('effects = cas:fxaa',Path(result['path']).read_text())
        self.assertEqual(list(self.binary.iterdir()),before)
        with self.assertRaises(ValueError):create_vkbasalt_config(self.game,self.repo,{'effects':['../../outside.fx']})

    def test_kde_hdr_json_reads_capabilities_without_mutating_displays(self):
        from optidx_desktop.launch import hdr_outputs
        response=subprocess.CompletedProcess([],0,json.dumps({'outputs':[{'name':'DP-1','id':1,'hdrEnabled':True,'capabilities':8}]}),'')
        with patch('optidx_desktop.launch.shutil.which',return_value='/usr/bin/kscreen-doctor'),patch.dict(os.environ,{'XDG_CURRENT_DESKTOP':'KDE'}),patch('optidx_desktop.launch.subprocess.run',return_value=response) as tool:
            info=hdr_outputs()
            self.assertTrue(info[0]['enabled']);self.assertTrue(info[0]['capable'])
            self.assertEqual(tool.call_args.args[0],['kscreen-doctor','-j'])

    def test_dxvk_driver_overrides_preserve_existing_environment(self):
        env=profile_environment({'dxvk_vsync':'0','fps_limit':'120','gl_vsync':'1','gl_gsync':'0','gl_shader_cache_mb':'1024'}, {'DXVK_CONFIG':'dxgi.hideAmdGpu = False'})
        self.assertIn('dxgi.hideAmdGpu = False;',env['DXVK_CONFIG'])
        self.assertIn('dxgi.maxFrameRate = 120',env['DXVK_CONFIG'])
        self.assertEqual(env['__GL_SHADER_DISK_CACHE_SIZE'],str(1024**3))

    def test_profile_launch_without_hdr_preserves_the_existing_hdr_state(self):
        path=self.root/'profile.json';atomic_json(path,{})
        with patch('optidx_desktop.launch.set_hdr') as hdr:
            self.assertEqual(run_profile(path,[sys.executable,'-c','pass']),0)
            hdr.assert_not_called()

    def test_catalog_refresh_is_read_only_for_games_and_reports_network_errors(self):
        from optidx_desktop.features import refresh_catalogs
        client=Client(self.repo.directory)
        before=list(self.binary.iterdir())
        with patch.object(client,'metadata',side_effect=OSError('offline')):
            info=refresh_catalogs(self.repo,client)
        self.assertEqual(len(info['errors']),2)
        self.assertEqual(list(self.binary.iterdir()),before)

    def test_failed_worker_restores_external_engine_ini(self):
        config=self.root/'config';config.mkdir();ini=config/'Engine.ini';ini.write_text('[SystemSettings]\nUserValue=keep\n');ini.chmod(0o444)
        (self.binary/'.optidx-files').write_text('dxgi.dll\n')
        def broken(*unused):
            ini.chmod(0o644);ini.write_text('[SystemSettings]\nUserValue=lost\n')
            raise RuntimeError('failed')
        with patch('optidx_desktop.worker.execute_backend',side_effect=broken),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):
            run_job({'game':self.game.to_dict(),'action':'update','preferences':{'config_dir':str(config)}},str(self.repo.directory))
        self.assertIn('UserValue=keep',ini.read_text());self.assertEqual(ini.stat().st_mode&0o777,0o444)

    def test_cost_scaler_installs_proxy_and_restores_real_nr_dll(self):
        from optidx_desktop.neural import cost_scaler
        base=pe_fixture()+b'real';proxy=pe_fixture()+b'proxy'
        (self.binary/'nvngx_dlssnr.dll').write_bytes(base)
        package=self.zip({'nvngx_dlssnr.dll':proxy,'nvngx_dlssnr.ini':b'[DLSSNR_Proxy]\nResolutionScale=1\n','dlssnr-companion.addon64':pe_fixture()})
        cost_scaler(self.game,self.repo,{'nr_cost_scale':'0.75'},{'source':{'path':str(package)}})
        self.assertEqual((self.binary/'nvngx_dlssnr.dll').read_bytes(),proxy)
        self.assertEqual((self.binary/'nvngx_dlssnr_real.dll').read_bytes(),base)
        self.assertIn('ResolutionScale=0.75',(self.binary/'nvngx_dlssnr.ini').read_text())
        cost_scaler(self.game,self.repo,{}, {},False)
        self.assertEqual((self.binary/'nvngx_dlssnr.dll').read_bytes(),base)
        self.assertFalse((self.binary/'nvngx_dlssnr_real.dll').exists())
        self.assertFalse((self.binary/'dlssnr-companion.addon64').exists())
        assets.remove(self.game.root,'dll:dlssnr:Binaries/Win64')
        self.assertEqual((self.binary/'nvngx_dlssnr.dll').read_bytes(),base)

    def test_cost_scaler_requires_real_dll_and_valid_resolution_scale(self):
        from optidx_desktop.neural import cost_scaler
        with self.assertRaisesRegex(ValueError,'real nvngx'):cost_scaler(self.game,self.repo,{}, {})
        (self.binary/'nvngx_dlssnr.dll').write_bytes(pe_fixture())
        with self.assertRaisesRegex(ValueError,'0.25'):cost_scaler(self.game,self.repo,{'nr_cost_scale':'0.1'}, {})

    def test_shortfuse_pipeline_stages_complete_runtime_before_deployment(self):
        from optidx_desktop.neural import deploy_tool
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        consumer=self.root/'renodx-dlss.addon64';consumer.write_bytes(pe_fixture()+b'consumer')
        sr=self.zip({'nvngx_dlss.dll':pe_fixture()+b'sr'},'sr.zip')
        nr=self.zip({'nvngx_dlssnr.dll':pe_fixture()+b'nr'},'nr.zip')
        sources={'consumer':{'path':str(consumer)},'dlss':{'path':str(sr)},'dlssnr':{'path':str(nr)}}
        deploy_tool(self.game,self.repo,{}, {'method':'shortfuse','sources':sources})
        self.assertTrue((self.binary/'renodx-dlss.addon64').exists())
        self.assertTrue((self.binary/'nvngx_dlss.dll').exists())
        self.assertTrue((self.binary/'nvngx_dlssnr.dll').exists())
        assets.remove(self.game.root,'neural:pipeline:Binaries/Win64')
        self.assertFalse((self.binary/'nvngx_dlssnr.dll').exists())

    def test_neural_pipeline_rejects_competing_optiscaler_before_downloads(self):
        from optidx_desktop.neural import deploy_tool
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        (self.binary/'OptiScaler.ini').write_text('[FrameGen]\nEnabled=auto\n')
        with self.assertRaisesRegex(ValueError,'OptiScaler'):deploy_tool(self.game,self.repo,{}, {'method':'shortfuse'})

    def test_neural_pipeline_failure_does_not_leave_a_partial_consumer(self):
        from optidx_desktop.neural import deploy_tool
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        consumer=self.root/'renodx-dlss.addon64';consumer.write_bytes(pe_fixture())
        sr=self.zip({'nvngx_dlss.dll':pe_fixture()},'sr.zip')
        nr=self.zip({'wrong.dll':pe_fixture()},'nr.zip')
        with self.assertRaises(ValueError):deploy_tool(self.game,self.repo,{}, {'method':'shortfuse','sources':{'consumer':{'path':str(consumer)},'dlss':{'path':str(sr)},'dlssnr':{'path':str(nr)}}})
        self.assertFalse((self.binary/'renodx-dlss.addon64').exists())
        self.assertFalse((self.binary/'nvngx_dlss.dll').exists())

    def test_layered_root_and_binary_dll_ownership_restore_in_correct_order(self):
        from optidx_desktop.features import remove_all_assets
        path=self.binary/'nvngx_dlssnr.dll';path.write_bytes(b'game original')
        assets.deploy(self.game.root,'dll:base',{'Binaries/Win64/nvngx_dlssnr.dll':b'sdk'},allow_foreign=True)
        assets.deploy(self.binary,'neural:overlay',{'nvngx_dlssnr.dll':b'proxy'},allow_foreign=True)
        remove_all_assets(self.game)
        self.assertEqual(path.read_bytes(),b'game original')

    def test_gpu_templates_are_editable_and_preserve_helix_and_framegen_paths(self):
        from optidx_desktop.templates import template_path,apply
        path=template_path(self.repo,'amd-dlss-nightly');path.parent.mkdir(parents=True)
        path.write_text('[Spoofing]\nDxgi=false\n[Libraries]\nFfxDx12Path=bad\n[FrameGen]\nEnabled=false\n')
        ini=self.binary/'OptiScaler.ini';ini.write_text('[Libraries]\nFfxDx12Path=my-helix\n[FrameGen]\nEnabled=true\n[Other]\nUser=keep\n')
        apply(self.game,self.repo,{'id':'amd-dlss-nightly'})
        self.assertIn('FfxDx12Path=my-helix',ini.read_text())
        self.assertIn('Enabled=true',ini.read_text())
        self.assertIn('Dxgi=false',ini.read_text())
        self.assertIn('User=keep',ini.read_text())

    def test_feeder_prepares_motion_shaders_and_ordered_preset(self):
        from optidx_desktop.neural import deploy_tool
        reshade=bytearray(pe_fixture());reshade[1600:1608]=b'\xbd\x04\xef\xfe\x00\x00\x01\x00'
        struct.pack_into('<II',reshade,1608,(6<<16)|8,0)
        (self.binary/'d3d12-ReShade64.dll').write_bytes(reshade)
        consumer=self.root/'renodx-dlss5.addon64';consumer.write_bytes(pe_fixture())
        feeder=self.zip({'dlss5-feed.addon64':pe_fixture(),'Shaders/DLSS5_Feed.fx':b'technique DLSS5_Feed { }'},'feed.zip')
        headers=self.zip({'Shaders/ReShade.fxh':b'header','Shaders/Base.fx':b'technique Base { }'},'headers.zip')
        motion=self.zip({'Shaders/Kernel.fx':b'technique Kernel20 { }'},'motion.zip')
        sr=self.zip({'nvngx_dlss.dll':pe_fixture()},'sr.zip');nr=self.zip({'nvngx_dlssnr.dll':pe_fixture()},'nr.zip')
        sources={k:{'path':str(v)} for k,v in {'consumer':consumer,'feeder':feeder,'CrosireMaster':headers,'LumeniteFX':motion,'dlss':sr,'dlssnr':nr}.items()}
        deploy_tool(self.game,self.repo,{}, {'method':'feeder','sources':sources})
        preset=(self.binary/'OptiDX-presets/neural-feeder.ini').read_text()
        self.assertIn('DLSS5_MV_PROVIDER=3',preset)
        self.assertIn('Kernel20@Kernel.fx,DLSS5_Feed@DLSS5_Feed.fx',preset)
        self.assertTrue((self.binary/'renodx-dlss5.addon64').is_file())
        self.assertTrue((self.binary/'dlss5-feed.addon64').is_file())

    def test_bridge_uses_neural_consumer_instead_of_shortfuse_consumer(self):
        from optidx_desktop.neural import deploy_tool
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        consumer=self.root/'renodx-dlss5.addon64';consumer.write_bytes(pe_fixture())
        bridge=self.root/'dlss5-bridge.addon64';bridge.write_bytes(pe_fixture())
        sr=self.zip({'nvngx_dlss.dll':pe_fixture()},'sr.zip');nr=self.zip({'nvngx_dlssnr.dll':pe_fixture()},'nr.zip')
        sources={k:{'path':str(v)} for k,v in {'consumer':consumer,'bridge':bridge,'dlss':sr,'dlssnr':nr}.items()}
        deploy_tool(self.game,self.repo,{'api_override':'DX11'}, {'method':'bridge','sources':sources})
        self.assertTrue((self.binary/'renodx-dlss5.addon64').exists())
        self.assertFalse((self.binary/'renodx-dlss.addon64').exists())

    def test_checked_backend_addon_download_never_copies_wrong_architecture(self):
        from optidx_desktop.backend import load_backend
        from optidx_desktop.channels import configure_backend
        module=load_backend();module.TMP_DIR=str(self.root)
        def fake(url,destination,tries=3):
            Path(destination).write_bytes(pe_fixture());return True
        module.fetch_payload=fake
        configure_backend(module,self.game,self.repo,{'bits_override':'32'})
        destination=self.binary/'renodx-game.addon32'
        self.assertFalse(module.fetch_payload('https://example.com/mod',str(destination)))
        self.assertFalse(destination.exists())

    def test_automatic_neural_and_cost_scaler_share_one_restorable_owner(self):
        from optidx_desktop.neural import deploy_tool,cost_scaler
        (self.binary/'d3d12-ReShade64.dll').write_bytes(pe_fixture())
        consumer=self.root/'renodx-dlss.addon64';consumer.write_bytes(pe_fixture())
        sr=self.zip({'nvngx_dlss.dll':pe_fixture()},'sr.zip');nr=self.zip({'nvngx_dlssnr.dll':pe_fixture()+b'real'},'nr.zip')
        proxy=self.zip({'nvngx_dlssnr.dll':pe_fixture()+b'proxy','nvngx_dlssnr.ini':b'[DLSSNR_Proxy]\nResolutionScale=1\n'},'proxy.zip')
        options={'method':'shortfuse','sources':{k:{'path':str(v)} for k,v in {'consumer':consumer,'dlss':sr,'dlssnr':nr}.items()}}
        deploy_tool(self.game,self.repo,{},options)
        cost_scaler(self.game,self.repo,{}, {'source':{'path':str(proxy)}})
        group='neural:pipeline:Binaries/Win64'
        self.assertEqual(set(assets.state(self.game.root)['groups']),{group})
        deploy_tool(self.game,self.repo,{},options)
        self.assertEqual((self.binary/'nvngx_dlssnr.dll').read_bytes(),pe_fixture()+b'proxy')
        assets.remove(self.game.root,group)
        self.assertFalse((self.binary/'nvngx_dlssnr.dll').exists())
        self.assertFalse((self.binary/'nvngx_dlssnr_real.dll').exists())

    def test_standalone_reshade_enables_and_restores_optiscaler_loader(self):
        from optidx_desktop.channels import install_reshade,restore_loader_settings
        ini=self.binary/'OptiScaler.ini';ini.write_text('[Plugins]\nLoadReshade=auto\nOther=keep\n')
        dll=self.root/'ReShade64.dll';dll.write_bytes(pe_fixture())
        install_reshade(self.game,self.repo,{'reshade_channel':'custom','reshade_custom':str(dll),'components':{'reshade':True}})
        self.assertIn('LoadReshade=true',ini.read_text())
        restore_loader_settings(self.game)
        self.assertIn('LoadReshade=auto',ini.read_text())
        self.assertIn('Other=keep',ini.read_text())

    def test_dll_only_optiscaler_build_gets_a_minimal_tracked_ini(self):
        from optidx_desktop.backend import load_backend
        from optidx_desktop.channels import configure_backend
        module=load_backend()
        module.install_optiscaler=lambda:(self.binary/'dxgi.dll').write_bytes(pe_fixture()+b'OptiScaler')
        configure_backend(module,self.game,self.repo,{})
        module.install_optiscaler()
        ini=self.binary/'OptiScaler.ini'
        self.assertTrue(ini.exists())
        self.assertIn('LoadReshade=true',ini.read_text())
        self.assertIn('FfxDx12Path=auto',ini.read_text())
        self.assertIn('OptiScaler.ini',module.INSTALLED_FILES)


if __name__=='__main__':unittest.main()
