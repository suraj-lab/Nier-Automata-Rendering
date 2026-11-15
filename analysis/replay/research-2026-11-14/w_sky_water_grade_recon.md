# Sky, grade for a second area, water, emission, hair — recon (2026-11-14)

Read-only recon for the rewrite of `analysis/PLAN_2026-11-14.md` items W1 (sky), W2 (grade), W3 (water), W4 (emission),
W5 (hair). Every claim carries `file:line`. `UNVERIFIED` marks what I could not check with the data in this repository.
Cites prefixed `FULL:` are the full Remix tree `analysis/runtime/src/dxvk-remix`; C API cites are
`analysis/runtime/remix-probe/sample/include/remix/remix_c.h` (referred to as `remix_c.h`).

Measured this session: the two laptop captures under `analysis/runtime/laptop-play-20261114/` (`frame_67279062` desert,
923 draws; `frame_67078468` water, 1,176 draws), and the camp capture
`/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_30632051` (read-only), through their
`capture.json`, `ps_cb_*.bin`, `textures/index.json` and the RDEF chunk of `shaders/ps_<hash>.dxbc`.

---

## 0. The five-line summary

1. **The sun is already game-driven; the sky is not.** Sun colour and direction come from the game's own PS CB2 and are
   re-created whenever they change (`checks/live_capture.h:2511-2517` → `checks/live_scene.h:555-562`). The dome light is a
   fixed DDS at fixed strength 2.0 (`checks/remix_live.cpp:269-277`, `checks/nscn_scene.h:212-230`).
2. **Sun constants differ per area, measured:** desert `(8, 7.2, 4.8)` / camp `(6, 5.1, 4.8)`; fog colour `2.937` /
   `6.208` (§2 table). So the light budget outdoors and indoors is different before any tone curve is applied.
3. **One grade cannot hold in both areas**, and the reason is measurable, not aesthetic: the same `colorBalance`
   1.0/0.89/0.70 times `saturation` 1.6 is applied to a desert frame lit by a 1:0.9:0.6 sun and a camp frame lit by
   1:0.85:0.8 with a fixed warm dome on top of it. The fix is either a runtime-set grade from the game's constants
   (`remixapi_SetConfigVariable`, `remix_c.h:724`, `:810`) or fixing the light budget first.
4. **Water is identifiable and is being sent as a cutout.** The water surface is the alpha-blended translucent family
   `ps_550347550280` / `ps_550347548488` with `g_TranslucentParam` / `g_RefractParam` / `g_WaterFogParam` (§4). Blended
   draws are currently forced to `REMIXAPI_INSTANCE_CATEGORY_BIT_ALPHA_BLEND_TO_CUTOUT` (`live_scene.h:721`), so water
   reaches Remix as opaque geometry.
5. **Emission is off by construction** (`nscn_scene.h:120` sets `emissiveIntensity = 0` for every live material) while the
   API has the three fields needed (`remix_c.h:322-324`). **Hair** already has the alpha-test, double-sided and tint
   plumbing; what is missing is anisotropy and the hair-card category (`remix_c.h:240`, `:503`).

---

## 1. Sky today: what the proxy does, in code

| what | where | behaviour |
| --- | --- | --- |
| sky recognised by extent | `live_capture.h:2338-2363` | world-space extent of the first instance after the world matrix; `sky_extent = extent > 5000.f` (`:2362`), cached per geometry (`sky_geometries()`, `:371`, `:2363`) |
| carried on the draw | `live_capture.h:2390` (`upload.sky = sky_extent`), `:2461-2464` | `item.sky`; `frame.sky` counter incremented per draw |
| switch | `live_capture.h:251`, `remix_live.cpp:248` | `NIER_REMIX_LIVE_NO_SKY=1` drops sky draws again (pre-1.9 picture) |
| category | `live_scene.h:723` | `instance.categoryFlags \|= REMIXAPI_INSTANCE_CATEGORY_BIT_SKY` (`remix_c.h:479`) |
| what that category does | `FULL:src/dxvk/rtx_render/rtx_instance_manager.cpp:1046-1049` | "Hide the sky instance since it is not raytraced. Sky mesh and material are only good for capture and replacement purposes." → the game's sky mesh is submitted and never drawn |
| dome light | `nscn_scene.h:212-230` (`make_lights`), created at `live_scene.h:551-553`, drawn at `:790` | `remixapi_LightInfoDomeEXT` + one scalar radiance `o.sky` |
| dome texture and strength | `remix_live.cpp:269-277` | `NIER_REMIX_SKY_DDS`, default `nier_sky_hdr.dds` beside the scene file; `live_options.sky = 2.f`; `NIER_REMIX_SKY=<v>` overrides (0 → no dome light) |
| everything else about the light | `nscn_scene.h:87` | `sun = 2.f`, `sun_angle = 20.f`, `sky = 0.5f` are the NSCN defaults; the live path overrides `sky` with 2.0 and leaves `sun_angle` at 20° |

