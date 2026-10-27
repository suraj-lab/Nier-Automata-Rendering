# Live Remix *in NieR* — implementation plan (L1)

## Status 2026-10-27 late: the in-process bridge is PROVEN

`analysis/remix-probe/d3d11_bridge_probe.cpp` (+ `run_bridge.sh`) now demonstrates the complete chain that live
in-game needs, outside the game:

    Remix renders (own VkDevice) -> dxvk_CopyRenderingOutput(FINAL_COLOR) -> D3D9 surface -> CPU
      -> D3D11 texture (DXVK, own VkDevice, same process) -> back to CPU

Measured: `registered=1 startup_rc=5 (ALREADY_EXISTS)`, `d3d11: device ok, feature level 0xb000`,
`RESULT ok size=640x360 mean_luma=0.1037 nonblack=1.0000 bright=0.0765`, and the copied frame is a correctly lit
path-traced triangle. Two Vulkan devices coexist in one process under Proton; the frame crosses D3D9 -> CPU ->
D3D11 without loss. **This was the last structural unknown for live-in-NieR.**

Note: the surface must use the **default material** (`surface.material = nullptr`). The custom-material variant
is the one the record already flags as unproven in this runtime, and it reproduced here (dark frame, no triangle).

Cost of the bridge, measured (`--bench WxH`, which times the D3D11 hop alone):

| hop | 2580x1080 |
|---|---|
| Remix -> D3D9 -> CPU (measured earlier) | 0.49 ms |
| CPU -> D3D11 texture -> CPU (`--bench 2580x1080`) | **1.78 ms** |
| total per frame | **~2.3 ms** (14% of a 16.7 ms budget) |

So a live frame at XeSS Quality (48 fps = 20.8 ms of rendering) plus the bridge lands around 43 fps, and at native
(21 fps) around 20 fps. Arithmetic, not yet measured end-to-end inside the game.

