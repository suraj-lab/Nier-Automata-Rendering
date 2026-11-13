## Scout report: remix-1.6.1 material API, shading, tonemap, sky (agent 3)

**Path legend** (all under `R=analysis/runtime/src/dxvk-remix/`):
RA = `src/dxvk/rtx_render/rtx_remix_api.cpp` · OI = `src/dxvk/shaders/rtx/concept/surface_material/opaque_surface_material_interaction.slangh` · BL = `…/opaque_surface_material_blending.slangh` · IM = `src/dxvk/rtx_render/rtx_instance_manager.cpp` · RC = `analysis/runtime/remix-probe/sample/include/remix/remix_c.h`

**Caveat:** `remix_c.h` is not in the 1.6.1 tree (`include/` has no `remix/`). RC is the nearest copy (API 0.6.6, RC:64-65). Field names match the tree's consumers. Struct layout is unverified against 1.6.1.

### 1. Fields and use

**MaterialInfo (RC:315-331)**
- `albedoTexture`, `normalTexture`, `tangentTexture`, `emissiveTexture`: loaded through `findAsset` and `preloadTextureAsset(…, ColorSpace::AUTO)` (RA:217-222, 271-281). A missing asset silently yields an empty slot, so constants apply.
- `hash`: used directly as the material handle (RA:875-900).
- `emissiveIntensity`: `enableEmission = intensity > 0` (RA:411, 451, 474).
- `filterMode`, `wrapModeU/V`: passed raw as `lss::Mdl` enums (RA:332-334). Filter: Nearest=0, Linear=1. Wrap: Clamp=0, Repeat=1, Mirror=2, Clip=3 (`src/lssusd/mdl_helpers.h:30-50`). Mapped to VkSampler at `rtx_materials.h:2091-2095`. A zero-initialised struct gives Nearest + Clamp.
- `spriteSheetRow/Col/Fps`: raw (RA:~400-420).

**Opaque (RC:235-269; RA:387-441)**
- `roughnessTexture`, `metallicTexture`: used when loaded, `.x` channel (OI:623-624, 831-833, 850-852).
- `albedoConstant`: fallback only. When the albedo texture loads it **replaces**, not multiplies (OI:638, 656-658).
- `opacityConstant`: used only without an albedo texture (OI:639). With a texture, opacity = albedo alpha (OI:674) unless `isFullyOpaque` (OI:39-43).
- `roughnessConstant`, `metallicConstant`: fallbacks (OI:829, 848).
- `anisotropy`: `calcRoughness` (brdf.slangh:104-110).
- `thinFilmThickness_*`, `alphaIsThinFilmThickness`: thin film. Alpha becomes thickness when the flag is set (OI:667-670). Default 200 nm (RA:417).
- `heightTexture`, `displaceIn/Out`: POM, only when displacement is valid (rtx_materials.h:641-645).
- `useDrawCallAlphaState`: when true, blend and alpha state come from `InstanceInfoBlendEXT` (IM:710-760).
- `blendType_hasvalue` → `BlendEnabled`. Blend type defaults to kAlpha; `invertedBlend` (RA:387-441).
- `alphaTestType`: cast from int. **Enum 0 = kNever** (`surface_shared.h:47-48`). With legacy state off, that sets alpha to 0 (BL:58-60) and disables the fully-opaque shortcut (IM:900). A zero-initialised struct therefore yields an invisible surface. `alphaReferenceValue` is the comparison value (BL:48).
- `displaceOut`: only for API ≥0.4.2 (RA:425). DLSS control-mask fields: API ≥0.6.5, otherwise forced true (RA:~437).
- `textureScrollRate/Angle`, `textureScale`, `textureOffset`, `textureRotation` (RC:263-268): **no consumer found** in the tree.

**SubsurfaceEXT (RC:272-287)**: subsurface textures and constants, mapped into the SSS slots (RA:219-226, 388-400). Defaults 0.5 when absent.

**TranslucentEXT (RC:289-306; RA:443-463)**: `transmittanceTexture`, `refractiveIndex`, `transmittanceColor`, `transmittanceMeasurementDistance`, `thinWallThickness` (default 0.001 if unset), `useDiffuseLayer`. Scroll/scale fields unused.

**PortalEXT (RC:308-313; RA:465-480)**: `rayPortalIndex`, `rotationSpeed`. Emission comes from top-level fields.

### 2. Albedo colour space and alpha
- **Format is kept as-is** (`ColorSpace::AUTO`): `rtx_texture.cpp:145-147`. `FORCE_BC_SRGB` is never used by this API.
- **DDS mapping:** legacy DXT1 → `BC1_UNORM` (`include/gli/core/dx.inl:165`). DX10 header → the DXGI format as stored (`dx.inl:166`). BC1 enum values match VkFormat 133/134 after `static_cast` (`rtx_asset_data_manager.cpp:159`; `format.hpp` ordering checked).
- **Shader always decodes:** `pow(x,2.2)` on albedo and emissive regardless of format (OI:750-758; `utility/color.slangh:90,105-107`). The comment says "assuming all textures are not sRGB" (OI:750-752).
  - UNORM sources: one decode, correct for sRGB-encoded art.
  - sRGB-tagged DX10 (BC1/BC3_SRGB): hardware decode plus shader decode. That is a double decode, giving darker, higher-contrast output.
