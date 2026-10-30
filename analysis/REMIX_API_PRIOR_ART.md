# Research: RTX Remix C API: mesh/light hash lifetime, per-frame dynamic meshes, and API skinning

Scope: dxvk-remix `main` as of this run (header `REMIXAPI_VERSION 0.6.6`), plus one older upstream snapshot (commit `6e73bea`, 2025-05), public remixapi users, and the Remix Plus fork. **Caveat:** your runtime is "0.6.x". I don't know its exact commit, so line numbers and some internals may differ from what I quote.

## Summary
- **Handles are hashes.** `CreateMesh` and `CreateLight` cast `info->hash` straight into the handle.
- **Live mesh hash:** re-creating a mesh whose hash is still live is ignored on purpose. The runtime logs "Ignoring repeated mesh registration". This explains your observation (1).
- **Live light hash:** re-creating a light whose hash is still live overwrites it in place.
- **Destroy is not deferred.** Destroy and Create are queued on the same CS thread and run in submission order.
- **Your crash (2):** I found no code path that explains the same-hash crash. Your working pattern (new hash, then destroy the old one) is the same pattern the GMod RTX module uses.
- **Skinning bug confirmed.** Upstream API skinning hard-codes a blend-weight stride of `sizeof(float)`, but the header documents `bonesPerVertex` weights per vertex. The community Remix Plus fork fixed it by changing the stride to `sizeof(float) * bonesPerVertex`.

---

## Q1: What CreateMesh / DestroyMesh / CreateLight / DestroyLight do with the hash

**Handle == hash (VERIFIED-IN-SOURCE).** In `src/dxvk/rtx_render/rtx_remix_api.cpp` (`remixapi_CreateMesh`):
```cpp
static_assert(sizeof(remixapi_MeshHandle) == sizeof(info->hash));
auto handle = reinterpret_cast<remixapi_MeshHandle>(info->hash);
if (!handle) { return REMIXAPI_ERROR_CODE_INVALID_ARGUMENTS; }
...
remixDevice->EmitCs([cHandle = handle, cSurfaces = std::move(allocatedSurfaces)](dxvk::DxvkContext* ctx) mutable {
  auto& assets = ctx->getCommonObjects()->getSceneManager().getAssetReplacer();
  assets->registerExternalMesh(cHandle, std::move(cSurfaces));
});
```
`remixapi_CreateLight` does the same: `auto handle = reinterpret_cast<remixapi_LightHandle>(info->hash);`.
Source: https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/rtx_render/rtx_remix_api.cpp

**Re-creating a live mesh hash is silently ignored (VERIFIED-IN-SOURCE; explains observation 1).** The GPU buffers are still allocated on the calling thread first, so that work is wasted. In `src/dxvk/rtx_render/rtx_asset_replacer.cpp` (same in main and in the 2025-05 snapshot):
```cpp
void AssetReplacer::registerExternalMesh(remixapi_MeshHandle handle, std::vector<RasterGeometry>&& submeshes) {
  if (m_extMeshes.count(handle) > 0) {
    Logger::info("Ignoring repeated mesh registration (handle=" + tostr(handle) + ") ");
    return;
  }
  m_extMeshes.emplace(handle, ...);
}
void AssetReplacer::destroyExternalMesh(remixapi_MeshHandle handle) { m_extMeshes.erase(handle); }
```
Sources: https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/rtx_render/rtx_asset_replacer.cpp and https://github.com/NVIDIAGameWorks/dxvk-remix/blob/6e73beaff7c2a26be615f204116fb4c055fc4ca4/src/dxvk/rtx_render/rtx_asset_replacer.cpp

