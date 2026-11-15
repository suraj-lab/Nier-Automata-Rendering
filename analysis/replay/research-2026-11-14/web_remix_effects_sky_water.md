# Remix effects, sky, water, emissive, hair, texture mips, shutdown — research for PLAN_2026-11-14

Date 2026-11-14. Read-only research. Input for the rewrite of `analysis/PLAN_2026-11-14.md`.

## Sources used and how to read the citations

| Label | What it is |
| --- | --- |
| `LOCAL:file:line` | Files in `analysis/runtime/remix-source/0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a/` (14 files only: `rtx_remix_api.cpp`, `rtx_context.cpp`, `rtx_resources.cpp`, `rtx_scene_manager.cpp`, `rtx_lights.*`, `rtx_light_manager.cpp`, `...`). |
| `src/...:NN @0ba9973` | Full dxvk-remix tree at the same commit. Not in the repo; reproduce with `git show 0ba9973:<path>` in a clone of `NVIDIAGameWorks/dxvk-remix`. All line numbers below were read that way. |
| `RtxOptions.md:NNN @0ba9973` | Generated option reference that ships in the repo at that commit (`RtxOptions.md`, also published as <https://github.com/NVIDIAGameWorks/dxvk-remix/blob/0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a/RtxOptions.md>). This is the only authoritative name+type+default source. |
| `remix_c.h:NNN` | `public/include/remix/remix_c.h` at 0ba9973 (<https://github.com/NVIDIAGameWorks/dxvk-remix/blob/0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a/public/include/remix/remix_c.h>). Remix API version **0.6.6** (`remix_c.h:63-65`). |
| `docs:URL` | <https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/...> |

Two identity caveats, both material for the plan:

1. `analysis/RTX_OPTIONS_THIS_BUILD.txt` was recovered from **Portal RTX's** `bin/.trex/d3d9.dll` (its own header, lines 1-4) and stores **leaf names only, deduplicated** — `particleTextures`, not `rtx.particleTextures`. It is also **incomplete**: `anisotropy` is absent even though `rtx.legacyMaterial.anisotropy` is documented at `RtxOptions.md:358 @0ba9973`. It also contains non-option strings (e.g. `rasterizeToSkyProbe`, line 689, is a C++ function name, `src/dxvk/rtx_render/rtx_context.cpp:2638 @0ba9973`). Use it only as a "does this leaf exist" smoke test, never as proof.
2. The laptop's runtime log says `DXVK_Remix: remix-main+5a7eec84` (`analysis/runtime/laptop-play-20261114/remix.log:6`), not 0ba9973. UNVERIFIED that 0ba9973 is that build. The repo's own note calls 0ba9973 "remix-1.6.1 source" (`analysis/PBR_MAPPING.md:43`). Every claim below is from 0ba9973; a plan step should re-confirm the few that matter on the device (see Recommended steps).

---

## 0. The API surface we actually have (no texture creation, no swapchain control)

The whole interface, `remix_c.h:805-833` (member order is frozen):

`Shutdown, CreateMaterial, DestroyMaterial, CreateMesh, DestroyMesh, SetupCamera, DrawInstance, CreateLight, DestroyLight, DrawLightInstance, SetConfigVariable, dxvk_CreateD3D9, dxvk_RegisterD3D9Device, dxvk_GetExternalSwapchain, dxvk_GetVkImage, dxvk_CopyRenderingOutput, dxvk_SetDefaultOutput, pick_RequestObjectPicking, pick_HighlightObjects, Startup, Present, SetCameraMediumMaterial`

- **There is no `remixapi_CreateTexture` at this version.** Textures reach Remix only as file paths: every texture field in `remixapi_MaterialInfo*` is a `remixapi_Path` (`remix_c.h:235-269`, `289-306`, `315-331`) and is resolved by `AssetDataManager::get().findAsset(path)` then `preloadTextureAsset(...)` (`LOCAL:rtx_remix_api.cpp:1184-1192`). C API add-ons in the changelog stop at 0.4.3 (`documentation/RemixApiChangelog.md @0ba9973`, 55 lines, entries 0.6.6/0.6.5/0.4.2/0.4.3 only) — particle systems, dome lights and camera medium are **not** listed there, so the header + implementation are the only spec.
- `remixapi_Shutdown` (`LOCAL:rtx_remix_api.cpp:1726`), `Startup` (`:1650`), `Present` (`:1756`); implementation/typedef line numbers differ between header copies (this one: `SetConfigVariable` typedef `remix_c.h:724`, interface member `:816`; the copy in `analysis/runtime/remix-probe/sample/include/remix/remix_c.h` has `:724` and `:810`). **Cite API functions by name in the plan, not by header line.**
- Category bits: `remix_c.h:477-505`; conversion to Remix categories `LOCAL:rtx_remix_api.cpp:670-700` with `static_assert((int)InstanceCategories::Count == 25, ...)` at `:698` — so all 25 bits are wired.

| bit | value | mapped at | notes |
| --- | --- | --- | --- |
| `WORLD_UI` | 1<<0 | `LOCAL:rtx_remix_api.cpp:673` | forces emission, intensity 2.0, emissive = albedo (`src/dxvk/rtx_render/rtx_instance_manager.cpp:1140-1146 @0ba9973`) |
| `SKY` | 1<<2 | `:675` | **instance is hidden, cannot be used to feed the sky probe** (see §2) |
| `IGNORE` `IGNORE_LIGHTS` `IGNORE_ANTI_CULLING` `IGNORE_MOTION_BLUR` `IGNORE_OPACITY_MICROMAP` `IGNORE_ALPHA_CHANNEL` `HIDDEN` | 1<<3..8, 1<<21 | `:676-682` | |
| `PARTICLE` | 1<<9 | `:683` | sets `surface.isParticle` → soft-particle fade + unordered approximation path (`rtx_instance_manager.cpp:890 @0ba9973`) |
| `BEAM` | 1<<10 | `:684` | |
| `DECAL_STATIC` `DECAL_DYNAMIC` `DECAL_SINGLE_OFFSET` `DECAL_NO_OFFSET` | 1<<11..14 | `:685-688` | |
| `ALPHA_BLEND_TO_CUTOUT` | 1<<15 | `:689` | |
| `TERRAIN` | 1<<16 | `:690` | |
| `ANIMATED_WATER` | 1<<17 | `:691` | drives the animated-water normal animation |
| `THIRD_PERSON_PLAYER_MODEL` `_BODY` | 1<<18..19 | `:692-693` | |
| `IGNORE_BAKED_LIGHTING` | 1<<20 | `:694` | |
| `IGNORE_TRANSPARENCY_LAYER` | 1<<22 | not mapped | documented "Deprecated. Reserved for API compatibility and ignored by the runtime" (`remix_c.h:499-500`) |
| `PARTICLE_EMITTER` | 1<<23 | `:695` | spawns Remix-generated particles from the instance (see §1.4) |
| `SMOOTH_NORMALS` | 1<<24 | `:696` | |
| `HAIR_CARDS` | 1<<25 | `:697` | |
| `VIEW_MODEL` | 1<<26 | `:662-664` | camera type ViewModel |

---

## 1. Particles and effects

### 1.1 How Remix renders alpha-blended billboards (this is the whole answer for E1)

The blend state of an opaque-material instance is derived in `calculateAlphaState` (`src/dxvk/rtx_render/rtx_instance_manager.cpp:735-880 @0ba9973`). There are exactly two inputs, and `remixapi_MaterialInfoOpaqueEXT.useDrawCallAlphaState` selects between them (`remix_c.h:249-253`, read at `LOCAL:rtx_remix_api.cpp:429`):

- `useDrawCallAlphaState = 1` → use `remixapi_InstanceInfoBlendEXT` factors (`src/.../rtx_instance_manager.cpp:767-862`).
- `useDrawCallAlphaState = 0` → use the material's own `blendType_value` / `invertedBlend` / `alphaTestType` (`:764-768`; fields `remix_c.h:253-257`).

Translation table for the draw-call route (`rtx_instance_manager.cpp:770-862 @0ba9973`), `BlendType` enum `src/dxvk/shaders/rtx/concept/surface/surface_shared.h:24-37 @0ba9973`:

| src/dst colour factors, op=ADD | resulting `BlendType` | comment in source |
| --- | --- | --- |
| ONE / ZERO | blending off | "Opaque Alias" |
| SRC_ALPHA / ONE_MINUS_SRC_ALPHA | `kAlpha` (0) | |
| ONE_MINUS_SRC_ALPHA / SRC_ALPHA | `kAlpha`, `invertedBlend=1` | |
| SRC_ALPHA / ONE | `kAlphaEmissive` (1) | "Standard Emissive Alpha Blending" |
| ONE_MINUS_SRC_ALPHA / ONE | `kAlphaEmissive`, inverted | |
| ONE / SRC_ALPHA | `kReverseAlphaEmissive` (2) | |
| ONE / ONE_MINUS_SRC_ALPHA | `kAlphaEmissive` if the alpha-factors "look premultiplied", else `kReverseAlphaEmissive` inverted (`:791-818`) | |
| SRC_COLOR / ONE_MINUS_SRC_COLOR (and inverse) | `kColor` (3) | |
| SRC_COLOR / ONE, ONE_MINUS_SRC_COLOR / ONE | `kColorEmissive` (4) | |
| ONE / SRC_COLOR | `kReverseColorEmissive` (5) | |
| ONE / ONE_MINUS_SRC_COLOR | `kColorEmissive` | |
| **ONE / ONE** | **`kEmissive` (6)** | "Emissive Blending" — this is pure additive |
| DST_COLOR/ZERO, ZERO/SRC_COLOR | `kMultiplicative` (7) | |
| DST_COLOR / SRC_COLOR | `kDoubleMultiplicative` (8) | |
| anything else | **blending off → solid geometry** | `:857-859` |

Every `k*Emissive` case is gated on `RtxOptions::enableEmissiveBlendModeTranslation()` (default **true**, `RtxOptions.md:241 @0ba9973`); with it off those modes degrade to `kAlpha`/`kColor`. **That fall-through to "blending off" at `:857` is the mechanism that turned NieR's effect draws into solid cutout geometry** — for exotic factor combinations there is no Remix blend type at all.

What each blend type becomes in the shader (`src/dxvk/shaders/rtx/concept/surface_material/opaque_surface_material_blending.slangh:100-170 @0ba9973`):

- `kAlpha` → `opacity = alpha`; `kColor` → `opacity = luma(albedo)`.
- `kAlphaEmissive` → `opacity = luma(albedo)*alpha` **and** `emissiveBlendOverrideInfluence = alpha`; `kEmissive` → `emissiveBlendOverrideInfluence = 1`, opacity `luma(albedo)`.
- The `if (enableOpacityEmissiveBlendModes)` branch is `cb.wboitEnabled` (`opaque_surface_material_interaction.slangh:722 @0ba9973`), i.e. `rtx.wboitEnabled`, default true (`RtxOptions.md` / `rtx_options.h:947 @0ba9973`). With WBOIT off, emissive-blend materials get `opacity = 0` — invisible except for their glow.
- Final emission: `emissiveRadiance = emissiveBlendOverrideInfluence * emissiveColor * emissiveIntensity` (`opaque_surface_material_interaction.slangh:882`).

Brightness control for additive things, exact rules:

- If `useDrawCallAlphaState = 1` and the blend resolved to an emissive type, Remix **patches** the material: `enableEmission = true`, `emissiveIntensity = rtx.emissiveBlendOverrideEmissiveIntensity` (default **0.2**, `rtx_options.h:937`), `emissiveColorTexture = albedoOpacityTexture` (`rtx_instance_manager.cpp:1146-1153`). Guarded by `rtx.enableEmissiveBlendEmissiveOverride` (default true, `rtx_options.h:936`) **and** `useLegacyAlphaState` — the "assume the user knows what they are doing" comment means this override does **not** fire on the explicit-material route.
- If `useDrawCallAlphaState = 0`, the material's own `emissiveIntensity` / `emissiveColorConstant` / `emissiveTexture` are used unchanged (`LOCAL:rtx_remix_api.cpp:411-416`). This is the route for per-effect brightness.
- Global multiplier `rtx.emissiveIntensity` (default 1, `RtxOptions.md:225`) scales every emissive material.

Practical recipe for additive sparks/beams through the API (all names verified in the header/source):
`remixapi_InstanceInfo.categoryFlags |= REMIXAPI_INSTANCE_CATEGORY_BIT_PARTICLE` (or `_BEAM`), material opaque EXT with `useDrawCallAlphaState=1` and an `remixapi_InstanceInfoBlendEXT` with `alphaBlendEnabled=1, srcColorBlendFactor=1 (ONE), dstColorBlendFactor=1 (ONE), colorBlendOp=0` → `kEmissive`, emissive colour taken from the albedo texture, intensity `rtx.emissiveBlendOverrideEmissiveIntensity`. For per-effect control instead set `useDrawCallAlphaState=0` + `blendType_hasvalue=1, blendType_value=6` + `emissiveIntensity` on the material.

### 1.2 Soft particles (depth fade) — present, but it is a distance fade

`rtx.particleSoftnessFactor` (default **0.05**, range 0..1, `rtx_options.h:939-940`) is used only for surfaces with `isParticle` (the PARTICLE category):

```
softBlendFactor = saturate((ray.tMax - hitDistance) / (ray.tMax * particleSoftnessFactor))   // resolve.slangh:1038 @0ba9973
blendFactor     = surface.isParticle ? softBlendFactor : 1.0
```

So the fade is measured against **that ray's maximum distance**, not against a depth buffer / geometry proximity: particles closer than ~`tMax*factor` to the end of the ray fade out. For primary rays, `tMax` is the distance to what the ray eventually hits, which is a decent stand-in for soft particles; it is not the game's own depth-based fade. Documented as "Multiplier for the view distance that is used to calculate the particle blending range" (`docs:docs/runtimeinterface/renderingtab/remix-runtimeinterface-rendering-alphatestbending.html`).

### 1.3 Unordered approximations

- `rtx.enableSeparateUnorderedApproximations` (default true, `rtx_options.h:703-707`): separate resolve loop for particles/decals; "unordered nature … may result in visual artifacts with large numbers of stacked particles"; only first indirect bounce.
- `rtx.enableUnorderedResolveInIndirectRays` and `rtx.enableUnorderedEmissiveParticlesInIndirectRays` (default **false**, `rtx_options.h:860-864`) — without the latter, emissive particles do not light reflections/GI.
- `rtx.wboitEnabled` (default true) is required for emissive-blend particles to have any opacity (§1.1).
- `rtx.primaryRayMaxInteractions` / `rtx.psrRayMaxInteractions` (default 32, `RtxOptions.md:621,624`) cap how many decals/portals/"potentially particles (if unordered approximations are not enabled)" a ray may cross.

### 1.4 Remix's own particle system (exists in this build, usable from the API)

Options live under `rtx.particles.*` and `rtx.particles.globalPreset.*` (`src/dxvk/rtx_render/rtx_particle_system.h:180-239 @0ba9973`): `enable`, `enableSpawning`, `timeScale`, `enableDiscontinuityGuard`, `discontinuityFactor`, `discontinuityFloor`; preset: `spawnRatePerSecond`, `spawnBurstDuration`, `numberOfParticlesPerMaterial`, `minParticleLife`, `maxParticleLife`, `minSpawnSize`/`maxSpawnSize`, `minTargetSize`/`maxTargetSize`, `initialVelocityFromNormal`, `initialVelocityConeAngleDegrees`, `gravityForce`, `alignParticlesToVelocity`, `enableCollisionDetection`, `collisionMode`, `useTurbulence`, `enableMotionTrail`, `motionTrailMultiplier`, `billboardType`, `spriteSheetMode`, `randomFlipAxis`, `dragCoefficient`, `attractor*`, `restrictVelocityX/Y/Z`.

- API struct: `remixapi_InstanceInfoParticleSystemEXT` (`remix_c.h:532-574`) — per-emitter parameters incl. animated curves (`remixapi_AnimatedFloat1D/2D/3D/4D`, `remix_c.h:510-528`), `maxNumParticles`, `billboardType`, `spriteSheetMode`, `collisionMode`, `randomFlipAxis`; parsed at `LOCAL:rtx_remix_api.cpp:795-807`, attached to the draw state at `:862-868`.
- It works for external draws: `submitExternalDraw` (`src/dxvk/rtx_render/rtx_scene_manager.cpp:2535 @0ba9973`) → `processDrawCallState(..., pParticles)` (`:2599`) → `RtxParticleSystemManager::spawnParticles` (`:1594`), and the emitter mesh is drawn as normal geometry unless `hideEmitter` is set (`:1596-1598`).
- Legacy counterpart: `remixapi_InstanceInfoParticleSystemLegacyEXT` / struct type `REMIXAPI_STRUCT_TYPE_DEPRECATED_LEGACY_PARTICLE_SYSTEM` (`remix_c.h:134`, handled at `LOCAL:rtx_remix_api.cpp:865-867`).
- Texture-tag route (no API call needed): a texture in `rtx.particleTextures` (hash set, `rtx_options.h:211`) marks *existing billboards* as particles (approximate rendering); a texture in `rtx.particleEmitterTextures` (`rtx_options.h:296`) makes that object **emit** Remix-generated particles using the global preset (`rtx_scene_manager.cpp:1584-1588`). `rtx.beamTextures` (`rtx_options.h:222`) tags beams. The particle-manager selection also looks at material replacements' particle desc (`:1580-1583`), priority "Mesh, Material, Texture".
- Docs: `docs:docs/howto/learning-particles.html` — "assigning a 'Particle Emitter' Render Category to any texture will create a particle system … All particles will use a single set of global settings"; the Toolkit authors per-emitter systems through the `ParticleSystemAPI` USD schema. Advanced Particle VFX (curve editor, attractors, X/Y size, drag, bounce/stop/kill) arrived in 1.4 (`docs:docs/changelog/remix-releasenotes.html`, "RTX Remix Release 1.4 Notes (4/21/2026)").

### 1.5 What an API client cannot do

| Wanted | Status |
| --- | --- |
| Additive sparks that light the scene | Possible: PARTICLE/BEAM category + `kEmissive`/`kAlphaEmissive` blend, `rtx.emissiveIntensity`, and `rtx.enableUnorderedEmissiveParticlesInIndirectRays=1` so they appear in reflections/GI. |
| Soft smoke | Approximate: PARTICLE category (distance fade via `rtx.particleSoftnessFactor`) + `kAlpha`/`kAlphaEmissive`; or Remix-generated volumetric-looking puffs via `ParticleSystemEXT`; or a global fog via the camera-medium material (§1.6). |
| **Screen-space distortion / refraction of the already-rendered image** | **Not available.** No API field for a distortion/refraction of the frame; the closest real refraction is the translucent material's `refractiveIndex` (`remix_c.h:293`) which bends *rays*, and ray portals (`remixapi_MaterialInfoPortalEXT`, `remix_c.h:308-313`), which need real paired geometry and `rtx.rayPortalEnabled` + `rtx.rayPortalModelTextureHashes` (`RtxOptions.md:633`). NieR's heat-haze/distortion pass cannot be reproduced; it has to be composited over the Remix image or dropped. |
| Per-particle lighting | Only through `rtx.neeCache.approximateParticleLighting` (default true, "Use particle albedo as emissive color", `rtx_nee_cache.h:66`) and the effect-light converter (§1.7). |
| Game's exact soft-particle depth fade | No: §1.2 is a ray-length fade. |

### 1.6 Camera medium (free "everything is foggy/smoky" switch)

`remixapi_SetCameraMediumMaterial` (`remix_c.h:424-428`; `LOCAL:rtx_remix_api.cpp:1108-1140`): pass a **material handle of type Translucent**; Remix starts every camera ray inside that medium (volumetric scattering). Passing `nullptr` clears it. Errors are only logged ("material must be translucent"). Useful for combat dust/fog ambience, but it is global and camera-locked, not a plume.

### 1.7 Cheap effect lighting without particles

`rtx.lightConverter` (hash set, `rtx_options.h:209-210`): tagged draw calls spawn a dynamic sphere light at the geometry centroid with plasma-ball animation. Applied in `processDrawCallState` (`src/dxvk/rtx_render/rtx_scene_manager.cpp:1573-1575 @0ba9973`), so it also sees external draws whose material hash matches. UNVERIFIED whether an API material's hash can be placed in that set; the hash is the same one used for replacement lookup (`setHashOverride(material->getHash())`, `rtx_scene_manager.cpp:2585`), so it is plausible.

---

## 2. Sky

### 2.1 The finding that changes W1: `SKY` instances from the API are hidden

- `LOCAL:rtx_remix_api.cpp:662-668`: `REMIXAPI_INSTANCE_CATEGORY_BIT_SKY` → `CameraType::Sky`; `:675` sets `InstanceCategories::Sky`.
- API draws go `remixapi_DrawInstance` → `commitExternalGeometryToRT` (`LOCAL:rtx_remix_api.cpp:1143-1160`, `LOCAL:rtx_context.cpp:1092-1094`) → `SceneManager::submitExternalDraw` (`src/dxvk/rtx_render/rtx_scene_manager.cpp:2535 @0ba9973`).
- The sky rasterisation lives on the **game** draw path only: `RtxContext::commitGeometryToRT` calls `tryHandleSky(&params, &drawCallState)` (`src/dxvk/rtx_render/rtx_context.cpp:1049 @0ba9973`; declaration `src/dxvk/rtx_render/rtx_sky.h:82`), and `tryHandleSky` → `rasterizeSky` → `rasterizeToSkyMatte` + `rasterizeToSkyProbe` (`rtx_sky.h:122`, `rtx_context.cpp:2897-2898`). `rasterizeSky` has exactly one caller (`rtx_sky.h:122`), so nothing an API client submits can ever reach it.
- Instead, the instance manager hides it: *"Hide the sky instance since it is not raytraced. Sky mesh and material are only good for capture and replacement purposes."* — `src/dxvk/rtx_render/rtx_instance_manager.cpp:1047-1051 @0ba9973`.

**Consequence: `rtx.skyBoxTextures`, `rtx.skyBoxGeometries`, `rtx.skyAutoDetect`, `rtx.skyMinZThreshold`, `rtx.skyDrawcallIdThreshold`, `rtx.skyReprojectToMainCameraSpace` and the sky probe are all zero-effect for an API client.** Those heuristics run in `DrawCallState::setupCategoriesForHeuristics` (`src/dxvk/rtx_render/rtx_types.cpp:585-600 @0ba9973`, hash lookups at `:560-568`) and only matter for the D3D9 draw path. W1 must be re-specified.

### 2.2 What an API client *can* do about the sky: the dome light

`remixapi_LightInfoDomeEXT` (`remix_c.h:670-675`): `transform` + `colorTexture` (a path), radiance comes from `remixapi_LightInfo.radiance` (`remix_c.h:702-707`). Created through `remixapi_CreateLight` (`LOCAL:rtx_remix_api.cpp:1162-1215`; dome branch `:1180-1211`):

- The texture is loaded through the same asset manager (`findAsset` at `:1191`, `preloadTextureAsset(assetData, ColorSpace::AUTO, true)` at `:1194-1195`) and kept in VRAM (`:1206`).
- Sampling is **equirectangular lat-long**, not cubemap: `sampleUV = cartesianDirectionToLatLongSphere(mul(worldToLight, float4(dir,0)).xyz)` (`src/dxvk/shaders/rtx/concept/light/light_helper.slangh:40-52 @0ba9973`), with `theta = acos(z), phi = atan2(x, y), uv = (0.5 + phi/2pi, theta/pi)` (`src/dxvk/shaders/rtx/utility/math.slangh:216-221`). So the DDS must be a lat-long panorama laid out with +Y at u=0.5, v=0 top.
- It **overrides the sky for primary rays and for indirect misses whenever it is active**: `composite.comp.slang:624-647` picks `domeLightArgs` first, then `skyUseProbeForPrimaryRays`, then the screen-space sky matte; `integrator_indirect.slangh:372` and `geometry_resolver.slangh:2036,2931` do the same on misses. Multiplying factor is `info.radiance` × texture.
- At most one dome light is active — the light manager keeps an "active external dome light" (`src/dxvk/rtx_render/rtx_light_manager.h:134-137`, `rtx_light_manager.cpp:812-846 @0ba9973`).

The sun: `remixapi_LightInfoDistantEXT` (`remix_c.h:661-668`) — `direction` (must be normalized), `angularDiameterDegrees`, `volumetricRadianceScale`; converted at `LOCAL:rtx_remix_api.cpp:648-657`. Works through the API. Note PR #148 upstream "Use full fp32 for direction and orientation on distant lights" (merged) is about precision, not availability.

### 2.3 The rest of the sky options (for completeness; only meaningful if the game's own sky draws ever go through Remix)

| key | default | meaning | source |
| --- | --- | --- | --- |
| `rtx.skyBrightness` | 1 | multiplier on probe/matte radiance in composite, indirect integrator, resolver (`composite.comp.slang:628-636`, `integrator_indirect.slangh:376`) | `rtx_options.h:1236` |
| `rtx.skyForceHDR` | false | rasterise the sky into `VK_FORMAT_B10G11R11_UFLOAT_PACK32` instead of the game's RT format; warns "Sky may not appear correct…" when the game sky is LDR and no HDR replacement exists | `rtx_sky.h:90-98`, `rtx_context.cpp:2887-2892` |
| `rtx.skyProbeSide` | 1024 | probe cube resolution (power of two, GUI clamps 256..8192) | `rtx_options.h:1238`, `dxvk_imgui.cpp:2984-2989` |
| `rtx.skyUseProbeForPrimaryRays` | false | primary misses sample the probe by direction instead of the screen-space matte | `composite.comp.slang:630-634` |
| `rtx.skyReprojectToMainCameraSpace` | false | promote 3D sky geometry into ray-traced geometry | `rtx_sky.h:104-127` |
| `rtx.skyReprojectScale` | 16 | | `RtxOptions.md:746` |
| `rtx.skyForceAutoDetectedToReproject` | false | | `rtx_sky.h:104-118` |
| `rtx.skyUiDrawcallCount` | 0 | **`RtxOptionFlags::NoSave`, no description**, not user-facing | `rtx_options.h:1239` |
| `rtx.skyDrawcallIdThreshold` | 0 | first N untextured draw calls are sky | `rtx_options.h:1240` |
| `rtx.skyMinZThreshold` | 1 | | `RtxOptions.md:744` |
| `rtx.skyAutoDetect` | 0 (None) | 0=none, 1=camera position, 2=+depth flags | `rtx_options.h:1242-1247`, `rtx_types.cpp:448-470` |
| `rtx.skyBoxTextures`, `rtx.skyBoxGeometries` | empty sets | hash sets | `RtxOptions.md:1038-1039` |

No physical/atmospheric *sky* exists in this build: only `rtx.volumetrics.enableAtmosphere`, `atmosphereHeightMeters`, `atmospherePlanetRadiusMeters`, `atmosphereInverted` (`RtxOptions.md:924-930`), which are finite-atmosphere volumetrics, not a sky model. `rtx.atmosphere.sunElevation` / `sunRotation` — used by `analysis/FO4_REMIX_NOTES.md:138,192` — **do not exist here** (not in `RtxOptions.md @0ba9973`, not in `RTX_OPTIONS_THIS_BUILD.txt`; the only `atmosphere*` leaves there are the four volumetric ones, lines 71-73, 228).

Docs corroboration for HDR sky textures: a skybox texture becomes a linear **BC6H `.s.rtex.dds` with a full mip chain**, and *"Set `rtx.skyForceHDR` before you use a skybox. With the default value, the runtime draws the sky in the SDR format of the game. It clips values above 1 and reads the linear values as sRGB, so the sky is too dark."* (`docs:docs/howto/learning-ingestion.html#skybox-textures`).

---

## 3. Water

### 3.1 Translucent material fields available to the API

`remixapi_MaterialInfoTranslucentEXT` (`remix_c.h:289-306`), parsed at `LOCAL:rtx_remix_api.cpp:459-487`:

| field | maps to | notes |
| --- | --- | --- |
| `transmittanceTexture` | `transmittanceOrDiffuseTextureIndex` | preloaded only in the translucent branch (`LOCAL:rtx_remix_api.cpp:236-252`) |
| `refractiveIndex` | IOR | scaled globally by `rtx.translucentMaterial.refractiveIndexScale` (clamp 0..3) |
| `transmittanceColor` + `transmittanceMeasurementDistance` | per-channel extinction over that distance | |
| `thinWallThickness_hasvalue` / `thinWallThickness_value` | `isThinWalled` + thickness | default thickness 0.001 (`LOCAL:rtx_remix_api.cpp:474-476`); thin-walled is encoded as **negative** `thicknessOrMeasurementDistance` (`src/dxvk/rtx_render/rtx_materials.h:1204 @0ba9973`) and the shader then skips refraction/reflection path splitting (`visibility.slangh:202-206`, `translucent_surface_material_interaction.slangh:496-500`) |
| `useDiffuseLayer` | `useDiffuseLayer` | a diffuse (frosted) layer on top |
| `textureScroll*`, `textureScale*`, `textureOffset`, `textureRotation` | texture transform | 0.6.6 only (`remixapi_MaterialInfo` requires `s_apiVersion >= 0.6.6`, `LOCAL:rtx_remix_api.cpp:398`) |

Performance/quality knobs that matter for a large water plane:

- `rtx.enableDirectTranslucentShadows` (default **false**) and `rtx.enableIndirectTranslucentShadows` (default false): without them water does not produce coloured shadows in direct/indirect light (`RtxOptions.md:239,248`).
- `rtx.enableTransmissionApproximationInIndirectRays` (default false): indirect rays through glass/water "will not alter ray direction, just change the ray throughput" (`RtxOptions.md:277`) — the cheap mode for a big plane in reflections.
- `rtx.enablePSTROutgoingSplitApproximation` / `...SecondaryIncidentSplitApproximation` (both default true) trade accuracy for glass quality (`RtxOptions.md:256-257`).
- `rtx.minTranslucentTransmissionLobeSamplingProbability` (0.25), `rtx.translucentTransmissionLobeSamplingProbabilityZeroThreshold` (0.01), `rtx.minTranslucentSpecularLobeSamplingProbability` (0.3) (`RtxOptions.md:399-400,879-880`).
- `rtx.volumetrics.enableTranslucentShadows` (false) for volumetric light rays through water (`RtxOptions.md:940`).
- Every translucent surface is resolved in the unordered/alpha path (WBOIT + resolve loop, §1.1/1.3), i.e. it costs extra resolve interactions, and each translucent layer along a ray is another interaction (`rtx.primaryRayMaxInteractions`, default 32).

### 3.2 Animated water: two independent mechanisms, both reachable by category bit

The category bit is all that is needed — `REMIXAPI_INSTANCE_CATEGORY_BIT_ANIMATED_WATER` → `InstanceCategories::AnimatedWater` (`LOCAL:rtx_remix_api.cpp:691`). `rtx.animatedWaterTextures` (`rtx_options.h:259-262`) is only the texture-hash shortcut for the game path.

- **Opaque** water: `rtx.opaqueMaterial.layeredWaterNormalEnable` (default true), `layeredWaterNormalMotion` (Vector2), `layeredWaterNormalMotionScale` (9.0), `layeredWaterNormalLodBias` (5.0) (`src/dxvk/shaders/rtx/pass/material_args.h:86-99 @0ba9973`). A second, blurred normal sample is taken from the same normal map with a shifted texture transform and blended in (`opaque_surface_material_interaction.slangh:604-617`).
- **Translucent** water: `rtx.translucentMaterial.animatedWaterEnable` (default true), `animatedWaterPrimaryNormalMotion` (0.05, 0.05), `animatedWaterSecondaryNormalMotion` (-0.03, -0.06), `animatedWaterSecondaryNormalLodBias` (1.0) (`material_args.h:141-151`). The primary UV is scrolled and a second normal sample is blended (`translucent_surface_material_interaction.slangh:62-89 @0ba9973`). Both are driven by Remix's own `timeSinceStartSeconds` — the docs say so explicitly ("will not respect any time warping performed by the game (so pause, slow mo, etc will not change animation speed)", `material_args.h:141-146`) — so water keeps moving while the game is paused.
- Ray-reconstruction history: `rtx.rayreconstruction.invalidateHistoryForAnimatedWater` (default false) avoids ghosting from moving water normals (`src/dxvk/rtx_render/rtx_ray_reconstruction.h:77 @0ba9973`, used at `geometry_resolver.slangh:510`, `translucent_surface_material_interaction.slangh:867`).

How other Remix mods do large water: the documented route is a *material replacement* over the game's own static water plane, converted to translucent, with animated water normals enabled — `docs:docs/howto/learning-materials.html#translucency` ("Materials containing 'translucent,' 'glass,' or 'trans' in their name are automatically converted…", manual override via "Create Material Override (Translucent)") plus tagging the plane's texture as animated water. Remix 1.5 notes add transmission of light rays through water/glass for volumetrics (`docs:docs/changelog/remix-releasenotes.html` "Light rays in the volumetrics system now support transmission through water and glass"). No mod I could inspect uses actual geometry-level water simulation; UNVERIFIED that any public mod does more than this.

---

## 4. Emissive materials

- API: `remixapi_MaterialInfo.emissiveTexture`, `emissiveIntensity`, `emissiveColorConstant` (`remix_c.h:322-325`); opaque EXT has no separate emissive intensity. Parsed at `LOCAL:rtx_remix_api.cpp:412-415` (`emissiveIntensity`, `emissiveColorConstant`) and `:224` (`emissiveTexture` preload). The material-level "enable emission" flag is `emissiveIntensity > 0` (`:415`), so **intensity 0 silently disables emission and the emissive texture is not even sampled** (`opaque_surface_material_interaction.slangh:855-860`).
- Global: `rtx.emissiveIntensity` (1.0) scales all emissive materials (`RtxOptions.md:225`). `rtx.legacyMaterial.emissiveIntensity` (0), `...enableEmissive` (false), `...emissiveColorConstant` (0,0,0) are the defaults for **non-replaced** legacy materials only (`RtxOptions.md:359-361`) — i.e. what the game's own draws get.
- Glow/bleed: `rtx.bloom` / post-processing — not researched here; `rtx.neuralRadianceCache.boostEmissives` (true) keeps emissive lighting on indirect bounces where NRC would otherwise skip it (`RtxOptions.md:430`).
- Night scenes: nothing special is required — an emissive material with `emissiveIntensity > 0` lights the scene through NEE/GI; the practical limits are `rtx.primaryRayMaxInteractions` and the unordered-emissive-in-indirect switch (§1.3). Per-material emissive textures must be DDS on disk (§7).

---

## 5. Hair: what anisotropy actually is here

- Field exists and is reachable: `remixapi_MaterialInfoOpaqueEXT.anisotropy` (`remix_c.h:240`), read straight into `OpaqueMaterialData` at `LOCAL:rtx_remix_api.cpp:412`. Range −1..1, 0 = isotropic (`RtxOptions.md:358` for the legacy equivalent).
- It is a **per-material scalar**, not a direction map: `calcRoughness(roughness, anisotropy, isotropicRoughness, anisotropicRoughness)` splits roughness into two lobes (`src/dxvk/shaders/rtx/concept/surface_material/opaque_surface_material_interaction.slangh:846-849 @0ba9973`), and the shading tangent for anisotropy is explicitly unimplemented — the comment at `:836` reads `// Todo: Shading tangent/bitangent for anisotropy?`.
- The `tangentTexture` field (`remix_c.h:322`) is loaded and then **never used**: `tangentSample` is assigned at `opaque_surface_material_interaction.slangh:620` and does not appear again anywhere in the shader tree (grep for `tangentSample` returns only `:596` and `:620`). So a tangent-space anisotropy direction cannot be fed through the API at this version.
- Subsurface is available for the "light bleeding through hair/skin" part: `remixapi_MaterialInfoOpaqueSubsurfaceEXT` (`remix_c.h:272-287`) — transmittance colour/texture, measurement distance, single-scattering albedo, volumetric anisotropy, diffusion profile, radius/scale/max sample radius; parsed at `LOCAL:rtx_remix_api.cpp:435-443` with defaults `(0.5,0.5,0.5)` and distance 0 when the EXT is absent. Notes: `subsurfaceRadiusTexture` needs API ≥ 0.5.1 (`:233`).
- `REMIXAPI_INSTANCE_CATEGORY_BIT_HAIR_CARDS` (1<<25) exists (`remix_c.h:503`) and is mapped (`LOCAL:rtx_remix_api.cpp:697`); its runtime effect was not traced here (UNVERIFIED).
- `rtx.maxAnisotropySamples` (8) and `rtx.useAnisotropicFiltering` (true) are **texture filtering**, not shading anisotropy (`RtxOptions.md:390,887`). `rtx.dust.anisotropy` (0.5) is the built-in dust particle phase function (`RtxOptions.md:203`).

---

## 6. Replacement texture mip chains and the "suboptimal" warning

- Exact trigger: `warnIfTextureSuboptimal` (`src/dxvk/rtx_render/rtx_texture_manager.cpp:1481-1492 @0ba9973`)
  `(mipLevels == 1) && (width*height >= 512*512)` → `Logger::warn("A suboptimal replacement texture detected: <file>! Please make sure all replacement textures have mip-maps.")`.
  Called from `preloadTextureAsset` at `:1553`, i.e. **every** texture loaded by path — replacement material textures *and* API material textures *and* the dome-light texture, which also goes through `preloadTextureAsset(..., forceLoad=true)` (`LOCAL:rtx_remix_api.cpp:1191`).
- Consequence of the warning: the texture is still loaded, but with `requestMips(1)` when it fits the staging budget (`rtx_texture_manager.cpp:1558-1566`), so it is sampled at mip 0 only — aliasing and memory pressure. Remix does **not** generate the missing mips: `RtxMipmap` (`src/dxvk/rtx_render/rtx_mipmap.cpp`) is used only for internal render targets and the terrain baker (grep `RtxMipmap::` → `rtx_local_tone_mapping.cpp`, `rtx_terrain_baker.cpp` only). `MAX_MIPS` is 32 (`src/dxvk/rtx_render/rtx_texture.h:46`).
- Mip count comes from the DDS header: `m_levels = (header.Flags & DDSD_MIPMAPCOUNT) ? header.MipMapLevels : 1` (`src/dxvk/rtx_render/rtx_asset_data_manager.cpp:157-159`). Parsing is gli's DDS reader with DX10-header support (`:117-175`), so BC1/BC3/BC4/BC5/BC6H/BC7 and uncompressed DXGI formats are accepted as far as gli maps them.
- Unsupported formats are rejected loudly, not silently converted: if the format lacks `VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT` or `TRANSFER_DST_BIT`, Remix logs `Ignoring replacement texture with unsupported format [<fmt>]: <file>` and returns no texture (`rtx_texture_manager.cpp:1541-1548`). So the accepted set is device-driven; the exact BCn list is UNVERIFIED beyond "whatever the GPU reports sampled+transfer-dst".
- Oversized assets: if the whole asset exceeds the staging budget, Remix logs "doesn't fit into STAGING memory for streaming … Forcing synchronous upload, disabling texture streaming" (`:1494-1514`).
- Sky textures: official format is BC6H `.s.rtex.dds` with a full mip chain, plus `rtx.skyForceHDR=True` (`docs:docs/howto/learning-ingestion.html#skybox-textures`).

---

## 7. Shutdown hangs

- What `remixapi_Shutdown` does, in order (`LOCAL:rtx_remix_api.cpp:1726-1753`): clear the external presenter's present tasks → `g_dxvkDeviceNative = nullptr` → **force `Release()` the D3D9 device in a loop until refcount 0** → same for the `IDirect3D9Ex` → `dxvk::sentry::shutdown()`. It joins no thread itself; all waits happen inside the destructors that the forced releases run. (The deep thread-by-thread analysis already exists in `analysis/replay/research-2026-11-13/remix_exit_path.md`; its line numbers are from a slightly earlier snapshot — the function body quoted there matches `:1726-1753` here.)
- The documented client sequence is `remixapi_lib_shutdownAndUnloadRemixDll` = `Shutdown()` then `FreeLibrary(remixDll)` (`remix_c.h:994-1012`).
- **No public issue tracker**: `NVIDIAGameWorks/dxvk-remix` has `has_issues = false` (verified via `https://api.github.com/repos/NVIDIAGameWorks/dxvk-remix`; the `/issues` endpoint returns only pull requests). A search of PRs for shutdown/hang/deadlock returns exactly two shutdown-adjacent changes: PR #138 "Filter log level at emitMsg entry to avoid locale-facet UAF on shutdown" (closed, bridge logger) and PR #144 "Guard repeated WndProc setup and ImGui dispatch" (open). **There is no community record of an API-client teardown deadlock; the exit hang is our bug to characterise.** The release notes/changelog (`docs:docs/changelog/remix-releasenotes.html`, `remix-full-changelog.html`) contain no runtime "hang on exit" entry.
- Ordering rules that follow from the source, for an API client:
  1. stop calling `Present`/`DrawInstance` and drain in-flight frame tasks first (the presenter's tasks are only cleared, not waited on, `:1727-1729`);
  2. `DestroyMaterial` / `DestroyMesh` / `DestroyLight` every handle while the device still exists — handles are bare pointers cast from the caller's `hash` (`LOCAL:rtx_remix_api.cpp:898-905`, `1172-1178`) and are resolved against device-owned tables (`accessExternalMaterial`, `accessExternalMesh`), so destroying them after `Shutdown` touches released state;
  3. clear the camera medium (`SetCameraMediumMaterial(nullptr)`), which holds a `const MaterialData*` into the external material table (`LOCAL:rtx_remix_api.cpp:1124-1140`);
  4. `Shutdown()`, then `FreeLibrary`;
  5. expect no further Remix log lines from other threads after `Shutdown` — every remaining owner is force-released, which is exactly how a hang turns into "log stops here".

---

## 8. Option-key cross-check table (leaf name in `RTX_OPTIONS_THIS_BUILD.txt` → real key)

Only the ones a plan for E1/W1/W3/W4/W5 would touch. `present` = found in `RTX_OPTIONS_THIS_BUILD.txt`; everything else from `RtxOptions.md`/source.

| real key | leaf present | default | source |
| --- | --- | --- | --- |
| `rtx.particles.enable` | **no** (`enable` absent — list is not exhaustive) | true | `rtx_particle_system.h:180` |
| `rtx.particles.globalPreset.spawnRatePerSecond` | yes | 100 | `rtx_particle_system.h:188` |
| `rtx.particles.globalPreset.numberOfParticlesPerMaterial` | yes | 10000 | `:190` |
| `rtx.particleTextures` / `rtx.particleEmitterTextures` / `rtx.beamTextures` | yes / yes / yes | empty | `rtx_options.h:211,296,222` |
| `rtx.particleSoftnessFactor` | yes | 0.05 | `rtx_options.h:939` |
| `rtx.enableEmissiveBlendModeTranslation` | yes | true | `rtx_options.h:935` |
| `rtx.enableEmissiveBlendEmissiveOverride` | yes | true | `rtx_options.h:936` |
| `rtx.emissiveBlendOverrideEmissiveIntensity` | yes | 0.2 | `rtx_options.h:937` |
| `rtx.emissiveIntensity` | yes | 1 | `RtxOptions.md:225` |
| `rtx.enableSeparateUnorderedApproximations` | yes | true | `rtx_options.h:703` |
| `rtx.enableUnorderedEmissiveParticlesInIndirectRays` | yes | false | `rtx_options.h:860` |
| `rtx.wboitEnabled` | yes (`wboitEnabled`) | true | `rtx_options.h:947` |
| `rtx.neeCache.approximateParticleLighting` | yes | true | `rtx_nee_cache.h:66` |
| `rtx.lightConverter` | yes (`lightConverter`) | empty | `rtx_options.h:209` |
| `rtx.skyBrightness` / `skyForceHDR` / `skyProbeSide` / `skyUseProbeForPrimaryRays` | yes | 1 / false / 1024 / false | `rtx_options.h:1236-1249` |
| `rtx.animatedWaterTextures` | yes | empty | `rtx_options.h:259` |
| `rtx.opaqueMaterial.layeredWaterNormalEnable` | yes | true | `material_args.h:97` |
| `rtx.translucentMaterial.animatedWaterEnable` | yes | true | `material_args.h:150` |
| `rtx.rayreconstruction.invalidateHistoryForAnimatedWater` | yes | false | `rtx_ray_reconstruction.h:77` |
| `rtx.enableDirectTranslucentShadows` / `enableIndirectTranslucentShadows` | yes | false | `RtxOptions.md:239,248` |
| `rtx.volumetrics.enableTranslucentShadows` | yes | false | `RtxOptions.md:940` |
| `rtx.rayPortalEnabled` | yes | false | `RtxOptions.md:633` |

---

## Open questions

1. **Is 0ba9973 the build on the laptop?** The log says `remix-main+5a7eec84` (`remix.log:6`), the repo doc says 0ba9973 is "remix-1.6.1 source". Determine: on the laptop, run the game once and grep `remix.log` for `DXVK_Remix:` and compare with the sibling commit; or dump the DLL's version string next to `checks/install_live_dll.py`'s hash pin. Anything below that depends on a version gate (`s_apiVersion >= REMIXAPI_VERSION_MAKE(x,y,z)`, `LOCAL:rtx_remix_api.cpp:398,401,436,860`) should be checked against the header the proxy is compiled with (`analysis/runtime/remix-probe/sample/include/remix/remix_c.h`, also 0.6.6).
2. **Does NieR's effect geometry survive `kEmissive` at all?** The blend factors NieR uses for its particle/distortion shaders are not in this report (they are in the camp/desert captures). Determine: run the proxy's shader table on a capture (`remix: shader ... effect=` counts already exist) and print each effect draw's `srcColor/dstColor/colorBlendOp` + target; classify against §1.1's table. This is the input the E1 decision needs.
3. **`rtx.lightConverter` on API material hashes** — UNVERIFIED. Determine: set the hash of one API material in `rtx.lightConverter` and watch for the "[Light Converter]" / effect-light creation log line plus an extra sphere light in the Remix UI.
4. **`REMIXAPI_INSTANCE_CATEGORY_BIT_HAIR_CARDS` runtime effect** — not traced. Determine: grep `InstanceCategories::HairCards` at 0ba9973 and read the consumer.
5. **Exact accepted DDS format list** — device-driven check only. Determine: try BC1/BC3/BC5/BC7 sRGB + RGBA8 on the laptop and read for "Ignoring replacement texture with unsupported format".
6. **Why the exit hang needs ptrace** (`PLAN` C2) is unchanged by this research; nothing online documents it because the upstream tracker is closed.

---

## Recommended steps for the plan

1. **Re-specify W1 (sky) before any code is written.** In `analysis/PLAN_2026-11-14.md`, replace "the sky is not a flat plate" with: a sky is *only* achievable through `remixapi_LightInfoDomeEXT` (equirect DDS + `remixapi_LightInfo.radiance`) and/or emissive geometry; `REMIXAPI_INSTANCE_CATEGORY_BIT_SKY`, `rtx.skyBoxTextures`, `rtx.skyAutoDetect`, the sky probe and the sky matte are dead for an API client (`rtx_instance_manager.cpp:1047-1051`, `rtx_context.cpp:1049`). Check: a `checks/test_*.py` gate that submits a SKY-category instance and asserts it is *not* visible in the Remix frame but *is* counted as hidden (use the fake runtime to capture the call, then a laptop frame to confirm invisibility).
2. **Add a gate first for `DomeLight` end-to-end on the fake runtime**: `remixapi_CreateLight` with `remixapi_LightInfoDomeEXT` + `sType`/`pNext` chain, asserting the handle is non-null and non-zero hash, and that sampling code is reached only after the texture resolves. File: new `checks/test_dome_light.py` beside `checks/remix_live_fake_runtime.cpp`; the fake runtime already fakes `remixapi_Interface` members.
3. **Generate the dome-light panorama offline**: 2048x1024 (or 1024x512) lat-long DDS, BC6H HDR, full mip chain, laid out per `math.slangh:216-221`; verify with a script that samples the DDS at known directions (+Y = u 0.5, v 0 top) and compares to the intended sky colours. Put the generator in `analysis/tools/` and the check in `analysis/checks/`. Then A/B `radiance` and `rtx.skyBrightness` against the game's frame for the same camera, per W1's "not a flat plate" criterion.
4. **E1 step 0 (data, no code)**: extend the shader table the proxy already logs so every draw in the camp/desert captures prints `effect=<name> blend=<src,dst,op> target=<rt> count=<n>`; classify each against the §1.1 table and write the result into the plan next to E1. Nothing else in E1 is decidable before this list exists.
5. **E1 step 1 (cheapest visual win)**: put back the effect draws (`NIER_REMIX_LIVE_EFFECTS=1` path) with `useDrawCallAlphaState=1` and pass NieR's real blend factors through `remixapi_InstanceInfoBlendEXT`, plus `categoryFlags |= PARTICLE` for the billboard/smoke shaders. Gate: a `checks/test_*.py` that asserts (a) a ONE/ONE draw reaches Remix with blend factors ONE,ONE and the instance carries the PARTICLE bit, and (b) the old defect — solid geometry — is impossible because the fake runtime records `blendType=kEmissive`. Then one laptop frame in the camp with smoke visible, compared to the game's frame.
6. **E1 step 2 (per-effect brightness)**: for the effects that came out too dim or too bright, switch those materials to the explicit route (`useDrawCallAlphaState=0`, `blendType_value` from the §1.1 table, `emissiveIntensity` authored per material) because the 0.2 global override only applies on the draw-call route (`rtx_instance_manager.cpp:1146-1153`). Gate: fake-runtime test that the emitted material has `useLegacyAlphaState=false` and the authored intensity.
7. **E1 step 3 (lighting)**: set `rtx.enableUnorderedEmissiveParticlesInIndirectRays=True` for combat and confirm the sparks appear in reflections; measure the frame-time delta on the laptop and record both numbers next to E1. If emissive particles still do not light the ground, try `rtx.lightConverter` on one API material hash (open question 3) before writing any new renderer code.
8. **E1 step 4 (record the dead ends)**: add a short "cannot be done" table to the plan — screen-space distortion/heat haze (no API field), exact soft-particle depth fade (§1.2 is a ray-length fade), per-particle lighting. This stops a future session from re-deriving them.
9. **W3 (water)**: implement it as a translucent material with `thinWallThickness_hasvalue=1` (thin-walled, no refraction) + `transmittanceColor`/`transmittanceMeasurementDistance`, `categoryFlags |= ANIMATED_WATER`, and turn on `rtx.translucentMaterial.animatedWaterEnable` with authored `animatedWaterPrimaryNormalMotion`/`SecondaryNormalMotion`. Gate: fake-runtime test asserting the translucent EXT fields and the category bit; then a laptop frame against `frame_67078468` with the same tolerance scheme used for the camp.
10. **W4 (emission/night)**: no new mechanism needed — `emissiveIntensity > 0` on the material plus `emissiveTexture` as a DDS **with mips** (a 512² single-mip emissive texture will trip the suboptimal warning and alias, §6). Add the assertion to the existing material gate: any texture path handed to Remix must be a DDS with `mipLevels >= floor(log2(max(w,h)))+1`, checked in `analysis/checks/` by parsing the DDS header (`rtx_asset_data_manager.cpp:157-159` is the reference behaviour).
11. **W5 (hair)**: do not plan on a tangent/anisotropy map — it is read and unused (`opaque_surface_material_interaction.slangh:596,620`; `:836` "Todo"). Plan the look A/B on `remixapi_MaterialInfoOpaqueEXT.anisotropy` (scalar) + `remixapi_MaterialInfoOpaqueSubsurfaceEXT` (transmittance colour/distance) only, and give the user the A/B sheet in the plan's own format.
12. **C2 (exit hang)**: add to the plan that nothing upstream documents this (`has_issues=false`; only PRs #138/#144 touch shutdown-adjacent paths), so the item needs local evidence: a `checks/` gate that logs the last line written before the hang plus the ordered teardown list in §7 (destroy handles → clear medium → `Shutdown` → `FreeLibrary`), and a minimum-repro probe DLL that starts Remix, draws one instance, and exits — bisecting which step hangs requires no ptrace at first, only stderr timestamps around each API call.
13. **Fix the plan's citations**: `remix_c.h:786` for `SetConfigVariable` is wrong for both copies we hold (typedef at 724; interface member at 810/816). Cite by name. Also correct `analysis/FO4_REMIX_NOTES.md`'s `rtx.atmosphere.sunElevation/sunRotation` note — those options do not exist in this runtime; the sun is a `remixapi_LightInfoDistantEXT`.