Two Remix facilities exist that the plan should know about and neither works for us today:

- `rtx.skyReprojectToMainCameraSpace` / `rtx.skyForceAutoDetectedToReproject` / `rtx.skyReprojectScale` promote *D3D9 sky
  draw calls* from sky rasterisation into the traced scene (`FULL:src/dxvk/rtx_render/rtx_sky.h:104-155`,
  `rtx_options.h:1251-1258`). The path is entered only from the draw-call hook, i.e. from D3D9 draws
  (plan §11.7, `PLAN_2026-11-13.md:1824-1826`); an API instance in the Sky category never reaches it. UNVERIFIED whether
  any of these three options affects API instances in the runtime in use.
- `rtx.skyUseProbeForPrimaryRays` (`RtxOptions-1.6.md:746`) samples the sky probe for primary misses. With no D3D9 sky
  draws, nothing fills that probe, so it would show the clear colour. UNVERIFIED, untested.

### 1a. Finding the sky draws in a capture — what the data supports

Census of the two laptop captures (per pixel shader: draws at 2880x1800, `t20` = `g_PointLightAryBuffer` declared):

| ps_hash | desert n / idx | water n / idx | viewport | t20 | what it is |
| --- | --- | --- | --- | --- | --- |
| 550287367752 | 438 / 6,785,400 | 351 / 2,753,001 | 1024x1024 | no | shadow pass; declares **no** resources |
| 550285061128 | 144 / 1,818,933 | 284 / 1,655,133 | 2880x1800 | no | depth pre-pass (`SceneBuffer` cb0 + `CamParam` cb13 only) |
| 550286859080 | 29 / 281,259 | 46 / 318,159 | 1440x900 | no | half-res pass, declares **no** resources → writes interpolants only (a linear-depth pass) |
| 550286352392 | 19 / 209,187 | 46 / 198,723 | 2880x1800 | no | unlit (`g_Texture0` only, no lighting/fog/LUT), 1024² and 2048² BC2 textures, cull none, depth write on |
| 550288868808 / 550421507528 / 550288864328 / 550345096712 | 4 / 6 / 6 / 4 | 4 / 0 / 5 / 18 | 2880x1800 | no | read `g_ColorTexture`, `g_EffectPixelCommonBuffers` t27, additive (`blend_enable 1, src 5, dest 6`) → the effect/post draws of E1 |
| 550337746952 / 550296127432 / … | 88 / 34 / … | 114 / 87 / … | 2880x1800 | yes | the lit families |

**Conclusion: the desert capture contains no draw that is unambiguously the sky dome.** Every draw without a light buffer
is either a depth pass, a shadow pass or an effect that samples the colour buffer; the only unlit textured family
(`550286352392`) re-appears in the 1024x1024 shadow pass with identical index counts (desert `draw_0012` idx 49,656 =
`draw_0698` idx 49,656), i.e. it is shadow-casting geometry (props/signs), not a background shell. The sky in that view is
therefore not a separate draw, or it was below the capture's index threshold, or it is drawn by a lit shader.
The proxy's own count is the only authority: the camp capture reports `sky=7` (plan §11.9, `PLAN_2026-11-13.md:1889-1893`)
and the G4 replay of `frame_12935626` reports `8 sky draws` (`PLAN_2026-11-13.md:1498-1501`).
How to get the *identity* of those draws without guessing: the visibility trace already carries a per-event sky bit
(`live_capture.h:2506`, `visibility_trace::Reason::Sky` at `visibility_trace.h:20`) — add the shader code and extent to
that one event (see step 1 of the recommendations).

The texture that would identify the sky dome is also not visible in the census: no draw in either capture binds a
2048x1024 or 4096x2048 texture, so the sky texture is either 1024² BC2 like `550286352392`'s or not captured.

---

## 2. The grade, item L1, and why W2 needs more than a conf edit

### 2a. What L1 asked for and what was found (`PLAN_2026-11-13.md`)

- Item text `:196-236`: config-only work; keys are `rtx.localtonemap.exposure`, `.highlights`, `.shadows`,
  `rtx.useLegacyACES`, `rtx.autoExposure.evMaxValue`, global mode with `rtx.tonemap.dynamicRange` +
  `colorGradingEnabled` + `saturation`, and the dome strength `NIER_REMIX_SKY`. Method: one key per run on captures
  `30632051` and `41686139`, 2,500 frames each, judged by the section 3b row.
- Acceptance rule `:211`: **discard a run with clipping above 0.5% or crush above 2%.**
- Section 3b row is produced by `replay/frame_tools.py:17-27`: median luma (Rec.709 on stored 8-bit values), 95th
  percentile, `clip_pct` = share of pixels with luma > 0.98, `crush_pct` = share < 0.02, mean HSV-style saturation
  `(max-min)/max`. `frame_tools.py:11-13` states the noise floor: two runs of the same static frame differ by 1.1-1.3 grey
  levels, so a diff under 2 is "unchanged".
