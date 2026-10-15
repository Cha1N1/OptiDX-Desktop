"""API-specific ReShade and DXVK deployment and backend channel overrides."""
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlparse

from . import assets
from .downloads import Client, archive_files, binary_member, sha
from .features import payload
from .inspection import inspect_game, manifest_paths, contained
from .storage import atomic_json, read_json


def effective_api(game, preferences):
    override = preferences.get('api_override', '')
    if override:
        return override
    apis = inspect_game(game)['apis']
    return next((a for a in ['DX12', 'DX11', 'DX10', 'DX9', 'DX8', 'Vulkan', 'OpenGL', 'DXGI'] if a in apis), 'DX12')


def reshade_source(preferences, bits, client):
    channel = preferences.get('reshade_channel', 'stable')
    if channel == 'custom':
        return {'path': preferences.get('reshade_custom', ''), 'version': 'Custom'}
    if channel == 'nightly':
        return {'url': f'https://nightly.link/crosire/reshade/workflows/build/main/ReShade%20({bits}-bit).zip'}
    if channel == 'legacy':
        version = preferences.get('reshade_version', '')
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('Choose a ReShade version such as 6.7.3')
    else:
        page = client.fetch('https://reshade.me', refresh=True).read_text(errors='replace')
        match = re.search(r'/downloads/ReShade_Setup_(\d+\.\d+\.\d+)_Addon\.exe', page)
        if not match:
            raise ValueError('Could not determine the current official ReShade release')
        version = match[1]
    suffix = '' if channel == 'no_addons' else '_Addon'
    return {'url': f'https://reshade.me/downloads/ReShade_Setup_{version}{suffix}.exe', 'version': version}


def prepare_reshade(game, repository, preferences):
    bits = int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    api = effective_api(game, preferences)
    if api == 'Vulkan':
        raise ValueError('ReShade Vulkan addons require a Wine Vulkan-layer adapter. Use the Linux vkBasalt controls for shader effects.')
    if api == 'DX8':
        raise ValueError('DX8 needs a translation layer first; select DX9 after configuring your game runner')
    client = Client(repository.directory)
    source = reshade_source(preferences, bits, client)
    path, metadata = payload(client, source, preferences.get('reshade_channel') == 'nightly')
    files = {f'ReShade{bits}.dll': path.read_bytes()} if source.get('path') and path.suffix.lower() == '.dll' else archive_files(path)
    data = binary_member(files, f'ReShade{bits}.dll', bits)
    coexist = bits == 64 and inspect_game(game)['components']['OptiScaler']
    selected = preferences.get('components', {}).get('optiscaler', False)
    coexist = coexist or (bits == 64 and selected)
    storage = 'd3d12-ReShade64.dll' if bits == 64 else 'ReShade32.dll'
    proxy = preferences.get('proxy_override') or {'DX9': 'd3d9.dll', 'OpenGL': 'opengl32.dll'}.get(api, 'dxgi.dll')
    if proxy not in {'dxgi.dll', 'd3d9.dll', 'opengl32.dll', 'd3d11.dll', 'd3d12.dll', 'winmm.dll', 'version.dll', 'winhttp.dll'}:
        raise ValueError('Unsupported proxy filename')
    result = {storage: data}
    if not coexist:
        result[proxy] = data
    return result, {**metadata, 'channel': preferences.get('reshade_channel', 'stable'), 'kind': 'reshade', 'api': api, 'bits': bits}


def install_reshade(game, repository, preferences):
    files, metadata = prepare_reshade(game, repository, preferences)
    result=assets.deploy(game.target, 'channel:reshade', files, metadata, preferences.get('allow_foreign', False))
    loader_settings(game, {'LoadReshade':'true'})
    return result


