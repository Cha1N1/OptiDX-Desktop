"""Portable feature operations used by GUI jobs and bulk updates."""
import configparser
import io
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile

from . import assets
from .catalog import catalogs, EXTRAS, DLSS_FILES, STREAMLINE_FILES, DLSS_MANIFEST, RHI_MANIFEST, game_data
from .downloads import Client, archive_files, binary_member, sha
from .inspection import contained, inspect_game, compatible_binary
from .storage import atomic_json, read_json

FEATURE_ACTIONS = {'import_asset', 'deploy_asset', 'remove_asset', 'toggle_asset', 'deploy_shader',
                   'shader_files', 'swap_dll', 'restore_dll', 'check_updates', 'refresh_catalogs', 'apply_display',
                   'deploy_extra', 'list_releases', 'install_reshade', 'install_dxvk', 'deploy_pipeline', 'import_url', 'deploy_catalog_addon', 'create_vkbasalt_config', 'edit_config', 'nr_cost_scaler', 'deploy_neural_tool', 'prepare_template', 'apply_template', 'remove_helixsr'}


def ini_edit(data, sections):
    # Preserve existing comments and unrelated settings through the backend's
    # line-based INI editor; ConfigParser validates imported presets separately.
    from .backend import load_backend
    module = load_backend()
    encoding = module.hdr_ini_encoding(data)
    text = data.decode(encoding)
    for section, values in sections.items():
        text = module.set_ini_values(text, section, values)
    return text.encode(encoding)


def validate_preset(data):
    text = data.decode('utf-8-sig')
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    # ReShade allows an unnamed top-level section.
    parser.read_string('[DEFAULT]\n' + text)
    if not ('Techniques' in parser.defaults() or any('Techniques' in parser[s] for s in parser.sections())):
        raise ValueError('This INI is not a ReShade preset (Techniques is missing)')
    return text


def shader_layout(files, key, selected=None):
    result = {}
    for name, data in files.items():
        parts = PurePosixPath(name).parts
        lower = [p.lower() for p in parts]
        suffix = PurePosixPath(name).suffix.lower()
        if 'shaders' in lower:
            tail = parts[lower.index('shaders') + 1:]
            category = 'Shaders'
        elif 'textures' in lower:
            tail = parts[lower.index('textures') + 1:]
            category = 'Textures'
        elif suffix in {'.fx', '.fxh', '.h', '.hlsl'}:
            tail = parts[1:] if len(parts) > 1 else parts
            category = 'Shaders'
        elif PurePosixPath(name).name.lower().startswith(('license', 'copying', 'notice')):
            tail, category = (PurePosixPath(name).name,), 'Licenses'
        else:
            continue
        if not tail:
            continue
        relative = '/'.join(tail)
        if category == 'Shaders' and suffix == '.fx' and selected is not None and relative not in selected:
            continue
        destination = f'reshade-shaders/OptiDX/{key}/{category}/{relative}'
        if destination in result and result[destination] != data:
            raise ValueError('Shader archive contains colliding files: ' + relative)
        result[destination] = data
    if not any(n.endswith('.fx') for n in result):
        raise ValueError('No selected ReShade effects found in this pack')
    return result


def import_asset(repository, path, kind='addon', label=''):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Select an existing file')
    data = path.read_bytes()
    key = sha(data)[:20]
    destination = repository.directory / 'custom' / key / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    assets.atomic_bytes(destination, data)
    if kind == 'preset':
        validate_preset(data)
    elif kind == 'shader':
        if path.suffix.lower() != '.fx':
            shader_layout(archive_files(path), key)
    elif kind == 'addon':
        files = {path.name: data} if path.suffix.lower() in {'.addon64', '.addon32', '.addon'} else archive_files(path)
        if not any(PurePosixPath(n).suffix.lower() in {'.addon64', '.addon32', '.addon'} for n in files):
            raise ValueError('No addon files in this package')
    elif kind != 'binary':
        raise ValueError('Unknown custom asset type')
    item = {'id': key, 'label': label or path.stem, 'kind': kind, 'path': str(destination), 'sha256': sha(data)}
    library = read_json(repository.directory / 'assets.json', {})
    library[key] = item
    atomic_json(repository.directory / 'assets.json', library)
    return item


