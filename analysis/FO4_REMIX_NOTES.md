# Research: Kim2091/FO4-Remix (F4SE → RTX Remix via remixapi) vs. our NieR:Automata d3d11 proxy

Sources: I cloned the repo (default branch `master`) and read README.md, KNOWLEDGEBASE.md (KB), FO4RemixPlugin.ini, and these source files: src/remix_api.cpp, src/remix_renderer.cpp, src/skinned_meshes.{h,cpp}, src/draw_capture.h, src/raster_suppress.h, src/hzb_occlusion.h, src/window_manager.h, src/bs_extraction.cpp, src/resolvers/lighting_static.cpp, src/present_hook.cpp, and extern/remix/remix_c.h. I also compared against the upstream header at https://raw.githubusercontent.com/NVIDIAGameWorks/dxvk-remix/main/public/include/remix/remix_c.h.
Raw URL pattern: `https://raw.githubusercontent.com/Kim2091/FO4-Remix/master/<path>`

## Summary
FO4-Remix runs in-process. It gets geometry from Fallout 4's own scene graph: it hooks the engine's `GetRenderPasses` function and reads the engine's CPU-side vertex and index buffer copies. It only uses the D3D11 draw stream for side jobs: an occlusion signal and decoding precombined instances. Remix renders into its **own separate window**, driven by a dedicated Remix thread at about 60–120 fps. The plugin never reads Remix's output back into the game's backbuffer. Instead, it copies the game's UI render target into Remix with `DrawScreenOverlay`.

**Most important finding for us:** the plugin is built against a **forked Remix runtime**. Its header says `REMIXAPI_VERSION_MINOR 1000`, and the upstream header is 0.6.6. Several things it relies on don't exist in upstream remix_c.h:
- `CreateTexture` (textures uploaded from memory)
- `CreateMeshBatched`
- `MeshInfoRefreshGeometryEXT`
- `DrawScreenOverlay`
- `GetVramStats`
- `UpdateLightDefinition`
- `dxvk_GetSharedD3D11TextureHandle`

So several of its techniques only carry over to us if we adopt that fork too.

---

## Q1 Architecture

- **In-process, separate window.** The KB says the plugin "loads `d3d9.dll` from the game directory … creates a hidden D3D9Ex device, and registers it via Remix's `dxvk_RegisterD3D9Device` extension. A separate `Fallout 4 - RTX Remix` window receives the path-traced output." In practice the window is visible, not hidden. `src/remix_api.cpp` `CreateRemixWindow` uses `WS_OVERLAPPEDWINDOW | WS_VISIBLE`, class `L"FO4RemixWindow"`.
- **Device creation** (`src/remix_api.cpp`, `RemixAPI::Initialize`):
  - `remixapi_lib_loadRemixDllAndInitialize(L"d3d9.dll", &g_remixInterface, &g_remixDll)`
  - Then `dxvk_CreateD3D9(FALSE,&g_d3d9)`, then `CreateDeviceEx(... D3DCREATE_HARDWARE_VERTEXPROCESSING | D3DCREATE_MULTITHREADED ...)`, then `dxvk_RegisterD3D9Device`.
  - If that fails, it falls back to `Startup(&startupInfo)` with `hwnd = g_remixWindow`.
  - Comment in the code: "D3DCREATE_MULTITHREADED is LOAD-BEARING … dxvk's D3D9DeviceLock … compiles to a NO-OP without this flag". Without it, a create call from the game thread raced the Remix thread's Present (an access violation at `dxvk_cs.h:171`).
  - It uses the RegisterD3D9Device path so `Startup()` doesn't spawn the dev-menu overlay. That overlay's `RegisterRawInputDevices(RIDEV_NOLEGACY)` steals the game's input.
