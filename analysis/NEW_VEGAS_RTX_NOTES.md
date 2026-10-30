# Research: Kim2091/New-Vegas-RTX (FNV → Remix via the bridge) vs. our NieR:Automata D3D11 in-process proxy

**Sources read:**
- The cloned repo at HEAD, with tree root `b1e982f`. The `runtime` submodule is pinned at `925d7ab`.
- From that repo:
  - README
  - `docs/fnv-api-only.md`, `docs/perf-profile.md`, `docs/engine-classification.md`, `docs/hook-compat.md` (first 40 lines)
  - `assets/.trex/bridge.conf`
  - `deps/bridge_api/bridge_remix_api.h`
  - `src/shared/common/remix_api.cpp`
  - `src/comp/d3d9_proxy.cpp`
  - `src/comp/game/api_mesh.hpp`, `api_submit.cpp`, `api_skinned.cpp` (lines 1–1010 of 1309)
  - `stable_origin.hpp`, `ui_boundary.hpp`
- From the fork `Kim2091/dxvk-remix` branch `fnv/main` (Remix Plus), fetched as raw files rather than cloned:
  - `README`
  - `docs/RemixApi.md`, `docs/api-host-path-migration.md`
  - `public/include/remix/remix_c.h`
  - `src/dxvk/rtx_render/rtx_remix_api.cpp`
  - `bridge/README.md`, `bridge/src/client/remix_api.cpp`
- Upstream `NVIDIAGameWorks/dxvk-remix` main `rtx_remix_api.cpp`, used for the diff.
- The RemixProjGroup and NVIDIA release pages.

I did not read the NVSE plugin sources beyond the docs' description of them, because of the time box.

**Where FNV differs from FO4-Remix:** for FO4 see `analysis/FO4_REMIX_NOTES.md`, which I won't repeat.
- **Process model.** FNV runs out of process through the 32-bit bridge. FO4 ran in process as x64.
- **Output.** FNV renders into the game's own window. FO4 used a separate glued window.
- **HUD.** FNV draws its HUD as plain D3D9 raster after the runtime's RTX "injection". FO4 used a CPU `DrawScreenOverlay`.
- **Skinning source.** FNV captures bones from **VS constants at draw time**, which is close to what we do. FO4 read them from the scene graph.
- **Static objects.** FNV uses the fork's **retained instances**, plus a stable render origin.
- **Header version.** Both use the same fork family, but the header is now `0.1000.1`.

---

## Q1. Bridge

**How the wrapper loads the bridge.**
- The bridge is installed as `d3d9_remix.dll` next to the game. The wrapper `d3d9.dll` `LoadLibraryA`s it and resolves the D3D9 exports from it. Excerpt from `src/comp/d3d9_proxy.cpp`, `init()`:
  ```cpp
  chain_module_ = LoadLibraryA(cfg.remix.dll_name.c_str()); // default d3d9_remix.dll
  ...
  shared::globals::d3d9_chain_module = chain_module_;
  ```
- The wrapper first checks that `.trex\NvRemixBridge.exe` or `trex\NvRemixBridge.exe` exists (`renderer_installed()`). If it doesn't, it falls back to the system `d3d9.dll`.
- The game then creates its device through the bridge's `Direct3DCreate9`, so the **game's own device is the bridge device**.

**Init sequence** (`src/shared/common/remix_api.cpp`):
- `GetProcAddress(chain_module, "remixapi_InitializeLibrary")`, then `pfn_init(&{INITIALIZE_LIBRARY_INFO, VERSION_MAKE(0,1000,1)}, &iface)`, then `remixapi_RegisterCallbacks(beginScene, endScene, present)`.
- The upstream helper `bridge_initRemixApi` uses `GetModuleHandleA("d3d9.dll")`. The wrapper deliberately avoids it. Its comment: "This DLL is d3d9.dll … would find it instead of the Remix bridge".
- `bridge.conf` (`assets/.trex/bridge.conf`) sets only one value: `exposeRemixApi = True`. The file itself describes this as "EXPERIMENTAL … Defaults off". Everything else in it is commented-out defaults.

