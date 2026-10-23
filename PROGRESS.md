# NieR:Automata Rendering — Progress & Resume

Last updated: 2026-10-23 (depth-scale investigation and corrected test evidence).
The user-approved scale-only game test ran on 2026-10-23 and was restored; the
current continuation is offline only. Historical sections below retain their
original scope unless explicitly superseded.

**Current user constraint:** do not launch NieR, attach to live game processes,
replace installed DLLs, or change game configs/saves without fresh approval.
The user approved only offline evidence files and report corrections for this
continuation. The next game test is deferred until they are at the desktop.

## Goal and order

1. **FSR4 native AA** — DONE, working.
2. **Resolution upscaling** — IN PROGRESS. In-game frame dumps show a clean post-AA handoff (two scene readers; HUD already native). Scene-domain scaling is the remaining hard part.
3. **DLSS 5 NR** — BLOCKED on `nvngx_dlssnr.dll` (only ships with NBA 2K27; user doesn't own it).
4. **Frame generation** — afmf-linux installed & verified, not yet tested in-game.

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
