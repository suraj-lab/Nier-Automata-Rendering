# Scout report (agent 4): Redstone inputs, Hookshot vs NieR

Shorthand: **H** = `/home/suraj/Projects/hookshot-fsr4`, **B** = `H/build/framegen-investigation`, **U** = `N/upstream/Nier-FSR4`, **N** = `/home/suraj/Projects/Nier-Automata-Rendering`. Read-only. Nothing built or run.

## Scope warning
- **H is Hookshot**, a Switch 2 Zelda: Ocarina of Time remake on native Linux Vulkan (`H/docs/design.md:1-6`). It is not NieR and has no D3D11/D3D12 code (no d3d/dxgi/vkd3d hits in `H/gpu/vk`, `H/host`). NieR's FSR4 bridge is U. They share AMD's FSR 4.1.1 but not code.
- The handoff (`H/docs/FRAMEGEN-REDSTONE-HANDOFF.md`, dated 2026-11-11) is stale. Later B files of 11-12 change Phase C (§4).

## 1. What "Redstone" means
- **Hookshot:** FSR Frame Generation 4.0.2 (ML), SDK v2.4.0. Provider `amd_fidelityfx_framegeneration_vk.dll`, sha256 `d002dabf…` (`B/REDSTONE-FEASIBILITY-20261112.md:7-12`). AMD lists Win11, RX 9000+, Vulkan 1.2 or DX12 (`H/docs/FRAMEGEN-REDSTONE-HANDOFF.md:304-305`).
- Hookshot's upscaler is a separate FSR 4 v07 INT8 Vulkan provider, loaded from `RX_FSR4_DIR` (`H/gpu/vk/vk_fsr4.cpp:3-4,65`).
- **NieR notes** call SDK 2.3 "Redstone": FG 4.0.1, Ray Regeneration 1.2.0, Radiance Caching preview, "DX12 + Windows only" (`N/PROGRESS.md:1315-1317`). `U/README.md:4-5` uses the name for the 4.1.1 upscaler. These versions conflict with Hookshot's; not resolved here.
- Ray regeneration and radiance caching: no code use in H or U. Signed denoiser and radiancecache DLLs exist in the SDK (`B/REDSTONE-FEASIBILITY-20261112.md:27`). Ray Regen needs ray-traced G-buffers Remix does not expose (`N/analysis/LIVE_IN_GAME_PLAN.md:161-162`).
- **Upscaler inputs** (vendored header): color, depth, motionVectors; optional exposure, reactive, transparencyAndComposition; jitterOffset, motionVectorScale, renderSize, upscaleSize, preExposure, reset, cameraNear/Far/FovVertical, viewSpaceToMetersFactor (`U/third_party/FidelityFX/upscalers/include/ffx_upscale.h:87-111`).
- **FG inputs:** PrepareV2 takes depth, motionVectors, renderSize, jitter, motionVectorScale, frameTimeDelta, reset, camera near/far/FOV, viewSpaceToMeters, and world-space cameraPosition/Up/Right/Forward (`B/redstone/sdk/Kits/FidelityFX/framegeneration/include/ffx_framegeneration.h:225-249`). Dispatch takes presentColor, outputs[4], numGeneratedFrames, reset, backbufferTransferFunction, minMaxLuminance, generationRect, frameID (`…:92-104`). Configure takes swapChain and optional HUDLessColor (`…:110-123`).

## 2. Hookshot inputs, presentation, platform
- **Inputs are self-made.** Depth is R32F reversed. Motion is RG16F from camera reprojection, not game data (`B/source/gpu/vk/vk_fsr3_inputs.h:30-31`; `B/recon-game-motion-vectors.md` verdict). Jitter is the game's own (`vk_fsr3_inputs.h:6`). Camera comes from projection matrices (`:9`). Actor motion is behind `HOOKSHOT_NGX` (`:11`; `B/FINDINGS-20261111-night.md:110-116`).
- **Colour conflict:** `vk_fsr3_inputs.h:29` says RGBA16F. The ML FG path copies R8G8B8A8_UNORM (`B/mlfg/source/gpu/vk/vk_framegen.cpp:646-649`).
- **Native FSR4** runs LDR (no HDR flag), standard depth, and fixed camera values near 0.1 / far 1000 / fov 1.0 / viewToMeters 1.0 (`H/gpu/vk/vk_fsr4.cpp:114-115,250`).
- **Presentation:** Hookshot owns the Vulkan swapchain (`H/gpu/vk/vk_main.cpp:539`) and calls `vkQueuePresentKHR` (`H/gpu/vk/vk_replay.cpp:3133-3135`). No D3D, Proton or vkd3d.
- **ML FG** (B worktree, `RX_VK_MLFG=1`, opt-in): configure, then PrepareV2, then dispatch per frame. Reset frames are refused. 2x only (`B/redstone/REDSTONE-C3-RESULT.md:4-6,50,55`). One dispatch makes one frame at t=1/2; 3x/4x is impossible through this API (`B/redstone/C1-RESULT.md:64-78`). The mlfg tree sets no HUDLessColor.
- **Platform:** the AMD DLL loads in-process via ffx-vk-linux (`B/redstone/HOW-REDSTONE-RUNS-ON-LINUX.md:62-67`). RADV needs `radv_cooperative_matrix2_nv` and `radv_device_coherent_memory` (`C1-RESULT.md:33-36`). The Wine harness used a Win11 prefix (`C1-RESULT.md:31-33`). Tested only on RX 9070 XT, RADV gfx1201, Mesa 26.2.6 (`HOW…:2-4`). RDNA2 ML FG: not found. NieR's FSR4 needs RX 7000/9000 (`U/README.md:20-21`).

