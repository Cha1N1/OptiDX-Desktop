# Unreleased — desktop quality-of-life improvements

- Appearance now offers Dark, Light and System. Dark is the original navy/teal
  style; saved Original choices migrate to Dark. System uses the actual desktop
  Qt palette (including custom KDE colors) rather than selecting an app preset.
  Native palette updates and KDE color-file replacement are followed live;
  application presets no longer overwrite the native application palette.

- Fixed the library/detail splitter producing overlapping columns. Added an
  explicit drag gutter, consistent library/header spacing and a wider navigation
  panel with clearer separation from page content. Columns cannot collapse away.

- Added 140 ms smooth wheel scrolling with capped acceleration during repeated
  ticks. Pauses and reversals reset speed; dragging, keyboard input and leaving a
  page cancel pending motion. Precision touchpad gestures and dropdowns remain
  native. Reduce motion disables wheel smoothing/acceleration.

- Prefer native Wayland on Wayland sessions, with Qt's X11 fallback. Preserve
  single-backend QT_QPA_PLATFORM overrides; inherited xcb;wayland lists now
  prefer Wayland when launched from file managers such as Nemo. The footer and copied diagnostics now report
  the actual Qt backend; selection is scoped to the GUI and cannot leak to games.

- Unified Qt's base palette and popup/menu styling with the dark controls, removing
  bright native dropdown outlines. Added rounded, arrow-free scrollbars and
  consistent focus/pressed states; corrected SVG control icon paths.
- Added interruptible 110 ms page fades and 140 ms section expansion/collapse.
  App settings includes Reduce motion; transitions never delay button actions.

- Retain per-game unsaved drafts across navigation and restarts, with Save/Revert.
- Show selected/detected/update/dependency status beside component choices and
  explain disabled core actions.
- Add persistent job history, log/backup links, rollback outcomes and removal of
  individual waiting jobs. Interrupted operations remain visible for review.
- Preview bulk updates with per-game selection, component scope and skip reasons.
- Show launch routing beside Launch game and provide the managed launch command.
- Add verified snapshot browsing and explicit recorded-file restoration through
  the rollback-protected worker. Refuse ownership/journal conflicts and retain
  newer unrecorded files.
- Remember workspace layout and navigation, add library sorting and Ctrl+F/S/R.

**Validation:** 158 automated tests pass, including draft persistence, queue controls,
restore verification and simulated restore-failure recovery. Fresh offscreen renders
checked at 1220×880 and 930×740. Tests use temporary game folders; real game installs
and gameplay were not changed or tested. Rebuilt the local 0.3.4 AppImage without a version bump. All 158 tests also
pass with the bundled interpreter; checksum, FUSE-free startup and backend help
were verified.

---

# OptiDX Desktop 0.3.4

- Fixed HelixSR removal leaving stale library paths when a game used a mapped Wine drive or dot-relative paths.
- Fixed failed operations retaining a new baseline or losing the original baseline after an interrupted uninstall. Profile changes commit after successful file inspection; recovery attempts continue independently if one location cannot be restored.
- Fixed queued operations following a later executable change and delayed shader/vkBasalt callbacks affecting another selected game.
- Preserved game-specific DLL folders, launch environments, runner options and REFramework package choices when applying shared profiles.
- Heroic launches now honor the native/Flatpak installation that supplied the game metadata. Refresh the library to update cached entries.
- Rejected ARM64 payloads posing as x64 DLLs and malformed PE headers; rejected Windows filename capitalization conflicts before deployment.
- Validated environment JSON before saving/exporting, converted booleans to `1`/`0`, and included custom display names in library searches.
- Removed repeated archive duplicate scans and cached directory checks during deployment.
- Rebuilt the Linux x86_64 AppImage.

**Validation:** 122 tests pass, including failure recovery, mapped Wine paths, delayed UI callbacks, launcher ownership and binary validation. Games were not launched or modified during verification.

---

# OptiDX Desktop 0.3.3

- Native Heroic games now launch through the installed `heroic --no-gui` command, supporting CachyOS's packaged Electron launcher instead of depending on an old desktop URI handler.
- Restores the host environment before starting Heroic and retains desktop URI dispatch when no native Heroic command is available, including Flatpak/custom installations.
- Reports launcher startup errors in the GUI.
- Rebuilt the Linux x86_64 AppImage.

**Validation:** Targeted launcher checks cover command arguments, host environment restoration and URI fallback. No games were launched during verification.

---

# OptiDX Desktop 0.3.2

- New profiles now leave HelixSR unchecked while retaining Cyboman lossy FSR4. Existing saved selections remain unchanged.
- Added **Remove HelixSR / restore direct FSR4** under Installation → Update or remove this game's setup.
- Targeted removal resets only library paths referencing managed HelixSR DLLs and connects the FSR backend directly to the existing lossy DLL. Other mods, custom library overrides, HDR and frame-generation configuration remain in place.
- Verified original HelixSR files are restored when available; untracked user files and logs are preserved. Failed operations roll back the installation snapshot.
- Successful removal clears HelixSR from the saved component selection so future updates do not reinstall it.
- Rebuilt the Linux x86_64 AppImage.