**What goes over IPC** (fork `bridge/src/client/remix_api.cpp`):
- Every interface call becomes a `ClientMessage(Commands::RemixApi_*)` that is serialised into the shared-memory ring. These are:
  - CreateMaterial, DestroyMaterial
  - CreateTexture (the full pixel payload goes in its own data-queue entry)
  - CreateMesh, DestroyMesh
  - DrawInstance, including the BoneTransforms, Blend, MaterialOverride, GpuInstancing, Picking and Particle extensions
  - CreateLight, DestroyLight, DrawLightInstance
  - SetupCamera
  - SetConfigVariable
  - the retained-instance calls
  - host settings and colour grades
- **Handles are minted on the client side**, so creates do not wait for the server. Retained handles come from `g_nextRetainedHandle`, and mesh uids come from `MeshHandle fresh`.
- **`CreateMeshBatched` is just `CreateMesh` on the bridge.** Comment: "across the bridge a plain CreateMesh is already async".
- **Not available through the bridge:**
  - `Startup`, `Shutdown` and `Present` are commented out of the interface table: `// interf.Present = remixapi_Present;`.
  - `dxvk_CreateD3D9` and `dxvk_RegisterD3D9Device` return `GENERAL_FAILURE` with the message "Device used by Remix API defaults to most recently created by client application."
  - `dxvk_CopyRenderingOutput` and picking are commented out.
  - `DrawScreenOverlay` is not forwarded.

**Threading and cost.**
- The wrapper issues API calls from the game thread, inline in its D3D9 draw hooks. It also uses BeginScene and Present callbacks. For example, `retained::replay_for_frame` runs "from the frame's first BeginScene" (`api_mesh.hpp`).
- `bridge.conf` documents these defaults:
  - `threadSafetyPolicy = 1` (force thread-safe)
  - `presentSemaphoreEnabled = False`
  - `commandBatchingEnabled` "not fully implemented"
  - channel memory 96 MB client→server (the commented sample is 192 MB)
  - command queues of 3000–6000 items
- The wrapper's answer to per-call cost is **fewer calls**:
  - Statics are retained. Per frame, only changes cross the bridge: "one batched `UpdateRetainedInstances` ends the frame; one `DrawRetainedInstances(O)` starts the next" (`api_mesh.hpp`).
  - It folds repeated draws of the same entry.
  - It throttles builds with a fair queue: 64 small-mesh builds per frame and an 8 MB texture-upload soft budget (`fnv-api-only.md`).
- I found no per-call µs number specific to the bridge. The fork README only says "Faster 32-bit bridge: less work per command and fewer round trips".

**Known bridge limitations and fixes found:**
- **Upstream skinning-size bug.** On a client without the fork's fix, "a skinned CreateMesh reads ~64 x V^2 bytes past the caller's arrays and kills the game". The wrapper detects the fix by searching the client image for the string `"Invalid skinning on surface"` (`api_skinned.cpp`, `bridge_has_skinning_fix`).
- **Mesh uid leak and refresh bug.** Upstream minted a new uid for each refresh. The fork now keeps "one uid per live hash" (`g_meshUidByHash`). Its comment: minting a fresh uid "leaked one server handle-map entry each time, and a DestroyMesh on any of those uids destroyed the one shared mesh."
- **Asset keys** are forwarded on MeshInfo only, not on MaterialInfo (`RemixApi.md`).
- **Version check.** The client rejects any app whose major is 0 and whose minor is not equal to its own (`isRemixApiVersionCompatible`). So a 0.6.x-built caller gets `INCOMPATIBLE_VERSION` from a 0.1000 client.

