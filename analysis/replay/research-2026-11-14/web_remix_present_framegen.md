# Presentation, DLSS frame generation and UI in RTX Remix 1.6.1 — web + source research (2026-11-14)

Input to the rewrite of `analysis/PLAN_2026-11-14.md`, specifically item **P2** ("Remix owns presentation") and
**P1** ("standard DLSS modes"), plus the HUD question in P2 and E1.

Runtime under study: dxvk-remix commit `0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a` = tag `remix-1.6.1`
(2026-10-23), local full clone at `analysis/runtime/src/dxvk-remix`. All local citations below are from that commit
(read with `git show <sha>:path`, so they are exact for the shipped runtime). `analysis/runtime/remix-source/<sha>/`
is only a partial tree (API-layer `.cpp` files; no `public/include`, no `src/d3d9`) — do not use it as the source of
truth for API or swapchain questions.

Method note: no `web_search`/`fetch_content` tools were exposed in this session; every web fact below was fetched with
`curl`/`urllib` from the URL given (GitHub REST API, raw.githubusercontent.com, learn.microsoft.com,
registry.khronos.org, docs.nvidia.com, developer.nvidia.com). One peer report already exists in this folder,
`web_ops_debug_framegen_alt.md`, which covers Steam-overlay mechanics and FG alternatives; this file covers the
presentation/API questions and does not repeat it.

---

## 0. Summary of the five findings that change the plan

1. **There is exactly one presentation path for an API client, and it is a hidden internal D3D9 device with a
   Vulkan swapchain.** `remixapi_Startup` creates its own `IDirect3DDevice9Ex` + swapchain on the `HWND` you pass
   (`public/include/remix/remix_c.h:212-231`, `src/dxvk/rtx_render/rtx_remix_api.cpp:1650-1745`), and
   `remixapi_Present` just calls `IDirect3DDevice9Ex::Present` on it
   (`rtx_remix_api.cpp:1756-1762`). There is no "give Remix my D3D11 swapchain" mode and no compositing entry point.
