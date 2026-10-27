# NieR:Automata Rendering — Progress & Resume

Last updated: 2026-10-27 (evening). **Read the first checkpoint: the transfer blocker is gone.**

## Checkpoint — 2026-10-27 evening: the frame can leave the runtime, and it was our bug

**Live Remix unknown (a) is answered — yes, and the previous session's "all copy routes fail" conclusion is
wrong.** Full write-up and measurements: [LIVE_TRANSFER.md](analysis/LIVE_TRANSFER.md). Summary:

- `dxvk_CopyRenderingOutput(FINAL_COLOR)` copies the **registered device's backbuffer**
  (`rtx_remix_api.cpp`, `copyRenderingOutput`), and `dxvk_RegisterD3D9Device` **replaces** the presenting device.
  Our probe called `Startup` first (which creates and registers the presenting device), then registered a
  second, never-presented device with a 64x64 swapchain. The copy faithfully copied an empty backbuffer.
- Working order: `dxvk_CreateD3D9` -> `CreateDeviceEx` with a real swapchain at render size ->
  `RegisterD3D9Device` -> `Startup` (returns `ALREADY_EXISTS`, expected) -> submit -> `Present` -> copy into a
  target **sized from `GetBackBuffer()->GetDesc()`**.
- Measured: copy `ok=1`, mean luma 0.4522, non-black 0.9996 at 2580x1080; identical to a direct backbuffer
  read; readback control (`ColorFill` green) reads exactly 0.7152, so the instrument is trustworthy;
  copy+readback **0.49 ms/frame** at 11.1 MB (0.21 ms at 3.8 MB).
- **Framerate, corrected the same evening: native 2580x1080 is 21 fps**, not 53. The 53-60 fps figures came
  from runs with no conf applied, where `rtx.dlssPreset = On` requests DLSS, DLSS does not exist on AMD, and the
  runtime silently falls back to a lower internal render resolution - they were already upscaled. With conf
  verified applied (`DXVK_LOG_LEVEL=debug`): **native 21 fps, XeSS Quality (preset 3) 48 fps** on the textured
  camp scene (2.7M triangles, 190 textures). Live is still viable, but at XeSS-level render scale, not native.
- Runtime version question settled: Portal RTX's `.trex/d3d9.dll` and public **remix-1.6.1** are the same
  build family (same size, 322 differing 4K blocks). The 1.6.1 PDB names `CopyRenderingOutput`,
  `GetExternalSwapchain`, `GetVkImage`, `SetDefaultOutput`, `RegisterD3D9Device` and has **no**
  `GetInteropInfo`/`clientDoneSemaphore`: the interop-image path is the **NVIDIA-internal** runtime
  (`rtx-remix-minecraft` compiles against remixapi **0.16.0**; ours is 0.6.5), not the public release.
  Remix **1.6 added Windows-on-Arm** runtime support with public ARM64/ARM64EC artifacts, which makes the
  laptop (RTX Spark N1X) a native-NVIDIA Remix host for the first time.
- Probe controls added (opt-in, defaults unchanged): `REPROBE_PRE_REGISTER`, `REPROBE_INTEROP_CONTROL`,
  `REPROBE_INTEROP_BACKBUFFER`, `REPROBE_INTEROP_LOOP`, `REPROBE_INTEROP_CLEAR`; `REPROBE_INTEROP_REGISTER` now
  defaults **off**. Exe `5b70560f…`, 27 CPU gates + the probe build green.

- Per-draw submission cost is **unmeasured**: adding `REPROBE_INSTANCES` to the probe showed the effect is confounded
  by clustered overdraw in view (47/26/34 fps at N=100/300/1000, non-monotonic), and with instances moved behind the
  camera to isolate submit cost the probe **dies before its first report at N>=500** (0-byte metrics.txt, no stray
  processes). Next session starts there.
- FSR SDK 2.3 (Redstone) is **DX12 + Windows only**: Upscaling 4.1.1 (already in-game here via the D3D11<->D3D12
  bridge), Frame Generation 4.0.1 and Ray Regeneration 1.2.0 on RDNA4, Radiance Caching preview. FG additionally
  needs a DX12 swapchain, which NieR (D3D11) does not have - so desktop gets XeSS + FSR4 upscaling, and frame
  generation + DLSS/RR live on the Windows/NVIDIA laptop.

**What live now needs, in order:** (1) feed NieR's live draw stream instead of a converted capture — cache
materials/meshes/textures by hash, update camera and instance transforms per frame (the probe already submits
2.7M triangles per frame at 53 fps, so the renderer side is proven); (2) composite: copy -> sysmem -> D3D11
texture -> fullscreen quad in our own Present hook (cost measured above); (3) the one unsolved design problem
is **UI**, which is D3D11 in the game frame and absent from Remix's output.

## Checkpoint — 2026-10-27 (CPU-only session: interop API decoded; desktop runs restricted)

No game, no GPU. Everything below came from reading the shipped binary and its reference implementation.
Full write-up: [INTEROP_API.md](analysis/INTEROP_API.md). Host constraint that shaped the session: the
desktop shares monitors with the user's work machine, so desktop runs must be scheduled with them.