## 3. NieR: the bridge and our proxy
- NIER_DLAA 1.1 `d3d11.dll`. `tools/patch_mod.py` redirects NGXLoadCoreLibrary to `NIER_FSR4.dll` (`U/docs/REVERSE_ENGINEERING.md:41-44`; `U/tools/patch_mod.py:1-16`).
- **Mod-supplied inputs** (`REVERSE_ENGINEERING.md:72-81`): Color = HDR scene texture; Depth = device depth; MotionVectors = camera plus character motion, render pixels (`:12-14`; `U/README.md:37`); jitter; MV scale 1.0; Reset; render subrect.
- **Bridge:** copies color, depth and MV into shared D3D12 textures (`U/src/nier_fsr4.cpp:1207-1209`). D3D11 signals a ready fence (`:1211`). D3D12 dispatches (`:1266`), then signals done (`:1275`). D3D11 waits and copies out (`:1282,1297`). Three command allocators (`:489`). D3D12 device on the game's LUID, FL 12_0 (`:539-590`).
- **Camera:** near, far and FOV read from mod memory (`:288-293,322-368`). `viewSpaceToMeters=1.0` (`U/dist/NIER_FSR4.ini:31-38`).
- **Exposure:** only `DLSS.Pre.Exposure` becomes preExposure (`:1234,1252`). No reactive, transparency or HUD-less input (`:1129-1131`). `FrameGeneration.Available=0` (`:1404`).
- **Our proxy:** `analysis/checks/d3d11_scale_setter.cpp:1-3` chainloads NIER_DLAA. Patches: gates (parts 0/0b), native output size (parts 1/2), and part 3, where bloom and tonemap read the FSR output with copy-back skipped (`N/analysis/UPSCALING_PATCH.md:14-21,25-84`). So FSR sees pre-tonemap HDR (`:82-84`). Live result: 2580x1080 to 3440x1440 (`:14-21`).
- **Proton:** GE-Proton11-7 passed a synthetic 4.1.1 dispatch. GE11-1 fell back to 3.1.5 (`N/analysis/FSR4_RESULTS.md:9-24,48-51`). Synthetic only.
- **Remix path:** final colour goes to a D3D9 target, then readback (`analysis/checks/remix_live.cpp:946-952`), then `frame_copy::bgra` (`frame_copy.h:8-9`), then `UpdateSubresource` into the backbuffer (`remix_live.cpp:1132,1263`). Colour only; no depth or motion readback found.

## 4. Open problems
**Still open per the 11-11 handoff:**
- Node launcher broke on simdjson `.so.34`, and an automatic upgrade re-broke it (`H/docs/FRAMEGEN-REDSTONE-HANDOFF.md:84-108`; `B/FINDINGS-20261111-night.md` checklist).
- Quarter-window root cause not isolated. No HUD-less colour (`:147-149`).
- VUID-01387 is pre-existing. Post-link checker false-positives on 41 imports (`:287-290`).
- Live install is v2.0.14 with `RX_VK_FSR_FG=0`. User verdict: "workaround looks good" (`:23-31`).

**Superseded by 11-12 files (not rerun by me):**
- Root cause found upstream: NotRexed/Hookshot#1943, a wrong render-size flag (`B/FINDINGS-20261111-night.md`, "2026-11-12 day session").
- Redstone C1 passed: correct midpoint, provider 4.0.2 (`C1-RESULT.md:1-27`).
- In-game opt-in: 600/600 made frames; soft frames 2% vs 9% for the renderer's own (`C3:26-41`). 30-min soak, VRAM flat at about 8.1 GB (`C3:66-86`).
- Still open: no HUD-less input (`C3:47-49`); reset frames discarded; world scale unknown (`C3:50-53`); AMD DLL redistribution licence (`C1:62`); camera-only motion vectors (`REDSTONE:115-116`).

## 5. Needed to run Redstone on the Remix frame in NieR
**Available:** colour (CPU readback path), jitter, mod MVs, mod depth, near/far/FOV, reset.

**Missing or unverified:**
1. GPU-resident Remix colour. The current path is CPU readback plus upload. No shared texture from Remix was found.
2. Correct colour role. FG wants display-referred colour with a transfer function (`ffx_framegeneration.h:92-104`). NieR's FSR input is pre-tonemap HDR. The handoff forbids substituting that without proof (`H/docs/FRAMEGEN-REDSTONE-HANDOFF.md:168`). The Remix frame before `hud_replay::draw` (`remix_live.cpp:1263-1270`) may be a HUD-less source. This is inference.
3. World camera position and basis (PrepareV2 fields, `ffx_framegeneration.h:240-247`). U reads only near/far/FOV (`nier_fsr4.cpp:322-368`).
4. A world scale for viewSpaceToMeters. Unknown; 1.0 everywhere.
5. Depth and motion matching Remix's frame. Remix's own depth and vectors are not read back. Mod MVs and depth describe the game's frame, not the Remix frame. Unverified.
6. Presentation takeover. FG needs a swapchain it owns (`ffx_framegeneration.h:110-123`). NieR presents via D3D11. The DX12 present takeover is "unbuilt" (`N/VISION.md:63`).
7. ML FG under Proton is unproven. C1 ran in a Win11 Wine prefix. NieR's prefix is not checked.
8. Ray regeneration and radiance caching: no inputs available (`LIVE_IN_GAME_PLAN.md:161-162`).
9. Providers: U ships only `loader_dx12` and `upscaler_dx12` (`N/analysis/FSR4_RESULTS.md:37-42`). No FG DLL.
10. Hookshot's FG code does not port directly: native Vulkan frame versus a D3D11 host.