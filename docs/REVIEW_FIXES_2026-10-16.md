# Review fixes and optional snapshot retention — 2026-10-16

The seven findings in the historical `REVIEW_2026-10-16.md` are addressed in the
local 0.3.5 source. No version bump, commit, push, or publication was requested.

## Changes

- Core OptiScaler payloads use bounded archive reading, unique compatible PE
  selection, complete destination preflight, and the asset ledger's verified
  originals. Nested files are tracked individually. Existing INI settings are
  preserved. Explicit app configuration edits update their ownership hashes.
- Component pruning shares targeted HelixSR removal, restoring its verified
  direct-layout original before processing other selected components.
- Backend removal propagates failed deletions and retains tracking until it can
  complete. The worker can therefore roll back partial removal.
- DXVK and standalone ReShade updates route to their dedicated installers.
  GUI/backend ReShade preparation always uses validated payload selection.
- Manual source launches use the absolute `launcher.py` entrypoint, retaining the
  game working directory while making package imports reliable.
- Rollback restores ledger-held originals for files omitted from the initial
  snapshot before deleting newly created records or original blobs.

## Backup behavior

Operation history is opt-in, disabled by default for existing and new app data
without an explicit setting. Automatic in-job rollback still uses temporary,
verified snapshots. They are discarded after success or successful rollback.
Failed recovery and interrupted jobs retain their snapshots for inspection.

When enabled in App settings, retained history defaults to three snapshots per
game and accepts a limit of 1–50. Original-file baselines omit untouched DLLs and already verified ledger-held
originals as well as managed setup copies; they and active/manual-recovery snapshots do not count
against disposable history. Original recovery data is still necessary when
unmanaged DLLs were replaced.

Turning retention off does not silently erase existing completed history. The
explicit **Delete completed operation snapshots…** action verifies/compacts
baseline originals before removing completed history. It acquires job locks and
refuses cleanup while a job is running. It does not delete game-local original
blobs, imported assets, downloads, or interrupted/manual-recovery snapshots.
History log entries can reference a discarded temporary snapshot; the retention
policy determines whether that location remains available.

## Validation

Regression coverage includes actual core-installer preflight, nested originals,
late worker failure, x86/ARM64/malformed/ambiguous DLL rejection, archive traversal,
capitalization conflicts, linked support folders, failed backend uninstall,
HelixSR pruning restoration, worker update routing/exclusions, source launches
from an external directory, opt-in settings, retention limits, default rollback,
original preservation, and cleanup locking.

The fresh settings dialog was rendered offscreen and visually inspected. Tests
use temporary game folders and harmless launch commands; real games were not
changed or launched. Live downloads, GPU/gameplay compatibility, and other
Linux distributions remain outside this validation.

Final checks: all **179 tests passed** in source (69.085 s) and with the bundled
interpreter (69.364 s). The rebuilt 0.3.5 AppImage is 64.4 MiB; its SHA-256 sidecar,
FUSE-free offscreen startup, and backend help passed. Bundled application source
matches the workspace, and the backend snapshot checksum matches. The existing
verified local AppImage runtime was reused. The settings dialog and main window
were visually inspected offscreen. One Qt watcher test now waits for its signal
with a bounded timeout instead of relying on a fixed 300 ms sleep.

Artifact: `dist/OptiDX-Desktop-0.3.5-x86_64.AppImage`. Existing personal backup
history was not deleted during implementation; cleanup is available in App settings.
