"""Neural rendering adapters with explicit forwarding and restoration contracts."""
from pathlib import Path, PurePosixPath

from . import assets
from .downloads import Client, archive_files, binary_member
from .features import payload, ini_edit
from .inspection import contained, inspect_game

COST_SOURCE={'repo':'xenmods/DLSSNR-Cost-Scaler','pattern':r'\.zip$'}


def cost_scaler(game, repository, preferences, options, enabled=True):
    root=Path(game.root)
    folder=contained(root,options.get('target_dir','')) if options.get('target_dir') else game.target
    prefix=str(folder.relative_to(root))
    group='dll:dlssnr:'+prefix
    ledger=assets.state(root)
    candidate=str((folder/'nvngx_dlssnr.dll').relative_to(root))
    group=next((key for key,record in ledger['groups'].items() if record.get('metadata',{}).get('kind')=='neural' and candidate in record['files']),group)
    item=ledger['groups'].get(group,{})
    base_path=folder/('nvngx_dlssnr_real.dll' if item.get('metadata',{}).get('cost_scaler') else 'nvngx_dlssnr.dll')
    if not enabled:
        if not item.get('metadata',{}).get('cost_scaler'):
            return ledger
        real_name=str(base_path.relative_to(root))
        files={n:contained(root,n).read_bytes() for n in item['files'] if n not in item['metadata']['cost_files']}
        files[str((folder/'nvngx_dlssnr.dll').relative_to(root))]=base_path.read_bytes()
        metadata=dict(item['metadata']);metadata.pop('cost_scaler');metadata.pop('cost_files')
        return assets.deploy(root,group,files,metadata)
    if inspect_game(game)['bits'] != 64:
        raise ValueError('NR Cost Scaler requires a 64-bit game')
    if not base_path.is_file():
        raise ValueError('Install the real nvngx_dlssnr.dll in the selected DLL folder before enabling Cost Scaler')
    scale=float(preferences.get('nr_cost_scale') or 0.75)
    if not 0.25 <= scale <= 2:
        raise ValueError('NR cost scale must be between 0.25 and 2.0')
    source=options.get('source') or COST_SOURCE
    path,version=payload(Client(repository.directory),source,options.get('refresh',False))
    archive=archive_files(path)
    proxy=binary_member(archive,'nvngx_dlssnr.dll',64)
    base=binary_member({'nvngx_dlssnr.dll':base_path.read_bytes()},'nvngx_dlssnr.dll',64)
    files={n:contained(root,n).read_bytes() for n in item.get('files',{})}
    ini_matches=[data for name,data in archive.items() if PurePosixPath(name).name.lower()=='nvngx_dlssnr.ini']
    if len(ini_matches)!=1:
        raise ValueError('Cost Scaler package needs exactly one nvngx_dlssnr.ini')
    base_name=str((folder/'nvngx_dlssnr_real.dll').relative_to(root))
    proxy_name=str((folder/'nvngx_dlssnr.dll').relative_to(root))
    ini_name=str((folder/'nvngx_dlssnr.ini').relative_to(root))
    files.update({base_name:base,proxy_name:proxy,ini_name:ini_edit(ini_matches[0],{'DLSSNR_Proxy':{'EnableProxy':'1','ResolutionScale':str(scale)}})})
    cost_files=[base_name,ini_name]
    if any(PurePosixPath(n).name.lower()=='dlssnr-companion.addon64' for n in archive):
        companion=str((game.target/'dlssnr-companion.addon64').relative_to(root))
        files[companion]=binary_member(archive,'dlssnr-companion.addon64',64)
        cost_files.append(companion)
    metadata={**item.get('metadata',{}),'kind':item.get('metadata',{}).get('kind','dlssnr'),'target_dir':options.get('target_dir',''),
              'cost_scaler':version,'cost_files':cost_files}
    # Enabling the proxy is an explicit replacement operation, like a DLL swap.
    return assets.deploy(root,group,files,metadata,allow_foreign=True)


