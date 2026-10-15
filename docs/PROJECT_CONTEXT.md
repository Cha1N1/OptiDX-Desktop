# OptiDX Desktop project context

This is the continuation record for the standalone Linux desktop application.
Use release notes for shipped changes and focused reports for detailed findings.

## Boundaries and durable decisions

- Primary folder: `/home/DwE/OptiDX-Desktop`.
- Original script: `/home/DwE/OptiDX`, preserved separately.
- OptiScaler fork: `/home/DwE/OptiScaler`, a separate project.
- App state: `$XDG_DATA_HOME/optidx-desktop`, otherwise
  `~/.local/share/optidx-desktop`.
- Backups: `/home/DwE/project-backups`.

The desktop backend began as an OptiDX 2.1.2 snapshot and has independent changes.
Its current and original provenance live in `backend/SNAPSHOT.json` and
`backend/UPSTREAM_SNAPSHOT.json` respectively.

Provide an RHI-inspired Linux workflow with independent component choices,
per-game management, and bulk updates. Explain platform gaps explicitly.
Keep core installation, HDR/configuration, ReShade content, installed tools,
game DLLs, optional tools, launch settings, and profiles clearly separated.
Buttons must describe what they change; profile saving does not deploy files.

Pre-installing mods does not require launching the game. Wrappers remain useful
for managed environments and deferred Unreal HDR configuration. Preserve unmanaged
files and verified originals. File detection is not proof of runtime compatibility.

Cyboman lossy FSR comes from official
`zgauthier2000/fsr4-shader-performance-overrides` releases, selecting the lossy DLL
from the archive. HelixSR remains optional and off for new profiles because direct
lossy FSR worked better for the user's setup. Preserve existing explicit selections.
Targeted HelixSR removal restores direct FSR without removing unrelated mods.
HelixSR assets are prepared locally; startup must not compile weights.

D3D-prefixed ReShade naming avoids a confirmed Wine WGL recursion problem.
Native/Flatpak Heroic games must use their corresponding installation. CachyOS's
`heroic` command may be an Electron wrapper; do not hard-code `/opt` paths.

## Checkpoint — 2026-10-15

Desktop version: **0.3.4**. Artifact:
`dist/OptiDX-Desktop-0.3.4-x86_64.AppImage`, with a SHA-256 sidecar.
This is a historical checkpoint; consult `optidx_desktop/__init__.py` and
`RELEASE_NOTES.md` for later versions.

The latest review fixed queued-game targeting, delayed callbacks, failed-operation
metadata recovery, mapped Wine paths for HelixSR removal, shared-profile leakage,
Heroic origin selection, PE architecture validation, filename conflicts, and
environment validation. See [the review report](REVIEW_2026-10-15.md).

At this checkpoint, 122 tests passed in source and with the bundled interpreter;
the checksum and offscreen FUSE-free startup were checked. Validation used temporary
game folders. Gameplay and all live download sources were not verified. No real
game installation was changed by that review.

ReLimiter's repeated `AvSetMmMaxThreadCharacteristicsA failed err=1550` warning is
an external addon/Wine interaction. It was diagnosed, not patched in this project.
Disabling the addon takes effect after restarting the game.

Pre-review source backup:
`/home/DwE/project-backups/OptiDX-Desktop-0.3.3-before-review-20261015.tar.gz`.
Original script backup:
`/home/DwE/project-backups/OptiDX-2.1.2-20261012-004108.tar.gz`.

## Working preferences

Use focused checks during iteration and the full suite for backend/release work.
Avoid redundant tests, unnecessary rebuilding, repetitive approval questions, and
overlapping settings. Explain concrete findings and limitations concisely.
Do not commit, push, or publish without a request. Keep the original script separate.

Future chats should read `AGENTS.md` and relevant task documentation. Update this
record when durable decisions change; project membership does not replace docs.

## Development workflow update — 2026-10-15