**Destruction is not deferred to a later frame (VERIFIED-IN-SOURCE).**
- `remixapi_DestroyMesh` and `remixapi_DestroyLight` only `EmitCs` a lambda. It runs on the dxvk CS thread in submission order, after any earlier-emitted CreateMesh or DrawInstance:
  ```cpp
  remixDevice->EmitCs([cHandle = handle](dxvk::DxvkContext* ctx) {
    ctx->getCommonObjects()->getSceneManager().destroyExternalMesh(dxvk::Rc<dxvk::DxvkContext>(ctx), cHandle);
  });
  ```
- So `Destroy(h); Create(h)` from one thread reaches the CS thread as erase-then-emplace. On paper the new geometry should register.
- What does outlive the destroy is the derived scene state. BLAS/draw-call-cache entries are garbage-collected by age. From `rtx_scene_manager.cpp`:
  ```cpp
  if (iter->second.frameLastTouched < oldestFrame && iter->second.getLinkedInstances().empty()) { ... entries.erase(iter); }
  ```
  - `oldestFrame = currentFrameId - RtxOptions::numFramesToKeepGeometryData()`.
  - `RtxOptions.md` lists `rtx.numFramesToKeepBLAS=1`, `rtx.numFramesToKeepInstances=1`, `rtx.numFramesToKeepLights=100`.

**Upstream main shows a known destroy-while-referenced hazard (VERIFIED-IN-SOURCE).**
- Main now stores meshes as `shared_ptr<vector<RasterGeometry>>`. In `rtx_scene_manager.cpp` (external draw path) the comment reads:
  > "The aliasing ctor shares submeshesRef's ref-count while pointing at the element, keeping the vector alive if destroyExternalMesh erases the entry while a BlasEntry still holds this pointer."
- Main's `SceneManager::destroyExternalMesh` also calls `m_drawCallTracker.removeReplacementInstancesWithSpatialMapHash(spatialMapHashForExternalDrawMesh(handle))`. That state is keyed by the handle, i.e. the hash.
- Main also builds a per-draw identity from `data.meshId = reinterpret_cast<uintptr_t>(mesh)`, which is again the hash.
- In the 2025-05 snapshot the external draw copied `RasterGeometry` by value (`state.drawCall.geometryData = submesh;`), so that particular dangling pointer didn't exist there.

**Is re-creating a just-destroyed hash a known problem?**
- I found no GitHub issue or doc that names it.
- Official RemixSDK.md actually *recommends* Destroy + Create with the same hash, but only for lights (see Q4). It gives no such guidance for meshes.
- **INFERRED:** your access violation (2) most likely comes from per-handle derived state (BLAS/instance/replacement tracking keyed by hash or mesh pointer) outliving the destroy and being matched to the new mesh with the same hash. That fits the code above, but I couldn't pin it to a line in your runtime version.

**What a new hash per update costs (VERIFIED-IN-SOURCE).** `allocateSurfaceGeometry` gives every created surface fresh internal geometry hashes:
```cpp
dst.hashes[HashComponents::Indices] = dst.hashes[HashComponents::VertexPosition] = hack_getNextGeomHash();
```
- So every CreateMesh produces a never-seen geometry, which means a new draw-call-cache/BLAS entry (`KBuildBVH` path in `processGeometryInfo`).
- Each create also allocates host-visible buffers (`HOST_VISIBLE | HOST_CACHED`, "Remix API mesh buffer").

## Q2: How existing remixapi users handle per-frame meshes, skinning and hashes

