# W1.3 step 1 — the sky layer's own inputs reach its material (offline, 2026-11-15)

Scope: W1.3 step 1 of `PLAN_2026-11-14.md` ("sky image and illumination"), as the previous handoff left it: fold the
three per-layer inputs a capture does hold into the material of a sky-classified draw, behind a default-off switch, and
gate it on the submitted material colour plus default-off parity. No game run, no DLL install, no package or system
change; the desktop game folder was not touched.

## What the shader does with the numbers (from the repository's own disassembly)
`runtime/w1-disasm/sky_ps.asm` (FNV-1a 64 of the bytecode `0x33856d1d3ba64bb3`, the same shader in camp, desert and
pond) per layer:

| asm | operation |
| --- | --- |
| 21-23 | `uv = pixel.xy / cb12[0].zw`; `t0` sampled at `v1.xy + g_UvOffset.xy` |
| 24-26 | `base = (g_AlbedoParam.w > 0 ? g_AlbedoParam.rgb : t0.rgb) * g_IntensityParam.y` |
| 27-29 | `base *= saturate(t17(uv) + g_ShadowParam.z)` — the AO mask, **not in any capture** (PS slot 17) |
| 30 | `base *= g_MeshColor.rgb` (identity in all three areas) |
| 31-51 | `f = exp(log(saturate((dist - g_FogParam.x) * g_FogParam.y)) * g_FogParam.z)`; `out = lerp(base, t12/t19 LUT * g_FogColor.rgb, f * lut.a)` — **the LUT's cube face is not in any capture** |

So of the five multiplicative inputs, three are in the captures (`g_IntensityParam.y`, the `g_AlbedoParam` override,
`g_MeshColor`), and two are not (AO, fog). This step folds the three and states the two as limitations; it does not
invent the missing ones.

## What was built
- `checks/sky_layer.h` (new, portable C++17, no D3D): parses a shader's DXBC `RDEF` into name → (bind slots, byte
  offset, declared buffer size); places each declared buffer on a bound slot by **exact declared size first, then a
  single remaining fit, refusing two candidates** (the rule `checks/sky_cb_dump.py` proved on the packed captures);
  reads `g_IntensityParam.y`, `g_AlbedoParam`, `g_MeshColor` as finite float4s; and computes the base colour
  `albedo * intensity * mesh` **only when the shader's own `w > 0`**.
- `checks/live_capture.h`: `NIER_REMIX_LIVE_SKY_LAYERS` (default off, read at load), the per-shader RDEF member list
  cached in `PixelInfo`, `sky_inputs()` (queries only the slots the shader declares, reads only the two that hold the
  members, owns a copy of the bytes), and the fold at the world-extent decision — so it runs only for a draw the path
  already classifies as the background shell. Counters `sky_layer_{draws,folded,textured,unresolved}`.
- `checks/remix_live.cpp`: one stats line, `remix: live sky_layers draws=… folded=… textured=… unresolved=…`.
- `checks/menu_overlay_mock_game.cpp`: `MOCK_SKY_PS` — a pixel shader shaped like the game's (`PSParamBuffer1` at b1
  declaring 64 bytes while the run binds 112, `g_AlbedoParam` at reg 3, `ModelBuffer` at b4) — plus `MOCK_SKY_PS_ANIM`,
  which changes the layer's intensity every 8 frames so a fold that never reaches a new material can be caught.

