**Short answer:** Yes, but only by destroying and re-creating the material under the same handle. The mesh is never touched. A mesh stores the material handle, not a pointer, and the material is looked up on every draw. `CreateMaterial` with an existing hash is silently ignored, so it cannot update a material by itself.

Scope note: `public/include/remix/remix_c.h` does not exist under the dxvk-remix tree (`include/` only has gli, glm, vulkan). A `find` for `remix_c.h` found copies at `analysis/runtime/remix-probe/sample/include/remix/remix_c.h` and under `prior-art-deep-20261031/`. I did not open them, so the `MaterialInfo` field layout is not verified here. The fields the implementation reads are `hash`, `albedoTexture`, `normalTexture`, and `sType`.

**(1) CreateMaterial with an existing hash: ignored, no error**
- `rtx_remix_api.cpp:886` `auto handle = reinterpret_cast<remixapi_MaterialHandle>(info->hash);` (handle = hash)
- `rtx_remix_api.cpp:893-904` the work is queued to the command stream and the call returns `REMIXAPI_ERROR_CODE_SUCCESS`.
- `rtx_asset_replacer.cpp:223-227` `auto [iter, isNew] = m_extMaterials.emplace(...); if (!isNew) { Logger::info("Ignoring repeated material registration ..."); return; }`
- Side effect: the new paths are still preloaded before the discard, because `toRtMaterialFinalized(...)` is evaluated inside the lambda (`rtx_remix_api.cpp:897-900`).

**(2) Mesh whose material handle was destroyed: default material, draw not skipped**
- `rtx_remix_api.cpp:907-915` `DestroyMaterial` queues `destroyExternalMaterial` and always returns success.
- `rtx_asset_replacer.cpp:239-240` `m_extMaterials.erase(handle);`
- `rtx_scene_manager.cpp:2577-2580` `const MaterialData* material = m_pReplacer->accessExternalMaterial(submeshes[i].externalMaterial); if (material != nullptr) { ...setHashOverride(...) }`
- `rtx_scene_manager.cpp:2590-2591` `static MaterialData defaultMaterialData(LegacyMaterialData::createDefault()); auto& materialData = material != nullptr ? *material : defaultMaterialData;`
- Result: the draw proceeds with the default material. No crash path found.

**Per-draw lookup (no cached pointer)**
- `rtx_remix_api.cpp:988` `dst.externalMaterial = src.material;`
- `rtx_types.h:397` `remixapi_MaterialHandle externalMaterial = nullptr;` (a handle, not a pointer)
- `rtx_scene_manager.cpp:2553` `accessExternalMesh(state.mesh)` runs each draw; `:2577` resolves the material per submesh.
- `rtx_scene_manager.cpp:2556-2559` the instance key uses the legacy draw material hash, not the API material. Swapping the API material under the same handle does not change the instance key.
- `rtx_scene_manager.cpp:1665-1694` the surface-material cache key folds in `renderMaterialData.getHash()` plus a texture-presence mask. `rtx_texture.h:129-145` `getImageHash()` includes the asset hash, so a new texture file yields a new surface material.
- Meshes with the same handle are also ignored on repeat: `rtx_asset_replacer.cpp:244-246`.

**(3) Texture loading**
- Path lookup is synchronous on the command-stream thread: `rtx_remix_api.cpp:276` `AssetDataManager::get().findAsset(path.string())`, returning `{}` if null (`:277-279`).
- `rtx_asset_data_manager.cpp:620-633`: anything not `.dds` is rejected (`Logger::err` unless suppressed) and returns `nullptr`.
- `rtx_asset_data_manager.cpp:635-640`: partial DDS loader, synchronous header read.
- `rtx_asset_data_manager.cpp:677-684`: GLI fallback loads the whole file into RAM; returns `nullptr` on failure.
- Pixel upload is asynchronous: `rtx_texture_manager.cpp:1517-1567` `preloadTextureAsset` calls `scheduleTextureLoad(...)` (`:1562`/`:1566`). `:889-921` queues onto `m_asyncThread` / `m_asyncThread_rtxio`.
- Cache: `rtx_texture_manager.cpp:1526-1531` returns a cached texture if the asset hash and info match; `:1586` stores the new one.
- While loading: the texture is not resident until `m_currentMipView` is set (`rtx_texture_manager.cpp:758-761`, `:945`). `rtx_texture.h:119-127` `getImageView()` returns null and `:115-117` `isImageEmpty()` is true, so the albedo slot is empty. What the shader samples for an empty slot was not traced.
- Missing file at CreateMaterial: `findAsset` returns null and the material is stored with an empty albedo. No retry and no negative cache. Retry only happens after DestroyMaterial and CreateMaterial again.
- `rtx_texture.h:55` declares `kFailed`, and `rtx_texture_manager.cpp:882-884` checks it, but no code path assigns it (grep). Not found: any assignment.
- Hot reload: `rtx_texture_manager.cpp:1081-1094` `requestHotReload` (needs the async thread); `rtx_file_watch.cpp:639` `watchTexture`. Hot reload only applies to textures that already exist. A missing-at-create file never gets a watch.

**(4) Memory upload API**
- Not found. The interface table at `rtx_remix_api.cpp:1784-1797` has no texture entry. Grep for `UploadTexture|CreateTexture|remixapi_.*Texture` in `src/` only hits the D3D9/10/11 device `CreateTexture` for the game's own resources and `ImGui` pixels.
- Textures must be `.dds` files on disk (see `:620-633`).

**Cheapest correct way for "this material's albedo is now file X" on existing meshes**
1. Write `X` as a DDS file on disk (required format).
2. Call `remixapi_DestroyMaterial(H)`, then `remixapi_CreateMaterial(&info)` with the same `info.hash` (so `H` is unchanged) and `albedoTexture = X`, passing the full `MaterialInfo` again.
3. Do not touch the meshes. Both calls go through the same command-stream queue (`rtx_remix_api.cpp:893`, `:911`), so later draws see the new material.

Caveats:
- Calling `CreateMaterial` alone with the same hash does nothing (see (1)).
- If `X` is missing at step 2, the material has no albedo until the next destroy and create.
- A changed file at an already-loaded path is handled by hot reload, if enabled, and not verified here.