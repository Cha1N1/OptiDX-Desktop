"""Read-only check for newer OptiDX Desktop releases.

The app never replaces itself: it reports a newer release and links to it. The
AppImage also embeds update information for AppImageUpdate-compatible tools.
"""

import re

from . import __version__
from .downloads import Client

REPOSITORY = "Cha1N1/OptiDX-Desktop"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
UPDATE_INFORMATION = (
    f"gh-releases-zsync|{REPOSITORY.replace('/', '|')}|latest|OptiDX-Desktop-*x86_64.AppImage.zsync"
)


def parse_version(text):
    match = re.search(r"(\d+(?:\.\d+)*)", str(text or ""))
    if not match:
        raise ValueError(f"Unrecognized version: {text!r}")
    return tuple(int(part) for part in match[1].split("."))


def newer_release(directory, current=__version__, client=None):
    """Return {"version", "url"} for a newer stable release, otherwise None."""
    client = client or Client(directory)
    release = client.metadata(LATEST_URL, refresh=True)
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    tag = release.get("tag_name", "")
    if parse_version(tag) <= parse_version(current):
        return None
    url = release.get("html_url", "")
    if not url.startswith(f"https://github.com/{REPOSITORY}/"):
        url = RELEASES_PAGE
    return {"version": tag.lstrip("v"), "url": url}