- Ten single-key runs, table at `:239-262`. Survivors: `rtx.localtonemap.exposure = 0.5` (0.456 / 0.878 / 0.0% / 1.6% /
  0.136) and global mode with `saturation` 1.15 and 1.3. Discarded: exposure 0.35 (crush 2.5%), `highlights 2 + shadows 1`
  (clip 2.0%), `useLegacyACES = False` (crush 4.0%), `evMaxValue 3`/`2` (no effect at all), `NIER_REMIX_SKY = 1.0`
  (clip 2.1%).
- User pick `:283-288`: **variant 4 = global tonemap, `saturation` 1.3**, applied to `deploy/rtx/desktop-replay.conf`,
  `laptop-a-fg-off.conf`, `laptop-b-dlss-perf.conf`, `laptop-c-fast.conf`.
- **The confs have moved on since that text was written.** `deploy/rtx/game.conf:38-44` and
  `deploy/rtx/laptop-game.conf:14-20` now carry `rtx.tonemappingMode = 0`, `rtx.tonemap.dynamicRange = 15`,
  `colorGradingEnabled = True`, **`saturation = 1.6`**, **`contrast = 0.90`**, **`colorBalance = 1.0, 0.89, 0.70`**,
  **`exposureBias = -0.85`**. The in-game fit that produced them is recorded in `deploy/rtx/game.conf:4-6`: truth pair
  at the same spot, median 0.333 vs 0.306, p95 0.564 vs 0.554, saturation 0.191 vs 0.184, R:B 1.23 vs 1.21, 55.9 fps at
  640x350. So the *numbers* the plan quotes for L1 ("saturation 1.3") are stale relative to the confs; the plan rewrite
  must not re-apply 1.3.
- The tolerance the truth pair was accepted at (game vs ours, camp): median ±0.027, p95 ±0.010, saturation ±0.007,
  R:B ±0.02 (`game.conf:4-6`). The G4 pair one day earlier was far worse: 0.372 / 0.569 / 0.180 against
  0.495 / 0.859 / 0.108 (`PLAN_2026-11-13.md:1499-1507`). Those are the two reference points "within the camp's
  tolerances" should mean in W2.
- `replay/l1_table.py` prints exactly that row per `runtime/replay/l1*` run: it shells `frame_tools.py stats` on
  `shot-2499.png`, adds `fps` from `summary.json` and the non-boilerplate conf keys (`l1_table.py:1-30`).

### 2b. What the game's own constants say about "one grade for both areas"

`PSParamBuffer1` at PS slot 2 (128 B) is the scene CB2 that `light_convert::parse_sun` reads
(`light_convert.h:40-56`). Names and offsets below come from the RDEF of `ps_550344741192.dxbc` (desert lit shader),
parsed this session; the values are the first 4 floats of each variable.

| float idx | variable (RDEF) | desert `frame_67279062/draw_0701` | camp `frame_30632051/draw_2180` |
| --- | --- | --- | --- |
| 0 | `g_lightColor` | 8, 7.2, 4.8, 8 | 6, 5.1, 4.8, 6 |
| 4 | `g_lightVec` | 0.1504, 0.5, -0.8529, 0 | -0.4292, 0.8387, -0.3353, 0 |
| 8 | `g_FogParam` | 0, 0.001171, 0.8828, 2.937 | 0, 4.784e-05, 0.7231, 6.208 |
| 12 | `g_ScreenTileSize` | 90, 60, 0.03125, 0.03333 | 81, 36, 0.03125, 0.03333 |
| 16 | `g_SpParam` | 1, 0, 0, 1 | 1, 0, 0, 1 |
| 20 | `g_spotShadowNo` | nan x4 | nan x4 |
| 24 | `g_ScreenTileOffset` | 0.4, 0.45, 0.5, 0 | 1.27, 1.28, 1.34, 0 |
| 28 | `g_FogColor` | 2.937 white | 6.208 white |

The water capture differs again: `g_lightColor = 10, 9, 7` (`frame_67078468/draw_1136`, slot 2).

**Correction to the briefing note:** floats 24-26 are `g_ScreenTileOffset`, not a grade constant. The camp's
`(1.27, 1.28, 1.34)` is nearly neutral, so the earlier suggestion that it is the camp's warmth does not hold. What the
shader computes with `cb2[24].xyz` beyond the per-tile light lookup (`g_ScreenTileSize` = 90x60 tiles = 2880x1800 in
32x30 px tiles) is UNVERIFIED — it needs an opcode read of a lit shader.

The three measured facts that make one fixed grade fail: (i) the sun's colour ratio differs (desert 1 : 0.90 : 0.60,
camp 1 : 0.85 : 0.80); (ii) the fog colour differs by 2.1x (2.937 vs 6.208) and `g_FogParam.z` (0.8828 vs 0.7231) too;
(iii) the dome is the same fixed warm HDR file at strength 2 in both. A fixed `colorBalance` 1.0/0.89/0.70 plus
`saturation` 1.6 therefore over-warms the desert (already red-heavy sun) and under-fills the camp's shadows. Note also
that the current fit was made under XeSS without Ray Reconstruction at 640x350 (`game.conf:4-6`) and
`laptop-game.conf:2-3` explicitly says: "Exposure was fitted under XeSS without Ray Reconstruction: check one truth pair
on the laptop before trusting it."