2. **`hwndOverride` does not just move the window: it destroys and recreates the Vulkan swapchain on the new HWND.**
   `D3D9SwapChainEx::Present` compares the override against its own window and sets `recreate = true`
   (`src/d3d9/d3d9_swapchain.cpp:509-517`), which re-runs `CreatePresenter()` →
   `vkCreateSwapchainKHR` on that HWND. Pointing that at the game's flip-model D3D11 HWND is exactly the case that
   NVIDIA's own Minecraft Remix port hit and had to abandon: `vkCreateSwapchainKHR failed, error code:
   VK_ERROR_NATIVE_WINDOW_IN_USE_KHR` → `Startup failed: GENERAL_FAILURE`
   (<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/53>); fixed in 0.1.1 by *"presents through its own
   window instead"* (<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/54>).
3. **DLSS Frame Generation is wired only to the D3D9 swapchain presenter, and it is available to API clients — but it
   forces vsync off and interpolates whatever is already in the backbuffer, including Remix's own ImGui and anything
   the client drew into it.** `DxvkDLFGPresenter` is constructed only at `d3d9_swapchain.cpp:1416-1428`
   (`if (dlfgEnabled)`), `dispatchDLFG()` turns `rtx.enableVsync` off explicitly ("we don't properly support FG +
   vsync", `rtx_context.cpp:2382-2386`), and the interpolator's colour input is the backbuffer that ImGui/HUD were
   drawn into (`rtx_dlfg.cpp:445-479`, `d3d9_swapchain.cpp:1235-1240`).
4. **An API client cannot draw 2D UI into Remix's frame in 1.6.1.** `remix_c.h` has no `remixapi_DrawUIInstance`
   and no screen-UI category; the full interface is `remix_c.h:805-833`. The only UI mechanisms are (a) instances
   tagged `REMIXAPI_INSTANCE_CATEGORY_BIT_WORLD_UI` (`remix_c.h:477`) — i.e. *geometry* with a Remix material, and
   (b) Remix's *own* ImGui, which lives inside the runtime and is composited in
   `d3d9_swapchain.cpp:1239` (`gui.render`). `rtx.uiTextures` is a **D3D9 texture-hash list**
   (`rtx_options.h:187`, consumed in `src/d3d9/d3d9_rtx.cpp:592`) and is useless to a D3D11 proxy.
5. **`remixapi_SetConfigVariable` applies a value but does not persist it.** It writes to the *user layer*
   (`rtx_remix_api.cpp:1290-1300`), which is `user.conf` (`rtx_option_layer.cpp:735`), and that file is only written
   when someone presses "Save Settings" in Remix's own menu (`src/dxvk/imgui/rtx_user_menu.cpp:277-279`). It also
   returns `REMIXAPI_ERROR_CODE_SUCCESS` even when the value fails to parse (`rtx_remix_api.cpp:1290-1303`;
   `RtxOptionImpl::readOption` ignores parse failure, `rtx_option.cpp:447-466`). On the laptop the user layer lives
   at `%LOCALAPPDATA%\NVIDIA\RTXRemix\user_settings\<appid>.conf`
   (<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/41>).

---

## 1. Question 1 — how a Remix API client presents frames

### 1.1 The modes that exist in 1.6.1

| Mode | How it is selected | What actually presents | Evidence |
| --- | --- | --- | --- |
| **Vulkan swapchain on a window** (default) | `remixapi_Startup` with `StartupInfo.hwnd` non-null, `forceNoVkSwapchain = 0` | Remix's internal D3D9 device owns a `D3D9SwapChainEx` → `vk::Presenter` → `vkCreateSwapchainKHR` on that HWND | `remix_c.h:212-228` (`hwnd` :215), `rtx_remix_api.cpp:1650-1735` (device created with `D3DPRESENT_PARAMETERS.hDeviceWindow = info->hwnd`), `d3d9_swapchain.cpp:1376-1443` |
| **No Vulkan swapchain, client presents** | `StartupInfo.forceNoVkSwapchain = 1` | Client calls `dxvk_GetExternalSwapchain()` and gets a raw `VkImage` + two semaphores, then presents it itself (the header's stated example: convert to GL and present with OpenGL) | `remix_c.h:217-221` (comment), `rtx_remix_api.cpp:1440-1457`, `d3d9_device.cpp:7924-7928` (`m_withExternalSwapchain` → `D3D9SwapchainExternal`), `src/d3d9/d3d9_swapchain_external.cpp:35-120` |
| **Headless / copy-out** | `StartupInfo.hwnd = NULL` (width/height stay 0, no window) and `remixapi_Present(nullptr)`; output taken with `dxvk_CopyRenderingOutput` | Nothing is scanned out; the client reads AOVs into a `IDirect3DSurface9` | `rtx_remix_api.cpp:1666-1690` (`if (info->hwnd)` only then is a window used), `remix_c.h:774-790` (`REMIXAPI_DXVK_COPY_RENDERING_OUTPUT_TYPE_FINAL_COLOR = 0` … `GUI = 4`) |
| **Window retarget at present time** | `PresentInfo.hwndOverride` | Destroys + recreates the Vulkan swapchain on that HWND (and resizes if the client rect differs) | `remix_c.h:728-734`, `d3d9_swapchain.cpp:509-517`, `rtx_remix_api.cpp:1763-1790` |

There is no fourth "share my swapchain" mode. `dxvk_CopyRenderingOutput` is **read-only** (Remix → a D3D9 surface,
`rtx_remix_api.cpp:1477-1560`), and `dxvk_SetDefaultOutput` only chooses *which* AOV is the default output
(`remix_c.h:792-794`).

### 1.2 What known clients actually do

| Client | API used | Presentation | Evidence |
| --- | --- | --- | --- |
| Remix API C sample (ships in the runtime source tree) | `remix_c.h` directly | `Startup` with a real window + `forceNoVkSwapchain = FALSE`, then `Present(NULL)` every frame | `analysis/runtime/remix-probe/sample/remixapi_example_c.c:40-47` and `:199`; the documented flow is `documentation/RemixSDK.md:143` |
| NVIDIA "RTX Remix for Minecraft" (Fabric mod, 1.6 beta) | `remix_c.h` + GL↔Vulkan interop; **an API client, not a D3D9 game** | Own window owned by the mod (since 0.1.1), Remix presents into it with its Vulkan swapchain | <https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/53>, <https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/54>, release notes in <https://github.com/NVIDIAGameWorks/rtx-remix/releases/tag/remix-1.6.1> ("new API rendering pipeline") |
| Bridge-based mods (Garry's Mod RTX, xoxor4d `remix-comp-base`) | `bridge_remix_api.h` — **not** `remixapi_Present` | The game's own (Remix-provided) D3D9 swapchain presents; the bridge only registers `beginScene` / `endScene` / `present` callbacks | `public/include/remixapi/bridge_remix_api.h:45-95`; `bridge/src/client/remix_api.cpp:513-515` (Startup/Present are commented out); <https://github.com/xoxor4d/remix-comp-base/blob/master/src/shared/common/remix_api.hpp> (`#include "bridge_remix_api.h"`) |
| `py-rtx-remix` (ctypes wrapper) | `remix_c.h` | Same as the C sample (window + `Present`) | <https://pypi.org/project/py-rtx-remix/> (UNVERIFIED: I did not read its present call) |

Consequence for this project: our proxy is in the same class as Minecraft Remix (external client, non-D3D9 game), so
Minecraft's issues are our best public precedent — good and bad (§4).

---

## 2. Question 2 — what DLSS Frame Generation requires inside dxvk-remix

### 2.1 The options (exact names, defaults, at 1.6.1)

| Option | Type / default / range | Evidence |
| --- | --- | --- |
| `rtx.dlfg.enable` | bool, default **true**, env `RTX_DLFG_ENABLE`, `UserSetting` | `src/dxvk/rtx_render/rtx_dlfg.h:313-315` |
| `rtx.dlfg.maxInterpolatedFrames` | uint32, default **2**, min 1, **max 6** ("For DLSS 4.5 frame generation … Ignored for DLSS 3.0") | `rtx_dlfg.h:316-318` |
| `rtx.dlfg.litePreset` | bool, default false = Preset A, true = Preset C (lightweight); env `RTX_DLFG_LITE_PRESET`; recreates FG live | `rtx_dlfg.h:319-322` |
| `rtx.dlfg.enablePresentMetering` | bool, default **true** (hardware present metering instead of CPU pacing) | `rtx_dlfg.h:323` |

