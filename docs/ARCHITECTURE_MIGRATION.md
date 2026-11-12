# Ownership and component migration

Goal: one ownership record per game (the Desktop asset ledger,
`.optidx-desktop-assets.json`) and Desktop-native component installers behind
one interface, instead of driving the legacy `backend/OptiDX.py` by replacing
its functions at runtime. The legacy manifest (`.optidx-files`,
`.optidx-components.json`, `.optidx-installed`) becomes a generated
compatibility export for the standalone script and `--backend` launch mode.

Migrate one component at a time. Each stage must keep existing installations
removable with their originals, and must not rewrite recovery evidence.

## Current state (2026-11-13)

`optidx_desktop/components.py` is the single declaration of component labels,
dependencies, exclusivity, 32-bit/DX9/OpenGL limits, addon-channel needs and
ledger groups. `status.py` (UI availability) and `backend.py` (job preflight)
both use `selection_problems`; backend pruning iterates `ledger_groups()`.

| Component | Installer | Ownership record |
|---|---|---|
| OptiScaler | Legacy download, Desktop `core_payload` deployment | Ledger `backend:optiscaler` + legacy manifest |
| ReShade | Desktop `channels.prepare_reshade` (via hook) | Ledger `channel:reshade` + legacy manifest |
| Cyboman lossy FSR | **Native** `components.install_cyboman` | Ledger `backend:amd_fsr` + legacy manifest export |
| DLSS Enabler | **Native** `components.install_dlss_enabler` | **Ledger `component:dlss_enabler`** (new; originals retained) + legacy export |
| HelixSR (direct) | Legacy `install_helixsr` | Separate `.optidx-helixsr.json` + `.bin` backup |
| RenoDX / Luma | Legacy wiki/mirror matching | Legacy manifest only |
| d3dcompiler_47, UE HDR state | Legacy | Legacy manifest only |

Native installers download through `downloads.Client` (one cache, digest
checks), require Windows x64 PE payloads, write through `assets.deploy`
(preflight, case/symlink checks, original blobs, rollback) and call
`module.track` only to keep the legacy manifest consistent.

`components.LEGACY_HOOKS` lists every backend attribute Desktop still replaces;
`tests/test_native_components.py` fails if the script drops one. Shrink the list
as stages complete.

## Remaining stages

1. **Lifecycle harness** (recommended before stage 4): randomized
   install/update/prune/HelixSR↔Cyboman/relocate/remove sequences on fixture
   games asserting byte-identical originals after full removal, no deletion of
   unowned files, and ledger hashes matching disk.
2. **HelixSR as a ledger overlay.** Model "replaces another group's file" in the
   ledger (previous owner + previous bytes blob) and migrate
   `.optidx-helixsr.json`/`.optidx-helixsr-original.bin` with verification.
3. **RenoDX/Luma through the ledger.** Keep the legacy matcher as a pure
   function returning a URL; download to staging and deploy via
   `assets.deploy` so replaced addons keep originals. Then OptiScaler release
   resolution and `d3dcompiler_47.dll` through `Client`/ledger.
4. **Desktop orchestrator.** Replace `install_selected_components` for the
   selective path (ordering, pruning, dependency checks, UE HDR, marker). Generate
   `.optidx-files`/`.optidx-components.json` from the ledger as an export only.
   Keep the standalone script working for the `--backend` launch wrapper.
