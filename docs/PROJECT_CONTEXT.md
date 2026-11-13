# OptiDX Desktop project context

This is the continuation record for the standalone Linux desktop application.
Use release notes for shipped changes and focused reports for detailed findings.

## Test suite trim and speed-up — 2026-11-13

Removed 17 cosmetic tests (`test_scrolling.py`, `test_motion.py` and the palette/
contrast/KDE-colour tests in `test_theme.py`); kept the two theme tests that check
settings preservation and that theme changes never touch drafts or games. 261
tests remain. Each closed MainWindow left its smooth-scrolling and theme filters
installed on the QApplication (tests and shutdown never processed the deferred
delete), so every later Qt event ran through a growing chain: the full suite took
90–120 s. `MainWindow.closeEvent` now removes both filters when a close is
accepted; the full suite runs in about 24 s. Prefer focused test files while
iterating and the full suite once before commits/builds.

## Fork retirement and frame-generation tools — 2026-11-13

The user no longer maintains the `Cha1N1/OptiScaler` fork. Source backup:
`/home/DwE/project-backups/OptiDX-Desktop-before-fork-retirement-20261113-0127.tar.gz`.

- OptiScaler source: `channels.optiscaler_source` is the single resolver for
  installs and update checks. Default/Nightly use `optiscaler/OptiScaler-nightly`;
  `RETIRED_OPTISCALER_REPOSITORIES` redirects recorded or entered fork repos; other
  explicit repos are kept; a recorded repo is reused only for the same channel.
  Desktop now always resolves the release itself (no backend-default path), so the
  version record names the repository actually used. Backend `REPO_OPTISCALER`
  changed to upstream (SNAPSHOT updated, upstream provenance unchanged).
- The fork's INI changes (Dx12Upscaler=ffx, FGInput=dlssg, FGOutput=xefg,
  [XeFG] InterpolationCount=5) are `templates.BUILTIN["optidx"]`, generated
  locally and applied explicitly; unlike RHI templates it may set [FrameGen].
- The fork bundled MFGUnlocker.asi (and an XeFGUnlock plugin, now obsolete since
  upstream XeFG has InterpolationCount). Replaced by optional tools in
  `framegen_tools.py` (declared in `catalog.FRAMEGEN_TOOLS`, merged into EXTRAS):
  MFG Unlocker → `OptiScaler/plugins/MFGUnlocker.asi` (transfers ownership from
  `backend:optiscaler` for fork-era copies, LoadAsiPlugins=true); XeMFG XMX,
  dlssg-to-xefg, ANR FG → `OptiScaler/custom/<folder>/dlssg` (only the provider
  tree; x64 + NVSDK_NGX_D3D12 export check; installed-DLL capability marker
  "isn't a replacement or a folder with dlssg in"). First install journals and
  sets FGInput=nvngxfg/FGNvngxReplacement; removal restores only while that
  provider is still active, hands originals to a stacked provider otherwise,
  never restores a removed provider's name, and prunes empty folders. Refresh
  keeps edited *.ini. ANR's `-full` package (own OptiScaler) and install scripts
  are deliberately unused; MFG Unlocker's FGNvngxReplacement=MFGUnlocker mode
  needs dashdogy's OptiScaler build and is not configured.

Validation: 11 new regression tests; all 278 tests pass in source; Black/Ruff on
changed files. Real release archives (MFG Unlocker v1.7.1, dlssg-to-xefg-xmx
build-10, dlssg-to-xefg build-6, ANR FG V.B15 addon) map and pass PE/export
checks in scratch only. No real game writes, gameplay or Wine verification.

## Architecture and robustness pass — 2026-11-13

Implemented the agreed Tier 1/Tier 2 items plus selected Tier 3 items; the
lifecycle harness was explicitly excluded. Source backup:
`/home/DwE/project-backups/OptiDX-Desktop-before-architecture-20261112-2352.tar.gz`.
The initial Git commit was attempted but blocked by the tool permission policy;
the repository still has no commits.

- Library/UI reads go through Qt-free `status.py`. Unreadable records mark only
  their game "Needs attention", disable management/save with the reason and are
  never rewritten. Strict reads still block jobs.
- Worker failures are typed (`errors.py`): CorruptRecord, ManualRecoveryRequired,
  GameBusy; structured `recovery` events and `recovery_state` history replace
  message matching (legacy text still honoured for old records). The footer can
  cancel the running job (SIGTERM rollback).