---

## 3. Emission, item L6

Plan text: `PLAN_2026-11-13.md:525-548`. Facts it relies on: emission is `emissiveColorTexture` if loaded else
`emissiveColorConstant`, sRGB-decoded, times `emissiveIntensity`; off at 0 or less; it goes through tone mapping and auto
exposure, so it interacts with L1.

Code state today:

- Every live material is created with `info.emissiveIntensity = 0` (`nscn_scene.h:120`, inside `make_material_info`);
  neither `emissiveTexture` nor `emissiveColorConstant` is ever set. Nothing in the live path emits.
- The API fields exist: `remixapi_MaterialInfo.emissiveTexture` (`remix_c.h:322`), `emissiveIntensity` (`:323`),
  `emissiveColorConstant` (`:324`).
- Material identity is the hash alone, built from albedo/normal/alpha-test/constants (`live_scene.h:213-233`). An emissive
  variant must be part of the hash or two draws sharing an albedo will share one material. The PBR branch already takes
  bit 63 (`:228`) and the L3 constants branch bit 62 (`:233`); the emissive flag needs a third combination, and the
  material-cache key (`live_scene.h:176-196`, `key = ...` and `s.materials.find(key)`) must include it.
- Which draws: the plan's own classifier split (11.8, `PLAN_2026-11-13.md:1866-1884`) has 228 "samples a material slot,
  no lighting maths" shaders and 218 lit ones without pinnable roles. In the desert capture the unlit family is
  `550286352392` (19 draws, 209k indices, `g_Texture0` only) and the effect family (which E1 owns). W4's first
  measurement is therefore: per capture, which shaders emit *after fog* (the plan names cube `t8` and 2D `t10`,
  `PLAN_2026-11-13.md:928-931`) and whether any of them appears by day. Daytime captures cannot settle this: the plan is
  right that a night capture is needed (W4 "blocked on data").

---

## 4. Water, item L8

Plan text: `PLAN_2026-11-13.md:935-951`. It says (a) tint has to be baked because Remix has no multiply, (b) hair is
alpha-tested cards, (c) "Remix has a translucent material with a second normal".

**Contradiction:** the C API has no second-normal translucent material. `remixapi_MaterialInfoTranslucentEXT`
(`remix_c.h:289-306`) carries `transmittanceTexture`, `refractiveIndex`, `transmittanceColor`,
`transmittanceMeasurementDistance`, `thinWallThickness_*`, `useDiffuseLayer` and texture scroll/scale/tiling — no second
normal. A second normal is a legacy-material-system feature (`rtx_materials.h`), not reachable through `remixapi`.
What the API does give for water: `REMIXAPI_INSTANCE_CATEGORY_BIT_ANIMATED_WATER = 1 << 17` (`remix_c.h:494`).

### 4a. Measured: which draws are water

Variable names in the RDEF of the two laptop captures' 41 pixel shaders include `g_TranslucentParam`, `g_RefractParam`,
`g_WaterFogParam`, `g_WetParam1`, `g_WetParam2`, `g_wetLv1`, `g_wetLv2`, `g_CubeBlendRate`, `g_CtoSFogColor`,
`g_StoBFogColor`. Two shaders carry the water trio:

| shader | variables (offset) | desert draws | water draws |
| --- | --- | --- | --- |
| `ps_550347548488` | `g_TranslucentParam` 144, `g_RefractParam` 160, `g_WaterFogParam` 208 | 5 (max 3,924 idx) | 10 (max 3,135 idx) |
| `ps_550347550280` | `g_TranslucentParam` 160, `g_WetParam1` 112 | 4 (max 1,329 idx) | 5, **one of 16,848 idx** |

Both are declared with `g_CubeTexArray` (t18, a cube-map array) and `g_CubePixelBuffer` (t25) → the game's reflections
come from a cube map; `550347548488` also samples `g_Opacity_Tex` (t13). Both read the point-light arrays (t20/t21/t22),
so they are lit. State of every draw of both: `blend_enable 1, src_blend 5 (SRC_ALPHA), dest_blend 6 (INV_SRC_ALPHA),
depth_write 1, dsv 45`.

Values measured at PS slot 1 (the 176-byte `PSParamBuffer1`), water capture `draw_1136` vs desert `draw_0902`:

| variable | water | desert |
| --- | --- | --- |
| `g_AlbedoColor` | 0.229, 0.229, 0.229, 1 | 0.229, 0.229, 0.229, 1 |
| `g_WetParam1` | 0, 0, 0.63, 0.85 | 0, 0, 1, 0 |
| `g_TranslucentParam` | 1.163, 0, 1.256, 12.56 | 0, 0, 1.533, 10.22 |