- **Albedo alpha is opacity only** when all of these hold: the albedo texture loaded, the thin-film flag is off, and the surface is not fully opaque. Fully opaque means blend off and alpha test = kAlways (OI:39-43; IM:900). For API materials, blend is on only with `blendType_hasvalue` or legacy state. So BC1/BC3 alpha is ignored by default.
- `IGNORE_ALPHA_CHANNEL` is not set by the API path (`rtx_material_data.h:313` default false).

### 3. Vertex colour
- `color` is B8G8R8A8_UNORM on the colour0 buffer (RA:997; RC:341-353).
- It is used only when a texture-argument source is `VertexColor0` (BL:185-197 macro).
- Defaults in `LegacyMaterialData` (`rtx_materials.h:1879-1884`): arg1 = Texture, arg2 = None (→1.0), op = Modulate. Vertex colour is therefore **unused** by default.
- Blend ext selects sources and ops (RA:830-838).
- Even when used, normalisation by max component (OI:703-713) is gated by `isVertexColorBakedLighting`. Its default is true (`rtx_materials.h:1888`; `rtx_options.h:348`). `vertexColorStrength` = 0.6 (`rtx_options.h:344`).

### 4. Tonemap and exposure defaults
- `rtx.tonemappingMode` = **Local** (`rtx_options.h:1181`). `rtx.useLegacyACES` = true, which over-saturates highlights (`:1186`). `showLegacyACESOption` = false (`:1188`).
- **Local mode** (`rtx_local_tone_mapping.cpp:144`):
  - `rtx.localtonemap.exposure` 0.75 (`rtx_local_tone_mapping.h:70`)
  - `shadows` 2.0 (`:71`), `highlights` 4.0 (`:72`)
  - `finalizeWithACES` true (`:69`), `boostLocalContrast` false (`:67`)
- **Global only** (`rtx_tone_mapping.cpp:123`; `rtx_context.cpp:1950`):
  - `rtx.tonemap.dynamicRange` 15 (`rtx_tone_mapping.h:118`)
  - `toneCurveMinStops/MaxStops` −24/8 (`:114-115`)
  - `shadowContrast` 0, `shadowMinSlope` 0 (`:119-120`)
  - `exposureBias` 0 (`:103`), `tonemappingEnabled` true (`:104`)
  - `colorGradingEnabled` false (`:105`), `contrast`/`saturation` 1 (`:109-110`)
  - `finalizeWithACES` false (`:117`)
- **Auto exposure** (`rtx_auto_exposure.h`): enabled true (`:76`), speed 5 (`:79`), EV range −2…5 (`:80-81`), Median mode (`:84`), center metering off (`:82`).
- **User brightness** = 50, giving 0 EV bias. Range is 3 EV (`rtx_options.h:1277-1279, 1514-1517`).
- **Likely contrast levers** (facts only): local `shadows`/`highlights`/`exposure`, the auto-exposure EV window, and global `dynamicRange`/`toneCurve*`.

### 5. Sky
- A SKY-category API instance gets `CameraType::Sky` (RA:640-648, 798-802).
- **It is hidden from the path-traced scene:** `m_isHidden = true` (IM:1047-1050), then `mask = 0` (IM:1348-1349). Its texture is **not** shown directly, and the material is "only good for capture and replacement" (IM:1046-1048).
- Its transforms use the sky RtCamera (`rtx_scene_manager.cpp:2539-2545`), but it is hidden regardless.
- The game-side sky path (`tryHandleSky` → `rasterizeSky`) is only called from the D3D9 draw path (`rtx_context.cpp:1018`, `:2366`). API instances do not reach it. `rtx_sky.h:84-120`.
- Sky radiance = `skyBrightness × SkyProbe` (`composite.comp.slang:631`; `integrator_indirect.slangh:376`). Defaults: `skyBrightness` 1 (`rtx_options.h:1236`), `skyForceHDR` false (`:1237`), `skyMinZThreshold` 1.0 (`:1241`), `skyAutoDetect` None (`:1242`), `skyReprojectToMainCameraSpace` false (`:1251`).
- Auto-detect and min-Z classification apply to D3D9 draw states (`rtx_types.cpp:551-595`), not to API categories (RA:650-680).
- **Not found:** an API path that fills the sky probe, or a fallback sky colour when no game sky draws exist.

### 6. Emissive
- Opaque emission = `emissiveColorTexture` if loaded, else `emissiveColorConstant` (OI:629-634), sRGB-decoded (OI:758), times `emissiveIntensity` (OI:875).
- Emission is off when intensity ≤ 0 (`rtx_materials.h:914`).
- **Unlit approximation is partial.** Albedo 0 still leaves dielectric F0 = 0.04 specular (brdf.slangh:36, 58-61; OI:867-868). Emission is additive and goes through the tonemapper and auto exposure.
- `isMatte` (zeroes albedo and reflectivity, OI:867-868) is never set on the API path (only `false` at IM:1091). **Not found:** an API route to it.

### Other API-path defaults relevant to symptoms
- Roughness is perceptual, α = r² (brdf.slangh:65-67, 109). `roughnessConstant` 0.6 → α 0.36.
- Metallic = 1 makes albedo the reflectivity and diffuse zero (brdf.slangh:49-61). Metallic read from `.x` of a single-channel texture.
- Zero-initialised struct pitfalls: `alphaTestType` 0 = kNever, `blendType_hasvalue` 0 = blend off, `filterMode` 0 = Nearest, `wrap` 0 = Clamp.