**Could a D3D11 process use the bridge client the same way?**
- **Yes in principle, with two hard conditions:**
  1. The process must create **a D3D9 device through the bridge client**. The API binds to "the most recently created" client device, and frame end is that device's `Present`, because `remixapi_Present` is not exposed. For us that means a hidden or overlay HWND and a D3D9Ex device made with the bridge's `Direct3DCreate9`. *(INFERRED from the excerpts above.)*
  2. **The bridge client must match the process bitness.** `bridge/README.md` says the client "is built by the x86 solution"; the bridge exists "for enabling a 32-bit game to interact with the 64-bit Remix Runtime". **NieR:Automata is x64**, so the stock x86 client cannot load into it.
- Upstream NVIDIA added Windows-on-Arm builds with "public ARM64/ARM64EC build artifacts" (rtx-remix 1.6.x release notes), and the commit `dfd6639` adds `bridge/build-wina64ec.txt`.
- **INFERRED:** an **ARM64EC runtime `d3d9.dll`** can be loaded directly into an emulated x64 process and run its own code natively. That would be our "native renderer on the laptop" route **without the bridge**. I could not verify which artifact is ARM64EC, or whether an x64 or ARM64EC *bridge client* ships. This is the key open question (see Next steps).
- The output still has to reach the screen. The bridge server "presents directly into" the client's HWND (`bridge/README.md`). That HWND would be our helper window, not NieR's DXGI swapchain. So the readback problem becomes a window-composition problem.

## Q2. Skinning

**Path** (`src/comp/game/api_skinned.cpp`, file comment and `build_mesh` / `submit`):
- **One mesh per skinned partition draw, built once in bind (skin) space.** It is built from the bridge client's CPU shadow of the VB/IB (READONLY locks) and keyed by geometry, the VB/IB write generations and the material key. The hash is `next_object_hash(key, kSkinnedDomain)`, a new hash for every build.
- **Weights:** `kBonesPerVertex = 4`, with a flat `float weights[V*4]` and `uint32 indices[V*4]`. The layout follows FFP indexed blending:
  - `nw` explicit weights, with `w[nw] = 1 - sum`, and zero-weight slots get index 0.
  - Counts are the array totals: `blendWeights_count = V*4`. Comment: "a client with the fix checks exactly that".
  - "The runtime reads the first three weights and gives the fourth the remainder (skinning.h)".
- **Bones per instance:**
  - Bones come from the captured VS constants `c[44+3n..]`, sent as `remixapi_InstanceInfoBoneTransformsEXT` with no transpose: `m[r][c] = c[3n+r][c]`.
  - The bone translation is shifted by `+ D - anchor`.
  - The instance transform is `scale * T(anchor)`, where the anchor is bone 0's translation rounded to 1/16 unit. That keeps motion histories per actor.
  - It uses one `DrawInstance` per frame and never retains skinned instances. Comment: "the batched retained update can't carry bones".
- **Held poses.** If the pose is within `kHoldLinear=1e-5` and `kHoldTranslation=1/256` unit of the last pose sent, the last pose is resent bit-for-bit. Reason given: "the runtime refits an instance's BLAS whenever its bone hash changes, and the engine's camera-relative bones change in their low bits whenever only the camera moves."
- **Pass arbitration.** One primary pass per object, where the object key is VB+IB+window+palette. Later raster-lighting passes (additive or multiply) are dropped.
- **Morph meshes** (FaceGen heads, rewritten VBs) are refreshed in place with `MeshInfoRefreshGeometryEXT` under the same hash.

**What the fork changed versus upstream** (`rtx_remix_api.cpp`). This is the stride bug we measured.
- Upstream main:
  ```cpp
  dst.blendWeightBuffer  = dxvk::RasterBuffer { blendWeightsSlice, 0, sizeof(float), VK_FORMAT_R32_SFLOAT };
  dst.blendIndicesBuffer = dxvk::RasterBuffer { blendIndicesSlice, 0, sizeof(uint32_t), VK_FORMAT_R8G8B8A8_USCALED };
  ```
