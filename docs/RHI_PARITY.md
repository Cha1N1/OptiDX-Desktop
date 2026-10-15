# RHI parity status — Desktop 0.3.4

Compared against the published [RHI README](https://github.com/RankFTW/RHI) and [guide](https://github.com/RankFTW/RHI/blob/main/docs/DETAILED_GUIDE.md) on 2026-10-12. “Implemented” describes code and local checks, not a guarantee that every third-party mod works in every Wine game.

| Area | Current implementation | Remaining difference |
|---|---|---|
| Library and profiles | Steam/Heroic/Lutris/Bottles, manual executables, disconnected cache, favourites, hidden games, display-name override, shared profiles and import/export | Windows registry stores/Game Pass have no equivalent discovery adapter; no multi-title manifest splitting |
| Component setup | Independent core components, queued/per-game/bulk updates, exclusions, selective ownership/removal | Version availability for legacy unversioned installs can remain unknown until an update records metadata |
| ReShade | Stable/Nightly/Custom/Legacy/No Addons; 32/64-bit; DX9/DX10/DX11/DX12/OpenGL naming; foreign-file checks | Wine Vulkan injection is not implemented; native vkBasalt provides a shader-effects alternative, not RenoDX addon parity |
| OptiScaler | Stable/Nightly/custom/pinned builds, repository override, existing HelixSR/Cyboman/DLSS Enabler support and FG controls | Six editable per-GPU Stable/Nightly templates with explicit application, preserving library paths/FG/loader values; Streamline swaps are independent of Enabler deployment |
| Shaders | Broad upstream catalog, named profiles, individual effects, dependencies, custom packs, textures/includes/licenses, ZIP export | Shader compilation and visual correctness need actual game testing; vkBasalt supports only its compatible effects |
| Addons and presets | Local/archive/HTTPS imports, per-game enable/disable/removal, upstream addon catalog, preset deployment | Toggling an addon that replaced a foreign original is refused; remove/restore that original instead |
| DLSS/Streamline | SR/RR/FG/NR catalogs, exact engine/plugin folders, custom payloads, version swaps, original restoration, global defaults and batch deployment | Compatibility across particular game/Streamline versions and GPUs is not validated |
| DLSS presets/MFG/render scale | Saved DXVK-NVAPI environment controls for presets, SR/RR scales, override flags, fixed/dynamic MFG and target FPS | Requires a compatible runner and GPU; no Windows driver-profile writes or hardware unlock guarantee |
| Frame limiters | ReLimiter/Display Commander deployment, mutual exclusion, component INI editor, bulk update participation; DXVK FPS alternative | Limiter runtime behavior under Wine has not been tested; no bespoke graphical editor for every limiter setting |
| RE Framework | Game-specific archive selector, custom packages, update/removal | User must select the matching archive; automatic pd-upscaler-branch selection is not implemented |
| OptiPatcher/DOF | ASI plugin deployment to OptiScaler plugins; UE DOF source and 5.0–5.6/64-bit eligibility checks | Optional game-specific behavior still needs real testing; some packaged games require a UE version override |
| Neural rendering | 64-bit Feeder/ShortFuse/DX11 bridge staging, SR/NR runtimes, motion shaders/preset; NR Cost Scaler forwarding/restore; custom imports | Requires compatible ReShade/GPU and recognized source layouts; live downloads/gameplay unvalidated; 32-bit helpers and OptiScaler NR consumers unavailable |
| Updates and tray | Read-only availability records/badges, optional four-hour checks, tray mode, per-component exclusions | No application self-updater; direct non-GitHub custom URLs may require an explicit update to detect a changed payload |
| Download watcher | Optional folder watching and notifications; addon/preset/archive drag-and-drop | Notifications do not silently install files; file-association/single-instance forwarding is not implemented |
| Game launch | Store URIs; saved Wine/Proton/UMU commands; Bottles CLI; per-game argv/env; copied persistent profile wrappers | Store URI launch keeps launcher settings. Managed env/HDR needs the profile wrapper; running indicators cover managed direct launches |
| Desktop HDR | KDE Plasma `kscreen-doctor` adapter, original state restored after command exit, deferred UE HDR completion | Other compositors are unsupported; forced termination of the wrapper cannot guarantee restoration |
| Display/driver controls | Shared peak-nits values, screenshots/hotkeys, DXVK VSync/FPS; NVIDIA OpenGL VSync/G-Sync/cache; Gamescope options | RTX HDR, Smooth Motion, Windows ReBAR/power/latency/profile export, digital vibrance and global NVIDIA profile editing are unavailable |
| Game data/notes | Cached RHI game notes, wiki-name override, PCGamingWiki link, generic UE preference | RHI-specific launch fixes, external-store URLs, Luma TAA recipes and arbitrary server-side Engine.ini templates are not automatically applied |
| Restore and diagnostics | Verified pre-operation snapshots, owned original DLL blobs, journaled config edits, failed-job rollback, live Activity | Hardware/runtime checks and crash recovery after system power loss still need broader testing |

## Validation and rollout

The stable 0.2.0 source was backed up before work. Original `~/OptiDX` is unchanged. New features live in independent desktop adapters, preserving the existing script backend.

94 automated tests cover existing component combinations plus archive containment, architecture matching, ownership conflicts, original-file checksums, failed-write/job rollback, external Engine.ini restoration, shader dependencies, DLL swaps, Linux environment encoding, KDE HDR lifetime, config edit races, and launcher discovery. Real local ReShade 6.7.3, RenoDX and DLSS 310.7.0 packages were installed/removed in temporary folders. Existing games were only inspected.

Shell DNS/networking is blocked here, so live downloads for new components are not verified. The AppImage is tested locally with bundled Python/Qt/PyYAML. Game compatibility, other distributions, hardware-dependent controls, Vulkan injection and neural rendering need separate validation. This is a substantial parity expansion, not full RHI equivalence.

## Sources and implementation references

- [RHI shader source catalog](https://github.com/RankFTW/RHI/blob/main/RenoDXCommander/Services/ShaderPackService.cs): upstream repository URLs only; no shader source ships with the app.
- [RHI manifests](https://github.com/RankFTW/RHI/blob/main/manifest.json) and [DLSS manifest](https://github.com/RankFTW/RHI/blob/main/dlss_manifest.json): source locations and schemas used by read-only catalog refresh.
- [DXVK-NVAPI settings](https://github.com/jp7677/dxvk-nvapi/wiki/Passing-driver-settings): named environment controls. MFG count `1` means 2x, through `5` for 6x.
- [DXVK configuration](https://github.com/doitsujin/dxvk/wiki/Configuration), [NVIDIA OpenGL controls](https://download.nvidia.com/XFree86/Linux-x86_64/550.144.03/README/openglenvvariables.html), [vkBasalt](https://github.com/DadSchoorse/vkBasalt), [Bottles CLI](https://docs.usebottles.com/advanced/cli), , [NR Cost Scaler](https://github.com/xenmods/DLSSNR-Cost-Scaler), [DLSS5 Feeder](https://github.com/jlrouzies-fr/DLSS5-Feeder), [DLSS5 bridge](https://github.com/NIGos/dlss5-bridge), and [KScreen doctor](https://github.com/KDE/libkscreen/blob/master/src/doctor/doctor.cpp).
