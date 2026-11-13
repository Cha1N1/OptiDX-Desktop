"""Editable OptiScaler.ini presets with explicit application.

RHI's per-GPU templates are downloaded on first use. Built-in presets are
generated locally; ``optidx`` carries the settings the retired Cha1N1/OptiScaler
fork shipped as its OptiScaler.ini defaults.
"""

import configparser

from .assets import atomic_bytes
from .downloads import Client
from .features import ini_edit

TEMPLATES = {
    f"{gpu}-{channel}": f"OptiScaler{suffix}.{gpu}.ini"
    for gpu in ["nvidia", "amd-dlss", "amd-nodlss"]
    for channel, suffix in [("stable", ""), ("nightly", "_nightly")]
}

# Built-in presets: file name, sections. Unlike RHI templates they may set frame
# generation, because choosing that route is the point of the preset.
BUILTIN = {
    "optidx": (
        "OptiScaler.optidx.ini",
        {
            "Upscalers": {"Dx12Upscaler": "ffx"},
            "FrameGen": {"FGInput": "dlssg", "FGOutput": "xefg"},
            "XeFG": {"InterpolationCount": "5"},
        },
    ),
}
BUILTIN_HEADER = """; OptiDX OptiScaler.ini preset (formerly the Cha1N1/OptiScaler fork defaults).
; Only these keys are written; every other setting in OptiScaler.ini is kept.
; Dx12Upscaler=ffx uses FSR 4 / the installed FFX upscaler in DX12 games.
; FGInput=dlssg with FGOutput=xefg runs XeSS FG from the game's DLSS FG inputs.
; [XeFG] InterpolationCount=5 allows up to 6X (lower it, or enable V-Sync, if pacing suffers).
"""


def template_path(repository, key):
    if key in BUILTIN:
        return repository.directory / "templates" / BUILTIN[key][0]
    if key not in TEMPLATES:
        raise ValueError("Unknown GPU template")
    return repository.directory / "templates" / TEMPLATES[key]


def builtin_text(key):
    lines = [BUILTIN_HEADER]
    for section, values in BUILTIN[key][1].items():
        lines.append("[" + section + "]")
        lines.extend(name + "=" + value for name, value in values.items())
        lines.append("")
    return "\n".join(lines)


def prepare(repository, key):
    path = template_path(repository, key)
    if key in BUILTIN:
        # Editable once written; a user's edits are kept like downloaded templates.
        if not path.is_file():
            payload = builtin_text(key).encode()
            validate(payload)
            atomic_bytes(path, payload)
        return path
    if not path.is_file():
        url = "https://raw.githubusercontent.com/RankFTW/RHI/main/RenoDXCommander/" + TEMPLATES[key]
        payload = Client(repository.directory).fetch(url).read_bytes()
        validate(payload)
        atomic_bytes(path, payload)
    return path


def validate(data):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(data.decode("utf-8-sig"))
    if not parser.sections():
        raise ValueError("Template contains no INI sections")
    return parser


def apply(game, repository, options):
    path = prepare(repository, options["id"])
    parser = validate(path.read_bytes())
    destination = game.target / "OptiScaler.ini"
    if not destination.is_file():
        raise ValueError("Install OptiScaler before applying its GPU template")
    # HelixSR forwarding, custom library locations and explicit FG settings must
    # remain independent of a generic GPU template. Built-in presets set FG.
    protected = {"libraries", "plugins"} | (set() if options["id"] in BUILTIN else {"framegen"})
    sections = {
        section: dict(parser[section])
        for section in parser.sections()
        if section.casefold() not in protected
    }
    atomic_bytes(
        destination,
        ini_edit(destination.read_bytes(), sections),
        destination.stat().st_mode & 0o777,
    )
    from .assets import accept_config_edit

    accept_config_edit(game.target, "OptiScaler.ini")
    return {"path": str(destination), "template": str(path)}