| Project | Mesh update pattern | Hash reuse? | Skinning |
|---|---|---|---|
| **Garry's Mod RTX Remixed** (`source/remixapi/remixapi.cpp`, `MeshManager::UpdateMesh`) | `CreateMesh(newInfo)` **then** `DestroyMesh(oldHandle)`, i.e. create-new-then-destroy-old, the same as your working pattern (3) | Lua callers supply the hash; the binding does nothing to keep the old hash, so it must differ or the create is ignored | Lua mesh binding: `surfInfo.skinning_hasvalue = false; // Skinning not supported in Lua binding yet`. Character skinning goes through **D3D9 fixed-function** instead: `HardwareSkinningHooks.cpp` ("Forces MESHGROUP_IS_HWSKINNED flag and sets bone transforms via D3D9 fixed-function API", `D3DRS_VERTEXBLEND = D3DVBF_2WEIGHTS`, `SetTransform(D3DTS_WORLDMATRIX(i))`) |
| **xoxor4d l4d2-rtx** (`src/components/modules/remix_api.cpp`) | Debug lines/circles: each frame, destroy all of last frame's meshes in `on_renderview`, then create new ones | **New hash each time:** `.hash = utils::string_hash64(utils::va("line%d", m_debug_last_line_hash ...))`, where the last hash is the previous handle, so it is a hash chain | None (`.skinning_hasvalue = FALSE`) |
| **xoxor4d gta4-rtx** (`src/gta4/modules/remix_lights.cpp`, `remix_markers.cpp`) | Uses remixapi only for lights. Markers are drawn via D3D9 `DrawPrimitiveUP` | n/a | n/a |
| **NVIDIA test app** `remixapi_example_c.c` | Static triangle created once | n/a | `.skinning_hasvalue = FALSE` |

- **No public project found that sets `skinning_hasvalue = TRUE`** or uses `remixapi_InstanceInfoBoneTransformsEXT`. GitHub hits for `remixapi_MeshInfoSkinning` / `BoneTransformsEXT` were only vendored headers (l4d2-rtx, nfsc-rtx, p2-rtx).
- I searched via web/Exa, not GitHub code search, so coverage is not exhaustive.

Sources:
- https://github.com/Xenthio/garrys-mod-rtx-remixed/blob/main/source/remixapi/remixapi.cpp
- https://github.com/Xenthio/garrys-mod-rtx-remixed/blob/main/source/remixapi/mesh_lua_bindings.cpp
- https://github.com/Xenthio/garrys-mod-rtx-remixed/blob/main/source/HardwareSkinningHooks.cpp
- https://github.com/xoxor4d/l4d2-rtx/blob/master/src/components/modules/remix_api.cpp
- https://github.com/xoxor4d/gta4-rtx/blob/master/src/gta4/modules/remix_lights.cpp

## Q3: Guidance on per-frame mesh cost, BLAS cost, and the intended animated-mesh pattern

### Upstream skinning stride bug (VERIFIED-IN-SOURCE)
The header contract, in `public/include/remix/remix_c.h` (`remixapi_MeshInfoSkinning`):
> "Each tuple of 'bonesPerVertex' float-s defines a vertex. I.e. the size must be (bonesPerVertex * vertexCount)."

The upstream implementation in `rtx_remix_api.cpp` (`allocateSurfaceGeometry`):
```cpp
dst.blendWeightBuffer  = dxvk::RasterBuffer { blendWeightsSlice, 0, sizeof(float),    VK_FORMAT_R32_SFLOAT };
dst.blendIndicesBuffer = dxvk::RasterBuffer { blendIndicesSlice, 0, sizeof(uint32_t), VK_FORMAT_R8G8B8A8_USCALED };
```

The shader in `src/dxvk/shaders/rtx/pass/skinning.h`:
```hlsl
const uint32_t baseWeightsOffset = (cb.blendWeightOffset + idx * cb.blendWeightStride) / 4;
...
if (i + j != cb.numBones - 1) { blendWeight = srcBlendWeight[baseWeightsOffset + i + j]; lastWeight -= blendWeight; }
```