Implemented the eight agreed quality-of-life improvements in source, without a
version bump or AppImage rebuild: persistent raw per-game drafts with Save/Revert,
component status beside selectors, disabled-action explanations, persistent job
history and individual queue removal, bulk-update preview, visible launch routing
and wrapper copy, verified snapshot browsing/restoration, and workspace persistence
with sorting and keyboard shortcuts. UI helpers live in `optidx_desktop/qol.py`.

Drafts must preserve invalid/incomplete text without validating or deploying it.
Bulk updates use saved profiles. Recovery restores recorded files only; it retains
newer unrecorded files and refuses to orphan newer ownership/journal data. Restore
runs under the existing worker lock, verifies all source files before writes, takes
fresh snapshots and uses the existing failed-operation rollback. It does not restore
external HDR configuration, profiles or baseline pointers. Full removal remains a
separate workflow. Older snapshots without action metadata are labelled accordingly.

Pre-change source/uncommitted/Git backup:
`/home/DwE/project-backups/OptiDX-Desktop-before-qol-20261015.tar.gz`.

Validation: 134 tests pass. Fresh offscreen fixture renders were inspected at
1220×880 and 930×740. No real game files were changed, games launched or live
compatibility claims added. The packaged 0.3.4 AppImage remains the earlier build;
run `./run.sh` to use these source changes.

## Packaging preference — 2026-10-15

The user wants an updated AppImage after app changes and prefers it over `run.sh`.
Rebuild and validate the local AppImage as part of implementation by default.
Documentation-only edits need no rebuild. Keep version bumps and publication
separate unless requested. The quality-of-life source changes are now packaged
under the existing 0.3.4 version; the previous source-only checkpoint above is historical.

Rebuilt `dist/OptiDX-Desktop-0.3.4-x86_64.AppImage` (61.0 MiB) using the existing
local runtime. SHA-256 sidecar passes; all 134 tests pass with the bundled
interpreter. FUSE-free offscreen startup and backend help pass. Run extraction
checks sequentially because this local runtime shares an extraction cache.

## UI consistency and motion — 2026-10-15

Use a Fusion base with an explicit dark palette (`theme.py`) so platform popup
frames do not introduce light outlines. Shared QSS covers scrollbars, dropdowns,
menus, tooltips, focus and pressed states. SVG URLs use absolute file paths.
Keep keyboard focus visible in muted teal rather than removing focus feedback.
`motion.py` provides interruptible 110 ms page fades and 140 ms section resizing;
completed expansion releases its height constraint for later layout changes.
App settings → Reduce motion disables those transitions. Actions remain immediate.
The 137-test suite passes, including rapid animation reversal, page cleanup and
reduced motion. Fresh normal/compact/popup offscreen previews were inspected;
actual compositor rendering still depends on the host desktop.

The local 0.3.4 AppImage was rebuilt with these UI changes. All 137 checks pass
with bundled Python, checksum verification passes, and FUSE-free offscreen startup
and backend help pass. No games were launched or real game files changed.

## Native Wayland selection — 2026-10-15

The user's xwininfo output proved their running OptiDX window used XWayland;
an earlier bare bundled-Qt probe choosing Wayland did not establish that window's
backend. The GUI now supplies Qt `-platform wayland;xcb` when WAYLAND_DISPLAY or
XDG_SESSION_TYPE indicates Wayland and QT_QPA_PLATFORM is unset/empty. Explicit
platform overrides, including offscreen tests and xcb, are preserved. Selection
uses QApplication arguments only, so launcher/game environment is unchanged.
Footer and copied diagnostics report the actual loaded Qt platform. Existing
windows need a restart to switch display backends.

Rebuilt local 0.3.4 AppImage and verified its actual native Wayland startup on the
host desktop using fresh temporary data and --screenshot (no forced platform).
The captured footer reads Wayland. All 139 tests pass in source and bundled
Python; checksum and FUSE-free backend help pass. No game scan or game mutation.

## Nemo launch correction — 2026-10-15