def configure_backend(module, game, repository, preferences):
    """Override independent install functions while keeping OptiDX ownership."""
    if preferences.get('optiscaler_channel'):
        channel = preferences['optiscaler_channel']
        if channel == 'custom':
            path = Path(preferences.get('optiscaler_custom', '')).expanduser().resolve()
            if not path.is_file():
                raise ValueError('Select an OptiScaler archive for the Custom channel')
            archive_files(path)
            module.optiscaler_urls = lambda: [path.as_uri()]
            original = module.download_file
            def local_download(url, destination, tries=2):
                if urlparse(url).scheme == 'file':
                    shutil.copyfile(unquote(urlparse(url).path), destination)
                    return True
                return original(url, destination, tries)
            module.download_file = local_download
        else:
            repo = preferences.get('optiscaler_repo') or ('optiscaler/OptiScaler' if channel == 'stable' else module.REPO_OPTISCALER)
            selected_release = []
            def urls():
                if not selected_release:
                    selected_release.append(Client(repository.directory).release_asset(repo, r'\.7z$', channel,
                                preferences.get('optiscaler_tag', ''), module.FORCE_UPDATE))
                release = selected_release[0]
                record_version(game, 'optiscaler', {**release, 'channel': channel})
                return [release['browser_download_url']]
            module.optiscaler_urls = urls
    bits = int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    original_payload = module.fetch_payload
    def checked_payload(url, output, tries=3):
        if output is not None and Path(output).suffix.lower() in {'.addon32','.addon64','.addon'}:
            suffix=Path(output).suffix.lower()
            if suffix in {'.addon32','.addon64'} and not suffix.endswith(str(bits)):
                module.warn('Skipped an addon for the wrong architecture: '+str(output))
                return False
            import tempfile
            from .inspection import compatible_binary
            fd,pending=tempfile.mkstemp(dir=module.TMP_DIR or None)
            os.close(fd)
            try:
                if not original_payload(url,pending,tries):return False
                if not compatible_binary(pending, bits):
                    module.warn('Addon PE architecture does not match this game')
                    return False
                shutil.copyfile(pending,output)
                return True
            finally:
                Path(pending).unlink(missing_ok=True)
        return original_payload(url,output,tries)
    module.fetch_payload=checked_payload
    if bits != 64 or effective_api(game,preferences) not in {'DX11','DX12','DXGI'}:
        module.install_engine_fallback=lambda:None
    if bits == 32:
        module.RESHADE_DLL_NAME = module.RESHADE_LEGACY_DLL_NAME = 'ReShade32.dll'
    if preferences.get('reshade_channel') or preferences.get('api_override') or preferences.get('bits_override') or bits == 32:
        def install():
            files, metadata = prepare_reshade(game, repository, preferences)
            owned = set(manifest_paths(game.target))
            allow = preferences.get('allow_foreign', False)
            owns_assets = 'channel:reshade' in assets.state(game.target)['groups']
            if owns_assets:
                assets.deploy(game.target, 'channel:reshade', files, metadata, allow)
            for name, data in files.items():
                path = contained(game.target, name)
                if path.is_symlink():
                    raise assets.Conflict('Proxy is a symlink: ' + name)
                if path.exists() and not owns_assets and name not in owned and path.read_bytes() != data and not allow:
                    raise assets.Conflict('Existing DLL needs explicit replacement approval: ' + name)
            for name, data in files.items():
                assets.atomic_bytes(game.target / name, data)
                module.track(name)
            record_version(game, 'reshade', metadata)
        module.install_reshade = install
    original_optiscaler = module.install_optiscaler
    def guarded_optiscaler():
        path = game.target / module.QUIRK_OPTISCALER_DLL
        if path.is_symlink():
            raise assets.Conflict('Injection DLL is a symlink: ' + path.name)
        if path.is_file() and path.name not in manifest_paths(game.target) and not preferences.get('allow_foreign'):
            # An existing installation of the same component can be updated.
            data = path.read_bytes()
            if b'OptiScaler' not in data and 'OptiScaler'.encode('utf-16-le') not in data:
                raise assets.Conflict('Existing injection DLL belongs to another tool: ' + path.name)
        result=original_optiscaler()
        ini=game.target/'OptiScaler.ini'
        if path.is_file() and not ini.exists():
            # DLL-only nightly archives rely on OptiScaler defaults. Seed only
            # known loader/default keys so prepared HelixSR can configure paths.
            assets.atomic_bytes(ini,b'[Upscalers]\nDx11Upscaler=auto\nDx12Upscaler=auto\n[FrameGen]\nEnabled=auto\n[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n[Plugins]\nLoadReshade=true\n')
            module.track('OptiScaler.ini')
        return result
    module.install_optiscaler = guarded_optiscaler
    if preferences.get('proxy_override'):
        original_quirks = module.resolve_game_quirks
        def quirks():
            original_quirks()
            module.QUIRK_OPTISCALER_DLL = preferences['proxy_override']
        module.resolve_game_quirks = quirks
    if preferences.get('wiki_name'):
        original_detect = module.detect_game
        def detect():
            result = original_detect()
            module.GAME_KEY = module.norm(preferences['wiki_name'])
            module.add_candidate_title(preferences['wiki_name'])
            return result
        module.detect_game = detect
    if preferences.get('force_ue_extended'):
        module.find_renodx_mod = lambda: None