`maxInterpolatedFrames = 6` = "6× MFG" (1 rendered + 5 interpolated), which matches the 1.6 release note "**Up to 6×
Multi Frame Generation**" and the "6x Multi Frame Generation producing up to five additional frames per rendered
frame" wording in the RTX Spark blog (URLs in §6).

### 2.2 The gate: when DLFG is actually on

```
DxvkContext::isDLFGEnabled() =
      metaNGXContext().supportsDLFG() && DxvkDLFG::enable() && !metaDLFG().hasDLFGFailed()
```
`src/dxvk/dxvk_context.cpp:59-64`. `supportsDLFG()` is set in `NGXContext::checkDLFGSupport`
(`rtx_ngx_wrapper.cpp:511-566`) and fails when:

| Condition | Log / reason | Evidence |
| --- | --- | --- |
| `NVSDK_NGX_Parameter_FrameGeneration_Available == 0` | "NVIDIA DLSS Frame Generation not available on this hardware/platform" | `rtx_ngx_wrapper.cpp:523-528` |
| `FrameGeneration_NeedsUpdatedDriver` | "requires a newer driver" + min version | `rtx_ngx_wrapper.cpp:530-547` |
| **Hardware-accelerated GPU scheduling off** | "requires GPU hardware scheduling … enable it in Settings → System → Display → Graphics Settings" | `rtx_ngx_wrapper.cpp:548-557` |
| `NVSDK_NGX_DLSSG_Parameter_MultiFrameCountMax` query fails | "NGX parameter query for MultiFrameCountMax failed" | `rtx_ngx_wrapper.cpp:558-563` |

Streamline's guide states the same OS-level requirements for DLSS-G: Win10 20H1+ and **"Display Hardware-accelerated
GPU Scheduling (HWS) must be enabled"** (Streamline `docs/ProgrammingGuideDLSS_G.md` §1.0,
<https://raw.githubusercontent.com/NVIDIAGameWorks/Streamline/main/docs/ProgrammingGuideDLSS_G.md>).

### 2.3 The presenter — this is the hard requirement

DLFG needs a *Vulkan* swapchain whose images it can write, because it runs an NGX Vulkan DLSS-G evaluate and writes
interpolated frames directly into swapchain images:

- `class DxvkDLFGPresenter : public vk::Presenter` — `rtx_dlfg.h:134-240`, constructed **only** at
  `d3d9_swapchain.cpp:1422` inside `if (dlfgEnabled)`; the non-DLFG path constructs a plain `vk::Presenter`
  (`d3d9_swapchain.cpp:1428-1432`).
- With DLFG on, `GetPresenter()` returns the DLFG presenter (`d3d9_swapchain.cpp:450-458`) and the swapchain is
  **sized for N interpolated frames + 1 rendered frame** (`rtx_dlfg.h:166-168`, `imageCount++` at
  `d3d9_swapchain.cpp:1419-1421`).
- `D3D9SwapChainEx::CreatePresenter` additionally moves to the **present queue** and asks the device for
  `fullScreenExclusive` support (`d3d9_swapchain.cpp:1400-1413`).
- Interpolation: `DxvkDLFGPresenter::interpolateFrame` → `dlfg.dispatch(ctx, …, outputImage = swapchain image,
  colorBuffer = backbuffer, motionVectors = primaryScreenSpaceMotionVector, depth = primaryDepth, …)`
  (`rtx_dlfg.cpp:445-479`); the *real* frame is a plain `vkCmdCopyImage` of the backbuffer into the swapchain image
  (`rtx_dlfg.cpp:533-590`), so real frames and generated frames differ only by the interpolation.
- Motion vectors and depth are Remix's own (`rtx_context.cpp:2389-2398`), so **no game-provided motion vectors are
  needed** — good for our proxy.

**External-presenter mode cannot do frame generation.** `D3D9SwapchainExternal` overrides `Present`
(`src/d3d9/d3d9_swapchain_external.cpp:70`) and contains **zero** references to DLFG (grep for `dlfg|interp` in that
file: none). So `forceNoVkSwapchain = 1` and `rtx.dlfg.enable = 1` are mutually exclusive in practice.

**No fullscreen requirement exists in Remix's code** (no check on `Windowed` / `fullScreenExclusive` inside
`rtx_dlfg.*`); what *is* enforced is vsync: `RtxContext::dispatchDLFG` sets `rtx.enableVsync` to `Off` with the
comment "force vsync off if DLFG is enabled, as we don't properly support FG + vsync"
(`rtx_context.cpp:2376-2387`). Reflex is not optional either: when DLFG is on, the normal Reflex present markers are
skipped because "the DLFG Presenter will insert its own Reflex markers"
(`d3d9_swapchain.cpp:1315-1319`), with `__DLFG_REFLEX_WORKAROUND 1` in `rtx_ngx_wrapper.h:56`.

### 2.4 Does it work for API clients that present through `remixapi_Present`?

