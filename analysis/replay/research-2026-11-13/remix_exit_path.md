**Short answer (source-only, nothing run):** `remixapi_Shutdown` does not join any thread itself. It force-releases the D3D9 device to refcount 0, then the D3D9 interface, then calls `sentry::shutdown()`. The waits come from the destructors that run inside those Releases. The most likely multi-minute cause is `RtxInitializer::waitForShaderPrewarm()`: it busy-waits with no timeout until the whole shader compile queue drains, and the stop flag for compiler threads is not set until later. `cancelLoading()` covers only asset/mod loading, not prewarm. This is a hypothesis; I did not confirm it at runtime.

Paths are relative to `analysis/runtime/src/dxvk-remix/`.

**(1) Shutdown**
- `src/dxvk/rtx_render/rtx_remix_api.cpp:1671` `remixapi_ErrorCode REMIXAPI_CALL remixapi_Shutdown(void) {`
- `:1674-1678` `while (true) { ULONG left = s_dxvkDevice->Release(); if (left == 0) break; }`. This drives refcount to 0 regardless of other owners.
- `:1682-1689` same forced-release loop for `s_dxvkD3D9`.
- `:1693` `dxvk::sentry::shutdown();`. Bounded: `src/util/util_sentry.cpp:82` `kSentryShutdownTimeoutMs = 4000`, applied at `:531`.
- Pointer wiring: `rtx_remix_api.cpp:1785` `interf.Shutdown = remixapi_Shutdown;`.

**(2) Threads and how they are joined**
- D3D9 device dtor (the wait path): `src/d3d9/d3d9_device.cpp:164-175` runs `Flush()`, `SynchronizeCsThread()`, `waitForIdle()`, `getCommon()->onDestroy()`.
- Submit + finish threads: `src/dxvk/dxvk_queue.cpp:44-45` create; `:57-58` `m_submitThread.join(); m_finishThread.join();` with no timeout. Stop is checked at `:179-185` and `:323-338`.
- CS thread: `src/dxvk/dxvk_cs.cpp:117-123` sets stop, then `m_thread.join()`; loop checks stop at `:174`.
- Shader compiler workers + writer: `src/dxvk/dxvk_state_cache.cpp:222-229`; joined in `:400-415` (`:411-414`). Workers check stop only between items (`:1046`, `:1055`).
- RTX async asset thread: `src/dxvk/rtx_render/rtx_initializer.cpp:128-131` spawn; joined at `:59-64`.
- Texture async threads: `rtx_texture_manager.cpp:445-463` (AsyncRunner, join `:460-462`); `:640-653` (AsyncRunner_RTXIO, join `:650-652`).
- USD mod rebuild thread: `src/dxvk/rtx_render/rtx_mod_usd.cpp:1841-1856` (`onDestroy`, join `:1849-1851`); backstop join in `~Impl` at `:1858-1863`.
- DLFG present/pacer threads: `rtx_dlfg.cpp:208-228`; stop-checked loops at `:630-639` and `:998-1005`.
- File watcher: `rtx_file_watch.cpp:599-607` (join `:605`). Each wait is timed by `WaitIntervalMS` (`:465`), default 100 ms (`rtx_options.h:1169`), so this join is short.
- Input ping thread (d3d9 swapchain): `d3d9_swapchain.cpp:382-392` join `:391`; loop uses `wait_for` with a stop predicate at `:1611`, so it exits promptly.
- Overlay thread: `rtx_overlay_window.cpp:83-93` (join `:91`).
- Message channel: `util_messagechannel.cpp:176-188` detaches instead of joining (`:186`), with comment `:182-184`.
- Shared thread-pool workers: `util_threadpool.h:314-325` (join `:323-325`); a worker only checks stop after a wait (`:385-398`).
- `dxvk::thread::join` waits `INFINITE`: `src/util/thread.cpp:38`. `~thread` calls `std::terminate` if still joinable (`:25-27`).

