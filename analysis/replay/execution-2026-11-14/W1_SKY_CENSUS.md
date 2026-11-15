# W1.1 sky-candidate census — 2026-11-15 (offline)

`NIER_REMIX_LIVE_SKY_CENSUS=1` (default off): one `remix: sky-census <JSON>` record per geometry build with world extent
> 1000 (64/session): PS FNV code, indices/instances, extent, is_sky (existing >5000 rule), PS SRVs with format and
texture size, VS/PS constant-buffer slots and sizes, RT0. Diagnostic only; submissions unchanged.
Gate `checks/test_sky_census.py` v1 210e875f… red "no sky-census records"; v2 c98747df… (v1 archived
`sky-census-gate-v1.py`): v1's "submissions unchanged" oracle compared timing-dependent DrawInstance counts (failed on
restored code) -> now compares created meshes minus run-local hash/key/presented. Mutations
(`runtime/w1-sky-census-mutations.json`): default-on red, CBs-not-recorded red, **wrong is_sky threshold (2000)
SURVIVED** - the mock has no 2000-5000 candidate; gap disclosed. Suite s89 127/127. DLL a176a0bc… (not installed).

## Replay rows (fake runtime, 60 frames; `runtime/w1-sky-census-replays.json`)
| Area | Sky (extent >5000) | Candidates 1000-5000 |
| --- | --- | --- |
| camp | 7 builds, all PS 33856d1d…, extents 8.3k-19k, 165-900 indices | 1 (PS cd8687d6…, 1003) |
| desert | 3 builds, PS 33856d1d…, 18k-19k | 4 (PS 697e111a… x3 terrain-like 41k idx, cd8687d6…) |
| pond | 3 builds, PS 33856d1d…, 18k-19k | 0 |
Every sky draw: one PS (33856d1d…), 6 PS textures t0-t5 (t0 BC? fmt 71/72 256-2048, t3 up to 4096x4096), VS CBs
b0 256/b1 16/b2 48/b5 128/b6 16/b10 368/b11 64/b12 16/b13 32, PS CBs incl. b1 112, b6 144-448, b10 368. Same
CB layout as world draws, so the sky is drawn by a material-style shader, not a dedicated sky pass. Several dome
layers per frame (camp 7) - consistent with plan W1.1 warning that layers need not form one dome.
Next (W1.2): disassemble PS 33856d1d to trace projection, colours and which CB values drive sky colour/exposure.

## Prior-art input (scout 623638fc, `NEW_VEGAS_RTX_SKY_EFFECTS_2026-11-15.md`)
New Vegas RTX drops all game sky draws and uses the fork-only NUMOS sky; upstream path = SKY category rasterized
into the sky cube (our current approach) + `rtx.skyBrightness`. No game sky colour/exposure mapping exists to copy.

## Review / fixes
Reviewer 1271c306 (anthropic/claude-haiku-5-5): OK with notes. Fixed all three P2s: extent printed with 9 significant
digits (no rounding across the 1000/5000 thresholds), non-finite extents skipped (invalid JSON), one
`remix: sky-census-limit` line when the 64-record cap is hit. Gate green; suite s90 127/127.

## W1.2 first trace: sky PS 33856d1d (ps_110908416.dxbc, SHA256 ecd57fe6…)
Disassembly `runtime/w1-disasm/sky_ps.asm` (CPU-only D3DDisassemble under Wine); names from the shader's own RDEF.
- base = `g_Texture0` (t0) sampled at mesh UV + `g_UvOffset` (MeshBuffer1 b3[1], scrolling clouds); replaced by
  `g_AlbedoParam.rgb` (b1[3]) when its w > 0.
- x `g_IntensityParam.y` (b1[1].y) - the sky's own brightness scalar.
- x saturate(`g_AO_Texture` (t17, screen-space at pos / `g_TargetUvParam.zw`) + `g_ShadowParam.z`).
- x `g_MeshColor.rgb` (ModelBuffer b4) tint. Output alpha = t0 alpha (layers blend).
- fog unless `g_BaseBoolParam.w` != 0: factor = pow(saturate((dist(camera `g_CameraVec` b13[1], world pos) -
  g_FogParam.x) * g_FogParam.y), g_FogParam.z) * lut.a; colour = lerp(`g_BeforeFogLUT` t19, `g_FogLUT` t12 cube,
  `g_SpParam.w`) * `g_FogColor.rgb` (b2[7]); result = lerp(base, fog, factor).
Reading: the sky is textured dome layers (UV-mapped, not a lat-long/procedural projection) with per-layer intensity,
tint, AO/shadow mask and cubemap fog. No exposure term inside; colour/intensity come from b1/b4/b2 per draw.
Candidate Remix inputs (unverified): per-layer texture * g_IntensityParam.y * g_MeshColor, horizon from the fog
cubemaps; `g_lightColor`/`g_lightVec` (b2[0..1]) are present in the CB but unused by this PS.

## Correction (2026-11-15, W1.2)
The body above is kept as written; two corrections from `W1_SKY_CB_VALUES.md`: the fog LUT t12/t19 are
declared `texturecube` but every capture stores a single 32x32 face (`texture_capture.h::write_dds` writes
TEXTURE2D/array 1), and this census's own SRV list only ever contains slots 0-15 because
`texture_capture.h::capture` enumerates `PSGetShaderResources(0, 16, views)` — so "no t17/t19" here means
"not captured", not "not bound in the game".