- Fork `fnv/main` (there are two sites: immediate and batched/deferred):
  ```cpp
  dst.blendWeightBuffer  = dxvk::RasterBuffer { blendWeightsSlice, 0, uint32_t(sizeof(float) * src.skinning_value.bonesPerVertex), VK_FORMAT_R32_SFLOAT };
  dst.blendIndicesBuffer = dxvk::RasterBuffer { blendIndicesSlice, 0, uint32_t(sizeof(uint32_t) * dxvk::divCeil(src.skinning_value.bonesPerVertex, 4u)), VK_FORMAT_R8G8B8A8_USCALED };
  ```
- **This confirms the cause.** The upstream stride is one float, which matches our "bonesPerVertex=2 works, 4 broken" result. The fork uses `bonesPerVertex` floats per vertex. *(Interpretation: with a 1-float stride, vertex v reads weights `v..v+2`, which the runtime treats as one tuple. That matches ours.)*
- **RefreshGeometry in the fork.** `CreateMesh` with a chained `MeshInfoRefreshGeometryEXT` re-registers the live hash. Without it, a re-create of a live handle is dropped (`skipRepeatedMeshCreate`). Comment: "A re-create of a live handle without the refresh extension is dropped by AssetReplacer::registerExternalMesh". This matches our "CreateMesh on a live hash keeps old geometry".
- **Upstream workaround** without the fork *(INFERRED)*: pre-expand each vertex so weights sit at stride 1. That isn't possible for overlapping tuples, so stay at bonesPerVertex ≤ 2, or CPU-skin.

## Q3. Fork

**Runtime features the wrapper needs that upstream lacks.** These are named in the wrapper code and the fork docs.
- **`MeshInfoRefreshGeometryEXT`**, used for morph heads, far LOD and unlit UV animation.
- **The skinning stride fix and the bridge skinning-size fix**, without which skinned actors are refused.
- **Retained instances:**
  - `CreateRetainedInstance(s)`, `UpdateRetainedInstances` (batched), `DrawRetainedInstances(origin)`, `DestroyRetainedInstances`
  - the `rtx.retainedHiddenPolicy` setting
- **`remixapi_AssetKeyEXT`** and its bridge forwarding.
- **Material extensions:**
  - `InstanceInfoMaterialOverrideEXT`
  - `MaterialInfoOpaqueAlbedoTintEXT`, forwarded and detected through the client log string
  - `MaterialInfoTerrainLayersEXT`, described in the source as "FNV terrain layers"
- **Bridge forwarding of `InstanceInfoGpuInstancingEXT`.**
- **`SetGameValue`** (`__mcrtx.world_origin.*`) and `rtx.worldOrigin.enable`.
- **The NUMOS sky and weather.**
- **`rtx.worldSpaceUiEmissiveIntensity`** (`fnv-api-only.md`).
- **`remixapi_ImportD3D9Texture`**, exported by the bridge.
- **`CreateTexture`** with in-memory pixels.
- **Fork-only extras that matter to us even though the wrapper doesn't use them:**
  - `RegisterD3D11Device`, `RenderD3D11`, `DrawScreenOverlayD3D11(Ex)`
  - `PrepareD3D11TextureEx` / `ImportD3D11TextureEx`
  - `dxvk_GetSharedD3D11TextureHandle`
  - "External frame"

**Buildable or released.**
- It builds with `scripts/build.ps1` (Meson, VS 2026/2022, Vulkan SDK 1.4.313.2+) and `bridge/scripts/build.ps1`, according to the fork README.
- Binaries exist. The RemixProjGroup/dxvk-remix release "Remix Plus v2.0.0" ships `Remix_Plus_v2.0.0.zip` with "the runtime, the 32-bit bridge, the Remix API headers and docs".
- The README says "built and tested on x64 Windows", with **no ARM64 build mentioned**.
- The FNV wrapper's README requires "the bridge client and server from the same build" as the runtime.

