# NV-RTX sky / effects follow-up (2026-11-15)

Method: shallow clones to /tmp (not the repo). Refs read:
- `Kim2091/New-Vegas-RTX` default branch, HEAD `1367eac` (1.2.0). Compare `b1e982f...HEAD` = 6 commits.
- `Kim2091/dxvk-remix` `fnv/main`, HEAD `2a5f15a` (1.2.0). Compare `925d7ab...fnv/main` = 4 commits.
- `RemixProjGroup/dxvk-remix` `remix-plus-2.0.0`, HEAD `268fb5b` ("Remix Plus v2").
- `NVIDIAGameWorks/dxvk-remix` `main`, HEAD `2b46bed` (2026-11-14), used as the upstream reference.

Tags: **DIRECT** = read in source at the cited path and line. **INFERRED** = my reasoning from the excerpts. Paths below are relative to each repo root. The NV-RTX URL is `https://github.com/Kim2091/New-Vegas-RTX/blob/1367eac/<path>` (same for the others at their HEAD).

Correction to the parent notes: the repo HEAD is now `1367eac`, not `b1e982f`, and the fork is `2a5f15a`, not `925d7ab`. Both are only as of the fetch time.

---

## Q1. Sky: how FNV gets its sky into Remix

**Summary.** NV-RTX does not submit any sky geometry. It drops every draw with the game's sky shader, and the Remix runtime's NUMOS sky (fork-only) draws the whole sky. The wrapper's only jobs are to report the game's sun, moon, weather and camera to NUMOS through `SetConfigVariable`. NUMOS takes no game sky colour or exposure values. Nothing in the wrapper reads sky colours, exposure or fog colour.

1. **DIRECT: sky draws are dropped.** `docs/fnv-api-only.md:5-9`:
   > "Draws with the game's sky shader (SKIP_GAME_SKY) and the near land LOD (PASS_LOD_SHADER) are dropped: the NUMOS sky draws the sky, and the far LOD and the terrain cover the land."

   `src/comp/modules/renderer.cpp:1120-1125`:
   ```cpp
   else if (game::is_sky())
   {
       // NUMOS draws the whole sky: atmosphere, clouds, sun, moon and stars.
       // Every draw with the game's sky shader is dropped, whatever mesh a
       // mod puts under the sky, so none of it becomes a dome in the scene.
       route_tag(diag, "SKIP_GAME_SKY");
   ```
   The same drop is at `renderer.cpp:867-870` (the indexed path).

2. **DIRECT: the game-to-NUMOS channel is `SetConfigVariable` on `rtx.atmosphere.*`, `rtx.weather.*` and `rtx.skyProvider.*`.**
   - `src/comp/comp.cpp:53-61`: `rtx.atmosphere.sunElevation`, `sunRotation`, `moon0.enabled`, `moon0.elevation`, `moon0.rotation`, `moon0.phase`, `useCameraWorldOverride`, `cameraWorldOverride`.
   - `src/comp/game/weather.cpp:110-112`: `rtx.weather.gameWeather`, `rtx.weather.gameWeatherOutgoing`, `rtx.weather.gameWeatherBlend`.
   - `src/comp/game/weather.hpp:1-27` describes the flow. The class comes from the record's flags, thunder frequency, day fog far and wind, mapped by the thresholds in `[Weather]`.
   - **Gap:** NV-RTX never pushes `rtx.skyProvider.worldChangeCount`. The fork doc says to bump it on a save load, interior or worldspace change (`docs/RemixSkyAPI.md:30-31` table row). `grep -rn worldChangeCount src` returned nothing.

3. **DIRECT: sun.** `src/comp/comp.cpp:86-122` `update_sun()`. It calls `game::try_get_sun_orientation(elevation, rotation, &hour, &night)` and pushes the result as `sunElevation`/`sunRotation` with `%.2f`. The default when the cycle is off is `15.00`/`0.00`. The sun's direction comes from the live scene graph (`src/comp/game/structs.hpp:96` `SUN_ROOT_OFF = 0x04`, and the arc maths in `structs.hpp:61-70`). Game hour is `sky+0xEC` (`structs.hpp:95`, `SKY_GAME_HOUR_OFF`). The sunrise and sunset horizon crossings come from the climate times (`structs.hpp:100`).