What this means:
- With stride 4 bytes, vertex `idx` reads weights `[idx .. idx+bonesPerVertex-2]`. Your diagnosis is correct.
- The last weight is never read; it is computed as `1 - sum(others)`.
- Bone indices are packed as 8 bits each (so at most 256 bones, matching `REMIXAPI_INSTANCE_INFO_MAX_BONES_COUNT 256`).
- The index stride is also hard-coded to 4 bytes, so it is only correct for `bonesPerVertex <= 4`.
- **INFERRED from the shader math:** with the upstream runtime as-is, `bonesPerVertex = 2` with **one weight per vertex** (bone 0's weight; bone 1 gets the remainder) is read correctly. `bonesPerVertex = 1` (rigid) is also correct.

**The Remix Plus fork fixed exactly this (VERIFIED-IN-SOURCE):**
```cpp
dst.blendWeightBuffer  = dxvk::RasterBuffer { blendWeightsSlice, 0, uint32_t(sizeof(float) * src.skinning_value.bonesPerVertex), VK_FORMAT_R32_SFLOAT };
dst.blendIndicesBuffer = dxvk::RasterBuffer { blendIndicesSlice, 0, uint32_t(sizeof(uint32_t) * dxvk::divCeil(src.skinning_value.bonesPerVertex, 4u)), ... };
```
Source: https://github.com/NightSightProductions/dxvk-remix-plus/blob/main/src/dxvk/rtx_render/rtx_remix_api.cpp

I found no upstream issue or PR for this bug.

### Intended dynamic path: one stable mesh plus per-frame bones (VERIFIED-IN-SOURCE)
- `DrawInstance` with `remixapi_InstanceInfoBoneTransformsEXT` fills `skinningData.pBoneMatrices` and calls `computeHash()`.
- `processGeometryInfo` then compares state against the cached entry:
  ```cpp
  if (VertexPosition hash same && VertexShader hash same && boneHash == lastBoneHash) result = kUpdateInstance; else result = kUpdateBVH;
  ```
- On `KBuildBVH` or `kUpdateBVH` with `numBones > 0` it runs `dispatchSkinning`. Skinning runs on the CPU for 256 vertices or fewer with mappable buffers, otherwise on the GPU.
- So a stable mesh hash with changing bone matrices gets a BLAS **update** instead of a new BLAS entry per pose. The remix-1.1.0 release notes say: "Added support to update BLAS (rather than build) where possible for better performance."

### Documentation and issues
- No official numbers on per-frame `CreateMesh` cost were found.
- Official RemixSDK.md says the API "has been tested mostly for [the HdRemix Hydra delegate] use case" and that the vertex format is "subject to change".
- Remix Plus docs: upstream `CreateMesh` "allocates DXVK buffers and registers replacement assets synchronously on the calling thread". The fork adds `CreateMeshBatched` to defer that to the render thread. That is fork-only, not upstream.

Sources:
- https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/shaders/rtx/pass/skinning.h
- https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/rtx_render/rtx_scene_manager.cpp
- https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/documentation/RemixSDK.md
- https://github.com/NVIDIAGameWorks/rtx-remix/releases/tag/remix-1.1.0
- https://github.com/NightSightProductions/dxvk-remix-plus/blob/main/docs/RemixApi.md

## Q4: Lights

**Officially documented pattern:** Destroy + Create with the **same** hash. From RemixSDK.md:
> "`.hash` should be a unique ID, it is used to identify the light source between the current and previous frame for a more stable denoising / light sampling … to update a light with the new parameters, recreate it by calling `DestroyLight` + `CreateLight` but with the same `.hash` value as the old one"

**Runtime code (VERIFIED-IN-SOURCE), `rtx_light_manager.cpp`:**
```cpp
void LightManager::addExternalLight(remixapi_LightHandle handle, const RtLight& rtlight) {
  auto found = m_externalLights.find(handle);
  if (found != m_externalLights.end()) {
    // TODO: warn the user about id collision, or just overwriting existing one is fine?
    uint32_t stableIdentity = found->second.getStableIdentity();
    found->second = rtlight; found->second.setStableIdentity(stableIdentity);
  } else { m_externalLights.emplace(handle, rtlight); }
}
void LightManager::removeExternalLight(remixapi_LightHandle handle) { m_externalLights.erase(handle); m_externalDomeLights.erase(handle); }
```
- So `CreateLight` on a **live** hash simply overwrites the light and keeps its stable identity. You don't strictly need the Destroy.
- `DrawLightInstance` must be called every frame: `m_externalActiveLightList` is cleared at the end of each frame.

**What projects do:**
- **xoxor4d l4d2-rtx** flashlights: every frame `DestroyLight(fl.handle)` then `CreateLight` with `hash = string_hash64(va("fl%s", name))`, i.e. the same hash every frame.
- **gta4-rtx** `spawn_or_update_remix_sphere_light`: `if (light.m_handle) destroy_light(light);` then `CreateLight` (the update path keeps the previous `m_info.hash`), then `DrawLightInstance` each frame.
- **GMod** uses fork-only `UpdateLightDefinition` and `AutoInstancePersistentLights` (Remix Plus / dxvk-remix-gmod runtime). Before destroying a light it zeroes its radiance "to avoid one-frame persistence".
- No crash reports were found for same-hash light recreation.

Sources:
- https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/rtx_render/rtx_light_manager.cpp
- https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/documentation/RemixSDK.md
- https://github.com/xoxor4d/l4d2-rtx/blob/master/src/components/modules/remix_api.cpp
- https://github.com/xoxor4d/gta4-rtx/blob/master/src/gta4/modules/remix_lights.cpp
- https://github.com/Xenthio/garrys-mod-rtx-remixed/blob/main/source/remixapi/remixapi.cpp

## Contradictions
- **Header vs implementation on blend weights.** The header says `bonesPerVertex` weights per vertex; upstream code reads with a stride of 1 float. Remix Plus sides with the header.
- **Mesh vs light semantics on a live hash.** Re-creating a live mesh hash is ignored; re-creating a live light hash overwrites it. The API has no doc comment on mesh re-creation.

## Missing evidence
- The exact commit of your 0.6.x runtime, and therefore the true root cause of the same-hash Destroy→Create crash. No issue was found.
- Measured cost of a per-frame `CreateMesh` vs a bone-transform update. No public benchmarks exist.
- Whether upstream's `kUpdateBVH` is a real refit or a rebuild for API meshes (I didn't trace `m_accelManager`).
- Whether a new hash every frame breaks motion vectors / temporal history, since main keys draw identity on `meshId`. This is INFERRED risk, not verified.

