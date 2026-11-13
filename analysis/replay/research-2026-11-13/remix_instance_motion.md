**Short answer**

- No explicit instance id is consumed. Temporal identity is an XXH64 identity hash of the mesh handle value, the prototype material hash, bone hash, camera type, categories, texgen/z flags, `objectToWorld` and `textureTransform`. A fallback matches the same mesh handle to the nearest existing instance within `uniqueObjectDistance` (default 300 game units) of its world position. The mesh handle is `info->hash`, chosen by the client.
- The previous transform is internal. `surface.prevObjectToWorld` is last frame's `objectToWorld`, set by `move()` on the first update each frame. No InstanceInfo field supplies it; `rtx_remix_api.cpp` contains no "prev" at all.
- Previous vertex positions exist only for GPU-skinned meshes (bone transforms) whose BlasEntry was re-skinned this frame. Re-uploaded pre-skinned geometry gets none.
- Recreating a mesh under a new handle resets instance identity, BLAS and skinning history for that object. I found no per-instance denoiser/upscaler reset; history resets are global only.

Paths below are relative to `analysis/runtime/src/dxvk-remix/src/dxvk/rtx_render/`.

**(1) Matching an API instance to its previous-frame instance**

- `rtx_scene_manager.cpp:91` — `data.meshId = reinterpret_cast<uintptr_t>(mesh);`
- `rtx_scene_manager.cpp:92-94` — `data.materialHash = drawCall.getMaterialData().getHash();` / `data.boneHash = ...` / `data.cameraType = cameraType;`
- `rtx_scene_manager.cpp:116-134` — `hashStructByMemory<ExternalDrawIdentityHashData, ... &ExternalDrawIdentityHashData::objectToWorld, ...textureTransform>` (the hashed fields). `objectPickingValue`, `doubleSided` and the external surface material are not in this list.
- `rtx_scene_manager.cpp:2556-2562` — identity and spatial hash computed before the material override loop; the key's 4th field is `kEmptyHash`: `const ReplacementInstance::LookupKey externalKey { identityHash, spatialMapHash, matHash, kEmptyHash, worldPos, xform };`
- `rtx_scene_manager.cpp:58-61` — `spatialMapHash` is XXH3 of the mesh pointer value only.
- `rtx_draw_call_tracker.cpp:232` — L1: `auto exactMatchIter = m_identityHashMap.find(key.identityHash);`
- `rtx_draw_call_tracker.cpp:252-256` — L2: tracking hash plus spatial proximity; `l2Filter` requires `candidate->materialHash == key.materialHash` and the same `sourceVertexBufferAddress`, and does not check categories.
- `rtx_draw_call_tracker.cpp:289` — `spatialMapIter->second.getNearestData(key.worldPos, uniqueObjectDistanceSqr, ...)`
- `rtx_draw_call_tracker.cpp:304-305` — L3: `auto newReplacementInstance = std::make_unique<ReplacementInstance>(key, ...)`, i.e. a new instance.
- `rtx_options.h:525` — `uniqueObjectDistance, 300.f`.
- `rtx_remix_api.cpp:803-805` — `prototype.transformData.objectToWorld = convert::tomat4(info.transform);` / `prototype.categories = convert::toRtCategories(info.categoryFlags);`
- `rtx_remix_api.cpp:809`, `866`, `869` — `prototype.drawCallID = objectPicking->objectPickingValue;`, `state->mesh = info.mesh;`, `state->doubleSided = convert::tobool(info.doubleSided);`

**(2) Previous transform; duplicate draws; destroy and recreate**

- `rtx_instance_manager.cpp:324-325` — `bool RtInstance::move(...) { surface.prevObjectToWorld = surface.objectToWorld;`
- `rtx_instance_manager.cpp:272-275` — 1-arg `teleport()` sets `surface.prevObjectToWorld = objectToWorld;` (prev = current, zero motion).
- `rtx_instance_manager.cpp:1206` — `const bool isFirstUpdateAfterCreation = currentInstance.isCreatedThisFrame(...) && isFirstUpdateThisFrame;`
- `rtx_instance_manager.cpp:1220-1225` — `if (isFirstUpdateAfterCreation) { teleport } else if (isFirstUpdateThisFrame) { move } else { moveAgain }`
- `rtx_instance_manager.cpp:1068` — `mergeInstanceHeuristics(...)` runs on a second draw of the same instance; `moveAgain` (line 339) does not touch prev.
- Same frame, same identity: L1 returns the same RI (`draw_call_tracker.cpp:232-246`), so one RtInstance is reused via `existingInstance` (`scene_manager.cpp:2593`).
- `rtx_instance_manager.cpp:929` — `currentInstance->m_frameCreated = currentFrameIdx;`
- `rtx_asset_replacer.cpp:243-250` — `registerExternalMesh`: `if (m_extMeshes.count(handle) > 0) { Logger::info("Ignoring repeated mesh registration...")`. Re-creating with a live handle is silently ignored; the new vertex data is dropped.
- `rtx_scene_manager.cpp:2625-2627` — `removeReplacementInstancesWithSpatialMapHash(...); m_pReplacer->destroyExternalMesh(handle);`
- `rtx_draw_call_tracker.cpp:170-177` — removes every RI with that spatial hash via `destroyReplacementInstance` (immediate, not GC/anti-cull).
- `rtx_types.cpp:117-121` — `subInstance->markForGarbageCollection();` on clear.
- `rtx_context.cpp:392, 405, 411, 418` — `m_resetHistory = true;` only on global triggers (render-mode change, indirect/sparse change, camera cut via `rtx_camera.cpp:110-117`). Per-instance creation does not set it.

