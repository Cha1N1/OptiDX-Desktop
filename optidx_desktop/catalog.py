"""Upstream sources; downloaded on demand, never packaged with personal data."""
from pathlib import Path
import re

from .storage import read_json

RHI_MANIFEST = 'https://raw.githubusercontent.com/RankFTW/RHI/main/manifest.json'
DLSS_MANIFEST = 'https://raw.githubusercontent.com/RankFTW/RHI/main/dlss_manifest.json'
# Repository URLs were checked against RHI's published shader catalog. No shader
# source is redistributed in the app. Each downloaded pack retains its licenses.
_PACKS = '''
CrosireMaster|crosire/reshade-shaders|master
CrosireLegacy|crosire/reshade-shaders|legacy
SmolbbsoopShaders|smolbbsoop/smolbbsoopshaders|main
MaxG2DSimpleHDR|MaxG2D/ReshadeSimpleHDRShaders|main
ClshortfuseShaders|clshortfuse/reshade-shaders|main
PotatoFX|CreepySasquatch/potatoFX|main
Azen|Zenteon/Azen|main
SweetFX|CeeJayDK/SweetFX|master
OtisFX|FransBouma/OtisFX|master
Depth3D|BlueSkyDefender/Depth3D|master
DaodanShaders|Daodan317081/reshade-shaders|master
BrussellShaders|brussell1/Shaders|master
FubaxShaders|Fubaxiusz/fubax-shaders|master
qUINT|martymcmodding/qUINT|master
AlucardDH|AlucardDH/dh-reshade-shaders|master
WarpFX|Radegast-FFXIV/Warp-FX|master
Prod80|prod80/prod80-ReShade-Repository|master
CorgiFX|originalnicodr/CorgiFX|master
InsaneShaders|LordOfLunacy/Insane-Shaders|master
CobraFX|LordKobra/CobraFX|master
AstrayFX|BlueSkyDefender/AstrayFX|master
CRTRoyale|akgunter/crt-royale-reshade|master
RSRetroArch|Matsilagi/RSRetroArch|main
VRToolkit|retroluxfilm/reshade-vrtoolkit|main
FGFX|AlexTuduran/FGFX|main
CShade|papadanku/CShade|main
iMMERSE|martymcmodding/iMMERSE|main
VortShaders|vortigern11/vort_Shaders|main
BXShade|liuxd17thu/BX-Shade|main
SHADERDECK|IAmTreyM/SHADERDECK|main
METEOR|martymcmodding/METEOR|main
AnnReShade|AnastasiaGals/Ann-ReShade|main
ZenteonFX|Zenteon/ZenteonFX|main
GShadeShaders|Mortalitas/GShade-Shaders|master
PthoFX|PthoEastCoast/Ptho-FX|main
Anagrama|nullfrctl/reshade-shaders|main
BarbatosShaders|BarbatosBachiko/Reshade-Shaders|main
BFBFX|yplebedev/BFBFX|main
Rendepth|outmode/rendepth-reshade|main
CropAndResize|P0NYSLAYSTATION/Scaling-Shaders|main
FXShaders|luluco250/FXShaders|master
LumeniteFX|umar-afzaal/LumeniteFX|mainline
NNShaders|Sarenya/NN-Shaders|master
QdOledAplFixer|mspeedo/QD-OLED-APL-FIXER|main
GlamaryeFX|rj200/Glamarye_Fast_Effects_for_ReShade|main
LumaBoost|Valadore/LumaBoost|main
RenoFXHDRToolkit|clshortfuse/renofx|main
'''
SHADERS = {key: {'label': key, 'url': f'https://github.com/{repo}/archive/refs/heads/{branch}.zip'}
           for key, repo, branch in (line.split('|') for line in _PACKS.strip().splitlines())}
SHADERS.update(Lilium={'label': 'Lilium HDR', 'repo': 'EndlesslyFlowering/ReShade_HDR_shaders', 'pattern': r'\.7z$'},
               PumboAutoHDR={'label': 'PumboAutoHDR', 'repo': 'Filoppi/PumboAutoHDR', 'pattern': r'\.zip$'})
