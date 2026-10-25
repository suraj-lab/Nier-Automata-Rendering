# NieR:Automata Rendering — Progress & Resume

Last updated: 2026-10-25 (late). **Checkpoint below is the place to resume.** Upscaling (Custom75,
FSR4 2580x1080 -> 3440x1440) and the in-game menu are working and installed; the RTX Remix track has
gone from a standalone triangle to path-traced captures of real NieR scenes.

## Checkpoint — 2026-10-25 late (start here)

**Installed in the game** (`d3d11.dll` = menu + upscaler + capture, `31fc04351e2f…`; Custom75 selected,
60 FPS cap unchanged). Rollback chain: `backups/ingame-menu-*` (newest
`ingame-menu-textures-20261025T225826Z/`), each with a hash receipt.
- **Menu:** Insert toggles; save-for-next-launch works both ways (live-tested). Mouse: WndProc
  consumption + `SetCursorPos` IAT block + **DirectInput8 `GetDeviceState`/`GetDeviceData` blanking**
  (slots 9/10) while the panel is open. User confirmed the camera stays still. NieR reads mouselook via
  DINPUT8, which is why message consumption alone did not work.
- **F9 = whole-frame capture** to `NIER_CAPTURE/frame_<tick>/draw_NNNN/` (+ `buffers/`, `textures/`).
  Static VB/IB read once per frame (dynamic always fresh), hard-linked per draw; caps 4096 draws /
  768 MB unique buffers / 1 GB textures. Real frame: 2995 draws, 0 skipped, 456 MB, ~7 s stall.
  **Texture capture (PS-bound static textures, mip 0, DDS) is installed but not yet run in the game.**

**Verified NieR facts** (details `analysis/runtime/remix-probe/world-matrix-finding.json`,
`analysis/REMIX_FEASIBILITY.md`):
- VS `cb0` = per-frame camera (view 3x4 + projection); `cb11` = per-object world 3x4 (64-byte stride, one
  per instance for `DrawIndexedInstanced`) or a skinned bone palette (48-byte 3x4s, BLENDINDICES UINT8 /
  BLENDWEIGHT UNORM8). The earlier "cb0 = world" finding was wrong.
- Colour-pass layouts declare NORMAL (half4, object space) and TEXCOORD (half2; first one is the UV).
  Front faces are clockwise. Depth pre-pass draws carry only position (+skin).
- vtable slots (checked against headers, then end-to-end mocks): context `DrawIndexed` 12,
  `DrawIndexedInstanced` **20** (19 is `IASetIndexBuffer`), device `CreateInputLayout` 11; DInput device
  `GetDeviceState` 9 / `GetDeviceData` 10.
- Shadow maps are 2048x2048 draws; a half-res 1290x540 pass exists; sky dome/cloud shells are 10-19 km
  meshes that enclose the camera.

**Remix pipeline (offline, laptop + desktop):**
- `analysis/remix-probe/scene_from_frame.py` (gated, scene v2): main-viewport draws, dedupe across passes
  keeping the colour pass, instancing, world normals + UVs -> `scene.bin`. Camp frame: 880 draws,
  3.51M triangles. `capture_to_mesh.py`: single draw -> header.