Yes, mechanically: `remixapi_Present` → `IDirect3DDevice9Ex::Present` → `D3D9SwapChainEx::Present` →
`DxvkDLFGPresenter`, which is the same code path a D3D9 game uses. Public evidence that the path *engages* in an API
client: NVIDIA's Minecraft port ships with FG on by default — "Restore DLSS Frame Generation to the default of
dxvk-remix" (<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/pull/75>, "FG still will be disabled for
benchmarks").

Known bugs on that path (all open unless noted):

| Bug | Report |
| --- | --- |
| GPU crash `VK_ERROR_DEVICE_LOST` in the Minecraft API client as soon as FG is enabled, any multiplier; fine without FG, 3440x1440 | <https://github.com/NVIDIAGameWorks/rtx-remix/issues/1119> |
| FG + Steam overlay: screenshots crash; cause narrowed to "our DLSS-FG implementation not playing well with Steam's overlay layer" (NVIDIA maintainer, internal REMIX-3899) | <https://github.com/NVIDIAGameWorks/rtx-remix/issues/769> (comment 2025-03-19) |
| Multipliers above 2× "feel off" / stutter even when the frame counter rises (5×, 6× worst) | <https://github.com/NVIDIAGameWorks/rtx-remix/issues/1078> |
| Screen flashing with FG on (D3D9 game) | <https://github.com/NVIDIAGameWorks/rtx-remix/issues/567> |
| Crash on window resize in the D3D9 swapchain path (`STATUS_HEAP_CORRUPTION`, stack in the WndProc of the runtime's `d3d9.dll`) — directly relevant to "Remix presents into the game window" | <https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/64> |

---

## 3. Question 3 — two APIs, one HWND

### 3.1 The rules as documented

- **DXGI, Microsoft (normative guidance):** *"Use one flip model swap chain per HWND. Do not target multiple flip
  model swap chains to the same HWND."*
  <https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/dxgi-flip-model>
  The same page: keep the **BitBlt** model only for legacy GDI interop, and the flip model is the one that gives
  present statistics/DWM composition. I could **not** find a documented DXGI error code for "second flip swapchain on
  the same HWND" (`CreateSwapChainForHwnd` documents only `E_OUTOFMEMORY` and `DXGI_ERROR_INVALID_CALL` for bad
  arguments, <https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgifactory2-createswapchainforhwnd>)
  — the actual failure mode of two flip swapchains on one HWND is **UNVERIFIED**; what is documented is "don't".
- **Vulkan (normative):** `VK_ERROR_NATIVE_WINDOW_IN_USE_KHR` — *"The requested window is already in use by Vulkan
  **or another API** in a manner which prevents it from being used again."*
  <https://registry.khronos.org/vulkan/specs/latest/html/vkspec.html> (VkResult section; Win32 platform section
  40.2.3, `vkCreateWin32SurfaceKHR`).
- **NVIDIA driver knob that decides which layer Vulkan presents through:** NVIDIA App → Graphics → **Global**
  Settings → *Vulkan/OpenGL present method*, which must be **Auto** for Remix to attach; "Prefer layered on DXGI
  Swapchain" is the failure case called out by NVIDIA's own Minecraft trouble-shooting
  (<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/54>). Under that setting the driver itself puts a
  DXGI swapchain under the Vulkan swapchain — i.e. it manufactures the two-swapchain conflict on purpose.

### 3.2 The observed failure, in our exact shape

NVIDIA's Minecraft Remix 0.1.0 attached Remix to Minecraft's own window and got:

```
Presenter: vkCreateSwapchainKHR failed, error code: VK_ERROR_NATIVE_WINDOW_IN_USE_KHR
Presenter: retrying to create swap chain without Exclusive FS
Presenter: vkCreateSwapchainKHR failed again, error code: VK_ERROR_NATIVE_WINDOW_IN_USE_KHR
Failed to create swap chain
Failed to initialize RTX Remix: Startup failed: GENERAL_FAILURE (error code: 1)
```

<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/53>. The fix in 0.1.1 was **not** a different
swapchain configuration: *"In 0.1.0 this almost always came with VK_ERROR_NATIVE_WINDOW_IN_USE_KHR … 0.1.1 presents
through its own window instead, so updating is the fix."*
<https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/54>.

That is the strongest available evidence for our P2: **Remix will not get a Vulkan swapchain on a window that another
API is already presenting to.** Note also the retry "without Exclusive FS" — the failure is not exclusivity-related.

### 3.3 Workarounds, ranked by evidence