- Job requests go to the worker on stdin (`--request` kept for compatibility);
  the GitHub token reaches curl via `--config -` stdin, in Desktop and backend.
- Copied launch commands use `$XDG_DATA_HOME/optidx-desktop/bin/optidx-launch`,
  rewritten on GUI startup to the running AppImage; with a missing image it runs
  the command after `--`. Manual game launches are detached (`running.json`,
  `/proc` start-time + zombie checks); closing the app no longer waits for games.
- App settings has a scrollable layout, Storage usage, cache clearing and a
  30-day startup cache prune (job locks respected; backups untouched), and an
  opt-in GitHub release notice. Builds embed AppImage update information.
- `app.py`/`feature_ui.py` were split into mixins (`jobs_ui`, `launch_ui`,
  `services_ui`, `feature_pages/*`, `widgets`).
- `components.py` is the single rule registry. DLSS Enabler (new ledger group
  `component:dlss_enabler`, originals retained, x64 check) and direct Cyboman
  install natively through the shared download client. Remaining stages are in
  `docs/ARCHITECTURE_MIGRATION.md`. Backend changes: token via stdin and
  registry-driven ledger pruning; checksum/changes updated in SNAPSHOT.json,
  upstream provenance unchanged.

Validation: Black/Ruff (pinned versions in a scratch venv) and all 267 tests pass
in source; the new/changed job, component, status, runtime and maintenance suites
pass with the bundled interpreter and bundled curl. Rebuilt local 0.3.6 AppImage
with the existing runtime (no version bump): checksum, embedded update
information, FUSE-free version/backend help, fresh-data offscreen preview and
packaged application/backend source parity pass. No .zsync was produced because
zsyncmake is not installed. Settings/storage and main-window previews inspected.
Temporary folders only; no real game writes, launches, live downloads or
publication. Corrupt-record startup was reproduced before the fix and verified after.

## Local release preparation — 2026-11-07

Prepared 0.3.6 from the current local code, separating post-0.3.5 maintenance and
custom-upscaler work into a new release entry. Refreshed README highlights,
versioned filenames, validation count, parity heading and publishing instructions.
The existing synthetic README screenshot remains explicitly labelled as 0.3.5.
No application behavior changed beyond the version identifier. Historical review
reports and backend provenance are preserved.

Built the AppImage with the existing local runtime, preserving older artifacts.
Prepared a clean source directory, tar.gz, checksum and per-file SHA-256 manifest
under dist using explicit source/root allowlists plus Git ignore filtering.
Excluded Git metadata, build/dist output, caches, private state and prepared assets.
The local repository still has no commits; no commit, push, tag or publication
was performed. Original OptiDX and OptiScaler repositories were untouched.

Validation: all 243 tests pass in source and with the rebuilt AppDir interpreter.
Source and FUSE-free AppImage fresh-data offscreen previews pass; packaged preview
visually inspected. Version, backend help, AppImage checksum, backend snapshot
checksum and packaged application/backend source parity pass. Black/Ruff could
not run because neither tool is installed in the available environment; no Python
formatting changes were made. Deployment tests use temporary game folders; live
download, gameplay and cross-distribution compatibility remain unverified.

## Executable folder recovery — 2026-10-30

Selecting another executable folder under the same game ID is distinct from
moving an installation. Keep the existing legacy baseline bound to its original
folder and use a target-hashed baseline directory for the new folder. Do not
rewrite old snapshot targets or restore old-folder originals into the new folder.
Snapshot pruning protects every target baseline; returning to the previous
executable can still restore its originals. Verified whole-install relocation
continues to rebind recovery metadata, including target-scoped records.

Core package updates already retain the current OptiScaler.ini bytes; now refresh
that mutable configuration's ledger hash before deployment so in-game/user saves
do not falsely block updates. Binary conflict checks remain enforced. Regressions
use temporary folders and cover both folders' originals, pruning, edited INI
preservation and edited binary rejection. All 243 source tests and 24 focused
bundled-interpreter tests pass; rebuilt AppImage checksum, packaged-source parity,
lint and clean FUSE-free offscreen startup pass. No real game installation was modified.

## CustomProviders detection follow-up — 2026-10-30

The managed update correctly installed the current fork nightly, but the custom
upscaler preflight falsely rejected it because it required the exact diagnostic
`Can't load custom upscaler {} from {}`. Upstream refactored CustomUpscalers to
`OptiScaler/misc/CustomProviders.h` and changed that message to printf formatting
(`Can't load custom upscaler %s`). The custom/<name>/ffx and dlss layout is unchanged.