- **Window compositing:** `src/window_manager.h` has `[Window] OverlayMode=1`. It turns the Remix window into "a borderless, topmost, non-activating overlay glued to the game window's client rect". The game keeps focus, and raw input is re-registered to the game window on every Present (`RemixAPI::RebindRawInputToGameWindow`). The two windows are glued together, not composited. Optionally, `SuppressGameRaster` drops the game's own scene draws (shipped default 0).
- **Threads:**
  - The game thread runs `hkPresent` (a DXGI Present hook, vtable index 8), the `GetRenderPasses` detours, and `SemanticCapture::Tick`. Tick does the resolve and `SubmitDrawable` work: Create* calls happen on the **game thread**.
  - The Remix thread (`RemixThreadFunc`, started lazily on the first `hkPresent`) runs `OnFrame`: SetupCamera, then the DrawInstance loop, then Present.
  - The KB still says "~60 Hz with `Sleep(16)`". That is stale: `present_hook.cpp` now paces to `RemixMaxFPS` (ini 120) with `timeBeginPeriod(1)`, and its comment says "The previous flat Sleep(16) added a full budget on top of every frame's render time".
- **D3D11↔Remix image interop / readback: none for the Remix output.** The only image transfer goes the other way, game to Remix:
  - The UI render target is copied to a staging texture with `CopyResource` and mapped one or more frames later with `D3D11_MAP_FLAG_DO_NOT_WAIT` (`present_hook.cpp` comment: "Map-first capture … the game thread never blocks on the GPU pipeline").
  - It is then un-premultiplied and passed to the fork's `api->DrawScreenOverlay(pixels,w,h,fmt,1.0f)` (`remix_renderer.cpp`).
  - The fork header declares `dxvk_GetSharedD3D11TextureHandle(void** out_sharedHandle, uint32_t* w, uint32_t* h)` and `dxvk_CopyRenderingOutput`, but I found **no calls** to either in remix_renderer.cpp or present_hook.cpp.

## Q2 Geometry source

- **Scene graph, not draw capture.** The KB pipeline says the engine "fires `BSLightingShaderProperty::GetRenderPasses`". The detour (`semantic_capture.cpp`) builds `PassKey = FNV1a(geo, property, material)` and records the geometry/material pointers plus `m_worldTransform` (+0x70) into `g_drawableMap`. Terrain comes from a separate walk over `TESObjectLAND` quadrants every 60 frames.
- **Vertex/index bytes come from the engine's CPU copies, not GPU readback.** From `src/bs_extraction.cpp`:
  ```cpp
  auto* gfxData = static_cast<BSGraphics::TriShape*>(shape->pRendererData);
  uint8_t* vbData = static_cast<uint8_t*>(gfxData->pVB->pData);
  uint8_t* ibData = static_cast<uint8_t*>(gfxData->pIB->pData);
  ```
  GPU staging readback of buffers is used **only** for precombined "merge chunk" geometry (`lighting_static.cpp`): `sd.Usage = D3D11_USAGE_STAGING; ... ctx->CopySubresourceRegion(staging, 0, 0,0,0, buf, 0, &box);`. That path is asynchronous (`SliceStatus::kPending`) and range-checks the live buffer first, because "An out-of-range CopySubresourceRegion is silently dropped … but the Map still succeeds -- never-written staging memory … would come back as 'successful'".
- **Vertex format decode** is driven by Bethesda's packed 64-bit vertex descriptor nibbles (`bs_extraction.cpp`):
  - `oUV = (attrShift + ((desc >> 8) & 0xF)) * 4; oNormal = ...>>16...; oColor = ...>>24...; bool posHalfFloat = !(desc & BSGeometry::kFlag_FullPrecision);`
  - Output is `remixapi_HardcodedVertex` (pos/normal/uv/color).
  - BSDynamicTriShape morphed positions come from a separate dynamic VB.
- **Instancing:**
  - Drawables with byte-identical geometry and the same material share one mesh handle. The key is `(ContentHashOf(mesh), materialHash)`, where the content hash is FNV over the vertex and index bytes.
  - `OnFrame` buckets drawables by mesh handle. A bucket of one gets a plain `DrawInstance`. A bucket of more than one gets `remixapi_InstanceInfoGpuInstancingEXT` with per-member transforms (KB; ini `GpuInstancing=1`).
  - Precombines (`BSMergeInstancedTriShape`) are expanded with help from a D3D11 draw-capture hook. `src/draw_capture.h` hooks `DrawIndexedInstanced` (vtable 20) and DrawIndexed, then watches for draws that bind the shape's instance-record SRV at t8. This recovers the engine's per-chunk IB offsets ("pre-baked expanded mesh … ~2k-tri chunks … drawn as plain DrawIndexed with a per-chunk IB OFFSET"). Note: the KB "Known limitations" entry still calls precombine transforms "wrong (open, 2026-07-03)", while the ini ships `MergeInstanceExpansion=1` with "validated (1,0)". The KB is likely stale here (INFERRED).