def payload(client, source, refresh=False):
    if source.get('path'):
        path = Path(source['path'])
        if source.get('sha256') and sha(path.read_bytes()) != source['sha256']:
            raise ValueError('Custom asset changed after importing')
        return path, {'version': source.get('version', 'Custom'), 'source': source}
    if source.get('repo'):
        release = client.release_asset(source['repo'], source.get('pattern', r'\.zip$'),
                                       source.get('channel', 'stable'), source.get('tag', ''), refresh)
        return client.fetch(release['browser_download_url'], release.get('digest') or ''), {
            'version': release['version'], 'url': release['browser_download_url'], 'source': source,
            'digest': release.get('digest'), 'asset_id': release.get('id'), 'updated_at': release.get('updated_at')}
    if source.get('url'):
        match = re.fullmatch(r'https://github.com/([^/]+/[^/]+)/archive/refs/heads/(.+)\.zip', source['url'])
        if match:
            from urllib.parse import quote
            commit = client.metadata('https://api.github.com/repos/' + match[1] + '/commits/' + quote(match[2], safe=''), refresh)
            revision = commit.get('sha', '')
            if not re.fullmatch(r'[0-9a-f]{40}', revision):
                raise ValueError('Invalid upstream shader commit')
            path = client.fetch('https://github.com/' + match[1] + '/archive/' + revision + '.zip')
            return path, {'version': revision, 'url': source['url'], 'source': source, 'sha256': sha(path.read_bytes())}
        path = client.fetch(source['url'], source.get('sha256', ''), refresh=refresh)
        return path, {'version': source.get('version') or sha(path.read_bytes())[:12], 'url': source['url'], 'source': source}
    raise ValueError('This component needs a custom file or an upstream download source')


def addon_files(path, bits):
    if path.read_bytes()[:2] == b'MZ':
        name = path.name
        if not name.lower().endswith(('.addon', '.addon32', '.addon64')):
            raise ValueError('Raw addon downloads must retain their upstream filename')
        files = {name:path.read_bytes()}
    else:
        files = archive_files(path)
    result = {}
    for name, data in files.items():
        leaf = PurePosixPath(name).name
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in {'.addon64', '.addon32', '.addon'}:
            with tempfile.NamedTemporaryFile() as f:
                f.write(data); f.flush()
                if not compatible_binary(f.name, bits):
                    continue
            if leaf.casefold() in {n.casefold() for n in result}:
                raise ValueError('Ambiguous addon archive')
            result[leaf] = data
        elif leaf.lower().startswith(('license', 'copying', 'notice')):
            result['OptiDX-licenses/' + sha(str(path).encode())[:12] + '/' + leaf] = data
    if not any(n.lower().endswith(('.addon', '.addon32', '.addon64')) for n in result):
        raise ValueError('No addon matches this game architecture')
    return result


def reshade_present(game):
    return inspect_game(game)['components']['ReShade'] or any((game.target / n).exists() for n in ('d3d9.dll', 'opengl32.dll'))


def deploy_custom(game, repository, item, preferences):
    path = Path(item['path'])
    if sha(path.read_bytes()) != item['sha256']:
        raise ValueError('Imported asset checksum mismatch')
    bits = int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    group = 'custom:' + item['id']
    if item['kind'] == 'addon':
        if not reshade_present(game):
            raise ValueError('Install ReShade before deploying addons')
        files = addon_files(path, bits)
    elif item['kind'] == 'preset':
        validate_preset(path.read_bytes())
        files = {f'OptiDX-presets/{item["id"]}.ini': path.read_bytes()}
    elif item['kind'] == 'shader':
        files = shader_layout({path.name: path.read_bytes()} if path.suffix == '.fx' else archive_files(path), item['id'])
    else:
        raise ValueError('Use the DLL manager for binary imports')
    result = assets.deploy(game.target, group, files, {'source': item, 'version': 'Custom', 'kind': item['kind']},
                           preferences.get('allow_foreign', False))
    if item['kind'] in {'shader', 'preset'}:
        apply_display(game, preferences, preset=f'OptiDX-presets/{item["id"]}.ini' if item['kind'] == 'preset' else '')
    return result


