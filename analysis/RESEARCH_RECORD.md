# NieRAutomata rendering: consolidated research record

Compiled from the workspace documents as they stood when this record was written.
[PROGRESS.md](../PROGRESS.md) was last updated 2026-10-19. Dates are copied from
the docs. Folder labels such as `20261018T201659Z` are copied as written; no time
zone conversion was done.

---

## 1. Purpose and how to use this record

This record is an index and ledger. It does not replace the topic documents.
Each row points to the document that holds the detail. Read the topic document
before you rely on a finding.

Goal order, from [PROGRESS.md](../PROGRESS.md):

1. FSR4 native anti-aliasing: **done**, working in game.
2. Render-resolution upscaling: **in progress**, the main open problem.
3. DLSS 5 NR: **blocked** on `nvngx_dlssnr.dll`, which the project does not have.
4. Frame generation (afmf-linux): **installed, dormant, untested in game**.

Status labels used in the ledger:

| Label | Meaning |
| --- | --- |
| proven | Seen in a live game run, or confirmed by a hash/check on the exact artifact. Scope is stated in the caveat column. |
| observed in synthetic test | Seen in an isolated, synthetic Proton or GPU harness. Not game integration. |
| static-only inference | Read from decompilation, disassembly or source. Not executed. |
| open | Not resolved. Next step is in section 4. |

Rule used throughout: an inference is never written as a fact. Where docs
disagree, both versions are recorded and the conflict is flagged in section 4.

---

## 2. Timeline of milestones

Dates are as recorded in the docs. Where a doc gives no date, that is stated.

| Date (as recorded) | Milestone | Source |
| --- | --- | --- |
| 2026-09-06 | Old game logs show Special K 25.12.2.5 ran as `d3d11.dll`. Historical only. | [VISUAL_STACK.md](VISUAL_STACK.md) |
| Folder label 20261018T201659Z | Native-AA backup taken before install. | [../backups/native-aa-20261018T201659Z/manifest.json](../backups/native-aa-20261018T201659Z/manifest.json) |
| 2026-10-18 | Native AA installed: 8 files added, no existing file overwritten. GE-Proton11-7 registered for Steam. | [NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md) |
| 2026-10-18 (checked UTC 20:25:25) | Live check: FSR provider 4.1.1 context at 3440x1440; evaluations logged through frame 14400 (log time 21:25:06). | [evidence/first-live-game-verification.json](evidence/first-live-game-verification.json) |
| Folder label 20261018T210248Z | Visual-stack backup before LodMod install. | [../backups/visual-stack-20261018T210248Z/manifest.json](../backups/visual-stack-20261018T210248Z/manifest.json) |
| 2026-10-18 | LodMod 0.77.5 added as `dinput8.dll` with `LodMod.ini`. Special K isolated probes stalled; Special K not installed. | [VISUAL_STACK.md](VISUAL_STACK.md) |
| Folder label 20261018T215003Z | Special K crash files quarantined. | [../quarantine/specialk-crash-20261018T215003Z](../quarantine/specialk-crash-20261018T215003Z) |
| Folder label 20261018T222240Z | WAX backup, before the exe swap. | [../backups/wax-20261018T222240Z](../backups/wax-20261018T222240Z) |
| 2026-10-18 22:27 | Game switched to the Windows 10 exe (needed for WAX). Compat exe quarantined. | [PROGRESS.md](../PROGRESS.md), [evidence/win10-exe-swap.json](evidence/win10-exe-swap.json) |
| 2026-10-18 (later) | WAX installed as `dxgi.dll`: 289 textures reported active. | [PROGRESS.md](../PROGRESS.md) |
| 2026-10-19 (time not recorded) | Display regression diagnosed and fixed (X primary output set; persisted in Hyprland `monitors.lua`). | [PROGRESS.md](../PROGRESS.md) |
| Folder label 20261019T203031Z | First frame-dump INI backup. | [../backups/framedump-capture-20261019T203031Z](../backups/framedump-capture-20261019T203031Z) |
| Folder label 20261019T211032Z | `Graphic.ini` backup for the display fix. | [../backups/graphicini-fix-20261019T211032Z](../backups/graphicini-fix-20261019T211032Z) |
| Folder label 20261019T213846Z | Second frame-dump INI backup. | [../backups/framedump-capture-20261019T213846Z](../backups/framedump-capture-20261019T213846Z) |
| 2026-10-19 22:43:09 and 22:43:39 (file names) | Two in-game frame dumps at 3440x1440. | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) |
| 2026-10-19 (no time) | Offline work: camera RE, dimension source, motion-vector shaders, routing mock, logger correction, synthetic GPU tests (64 evaluations), scene inventory, SteamStub unpack, render-scale RE. | [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md), [ROUTING_RESULTS.md](ROUTING_RESULTS.md), [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md), [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) |
| Undated in docs | Phase 2 native analysis and phase 3 synthetic FSR4.1.1 tests. | [RESULTS.md](RESULTS.md), [FSR4_RESULTS.md](FSR4_RESULTS.md) |

---

## 3. Findings ledger

Each row is one finding. Status uses the labels in section 1.