| Workaround | Status / evidence |
| --- | --- |
| **Remix keeps its own window; the client composites or copies** (what we do today with a hidden window, and what Minecraft 0.1.1 does) | Proven in production by NVIDIA's own client (issue #54). No frame generation problem and no overlay problem on the Remix side, because Remix never touches the game's HWND. Cost: the per-frame readback the plan wants to remove. |
| **Remix on a borderless top-level window owned by us, placed above the game window** | Standard DWM layering; no two-swapchain conflict because each HWND has exactly one presenter. Not exercised by any project I found (**UNVERIFIED**): z-order, click-through (`WS_EX_TRANSPARENT`) and alt-tab behaviour would need testing. |
| **Remix on a child window (`WS_CHILD`) of the game window** | Mechanically the cleanest "one HWND, one swapchain" split, but a child window cannot be presented to independently of the parent's DWM surface in the flip model; **UNVERIFIED**, and no project found doing it. |
| **Withhold the game's `Present` and let Remix own the HWND** (P2 as written) | Requires Remix's `vkCreateSwapchainKHR` to succeed on an HWND whose D3D11 flip swapchain still exists. Nothing found that does this successfully. It can only work if the game's DXGI swapchain is destroyed or created on a *different* HWND (e.g. our own child window), which is a much bigger change than "withhold Present". |
| **Force the game's swapchain to BitBlt model** (`DXGI_SWAP_EFFECT_DISCARD`) | The flip-model "one swapchain per HWND" rule then does not apply to it. But BitBlt + Vulkan on one HWND is still two presenters on one window; the Microsoft guidance does not bless it. **UNVERIFIED.** Note `dxgi.dll` in the game folder would have to be intercepted — we already own `d3d11.dll` only. |
| **Set NVIDIA *Vulkan/OpenGL present method* = Auto globally** | Required regardless (issue #54). Not a fix for the conflict, a prerequisite for any diagnostic. |

---

## 4. Question 4 — overlays, HUD and frame generation

### 4.1 What DLSS-G wants (NVIDIA, normative)

From Streamline `docs/ProgrammingGuideDLSS_G.md` §5.1 (same URL as §2.2): for best quality it is *"critical"* to tag a
**Hudless** colour buffer (scene *before* UI) plus either **UI Alpha** (preferred, single channel) or **UI Color and
Alpha**, satisfying `Final_Color.RGB = UI.RGB + (1 - UI.Alpha) × Hudless.RGB`, with UI RGB pre-multiplied by alpha,
and Hudless/UI extents equal to the backbuffer. §12.0: *"DLSS-G takes over frame presentation"*, and FG must be turned
off by the app whenever the swapchain may deadlock (resolution change, full-screen ↔ windowed).

### 4.2 What Remix actually feeds it

Remix gives NGX **no separate UI buffer at all**: the interpolation input colour is the swapchain backbuffer
(`rtx_dlfg.cpp:470-473`), and into that same backbuffer Remix has already drawn its HUD and its ImGui menu
(`d3d9_swapchain.cpp:1235-1240`: `m_hud->render(...)` then `gui.render(...)`). So with FG on, **Remix's own overlay
and menu are inside the interpolated image** and will smear/distort exactly like any other HUD. There is no
`rtx.uiTextures`-style exclusion for the ImGui pass (`rtx.uiTextures` only gates *D3D9 texture* draws,
`rtx_options.h:187` + `src/d3d9/d3d9_rtx.cpp:592`).

Practical consequence for us: whatever we draw into Remix's frame to represent NieR's HUD (see 4.4) becomes part of the
FG input and will be interpolated. The options are (a) accept the smear (it is what Remix itself does), or (b) draw
the HUD *outside* Remix — which requires owning presentation.

### 4.3 Steam overlay

The overlay hooks the presents it finds; with Remix owning presentation it hooks Remix's Vulkan/D3D9-side present, and
NVIDIA has confirmed a live `DLSS-FG` × overlay bug (REMIX-3899, issue #769 above), with the official workaround being
"disable Frame Generation". The laptop-specific evidence (overlay `gameoverlayrenderer64.dll` cannot be kept out, and
the old rehook loop crashed) is in `web_ops_debug_framegen_alt.md` §3 and `LAPTOP_PORT.md:142-170`; I did not re-derive
it.

### 4.4 Is there any way for an API client to draw 2D UI into Remix's frame?

| Mechanism | Usable? | Evidence |
| --- | --- | --- |
| `remixapi_DrawUIInstance` / screen-space UI category | **Does not exist in 1.6.1.** The whole interface is 19 functions (`remix_c.h:805-833`); instance categories stop at `REMIXAPI_INSTANCE_CATEGORY_BIT_VIEW_MODEL = 1 << 26` (`remix_c.h:477-504`) and contain `WORLD_UI` (world-space) but no screen-space UI | `remix_c.h:477-504`, `:805-833` |
| Instances tagged `REMIXAPI_INSTANCE_CATEGORY_BIT_WORLD_UI` | The only supported way to get client-owned 2D content into Remix's frame: draw screen-space quads as instances with an unlit/emissive material. Colour-space and alpha handling must be matched by hand | `remix_c.h:477`; used by the sample's debug lines (same mechanism, `remixapi_example_c.c`) |
| `combineGuiInFinalColor = 0` + `dxvk_CopyRenderingOutput(GUI)` | Composites/reads **Remix's own** ImGui, not ours | `remix_c.h:222-227`, `:779`, `rtx_remix_api.cpp:1521-1526` |
| Write into the output image ourselves | Not exposed: `dxvk_GetExternalSwapchain` returns a `VkImage` only in `forceNoVkSwapchain` mode, and `dxvk_CopyRenderingOutput` copies **out of** Remix into a D3D9 surface | `rtx_remix_api.cpp:1440-1457`, `:1477-1560` |
| `rtx.uiTextures` | D3D9 texture hashes only — no meaning for our D3D11 proxy | `rtx_options.h:187`, `src/d3d9/d3d9_rtx.cpp:592` |

Note where our HUD lives today: `analysis/checks/hud_replay.h:1-14` replays the game's 56 alpha-blended HUD draws with
**our own D3D11 pixel shader into the game's D3D11 backbuffer**, inside our `Present` hook — i.e. entirely outside
Remix, after Remix's image has been copied in. If Remix takes over presentation, that code has no surface to draw on
until either (a) we hand Remix a HUD as `WORLD_UI` instances, or (b) we keep the game presenting and composite there.

---

## 5. Question 5 — DLSS mode control

| Item | Value | Evidence |
| --- | --- | --- |
| Option | `rtx.qualityDLSS`, type `DLSSProfile`, default **`Auto`**, env `RTX_QUALITY_DLSS`, `UserSetting` | `rtx_options.h:569-571` |
| Enum values (**must be sent as integers** — enums are `OptionType::Int` in the option system) | `UltraPerf=0, MaxPerf=1, Balanced=2, MaxQuality=3, Auto=4, FullResolution=5, Invalid=6` | `rtx_dlss.h:35-43`; `rtx_option.h:557-559` (`is_enum_v<T> → OptionType::Int`); parse path `rtx_option_dynamic.cpp:304-330` / `Config::parseOptionValue(int32_t&)` `config.h:372-375` |
| Human labels Remix shows | Ultra Performance / Performance / Balanced / Quality / Full Resolution / Auto | `dxvk_imgui.cpp:313-320`, `rtx_dlss.cpp:41-51` |
| **Preset override trap** | `rtx.dlssPreset` (`Off=0, On=1, Custom=2`, default **On**) *forces* `upscalerType = DLSS` **and `qualityDLSS = Auto`** whenever it is `On`. A `rtx.qualityDLSS` value set while `dlssPreset = On` is silently overwritten. To pin a mode you must also set `rtx.dlssPreset = 2` (Custom). | `rtx_options.h:83-87` (enum), `rtx_options.h:323-325` (option), `rtx_options.cpp:168-183` (`updateUpscalerFromDlssPreset`, the `case DlssPreset::On:` block) |
| Auto resolution | `Auto` resolves per display height (≤1080 → MaxQuality, <2160 → Balanced, <4320 → MaxPerf, else UltraPerf), biased down at Medium/Low graphics preset, and **overridden to MaxPerf on RTX Spark** | `rtx_dlss.cpp:101-135`; `rtx_gpu_profile.cpp:42`, `:225-232` |
| Where the render size comes from | NGX itself: `queryOptimalSettings(displaySize, perfQuality)` — Remix does not compute ratios | `rtx_dlss.cpp:165-171` |
| Where to read the result (for the gate) | Remix prints `"Computed DLSS Mode: <mode>, Render Resolution: <w>x<h>"` in the Graphics tab | `rtx_user_menu.cpp:421-430` |
| Ray Reconstruction | `rtx.enableRayReconstruction`, default **true**; when on, the *RR* profile is what matters, and the menu reads `rayReconstruction.getCurrentProfile()` instead of `dlss.getCurrentProfile()` | `rtx_options.h:511`, `rtx_user_menu.cpp:421` |

Expected render resolutions if the standard NGX factors apply (quality 2/3, balanced 0.58, performance 1/2, ultra
performance 1/3, DLAA 1.0) — **UNVERIFIED exact**: NGX rounds and may clamp, so treat the logged value
(`rtx_user_menu.cpp:430`) as the fact and these as the expectation:

| Output | Quality | Balanced | Performance | Ultra Performance | Full Resolution / DLAA |
| --- | --- | --- | --- | --- | --- |
| 2880×1800 | 1920×1200 | ~1670×1044 | 1440×900 | 960×600 | 2880×1800 |
| 3440×1440 | ~2293×960 | ~1995×835 | 1720×720 | ~1147×480 | 3440×1440 |

---

## 6. Question 6 — Windows on ARM (Prism) and RTX Spark N1X

| Point | Evidence |
| --- | --- |
| Remix 1.6.1 ships a **native ARM64 runtime**: release assets include `rtx-remix-for-arm64-games-release-remix-1.6.1.zip`, alongside `…-x64-games-…` and `…-x86-games-…` | <https://github.com/NVIDIAGameWorks/rtx-remix/releases/tag/remix-1.6.1> (asset list, fetched via GitHub API) |
| "**Windows on ARM:** Added Windows on Arm runtime support and public ARM64/ARM64EC build artifacts. Day 1 support for Portal RTX, Half-Life 2 RTX Demo and RTX Remix for Minecraft (Beta)." | same release notes, "Platform & Driver Requirements" |
| "**Up to 6× Multi Frame Generation:** Added 5× and 6× frame-generation choices on supported hardware." | same release notes |
| Minimum driver raised to **616.92** | same release notes |
| "Frame generation model … beta performance mode (Preset C for Frame Generation)" — this is `rtx.dlfg.litePreset` | same release notes; `rtx_dlfg.h:319` |
| Remix **auto-detects RTX Spark** and changes defaults: graphics preset → Medium, Auto DLSS → Performance (`MaxPerf`), low-memory mode if device-local heap ≤ threshold; detection = NVIDIA vendor + integrated GPU + NVAPI arch `GB200`, matched by LUID | `rtx_gpu_profile.cpp:42`, `:148-170`, `:173-186`, `:225-232`, `:265-275`; documented in `documentation/RemixConfig.md:122-130` |
| NVIDIA states the full DLSS suite, **including Dynamic Multi Frame Generation**, works on RTX Spark in supported games (i.e. under x64 emulation, since games are x64), "up to 5 additional frames per rendered frame" | <https://developer.nvidia.com/blog/nvidia-rtx-spark-powers-neural-rendering-and-ai-characters-in-games/> |
| Prism is the x86/x64 user-mode emulator; drivers must be native Arm64 | <https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation>; <https://docs.nvidia.com/rtx-spark/rtx-spark-porting-guide/latest/portingandemulation/index.html> |
| A process loads only same-architecture DLLs, so an x64 game on the laptop needs the **x64** Remix runtime and the x64 `nvngx_dlssg.dll`, both under Prism | `LAPTOP_PORT.md:21-27` (repo-internal, but it is a hardware fact); our downloaded x64 runtime does contain `runtime/nvngx_dlssg.dll` (`analysis/downloads/remix-1.6.1-x64/release-crc.txt:23`) |
| DLSS-G specifically under **x64 emulation** | **UNVERIFIED.** No public report found either way, and nothing in the repo measured it (`DRAW_HOOK_LOSS.md:47` saw `nvngx_dlssg.dll=absent`, but the runtime was not loaded in that run). The requirement that dlfg must pass `NVSDK_NGX_Parameter_FrameGeneration_Available` *and* HWS (`rtx_ngx_wrapper.cpp:523-557`) makes this the first thing to measure on the laptop — the answer is a log line, not an experiment. |
| Reflex under emulation | **UNVERIFIED.** No documented limitation found; Remix only requires that Reflex initialise (it logs "Reflex initialized successfully", cf. <https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/issues/64>). |

---

## 7. Where this contradicts `PLAN_2026-11-14.md`

| Plan text | What the evidence says |
| --- | --- |
| P2: "Remix presents into the game's window, the game's Present is withheld while Remix shows frames" | Withholding `Present` does not free the HWND. Remix's `vkCreateSwapchainKHR` on an HWND that still has the game's DXGI flip swapchain is the documented `VK_ERROR_NATIVE_WINDOW_IN_USE_KHR` failure (minecraft #53/#54) and Microsoft says "one flip model swap chain per HWND" (learn.microsoft.com DXGI flip model). The spike must therefore also try the alternatives in §3.3 — most cheaply "Remix on its own borderless top-level window above the game's", which is what NVIDIA's own API client settled on. |
| P2: "HUD drawn into Remix's frame" | There is no screen-space UI API in 1.6.1 (`remix_c.h:805-833`). Realistically the HUD becomes `WORLD_UI` instances, and with FG on it will be interpolated/smeared because Remix feeds the whole backbuffer to DLSS-G (`rtx_dlfg.cpp:470-473`). Current HUD code draws into the *game's* backbuffer (`checks/hud_replay.h:1-14`), which does not exist as a target once Remix presents. |
| P2: "enables DLSS frame generation and removes the per-frame readback" — as one item | DLFG and external-presenter/readback are mutually exclusive by construction (`forceNoVkSwapchain` → `D3D9SwapchainExternal`, which has no DLFG code), so this cannot be de-risked incrementally; it is one all-or-nothing switch. Also `rtx.dlfg.enable` defaults to **true** already (`rtx_dlfg.h:313`), so on the laptop FG may already be on today whenever the gate passes — worth checking the log before building anything. |
| P1: "set through the Remix API's `SetConfigVariable` (`remix_c.h:786`)" | Wrong line (it is `remix_c.h:724` for the typedef, `:816` for the interface member in the shipped 1.6.1 header; `:724/:810` in the copy our proxy includes). And it will not take effect unless `rtx.dlssPreset` is also moved off `On`/`Auto` (`rtx_options.cpp:174-178`), values must be **integers** (`rtx_option.h:557-559`), the call returns SUCCESS even for a value it ignored (`rtx_remix_api.cpp:1290-1303`), and it is **not persisted** (`rtx_user_menu.cpp:277-279`) — so "saved for the next launch" needs our own config file. |
| P2: ">= 40 fps presented at 2880x1800" | No contradiction, but two suppressions must be in the measurement's small print: DLFG forces vsync off (`rtx_context.cpp:2382-2386`), and "presented fps" ≠ rendered fps (`DxvkDLFGPresenter::getPresentFrameCount`, `rtx_dlfg.h:163-165`). |

---

## Open questions

1. **Does `vkCreateSwapchainKHR` actually fail on NieR's own HWND on the laptop?** Not determinable from documents:
   it depends on the NVIDIA driver's WSI and on whether the game's swapchain is a flip model one. Cheap test: point
   `StartupInfo.hwnd`/`PresentInfo.hwndOverride` at the game window in a debug build and grep the runtime log for
   `VK_ERROR_NATIVE_WINDOW_IN_USE_KHR` / `Presenter: retrying to create swap chain without Exclusive FS`
   (the exact strings are in minecraft #53). Also try the child-window and top-level-sibling variants the same way.
2. **Does DLSS-G pass its gate under x64 emulation on the N1X?** One run: does `remix-dxvk.log` contain
   "NVIDIA DLSS Frame Generation not available on this hardware/platform" or the hardware-scheduling warning
   (`rtx_ngx_wrapper.cpp:523-557`)? HWS state is visible in Windows Settings → Display → Graphics → default graphics
   settings.
3. **Does the laptop's shipped x64 `.trex` contain `nvngx_dlssg.dll`?** Our downloaded `remix-1.6.1-x64` does
   (`analysis/downloads/remix-1.6.1-x64/release-crc.txt:23`); the game's own `.trex` was never inventoried for it
   (`LAPTOP_PORT.md` lists the `.trex_arm64` NGX DLLs only).
4. **Whether a `WORLD_UI` quad can reproduce NieR's HUD** (alpha, sRGB, texture filtering, and whether Remix applies
   tone mapping to it) — needs a 20-minute spike with the sample client, not research.
5. **Whether Remix's ImGui and our HUD are separately controllable under FG** — `combineGuiInFinalColor` exists
   (`remix_c.h:227`) but its interaction with the DLFG backbuffer copy is unread code; check whether `gui.render` is
   skipped when `combineGuiInFinalColor = 0` in the *non*-external path.
6. **Steam overlay behaviour when Remix owns the window** — partly in `web_ops_debug_framegen_alt.md` §3; the open
   question is only whether the overlay hooks Remix's present at all on the laptop, which is a one-run observation
   (does the overlay appear over the path-traced image?).
7. **Whether `rtx.dlfg.*` survives `remixapi_SetConfigVariable`** (it is a `UserSetting`, so a user-layer write is
   allowed) and whether `hasDLFGFailed()` latches permanently after one failure (`rtx_dlfg.h:304`, flag at `:327`), which would make
   a mid-session retry impossible.

## Recommended steps for the plan

1. **Split P2 into three independently gated steps, in this order** (each one a switch defaulting to today's
   behaviour, gated in `analysis/checks/`):
   P2a *Remix frames a window the player sees* (hidden window → visible sibling window, readback kept);
   P2b *FG enabled* (`rtx.dlfg.enable`, `rtx.dlfg.maxInterpolatedFrames`, gated on the log lines in
   `rtx_ngx_wrapper.cpp:523-563`);
   P2c *Remix owns the game's window* (only if P2a's spike cannot reach the frame-rate target).
2. **Record the presentation-mode matrix as a gate before writing code**: extend the fake runtime
   (`analysis/checks/remix_live_fake_runtime.cpp`) to assert on `StartupInfo`/`PresentInfo` fields our proxy sends
   (`hwnd`, `forceNoVkSwapchain`, `combineGuiInFinalColor`, `hwndOverride`), so a wrong combination fails in the gate
   instead of at the laptop. Reference semantics: `remix_c.h:212-234`, `:728-734`.
3. **First laptop run for P2 is a 10-minute diagnostic, not a spike**: start the game with FG on and capture
   `remix-dxvk.log`; record (a) whether DLFG passed its gate and why not, (b) the `Computed DLSS Mode … Render
   Resolution` line (`rtx_user_menu.cpp:430`), (c) any `VK_ERROR_NATIVE_WINDOW_IN_USE_KHR`. This decides whether P2b
   is even available on the N1X.
4. **Before any window-target change, set NVIDIA App → Graphics → Global Settings → Vulkan/OpenGL present method =
   Auto** and note it in the run's environment record (minecraft #54).
5. **Replace P1's `SetConfigVariable` design with a three-key write plus a readback**, all through
   `remixapi_SetConfigVariable`, in this order: `rtx.dlssPreset = 2` (Custom), then `rtx.qualityDLSS = <0..5>`, then
   verify by parsing the "Computed DLSS Mode / Render Resolution" log line; persist the user's pick in **our** config
   (not `user.conf`). Unit-gate the integer encoding of `DLSSProfile` (`rtx_dlss.h:35-43`) against the fake runtime.
6. **Add an explicit note to P1 that `rtx.graphicsPreset` can bias or replace the DLSS mode**
   (`rtx_dlss.cpp:101-135`, `rtx_options.cpp:441-445`), and that on RTX Spark `Auto` resolves to `MaxPerf` — so the
   four menu rows must write explicit values, never `Auto`.
7. **For the HUD under FG (P2 + E1), pick one of two designs deliberately and write it into the plan**: either
   (a) HUD as `REMIXAPI_INSTANCE_CATEGORY_BIT_WORLD_UI` instances (survives FG, but is interpolated and must be
   re-authored as materials), or (b) HUD stays outside Remix and presentation stays with the game (today's
   architecture). Today's `hud_replay` code cannot be reused in either case without a rewrite
   (`checks/hud_replay.h:1-14`).
8. **Add the known FG/overlay bug to P2's risk line** with its source: rtx-remix#769 (REMIX-3899, workaround = turn FG
   off), #1119 (device lost in an API client), #1078 (>2× feels off), minecraft #64 (resize crash in the D3D9
   swapchain path).
9. **Correct the two factual slips in the plan** (`remix_c.h:786` line number; "saved for the next launch" via
   `SetConfigVariable`) and add the FG-forces-vsync-off fact to the frame-rate acceptance criterion.
