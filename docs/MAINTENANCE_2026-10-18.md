# Source maintenance — 2026-10-18

This records implementation of the supplied source-review findings and maintenance
proposals. Historical reviews are unchanged. Desktop remains version 0.3.5; no
commit, push, or publication was requested.

Before the broad refactor, source, uncommitted work, and Git history were backed
up to `/home/DwE/project-backups/OptiDX-Desktop-before-maintenance-20261018.tar.gz`,
excluding build/dist output and Python caches. The separate OptiDX and OptiScaler
repositories were not changed.

## Download, ownership, and launch fixes

- Backend curl retries retain certificate verification and require HTTPS for
  redirects. Available GitHub SHA-256 digests are retained for OptiScaler and
  DLSS Enabler, including channel overrides, and checked against cached payloads.
  Upstreams without a digest still lack that independent verification.
- JSON reads distinguish missing records from unreadable/corrupt records. Strict
  reads are the default for ownership, recovery, profiles, drafts, and libraries.
  Corrupt records remain intact and block the operation. Only disposable download
  cache metadata opts into fallback, preserving malformed JSON with a unique
  `.corrupt-*` suffix. This intentionally exposes damage instead of overwriting it.
- Atomic JSON, asset, and backend writes flush/fsync contents and modes before
  replacement and fsync the containing directory afterward. This improves
  durability; it does not claim exhaustive power-failure recovery validation.
- Both `name = settings` and `name settings` quirks forms work. Prefix matching
  requires an executable-derived candidate, at least 80% coverage, and one unique
  matching title; short generic parent-folder prefixes are refused.
- Launch wrappers log invalid environment/deferred-HDR/Gamescope setup and launch
  the command with the remaining usable settings. Corrupt profiles fall back to
  the host environment. Actual process-launch failures still surface normally.
- KDE HDR holds a lock only while changing a per-display user record. Multiple
  wrappers share HDR; the last user restores the original state. PID start times
  discard stale users. Forced kills/power loss still cannot guarantee immediate
  desktop restoration; the record retains the original state for subsequent use.
- The configuration editor retains the original BOM, UTF-16 byte order, and
  newline convention while preserving its concurrent-edit/hash check. Its modal
  result is bound to the original game.
- Graceful worker SIGTERM/SIGINT raises an exception through transaction rollback.
  Repeated cancellation is ignored during recovery. SIGKILL cannot be caught.
- Manifest removal checks path components, accepting legitimate `a..b` names while
  rejecting traversal and refusing directory removal.
- Copied diagnostics recursively redacts values under TOKEN/KEY/SECRET/PASS keys.
  Local paths and non-secret preferences remain useful for support.

## Performance and operation boundaries

- Library population loads profiles/update records once per pass. Cheap HelixSR
  defaults no longer execute the backend on search/filter changes.
- A short-lived UI inspection cache keys on the immutable game and relevant file/
  directory timestamps, expires after 500 ms, and clears after jobs. Workers use
  fresh inspections. Profile/draft loading blocks control signals and synchronizes
  mutually exclusive FSR controls once.
- DLL discovery uses pruned non-symlink traversal in a background task. Results
  carry the originating immutable game and request generation. Backup discovery
  uses the same pruning; managed files remain explicitly included.
- Draft saving uses a single-shot 500 ms debounce. Idle forms do not repeatedly
  capture/write drafts or rebuild queue views. Reverting to saved values removes
  the draft. Selection/close still flush pending edits.
- Checked shader packs deploy as one dependency-ordered job and rollback snapshot.
- Optional update groups each receive their own transaction and error reporting.
  A dependent core setup remains one atomic unit; a dead optional URL no longer
  rolls back unrelated successful groups. Incomplete recovery/corrupt metadata
  stops the update rather than proceeding over uncertain ownership.
- Operation history remains opt-in and bounded. Snapshot payloads use per-game
  SHA-256 objects/hardlinks, separate from live game files, with unreferenced-object
  collection under the game lock. Compact originals and interrupted/manual recovery
  remain protected. The last 200 completed activity records/logs are retained;
  unresolved recovery records remain available. Individual logs retain recent
  output after 8 MiB. Existing loose logs without a history record are not deleted.
- Solid 7z archives are listed/preflighted, extracted once into a temporary folder,
  and checked for unexpected files, links, and size mismatches. 7z/7za/7zz are
  supported; unsafe names/links are refused before extraction.
- Desktop downloads use low-speed stall detection instead of a 180-second total
  deadline. GitHub API requests can use `GITHUB_TOKEN`. Verified stale metadata is
  available with a warning on network failure; payload failures never silently use
  stale content.

## Maintenance structure and compatibility

- `Game` is frozen; executable changes replace the game value. Named `Job` records
  capture nested preferences/options instead of positional five-tuples.
- Steam IDs use app IDs. Heroic IDs include launcher ownership, runner/store, and
  app ID, preserving native/Flatpak routing. Existing path-based records migrate
  before UI state loads: profiles, updates, drafts, workspace/history references,
  and recovery metadata are adopted. Recovery file bytes are never rewritten.
  Legacy records remain available as evidence; conflicting records stop migration.
  Stable IDs do not bypass existing game-path/ownership recovery checks.
- Profiles have `schema_version` and an ordered migration list. Legacy component
  modes and the Original appearance alias have centralized migration functions.
  Explicit HelixSR choices are retained; new profiles keep HelixSR off.
- `BackendContext` carries game/preferences/module and confines legacy backend
  globals to a fresh worker module, with one guarded cwd/environment scope that
  always restores the caller. The legacy backend internals remain incremental
  adaptation work, rather than a wholesale rewrite of the upstream script.
- QWidget page classes own raw draft load/collect behavior; the central
  `form_widgets` registry is removed. Main-window layout construction owns sort,
  status, launch, and profile controls; workflow helpers no longer splice those
  controls into layouts by index. Installation exposes explicit extension methods.
- QSS uses semantic color tokens shared by Dark/Light/System palettes instead of
  regex replacement of hex literals. Existing colors/geometry are preserved.
- `pyproject.toml` defines source entry points, Python/dependency requirements,
  Black/Ruff configuration and pinned development tools. The backend/provenance
  and SVG assets are included in Python packaging. Source wrappers retain their
  absolute entrypoint; installed packages can use the module entrypoint.
- CI runs formatting, lint, offscreen tests and a fresh-data startup preview.
  Python sources are formatted consistently; reusable PE fixtures live in
  `tests/helpers.py`. Animation completion waits for observed state with a bounded
  Qt event loop, since this PySide6 does not expose QTest.qWaitFor.
- Current docs and bundled backend usage were refreshed; the external original
  script README is outside this repository's authorized scope.

## Validation

All 207 tests pass with both source and bundled Python. Black checks all 54
Python files and Ruff passes. The rebuilt 0.3.5 AppImage passes SHA-256,
packaged-source equality, backend snapshot checksum, FUSE-free version/help and
fresh-data offscreen startup. Wide/compact synthetic source previews and the
packaged preview were inspected. Wheel creation and the installed entrypoint/module
wrapper also pass from outside the source directory. CI is configured but has
not been run remotely. Further details are in PROJECT_CONTEXT.md. All deployment, migration, signal, and recovery tests use
temporary fixtures. No real game installation, launch, live mod download, desktop
HDR setting, or personal application state was changed for validation. Actual
gameplay, cross-distribution behavior, and exhaustive power-failure recovery remain
outside these checks.