| ID | Finding | Status | Evidence | Caveats |
| --- | --- | --- | --- | --- |
| F01 | FSR4 native AA works in game at 3440x1440, through the NIER_DLAA proxy and the open FSR4 bridge. | proven (live run, 2026-10-18) | [evidence/first-live-game-verification.json](evidence/first-live-game-verification.json); [NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md); [FSR4_RESULTS.md](FSR4_RESULTS.md) | Visual and temporal quality not independently verified. Not re-tested in this record. Config-change-only check. |
| F02 | Live provider is 4.1.1, not an older fallback. | proven (live log) | [evidence/first-live-game-verification.json](evidence/first-live-game-verification.json) (`provider 4.1.1` line) | Synthetic runs also checked the provider with a strict verifier. |
| F03 | The bridge accepts unequal render and output sizes (`Width/Height` separate from `OutWidth/OutHeight`). | observed in synthetic test; also static-only for the code path | [FSR4_RESULTS.md](FSR4_RESULTS.md) (320x180 to 640x360, provider 4.1.1, 16 frames); [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md) (1720x720 to 3440x1440, 32 evaluations); [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (source lines 1510-1524, 716-817, 1172-1196) | Synthetic inputs. Not the game path. `Bridge::Ensure` creates shared textures from supplied descriptors, so changing OutWidth alone does not enlarge a texture. |
| F04 | Closed proxy: the native AA dispatch sets render and output width/height to the same scene size and requests flags 0x43. | static-only inference | [evidence/dlaa-render-dispatch-function.json](evidence/dlaa-render-dispatch-function.json) (`ev_0786e85e94c2c3a424ad0b893af1ab09c2a6595c68c8c922169160cf17524326`); [RESULTS.md](RESULTS.md) | Ghidra pseudocode, not executed. Flow and indirect-call limits apply. |
| F05 | Closed proxy copy-back: after evaluation it copies the mod Output into the scene texture with `CopyResource` (context slot 47, offset 0x178). | static-only inference for the code; observed in-game for the copy | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (point 3); [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) (`#5798` `CopyResource` copy-back in dump 1) | The copy itself is seen in the dump. Its operand sizes are static. |
| F06 | Equal-size blocker: `CopyResource` needs identical dimensions and does not stretch, so native Output cannot be copied into a reduced scene. | static-only inference (API rule cited from Microsoft docs, not re-checked) | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (point 4) | Status conflict with F12. See section 4. |
| F07 | Bridge already has a second copy-back: shared output to the supplied NGX Output. | static-only inference | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (point 3, bridge line 1297) | Upstream commit `32667ad4cb579f83798e78fe5df1589c731d010c`, as recorded. Not re-checked here. |
| F08 | Allocator `0x180017e20` gives all mod targets (motion vectors, depth, Output, auxiliary) the same scene width and height. | static-only inference | [offline-camera/](offline-camera/); [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (allocator section) | Evidence in `offline-dimensions/` and `offline-framedump/` snapshots. Evidence IDs are as given in the docs. |
| F09 | Pre-dispatch gate `0x1800173c0` compares PS SRV slot 0 texture size with camera W/H. Shrinking only the scene would skip AA. | static-only inference | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md); [evidence/upscale-dispatch-caller-function.json](evidence/upscale-dispatch-caller-function.json) (`ev_92cc16a9eb1233c7e3bae75b13134fe7ec6c0d3a8f44e96139faa1515e2e31bb`) | Not executed. |
| F10 | Camera W/H come from the swap chain, not the scene. The proxy calls `IDXGISwapChain::GetDesc` (slot 12) on entry to its hooked Present (slot 8), then forwards Present. | static-only inference (see caveat) | [ROUTING_RESULTS.md](ROUTING_RESULTS.md) (section 1); [offline-dimensions/](offline-dimensions/) (`factory-create-function.json`, `factory2-create-function.json`, `swapchain-install-function.json`); [offline-camera/dimension-entry-function.json](offline-camera/dimension-entry-function.json) | [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md) calls the setter caller identity "supported inference, not established". ResizeBuffers internals and multi-swap-chain cases not traced. Status conflict noted in section 4. |
| F11 | Camera buffer layout: W/H at +0x08/+0x0c; generated pixel jitter at +0x10/+0x14; 32-entry Halton(2,3)-style sequence; projection mutation `(2*jx/W, -2*jy/H)`; NGX jitter scaled by scene/camera size ratio. | static-only inference | [offline-camera/camera-getter-function.json](offline-camera/camera-getter-function.json) (`ev_2a9874c4bc21a9628812fa17232d11d92c9b64c6888b0c20ff823f9226a4b667`); [offline-camera/camera-producer-180015703.json](offline-camera/camera-producer-180015703.json) (`ev_5c9aa3a4d12bd56f294f2967d022a2c4bfbef17ca89eae998e164a628a32f866`); [offline-camera/detail-180015be0.json](offline-camera/detail-180015be0.json) (`ev_5505a12e4771876e0331e0ff1282f0bacd5cfc4f4a4ecf87d11c408d086994a4`); [offline-camera/evidence-index.json](offline-camera/evidence-index.json) | Game timing of jitter not validated. Sign helper `0x180019c20` is not the jitter generator. Compute state capture is not proof of full graphics-state preservation. |
| F12 | Frame dump: after the AA copy-back, exactly two passes read the scene, both at PS SRV slot 0: bloom downsample `68495C5BDCDE8322` (1720x720) and tone-map `2C76D68A52500A65` (3440x1440). Nothing writes the scene again. | proven (in-game dump, 2 frames) | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md); [framedump-capture/NIER_DLAA_frame_20261019_224309_810.txt](framedump-capture/NIER_DLAA_frame_20261019_224309_810.txt); [framedump-capture/NIER_DLAA_frame_20261019_224339_508.txt](framedump-capture/NIER_DLAA_frame_20261019_224339_508.txt) | Counts only slot 0. Slots 4-14 are open (F17). "Clean handoff" is the doc's reading. Two frames only. |
| F13 | HUD and final present work on native intermediates, not the scene. HUD is about 50 draws (`A1B77252`); final pass `7A49D93C` writes the 3440x1440 RGBA8 swap chain. | proven (in-game dump, 2 frames) | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) (annotated chain) | Same dumps as F12. Whether HUD needs anything from render resolution is untested. |
| F14 | A replacement route is proposed: give the two scene readers (F12) the native FSR output as their slot-0 SRV, instead of copying back into a smaller scene. | static-only inference (proposal) | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) ("practical options") | Not implemented or tested. Doc says "not decided". Status conflict with F06 noted in section 4. |
| F15 | Scene-domain inventory (dumps): 14 native 3440x1440 game targets, 5 half-res 1720x720, 1 quarter 860x360, 2 screen-tile compute buffers. Shadow, environment and LUT resources are fixed-size. | proven (in-game dumps, parsed offline) | [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md) | Count differs from F19 (scope differs). See section 4. |
| F16 | Viewport and draw distribution before AA: native viewport about 1560-1680 draws; half-res 74-128; quarter 1. | proven (in-game dumps) | [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md) | Draw counts differ across docs. See section 4. |
| F17 | Global texture block: post-AA draws and most scene passes have `T3841`, `T2781` (scene copy), `T2787` (linear depth) bound at PS SRV slots 4-14. | proven that bound (in-game dumps); open whether sampled | [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md) ("Global texture block") | Open: whether post-AA shaders sample these, and by UV or pixel coordinates. Affects F12. |
| F18 | Motion-vector units: camera CS (`cs_5_0_0508b0`) and character PS (`ps_5_0_052590`) both output previous-minus-current NDC times `(W/2, -H/2)`. That is screen pixels, X right, Y down. | static-only inference for both shaders; observed in synthetic test for the CS | [offline-motion/shaders/cs_5_0_0508b0.asm](offline-motion/shaders/cs_5_0_0508b0.asm) (lines 20-43); [offline-motion/shaders/ps_5_0_052590.asm](offline-motion/shaders/ps_5_0_052590.asm) (lines 22-30); [offline-motion/motion-gpu-checked-validation.json](offline-motion/motion-gpu-checked-validation.json); [checks/motion_shader_probe.cpp](checks/motion_shader_probe.cpp) | Synthetic CS only: 10 cases in R16G16_FLOAT and 10 in R32G32_FLOAT. The PS was not executed. Bone data, timing and temporal quality are not validated. |
| F19 | Object motion replaces the camera vector where the object texture W > 0.5, and uses camera motion otherwise. It does not add the two. | static-only inference | [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md) | Exact W = 0.5 selects camera motion. Coverage effects not tested. |
| F20 | Motion vectors are passed to the bridge unchanged, with scale 1.0 by default. The AMD manual cited in MOTION_VECTOR_RESULTS.md gives the same pixel, current-to-previous convention. | static-only inference (bridge); external doc cited, not re-checked | [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md); `upstream/Nier-FSR4/src/nier_fsr4.cpp` lines 1206-1213, 1243-1246 | No blanket W/H multiplier should be added. Reduced-resolution grids must match before the merge. |
| F21 | NGX flags: production FSR translation is 0x21; the test's DebugChecking adds 0x80 (0xa1). The DLSS-named flag 0x43 selects render-resolution motion vectors, not jitter cancellation. | proven for the logged values (in-game log line `flags 0x21 (DLSS flags 0x43)`); flag meaning static-only | [evidence/first-live-game-verification.json](evidence/first-live-game-verification.json) (verbatim log line); [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md) | Bit translation is not a unit conversion. |
| F22 | Logger was wrong when first built: RSSetViewports is slot 44, not 40; it loaded system D3D11 directly; export parity was incomplete. | proven (source corrected and reviewed) | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (point 5); [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md) | The old DLL `build/d3d11_log_proxy.dll` still exists and must not be used. |
| F23 | Logger after correction: 51 export names and ordinals match; immediate and deferred context tests pass; 141-event chain trace verified. | observed in synthetic test | [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md); [offline-routing/trace-verification.json](offline-routing/trace-verification.json); [offline-routing/chain-checked-validation.json](offline-routing/chain-checked-validation.json) | Not deployed. Probe calls the bridge NGX exports directly, so the closed mod's game path was not exercised. Logger on hold. |
| F24 | Synthetic GPU results: native 3440x1440 and 1720x720 to 3440x1440 with FSR4.1.1, direct and through the logger-to-renamed-AA-proxy chain. 64 evaluations, zero failures. | observed in synthetic test | [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md); [isolated-gpu-3440-20261019/](isolated-gpu-3440-20261019/) (`verification.json`, `logger-verification.json`); [evidence/fsr4-validation-summary.json](evidence/fsr4-validation-summary.json) | Zero motion and jitter, constant depth. No timing, power, memory or quality benchmark. |
| F25 | Mock route reduced, to native, to native post works with nearest-neighbour upscaling (not FSR), both direct and through the logger chain. 10 checks each. | observed in synthetic test (Proton/DXVK on Linux, not native Windows D3D11) | [ROUTING_RESULTS.md](ROUTING_RESULTS.md); [offline-routing/baseline-checked-validation.json](offline-routing/baseline-checked-validation.json); [offline-routing/chain-checked-validation.json](offline-routing/chain-checked-validation.json) | Does not show the game's post or HUD consumers. Does not show the closed-mod copy-back works. |
| F26 | Engine built-in render scale: renderer float at `renderer+0x80`, written as 1.0 (`0x3f800000`) in the renderer initialiser. The creator `0x140773cd0` scales 40 targets via a per-target flag. The other 28 stay native. | static-only inference (decompile of unpacked workspace copy) | [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md); [offline-gameexe/rt-creator-function.json](offline-gameexe/rt-creator-function.json) (`ev_c73715f51361503014a9def6bcc038ddc2381514347af86b95a5dba0780b4188`); [offline-gameexe/rt-creator-function.decoded.c](offline-gameexe/rt-creator-function.decoded.c) | No runtime setter found. Not run. Scale 0.75 and similar values are proposals, not tested. |
| F27 | Per-target flag table: scaled (40): scene `g_TargetTexture_Origin[0..2]`, velocity, linear depth, Hi-Z, AO, SSSS, shadow receive, scene copy, bloom, DOF, SMAA, screenshot. Native (28): back-buffer intermediates, CAS result, UI, fixed-size 256/512/1024 textures, shadow cast, Enlighten. | static-only inference | [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) (scaled and native lists) | Consistent with the dumps' scene, depth, AO, velocity and bloom behaviour, and with HUD being native. Counts differ from F15 (see section 4). |
| F28 | Open: whether scene passes take viewports and screen-size constants from the scaled size or the screen size. The dumps cannot tell, because at scale 1.0 they are equal. | open | [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) ("Open question") | Needs a non-1.0 test, which needs approval (section 4). |
| F29 | Camera and motion grids must follow render resolution together with the scene. Mixed-grid motion fields cannot be fixed by one global scale. | static-only inference | [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md) ("Implication"); [ROUTING_RESULTS.md](ROUTING_RESULTS.md) | Design guidance from the doc. Not tested. |
| F30 | SteamStub unpack, offline on a workspace copy only. Steamless v3.1.0.5; unpacked `.text` entropy 6.51, 15,989 prologues, original entry `0x1409d5a24`. | proven (artifact produced, hashed) | [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) (binary section); [offline-unpack/](offline-unpack/); [offline-gameexe/unpacked_snapshot.json](offline-gameexe/unpacked_snapshot.json) | Analysis copy only. Never run, installed or shared. Steamless licence not recorded. |
| F31 | Display regression root cause: the Win10 exe picks its monitor by name (`DisplayConfigGetDeviceInfo`). Under Xwayland, both monitors show as `Default_Monitor`, so the game took `DISPLAY1`, which was the ViewSonic with no X primary. Setting DP-2 as X primary makes `DISPLAY1` the Dell 3440x1440. | observed in synthetic test (diagnostic probe in private prefix) | [PROGRESS.md](../PROGRESS.md) (display section); [checks/display_probe.cpp](checks/display_probe.cpp); [offline-display/](offline-display/) (`logs/`, `logs-after-primary/`) | Probe is a diagnostic program, not the game. Caused by no X primary, not by the `[Debug]` INI edit, monitor layout, Motion Blur or Graphic.ini (ruled out per PROGRESS). |
| F32 | Display fix is persistent: `xrandr --output DP-2 --primary` applied from `~/.config/hypr/modules/monitors.lua` on `hyprland.start` and `monitor.added`, with a 20 s retry. | proven (local config checks recorded in PROGRESS; luac, sh syntax, `hyprctl reload`, `configerrors` clean) | [PROGRESS.md](../PROGRESS.md); [../backups/hypr-primary-20261019/monitors.lua](../backups/hypr-primary-20261019/monitors.lua) | PROGRESS does not say whether the game was re-checked in its menu after the fix. Dotfiles copy not updated. |
| F33 | Visual stack: LodMod 0.77.5 (`dinput8.dll`) and WAX texture injection (`dxgi.dll`, 289 textures reported active) coexist with the FSR4 proxy. | proven as installed state (2026-10-18 record); in-game visuals not validated | [VISUAL_STACK.md](VISUAL_STACK.md); [PROGRESS.md](../PROGRESS.md); [evidence/visual-stack-final-verification.json](evidence/visual-stack-final-verification.json) | LodMod starting values are a profiling choice, not a measured optimum. WAX gameplay patches off. |
| F34 | Special K as `dxgi.dll` stalls in isolated synthetic prefixes. Real-game Special K not tested. WAX chosen instead. | observed in synthetic test (stall); real-game case open | [VISUAL_STACK.md](VISUAL_STACK.md); [evidence/visual-stack-probe-run/](evidence/visual-stack-probe-run/) | Special K is quarantined, not installed. Do not infer it can never work. |
| F35 | Object motion is active in game: 33345 character draws repeated and 600 motion-blur draws skipped in the last 600 presents. | proven (live log line) | [evidence/first-live-game-verification.json](evidence/first-live-game-verification.json) | Requires in-game Motion Blur On. Correctness of bone motion not validated. |
| F36 | Frame generation (afmf-linux v1.3.1) installed and dormant (`AFMF_ENABLE=1` to activate). | open (not tested in game) | [PROGRESS.md](../PROGRESS.md); [VISUAL_STACK.md](VISUAL_STACK.md) | "Installed and verified" in PROGRESS refers to install checks, not gameplay. See section 4. |
| F37 | DLSS 5 NR is blocked: `nvngx_dlssnr.dll` is not in the workspace. PROGRESS says it ships only with NBA 2K27, which the user does not own. No NVIDIA DLL is installed. | open (blocker) | [PROGRESS.md](../PROGRESS.md); [NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md) | Must come from a game the user owns. Never redistribute. Source of the DLL is in conflict across docs (section 4). |
| F38 | Bundled proxy and patcher: the original NIER_DLAA 1.1 (SHA-256 `f1c77c58...`) patches to the pinned upstream hash `3d628eb5...` with the exact 41-byte stub. A one-byte change is rejected. | proven (static patcher checks, run in a temp workspace) | [../README.md](../README.md) ("Checks performed: passed" section) | Patcher checks only. Not a Windows or GPU test. |
| F39 | AMD runtime provenance: `amd_fidelityfx_loader_dx12.dll` and `amd_fidelityfx_upscaler_dx12.dll` from official SDK 2.3.0 signedbin match the bridge's pinned hashes. | proven (hash match) | [FSR4_RESULTS.md](FSR4_RESULTS.md); [evidence/amd-runtime-provenance.json](evidence/amd-runtime-provenance.json) | Authenticode trust chain not checked. |

