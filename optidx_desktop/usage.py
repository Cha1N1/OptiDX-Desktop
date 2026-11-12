"""Disk usage of app data and explicit/automatic cleanup of disposable caches.

Download caches are disposable: payloads are fetched again when a job needs them.
Backups, imports, profiles and recovery records are reported but never deleted
here; snapshot cleanup keeps using backups.cleanup_completed_snapshots.
"""

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import shutil
import time

CACHE_MAX_AGE_DAYS = 30


def backend_cache_dir():
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "optidx"


def tree_size(path, seen=None):
    """Bytes used below path, counting hard-linked snapshot objects once."""
    seen = set() if seen is None else seen
    total = 0
    path = Path(path)
    if not path.exists() or path.is_symlink():
        return 0
    for folder, directories, files in os.walk(path):
        directories[:] = [d for d in directories if not Path(folder, d).is_symlink()]
        for name in files:
            try:
                info = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            key = (info.st_dev, info.st_ino)
            if key not in seen:
                seen.add(key)
                total += info.st_size
    return total


def cache_locations(repository):
    return {
        "App download cache": repository.directory / "downloads",
        "Component payload cache": backend_cache_dir() / "payloads",
    }


def usage(repository):
    """Ordered (label, path, bytes, disposable) rows for the storage panel."""
    rows = [
        ("Backups and verified originals", repository.directory / "backups", False),
        *((label, path, True) for label, path in cache_locations(repository).items()),
        ("Imported custom assets", repository.directory / "custom", False),
        ("Job logs", repository.directory / "logs", False),
    ]
    seen = set()
    return [(label, path, tree_size(path, seen), disposable) for label, path, disposable in rows]


def human(size):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _hold_job_locks(stack, repository):
    """Take every game lock without waiting so no running job loses its payload."""
    locks = repository.directory / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    for path in sorted(locks.glob("*.lock")):
        lock = stack.enter_context(path.open("a"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


def clean_download_caches(repository, max_age_days=0, now=None):
    """Delete cached downloads older than max_age_days (0 = all).

    Returns (files removed, bytes freed), or None when a job is running.
    """
    now = time.time() if now is None else now
    cutoff = now - max_age_days * 86400
    removed = freed = 0
    with ExitStack() as stack:
        if not _hold_job_locks(stack, repository):
            return None
        for root in cache_locations(repository).values():
            if not root.is_dir() or root.is_symlink():
                continue
            for entry in root.iterdir():
                try:
                    info = entry.lstat()
                except OSError:
                    continue
                if max_age_days and info.st_mtime > cutoff:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    size = tree_size(entry)
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    size = info.st_size
                    entry.unlink(missing_ok=True)
                removed += 1
                freed += size
    return removed, freed
