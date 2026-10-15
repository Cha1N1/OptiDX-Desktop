"""Read launcher metadata without launching games or modifying launcher settings."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode

from .models import Game, game_id
from .storage import read_json

SKIP_EXE = re.compile(r"crash|unins|redist|setup|easyanticheat|beservice|prereq|cef|installer", re.I)


def vdf_parse(text):
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', re.sub(r"(?m)^\s*//.*$", "", text))
    values = [s.replace('\\\\', '\\').replace('\\"', '"') if not brace else brace for s, brace in tokens]
    index = 0

    def block():
        nonlocal index
        result = {}
        while index < len(values):
            key = values[index]
            index += 1
            if key == "}":
                return result
            if index >= len(values):
                break
            value = values[index]
            index += 1
            result[key] = block() if value == "{" else value
        return result

    return block()


def find_executable(root, limit=600):
    best, best_score, count = "", -10000, 0
    for directory, dirs, files in os.walk(root):
        if len(Path(directory).relative_to(root).parts) >= 7:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if d.lower() not in {".git", "redist", "__pycache__"})
        for name in sorted(files):
            if not name.lower().endswith(".exe") or SKIP_EXE.search(name):
                continue
            count += 1
            if count > limit:
                return best
            path = Path(directory) / name
            score = 100 - len(name) // 2
            low = str(path).lower().replace("\\", "/")
            if name.lower().endswith("shipping.exe"):
                score += 100
            if name.lower().endswith("game.exe"):
                score += 50
            if "win64" in name.lower():
                score += 20
            if "/binaries/win64/" in low:
                score += 40
            if "/engine/" in low or "launcher" in name.lower():
                score -= 60
            try:
                score += min(path.stat().st_size // 10_000_000, 30)
            except OSError:
                continue
            if score > best_score:
                best, best_score = str(path), score
    return best


def steam_games(home):
    roots = [home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root",
             home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    libraries = set()
    for root in roots:
        if not root.is_dir():
            continue
        libraries.add(root.resolve())
        file = root / "steamapps/libraryfolders.vdf"
        if file.is_file():
            folders = vdf_parse(file.read_text(errors="replace")).get("libraryfolders", {})
            for key, value in folders.items():
                if str(key).isdigit():
                    path = value.get("path") if isinstance(value, dict) else value
                    if path:
                        libraries.add(Path(path))
    for library in sorted(libraries):
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            data = vdf_parse(manifest.read_text(errors="replace")).get("AppState", {})
            app_id, directory = data.get("appid"), data.get("installdir")
            if not app_id or not directory or Path(directory).is_absolute() or ".." in Path(directory).parts:
                continue
            root = library / "steamapps/common" / directory
            if not root.is_dir():
                continue
            if re.search(r"^(Proton|Steam Linux Runtime|Steamworks Common)", data.get("name", "")):
                continue
            yield Game(game_id("Steam", root.resolve()), data.get("name", directory), "Steam", str(root),
                       find_executable(root), str(library / "steamapps/compatdata" / app_id / "pfx"),
                       app_id, "steam", "steam://rungameid/" + app_id)


def heroic_games(home):
    roots = [home / ".config/heroic", home / ".var/app/com.heroicgameslauncher.hgl/config/heroic"]
    for config in roots:
        sideload = read_json(config / "sideload_apps/library.json", {}).get("games", [])
        if isinstance(sideload, dict):
            sideload = list(sideload.values())
        legendary = read_json(config / "legendaryConfig/legendary/installed.json", {})
        gog = read_json(config / "store_cache/gog_install_info.json", {})
        for runner, entries in [("sideload", sideload), ("legendary", list(legendary.values())),
                                ("gog", list(gog.values()) if isinstance(gog, dict) else gog)]:
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("is_dlc"):
                    continue
                install = entry.get("install", {})
                key = str(entry.get("app_name") or entry.get("appName") or entry.get("gameId") or "")
                executable = str(install.get("executable") or entry.get("executable") or "")
                root = entry.get("install_path") or entry.get("installPath") or entry.get("folder_name")
                if not root and executable:
                    root = str(Path(executable).parent)
                if not root or not key:
                    continue
                root = Path(root)
                if executable and not Path(executable).is_absolute():
                    executable = str(root / executable.replace("\\", "/"))
                # Heroic's top-level executable can be a launcher; use the UE shipping binary for injection.
                selected = find_executable(root) if root.is_dir() else ""
                executable = selected or executable
                profile = read_json(config / "GamesConfig" / (key + ".json"), {}).get(key, {})
                uri = "heroic://launch?" + urlencode({"appName": key, "runner": runner})
                yield Game(game_id("Heroic", root.resolve()), entry.get("title") or root.name, "Heroic", str(root),
                           executable, profile.get("winePrefix", ""), key, runner, uri,
                           "flatpak" if config == roots[1] else "native")


def scan_library(home=None, cached=()):
    home = Path(home) if home else Path.home()
    # Cached entries survive an unplugged drive. Discovery only refreshes matching IDs.
    games = {game.id: game for game in cached}
    warnings = []
    import sqlite3
    from .extra_library import lutris_games, bottles_games
    for name, scanner in [("Steam", steam_games), ("Heroic", heroic_games), ("Lutris", lutris_games), ("Bottles", bottles_games)]:
        try:
            for game in scanner(home):
                games[game.id] = game
        except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error) as error:
            warnings.append(f"{name}: {error}")
    return sorted(games.values(), key=lambda g: g.title.casefold()), warnings


def manual_game(executable, title=""):
    path = Path(executable).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".exe":
        raise ValueError("Choose the Windows game executable (.exe).")
    root = path.parent
    if root.name.lower() in {"win64", "win32"} and root.parent.name.lower() == "binaries":
        root = root.parent.parent
        if (root.parent / "Engine").is_dir():
            root = root.parent
    return Game(game_id("Manual", path), title or root.name, "Manual", str(root), str(path))