Host process inspection confirmed Nemo and its OptiDX child inherited
`QT_QPA_PLATFORM=xcb;wayland`, while terminal launches had no override. That list
selected xcb despite native Wayland support. On Wayland sessions `gui_arguments`
now moves native Wayland entries ahead of xcb in mixed fallback lists, preserving
plugin options and other choices. Single explicit backends and X11 sessions are
unchanged. This remains scoped to QApplication argv; launcher environments retain
their original values. Nemo itself and desktop-wide settings are not modified.

Rebuilt the local 0.3.4 AppImage; 141 tests pass with bundled Python and checksum
verification passes. Real-host FUSE-free startup using Nemo's exact
QT_QPA_PLATFORM=xcb;wayland now captures a Wayland footer. Backend help passes.
This reproduced Nemo's environment without altering Nemo or real game files.

## Accelerated wheel scrolling — 2026-10-15

`scrolling.py` installs a window-scoped Qt event filter for scroll-area viewports,
including dynamically created child dialogs. Item views scroll in pixels.
Wheel targets ease over 140 ms; same-direction ticks within 220 ms progressively
accelerate, capped at 3.1×, with pending travel capped to 1.5 viewport lengths.
Pauses/reversals reset the burst; reversals discard the old target. Dragging,
scrollbar actions, range changes, keyboard/click input and hiding cancel motion.
Boundary wheels remain available for Qt propagation. Pixel/phase/touchpad gestures,
modifier wheels and popup lists retain native handling. Plain text editors retain
Qt's line-based scrollbar units. Reduce motion bypasses smoothing and acceleration.
This affects UI scrolling only, not any game/profile/deployment behavior.

Validation: all 148 tests pass with bundled Python, including real Qt wheel-event
delivery, acceleration/reset/reversal, fractional input, bounded travel, manual
cancellation, precision passthrough and reduced motion in child dialogs. Fresh
offscreen startup preview inspected. Rebuilt the local 0.3.4 AppImage; checksum,
FUSE-free startup and backend help pass. Hardware mouse/touchpad feel remains a
user check; no games were launched or real game files changed.

## Layout spacing cleanup — 2026-10-15

A fresh geometry probe found the styled splitter reporting handleWidth=-1 and
its two columns overlapping by one logical pixel. Do not rely on QSS width for
QSplitter handles. Set handle width explicitly (20 logical pixels), keep columns
non-collapsible, and give details 4 pixels of left padding. Library controls use
8-pixel spacing, details 10, navigation/content 12. Navigation width is 156 so
labels fit more consistently. Saved splitter ratios remain usable. These are
focused layout changes; profile and game operations are unchanged.
Fresh fixture previews inspected at 1220×880 and 930×740, with an additional
2000×1100 render. Geometry regression covers resizing and restored splitter sizes.

All 149 tests pass in source and bundled Python. Rebuilt local 0.3.4 AppImage;
SHA-256 verification, fresh FUSE-free offscreen startup and backend help pass.
No real game installation was changed or launched during this cleanup.

## Appearance modes — 2026-10-15

App settings now offers Original / Dark / Light / System. Original (the existing
navy/teal design) remains the default for existing and new data directories.
Dark uses neutral charcoal colors, Light pale surfaces/darker teal accents.
`theme.py` recolors the existing shared QSS without changing geometry. Native
palette roles, popups, help/status text and light-theme SVG icons match the mode.
Avoid inline fixed-color styles in new UI controls; use semantic object names or
properties so theme switching can update existing widgets.

Appearance applies/saves immediately in app settings; saving other settings merges
existing fields so theme and future fields are retained. Theme changes do not
save game drafts or deploy files. System listens to QStyleHints.colorSchemeChanged;
forced modes ignore desktop changes. Unknown desktop preference falls back to the
initial native palette, captured before app colors are applied. Qt on the actual
host reported ColorScheme.Dark; desktop preference was read without changing it.
Reference: https://doc.qt.io/qt-6/qstylehints.html#colorScheme-prop