4. **DIRECT: moon.** `src/comp/comp.cpp:124-` `update_moon()` pushes `moon0.*`. The moon's direction is read from the billboard chain (`structs.hpp:17-30`, the chain TES → manager `+0x68` → `+0x30` → `+0x10` → parent `+0x18`), and the direction is `(billboard.T - parent.T)` normalised. `structs.hpp:186` says it "Reads the moon's rendered direction from the live scene graph".

5. **DIRECT: no sky colour, exposure, fog colour or brightness is pushed.** A repo-wide grep for `exposure`, `skyColor`, `sky_color`, `fogColor`, `rtx.fog`, `skyBrightness` and `skyMode` finds nothing in NV-RTX (the only hits are `ambient` in lighting code, which is unrelated). `remix-comp.ini` has no sky-mode key, so the runtime default applies.

6. **DIRECT: the sky-mode setting is not in the repo.** The fork default is `SkyboxRasterization` (`fork src/dxvk/rtx_render/rtx_options.h:1995-1996`, see below). NV-RTX never sets `rtx.skyMode`. **INFERRED:** the NUMOS path (`skyMode = 1`) needs to be set in the user's `rtx.conf` or the shipped Remix Plus package. I could not confirm this from the repo, so it is an open question (see Risks).

7. **DIRECT: NUMOS mode and its config (fork).**
   - `src/dxvk/rtx_render/rtx_options.h:177-180`: `enum class SkyMode { SkyboxRasterization = 0, Numos = 1 }`.
   - `rtx_options.h:1995-1997`: `RTX_OPTION("rtx", SkyMode, skyMode, SkyMode::SkyboxRasterization, "... 1: Numos renders a physically based sky and atmosphere.")`.
   - `docs/RemixSkyAPI.md:3-6` says NUMOS is "the standalone NUMOS library (`submodules/numos`)"; there is no dedicated sky function in the remix API, so everything is `SetConfigVariable`.
   - `docs/RemixSkyAPI.md:18-47` lists the keys an integration typically pushes. The relevant rows are `rtx.skyMode`, `sunElevation`/`sunRotation`, `unitsPerMeter`, `worldScale`, `groundLevelAuto`, `useCameraWorldOverride`/`cameraWorldOverride`, `rtx.skyProvider.worldChangeCount` and `moon<N>.*`. Quote: "While a weather preset shows, the keys it lists override the user's values (section 2)".
   - `src/dxvk/rtx_render/rtx_numos_weather.h:1-40` describes the weather preset files (`rtx.weather.presetDirectory`, `weather.bindings`, the `x<value>` multiplier syntax, `rtx.weather.followGame`).
   - Blend for weather: `rtx.weather.gameWeatherBlend` < 0 means the runtime blends over the preset transition time (`rtx_numos_weather.h:21-22`).

8. **DIRECT: upstream SKY category and sky-camera rasterization exist.** `NVIDIAGameWorks/dxvk-remix` (`nvg`) `src/dxvk/rtx_render/rtx_remix_api.cpp:678`: `if (flags & REMIXAPI_INSTANCE_CATEGORY_BIT_SKY) { result.set(InstanceCategories::Sky); }`. `rtx_remix_api.cpp:515` and `:669-670`: `if (flags & REMIXAPI_INSTANCE_CATEGORY_BIT_SKY) return CameraType::Sky;`. `rtx_camera_manager.cpp:51`: `input.testCategoryFlags(InstanceCategories::Sky) ? CameraType::Sky : CameraType::Unknown`. `nvg src/dxvk/rtx_render/rtx_types.cpp:420`: `setCategory(InstanceCategories::Sky, lookupHash(RtxOptions::skyBoxTextures(), textureHash));` and `:428` (the geometry list). `nvg src/dxvk/rtx_render/rtx_sky.h:32`: `static bool isSkyboxQuad(...)`. `nvg rtx_options.h:1247-1253`: `skyBrightness` (default 1.f), `skyForceHDR` (false), `skyAutoDetect` (None).