def record_version(game, component, value):
    path = game.target / '.optidx-desktop-versions.json'
    data = read_json(path, {})
    data[component] = value
    atomic_json(path, data)


def install_dxvk(game, repository, preferences, options):
    api = effective_api(game, preferences)
    if api not in {'DX9', 'DX10', 'DX11', 'DXGI'}:
        raise ValueError('DXVK deployment supports DX9, DX10 and DX11')
    if inspect_game(game)['components']['OptiScaler']:
        raise ValueError('Custom DXVK and OptiScaler proxy chaining requires a game-specific adapter; keep the runner DXVK with OptiScaler')
    client = Client(repository.directory)
    source = options.get('source') or {'repo': 'doitsujin/dxvk', 'pattern': r'\.tar\.gz$',
                                     'channel': 'stable', 'tag': options.get('tag', '')}
    path, metadata = payload(client, source)
    files = archive_files(path)
    bits = int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    names = {'DX9': ['d3d9.dll'], 'DX10': ['d3d10core.dll', 'd3d11.dll', 'dxgi.dll'],
             'DX11': ['d3d11.dll', 'dxgi.dll'], 'DXGI': ['d3d11.dll', 'dxgi.dll']}[api]
    result = {n: binary_member(files, n, bits) for n in names}
    return assets.deploy(game.target, 'extra:dxvk', result, {**metadata, 'kind': 'dxvk'}, preferences.get('allow_foreign', False))


def record_installed_versions(module, game, preferences):
    from .inspection import file_version
    versions=read_json(game.target/'.optidx-desktop-versions.json',{})
    selected=module.COMPONENT_SELECTION or set()
    if 'optiscaler' in selected and not preferences.get('optiscaler_channel'):
        data=read_json(module.CACHE_DIR/'optiscaler_nightly.json',{})
        if data:
            version=file_version(game.target/module.QUIRK_OPTISCALER_DLL)
            versions['optiscaler']={'version':data.get('tag_name'), 'binary_version':version,
                         'repository':module.REPO_OPTISCALER,'channel':'nightly',
                         'id':next((a.get('id') for a in data.get('assets',[]) if a.get('name','').endswith('.7z')),None),
                         'updated_at':next((a.get('updated_at') for a in data.get('assets',[]) if a.get('name','').endswith('.7z')),None)}
    for key,files in [('reshade',[module.RESHADE_DLL_NAME]),('renodx',list(game.target.glob('renodx-*.addon*'))),('luma',list(game.target.glob('*.addon')))]:
        if key in selected:
            names=[Path(p) if Path(p).is_absolute() else game.target/p for p in files]
            existing=[p for p in names if p.is_file()]
            if existing:
                item=versions.setdefault(key,{})
                item['binary_versions']={p.name:file_version(p) for p in existing}
                item['files']={p.name:sha(p.read_bytes()) for p in existing}
    if 'luma' in selected:
        release=read_json(module.CACHE_DIR/'luma_release.json',{})
        if release:versions.setdefault('luma',{})['version']=release.get('tag_name')
    if versions:atomic_json(game.target/'.optidx-desktop-versions.json',versions)


def loader_settings(game, values):
    from .features import ini_edit
    from .backend import load_backend
    ini=game.target/'OptiScaler.ini'
    if not ini.is_file():return
    module=load_backend()
    data=ini.read_bytes();text=data.decode(module.hdr_ini_encoding(data))
    old=module.hdr_ini_values(text,'Plugins')
    journal_path=game.target/'.optidx-desktop-loader.json'
    journal=read_json(journal_path,{'mode':ini.stat().st_mode&0o777,'values':{}})
    for key,value in values.items():
        record=journal['values'].setdefault(key,{'original':old.get(key.casefold())})
        record['applied']=value
    atomic_json(journal_path,journal)
    assets.atomic_bytes(ini,ini_edit(data,{'Plugins':values}),ini.stat().st_mode&0o777)


def restore_loader_settings(game):
    from .backend import load_backend
    path=game.target/'.optidx-desktop-loader.json'
    journal=read_json(path,{})
    if not journal:return
    ini=game.target/'OptiScaler.ini'
    if ini.is_file():
        module=load_backend();data=ini.read_bytes();encoding=module.hdr_ini_encoding(data);text=data.decode(encoding)
        current=module.hdr_ini_values(text,'Plugins')
        changes={key:record['original'] for key,record in journal['values'].items() if current.get(key.casefold())==record['applied']}
        assets.atomic_bytes(ini,module.edit_hdr_ini(text,'Plugins',changes).encode(encoding),journal['mode'])
    path.unlink(missing_ok=True)