- `triangle.cpp` probe: `build.py --scene` / `--mesh`; `run_remote.py --scene <bin> --hold --shot-frame 1500`
  (laptop screenshot); `show_on_laptop.sh <label> scene <bin>` (live window in the user's session).
  Skips draws wider than 5 km (sky shells block the sun). Large scenes need ~15 s before the first RTX
  frame; the old 4 s default run never rendered them.
- **Desktop Proton works:** the probe rendered via the Remix API with Portal RTX's runtime under
  proton-cachyos 11 on this Arch desktop.

**Next (Goal 1 — good-looking snapshots, then decide on live play):**
1. User F9 with the texture build -> identify the albedo SRV slot from real data -> converter v3 (per-draw
   albedo texture) -> probe creates Remix materials from the DDS files.
2. Sky as Remix sky (instead of skipping), sun direction from the game's constants (likely `cb10`).
3. Then Goal 2 feasibility: load the Remix runtime inside a DXVK D3D11 process (NieR) under Proton.

**Delegation this session:** desktop `local-worker` built `capture_to_mesh.py`, `scene_from_frame.py` v1/v2
against frozen gates (one thinking runaway; `:low` + write-first fixed it). Cloud reviewer found real
malformed-input bugs twice. Ledger: `~/Documents/Local-Model-Delegation-Outcomes.jsonl`.
Methodology for future projects: `~/.pi/agent/skills/gated-delegation-re/SKILL.md`.

---

## Prior continuation: settings, patch safety and FAR (start here)

- **Installed for approved test:** candidate `c4996b836646f9b26db6dcd57df609daa754e49a5f89b23ce454e0874fb248e0`,
  with new `NIER_RENDER.ini` now selecting Custom75. Original mod DLL, `NIER_DLAA.ini`/debug settings and
  native 60 FPS cap unchanged. No game launch by assistant, commit or push.
- **Rollback:** `backups/startup-settings-test-20261024T161800Z/` contains the exact previous v4 DLL,
  mod/INI snapshots, logs, verified hashes and `RESTORE.md`. `NIER_RENDER.ini` was absent before this
  test. Keep logs on rollback; restore the v4 DLL and remove only our test INI with the game closed.
  Do not use the pinned v4 deploy script while this unknown-to-it candidate is installed.
- **Candidate source/build:** `analysis/runtime/startup-settings/d3d11.dll` (gitignored).
  Reads Native or Custom75 once at startup. Missing file preserves Custom75; invalid/unreadable
  config selects Native. Native exits before patching or scale polling. Tracked v4 build stays unchanged.
- **Safety fix:** reduced scale now requires both depth and proxy success. The proxy installer
  prepares all seven sites before writing, reverses overlapping-page protection restoration,
  and rolls bytes back after cache/protection failures. Persistent OS failures can prevent full
  recovery and require restart; startup patching is not thread-suspended hot reload.
- **Gates:** pure settings ASan/UBSan pass; new actual-function fault harnesses pass; existing
  29/29 Part 3 checks pass; 11 real Win32 INI cases pass under an isolated Wine prefix. MinGW
  candidate builds with `-Werror`; 51 export names/ordinals and 49 forwarders match. Luna accepted
  the source/tests for offline use. Details and commands: `analysis/STARTUP_SETTINGS.md`.
- **FAR:** `analysis/FAR_RESEARCH.md` records the pinned-source limiter/timing findings. New
  `analysis/FAR_UNCAP_FOLLOWUP.md` qualifies the conditional external target, version detection,
  typed-pointer arithmetic and cutscene uncertainties. Desktop local-worker research
  `bc33ffcd-024a-41e0-a435-f69d3c357904` exceeded its eight-minute brief and was interrupted/paused;
  a draft exists in managed artifacts but is not an accepted independent review. Do not resume it
  silently. No high-FPS correctness or quarantined-binary equivalence is established.
- **Parked:** GPU headroom capture, FG and NR. Luna caught non-finite optional sampler readings;
  lead reproduced/fixed it and all eight fake-sysfs tests pass. Live capture remains pending.
  No extra presets, menu, uncap, NR or FG integration yet.

**Native test passed:** `Preset=Native scale=1.000 valid=1 defaulted=0`, no depth/proxy/scale patches,
FSR4 native AA 3440x1440 -> 3440x1440, no logged errors; user reports no visual issues.
Evidence: the backup's `native-run/` folder.

**Custom75 test passed:** both prerequisite patches applied (7 proxy sites), renderer/gate scale 0.75,
Output SRV and slot-0 redirect active. FSR4 colour/depth/MVs are 2580x1080; output is 3440x1440.
Logs reach evaluation frame 3600 with no error/warning lines; user says "done, looks good".
The early setter line reports boot dimensions 1600x900; actual FSR context dimensions above confirm
configured 3440x1440 output without any resolution re-apply. Evidence: the backup's `custom75-run/`.

**Menu design decided:** one compact ivory/charcoal Dear ImGui panel; official MIT Win32/D3D11
example/backends as references, FAR/ReShade for hierarchy only. Active/saved/edited values stay
separate; Save means next launch. Default design hotkey Insert; F8 already belongs to the AA mod.
One shared UI for native Windows and Linux/Proton, including eventual Windows-on-ARM host testing
with the x64 game ABI. Windows support is not yet validated; the Windows mock is a capability-aware
scenario, not a support claim. No in-game menu/hooks were implemented or installed.

**Claude Design received/reviewed:** the refined ivory/charcoal panel is the UI target. Independent
Luna review `1ad38d06-5472-4b26-8e5c-28d1f99b78f4` accepted it with notes; right-pivot positioning
and repeat DPI scaling need correction in C++. `analysis/menu-design/IMPLEMENTATION_NOTES.md` records
those corrections, simulator quirks and integration limits without editing the received files.

**Offline menu controller candidate:** `analysis/checks/menu_state.h` reuses the existing mode enum,
separates applied/saved/edited state and performs no I/O or game work. Tests written first passed
ASan/UBSan/-Werror across 69,177,612 transitions; MinGW x64 cross-build passed (EXE not executed).
`test_menu_design_prototype.cjs` passes 10 scenarios against the actual exported state script without
loading its browser/CDN runtime. Receipts: `analysis/runtime/menu-state/validation.json`. The header
is NOT integrated into the production setter; no real config writer or in-game overlay is built.

**Laptop used and result validated:** user confirmed game-free. Laptop Qwen 35B-A3B helper
`a029dbdb-ea88-4376-93fb-fcdf6e15e618` extracted the design constants: 19 colors, 11 layout and
16 typography tokens, DPI scales and glyphs. It put JSON in the managed report rather than the
requested repository file; lead promoted that exact block without rewriting or rerunning the model.
`analysis/checks/test_menu_style_tokens.py` now passes against
`analysis/menu-design/claude_style_tokens.json`. All three original handoff hashes and live game
files remain unchanged. Receipt: `analysis/runtime/menu-style-tokens/validation.json`.

**Isolated preview DONE:** `analysis/menu-preview/` contains the real ImGui panel, Win32/D3D11 host,
reproducible build/capture scripts, pinned MIT ImGui v1.91.9b and unmodified OFL IBM Plex fonts/notices.
42 native ASan/UBSan layout/state cases passed; MinGW x64 build passed; all 42 D3D11 Wine/Xvfb captures
passed (7 fixtures × 2 resolutions × 3 scales). The footer stays in bounds at 200%, body scrolls,
unknown sizes stay labelled unknown, and closed frontend draws zero vertices. Saves are simulated
in memory only. Screenshots: `analysis/menu-preview/screenshots/`; full capture/geometry receipt:
`analysis/runtime/menu-preview/render-validation.json`. Initial headless launch timed out; the retry
passed with optional installers disabled, but prefix warm-up also changed, so root cause is unproven.
Luna review b223507e / follow-ups 7d1adcf6 and 8c101e8d accepted OFFLINE PREVIEW with notes; all three
P2 findings were corrected/confirmed. No native Windows/ARM64 or in-game execution is established.

**Save/status checkpoint accepted offline:** lead-owned `analysis/checks/preset_rewrite.h` passes
437 preservation/error assertions, ASan/UBSan, two-TU linkage and MinGW. The local-worker draft was
rejected after a diagnostic loop; parent workflow b1f8ef23 / child 80a1a375 were stopped before review.
Frozen files were unchanged before lead edits. `startup_status.h` passes concurrent publication tests;
actual setter/bootstrap producers are connected and fault-tested, without backend/dimension claims.
The new DLL exists ONLY at `analysis/runtime/settings-writer/status-candidate/d3d11.dll`, SHA256
`914948447eeae3c3e8b486402c99d3da61a1e191ec8eb5a37afe3eca5bdd9fdd`; ABI checks retain all 51
exports and 49 forwarders. It is NOT installed. Part3 remains 29/29. Reviewer 456088bc found no issues
for these components only. The preview still uses simulated saves/status; no real writer/UI consumer.

**Resource state:** desktop Qwen was JIT-loaded for that bounded job, then unloaded again after the
failed workflow stopped. Laptop services/settings were not touched. The old FAR run remains paused;
do not resume it silently. No model job is assigned merely to keep memory occupied.

**Real save writer DONE offline (2026-10-25):** `analysis/checks/settings_save.h`, 13 oracle + 6 extra
Wine cases, 5 mutants caught, Luna blocked once (same-bytes swap) then accepted. Menu state now models
missing/invalid/unreadable files and committed/not-saved/recovery-required outcomes (desktop worker,
gate passed, reviewed; lead fixed a notice-priority flaw in its own contract). Details and limits:
`analysis/SETTINGS_WRITE_PLAN.md`. Laptop is in use for work: desktop-only delegation for now.

**Step 4 DONE offline:** startup status -> menu (`menu_session.h`, desktop worker, first-pass gate),
real save adapter with fresh re-read (`menu_settings_io.h`, 20 Wine cases), panel notices for
invalid/unreadable/recovery files, 66 layout + 66 D3D11 capture checks. New screenshots in
`analysis/menu-preview/screenshots/`. RTX Remix MCP not visible in this session yet (needs restart?).

**Step 5 built offline (NOT installed):** the proxy DLL now hosts the menu (`checks/menu_overlay.cpp`,
vtable-slot hooks after NIER_DLAA, Insert toggle, real writer). Wine mock-game E2E passes (panel draws,
real click repairs the INI, stub layer sees 80/80 frames, fails closed without fonts). Design, evidence,
limits and the live-test/rollback plan: `analysis/IN_GAME_MENU.md`. Luna c9bc992c blocked once (ImGui
DX11 backend cleared HS/DS/CS; reproduced cs_lost=51, fixed, 0) then OK with notes for a supervised test.
Menu DLL `ac58f09f…` (runtime/menu-dll). Live test requires explicit user approval. Keep
save-and-restart only and Custom75 unchanged. Resolution/long-play, native Windows/ARM64 and real
swapchain/input tests remain pending. Keep v4 pins/build and exact rollback intact.

## Earlier session 2026-10-24 (history)

**Depth fix is DONE and live-verified.** The depth-patch code cave (in `checks/depth_patch.h`) was
reviewed by a cloud reviewer (caught + fixed a P0 EFLAGS bug) and confirmed in-game: scene depth
now `2580x1080 D24S8 array=1` matching the 0.75× colour. The game renders colours correctly at
reduced scale; the residual "shaking" is the DLSS camera jitter (expected — FSR4 skips at reduced
scale, see below).

**FSR4 upscaling runs in-game (2026-10-24, test 2).** `CreateFeature: 2580x1080 -> 3440x1440`,
6613 frames evaluated, 0 evaluate failures; a mid-game resolution change (2560x1080 -> back)
rebuilt cleanly. Jitter shake is gone. Built in `checks/proxy_patch.h` (5 sites, 320-byte cave):
parts 1-2 (native OutWidth/OutHeight + Output, fixed float->int with `cvttss2si`), Part 0
(dispatch size gate) and **Part 0b** (identical size gate in the linear-depth capture at
`0x18001a6a4`; test 1 failed on it with "linear depth target not found yet, skipping").
Setter DLL `3aaf52fa…`. Details: `analysis/UPSCALING_PATCH.md`.

**Part 3 DONE (test 3, 2026-10-24): correct image, user-confirmed "looks good".** Test 2's
offset/zoomed image came from the mod's copy-back cropping the native FSR output. Part 3 adds an
exit hook in `FUN_1800173c0` that calls the setter's `on_dispatch_exit`, which rebinds PS SRV
slot 0 to an SRV of the FSR Output for the draws that read the scene after dispatch, and skips
the copy-back. Frame dump: bloom `#5266` and tone-map `#5286` read Output `T4803` (3440x1440,
bind 0x88) at slot 0, the pre-AA reader is untouched, and there is no `CopyResource`. The tone-map
samples with plain UVs, so no shader constant patch was needed. FSR: 0 evaluate failures, clean
rebuilds across two resolution changes. Design: `analysis/PART3_REDIRECT.md`.

Builds: v3 `936602b3…` (tested in game; superseded by the permanent v4 install below). v4 `3afafb60…` (=
`analysis/build/scale-setter/d3d11.dll`) adds the reviewer P1/P2 fixes: retry a failed Output
SRV, assign only on SUCCEEDED, log when the copy-back is skipped without a redirect. v4 is
gated (29/29) and only changes failure paths; it has not been run in-game yet.

Historical test 3 state: **v3 test DLL** (`d3d11.dll` = setter, `d3d11_dlaa.dll` = mod,
`NIER_DLAA.ini [Debug] Enabled=1`), superseded by the permanent v4 install below. The old native-AA
restore entry point was
`backups/upscale-test-20261024T132205Z/restore.sh` (hash-verified). Test logs and dumps are there
too; that folder's `install.sh` installs v1, so install v3/v4 manually as done in test 3.

**Permanent install (2026-10-24): setter v4 INSTALLED via `analysis/deploy/nier_upscale.sh`**
(status/install/restore, hash-pinned, refuses while the game runs; tested by
`analysis/deploy/test_nier_upscale.sh`). Debug keys off. The scale applies at launch, so no
resolution re-apply is needed. The original mod files are in `backups/native-aa-baseline/` (gitignored).
v4's failure-path fixes get their first real run in the next play session.

**Previous next step (now parked):** measure GPU headroom (A/B on GPU usage/power at the 60 FPS cap),
then frame generation (afmf-linux). Startup settings/menu work now comes first. DLSS 5 NR stays parked.

**New tools:** `checks/analyze_framedump.py` (delegated to local-worker; gate
`test_analyze_framedump.py` passes) auto-checks depth/colour size + array-count invariants on a
`NIER_DLAA_frame_*.txt` dump. `checks/proxy_patch_test.cpp` is the native test for parts 1+2.

*(Superseded on 2026-10-24: the current game state is described at the top of this section.)*
**Older installed game state:** restored to the safe native-AA state at checkpoint (see below).
To re-test the depth fix or upscale patch, re-run the install flow (rename `d3d11.dll` →
`d3d11_dlaa.dll`, install `analysis/build/scale-setter/d3d11.dll` as `d3d11.dll`, set
`NIER_DLAA.ini` `[Debug] Enabled=1` for F10 dumps), and use the backup in `backups/` to restore.

The user-approved scale-only game test ran on 2026-10-23 and was restored; the
current continuation is offline only. Historical sections below retain their
original scope unless explicitly superseded.

**Current user constraint:** do not launch NieR, attach to live game processes,
replace installed DLLs, or change game configs/saves without fresh approval.
The user approved only offline evidence files and report corrections for this
continuation. The next game test is deferred until they are at the desktop.

## Goal and order

1. **FSR4 native AA** — DONE, working.
2. **Resolution upscaling** — DONE (2026-10-24): FSR4 2580x1080 -> 3440x1440 with native post-processing (test 3).
3. **DLSS 5 NR** — UNBLOCKED, parked by choice (see "DLSS 5 NR findings" below). The old blocker was wrong twice: the DLL is available, and the real limit is hardware.
4. **Frame generation** — afmf-linux installed & verified, not yet tested in-game.

## DLSS 5 NR findings (2026-10-24, parked; pick up later)

- **Desktop has no NVIDIA GPU** (`lspci`: RX 9070 XT, RX 6800 XT, Raphael iGPU; amdgpu only). Native
  DLSS (any version) cannot run here; the FSR4 bridge replaces DLSS, it does not run it.
- **Laptop `spaghetti` is an NVIDIA RTX Spark N1X** (Blackwell, 6144 cores, driver 617.69, `nvidia-smi`
  reports 49152 MiB unified; plus NVIDIA NPU). RTX Spark is on NVIDIA's DLSS 5 support list.
- **DLL source (user-owned):** Portal with RTX (app 2012840; official DLSS 5 NR since its 21 Oct 2026
  RTX Remix update) on the laptop ships `nvngx_dlssnr.dll` **v310.9.16**:
  `C:\Program Files (x86)\Steam\steamapps\common\PortalRTX\bin\.trex\nvngx_dlssnr.dll` (x64, 266,424,944 B)
  and `...\bin\.trex_arm64\nvngx_dlssnr.dll` (ARM64, 266,392,688 B). Also being downloaded on the desktop
  (`/mnt/second/SteamLibrary`). Never redistribute it; NVIDIA's licence does not address reuse outside the
  shipping game (grey area, personal use only).
- **NieR is also installed on the laptop** (`steamapps\common\NieRAutomata`, with `nvngx_dlss.dll` v310.9.16).
- **Route A (recommended first): laptop + NVIDIA runtime.** Verify Portal with RTX's NR mode runs on the
  laptop, then try NieR (x64 under Windows-on-ARM emulation) + NIER_DLAA + an NR injector on its DLSS
  calls (OptiScaler "DLSS 5 one click" is the obvious candidate; DX11 support unverified). Unknowns:
  NieR frame rate under emulation, injector DX11 support.
- **Route B: desktop + open-source AMD port** `github.com/lmxxf/dlss5-on-amd-9070xt-porting`: from-scratch
  HIP reimplementation of the 71-block DLSSNR network for gfx1201 (= RX 9070 XT), weights from the user's
  own DLL, runs pre-upscale (network on render-res frame, then FSR). Windows-only today (`amdhip64_7.dll`,
  D3D12<->HIP shared buffers); NieR here runs on Proton, so it would need a Linux ROCm port plus a
  Proton<->native-HIP bridge: research-grade, weeks. Not bit-exact; per-frame history reset.
  **Caution:** the repo tree appears to contain an `nvngx...dlssnr.dll` in a dev folder; do not clone it
  wholesale (fetch source folders only). A second project, Daniel Blonk's "DLSS NR on AMD" / NeuralHub,
  is closed-source (installer only, unauditable): avoid.

No FPS uncap anywhere. Game runs at its native 60 FPS cap. Resolution upscaling = lower GPU load for headroom (not more FPS). Frame gen later = 60→120 via interpolation, still no uncap.

## Display regression and fix (2026-10-19)

**Symptom:** game rendered 720×480 in a corner, then offered at most 1920×1080;
3440×1440 missing from the list, "Select Monitor" greyed out.

**Root cause:** the Oct 18 22:27 swap to the Windows 10 exe (done for WAX). The
Win10 build selects its monitor by name via `DisplayConfigGetDeviceInfo`. Under
Xwayland, Wine has no real EDID, so both monitors are `Default_Monitor` and the
game takes Wine's `DISPLAY1`. With no X primary output set, Wine's `DISPLAY1` was
the ViewSonic (1920×1080). The compat exe did not use those APIs and offered
3440×1440. Verified with `analysis/checks/display_probe.cpp` (DXGI/GDI view, run
in the private test prefix). Not caused by the `[Debug]` INI edit, the monitor
layout, Motion Blur, or `Graphic.ini` (all ruled out; Graphic.ini restore was a
no-op because `\\.\DISPLAY1` was the ViewSonic).

**Fix:** `xrandr --output DP-2 --primary` (Xwayland, runtime-only). Probe then
shows `DISPLAY1` = Dell 3440×1440 as DXGI output 0. Made persistent in
`~/.config/hypr/modules/monitors.lua` (re-applied on `hyprland.start` and
`monitor.added`, with a 20 s retry for Xwayland startup); luac/sh syntax checks,
`hyprctl reload` and `configerrors` clean. Original backed up at
`backups/hypr-primary-20261019/monitors.lua`. The dotfiles copy
(`~/Projects/Dotfiles/arch_hyprland_dots/.config/hypr/modules/monitors.lua`) was
not updated. Revert: restore the backup, or `xrandr --output HDMI-A-1 --primary`.

## Recorded game working state (verified 2026-10-18; not re-tested here)

Game dir: `/mnt/second/SteamLibrary/steamapps/common/NieRAutomata`

| File | What | SHA-256 |
|---|---|---|
| `NieRAutomata.exe` | Windows 10 build (WAX-supported) | sha1 `420cbab7daa1d94a79473c0a6271ef9c30e516e5` |
| `d3d11.dll` | NIER_DLAA proxy → FSR4 | `3d628eb576b505180206653d72e4e4da6a4345334f19863256ab5b10e06b6915` |
| `dinput8.dll` | LodMod | `06c5e5f1b3f4675f6d09fcaa81a6b5326b74e15a3d12312678527df68922c919` |
| `dxgi.dll` | WAX (texture injection) | `f17c392569cbb3d1ab2dbdcc19f8f1d5b779c70ce25b3a6a6aa98f1299f7517d` |
| `NIER_FSR4.dll` | open-source FSR4 bridge | `236511e11b0e4f516d1d6c475bcf2ffccbf05f662a7b468d9e0597cf1afb87c9` |
| `NIER_DLAA.ini` | AA toggle = F8 (`0x77`) | — |

Steam runner: **GE-Proton11-7-x86_64** (symlink in `~/.local/share/Steam/compatibilitytools.d/` → `analysis/runners/GE-Proton11-7-x86_64`).

Launch options:
```
WINEDLLOVERRIDES="d3d11=n,b;dinput8=n,b;dxgi=n,b" mangohud gamemoderun %command%
```

In-game: Anti-Aliasing **Off**, Motion Blur **On** (mod uses MB pass for character motion vectors, hides visible blur).

Textures: WAX texture-only config at `wax/config.json` (all gameplay patches off, `auto_purge_inventory=false`, `uncap_fps=false`). 289 textures active in `wax/mods/!base/textures/` (292 copied; 4 non-canonical author filenames skipped by WAX's 8-hex hash match).

afmf-linux v1.3.1 installed (Vulkan implicit layer, dormant until `AFMF_ENABLE=1`): lib `~/.local/lib/afmf-linux/libafmf-linux.so`, manifest `~/.local/share/vulkan/implicit_layer.d/afmf-linux.json`. Uninstall: `install.sh --uninstall`.

## Backups & quarantine

- `backups/` — hashed backups of saves + configs at each phase (native-aa, visual-stack, wax, win10-exe-swap).
- `quarantine/` — moved/blocked files: Special K (`specialk-crash-*`), compat exe (`compat-exe-*`), osverification scripts (`osverification-*`), instrumentation mod DLLs (`instrumentation-*`).
- **Important:** if Steam "verify integrity" runs again, `NieRAutomataCompat.exe` + `win10setup.bat` + `win8_7_setup.bat` + `installation_os_check.vdf` will return and must be re-quarantined (they re-select the Win7 compat exe on launch).

## Resolution upscaling — investigation status

### Render-target map (captured via instrumented proxy)

Log: `data/texture-map.log` (game CWD is `data/`, not the game root).

Main scene (what FSR4 already hooks), all native 3440×1440:
- **R11G11B10F** `SRV|RTV` — HDR scene color (the scene buffer).
- **D24_UNORM_S8_UINT** `DSV` — depth buffer.
- **R32_FLOAT** `SRV|RTV` — linear depth/aux.
- **R8G8B8A8_UNORM** `SRV|RTV` — LDR post/HUD composite.
- R11G11B10F + `UAV` — compute HDR passes.

Bloom downsampling chain: 1720×720 → 860×360 → 430×179 → … (R11G11B10F).
Also a parallel 16:9 chain (1600×900 / 800×450 / 400×225) — likely UI/menu.
Thousands of immutable `FMT_71/72/77/78` (BC1/2/3/5) mipmapped assets — game textures (WAX's target).

**Earlier hypothesis, not an established integration:** scale scene/depth and
viewports, reconstruct before native post/HUD. The allocation map does not prove
the resource handoff. Research on 2026-10-19 found that the closed proxy copies
Output back into the original scene, preventing a native→reduced CopyResource.
The bridge already supports unequal render/output sizes synthetically
(320×180→640×360, provider 4.1.1); the game caller/routing remains unresolved.
See [research decision](analysis/UPSCALING_RESEARCH.md).

### RE findings (Ghidra via REA CLI)

Target: NIER_DLAA d3d11.dll (original SHA-256 `f1c77c58…`), image base `0x180000000`.

- Hook-install function: `FUN_1800039c0` (`0x1800039c0`). Evidence `ev_49e631910fa6a36726065db46ae08aa97012de12f25cdd18fbb43ce6de3fef61` (in `analysis/evidence/hook-install-function.json`).
- Device hooks: **CreateBuffer(slot 3), CreateVertexShader(12), CreatePixelShader(15), CreateComputeShader(18), CreateSamplerState(23), CreateDeferredContext(27)**. The installer calls `FUN_180006480` for Immediate-context hooks (PSSetShader=9, PSSetSamplers=10, OMSetRenderTargets=33, …). `FUN_180005750` instead installs DXGI factory swap-chain hooks; the earlier attribution was incorrect.
- **It does NOT hook `CreateTexture2D` (device slot 5) or `RSSetViewports`**. These are possible interception points, not evidence that two hooks suffice for upscaling.
- Earlier dossiers: render dispatch `0x180018210` (sets `Width=OutWidth=scene width` → native AA), NGX param helper `0x180019f20`, NGX loader `0x1800229a0`.

### vtable slot facts (also checked against local SDK)

- Device vtable: `CreateTexture2D` = **slot 5** (my logger proved it); prefix = 3 (IUnknown only).
- Context vtable: prefix = 7 (IUnknown + 4 ID3D11DeviceChild methods). `PSSetShader`=9, `OMSetRenderTargets`=33, **`RSSetViewports`=44** (not 40 — my first logger used 40, bug).
- These are raw 0-based vtable indices. The compile-only
  `analysis/checks/d3d11_abi_check.cpp` now verifies them and related RE offsets
  against the local MinGW SDK. Slot 40 is **DrawInstancedIndirect**, with a
  different signature. The old built logger must not be reused; corrected source
  and the separate new DLL are covered by the latest offline-validation report.

### Proposed interception mechanism (not a complete scaling design)

An outer `d3d11.dll` could chainload renamed NIER_DLAA and intercept allocation
and viewport calls. Distinct hook slots avoid one direct collision but do not
prove export coverage, context lifetime, safe chaining or native-output routing.
Do not build the two-hook scaler as originally proposed without resolving:

- A distinct native Output and native post destination: the closed proxy's final
  `CopyResource(scene, Output)` requires identical dimensions.
- Caller resource allocation and NGX dimensions: the bridge already accepts
  separate sizes and dispatches using actual output descriptors. Hardcoding
  OutWidth/OutHeight in the bridge cannot fix reduced output allocations.
- Coherent scene/MRT/depth/MV selection, render-size constants, compute coverage,
  jitter calibration, and native post/HUD consumers.
- Logger resource-flow coverage: the source correction fixes slot/chaining/export
  defects and passes isolated immediate/deferred tests, but allocation/viewport
  logging alone still cannot identify the native post/HUD handoff.

## Research continuation (2026-10-19)

README and visual-stack entry points now distinguish the current recorded setup
from historical deployment instructions. The workspace root is not a Git
repository; all three upstream Git checkouts were clean at inspection. No Git
initialization, commits, pushes, or upstream updates were performed.

Two read-only subagents completed local sizing/copy-back analysis and primary
Microsoft/AMD API research. Their findings and parent source spot-checks are
preserved in [UPSCALING_RESEARCH.md](analysis/UPSCALING_RESEARCH.md).

**Result:** bridge changes are not the first gate. The closed proxy's native-AA
resource/copy-back contract must be separated into reduced input and a compatible
native post destination. Existing texture logs do not establish that boundary.
The initial two-agent research did not run tests or change source/game files.

Offline continuation then located the actual allocator (`0x180017e20`), texture
helper (`0x180019c50`), scene-selection gate (`0x1800173c0`) and pre-Draw boundary
(`0x180004130`). New REA evidence and a separate updated snapshot are saved.
All mod-owned MV/depth/Output/aux targets use the same scene dimensions. The gate
also compares PS SRV slot 0's texture dimensions with camera metadata before AA;
shrinking only allocations may skip AA entirely. At that stage the native post
destination and camera/jitter semantics were unresolved; subsequent camera and
shader work is recorded below. Details and Evidence IDs are in the research decision.

Added a compile-only SDK ABI/layout check; MinGW `-fsyntax-only` passed with
`-Wall -Wextra -Werror`. Static PE checks confirm original 51 exports/creation
ordinals 22–23 versus old logger 2 exports/ordinals 1–2. That pass left the logger
source/DLL unchanged; the later correction is recorded below. The third scout's logger-readiness audit is
retained under run `7d290651-2a39-47a8-8522-a6fe3f64e539`.
That initial pass performed no Windows/GPU execution or installed changes.

### Latest offline implementation and synthetic GPU results

See [OFFLINE_VALIDATION.md](analysis/OFFLINE_VALIDATION.md) for complete scope,
checks, artifacts and remaining limits.

- Camera getter/producer/setters are mapped: W/H at camera-copy +0x08/+0x0c,
  generated pixel jitter +0x10/+0x14, 32-entry Halton-style sequence, projection
  mutation `(2*jx/W,-2*jy/H)`, NGX jitter multiplied by scene/camera size ratio.
  Fifteen new REA records and a camera snapshot are in `analysis/offline-camera/`.
  Subsequent shader work resolves MV units; exact dimension-source interface and
  actual game temporal timing remain unvalidated.
- Logger source is corrected: slot 44, per-slot originals, safe publication/error
  diagnostics, sibling proxy loading, 51-export parity, optional outputs, base
  deferred contexts and per-line context/thread attribution. No scaling code.
- Native registry tests, including ASan/UBSan, SDK compile assertions and seven
  Python verifier tests pass; MinGW builds pass with warnings treated as errors.
  Fresh review and focused follow-up found no remaining offline-code findings.
- RX 9070 XT processed **3440×1440 native** and **1720×720→3440×1440** through
  FSR4.1.1: 16 frames each, then the same pair through logger→renamed AA-proxy
  device creation. **64 total synthetic evaluations**, no evaluation failures.
  Independent raw-output verification passes for all four images.
- Logger chain test records immediate/deferred viewport state and unbinds, without
  hook errors. The probe still calls NGX directly, so this does not validate the
  closed mod's game-specific dispatch/copy-back or HUD integration.
- Artifacts: `analysis/isolated-gpu-3440-20261019/`; new logger DLL only at
  `analysis/build/offline-logger/d3d11.dll` and in the private test directory.
  The old built logger and installed game stack were not replaced. The private
  Steam appcache link resolves inside the test workspace, not installed Steam.

No game run, live game capture, save/config/installed DLL changes or upstream edits.
Synthetic timing is not a performance or temporal-quality benchmark.

### Motion-vector unit question resolved offline

See [MOTION_VECTOR_RESULTS.md](analysis/MOTION_VECTOR_RESULTS.md).

- Five embedded DXBC containers were extracted and CPU-disassembled; immutable
  source/shader hashes, PE offsets/VAs and RDEF metadata are retained in
  `analysis/offline-motion/` with a separate Ghidra snapshot.
- Camera CS and character PS both compute previous-minus-current NDC multiplied
  by `(W/2,-H/2)`: screen-space pixels under intended previous-matrix bindings.
  Character PS writes validity W=1; CS chooses object XY unchanged only for W>0.5.
- Exact shader creation/binding addresses connect the bytecode to the producer
  path. AMD's FSR4.1.1 manual independently confirms pixel/current-to-previous
  convention; the bridge copies values and uses unity scale by default.
- The actual extracted compute shader passes 10 synthetic cases in R16G16_FLOAT
  and the same 10 in diagnostic R32G32_FLOAT. No rewritten substitute was used.
  These are producer-shader checks, not new FSR evaluations or object PS raster tests.
- The initial 20×12 R16 test failed a fixed 0.001 threshold by one half-float ULP;
  that failure is retained. Float32 error was 3.57627869e-7 pixels. Final tests
  use self-checked per-component half ULP bounds and 1e-5 for float32; review passed.
- Do not add a blanket MV multiplier. A reduced-resolution path must coordinate
  the camera scene grid, object replay grid and constants before their integer-
  load merge; one global scale cannot repair a mixed-grid vector field.

No game inputs/timing, bone-motion correctness, temporal quality or native post
routing was validated. The game remains closed and installed files untouched.

### Dimension source and routing (offline)

See [ROUTING_RESULTS.md](analysis/ROUTING_RESULTS.md).

- Camera W/H come from `IDXGISwapChain::GetDesc().BufferDesc` on entry to the
  hooked Present (slot 8 → GetDesc slot 12), not from the scene texture. With the
  swap chain at native size they stay native, so a smaller scene currently fails
  the pre-dispatch size gate. Evidence: `analysis/offline-dimensions/`.
- Logger now passively traces SRV/RTV/DSV/UAV bindings, draws, dispatches, copies
  and command lists with resource identities; ABI types are compile-checked.
- Mock reduced→native→native-post route (nearest neighbour, not FSR) passes 10
  exact-pixel checks with and without logger→renamed AA proxy. The chained
  141-event trace passes a semantic verifier; 7 verifier unit tests pass.
- Review fixes are in place. A fresh Claude Haiku 5.5 re-review confirmed them:
  **OK with notes** for offline use, no P0/P1. Doc overclaims it found are fixed;
  code-level P2 hardening is deferred while the logger is on hold.
- **Better capture path found:** the installed AA proxy has a built-in frame
  render-graph dump (`NIER_DLAA.ini` `[Debug] Enabled=1`, F10 or `DumpFrameAt`).
  It records every pass of one frame with shaders, SRVs, render targets, UAVs,
  copies and a resource table. This needs only an INI change, no DLL swap, so the
  in-game logger is on hold.
  Debug-mode safety is now checked statically (`analysis/offline-framedump/`):
  `Enabled=1` with no key pressed adds only ~6 GetAsyncKeyState polls + a compare
  per foreground Present; no recording or state change. F10 is edge-triggered and
  needs game-window focus; one file writes synchronously two Presents later
  (~1-few MB, brief hitch). Avoid F11/End/PageUp/F6/F7/Home (they change rendering
  or add readback).

## Frame-dump results (2026-10-19)

See [FRAMEDUMP_RESULTS.md](analysis/FRAMEDUMP_RESULTS.md). Two in-game dumps
(AA mod's own F10 dump, INI-only, restored and hash-verified) at 3440×1440:

- After the AA copy-back, the scene is read by exactly two passes, both at PS SRV
  slot 0: bloom downsample `68495C5BDCDE8322` (1720×720) and tone-map
  `2C76D68A52500A65` (3440×1440). Nothing writes the scene again.
- HUD (~50 draws, `A1B77252`) and the final present pass work on native
  intermediates, never the scene.
- Same structure in both frames.

So the equal-size copy-back blocker can be avoided: give those two draws the
native FSR output's SRV instead of copying it into a smaller scene. Remaining hard
part: scaling the scene domain (~1000 draws, depth, pre-AA scene readers, camera
W/H and jitter, motion grids).

## Remix object milestone: first NieR mesh rendered (2026-10-25)

- In-game F9 captured 2B's head (786 indices, 2580x1080 scene viewport) through the menu DLL; the
  converter (`analysis/remix-probe/capture_to_mesh.py`, gated) turned it into a header, and the standalone
  Remix probe path-traced it on the laptop. Details, evidence and limits: `analysis/REMIX_FEASIBILITY.md`.
- Menu DLL now installed: `8506cea2…` (DirectInput mouse block, capture size filter >=128 indices,
  viewport + layout slot in capture JSON, half-float decode). User live test of the mouse fix pending.
  Rollback chain under `backups/ingame-menu-*`.

## Remix scene milestone (2026-10-25, later)

- F9 = whole-frame capture with a per-frame static buffer cache (menu DLL `947784e0…` installed); first
  NieR frame rebuilt and path-traced in Remix on the laptop. Mouse fix confirmed live by the user.
  Details: `analysis/REMIX_FEASIBILITY.md` "First NieR scene in Remix".
- Next: user full-frame F9 with the cached build (expect ~3400 draws incl. colour pass), then UVs/textures.

## Next steps (pick up here)

**Session ended 2026-10-19 late. User approved: finish option 1, then option 2.**

1. **Option 1 (offline): DONE 2026-10-23.** See
   [VIEWPORT_RESULTS.md](analysis/VIEWPORT_RESULTS.md) (verifier:
   `analysis/offline-viewport/verify_viewport_scale.py`, 18/18 pass). Scene
   viewports follow the bound target size (begin-pass `0x140243b90`, 45 callers).
   A scale setter `0x14024d2b0` exists but only in a dead debug hotkey.
   `0x1402f3e60` is AMD CasSetup; inspected mode setters pass 0/1. Test CAS off
   next; a mode-2 write is untested and does not fix the depth mismatch.
   **Correction:** viewport sizing is conditional on successful pass setup.
   `0x14024a9c0` builds size constants, not textures; actual colour resize uses
   the scale but depth resize does not. See
   [DEPTH_SCALE_RESULTS.md](analysis/DEPTH_SCALE_RESULTS.md).
2. **Option 2 Phase B test 1 DONE 2026-10-23 (restored):** the scale applied and the
   colour targets scaled, but the image was black. The captured HDR scene draw
   entries have no depth bound; static code shows native depth sizes mismatching
   reduced colour, which the engine can reject before binding. CAS was on, so
   fixing depth alone is not yet proven sufficient. See
   [scale-test-20261023/RESULTS.md](analysis/scale-test-20261023/RESULTS.md).
   **Offline follow-up DONE:** depth init `0x14024c340`, depth resize
   `0x140252210`, shared creation wrapper `0x140253410`, validator `0x1402439a0`.
   Evidence: `analysis/offline-depth/`; verifier 34 checks pass. Only fixed
   256×256 D24S8 appears in the reduced capture, not main scene depth.
   **Next:** design/test a selected scene-depth allocation+metadata fix for
   creation and resize, then request approval before another game test.
   No depth fix or setter change was made. Desktop repeat should use CAS off.
   **Phase A (offline) DONE 2026-10-23:** setter built and tested in the
   Proton harness, see [SCALE_SETTER.md](analysis/SCALE_SETTER.md). The headless
   test actually reached 1920×1080 (rather than the predicted 1920×1200).
   Original plan notes:
   **Option 2 (approved, needs game closed + backups): in-game render-scale test.**
   Add a minimal scale setter to the tested outer d3d11 chain-loader
   (`analysis/checks/d3d11_log_proxy.cpp`): module base + `0x177f1a0` → renderer;
   write float at `+0x80` (e.g. 0.75) only after verifying code bytes
   (`4c8b1520705301` at RVA `0x248179`, `f3410f598280000000` at RVA `0x2481b8`);
   do nothing on mismatch. Build and test in the isolated harness first. In game:
   back up and hash-check `d3d11.dll`, rename it to `d3d11_dlaa.dll`, install the
   setter as `d3d11.dll`; user re-applies resolution, plays briefly with AA off (F8);
   then restore and re-verify hashes. The AA mod will skip AA at reduced scale
   until patched (size gate) — expected.
3. Then the mod patch for FSR4 upscaling (unequal NGX create, native output, SRV
   redirect at bloom `68495C5B` / tone-map `2C76D68A`), building on the above.
4. **Research recorder:** [RESEARCH_RECORD.md](analysis/RESEARCH_RECORD.md) written by
   subagent `b06f5fc8-07c4-40ee-85dc-978d8cb1c010` (Claude Haiku 5.5): 39-finding
   ledger, open questions, 12 recorded doc conflicts, safety log, DLSS 5 NR
   applicability. Re-run it after each milestone so the record stays current. The research applies to DLSS 5 NR
   too (same inputs: colour, depth, pixel-space MVs, jitter, render/output sizes,
   post-AA handoff, render-scale mechanism).
5. DLSS 5 NR still needs a legitimately obtained `nvngx_dlssnr.dll`; afmf-linux frame
   generation later. No FPS uncap or dynamic resolution in this milestone.

## Current safe state at end of session

- Installed game files: all DLLs and INIs match recorded hashes; `NIER_DLAA.ini`
  `[Debug] Enabled=0` (restored, hash-verified). No logger or setter installed.
- `Graphic.ini` restored to `\\.\DISPLAY1` (harmless; old Default/LAY1 version backed up
  at `backups/graphicini-fix-20261019T211032Z/`).
- Display fix: Dell (DP-2) set as Xwayland primary; persisted in
  `~/.config/hypr/modules/monitors.lua` (backup `backups/hypr-primary-20261019/`).
  Dotfiles copy not yet mirrored.
- SteamStub-unpacked exe exists only as an analysis copy:
  `analysis/input/NieRAutomata_win10.unpacked.exe` (never run, never shared).

## Tooling for resume

- REA CLI: `/home/suraj/.npm/_npx/af752b90495482d7/node_modules/.bin/rea` (v6.4.0). Use with env:
  `GHIDRA_INSTALL_DIR=/opt/ghidra JAVA_HOME=/usr/lib/jvm/java-21-openjdk TMPDIR=<analysis/runtime/tmp> HOME=<analysis/runtime/home>`.
  Ghidra snapshots: original `analysis/snapshots/NIER_DLAA_1.1.json` remains
  unchanged; use `analysis/snapshots/NIER_DLAA_upscaling_offline_20261019.json`
  with `--snapshot` for the seven additional offline queries. Camera continuation
  uses `analysis/offline-camera/NIER_DLAA_camera_snapshot.json`; its evidence index
  is `analysis/offline-camera/evidence-index.json`. Motion continuation snapshot:
  `analysis/offline-motion/NIER_DLAA_motion_snapshot.json`; shader extraction and
  validation manifests are beside it. See `analysis/MOTION_VECTOR_RESULTS.md`.
  The MCP REA server is *not* configured for Ghidra (process launched without env); use the CLI.
- Cross-compile Windows DLLs: `x86_64-w64-mingw32-g++` (with `-static -static-libgcc -static-libstdc++`).
- FSR4 bridge source (open): `upstream/Nier-FSR4` (commit `32667ad4…`).
- NIER_DLAA proxy (closed): `upstream/Nier-FSR4/third_party/NIER_DLAA/d3d11.dll` + copy at `analysis/input/NIER_DLAA_1.1.dll`.
- Key evidence: `analysis/evidence/*.json`, `analysis/FSR4_RESULTS.md`, `analysis/VISUAL_STACK.md`, `analysis/NATIVE_AA_INSTALL.md`.

## Safety invariants

- Never delete user data without asking. Quarantine (move) is the rollback mechanism.
- Preserve the working FSR4+WAX+LodMod state; only swap DLLs temporarily and restore (as done for instrumentation).
- Do not touch saves. WAX `auto_purge_inventory` stays `false`.
- Do not source `nvngx_dlssnr.dll` from redistribution — user must own a shipping game (NBA 2K27 / Hogwarts Legacy / Where Winds Meet).
