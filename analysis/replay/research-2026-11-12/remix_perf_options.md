# Scout report (agent 2): dxvk-remix remix-1.6.1

Read-only; nothing built or run. `R/` = `src/dxvk/rtx_render/`. Defaults are declared values. Other values are what presets write.

**Caveat:** the "Quality Presets" layer has the highest priority when preset ≠ Custom (`R/rtx_option_constants.h:194`, `R/rtx_option_layer.cpp:731`). Preset values therefore override rtx.conf/user.conf. Switching to Custom migrates them to User (`R/rtx_options.cpp:52-88`).

## 1. Cost-related options

`rtx.graphicsPreset` defaults to Auto (`R/rtx_options.h:331`). `RtxOptions::updateGraphicsPresets` (`R/rtx_options.cpp:410-614`) branches at Ultra 537, High 559, Medium 581, Low 592. Low and Medium share the block at 479-493.

| Setting (default, source) | Ultra | High | Medium | Low |
|---|---|---|---|---|
| pathMin/MaxBounces (1/4, `h:791,799`) | 1/4 | 0/2 | 0/2 | 0/2 |
| RR max / 1st-bounce continue (0.9/0.6, `h:778,783`) | 0.9/0.6 | 0.9/0.6 | 0.7/0.4 | 0.7/0.4 |
| Volumetric froxel XY divisor (8, `R/rtx_global_volumetrics.h:93`; table `cpp:184-190`) | 4 | 8 | 16 | 32 |
| Sparse samplingRate/exponent (0.357/0.69, `R/rtx_sparse_rendering.h:50,68`) | 0.357/0.69 | 0.228/0.83 | 0.125/0.83 | 0.1/0.91 |
| denoiseDirectAndIndirectLightingSeparately (true, `h:623`) | true | false | false | false |
| enableUnorderedResolveInIndirectRays (true, `h:849`) | true | true | false | false |
| enableUnorderedEmissiveParticlesInIndirectRays (false, `h:860`) | true | false | false | false |
| enableTransmissionApproximationInIndirectRays (false, `h:866`) | false | true | true | true |
| DLFG lite (frame gen) | off | off | on (`cpp:582`) | on (`cpp:593`) |

- Sparse rendering is off by default (`R/rtx_sparse_rendering.h:41`). No preset writes `enableSparseRendering`.
- Indirect mode (`rtx.integrateIndirectMode`, default SHaRC, `h:496`) is forced to SHaRC by all presets unless ReSTIR GI is set. NRC is kept only if supported (`cpp:494-516`).
- Auto DLSS profile (`R/rtx_dlss.cpp:103-128`): height ≤1080 → MaxQuality; <2160 → Balanced; <4320 → MaxPerf; else UltraPerf. Medium is one step lower, Low two steps lower. At 1800p, Ultra/High give Balanced, not Performance. Presets reset `qualityDLSS` to Auto unless `dlssPreset` is Custom (`cpp:606-609`).
- No preset writes these, so the defaults apply:
  - `upscalerType` DLSS (`h:508`), `enableRayReconstruction` true (`h:511`), `dlssPreset` On (`h:323`).
  - `resolutionScale` 0.75 (`h:515`), used only for NIS/TAAU/XeSS (`R/rtx_context.cpp:274-282`).
  - `useRTXDI` true (`h:493`). With RR on, the RR preset applies: initialSampleCount 3, spatial 2, disocclusion 2, sample stealing off, best-light off (`cpp:321-352`). Non-RR defaults are 4/2/4, stealing on (`R/rtx_rtxdi_rayquery.h:53-73`).
  - NRD denoiser `RELAX_DIFFUSE_SPECULAR` (`R/rtx_nrd_settings.h:43-44`), `useDenoiser` true (`h:593`).
  - Opacity micromaps: building, binding and baking arrays on (`R/rtx_opacity_micromap_manager.h:47-49`). Animated instances off (`:87`). Active only when the memory budget is >0 (`R/rtx_opacity_micromap_manager.cpp:2533-2535`).
  - `enableSeparateUnorderedApproximations` true (`h:703`). `enableEmissiveBlendModeTranslation` true (`h:935`).
  - `rtx.volumetrics.enable` true (`R/rtx_global_volumetrics.h:134`).
- `rtx.raytraceModePreset` Auto (`h:335`). Auto sets GBuffer RayQuery, Direct RayQuery, Indirect TraceRay on NVIDIA/RADV/AMD-prop, and Indirect RayQuery otherwise (`cpp:619-660`). Explicit defaults are GBuffer RayQuery (`h:575`), Direct RayQuery (`h:580`), Indirect TraceRay (`h:585`). Enum: RayQuery=0, RayQueryRayGen=1, TraceRay=2 (`R/rtx_pathtracer_gbuffer.h:33-38`).