`g_TranslucentParam.x` is 0 in the desert and 1.163 in the water capture, and `g_WetParam1.z/w` differ too: two scalars a
switch can key on. The 16,848-index draw (`frame_67078468/draw_1136`, albedo 128x128 BC7, normal 64x64 BC7) is the
largest translucent surface and the best candidate for the water sheet; the four other draws of that shader are
1,320-6,912 indices (puddle edges, splashes, sheets). **This is a strong inference, not a verified identification:**
confirming it needs the replay picture at that frame (window crop) or the game's own frame at the same spot.

### 4b. Viewport census (`frame_67078468`, the water capture)

704 draws at 2880x1800, 426 at 1024x1024 (shadow), 46 at 1440x900. The 1440x900 block is draws 1087-1132, one shader
(`ps_550286859080`, **no** resources declared, depth test on, depth write off) and it starts immediately before the
translucent block at 1134-1148. In the desert the same block is draws 872-900 (29 draws). So the 1440x900 pass is not a
reflection target: it is a half-res linear-depth pass, in both areas, and the *only* pass that changes size.
No reflection render target appears in either capture — because a capture only records draws whose index count is above
the capture threshold (`frame.json`, `min_index_count` 128, plan §11.8 `:1880-1885`), and reflection passes draw a quad.
That is also why `g_CubeTexArray` reflections can never be sent as geometry: the cube map itself is not rendered into a
capturable target.

---

## 5. Hair, item L8 (W5)

What exists already:

- Alpha-tested cutout path: the game's own `discard` is parsed into `alpha_test::Result` (`live_capture.h:1319`,
  `:2066-2068`, `:2391`) and passed into the material as `ext.alphaTestType` / `alphaReferenceValue`
  (`live_scene.h:239-240`, `nscn_scene.h:144-150`).
- Every instance is submitted `doubleSided = 1` (`live_scene.h:719`), so hair cards are visible from both sides.
- The tint that hair needs is detected: `PixelInfo::tint_cb8_cb4` is set when the shader multiplies
  `cb8[0].xyz * cb4[0].xyz` (`live_capture.h:1319`, `:1456-1462`), with an explicit `shortcut:` note that only the
  non-instanced `cb8[0]` form is handled. `live_types.h:43` records that blended draws are "foliage, hair, grilles".
- Blended draws are forced to cutout (`live_scene.h:721`), so hair is already cutout rather than see-through.

What is missing for "the game's anisotropic silver":

- `remixapi_MaterialInfoOpaqueEXT.anisotropy` (`remix_c.h:240`) is never set (no `anisotropy` occurrence anywhere under
  `checks/`).
- `REMIXAPI_INSTANCE_CATEGORY_BIT_HAIR_CARDS = 1 << 25` (`remix_c.h:503`) is never used. UNVERIFIED what the runtime
  does with it (no source in the FULL tree for the API path was read).
- The hair shader's own anisotropy constants exist in the shaders (`g_AnisoParam1`, `g_AnisoParam2`,
  `g_SecondarySpecParam`, `g_BaseBoolParam*` in the RDEF name set of the two captures' shaders) but which offsets belong
  to which parameter is UNVERIFIED, and 2B is not in the desert or water capture, so her hair shader must be found in the
  camp capture (`frame_30632051`) first.
- The plan's L8 hair note (`PLAN_2026-11-13.md:944-946`) says the hair "reads as a white blob with UNORM and normals on":
  that is consistent with an alpha-tested card whose albedo texture is mostly white and whose normal map is being
  applied with remapped strength — the same problem L3 solves with constants.

---

## 6. How one compares a replay shot against the game's own frame

Tooling that exists and its exact interface:

| step | command | evidence |
| --- | --- | --- |
| pack an F9 capture for the replayer | `replay/pack_capture.py <frame_dir> <out> --name scene --min-indices N` (hard-links capture buffers, one constant-buffer blob) | `pack_capture.py:21-42`, `:94-98`; `README.md:9` |
| replay it through the real proxy | `replay/run_replay.py <label> <frames_dirs...> --mode real --conf <conf> --shots 300,600 --frames 2500 --size WxH --env K=V --min-indices N` | `run_replay.py:96-110` |
| read numbers off a shot | `replay/frame_tools.py stats <png>` → median / p95 / clip / crush / saturation; `diff a b` → mean abs difference in grey levels; `sheet out.jpg label=png ...` → A/B panels | `frame_tools.py:3-13`, `:17-27` |
| the row per run | `replay/l1_table.py` (all `runtime/replay/l1*`) | `l1_table.py:1-30` |
| rules | same camera, same spot; two runs of the same static frame differ by 1.1-1.3 grey levels, so a `diff` under 2 is "unchanged" | `frame_tools.py:11-13` |

