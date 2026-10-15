"""Cached upstream metadata and bounded, path-checked archive readers."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlparse, quote
import zipfile

from .storage import atomic_json, read_json

LIMIT = 512 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    name = name.replace('\\', '/')
    path = PurePosixPath(name)
    if not name or name.startswith('/') or '..' in path.parts or re.match(r'^[A-Za-z]:', name):
        raise ValueError('Unsafe archive path: ' + name)
    return str(path)


class Client:
    def __init__(self, directory):
        self.directory = Path(directory) / 'downloads'
        self.directory.mkdir(parents=True, exist_ok=True)

    def fetch(self, url, digest='', refresh=False):
        if urlparse(url).scheme != 'https':
            raise ValueError('Download URLs must use HTTPS')
        path = self.directory / sha(url.encode())
        record = read_json(path.with_suffix('.json'), {})
        if path.is_file() and not refresh and record.get('sha256') == sha(path.read_bytes()):
            payload = path.read_bytes()
        else:
            fd, temporary = tempfile.mkstemp(dir=self.directory)
            os.close(fd)
            try:
                result = subprocess.run(['curl', '-fL', '--proto', '=https', '--proto-redir', '=https',
                                         '--connect-timeout', '10', '--max-time', '180', '--retry', '1',
                                         '--max-filesize', str(LIMIT), '-A', 'OptiDX-Desktop', '-e', 'https://reshade.me/', '-o', temporary, url],
                                        capture_output=True, text=True)
                if result.returncode:
                    raise OSError('Download failed: ' + result.stderr[-600:])
                payload = Path(temporary).read_bytes()
                if len(payload) > LIMIT:
                    raise ValueError('Download exceeds size limit')
                if digest and sha(payload) != digest.removeprefix('sha256:').lower():
                    raise ValueError('Download SHA-256 mismatch')
                os.replace(temporary, path)
                atomic_json(path.with_suffix('.json'), {'url': url, 'sha256': sha(payload), 'time': time.time()})
            finally:
                Path(temporary).unlink(missing_ok=True)
        if digest and sha(payload) != digest.removeprefix('sha256:').lower():
            raise ValueError('Download SHA-256 mismatch')
        return path

    def metadata(self, url, refresh=False):
        path = self.directory / sha(url.encode())
        record = read_json(path.with_suffix('.json'), {})
        age = time.time() - record.get('time', 0)
        return json.loads(self.fetch(url, refresh=(refresh and age > 10) or age > 14400).read_text())

    def releases(self, repo, refresh=False):
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
            raise ValueError('Invalid GitHub repository')
        data = self.metadata('https://api.github.com/repos/' + repo + '/releases?per_page=100', refresh)
        if not isinstance(data, list):
            raise ValueError('Invalid release response')
        return [r for r in data if not r.get('draft')]

    def release_asset(self, repo, pattern, channel='stable', tag='', refresh=False):
        releases = self.releases(repo, refresh)
        if tag:
            releases = [r for r in releases if r.get('tag_name') == tag]
        elif channel == 'stable':
            releases = [r for r in releases if not r.get('prerelease') and 'nightly' not in r.get('tag_name', '').lower()]
        elif channel == 'nightly':
            releases = sorted(releases, key=lambda r: 'nightly' in r.get('tag_name', '').lower(), reverse=True)
        for release in releases:
            assets = [a for a in release.get('assets', []) if re.search(pattern, a.get('name', ''), re.I)
                      and not re.search(r'(?:symbols|debug|pdb|source)', a.get('name', ''), re.I)]
            direct = [a for a in assets if a.get('name', '').lower().endswith(('.addon32', '.addon64', '.asi'))]
            if len(direct) == 1:
                assets = direct
            if len(assets) == 1:
                return {**assets[0], 'version': release['tag_name'], 'repository': repo}
            if len(assets) > 1:
                raise ValueError('Several release assets match; choose an exact asset name or custom file')
        raise ValueError('No matching release asset for ' + repo + (' at ' + tag if tag else ''))


def archive_files(path):
    """Read files without executing installers or trusting archive links."""
    path = Path(path)
    result, total = {}, 0
    seen = set()
    def add(name, size, reader, link=False):
        nonlocal total
        name = safe_name(name)
        if link:
            raise ValueError('Archive links are not supported: ' + name)
        total += size
        if total > LIMIT or len(result) >= 20000:
            raise ValueError('Archive exceeds extraction limits')
        if name.casefold() in seen:
            raise ValueError('Duplicate archive member: ' + name)
        seen.add(name.casefold())
        data = reader()
        if len(data) != size:
            raise ValueError('Archive member size mismatch')
        result[name] = data
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                safe_name(entry.filename)
                if not entry.is_dir():
                    add(entry.filename, entry.file_size, lambda e=entry: archive.read(e),
                        (entry.external_attr >> 16) & 0o170000 == 0o120000)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            for entry in archive:
                safe_name(entry.name)
                if entry.isdir():
                    continue
                if not entry.isfile():
                    raise ValueError('Unsupported tar member: ' + entry.name)
                add(entry.name, entry.size, lambda e=entry: archive.extractfile(e).read())
    else:
        # 7z/NSIS: list and stream individual members; never extract to disk.
        listing = subprocess.run(['7z', 'l', '-slt', '--', str(path)], capture_output=True, text=True, timeout=30)
        if listing.returncode:
            raise ValueError('Unsupported or damaged archive')
        body = listing.stdout.split('----------', 1)[-1]
        for block in body.strip().split('\n\n'):
            values = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
            name = values.get('Path')
            if not name:
                continue
            safe_name(name)
            if values.get('Folder') == '+' or values.get('Attributes', '').startswith('D'):
                continue
            size = int(values.get('Size', 0))
            def read(n=name):
                run = subprocess.run(['7z', 'x', '-so', '-spd', '--', str(path), n], capture_output=True, timeout=60)
                if run.returncode:
                    raise ValueError('Could not read archive member: ' + n)
                return run.stdout
            add(name, size, read, bool(values.get('Symbolic Link') or values.get('Hard Link')))
    if not result:
        raise ValueError('Archive contains no files')
    return result


def binary_member(files, filename, bits=64):
    from .inspection import compatible_binary
    matches = [(n, d) for n, d in files.items() if PurePosixPath(n).name.casefold() == filename.casefold()
               and not any(p.lower() in {'debug', 'development'} for p in PurePosixPath(n).parts)]
    # Architecture directory names disambiguate Streamline and DXVK archives.
    appropriate = [(n, d) for n, d in matches if not any(p.lower() in
                   ({'x32', 'x86', 'win32', 'arm64', 'aarch64'} if bits == 64 else {'x64', 'win64', 'arm64', 'aarch64'}) for p in PurePosixPath(n).parts)]
    if len(appropriate) != 1:
        raise ValueError('Expected exactly one ' + filename + ' for this architecture')
    data = appropriate[0][1]
    with tempfile.NamedTemporaryFile() as f:
        f.write(data); f.flush()
        compatible = compatible_binary(f.name, bits)
    if not compatible:
        raise ValueError(filename + ' does not match the game architecture')
    return data