Tests cover persistence, app-setting preservation, incomplete drafts, live scheme
signals, light popup/icons and body/muted text contrast. Fresh offscreen Original,
Dark, Light and app-settings previews were inspected.

Validation: all 155 checks pass in source and bundled Python. Rebuilt local 0.3.4
AppImage; checksum, FUSE-free startup and backend help pass. A real-host packaged
System-mode preview selected the desktop's Dark preference and ran under Wayland
with Nemo's inherited fallback list. Live changes were tested via Qt appearance
signals without changing the user's desktop theme. No real game files changed.

## Final three-mode appearance — 2026-10-15

Supersedes the four-mode design above. Appearance is now Dark / Light / System.
Dark is exactly the original navy/teal styling; the charcoal preset was removed.
Saved `original` settings migrate to `dark`, preserving other settings. Default
and invalid selections resolve to Dark. Light remains the existing light preset.

System uses actual native Qt palette roles for surfaces/text/buttons/selections,
not a light/dark preset. `system_palette.py` captures native colors before app
styling and observes native application palette changes. App presets now set only
owned window/dialog palettes; do not override QApplication's palette, which would
contaminate future native palette reads. KDE's current `Colors:*` groups are read
from XDG_CONFIG_HOME/kdeglobals to avoid bundling KDE platform-theme dependencies
and to preserve custom schemes inside AppImages. QFileSystemWatcher watches the
file/parent, debounces updates and reattaches after atomic replacement. No desktop
preferences are written. Other desktops use Qt's native palette. System icons are
recolored into temporary SVGs; personal theme configuration is never packaged.

The custom control shapes, spacing and animations stay consistent in all modes.
Focused tests cover native color/selection updates, app-palette isolation, RGB KDE
settings, atomic replacement, and legacy migration without saving game drafts.

Validation: 158 tests pass in source and bundled Python. Fresh compact/settings
System previews and a real-host packaged Wayland preview were inspected; the
packaged UI uses the desktop's actual purple/lavender palette. Rebuilt local 0.3.4
AppImage; checksum, FUSE-free startup and backend help pass. Native SVG icons use
an absolute temporary directory, so System mode also works from read-only launch
locations. No desktop preferences or real game files were changed.

## Public README preparation — 2026-10-15

The user intends to publish Desktop separately while keeping
https://github.com/Cha1N1/OptiDX script-only. Rewrote README.md for public users:
AppImage-first setup, first-use flow, action boundaries, recovery, actual platform
limits, issue-report guidance and credits. Added docs/screenshots/desktop.png from
synthetic library entries in isolated temporary data; no personal library or game
installation is included. Removed machine-specific development paths from README.

The new Desktop GitHub repository name/URL has not been provided and no remote is
configured; README does not invent one. No repository creation, commit, push,
version bump or release publication was requested or performed. Local README
links, code fences and the 0.3.4 AppImage filename were checked. Documentation-only
work does not require an AppImage rebuild or another full test run.

## Source cleanup and export — 2026-10-15

Removed 36 leftover root `optidx-theme-icons-*` directories after verifying they
were empty or contained only the generated hash-named SVGs. They came from the
earlier relative QTemporaryDir template; that code already uses an absolute system
temporary directory and has a regression check. Added ignore rules for those
caches, local assistant/configuration directories, environment files and AppImages.

Removed Python caches and the disposable `build/OptiDX-Desktop.AppDir` staging tree
(about 162 MiB of files). Kept the verified `build/runtime-x86_64` and all existing
release AppImages/checksums. Generated Qt/runtime icon trees were build output,
not source assets. Historical reports and actual app/packaging/README assets stay.

`docs/PUBLISHING.md` explains separate Desktop GitHub source and Release assets.
Prepared a clean source folder/archive under dist using Git's non-ignored source
list, excluding .git, build output, binaries and caches. No commit, push, new remote
or publication was performed. Source cleanup/documentation does not change app
behavior and needs no AppImage rebuild or another full suite.
