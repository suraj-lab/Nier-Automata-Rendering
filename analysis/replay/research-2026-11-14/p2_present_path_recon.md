# P2 — "Remix owns presentation": how a frame reaches the screen today

Input to the rewrite of `analysis/PLAN_2026-11-14.md`, item **P2**. Read-only recon, 2026-11-14.
Cites are relative to `/home/suraj/Projects/Nier-Automata-Rendering/analysis`.

Trees:
- **PROXY** = `checks/` (the `d3d11.dll` proxy; `remix_live.cpp` is host to the Remix API).
- **FULL** = `runtime/src/dxvk-remix` (complete tree; `src/dxvk/rtx_render/rtx_remix_api.cpp`, `src/d3d9/d3d9_swapchain.cpp`, …).
- **PARTIAL** = `runtime/remix-source/0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a` (14-file drop). Its `rtx_remix_api.cpp`
  is the same code as FULL with **+55 lines offset** (`remixapi_Startup` at PARTIAL:1650 = FULL:1595).
- **CAPIHDR** = `runtime/remix-probe/sample/include/remix/remix_c.h` (what the proxy compiles against).

Prior reports not repeated here: `web_remix_present_framegen.md` (Remix-side present/framegen research),
`e1_effects_recon.md` (HUD draw filters).

## 0. Findings that matter most

1. **`Startup()` is a no-op in our host today.** The proxy creates the D3D9 device first
   (`checks/remix_live.cpp:784,786,791`), so `Startup` returns `ALREADY_EXISTS` at
   `FULL src/dxvk/rtx_render/rtx_remix_api.cpp:1599-1602`; the laptop log shows `startup=5`
   (`runtime/laptop-play-20261114/NIER_SCALE.log:27`). Consequence: `startup.hwnd`,
   `startup.combineGuiInFinalColor` (`remix_live.cpp:794-795`) and every other StartupInfo field are **ignored**.
   The window Remix uses comes from our `CreateDeviceEx(..., pp.hDeviceWindow = window, ...)` (`remix_live.cpp:786`).