---

## 4. Open questions, conflicts and blockers

### 4a. Open questions

| # | Question | What would resolve it |
| --- | --- | --- |
| Q1 | Do post-AA shaders sample the global slots 4-14 (scene copy `T2781`, linear depth `T2787`, `T3841`), and by UV or pixel coordinates? | Shader resource declarations from the mod's `DumpShaders` option in one more INI-only capture, or DXBC matching offline. Needs your approval for any capture (section 5). |
| Q2 | Do scene passes take viewports and size constants from the scaled size or the screen size? | Decompile the viewport and constant setup (`0x1402f3e60` and callers), then a non-1.0 scale test in game. Needs approval. |
| Q3 | Which of the 40 scaled targets are created with the scaled size only through the creator, and do all of them match the dump sizes after scaling? | Repeat the dump at a non-1.0 scale. Needs approval. |
| Q4 | Is the engine's native CAS result the upscale step after a reduced render? | Static trace of CAS input and output sizes, then test. Inference only so far. |
| Q5 | Where does the closed mod's game-specific dispatch differ from the synthetic probe? | Game capture of the AA path with the logger or frame dump. Needs approval. |
| Q6 | Does the HUD depend on any render-resolution value? | Test after Q2, with HUD sharpness checks. |
| Q7 | Temporal quality, reduced-resolution motion-vector correctness, bone and camera motion, and GPU headroom at the 60 FPS cap. | Game tests after the native handoff is designed. Needs approval. |
| Q8 | Whether the native AA copy-back can be replaced by a native-output route without patching the closed binary. | Design decision. See F14 and F06. |

