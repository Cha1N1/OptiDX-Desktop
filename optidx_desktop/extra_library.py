"""Read-only Lutris/Bottles discovery, including Flatpak locations."""
from pathlib import Path
import sqlite3
from contextlib import closing

import yaml

from .models import Game, game_id


def config(path):
    try:
        data = yaml.safe_load(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def lutris_games(home):
    from .library import find_executable
    roots = [(home / '.local/share/lutris', home / '.config/lutris'),
             (home / '.var/app/net.lutris.Lutris/data/lutris', home / '.var/app/net.lutris.Lutris/config/lutris')]
    for data, conf in roots:
        database = data / 'pga.db'
        if not database.is_file():
            continue
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute('SELECT * FROM games')]
        for row in rows:
            if not row.get('installed'):
                continue
            settings = config(conf / 'games' / (str(row.get('configpath') or row.get('slug')) + '.yml'))
            game = settings.get('game', {})
            prefix = str(game.get('prefix') or '')
            exe = str(game.get('exe') or '')
            directory = row.get('directory') or game.get('working_dir') or (str(Path(exe).parent) if exe else '')
            if not directory or not exe:
                continue
            if not Path(exe).is_absolute():
                exe = str(Path(directory) / exe)
            root = Path(directory)
            selected = find_executable(root) or exe
            if Path(selected).suffix.lower() != '.exe':
                continue
            yield Game(game_id('Lutris', row['id']), row.get('name') or root.name, 'Lutris', str(root),
                       selected, prefix, str(row['id']), str(row.get('runner') or ''), 'lutris:rungameid/' + str(row['id']))


def bottles_games(home):
    roots = [home / '.local/share/bottles/bottles', home / '.var/app/com.usebottles.bottles/data/bottles/bottles']
    for root in roots:
        for bottle in root.glob('*'):
            if not bottle.is_dir():
                continue
            data = config(bottle / 'bottle.yml')
            programs = data.get('External_Programs', {})
            if not isinstance(programs, dict):
                continue
            for name, item in programs.items():
                if not isinstance(item, dict):
                    continue
                exe = str(item.get('path') or item.get('executable') or '')
                if exe.lower().startswith('c:'):
                    exe = str(bottle / 'drive_c' / exe[3:].replace('\\','/'))
                if not exe or Path(exe).suffix.lower() != '.exe':
                    continue
                yield Game(game_id('Bottles', str(bottle) + ':' + name), item.get('name') or name, 'Bottles',
                           str(Path(exe).parent), exe, str(bottle), name, str(data.get('Name') or bottle.name))