## Implications for us
- **VERIFIED-IN-SOURCE:** A live hash can never update mesh geometry; the runtime ignores the repeated registration. Keep create-new-hash → destroy-old-handle, which matches GMod's `UpdateMesh`. Avoid same-hash Destroy→Create, which is undocumented for meshes and crashed for you.
- **VERIFIED-IN-SOURCE:** Every `CreateMesh` allocates new host-visible buffers and gets fresh internal geometry hashes. So a new mesh per pose means a fresh BLAS build every frame, plus cache entries that linger until GC.
- **VERIFIED-IN-SOURCE:** Upstream API skinning reads weights at a 1-float stride per vertex and derives the last weight implicitly. The header's 4-weights-per-vertex layout is broken upstream; Remix Plus has a one-line fix.
- **INFERRED (from the shader math):** On the current upstream runtime, GPU skinning should work if you reduce to `bonesPerVertex = 2` and pass exactly one weight per vertex. Then you'd create one stable mesh per model and send `InstanceInfoBoneTransformsEXT` each frame. Validate visually before relying on it; quality drops for 4-bone rigs.
- **VERIFIED-IN-SOURCE:** For lights, `CreateLight` with the same hash, with or without a prior `DestroyLight`, is the documented and code-supported update. Call `DrawLightInstance` every frame.
- **INFERRED:** Keeping hashes stable per object (lights, and mesh-plus-bones if adopted) probably helps denoiser and motion-vector stability, since the runtime keys identity on the handle.