### 4b. Blockers

| Blocker | What is blocked | To unblock |
| --- | --- | --- |
| `nvngx_dlssnr.dll` not available | DLSS 5 NR work (goal 3) | User supplies a file from a game they own. Never redistribute. |
| Live game validation not authorised | Any in-game capture, scale test, or install change | Explicit user approval, per run. |
| Equal-size copy-back in the closed proxy | Render-resolution scene (F06) | Native-output route (F14) or patched/replacement AA path. Design decision. |

### 4c. Conflicts between documents

Both versions are recorded. None are resolved here.

| # | Topic | Version A | Version B | Note |
| --- | --- | --- | --- | --- |
| C1 | Status of the copy-back blocker | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) and [PROGRESS.md](../PROGRESS.md) (earlier section) call it a blocker. | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) says "the earlier blocker has a concrete solution"; PROGRESS says it "can be avoided". | B is an untested proposal (F14). Treat the blocker as open. |
| C2 | "Exactly two readers" of the scene | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) and PROGRESS: exactly two scene readers after copy-back. | [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md): post-AA draws have the scene copy and other targets bound at slots 4-14; whether they are read is open. | Not contradictory if only slot 0 is meant. Scope must be stated (Q1). |
| C3 | Scene draw counts | [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md): about 950-1100 scene draws. | [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md): about 1360 main-scene draws; about 1560-1680 native-viewport draws; about 980 reads of one mask. | Different definitions over the same dumps. Not reconciled. |
| C4 | Count of screen-sized targets | [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md): 14 native, 5 half, 1 quarter (observed in frame). | [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md): 40 scaled and 28 native (creator-level). | Different scope: observed in frame versus every registered target. Not a contradiction, but the numbers do not match. |
| C5 | Certainty of camera-dimension source | [ROUTING_RESULTS.md](ROUTING_RESULTS.md): states the GetDesc-at-Present source as a static finding. | [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md): setter caller identity is "supported inference, not established". | Recorded as static-only (F10). |
| C6 | Frame generation status | [PROGRESS.md](../PROGRESS.md): "installed & verified". | [VISUAL_STACK.md](VISUAL_STACK.md) and PROGRESS elsewhere: "not tested in game". | "Verified" refers to install checks. Gameplay untested. |
| C7 | Games that ship `nvngx_dlssnr.dll` | [PROGRESS.md](../PROGRESS.md) goal list: only NBA 2K27. | [README.md](../README.md) and PROGRESS safety section: NBA 2K27, Hogwarts Legacy, Where Winds Meet. | Not resolved. Check the user's own sources before relying on either list. |
| C8 | GE-Proton11-7 in Steam | [FSR4_RESULTS.md](FSR4_RESULTS.md): runner not installed into Steam's compat tools (phase 3). | [NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md): symlink created in `compatibilitytools.d`. | Later state wins: symlink registered. Not a true conflict. |
| C9 | Game executable hashes | [VISUAL_STACK.md](VISUAL_STACK.md): historical exe SHA-256 `042e9fef...`, size 17,786,752. | [evidence/win10-exe-swap.json](evidence/win10-exe-swap.json): `042e9fef...` is the pre-swap compat exe; the Win10 exe is recorded by SHA-1 `420cbab7...` only. [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) gives Win10 SHA-256 `5171bed0...`. | Workspace copy `input/NieRAutomata_win10.exe` matches SHA-1 `420cbab7...` and SHA-256 `5171bed0...` (checked for this record). The installed exe's SHA-256 is not recorded anywhere other than GAME_RENDER_SCALE. |
| C10 | Render-scale doc wording | [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) body: flag table "confirmed by Ghidra decompilation". | Same doc, "Next": "Confirm the flag table ... with the Ghidra decompile." | Parent is editing this file. Record the body as static-only until the next step is done. |
| C11 | Motion-vector unit status | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) (earlier): unit question open. | [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md): resolved for both shaders (static, plus synthetic CS). | Later doc supersedes. Game timing still open. |
| C12 | Logger status | [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md): original logger wrong; do not reuse. | [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md): corrected source passes isolated tests. The old DLL is still on disk. | Corrected source is the one to use. Logger is on hold. |

