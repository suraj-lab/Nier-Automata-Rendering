# W1.3 step 1b — a textured sky layer is t0 * factor, as a copy of t0 (offline, 2026-11-15)

Scope: W1.3 step 1b of `PLAN_2026-11-14.md`: the textured sky layers (`g_AlbedoParam.w == 0`) of the sky shader read
`base = t0 * g_IntensityParam.y * g_MeshColor.rgb` (`runtime/w1-disasm/sky_ps.asm:24-30`), and Remix's
`MaterialInfoOpaqueEXT.albedoConstant` **replaces** the albedo texture instead of multiplying it
(`replay/research-2026-11-12/remix_material_api.md`), so step 1 left those layers at today's material (t0 at full
intensity, counted `textured`). This step writes the product once per (texture, factor) as its own DDS and names it.
No game run, no DLL install, no package or system change, no GPU: the desktop game folder was not touched.

## What a copy has to be (and the colour space it must be in)
The layer's bytes are sRGB-encoded art. Remix's own albedo shader applies `pow(x, 2.2)` whatever the DDS tag says, and the
live path writes every albedo **untagged** (`remix_live.cpp:89` `albedo_unorm`, `:466-469`), so a UNORM file is decoded
exactly once (`remix_material_api.md`: "the shader **always** applies `pow(x,2.2)` … UNORM sources: one decode, correct
for sRGB-encoded art"). Multiplying the colour that is *rendered* by `f` therefore means multiplying the stored byte by
`f^(1/2.2)`, not by `f`. This was the reviewer's P1 and is now what the code does (`sky_scale.h` `kDecodeGamma`).

A tagged source is refused (counted): only `NIER_REMIX_LIVE_ALBEDO_UNORM=0` produces one, its factor would sit in a
different space, and guessing is worse than keeping today's texture.

## What was built
- `checks/mask_channels.h`: `Source::Bc2`. BC2 is a 16-byte block: 8 bytes of explicit 4-bit alpha (16 nibbles,
  row-major, low nibble first) then a BC1-shaped colour block that **always** interpolates four colours. Alpha is linear,
  never sRGB. Camp's 2048x2048 cloud layers are BC2, which nothing in the repository could decode before.
- `checks/terrain_bake.h`: `read_dds` accepts BC2 (74/75) **only when asked** (`bool bc2 = false`), so the default-on
  terrain bake keeps refusing a BC2 layer exactly as before; it also reports the file's encoding through
  `bool* srgb`, and `dds_bytes` gained `bool srgb = true` (format 29 or 28, re-encoded or passed through).
- `checks/sky_scale.h` (new): `layer_factor` (the shader's `g_IntensityParam.y`, only while `g_MeshColor` is the identity,
  quantised to 1/64, factor 1 = no copy), `file_name` (`sky_<texture id>_<factor in thousandths>.dds`), `scaled_dds`
  (header sanity + `read_dds` + the 1/2.2 gain + a full mip chain, UNORM out), and the `draws`/`copies`/`refused` counters.
- `checks/live_types.h`: `MaterialConstants.albedo_scale` (1 = no copy). It joins `any()` only when set, so every material
  the accepted paths create keeps its key and its hash.
- `checks/live_scene.h`: `State::scaled_paths`/`scaled_copies`, `scaled_path()` (one decode+write per (texture, factor) on
  the worker, memoised in map nodes so the `c_str()` Remix keeps stays valid, `kMaxCopies = 8` successes per session,
  refusals counted and bounded), and one branch in `material_for` that names the copy. `read_whole`/`write_whole` moved up
  unchanged so the sky path can use them.
- `checks/live_capture.h`: the sky branch asks `sky_scale::layer_factor` (instead of always counting `textured`), mixes the
  factor into the surface version (`uv_bits`, the same rule the folded colour uses) and into the content hash, so a
  changed factor rebuilds the mesh and reaches a new material.
- `checks/remix_live.cpp`: the stats line gained `scaled= copies= copy_refused=`.
- `checks/remix_live_fake_runtime.cpp`: `check_on_disk` also covers `sky_*.dds`, so "never name an unfinished file" is
  asserted for the copies too.
- `checks/menu_overlay_mock_game.cpp`: `MOCK_SKY_PS_ANIM_BASE` shifts the animation cycle off factor 1 (the existing case
  is unchanged: the default base is 1).

## Gates (frozen)
1. `checks/test_sky_scale.py` (new, SHA-256 `7bf10fe2…`) — native g++, ASan+UBSan, real files on disk:
   - BC2 from a fixture built **field by field** from the DDS/DX10 header and the BC2 layout (not through
     `dds_bytes`), with hand-computed texels: `c0 < c1` still gives four colours at index 3 (a BC1-style block would give
     transparent black), alpha nibbles 0,1,2,3 then 5 and F, sRGB-tagged BC2 decoded to linear, `BC2_TYPELESS`
     refused, `bc2=false` refused (the terrain bake's behaviour), truncated payload refused, a 6x6 texture keeps its size;
   - the copy: UNORM out, decodes (after the runtime's `pow 2.2`) to the source's colour times the factor, bytes move by
     `f^(1/2.2)`, alpha untouched, a mip chain, a tagged source refused, a cube refused, an 8192x8192 header refused
     before the decode (`plausible_size`), garbage/0/negative/NaN factors refused;
   - `layer_factor`: a textured layer with an identity mesh scales, an albedo override does not, a tinted mesh is refused,
     factor 1 is refused, a factor that quantises to zero is refused, the 1/64 grid, the `sky_<id>_<milli>.dds` name;
   - material: `albedo_scale` 1 submits byte-identical material (path and hash) to no constants at all; a scaled layer
     names `sky_1_500.dds`, whose mip 0 decodes to the layer's colour times 0.5, constant colour 1,1,1, a second ask is the
     same material, and the scaled and unscaled layer are two materials in one state; an unlanded layer is grey, no copy is
     attempted, and the grey material is swapped for the copy under the same hash once the file lands; an unreadable layer
     keeps today's texture and is counted; past the cap the rest keep today's texture and are counted.
2. `checks/test_live_sky_layers.py` (extended, SHA-256 `d445c67c…`) — the fake runtime under Wine. The step-1 cases are
   unchanged (`default`, `zero-parity`, `on-albedo`, `on-unresolved`, `anim`); case 4 became `on-unity` (**w = 0, intensity
   1: today's material byte for byte**, which is what a later default-on change must not disturb); new cases:
   - `on-scaled` (w = 0, intensity 0.5): exactly one material names `sky_1_500.dds` with `aconst` 1,1,1, the file's
     decoded mip 0 is 0.1251 = 0.2501 × 0.5, the world draw keeps `live_1.dds`, counters `scaled=1 copies=1
     copy_refused=0`;
   - `anim-scaled` (w = 0, intensity animated 2→4): `draws=10`, `copies=3`, materials naming `sky_1_2000.dds`,
     `sky_1_3000.dds`, `sky_1_4000.dds` — a factor that changes reaches a new copy, which a version-ignoring path cannot do.

Red before green, in the order it happened: the native gate first failed to compile (`sky_scale.h` absent) and the live
gate failed on the missing `scaled=` counter; the first implementation run then went red on two of the gate's own fixtures
(a wrong string length, and an assertion that expected alpha 1 where the fixture's nibble is 3), both gate bugs. The
reviewer's P1 (below) changed what the gate asserts, not whether it passes.

Mutations, each red, restored byte-identically (verified by SHA-256 before/after; `/tmp/w13b_mutations.py`, temporary):

| mutation | gate | result |
| --- | --- | --- |
| BC2 alpha nibble order swapped | unit | red |
| BC2 alpha byte index transposed | unit | red |
| BC2 colour not always-four | unit | red |
| BC2 accepted without the flag (the terrain bake's default changes) | unit | red |
| BC2 refused even for the copy | unit | red |
| source encoding not reported | unit | red |
| copy re-encoded as sRGB | unit | red |
| copy scaled by the factor, not by its 1/2.2 power | unit | red |
| copy not multiplied at all | unit | red |
| copy without a mip chain | unit | red |
| a tagged source is copied anyway | unit | red |
| a cube source is copied as one face | unit | red |
| no size guard before the decode | unit | red |
| a tinted mesh is scaled too | unit | red |
| factor 1 writes a copy | unit | red |
| factor not quantised | unit | red |
| copy name in hundredths | unit | red |
| material ignores the scale | unit | red |
| the scale is not part of the material key | unit | red |
| no session cap | unit | red |
| the sky draw never asks for a copy | live | red |
| a changed factor does not rebuild the surface | live | red |

## Independent cross-checks
- The BC2 fixture's semantics were verified once against **ImageMagick's own DXT3 decoder** (`convert /tmp/t_bc2.dds
  txt:-`, temporary): texels (0,0)=blue, (1,0)=red, (2,0)=(85,0,170), (3,0)=(170,0,85), alphas 0/17/34/51 — identical to
  the hand-computed values the gate pins, so the fixture is not the decoder's own opinion.
- The colour-space rule is the repository's audited research (`remix_material_api.md` §2, `PLAN_2026-11-13.md` §11.3:
  "the shader **always** applies `pow(x, 2.2)`"), not a new guess.

## Review
Reviewer `anthropic/claude-haiku-5-5`, read-only, verdict **BLOCK** → resolved:
- **P1 (fixed)**: the copy was scaled in the wrong space (`f` instead of `f^(1/2.2)` on sRGB-encoded, UNORM-tagged bytes),
  which on camp's measured intensity 6 would have rendered roughly 8× too bright. Fixed with `kDecodeGamma`; tagged
  sources are now refused rather than guessed; both gates now assert the *decoded* colour.
- **P2-1 (fixed)**: accepting BC2 in `read_dds` changed the default-on terrain bake (a BC2 layer would bake instead of
  staying grey). `read_dds` now takes `bc2 = false`, and the gate pins both directions.
- **P2-2 (fixed)**: a header-only 8192² file allocated ~1 GB before the short-payload refusal. `plausible_size` refuses
  above 4096² pixels before `read_dds` is called; gated directly and end to end.
- **P2-3 (fixed)**: the animated textured path had no live gate, and the cap's fallback was untested. The live gate now
  animates the factor and requires one copy per factor (`copies=3`); the cap is gated natively.
- **P3s fixed**: the cap now counts successes (`State::scaled_copies`) and the refusal memo is bounded; `scaled_path`
  refuses a non-finite or non-positive factor; a copy is skipped when an L3 albedo constant replaces the texture; the
  `late` case now runs `refresh_incomplete_materials` and requires the swap under the same hash; a cube source is refused;
  a partial-block BC2 (6x6) is pinned.
- **P3 recorded, not fixed**: `layer_factor` is not tied to the sky shader's bytecode (same design decision as step 1's
  P2-3: the runtime contract is "a draw the path already classifies as the background shell, whose shader declares these
  three members"); the cost of the copy is not measured live.

## Measurements
- Nothing here runs the game: no fps, memory or GPU numbers. What the copy costs, in the code as written: one
  `read_dds` intermediate of 16 bytes/texel (64 MB at 2048²) on the worker, and a written file of
  `w*h*4*(1+1/3)` ≈ 22 MB at 2048² versus 5.6 MB for the BC2 source (8-bit, full chain). At most `kMaxCopies = 8` per
  session, so ≤ ~175 MB of copies next to the capture's own texture directory.
- Files the live gate produced (fake runtime, `on-scaled`): `sky_1_500.dds` decoded 0.1251 against the layer's 0.2501.

## Acceptance / limits
- Offline only. The switch is **off** by default and was never enabled on a live run: W1.4's acceptance ("non-flat sky
  where the original is non-flat, recorded crop tolerances, user pick") still waits on same-camera crop sheets.
- **8-bit copy**: a factor that pushes a channel above white clamps (no HDR copy), and factors below 1 band the darks
  (an 8-bit re-quantisation of an 8-bit source). Both are limits of the DDS this path writes, not of the shader values.
- **Encoded space**: the gain is the runtime's `2.2` constant, not the sRGB piecewise curve the game's own sampler uses.
- **Untagged sources only**: `NIER_REMIX_LIVE_ALBEDO_UNORM=0` leaves textured layers at today's material (counted), never
  at a copy in the wrong space.
- **Mesh tint**: a layer whose `g_MeshColor` is not the identity keeps today's texture (one file name, three channels).
- **Cap**: after 8 distinct factors in one session the rest keep today's texture (`copy_refused` climbs).
- One frame per area, per the W1.2 receipt; the per-layer set is not claimed identical across frames.

## Status block
```
Status: implemented and gated (offline); W1.3 not accepted — its acceptance needs labelled same-camera crop sheets and
  the user's pick, and this step cannot produce them offline. Default off: nothing changed for today's runs.
Owner: lead session. Changed files: checks/sky_scale.h (new), checks/test_sky_scale.py (new), checks/mask_channels.h,
  checks/terrain_bake.h, checks/live_types.h, checks/live_scene.h, checks/live_capture.h, checks/remix_live.cpp,
  checks/remix_live_fake_runtime.cpp, checks/menu_overlay_mock_game.cpp, checks/test_live_sky_layers.py,
  replay/execution-2026-11-14/W1_SKY_SCALE.md (new), PLAN_2026-11-14.md (W1 row + Handoff), runtime/auto/REPORT.md.
Gates: python3 checks/test_sky_scale.py (green), python3 checks/test_live_sky_layers.py (8/8 green), 22 mutations red
  (table above), full suite 132/132 (runtime/suite-w13-1b, -j 14, 280.5 s).
Review: reviewer anthropic/claude-haiku-5-5, BLOCK -> P1 (colour space) fixed, 3 P2s fixed, 5 P3s fixed, 2 recorded.
Validation: full suite **132/132** after the P1 fix (runtime/suite-w13-1b). Baseline before any edit: 131/131
  (runtime/suite-w13-1b-base). Targeted regressions green: test_terrain_bake, test_sky_layer, test_sky_dds,
  test_sky_cb_dump, test_sky_census, test_remix_dds_formats, test_texture_convert_fast, test_live_albedo_tag,
  test_material_roles_override, test_live_scene, test_live_scene_target, test_live_texture_mips, test_terrain_mips,
  test_mask_channels, test_live_texture_wide. No live run, no DLL install, no GPU; game folder untouched.
Limitations: 8-bit copy (clamps above white, bands the darks); the runtime's 2.2, not sRGB's curve; untagged sources only;
  tinted layers and past-cap factors keep today's texture; mock-only evidence for the submission path.
Next ready substep: E1.6 spike (offline): straight-alpha/additive effect quads as Remix PARTICLE instances with
  InstanceInfoBlendEXT mapped from the D3D11 blend state, behind a switch, default off. Then W3 water / P2. W1.3 step 2
  still needs one fresh F9 capture (AO mask t17, fog LUT t12/t19) and waits on the user.
```