- **LOD:**
  - Worldspace LOD chunks are identified by parent NiNode names (`"chunk"` + `"4"|"8"|"16"|"32"`, or `"obj"`).
  - A chunk is hidden when the engine stops firing it for `LodChunkStaleFrames=30`, with a backstop that hides a chunk when the player is inside its coverage box.
  - Each mesh carries one LOD; the plugin follows the engine's choice.
- **Culling — yes, they deliberately submit off-screen geometry within limits.**
  - `FrustumCull=1` uses a margin-expanded frustum (`FrustumFovMarginDeg=12`, hysteresis). Inside `FrustumKeepRadius=4096` ("~58 m per 4096" per ini header) everything is kept "so nearby off-screen geometry still shows in ray-traced shadows/reflections/GI".
  - `OcclusionCull=1` uses the engine draw stream as a visibility signal, keyed by `EngineIbKey(ib, offset)` (`draw_capture.h`): "a key drawn recently then stopped is occluded … a key NEVER seen … stays EXEMPT". It needs `OcclusionStaleFrames=30` and is suspended when the scene drew fewer than `OcclusionMinSceneDraws=500` keys.
  - CPU Hi-Z occlusion (`hzb_occlusion.h`, 256×144) exists but is off by default (`HzbCull=0`).
  - Culling is all-or-nothing per instancing bucket ("a partially-visible batch rides along whole").
  - Culled handles "stay warm": they are not destroyed. Behind-camera parking, which does release resources, only starts at 60% VRAM (`ForceEvictViewPct=60`).

## Q3 Mesh identity and updates

- **Hash scheme** (`remix_renderer.cpp`):
  ```cpp
  meshKey.contentHash = mesh.hasSkinning ? hash : (g_config.gpuInstancingEnabled ? ContentHashOf(mesh) : hash);
  meshInfo.hash = RuntimeMeshHashOf(meshKey); // FNV(materialHash) seeded by contentHash
  ```
  - The material is folded into the hash because "Remix API handles in this fork are the caller-provided 64-bit hash value, and CreateMesh registrations are immutable while that handle is live".
  - Skinned meshes are keyed per drawable, because two actors sharing one handle "would fight over the same skinned BLAS".
  - Textures are hashed as FNV of the texture *name* plus a post-process mode, and get a synthetic path via `HashToPath(hash)` → `L"0x%llX"`.
- **This matches what we measured.** KB: "the runtime IGNORES repeated registrations of a live handle". Their FaceGen refresh went through three versions (comment in `remix_renderer.cpp`):
  - v1, recreate under the same hash and then destroy the old one: heads vanished, "the runtime ignored the re-registration … and the DestroyMesh then unregistered the live mesh". This is our "same hash keeps old geometry / destroy+recreate" result.
  - v2, a fresh salted hash: worked, but caused **ghosting**, because "a new hash per refresh handed the scene manager a brand-new object … no motion vectors and no denoiser history". This is our "new hash then destroy old works" result, and it has a temporal-quality cost we should expect.
  - v3 keeps the hash and uses the **fork-only** `remixapi_MeshInfoRefreshGeometryEXT` (`sType = REMIXAPI_STRUCT_TYPE_MESH_INFO_REFRESH_GEOMETRY_EXT`, `meshInfo.hash = (uint64_t)inst.meshHandle`).