**Validation:** 106 tests pass, including targeted removal through the real Qt worker, legacy manifest adoption, original-file restoration, missing-DLL rejection and rollback after a simulated write failure. Actual gameplay still requires checking after restarting the game.

---

# OptiDX Desktop 0.3.1

- Reorganized game pages into Installation, HDR/configuration, ReShade content, installed tools, game DLLs, optional tools, launch options and game profiles, with a persistent navigation list.
- Installation now shows the exact selected components and any HDR/FG settings it also applies. Its install button appears only on Installation; update and full removal have separate, explicit scopes.
- Removed duplicate ReShade installation, profile-save and launch-command controls. Shader packs, imported files, optional tools and DLL replacements retain their own named actions.
- Moved component download channels beside installation choices and placed OptiScaler GPU INI presets under advanced configuration with descriptive labels.
- Split ReShade content into shader packs, addons/presets and configuration. Importing a file is clearly separate from installing it.
- Moved app-wide catalog refresh, scheduled checks, tray and download-watcher settings into an App settings dialog. Advanced driver overrides and package options are collapsed by default.
- Rebuilt the Linux x86_64 AppImage. Existing game profiles remain compatible.

**Validation:** 97 tests pass, including distinct installation/shader actions, navigation and advanced configuration placement. Offscreen previews were checked at regular and compact window sizes.

---

# OptiDX Desktop 0.3.0

- Added upstream shader packs, individual effect selection, dependency checks, custom addon/preset/shader imports, per-game addon toggles, and bundle export.
- Added DLSS SR/RR/FG/NR and Streamline version catalogs, custom DLL swaps, exact engine/plugin folder selection, verified original backups, global defaults, and batch deployment.
- Added ReShade/OptiScaler release channels and pins, API/architecture/proxy overrides, foreign-DLL protection, and component configuration editing.
- Added ReLimiter, Display Commander, OptiPatcher, RE Framework and eligible UE DOF fix deployment, plus optional addon catalogs, custom packages, 64-bit Feeder/ShortFuse/bridge adapters and NR Cost Scaler forwarding/restoration.
- Added Lutris/Bottles discovery, favourites, hidden games, profile sharing, game notes, component update exclusions, update badges, scheduled checks, tray mode and download notifications.
- Added manual Wine/Proton/UMU/Bottles launching and saved launch environments, Gamescope, native vkBasalt configuration, DXVK FPS/VSync, NVIDIA OpenGL options, DXVK-NVAPI DLSS/MFG overrides, and KDE HDR lifetime management.
- DLL-only OptiScaler archives now receive a minimal INI; standalone ReShade and OptiPatcher enable their required loader options with undo records.
- Failed jobs now roll back verified snapshots and UE configuration; original DLL backups use compact checksum-verified blobs.
- Rebuilt the Linux x86_64 AppImage with PyYAML alongside Python, Qt and archive/download tools.

**Validation:** 94 tests pass. Real local ReShade 6.7.3, RenoDX and DLSS 310.7.0 payloads were installed and removed in temporary folders. New live downloads and actual gameplay/hardware behavior are not yet validated.

**Limits:** Windows RTX HDR/Smooth Motion/NVIDIA driver profiles, Wine Vulkan ReShade addon injection, 32-bit neural helper layouts and OptiScaler NR consumer-fork setup are not implemented. Automatic 64-bit recipes still require live-source/game validation. See [the parity table](docs/RHI_PARITY.md).

---

# OptiDX Desktop 0.2.0

- Added a Linux x86_64 AppImage with Python, Qt, curl, unzip, and 7-Zip bundled. Game wrappers use the persistent AppImage path; bundled runtime settings are restored before launching games.

- Replaced installation presets with independent component choices: OptiScaler, ReShade, RenoDX, Luma, Cyboman lossy FSR, HelixSR, and DLSS Enabler.
- Install/update only the selected components. Unchecked components stay installed unless explicit selective removal is enabled.
- Added backend component ownership records so removal targets managed files and preserves unrelated addons.
- Existing dependencies can be reused; incompatible selections are reported before component changes. Older saved presets migrate automatically.
- Switched FSR downloads to [Cyboman's official releases](https://github.com/zgauthier2000/fsr4-shader-performance-overrides/releases). The newest published release containing `fsr4.1.1-cyboman.zip` is selected, then only the `lossy` DLL is deployed.
- Added optional GitHub archive-digest verification and installed release/hash records. Explicit updates refresh release metadata.
- Refreshes HelixSR's managed FSR forwarding copy after an FSR update.
- ReShade updates now refresh an existing standalone ReShade proxy as well as the loader DLL.
- Selected update failures are reported instead of treating an old existing DLL as a successful update.
- Added coverage for all 128 selection combinations, dependency checks, selective removal, profile persistence/migration, release selection, archive extraction, and AppImage environment restoration. **39 tests pass.**

Restart the desktop app to load the new component-selection interface. The original `~/OptiDX` launch-script project remains separate from this desktop backend.