The game's own frame (the truth) is **not** in any F9 capture: a capture holds no final colour buffer and no draws below
128 indices, so no post pass and no colour grade (plan §11.8, `PLAN_2026-11-13.md:1880-1885`). It comes from the proxy's
Present hook instead: `NIER_SCREENSHOT_DIR` + `NIER_SCREENSHOT_AT` write `shot-N.raw` (12-byte header, rows) plus PNGs
(`checks/menu_overlay.cpp:401-414`, `poll_screenshots` `:478`, called every present `:649`; procedure
`replay/research-2026-11-14/c_laptop_ops_recon.md:229`, `:240-246`). The G4 pair was produced that way: run `game-truth`
(no `NIER_REMIX`) and `game-final` (live) with the same save and the same still-camera menu script
(`c_laptop_ops_recon.md:240-246`, numbers at `PLAN_2026-11-13.md:1499-1509`). Run summaries do **not** record the shot
times (`c_laptop_ops_recon.md:246`), which is a gap to close: store the exact command line and `NIER_SCREENSHOT_AT` in
`summary.json`.

For W2 (desert truth pair) nothing in the repository can produce the desert frame: the desktop save never leaves the camp
(`PLAN_2026-11-13.md:923-933`). The only route is the laptop's own save. What the user must do, concretely: stand at the
desert spot with `NIER_REMIX` unset (or `NIER_REMIX=0`) and one launch that takes a screenshot there — either
`NIER_SCREENSHOT_AT=<seconds>` in the laptop's `game_run.py` (which sets both variables, `c_laptop_ops_recon.md:229`) or
the in-game F9 key, which writes a capture but *not* the final frame. Then the same spot with `NIER_REMIX=1` for our
picture, and the two numbers land in the section 3b row. The desert capture `frame_67279062` gives the camera for free:
its transforms can be replayed, so "the same spot" can be made exact by replaying that capture instead of walking there
again — the replay's own frame is the "ours" panel, and only the game's panel needs the user.

---

## 7. Config keys: what is in the confs and what the runtime has

`deploy/rtx/laptop-game.conf` and `deploy/rtx/game.conf` set exactly these grade keys (line numbers above): no `rtx.sky*`
key in any conf under `deploy/rtx/`. `NIER_REMIX_SKY` / `NIER_REMIX_SKY_DDS` are proxy environment options, not conf keys
(`remix_live.cpp:269-277`).

Option names available in the runtime, with defaults, from `analysis/runtime/remix-probe/RtxOptions-1.6.md` (the
authoritative list the gate `checks/test_rtx_conf_input.py:12-16` validates against) and cross-checked name-by-name in
`RTX_OPTIONS_THIS_BUILD.txt` (the `PortalRTX/bin/.trex/d3d9.dll` string dump — note the laptop's own log says the runtime
in use is `DXVK_Remix: remix-main+5a7eec84`, `runtime/laptop-play-20261114/remix.log:7`):

| key | type | default | line |
| --- | --- | --- | --- |
| `rtx.skyBrightness` | float | 1 | `RtxOptions-1.6.md:737` |
| `rtx.skyProbeSide` | int | 1024 | `:742` |
| `rtx.skyDrawcallIdThreshold` | int | 0 | `:738` |
| `rtx.skyAutoDetect` | int | 0 | `:735` |
| `rtx.skyMinZThreshold` | float | 1 | `:741` |
| `rtx.skyForceHDR` | bool | False | `:740` |
| `rtx.skyReprojectToMainCameraSpace` | bool | False | `:744` |
| `rtx.skyReprojectScale` | float | 16 | `:743` |
| `rtx.skyUseProbeForPrimaryRays` | bool | False | `:746` |
| `rtx.tonemappingMode` | int | 0 = Local | `:862` area (`PLAN_2026-11-13.md:1827-1832`) |
| `rtx.tonemap.dynamicRange` | float | 15 | `:852` |
| `rtx.tonemap.exposureBias` | float | 0 | `:853` |
| `rtx.tonemap.colorGradingEnabled` | bool | False | `:849` |
| `rtx.tonemap.colorBalance` | float3 | 1,1,1 | `:848` |
| `rtx.tonemap.contrast` | float | 1 | `:850` |
| `rtx.tonemap.saturation` | float | 1 | `:856` |
| `rtx.tonemap.toneCurveMinStops` / `MaxStops` | float | -24 / 8 | `:860-861` |
| `rtx.tonemap.maxExposureIncrease` | float | 5 | `:855` |
| `rtx.tonemap.finalizeWithACES` | bool | False | `:854` |
| `rtx.localtonemap.exposure` / `.shadows` / `.highlights` | float | 0.75 / 2 / 4 | `:376`, `:382`, `:380` |
| `rtx.localtonemap.finalizeWithACES` | bool | True | `:379` |
| `rtx.autoExposure.enabled` | bool | True | `:47` |
| `rtx.autoExposure.evMinValue` / `evMaxValue` | float | -2 / 5 | `:49`, `:48` |
| `rtx.autoExposure.autoExposureSpeed` | float | 5 | `:45` |
| `rtx.autoExposure.exposureAverageMode` | int | 1 (Median) | `:50` |
| `rtx.autoExposure.exposureCenterMeteringEnabled` | bool | False | `:51` |
| `rtx.autoExposure.useExposureCompensation` | bool | False | `:57` |

