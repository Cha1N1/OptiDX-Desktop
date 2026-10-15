"""Read-only update availability checks and per-component exclusions."""
import time

from . import assets
from .channels import reshade_source
from .catalog import DLSS_MANIFEST
from .downloads import Client
from .storage import atomic_json, read_json


def check_updates(game, repository, preferences, client=None):
    client = client or Client(repository.directory)
    records, errors = [], []
    exclusions = set(preferences.get('exclude_components', []))
    scopes = {str(game.target): 'target', str(game.root): 'root'}
    dlss_manifest = None
    for scope, label in scopes.items():
        for group, item in assets.state(scope)['groups'].items():
            if group in exclusions:
                continue
            source = item['metadata'].get('source', {})
            if source.get('path'):
                continue
            if group.startswith('dll:') and preferences.get('auto_update_dlss'):
                try:
                    if dlss_manifest is None:dlss_manifest=client.metadata(DLSS_MANIFEST,True)
                    entries=dlss_manifest.get(item['metadata'].get('kind'),[])
                    if entries:records.append({'component':group,'installed':item['metadata'].get('version'),'available':entries[0]['version'],'update':entries[0]['version']!=item['metadata'].get('version')})
                except (OSError,ValueError) as error:errors.append(group+': '+str(error))
                continue
            if not source.get('repo'):
                import re
                from urllib.parse import quote
                match=re.fullmatch(r'https://github.com/([^/]+/[^/]+)/archive/refs/heads/(.+)\.zip',source.get('url',''))
                if match:
                    try:
                        commit=client.metadata('https://api.github.com/repos/'+match[1]+'/commits/'+quote(match[2],safe=''),True)['sha']
                        records.append({'component':group,'installed':item['metadata'].get('version'),'available':commit,'update':commit!=item['metadata'].get('version')})
                    except (OSError,ValueError,KeyError) as error:errors.append(group+': '+str(error))
                continue
            try:
                release = client.release_asset(source['repo'], source.get('pattern', r'\.zip$'),
                            source.get('channel', 'stable'), source.get('tag', ''), True)
                digest = release.get('digest')
                previous_digest = item['metadata'].get('digest')
                # Moving tags (nightly/latest) are compared by asset identity too.
                available = release['version'] != item['metadata'].get('version') or (
                    release.get('updated_at') and release.get('updated_at') != item['metadata'].get('updated_at'))
                records.append({'component': group, 'installed': item['metadata'].get('version'),
                                'available': release['version'], 'update': bool(available), 'scope': label})
            except (ValueError, OSError) as error:
                errors.append(group + ': ' + str(error))
    versions = read_json(game.target / '.optidx-desktop-versions.json', {})
    if 'optiscaler' in versions and 'optiscaler' not in exclusions:
        old = versions['optiscaler']
        try:
            release = client.release_asset(preferences.get('optiscaler_repo') or old.get('repository', 'optiscaler/OptiScaler'),
                        r'\.7z$', preferences.get('optiscaler_channel', old.get('channel', 'nightly')),
                        preferences.get('optiscaler_tag', ''), True)
            records.append({'component': 'optiscaler', 'installed': old.get('version'), 'available': release['version'],
                            'update': release.get('id') != old.get('id') or release.get('updated_at') != old.get('updated_at')})
        except (ValueError, OSError) as error:
            errors.append('OptiScaler: ' + str(error))
    record_source_updates(game, repository, preferences, client, records, errors)
    result = {'checked_at': time.time(), 'components': records, 'errors': errors,
              'update_available': any(r['update'] for r in records)}
    atomic_json(repository.directory / 'updates' / (game.id + '.json'), result)
    return result


def record_source_updates(game, repository, preferences, client, records, errors):
    from .inspection import file_version, inspect_game
    exclusions=set(preferences.get('exclude_components',[]))
    versions=read_json(game.target/'.optidx-desktop-versions.json',{})
    if 'reshade' not in exclusions and (versions.get('reshade') or 'channel:reshade' in assets.state(game.target)['groups']):
        channel=preferences.get('reshade_channel','stable')
        if channel not in {'custom','legacy'}:
            try:
                source=reshade_source(preferences,int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64),client)
                if channel=='nightly':
                    path=client.fetch(source['url'],refresh=True)
                    from .downloads import archive_files,binary_member,sha
                    bits=int(preferences.get('bits_override') or inspect_game(game)['bits'] or 64)
                    data=binary_member(archive_files(path),'ReShade'+str(bits)+'.dll',bits)
                    installed=next((game.target/n for n in ['d3d12-ReShade64.dll','ReShade32.dll','ReShade64.dll'] if (game.target/n).is_file()),None)
                    update=bool(installed and sha(installed.read_bytes())!=sha(data))
                    new=sha(data)[:12]
                else:
                    installed=next((game.target/n for n in ['d3d12-ReShade64.dll','ReShade32.dll','ReShade64.dll'] if (game.target/n).is_file()),None)
                    old=file_version(installed) if installed else ''
                    new=source['version']
                    update=bool(old and not old.startswith(new+'.') and old!=new)
                records.append({'component':'reshade','installed':file_version(installed) if installed else '', 'available':new,'update':update})
            except (ValueError,OSError) as error:errors.append('ReShade: '+str(error))
    amd=read_json(game.target/'OptiScaler/.optidx-amd-release.json',{})
    if amd and 'amd_fsr' not in exclusions:
        try:
            release=client.release_asset('zgauthier2000/fsr4-shader-performance-overrides',r'^fsr4\.1\.1-cyboman\.zip$',refresh=True)
            records.append({'component':'amd_fsr','installed':amd['tag'],'available':release['version'],'update':amd['tag']!=release['version']})
        except (ValueError,OSError) as error:errors.append('Cyboman FSR: '+str(error))
    for component in ['renodx','luma']:
        item=versions.get(component,{})
        if component in exclusions:continue
        for name,digest in item.get('files',{}).items():
            try:
                if component=='renodx':
                    data=client.metadata('https://api.github.com/repos/clshortfuse/renodx/releases/tags/snapshot',True)
                else:
                    data=client.metadata('https://api.github.com/repos/Filoppi/Luma-Framework/releases/latest',True)
                asset=next((a for a in data.get('assets',[]) if a.get('name')==name),None)
                if component=='luma' and item.get('version'):
                    records.append({'component':'luma','installed':item['version'],'available':data.get('tag_name'),'update':item['version']!=data.get('tag_name')})
                    break
                if not asset or not asset.get('digest'):continue
                records.append({'component':component,'installed':item.get('binary_versions',{}).get(name),
                                'available':data.get('tag_name'),'update':asset['digest'].removeprefix('sha256:')!=digest})
            except (ValueError,OSError) as error:errors.append(component+': '+str(error))