### 4d. Gaps and what I could not verify

- I did not run the game, Proton, Wine, Ghidra, builds or any network fetch.
- I did not read the live game install, Hyprland config or Steam config outside the
  workspace. Restore claims for those are taken from the docs.
- The frame-dump INI restore is stated in [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) and
  PROGRESS as "restored and hash-verified". The workspace has the two pre-capture INI
  backups, which are identical and show `[Debug] Enabled=0`. No restore manifest is in the
  workspace. I did not verify the live file.
- Evidence IDs abbreviated in the docs (for example `ev_7290b085...`) are cited as
  file paths only. I checked that the full IDs exist in the named JSON files where
  the full ID was given.
- No git state was checked (no git commands were allowed).
- The external AMD and Microsoft citations were not re-fetched.
- WAX rollback steps are not written out in any doc. PROGRESS only says "backups at each phase".
- The `Graphic.ini` change and restore are described only as "restore was a no-op". The docs do not say whether a `Graphic.ini` edit was ever made.

---

## 5. Safety and reversibility record

Status is as recorded in the docs. Nothing in this table was executed by this record.

| # | Change | Where | Backup or quarantine | Restore path (from docs) | Restore status |
| --- | --- | --- | --- | --- | --- |
| S1 | Native AA: 8 files added (`d3d11.dll` proxy, `NIER_DLAA.ini`, `NIER_FSR4.dll`, `NIER_FSR4.ini`, two AMD DLLs, licence, README). | Game root | [../backups/native-aa-20261018T201659Z](../backups/native-aa-20261018T201659Z) (saves, game config, Steam appuserdata; `manifest.json` with SHA-256) | Move the 8 files to quarantine; select previous runner; restore original launch options. Do not restore old saves over newer ones. | In effect. No restore run. |
| S2 | GE-Proton11-7 directory symlink. | `~/.local/share/Steam/compatibilitytools.d/` (outside workspace) | Not applicable (new symlink). Runner stays at `analysis/runners/GE-Proton11-7-x86_64`. | Remove the symlink; do not move or delete the runner while it is registered. | In effect. |
| S3 | Steam launch options: `WINEDLLOVERRIDES="d3d11=n,b;dinput8=n,b;dxgi=n,b" mangohud gamemoderun %command%`. | Steam UI (not VDF-edited by the agent) | Original options recorded in [NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md). | Restore original `mangohud gamemoderun %command%`, then remove overrides. | In effect. |
| S4 | LodMod: `dinput8.dll` and `LodMod.ini` added; settings changed (LODMultiplier 10, ShadowResolution 4096, ShadowDistanceMinimum 35). | Game root | [../backups/visual-stack-20261018T210248Z](../backups/visual-stack-20261018T210248Z) (nine files, including game config) | With the game closed, move both files to quarantine; remove the `dinput8` override. | In effect. |
| S5 | WAX: `dxgi.dll` added; texture pack in WAX directory; WAX config (gameplay patches off). | Game root and WAX directory | [../backups/wax-20261018T222240Z](../backups/wax-20261018T222240Z) (saves, game config) | Not written in any doc. Gap. | In effect. Restore steps need writing. |
| S6 | Windows 10 exe installed in place of the Windows 7/8 compat exe (2026-10-18 22:27). | Game root | Compat exe moved to [../quarantine/compat-exe-20261018T222737Z](../quarantine/compat-exe-20261018T222737Z) and copied to [../backups/win10-exe-swap-20261018T222716Z](../backups/win10-exe-swap-20261018T222716Z) (`NieRAutomata.exe.compat`, SHA-256 `042e9fef...`). | Steam "verify integrity" restores the Win7 compat scripts. Re-quarantine if it does. Restoring the compat exe is documented only as the backup copy. | In effect. Win10 exe is installed. |
| S7 | OS-verification scripts moved out of the game. | Game root | [../quarantine/osverification-20261018T223055Z](../quarantine/osverification-20261018T223055Z) (`NieRAutomataCompat.exe`, `win10setup.bat`, `win8_7_setup.bat`, `installation_os_check.vdf`) | Re-quarantine after any Steam verify. | In effect. |
| S8 | Special K: quarantined, not installed. | Quarantine | [../quarantine/specialk-crash-20261018T215003Z](../quarantine/specialk-crash-20261018T215003Z) | Not applicable. | Not installed. |
| S9 | Instrumentation mod DLLs: quarantined. | Quarantine | [../quarantine/instrumentation-20261018T225015Z](../quarantine/instrumentation-20261018T225015Z) | Not applicable. | Quarantined. |
| S10 | Frame-dump: `NIER_DLAA.ini` `[Debug] Enabled` temporarily set to 1, F10 captures. | Game root INI | [../backups/framedump-capture-20261019T203031Z](../backups/framedump-capture-20261019T203031Z) (INI; `d3d11.dll` SHA-256 `3d628eb5...`) and [../backups/framedump-capture-20261019T213846Z](../backups/framedump-capture-20261019T213846Z) (INI). Both show `Enabled=0`. | Restore INI from backup and hash-check. | Recorded as restored and hash-verified in docs. Not re-verified here. |
| S11 | Display: `Graphic.ini` fix attempt. | Game config | [../backups/graphicini-fix-20261019T211032Z](../backups/graphicini-fix-20261019T211032Z) (`Graphic.ini.Default-LAY1`). | Docs say restore was a no-op because `\\.\DISPLAY1` was the ViewSonic. | Docs do not say whether any edit was made. Gap. |
| S12 | Desktop: X primary output set to DP-2 by `xrandr`, persisted in `~/.config/hypr/modules/monitors.lua`. | Desktop config (outside workspace) | [../backups/hypr-primary-20261019/monitors.lua](../backups/hypr-primary-20261019/monitors.lua) (SHA-256 `392d0bee...`). Dotfiles copy not changed. | Restore backup, or `xrandr --output HDMI-A-1 --primary` at runtime. | In effect. |
| S13 | Private test prefixes, caches and test data for the synthetic probes. | Workspace only | Kept in workspace (`runtime/`, `isolated-gpu-3440-20261019/`, `offline-unpack/`, etc.) | Delete only with approval. | Not game data. |
| S14 | Offline unpacked game exe, a workspace copy only. | `analysis/input/` and `analysis/offline-unpack/` | Original copy unchanged in game. | Not applicable. Never install or share. | Analysis only. |
| S15 | Logger and probe builds. | `analysis/build/` (workspace) | Old `build/d3d11_log_proxy.dll` left in place. | Not deployed. Do not use the old DLL. | Not deployed. |
| S16 | Upstream checkouts (`upstream/`). | Workspace | Clean at inspection, as recorded. | Not applicable. | Not edited. |