Recognize the diagnostic prefix independent of format arguments, with the DX12
custom-folder resolver diagnostic as another capability indicator. Report unknown
capability as an identification failure, without incorrectly asserting that the
installed build is stable 0.9.4. Do not change source selections or demand another
OptiScaler update when the installed DLL is already capable. Regression coverage
includes both diagnostic styles, the refactored resolver and an incapable binary.
A read-only check against the actual installed current fork DLL now succeeds.
All 241 tests pass in source and bundled Python; the rebuilt package passes
the complete loader preflight against the installed DLL read-only. Checksum,
source parity, lint/format, backend help and clean FUSE-free startup pass.
No real-game/profile writes; rebuilt local 0.3.5 with existing runtime.

## Legacy package overlap updates — 2026-10-30

An older setup successfully relocated but the next core update blocked on
`Licenses/FidelityFX_v2_LICENSE.md`: its component record owned `Licenses` and
`OptiScaler` as directories, while the flat manifest omitted their children.
`legacy_core_overlaps` now identifies only new-package members under those two
explicitly recorded directories, requiring a prior marker/proxy manifest and no
modern core asset group. `assets.deploy` accepts a scoped `replace_unmanaged`
allowlist that bypasses only the unknown-file approval check; it still backs up
previous bytes and enforces owner/hash/path/case/symlink safeguards.

Never expand ownership to all files in those folders. Exclude custom/legacy
HelixSR subtrees; preserve exact paths explicitly owned by other legacy components
(in particular the independently replaced AMD DLL) when preparing the core archive.
Do not turn on global allow_foreign or weaken edited modern binary checks.
Regression fixtures cover vendor/license upgrade with original restoration,
unknown/custom collisions, independent AMD preservation and modern hash conflicts.
Validation: all 240 tests pass in source and bundled Python, including four new
overlap regressions.
The current cached upstream archive installs successfully against a temporary
copy of the reported legacy package overlaps, with the license updated and the
independent AMD DLL preserved. Rebuilt local 0.3.5 with the existing runtime;
checksum, source parity, Black/Ruff and clean FUSE-free startup pass.
No real-game writes or changes to the backend script/provenance.

## Moved installation recovery — 2026-10-30

Worker mutation jobs now rebind moved-install markers before taking their normal
operation snapshots. `relocation.py` requires the old target to be absent, the
same relative executable layout, and verified owned binaries/original blobs.
Legacy component manifests plus the recorded Cyboman SHA-256 are accepted when
no asset ledger exists. Missing ownership evidence, modified binaries, existing
old installs and linked/unsafe recovery paths remain blockers. Read-only jobs
can inspect moved games but do not migrate their files.

Rebind only snapshot metadata for this game ID's old target/root; verify every
payload before edits, retain prior metadata/modes in a durable relocation journal,
and publish the marker last. In-process failures restore prior bytes; an
interruption before marker publication can retry with mixed old/new snapshot
scopes. Subsequent failed operations roll back to the newly bound location.
No payload bytes, other game IDs, launch settings or arbitrary paths are rewritten.
The direct validate_game API remains strict unless its worker caller explicitly
allows preliminary moved-target validation. No backend script/snapshot changes.

Tests cover moved original recovery, copy/wrong-folder rejection, modified binary
and corrupt snapshot refusal, marker-only rejection, rollback on marker-write
failure, interrupted root/target metadata rebinding, linked recovery directories,
legacy installations without an asset ledger, and failed/read-only worker jobs.
A mocked-write preflight against the user's reported legacy setup passed without
changing its marker. Existing games were only inspected; execution testing uses
temporary game folders. All 236 tests pass in source and with bundled Python. Local AppImage rebuilt with the existing runtime;
checksum, source parity, backend help and fresh-data FUSE-free startup pass.
Version unchanged and no commit/publication.

## Lossy2 selection follow-up — 2026-10-29

A user deployment failed because the old Lossy2 checkbox was selectable with the
current archive. Gate that choice on an explicit older release pin or local
archive. Keep saved/draft selections visible and untickable, show a corrective
message and disable the custom install action until resolved. Never silently
substitute retrained Lossy for an explicit old Lossy2 choice. Backend preflight
rejects the combination before release lookup/download. Existing installed
variants remain intact. Added UI stale-choice/source-transition and backend
no-download regression coverage. All 226 tests pass in source and bundled Python; rebuilt local 0.3.5
with the existing runtime. Checksum, packaged-source parity, clean offscreen
startup and backend help pass. No version bump/publication or real-game writes.