Verified method for "did this key take effect": the runtime echoes the *effective combined config* into `remix.log`
(`runtime/laptop-play-20261114/remix.log:20-40` lists every key it parsed, including all five `rtx.tonemap.*` lines).
A misspelt key is silently absent from that echo — that is the cheapest gate for every conf change in this phase.

---

## Open questions

1. **Which draw is the sky in the desert capture?** Not determinable from the capture alone (§1a). Determine: add the
   pixel shader code and `extent` to the existing `sky` visibility event (`live_capture.h:2359-2363`, `:2506`), replay
   `pack_capture.py`-packed `frame_67279062` in `--mode off`, read the event.
2. **Is the water sheet really `ps_550347550280`'s 16,848-index draw?** Determine: replay `frame_67078468` with
   `--shots` at that frame, crop the bottom half (`view.py`, `frame_tools.py sheet --crop`), look; or hide that shader
   behind a temporary switch and see the water disappear.
3. **What does the shader do with `cb2[24].xyz`?** Determine: disassemble a lit shader with
   `checks/disassemble_shader.cpp` / `dxbc_disasm` and read the `cb2[24]` uses.
4. **Does the runtime in use have `rtx.skyReprojectToMainCameraSpace` and does it affect API Sky instances?** Determine:
   set it in a replay conf, watch the remix.log echo (proves the key parsed) and the shot (proves the effect). The
   FULL-tree code path is entered only from D3D9 draw calls.
5. **`REMIXAPI_INSTANCE_CATEGORY_BIT_HAIR_CARDS` and `..._ANIMATED_WATER` semantics in remix-main+5a7eec84.** No API-path
   source for either was read. Determine: grep the runtime's own remix log at startup, or test one instance of each and
   compare a shot.
6. **What the game's anisotropic hair constants are.** 2B is not in either laptop capture. Determine: find her hair shader
   in `/mnt/second/.../NIER_CAPTURE/frame_30632051` by `tint_cb8_cb4` + alpha-test + `g_AnisoParam1`, then read those
   offsets.
7. **`g_Opacity_Tex` at t13** contradicts the plan's "slot 13 is depth, never a material" (`PLAN_2026-11-13.md:1863`).
   Which shaders treat 13 as depth and which as opacity? Determine: count per shader how the slot is declared (the RDEF
   name already says it) and fix the note.

## Recommended steps for the plan

Each step: what to do, in which file, how it is checked, and the mutation that must turn the gate red.

1. **Name the sky draws (W1, first, ~1 h).** In `analysis/checks/live_capture.h` inside the `sky_extent` branch
   (`:2359-2363`), log `remix: sky geometry=%llu extent=%.1f ps=%llx` behind the existing trace switch
   (`visibility_trace.h`). Add the case to `checks/test_live_scene.py` or a new `test_sky_identity.py` that packs a tiny
   fake capture with one 6000-unit mesh and asserts the line. **Gate asserts:** exactly one sky line, with the extent
   above 5000 and the shader code of the draw. **Red mutation:** change `5000.f` to `50000.f` (`live_capture.h:2362`) —
   the gate must fail. Then run it on the packed `frame_67279062` and on `frame_30632051`.
2. **Fix the RDEF variable parser before trusting any constant name (blocks W2/W3/W4/W5 evidence).**
   `analysis/checks/dump_shader_decls.py:54` reads each variable at `cb_offset + var_offset + 24 * v`; the offsets are
   absolute RDEF offsets and the entry stride is 40 bytes for these blobs (verified: `g_lightColor` at 1548, `g_lightVec`
   at 1588, `g_FogParam` at 1628; the same call at `cb_offset+var_offset` decodes string bytes). Fix to
   `var_offset + 40 * v` with a 24-vs-40 stride probe. **Gate:** a new `checks/test_shader_decls.py` asserting that
   `ps_550344741192.dxbc` yields `g_lightColor@0`, `g_lightVec@16`, `g_FogParam@32`, `g_FogColor@112` and that
   `ps_550347548488.dxbc` yields `g_WaterFogParam@208`. **Red mutation:** restore `cb_offset +` — the gate must fail.
3. **Sky colour and strength from the game's constants, behind a switch (W1).** New option struct in
   `analysis/checks/live_types.h` + `live_scene.h`: `SkyDrive { off, constants }`. When on, set the dome radiance per frame
   from the frame's own `Sun` (already in `Frame`, `live_types.h:94`) — `sky = k * (0.2126*c.r + 0.7152*c.g + 0.0722*c.b)`
   of `g_lightColor`, clamped, and tint the dome by `g_lightColor` normalised — and regenerate nothing (one DDS, one
   scalar). Env `NIER_REMIX_SKY_DRIVE=1`, default off. **Gate:** extend `checks/test_live_lights.py` so a fake runtime
   with `g_lightColor = (8, 7.2, 4.8)` produces dome radiance `X` and with `(6, 5.1, 4.8)` produces `Y != X`.
   **Red mutation:** hard-code 2.0 again — the gate must fail. Measurement after: one replay of `frame_67279062` and one
   of `frame_30632051` with the switch on and off; the section 3b row must move toward the truth pair, not away.
