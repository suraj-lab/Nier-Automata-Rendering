# Live Remix transfer: SOLVED (2026-10-27, desktop GPU)

The step that blocked live Remix in NieR — getting the path-traced frame out of the runtime — now works,
and the earlier conclusion that it was impossible was an error in our test setup, not a property of the API.
This file replaces the "all three documented extraction routes fail" table in `PROGRESS.md`.

## What was wrong

The public runtime source (`NVIDIAGameWorks/dxvk-remix`, `src/dxvk/rtx_render/rtx_remix_api.cpp`) states
plainly what `dxvk_CopyRenderingOutput` copies:

```cpp
// copyRenderingOutput(), FINAL_COLOR case
IDirect3DSurface9* pSurface = nullptr;
remixDevice->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &pSurface);   // remixDevice == s_dxvkDevice
...
case REMIXAPI_DXVK_COPY_RENDERING_OUTPUT_TYPE_FINAL_COLOR:
    srcImage = cBackbuffer;   // the REGISTERED DEVICE'S backbuffer, not the path-traced output image
```

and what `dxvk_RegisterD3D9Device` does (`rtx_remix_api.cpp:1410-1440`):

```cpp
s_dxvkD3D9   = dxvkD3d9Ex;
s_dxvkDevice = dxvkDevice;              // replaces the presenting device
g_dxvkDeviceNative = dxvkDevice->GetDXVKDevice().ptr();
```

`remixapi_Startup` is the function that *creates* the presenting device (D3D9 → `CreateDeviceEx` with a
swapchain over `StartupInfo.hwnd`, then registers it), and it refuses with `ALREADY_EXISTS` if a device is
already registered.

Our probe did the opposite of the working order: it called `Startup` (runtime made its own presenting device),
then later created a **second** device with a 64x64 swapchain and registered *that*, displacing the presenting
device. The copy then blitted a backbuffer that had never been rendered into — black. Two further defects
compounded it: the copy is queued on the render thread (`remixDevice->EmitCs`) so an immediate readback races
it, and the destination surface was 430x180 while the source backbuffer was 928x1028, which scales.

So the "black copy" had three causes, all ours. Nothing here was an AMD, RADV or Wine limitation.

## What works, measured

Order that works: **create D3D9 → `CreateDeviceEx` with a real swapchain at the render size on our own window
→ `dxvk_RegisterD3D9Device` → `Startup` (which now returns ALREADY_EXISTS, expected) → submit scene →
`Present` → `CopyRenderingOutput(FINAL_COLOR)` into a target sized from `GetBackBuffer`'s desc → read back.**

| measurement | value |
|---|---|
| copy result, 928x1028 | `ok=1`, mean luma 0.4537, non-black 0.9998 |
| copy result, 2580x1080 | `ok=1`, mean luma 0.4522, non-black 0.9996 |
| identical to direct backbuffer read? | yes, same content, 1:1 |
| readback control (`ColorFill` green, then read) | luma 0.7152 = exactly green's Rec.709 luma |
| copy + readback cost, 3.8 MB | 0.21 ms/frame |
| copy + readback cost, 11.1 MB (2580x1080) | 0.49 ms/frame |
| path-traced scene fps, 2580x1080, 2.7M tris, 190 textures | **53 fps** |
| path-traced scene fps, 430x180 | 57 fps (probe's 16 ms hold floor) |

The readback control matters: without it, "the copy is black" and "our readback is broken" are
indistinguishable, and that ambiguity is what produced the wrong conclusion last session.

Probe controls added (all opt-in, default output unchanged): `REPROBE_PRE_REGISTER`,
`REPROBE_INTEROP_CONTROL`, `REPROBE_INTEROP_BACKBUFFER`, `REPROBE_INTEROP_LOOP`, `REPROBE_INTEROP_CLEAR`,
`REPROBE_INTEROP_REGISTER` (default off now). Exe: `5b70560f…`.

## The runtime version question, settled

- Portal RTX's `.trex/d3d9.dll` and the public **remix-1.6.1** `d3d9_x64.dll` are the same build family:
  identical size (282,883,696 B), 322 differing 4K blocks, different sha256 (`ca71edf1…` vs `c05c552e…`).
  We already render with a 1.6-era runtime.
- The 1.6.1 **PDB** (published with the release) names `CopyRenderingOutput` (23 hits),
  `GetExternalSwapchain` (7), `RegisterD3D9Device` (5), `SetDefaultOutput` (12), `GetVkImage` (7) — and
  **zero** occurrences of `GetInteropInfo` or `clientDoneSemaphore`.
- The interop-image route (`StartupInfo.interopImage` + `dxvk_GetInteropInfo`) is an **NVIDIA-internal**
  runtime: `NVIDIAGameWorks/rtx-remix-minecraft` compiles against `remixapi` **0.16.0** (our build:
  0.6.5, `InitializeLibrary` gates on minor 6) and pulls its runtime from a packman package named
  `demo-runtime-*` / `runtime-*`, not the public release. Public 1.6.1 does not carry it.
- Remix 1.6 (2026-10-23) added **Windows on Arm** runtime support and public **ARM64/ARM64EC** build
  artifacts (day 1 for Portal RTX, Half-Life 2 RTX Demo, Remix for Minecraft). That matters because the
  laptop (`spaghetti`, RTX Spark N1X) becomes a native-NVIDIA Remix host for the first time.

## What this means for "live Remix in NieR"

Unknown (a) — "can a frame leave the runtime" — is answered: **yes, through the D3D9 copy, at a cost of
~0.5 ms per 1080p frame.** The remaining work is no longer about transfer:

1. **Per-frame scene submission inside NieR.** Materials, meshes and textures are created once and cached by
   hash; per frame only the camera, the per-instance transforms and the light state are updated. The probe
   already submits a full 2.7M-triangle scene every frame at 53 fps, so the renderer side is proven; what is
   missing is feeding it NieR's live draw stream instead of a converted capture.
2. **Compositing.** Copy into a system-memory surface, upload into a D3D11 texture, draw it as a fullscreen
   quad in our own `d3d11.dll` Present hook (that proxy already has a fullscreen-quad pipeline for the menu).
   Cost measured above; the upload is the same order as the readback.
3. **UI.** NieR's HUD/menus are D3D11 draws inside the game frame and are not in Remix's output. This is the
   only genuinely unsolved design problem left. Cheapest first version: show Remix output and fall back to
   the game's own frame when a menu is open (the proxy already knows when its menu is up and can detect the
   game's menu draws); better: replay the game's UI draws as a separate pass on top.

## Rules to not rediscover

- **Create and register our device before `Startup`.** After it, `Startup` has already registered the
  runtime's own presenting device and `ALREADY_EXISTS` is permanent.
- **Size the copy destination from `GetBackBuffer(0,0)->GetDesc()`**, never from the window size you asked
  for. The presentation path resets the swapchain to the real client size (928x1028 for a 430x180 request in
  this compositor).
- **`LockRect` before believing a timing.** DXVK defers the readback until the resource is mapped.
- **`ColorFill`, not `Clear`**, to write a known value into a specific surface: `Clear` hits the bound target.
- Use copy types 0/1/2 as separate probes of the same path — all three now return content, which is what
  localised the fault to the source device rather than the copy call.