## Selected custom upscalers — 2026-10-29

Added an independent Installation dropdown/action for selected custom variants.
`upscalers.py` validates actual x64 PE export tables for FFX/NGX, requires the
installed OptiScaler custom-loader diagnostic marker, resolves hardware-specific
Cyboman archives and deploys curated variant groups through the existing asset
ledger. `upscaler_ui.py` exposes bound per-game/draft checkboxes and local HelixSR
DLL paths. No backend snapshot changes; no existing direct-install migration.

An explicit upstream-nightly source uses `optiscaler/OptiScaler-nightly`; the old
Nightly source retains the configured fork. Stable 0.9.4 has no custom loader.
The current upstream nightly archive was downloaded to /tmp and its marker
verified. Public HelixSR 3.2.0 unprepared DLL exports match FFX and NGX respectively;
users must supply locally prepared DLLs, and runtime compatibility needs gameplay
verification. Never package prepared user assets or run setup at game startup.

Cyboman's linked `dll-2026-10-29` release changes Lossy to retrained former Lossy2
and adds `4.1.2l-exact` / `4.1.2l-lossy`; the archive has no separate lossy2 folder.
Keep older Lossy2 explicit and fail on missing/ambiguous variants, with no silent
fallback. Current hardware archive names include rx6000/rx7000/igpu-rdna2/igpu-rdna3;
choose hardware explicitly. Copy only requested variants and their warning files.
The new path does not use the legacy fixed-name lossy downloader. Managed groups
update independently, retain source/hardware/pin provenance and use worker snapshot
rollback; removing a selected DX12 variant resets its INI value preserving encoding.

Validation: all 224 tests pass in source and with bundled Python. Added failure
coverage for partial custom deployment rollback, absent variants, malformed/wrong
architecture exports, unsafe/ambiguous archives, case conflicts, external edits,
profile/draft round-trips, popup multi-selection, source routing, update provenance
and core-update preservation. Black and Ruff pass. Downloaded the current official
nightly and RX6000 Cyboman archives to /tmp; all four current Cyboman variants
installed and removed successfully in a temporary game directory (including both
lossy warning files). Helix DLL export validation used public unprepared DLLs;
prepared-network execution/gameplay has not been tested.

Rebuilt the local 0.3.5 AppImage with the existing runtime; checksum, source parity,
backend checksum/help and fresh-data FUSE-free offscreen preview checked. The
custom section and dropdown were rendered and visually inspected. The popup
preview exposed an app-wide scroll-filter teardown warning; detach that filter
on Qt aboutToQuit before popup/window destruction. A fresh source preview now
exits without warnings, and the seven scrolling checks pass. Version unchanged;
no commits, publication, changes to other repositories or real-game writes.

## Comprehensive source maintenance — 2026-10-18

Implemented the supplied review's remaining safety/performance findings and
maintenance proposals. See [the implementation record](MAINTENANCE_2026-10-18.md).
Downloads retain TLS verification and available asset digests; corrupt critical
JSON blocks operations; atomic writes fsync; wrappers tolerate optional setup
failures; shared per-display HDR users preserve lifetime; config edits retain
encoding; graceful worker signals roll back. Optional updates now transact by
group, retaining the dependent core as one unit and stopping on incomplete recovery.

Game values are immutable and queue entries are named Job records. Existing
Steam/Heroic path-based identities migrate before workflow state loads, retaining
legacy evidence and exact recovery bytes. Profiles have versioned migrations.
BackendContext confines legacy mutable backend state and restores cwd/environment;
keep management jobs in separate processes. Page-owned raw draft bindings replace
the central widget registry; workflow layout ownership is explicit. Semantic QSS
tokens replace hex substitution. Drafts debounce at 500 ms; UI inspection is cached
briefly; DLL discovery is asynchronous and bound to game/request generation.
Checked shaders share one job; 7z solid archives extract once after preflight.
Snapshot payloads share per-game SHA-256 objects; completed history/logs are bounded
while unresolved recovery is protected. Black/Ruff and offscreen CI are configured.

