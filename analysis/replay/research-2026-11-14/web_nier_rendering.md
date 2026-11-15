# How NieR:Automata (PC, D3D11) renders — online research for the path-traced replacement

Researched 2026-11-14 for the rewrite of `analysis/PLAN_2026-11-14.md`. Read-only: no game run, no build, no install,
no ssh. Web pages fetched directly with curl (Brave/Bing search, GitHub API/raw, `web.archive.org`).

Confidence labels used below: **VERIFIED** = the claim is a direct quote or a code line I read.
**UNVERIFIED** = inferred from names or by elimination; must be checked before it goes into a plan as fact.

---

## 1. Summary in one paragraph

NieR:Automata's renderer is **Forward+ on PlatinumGames' own engine**, extended to PBR for this game, with **Enlighten**
(Geomerics, later Silicon Studio) supplying all global illumination as a **compute-shader radiosity over light volumes**
(128 volumes per dispatch). Screen-space effects run at **fixed, tiny resolutions**: AO at 800x450 (with an 800x450
hierarchical-Z input and a two-direction depth-aware blur), bloom as a 5-level pyramid 800x450 → 50x28. Its transparent
effects are, by the developer's own account, **mostly drawn opaque with a dither punch-out and repaired by bloom** — this
is the single most useful fact for the "effects are missing in Remix" item, because it means the game's own technique is
closer to cutout-plus-bloom than to alpha compositing. Materials are named shaders (`PBS00_XXXXX`, `Hair01_XXXXX`,
`Wtr00_XXXXX`, ...) whose parameter names are public and give the water, hair and cloth models almost directly. There is
**no day/night cycle** in the game at all (in-universe the Earth is tidally locked), so "get a night capture for
emission" cannot be satisfied by playing outdoors.

---

## 2. Sources

| # | Source | What it is | What it establishes |
| --- | --- | --- | --- |
| S1 | https://cgworld.jp/feature/201704-cgw225-nier.html (CGWorld vol.225, 2017-04, JP) | Developer feature: rendering programmer 髙橋遼一, lead VFX 中島史音, char. modeller 松平仁, TA/lighting 亀岡昇平 | Forward+, 900p (1080p on PS4 Pro), 60 fps; effect dithering; bullet rendering; hair/cloth/eye/skin shaders; A2 emissive |
| S2 | https://cgworld.jp/interview/201803-Enlighten.html (CGWorld, 2018-03, JP, Silicon Studio PR) | Enlighten integration write-up with the same TA 久禮義臣 and programmer 髙橋遼一 | Enlighten GI, probes, per-area cubemaps, characters get only indirect from point lights |
| S3 | https://www.pcgamingwiki.com/wiki/NieR:_Automata | PCG factsheet | Direct3D 11, **32-bit** exe, middleware Wwise/Scaleform/Criware, "Uses Enlighten for global illumination", AA = up to 8x MSAA (+SMAA via mod) |
| S4 | https://github.com/Kaldaien/FAR (`nier.cpp`, `README.md`) | FAR, the original 2017 renderer mod | Bloom pyramid sizes/formats, AO buffers/formats, GI light-volume buffer, light-scattering cbuffer |
| S5 | https://wiki.special-k.info/SpecialK/Custom/FAR | SpecialK's official wiki for the FAR feature set | GI quality = compute workgroup count: Ultra 128, High 64, Medium 32, Low 16, Off 0 |
| S6 | https://github.com/PeterTh/GameManipTutorial (`README.md`) + http://blog.metaclassofnil.com/?p=867 (Durante) | RenderDoc tutorial done *on NieR:Automata* | AO pass output 800x450 at 2560x1440, single 800x450 HZB input, H+V depth-dependent blur, PS cbuffer holding 1/1600, 1/900 |
| S7 | https://github.com/emoose/NieRAutomata-LodMod (`LodMod.ini`, `AOFixes.cpp`, `ShadowFixes.cpp`) | LodMod | "AO resolution in vanilla game is set to 1/4 your screen res"; shadow resolution/distance/filter knobs; engine function named `SAO CreateTextureBuffer`; cloud layer is a model |
| S8 | https://github.com/WoefulWolf/NieR2Blender2NieR (`dump.json`, `materials_miner.py`) | Blender importer/exporter for WMB/WTP/WTA | The 16 material shader names and their per-shader variable names (the "material parameters" table in §10) |
| S9 | https://github.com/ArthurHeitmann/NierDocs (`docs/cpkAndDttContents/effects.md`, `BinaryTemplates/NierA_EST.bt`) | NieR modding docs | `.eff` = numbered effect list per character/background; `.est` = the effect record, with named fields incl. `distortion_effect_strength` |
| S10 | https://github.com/Kerilk/bayonetta_tools (`binary_templates/Bayonetta 2 est.bt`) | Kerilk's PlatinumGames format tools | Same EST container/chunk IDs (TRAP/EVOM/FIME/TEX/PSSA/FVWK/FWK/EMMV/EMFW/MJSG/MCJM) — cross-title Platinum format family |
| S11 | https://www.platinumgames.com/official-blog/article/13708 | PlatinumGames blog, Bayonetta 3 VFX (2023) | House practice: GPU particles with per-particle light computation; impostor texture sheets. **Not NieR** — context only |
| S12 | https://steamcommunity.com/app/524220/discussions/0/135511757692967776/ | Steam discussion "No Dynamic Weather? Day/Night Cycle?" | No day/night cycle; community explanation is the tidally-locked Earth. Community claim, not a dev statement |