Items the docs say are not changed: saves, the Steam VDF files, the installed FSR4
and LodMod DLLs beyond the above, and NVAPI settings.

---

## 6. DLSS 5 NR applicability

Rules for this section:

- "Project evidence" means what the docs show. It is labelled with the status from
  section 3.
- "Assumption about NR" is not from the project. It must be checked against the
  user's own legal copy of `nvngx_dlssnr.dll` and its NGX documentation. No DLSS 5 NR
  API detail is stated here. None is known to this record.
- `nvngx_dlssnr.dll` is not available in the workspace. It must come from a game the
  user owns. Never redistribute it.

### 6a. Carry-over per finding

| Finding | Project evidence (status) | How it might carry over to DLSS 5 NR | Assumption or unknown |
| --- | --- | --- | --- |
| F01, F03 (AA path, unequal sizes) | FSR4 bridge handles unequal sizes in synthetic tests (observed). | The bridge is FSR-only. Its NGX-style interface may be a reusable pattern. | Whether NR accepts unequal render and output sizes in the same way is unknown. |
| F04, F05, F06, F07 (dispatch, copy-back) | Static, plus copy seen in dumps. | The equal-size copy-back is the closed FSR wrapper's behaviour. It applies to NR only if the same wrapper pattern is reused. | Assumption. The copy-back is not part of any NR interface known to this record. |
| F08, F09 (allocator, gate) | Static. | The gate keys on camera size. Any NR integration would need matching camera metadata. | Unknown. Whether NR has the same gate is not known. |
| F10 (camera W/H from swap chain) | Static, with the caveat in C5. | Render-size metadata would come from the same camera source. | Assumption. NR's size inputs are not known to this record. |
| F11 (camera and jitter layout) | Static. Jitter generated in pixel space, scaled by size ratio, passed to the bridge. | Jitter is an input to any temporal upscaler. Its sign and units would matter for NR. | Assumption. NR's jitter convention is unknown. `JitterSign` is an INI setting in this project (default 1). |
| F12, F13, F14 (post-AA handoff, HUD, replacement route) | In-game dumps (proven). Proposal is untested (F14). | The handoff point is after the AA output. Any NR output would have to feed the same two readers. | Assumption. Whether NR output can be written to the same slot-0 SRV is untested. |
| F15, F16, F17 (scene inventory, draws, global slots) | In-game dumps. Global slots open (Q1). | Any NR path would need the same scene inventory to know which targets scale. | Unknown whether NR needs slots 4-14. |
| F18, F19, F20, F29 (motion-vector units, object motion, grids) | Static plus synthetic CS. Units are pixel, current-to-previous. | Motion vectors are an input to NR. Units, space, scale and jitter cancellation would all need checking. | Assumption. The FSR bridge's unit conventions are documented; NR's are not known to this record. The docs do not say NR uses the same convention. |
| F21 (NGX flags) | Logged values proven; flag meaning static. | Flags are per-API. Some bits map to FSR behaviour, not NR. | Assumption. NR flag meanings are unknown. |
| F22, F23, F24, F25 (logger, synthetic GPU, mock route) | Synthetic, FSR only, plus a nearest-neighbour mock. | Harness could be reused for NR inputs once NR is available. | Not done. NR has not been run. |
| F26, F27, F28 (render scale mechanism) | Static. Engine-side. | An engine-side scale would change every input before any upscaler sees it. This is independent of the upscaler backend. | Assumption. Whether NR accepts scaled inputs is not known. |
| F30 (SteamStub unpack) | Proven, workspace only. | Not relevant to NR except that the same analysis copy would be used. | None. |
| F31, F32 (display) | Observed in probe, persisted. | Display config may affect any NR mode, but nothing in docs links it to NR. | Unknown. |
| F33, F34 (visual stack, Special K) | Installed state and synthetic stalls. | Texture injection is independent of NR. Special K is not tested. | None for NR. |
| F35 (object motion) | In-game log, proven. | Character motion is an input to any temporal upscaler, NR included. | Assumption about NR's use of object motion. |
| F36 (frame generation) | Installed, dormant. | Frame generation is a separate stage. Not part of NR. | None. |
| F37 (NR blocked) | Blocker recorded. | NR path cannot start until the DLL is supplied. | Blocker. |
| F38, F39 (proxy patcher, AMD SDK hashes) | Static and hash checks. | Relevant only to the FSR path. | None for NR. |