The source/Git backup is
`/home/DwE/project-backups/OptiDX-Desktop-before-maintenance-20261018.tar.gz`.
The original script and OptiScaler repositories are unchanged. Backend checksum
was refreshed and original provenance verified unchanged. Version remains 0.3.5;
no commit, push, external AppImage replacement, or publication.

Validation: all 207 tests pass in source and with the rebuilt AppImage's bundled
interpreter. Black checks all 54 Python files; Ruff passes. The local 0.3.5 AppImage
was rebuilt with the existing verified runtime; checksum, packaged-source equality,
backend checksum, FUSE-free version/help and fresh-data offscreen startup pass.
Source wide/compact synthetic HelixSR previews and the packaged preview were
visually inspected. Python wheel creation plus the installed command/module wrapper
were smoke-tested outside the source directory. Tests cover real SIGTERM rollback,
per-group update failure, corruption, BOM/endian/newline preservation, migrations,
stale metadata, solid archives and delayed UI results. Temporary fixtures only;
no real game writes/launches, live mod downloads, personal-state migration or
actual HDR changes. Gameplay/cross-distribution/power-failure coverage remains
limited. CI configuration is prepared locally; no remote CI run was triggered.

## Code quality review — 2026-10-17

The [follow-up review](REVIEW_2026-10-17.md) reproduced three issues:
compacted baselines omit originals overwritten by later operations, ReShade
pruning bypasses asset restoration and retains stale ownership, and Cyboman
replacement of an archive-bundled AMD DLL invalidates the OptiScaler ledger hash.
The review itself changed no application code. The subsequent fixes merge newly
overwritten originals into the compact baseline before snapshot disposal, remove
ReShade through the asset ledger during pruning, and transfer AMD DLL ownership
and original recovery records to `backend:amd_fsr`. Core updates retain that
independently owned DLL. Old dual records migrate only when backend component
ownership and Cyboman's recorded SHA-256 verify the replacement; external edits
remain conflicts. Failure tests cover ledger-write rollback. Historical review
reports remain unchanged. Version remains 0.3.5; no publication was requested.

Validation: 183 tests passed in the source full run; the subsequently added
ledger-write failure regression passed in the 18-test focused source run, and
all 184 tests passed with bundled Python. All 17 component tests also passed.
Rebuilt `dist/OptiDX-Desktop-0.3.5-x86_64.AppImage` using the existing verified
runtime. Package checksum, bundled-source equality, backend snapshot checksum,
backend help, and fresh-data FUSE-free offscreen startup passed; the preview was
visually inspected. Temporary fixtures only; no real games, live downloads, or
gameplay validation. No commit, push, or publication.

## Code quality review — 2026-10-16

The [historical source review](REVIEW_2026-10-16.md) recorded seven findings.
They are addressed in the current local source: core payload preflight/architecture
validation, direct HelixSR pruning restoration, uninstall error propagation, DXVK
and standalone ReShade update dispatch, and source manual launch routing.

Operation snapshot history now defaults to off. Jobs still take temporary rollback
copies, deleting them on success or successful rollback. Opt-in retention defaults
to three snapshots per game (configurable 1–50). Explicit cleanup preserves compact
verified original-file baselines and snapshots marked active/manual recovery.
Existing completed history is kept until explicit cleanup or opt-in bounded
retention. No real game installation was changed for validation. See
[the implementation record](REVIEW_FIXES_2026-10-16.md) for details. All 179 tests
pass in source and with bundled Python; the 0.3.5 AppImage was rebuilt and its
checksum, FUSE-free preview, and backend help checked. Personal backup history
was not deleted during implementation.

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

## Startup timing investigation — 2026-10-15

User reports about 2–3 seconds to open. Running binary is now
`/home/DwE/AppImages/optidx_desktop.appimage`, matching the last local 0.3.4 checksum;
the dist copy was moved, not deleted by source cleanup. Do not overwrite that
external application path without a task authorizing it.

Read-only source profiling used a temporary copy of app metadata, with background
services disabled and scanning off. The cached 49-game library took about 0.386 s
to construct and 0.076 s to show; two populate calls totaled about 0.09 s. A fresh
empty-data source probe took 0.467 s through first render. Running the packaged
interpreter from the already-mounted image took 0.680 s through first render.

Fresh normal AppImage probes took about 4.42–4.51 s to save a preview, including
the built-in 250 ms preview timer (rough first-show estimate 4.17–4.26 s), under
offscreen and native Wayland. Complete process timing was about 4.5–4.65 s.
FUSE-free extraction plus preview took about 8.0–8.1 s. Measurements are local,
cache-dependent and not a controlled cold-start benchmark. No game scan, game
launch, real-game mutation or original app-state writes were performed.