def apply_display(game, preferences, preset=''):
    root = game.target
    ini = next((root / n for n in ['ReShade.ini', 'reshade.ini'] if (root / n).is_file()), root / 'ReShade.ini')
    current = ini.read_bytes() if ini.exists() else b''
    sections = {}
    shader_dirs = [f'.\\reshade-shaders\\OptiDX\\{p.name}\\Shaders\\**' for p in (root / 'reshade-shaders/OptiDX').glob('*') if p.is_dir()]
    texture_dirs = [p.replace('\\Shaders\\', '\\Textures\\') for p in shader_dirs]
    from .backend import load_backend
    module = load_backend()
    text = current.decode(module.hdr_ini_encoding(current))
    general = module.hdr_ini_values(text, 'GENERAL')
    for key, directories in [('EffectSearchPaths', shader_dirs), ('TextureSearchPaths', texture_dirs)]:
        if directories:
            # ReShade's search paths are comma separated. Keep all existing paths.
            existing = (general.get(key.casefold()) or '').split(',')
            sections.setdefault('GENERAL', {})[key] = ','.join(dict.fromkeys(p for p in existing + directories if p))
    if preset:
        sections.setdefault('GENERAL', {})['PresetPath'] = '.\\' + preset.replace('/', '\\')
    if preferences.get('screenshot_path'):
        sections['SCREENSHOT'] = {'SavePath': preferences['screenshot_path']}
    if preferences.get('reshade_hotkey'):
        sections['INPUT'] = {'KeyOverlay': preferences['reshade_hotkey']}
    peak = preferences.get('peak_nits')
    if peak:
        if not 80 <= int(peak) <= 10000:
            raise ValueError('Peak brightness must be between 80 and 10000 nits')
        names = re.findall(r'^\s*\[(renodx-preset[^\]]*)\]', text, re.M) or ['renodx-preset']
        for name in names:
            sections[name] = {'ToneMapPeakNits': str(int(peak))}
    if sections:
        journal_display(game, ini, current, sections)
        assets.atomic_bytes(ini, ini_edit(current, sections), ini.stat().st_mode & 0o777 if ini.exists() else 0o644)
    return {'path': str(ini)}


def dll_locations(game):
    names = set(DLSS_FILES.values()) | set(STREAMLINE_FILES)
    root = Path(game.root)
    return sorted(str(p.relative_to(root)) for p in root.rglob('*.dll') if p.name.lower() in names and not p.is_symlink()
                  and not any(part.startswith('.optidx') for part in p.relative_to(root).parts))


def swap_dll(game, repository, kind, version, target_dir='', custom_path='', refresh=False):
    if kind not in {*DLSS_FILES, 'streamline'}:
        raise ValueError('Unknown DLSS component')
    client = Client(repository.directory)
    if custom_path:
        source = {'path': custom_path, 'version': 'Custom'}
    else:
        manifest = client.metadata(DLSS_MANIFEST, refresh)
        entries = manifest.get(kind, [])
        item = next((v for v in entries if v['version'] == version), None)
        if version == 'Latest' and entries:
            item = entries[0]
        if not item:
            raise ValueError('Selected DLL version is absent from the upstream manifest')
        source = item
    path, metadata = payload(client, source)
    files = {Path(custom_path).name: path.read_bytes()} if custom_path and path.suffix == '.dll' else archive_files(path)
    scope = Path(game.root)
    folder = contained(scope, target_dir) if target_dir else game.target
    folder.resolve().relative_to(scope.resolve())
    prefix = str(folder.relative_to(scope))
    if kind == 'streamline':
        names = [n for n in STREAMLINE_FILES if any(PurePosixPath(p).name.lower() == n for p in files)]
        if 'sl.common.dll' not in names:
            raise ValueError('Streamline package is missing sl.common.dll')
    else:
        names = [DLSS_FILES[kind]]
    replacements = {str(Path(prefix) / n): binary_member(files, n, int(inspect_game(game)['bits'] or 64)) for n in names}
    # Version swapping explicitly replaces originals, which are retained by the ledger.
    return assets.deploy(scope, 'dll:' + kind + ':' + prefix, replacements,
                         {**metadata, 'kind': kind, 'target_dir': target_dir}, allow_foreign=True)