SHADERS['Azen']['requires'] = ['SmolbbsoopShaders']
SHADERS['CrosireLegacy']['requires'] = ['CrosireMaster']
EXTRAS = {
    'relimiter': {'label': 'ReLimiter', 'repo': 'RankFTW/ReLimiter', 'pattern': r'\.(zip|7z|addon64)$', 'kind': 'addon'},
    'display_commander': {'label': 'Display Commander', 'repo': 'pmnoxx/display-commander', 'tag': 'latest',
                          'pattern': r'^zzz_display_commander\.addon64$', 'kind': 'addon'},
    'optipatcher': {'label': 'OptiPatcher', 'repo': 'optiscaler/OptiPatcher', 'pattern': r'\.(zip|7z|asi)$', 'kind': 'asi'},
    'reframework': {'label': 'RE Framework', 'repo': 'praydog/REFramework-nightly', 'pattern': r'RE2\.zip$', 'kind': 'reframework'},
    'dof_fix': {'label': 'UE depth-of-field fix', 'repo': 'RankFTW/rhi-repo', 'pattern': r'^renodx-universal_ue-dof-fix\.addon64$', 'kind': 'addon'},
}
DLSS_FILES = {'dlss': 'nvngx_dlss.dll', 'dlssd': 'nvngx_dlssd.dll', 'dlssg': 'nvngx_dlssg.dll',
              'dlssnr': 'nvngx_dlssnr.dll'}
STREAMLINE_FILES = ['sl.common.dll', 'sl.deepdvc.dll', 'sl.directsr.dll', 'sl.dlss.dll', 'sl.dlss_d.dll',
                    'sl.dlss_g.dll', 'sl.interposer.dll', 'sl.nis.dll', 'sl.nvperf.dll', 'sl.pcl.dll', 'sl.reflex.dll']


def catalogs(repository):
    shaders = {k: dict(v) for k, v in SHADERS.items()}
    remote = read_json(repository.directory / 'remote-manifest.json', {})
    for key, item in remote.get('shaderPacks', {}).items():
        if item.get('disabled'):
            shaders.pop(key, None)
            continue
        entry = shaders.setdefault(key, {'label': key})
        if item.get('displayName'):
            entry['label'] = item['displayName']
        if item.get('url'):
            if item.get('kind') == 'GhRelease':
                match = re.search(r'/repos/([^/]+/[^/]+)/releases', item['url'])
                if match:
                    entry.update(repo=match[1], pattern=re.escape(item.get('assetExt', '.zip')) + '$')
                    entry.pop('url', None)
            else:
                entry.update(url=item['url']); entry.pop('repo', None)
        if item.get('requires'):
            entry['requires'] = item['requires']
    shaders.update(read_json(repository.directory / 'custom-shader-catalog.json', {}))
    return shaders


def game_data(repository, title):
    remote = read_json(repository.directory / 'remote-manifest.json', {})
    match = lambda mapping: next((v for k, v in remote.get(mapping, {}).items() if k.casefold() == title.casefold()), None)
    return {'notes': match('gameNotes'), 'engine': match('engineOverrides'), 'wiki_name': match('wikiNameOverrides'),
            'reshade': match('reshadeGameInfo'), 'luma': match('lumaGameNotes'),
            'api': match('graphicsApiOverrides'), 'dlls': match('dllNameOverrides'),
            'renodx_ini': match('renodxIniOverrides'), 'engine_ini': match('engineIniFiles')}


def addon_catalog(repository):
    result = {
        'dlss5-feed': {'label':'DLSS5 Feeder', 'repo':'jlrouzies-fr/DLSS5-Feeder'},
        'dlss5-dx11-bridge': {'label':'DLSS5 DX11 bridge', 'repo':'NIGos/dlss5-bridge'},
        'mfgunlock': {'label':'MFG Ada Unlock', 'repo':'mavismmg/MFGAdaUnlock-RenoDx'},
        'renodx-devkit': {'label':'RenoDX devkit', 'repo':'clshortfuse/renodx', 'tag':'snapshot', 'pattern':r'^renodx-devkit\.addon64$'},
        'renodx-dlssfix': {'label':'RenoDX DLSS fix', 'repo':'clshortfuse/renodx', 'tag':'snapshot', 'pattern':r'^renodx-dlssfix\.addon64$'},
    }
    remote = read_json(repository.directory/'remote-manifest.json',{})
    for key, item in remote.get('addonPacks',{}).items():
        if item.get('disabled'):
            result.pop(key,None);continue
        value=result.setdefault(key,{})
        value['label']=item.get('packageName') or value.get('label') or key
        value['url32']=item.get('downloadUrl32') or value.get('url32')
        value['url64']=item.get('downloadUrl64') or value.get('url64')
        url=item.get('releaseApiUrl','')
        match=re.search(r'/repos/([^/]+/[^/]+)/releases',url)
        if match:value['repo']=match[1]
    return result