Current packaging uses XZ compression; per-mount runtime/dependency loading is
the main measured difference, not library scanning. UI also eagerly builds all
pages and populates twice; those are secondary opportunities. Future optimization
should benchmark faster SquashFS compression and reduce pre-show work before
claiming a speedup. No performance code or package was changed by this investigation.

## Startup optimization — 2026-10-15

Switched AppImage default compression from XZ to gzip; this installed appimagetool
explicitly rejects zstd. Added --compression xz as an opt-in size tradeoff and
recorded compression in BUILD_INFO.json. Removed the early duplicate populate()
and blocked search/filter/sort signals while restoring workspace state before
the single initial population. All pages still construct eagerly: a lazy-page
refactor was unnecessary for the measured main bottleneck and is deferred.

Repeated normal FUSE offscreen preview probes with fresh temporary app data:
old image 4.424/4.384 s, new image 1.240/1.229 s to saved preview, including the
250 ms timer. New image is 64.4 MiB. Measurements are cache-dependent, with no
scanning or real-game changes. Built local 0.3.4 in dist; did not overwrite the
user's /home/DwE/AppImages/optidx_desktop.appimage. Version unchanged.
Added a regression covering saved search/favourite filter/sort/page/draft restore
and working filter signals after construction. Source offscreen preview inspected;
checksum, FUSE-free runtime info and backend help passed.
Final validation: all 159 tests passed with both the source and bundled Python;
normal native Wayland packaged preview also passed. No gameplay/download claims.

## HelixSR picker and Installation styling — 2026-10-16

HelixSR selection reveals a per-game DLL path and Browse button directly under
its checkbox. The path participates in profile saving and retained drafts. GUI
install/update binds the chosen local x64 Windows DLL to the queued job; prepared
helixsr_weights.bin and helixsr_kernels.pak must sit beside it. Custom filenames
are accepted and copied to the existing tracked HelixSR runtime names. No weight
compilation or downloads were introduced. Existing explicit conflicting profiles
normalize to HelixSR in the UI; the installer rejects selecting both HelixSR and
Cyboman lossy FSR. Untick the active choice to enable the alternative checkbox.
Unchecked installed files retain the existing explicit-pruning behavior.

Update and removal buttons are pinned below Installation alongside the main
install action, outside collapsible sections. Added the app icon beside the
header name, changed Dark to white accents/navy backgrounds, and recolored both
source and packaged app SVGs. Light and actual System Qt palettes remain.
Backend snapshot checksum/change description updated; upstream provenance retained.
Built local 0.3.4 AppImage without version bump or publication. Tests use temporary
game folders only; actual latest HelixSR gameplay is not established by fixtures.

## Near-black dark palette — 2026-10-16

Darkened the blue palette at user request: window #090c12, input/list backgrounds
#0d111a, cards #121823, and darker blue button/selection surfaces. White accents
remain. Both logo backgrounds match the window. Light/System unchanged.
Rebuilt local 0.3.4 AppImage; no version bump or publication.
Validation: 162 source tests pass; all 9 theme tests pass with bundled Python.
Fresh source and FUSE-free packaged previews pass and were checked; checksum OK.

## Standalone HelixSR correction — 2026-10-16

User clarified current HelixSR is a standalone DLL. Removed external weights and
kernel checks and copying from the adapter and bundled backend. Local DLL x64 PE
validation remains; canonical installed runtime copies, routing and ownership
remain. Global prepared-HelixSR indicator now checks the DLL alone. Existing
managed/unmanaged companion files are preserved rather than deleted implicitly.
Updated backend snapshot checksum and description, preserving upstream provenance.

Picker input is capped at 200 px and 32 px high with Browse beside it. Disabled
HelixSR/Cyboman checkboxes and indicators are visibly dimmed; the status explains
which selected alternative to untick, also available as a tooltip. Tests now use
DLL-only fixtures and cover architecture rejection, standalone deployment and
visible mutual-exclusion messaging. README and release notes corrected; earlier
checkpoint entries describe historical companion-file behavior.
Validation: all 162 tests pass with source and bundled Python. Synthetic HelixSR
picker preview inspected; FUSE-free package preview/backend help and checksum
pass. Rebuilt local 0.3.4 AppImage; no version bump, publication or real-game writes.

