# What NieR's pixel shaders do with each texture channel (2026-11-01)

Read from the game's own shaders (D3DDisassemble of captured DXBC, `analysis/checks/dxbc_disasm.cpp`), not inferred
from texture sizes or formats. Shader sets: 13,715 blobs in `NIER_CAPTURE/shaders` (desktop install) and the 605
main-view shaders of F9 capture `frame_453279156` (`analysis/runtime/laptop-port/live-hyst/capture-meta/shaders`).
Disassembly work dir: `analysis/runtime/pbr-re/` (ignored).

## Two families, and the live path treats both as one

| family (by RDEF names) | main-view shaders | what it is | evidence |
|---|---|---|---|
| `g_ColorTexture` / `g_MaskTexture` / `g_NormalTexture` | 297 | **effects**: particles, smoke, distortion | reads `g_EffectPixelCommonBuffers` (t27) / `CategoryBuffers` (t30), one output, never reads lights; slot 4 is a UV-distortion map, the mask is an alpha-dissolve term |
| `g_Texture0..N` with `g_PointLightAryBuffer` (t20) | 134 (93 with `SH`) | **world and character materials, forward-lit PBR** | Burley diffuse (`(1-n·l)^5` terms) + GGX, cube-array reflections at a roughness-driven mip |

`MATERIAL_INPUTS_SLOTS.md` concluded "slot 4 is the normal map" from the named family's `g_NormalTexture`. For the
world materials that is wrong: see below.

## Generic lit family, the three largest variants (`ps_1874571568`, `ps_1872570064`, `ps_1840406672`)

| slot | role | evidence |
|---|---|---|
| 0 | albedo; alpha < 0.8 discards | × per-instance tint (cb4 × cb8[instance]) × screen-space AO (t17) |
| 1 | sampled with the **second** UV set (`v1.zw`); multiplies the colour under a flag | lightmap/AO style; not yet pinned |
| 2 | mask: **R = metalness**, **G = gloss** (roughness = 1 − G), A = detail-normal weight, B = unknown (× `t1.y` under a flag) | diffuse × (1 − R); F0 = lerp(0.03, albedo, R) (also 0.08); α = (1 − G)²; G and R each overridable by a constant (cb1[5].x / .y) |
| 3 | **normal map**, tangent space, RGB centred on 0.5 (default (0, 0, 0.5) when absent) | N = x·T − y·(N×T) + z·N (sign of y: green points along −bitangent) |
| 4 | **detail normal**, 2 channels, ×2 − 1, own tiling (cb1[2].xy), weighted by mask A | added to the main normal's xy |

## Variants differ

`ps_550294968008` (generic, lit, with an `SH` cbuffer, main view): F0 = lerp(0.03, albedo, **t1.x**) and roughness from
**t1**, not t2. Channel roles move between shader variants, so a fixed slot→role table cannot be right for every draw.

## Consequence for the live path

- The normal map sent for world geometry is the **detail normal** (slot 4), not the normal map (slot 3 in the main
  generic variants).
- Metalness and roughness are never sent (constant roughness 0.6); they are in the mask, per variant.
- Effects-family draws reach Remix as cutout world geometry; their slot 4 is a distortion map, not a normal.
- The robust mapping is per pixel shader: trace, in each shader's disassembly, which texture channel feeds the F0
  lerp (metalness), the GGX α (gloss/roughness), the TBN (normal) and the colour (albedo), and key the live material
  on the bound pixel shader.
