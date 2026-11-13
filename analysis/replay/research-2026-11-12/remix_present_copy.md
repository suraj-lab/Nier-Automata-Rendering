## Scout report: dxvk-remix remix-1.6.1 readback path

**Caveat:** `remix_c.h` is not in this tree. `include/` holds only gli, glm, vulkan, and `public/` is absent (meson.build:200 expects it). The nearest copy is `analysis/runtime/remix-probe/sample/include/remix/remix_c.h`, which I did not verify against this tag. Its `remixapi_Interface` has 22 pointers, matching the `static_assert(sizeof(interf)==176)` at rtx_remix_api.cpp:1807. Header citations below use that copy.

### 1. CopyRenderingOutput, Present, StartupInfo

- **dxvk_CopyRenderingOutput** (rtx_remix_api.cpp:1453-1556). For `FINAL_COLOR` the source is the device back buffer 0 (1501-1504, 1517-1518), blitted nearest-neighbour into the caller's `IDirect3DSurface9` (1548-1549). The copy is only queued via `remixDevice->EmitCs(...)` (1506-1551) and the function returns `SUCCESS` without waiting. It executes in CS order after the most recent `Present`'s `EndFrame`/inject blit (d3d9_rtx.cpp:1279-1284; rtx_context.cpp:811). Lines 1465-1466 dereference `destTexInfo` before the null check at 1468.
- **OBJECT_PICKING** is special-cased (1472-1478). **GUI** fails with `GENERAL_FAILURE` unless `rtx.gui.enableExternalPresenter` is set, which defaults to false (1489-1492; dxvk_imgui.h:281).
- **remixapi_Present** (1698-1741) calls `remixDevice->Present(NULL, NULL, info->hwndOverride, NULL)` (1703). It then resizes the device with `ResetEx` if the window size changed (1708-1737). The condition at 1732-1733 uses `&&`, so a reset happens only when both dimensions change.
- **D3D9 Present path:** `D3D9DeviceEx::PresentEx` forwards to `m_implicitSwapchain->Present` (d3d9_device.cpp:3745-3758). In the normal swapchain that is `D3D9SwapChainEx::Present` (d3d9_swapchain.cpp:460-562). It sets `m_window = hDestWindowOverride` when non-null (508-510), recreates the presenter if the window changed (516, 541-542), then calls `PresentImage` (556).
- **StartupInfo** (remix_c.h:212-228; `sizeof` asserted as 40 at rtx_remix_api.cpp:1378):
  - `hwnd`: becomes the device window. Its client rect sets the back-buffer size (1612-1621, 1643-1650).
  - `disableSrgbConversionForOutput`: sets `g_allowSrgbConversionForOutput` (1352), which gates the sRGB conversion in rtx_context.cpp:780.
  - `forceNoVkSwapchain`: passed as `WithExternalSwapchain` (1343). This selects `D3D9SwapchainExternal` (d3d9_device.cpp:7925-7926). The header says "Use VkSwapchainKHR to present frame into HWND" when false (remix_c.h:217-220).
  - `editorModeEnabled`: sets the object-picking mapping flag, `g_remixApiEditorModeEnabled`, and several UI/light defaults (1353-1361).
  - `combineGuiInFinalColor`: sets `g_combineGuiInFinalColor` (1351). It is read only in the external presenter (d3d9_swapchain_external.cpp:84).

### 2. Own swapchain into an arbitrary HWND; vsync and pacing

- **Yes, when `forceNoVkSwapchain=false`.** The base constructor calls `CreatePresenter()` on `m_window` (d3d9_swapchain.cpp:353-357). That creates `new vk::Presenter(m_window, ...)` (1426-1431), which calls `vkCreateSwapchainKHR` on the HWND (vulkan_presenter.cpp:285). A later `hwndOverride` triggers a presenter recreate on the new window (d3d9_swapchain.cpp:516, 541-542). Nothing in this code limits the HWND to a top-level window. Whether a child or owned window works is not verified.
- **Present path (normal):** `D3D9SwapChainEx::PresentImage` calls `m_parent->Flush()` (1155), acquires an image (1200), blits the RT output into the swap image (1227-1229), renders HUD/GUI (1231-1235), runs `reflex.sleep()` (1257), then `SubmitPresent` (1244). `SubmitPresent` calls `m_device->presentImage(...)` on the CS thread (1288-1316). That reaches `vkQueuePresentKHR` (vulkan_presenter.cpp:148).
- **Vsync is not forced.** `PresentationInterval` is 0 for remixapi_Startup (rtx_remix_api.cpp:1640). The constructor sets `enableVsyncState` from it only when `rtx.enableVsync` is `WaitingForImplicitSwapchain` (d3d9_swapchain.cpp:345-347). `Present` then maps the state to interval 0 or 1 (490-503). `PickPresentModes` gives IMMEDIATE/MAILBOX when off and FIFO when on (1689-1705).
- **Options:**
  - `rtx.enableVsync`, default 2 in RtxOptions.md:279 (rtx_options.h:1119). Its docs say native game vsync is ignored.
  - `d3d9.presentInterval`, default -1 (d3d9_options.cpp:68; applied at d3d9_swapchain.cpp:486-487).
  - `d3d9.tearFree` (d3d9_options.cpp:101; used at d3d9_swapchain.cpp:1695-1700).
  - `d3d9.numBackBuffers` (d3d9_options.cpp:79; used at 1710-1711).
  - `d3d9.maxFrameLatency`, default 0 (d3d9_options.cpp:66). `SyncFrameLatency` waits on the signal (d3d9_swapchain.cpp:1587-1591, called at 1182).
  - `d3d9.maxFrameRate`, default 0 (d3d9_options.cpp:67). It drives the presenter's FPS limiter (d3d9_swapchain.cpp:1433; vulkan_presenter.cpp:173-176).
  - `rtx.reflexMode`, default LowLatency (rtx_options.h:1100-1104). It adds a CPU sleep in Present (d3d9_swapchain.cpp:1257).