**License.**
- Fork: zlib (DXVK) plus MIT (NVIDIA dxvk-remix and the contributors' parts). NUMOS is Apache-2.0. The NVIDIA SDKs are under their own licences.
- New-Vegas-RTX itself: MIT (xoxor4d plus Kim2091).

**ABI for the calls we use.**
- The header is `REMIXAPI_VERSION 0.1000.1`. The release notes say the 0.1000.0 line "realigned [category bits and interface structs] to match upstream exactly", and PATCH 1 tracks upstream 0.6.5's `MaterialInfoOpaqueEXT` growth.
- **The version gate rejects us.** For major 0, the minor must be equal (bridge client `isRemixApiVersionCompatible`). Our 0.6.6 build would get `INCOMPATIBLE_VERSION`, so we **must recompile against the fork's `remix_c.h`**.
- **INFERRED:** it should be source-compatible for CreateMesh, DrawInstance, SetupCamera, CreateMaterial and lights, because the docs say "Nothing was removed or changed in `remix_c.h`: the new calls are additions". I did not check this struct by struct.

## Q4. HUD

**How FNV does it** (`src/comp/game/ui_boundary.hpp`). Everything stays on **one D3D9 device**: the bridge device that the runtime traces on.
- The runtime "path traces the frame at its RTX injection and writes the result over the target". It injects at the first draw it takes as UI (`d3d9_rtx.cpp isRenderingUI`).
- The wrapper hooks FNV's `Main_Render` call sites (`0x870403`, plus the RenderWorldScene calls) to mark the UI boundary.
- At the first UI draw to the back buffer, it issues a degenerate orthographic fixed-function draw to trigger the injection. After that, every HUD and menu draw is **rasterised normally on top of the traced image**.
- Menu frames without the world use raster-only frames plus `rtx.uiTextures`.
- No `combineGuiInFinalColor` and no CPU overlay are involved.

**Mapping to D3D11.**
- **On upstream:** our UI is D3D11, so it can't be drawn natively on the Remix D3D9 device. Two options:
  - Draw a textured screen quad on the Remix device after the injection, which needs the UI render target uploaded each frame (a CPU copy, and over IPC on the bridge route).
  - Glue an overlay window, as in the FO4 notes.
- **On the fork, in process:** `DrawScreenOverlayD3D11(Ex)` composites up to 8 `ID3D11Texture2D` layers "on the host's command stream … no readback and no per-call allocation". But it **requires the game's device to be the fork's DXVK D3D11.** `remixapi_RegisterD3D11Device` does `dynamic_cast<dxvk::D3D11Device*>` and returns `INVALID_ARGUMENTS` otherwise. So NieR would have to run on the fork's DXVK `d3d11.dll`, built with `-Denable_d3d11=true -Denable_dxgi=true`, with our proxy chained in front of it.
- **Through the bridge:** neither `DrawScreenOverlay` nor the D3D11 calls are forwarded.

## Q5. Identity, culling, camera, classification, settings

**Mesh identity.**
- `next_object_hash(key, domain)` mixes the cache key with a **process-wide build counter**, "so a rebuilt entry never reuses the hash of one destroyed moments ago" (`api_mesh.hpp`). This is the same lesson as our crash with destroy-then-recreate under the same hash.
- Stable, mod-facing identity comes from `remixapi_AssetKeyEXT`, computed with the runtime's `positions,indices,geometrydescriptor` rule.
- Static mesh keys come from the bytes of the buffer window, rehashed only when its write generation moves.
- Skinned meshes get a per-actor anchor and held poses (Q2).
- Unlit tint variants: up to 16 per geometry, with LRU eviction and coarser quantisation for continuous tints (`fnv-api-only.md`).

**Culling and off-screen retention.**
- **Statics are decided by scene membership, not by draws.** Doc: "Whether the engine drew it this frame (frustum, portal / room and fade culling) never adds or removes it."
- Membership comes from the NVSE plugin's ref-attach walks, and hiding comes only from engine data (app-cull flags, disabled refs, switch/LOD children).
- Per-feature `Residency` policies (`api_mesh.hpp`):
  - `Drawn` (hidden when not drawn)
  - `Cell` (kept while culled until it leaves the loaded cell grid, the interior changes or the camera jumps)
  - `LodOnScreen` (hidden if on screen in a 3° guard-band view cone but not drawn for N frames)
  - `Foliage`, `FoliageBatch`
- Draw-captured statics become retained "kept while culled" after 60 frames with a stable mesh and placement.
- The fork docs give the same rule: "Hiding objects that are off screen … Symptom: hitches, VRAM spikes, missing shadows and reflections."

**Camera / stable origin** (`stable_origin.hpp`).
- FNV renders camera-relative. The wrapper picks an origin O, the camera snapped to a grid and re-snapped only beyond `StableOriginRadius`, and sets `D = camera - O`.
- Every device `WORLD` becomes `W*T(D)` and `VIEW` becomes `T(-D)*V`, so raster output is unchanged. API instances are submitted at camera-relative + D.
- O is published through `SetGameValue __mcrtx.world_origin.*` for history shifts.
- An optional `WorldUnitScale` changes units.
- **Interpretation:** the main camera reaches Remix through the D3D9 transforms set on the bridge device, not through `SetupCamera`. The view-model camera is separate (`api_camera`).

**Engine classification** (`engine-classification.md`).
- It hooks the render-pass dispatcher `0xB994F0`. That gives the `NiGeometry`, the pass type (757 `BSSM_*` values grouped into kinds), the shader class id and the skin instance for every D3D draw made inside the call.
- Shader-constant names are only a fallback, and disagreements between the two are logged.
- **For us this is NEEDS-ENGINE-ACCESS.** We would need an equivalent hook into NieR's own draw dispatcher; without one we stay on shader-hash classification.

**Game settings disabled in memory.** Per the README `[GameSettings]` section: "shadow maps, HDR, multisampling, depth of field and the water reflection passes". The NVSE plugin also sets the app-culled flag on fog, mist and haze cards (`fnv-api-only.md`, "Game fog").

## Q6. perf-profile.md

- **`docs/perf-profile.md` contains no performance numbers.** It is a guide to the wrapper's own sampling profiler:
  - It samples the game thread at 25 Hz.
  - It writes `[Perf]`, `[PerfSlow]` and `[PerfSummary]` lines: top modules, wait kinds, "wrapper draws by route", and "wrapper end of frame by part" (`d3d9ex.cpp pre_present`).
  - It explains how to resolve `module+RVA` with `llvm-symbolizer` or retools.
  - A 30 s window is about 750 samples, accurate to about ±2%.
- The only cost numbers I found are in the fork's `docs/api-host-path-migration.md`. They come from "an open-world API host, RTX 5080 Laptop", which is not FNV (INFERRED: probably FO4):
  - Per-frame `DrawInstance` costs about 5.8 µs per object on the render thread. A retained, unchanged object costs about 0.3 µs.
  - The render thread fell from 29.4 ms (CPU-bound, 33 fps) to 7.7–11.4 ms (GPU-bound) after retained instances plus four rounds of runtime work.
  - GPU texture import saved 2.0–2.6 GB VRAM.
  - The guidance is: "Keep per-frame DrawInstance for skinned characters … short-lived effects."
- Main costs, as both repos describe them:
  - per-object submission on the render thread
  - BLAS refits from float-noisy transforms or bones (hence held poses and bit-exact matrices)
  - destroy/recreate churn
  - texture CPU upload and VRAM

## Q7. Recommendations for NieR (priority order a–d, then others)

| # | Recommendation | Tag | Why (one line) |
|---|---|---|---|
| a1 | Before building anything for the bridge, check whether upstream's **ARM64EC** runtime `d3d9.dll` loads in-process in emulated x64 NieR | ADOPTABLE-NOW (investigation) | rtx-remix 1.6.x ships "ARM64/ARM64EC build artifacts"; ARM64EC is designed for loading into x64 processes, so this may give native rendering with no IPC. Unverified, and needs a runtime upgrade from 0.6.6. |
| a2 | Bridge route: our x64 proxy loads an **x64 (or ARM64EC) bridge client**, creates a D3D9Ex device on a helper HWND through it, then `remixapi_InitializeLibrary` from that module | NEEDS-BRIDGE | The stock client is x86-only (`bridge/README.md`). Through the bridge the API binds to "most recently created" client device, with no Startup or Present, and the frame ends on that device's `Present`. |
| a3 | If we go over IPC, cut the per-frame call count: retained statics, a batched update, one replay per frame, bit-exact transforms | NEEDS-FORK | Every call is a ring-buffer message; FNV's whole design minimises per-frame traffic. Upstream has no retained API. |
| b1 | GPU skinning with bonesPerVertex=4 | NEEDS-FORK | The fork's `blendWeightBuffer` stride is `sizeof(float)*bonesPerVertex`; upstream's is `sizeof(float)`. |
| b2 | On upstream now: keep bonesPerVertex ≤ 2, and add FNV's **held pose** (resend the last pose bit-exact when within 1e-5 / 1/256 unit) plus a per-actor **anchor** instance transform | ADOPTABLE-NOW | Pure client logic. It stops camera-only motion from refitting skinned BLASes, and our bones come from VS constants as FNV's do. |
| b3 | One primary pass per skinned object, keyed by VB+IB+window+palette; drop later additive or multiply passes | ADOPTABLE-NOW | Draw-stream logic only; it avoids coplanar duplicate instances. |
| b4 | Validate skinning array totals (`count >= bonesPerVertex*V`) before CreateMesh | ADOPTABLE-NOW | Same check as the fork client's `validateSkinning`; it guards against out-of-bounds reads. |
| c1 | Remove readback by rendering into the game's backbuffer with `RegisterD3D11Device` + `RenderD3D11` | NEEDS-FORK (+ the game on the fork's DXVK D3D11) | `dynamic_cast<dxvk::D3D11Device*>` requires NieR's device to be DXVK's from the same runtime build. That is a big change, in-process only, and gives no ARM benefit unless the runtime is ARM64EC. |
| c2 | Remove readback by sharing the output texture with `dxvk_GetSharedD3D11TextureHandle`, opened on NieR's device, and copied GPU→GPU into the backbuffer | NEEDS-FORK *(verify; FO4 notes list it in the fork header)* | Avoids GetRenderTargetData plus the CPU copy. It only works in-process, and cross-adapter under emulation is unverified. |
| c3 | Remove readback with an overlay window: on the bridge route the server already presents into our helper HWND; glue it over NieR's window | ADOPTABLE-NOW | Pure Win32. It matches how the bridge presents (FO4 notes technique 1). |
| d1 | HUD on upstream: after the traced draws, draw NieR's UI render target as a fullscreen ortho quad on the Remix D3D9 device; a fixed-function ortho draw triggers injection, and everything after is raster over the traced image | ADOPTABLE-NOW | This is FNV's `ui_boundary` mechanism. The cost is one UI-RT copy per frame (CPU in-process, IPC on the bridge). |
| d2 | HUD with `DrawScreenOverlayD3D11Ex` (GPU layers, premultiplied flag) | NEEDS-FORK (+ DXVK D3D11) | Not forwarded over the bridge. |
| e1 | Give mesh hashes a process-wide build counter (never reuse a destroyed hash), and update with RefreshGeometry where available | ADOPTABLE-NOW (counter) / NEEDS-FORK (refresh) | Matches our measured crash and keep-old behaviour. |
| e2 | Retain off-screen geometry by residency policy (cell/distance plus a guard-band LOD rule), not by "drawn this frame" | ADOPTABLE-NOW | Needs only our mesh cache plus a TTL. |
| e3 | Stable render origin (snap to a coarse grid, shift on large moves only), if NieR's matrices are camera-relative | ADOPTABLE-NOW | Removes per-frame transform noise for all instances. Check NieR's CB layout first. |
| e4 | Classify draws from the engine's render-pass dispatcher | NEEDS-ENGINE-ACCESS | We have no NieR RVA for an equivalent dispatcher. |
| e5 | Turn off native shadow, DOF and SSR passes in memory instead of dropping their draws | NEEDS-ENGINE-ACCESS | FNV patches engine globals; for NieR we would need setting addresses (draw-level skipping is our fallback). |