### 6b. Inputs an NR integration would need, and project status

The list below is for planning. Each row says what the project has, not what NR needs.

| Input | Project status | Needed for NR? |
| --- | --- | --- |
| Colour (HDR scene) | In game: R11G11B10F scene, mod passes it to FSR. | Unknown. Assumption: yes. |
| Depth | In game: D24S8 and R32F linear depth. Mod generates depth for FSR. | Unknown. |
| Motion vectors (units, space, scale) | Pixel, current-to-previous. Scale 1.0 default in bridge. | Unknown. Check NR docs. |
| Jitter (sign, units, scaling) | Pixel-domain, sign setting, scaled by size ratio. | Unknown. Check NR docs. |
| Render and output sizes | Bridge supports unequal sizes (synthetic). Closed proxy uses equal sizes. | Unknown. Check NR docs. |
| Reset or history flag | FSR helper sets reset on frames 0 and 8 in the synthetic test. | Unknown. Check NR docs. |
| Post-AA handoff point | After the copy-back, before the two readers (F12). | Assumption: same point. |
| Render-scale mechanism | Engine-side float at `renderer+0x80`. Static. | Engine-side; independent of backend. |
| NGX interface | Closed mod RE: loader paths, parameter helper, flags 0x43, DLAA quality value 5. | Only the FSR-facing names are known. NR interface is unknown to this record. |