9. **DIRECT: the upstream sky path has no NUMOS and no `skyMode`.** `grep -rli numos nvg` returns 0 files. `grep skyMode nvg/src/dxvk/rtx_render/rtx_options.h` returns nothing. Upstream therefore always rasterizes the sky-camera draws to a sky cube (`rtx_sky.h`, `rasterizeSky`, `tryHandleSky`).

10. **DIRECT: the fork's `skyMode` changes what a SKY draw does.** `fork src/dxvk/rtx_render/rtx_sky.h:177-181`:
    ```cpp
    bool dxvk::RtxContext::rasterizeSkyDraw(...) {
      if (RtxOptions::skyMode() == SkyMode::Numos) {
        return true;  // NUMOS draws no game sky; tryHandleSky skips these draws too
      }
    ```
    and `rtx_sky.h:224-229` (`tryHandleSky`):
    ```cpp
    // Skip all sky geometry when using Numos mode
    if (originalParams && originalDrawCallState && originalDrawCallState->cameraType == CameraType::Sky &&
        RtxOptions::skyMode() == SkyMode::Numos) {
      return TryHandleSkyResult::SkipSubmit;
    ```
    So in NUMOS mode, **any SKY-category dome is skipped**. The fork's `d3d9_frontend.cpp:1365-1367` also skips the NUMOS sky draws on the D3D9 route.

11. **DIRECT: the fork's NUMOS radiance is pre-exposed.** `fork src/dxvk/rtx_render/rtx_numos.cpp:423-425`: "NUMOS's radiance carries its own pre-exposure R; the renderer's is P (rtx_pre_exposure.h)." and `:425` `constants.skyRadianceUnscale = PreExposure::get() / radianceScale;`. `:535`: `skyRadianceScale = (o && o->radianceScale > 0.0f ? o->radianceScale : 1.0f) * PreExposure::inverse();`. `fork src/dxvk/rtx_render/rtx_pre_exposure.h:1-16`: radiance is multiplied by a power-of-two P that follows the exposure, and every meter/tonemapper divides it out. **INFERRED:** we do not set `radianceScale` anywhere, so the sky brightness is NUMOS's default. `rtx_numos_ui.cpp:358`: "Night Precision (Pre-exposure)" is a NUMOS dev-menu setting.