## Contradictions

- **`exposeRemixApi`.** `bridge.conf` calls it "EXPERIMENTAL … Defaults off", while the fork ships it set to `True` and the whole FNV design relies on it. That isn't a real conflict, but it means the bridge API path is less exercised upstream.
- **Which API calls work on which host.** The fork's host-path doc says "D3D9 game using the API … Test first: only D3D11 has been exercised". Yet FNV (D3D9 through the bridge) uses retained instances heavily. The doc is probably stale *(INFERRED)*.
- **Runtime support for D3D11.** The fork README says "Remix API hosts … from its own D3D11 device". The code requires *DXVK's* D3D11 device, not a native driver device. The README glosses over this.

## Missing evidence

- **Whether an x64 or ARM64EC bridge client exists**, upstream or in the fork, and exactly which ARM64EC artifacts upstream ships. This decides how feasible a2 is.
- **Bridge per-call latency and throughput numbers**: none found in either repo.
- **Whether `dxvk_GetSharedD3D11TextureHandle` still exists in fork 0.1000.1**: not verified in this pass.
- **The rest of `api_skinned.cpp`** (lines 1011–1309) and the NVSE plugin sources: not read.
- **The fork commit**: I didn't confirm that it equals the submodule SHA `925d7ab`; I read the tip of `fnv/main`.

