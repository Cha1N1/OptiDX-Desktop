"""Qt-free game status shared by the library list, details and action buttons.

Each record is read once per refresh. Unreadable records are reported for their
own game instead of breaking the library: management jobs still read strictly and
refuse to run, so corrupt evidence is never overwritten implicitly.
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import assets
from .components import selection_problems
from .inspection import DIRECTX_INPUTS
from .storage import read_json

SUPPORTED_APIS = DIRECTX_INPUTS | {"DX9", "DX10", "OpenGL"}


@dataclass(frozen=True)
class GameStatus:
    game: object
    profile: dict = field(default_factory=dict)
    update: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)  # scope -> asset ledger groups
    backend_installed: bool = False
    errors: tuple = ()
    profile_error: str = ""

    @property
    def installed(self):
        return self.backend_installed or any(self.groups.values())

    @property
    def display_name(self):
        return self.profile.get("display_name") or self.game.title

    @property
    def needs_attention(self):
        return bool(self.errors)

    @property
    def update_available(self):
        return bool(self.update.get("update_available"))

    def group_names(self):
        return sorted({name for groups in self.groups.values() for name in groups})


def scopes(game):
    """Ownership scopes in a stable order, without duplicating root == target."""
    result = {"target": game.target}
    if Path(game.root) != game.target:
        result["root"] = Path(game.root)
    return result


def game_status(game, repository):
    errors = []

    def attempt(reader, default):
        try:
            return reader()
        except (OSError, ValueError) as error:
            errors.append(str(error))
            return default

    profile = attempt(lambda: repository.preferences(game), None)
    profile_error = errors[-1] if profile is None else ""
    update = attempt(
        lambda: read_json(repository.directory / "updates" / (game.id + ".json"), {}), {}
    )
    groups = {}
    backend_installed = False
    if game.available:
        for scope, root in scopes(game).items():
            groups[scope] = attempt(lambda root=root: assets.state(root)["groups"], {})
        backend_installed = attempt(lambda: (game.target / ".optidx-files").is_file(), False)
    return GameStatus(
        game,
        profile or {},
        update if isinstance(update, dict) else {},
        groups,
        backend_installed,
        tuple(errors),
        profile_error,
    )


def install_problems(chosen, detected, helixsr_dll=None):
    """Dependency and exclusivity problems for a component selection."""
    problems = selection_problems(chosen, detected)
    if "helixsr" in chosen and helixsr_dll is not None:
        if not helixsr_dll.strip() or not Path(helixsr_dll).expanduser().is_file():
            problems.append("Choose the locally built HelixSR FSR DLL")
    return problems


@dataclass(frozen=True)
class ActionState:
    enabled: bool
    reason: str = ""


def action_states(status, info, *, busy, chosen, prune, problems, launchable):
    """Availability and the user-facing reason for each game action."""
    if status is None:
        reason = "Choose a game."
    elif busy:
        reason = "Another operation is running."
    elif status.errors:
        reason = "Unreadable record: " + status.errors[0]
    elif not info.get("executable_exists"):
        reason = "Select an existing executable in Installation → diagnostics."
    else:
        reason = "; ".join(problems)
    ready = status is not None and not busy and not status.errors
    exists = bool(info.get("executable_exists"))
    supported = not info.get("apis") or bool(set(info["apis"]).intersection(SUPPORTED_APIS))
    installed = bool(status and status.installed)
    install = ready and exists and supported and bool(chosen or prune) and not problems
    states = {
        "install": ActionState(
            install,
            reason or ("" if install else "Select a component or use a supported graphics API."),
        ),
        "update": ActionState(
            ready and exists and supported and installed,
            reason or "No managed installation found.",
        ),
        "remove": ActionState(
            ready and exists and installed, reason or "No managed installation found."
        ),
        "configure": ActionState(ready and exists, reason),
        "launch": ActionState(
            status is not None and not busy and launchable,
            reason if status is None or busy else "Configure a runner in Launch options.",
        ),
        "save": ActionState(
            status is not None and not status.profile_error,
            (
                "The saved profile is unreadable; repair or remove it first: "
                + status.profile_error
                if status is not None and status.profile_error
                else ""
            ),
        ),
    }
    return {
        key: ActionState(value.enabled, "" if value.enabled else value.reason)
        for key, value in states.items()
    }


def launchable(game, profile):
    return bool(game.launch_uri or game.store == "Bottles" or profile.get("runner_command"))