**Answer for our wrapper.** Our plan (submit NieR's sky dome with `REMIXAPI_INSTANCE_CATEGORY_BIT_SKY` plus a fixed texture) only works on **skyMode 0** (SkyboxRasterization). **It cannot coexist with NUMOS in the fork.** NV-RTX's approach (drop sky, use NUMOS) needs skyMode 1 and the fork.

**Mapping to D3D.** There is no game sky colour or exposure mapping in NV-RTX. The game's weather id and blend, the sun and moon angles, the camera world position and the world-change signal are the only game values fed to NUMOS.

---

## Q2. Particles, smoke, fire, sparks, additive/alpha, distortion

**Summary.** NV-RTX does **not** use `remixapi_InstanceInfoParticleSystemEXT`. It submits the quads of each particle system as **ordinary traced geometry** with the `PARTICLE` category flag and an `InstanceInfoBlendEXT` copied from the D3D9 state. The runtime does the additive/alpha work. Refused draws are dropped, not rasterized. Distortion is not handled anywhere.

1. **DIRECT: the particle path.** `src/comp/game/api_particles.cpp:1-6` (header, "Flipbook particles through the Remix API. A refused draw is not drawn (counted per reason); only the Pip-Boy's own draws keep the renderer's D3D9 route."). Taken draws, lines 11-31: `NOLIGHT017/019` particle draws (`ParticleSubTex`), and the `NoLightUv` effect particle systems (fire, embers) from a dynamic VB. Quads are built on the CPU by the engine and replayed by `vs_expand::describe_for_api`.

2. **DIRECT: the mesh and the instance.** `api_particles.cpp:52-60`: one capacity mesh per system, re-sent every frame under the same hash with `MeshInfoRefreshGeometryEXT`. Quote: "Drawn with one DrawInstance (PARTICLE, no opacity micromaps, double sided, the draw's own InstanceInfoBlendEXT: the runtime handles additive and multiplicative blends as it does for the D3D9 draw)." `api_particles.cpp:567-570`:
   ```cpp
   ii.pNext = &blend;
   ii.categoryFlags = mat.categories | REMIXAPI_INSTANCE_CATEGORY_BIT_PARTICLE |
       REMIXAPI_INSTANCE_CATEGORY_BIT_IGNORE_OPACITY_MICROMAP;
   if (vm) ii.categoryFlags |= api_camera::view_model_categories(dev);
   ```
   **DIRECT:** `api_particles.cpp:446-449` builds `remixapi_InstanceInfoBlendEXT blend;` from the D3D9 state via `material::draw_state_blend(dev, vertex_color, mat.alpha_dropped, blend, reject)`.

3. **DIRECT: the particle-system extension is unused.** `grep -n InstanceInfoParticleSystem nvr/src` finds nothing. `api_particles.cpp` mentions `ParticleSystem` three times, all in comments or as the engine's `NiParticleSystem` name (lines 37, 42, 121). The struct is in the header only: `nvr deps/bridge_api/remix/remix_c.h:700-742` (`remixapi_InstanceInfoParticleSystemEXT`, with `maxNumParticles`, `minTimeToLive`, `spawnRatePerSecond`, `billboardType`, `minColor`/`maxColor` animated floats, `attractorPosition`, `gravityForce`, `dragCoefficient`, etc.).

4. **DIRECT: the blend mapping.** `src/comp/game/api_material.cpp:347-410`, `draw_state_blend()`:
   - `:350-356`: `out = vertex_color_blend()`; the tint and `tFactor` from `D3DRS_TEXTUREFACTOR`; `writeMask` from `COLORWRITEENABLE`; `isVertexColorBakedLighting = 0` for particles and unlit FX. Comment: "the vertex colour is a real colour (a tint, a fade), not baked lighting the runtime should normalise away, as the runtime's own particle system treats it."
   - `:357-368`: alpha test maps `D3DCMPFUNC` to `VkCompareOp` via `func - 1u` and `alphaTestReferenceValue` from `D3DRS_ALPHAREF`.
   - `:374-404`: `D3DRS_SRCBLEND`/`DESTBLEND`/`BLENDOP` (and the separate alpha ones) go through `vk_blend_factor()` / `vk_blend_op()`, which are the Vulkan enum values (line 307-313: `D3DBLEND_ONE → 1`, etc.). The result goes into `alphaBlendEnabled`, `srcColorBlendFactor`, `dstColorBlendFactor`, `colorBlendOp`, `srcAlphaBlendFactor`, `dstAlphaBlendFactor`, `alphaBlendOp`. A non-mappable factor or op is **refused** with reason "blend factor / op" (`:380-384`).
   - `api_material.cpp:405-410` `draw_is_additive()`: additive if `DESTBLEND == ONE` and `SRCBLEND == ONE or SRCALPHA`.
   - `api_material.cpp:412-418` `translucent_card()`: SRC_ALPHA/ONE_MINUS_SRC_ALPHA pairs.

5. **DIRECT: fork and upstream both parse the blend and particle extensions.** `fork src/dxvk/rtx_render/rtx_remix_api.cpp:1061` `toLegacyBlendDesc(...)`, `:1108` `pnext::find<remixapi_InstanceInfoBlendEXT>`. `:954` and `:1013` `toRtParticleDesc(...)` for both the legacy and the new struct. `:877`/`:880` (in `nvg`) `pnext::find<remixapi_InstanceInfoParticleSystemEXT>` and the legacy one. The struct is identical in the fork (`fork public/include/remix/remix_c.h:717-759`) and in upstream (`nvg public/include/remix/remix_c.h:573-615`), field for field (the diff was empty).

6. **DIRECT: unlit emissive glow.** `api_particles.cpp:35` and `:385-392`: the particle texture is also its own glow at `UnlitEmissiveIntensity` (tinted by `MaterialColor`, `ApiGlowTint` permitting), unless the draw blends additively.

7. **DIRECT: refusal drops, it does not rasterize.** `api_particles.cpp:3-4`: "A refused draw is not drawn (counted per reason)". `api_particles.cpp:81-86` (refusal reasons): `Refuse(Reason::Blend, reject)`, and `:427` ("create" path: `g_retry_at`, `take_build_budget`, `Reason::Budget`, `Reason::Retry`).

8. **DIRECT: what reaches the D3D9 route.** `docs/fnv-api-only.md:1-15` lists the D3D9 survivors: HUD/UI/menus (`PASS_2D`, `POSITIONT`), offscreen passes, draws without view/projection, and `PASS_NO_DIFFUSE_ROLE`. Also `rtx.uiTextures` (screen UI) and the Pip-Boy's own draws. `docs/fnv-api-only.md:12-22`.

9. **DIRECT: distortion is not handled.** `grep -rniI "distort|heat haze|refraction" nvr/src nvr/docs` finds only `RefractionMap` in the shader reflection code (`src/shared/common/ps_reflect.hpp:54,67,320`) and the water refraction ini key. **INFERRED:** FNV heat-shimmer or distortion passes are not special-cased. They either go through as an ordinary alpha/additive particle draw with a blend, or fall into a refusal. I could not confirm which.

10. **DIRECT: the HUD/UI composite and tonemapping.** `docs/fnv-api-only.md:275-285` (the HUD text "so sun and sky don't wash out the background behind the text" line, around 281). The screen UI goes through `DrawScreenOverlay`/D3D9 and is not tone mapped by the runtime, which is what the `rtx.uiTextures` list is for (`api_rtxconf.cpp:55-95`, `uiTextures` is `0u`, i.e. D3D9-only). **INFERRED:** effects traced into the scene are tone mapped and pre-exposed with the scene (`fork rtx_pre_exposure.h:1-16`, "every radiance source multiplies by P"), so additive effects follow the same exposure as the world. Not verified in code.

11. **DIRECT: fork changes that touch the tone curve (possible effect on glows).** `fork CHANGELOG`/`src/dxvk/shaders/rtx/pass/tonemap/tonemapping_inverse_tonemapping.comp.slang` (2a5f15a..fnv/main, commit `d8d9b8d`): `originalToneMapped = saturate(curveOutput)`, and inverse only when `curveOutput >= 0`. Quote: "a colour grade could send NaN pixels into DLSS-NR". **INFERRED:** it does not change effect blending, but it changes the inverse-tonemap path for HDR pixels that the colour grade pushes below zero.

---

## Q3. New commits since b1e982f / 925d7ab

### NV-RTX (`b1e982f...1367eac`, 6 commits, 75 files)
- `f40296c` 2026-10-30 `1.2.0-rc4: fix distant tree instance lookup`
- `af63b85` 2026-11-01 `1.2.0-rc5: name static meshes per diffuse and by vertex colours`
- `108a38f` 2026-11-02 `1.2.0-rc6 prep: engine audit fixes, UI classification and FaceGen maps`
- `3942ac5` 2026-11-03 `1.2.0-rc6: trace the Pip-Boy at the game's Pip-Boy FOV, no self-glow on tree leaves`
- `16c4bf5` 2026-11-04 `1.2.0-rc7: hide the game's light glow cards, setup help dialogs, faster first start`
- `1367eac` 2026-11-09 `1.2.0: the GECK gets the system d3d9, menu-exit frames are path traced`

Relevant files (DIRECT, from the compare API):
- **Sky:** no `weather.cpp`/`comp.cpp`/`structs.hpp` change in this range. `src/comp/game/api_particles.cpp` is not a sky file. **No sky change.**
- **Effects:** `src/comp/game/api_particles.cpp` (62 lines): adds `D3DPT_TRIANGLESTRIP` support, `strip_to_quads()` with `kStripPattern = { 0,1,2,2,1,3 }`, for BSStripParticleSystem ribbons. Rejects other topologies. `src/comp/game/api_unlit.cpp` (23 lines): `Reason::LightCard`, `scene_statics::light_card(dev)` (additive glow, flare and light-beam cards on placed STATs are refused), and tree leaves (`textures\trees\`) get no glow.
- **Light cards:** `src/comp/game/scene_statics.cpp` (163 lines).
- **HUD/UI:** `src/comp/game/ui_boundary.cpp` (21) and `.hpp` (24), `src/comp/game/screen_space.cpp` (4) and `.hpp` (9), `note_applied_projection(proj, bool viewmodel)`. `src/comp/game/pipboy_cursor.cpp` (289) and `.hpp` (62) are **renamed** in this range.
- **D3D9 host:** `src/comp/d3d9_proxy.cpp` (88), `src/comp/modules/d3d9ex.cpp` (3), `src/comp/modules/renderer.cpp` (13).
- **Performance:** `src/comp/game/tex_archive.cpp` (143), `tex_pool.cpp` (83), `api_asset_keys.cpp` (98), `shared_mesh_keys.hpp` (new, 78).

### Fork (`925d7ab...fnv/main`, 4 commits, 33 files)
- `e2da17e` 2026-11-01 `1.2.0-rc5: replacement toggle and failed mip read fixes`
- `d8d9b8d` 2026-11-02 `1.2.0-rc6 prep: DLSS-NR NaN fix and a shorter problem section`
- `a186b64` 2026-11-04 `1.2.0-rc7: fast NUMOS cloud compiles, pipeline cache kept across updates, SER SHARC update`
- `2a5f15a` 2026-11-09 `1.2.0: no crash or hang when the window is minimized during a present`

Relevant files:
- **Sky (NUMOS):** `src/dxvk/rtx_render/rtx_numos.cpp` (122 lines), `rtx_numos.h` (11), `rtx_numos_gpu.cpp` (8), `rtx_numos_gpu.h` (11). Fast cloud compiles: NUMOS `cloud_render` was 80-90 s to compile in the driver, now split into single-call cloud march/sample steps. The prewarm now compiles only the one `cloud_render` variant that `rtx.atmosphere.cloudPerformancePreset` selects, and the wait screen no longer waits for NUMOS shaders. **Performance-relevant.**
- **Tone mapping:** `src/dxvk/shaders/rtx/pass/tonemap/tonemapping_inverse_tonemapping.comp.slang` (10 lines) and `tonemapping_fast_tonemapping.comp.slang` (4 lines). DLSS-NR NaN fix: negative matrix terms can send a channel below zero.
- **Effects:** no particle or blend change in the fork range.
- **HUD/UI composite:** `src/dxvk/imgui/rtx_fault_notice.cpp` (284) and `.h` (24), `src/dxvk/imgui/rtx_user_menu.cpp` (5). Not a composite change.
- **D3D9 host:** `src/d3d9/d3d9_swapchain.cpp` (19). A window with a zero-sized client area gets no swap chain. A frame that is not presented still signals its frame latency. Fixes the minimized-window hang.
- **Performance:** `src/dxvk/dxvk_pipecache.cpp` (35) and `.h` (12). The pipeline cache is checked only against GPU and driver, so it survives runtime updates. `rtx_texture_manager.cpp` (14), failed mip read no longer swaps in uninitialised memory. `rtx_retained_v2.cpp` (3), `rtx_scene_manager.cpp` (20).

### Upstream `NVIDIAGameWorks/dxvk-remix` `main` (`nvg`)
- Not compared since 925d7ab (not in the task's scope; the clone is the head as of 2026-11-14).
- Sky: `skyMode` absent. `skyBrightness`, `skyForceHDR`, `skyAutoDetect`, `skyReprojectToMainCameraSpace` present (`rtx_options.h:1247-1267`).
- Particles: `remixapi_InstanceInfoParticleSystemEXT` handled (`rtx_remix_api.cpp:766`, `:877`).
- Blend: `InstanceInfoBlendEXT` handled.

### RemixProjGroup `remix-plus-2.0.0` (`268fb5b`, "Remix Plus v2")
- Same structure as the fork: `rtx_numos*.cpp` (10 files), `rtx_options.h:177-180` (`SkyMode`), `:1877-1879` (`skyMode` default `SkyboxRasterization`).
- It is the release branch; I did not diff it against `fnv/main`.

---

## Architecture

**NV-RTX data flow for sky and effects:**
1. Every frame: `comp.cpp` `update_sun`/`update_moon` pushes `rtx.atmosphere.*` (`comp.cpp:53-61`, `86-` and `124-`). `weather.cpp` `update()` pushes `rtx.weather.gameWeather*` (`weather.cpp:110-112`, `279-320`). Both are `SetConfigVariable` calls. NUMOS (fork) draws the sky.
2. Sky-shader draws: `renderer.cpp:867-870`, `1120-1125` drop the draw. The fork (in NUMOS mode) skips sky-camera draws too (`rtx_sky.h:224-229`).
3. Particles: `api_particles.cpp` builds quads on the CPU, keeps one mesh per system with `MeshInfoRefreshGeometryEXT`, and submits a traced instance (`PARTICLE` category, `InstanceInfoBlendEXT`) (`:52-60`, `:446-449`, `:567-570`). A refused draw is dropped.
4. Blend: `draw_state_blend()` (`api_material.cpp:347-404`) maps the D3D9 blend and alpha state. An unmappable factor refuses the draw.
5. HUD/UI: D3D9 route (`fnv-api-only.md`), `rtx.uiTextures` D3D9-only (`api_rtxconf.cpp:55-95`).

**Upstream sky path (what we can use now):** SKY category → `CameraType::Sky` → sky cube rasterization (`rtx_remix_api.cpp:669-678`, `rtx_camera_manager.cpp:51`, `rtx_sky.h`). No NUMOS.

## Start Here

Open `NV-RTX/src/comp/modules/renderer.cpp` at 1120-1125 for the sky drop, and `NV-RTX/src/comp/comp.cpp` at 53-61 for the atmosphere keys. Then read the fork's `src/dxvk/rtx_render/rtx_sky.h` at 177-181 and 224-229. The fork's skyMode check decides whether our SKY dome survives at all.

## Usable on upstream now vs needs fork

**Usable on upstream now (DIRECT or INFERRED as marked):**
- SKY category submission and sky-camera rasterization (`nvg rtx_remix_api.cpp:678`, `:669-670`; `rtx_camera_manager.cpp:51`; `rtx_types.cpp:420-428`). This is our dome plan. Note that it only works while the fork's `skyMode` is 0, and upstream has no `skyMode` at all, so upstream always rasterizes.
- `skyBrightness` (`nvg rtx_options.h:1247`), `skyAutoDetect` (`:1253`) and `skyReprojectToMainCameraSpace` (`:1262`).
- `InstanceInfoParticleSystemEXT` (identical struct, handled at `nvg rtx_remix_api.cpp:766`, `:877`). NV-RTX does not use it; we need not either.
- `InstanceInfoBlendEXT` and the `PARTICLE` category flag (`api_particles.cpp:567-570`, `api_material.cpp:347-404`). The struct layout matches upstream.

**Needs fork (Remix Plus):**
- `rtx.skyMode = 1` (NUMOS) and everything under `rtx.atmosphere.*`, `rtx.weather.*`, `rtx.skyProvider.*` (`docs/RemixSkyAPI.md`, `rtx_numos*.cpp`). None of this exists on upstream.
- The game-driven sun/moon/weather/world-change signal into NUMOS (`comp.cpp:53-61`, `weather.cpp:110-112`).
- NUMOS pre-exposure (`rtx_numos.cpp:423-425`, `:535`). **Not verified** that upstream's pre-exposure matches, so treat as fork-only.
- The fork's fixed `d3d9_swapchain.cpp` minimized-window hang and `pipecache` change (performance; fork-only).

**Not usable on either (no implementation found):** game sky colour, exposure or fog-colour mapping. Distortion/refraction effects. Heat-shimmer effects.

## Risks and open questions
1. **Sky mode conflict (highest risk).** Our dome plan needs `skyMode = 0` (SkyboxRasterization). NV-RTX needs `skyMode = 1` (NUMOS), and in NUMOS mode the fork skips SKY-camera draws (`rtx_sky.h:224-229`). We cannot run both on one runtime. Decision needed before any sky work.
2. **Where `skyMode = 1` comes from.** NV-RTX never sets `rtx.skyMode` (grep empty). The shipped config or the user's `rtx.conf` must do it. Not confirmed in the repo.
3. **Sky dome transform.** Upstream rasterizes sky-camera geometry to the sky cube. **INFERRED:** the dome must be expressed in sky-camera space (no camera translation), but I did not read the upstream sky-camera transform code to confirm. Check `rtx_sky.h` and `rtx_camera_manager.cpp` before relying on it.
4. **Worldchange signal missing.** NV-RTX never bumps `rtx.skyProvider.worldChangeCount` (grep empty). Fork doc says NUMOS needs it on loads and worldspace changes (`docs/RemixSkyAPI.md:30-31`).
5. **Distortion and heat-shimmer.** No handling found in NV-RTX. Behaviour unknown (dropped or traced as an ordinary alpha draw).
6. **Repo HEAD drift.** The notes cited `b1e982f` / `925d7ab`. The current heads are `1367eac` and `2a5f15a`. The relevant sky and particle files did not change in those ranges (see Q3).
7. **Unverified:** the blend factor values `vk_blend_factor` produce (`api_material.cpp:307-313`) are the Vulkan enum numbers, which I checked only for the first few entries.

## Commands run (read-only, no repo edits)
- `git clone --depth 1` of NV-RTX, fork `fnv/main`, `RemixProjGroup remix-plus-2.0.0`, `NVIDIAGameWorks main` to `/tmp`.
- `curl` GitHub API `compare` for NV-RTX `b1e982f...HEAD` and fork `925d7ab...fnv/main`.
- `grep`/`sed` read-only on the clones and the repo `analysis/NEW_VEGAS_RTX_NOTES.md`.
- No build, no game run, no deployment, no repo writes except this report.

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Concise result in this report: Q1 sky (NUMOS, SKY category, skyMode conflict), Q2 effects (PARTICLE category plus InstanceInfoBlendEXT, no ParticleSystemEXT, distortion unhandled), Q3 commit deltas for NV-RTX (6) and fork (4), and a usable-on-upstream vs needs-fork list. Residual risks listed."
    }
  ],
  "changedFiles": [
    "/home/suraj/.pi/agent/sessions/--home-suraj-Projects-Nier-Automata-Rendering--/subagent-artifacts/outputs/623638fc-aec9-4cb9-8c4c-475178e8c68b/context.md"
  ],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "git clone --depth 1 (NV-RTX, fork fnv/main, RemixProjGroup remix-plus-2.0.0, NVIDIAGameWorks main) to /tmp; curl GitHub API compare; grep/sed read-only",
      "result": "passed",
      "summary": "Heads: NV-RTX 1367eac, fork 2a5f15a, RPG 268fb5b, NVG 2b46bed. Compare b1e982f...HEAD 6 commits, 925d7ab...fnv/main 4 commits."
    }
  ],
  "validationOutput": [
    "Sky: renderer.cpp:1120-1125 drops SKIP_GAME_SKY; comp.cpp:53-61 atmosphere keys; fork rtx_sky.h:177-181, 224-229 skip SKY draws in NUMOS mode."
  ],
  "residualRisks": [
    "skyMode conflict: dome plan needs skyMode 0; NUMOS needs 1 and skips SKY draws in the fork.",
    "Source of rtx.skyMode=1 for NV-RTX not confirmed.",
    "Dome sky-camera transform unverified (INFERRED).",
    "Distortion/heat-shimmer handling not found; behaviour unknown.",
    "Upstream not compared beyond the sky/particle/blend structs."
  ],
  "noStagedFiles": true,
  "diffSummary": "Research report only. No repo files changed; clones are in /tmp.",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "Output path: the task's Output section names .../subagent-artifacts/outputs/623638fc-.../context.md, which I wrote. The task text also named analysis/NEW_VEGAS_RTX_SKY_EFFECTS_2026-11-15.md in the repo; I did not write there because the output instruction says to ignore other output paths. Parent can copy it if wanted. The repo notes file was partly unreadable through the tool output, so I used the grep/sed excerpts for the parts I cited."
}
```