## Sources

**Kept:**
- New-Vegas-RTX: https://github.com/Kim2091/New-Vegas-RTX. Primary source; files listed at the top.
- Fork `Kim2091/dxvk-remix`, branch `fnv/main`:
  - `README`
  - `docs/RemixApi.md`
  - `docs/api-host-path-migration.md`
  - `bridge/src/client/remix_api.cpp`
  - `bridge/README.md`
  - `src/dxvk/rtx_render/rtx_remix_api.cpp`
  - `public/include/remix/remix_c.h`
- Upstream `rtx_remix_api.cpp`: https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/rtx_render/rtx_remix_api.cpp. Used for the stride diff.
- RemixProjGroup releases: https://github.com/RemixProjGroup/dxvk-remix/releases. Binaries and licences.
- NVIDIA rtx-remix releases: https://github.com/NVIDIAGameWorks/rtx-remix/releases, and commit https://github.com/NVIDIAGameWorks/dxvk-remix/commit/dfd6639. Windows-on-Arm and ARM64EC.

**Deprioritized:**
- NVIDIA docs pages: generic install information.
- The deprecated `bridge-remix` repo: superseded by the `bridge/` folder.

## Next steps

1. Download the rtx-remix 1.6.x Windows-on-Arm package. Check the PE machine type of each `d3d9.dll` and `NvRemixBridge.exe`, then try loading the ARM64EC runtime from our x64 proxy on the laptop.
2. If we go with the bridge: check `bridge/meson.build` (fork and upstream) for an x64 or ARM64EC client target.
3. Prototype the FNV-style HUD (d1) and held poses (b2) on upstream 0.6.6. Both are client-only.
