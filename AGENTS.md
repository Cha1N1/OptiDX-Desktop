# OptiDX Desktop contributor instructions

## Scope

Work from this repository root. This is the Linux desktop mod manager, developed
separately from the original launch script. Do not change `/home/DwE/OptiDX` or
the OptiScaler fork at `/home/DwE/OptiScaler` as a side effect of Desktop work.
Changes to this repository's `backend/OptiDX.py` are allowed when needed; update
its checksum and change description in `backend/SNAPSHOT.json` and preserve the
original provenance in `backend/UPSTREAM_SNAPSHOT.json`.

Complete authorized work without repetitive permission questions. Ask when missing
information materially blocks progress. Do not commit, push, or publish releases
unless requested. Before broad rewrites or migrations, back up source, uncommitted
work, and Git history under `/home/DwE/project-backups`, excluding regenerable
`build/`, `dist/`, and Python caches. Routine focused edits need no full backup.

## Documentation and continuity

Read the documents relevant to the task:

- `README.md`: setup, storage, behavior, and UI action boundaries.
- `docs/PROJECT_CONTEXT.md`: durable decisions and continuation checkpoint.
- `docs/RHI_PARITY.md`: current feature coverage and Linux limitations.
- `docs/RHI_COMPARISON.md`: historical initial comparison, not current status.
- `docs/REVIEW_2026-10-15.md`: regression findings and validation limits.
- `packaging/README.md`: AppImage workflow and runtime provenance.
- `RELEASE_NOTES.md`: user-facing release history.

Preserve historical reports. Update relevant documentation when behavior changes,
and record durable decisions in the repository so future chats can continue.
Do not store full chat transcripts, credentials, personal library dumps, or model
weights in documentation or packages.

## Architecture and invariants

- UI: `optidx_desktop/app.py` and `feature_ui.py`; queued jobs: `worker.py`;
  bundled-script adapter: `backend.py`.
- Ownership/recovery: `assets.py`, `backups.py`, `storage.py`.
- Discovery: `library.py`, `extra_library.py`; launching/environment:
  `launch.py`, `runtime.py`.
- Deployment: `downloads.py`, `channels.py`, `features.py`, `neural.py`,
  `helixsr.py`. Inspect relevant code before editing.

Keep installation, configuration, optional tools, DLL replacement, profile saving,
and launching distinct. Buttons must state their scope. Saving profiles does not
install files; management jobs do not launch games. Preserve independent component
selection and explicit dependency checks.

Preserve unmanaged files, verified originals, baseline metadata, and rollback.
Reject unsafe archive paths, ambiguous Windows filename capitalization, and
incompatible PE machine types. Bind queued operations and asynchronous results to
their originating game and executable. Use temporary game folders for deployment
tests; changing real game installations requires authorization for that task.

New profiles leave HelixSR unselected and use direct Cyboman lossy FSR; preserve
existing explicit choices. HelixSR uses prepared local assets: do not introduce
weight compilation or large downloads during game startup. D3D-prefixed ReShade
naming is intentional for Wine compatibility. Preserve native/Flatpak launcher
ownership and restore the host environment before starting external processes.

## Validation

Use focused tests while iterating, for example:

```bash
python3 -B -m unittest discover -s tests -p 'test_runtime.py' -v
```

Run the full suite for cross-cutting backend changes and release builds:

```bash
python3 -B -m unittest discover -s tests -q
```

Add meaningful regression tests for failure cases, especially ownership, rollback,
paths, launcher routing, and delayed UI actions. Avoid tests that just repeat the
implementation. Documentation-only edits need no full suite or AppImage rebuild.

For UI changes, choose a fresh temporary data directory and render offscreen:

```bash
QT_QPA_PLATFORM=offscreen ./run.sh --data-dir /tmp/optidx-ui-check --screenshot /tmp/optidx-ui-check.png
```

`--scan` writes the app's library cache; `--screenshot` does not scan or modify
games. Fixture tests and startup checks do not establish gameplay or live-download
compatibility. Report actual checks and limits concisely.

## Packaging

Version source: `optidx_desktop/__init__.py`. Bump versions when requested or as
part of an agreed release; keep release notes and packaging examples consistent.
The current local development build uses:

```bash
python3 -B packaging/build_appimage.py --runtime-file /home/DwE/OptiDX-Desktop/build/runtime-x86_64
```

If that runtime is absent, follow `packaging/README.md`; do not silently substitute
an unverified download. Preserve host graphics-driver loading and external
environment restoration. Keep personal state and prepared weights out of packages.
For a release, check the checksum, FUSE-free startup, backend help, and relevant
tests with the bundled interpreter. Rebuild the AppImage after app behavior/UI changes by default: the user prefers
using the AppImage rather than `run.sh`. Documentation-only changes do not require
a rebuild. Do not bump versions or publish unless requested.