**(3) Waits with no timeout on exit paths**
- `rtx_initializer.cpp:201-209`: `while (m_device->getCommon()->pipelineManager().isCompilingShaders()) { Sleep(1); }`. `isCompilingShaders()` is `m_workerBusy > 0` (`dxvk_state_cache.h:123-125`). It drains the whole queue, not just the current item.
- Call order: `RtxInitializer::onDestroy` calls it unconditionally at `rtx_initializer.cpp:57`. The stop flag is set only later, in `dxvk_device.cpp:167` (`stopWorkerThreads()`), after `waitForIdle` (`:141`) and `release()` (`:144`).
- `dxvk_device.cpp:486` `vkDeviceWaitIdle` (in `waitForIdle`, `:477-489`). Bounded only by GPU work.
- `dxvk_cmdlist.cpp:173-177`: `while (status == VK_TIMEOUT) vkWaitForFences(..., 1'000'000'000ull)`. Retries forever.
- `dxvk_queue.cpp:114-120` `synchronize()` cond-waits with no timeout.
- `rtx_texture_manager.cpp:656-660` `syncPoint` spins with `_mm_pause` (caller `:948`).
- Bounded: `dxvk_queue.cpp:392` 5 s cap in `waitForAftermathDump`, and `:410-415` a device-lost path that sleeps forever. Both only on GPU crash.
- `dxvk_raytracing.cpp:102-111`: `DxvkDeferredOpFinalizer` is a `Singleton`. Its dtor calls `release()` (`:109-119`), which deletes the pool and joins its workers. Workers may be inside `vkDeferredOperationJoinKHR` (`:132-133`). Only a static-destructor path.
- Static `FileWatch` singleton: `rtx_file_watch.h:39`; dtor at `rtx_file_watch.cpp:567-569`.
- `rtx_common_object.h:62-77`: `atexit` leak logger only, non-blocking.

**DllMain / static destructors**
- No `DllMain` / `DLL_PROCESS_DETACH` in `src/` (grep). The only hits are comments: `src/d3d9/d3d9_main.cpp:49` and `src/tracy/client/TracyProfiler.cpp:1480`.
- `d3d9.dll` is a shim: `src/d3d9/d3d9_rtx_shim.cpp:23-25` (comment), `:150` `LoadLibraryW(g_shimTargetDllPath)`, `:291-295` forwards `remixapi_InitializeLibrary`. The shim has no `DllMain` and no `FreeLibrary`.
- Inference, not verified: the device is a heap object with no `DllMain` hook. A plain `ExitProcess` without `remixapi_Shutdown` should not run `~D3D9DeviceEx`. If the 230-320 s wait happens with no `Shutdown` call, look at static destructors (`DxvkDeferredOpFinalizer`, `FileWatch`) and the CRT.

**(4) Expected clean-exit order (code-derived; no docs found)**
- `remixapi_InitializeLibrary` (`rtx_remix_api.cpp:1769`) returns the function table. Its `sizeof(interf) == 176` `static_assert` is at `:1790`.
- `remixapi_Startup` (`:1595`) creates the device with `hwnd`. Registration is at `:1408` (`s_dxvkDevice = dxvkDevice;`).
- Per frame: `remixapi_Present` (`:1698`).
- Last: `remixapi_Shutdown` (`:1671`), once, before `ExitProcess`. Nothing else is needed; there is no separate window or device release in the API.
- Caveat: `Shutdown` forces the game's own COM references to 0 (`:1674-1678`). Do not use those objects afterward. Calling `Shutdown` moves the wait; it does not remove it.

**Not found**
- `remix_c.h` / `remixapi_Shutdown` docs: `include/` has only `gli`, `glm`, `vulkan`. The header is not in this tree.
- `DllMain` / `atexit` other than `rtx_common_object.h:62`.
- Callers of `RtxIo::release` (`rtx_io.cpp:265`): none found in src; only `dxvk_device.cpp:144` calls the initializer's `release()`.