def deploy_extra(game, repository, key, preferences, source=None, refresh=False):
    if key not in EXTRAS:
        raise ValueError('Unknown extra component')
    item = {**EXTRAS[key], **(source or {})}
    if key == 'display_commander' and str(preferences.get('bits_override') or inspect_game(game)['bits']) == '32' and not (source or {}).get('pattern'):
        item['pattern'] = r'^zzz_display_commander\.addon32$'
    bits = int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    if key in {'relimiter', 'display_commander'}:
        opposite = 'display_commander' if key == 'relimiter' else 'relimiter'
        if 'extra:' + opposite in assets.state(game.target)['groups']:
            raise ValueError('Remove the other frame limiter first')
    if item['kind'] == 'addon' and (not reshade_present(game) or preferences.get('reshade_channel') == 'no_addons'):
        raise ValueError('Install ReShade before deploying this addon')
    if key == 'optipatcher' and not inspect_game(game)['components']['OptiScaler']:
        raise ValueError('OptiPatcher requires OptiScaler')
    if key == 'reframework' and inspect_game(game)['engine'] != 'RE Engine':
        raise ValueError('RE Framework is only offered for detected RE Engine games')
    if key == 'dof_fix':
        from .inspection import unreal_version
        version = preferences.get('ue_version') or unreal_version(game)
        remote = read_json(repository.directory / 'remote-manifest.json', {})
        forced = game.title.casefold() in {n.casefold() for n in remote.get('dofFixForceGames', [])}
        skipped = game.title.casefold() in {n.casefold() for n in remote.get('dofFixSkipGames', [])}
        if bits != 64 or skipped or (not forced and not re.fullmatch(r'5\.[0-6](?:\.\d+)?', version)):
            raise ValueError('The DOF fix requires UE 5.0–5.6 and 64-bit; set the UE version override when detection is inconclusive')
    path, metadata = payload(Client(repository.directory), item, refresh)
    if item['kind'] == 'addon':
        if path.read_bytes()[:2] == b'MZ' and not path.name.lower().endswith(('.addon', '.addon32', '.addon64')):
            from urllib.parse import urlparse, unquote
            name = Path(unquote(urlparse(metadata.get('url', '')).path)).name
            if not name.lower().endswith(('.addon', '.addon32', '.addon64')):
                raise ValueError('Unrecognized upstream addon filename')
            files = {name:binary_member({name:path.read_bytes()},name,bits)}
        else:
            files = addon_files(path, bits)
    else:
        if path.read_bytes()[:2] == b'MZ':
            from urllib.parse import urlparse, unquote
            name = path.name if path.suffix.lower() == '.asi' else Path(unquote(urlparse(metadata.get('url','')).path)).name
            archive = {name:path.read_bytes()}
        else:
            archive = archive_files(path)
        if item['kind'] == 'reframework':
            files = {'dinput8.dll': binary_member(archive, 'dinput8.dll', bits)}
        else:
            names = [n for n in archive if n.lower().endswith('.asi')]
            if len(names) != 1:
                raise ValueError('Expected exactly one ASI plugin')
            data = binary_member(archive, PurePosixPath(names[0]).name, bits)
            files = {'OptiScaler/plugins/' + PurePosixPath(names[0]).name: data}
    result=assets.deploy(game.target, 'extra:' + key, files, {**metadata, 'kind': item['kind']}, preferences.get('allow_foreign', False))
    if key=='optipatcher':
        from .channels import loader_settings
        loader_settings(game,{'LoadAsiPlugins':'true'})
    return result