def deploy_tool(game, repository, preferences, options):
    """Stage complete 64-bit ShortFuse/bridge runtime files before one deployment."""
    from .channels import effective_api
    from .features import reshade_present, addon_files
    from .catalog import DLSS_MANIFEST
    method=options['method']
    if method not in {'shortfuse','bridge','feeder'}:
        raise ValueError('This automatic adapter supports ShortFuse, DLSS5 Feeder and the DX11 bridge')
    if inspect_game(game)['bits'] != 64:
        raise ValueError('Neural rendering tools require 64-bit in this adapter')
    api=effective_api(game,preferences)
    if (method=='shortfuse' and api!='DX12') or (method=='bridge' and api!='DX11') or (method=='feeder' and api not in {'DX11','DX12'}):
        raise ValueError('Choose DX12 for ShortFuse or DX11 for the bridge in the API override')
    if not reshade_present(game) or preferences.get('reshade_channel')=='no_addons':
        raise ValueError('Install ReShade with addon support first')
    if inspect_game(game)['components']['OptiScaler']:
        raise ValueError('Remove stock OptiScaler before installing this neural consumer; it intercepts the same NGX calls')
    prefix=str(game.target.relative_to(Path(game.root)))
    group='neural:pipeline:'+prefix
    previous=assets.state(game.root)['groups'].get(group,{})
    owned = {PurePosixPath(n).name for n in previous.get('files',{})}
    for path in game.target.glob('*.addon64'):
        if path.name not in owned and path.name.lower().startswith(('renodx-dlss5','deep-fried-chicken','dlss5-feed','renodx-dlss.')):
            raise ValueError('Remove the other neural consumer/Feeder before choosing ShortFuse')
    client=Client(repository.directory)
    sources=options.get('sources',{})
    consumer_name='renodx-dlss.addon64' if method=='shortfuse' else 'renodx-dlss5.addon64'
    source=sources.get('consumer') or ({'repo':'clshortfuse/renodx','tag':'snapshot','pattern':r'^renodx-dlss\.addon64$'} if method=='shortfuse' else {'repo':'RankFTW/rhi-repo','pattern':r'^renodx-dlss5.*\.addon64$'})
    path,metadata=payload(client,source,options.get('refresh',False))
    data=path.read_bytes()
    if data[:2]==b'MZ':
        files={consumer_name:binary_member({consumer_name:data},consumer_name,64)}
    else:
        files=addon_files(path,64)
    if method=='feeder':
        files.update(prepare_feeder(game,repository,client,sources,options.get('refresh',False)))
    if method=='bridge':
        bridge=sources.get('bridge') or {'repo':'NIGos/dlss5-bridge','pattern':r'\.zip$|\.addon64$'}
        archive,bridge_version=payload(client,bridge,options.get('refresh',False))
        if archive.read_bytes()[:2]==b'MZ':
            files['dlss5-bridge.addon64']=binary_member({'dlss5-bridge.addon64':archive.read_bytes()},'dlss5-bridge.addon64',64)
        else:
            bridge_files=addon_files(archive,64)
            if set(files).intersection(bridge_files):raise ValueError('Bridge and consumer package filenames collide')
            files.update(bridge_files)
        metadata['bridge']=bridge_version
    manifest=None
    for key,name in [('dlss','nvngx_dlss.dll'),('dlssnr','nvngx_dlssnr.dll')]:
        source=sources.get(key)
        if not source:
            if manifest is None:manifest=client.metadata(DLSS_MANIFEST,options.get('refresh',False))
            entries=manifest.get(key,[])
            if not entries:raise ValueError('The upstream manifest has no '+key+' runtime')
            source=entries[0]
        archive,runtime_version=payload(client,source)
        archive_files_map={name:archive.read_bytes()} if archive.read_bytes()[:2]==b'MZ' else archive_files(archive)
        files[name]=binary_member(archive_files_map,name,64)
        metadata[key]=runtime_version
    if previous.get('metadata',{}).get('cost_scaler'):
        cost_scaler(game,repository,preferences,{'target_dir':prefix},False)
    files={str(Path(prefix)/name):data for name,data in files.items()}
    result=assets.deploy(Path(game.root),group,files,{**metadata,'method':method,'kind':'neural','options':options,'target_dir':prefix},preferences.get('allow_foreign',False))
    if previous.get('metadata',{}).get('cost_scaler'):
        source=previous['metadata']['cost_scaler'].get('source')
        cost_scaler(game,repository,preferences,{'target_dir':prefix,'source':source,'refresh':options.get('refresh',False)})
    if method=='feeder':
        from .features import apply_display
        apply_display(game,preferences,'OptiDX-presets/neural-feeder.ini')
    return result


def prepare_feeder(game, repository, client, sources, refresh=False):
    import re
    from .catalog import catalogs
    from .features import shader_layout
    from .inspection import file_version
    reshade=next((game.target/n for n in ['d3d12-ReShade64.dll','ReShade64.dll'] if (game.target/n).is_file()),None)
    version=file_version(reshade) if reshade else ''
    if not version or tuple(int(n) for n in version.split('.')[:2]) < (6,8):
        raise ValueError('Current DLSS5 Feeder shaders require ReShade 6.8 or newer; install a compatible build first')
    source=sources.get('feeder') or {'repo':'jlrouzies-fr/DLSS5-Feeder','pattern':r'\.zip$','channel':'latest'}
    path,metadata=payload(client,source,refresh)
    archive=archive_files(path)
    prepared={'dlss5-feed.addon64':binary_member(archive,'dlss5-feed.addon64',64)}
    prepared.update(shader_layout(archive,'neural-feeder'))
    packs=catalogs(repository)
    for key,namespace in [('CrosireMaster','neural-headers'),('LumeniteFX','neural-motion')]:
        path,version=payload(client,sources.get(key) or packs[key],refresh)
        prepared.update(shader_layout(archive_files(path),namespace))
    feed=[(name,data) for name,data in prepared.items() if PurePosixPath(name).name.lower()=='dlss5_feed.fx']
    kernel=[(name,data) for name,data in prepared.items() if name.lower().endswith('.fx') and 'kernel' in PurePosixPath(name).name.lower()]
    if len(feed)!=1 or len(kernel)!=1:
        raise ValueError('The shader package layout changed; choose a prepared neural package instead')
    def technique(entry):
        match=re.search(rb'\btechnique\d*\s+([A-Za-z_]\w*)',entry[1])
        if not match:raise ValueError('Required shader technique cannot be identified')
        return match[1].decode()+'@'+PurePosixPath(entry[0]).name
    preset='PreprocessorDefinitions=DLSS5_MV_PROVIDER=3\nTechniques='+technique(kernel[0])+','+technique(feed[0])+'\n'
    prepared['OptiDX-presets/neural-feeder.ini']=preset.encode()
    return prepared