### 6c. Shortcuts that do not carry over

- The equal-size copy-back and the FSR flags (0x21 and 0x43) are FSR-specific
  observations. Do not treat them as NR requirements.
- The synthetic test results are FSR only.
- DLSS-named strings in the mod (`nvngx_dlss.dll`, `DLSS` section) are inherited from
  the original mod. The installed package has no NVIDIA DLL
  ([NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md)).

---

## 7. Document index

Root documents:

| Path | Description |
| --- | --- |
| [../PROGRESS.md](../PROGRESS.md) | Authoritative resume state: goals, installed state, backups, display fix, safety invariants. |
| [../README.md](../README.md) | Entry point: current status table, launch options, upstream pin, distribution boundary. |

Analysis topic documents:

| Path | Description |
| --- | --- |
| [GAME_RENDER_SCALE.md](GAME_RENDER_SCALE.md) | Engine built-in render scale at `renderer+0x80`, the per-target flag table, and the offline SteamStub unpack. |
| [UPSCALING_RESEARCH.md](UPSCALING_RESEARCH.md) | Engine-resolution upscaling decision: sizing, copy-back blocker, allocator, gate and logger correction. |
| [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md) | Offline results: logger correction, isolated synthetic GPU tests, camera and jitter findings, artifacts. |
| [MOTION_VECTOR_RESULTS.md](MOTION_VECTOR_RESULTS.md) | Motion-vector units from shader bytecode, consumer contract, and synthetic compute-shader checks. |
| [ROUTING_RESULTS.md](ROUTING_RESULTS.md) | Camera dimension source, logger resource tracing, synthetic routing mock, and the frame-dump option. |
| [FRAMEDUMP_RESULTS.md](FRAMEDUMP_RESULTS.md) | Two in-game frame dumps: the post-AA handoff and the replacement idea. |
| [SCENE_DOMAIN_INVENTORY.md](SCENE_DOMAIN_INVENTORY.md) | Pre-AA scene-domain inventory from the two dumps, with the global-slot open item. |
| [FSR4_RESULTS.md](FSR4_RESULTS.md) | Phase 3: FSR4.1.1 synthetic dispatch under Proton, runner comparison, provenance. |
| [NATIVE_AA_INSTALL.md](NATIVE_AA_INSTALL.md) | Native-AA installation: 8 files, backup, runner registration, Steam options, reversibility. |
| [VISUAL_STACK.md](VISUAL_STACK.md) | LodMod and WAX visual stack; historical LodMod phase; Special K isolated stalls. |
| [RESULTS.md](RESULTS.md) | Phase 2: native Ghidra analysis of the closed proxy and isolated loader, ABI and GPU-interop checks. |
| [RESEARCH_RECORD.md](RESEARCH_RECORD.md) | This record. |

Evidence and artifact folders (not read in full; cited by path and Evidence ID):

| Path | Description |
| --- | --- |
| [evidence/](evidence/) | 75 JSON and log entries: install, live verification, Ghidra function records, validation summaries. Some files are multi-MB single lines. |
| [offline-camera/](offline-camera/) | Camera, jitter and dimension RE: decoded pseudocode, snapshot and evidence index. |
| [offline-dimensions/](offline-dimensions/) | Swap-chain dimension source: factory and installer records, SDK header evidence. |
| [offline-motion/](offline-motion/) | Shader extraction, disassembly, reflection, shader manifest, and synthetic GPU validation. |
| [offline-routing/](offline-routing/) | Synthetic routing-mock baseline and chained runs, with trace verification. |
| [offline-framedump/](offline-framedump/) | Static safety check of the built-in frame dump and xref records. |
| [offline-gameexe/](offline-gameexe/) | Render-target creator record and unpacked snapshot. |
| [offline-display/](offline-display/) | Display probe binary and logs before and after the X primary fix. |
| [offline-unpack/](offline-unpack/) | SteamStub unpack working copy (analysis only). |
| [framedump-capture/](framedump-capture/) | Two in-game frame dumps and the mod logs for that session. |
| [isolated-gpu-3440-20261019/](isolated-gpu-3440-20261019/) | Synthetic FSR4.1.1 GPU runs at 3440x1440, with and without the logger chain. |
| [checks/](checks/) | Probe, verifier and ABI-check sources and tests. |
| [snapshots/](snapshots/) | Ghidra snapshots: original and offline upscaling. |
| [../backups/](../backups/) | Phase backups with manifests (native AA, visual stack, WAX, exe swap, frame dump, Graphic.ini, Hyprland). |
| [../quarantine/](../quarantine/) | Quarantined files: compat exe, OS-verification scripts, Special K crash files, instrumentation DLLs. |

---

## Validation performed on this record

- Source files: all 11 topic docs, PROGRESS and README read in full. The two parent-owned
  files, `GAME_RENDER_SCALE.md` and `offline-gameexe/`, were read but not written.
- Workspace hashes checked (read-only): `input/NieRAutomata_win10.exe` SHA-1
  `420cbab7...` and SHA-256 `5171bed0...`; `input/NIER_DLAA_1.1.dll` SHA-256 `f1c77c58...`;
  backup `NieRAutomata.exe.compat` SHA-256 `042e9fef...`; `hypr-primary` `monitors.lua`
  SHA-256 `392d0bee...`.
- Evidence IDs: each full ID cited in section 3 was found in the named JSON file or snapshot.
- Relative links: 69 unique links checked after writing; all resolve to existing files.
- Code fences: none in this file, so the count is balanced (zero).
- Ledger: 39 rows (F01-F39). Conflicts: 12 (C1-C12). Open questions: 8 (Q1-Q8).