Searched and found nothing usable: any PlatinumGames CEDEC/GDC talk about NieR:Automata *rendering* (the CEDEC talks are
audio and action design), any published frame breakdown of NieR:Automata other than S1/S6, any NAIOM or 2B Hook
rendering documentation (both are gameplay/input mods: https://www.nexusmods.com/nierautomata/mods/12 and
https://github.com/Martymoose98/2BHook — no renderer information; do not budget time for them).

---

## 3. The frame, in the game's own numbers

| Stage | Facts | Source |
| --- | --- | --- |
| Renderer | Forward+ ("フォワードプラス"). Chosen because the platform was not yet fixed and deferred was judged risky on memory/speed. Base 900p, PS4 Pro 1080p, 60 fps target | S1 |
| Engine | PlatinumGames in-house, extended for this title to PBR by the TA + rendering programmer | S1 |
| Scene target | R11G11B10F (`T2772`), drawn after a depth/linear-depth prepass and after the background/sky passes | `analysis/SCENE_DOMAIN_INVENTORY.md:27,32,33` |
| Lights | Tiled forward: `g_PointLightAryBuffer` t20, `g_PerTileLightIndexBuffer` t21, `g_SpotLightAryBuffer` t22, plus a screen-tile compute pass | `analysis/SHADER_DECLARATIONS.md:46-56`, `analysis/SCENE_DOMAIN_INVENTORY.md:29` |
| GI | Enlighten: compute-shader radiosity over **light volumes**; 128 volumes per dispatch at Ultra, 64/32/16/0 at High/Medium/Low/Off | S2, S3, S4 `nier.cpp:370-400`, `nier.cpp:186`, S5 |
| AO | Quarter res: 800x450 `R8G8B8A8_UNORM` coverage + 800x450 `R32_FLOAT` hierarchical Z with mips; then horizontal and vertical depth-dependent blur. "AO resolution in vanilla game is set to 1/4 your screen res" | S4 `nier.cpp:1240-1246`, S6, S7 `LodMod.ini:57` |
| Shadows | Separate shadow map with configurable resolution (default bits patched to `ShadowResolution = 8192`), per-scene distance multiplier, per-area blur strength, a "half shadow map" buffer | S7 `LodMod.ini:65-122`, `ShadowFixes.cpp:1-30` |
| Bloom | 5-level pyramid at **800x450, 400x225, 200x112, 100x56, 50x28**, `R11G11B10_FLOAT`, fixed regardless of resolution | S4 `nier.cpp:1161-1173` |
| Auto exposure | The 50x28 level is read by a **compute shader** and sets the whole-screen white level; an `g_AverageBrightnessBuffer` exists on 17 shaders | S4 `nier.cpp:1197-1200`, `analysis/SHADER_DECLARATIONS.md:41` |
| Light shafts | A 160-byte cbuffer: `Near_Far_Stepnum[4][4]`, `LightColor[4][4]`, `LightDirView_Range15[4]`, `ScatterParam_Range7[4]` — a screen-space scattering pass with 4 light slots | S4 `nier.cpp:333-345` |
| Tone / grade | Exposure is decoupled from character brightness; "nostalgic filter" (saturation + chromatic aberration) on heavy damage; vignette + a fine screen grid | S1, S2 |
| AA | Native 8x MSAA; SMAA added by mod. Material shading can be forced once-per-pixel | S3 |
| UI | 58 HUD sprite draws into the native target; menu wipes use an "alpha punch-through" ordered by an alpha channel, originally an effect feature | S1, `analysis/PRIOR_ART.md:36` |

Not in the game: a G-buffer. The plan's open phrase "G-buffer or forward" resolves to **forward+ with a depth
prepass**; there is nothing to hook for deferred material data, which is why the live path reads bound textures and
constant buffers (`analysis/MATERIAL_INPUTS_SLOTS.md`, `analysis/PBR_MAPPING.md`).

---

## 4. (a) Particles and effects

### What is known

1. **The main effects are not alpha blended. They are dithered cutouts.** S1, verbatim: 「エフェクトといえば半透明のため
   描画負荷が高いというのが特徴でもあるが、本作ではディザによる抜きを利用して不透明で描画することで処理負荷の軽減を図っている。
   ディザだとドット感が気になりそうだが、抜き具合の調整とポストエフェクトのブルームにより目立たないようにしている」
   — transparent effects are expensive, so they are drawn **opaque** with a **dither mask**, and the dot pattern is
   hidden by the **bloom**. The article shows three images: alpha-blended flame, dither-only flame, bloom-applied flame.
   **VERIFIED as the author's statement about fire/explosion effects.** How far it generalises to every effect draw is
   **UNVERIFIED** (bullets and glows are plausibly still additive).
2. **Budgets:** 1500 effect instances total, of which at most 700 may be "sub-effects" (low-priority parts such as
   sparks) — S1.
3. **Bullets are not billboards of a texture:** a compute shader renders the shape into 3D first, then it is instanced
   onto round plates ("コンピュートシェーダを使用しいったん3D空間上で描画してから丸い形状の板にインスタンシングで描画").
   Up to 4 bullet patterns can be mixed; each bullet also draws a fake round shadow sprite to give depth cues — S1.
4. **Effect authoring is data-driven per model/background:** `.eff` files hold numbered records (`core.eff 092/093/094/095`
   weapon rings, `096` shockwave sphere, `pl000f.eff 500` berserk glow, `wp0075.eff 001-015` weapon rings/dash, `bg0170.eff
   000` animated flame with embers, `r200.eff 105` storm screen effect) — S9 `effects.md`.
5. **The record itself is an EST:** chunked container with IDs `TRAP` (particle), `EVOM` (movement), `FIME` (emitter),
   `TEX` (texture/frame), `PSSA`, `FVWK`/`FWK`, `EMMV`, `EMFW`, `MJSG`, `MCJM`. Named fields in the public template:
   per-particle `effect_length`, `anchor_bone`; per-emitter `spawn_area_width/height/depth`, `move_speed_*`, `red/green/
   blue/alpha`, `fadeInSpeed`, `fadeOutSpeed`, `effect_size_limit_1..4`, `angle`, `scale1..3`; per-texture
   **`distortion_effect_strength`**, `brightness`, `texture_file_id`, `mesh_id` (particles can be meshes),
   `is_single_frame`, `video_fps_maybe`; `FWK` has `particle_count` ("max 1024"), `center_distance`, `edge_fade_range`.
   — S9 `NierA_EST.bt:30-160`; S10 shows the same chunk IDs in Bayonetta 2, i.e. a Platinum-wide format family.
6. **Distortion is a per-particle number, and it needs the scene colour:** the EST field is named
   `distortion_effect_strength` (S9). In the capture, the game keeps a **scene colour copy** (`T2781`) and later
   transparent draws read it — `analysis/SCENE_DOMAIN_INVENTORY.md:36-38` — which is the buffer a refraction/distortion
   shader would sample. Whether those specific draws are the distortion ones is **UNVERIFIED**.
7. **Effects run at half resolution with their own depth buffer:** viewport 1720x720 → `T4826` RGBA8 + `T4827` D24S8,
   then composited into the scene — `analysis/SCENE_DOMAIN_INVENTORY.md:35-36`. A depth buffer being present in the
   effect pass means soft, depth-faded particles are possible; the EST `edge_fade_range` / `center_distance` fields
   suggest a camera-centred fade **UNVERIFIED**.
8. **Depth is bound to effect shaders:** `g_ZTexture` (t13, 2618 shaders), `g_Z_Tex` (t1/t6/t13), `g_Opacity_Tex` — so a
   soft-particle term is obtainable — `analysis/SHADER_DECLARATIONS.md:22`.
9. **The effect parameter system is indexed, not per-draw constants:** `EffectParameterIndex` cbuffer (4879 shaders),
   `g_EffectPixelCommonBuffers` (t27, 4641), `g_EffectPixelCategoryBuffers` (t30, 3570),
   `g_EffectPixelProjectionBuffers` (t28, 459) — `analysis/SHADER_DECLARATIONS.md:34-36,70`. This is how the `.eff`/`.est`
   data reaches the shader.
10. **The effects family reads no lights and writes one output**, and its slot 4 is a **UV distortion map** while the mask
    is an alpha-dissolve term — `analysis/PBR_MAPPING.md:12,38`. This agrees with S1's dither claim and with S9's
    distortion field: the "dissolve" is the dither.
11. Platinum's later title (not NieR) adds per-particle point-light evaluation — S11. Treat as house style, not evidence
    about NieR.

### What remains unknown

* The **blend state and render target of each individual effect shader** in NieR. Nothing public lists them; only the
  capture can (the proxy already records `blend_src`/`blend_dest`/`depth_write`, `checks/live_capture.h:1700-1725`).
* Whether soft particles fade against `g_ZTexture` in NieR, or the fade is only the `FWK` camera-distance/edge term.
* What `PSSA`, `FVWK`, `EMFW`, `MJSG`, `MCJM` chunks mean (S9's own template leaves them as byte blobs).
* Whether distortion is a separate pass or a per-particle branch inside the particle shader.

---

## 5. (b) Sky

### What is known

1. **The sky/background is drawn before the main scene** into its own colour and depth targets: dump entries 4627-4647
   "background/sky-style passes" writing `T2773` + `T2774` D24S8, `T3902`, `T3904`, immediately before the main scene at
   4648 — `analysis/SCENE_DOMAIN_INVENTORY.md:32-33`.
2. **There is a background texture slot** (`g_BgTexture`, t10, 799 shaders) plus a background cube (`g_ElevatorCube`, t29,
   646) and a cube array for reflections (`g_CubeTexArray`, t18, 2427) — `analysis/SHADER_DECLARATIONS.md:19,26,28`.
3. **Fog is a LUT pair applied per material, not a sky model:** `g_FogLUT` (t12) and `g_BeforeFogLUT` (t19) are bound on
   4348 shaders each — `analysis/SHADER_DECLARATIONS.md:21,27`; "slots 12 and 19 are fog LUTs ... these are bound on
   nearly every draw" — `analysis/MATERIAL_INPUTS_SLOTS.md:20`. So the sky colour that a pixel sees through fog comes out
   of a 256-entry-style LUT indexed by depth/height, and every material is graded by it.
4. **Clouds are geometry:** LodMod has a filter entry commented 「don't enable shadows on cloud layer during intro
   section」 applied to the model name `landscape` — `LodMod.ini:1439`, i.e. a cloud layer is a mesh that would otherwise
   cast shadows. So the sky is at least partly **dome/plane meshes with textures**, not a procedural atmosphere.
5. **Ambient lighting does not come from the sky model.** S2: static objects get GI from Enlighten probes; dynamic
   objects (characters) get indirect from **per-area cubemaps** ("エリアごとのフィールドの景観に応じたキューブマップを参照する
   ことで、キャラクターなどの動的オブジェクトも間接光の影響を受ける"). The same article's A/B/C/D comparison set is
   exactly "GI on/off × cubemap-in-cubemap on/off", which confirms that the cubemap is a separate, hand-placed input.
6. The capture has **256² environment cube faces and a 1024×1 LUT** — `analysis/SCENE_DOMAIN_INVENTORY.md:18` — i.e.
   prefiltered specular IBL plus a BRDF LUT, consistent with `g_CubeTexArray` + roughness-driven mip
   (`analysis/PBR_MAPPING.md:14`).
7. No public source describes a Rayleigh/Mie atmosphere, a scattering LUT, or a sky radiance model for NieR. The
   "light scattering" pass in FAR (S4) is **screen-space god rays** from the sun, not atmosphere.

### What remains unknown

* Which shader draws the sky and whether it is a dome, a full-screen quad, or a box: no shader names are public (the WMB
  material list in S8 contains no `Sky` shader, so the sky is engine-side, not a model material).
* Whether the sky texture is a cubemap or a 2D panorama (the `g_BgTexture` name plus the separate sky colour/depth targets
  suggest 2D; **UNVERIFIED**).
* Whether the cube faces are rendered from the sky per frame or captured once per area (**UNVERIFIED**; S2's phrasing
  "エリアごと" suggests per area).

---

## 6. (c) Water

### What is known

NieR has **three water material shaders**, `Wtr00_XXXXX`, `Wtr01_XXXXX`, `Wtr02_XXXXX` (S8), with these parameters
(names are the game's own; the same dump is the source NieR2Blender uses to rebuild materials):

| Parameter | Wtr00 | Wtr01 | Wtr02 | Meaning (inferred from the name) |
| --- | --- | --- | --- | --- |
| `g_ReflectionIntensity` | yes | yes | yes | specular/reflection weight |
| `g_RefractBlend`, `g_RefractStregth` (sic), `g_RefractDepthTest` | yes | – | yes | refraction blend, strength, depth test toggle |
| `g_FresnelExpU`, `g_FresnelExpV` | yes | yes | yes | Fresnel exponent pair (two-lobe or UV-anisotropic) |
| `g_TranslucentStrength`, `g_TranslucentPow` | yes | yes | yes | wrapped/translucent diffuse term |
| `g_NormalTile1/2`, `g_Normal_Animation1/2`, `g_NormalTexSpeed1..3` | yes | – | yes | two scrolling normal maps |
| `g_DetailNormalTile1/2`, `g_DN_Animation1/2` | – | yes | – | detail normals (Wtr01 variant) |
| `g_CamToSurfaceNearZ/FarZ`, `g_CamToSurfaceFogColor_XYZ` | yes | – | yes | fog between camera and surface |
| `g_SurfaceToBottomNearZ/FarZ`, `g_SurfaceToBottomFogColor_XYZ` | yes | – | yes | **underwater** fog below the surface |
| `g_OpacityMode`, `g_Priotiry` (sic) | yes | – | yes | sorting/blend mode and priority |
| `g_Anisotropic`, `g_UseLightMap`, `g_UseOcclusionMap`, `g_UV2Use`, `g_WetMagAlbedo`, `g_WetConvergenceGlossiness` | yes | yes | yes | shared with other materials |
| `g_UseEnvWet`, `g_DetailNormalTile*`, `g_NormalReverse` | – | yes | – | Wtr01 = the "wet surface" variant, no refraction |

S8: https://github.com/WoefulWolf/NieR2Blender2NieR/blob/master/dump.json (16 shader entries, `Variables` arrays).

Interpretation, and what is **UNVERIFIED**:

* A named `g_RefractDepthTest` means the refraction path samples something with a depth compare — most likely the scene
  colour copy with a depth rejection so that geometry in front of the water is not smeared. **UNVERIFIED** which buffer.
* The water reflection is **most likely IBL from the area cube array** (`g_ReflectionIntensity` + `g_CubeTexArray` on
  nearly every material, `analysis/SHADER_DECLARATIONS.md:26`) rather than planar or SSR: the frame inventory contains
  no mirrored-camera pass and no separate reflection RT (14 native + 5 half-res + 1 quarter-res targets, all accounted
  for by depth/HDR/AO/particles/fog — `analysis/SCENE_DOMAIN_INVENTORY.md:12-18`). **UNVERIFIED**: absence of a mirror
  pass in two dumps is not proof, and water areas (Flooded City) were not in those dumps.
* No public documentation of NieR water exists at all (no article, no mod notes). Everything above is name reading.

---

## 7. (d) Emission and bloom

### What is known

1. **Bloom is the repair mechanism for the dither**, by the developer's own description (S1, quoted in §4.1). Any
   replacement that gets the dither right but drops the bloom will show the dither pattern.
2. **Bloom is a fixed 800x450 → 50x28 pyramid in R11G11B10F**, independent of render resolution; the smallest level is
   read by a compute shader and controls the whole-screen white level (S4 `nier.cpp:1161-1173`, `1197-1223`). Consequence
   for us: **at 3440x1440 or 2880x1800 the game's own bloom is soft and low-frequency** — a truth pair captured from the
   game carries that blur, and a Remix bloom that is sharper will not match it.
3. **Per-material emission is not a named parameter.** None of the 16 material shaders in S8 has an `g_Emissive*`
   variable. Instead:
   * `PBS20_XXXXX` has `g_AddBlend`, `g_MulBlend`, `g_SubBlend`, `g_GlossinessSP`, `g_MetallicSP`,
     `g_PatternHilightColor_XYZ`, `g_PatternHilightRange`, `g_PatternImpactRange`, `g_PatternBlendFallOff` — a
     pattern/impact glow layer driven by blend modes.
   * `CNS00_XXXXX` is unlit: `g_Intensity`, `g_InvalidFog`, `g_UseMultiplicationBlend`, `g_UseSubtractionBlend`,
     `g_UvAnimation_X/Y`, `g_Tile_X/Y`, `g_bAlbedoOverWrite`, and it deliberately has **no** `g_AmbientLightIntensity`,
     `g_LightIntensity`, `g_Metallic`, `g_Glossiness` — i.e. a pure blended overlay material (glows, beams, decals).
     Source: S8 `dump.json`.
4. **A2's berserk glow** is vertex-colour driven with an animation-controlled threshold and an additive blend, colour
   from a texture — S1 (「頂点カラーで赤熱しやすさを設定しており…しきい値を調整して加算ブレンドしている」). Eve's spreading
   tattoos use the same vertex-colour threshold trick against albedo — S1.
5. Ambient/emissive interplay: characters are estimated separately from scene exposure, and characters deliberately do
   **not** receive direct light from fixed point lights, only the Enlighten indirect (S2) — see §11 for why this matters
   for grading.

### What remains unknown

* Whether the live (non-WMB) shaders carry an emissive constant. `analysis/PRIOR_ART.md:62` proposes emissive from the
  pixel-shader constant buffers; nothing in the public material dump names such a parameter, so that idea is
  **UNVERIFIED** and should be re-derived from the shader disassembly, not assumed.
* Which emissive path the game's lamps and signs use (CNS00 overlay vs. PBS20 pattern vs. a lit material with a black
  albedo and high `g_LightIntensity`).

---

## 8. (e) Hair, cloth and skin

### What is known

`Hair01_XXXXX` (S8) has, beyond the shared set:

* `g_AnisoLightMode`, `g_AnisoLightMode2` — **two anisotropic light modes**, i.e. two independent anisotropic lobes/enable
  flags.
* `g_Anisotropic`, `g_Anisotropic_X`, `g_Anisotropic_Y` — anisotropy amount plus a 2D anisotropy direction/tangent
  control.
* `g_SpecShift`, `g_SecondarySpecShift`, `g_SecondaryGlossiness`, `g_SecondaryMetalic` — primary and secondary specular
  with independent gloss and metalness: a classic two-lobe shifted-specular hair model.
* `g_FuzzExponent`, `g_FuzzMaskEffective`, `g_bDispNoise`, `g_NoiseTile_X/Y` — a fuzz/rim term with an exponent and a
  noise-masked variation.
* `g_HilIghtIntensity`, `g_EnvRoughnessHosei` ("hosei" = correction), `g_ReflectionIntensity`, `g_1BitMask`,
  `g_DetailNormalTile_X/Y`, `g_UseDetailNormalMap`, `g_NormalReverse`.
* Wetness: `g_ObjWetStrength`, `g_UseObjWet`, `g_WetMagAlbedo`, `g_WetConvergenceGlossiness`,
  `g_WetConvergenceHLI`, `g_WetConvergenceSecondaryGlossiness`, `g_WetMagNoiseTile_X/Y`.

`CLT00_XXXXX` (cloth: velvet/satin) shares the anisotropic and fuzz set and adds `g_FuzzColorCorrection_XYZ`, `g_FuzzMul`,
`g_FuzzReverse`, `g_FuzzShadowLowerLimit` (fuzz is suppressed in shadow), `g_WetConvergenceMetalic`. S1 says the cloth
shader is "PBR plus fuzz plus anisotropy" and that cloth and hair shaders expose a **wet fuzz value**: 「クロスシェーダや
ヘアシェーダは濡れた際のファズの値なども設定可能」.

`SKN00_XXXXX`/`SKN01_XXXXX` (skin) have `g_rho_s`, `g_TransMissionColor_XYZ`, `g_OcclusionColor_XYZ`,
`g_bDispCurvature`, `g_bUseCurvatureMap`, `g_tuneCurvature`, `g_bDispSpecular`. S1 says skin uses **screen-space
subsurface scattering, deliberately strong**: 「SSSSSは強めにかけると蝋人形のような質感になりますが、本作ではその方が世界観に
合っていると判断してわざと強めにしています」.

`Eye00_XXXXX` has `g_ParallaxStrength`, `g_GlossinessIris`, `g_MetallicIris`, `g_LightIrisIntensity`,
`g_AddEnvCubeIntensity`. S1: the eye is a dedicated shader with a **multiply-blended semi-transparent shadow layer** over
it (「半透明のシェーダを乗算ブレンドで被せている」) so the iris reads as recessed.

### What remains unknown

* The actual BRDF. The names fit a Kajiya-Kay or a two-lobe shifted-tangent model with a Charlie-like fuzz, but the
  exponents and the shift direction are **UNVERIFIED**; they must come from the shader disassembly or from matching
  renders.
* Whether `g_AnisoLightMode*` select between models or are just toggles (**UNVERIFIED**).
* How the game composites SSSSS (kernel, thickness source). Only the material switch names are public.

---

## 9. (f) Time of day

### What is known

1. **There is no day/night cycle and no dynamic weather.** The game is permanently day in every outdoor area; the
   community explanation (and the reason the sun never moves) is that the Earth in this setting is tidally locked —
   S12 (community, not a developer statement).
2. **The fixed sun is measurable and identical across captures:** PS CB2 byte 0 = directional RGB `(6.0, 5.1, 4.8)`,
   byte 16 = unit surface-to-light vector `(-0.4291814, 0.8386706, -0.3353132)`, in both `frame_23275488` and
   `frame_30632051`, from two different areas — `analysis/SUN_LIGHTING.md:14-18`.
3. Everything that looks like "different time of day" is per-area lighting authored with Enlighten probes and per-area
   cubemaps, plus fog LUTs and exposure (S2, `analysis/SCENE_DOMAIN_INVENTORY.md:31`), not a clock.
4. Weather is scripted: `r200.eff 105` "storm onscreen effect" and rain/wet-status handling in S9/S1 (8-step wet level
   driven by 7 nulls from feet to head, plus splash events).

### Where night exists

* Lore only: "Kingdom of Night" is a place name, not playable in Automata.
* In practice the dark scenes are **interiors and special maps**: the abandoned factory, the Bunker, caves, the Copied
  City (white, no sky, no sun), and scripted story beats. There is no outdoor night.
* An in-game **debug menu** exists and can be unlocked (S: https://github.com/Aemony/NieRAutomata_Chapter_Select_Debug_Mode_Unlocker,
  free camera: https://github.com/Spl3en/NierAutomataFreeCamera). Whether it can override lighting/time/exposure is
  **UNVERIFIED** — worth checking before assuming a "night capture" is impossible.

**Consequence for the plan:** item W4 ("Emission — Needs a night capture") is blocked by a game design fact, not by
scheduling. The reachable substitutes are (a) a dark interior map, (b) the Copied City, (c) if the debug menu exposes
lighting, a forced setup.

---

## 10. Material shader names and their parameters

The complete public list of WMB material shaders (S8 `dump.json`) — 16 entries:

| Shader | Kind | Distinguishing parameters (beyond the shared set) |
| --- | --- | --- |
| `PBS00_XXXXX` | standard PBR | `g_Metallic`, `g_Glossiness`, `g_DetailNormalTile_X/Y`, `g_Tile_X/Y`, `g_UseLightMap`, `g_UseEnvWet`, `g_ObjWetStrength`, `g_Decal` |
| `PBS10_XXXXX` | PBR, 3 blend layers | `g_Glossiness1..3`, `g_Metallic1..3`, `g_MaterialTile1..3`, `g_InterpolationRate`, `g_UseVertexAlpha_B` |
| `PBS11_XXXXX` | PBR, 2 layers + animated detail normals | `g_DN_Animation1/2`, `g_UvAnimation1/2`, `g_Glossiness1/2` |
| `PBS20_XXXXX` | PBR + pattern glow | `g_AddBlend`, `g_MulBlend`, `g_SubBlend`, `g_PatternHilightColor_XYZ`, `g_PatternHilightRange`, `g_PatternImpactRange`, `g_GlossinessSP`, `g_MetallicSP` |
| `Gls00_XXXXX` | glass | `g_FresnelExpU/V`, `g_RefractBlend`, `g_RefractStregth`, `g_HLC_EffectiveCube`, `g_HiLightCubeIntensity`, `g_EnvEffectiveRange`, `g_bOffSceneCube`, `g_TranslucentStrength/Pow`, `g_SFParticleIntensity` |
| `Wtr00/01/02_XXXXX` | water, 3 variants | see §6 |
| `SKN00/01_XXXXX` | skin | `g_rho_s`, `g_TransMissionColor_XYZ`, `g_OcclusionColor_XYZ`, `g_bDispCurvature`, `g_bUseCurvatureMap` |
| `Hair01_XXXXX` | hair | see §8 |
| `CLT00_XXXXX` | cloth | aniso + fuzz + `g_FuzzColorCorrection_XYZ`, `g_FuzzShadowLowerLimit` |
| `Plt00/01_XXXXX` | plant | `g_SwingHeightCycle`, `g_SwingPower`, `g_SwingSpeed`, `g_Tickness` (vertex wind) |
| `CNS00_XXXXX` | unlit blended overlay | `g_Intensity`, `g_InvalidFog`, `g_UseMultiplicationBlend`, `g_UseSubtractionBlend`, `g_UvAnimation_X/Y` |
| `Eye00_XXXXX` | eye | `g_ParallaxStrength`, `g_GlossinessIris`, `g_LightIrisIntensity`, `g_AddEnvCubeIntensity` |

**Shared by all 16:** `Binormal0`, `Color0`, `Normal`, `Position`, `Tangent0`, `TexCoord0/1`, `g_AlbedoColor_XYZ`,
`g_IsSwatchRender`, and — importantly — a **three-light material model**:
`g_LightColor0_XYZ`, `g_LightColor1_XYZ`, `g_LightColor2_XYZ` with `g_LighIntensity0/1/2` (sic), plus a master
`g_LightIntensity` and `g_AmbientLightIntensity`. So characters/props are lit by **three analytic lights at material
level plus ambient**, on top of the tiled forward light buffers. Which three they are (sun + 2 fill? per-instance?)
is **UNVERIFIED**.

---

## 11. Cross-check against the repository's own notes

| Claim here | Local note | Verdict |
| --- | --- | --- |
| Forward+ with tiled light lists (S1) | `g_PointLightAryBuffer` t20 + `g_PerTileLightIndexBuffer` t21 (`analysis/SHADER_DECLARATIONS.md:46-56`), screen-tile compute pass (`analysis/SCENE_DOMAIN_INVENTORY.md:29`) | **Agrees.** Describe the renderer as forward+, not as "forward or deferred" |
| AO at quarter resolution, HZB input, H+V blur (S4/S6/S7) | No local number (grep for `800x450` in `analysis/*.md` finds nothing outside `runtime/`) | **New.** The repo has never written the fixed 800x450 / bloom-pyramid sizes down; add them, they explain quality differences against the game's own frame |
| Bloom pyramid fixed at 800x450…50x28, white level by CS (S4) | Local only knows `g_AverageBrightnessBuffer` on 17 shaders (`analysis/SHADER_DECLARATIONS.md:41`) | **Agrees and adds detail** |
| GI = Enlighten, compute over light volumes, 128 workgroups (S2/S4/S5) | Local notes have no GI model at all | **New axis.** The path tracer replaces it outright; the game's GI is the thing that makes shadowed areas light |
| Characters receive only *indirect* from fixed point lights, no direct (S2) | `analysis/SUN_LIGHTING.md:14-18` treats the sun and the point/spot arrays as the light set | **Conflict of intent worth stating:** reproducing the game's lighting literally means *not* giving characters direct light from some point lights. A path tracer that adds them will light 2B differently from the game — a grading risk for W2/W5 |
| Effects are dithered-opaque cutouts repaired by bloom (S1) | `analysis/PBR_MAPPING.md:12` ("the mask is an alpha-dissolve term"), slot 14 = `g_DitherTex` on 1542 shaders (`analysis/SHADER_DECLARATIONS.md:23`) | **Agrees, and contradicts PLAN_2026-11-14.md's framing.** E1 says effects "reached Remix as solid cutout geometry" and proposes compositing the game's draws as the exact-look route. In the game most of them *are* cutout geometry, with a dither mask and a bloom; what is missing in Remix is the **dither pattern and the bloom**, not only the blend |
| Distortion reads a scene colour copy (S9 + `analysis/SCENE_DOMAIN_INVENTORY.md:36-38`) | Plan E1 direction 1 assumes the same | **Agrees** (still inference: which draws) |
| Water: `g_Refract*`, `g_ReflectionIntensity`, Fresnel, two scrolling normals, under-surface fog (S8) | `analysis/MATERIAL_INPUTS_SLOTS.md` has no water entry; the plan's W3 is "replay picture against the game's" with no model | **New.** W3 can be designed from named parameters instead of trial and error |
| Hair: two-lobe anisotropic + fuzz + wet params (S8, S1) | Plan W5 is "approximate the game's anisotropic silver — user's look decision" | **Agrees, and gives the parameter inventory to approximate** |
| No night, fixed sun (S12, `analysis/SUN_LIGHTING.md`) | Plan W4 is "blocked on data: needs a night capture" | **Contradicts the plan's unstated assumption that night is reachable by playing.** There is no night outdoors |
| Emissive from PS constant buffers (`analysis/PRIOR_ART.md:62`) | — | **No named emissive parameter exists in the public material dump**; the emission paths that are documented are blend modes (`CNS00`, `PBS20`) and vertex-colour thresholds (A2). Treat "emissive constant" as UNVERIFIED |
| MSAA 8x native (S3) | Not recorded locally | **New.** MSAA + forward means the effect/AA interaction (and the engine's own "shade once per pixel" option) is a known area |
| Executable is 32-bit (S3) | `analysis/PRIOR_ART.md:14` already reasons about 32-bit hosts | **Agrees** |

Also worth noting for the plan's `C3`/version questions: the AO buffer format changed between the 2017 and 2021 builds
(`R8G8B8A8_UNORM` vs `R8_UNORM`) and FAR only supports the 2017 build (`AOFixes.cpp:66-70`, `README.md` "PSA:
Incompatibility with the latest versions of the game"). Know which build the laptop runs before using FAR numbers as
absolute.

---

## 12. Open questions

1. **Which effect draws are dithered-opaque and which are genuinely blended?** Determined by: the capture already
   records blend state per draw (`checks/live_capture.h:1701-1725`); build a table shader-hash → blend → target → count
   for the camp and desert captures. No web source will answer this.
2. **Does NieR fade particles against `g_ZTexture`?** Determined by: disassembling an effect pixel shader that binds t13
   and looking for a soft-fade compare; the repo has `analysis/checks/dxbc_disasm.cpp` and 13,715 shader blobs.
3. **What is the sky, exactly?** Determined by: dumping the shaders of the entries 4627-4647 in a frame capture
   (`analysis/framedump-capture/`) and reading the pixel shader's texture declarations and constants; or by matching the
   camp capture's sky draws to `rtx.skyBoxGeometries` hashes.
4. **Water reflection method.** Determined by: a capture in the Flooded City or at the oasis, checking for a mirrored
   camera pass or for reading of `T2781` (scene copy) by the water shader, and by reading `g_ReflectionIntensity`
   values from the material constant buffer.
5. **What the three material lights (`g_LightColor0..2`) are.** Determined by: reading the material cbuffer for those
   three slots per draw and comparing against the verified sun bytes and the point/spot arrays.
6. **Whether the debug menu can override lighting/exposure/time.** Determined by: one run with the debug menu unlocked,
   looking for a lighting or "Sky/Env" section. Would unblock W4 if yes.
7. **Which build the laptop runs (2017 vs 2021).** Determined by: file hash / version of `NieRAutomata.exe` on the
   laptop, compared with the LodMod `GameVersion` enumerations (`SDKEnums.h`).
8. **The BRDF of `Hair01`.** Determined by: disassembly of the hair pixel shader (tangent shift, exponent, fuzz term) or
   by fitting renders against candidate models.

---

## 13. Recommended steps for the plan

1. **Record the fixed effect-buffer sizes in the repo, once.** Add a short "the game's own post chain" table (800x450 AO
   + HZB, 800x450…50x28 bloom, 1720x720 particles, 860x360 quarter downsample) to
   `analysis/SCENE_DOMAIN_INVENTORY.md`, citing `nier.cpp:1161-1173`, `nier.cpp:1240-1246`, `LodMod.ini:57` and
   `analysis/SCENE_DOMAIN_INVENTORY.md:31-38`. Checked by: the file lists a source line for every number.
2. **Build the effect inventory table before writing any effect code.** New file `analysis/EFFECT_INVENTORY.md`: one row
   per effect pixel shader from the camp and desert captures — shader hash, blend src/dst, depth write, render target,
   draw count, whether slot 14 (`g_DitherTex`) is bound, whether t13 (`g_ZTexture`) is bound. Source data: the existing
   `remix: shader ... effect=` log lines and the capture metadata the proxy already records
   (`checks/live_capture.h:1414-1453` for the shader flag, `1697-1699` and `1721-1728` for the two places a draw is
   dropped, `1704` for the blend/depth state it already inspects). Checked by: the row count equals the number of distinct
   effect shaders the log reports, and each row names its capture.
3. **Test the "cutout + dither + bloom" route for effects, not only compositing.** Add a switch
   `NIER_REMIX_LIVE_EFFECT_DITHER=1` next to the existing `NIER_REMIX_LIVE_EFFECTS` handling
   (`checks/live_capture.h:591,1693-1699`, `remix_live.cpp:259`) that (i) keeps the effect draws, (ii) sends the dither
   mask (slot 14) as the material's alpha for `alphaTestType`, (iii) sends `emissiveIntensity` scaled by the effect's own
   brightness where a constant is available. Gate first: new `analysis/checks/test_live_effect_dither.py` on the fake
   runtime asserting `cutout=true`, slot 14 captured, and the draw not dropped; run it against the unmodified build to
   see it fail for the right reason.
4. **Keep the composite-over-Remix route as the fallback and scope it as second.** It needs depth-tested replay of the
   1720x720 particle pass plus the scene-copy readers; the inventory from step 2 tells you how many draws that is before
   any code is written.
5. **Sky (W1): decide dome vs. texture from data, not from the picture.** In the camp capture, list the draws of dump
   entries 4627-4647 (`analysis/framedump-capture/`), their vertex counts and their textures; if it is one dome with one
   texture, implement it as a Remix sky texture (`rtx.skyBoxTextures`) and use `rtx.skyProbeSide` so the sky also feeds
   indirect; if it is several layers, tag each. Checked by: the Remix log shows the sky geometry classified as sky and the
   camp numbers against the game's frame move in the right direction.
6. **Ambient from the environment cube, not from the sky.** Add the per-area cube (`g_CubeTexArray`, t18,
   `analysis/SHADER_DECLARATIONS.md:26`) to the material mapping as the IBL source, and write the game's own
   `g_AmbientLightIntensity` value next to it in `analysis/MATERIAL_INPUTS_SLOTS.md`. Checked by: a camp A/B with the
   game's frame at the same camera.
7. **Water (W3): write the parameter table into the plan before rendering.** Put the §6 table into the plan item, then
   build the water material from `g_Metallic`/`g_Glossiness`/`g_ReflectionIntensity` (constant roughness from the material
   cbuffer, not a guess), two scrolling normals, and depth-based tint. Checked by: replay `frame_67078468` against the
   game's frame at the same spot with the same still camera.
8. **Hair (W5): the approximation target is a two-lobe model with a fuzz term.** Specify: primary + secondary anisotropic
   lobes with independent gloss (`g_Glossiness`, `g_SecondaryGlossiness`), a tangent shift (`g_SpecShift`,
   `g_SecondarySpecShift`), a fuzz exponent (`g_FuzzExponent`) and a wet-gloss shift (`g_WetConvergence*`). This gives
   the user a concrete A/B sheet. Checked by: one still frame of 2B's head, before/after, at the camp.
9. **Emission (W4): turn it into an interior task and unblock it.** Replace "needs a night capture" with "needs one
   capture in a dark interior (factory / Bunker) and one in the Copied City"; add the debug-menu lighting check
   (open question 6) as a 10-minute experiment before assuming it is impossible. Checked by: the plan item has a named
   location and a named capture id.
10. **Correct the plan's description of what the game's effects are.** In E1, replace "effects reached Remix as solid
    cutout geometry" with "the game draws most effects as dithered cutouts repaired by bloom, and our proxy drops them by
    their effect buffers (t27/t30)". This changes which route is cheapest, so it must be in the plan text, not only in a
    research file.
11. **Add the character-lighting caveat to the grading items (W2/W5).** One line: the game gives characters indirect
    light only from fixed point lights, and their base brightness is decoupled from scene exposure (S2), so a physically
    correct Remix render will not match the game's characters by construction; the tolerance must be set per area.
12. **Note the version dependence once.** In `analysis/LAPTOP_PORT.md` or the plan's equipment section: AO buffer format
    and FAR compatibility differ between the 2017 and 2021 builds (`AOFixes.cpp:66-70`, FAR `README.md`), and every FAR
    number in this file describes the 2017 build's fixed-function-era layout assumptions — verify on the actual exe.