**The interop-image route is not available in the runtime we render with.** `remixapi_InitializeLibrary`
(`0x180214d40`, 0x160 bytes) fills exactly **22** interface pointers, `+0x00..+0xa8`, matching the public
header 1:1 and ending at `SetCameraMediumMaterial`. Slot `+0xb0` (`dxvk_GetInteropInfo`) is never written,
and the same function only accepts `InitializeLibraryInfo.version` with major 6
(`(version & 0xffffffff0000) == 0x60000`). So `dxvk_GetInteropInfo` and `StartupInfo.interopImage` — the two
extensions the Minecraft bridge relies on (runtime API 0.16.0) — cannot exist here. The 2026-10-26 note
"architecture proven to exist, three unknowns left" is right about the architecture and wrong about
availability: that path needs a newer runtime (Toolkit or the Minecraft mod's), not more code from us.

**The copy route is confirmed as the available one, and its contract is now known**
(`dxvk_CopyRenderingOutput` @ `0x18020eeb0`): returns 7 before `Startup`, 3 for a null/invalid surface,
pulls the DXVK device out of the destination surface (`[surface+0x48] -> [+0x40]`) so the surface must come
from the device `dxvk_CreateD3D9` returned; accepts types 0/1/2/4, gates 3 behind a one-shot flag, and
**refuses GUI (4) when `combineGuiInFinalColor` was set**; synchronous, takes an internal mutex, retries
once. `interop_probe.h` already orders the calls this way.

**`dxvk_GetExternalSwapchain` succeeds with a null image** unless `forceNoVkSwapchain` was set at Startup:
it writes the semaphores regardless and returns 0. Judge that route by the handle, not the error code.
`dxvk_GetVkImage` (`0x18020f400`) returns the *surface's* backing VkImage (same-`VkDevice` hosts only), so
it cannot hand a second `VkDevice` Remix's final image.

**Denoise: root cause found, and it was our own config — see the section below.** NRD.dll is loaded
dynamically (one `"NRD.dll"` string at `0x190c26f48`, std::filesystem path, loader call through the IAT
slot `0x1806b32b8` at `0x1804e2bf8`), and it loads successfully: the runtime logs `Unable to load NRD` or
`Incorrect version of NRD` at error level on failure, and neither appears in any of the 61 stored run
dumps. The real blocker is `rtx.useDenoiserReferenceMode = True` in `rtx.no-ngx.conf`, which the source's
guide-allocation gate treats as "do not denoise".

**New tools** (both CPU-only, no third-party modules):
- `analysis/tools/pe_info.py` — exports, imported DLLs, and resolved import slots
  (`--imports=<substr>`), since the box has no pefile and the REA MCP is not wired to Ghidra here.
- `analysis/tools/xref.py` — RIP-relative cross-references to a string or VA, each hit re-decoded with
  objdump so a false positive is visible. This is how `useDenoiser` (only reachable in the option-registry
  initialiser) and the `NRD.dll` load site were found.

**`run_desktop.sh` teardown fixed.** Killing the process group left `wineserver` alive with its windows
still mapped on the user's screen (observed twice on 2026-10-27). Teardown now stops the prefix's
wineserver and prints an explicit warning if a probe window survived; it also prints `metrics.txt` and
`interop.txt` after every run.

**Environment facts to not rediscover** (each cost time on 2026-10-27):
- Proton on this desktop **drops the child's stdout entirely** — a 12-line `hello.exe` printing to both
  stdout and stderr produced nothing, `rc=0`. Hence `metrics.txt`/`interop.txt`; never debug via stdout.
- **Wine maps its window on the focused monitor.** `xrandr --primary` does not influence placement (it only
  affects the mode list a Wine game offers), so it cannot keep a probe window off a physical monitor.
- **`hyprctl keyword` is unavailable on this Lua-parser Hyprland** ("keyword can't work with non-legacy
  parsers. Use eval"), so a window rule cannot be added from a shell; it needs the Lua config or `eval`.
- A **headless Hyprland output works** (`hyprctl output create headless` → `HEADLESS-1`, layout unchanged,
  physical modes byte-identical, removed cleanly with `hyprctl output remove HEADLESS-1`) — but a window is
  still placed on the focused physical monitor, so it does not isolate a run by itself.
- The desktop session can be **locked**, in which case a probe run creates `metrics.txt` and exits with no
  window and no rtx-remix log. That is the fingerprint of "locked", not of a broken probe.

**Queued, needs one GPU run each, in this order:** (1) native fps — `metrics.txt` already emits
`FPS <n> frames / <s> = <fps>` every 30 frames; (2) `REPROBE_INTEROP=1` for the copy route;
(3) the `forceNoVkSwapchain` + `GetExternalSwapchain` route, judged by a non-zero handle.

## Checkpoint — 2026-10-26/27 (start here)

**Installed in the game.** `d3d11.dll` = `b32f6f5f76e0d773…` (menu + FSR4 + capture + shader identity + PS constant
buffers); `d3d11_dlaa.dll` = `3d628eb5…` untouched; `NIER_RENDER.ini` = `Preset=Custom75`; 60 FPS cap unchanged.
Rollback: `backups/ingame-menu-shaderid-20261026T225431Z/` with `receipt.json`, plus the older `ingame-menu-*` chain.

**Gates: 22 green** — 17 in `analysis/checks/`, 5 in `analysis/remix-probe/`. Nothing is committed since 2026-10-25:
12 files modified, 6 new.

### What works

- **F9 -> Remix stills, textured.** `scene_from_frame.py` emits NSCN **v3**: per-draw albedo id, a texture table, the
  used `tex_<id>.dds` copied into `<out>_textures/`, and an 8x8 mip-chained `scene_sky.dds` for the dome light.
  Real capture: 1057 draws, 2.74M triangles, 190 textures. The camp renders with 2B, her dress and sword, vegetation
  from the WAX pack, shelves and crates. Image: `analysis/runtime/remix-probe/stills/`.
- **Materials.** `blendType_value`: **0 = fully transparent, 1 = blend by albedo texture alpha, 2 = opaque.** That one
  integer was the cause of every "black scene". Everything is currently forced to 2.
- **Capture records shader identity.** `vs_hash`/`ps_hash` (pointer identity, stable within a capture) and `ps_cbs`
  (pixel-shader constant buffers, written as `ps_cb_<slot>.bin`). Asserted by `test_menu_overlay.py`.
- **`dds_stack.py`** averages N post-tonemap frames (`test_dds_stack.py`, 3 checks).
- **`run_remote.py`** auto-unloads laptop models before rendering and takes `--sun --sun-angle --sky --albedo --mat
  --blend --flip-normals --skip-max --sky-tex --watchdog --env --no-unload`.

### Negative results, settled (do not re-run these)

- **NRD never engages for an API-only client.** Five configurations, noise 0.084 in all: `useDenoiser` on/off
  (1 float16 ULP apart), reference mode + `resetOnCameraTransformChange=False` + `numberOfFramesToAccumulate=1024`,
  `uniqueObjectDistance=1000000` (the option does exist — verified), frames 150 vs 1200. Source rules out the two
  structural explanations: `rtxImagePostTonemapping` *is* the final post-composite image, and the API path shares the
  D3D9 camera bookkeeping. Only option-layer precedence is left, and it needs a debug build.
- **The noise is deterministic**, so accumulation and frame averaging cannot fix it (two frames average to 0.978x
  where independent samples would give 0.707x). A box filter outside Remix gives 0.53x and is the only working lever.

### Live Remix in NieR — status changed, three unknowns left

1. **The interop API is present.** The export table has no `dxvk_*` names, but these are `remixapi_Interface` members.
   The probe now prints, on every scene run: `Interop: startup=1 createD3D9=1 registerD3D9=1 getSwapchain=1
   getVkImage=1 copyOutput=1 setDefaultOutput=1`.
2. **NVIDIA ships a non-D3D9 host.** RTX Remix for Minecraft (Fabric mod, Remix 1.6, 2026-10-23) drives Remix from a
   Java/OpenGL process via the C API, and solves presentation + UI with `StartupInfo.interopImage` +
   `dxvk_GetInteropInfo` + a Present handshake. Undocumented, absent from public source (runtime 0.16.0 vs public
   0.6.6). NVIDIA closed the *D3D11* request as NOT_PLANNED and no public D3D11 bridge exists.
3. **Design sketch, untested at every step:** inside NieR's process -> `dxvk_CreateD3D9` -> submit the captured scene
   per frame -> `dxvk_CopyRenderingOutput(surface, FINAL_COLOR)` into a surface we own -> bring that image into DXVK's
   D3D11 device (shared handle, or `dxvk_GetVkImage` + cross-device import) -> replay NieR's UI draws on top ->
   present through the game's own swapchain.

**Unknowns in risk order:** (a) can two Vulkan devices in one Proton process share an image at all; (b) native
framerate — **no valid number exists yet** (the 0.52 fps measurement came from the ARM laptop running x64 under
emulation and proves nothing about native); (c) UI replay cost.

### Next steps, in order

1. **Native framerate.** One clean desktop run at `HEIGHT=180` with a teardown that actually kills the wine process
   (`setsid` + `kill -- -$pid` then verify with `pgrep -x remix-scene.exe`). This single number decides whether live
   is worth building.
2. **Interop probe** (delegate to a cloud agent with a gate): create a D3D11 device, init Remix, `dxvk_CreateD3D9`,
   `CopyRenderingOutput` into a host-owned surface, read the pixels back. Either it produces pixels or it tells us
   where the boundary is.
3. **Stills polish, all cheap and option-verified** (see `RtxOptions.md`, 1041 lines, dumped from the running binary):
   `rtx.enableCullingInSecondaryRays = True` for the streaks; legacy DDS with RGB masks for the dome/sky; cutouts by
   scanning each `ps_hash` for `discard` then setting `alphaTestType`; exposure via `rtx.autoExposure.evMinValue/
   evMaxValue` (-2..5 default).
4. Skip: denoising inside Remix. Post-filter only.

### How to resume

```
# gates
for t in analysis/checks/test_*.py; do python3 "$t" >/dev/null || echo "FAIL $t"; done
cd analysis/remix-probe && python3 test_scene_from_frame.py scene_from_frame.py

# still from a fresh F9 capture
python3 analysis/remix-probe/scene_from_frame.py <F9 frame dir> /tmp/out/scene.bin
python3 analysis/remix-probe/run_remote.py still-1 --scene /tmp/out/scene.bin   --conf analysis/remix-probe/rtx.no-ngx.conf --hold --shot-frame 600   --sun 2 --sun-angle 20 --sky 0.5 --watchdog 45000 --env REPROBE_HEIGHT=360

# authoritative option list for the exact binary in use
  ... --env DXVK_DOCUMENTATION_WRITE_RTX_OPTIONS_MD=1     # writes RtxOptions.md into the run folder
```

**Method (see the section below): check the reference implementation first** — `PortalRTX/dxvk.conf`,
`bridge.defaults.conf`, `strings` on `.trex/d3d9.dll`, and prior art — before source reading or GPU runs. That single
change of order is what produced the interop finding after a session of negative conclusions.

## Checkpoint — 2026-10-26 (textured stills in Remix)

**v3 converter + materials landed.** `scene_from_frame.py` now emits NSCN v3: per-draw albedo id plus a
texture table, and copies the used `tex_<id>.dds` into `<out>_textures/`. Albedo = largest-area sRGB
(`*_UNORM_SRGB`) pixel-shader texture, lowest slot on a tie. Gates: `test_scene_from_frame.py` (11 checks,
incl. a hand-computed skinned vertex, stale-texture replacement, uint32 id bound, unusable output path) and
12/12 hidden, plus `SCENE_TEXTURED_FRAME=<capture>` for a real capture (1057 draws, 190 textures).
Independent reviewer found 14 issues, 9 valid and fixed; ledger updated.

**Remix now renders NieR geometry with materials and textures** (laptop, `remix-scene.exe`, 1028x540):
`analysis/runtime/remix-probe/stills/nier-camp-textured-v3-*.png`. 2B, her dress and sword, vegetation from
the WAX pack, shelves and crates, all path-traced from one F9 capture.

Facts established the hard way (each cost a GPU run — check these before re-diagnosing):
- **`blendType_value`: 0 = fully transparent, 1 = blend by albedo texture alpha, 2 = opaque.** A material with
  any other blend value renders invisible; this, not lighting, was behind every "black scene" run.
- Textures load: the runtime logs each `scene_textures/tex_<id>.dds` as a replacement texture (only a
  missing-mipmap warning). The DDS files are fine; do not re-test the loader.
- Sampling our own albedo at our own UVs gives mean rgb (0.44, 0.40, 0.36) over 40 draws — UVs and texture
  selection are correct.
- Scene normals are unit length and 48.5% face the sun; flipping them changes nothing.
- `nullptr` material renders bright and continuous (Remix's unlit default): it is *not* a lighting reference.
- Remix irradiance ≈ π·radiance, nearly independent of `angularDiameterDegrees`; use radiance ~1-100. A
  narrow disc trips the firefly filters (threshold 1000), so the sun is given a 20° diameter.
- `remixapi_LightInfoDomeEXT` with a null `colorTexture` produces **no light at all** (the texture index stays
  invalid and the radiance is never uploaded) — our "ambient dome" was void. Needs a 1x1 white DDS.

**Capture now records shader identity (2026-10-26 late, gated).** `draw_capture.h` gained `vs_hash`/`ps_hash`
(pointer identity — stable within a process, so one capture can group draws by shader family) and `ps_cbs`
(pixel-shader constant buffers, written as `ps_cb_<slot>.bin` so a slot shared with a VS buffer cannot
overwrite it). `test_menu_overlay.py` asserts the keys, that the two hashes differ, and that both files are
written; the mock game binds one PS constant buffer. All 17 gates pass; the DLL is rebuilt at
`analysis/runtime/menu-dll/d3d11.dll` (`d3d11_log_proxy` exports verified, no forbidden imports) and is **not
deployed**. Next: deploy it, take one F9 capture, and use `ps_hash` to identify the albedo slot per shader
family instead of guessing from texture formats — that is what fixes 2B's black dress.

**NRD does not denoise this client, measured three ways (2026-10-26).** Source reading says NRD should engage
(its only gates are `useDenoiser && !useDenoiserReferenceMode && !useRayReconstruction`, all satisfied, and the
missing log line is debug-level only). Empirically it does nothing: `rtx.useDenoiser=True` vs `False` differ by
one float16 ULP (max abs diff 0.000488) with identical noise 0.0841; `rtx.uniqueObjectDistance=1000000` (the
suggested fix if the camera reads as cut every frame) changes nothing either. So the guide resources are
presumably never allocated for an API-only client, or the result never reaches the composite. Conclusion for the
stills path: **denoising must happen outside Remix.** A box filter measured on a real frame gives 0.62x noise at
3x3 and 0.53x at 5x5 with block-level detail unchanged, so a tuned spatial filter is the practical deliverable.
Side note: a 1028x540 render of this scene consumes most of the laptop's unified memory; use
`REPROBE_HEIGHT=360` for diagnostic runs.

**Measured: no accumulation and no independent samples (2026-10-26 latest).** Two runs of the identical scene
differing only in the capture frame (150 vs 1200) give the same noise, 0.0843 vs 0.0841 within-block — so a static
camera does not converge no matter how long it runs, and `rtx.accumulation.resetOnCameraTransformChange=False` with
`numberOfFramesToAccumulate=64` changes nothing. The two frames are not byte-identical (pixel correlation 0.9807),
but averaging them only moves the noise to 0.0824 (factor 0.978 where independent samples would give 0.707). So
`dds_stack.py` is correct and useful, but it cannot denoise on its own: the frame-to-frame difference is largely the
same deterministic noise. Real options now: make NRD actually engage, or apply a spatial filter outside Remix.

**Frame averaging is in, for when the denoiser cannot run (2026-10-26 latest).** `analysis/remix-probe/dds_stack.py`
averages N `rtxImagePostTonemapping` DDS frames into one PNG in linear space, gated by `test_dds_stack.py`
(black+white -> mid-grey hand-computed, identical frames reproduce one frame, mismatched sizes / non-DDS /
NaN payloads exit 2 without a traceback or a stray output file). Written by a cloud agent against the gate
after both local nodes stalled for 12 minutes on the same brief; the gate did not change between candidates.
**Open question before it helps:** two identical runs produced byte-identical captures, so averaging separate
runs cannot reduce noise. Independent samples must come from different frames within one run (the screenshot
frame is configurable) or from a changed seed — worth one run to settle.

**Sky and denoising: both blocked, with measurements (2026-10-26 late).**
- *Sky via a dome light is blocked.* A dome light with a `colorTexture` crashes the runtime with
  `0xC0000094` (integer divide by zero) inside `Present`, on frame 0, measured with a 1x1 DDS and with an
  8x8 mip-chained DDS. `run_remote.py` now ships `scene_sky.dds`, and attaching it is opt-in
  (`REPROBE_SKY_TEX=1`). The promising alternative is a *real* sky: include NieR's own sky-dome draws as
  geometry via `REPROBE_SKIP_MAX` (they are 10-19 km shells skipped for blocking the sun at the default
  5000).
- *Denoising does not run.* `NRD.dll` ships with the runtime, the conf lines parse, and switching
  `rtx.useDenoiserReferenceMode` to False changes nothing measurable: within-block noise 0.0843 before vs
  0.0842 after. The log shows no NRD activity at all, consistent with NRD needing guides (motion vectors,
  normals) that an API-only client does not provide. Options: accept the noise, post-filter outside Remix, or
  enable DLSS/NGX (which hangs at shutdown on this host).
- Laptop renders now unload LM Studio models first (`run_remote.py` does it automatically): a loaded 35B model
  was holding 23.57 GB of the laptop's unified memory during earlier renders.

**Albedo selection is still the weak point (2026-10-26 late).** `mostly_black()` now rejects near-empty
atlases (>90% black blocks, read from the colour endpoints: BC1 bytes 0-3, BC2/BC3 bytes 8-11 — the reviewer
caught that my first version read the alpha block for BC2/BC3 and so mis-judged 28 of 190 textures).
A 50% threshold would reject the dress mask, but it also rejects a legitimate green banner (0.536 vs 0.660),
so the guard stays conservative; the real fix is shader identity, not texture statistics. For 2B's draws the
captured candidates contain no diffuse at all (a white 32x32 dummy, an environment photo, and blue-ish normal
maps), so her dress renders black from a detail atlas. `analysis/remix-probe/DIAGNOSIS_LOG.md` records the
wrong turns from this session, with the cheap check that would have avoided each.

**Next (in order):**
1. Denoising: `rtx.useDenoiser` / `rtx.useDenoiserReferenceMode` had no visible effect at frame 1200; verify the
   effective value (Remix option layers) and get a clean still. Noise is the biggest quality gap now.
2. Sky/ambient: 1x1 white DDS for the dome light, then `rtx.volumetrics.enableAtmosphere` for a physical sky.
   The 7 skipped sky-sized draws are still skipped.
3. Alpha: real cutout draws (foliage, hair) should use blend 1 + alpha test rather than blend 2.
4. Overdraw streaks visible in the still (thin geometry + no sky) — likely fixed by 2.
5. Only then: the Goal 2 decision (Remix live inside NieR), unchanged: the wall is presentation and the game's
   HUD, not geometry.

**Runner note:** `run_desktop.sh` exists for Proton runs but the desktop render competes with the compositor on
the same card (`MESA_VK_DEVICE_SELECT` pins Vulkan to the 9070 XT, which drives both monitors); prefer the
laptop for stills. `run_remote.py` gained `--sun --sun-angle --sky --albedo --mat --blend --flip-normals
--watchdog`, and the probe prints its effective modes.

---

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

**Delegation plan for the next session (user request: use the spare local models):**
- Converter v3 (albedo texture per draw): write the frozen gate first, then brief the SAME gate to two
  candidates in parallel: laptop **`gemma-4-31b-it`** (via PAIR; only while no Remix render runs on the
  laptop) and desktop **`qwen/qwen3.8-27b:low`**, each writing its own `*_cand_<model>.py`. Lead reruns
  gate + hidden cases for every candidate, keeps the best, records both in the ledger.
- Give desktop **`google/gemma-4-12b`** one small mechanical task (extraction/scaffolding into a new file)
  to see whether it is a useful fast helper.
- Neither Gemma model has any ledger records yet. Model guidance and the benchmark protocol:
  `~/.pi/agent/skills/local-delegation/MODEL_EVALUATION.md`. Brief template (with write-first block):
  `~/.pi/agent/skills/local-delegation/templates/brief.md`. Unload models afterwards.

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

## Live Remix in NieR: architecture exists (2026-10-26 late) — status changed

Two facts overturned the earlier "not viable" judgement:

1. **The interop API is present in the runtime we use.** The export table contains no `dxvk_*` names, but those are
   `remixapi_Interface` members, not exports. Probing the struct directly after `remixapi_InitializeLibrary` gives:
   `startup=1 createD3D9=1 registerD3D9=1 getSwapchain=1 getVkImage=1 copyOutput=1 setDefaultOutput=1`. The probe
   prints this line on every scene run now.
2. **NVIDIA ships a non-D3D9 host.** RTX Remix for Minecraft (Fabric mod, shipped with Remix 1.6, 2026-10-23) runs
   Remix from a Java/OpenGL process purely through the C API. Presentation and UI are solved with
   `StartupInfo.interopImage` + `dxvk_GetInteropInfo` + a Present handshake: the host draws its own UI into a shared
   image and Remix composites and presents it. That extension is undocumented and absent from public source (shipped
   runtime is API 0.16.0, public header 0.6.6). NVIDIA has closed the *D3D11* request as NOT_PLANNED, and no public
   D3D11 bridge exists — but the architecture for a non-D3D9 host is proven, in their own product.

**Sketch of a live path** (not yet tested at any step): inside NieR's process, `dxvk_CreateD3D9` to obtain Remix's own
D3D9 device -> submit the captured scene through the API -> `dxvk_CopyRenderingOutput(surface, FINAL_COLOR)` into a
host-owned surface -> bring that image into DXVK's D3D11 device (shared surface handle, or `dxvk_GetVkImage` +
cross-device import) -> replay NieR's UI draws on top -> present through the game's own swapchain.

**Unknowns, in order of risk:** (a) two Vulkan devices in one process under Proton sharing an image at all;
(b) framerate once it runs — no native measurement exists yet, the 0.52 fps figure came from the ARM laptop and is
not evidence; (c) UI replay cost and correctness.

## Denoise root cause found (2026-10-27) — our own config disabled it

The two-session mystery ("NRD never engages, five configurations, noise unchanged") is a single line in
`rtx.no-ngx.conf`, the file every documented run uses: **`rtx.useDenoiserReferenceMode = True`**.

From dxvk-remix source (sparse clone of `main`, `src/dxvk/rtx_render/`):

```cpp
bool Resources::needsNrdDenoisingGuideResources() const {   // rtx_resources.cpp:469
  return !device()->getCommon()->metaRayReconstruction().useRayReconstruction() &&
         RtxOptions::useDenoiser() &&
         !RtxOptions::useDenoiserReferenceMode();
}
```

and `RtxContext::dispatchDenoise` (rtx_context.cpp:1712) gates on the *allocated* resources:

```cpp
const bool shouldDenoise = getResourceManager().areNrdDenoisingGuideResourcesAllocated();
if (!shouldDenoise) { denoiser0.releaseResources(); ... return; }
```

So with reference mode on, the guides are never allocated, every denoiser is released and the function
returns before any dispatch. `rtx.useDenoiser` then has no observable effect — exactly the 1-float16-ULP
difference recorded on 2026-10-26. `useDenoiserReferenceMode` appears at 12 sites and *every* one of them
disables the realtime/NRD path (`rtx_resources.cpp:472`, `rtx_context.cpp:1076` and `:1886`,
`rtx_rtxdi_rayquery.cpp:399` and `:429`, `rtx_composite.cpp:430`), so no configuration that kept it True
could ever have denoised. The 2026-10-26 tests that "changed nothing" all ran with it True.

Two things this rules out, for the record: NRD.dll does load. `rtx_nrd_context.cpp` logs
`Unable to load NRD` or `Incorrect version of NRD` at error level on failure, and **neither appears in any
of the 61 stored run dumps** (checked across all fields, not just stderr). So the DLL load and the NRD
version check both passed; only the option gate was closed.

Fixed in `rtx.no-ngx.conf` (`useDenoiserReferenceMode = False`), with the reason inline. **Unverified
until one GPU run**; the check is that the still's noise drops below the 0.28 measured on the v3 frame,
since `noise.py` now defines the number to compare against.

## Material and alpha semantics, from the API implementation (2026-10-27)

`rtx_remix_api.cpp:429-434` is the whole story for how the API's opaque material is built:

```cpp
tobool(extOpaque->useDrawCallAlphaState),   // OpaqueMaterial::UseLegacyAlphaState
tobool(extOpaque->blendType_hasvalue),
extOpaque->blendType_hasvalue ? static_cast<BlendType>(extOpaque->blendType_value)
                              : BlendType::kAlpha,          // <- default is ALPHA, not opaque
tobool(extOpaque->invertedBlend),
static_cast<AlphaTestType>(extOpaque->alphaTestType),
extOpaque->alphaReferenceValue,
```

Consequences for the stills path:

- **Leaving `blendType_hasvalue` at 0 does not mean opaque** — it means `kAlpha`, i.e. blend by the
  albedo texture's alpha. That is why an unset material can render invisible when the map's alpha is
  mostly zero, and it is consistent with the measured 0/1/2 behaviour (0 transparent, 1 alpha-blend,
  2 opaque) recorded on 2026-10-26.
- `useDrawCallAlphaState` only makes sense for a D3D9 client, where the draw's own alpha state exists.
  An API-only client has no draw state, so it must stay 0 and everything must be stated explicitly —
  which is what `scene_from_frame.py` → `blendType_value = 2` currently does for every draw.
- Cutouts (foliage, hair, grilles) should therefore be `blendType` opaque **plus** `alphaTestType` and
  `alphaReferenceValue`, not blend 1. Blend 1 on a cutout card gives soft, sorting-dependent edges and
  the overdraw streaks visible in the v3 still; alpha test gives hard cutouts, which is what NieR's
  draws actually do in the game.
- **`AlphaTestType` values are now pinned** — `rtx_materials.h:77-84` asserts them equal to `VkCompareOp`:
  `kNever=0, kLess=1, kEqual=2, kLessOrEqual=3, kGreater=4, kNotEqual=5, kGreaterOrEqual=6, kAlways=7`,
  and the default is `kAlways` (7), i.e. no test. A cutout therefore wants `alphaTestType = 4` (Greater)
  with a sensible `alphaReferenceValue`, not blend 1.
- `blendType` / `alphaTestType` / `useDrawCallAlphaState` are **material fields, not conf keys** — confirmed
  against the recovered option list below, where all three are absent. They can only be set through the C
  API, so the fix belongs in `scene_from_frame.py` and the probe, not in `rtx.conf`.

## Shader blobs no longer depend on launch options (2026-10-27, late)

`shader_capture.h` now defaults its output directory to **`<exe dir>\NIER_CAPTURE\shaders`** instead of
requiring `NIER_SHADER_DIR`. The 14:0x game capture produced 3 185 draws but **zero** blobs because the
variable never reached the process — the hook was fine, the delivery method was not. Behaviour now:
`NIER_SHADER_DIR=<path>` still overrides, `NIER_SHADER_DIR=off` disables the hook, and with neither set a
normal Steam launch records bytecode.

Verified two ways before deploying: the gate `test_shader_capture.py` passes, and a manual mock run with
`NIER_SHADER_DIR` **removed from the environment** wrote 2 blobs into `<work>/NIER_CAPTURE/shaders/`
(`ps_56944128.dxbc` 376 B, `ps_2380208.dxbc` 660 B).

**Installed in the game: `d3d11.dll` = `a16e820e39db4786…`** (was `f8a416d8…`). Receipt and previous DLL in
`backups/ingame-menu-shaderdefault-20261027T143734Z/`; `d3d11_dlaa.dll` unchanged (`3d628eb5…`).

**So the next game run needs nothing but F9** — no launch options, no env. It will produce draws, per-draw
state, `ps_hash`, **and** `ps_*.dxbc` in one go, which is everything the cutout path and the black-dress albedo
work were waiting on.

## Session end state (2026-10-27) — read this first

**Installed in the game:** `d3d11.dll` = **`f8a416d8…`** (menu + capture + per-draw state + PS bytecode hook),
`d3d11_dlaa.dll` = `3d628eb5…` untouched. Rollback: `backups/ingame-menu-state-20261027T140214Z/` with
`receipt.json`. Two game captures exist under
`/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_21396979` and `frame_21565698`
(3 276 / 3 185 draws, ~50 GB each, `ps_hash` **and** `state` present). **No `ps_*.dxbc` blobs yet** —
`NIER_SHADER_DIR` did not reach the process, so the cutout/discard half of that capture is still unused.

**Copy-type sweep — the copy path is dead for a foreign D3D9 device, not merely empty:**

| `CopyRenderingOutput` type | result |
|---|---|
| 0 `FINAL_COLOR` | black |
| 1 `DEPTH` | black |
| 2 `NORMALS` | black |
| 4 `GUI` | **fails at the copy call**, returns `vk_image=0x0` |

Type 4 failing is the expected refusal (`combineGuiInFinalColor=1` makes the GUI copy illegal — decoded earlier
from `0x18020eeb0`), which is a nice independent confirmation that the disassembly reading was right. All
three legal types returning pure black on a surface that `dxvk_GetVkImage` maps to a real VkImage means the
copy is not delivering content for a device we created, even after `dxvk_RegisterD3D9Device` (rc accepted) and
`dxvk_SetDefaultOutput` (rc accepted).

**New probe controls added this session** (`triangle.cpp`, exe `4d8f792f…`, rebuilt and built clean):
`REPROBE_INTEROP_TYPE` (which copy type to request), `REPROBE_SWAPCHAIN` +
`REPROBE_NO_VKSWAPCHAIN` (external-swapchain probe; this route **crashes**), and `dxvk_RegisterD3D9Device` is
now called after `CreateDeviceEx` and reported as `registered=`.

**Probe must be run under plain `wine`, not `proton run`, with `DISPLAY=:1` and `XAUTHORITY` set** — Proton
drops the child's stdout and Wine needs X to create its window (`CreateWindow error 1400` otherwise). Both are
now handled by `run_desktop.sh`.

**Gates:** 28 green (19 checks + 8 probe + `test_scene_cutout.py`), `build.py --scene` clean at `4d8f792f…`.
Nothing is committed to git — 29 files modified/untracked.

**Next, in order:** (1) run the identical interop probe on the Spark (NVIDIA RTX + ARM64 runtime) — needs an
aarch64 Windows toolchain, which is **not installed** here, so it starts with `llvm-mingw`/`lld` setup; that one
test decides whether the copy failure is AMD/Proton-specific or inherent to the API. (2) Re-capture with
`NIER_SHADER_DIR` reaching the process, to unblock cutouts. (3) If (1) also fails, live Remix is blocked at the
transfer step on every documented route and the honest answer to "live" is "not with this API build".

## Interop: all three documented extraction routes fail on this build (2026-10-27, measured)

Three experiments, all on the desktop (9070 XT, RADV, plain wine, 430x180, textured camp scene):

| route | call sequence | result |
|---|---|---|
| A1 | `dxvk_CreateD3D9` → `CreateDeviceEx` → render target → `CopyRenderingOutput(FINAL_COLOR)` → `GetRenderTargetData` | **ok=0, image entirely black** (mean_luma 0.0000, nonblack 0.0000) |
| A2 | A1 + `dxvk_SetDefaultOutput(FINAL_COLOR, black)` first | `set_default_output_rc=0` (accepted), **still black** |
| A3 | A2 + `dxvk_RegisterD3D9Device(device)` | `registered=1` (accepted), **still black** |
| B | `StartupInfo.forceNoVkSwapchain=1` + `dxvk_GetExternalSwapchain(image, semDone, semResume)` | **crashes** — stack `remix-scene.exe+0x1456 / kernel32+0x11709 / ntdll+0x1116f`, no `swapchain.txt` written |

`dxvk_GetVkImage(surface)` **does** return a non-zero handle every run (`0x5555…`), so the surface is a real
Vk-backed D3D9 surface; only the *content* of the copy is absent.

**Side effect worth noting, unverified:** registering the D3D9 device changed the measured rate from ~42 fps to
**~59 fps** at 180p, which is suspiciously close to the probe's own 62 fps submit cap. A plausible reading is
that Remix stopped rendering into its own swapchain once a foreign device was registered, and simply
free-ran. That would also explain the black copy. If true it means the copy route requires Remix to keep
owning presentation, and the *destination* surface must be one it knows about.

**What this means for live Remix:** the blocker is now precisely the transfer step, not scene submission and
not presentation. Every documented way to get the composited frame out — copy to a D3D9 surface, copy with a
default output set, copy after registering the device, or take the external VkImage — fails or crashes on
this runtime build.

**Next discriminators:** (1) try `CopyRenderingOutput` with the other types (DEPTH, NORMALS, GUI) into the same
surface, to see whether *any* type produces pixels — that separates "copy is broken" from "FINAL_COLOR has no
content"; (2) run the identical probe on the Spark (NVIDIA + ARM64 runtime) to decide whether this is an
AMD/Proton/Wine-wrapper limitation or a property of the API itself.

## Desktop probe works again — and the interop probe returns its first real answer (2026-10-27)

**Why every desktop run today silently produced nothing:** this shell has no `DISPLAY`/`XAUTHORITY`, so Wine
failed with `CreateWindow error 1400` *after* initialising the runtime fine — and Proton drops the child's
stdout, so the message never surfaced. `run_desktop.sh` now exports `DISPLAY=${DISPLAY:-:1}` and
`XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}`. **Run the probe under plain `wine`, not `proton run`:** wine
preserves stdout, so `stage()` lines and the `Interop:` line are visible live (1429 lines captured vs none).

**First native desktop numbers** (`remix-scene.exe`, textured camp scene, 2.7M triangles, 430x180):
**~42 fps steady** (41.3 -> 42.1 over 90 s). Note the probe's own `hold_delay_ms=16` floors it near 62 fps, so
42 fps is real GPU-bound throughput at 180p — the first valid framerate datapoint for this card, and the
baseline for "is live viable" once scaled to the real resolution.

**Interop probe result — the mechanism works, the pixels do not (yet):**

```
ok=0 stage=copied image is black vk_image=0x5555725649d0 mean_luma=0.0000 nonblack=0.0000 size=430x180
```

Reading it precisely: `dxvk_CreateD3D9`, `CreateDeviceEx`, `CreateRenderTarget`, `CreateOffscreenPlainSurface`,
`dxvk_CopyRenderingOutput(target, FINAL_COLOR)`, and `dxvk_GetVkImage` **all succeeded** — and `GetVkImage`
returned a **non-zero handle** (`0x5555725649d0`). The only failure is that the copied surface is entirely
black. So the cross-API plumbing is real; what is missing is content in the copy.

**Two concrete next experiments, in order:**
1. Call `dxvk_SetDefaultOutput(FINAL_COLOR, …)` before Present — the API's member exists and has never been
   exercised by us; the copy may only be valid once the runtime knows what its default output is.
2. Start with `StartupInfo.forceNoVkSwapchain = 1` and use `dxvk_GetExternalSwapchain(out_vkImage,
   semRenderingDone, semResume)`, judging success by a **non-zero image** (it returns success with a null
   image when the flag was not set).

## Deployed: today's capture build is now installed in the game (2026-10-27T14:02Z)

`d3d11.dll` in the game is now **`f8a416d858cf3001e66b2d17…`** (was `b32f6f5f76e0d773…`). It adds, over the
previous install: per-draw **blend / depth-stencil / rasterizer state + DSV format** (`draw_capture.h`
`Record::State`, read with ordinary context getters — no vtable hooks) and the **pixel-shader bytecode hook**
(`shader_capture.h`, opt-in via `NIER_SHADER_DIR`). `d3d11_dlaa.dll` is unchanged (`3d628eb5…`).

Rollback chain: `backups/ingame-menu-state-20261027T140214Z/` with `receipt.json` (hashes of the replaced
`d3d11.dll` `b32f6f5f…`, `NIER_RENDER.ini`, `NIER_DLAA.ini`). Restore is one copy:

    cp backups/ingame-menu-state-20261027T140214Z/d3d11.dll \
       /mnt/second/SteamLibrary/steamapps/common/NieRAutomata/d3d11.dll

Capture environment: shader blobs are written only when `NIER_SHADER_DIR` is set, and because the hook runs
inside Wine it needs a **Windows path** — Steam launch options:
`NIER_SHADER_DIR=Z:\home\suraj\Projects\Nier-Automata-Rendering\analysis\runtime\shader-capture %command%`.
Host dir already created. F9 captures keep landing in the game directory as `frame_<tick>/`.

**Risk to watch on the first run:** `shader_capture` installs a vtable hook on `CreatePixelShader`, which has
only been exercised against wined3d in the mock, never against DXVK or the real game. If the game fails to
start or crashes early, the rollback above is the first thing to try — and that result is itself informative.

## NieR graphics bootstrap located via REA snapshot (2026-10-27)

Snapshot of the **game** now exists (`analysis/snapshots/NIER_game_20261027.json`, `target.sha256 = 44ee2dc0…`,
`entries: 0` by design — REA stores the binding, the dossiers are cached in the provider). Each `rea function`
query takes ~170 s and writes ~0.5–1.2 MB to `analysis/runtime/rea/fn_<addr>.json`.

**Found, with decompiled evidence:**

- `FUN_14025c590` = **device bootstrap**. Its callees include `D3D11.DLL::D3D11CreateDevice` and
  `DXGI.DLL::CreateDXGIFactory`; it takes an **HWND** parameter; it reads `%sGraphic.ini` with
  `GetPrivateProfileStructA("Graphic","VideoCard",…)` and `("Graphic","Output",…)`, i.e. the same ini the
  display work touched. Caller chain: `0x14025c590` ← `FUN_1402530f0` ← `FUN_1402496f0`.
- `FUN_14025e300` = **adapter selection**, decoded from its vtable offsets (no symbols needed):
  `(**(code **)(**(longlong **)(param_1 + 0x50) + 0x38))(factory, i, &adapter)` loops until
  `-0x7785fffe` (**DXGI_ERROR_NOT_FOUND**) — offset **0x38 = slot 7 = IDXGIFactory::EnumAdapters**; then
  `(**(code **)(*adapter + 0x40))(adapter, &desc)` — offset **0x40 = slot 8 = IDXGIAdapter::GetDesc**, filling
  a `DXGI_ADAPTER_DESC` to match the `VideoCard` ini entry. `param_1 + 0x50` holds the DXGIFactory.
- Eliminated: `FUN_14025bf50` (16 instrs), `FUN_140253040` (40 instrs), `FUN_14025e4f0` (no indirect calls) —
  none touch graphics.

**Not yet found: swapchain creation and the Present call site.** `FUN_14025c590` contains exactly one indirect
call (a release-style `(**(code **)*obj)(obj,1)`), so the swapchain is **not** created there; the remaining
candidates are its other callees (`0x1402586f0`, `0x14025c360`, `0x140255600`, `0x1402615f0`, `0x14026ef00`).
The next cheapest signal is an indirect call at factory vtable offset **0x50 = slot 10 = IDXGIFactory::CreateSwapChain**.

**Method cost, for planning:** hand-walking a 37 856-procedure graph at ~170 s per query is not viable. Batch
3–4 candidate functions per call, and prefer vtable-offset decoding in the pseudocode over name searching —
no symbol in this binary is named `SwapChain` or `Present`, so name search returns zero by construction.

## Prior art: nobody has done this, and the closest attempt fails at presentation (2026-10-27, researched)

A sourced research pass (tags: EVIDENCE / INFERENCE / NO EVIDENCE) settles the "has anyone done it" question:

- **The only published non-D3D9 Remix host is NVIDIA's own `rtx-remix-minecraft`** — a Fabric mod reaching the C
  API through a JNI shim. It is **Windows-only and RTX-only**: "the JNI bridge is compiled with MSVC, so there is
  no Linux or macOS build", and it requires "an NVIDIA RTX GPU, 30-series or newer"
  (`docs/GETTING_STARTED.md`). Not a route for AMD or Proton.
- **No D3D11 or D3D12 host exists, official or community**, and NVIDIA closed the request **not planned**
  (rtx-remix issue #322): "needing to be able to reconstruct a scene based on the data passed to a game's
  arbitrary shaders" and "our current priority is to keep focus on DX9 games". Our capture approach sidesteps
  exactly the objection they name — worth remembering, because it is the only reason this is not simply
  disallowed by design.
- Every other public `remixapi` consumer found is D3D9 (l4d2-rtx/p2-rtx via `bridge_initRemixApi`,
  NVIDIA's bridge-remix, Kim2091's wrappers), and the Toolkit is an asset authoring app, not a host.
- **The proposed presentation route is D3D9-shaped by construction.** `dxvk_CopyRenderingOutput` takes an
  `IDirect3DSurface9*`, so pixels must land in a surface from a Remix-created D3D9 device and then cross to the
  game's DXVK D3D11 device — a combination no source documents (**INFERENCE**, moderate).
- **The closest existing attempt fails at presentation, before AMD is even involved:** under Proton on NVIDIA, the
  Minecraft host initialises, loads NGX and draws the Remix UI, but "the game scene is black"; the reporter asks
  what the runtime needs from the presentation path under Wine/Proton (issue #1122). The single AMD-on-Linux
  datapoint is a startup crash on an RX 7900 XTX, closed not planned (issue #1029) — a fork that "does not
  support Linux", so neither side is a controlled test.
- **NO EVIDENCE** anywhere of Remix path tracing succeeding under Wine/Proton on AMD, or of a D3D11-injected Remix
  feed. **Demonstrated working under Proton:** D3D11 proxy/overlay hooks (ReShade), and D3D9 Remix mods on NVIDIA.

**What that changes:** the D3D11 `Present` hook is the cheap, well-precedented step (ReShade, SpecialK, and for
this game specifically `xkk-i/nier-mod-loader` already ships a `d3d11.dll` proxy). The chain that is most likely
to die is scene → frame → **cross-device transfer** → backbuffer, and we are attempting it on hardware where the
one prior attempt already stalls. That should be priced in to any decision to pursue live Remix rather than
stills.

## Snapshot provenance: corrected, and NieR's graphics-init anchors found (2026-10-27)

**Correction to a premise I introduced this session.** I briefly treated `analysis/snapshots/*.json` as snapshots
of the *game* and built a hash gate to check them against `NieRAutomata_win10.unpacked.exe`. They are not:
both record `target.sha256 = f1c77c58…` and `executable_role: shared-library`, and they are named
`NIER_DLAA_*` because they are snapshots of the **closed mod DLL**. That is what earlier sessions used them
for (shader extraction, camera/motion continuation, FSR4 routing, the upscaling patch), so **those conclusions
are unaffected and stand**. The real consequence is narrower: **there is no snapshot of the game exe**, so any
NieR-side question (present/HUD) needs a fresh analysis rather than a `--snapshot` query.

Also worth knowing: passing `--snapshot` **rewrote** `NIER_DLAA_upscaling_offline_20261019.json` (mtime
2026-10-27 11:55, 24 452 904 → 24 461 085 bytes). `analysis/snapshots/` is gitignored so git is unaffected, but
that file is no longer byte-identical to what earlier sessions analysed.

**NieR graphics-init anchors (verified by disassembly, not by report).** The exe imports exactly two graphics
entry points and no `Present` — Present is a COM vtable call, so it has no IAT entry:

| import | IAT slot | call site | instruction |
|---|---|---|---|
| `dxgi.dll!CreateDXGIFactory` | `0x140c1b720` | **`0x14025c6b8`** | `call [rip+0x9bf062]`, preceded by `lea rcx,[0x140db1478]` (an IID) and `lea edx,[rsi+0x50]`, followed by `test eax,eax; js` |
| `d3d11.dll!D3D11CreateDevice` | `0x140c1b710` | **`0x14025c95c`** | `call [rip+0x9bedae]`, after `mov QWORD PTR [rsp+0x68],1` and `xor edx,edx` |

Both live in one function region (`0x14025c6xx-0x14025c9xx`), i.e. a single graphics-init routine creates the
DXGI factory and then the device. The swapchain and the Present call hang off that, and must be found by
following the factory's vtable, not by import xref.

**Tool bug fixed:** `analysis/tools/xref.py` assumed every rip-relative operand belonged to a 3-byte `lea` and
therefore reported **off-by-one** addresses when the reference was a 2-byte `call [rip+..]` (`FF 15`). It now
picks the prefix from the preceding opcode bytes and re-decoded correctly to `0x14025c95c` / `0x14025c6b8`.

## HDR sky + NRD inventory applied (2026-10-27)

**Equirectangular RGBA16F sky shipped.** `scene_from_frame.py` gained `sky_dds_hdr()` (128x64, full 8-level mip
chain, `DXGI_FORMAT_R16G16B16A16_FLOAT = 10`, TEXTURE2D, one array slice, zenith-to-horizon gradient), selected
by `REPROBE_SKY_HDR=1`; the existing 8x8 RGBA8 writer and its assertions are untouched. Gate assertion added and
passing. A cloud scout validated it before I applied it by running the patched converter against a real capture
with and without the flag - and caught that `os` was not imported in that file. **Purpose: this variant tests
whether the dome crash is about the texture (size/format/mips) rather than the textured-dome path.**

**NRD inventory (for the first real denoise run).** NRD is disabled outright if `GetLibraryDesc`'s
major/minor/build disagree with `NRD_VERSION_MAJOR/MINOR/BUILD` (`rtx_nrd_context.cpp:86-89`). Those constants are
**not** in the public repo - they come from the external `NRD.h`, which is not vendored - but the package pin is
**`rtx-remix-nrd` 4.13** (`packman-external.xml:38-39`), so major/minor are almost certainly 4/13 with the build
number unknown (INFERENCE). The UI prints the loaded version as `NRD v%u.%u.%u`
(`rtx_nrd_settings.cpp:278`), which makes the first run's log a free way to confirm it without touching anything.

## Built offline (2026-10-27, this session) — two of three workstreams done, all gates green

**1. Rect-light ambient — DONE, builds clean (`0025f9c2…` then `30f2c6fc…` successive).**
`triangle.cpp` creates a `remixapi_LightInfoRectEXT` (400x400, 60 units up, aimed down) as an opt-in ambient
stand-in, submitted with `DrawLightInstance` every frame and destroyed on teardown. Enabled with
`REPROBE_AMBIENT=<radiance>`; off by default so nothing changes for existing runs. Comment records that the
emit direction convention and the radiance units are both undocumented and must be swept on the GPU.

**2. Cutout classification end to end — DONE, gated.** The scene format stayed **v3**: the cutout flag rides
in **bit 1 of the `skinned` table field**, which was safe to reuse because the probe has never read that
field at all. Net effect:
- `scene_from_frame.py` gained `load_discard()` (accepts `dxbc_disasm` stdout verbatim: `DISCARD ps_<id> 1`,
  or plain `ps_<id> <0|1>`) and a `--discard-file` flag. Flagged draws get `skinned |= 2`.
- `triangle.cpp` builds an **alpha-tested twin material** per albedo (`alphaTestType = 4` = `kGreater`,
  `alphaReferenceValue = 128`, `blendType` unchanged) and picks it when `d.skinned & 2`.
- Default output is **byte-identical**: a stale or absent discard list leaves the scene bytes unchanged, so
  every existing fixture, capture and the byte-exact scene gate are unaffected. Verified by test.
- New gate `test_scene_cutout.py` (3 checks): discard-list formats and junk rejection, byte-identity under a
  stale list, and that converter and probe agree on bit 1. It caught a real bug immediately — `ps_-3`
  parsed to a negative id — which is fixed.

**3. Blend/depth state capture — NOT STARTED.** Slots are verified (`OMGetBlendState` 91,
`OMGetDepthStencilState` 92, `RSGetState` 94, from `d3d11.h:6200`, independently recounted by the lead), but
the hook, the per-draw struct, the JSON fields and the mock-game assertions are all still to write. This is
the one piece of the three that was not built.

**Gate status: 19 checks + 8 probe gates green (27 total).** `test_scene_cutout.py` is the 27th.

**What the first real F9 capture unlocks immediately:** `scene_from_frame.py <frame> scene.bin
--discard-file <dxbc_disasm output>` now produces a scene whose foliage and hair are alpha-tested in the
probe, with no further code.

## Three implementation plans ready to apply (2026-10-27, end of session)

Cloud scouts produced read-only plans; **the lead verified the ABI facts independently** before trusting
them. Artifacts live under
`~/.pi/agent/sessions/--home-suraj-Projects-Nier-Automata-Rendering--/subagent-artifacts/`
(`57da386d…_scout_output.md` cutouts, `7a067642…_scout_output.md` rect light, `05ed55bf…_scout_output.md`
vtable slots).

**D3D11 slots — verified by my own count of `d3d11.h`, not accepted on report.** Block opens at
`d3d11.h:6200` (`ID3D11DeviceContext : public ID3D11DeviceChild`), 108 methods, first is slot 7
(IUnknown 0-2, DeviceChild 3-6):

| method | idx | slot | header |
|---|---|---|---|
| VSGetConstantBuffers | 66 | **72** | 6520 |
| PSGetShader | 68 | **74** | 6530 |
| VSGetShader | 70 | **76** | 6540 |
| PSGetConstantBuffers | 71 | **77** | 6545 |
| OMGetBlendState | 85 | **91** | 6615 |
| OMGetDepthStencilState | 86 | **92** | 6620 |
| RSGetState | 88 | **94** | 6628 |

**Gotchas found by the plans that will bite if missed:**

- The shader blobs land in a **flat directory from `NIER_SHADER_DIR`**, *outside* the frame tree
  (`shader_capture.h:41-51`), so the converter cannot assume `frame_dir/shaders/`; the walk needs the env
  path or a captured manifest.
- `dxbc_disasm` **exits non-zero on the first unreadable or undisassemblable blob**
  (`dxbc_disasm.cpp`), so one corrupt shader aborts a batch — the converter must tolerate per-shader failure
  rather than treat a non-zero exit as "no cutouts anywhere".
- `alphaTestType` is a bare `int` and `alphaReferenceValue` a `uint8_t` (`vendor/remix_c.h:255-256`); the
  vendored header does **not** name the enum values, which are pinned in this file as `VkCompareOp`
  (Greater = 4, default Always = 7).
- `remixapi_LightInfoRectEXT` carries **geometry only** — no radiance. Radiance lives on the parent
  `remixapi_LightInfo` (`{sType, pNext, hash, radiance}`, `vendor/remix_c.h:700-707`), and its **units are
  not documented anywhere reachable** — must be found empirically, which is another reason the next GPU run
  should sweep rect-light radiance.

**Next action:** apply the cutout wiring (converter + NSCN v4 + probe), then the rect light, then the state
capture using the verified slots. All offline; the GPU sitting is unchanged.

## The four divisions, analysed (2026-10-27, final state of the session)

Two agents ran on the extracted disassembly; the lead re-verified the mechanical half.

**Ranking from the analysis** (fixed schema per site):

| site | divisor | how zero arises | likelihood it is our fault |
|---|---|---|---|
| `0x18021befc` | `([rdi+0x10] - [rdi+0x8]) >> 3` — **element count of a `std::vector`** | **empty container** — the most ordinary divide-by-zero shape | **moderate-high** |
| `0x1802196a7` | `[rcx+0x114]` struct field | field never populated on this path | low-moderate |
| `0x18021cd13` | `[rbp-0x48] + 1` | only via `-1` wrap on the source | not read in full |
| `0x18021d9cd` | `[rcx+0x18]` struct field | field zero | not read in full |

Worth recording: in all four the `inc` sits on the **dividend**, not the divisor, so it neither protects the
divide nor creates the zero — my earlier "`-1` → `inc` → `0`" hypothesis for site 3 is not supported by the
instruction placement.

**Real function starts** (the naive "last `int3` before the address" heuristic is wrong here): the `int3`
bytes at `0x18021be5f`, `0x18021c4xx` and `0x18021d0ex` are **assert/fail trampolines inside a function**, of
the shape `jbe <cont>; call [0x1806b41f0]; int3; <cont>: ...`. Verified by disassembly. True starts:
`0x18021bc00` (site 2), `0x18021c420` (site 3), `0x18021d0f0` (site 4), `0x180219670` (site 1).

**Next step, bounded:** identify what the vector at `0x18021befc` holds by tracing the enclosing function
`0x18021bc00` — if it is a per-frame light or sky-image list, then a dome light whose texture registration
produced no entries is a concrete, testable explanation for the crash.

## Sky, corrected twice: the C API cannot fill the sky probe (2026-10-27, later)

The previous section in this file says "the fix is geometry, not a light: submit the sky as SKY-tagged
instances". **That is wrong**, and the local source proves it:

- `RtxContext::commitExternalGeometryToRT` (`rtx_context.cpp:1060-1061`) calls only
  `SceneManager::submitExternalDraw`. It does **not** call `tryHandleSky`.
- `tryHandleSky` is reached only from the D3D9 geometry path (`commitGeometryToRT`, `rtx_context.cpp:1018`)
  and, with nulls, from `flushCommandList` where it can only flush a delayed reprojection.
- The API's `REMIXAPI_INSTANCE_CATEGORY_BIT_SKY` bit therefore selects **which camera** the instance is
  transformed by (`convert::categoryToCameraType`, `rtx_remix_api.cpp:661-668`), not whether the sky probe
  is rasterised.

**So an API-only client cannot populate the sky probe at all.** That retires both "use NieR's sky shells via
`REPROBE_SKIP_MAX`" and "tag instances as SKY" as answers to the *ambient* problem. They remain useful for
drawing sky geometry, not for lighting the scene.

**What the one pure-API NVIDIA client actually does** (rtx-remix-minecraft): it publishes a
`LightInfoDomeEXT` with an **equirectangular HDR** texture for the visible sky, plus a **very large
`LightInfoRectEXT`** as a stand-in for sky ambient, and flags only sun/moon/star quads as SKY. That is the
shape our probe should copy:

- `remixapi_LightInfoRectEXT` **exists in our vendored header** (struct type 10, `vendor/remix_c.h:614`,
  with X/Y axis and direction fields), and `rectLight` appears 3160 times in the shipped runtime, so area
  lights are supported by this build.
- A large, dim rect light (or a few) is therefore the cheapest route to ambient without the probe, and it
  does not touch the dome-texture path that crashes.

**Consequence for the next run:** compare (a) current: sun only, no ambient; (b) sun + large dim rect light;
(c) sun + rect + dome with an equirect HDR DDS. That A/B answers the ambient question without needing the
probe, and skips the crash path entirely.

## Sky: the dome was never going to light the scene (2026-10-27)

A sourced research pass changes the plan. Remix's sky has two separate pieces, and we only ever drove the
wrong one:

- **`COMPOSITE_SKY_LIGHT_TEXTURE`** (a `SAMPLER2D`) is bound from the dome light's `colorTexture`. It paints
  **sky pixels on primary misses only**.
- **`COMPOSITE_SKY_PROBE_TEXTURE`** (a `SAMPLERCUBE`) is the thing that provides **ambient / indirect light**,
  and it is rasterised **only from geometry tagged `REMIXAPI_INSTANCE_CATEGORY_BIT_SKY`** (via
  `categoryToCameraType` → `RtxContext::tryHandleSky` → `rasterizeSky()`), never from a light.

That explains both recorded failures: a dome with a NULL `colorTexture` yields no texture-table entry, so
the dome is inactive and there is **no sky light at all**; and even a working dome leaves indirect lighting
reading an empty sky probe, which is why the stills look ambient-less and washed out.

**So the fix is geometry, not a light:** submit the sky as SKY-tagged instances. We already have real sky
geometry in the capture — NieR's own 10-19 km sky shells that `REPROBE_SKIP_MAX` currently discards — and the
community workaround in `rtx-remix` issue #525 is the same idea (a large prop-anchored sphere marked as sky).
Sky-side knobs that exist and are now worth setting: `rtx.skyBrightness`, `rtx.skyProbeSide` (default 1024),
`rtx.skyForceHDR`, `rtx.skyUseProbeForPrimaryRays`, `rtx.skyAutoDetect`, `rtx.skyDrawcallIdThreshold`,
`rtx.skyMinZThreshold`. There is **no** `rtx.atmosphere` sky/IBL feature —
`rtx.volumetrics.enableAtmosphere` only makes the volumetric fog shell finite.

**The dome crash is not the known upstream bug.** The runtime's PE timestamp is **2026-10-21**, i.e. after
REMIX-5443 ("Fix getDomeLightArgs returning active if dome light does not exist", June 2026), so this
divide-by-zero is a *different* fault and still unexplained. A division scan of the Present-region range
`0x18020e000-0x180240000` finds **10** divisions: six are chrono/timing (`imul ... 0x3b9aca00` / `0x64`
beforehand), and four sit in the render region at `0x1802196a7`, `0x18021befc`, `0x18021cd13`,
`0x18021d9cd`, each preceded by `xor edx,edx` and an `inc`. **Next step: identify the divisor register at
those four** — that is a bounded, offline job.

**Delegation note:** the desktop worker was given this scan as a fixed-schema task and returned nothing
usable (its artifact held one line, "Delivered. Final answer above"). Recorded in the ledger as a failed
deliverable; the lead ran the scan instead. The cloud researcher's report was strong and is the basis of
this section.

## Dome-light crash: not memory, not the DDS parser (2026-10-27)

The recorded explanation for the dome-light crash — "`0xC0000094` inside Present, probably memory, source's
only divisor on that path is the DDS parser's `(extent + blockExtent - 1) / blockExtent`" — is **wrong**,
and the stored run dumps prove it. In both crashing runs (`sky-v3`, `sky-v4`, exit
`0xC0000094` = EXCEPTION_INT_DIVIDE_BY_ZERO, no thread dump because the process died instantly) stdout reads:

```
end CreateSky -> 0            <- the dome DDS parsed and the light was created successfully
Frame 0
end SetupCamera -> 0 ... end DrawInstance -> 0 ... end DrawLightInstance -> 0
end DrawSky -> 0              <- the frame was submitted
begin Present                 <- fault here
```

So the DDS parse succeeded, the scene submitted, and the divide-by-zero is a **Present-path bug**, not a
texture-format or memory problem. It is deterministic and reproduces with a 1x1 texture, which also rules
out the "too big / out of unified memory" theory.

The only code that runs *additionally* when a dome light carries a colour texture is at
`rtx_composite.cpp:390-397`: the composite samples `COMPOSITE_SKY_LIGHT_TEXTURE` from the texture table when
`domeLightArgs.active && textureIndex != BINDING_INDEX_INVALID`, and otherwise falls back to `getSkyMatte`.
That branch has no division of its own, so the divisor is downstream in the composite dispatch. Next step:
disassemble `Present` (interface `+0xa0` → `0x18020e3e0`) into the composite dispatch and find the `idiv`
reached only on the textured-dome path. **Cheaper alternative that avoids the bug entirely:** include
NieR's own sky shells as geometry via `REPROBE_SKIP_MAX`, which needs no dome texture at all.

## Source-vs-binary calibration (2026-10-27) — the source conclusions transfer

Every conclusion in this document that came from reading the public dxvk-remix source is only valid for
the installed runtime if that runtime contains the same logic. Ten exact strings were probed in
`.trex/d3d9.dll`, and **all ten are present**:

| string | what it calibrates |
|---|---|
| `Neural Radiance Cache is not supported` | the NRC fallback path exists in this build |
| `Switching indirect illumination mode to ReSTIR GI` | the fallback target is ReSTIR GI, as read in source |
| `SHaRC requires shaderInt64` | the SHaRC gate |
| `Unsupported indirect illumination mode selected` | the mode-range guard |
| `Required extension not supported` / `VK_NVX_binary_import` | the NRC vendor/extension gate |
| `Unable to load NRD` / `Incorrect version of NRD` | the NRD load and version gates |
| `useDenoiserReferenceMode` | the flag that disabled denoising |
| `DLSS 3D-Guided Neural Rendering` (x10) | DLSS-NR is a real feature of this build |

So the shipped runtime is *recent* (it carries DLSS-NR, NRC, NRD) even though its remixapi version is
0.6.5 — the API version does not track source recency, and the public source is a safe oracle for behaviour
here. It also means the runtime's own warnings are usable as an oracle during a run: if NRC were requested
we would see the ReSTIR GI warning, and the absence of any NRD error means the DLL loaded fine (as
established earlier).

## Research round: NRC is unavailable here, and the fallback is not what was claimed (2026-10-27)

Three agents were sent at the open questions; every load-bearing claim was then re-checked against the
source on this disk. **One agent claim was wrong and one of my own recommendations died.**

**NRC cannot run on this hardware.** `NrcContext::checkIsSupported` (`rtx_nrc_context.cpp:140`) requires
`VK_NVX_binary_import` and `VK_NVX_image_view_handle` — NVIDIA-only Vulkan extensions that RADV does not
implement — plus an NVIDIA driver >= 565.90 for the CUDA runtime in the NRC SDK. So my earlier "NRC is the
most promising untested noise lever" was wrong, and it is now closed rather than queued.

**The fallback is ReSTIR GI, not ImportanceSampled.** An agent reported that asking for NRC on AMD silently
rewrites `rtx.integrateIndirectMode` to `ImportanceSampled` (mode 0, the noisiest, reference-only mode). The
code says otherwise — `RtxContext::checkIndirectLightingSupport` (`rtx_context.cpp:1598`):

```cpp
if (integrateMode == IntegrateIndirectMode::NeuralRadianceCache && !NeuralRadianceCache::checkIsSupported(...)) {
  Logger::warn("[RTX] Neural Radiance Cache is not supported. Switching indirect illumination mode to ReSTIR GI.");
  RtxOptions::integrateIndirectMode.setImmediately(IntegrateIndirectMode::ReSTIRGI, RtxOptionLayer::getQualityLayer());
}
```

It is a *warning*, not silent, and the fallback is **ReSTIR GI (1)**. The practical conclusion survives in
weaker form: the default mode is **SHaRC (3)** (`rtx_options.h:496`), so setting NRC on this host would
downgrade to ReSTIR GI. **Do not set `rtx.integrateIndirectMode = 2` here.** Enum order verified:
`ImportanceSampled=0, ReSTIRGI=1, NeuralRadianceCache=2, SHaRC=3`.

**Verified option facts** (source-confirmed, no longer guesses): `rtx.autoExposure.evMinValue` float default
**-2.0**, `rtx.autoExposure.evMaxValue` float default **5.0** (GUI slider clamps to ±24; the shader receives
`evMax - evMin`); `rtx.enableCullingInSecondaryRays` bool default **false**;
`rtx.denoiseDirectAndIndirectLightingSeparately` and `rtx.useDenoiserReferenceMode` both default **false**.
Note the separate, differently-scoped `rtx.debugView.evMinValue` is an int (-4..4) — not the exposure knob.

**Interop research (reported, only partly verifiable here).** For live Remix the claimed working path is not
a cross-device `VkImage` handoff: DXVK's D3D9 shared surfaces are created with the legacy
`VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_KMT_BIT` global handle rather than an NT handle, and the
`dxvk_GetVkImage` handle is only meaningful inside Remix's own device — which matches what the disassembly of
`dxvk_GetVkImage` showed (it returns the surface's backing image, not Remix's output). The suggested route is
therefore: Remix copies into **a shared D3D9Ex render target we create**, and the game's DXVK D3D11 device
opens it with `OpenSharedResource`. DXVK's own wiki labels cross-device sharing "partially supported", and
the D3D9 side in Remix exposes no keyed mutex, so synchronisation is the weak point. A ~19.8 MB per-frame
host readback is a fallback, not a plan (several ms plus a stall).

**Net effect on the next GPU run:** the candidate list is now `enableCullingInSecondaryRays = true` (default
is false, so this is untested and cheap), the corrected NRD conf, and the exposure knobs with known defaults.
NRC is out; DLSS-NR is out (NGX needs an NVIDIA card).

## What this runtime can do, straight from its exports (2026-10-27, static)

**API version: 0.6.5, definitively.** `QueryFeatureVersion` (export `0xf9990`) switches on its first
argument: id 2 returns 1, id 1 returns **0x60005** (major 6, minor 0, patch 5), id 0 returns 2, and any
other id takes an error path that formats the string at `0x1806c5f80`
(`"Could not find feature version for: "`). That independently confirms the 22-member interface and the
`major 6` gate decoded earlier from `remixapi_InitializeLibrary`.

**The status exports are global reads**, not calls into a library — cheap to query and easy to reason about:
- `remixinternal_GetDlssNeuralRenderingStatus` = `return *(int*)0x190d672b0;`
- `remixinternal_GetNrcStatus` reads a pointer at `0x190d9abc0` and returns **-1** when it is null.
`xref.py --va 0x190d672b0` found three writers of the DLSS-NR status global, and the values written are
**only `-1` and `0`** — `mov r14,-1` then `mov [global],r14d` at `0x1802bf895` (an early failure path, taken
when a byte of the feature's argument struct is zero), and `xor r12d,r12d` then `mov [global],r12d` at
`0x1802c0e89` (a teardown/reset path). So the honest reading is: **-1 = feature creation failed, 0 = not
initialised**; nothing in the reachable code writes a positive "ready" value without NGX. That is
consistent with NGX being required and with this host being an AMD card, but it is *not* proof — the
cheap decisive check is one line of code at the next run: read
`remixinternal_GetDlssNeuralRenderingStatus()` and print it.

**Two levers for noise that do not need NGX, both already installed:**
- `NRC_Vulkan.dll` (5.5 MB) is a **static import** of the runtime (`import NRC_Vulkan.dll`), so the Neural
  Radiance Cache is linked in at load time, and `rtx.neuralRadianceCache` exists in this build. Unlike NRD
  it is not gated behind the option we broke, and unlike DLSS it does not require NGX or an NVIDIA GPU.
  **This is the most promising untested noise lever and the top candidate for the next GPU run.**
- `nvngx_dlssnr.dll` (254.1 MB) also ships in `.trex`, so the note "DLSS 5 NR still needs a legitimately
  obtained nvngx_dlssnr.dll" is **out of date**: the file arrives with Portal RTX, which the user owns.
  It is still unusable here because NGX requires an NVIDIA GPU and this host is a 9070 XT.

Options confirmed present in this build by the recovered name list: `rtx.dlssNeuralRendering`,
`rtx.neuralRadianceCache` (plus `neuralRadianceCache.resetSceneBoundsOnCameraCut`), with descriptions in
the binary describing DLSS 3D-Guided Neural Rendering and NRC respectively.

## Capture now records pixel-shader bytecode, so cutouts are decidable (2026-10-27, no GPU)

The next in-game run should answer everything at once, so the capture was extended now rather than after
it. `analysis/checks/shader_capture.h` hooks `ID3D11Device::CreatePixelShader` (vtable slot 15) and writes
each shader as `ps_<id>.dxbc`, where `<id>` is the pointer identity that `draw_capture.h` already records
as `ps_hash` — so shader blobs join to draws with no extra index. Writes only when `NIER_SHADER_DIR` is
set, so an ordinary run never litters the game directory. Installed in `menu_overlay.cpp` next to the
existing input-layout hook; the DLL rebuilds with 51 exports intact and no forbidden imports.

**How `discard` is detected — and how it is not.** Parsing the DXBC token stream by hand was tried and
abandoned in this session: the instruction-length field is not a length for declaration opcodes, an
aligned walk stalls on the first `dcl_*` at `opcode 0x19`, and a plain token scan matched **five**
different opcode values (6, 13, 18, 49, 2038) on the same three fixtures. Any of those would have been a
guess. Instead `analysis/checks/dxbc_disasm.cpp` calls `d3dcompiler_47!D3DDisassemble` — the vendor's own
decoder — and the answer is a text search for `discard` in the disassembly.

Two new gates, both CPU-only, both green:
- `analysis/checks/test_dxbc_discard.py` — compiles three fixtures with D3DCompile in Wine (opaque, one
  discard, two discards), disassembles them, and asserts classification 0/1/1 *and* that the token appears
  0/1/2 times. A garbage `.dxbc` must exit non-zero with a reason.
- `analysis/checks/test_shader_capture.py` — builds the mock game (which now creates a cutout pixel
  shader), runs it against the built DLL under Wine + Xvfb with `NIER_SHADER_DIR` set, and asserts a blob
  was written from a live D3D11 device, that it disassembles as a *cutout*, and that it is a complete
  DXBC container (660 bytes, identical to the fixture).

Also learned and worth not repeating: **Wine refuses a WINEPREFIX under a directory it does not own** —
`/tmp` is root-owned here, so a prefix must live in `$HOME` ("wine: '/tmp' is not owned by you").

The hand-written, unverified `analysis/tools/dxbc.py` was **deleted** rather than left to be trusted.

## Option names recovered from the build (2026-10-27, no GPU)

`RtxOptions.md` only exists after a run and the 2026-10-26 dump is gone, so the option registry was read
straight out of the binary: `analysis/tools/rtx_options.py` (with `--self-check`) recovers the name list
from the description/name stream in `.rdata`, and writes `analysis/RTX_OPTIONS_THIS_BUILD.txt` —
**949 names**, self-check green against nine independently known keys.

What it settles: every key we intend to set exists in this build — `enableCullingInSecondaryRays`,
`useDenoiser`, `useDenoiserReferenceMode`, `evMinValue`, `evMaxValue`, `enableAtmosphere`, `blendMode` —
and `alphaTestType`, `useDrawCallAlphaState` and `blendType` are **not** in the list, which confirms from a
second direction that they are C-API material fields rather than conf keys.

What it does not give: types, defaults, ranges and the `rtx.`-prefixed path. Those still need
`RtxOptions.md`, i.e. a run with `DXVK_DOCUMENTATION_WRITE_RTX_OPTIONS_MD=1`, or a call to the runtime's
`writeAllMarkdownDocs` export. Names alone answer "does this key exist", which is the question that has
been guessed at repeatedly.

## Denoise, measured again offline (2026-10-27)

 — the filter is not the win

New tooling, all CPU-only and gate-tested: `analysis/remix-probe/noise.py` (the metric), `denoise.py`
(methods `box`, `atrous`, `firefly`, `firefly+atrous`), `test_denoise.py` (6 checks). The metric is now
defined in code: mean within-8px-tile luma std, Rec.709 luma, normalised by mean luma. **The historical
0.084 / 0.62x / 0.53x numbers came from an unstated definition and are not comparable to it**; only
ratios within this metric are valid.

Measured on the real v3 textured still (`captures-still-v1-20261026T223556Z`, noise 0.2801):

| method | noise | ratio |
|---|---|---|
| box 3x3 | 0.143 | 0.48x |
| box 5x5 | 0.102 | 0.34x |
| atrous sigma 0.12 | 0.110 | 0.39x |
| firefly only | 0.226 | 0.81x |
| firefly + atrous 0.06 | 0.101 | 0.36x |

Looking at the output decided the question the numbers could not. `atrous` alone smooths the large
fields but **keeps bright speckle**, because an edge-stopping filter treats a firefly as an edge; adding
outlier rejection first fixes that, and the result at 0.36x noise is still grainy *and* now mushy. The
reason is that this frame's dominant defects are not noise: they are the thin-geometry overdraw streaks
and the absent sky (the dome light is still void). So a spatial filter cannot rescue it, and the cheap
renderer-side options matter more than any post-filter:

1. `rtx.enableCullingInSecondaryRays = True` for the streaks,
2. alpha-test/cutout handling for foliage and hair (`blendType` is currently forced to 2),
3. a real sky (NieR's own sky shells via `REPROBE_SKIP_MAX`, or a legacy-DDS dome light).

`dds_stack.py` also refused a single frame although its usage advertises it (fixed: `len(argv) < 2`).

## Denoise: parked, with the evidence (2026-10-26 late)

Every configuration path has now been tried and all of them leave the image at noise ≈0.084 within-block:

| attempt | result |
|---|---|
| `useDenoiser=True` vs `False` | differ by 1 float16 ULP |
| `useDenoiserReferenceMode=True` + `resetOnCameraTransformChange=False` + `numberOfFramesToAccumulate=1024` | 0.0839, unchanged |
| `uniqueObjectDistance=1000000` (camera-cut hypothesis) | bit-identical; the option **does** exist in this build, so the test was valid |
| frame 150 vs 1200 | 0.0843 vs 0.0841 — no temporal convergence |
| averaging two frames | 0.0824 (0.978x; independent samples would give 0.707) |

Source reading rules out the two structural explanations: `rtxImagePostTonemapping` **is** the final post-composite
image (so we are not reading a pre-denoise buffer), and the API path uses the same `RtCamera` bookkeeping as D3D9, so
a static camera cannot trip `isCameraCut()`. What remains is option-layer precedence — a higher-priority layer may
win over `rtx.conf` — which cannot be settled without a debug build or a capture path that works.

**Crashes are probably memory, not code (user observation, 2026-10-26).** Every crash in this round happened on a
long `--hold` at full size, and the renderer at 1028x540 with 2.7M triangles plus 450 MB of textures consumes most of
the laptop's unified memory. Treat the two below as *unverified* — they are not established feature bugs:
- **Dome light with `colorTexture`**: `0xC0000094` inside `Present` on frame 0. Source's only divisor on that path is
  the DDS parser's `(extent + blockExtent - 1) / blockExtent`, zero when the pixel format does not map — so a
  *legacy* DDS with explicit RGB masks is still the thing to try, but only on a small, short run.
- **`rtx.captureDebugImage = True`**: `0xC0000005` after "Test screenshot capture triggered".

**Rule from this: size every run to fit.** `REPROBE_HEIGHT=360`, short watchdogs, models unloaded, and re-check the
feature in a small run before concluding it is broken.

Practical conclusion for stills: **denoise outside Remix** (a box filter measured 0.53x at 5x5), or accept the noise.
Recorded so nobody re-runs these.

## Method: check the reference implementation first

Learned the expensive way on 2026-10-26 after ~15 GPU runs and five research agents: **Portal RTX is installed on
this machine and is a working Remix game.** Before theorising, guessing conf keys or running anything:

1. `PortalRTX/dxvk.conf` and `rtx.conf` — the option names a shipping game actually uses, with working values.
2. `PortalRTX/bin/.trex/bridge.defaults.conf` — 568 lines of shipped defaults.
3. **`DXVK_DOCUMENTATION_WRITE_RTX_OPTIONS_MD=1`** as an env var when launching the runtime: it writes
   `RtxOptions.md` (1041 lines here) listing every option with type, default, min/max and description **for the
   exact binary in use**. This is authoritative and it ends all "does this key exist" guessing — unknown keys are
   never warned about at any log level, so a conf line being echoed means nothing.
4. `strings` on `PortalRTX/bin/.trex/d3d9.dll` for env vars and internal stage names. This is how the
   `rtxImagePostComposite`, `rtxImageDxvkView` and `RTX_TAKE_PRE_PRESENT_SCREENSHOT_FRAME` names were found —
   names that no amount of reasoning had produced.

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