- **Lifetimes:**
  - Entries in `g_drawableMap` expire after `kTTLFrames = 18000` (5 min) without an engine fire, swept every 60 frames.
  - Mesh/material/texture handles are refcounted.
  - Destroys are **deferred**: they are parked in `g_pendingDestroys` and drained on the Remix thread every 30 frames (`kDestroyDrainPeriodFrames`). With `DeferHandleDestroyToLoad=1` they wait until load screens. `CancelParkedHandle` rescues a handle that is recreated before its parked destroy runs. Reason given: a destroy between DrawInstance and Present makes the runtime's `.at()` throw `std::out_of_range`.
  - Creates use the fork's `CreateMeshBatched`, which "deep-copies the provided info and defers DXVK buffer allocation … to the next render thread flush point". Plain `CreateMesh` from the game thread raced Present (the "four-crash night").
  - Every API call is wrapped in both SEH and C++ try/catch (`RemixCallGuarded`), and minidumps are written from the SEH filter.
- **Budgets:**
  - `ResolveBudgetMs=3.0` per frame on the game thread.
  - `MaxUploadMiBPerTick=48`.
  - VRAM gate: resolving pauses at 90% of `driverBudgetBytes` (fork `GetVramStats`).
  - Texture/material LRU grace of 600 frames.
  - CPU decoded-texture cache of 1024 MiB.
  - `MaxTextureDimension=2048`.
  - `AsyncMeshParse=1` (a 2-thread pool) for big merges.
- **Per-frame cost numbers:** see Q6.

## Q4 Animated / skinned meshes

- **Supported, using API GPU skinning with 4 bones per vertex.** The KB "Remix integration" line "Skinning hasvalue is always 0" is **stale**; the code and the `[Skinning] Enabled=1` ini setting contradict it. From `remix_renderer.cpp`:
  ```cpp
  // 4-bone rigid layout (FO4 VB: 4x f16 weights + 4x u8 indices, widened at parse)
  surface.skinning_value.bonesPerVertex = 4;
  surface.skinning_value.blendWeights_values = mesh.blendWeights.data();   // float, 4/vertex
  surface.skinning_value.blendIndices_values = mesh.blendIndices.data();   // uint32, 4/vertex
  ```
- **Weight decode** (`bs_extraction.cpp`): three half-float weights are read and renormalised if their sum is over 1, then `w3 = 1 - (w0+w1+w2)`. Indices are `uint8` widened to `uint32`. A degenerate row becomes rigid to bone 0.
- **Bone transforms** (`src/skinned_meshes.h`):
  - Bones are read from the scene graph (`BSSkin::Instance::worldTransforms` +0x28, inverse binds from `BoneData`), composed as `IB*BW`, transposed to column-vector 3×4, and sent each frame through `remixapi_InstanceInfoBoneTransformsEXT` (at most 256 bones).
  - The Beth→Remix axis swap goes in the instance transform, not in the bones.
  - A skinned instance isn't drawn until its first bone set arrives (otherwise it would T-pose at the origin).
  - The header notes the engine's own skinning CBs are camera-relative (posAdjust), and says those CBs are "irrelevant here because matrices are built from the scene graph, not captured from shader constants".
- **Weight-stride bug:** they use 4 bones per vertex successfully, but on their **forked runtime**. I couldn't confirm whether the fork fixed the weight-stride bug we hit on upstream (2 bones per vertex works for us). INFERRED: the fork probably differs; check the fork's skinning code before trusting 4 bones per vertex upstream.
- **Face morphs and eyes:**
  - FaceGen dynamic vertex buffers are fingerprinted every 2 frames, with at most 8 rebuilds per tick, and rebuilt in place via RefreshGeometryEXT (fork only).
  - Iris gaze comes from `material + 0x0C` UV offset/scale and is baked into the vertex UVs.

## Q5 Camera, lights, sky, water, materials

- **Camera:**
  - Read from `g_playerCamera` → `cameraNode->m_worldTransform`. `[Camera] FovFromFrustum=1` reads the live NiCamera frustum.
  - Submitted with `remixapi_CameraInfoParameterizedEXT` (position, forward, up, right, fovY, aspect, near, far) with X/Y swapped.
  - A second `REMIXAPI_CAMERA_TYPE_VIEW_MODEL` camera is submitted for first-person, and the plugin enables `rtx.viewModel.enable`.
  - Fallback when the camera is unavailable: FOV 75, aspect 1280/720, near 0.1, far 1000.