2. **The per-frame readback is the dominant cost, not Remix's `Present`.** Worker logs: `present 0.3-2.4 ms,
   readback 35-77 ms` per frame (`NIER_SCALE.log:199,259,1803,4431`). Removing the readback removes a
   35-77 ms serialisation point but **does not make Remix render faster** — see §7 for what that means for P2's
   "40 fps presented".
3. **Frame generation with the readback path is pure cost, and the source says why:** `CopyRenderingOutput(FINAL_COLOR)`
   blits the D3D9 device's **backbuffer** (`rtx_remix_api.cpp:1502-1519` FULL), i.e. the rendered frame only.
   Interpolated frames exist only inside `DxvkDLFGPresenter::Present` (`rtx_dlfg.h:136-238`) and reach nothing but
   the presenter's window. `deploy/rtx/laptop-a-fg-off.conf:2` already said this in one sentence.
4. **`hwndOverride` is the lever, and it recreates the Vulkan swapchain.** `Present` forwards the override to
   `IDirect3DDevice9Ex::Present` (`rtx_remix_api.cpp:1703` FULL) and `D3D9SwapChainEx::Present` sets
   `recreate |= window != m_window` (`d3d9_swapchain.cpp:509-526` FULL). So passing the game's HWND once makes
   Remix's Vulkan swapchain (and `DxvkDLFGPresenter`, which takes the same `HWND`, `d3d9_swapchain.cpp:1418-1428`)
   bind the game's window. Whether two swapchains (game DXGI + Vulkan) can own one HWND is **UNVERIFIED** — that is
   the spike.
5. **`remixapi_Present` will call `ResetEx` behind our back** if the override window's client rect differs from the
   swapchain's size (`rtx_remix_api.cpp:1731-1737`, condition is `w != W && h != H` — an `&&`, not `||`). A `ResetEx`
   inside NieR froze the game once and crashed it once (`remix_live.cpp:1183-1184` comment; 2026-10-28). Any ownership
   code must refuse the override when the client rect ≠ Remix size.

## 1. The chain today

### 1.1 From `D3D11CreateDevice` to the Present hook

| Step | File:line (PROXY) |
| --- | --- |
| proxy export `D3D11CreateDevice` / `...AndSwapChain` forward to `d3d11_dlaa.dll`, then install hooks | `checks/d3d11_scale_setter.cpp:488-499`, `:501-514` |
| `menu_overlay::install(device, swapchain, host)` | `checks/d3d11_scale_setter.cpp:483-486` |
| swapchain vtable slot 8 named `kPresent`; `CreateSwapChain`=10, `ForHwnd`=15 | `checks/menu_overlay.cpp:44` |
| `adopt()` replaces slot 8 with `&present`, remembers the swapchain in `target` | `checks/menu_overlay.cpp:120-154` |
| factory hooks so later swapchains are adopted | `checks/menu_overlay.cpp:166, :175` |
| our `present()` | `checks/menu_overlay.cpp:637` |
| only the game's swapchain, no `DXGI_PRESENT_TEST` | `checks/menu_overlay.cpp:640` |
| order: `live_capture::end_frame()` → `remix_live::on_present()` → menu → real `Present` | `checks/menu_overlay.cpp:648-663` |
| after the real Present: `remix_live::begin_game_frame()` | `checks/menu_overlay.cpp:671` |
| the real `Present` is called unconditionally, once | `checks/menu_overlay.cpp:663` |

### 1.2 The Remix worker (one thread owns the runtime)

`struct Worker` `checks/remix_live.cpp:476`; started detached on the first game Present, with a watchdog
(`remix_live.cpp:1430-1431`, `worker_main` at `:1235`).

| Order | Action | File:line |
| --- | --- | --- |
| 1 | `remixapi_lib_loadRemixDllAndInitialize` | `remix_live.cpp:766` |
| 2 | API member floor (6 dxvk + Startup/Present/material/mesh/light/camera/draw) | `remix_live.cpp:768-772` |
| 3 | `dxvk_CreateD3D9(0, &d3d9)` — the **legacy** signature, `editorModeEnabled = 0` | `remix_live.cpp:784` |
| 4 | hidden window `nier-remix-live`, `WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE`, `WS_POPUP`, at `-32000,-32000`, size = monitor | `remix_live.cpp:774-781` |
| 5 | `CreateDeviceEx(adapter, HAL, window, …, &pp, …)`, `DISCARD`, `PRESENT_INTERVAL_IMMEDIATE`, `hDeviceWindow = window` | `remix_live.cpp:702-707`, `:786` |
| 6 | `dxvk_RegisterD3D9Device(device)` | `remix_live.cpp:791` |
| 7 | `StartupInfo{ sType, hwnd = window, combineGuiInFinalColor = 1 }` → `Startup` (`ALREADY_EXISTS` accepted) | `remix_live.cpp:792-798` |
| 8 | copy surfaces: DEFAULT-pool RT + SYSTEMMEM mirror, sized from the device's own backbuffer | `remix_live.cpp:716-735` |

### 1.3 Per frame (worker)

| Stage | Call | File:line |
| --- | --- | --- |
| submit instanced draws / camera | `live_scene::submit` or `nscn::submit` | `remix_live.cpp:940`, `:1130` |
| present | `api.Present(nullptr)` — **no PresentInfo, so no override** | `remix_live.cpp:1134` |
| copy | `dxvk_CopyRenderingOutput(target, …_FINAL_COLOR)`; queued on the CS thread, returns at once | `remix_live.cpp:1137` |
| wait + read back | `GetRenderTargetData(target, readback)` (this is where the 35-77 ms go) | `remix_live.cpp:1143` |
| lock / convert | `LockRect` → `frame_copy::bgra`, alpha forced to 0xff | `remix_live.cpp:1146-1151`, `checks/frame_copy.h:8-37` |
| publish | `swap(back, ready)` under `published` | `remix_live.cpp:1157-1158` |
| pacing | `Sleep` to keep ≥16 ms per worker frame | `remix_live.cpp:1227-1230` |

### 1.4 To the swapchain, two paths

**Path A — present-hook upload.** Inside `on_present`, on the game thread, when `shown` is valid and matches the
backbuffer (`remix_live.cpp:1447`):

```
context->UpdateSubresource(buffer, 0, nullptr, shown.pixels.data(), desc.Width*4, 0);   // :1454
hud_replay::draw(context, buffer, live_capture::ui_ready(), hud_pipeline);              // :1459
```

`buffer` = `swapchain->GetBuffer(0)` (`remix_live.cpp:1360`). This is a 20.7 MB upload at 2880x1800 per frame,
a memcpy of the same size in `frame_copy`, and a full-screen quad for the HUD.

**Path B — native HUD handoff quad.** `before_draw` (`remix_live.cpp:1262`) is called from the DrawIndexed hook
(`checks/draw_capture.h:252`, wired at `checks/menu_overlay.cpp:690`). When the game binds the verified
full-resolution `R11G11B10_FLOAT` HUD sprite target with no depth (`remix_live.cpp:1295-1297`) it uploads the
worker frame (`:1322-1323`) and draws a full-screen quad into that target (`:1335`), once per frame
(`native_hud_attempted`, `:1297`). Path A's upload is then skipped (`if (!native_hud_composed)`, `:1452`).
Laptop evidence: `remix: native HUD handoff 2880x1800 before game sprites` (`NIER_SCALE.log:155`), once.

Path B is still a **D3D11 copy of the frame into a game render target**, followed by the game's own final
compositor. Nothing in either path is Remix presenting.

### 1.5 Fallback: the game's own frames

`on_present` writes nothing unless *all* of `!world_gone`, `!original_view`, `shown.seq != 0`,
`shown.{width,height,format} == backbuffer desc` hold (`remix_live.cpp:1447`). There is no "draw the game's frame":
the game has already rendered one and the hook only declines to overwrite it.

| Case | Mechanism | File:line |
| --- | --- | --- |
| no live frame yet (menus, loading, all draws filtered) | worker returns before `Present`; one log line after 101 frames | `remix_live.cpp:1112-1132` |
| game backbuffer size ≠ Remix size | worker `paused`, one line "paused (game backbuffer …); game frames shown" | `remix_live.cpp:1185-1191` |
| loading screen (10 game frames with no scene draws) | `world_gone` | `remix_live.cpp:1437-1443` |
| F10 | `original_view`, capture suspended | `remix_live.cpp:1404-1410` |
| any worker failure | `fail()` → `State::Failed`, `on_present` returns | `remix_live.cpp:182-190`, `:1349` |
| stale frame (size/format changed) | the `shown.* != desc.*` test | `remix_live.cpp:1447` |

Menu/loading detection is therefore **inference from the draw stream**, not a menu state: the add-on menu itself
is ImGui drawn after the Remix composite in the same Present (`menu_overlay.cpp:649-663`), so it is always on top
while the game keeps presenting.

### 1.6 Threads and shared state

| Thread | Owns | File:line |
| --- | --- | --- |
| game render thread (inside `present()`) | `shown`, `native_hud_*`, `world_gone`, `original_view`, the swapchain/buffer | `remix_live.cpp:116-117`, `:1418-1425` |
| Remix worker | runtime, `d3d9`, `device`, `target`, `readback`, hidden window, live scene | `remix_live.cpp:476-518` |
| watchdog | stall reporting only | `remix_live.cpp:131-154` |

`published` guards `ready` + `want_width/height/format` (`remix_live.cpp:111-115`, `:1420-host`); `shown` is
presenting-thread-only; `state`, `original_view`, `worker_stage`, `hook_stage`, `presents` are atomics
(`remix_live.cpp:37-40`, `:119-125`). `live_capture::mutex()` (recursive) is taken by the camera CPU-mirror
callback on the game thread (`remix_live.cpp:1538`).

## 2. The Remix side

### 2.1 StartupInfo (CAPIHDR `remix_c.h:212-232`)

| Field | Line | Effect in the runtime (FULL `rtx_remix_api.cpp`) |
| --- | --- | --- |
| `hwnd` | `:215` | window for `CreateDeviceEx`; client rect = backbuffer size (`:1615-1620`), `hDeviceWindow` (`:1634`) |
| `disableSrgbConversionForOutput` | `:216` | `g_allowSrgbConversionForOutput = !x` (`:1352`) |
| `forceNoVkSwapchain` | `:221` | `dxvk::CreateD3D9(..., forceNoVkSwapchain, ...)` (`:1341`) → `D3D9SwapchainExternal`, no presenter; header comment `:217-220`: use `dxvk_GetExternalSwapchain`, default is a `VkSwapchainKHR` into the HWND |
| `editorModeEnabled` | `:222` | object-picking legacy hashes off, editor defaults (`:1353-1357`) |
| `combineGuiInFinalColor` | `:229` | `g_combineGuiInFinalColor` (`:1351`); when true, `CopyRenderingOutput(GUI=4)` is refused |

All five are unreachable through our current host (§0.1). The interface slot `dxvk_CreateD3D9` is bound to
`remixapi_dxvk_CreateD3D9_legacy` (`rtx_remix_api.cpp:1798` FULL), which only takes `editorModeEnabled` and fills
`disableSrgbConversionForOutput = forceNoVkSwapchain = editorModeEnabled`, `combineGuiInFinalColor = !editorModeEnabled`
(`:1368-1380`). With `editorModeEnabled = 0` today: sRGB conversion allowed, swapchain allowed, GUI combined in final
colour — which is what we want for presentation and is confirmed by the copy of type `GUI` being unusable.

Two startup shapes are possible against the same runtime:
(A) today's `CreateD3D9(legacy)` + `RegisterD3D9Device` + `Startup` → all StartupInfo fields dead;
(B) `Startup(StartupInfo)` **only** (what the shipped sample does: `remix-probe/sample/remixapi_example_c.c:40-51`,
    `Present(NULL)` at `:199`) → all fields honoured, Remix creates the device and registers it itself
    (`rtx_remix_api.cpp:1595-1665` FULL: presInfo `:1625-1640`, `CreateDeviceEx` `:1643`, `RegisterD3D9Device`
    `:1661`).
Shape B is required for `forceNoVkSwapchain` and for a StartupInfo-driven window; shape A is required for our
`D3DPRESENT_INTERVAL_IMMEDIATE`/`MULTITHREADED` flags.

### 2.2 `Present` and `hwndOverride`

`remixapi_PresentInfo{ sType, pNext, hwndOverride }` (`remix_c.h:728-732`). Implementation
(`rtx_remix_api.cpp:1698-1741` FULL):

1. `remixDevice->Present(NULL, NULL, info ? info->hwndOverride : NULL, NULL)` (`:1703`);
2. `HWND hwnd = hwndOverride ? hwndOverride : remixDevice->GetWindow()` (`:1710`), `GetClientRect` (`:1714-1717`);
3. if the client rect is non-zero, `GetSwapChain(0)->GetPresentParameters` and, **only if BOTH width and height
   differ**, `remixDevice->ResetEx(...)` (`:1725-1737`).

`D3D9SwapChainEx::Present` (`d3d9_swapchain.cpp:460-560` FULL): `window = hDestWindowOverride` (`:509-510`),
`recreate = NeedRecreatePresenter(); recreate |= window != m_window` (`:513-516`), `m_window = window` (`:526`),
`CreatePresenter()` when `recreate` (`:546-547`). So the first override to a new HWND destroys and rebuilds the
Vulkan swapchain on it; subsequent frames with the same HWND do not recreate. `m_window` also feeds
`DxvkDLFGPresenter(m_device, m_context, m_window, …)` (`:1418-1428`) and `vk::Presenter` (`:1426`), and the
surface is `vkCreateWin32SurfaceKHR(hwnd = m_window)` (`src/vulkan/vulkan_presenter.cpp:606-616` FULL).

Observed laptop state: the swapchain is **2880x1800, `VK_FORMAT_R8G8B8A8_UNORM`**, first
`VK_PRESENT_MODE_IMMEDIATE_KHR`, 2 images, then recreated `VK_PRESENT_MODE_FIFO_KHR`, 3 images
(`remix.log:257-275`). Vsync is forced on because `enableVsync` defaults to `WaitingForImplicitSwapchain` and the
code stores `PresentationInterval ? On : Off` (`d3d9_swapchain.cpp:345-347` FULL) — `D3DPRESENT_INTERVAL_IMMEDIATE`
is **4, not 0**, so "immediate" reads as vsync-on. To present unthrottled, `rtx.enableVsync = Off` must be set in
rtx.conf (option at `rtx_options.h:1119`). Queue families on the laptop: Present = 2 (`remix.log:241`), so DLFG's
present queue exists. `Reflex initialized successfully` (`remix.log:245`). One warning,
`[D3D9WindowProc] Swapchain handle is invalid` (`remix.log:277`), most likely from the off-screen hidden window
(UNVERIFIED: which window proc was hooked is not in the log).

### 2.3 The six `dxvk_*` interop functions (CAPIHDR `remix_c.h:756-788`, FULL impl)

| Function | Impl (FULL) | What it does |
| --- | --- | --- |
| `dxvk_CreateD3D9(bool editorMode, IDirect3D9Ex**)` | `:1368-1380` | legacy shim → `CreateD3D9(StartupInfo)`; also sets the three globals |
| `dxvk_RegisterD3D9Device(device)` | `:1383-1411` | accepts only a Remix `D3D9DeviceEx`; sets `s_dxvkDevice`, `g_dxvkDeviceNative` |
| `dxvk_GetExternalSwapchain(&img,&sem1,&sem2)` | `:1413-1434` | presenter's `VkImage` + semaphores; returns GENERAL_FAILURE when there is no external presenter. Prior art: a zero image handle with SUCCESS is possible (`INTEROP_API.md:140-153`) |
| `dxvk_GetVkImage(surface,&img)` | `:1437-1462` | the surface's backing `VkImage`; same-device only |
| `dxvk_CopyRenderingOutput(surface,type)` | `:1470-1556` | takes the device **backbuffer** (`:1502-1504`) and blits it (or depth/normals/picking) into `surface`; `GUI` renders Remix's ImGui into the destination instead (`:1534-1541`) |
| `dxvk_SetDefaultOutput(type,color)` | `:1559-1584` | clear colour per AOV |

The `CopyRenderingOutput` source being the backbuffer is the reason the copy cannot see interpolated frames, and
also why it is safe today: it copies exactly what Remix would have scanned out.

## 3. Frame generation (DLFG)

| Fact | Evidence (FULL) |
| --- | --- |
| enabled = hardware support ∧ option ∧ not failed | `src/dxvk/dxvk_context.cpp:59-64` (`isDLFGEnabled`) |
| presenter choice happens in `CreatePresenter` | `src/d3d9/d3d9_swapchain.cpp:1394-1432` (`if (dlfgEnabled) … new DxvkDLFGPresenter(… m_window …)`) |
| a live option flip recreates the presenter, no restart | `d3d9_swapchain.cpp:434-443` (`NeedRecreatePresenter`) |
| DLFG forces vsync off | `src/dxvk/rtx_render/rtx_context.cpp:2341-2344` ("we don't properly support FG + vsync") |
| options | `rtx.dlfg.enable` (default true), `maxInterpolatedFrames` 1-6 default 2, `litePreset`, `enablePresentMetering` — `src/dxvk/rtx_render/rtx_dlfg.h:313-323` |
| API path to flip them | `SetConfigVariable` → `RtxOptionImpl::readOption` for a static option (`rtx_remix_api.cpp:1240-1273`); option names in the `rtx.dlfg` namespace are static options, so this is the P1 mechanism too |
| hardware gates | `src/dxvk/rtx_render/rtx_ngx_wrapper.cpp:496-545`: `NVSDK_NGX_Parameter_FrameGeneration_Available`, updated driver, **GPU hardware scheduling**, `MultiFrameCountMax`; each failure logs and sets `supportsDLFG = false` |
| interpolated frames are written by the presenter | `DxvkDLFGPresenter` derives from `vk::Presenter` and owns the swapchain images (`rtx_dlfg.h:136-160`), submits via its own present/pacer threads (`rtx_dlfg.h:236-238`) |
| our conf has it off | `deploy/rtx/laptop-game.conf:4`, `laptop-a-fg-off.conf:3`; log `rtx.dlfg.enable = False` (`remix.log:22` and `:54`) |

What the source says, stated precisely:

- **Client reads frames back** (`CopyRenderingOutput` + `GetRenderTargetData`): the copy is of the backbuffer
  (`rtx_remix_api.cpp:1502-1519`), i.e. the rendered frame. Generated frames never appear in any AOV the API can
  copy, and they are only scanned out to the presenter's window. With the readback host, `rtx.dlfg.enable = True`
  buys extra GPU work and latency for frames nobody sees.
- **Remix presents to a window itself** (`Present` with a real `hwndOverride`, or a visible `StartupInfo.hwnd`):
  the Vulkan swapchain and the DLFG presenter are created on that HWND, and interpolated frames reach exactly that
  window. Nothing in the source requires the window to belong to Remix — it is the HWND of the swapchain that
  matters. Whether a Vulkan swapchain and the game's DXGI swapchain can both own one HWND is **UNVERIFIED**.
- DLFG is incompatible with `forceNoVkSwapchain = 1` (no presenter, so no interpolator): the two routes are
  mutually exclusive.

## 4. Gates that exist (presentation, HUD, fallback)

All run under Wine + Xvfb with `menu_overlay_mock_game.cpp` and, where noted,
`remix_live_fake_runtime.cpp`; each writes `validation.json`.

| Gate | What it asserts about presentation |
| --- | --- |
| `test_remix_live.py` | `Startup hwnd_visible=0 combineGui=1 registered=1` (`:123`); `Register 1920x1080 started=0` and device created at backbuffer size (`:122`); fake's input-sink window lands off every monitor (`:128-130`); window stays invisible after the fake's `ShowWindow` (`:133`); `startup=5` accepted (`:135`); pixel = Remix colour at probe (`:140`) with the menu on top (`:141`); pauses on resize with the game's frame shown (`:171-174`); `NIER_REMIX_SIZE` forced/unforced (`:163,182-193`); `presented == 80` and `stub_presents == 80` in every scenario (`:68`); four+ failure modes (missing runtime, relative path, bad scene, `copy:20` mid-run, incomplete shim) each produce exactly one `disabled` line and the game's frames (`:196-238`); `hang:present` → watchdog names the stage (`:215-217`); `steal-focus` → focus returned (`:224-226`) |
| `test_native_hud.py` | the HUD shader draws onto the Remix image before the HDR compositor; two sprites coexist; corner stays Remix; `NO_HUD` disables the handoff |
| `test_hud_replay_linkage.py` | pixel-shader inputs occupy the same registers as vertex-shader outputs (Wine cannot catch a mismatch) |
| `test_frame_copy.py` | `frame_copy::bgra` byte order, padding, opaque alpha, optional 2880x1800 benchmark (not asserted) |
| `test_present_overlay_rehook.py` | our Present hook must not be reachable through DXGI's shared vtable, else ours → Steam-overlay → ours loops (laptop 2026-10-30) |
| `test_present_interface_floor.py` | the swapchain-vtable copy keeps `Present1` when the interface is an alias |
| `test_menu_overlay.py` | the panel draws over the backbuffer without disturbing game state (mock + stub present counts) |
| `test_overlay_rule.py`, `test_menu_style_tokens.py`, `test_menu_design_prototype.cjs` | menu visuals only, no presentation |

Nothing asserts "Remix presented the frame". Every presentation assertion is "the bytes the game's swapchain
received". That is the gap P2 has to fill.

## 5. What the fixtures can and cannot simulate

`menu_overlay_mock_game.cpp` (the "game"): a real D3D11 device + `CreateSwapChain` on a window under Xvfb, 80
frames, `presented`/`stub_presents` counters (`:1582`), a downstream stub that records what our hook passed down,
resize (`MOCK_RESIZE_AT/TO`), BGRA, a shared-vtable overlay stand-in (`MOCK_OVERLAY_REHOOK`), draw-slot stealing,
scene-target variants (`:6-8, :82, :189-212, :432`). It **can** gate withholding: skip `next()` and
`stub_presents` drops while the game still runs 80 frames.

`remix_live_fake_runtime.cpp` (the "runtime"): real Wine d3d9 for CreateDevice/Reset/GetRenderTargetData/LockRect,
a `ColorFill(200,40,120)` "frame", a call-order contract with `VIOLATION` lines, `Startup` notes
`hwnd_visible/combineGui/registered` (`:61-74`), `Present` notes gaps and, on frame 1, tries to show the window and
creates the `RemixGuiInputSink` mimic (`:303-333`), `CopyRenderingOutput` notes size/type (`:336-350`).
`FAKE_REMIX_FAIL` modes: `copy:<n>`, `hang:present`, `steal-focus` (`:328, :365-366`).

Cannot: present anything (no Vulkan swapchain, no VkSurface), react to `PresentInfo.hwndOverride` (it ignores the
argument), represent DLFG, or model two swapchains on one HWND. Consequences:
- withholding can be gated on the mock, but "Remix presents into the game window" **cannot**;
- the fake must learn to record `hwndOverride != NULL` and to *fail* `Present` when the override is set in a
  `FAKE_REMIX_FAIL=override` mode, so the host's error path is gated;
- a real go/no-go needs the laptop.

## 6. Go/no-go spike (under one day, laptop, no game logic changed)

Purpose: decide whether Remix's Vulkan swapchain can own NieR's window while the game's DXGI swapchain exists.
Everything else in P2 depends on this one bit.

Shape: a standalone x64 test exe (`analysis/checks/present_spike.cpp`, run on the laptop, no game) that

1. creates two windows: `W_game` (a plain 2880x1800 popup, as a stand-in) and `W_remix` (hidden tool window);
2. creates a D3D11 DXGI swapchain on `W_game` (`SWAP_EFFECT_DISCARD` **and** `FLIP_DISCARD` as two cases) and
   presents a known colour 60 times/s — the "game";
3. loads the installed Remix runtime with the same calls the proxy makes (`CreateD3D9` legacy → `CreateDeviceEx` on
   `W_remix` → `RegisterD3D9Device` → `Startup`), then `Present(&{hwndOverride = W_game})` every frame with a
   one-quad scene;
4. after 100 frames stops the D3D11 Present and keeps presenting Remix;
5. writes a json receipt.

Measurements it must produce (each a number or a `remixapi_ErrorCode`, in one file):
`startup_code`, `override_present_hr`, `recreate_count` (log-diff the `Presenter: Actual swap chain properties`
lines), `game_present_hr` after Remix took the window, a screen capture of `W_game` (is it Remix's colour or the
game's?), `DwmGetCompositionTimingInfo`-based present delta, and the same run with
`rtx.dlfg.enable=True/False` + `rtx.enableVsync=Off`, plus `supportsDLFG` (grep the runtime log for the
"not available"/"requires GPU hardware scheduling" lines).

Go criteria (all must hold): `override_present_hr == 0` and `SUCCESS` for 100 consecutive frames;
`recreate_count == 1`; the capture of `W_game` shows Remix's frame while the D3D11 presenter is stopped; no crash
in 60 s; the Steam overlay (injected into the exe) either draws or fails harmlessly. With DLFG on: the log shows a
`DxvkDLFGPresenter` swapchain and the capture shows interpolated frames (motion in the one-quad scene while the
scene state is static).
No-go criteria: `Present` returns GENERAL_FAILURE, or `vkCreateWin32SurfaceKHR`/`vkCreateSwapchainKHR` fails on
`W_game`, or the D3D11 Present after the takeover hangs/errors, or the window shows nothing.

## 7. Staged design for the full item (behind a switch)

Switch: `NIER_REMIX_PRESENT_OWN=1` (default 0 = today's behaviour, byte-identical). Everything below is inert
without it and each stage keeps the previous one working.

- **Stage 1 — the ownership predicate and the withheld Present.** `menu_overlay.cpp` decides, before calling
  `next()`, whether Remix owns the window this frame. Predicate: switch on ∧ `state == Running` ∧
  `shown.seq && shown.{w,h,format} == desc` ∧ `!original_view` ∧ `!world_gone` ∧ menu closed ∧
  `GetClientRect(game_hwnd) == (width,height)`. Sticky with hysteresis: the mode may only change on a state
  transition, and any change of owner must go through one `keep_focus` + one log line. When owning: skip
  `next(self,sync,flags)` and `DwmFlush()` (or `Sleep` to the frame budget) in its place so the game does not
  unthrottle; still call `begin_game_frame` so capture continues.
- **Stage 2 — pass the override.** The worker keeps a copy of the game HWND (published from
  `sd.OutputWindow`, `remix_live.cpp:1401`) and calls `api.Present(&info)` with `hwndOverride = game_hwnd` only
  while the predicate holds, `nullptr` otherwise. Guard from §0.5: never pass an override whose client rect differs
  from `width x height`. On `GENERAL_FAILURE` from `Present`, drop the override, log once, and vacate ownership for
  the rest of the session (`State::Failed` semantics) — never retry per frame.
- **Stage 3 — stop the readback while owning.** Skip `CopyRenderingOutput`/`GetRenderTargetData`/`LockRect`/
  `frame_copy` in `Worker::frame` when `api.Present` succeeded with the override; keep them for every other mode
  (they are the only way to fail over). Keep the stage timings, add `own_` counters, so the plan can quote
  "before/after".
- **Stage 4 — the HUD.** The source offers no 2D UI draw to an API client (`remix_c.h:799-831`, no
  `DrawUIInstance`; only `REMIXAPI_INSTANCE_CATEGORY_BIT_WORLD_UI` `remix_c.h:477` and Remix's own ImGui), so the
  HUD must be **geometry**: a full-screen quad in the camera's near plane, material unlit/emissive with the HUD
  captured to a DDS (the live path already writes DDS + creates materials). Two answers are acceptable, decided by
  the user: (a) the mesh quad (HUD is interpolated → slight ghosting, DLSS-FG's normal UI behaviour), or (b) the
  game's own frames while the menu/cutscene is up and no HUD ownership at all. Stage 4 ships only after a
  still-frame comparison.
- **Stage 5 — frame generation.** `SetConfigVariable("rtx.dlfg.enable","True")`, `rtx.enableVsync=Off` in the
  laptop conf, `maxInterpolatedFrames` as a menu row next to P1's DLSS modes. Watch for
  `Present`-thread latency and the `Reflex` idle interplay (`d3d9_swapchain.cpp:402-408`).

What P2's "Done when" should become: presentation ownership is proven by a gate + one laptop log; the readback's
35-77 ms disappear from the worker's stage line; **"40 fps presented" requires stage 5**, because 2880x1800
path-traced frames cost 35-77 ms of GPU time regardless of how they are presented (§0.2). Without FG the honest
target is "the worker's fps unchanged, the game thread no longer stalls, no readback".

## 8. Contradictions and corrections for `PLAN_2026-11-14.md`

1. "removes the per-frame readback" is necessary but not sufficient for ">= 40 fps presented at 2880x1800": the
   measured 35-77 ms is Remix's GPU frame (`NIER_SCALE.log:199,1803`), so the frame rate only passes 40 with frame
   generation actually working (2x of ~20 fps).
2. "HUD drawn into Remix's frame" has no API: it must be a `WORLD_UI` instance (§7 stage 4) or the game's frames
   must be shown while the HUD matters. The plan should pick one.
3. "the game's Present is withheld while Remix shows frames" is compatible with capture (the capture hooks run
   before the decision: `menu_overlay.cpp:644-648`), but the game's frame pacing has to be replaced with an
   explicit `DwmFlush`/sleep or NieR will run its logic unthrottled.
4. `StartupInfo` is documented as the place to set `forceNoVkSwapchain`/`editorModeEnabled`; in our host those
   fields are dead (§0.1). A plan step that expects them to take effect must first move to the Startup-only shape,
   which is a separate risk (Remix's own `D3DPRESENT_PARAMETERS`, `rtx_remix_api.cpp:1625-1640` FULL).
5. The plan's spike wording ("with the Steam overlay injected, menus still visible") mixes two things: the Steam
   overlay is a DXGI-Present hook (invisible once the game stops presenting — `test_present_overlay_rehook.py`'s
   subject), while "menus" are either the game's own UI (game frames only) or our ImGui (needs a home in Remix's
   frame). The spike should test the swapchain-ownership bit alone and record overlay/menu behaviour as findings.

## Open questions

1. **Can a Vulkan swapchain and NieR's DXGI swapchain own one HWND at the same time?** Not answerable from source.
   Determine with §6's spike on the laptop; also try `SWAP_EFFECT_FLIP_DISCARD` for the game side.
2. **Does `supportsDLFG()` return true on the RTX Spark N1X under x64 emulation?** The laptop log has no DLSS-FG
   lines at all and `rtx.dlfg.enable = False` (`remix.log:22`). Determine by setting `rtx.dlfg.enable = True` in
   `deploy/rtx/laptop-game.conf` and grepping the runtime log for `NVIDIA DLSS Frame Generation` and
   `requires GPU hardware scheduling` (`rtx_ngx_wrapper.cpp:498-545`), with Windows hardware scheduling confirmed
   on/off in Settings.
3. **Does NieR survive its Present returning without presenting?** UNVERIFIED. Mock test first
   (`stub_presents` drops, 80 frames run), then the laptop with the switch on and `NIER_REMIX_CAPTURE_COMPOSITE`
   off.
4. **Does the game's swapchain keep its `DISCARD` model, or flip?** Determines whether two swapchains collide.
   Check `DXGI_SWAP_CHAIN_DESC` in the proxy log (not currently logged) — cheap to add one line.
5. **What does Remix's `Present` cost when the window is the game's and visible vs the hidden one?** `present` is
   0.3-2.4 ms today (`NIER_SCALE.log:4431`); a visible window adds the compositor. Measure in the spike.
6. **Where does the HUD texture go if stage 4 picks geometry?** UNVERIFIED: whether a DDS-backed `WORLD_UI`
   instance can be updated at 60 Hz without a material rebuild; the live path's texture writer
   (`checks/remix_live.cpp` `TextureWriter`, `:379`) writes a file per hash, so a fixed hash + rewrite is the
   candidate.

## Recommended steps for the plan

1. **Log the swapchain description once** in `checks/remix_live.cpp::on_present` (next to `:1401`):
   `sd.SwapEffect`, `BufferCount`, `Windowed`, `OutputWindow`. Check: `test_remix_live.py` gains an assertion that
   the line exists with `SwapEffect=1` (DISCARD) for the mock. Mutation that must turn it red: print
   `sd.BufferCount` instead of `sd.SwapEffect`.
2. **Teach the fake runtime `hwndOverride`**: record `override=<hwnd!=0>` in `remix_live_fake_runtime.cpp::present`
   (`:303`) and add `FAKE_REMIX_FAIL=override:<n>` to fail `Present` after n frames. Check: `test_remix_live.py`
   asserts the line and that a failing override leads to exactly one log line and back to game frames.
   Mutation: ignore the `info` argument again → red.
3. **Build the spike exe** `analysis/checks/present_spike.cpp` (§6) with a python runner
   `analysis/checks/test_present_spike.py` that parses its json, and a `--mock` mode that skips Remix so the runner
   itself is gated on CI (Wine/Xvfb, D3D11-only case). Check: the mock case asserts
   `game_present_hr == 0` for both swap effects; the laptop case is run by hand and its receipt committed under
   `analysis/runtime/present-spike-<date>/`. Mutation: pass `nullptr` instead of `W_game` → the mock case still
   passes (it must), so gate the *override count* from the fake as well.
4. **Stage 1 + 2 behind `NIER_REMIX_PRESENT_OWN`** in `checks/menu_overlay.cpp:637-673` (predicate + withhold) and
   `checks/remix_live.cpp` (publish `game_hwnd`, override in `Present`, one-shot failure handling). Check:
   `test_remix_live.py` new scenario `own` asserting `stub_presents < 80` on the mock and 80 `present` calls in
   the fake log with `override=1`, plus `own=off` byte-identical to today. Mutations: predicate ignores the size
   guard (→ a `paused`/`disabled` line appears, red); withhold without `DwmFlush` (→ the mock's frame timing
   assertion, if added, red).
5. **Stage 3**: skip the readback under ownership; assert in `test_remix_live.py` that the `own` scenario's log has
   **no** `Copy` line from the fake while having `Present` lines, and that the non-own scenario keeps them.
   Mutation: skip the copy but still `LockRect` → red.
6. **Stage 4 decision (user's pick)**: geometry HUD vs game frames while the HUD matters; gate the chosen one with
   a still-frame comparison against the game's own frame at the same spot (the existing truth-pair method in
   `deploy/rtx/game.conf`).
7. **Stage 5**: `rtx.dlfg.enable = True` + `rtx.enableVsync = Off` in a new `deploy/rtx/laptop-d-own-fg.conf`,
   driven from the menu via `SetConfigVariable` (P1's plumbing). Evidence to collect: the runtime log's
   `DxvkDLFGPresenter`/presenter block, `present`/`readback` stage deltas, and a 60 s recording for ghosting.
   Check: one laptop run with the numbers next to the item; no gate can assert this without the hardware.