What is left is engineering, not discovery:
1. Warm the geometry/material/texture cache from NieR's own draw stream (cache-first, see below).
2. Draw the uploaded frame in the existing Present hook (fullscreen quad; the proxy already has that pipeline).
3. UI (fallback to the game's frame while a menu is open).

Written 2026-10-27 evening, after the transfer step was proven ([LIVE_TRANSFER.md](LIVE_TRANSFER.md)).
Prerequisites are all in place: the copy route works at 0.49 ms/frame (1080p), the renderer does 53 fps on the
full textured camp scene, and the game's draw stream is already recorded with per-draw state, shader identity
and vertex data.

## Target for L1

NieR runs, our `d3d11.dll` is loaded, and the game's window shows a **path-traced NieR frame produced by the
Remix runtime inside NieR's own process**. Geometry comes from a cache warmed by the game's own draw stream, so
the scene animates. UI is not solved in L1 (see "UI" below); the game's own frame can be shown instead whenever
a menu is open.

## Why not stream the capture

The F9 capture is ~50 GB per frame because it dumps every vertex buffer it sees. At 60 fps that is impossible.
Live submission must be **cache-first**:

| per-draw input | when it is read | per-frame cost |
|---|---|---|
| vertex + index data | once, on first sight, keyed by a hash of the buffer pointer + size + shader | 0 |
| material parameters (albedo/rough/metal, blend, alpha test) | once per hash | 0 |
| textures | once per `tex_<id>` | 0 |
| world/view/projection (per instance transform) | every frame, from the VS constant buffer already hooked | one small read |
| camera + sun/light state | every frame | one small read |
| `DrawInstance` per draw | every frame | ~3 000 calls, CPU-only |

This mirrors what the probe already does: `triangle.cpp` submits the full 2.7M-triangle scene every frame and
reaches 53 fps, so per-frame submission is not the risk. The new work is the cache and the in-process host.

## Components

1. **`analysis/checks/remix_live.cpp/.h`** (new, compiled into `d3d11.dll`), gated by `NIER_REMIX=1`:
   - `LoadLibrary(runtime) → remixapi_InitializeLibrary(version 0.6.5, minor 6 gate)`.
   - `dxvk_CreateD3D9` → `CreateDeviceEx` with a real swapchain **at the game's backbuffer size on a hidden
     window we own** → `dxvk_RegisterD3D9Device` → `Startup` (expect `ALREADY_EXISTS`).
     Order is mandatory; see LIVE_TRANSFER.md "Rules to not rediscover".
   - Per frame: `SetupCamera`, `DrawInstance` × N, `DrawLightInstance`, `Present`.
   - Per frame transfer: `CopyRenderingOutput(FINAL_COLOR)` into a target sized from
     `GetBackBuffer()->GetDesc()`, `GetRenderTargetData`, `LockRect`, upload into a `D3D11_USAGE_DYNAMIC`
     texture. Measured 0.49 ms at 2580x1080; the upload is the same order.
2. **Geometry cache** keyed off the existing `draw_capture.h` record: on first sight of a draw, read the vertex
   and index buffers through the recorded device/context (the same path the offline capture uses, but once) and
   build a `remixapi_MeshInfo` + `remixapi_MaterialInfo`. Reuse `scene_from_frame.py`'s semantics — albedo
   selection, `blendType` 0/1/2, cutout via `ps_hash` (`discard`) — but in C++, driven by the same rules, and
   keep the Python converter as the reference the C++ must agree with (a gate can compare both on one capture).
3. **Composite**: in the existing `Present` hook (`menu_overlay.cpp` already has a fullscreen-quad pipeline and
   draws the menu), draw the uploaded Remix frame first, then the game's HUD is *not* drawn (L1), then our menu
   panel on top. If Remix fails at any step, fall back to the game's own frame; the proxy must never lose frames
   because of this feature.

## Gates before any game run

- **Mock game gate (extend `analysis/checks/test_menu_overlay.py`)**: `menu_overlay_mock_game.cpp` presents
  frames under Wine + Xvfb. Add: with `NIER_REMIX=1` and the Portal RTX runtime present, the proxy must
  (a) initialise Remix without failing the game loop, (b) produce a non-black composited frame, (c) fall back
  cleanly when the runtime path is bogus. This runs headless and needs no game — it is the cheapest way to
  catch ordering mistakes.
- **Converter parity gate**: one F9 capture → Python scene vs C++ cache must produce the same draw count,
  material count and texture list. This is what keeps the live path from drifting away from the verified
  offline path.
- Existing 27 gates must stay green; `build.py --scene` must stay clean.

## Order of work

1. `remix_live.cpp` host only (init, device order, `Present` loop) with a **single hard-coded triangle**. Gate:
   mock game shows a path-traced triangle instead of the game's colour. This proves in-process hosting, which
   is the whole risk.
2. Geometry cache behind a flag; render a *static* frame from a warm cache. Gate: compare against the offline
   still for the same capture (same camera, same textures).
3. Per-frame transform updates from the VS constant buffers → the scene animates.
4. Composite at the game's real resolution; measure end-to-end fps in NieR at 2580x1080 (upscaling path) and at
   3440x1440.
5. Only then: UI.

## UI — the one unsolved design problem

NieR's HUD and menus are D3D11 draws in the game frame; Remix's output has no UI. Options, cheapest first:

- **Fallback**: while a menu is open (the proxy can detect the game's menu draws, and we know our own menu
  state), present the game's own frame. HUD stays consistent, no extra work.
- **UI replay into a separate pass**: the capture already identifies UI draws (late draw order, orthographic
  projection, no depth write). Record them once, replay with their vertex data as a D3D11 pass on top of the
  Remix quad.
- **GUI buffer copy**: `CopyRenderingOutput(GUI)` exists but is refused when `combineGuiInFinalColor` is set,
  and it refers to *Remix's* ImGui overlay, not the game's UI. Not a solution for NieR's HUD.

## Safety

- The proxy must be deployable and revertible by the existing mechanism: `backups/ingame-menu-*/` with
  `receipt.json`; restore is one `cp` (see PROGRESS.md).
- `NIER_REMIX` off by default, so an ordinary run is byte-for-byte today's behaviour.
- The runtime path is configurable and verified by hash before load; never ship the 283 MB runtime inside the
  repo.
- Remix allocates its own VkDevice inside NieR's process: if the game becomes unstable, the first suspect is
  memory, and the second is the D3D9 device being created before the game's own D3D11 device is ready. Both are
  observable (probe log + `NIER_REMIX_DEBUG=1` breadcrumbs) and both revert by turning the flag off.
