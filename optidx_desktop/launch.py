"""Saved Wine/Proton launch profiles, per-game environment and HDR lifetime."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys

from .runtime import external_environment, appimage_arguments
from .storage import read_json, data_dir

# Named DRS settings are passed to DXVK-NVAPI, not written into Windows driver
# profiles. Availability depends on the runner's DXVK-NVAPI and the actual GPU.
DRS_CHOICES = {
    'NGX_DLSS_SR_OVERRIDE': ['OFF', 'ON'],
    'NGX_DLSS_RR_OVERRIDE': ['OFF', 'ON'],
    'NGX_DLSS_FG_OVERRIDE': ['OFF', 'ON'],
    'NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION': ['RENDER_PRESET_' + x for x in ['LATEST'] + list('ABCDEFGHIJKLMNO')],
    'NGX_DLSS_RR_OVERRIDE_RENDER_PRESET_SELECTION': ['RENDER_PRESET_' + x for x in ['LATEST'] + list('DEFGHIJKLMNO')],
    'NGX_DLSS_FG_OVERRIDE_RENDER_PRESET_SELECTION': ['RENDER_PRESET_' + x for x in ['LATEST', 'A', 'B']],
    'NGX_DLSSG_MODE': ['OFF', 'ON', 'DYNAMIC'],
    'NGX_DLSSG_MULTI_FRAME_COUNT': [str(n) for n in range(1, 6)],
    'NGX_DLSSG_DYNAMIC_MULTI_FRAME_COUNT_MAX': [str(n) for n in range(1, 6)],
}


def environment_overrides(values):
    if not isinstance(values, dict):
        raise ValueError('Environment must be a JSON object')
    result = {}
    for key, value in values.items():
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key) or '\0' in str(value):
            raise ValueError('Invalid environment variable')
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError('Environment values must be strings or numbers')
        result[key] = '1' if value is True else '0' if value is False else str(value)
    return result


def profile_environment(profile, base=None):
    env = dict(base if base is not None else external_environment())
    env.update(environment_overrides(profile.get('environment', {})))
    for key, value in profile.get('drs', {}).items():
        if key not in DRS_CHOICES or str(value) not in DRS_CHOICES[key]:
            raise ValueError('Unsupported DXVK-NVAPI setting: ' + key)
        env['DXVK_NVAPI_DRS_' + key] = str(value)
    for part in ('SR', 'RR'):
        scale = profile.get('dlss_' + part.lower() + '_scale')
        if scale:
            if not 33 <= int(scale) <= 100:
                raise ValueError('DLSS scale must be between 33 and 100')
            env['DXVK_NVAPI_DRS_NGX_DLSS_' + part + '_MODE'] = 'CUSTOM'
            env['DXVK_NVAPI_DRS_NGX_DLSS_' + part + '_OVERRIDE_SCALING_RATIO'] = str(int(scale))
    target = profile.get('mfg_target')
    if target:
        if not 20 <= int(target) <= 1000:
            raise ValueError('Dynamic MFG target is out of range')
        env['DXVK_NVAPI_DRS_NGX_DLSSG_DYNAMIC_TARGET_FRAME_RATE'] = str(int(target))
    dxvk = []
    if profile.get('dxvk_vsync') in {'0','1'}:
        dxvk += ['dxgi.syncInterval = '+profile['dxvk_vsync'], 'd3d9.presentInterval = '+profile['dxvk_vsync']]
    if profile.get('fps_limit'):
        if not 1 <= int(profile['fps_limit']) <= 1000:
            raise ValueError('Frame-rate limit must be between 1 and 1000')
        dxvk += ['dxgi.maxFrameRate = '+str(int(profile['fps_limit'])), 'd3d9.maxFrameRate = '+str(int(profile['fps_limit']))]
    if dxvk:
        env['DXVK_CONFIG'] = (env.get('DXVK_CONFIG','')+';' if env.get('DXVK_CONFIG') else '') + ';'.join(dxvk)
    for key, name in [('gl_vsync','__GL_SYNC_TO_VBLANK'),('gl_gsync','__GL_GSYNC_ALLOWED')]:
        if profile.get(key) in {'0','1'}:env[name] = profile[key]
    if profile.get('gl_shader_cache_mb'):
        if not 1 <= int(profile['gl_shader_cache_mb']) <= 65536:
            raise ValueError('OpenGL shader cache size must be between 1 and 65536 MiB')
        env['__GL_SHADER_DISK_CACHE_SIZE'] = str(int(profile['gl_shader_cache_mb']) * 1024 * 1024)
    prefix = profile.get('prefix')
    if prefix:
        env['WINEPREFIX'] = prefix
        if profile.get('runner_kind') == 'proton':
            location = Path(prefix).expanduser()
            env['STEAM_COMPAT_DATA_PATH'] = str(location.parent if location.name == 'pfx' else location)
            env.setdefault('STEAM_COMPAT_CLIENT_INSTALL_PATH', str(Path.home() / '.local/share/Steam'))
    for key in ('PROTON_ENABLE_HDR', 'PROTON_ENABLE_WAYLAND', 'DXVK_NVAPI_VKREFLEX', 'PROTON_ENABLE_NGX_UPDATER'):
        if profile.get(key) is not None:
            env[key] = '1' if profile[key] else '0'
    if profile.get('vkbasalt'):
        if not vkbasalt_available():
            raise ValueError('Install the native vkBasalt Vulkan layer before enabling it')
        env['ENABLE_VKBASALT'] = '1'
        if profile.get('vkbasalt_config'):
            env['VKBASALT_CONFIG_FILE'] = profile['vkbasalt_config']
    if profile.get('dxvk_native_overrides'):
        new = 'd3d9,d3d10core,d3d11,dxgi=n,b'
        env['WINEDLLOVERRIDES'] = new + (';' + env['WINEDLLOVERRIDES'] if env.get('WINEDLLOVERRIDES') else '')
    return env


def vkbasalt_available():
    roots = [Path('/usr/share/vulkan/implicit_layer.d'), Path('/etc/vulkan/implicit_layer.d'),
             Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'vulkan/implicit_layer.d']
    return any(list(root.glob('*[Bb]asalt*.json')) for root in roots)


def hdr_outputs():
    if not shutil.which('kscreen-doctor') or 'KDE' not in os.environ.get('XDG_CURRENT_DESKTOP', '').upper():
        return []
    result = subprocess.run(['kscreen-doctor', '-j'], capture_output=True, text=True, timeout=10,
                            env=external_environment())
    if result.returncode:
        return []
    return [{'name': o['name'], 'id': o['id'], 'enabled': bool(o.get('hdrEnabled', False)),
             'capable': bool(o.get('capabilities', 0) & 8)} for o in json.loads(result.stdout).get('outputs', [])]


def set_hdr(output, enabled):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', output):
        raise ValueError('Invalid display name')
    subprocess.run(['kscreen-doctor', f'output.{output}.hdr.' + ('enable' if enabled else 'disable')],
                   check=True, timeout=15, env=external_environment())


def runner_command(game, profile):
    kind = profile.get('runner_kind', 'wine')
    if game.store == 'Bottles' and not profile.get('runner_command'):
        command = ['bottles-cli'] if shutil.which('bottles-cli') else ['flatpak','run','--command=bottles-cli','com.usebottles.bottles']
        return command + ['run','-b',game.runner,'-p',game.app_id]
    command = shlex.split(profile.get('runner_command', ''))
    if not command:
        raise ValueError('Choose a Wine, Proton, or UMU runner command first')
    if kind == 'proton':
        command += ['run']
    command.append(profile.get('launch_executable') or game.executable)
    return command


def run_profile(profile_path, command):
    profile = read_json(profile_path, None)
    if profile is None or not command:
        raise ValueError('A saved profile and launch command are required')
    env = profile_environment(profile)
    finish_deferred_hdr(profile_path, profile)
    # Parameters are argv, never evaluated by a shell.
    arguments = shlex.split(profile.get('launch_arguments', ''))
    if profile.get('runner_kind') == 'bottles':
        if arguments:command += ['-a', shlex.join(arguments)]
    else:
        command += arguments
    if profile.get('gamescope'):
        if not shutil.which('gamescope'):
            raise ValueError('Install gamescope before enabling it')
        options = ['gamescope'] + shlex.split(profile.get('gamescope_arguments', ''))
        command = options + ['--'] + command
    output = profile.get('hdr_output') if profile.get('auto_hdr') else None
    lock = None
    previous = None
    if output:
        lock_path = data_dir() / 'locks' / 'hdr.lock'
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = lock_path.open('w')
        # Do not switch off HDR while another managed HDR game is running.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = next((o for o in hdr_outputs() if o['name'] == output), None)
        if info is None:
            lock.close()
            raise ValueError('The selected KDE HDR output is unavailable')
        if info.get('capable') is False:
            lock.close()
            raise ValueError('The selected display does not advertise HDR support')
        previous = info['enabled']
    try:
        if output and not previous:
            set_hdr(output, True)
        process = subprocess.Popen(command, env=env, start_new_session=True)
        old_handlers = {}
        for number in (signal.SIGTERM, signal.SIGINT):
            old_handlers[number] = signal.signal(number, lambda signum, frame: os.killpg(process.pid, signum))
        try:
            return process.wait()
        finally:
            for number, handler in old_handlers.items():
                signal.signal(number, handler)
    finally:
        if output and previous is not None and not previous:
            set_hdr(output, False)
        if lock:
            lock.close()


def wrapper_options(profile_path):
    image = os.environ.get('APPIMAGE')
    command = [str(Path(image).resolve()), *appimage_arguments(), '--launch-profile', str(profile_path)] if image else [
        sys.executable, str(Path(__file__).resolve().parents[1] / 'launcher.py'), '--profile', str(profile_path)]
    return shlex.join(command + ['--']) + ' %command%'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    return run_profile(args.profile, args.command[1:] if args.command[:1] == ['--'] else args.command)


def finish_deferred_hdr(profile_path, profile):
    from .storage import Repository
    repository=Repository(Path(profile_path).resolve().parent.parent)
    game=next((g for g in repository.games() if g.id == Path(profile_path).stem),None)
    if not game or not (game.target/'.optidx-ue-hdr.json').exists():return
    from .backend import load_backend, configure_environment
    module=load_backend()
    before=os.environ.copy()
    try:
        configure_environment(game,profile)
        module.DISABLE_UE_HDR=not profile.get('native_hdr',True)
        module.configure_ue_hdr(game.target)
    finally:
        os.environ.clear();os.environ.update(before)


if __name__ == '__main__':
    raise SystemExit(main())