### 3. DLFG

- DLFG is on when `rtx.dlfg.enable` (default true, rtx_dlfg.h:313), the NGX DLFG support check, and no failure hold. Those are combined in `DxvkContext::isDLFGEnabled` (dxvk_context.cpp:59-62).
- Frames are interpolated in `injectRTX`, via `dispatchDLFG` (rtx_context.cpp:802, 2336-2360). That forces vsync off (2341-2345) and queues `setupFrameInterpolation` (dxvk_queue.cpp:92-100).
- The DLFG presenter is created only in the swapchain's `CreatePresenter` when `isDLFGEnabled()` (d3d9_swapchain.cpp:1414-1425). Its frames are presented by `DxvkDLFGPresenter::presentImage` (rtx_dlfg.cpp:261-294). The queue calls `presenter->presentImage` for each present entry (dxvk_queue.cpp:247). Entries come from `SubmitPresent` (d3d9_swapchain.cpp:1316).
- **The external swapchain never calls `SubmitPresent` or `presentImage`** (d3d9_swapchain_external.cpp:45-110). My inference: with `forceNoVkSwapchain=true`, DLFG still interpolates, but its frames are never presented. Not verified at runtime.

### 4. Shared-handle routes and the full `dxvk_*` list

Within the C API, the struct registers these `dxvk_*` members (rtx_remix_api.cpp:1798-1803):
- `dxvk_CreateD3D9`: legacy wrapper around `remixapi_dxvk_CreateD3D9(StartupInfo)`. Creates `IDirect3D9Ex` (1338-1380).
- `dxvk_RegisterD3D9Device`: registers a device created by the host, and fails for non-Remix devices (1383-1411).
- `dxvk_GetExternalSwapchain`: returns the external presenter's raw `VkImage` and two semaphore handles as `uint64_t`. Fails unless the device is external (1413-1431; d3d9_device.cpp:7983-7988).
- `dxvk_GetVkImage`: returns the raw `VkImage` of a D3D9 surface (1433-1451).
- `dxvk_CopyRenderingOutput`: see section 1.
- `dxvk_SetDefaultOutput`: sets clear colours in `RtxGlobals` (1559-1593).

Other entries are `pick_RequestObjectPicking` and `pick_HighlightObjects` (1804-1805). **No C API function returns a Win32 or KMT shared handle.**

Shared handles do exist in the D3D9 layer. `CreateTexture` with `pSharedHandle` on DEFAULT pool creates a Vulkan image with Win32 KMT export (d3d9_device.cpp:511-519; d3d9_common_texture.cpp:259-270). The export is read at d3d9_common_texture.cpp:68-71 via `DxvkImage::sharedHandle()` (dxvk_image.cpp:259-270). Volume and cube textures reject shared handles (d3d9_device.cpp:549-550, 598-599). The MSDN-derived restrictions are at d3d9_common_texture.cpp:516-527. This route is public D3D9 API, not the Remix C API, and I did not verify it end-to-end.

### 5. Synchronisation points

- **CopyRenderingOutput:** `EmitCs` only, no flush or wait (rtx_remix_api.cpp:1506-1551).
- **GetRenderTargetData** (d3d9_device.cpp:974-1033). Its only CPU-side work is `EmitCs` of a `copyImageToBuffer` (1017-1027), then `SetWrittenByGPU` and `TrackTextureMappingBufferSequenceNumber` (1029-1030). It does not flush or wait. A DEFAULT-pool destination takes `StretchRect` instead (995-996).
- **The wait happens at Lock.** For a SYSTEMMEM destination with `wasWrittenByGPU` set, `LockImage` reaches `WaitForResource(mappedBuffer, Flags)` (d3d9_device.cpp:4685-4696). `WaitForResource` calls `Flush()` and `SynchronizeCsThread()`, then `m_dxvkDevice->waitForResource(...)` (4505-4522). That last call blocks on the submission queue until the resource is idle (dxvk_device.cpp:459-465).
- **Flush** submits pending work and signals a fence without waiting (d3d9_device.cpp:5688-5712). **SynchronizeCsThread** drains the CS thread (5246-5255).
- **Present (normal):** `PresentImage` calls `Flush` (d3d9_swapchain.cpp:1155). It then calls `SyncFrameLatency` (1182, 1591) and `SynchronizePresent` (1185).
- **Present (external):** `EndFrame` flushes (d3d9_rtx.cpp:1279). Then `Flush()` and `SynchronizeCsThread()` run on the caller thread (d3d9_swapchain_external.cpp:66-67). A frame-resume semaphore wait is queued (104-106).
- **Device reset:** `CreatePresenter` calls `waitForIdle` (d3d9_swapchain.cpp:1389). Any HWND change pays this cost.

**Inference for the 55 ms:** the readback stalls on the GPU work for the frame it reads, because Lock waits on that submission. The copies themselves are queued after it. Removing the readback removes that serial stall, but any alternative still needs a GPU-side fence.