def refresh_catalogs(repository, client=None):
    client = client or Client(repository.directory)
    errors = []
    for url, name in [(RHI_MANIFEST, 'remote-manifest.json'), (DLSS_MANIFEST, 'dlss-manifest.json')]:
        try:
            data = client.metadata(url, True)
            if not isinstance(data, dict):
                raise ValueError('Invalid upstream manifest')
            atomic_json(repository.directory / name, data)
        except (OSError, ValueError) as error:
            errors.append(str(error))
    return {'errors': errors, 'shader_packs': len(catalogs(repository)),
            'dlss': read_json(repository.directory / 'dlss-manifest.json', {})}


def run_feature(game, action, preferences, repository, options):
    if action == 'remove_helixsr':
        from .helixsr import remove
        return remove(game, repository, preferences)
    client = Client(repository.directory)
    if action in {'prepare_template','apply_template'}:
        from .templates import prepare, apply
        return {'path':str(prepare(repository, options['id']))} if action=='prepare_template' else apply(game, repository, options)
    if action == 'deploy_neural_tool':
        from .neural import deploy_tool
        return deploy_tool(game, repository, preferences, options)
    if action == 'nr_cost_scaler':
        from .neural import cost_scaler
        return cost_scaler(game, repository, preferences, options, options.get('enabled',True))
    if action == 'edit_config':
        return edit_config(game, options)
    if action == 'create_vkbasalt_config':
        return create_vkbasalt_config(game, repository, options)
    if action == 'import_url':
        return import_url(repository, options['url'], options.get('kind', 'addon'))
    if action == 'deploy_catalog_addon':
        return deploy_catalog_addon(game, repository, preferences, options['id'], options.get('refresh', False))
    if action == 'deploy_pipeline':
        return deploy_pipeline(game, repository, preferences, options)
    if action == 'import_asset':
        return import_asset(repository, options['path'], options.get('kind', 'addon'), options.get('label', ''))
    if action == 'deploy_asset':
        item = read_json(repository.directory / 'assets.json', {})[options['id']]
        return deploy_custom(game, repository, item, preferences)
    if action == 'remove_asset':
        if options['group'].startswith('shader:'):
            key=options['group'].split(':',1)[1]
            for group,item in assets.state(game.target)['groups'].items():
                if group != options['group'] and key in item['metadata'].get('source',{}).get('requires',[]):
                    raise ValueError('Remove dependent shader pack first: '+group)
        return assets.remove(Path(game.root) if options.get('scope') == 'root' else game.target, options['group'])
    if action == 'toggle_asset':
        return assets.toggle_addon(Path(game.root) if options.get('scope') == 'root' else game.target, options['group'], options['enabled'])
    if action in {'shader_files', 'deploy_shader'}:
        key = options['id']
        source = catalogs(repository)[key]
        for required in source.get('requires', []):
            if action == 'deploy_shader' and 'shader:' + required not in assets.state(game.target)['groups']:
                raise ValueError('Install the required shader pack first: ' + required)
        path, metadata = payload(client, source, options.get('refresh', False))
        files = archive_files(path)
        prepared = shader_layout(files, key, options.get('selected'))
        if action == 'shader_files':
            return {'files': [n.split('/Shaders/', 1)[1] for n in prepared if n.endswith('.fx')], 'id': key}
        result = assets.deploy(game.target, 'shader:' + key, prepared, {**metadata, 'kind': 'shader', 'selection': options.get('selected')}, preferences.get('allow_foreign', False))
        apply_display(game, preferences)
        return result
    if action == 'swap_dll':
        return swap_dll(game, repository, options['kind'], options.get('version', ''), options.get('target_dir', ''), options.get('path', ''))
    if action == 'restore_dll':
        return assets.remove(Path(game.root), options['group'])
    if action == 'deploy_extra':
        return deploy_extra(game, repository, options['id'], preferences, options.get('source'), options.get('refresh', False))
    if action == 'refresh_catalogs':
        return refresh_catalogs(repository, client)
    if action == 'list_releases':
        return {'releases': client.releases(options['repo'], True)}
    if action == 'check_updates':
        from .updates import check_updates
        return check_updates(game, repository, preferences, client)
    if action == 'apply_display':
        return apply_display(game, preferences)
    if action == 'install_reshade':
        from .channels import install_reshade
        return install_reshade(game, repository, preferences)
    if action == 'install_dxvk':
        from .channels import install_dxvk
        return install_dxvk(game, repository, preferences, options)
    raise ValueError('Unknown feature operation')