Why the texture case is not folded: Remix's `MaterialInfoOpaqueEXT.albedoConstant` **replaces** the albedo texture, it
does not multiply it (`replay/research-2026-11-12/remix_material_api.md:19-21`, re-confirmed by scout). A layer with
`g_AlbedoParam.w == 0` is `t0 * factor`, which this API cannot express without writing a scaled copy of the layer
texture; that copy needs a DDS decode of BC2 (camp's 2048² cloud layers) that `terrain_bake::read_dds` does not have.
Such layers therefore keep today's material and are counted as `textured` — never silently flattened to a constant.

## Gates (frozen)
1. `checks/test_sky_layer.py` (SHA-256 `1f72b9f6…`; header `checks/sky_layer.h` `32af1b8a…`) — native g++, ASan+UBSan. Pins `sky_layer.h` against the
   **repository's real sky bytecode** and against the (slot, register) pairs `checks/sky_cb_dump.py` measured on camp,
   desert and pond (`runtime/sky-cb-dump-gate/*.json`, a second implementation, so the header is not its own oracle):
   FNV of the fixture is the sky code; `PSParamBuffer1` is declared twice (64 and 128 bytes); with the captures'
   bindings every member lands where the capture measured it (`g_IntensityParam` b1 offset 16, `g_AlbedoParam` b1
   offset 48, `g_MeshColor` b4 offset 0); two exact-size candidates are refused; a too-small bind is refused; the
   colour is `albedo * intensity * mesh`; `w == 0` yields no constant; an unbound or short binding is refused; four
   malformed containers are refused without a crash.
2. `checks/test_live_sky_layers.py` (SHA-256 `a4bbab96…`) — the fake runtime under Wine. Cases: switch unset → today's
   material (`aconst` 1,1,1, the layer texture), nothing counted; `=0` → byte-identical material list to unset
   (`presented`/`id` stripped; `NIER_REMIX_LIVE_GREY_FIRST=0` keeps the list deterministic); on with `w = 1` → exactly
   one folded material, `aconst` = 5.000,3.565,2.750, no albedo texture, and the *world* draw of the same frame keeps
   today's material; on with `w = 0` → nothing folded, counted `textured`, material identical to today's; on with a
   shader declaring none of the members → counted `unresolved`; animated intensity → more rebuilds with the fold on
   (26 vs 4) **and all three colours resubmitted as new materials** with it on, none with it off.

Red before green, recorded as it happened (this is an honest log, not a claim that every gate was written before the
code): the unit gate first went red on three of its own assertions because its fixture wrote the intensity to lane x
instead of y; the live gate first went red on a `path=-` material that today's grey-then-textured swap legitimately
produces, then on two runs whose material lists differed only in `presented=` (removed by switching `grey_first` off in
the gate, so the list is deterministic), and finally on the reviewer's P1 — a changed colour that rebuilt the mesh but
never reached a new material. Each red was either a gate bug, a gate artefact, or a real path bug; the last one was
fixed in the path and the mutation table's L5 row re-introduces it.

Mutations, each red, restored byte-identically (`/tmp/w13_mutations.py`, temporary):

| mutation | gate | result |
| --- | --- | --- |
| slot by table order instead of by declared size | unit | red |
| ambiguity resolved by order instead of refused | unit | red |
| too-small bind accepted | unit | red |
| binds taken from declaration order, not the RDEF resource table | unit | red |
| `g_IntensityParam` read from lane x instead of y | unit | red |
| no binding-size check before reading a member | unit | red (ASan abort) |
| `g_MeshColor` ignored in the product | unit | red |
| a textured layer (`w == 0`) given a constant colour | unit **and** live | red both |
| fold ignores the sky classification | live | red |
| switch on by default | live | red |
| folded constants not hashed into the surface | live | red |
| a changed colour never reaches a new material (the reviewer's P1 reintroduced) | live | red |

## Review
Reviewer `anthropic/claude-haiku-5-5`, read-only, verdict **BLOCK** → resolved:
- **P1 (fixed)**: `unchanged` compares the decoded geometry only, so a changed folded colour rebuilt the mesh but skipped
  the upload that creates the material — the fold would have stuck at its first value. The fold now runs before the
  content hash and the colour is mixed into it; the gate gained the "all three colours resubmitted" assertion, which is
  red when the fix is reverted (mutation L5).
- **P2-1 (fixed)**: the RDEF offset/size checks were 32-bit; now 64-bit.
- **P2-2 (fixed)**: `sky_inputs` borrowed `buffer_bytes` storage, which a later call can trim; it now owns its copy.
- **P2-3 (not fixed, by decision)**: `kSkyPsCode` is not a runtime whitelist. A 64-bit bytecode hash would fold nothing
  for an instrumented or modded shader, and the mock cannot produce the game's hash, so the feature would be
  untestable offline; the runtime contract is instead "a draw the path already classifies as the background shell,
  whose shader declares these three members by their RDEF names". The header's gate still pins the real shader's code,
  so the offsets it uses are the sky shader's measured ones.
- **P3 (recorded, not changed)**: the default-on item L3 flag albedo has the same stale-material hole (its constants are
  not in the content hash). Fixing it changes when an accepted, default-on path rebuilds, so it needs its own gate; it
  is left as found and named here rather than folded into this item.

## Measurements
- Folded material colour for the mock's `g_AlbedoParam = (1, 0.713, 0.55, w=1)`, `g_IntensityParam.y = 5`,
  `g_MeshColor = 1`: `5.000, 3.565, 2.750` — the shader's own base colour, with no albedo texture.
- Rebuilds over 80 mock frames with the value animated every 8: 26 with the fold on, 4 with it off.
- No fps, memory or GPU numbers: nothing here runs the game. The two constant-buffer reads per sky draw (4-22 sky draws
  per frame on the captures) were not profiled; `NIER_REMIX_LIVE_SKY_LAYERS` also gates the reads, so a live A/B can
  measure them before any default change.

## Acceptance / limits
- Offline only. The switch is **off** by default and was never enabled on a live run: W1.4's acceptance ("non-flat sky
  where the original is non-flat, recorded crop tolerances, user pick") is untouched and still waits on same-camera
  crop sheets, which need live runs.
- **Not folded, by evidence**: the AO mask (`t17`, PS slot 17 is outside `texture_capture`'s 0-15) and the fog LUT
  (`t12`/`t19`, cube faces are stored as one face). Pond and desert saturate the fog factor to 1 at their dome extents
  (`1/g_FogParam.y` = 520/854 units against 8.3k-19k domes), so a Remix sky that reproduces the dome but not the fog
  will look wrong in exactly those two areas — a measured limitation to state with any artefact, not a bug to hide.
- **Not folded, by API**: `w == 0` layers keep their texture (see above). Camp's 2048² cloud layers are BC2, which
  `terrain_bake::read_dds` cannot decode.
- One frame per area, per the W1.2 receipt; the per-layer set is not claimed identical across frames.
- The live gate is a Wine mock: it pins what the path submits, not what Remix renders.

## Status block
```
Status: implemented and gated (offline); W1.3 not accepted — its acceptance needs labelled same-camera crop sheets
  and the user's pick, and this step cannot produce them offline. Default off: nothing changed for today's runs.
Owner: lead session. Changed files: checks/sky_layer.h (new), checks/test_sky_layer.py (new),
  checks/test_live_sky_layers.py (new), checks/live_capture.h, checks/remix_live.cpp,
  checks/menu_overlay_mock_game.cpp, replay/execution-2026-11-14/W1_SKY_LAYERS.md (new), PLAN_2026-11-14.md (W1 row
  + Handoff).
Gates: python3 checks/test_sky_layer.py (green), python3 checks/test_live_sky_layers.py (green), 12 mutations red
  (table above), full suite recorded in the Handoff section of PLAN_2026-11-14.md.
Review: reviewer anthropic/claude-haiku-5-5, BLOCK -> P1 fixed (with a new gate assertion that is red when reverted),
  2 P2s fixed, 1 P2 answered by design, 1 P3 recorded (item L3's identical stale-material hole, left as found).
Validation: full suite **s4 130/130** (runtime/suite-w13-s4, -j 14, 279.3 s, source unchanged). Two earlier runs on
  this item were 129/130 with `test_live_scene_target.py` red only in-lane (s1, s3) and green when rerun alone (both
  times, exit 0) — a load flake of the same kind as the documented `test_live_visibility`/`test_live_normal_map` pair,
  now with a third member; it is not this item's code (the switch is off, so the path it exercises is unchanged). No
  live run, no DLL install, no GPU; game folder untouched.
Limitations: AO and fog not folded (not in any capture); textured sky layers keep today's material (albedoConstant
  replaces, does not multiply; BC2 undecodable); mock-only evidence for the submission path.
Next ready substep: R2a (enumerate PS SRVs 0-31 behind a switch, measure cost) and R2b (cube faces in write_dds plus
  the matching read-back), both offline-implementable with default-off parity; their verification needs one fresh F9
  capture, which waits on the user.
```
