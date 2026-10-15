import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from optidx_desktop.backend import launch_options
from optidx_desktop.runtime import external_environment, python_executable
from optidx_desktop.runtime import open_game_uri
from optidx_desktop.models import Game


class RuntimeTests(unittest.TestCase):
    def test_gui_prefers_wayland_without_changing_external_environment(self):
        from optidx_desktop.runtime import gui_arguments
        environment = {'WAYLAND_DISPLAY': 'wayland-0', 'DISPLAY': ':1', 'XDG_SESSION_TYPE': 'wayland'}
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(gui_arguments('optidx'), ['optidx', '-platform', 'wayland;xcb'])
            self.assertEqual(external_environment(), environment)

    def test_nemo_fallback_list_prefers_wayland_without_leaking_to_launchers(self):
        from optidx_desktop.runtime import gui_arguments
        environment = {'QT_QPA_PLATFORM': 'xcb;wayland', 'WAYLAND_DISPLAY': 'wayland-0',
                       'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':1'}
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(gui_arguments('optidx'), ['optidx', '-platform', 'wayland;xcb'])
            self.assertEqual(external_environment(), environment)
        with patch.dict(os.environ, {**environment, 'OPTIDX_APPIMAGE_CONTEXT': '1'}, clear=True):
            gui_arguments('optidx')
            self.assertEqual(external_environment()['QT_QPA_PLATFORM'], 'xcb;wayland')

    def test_platform_list_keeps_options_and_other_choices(self):
        from optidx_desktop.runtime import gui_arguments
        for before, after in [('xcb:foo=1;wayland:bar=2', 'wayland:bar=2;xcb:foo=1'),
                              ('offscreen;xcb;wayland-egl;wayland', 'offscreen;wayland-egl;wayland;xcb')]:
            with self.subTest(before=before), patch.dict(os.environ, {
                    'WAYLAND_DISPLAY': 'wayland-0', 'QT_QPA_PLATFORM': before}, clear=True):
                self.assertEqual(gui_arguments('optidx'), ['optidx', '-platform', after])
        for environment in [{'QT_QPA_PLATFORM': 'xcb;wayland', 'XDG_SESSION_TYPE': 'x11'},
                            {'QT_QPA_PLATFORM': 'wayland;xcb', 'WAYLAND_DISPLAY': 'wayland-0'},
                            {'QT_QPA_PLATFORM': 'wayland;minimal;xcb', 'WAYLAND_DISPLAY': 'wayland-0'},
                            {'QT_QPA_PLATFORM': 'xcb;offscreen', 'WAYLAND_DISPLAY': 'wayland-0'}]:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(gui_arguments('optidx'), ['optidx'])

    def test_explicit_platform_and_x11_defaults_are_preserved(self):
        from optidx_desktop.runtime import gui_arguments
        for platform in ['xcb', 'wayland', 'offscreen', 'minimal']:
            with self.subTest(platform=platform), patch.dict(os.environ, {
                    'WAYLAND_DISPLAY': 'wayland-0', 'QT_QPA_PLATFORM': platform}, clear=True):
                self.assertEqual(gui_arguments('optidx'), ['optidx'])
                self.assertEqual(os.environ['QT_QPA_PLATFORM'], platform)
        with patch.dict(os.environ, {'DISPLAY': ':0', 'XDG_SESSION_TYPE': 'x11'}, clear=True):
            self.assertEqual(gui_arguments('optidx'), ['optidx'])
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}, clear=True):
            self.assertEqual(gui_arguments('optidx'), ['optidx', '-platform', 'wayland;xcb'])

    def test_flatpak_heroic_uses_its_own_installation_even_with_native_heroic_present(self):
        game = Game('test', 'Example', 'Heroic', '/games', launcher_kind='flatpak',
                    launch_uri='heroic://launch?appName=test&runner=legendary')
        with patch('optidx_desktop.runtime.shutil.which', side_effect=lambda name, **kw: '/usr/bin/' + name), \
                patch('optidx_desktop.runtime.subprocess.Popen') as popen:
            open_game_uri(game)
        self.assertEqual(popen.call_args.args[0], ['/usr/bin/flatpak', 'run', 'com.heroicgameslauncher.hgl', '--no-gui', game.launch_uri])
    def test_native_heroic_uses_host_command_and_preserves_uri_as_one_argument(self):
        game = Game('heroic-game', 'Example', 'Heroic', '/games',
                    launch_uri='heroic://launch?appName=game%20name&runner=sideload')
        environment = {'OPTIDX_APPIMAGE_CONTEXT': '1', 'PATH': '/bundle/bin:/usr/bin',
                       'OPTIDX_ORIG_PATH_SET': '1', 'OPTIDX_ORIG_PATH': '/usr/bin',
                       'APPIMAGE': '/tmp/OptiDX.AppImage', 'WAYLAND_DISPLAY': 'wayland-0'}
        with patch.dict(os.environ, environment, clear=True), \
                patch('optidx_desktop.runtime.shutil.which', return_value='/usr/bin/heroic') as which, \
                patch('optidx_desktop.runtime.subprocess.Popen') as popen, \
                patch('optidx_desktop.runtime.open_url') as uri_handler:
            open_game_uri(game)
        which.assert_called_once_with('heroic', path='/usr/bin')
        self.assertEqual(popen.call_args.args[0], ['/usr/bin/heroic', '--no-gui', game.launch_uri])
        self.assertNotIn('APPIMAGE', popen.call_args.kwargs['env'])
        self.assertEqual(popen.call_args.kwargs['env']['WAYLAND_DISPLAY'], 'wayland-0')
        uri_handler.assert_not_called()

    def test_heroic_without_native_command_and_steam_keep_uri_dispatch(self):
        for store, uri in [('Heroic', 'heroic://launch?appName=test&runner=gog'), ('Steam', 'steam://rungameid/123')]:
            with self.subTest(store=store), \
                    patch('optidx_desktop.runtime.shutil.which', return_value=None), \
                    patch('optidx_desktop.runtime.subprocess.Popen') as popen, \
                    patch('optidx_desktop.runtime.open_url') as uri_handler:
                open_game_uri(Game('test', 'Example', store, '/games', launch_uri=uri))
            uri_handler.assert_called_once_with(uri)
            popen.assert_not_called()

    def test_host_environment_is_restored_for_game_and_launcher(self):
        environment = {
            "OPTIDX_APPIMAGE_CONTEXT": "1", "APPIMAGE": "/tmp/App.AppImage", "APPDIR": "/tmp/mount",
            "PATH": "/tmp/mount/usr/bin:/usr/bin", "PYTHONHOME": "/tmp/mount/usr",
            "PYTHONPATH": "/tmp/mount/app", "QT_PLUGIN_PATH": "/tmp/mount/plugins",
            "OPTIDX_ORIG_PATH_SET": "1", "OPTIDX_ORIG_PATH": "/host/bin:/usr/bin",
            "OPTIDX_ORIG_PYTHONHOME_SET": "0", "OPTIDX_ORIG_PYTHONPATH_SET": "1",
            "OPTIDX_ORIG_PYTHONPATH": "/host/python", "OPTIDX_ORIG_QT_PLUGIN_PATH_SET": "0",
            "PROTON_ENABLE_WAYLAND": "1", "WAYLAND_DISPLAY": "wayland-0", "WINEPREFIX": "/game/prefix",
        }
        with patch.dict(os.environ, environment, clear=True):
            result = external_environment()
        self.assertEqual(result["PATH"], "/host/bin:/usr/bin")
        self.assertEqual(result["PYTHONPATH"], "/host/python")
        self.assertNotIn("PYTHONHOME", result)
        self.assertNotIn("QT_PLUGIN_PATH", result)
        self.assertNotIn("APPIMAGE", result)
        self.assertFalse(any(k.startswith("OPTIDX_ORIG_") for k in result))
        self.assertEqual(result["PROTON_ENABLE_WAYLAND"], "1")
        self.assertEqual(result["WINEPREFIX"], "/game/prefix")

    def test_worker_uses_bundled_python_wrapper(self):
        with tempfile.TemporaryDirectory() as folder:
            wrapper = Path(folder) / "python3"
            wrapper.write_text("wrapper")
            with patch.dict(os.environ, {"OPTIDX_BUNDLED_PYTHON": str(wrapper)}):
                self.assertEqual(python_executable(), str(wrapper))

    def test_launch_options_reference_persistent_appimage_instead_of_mount(self):
        with patch.dict(os.environ, {"APPIMAGE": "/home/user/Apps/OptiDX Desktop.AppImage"}):
            options = launch_options({"components": {"reshade": True}})
        self.assertTrue(options.startswith("'/home/user/Apps/OptiDX Desktop.AppImage' --backend"))
        self.assertNotIn("backend/OptiDX.py", options)
        self.assertTrue(options.endswith(" %command%"))

    def test_fuse_free_launch_commands_keep_the_runtime_flag(self):
        from optidx_desktop.launch import wrapper_options
        from optidx_desktop.backend import launch_options
        from unittest.mock import patch
        import os
        with patch.dict(os.environ,{'APPIMAGE':'/tmp/OptiDX.AppImage','APPDIR':'/tmp/appimage_extracted_abc'}):
            self.assertIn('--appimage-extract-and-run',wrapper_options('/tmp/profile.json'))
            self.assertIn('--appimage-extract-and-run',launch_options({'components':{}}))


if __name__ == "__main__":
    unittest.main()