def update_features(game, repository, preferences):
    exclusions = set(preferences.get('exclude_components', []))
    library = read_json(repository.directory / 'assets.json', {})
    for group, item in list(assets.state(game.target)['groups'].items()):
        if group in exclusions or item['metadata'].get('enabled') is False:
            continue
        if group == 'neural:pipeline':
            from .neural import deploy_tool
            deploy_tool(game, repository, preferences, {**item['metadata'].get('options',{}),'refresh':True})
        elif group.startswith('catalog:'):
            deploy_catalog_addon(game, repository, preferences, group.split(':',1)[1], True)
        elif group.startswith('shader:'):
            run_feature(game, 'deploy_shader', preferences, repository,
                        {'id': group.split(':', 1)[1], 'refresh': True, 'selected': item['metadata'].get('selection')})
        elif group.startswith('extra:'):
            run_feature(game, 'deploy_extra', preferences, repository,
                        {'id': group.split(':', 1)[1], 'refresh': True, 'source': item['metadata'].get('source')})
        elif group.startswith('custom:') and group.split(':', 1)[1] in library:
            deploy_custom(game, repository, library[group.split(':', 1)[1]], preferences)
    from .neural import deploy_tool
    for group,item in list(assets.state(Path(game.root))['groups'].items()):
        if group.startswith('neural:pipeline:') and group not in exclusions and item['metadata'].get('enabled') is not False:
            deploy_tool(game,repository,preferences,{**item['metadata'].get('options',{}),'refresh':True})
    if preferences.get('auto_update_dlss'):
        for group, item in list(assets.state(Path(game.root))['groups'].items()):
            if group.startswith('dll:') and group not in exclusions and not item['metadata'].get('source', {}).get('path'):
                swap_dll(game, repository, item['metadata']['kind'], 'Latest', item['metadata'].get('target_dir', ''), refresh=True)
                if item['metadata'].get('cost_scaler'):
                    from .neural import cost_scaler
                    cost_scaler(game, repository, preferences, {'target_dir':item['metadata'].get('target_dir',''),'source':item['metadata']['cost_scaler'].get('source'),'refresh':True})


def deploy_pipeline(game, repository, preferences, options):
    """Deploy an explicit upstream package without executing installer programs."""
    from .channels import effective_api
    if not reshade_present(game):
        raise ValueError('Install ReShade with addon support before deploying a neural-rendering pipeline')
    path = Path(options['path'])
    files = archive_files(path)
    bits = int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    if bits != 64:
        raise ValueError('Neural-rendering package deployment currently requires 64-bit; helper-process layouts need separate validation')
    result = {}
    binary_names = set(DLSS_FILES.values()) | set(STREAMLINE_FILES) | {'dinput8.dll', 'dlss5.dll'}
    for name, data in files.items():
        leaf = PurePosixPath(name).name
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in {'.addon', '.addon32', '.addon64', '.asi'} or suffix == '.dll' or leaf.lower() == 'dlss5-feed-host64.exe':
            if suffix in {'.addon32', '.addon64'} and not leaf.endswith(str(bits)):
                continue
            with tempfile.NamedTemporaryFile() as f:
                f.write(data); f.flush()
                if not compatible_binary(f.name, bits):
                    continue
            destination = 'OptiScaler/plugins/' + leaf if suffix == '.asi' and inspect_game(game)['components']['OptiScaler'] else leaf
            if destination in result:
                raise ValueError('Pipeline package has ambiguous binary names: ' + leaf)
            result[destination] = data
        elif leaf.lower() == 'reshadepreset.ini':
            validate_preset(data)
            result['ReShadePreset.ini'] = data
        elif suffix in {'.ini', '.cfg'}:
            result[leaf] = data
        elif leaf.lower().startswith(('license', 'notice', 'copying')):
            result['OptiDX-licenses/pipeline/' + leaf] = data
    if not any(n.lower().endswith(('.addon', '.addon32', '.addon64', '.asi')) for n in result):
        raise ValueError('This package has no addon or ASI plugin matching the game architecture')
    try:
        result.update(shader_layout(files, 'pipeline'))
    except ValueError as error:
        if 'No selected ReShade effects' not in str(error):
            raise
    group = 'pipeline:' + sha(options['method'].encode())[:12]
    ledger = assets.deploy(game.target, group, result, {'kind':'pipeline', 'version':'Custom',
                           'method':options['method'], 'source': {'path':str(path), 'sha256':sha(path.read_bytes())}},
                           preferences.get('allow_foreign', False))
    apply_display(game, preferences, 'ReShadePreset.ini' if 'ReShadePreset.ini' in result else '')
    return ledger


