"""Editable, per-GPU OptiScaler templates with explicit application."""
import configparser
from pathlib import Path

from .assets import atomic_bytes
from .downloads import Client
from .features import ini_edit

TEMPLATES={f'{gpu}-{channel}':f'OptiScaler{suffix}.{gpu}.ini' for gpu in ['nvidia','amd-dlss','amd-nodlss']
           for channel,suffix in [('stable',''),('nightly','_nightly')]}


def template_path(repository, key):
    if key not in TEMPLATES:
        raise ValueError('Unknown GPU template')
    return repository.directory/'templates'/TEMPLATES[key]


def prepare(repository, key):
    path=template_path(repository,key)
    if not path.is_file():
        url='https://raw.githubusercontent.com/RankFTW/RHI/main/RenoDXCommander/'+TEMPLATES[key]
        payload=Client(repository.directory).fetch(url).read_bytes()
        validate(payload)
        atomic_bytes(path,payload)
    return path


def validate(data):
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    parser.optionxform=str
    parser.read_string(data.decode('utf-8-sig'))
    if not parser.sections():
        raise ValueError('Template contains no INI sections')
    return parser


def apply(game, repository, options):
    path=prepare(repository,options['id'])
    parser=validate(path.read_bytes())
    destination=game.target/'OptiScaler.ini'
    if not destination.is_file():
        raise ValueError('Install OptiScaler before applying its GPU template')
    # HelixSR forwarding, custom library locations and explicit FG settings must
    # remain independent of a generic GPU template.
    sections={section:dict(parser[section]) for section in parser.sections()
              if section.casefold() not in {'libraries','framegen','plugins'}}
    atomic_bytes(destination,ini_edit(destination.read_bytes(),sections),destination.stat().st_mode&0o777)
    return {'path':str(destination),'template':str(path)}