## 2. Automatic preset selection

- Runs at init when `graphicsPreset==Auto` (`R/rtx_initializer.cpp:97-100`, `R/rtx_options.cpp:419`).
- Arch comes from `NvAPI_GPU_GetArchInfo` on the first physical GPU (`cpp:297,303-309`). On query failure it returns TU100, which gives Low.
- `selectAutoPreset` (`R/rtx_gpu_profile.cpp:166-221`), NVIDIA, no override:
  - arch < GA100 (Turing and older) → Low (`:187-191`)
  - < AD100 (Ampere) → Medium (`:193-195`)
  - < GB200 (Ada) → High (`:196-198`)
  - otherwise (Blackwell) → Ultra (`:199-201`)
- Non-NVIDIA → Low, plus resolutionScale 0.5 and NIS/TAAU Performance (`:203-208`, `cpp:450-456`).
- Exact device-local heap ≤ 8 GiB (`R/rtx_gpu_profile.h:61`): preset = clamp(preset+1, Medium, Low) and `lowMemoryGpu=true` (`cpp:213-220`). Net effect: Ada→Medium, Ampere→Low, Blackwell→Medium.
- RTX Spark (integrated Blackwell) → Medium (`:172-184`).
- Per-GPU override `rtx.gpuOverride.graphicsPreset.VVVV_DDDD` bypasses the table (`R/rtx_gpu_overrides.cpp:106-107,196-204`).
- Inconsistency: `:158` says NVAPI arch IDs are "not ordered by generation", yet `:187-199` compare with `<`.

## 3. BLAS/TLAS and mesh churn

- `minPrimsInDynamicBLAS` 1000, floored to 100 in code (`h:454`, `R/rtx_accel_manager.cpp:721`). `maxPrimsInMergedBLAS` 50000 (`h:455`). `forceMergeAllMeshes` and `minimizeBlasMerging` are both false and NoSave (`h:456-457`).
- Meshes under the threshold go to merged BLAS buckets, which are rebuilt each frame (`accel:726-737`, comment `:730`).
- BLAS compaction: not found. Build flags are PREFER_FAST_BUILD | ALLOW_UPDATE, plus LOW_MEMORY when `lowMemoryGpu` (`accel:292,857,1193,1905`). Geometry-only changes refit in UPDATE mode (`:896-899`).
- `enableInstanceMerging`: not found.
- Retention: `numFramesToKeepInstances` 1 (`h:629`), `numFramesToKeepBLAS` 1 (`h:630`), `numFramesToKeepLights` 100 (`h:631`). Geometry-data and material-texture retention alias the BLAS value (`h:642-648`). Effective BLAS keep is max(1 or 2, value) (`accel:97-99`). `enablePreviousTLAS` is true only when RR is off or ReSTIR GI is on (`h:650-652`). With the defaults (RR on, SHaRC) it is 1 frame.
- Pool GC: `accel:97-115`. Full skip when the scene is unchanged: `accel:445-450`.
- Threads:
  - `remixapi_CreateMesh` (`R/rtx_remix_api.cpp:1016-1044`) allocates surface buffers on the calling thread (`:1035`), then queues `registerExternalMesh` on the CS thread. It does not build a BLAS.
  - `DrawInstance` (`:1121-1137`) → `submitExternalDraw` (`R/rtx_scene_manager.cpp:2529-2600`).
  - The BLAS is built per frame on the render/CS context in `mergeInstancesIntoBlas`→`buildBlases` (`accel:434,1033,1756`), called from `scene_manager:2343`. A new mesh's BLAS is therefore built in the frame that processes its first draw.

## 4. Textures