def import_url(repository, url, kind='addon'):
    from urllib.parse import urlparse, unquote
    client=Client(repository.directory)
    path=client.fetch(url)
    name=Path(unquote(urlparse(url).path)).name
    if not name or name in {'.','..'}:
        raise ValueError('Download URL needs an asset filename')
    stage=repository.directory/'downloads'/'imports'/name
    assets.atomic_bytes(stage,path.read_bytes())
    return import_asset(repository,stage,kind)


def deploy_catalog_addon(game, repository, preferences, key, refresh=False):
    from .catalog import addon_catalog
    item=addon_catalog(repository)[key]
    bits=int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
    if not reshade_present(game) or preferences.get('reshade_channel')=='no_addons':
        raise ValueError('This addon needs ReShade with addon support')
    source={'repo':item['repo'],'pattern':item.get('pattern',r'\.addon'+str(bits)+r'$|\.zip$'), 'tag':item.get('tag','')} if item.get('repo') else {}
    if item.get('url'+str(bits)):
        source={'url':item['url'+str(bits)]}
    path,metadata=payload(Client(repository.directory),source,refresh)
    # Keep the upstream member filename for raw DLL downloads stored by hash.
    if path.read_bytes()[:2]==b'MZ':
        from urllib.parse import urlparse,unquote
        name=Path(unquote(urlparse(metadata.get('url','')).path)).name
        if not name.lower().endswith(('.addon','.addon32','.addon64')):
            raise ValueError('Upstream addon asset filename is not recognized')
        files={name:path.read_bytes()}
        data=binary_member(files,name,bits)
        prepared={name:data}
    else:
        if key == 'dlss5-feed':
            archive = archive_files(path)
            name = 'dlss5-feed.addon' + str(bits)
            prepared = {name:binary_member(archive,name,bits)}
            if bits != 64:
                raise ValueError('32-bit Feeder requires the helper process layout, which is not supported by this adapter')
        else:
            prepared=addon_files(path,bits)
        try:
            prepared.update(shader_layout(archive_files(path),key))
        except ValueError as error:
            if 'No selected ReShade effects' not in str(error):raise
    ledger=assets.deploy(game.target,'catalog:'+key,prepared,{**metadata,'kind':'addon'},preferences.get('allow_foreign',False))
    apply_display(game,preferences)
    return ledger


def create_vkbasalt_config(game, repository, options):
    effects=options.get('effects', ['cas'])
    if not effects:
        raise ValueError('Choose at least one Vulkan effect')
    builtin={'cas','dls','fxaa','smaa','lut'}
    lines=[];names=[]
    for index,effect in enumerate(effects):
        if effect in builtin:
            names.append(effect)
        else:
            path=contained(game.target,effect)
            if not path.is_file() or path.suffix.lower()!='.fx':
                raise ValueError('Choose an installed .fx file or builtin vkBasalt effect')
            if any(c in str(path) for c in '\n\r"'):
                raise ValueError('Shader path cannot be represented in vkBasalt configuration')
            name='effect'+str(index);names.append(name)
            lines += [name+' = "'+str(path)+'"', 'reshadeIncludePath = "'+str(path.parent)+'"']
            texture=next((p/'Textures' for p in path.parents if p.name in catalogs(repository)), None)
            if texture:lines.append('reshadeTexturePath = "'+str(texture)+'"')
    data=('effects = '+':'.join(names)+'\nenableOnLaunch = True\ntoggleKey = Home\n'+'\n'.join(lines)+'\n').encode()
    path=repository.directory/'configs'/game.id/'vkBasalt.conf'
    assets.atomic_bytes(path,data)
    return {'path':str(path)}


