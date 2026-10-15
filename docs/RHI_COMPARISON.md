# Original research plan

This document records the initial design. Current implementation status is in [RHI parity](RHI_PARITY.md).

# RHI research and Linux implementation plan

Reviewed RHI's current [README](https://github.com/RankFTW/RHI) and [detailed guide](https://github.com/RankFTW/RHI/blob/main/docs/DETAILED_GUIDE.md).

RHI combines store discovery, per-game mod deployment, HDR configuration, component updates, shader/addon management, DLSS version management, and Windows driver controls. Its library/details interface is a useful starting point. Windows registry discovery and NvAPI driver-profile writes need Linux-specific replacements.

| Area | This first Linux build | Next implementation |
|---|---|---|
| Library | Steam, Heroic, manual executables; offline cache | Lutris SQLite/YAML and Bottles programs |
| Detection | PE architecture/imports and engine layout | Cached inspection, API overrides, better title splitting |
| Mod setup | Individual component choices, selected-only updates, and ownership-based removal | Per-component channels and failed-operation rollback |
| HDR | OptiDX native UE configuration with undo | Profile-specific engine tweaks and compositor adapters |
| OptiScaler | Existing OptiDX build, HelixSR, AMD DLL, FG settings | Per-game stable/nightly selection and INI templates |
| Updates | Queued updates and per-game exclusions | Remote availability checks and component versions |
| Restore | Verified original-file backups plus backend uninstall | Failed-operation rollback and conflict-aware restoration |
| Diagnostics | Tools, session variables, exact paths, live logs | Running-process environment capture for launcher problems |
| Launch | Steam/Heroic URI, wrapper command generation | Configured manual Proton/UMU launch profiles |
| Shaders/addons | Existing unrelated addons retained | Custom imports, shader catalogs, addon toggles |
| DLSS/Streamline | Existing backend's Enabler deployment | Explicit DLL versions, backups, restore, batch profiles |
| Frame limiters | Not deployed yet | ReLimiter/Display Commander addon transactions |
| Driver settings | Not implemented | Separate research into Linux-supported controls |
| Vulkan / DX9 / 32-bit | Not deployed yet | API-specific injection and Wine/Vulkan layer behavior |

## Architecture

The original OptiDX project remains intact. The original upstream checksum and the separately modified desktop backend checksum are recorded. The desktop package owns discovery, profiles, backup records, diagnostics, and job scheduling. A fresh worker process imports the backend per job, so its global flags cannot leak between games. It binds detection to the chosen executable and forwards existing install flags without a game-launch command.

Qt's `QProcess` streams the worker's output without blocking the interface. Discovery uses a background thread. Jobs run sequentially and use a target-folder lock. The only adaptation of backend cleanup removes manifest-owned addons, preserving unrelated addons.

Desktop 0.2.0 separates component selection, download scheduling, dependencies, and ownership records in the backend. Components can be installed or updated individually, kept when unchecked, or explicitly pruned when unselected. Dependencies are checked before writes; independent install functions remain based on OptiDX. Official Cyboman releases supply the lossy FSR payload.

## Suggested implementation order

1. Per-component release channels and rollback after a partial failure, building on the implemented component ownership records.
2. Custom shader/addon imports with original-file preservation and explicit per-game enable/disable controls.
3. DLSS/Streamline version selection using pinned manifests, integrity checks, and reversible deployment.
4. Lutris/Bottles discovery and saved manual runner profiles.
5. Availability checks, component channels, and tray/background updates.
6. Separate Vulkan/DX9/32-bit deployment adapters and compositor HDR control, validated on actual Linux games.

Windows NVIDIA profile features should not be exposed as working Linux controls until a supported equivalent is established.