- **API material path:** `remixapi_CreateMaterial` (`R/rtx_remix_api.cpp:893-902`) runs `toRtMaterialFinalized` → `preloadTexture` (`:271-288`) on the CS thread. `AssetDataManager::findAsset` (`R/rtx_asset_data_manager.cpp:617-685`) accepts `.dds` only, using the partial DDS loader (`rtx.usePartialDdsLoader`, `h:1176`) or a full GLI load with a warning.
- `preloadTextureAsset` (`R/rtx_texture_manager.cpp:1517-1575`) calls `scheduleTextureLoad(async=false)` (`:1562,1566`). That goes to `queueAdd`'s sync branch (`:498-516`), which runs `makeStagingForTextureAsset` on the calling thread (`:207-235`). The GPU upload happens later on the render thread (`:923`). File reads for API materials are therefore synchronous on the CS thread.
- **Game textures:** `trackTexture` uses async=true (`R/rtx_scene_manager.cpp:1755-1769`). `addTexture` only updates sampler feedback (`R/rtx_texture_manager.cpp:953-981`). `garbageCollection` (`:1336`), fed by feedback (`R/rtx_context.cpp:729`), schedules async loads on the `rtx-texture-async` thread (`:527`).
- Options:
  - `texturemanager.budgetPercentageOfAvailableVram` 50 (`h:1149`). `fixedBudgetEnable` false (`:1155`). `fixedBudgetMiB` 2048 (`:1156`). Minimum budget 32 MiB (`R/rtx_texture_manager.cpp:1589-1646`).
  - `samplerFeedbackEnable` true (`h:1159`). `neverDowngradeTextures` false (`:1162`). `stagingBufferSizeMiB` 96 (`:1164`). `hotReload` false (`:1167`).
  - `alwaysWaitForAsyncTextures` false (`h:1173`). `asyncAssetLoading` true (`h:1175`). `adaptiveResolutionReservedGPUMemoryGiB` 2 (`h:1141`). `lowMemoryGpu` false (`h:336`), which trims one mip (`R/rtx_texture_manager.cpp:1396`).
- Not found in src (case-insensitive): `rtx.enableAsyncTextureUpload`, `rtx.asyncTextureUploadPreloadMips`, `rtx.forceHighResolutionReplacementTextures`.
- **Pixels from memory:** not in the 1.6.1 source. Material texture fields are `remixapi_Path` file paths (`R/rtx_remix_api.cpp:193-198`). The function table has only CreateMaterial/Mesh (`:1787-1790`). `remixapi_TextureInfo` with `data`/`dataSize`/`format` and `remixapi_CreateTexture` appear only in `analysis/reference/remix-plus-remix_c.h:877-910`. They are absent from `analysis/remix-probe/vendor/remix_c.h` and from src.

## 5. Instance category flags

- Source enum: `R/rtx_types.h:630-657` (25 entries). Mapping: `R/rtx_remix_api.cpp:650-678`, with `static_assert(Count==25)` at `:678`.
- Bit values: `analysis/remix-probe/vendor/remix_c.h:480-503`. This header has `IGNORE_TRANSPARENCY_LAYER`=1<<22 (`:500`) and `HAIR_CARDS`=1<<25 (`:503`). The reference copy lacks HAIR_CARDS. Src maps HAIR_CARDS but not IGNORE_TRANSPARENCY_LAYER.
- Effects:
  - WORLD_UI / WORLD_MATTE: world UI (`R/rtx_instance_manager.cpp:1044,1195-1196`) and background offset (`:1215`).
  - SKY: CameraType::Sky (`rtx_remix_api.cpp:640-647`, `R/rtx_camera_manager.cpp:51-114`).
  - IGNORE: D3D9 path returns before RT (`src/d3d9/d3d9_rtx.cpp:1136-1138`). No API-draw consumer found.
  - IGNORE_LIGHTS: no light added (`R/rtx_light_manager.cpp:627`).
  - IGNORE_ANTI_CULLING: exempt (`R/rtx_draw_call_tracker.cpp:488-502`).
  - IGNORE_MOTION_BLUR: mask-out (`instance_manager:1105`).
  - IGNORE_OPACITY_MICROMAP and IGNORE_ALPHA_CHANNEL: no OMM (`R/rtx_opacity_micromap_manager.cpp:1014-1016`). Alpha ignored on materials (`R/rtx_scene_manager.cpp:1782`).
  - HIDDEN: skipped in merged BLAS (`R/rtx_accel_manager.cpp:654`) and in instance manager (`instance_manager:1042,1348`).
  - PARTICLE: `instance_manager:889,1195`. BEAM: `:2138`. PARTICLE_EMITTER: `scene_manager:788,1582`.
  - DECAL_STATIC/DYNAMIC/SINGLE_OFFSET/NO_OFFSET: `instance_manager:890`, `R/rtx_types.h:662`.
  - ALPHA_BLEND_TO_CUTOUT: forced alpha test (`instance_manager:720`). HAIR_CARDS: `:721`, `scene_manager:1670`.
  - TERRAIN: backface culling off (`instance_manager:97`), OMM skip (`omm:1015`), baking (`R/rtx_types.cpp:598`).
  - ANIMATED_WATER: `instance_manager:1101`. SMOOTH_NORMALS: `scene_manager:456,1545`.
  - THIRD_PERSON_PLAYER_MODEL: `instance_manager:1043`, `draw_call_tracker:501`. THIRD_PERSON_PLAYER_BODY: `instance_manager:1829`.
  - IGNORE_BAKED_LIGHTING: set from a texture list (`R/rtx_types.cpp:391`). No consumer found.
  - IGNORE_TRANSPARENCY_LAYER: not mapped in src, no consumer.