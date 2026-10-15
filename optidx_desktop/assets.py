"""Reversible ownership for shaders, addons, presets and original game DLLs."""
import base64
import copy
import os
from pathlib import Path
import tempfile

from .downloads import sha
from .inspection import contained, manifest_paths
from .storage import atomic_json, read_json

ORIGINALS = '.optidx-desktop-originals'

LEDGER = '.optidx-desktop-assets.json'


def atomic_bytes(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(pending, mode)
        os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def state(root):
    value = read_json(Path(root) / LEDGER, {'version': 1, 'groups': {}})
    if value.get('version') != 1 or not isinstance(value.get('groups'), dict):
        raise ValueError('Unsupported asset ownership record')
    return value


class Conflict(ValueError):
    pass


def deploy(root, group, files, metadata=None, allow_foreign=False):
    """Preflight the whole group; save originals and roll back failed writes."""
    root = Path(root)
    ledger = state(root)
    backend_owned = set(manifest_paths(root))
    old = ledger['groups'].get(group, {})
    previous = old.get('files', {})
    owners = {name.casefold(): key for key, item in ledger['groups'].items() for name in item['files'] if key != group}
    lowered = set()
    spellings = {}
    existing_spellings = {}
    for name, data in files.items():
        path = contained(root, name)
        # Wine treats these names as equal even on a case-sensitive filesystem.
        # Reject ambiguous spellings instead of creating two competing DLLs.
        current = root
        prefix = []
        for part in Path(name).parts:
            prefix.append(part)
            spelling = '/'.join(prefix)
            if spelling.casefold() in spellings and spellings[spelling.casefold()] != spelling:
                raise Conflict('Conflicting path capitalization: ' + name)
            spellings[spelling.casefold()] = spelling
            if current not in existing_spellings:
                names = {}
                if current.is_dir():
                    for child in current.iterdir():
                        names.setdefault(child.name.casefold(), set()).add(child.name)
                existing_spellings[current] = names
            if existing_spellings[current].get(part.casefold(), set()) - {part}:
                raise Conflict('Existing path uses different capitalization: ' + name)
            current = current / part
        if name.casefold() in lowered:
            raise ValueError('Case-insensitive file collision: ' + name)
        lowered.add(name.casefold())
        if name.casefold() in owners:
            raise Conflict(name + ' belongs to ' + owners[name.casefold()])
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise Conflict('Cannot replace a link or directory: ' + name)
        if path.is_file():
            expected = previous.get(name, {}).get('sha256')
            if expected and sha(path.read_bytes()) != expected:
                raise Conflict('Managed file was edited outside the app: ' + name)
            if not expected and path.read_bytes() != data and not allow_foreign and name not in backend_owned:
                raise Conflict('Existing file needs explicit replacement approval: ' + name)
    for name, record in previous.items():
        path = contained(root, name)
        if path.exists() and (path.is_symlink() or sha(path.read_bytes()) != record['sha256']):
            raise Conflict('Managed file was edited outside the app: ' + name)
    touched = set(files) | set(previous)
    before = {n: (contained(root, n).read_bytes(), contained(root, n).stat().st_mode & 0o777)
              if contained(root, n).is_file() else None for n in touched}
    records = {}
    try:
        for name in touched:
            path = contained(root, name)
            if name in files:
                original = previous.get(name, {}).get('original')
                if name not in previous and before[name] is not None and name not in backend_owned:
                    digest = sha(before[name][0])
                    original_path = contained(root, ORIGINALS + '/' + digest)
                    if not original_path.is_file():
                        atomic_bytes(original_path, before[name][0], 0o600)
                    elif sha(original_path.read_bytes()) != digest:
                        raise ValueError('Original backup blob checksum mismatch')
                    original = {'blob': digest, 'mode': before[name][1], 'sha256': digest}
                atomic_bytes(path, files[name])
                records[name] = {'sha256': sha(files[name]), 'original': original}
            else:
                restore_file(path, previous[name], root)
        if records:
            ledger['groups'][group] = {'files': records, 'metadata': metadata or old.get('metadata', {})}
        else:
            ledger['groups'].pop(group, None)
        atomic_json(root / LEDGER, ledger)
    except Exception:
        for name, record in before.items():
            path = contained(root, name)
            if record is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, *record)
        raise
    return ledger


def restore_file(path, record, root):
    original = record.get('original')
    if original:
        if original.get('blob'):
            if len(original['blob']) != 64 or any(c not in '0123456789abcdef' for c in original['blob']):
                raise ValueError('Invalid original backup blob')
            data = contained(root, ORIGINALS + '/' + original['blob']).read_bytes()
        else:
            data = base64.b64decode(original['data'], validate=True)
        if sha(data) != original['sha256']:
            raise ValueError('Original file backup checksum mismatch')
        atomic_bytes(path, data, original['mode'])
    else:
        path.unlink(missing_ok=True)


def remove(root, group):
    return deploy(root, group, {})


def toggle_addon(root, group, enabled):
    item = state(root)['groups'][group]
    files = {}
    if any(r.get('original') for r in item['files'].values()):
        raise Conflict('This addon replaced an original file; remove/restore it before toggling')
    for name in item['files']:
        if name.lower().endswith(('.addon', '.addon32', '.addon64', '.addon.disabled', '.addon32.disabled', '.addon64.disabled')):
            destination = name.removesuffix('.disabled') if enabled else name.removesuffix('.disabled') + '.disabled'
        else:
            destination = name
        files[destination] = contained(root, name).read_bytes()
    return deploy(root, group, files, {**item['metadata'], 'enabled': enabled})