def restore_display(game):
    journal_path=game.target/'.optidx-desktop-settings.json'
    journal=read_json(journal_path,{})
    if not journal:return
    from .backend import load_backend
    module=load_backend()
    path=contained(game.target,journal['path'])
    if path.is_file():
        encoding=module.hdr_ini_encoding(path.read_bytes())
        text=path.read_bytes().decode(encoding)
        for section,values in journal['sections'].items():
            current=module.hdr_ini_values(text,section)
            changes={}
            for key,record in values.items():
                value=current.get(key.casefold())
                if key in {'EffectSearchPaths','TextureSearchPaths'}:
                    if value:
                        changes[key]=','.join(v for v in value.split(',') if '\\reshade-shaders\\OptiDX\\' not in v)
                elif value==record['applied']:
                    changes[key]=record['original']
            text=module.edit_hdr_ini(text,section,changes)
        assets.atomic_bytes(path,text.encode(encoding),journal.get('mode',0o644))
    journal_path.unlink(missing_ok=True)


def journal_display(game, ini, current, sections):
    from .backend import load_backend
    module=load_backend()
    encoding=module.hdr_ini_encoding(current)
    text=current.decode(encoding)
    path=game.target/'.optidx-desktop-settings.json'
    journal=read_json(path,{'path':str(ini.relative_to(game.target)),'mode':ini.stat().st_mode&0o777 if ini.exists() else 0o644,'sections':{}})
    for section,values in sections.items():
        old=module.hdr_ini_values(text,section)
        records=journal['sections'].setdefault(section,{})
        for key,value in values.items():
            record=records.setdefault(key,{'original':old.get(key.casefold())})
            record['applied']=value
    atomic_json(path,journal)


def edit_config(game, options):
    names={'ReShade.ini','reshade.ini','OptiScaler.ini','relimiter.ini','DisplayCommander.ini','dxvk.conf','ReShadePreset.ini','nvngx_dlssnr.ini'}
    name=options['name']
    if name not in names:
        raise ValueError('Select a supported component configuration file')
    path=contained(game.target,name)
    current=path.read_bytes() if path.is_file() else b''
    if sha(current)!=options['before_sha256']:
        raise assets.Conflict('Configuration changed while the editor was open')
    data=options['text'].encode('utf-8')
    if name.lower()!='dxvk.conf':
        parser=configparser.ConfigParser(interpolation=None,strict=False)
        parser.read_string('[DEFAULT]\n'+data.decode())
    assets.atomic_bytes(path,data,path.stat().st_mode&0o777 if path.exists() else 0o644)
    for scope in {game.target,Path(game.root)}:
        ledger=assets.state(scope)
        relative=str(path.relative_to(scope))
        updated=False
        for group in ledger['groups'].values():
            if relative in group['files']:
                group['files'][relative]['sha256']=sha(data);updated=True
        if updated:atomic_json(scope/assets.LEDGER,ledger)
    return {'path':str(path)}


def remove_all_assets(game):
    """Peel managed overlays before their underlying original DLL records."""
    scopes=sorted({game.target,Path(game.root)},key=lambda p:len(p.parts),reverse=True)
    pending=[(root,group) for root in scopes for group in assets.state(root)['groups']]
    while pending:
        changed=False
        for root,group in pending.copy():
            item=assets.state(root)['groups'][group]
            if all(not contained(root,name).exists() or (contained(root,name).is_file() and not contained(root,name).is_symlink()
                   and sha(contained(root,name).read_bytes())==record['sha256']) for name,record in item['files'].items()):
                assets.remove(root,group);pending.remove((root,group));changed=True
        if not changed:
            raise assets.Conflict('Managed files were edited or overlays cannot be restored: '+', '.join(g for r,g in pending))