**(3) Skinned meshes (`InstanceInfoBoneTransformsEXT`) and re-uploaded geometry**

- `rtx_remix_api.cpp:812-823` — bone matrices copied into `skinningData`; `computeHash()` (`rtx_types.h:304`) gives `boneHash`.
- `rtx_scene_manager.cpp:398-421` — `processGeometryInfo<false>`: `kUpdateInstance` only if vertex-position hash and bone hash are unchanged; otherwise `kUpdateBVH`.
- `rtx_scene_manager.cpp:452` — `output.previousPositionBuffer = RaytraceBuffer();` (reset each update).
- `rtx_scene_manager.cpp:512-544` — `kUpdateBVH`: `std::swap(output.historyBuffer[0], output.historyBuffer[1]);` then `output.previousPositionBuffer = RaytraceBuffer(DxvkBufferSlice(output.historyBuffer[1], ...))`. Previous positions = the previous GPU-skinned vertex buffer.
- `rtx_scene_manager.cpp:1556-1560` — `dispatchSkinning(...)` runs only on `KBuildBVH` or `kUpdateBVH`.
- `rtx_instance_manager.cpp:1198-1205` — `previousPositionsValidThisFrame = blas.frameLastUpdated == currentFrame`, and `hasPreviousPositions = ... && !isMotionUnstable` (translucent, particle, WorldUI excluded).
- `rtx_instance_manager.cpp:1235` — `isStatic = !(hasTransformChanged || hasPreviousPositions) || ...RayPortal`.
- Pre-skinned re-upload: a new handle gives new hashes (`rtx_remix_api.cpp:1008-1011`, `dst.hashes[...] = hack_getNextGeomHash();` per call, so the topological hash is new). `rtx_draw_call_cache.cpp:51` keys on it, so the BlasEntry is new and `KBuildBVH` runs (`scene_manager.cpp:475`), with `previousPositionBuffer` undefined. Motion is only the object transform.

**What a client that re-creates a mesh on every texture change loses**

1. Instance identity: the new handle changes `identityHash` and `spatialMapHash`; old RIs are destroyed immediately at DestroyMesh (`scene_manager.cpp:2625`). The first frame is a new RtInstance, so `teleport` gives zero object motion (`instance_manager.cpp:1206, 1221`).
2. Skinned/pre-skinned: a new BlasEntry means a full BLAS build (`scene_manager.cpp:475`) and no previous vertex positions that frame (`scene_manager.cpp:452`; `instance_manager.cpp:1198-1205`). History resumes the frame after.
3. Anti-culling/GC continuity of the old RI is bypassed (`draw_call_tracker.cpp:170-177`).
4. Cost: vertex copy and BLAS rebuild per texture change (`scene_manager.cpp:475`).
5. Not lost: object picking value, which is re-sent each frame (`instance_manager.cpp:1115`).

**(4) Fields for stable motion**

- Keep `info->hash` (mesh handle) stable across frames. It is part of both matching keys.
- `transform` is in the identity hash. Any change falls through to L2 (nearest within 300 units). Moving more than 300 units/frame loses history.
- `categoryFlags` is in the identity hash (`scene_manager.cpp:95`) but not in `l2Filter`, so a category change falls back to L2.
- `objectPickingValue` and `doubleSided` do not affect matching.
- No previous-transform field exists in the InstanceInfo consumer.
- Material-only texture swap (inference, not tested): the mesh looks up `externalMaterial` per draw (`scene_manager.cpp:2577`), and the identity hash uses the prototype material (`2559`, before the override at `2579`). Destroy-then-create of the material with the same handle (repeat creates are ignored: `asset_replacer.cpp:224-227`) should keep the RI and BlasEntry (`draw_call_cache.cpp:70`); the instance only gets `hasMaterialChanged` (`instance_manager.cpp:1079-1082`), which does not touch prev.

**Not found / not read**

- The C `remixapi_InstanceInfo` struct definition is not in this tree (grepped `typedef struct remixapi_InstanceInfo`, `REMIXAPI_STRUCT_TYPE_INSTANCE_INFO`); field list is inferred from consumers only.
- Shader-side use of `previousPositionBufferIndex`, `isStatic` and denoiser/DLSS history was not read (`src/dxvk/shaders` not examined).
- Whether DestroyMesh evicts BlasEntry from `DrawCallCache` was not read.