## Version 0.3.5 and README refresh — 2026-10-16

User requested a version bump and refreshed public README. Set package version to
0.3.5, promoted the accumulated unreleased notes to the 0.3.5 entry, and updated
README/packaging/publishing filename examples. README highlights current UI,
standalone HelixSR/mutual exclusion, visible maintenance actions and faster startup;
validation count updated to 162. Release download link points to Desktop GitHub
and explicitly says assets are available when published; nothing was published.

Replaced docs/screenshots/desktop.png with a 1500x1000 source render using a fresh
temporary five-game example library, synthetic executable fixtures and display
paths. It shows white/near-black styling, the DLL picker and disabled-choice
explanation, plus 0.3.5 in the footer. No personal library data was included and no
real game files were modified. Built dist/OptiDX-Desktop-0.3.5-x86_64.AppImage and
checksum; older local images remain. No commit/push/release publication performed.
0.3.5 validation: all 162 tests passed with bundled Python. The source full run
had one animation-completion timing failure while both suites ran concurrently;
all three motion tests passed on immediate focused rerun. No behavior change was
made for that timing failure. FUSE-free --version reports 0.3.5; packaged preview,
backend help and checksum passed. The refreshed README screenshot was inspected.

## HelixSR component-card spacing — 2026-10-16

User clarified the unwanted space was on the right. Capped the component card at
720 logical pixels and left-aligned it through a flexible row so narrow windows
can still use available width. Also replaced shared grid rows with independently
stacked columns; opening the picker no longer expands Cyboman's cell or pushes
DLSS below the taller neighbouring cell. New geometry regression checks both
cell spacing and the card-width cap on a wide window. Synthetic 1800/1500-pixel
previews inspected, README screenshot refreshed, current test count now 163.
Rebuilt 0.3.5 locally with no further version bump or publication.
Final checks: all 163 source tests pass, all 15 workflow/layout tests pass with
bundled Python; FUSE-free package preview, backend help and checksum pass.

## Correct HelixSR deployment layout — 2026-10-16

User corrected the runtime layout: standalone HelixSR replaces
OptiScaler/amd_fidelityfx_upscaler_dx12.dll directly. Replaced the old installer;
no new HelixSR subfolder, helixsr.dll duplicate, SR duplicate or forwarding DLL is
created. Removed forwarding repair code and launch-time repair calls. Library
routing uses the standard AMD path; managed legacy routing is reset on migration.

Installation retains the replaced AMD DLL in a tracked hidden .bin backup with
SHA-256, original mode and previous owner in OptiScaler/.optidx-helixsr.json.
Subsequent updates retain that original. Targeted removal verifies it before any
writes, restores it with ownership/mode, and removes replacement metadata. With
no previous DLL, targeted removal removes HelixSR and resets its routing instead.
Full uninstall continues to restore verified baseline originals. Remove managed
HelixSR before installing Cyboman so the recovery chain is not overwritten.

Only tracked legacy subfolder files are deleted during a successful install;
unmanaged files/logs remain. Empty legacy directory is removed. Legacy removal
support remains for cleanup of earlier installs. Direct HelixSR and Cyboman are
detected separately; source default now uses the standard AMD filename. Adapter
still validates supplied Windows x64 DLLs; path/case/symlink checks and backup
checksum validation protect replacement. Backend snapshot checksum updated while
preserving upstream provenance. README, release notes, removal label/help and
synthetic screenshot updated. Version remains 0.3.5; rebuilt local AppImage.

New regressions cover exact direct path (no duplicate DLLs), legacy migration
with retained user files, repeat update plus restored original ownership, distinct
component detection and checksum-failure refusal on update/removal. No real game
installations were touched; runtime/gameplay compatibility is not claimed.
Final validation: all 165 tests pass with source and bundled Python. Fresh
synthetic source preview and FUSE-free packaged preview/backend help pass;
AppImage checksum and backend snapshot checksum verified.

## Clean 0.3.5 source export — 2026-10-16

Prepared dist/OptiDX-Desktop-0.3.5-source plus a tar.gz and SHA-256 for upload,
using non-ignored source files and excluding Git metadata, build/dist output,
Python caches, virtual environments and local state. Includes current direct-path
HelixSR implementation, refreshed README/screenshot and provenance records.
Export contents and backend snapshot checksum verified; no source behavior change,
additional AppImage rebuild, commit, push or publication was required.