- **Lights:** the KB says lights are "retired", but the code revived them (`present_hook.cpp`: "Placed lights (revived 2026-07-07)").
  - Sphere lights only, via `remixapi_LightInfoSphereEXT`. Spot lights are sphere lights with `shaping` (cone angle from the FO4 FOV).
  - Conversion (`bs_extraction.cpp`):
    ```cpp
    const float intensity = fade * kLightIntensityScale * (float)rawRadius; // kLightIntensityScale = 0.1f
    light.radiance[0] = r * intensity; ...
    ```
  - Emitter size (`remix_renderer.cpp`): `rec.radius = max(light.radius * 0.025f * g_config.lightRadius, 0.5f)`.
  - Lights are polled from LIGH refs every 60 frames and diffed. Changed lights are updated in place with the fork's `UpdateLightDefinition`, so "persistent RTXDI reservoirs survive", with destroy+recreate as the fallback. `DrawLightInstance` is called each frame.
- **Sky / time of day:** there is no sky geometry. `weather_bridge.cpp` reads GameHour and pushes two values with `SetConfigVariable`: `rtx.atmosphere.sunElevation = sin((hour-6)/12*pi)*90` and `rtx.atmosphere.sunRotation = hour/24*360`. Weather and fog are not wired. Config writes are queued from the game thread and applied on the Remix thread, because `SetConfigVariable` contended the Remix-thread mutex (the "freezes until alt-tab" bug).
- **Water:** submitted with `MaterialInfoTranslucentEXT`: `refractiveIndex=1.33`, `transmittanceMeasurementDistance=500`, `transmittanceColor = kDeepColor`. The normal map is `spNormalMap01` converted to octahedral. Diffuse is a dummy 1×1 blue texture. Water instances get `REMIXAPI_INSTANCE_CATEGORY_BIT_ANIMATED_WATER`.
- **Materials / texture slots:**
  - Diffuse is `spDiffuseTexture`. It is forced to UNORM sampling (`ToUnormRemixFormat`, "force the ALBEDO/diffuse map to be sampled linearly").
  - Normal is `spNormalTexture`, converted to octahedral on the CPU (a port of NVIDIA's LightspeedOctahedralConverter).
  - Emissive is the glow map plus `pEmissiveColor * fEmitColorScale`.
  - Roughness: the KB says the `_s.dds` maps were removed and a constant 0.8 is used, but the ini has `RoughnessMapsEnabled=1, RoughnessMapFloor=0.15` (contradiction, probably revived).
  - Envmap-type metals get an albedo luminance floor of 0.25.
  - Alpha test/blend comes from `NiAlphaProperty` and is mapped to Vk enums.
- **Texture export: not DDS on disk.** Textures are uploaded from memory with the fork-only `api->CreateTexture(remixapi_TextureInfo*)` (packed mip chain, BC1/3/5/7 or RGBA8/BGRA8) and referenced by the synthetic path `L"0x%llX"`.
  - Source order: authored loose DDS / BA2 archive mips (read off-thread) first, then async GPU readback of every mip from the live texture (`ReadbackAllMipsAsync`, staging plus `Map(..., D3D11_MAP_FLAG_DO_NOT_WAIT)`).
  - BC data is only decoded when a post-process needs it.
  - Decoded results are cached on disk at `%LOCALAPPDATA%\FO4Remix\texcache` (up to 8 GiB).
  - Upstream remix_c.h has **no** `CreateTexture`.

## Q6 Performance numbers and limitations (KB + ini)

**Numbers:**
- Plugin game-thread work, as diagnostic snapshots (not a controlled benchmark): about 16.4 ms (7,939 drawables), then 9.6 ms (8,106), then 7.4 ms (8,268), after making diagnostic hooks opt-in.
- The texture "preserve win" is about 93–95%; destroys every frame would kill it, hence the 30-frame drain.
- A 13.5/14.7 GiB VRAM pileup dropped to 1 fps, which motivated the parking tiers.
- Single giant merge resolves hitched for about 35 ms, which motivated `AsyncMeshParse`.
- More than 4 BC decode workers was measured slower than 4.
- A 4-submissions-per-frame cap "starved streaming" and was removed.
- The HUD overlay capture is "a `CopyResource` + blocking `Map(READ)` on the game's render thread" with "measurable cost". It was later made non-blocking (map-first).
- Authored BA2 textures were loaded at 2048² where the live GPU resource was only 512².

**Limitations:**
- Weather is time-of-day only.
- Terrain uses one landscape layer.
- Face morph refresh is experimental.
- Overlay opacity is hardcoded to 1, with no menu input routing.
- Texture refcount leaks on failure paths are accepted.
- Cubemaps, arrays and render targets fall back to GPU readback.
- **The KB is internally stale in places:** lights retired vs. revived, skinning `hasvalue` always 0 vs. 4-bone skinning, roughness removed vs. `RoughnessMapsEnabled=1`, Sleep(16) vs. RemixMaxFPS pacing. Trust the code and ini.

## Q7 Techniques for a D3D11 game without an engine SDK (NieR)

| # | Technique | Verdict | Why |
|---|---|---|---|
| 1 | Separate Remix window glued over the game window as a topmost borderless overlay (`OverlayMode`). Removes our ~150 ms GetRenderTargetData+LockRect readback entirely. | ADOPTABLE | Pure Win32 (`window_manager`); no engine access. Trade-off: no in-backbuffer composite; works best in windowed/borderless mode. INFERRED: under Proton, topmost overlay behaviour depends on the WM. |
| 2 | `dxvk_RegisterD3D9Device` with `D3DCREATE_MULTITHREADED` instead of `Startup()`, plus rebinding raw input to the game HWND every Present | ADOPTABLE | Both are in the upstream API (dxvk_CreateD3D9 and RegisterD3D9Device exist upstream). The MULTITHREADED flag fixes cross-thread create/Present races. |
| 3 | Make all Create* calls on the Remix thread, or defer them; never Destroy between DrawInstance and Present. Park destroys and drain them at the top of the frame every N frames, with a cancel-on-recreate path. | ADOPTABLE | Same race class as our same-hash destroy crash; fixed purely on the client side. |
| 4 | Mesh hash = content hash (VB+IB bytes) folded with the material hash; share one handle and batch with `InstanceInfoGpuInstancingEXT` | ADOPTABLE | `GpuInstancingEXT` is upstream; we already hash captured buffer bytes. |
| 5 | Stable-hash geometry refresh (`MeshInfoRefreshGeometryEXT`) | NEEDS fork runtime (not engine) | Fork-only. Upstream we're stuck with new-hash-then-destroy-old, which FO4 found costs motion vectors and denoiser history (ghosting). Use it sparingly for CPU-skinned meshes, or move to API skinning. |
| 6 | API GPU skinning: bind-pose mesh once + per-frame `InstanceInfoBoneTransformsEXT` | ADOPTABLE with caveat | We can recover bones from the skinning CB; they read the scene graph instead, and note the engine CBs are camera-relative. 2 bones/vertex works for us; their 4 bones/vertex runs on the fork. Removes per-frame CPU-skin mesh recreation. |
| 7 | Occlusion signal from the D3D11 draw stream: key = (IB ptr, offset); drawn recently then stopped means cull; never-seen keys are exempt; suspend when the frame has few draws | ADOPTABLE | We already sit on the draw stream. Caveat: we only *know about* geometry the game draws, so stale/occluded geometry stays in the TLAS only if we cache it. |
| 8 | Keep off-screen geometry within a keep radius plus a margin-expanded frustum with hysteresis; cull whole buckets; keep handles warm | ADOPTABLE | Needs a geometry cache that persists across frames (we have mesh caching); pure client logic. |
| 9 | Async GPU readback: staging copy + `Map(DO_NOT_WAIT)` polled on later frames, with range-checks against the live buffer before `CopySubresourceRegion` | ADOPTABLE | Directly applicable to our VB/IB/CB readback fallback and texture readback; removes pipeline stalls. |
| 10 | Read engine CPU copies of VB/IB (`pRendererData->pVB->pData`) | NEEDS-ENGINE-ACCESS | Engine-struct reads. Our closest equivalent is the CPU shadows of Map/UpdateSubresource that we already keep. |
| 11 | Event-driven capture from `GetRenderPasses`, TTL-based drawable lifetime, retry/backoff resolve | NEEDS-ENGINE-ACCESS (hook) / ADOPTABLE (TTL+backoff) | The engine function hook needs an RVA. The TTL and exponential-backoff retry pattern applies to draw-capture keys. |
| 12 | Textures from memory via `CreateTexture` with synthetic hash paths | NEEDS fork runtime | Not in upstream remix_c.h; upstream needs file paths (DDS on disk). |
| 13 | Normal maps converted to octahedral on the CPU (LightspeedOctahedralConverter port); albedo forced to UNORM | ADOPTABLE | Pure texture processing. Applies whether we write DDS or upload from memory. |
| 14 | Decoded-texture disk cache keyed by stable hash; worker pool capped at 4; per-tick upload MiB budget; `MaxTextureDimension` cap | ADOPTABLE | Pure client-side. |
| 15 | Time of day via `SetConfigVariable("rtx.atmosphere.sunElevation/sunRotation")`, queued to the Remix thread | ADOPTABLE if we can source the sun direction | Upstream API. NieR has no SDK, but the sun direction can probably be read from a lighting CB (INFERRED). |
| 16 | Sphere/spot lights from engine light records, radiance = color·fade·0.1·radius, emitter radius = 0.025·range; live update keeps reservoirs | ADOPTABLE (formula) / NEEDS fork (UpdateLightDefinition) | Our lights come from CBs. The conversion heuristic is reusable; without the fork, recreate only on change and keep the same hash. |
| 17 | Water as translucent material + `ANIMATED_WATER` category | ADOPTABLE | Upstream API; needs a heuristic to detect water draws (shader hash). |
| 18 | UI overlay via `DrawScreenOverlay` with non-blocking capture of the UI render target | NEEDS fork runtime | Fork-only API. Without it, the overlay-window approach (1) shows no UI unless the game window shows through. |
| 19 | Suppress the game's raster draws after observing them (`RasterSuppress`): forward UI-phase draws and occlusion-query draws only | ADOPTABLE | Done at the D3D11 hook layer, which our proxy already has. Frees the GPU and VRAM for Remix. Only makes sense with the separate-window design. |
| 20 | Separate VIEW_MODEL camera | NOT-APPLICABLE (mostly) | NieR is third-person. |
| 21 | Precombine expansion via draw capture of the instance SRV | NOT-APPLICABLE | Specific to FO4 precombines; we already capture actual draws. |
| 22 | SEH + C++ guards around every remixapi call, with minidumps written from the SEH filter | ADOPTABLE | Cheap robustness; makes crashes inside the runtime diagnosable. |

## Contradictions
- The KB contradicts the current code and ini on lights, skinning, roughness maps and frame pacing (details in Q6). I treated code and ini as authoritative.
- Precombine transforms: the KB lists them as an open bug, while the ini says the decode was "validated". I didn't resolve this.

## Missing evidence
- Which dxvk-remix fork and commit the plugin targets. The header only says MINOR 1000 ("Remix Plus" ABI). I didn't inspect the fork's skinning code for the weight-stride bug.
- I didn't fully read `camera.cpp`, `weather_bridge.cpp` or `semantic_capture.cpp`; their claims rest on the KB plus excerpts.
- There are no controlled benchmark numbers, only diagnostic snapshots.

## Sources
- Kept: README.md, KNOWLEDGEBASE.md, FO4RemixPlugin.ini, and the files under src/ listed at the top (repo https://github.com/Kim2091/FO4-Remix). Primary sources.
- Kept: the fork's extern/remix/remix_c.h vs. upstream https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/public/include/remix/remix_c.h. Used to sort out which features are fork-only.
- Deprioritized: the KB's limitations prose where it disagrees with the code (stale).

## Next steps
1. Find the fork's repo/commit and check whether it fixes `bonesPerVertex>2` and whether RefreshGeometryEXT, CreateTexture and DrawScreenOverlay can be adopted (they need a runtime swap).
2. Prototype technique 1+2 (glued Remix window) under Proton to see whether it removes the 150 ms readback.

Skipped: full reads of camera.cpp, weather_bridge.cpp and semantic_capture.cpp, and a check of the fork's runtime source. Risk: several adoptable-looking techniques depend on the fork's ABI (MINOR 1000), which won't load against upstream binaries.