4. **A desert truth pair (W2, needs the user at the laptop, 10 min).** `analysis/runtime/game-runs/game_run.py` with
   `--shots` and `--env NIER_SCREENSHOT_AT=...`, `live: false`, at the desert spot of `frame_67279062`; then the same
   spot live. Record the command line and shot times in `summary.json` (close the gap in `c_laptop_ops_recon.md:246`).
   **Gate:** a `checks/test_truth_pair.py` that refuses a pair whose `summary.json` lacks the command line, the shot
   time, and the save hashes — and that prints the section 3b row for both. **Red mutation:** delete `shots` from one
   summary — the gate must fail.
5. **Grade that holds in both areas (W2).** Preferred order: (a) land steps 3 and 6 first (light budget), then re-fit;
   (b) only if one fixed block still cannot hold, add `NIER_REMIX_GRADE_FROM_CONSTANTS=1`, which calls
   `SetConfigVariable` (`remix_c.h:724`, `:810`; the same call path P1 already plans) for
   `rtx.tonemap.colorBalance`, `rtx.tonemap.saturation` and `rtx.tonemap.exposureBias` when `g_lightColor`/`g_FogColor`
   change by more than 5%, interpolating between two table rows (camp, desert) measured from the truth pairs.
   **Gate:** `checks/test_grade_table.py` — given the two measured constant sets, the emitted config values equal the
   fitted table; unchanged constants emit no call. **Red mutation:** return the desert row for the camp constants — fails.
   **Measurement each needs:** the section 3b row of camp and desert, against their own truth pair, clip <= 0.5% and
   crush <= 2% (`PLAN_2026-11-13.md:211`).
6. **Water as a Remix material (W3).** In `live_capture.h`, detect the translucent family by its declared
   `g_TranslucentParam` / `g_WaterFogParam` (the `material_roles.h` style declaration check already exists for
   `declares_effect_buffers`, `live_capture.h:1452`), carry a `water` flag on the item, and in `live_scene.h` create the
   material with `remixapi_MaterialInfoTranslucentEXT` (`remix_c.h:289-306`): `transmittanceColor` from
   `g_AlbedoColor * g_TranslucentParam.x`, `refractiveIndex` 1.33, `roughnessConstant` from `g_WetParam1.z`, normal map
   as today, and set `REMIXAPI_INSTANCE_CATEGORY_BIT_ANIMATED_WATER` (`remix_c.h:494`) instead of
   `ALPHA_BLEND_TO_CUTOUT` (`live_scene.h:721`). Env `NIER_REMIX_LIVE_WATER=1`, default off. **Gate:**
   `checks/test_live_water.py` on the fake runtime: a draw whose shader declares `g_WaterFogParam` produces a
   translucency struct with `refractiveIndex` 1.33 and the ANIMATED_WATER bit, and the same draw with the switch off
   produces today's cutout. **Red mutation:** drop the category bit — the gate must fail. **Measurement:** replay
   `frame_67078468` with and without; the 16,848-index surface must be visible, reflect the scene, and the section 3b row
   must not shift by more than the noise floor (2 grey levels) outside the surface.
7. **Emission (W4).** Add `emissive_intensity` and the emissive texture id to `PixelInfo` in `live_capture.h` (an unlit
   shader's albedo becomes the emissive texture, albedo black: `PLAN_2026-11-13.md:539-541`), extend the material hash
   (`live_scene.h:213-233`) and set `info.emissiveTexture` / `emissiveIntensity` in `make_material_info`
   (`nscn_scene.h:117-126`). Env `NIER_REMIX_LIVE_EMISSIVE=1` + intensity value. **Gate:** `test_live_emissive.py` —
   an unlit draw yields `emissiveIntensity > 0` and a non-null emissive path in the fake runtime's `CreateMaterial` line;
   a lit draw yields 0. **Red mutation:** set `emissiveIntensity = 0` again — the gate must fail. **Data:** a night
   capture (still blocked); until then the desert capture's unlit family `550286352392` gives the day-time sheet.
8. **Hair (W5, user's look decision).** Set `ext.anisotropy` from the hair shader's `g_AnisoParam*` (find the offsets
   first, open question 6) and add `REMIXAPI_INSTANCE_CATEGORY_BIT_HAIR_CARDS` (`remix_c.h:503`) for instances whose shader
   is the hair shader. Env `NIER_REMIX_LIVE_HAIR=1`. **Gate:** `test_live_hair.py` — a hair-flagged draw produces a
   material with `anisotropy` from the constant and the HAIR_CARDS bit; a non-hair draw does not. **Red mutation:** read
   the constant from the wrong offset (`+16`) — the gate must fail. **Sheet:** the user picks, as L8 specifies.
