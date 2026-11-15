# E1.6 — an effect quad as a Remix PARTICLE instance carrying the game's own blend state (offline, 2026-11-15)
Scope: E1.6 of `PLAN_2026-11-14.md`: "in a separate gated spike, test additive particles with Remix blend
extensions/categories so they can light the scene. Avoid double contribution when composite and geometry paths coexist.
Unsupported blends may become opaque in the inspected runtime; validate actual mapping and fake logs."
No game run, no DLL install, no package or system change, no GPU, no laptop: the desktop game folder was not touched. Only
the repository changed. Everything below sits behind `NIER_REMIX_LIVE_PARTICLE_BLEND=1`; unset, the capture path is
wire-identical to before (the reviewer re-checked this on the default-off path in round 2).

## What the runtime actually does with that state (read, not assumed)
- `remixapi_InstanceInfoBlendEXT` is consumed as **Vulkan** numbering: `rtx_remix_api.cpp:861-867` casts
  `srcColorBlendFactor`/`colorBlendOp`/`writeMask` straight to `VkBlendFactor`/`VkBlendOp`/`VkColorComponentFlags`.
  D3D11 and Vulkan do **not** share numbers (D3D11 `ONE` is 2, `VK_BLEND_FACTOR_ONE` is 1; D3D11 `DEST_COLOR` is 9,
  Vulkan's is 4), so a pass-through would have sent a different blend. Cross-checked against the FO4 prior art, whose
  `bs_extraction.cpp:3940-3978` builds the same Vk table from the Gamebryo enums.
- The runtime enables blending only for the (op, src, dst) combinations it recognises — 16 colour pairs — and sets
  `blendEnabled = false` (its "opaque alias") for everything else, including **any non-ADD op**
  (`rtx_instance_manager.cpp:771-860`). That is the plan's "unsupported blends may become opaque".
- `blendEnabled` is then forced off for any instance carrying `ALPHA_BLEND_TO_CUTOUT` (`:720`, `:758-759`), so a
  straight-alpha particle must not also be labelled cutout.
- With `useDrawCallAlphaState` on the material, the **instance**'s `alphaTestCompareOp` is read as well (`:745-746`);
  0 is `kNever`, i.e. every sample discarded. The field must be `kAlways` (7) for a particle that has no alpha test.
- `out.isParticle` is the PARTICLE category bit, and the runtime's own comment says particles "require blending be
  enabled".

## What was built
- `checks/particle_blend.h` (new): plain C++ (no D3D11, no Remix), so the game thread and the worker share one table.
  `factor()` D3D11_BLEND -> VkBlendFactor for the 15 values that can be expressed (`BLEND_FACTOR`/`InvBlendFactor` are
  refused: they need the blend constant and this path sends none), `blendable()` the runtime's 16 colour pairs,
  `map()` the whole `D3D11_RENDER_TARGET_BLEND_DESC` -> the EXT fields with every refusal in one place (blending off,
  alpha-to-coverage, non-ADD colour or alpha op, zero write mask, unknown factor, ONE/ZERO the opaque alias, and the
  premultiplied pair without the alpha state the runtime needs to classify it).
- `checks/live_types.h`: `Item::blend` (the full state as D3D11 reports it) + `Item::particle`, `Upload::particle`,
  `Frame::particles`.
- `checks/live_capture.h`: the bound blend state is recorded in full where it was already read; `particle_draw` is
  `switch && !ui_pass && pixel.effect && map().ok`; a particle draw gets its **own geometry key**
  (`hash_value(geometry ^ "particle")`) so the mesh it builds cannot displace an opaque mesh built from the same buffers
  (the mock's effect quad shares the world draw's buffers, so this is exercised); an effect draw with no texture is
  dropped where the texture becomes final, as it is with the switch off; `particle_draws`/`particle_submitted`/
  `particle_refused`.
- `checks/live_scene.h`: `material_for(..., bool draw_call_alpha)`, which mixes a salt into the material key, its hash and
  sets `MaterialInfoOpaqueEXT.useDrawCallAlphaState`. Without it the runtime never reads the instance's blend state. The
  salt is carried through `State::Incomplete`, so a `grey_first` refresh re-creates a *particle* material, not a world
  one. `build_mesh` passes `upload.particle`; the instance chains `InstanceInfoBlendEXT` into `pNext` (after the bone
  transforms, found by sType by the real runtime) and sets the PARTICLE bit; a particle is never also labelled cutout;
  `alphaTestCompareOp` is set to `kAlways`; a mesh with no material, or a carried stand-in, keeps today's path.
- `checks/remix_live.cpp`: `remix: live particle_blend draws= submitted= refused=`, printed only when the switch is on.
- `checks/remix_live_fake_runtime.cpp`: `pnext_find` walks the extension chain by sType (as the runtime's `pnext::find`
  does) instead of type-punning `pNext`, and the log gained the blend fields (`blend= src= dst= op= asrc= adst= aop=
  mask= atestop= atestref=`), `drawcall=` on `CreateMaterial`, and `mathash=` on `CreateMesh` (a material hash survives
  the `grey_first` refresh; a handle does not).
- `checks/menu_overlay_mock_game.cpp`: `MOCK_EFFECT_BLEND=atoc|opaque` (two states the path must refuse) and
  `MOCK_EFFECT_NO_TEX` (an effect draw with no albedo, so it gets no material).

## Gate
`checks/test_particle_blend.py` (new, SHA-256 `5051c681…`), two parts in one file:
1. **Native** (host g++, ASan+UBSan, `-Werror`): every D3D11 factor value by value and every refused one; the 16 pairs
   the runtime blends and 8 near misses it does not; the map for straight alpha, additive, premultiplied (with and
   without the alpha state it needs), multiplicative, independent alpha factors, write-mask pass-through, and each
   refusal; then a particle material is its own material with `useDrawCallAlphaState`, is memoised, and **stays** one
   when `grey_first` re-creates it after its texture lands.
2. **Live** (the mock game + the recording fake runtime, via `tr.run`): `default` and `zero` submit no PARTICLE category
   and no blend state and count nothing; `on-additive` submits exactly one PARTICLE instance per frame with
   `VK ONE/ONE/ADD`, mask 15, no cutout flag and `atestop=7`, on its own mesh whose material has `drawcall=1`, while the
   same frame's world draw of the same buffers gets neither; `on-straight` maps `SRC_ALPHA/ONE_MINUS_SRC_ALPHA` and also
   carries no cutout flag; `on-atoc`, `on-opaque` and `on-notexture` are refused, counted, and leave no PARTICLE
   instance (and `on-notexture` drops the draw instead of demoting it: `refused>0` is what catches a demotion, and the
   run builds exactly as many meshes as the switch-off run does).

## Mutations (19, all red, each restored byte-identically)
Write mask hardcoded; factors passed through unmapped; every pair accepted; alpha-to-coverage accepted; a zero write
mask accepted; `alphaBlendEnabled` never set; the alpha test left at `kNever`; a particle also labelled cutout;
`useDrawCallAlphaState` never set; the draw-call-alpha material sharing the world key; the `grey_first` refresh dropping
the flag; the blend chain without the PARTICLE bit; the particle sharing the world geometry key; the untextured draw
demoted instead of dropped; a submitted particle not counted; the switch on by default; a refusal not counted; the
premultiplied pair accepted with any alpha state; the stats line never printed.
Mutation testing earned its keep here: the native `grey_first` check first passed a mutation because a material from an
earlier block happened to share the hash. It now uses its own texture id, and the same mutation is red.

## Independent review (`anthropic/claude-haiku-5-5`, three rounds)
Round 1 **BLOCK**, 4 P1 + 2 P2 + 5 P3. Fixed: the cutout flag on a straight-alpha particle (the runtime would drop the
blend); the zero-filled `alphaTestCompareOp` (kNever would have made every particle invisible); the `grey_first` refresh
losing the flag; the untextured effect draw; `!ui_pass`. The gate gained a native table test and the cutout/alpha-test
assertions it was missing. Round 2 **BLOCK** with 1 P1 + 2 P2 + 1 P3 on the partial fix: the untextured draw was demoted
to world geometry instead of dropped (now dropped before the upload, gated by `bare_meshes=0` and by the switch-off run's
categories); a particle could still ride a material-less mesh (now `&& !s.bare.count(geometry)` in the chain — not
reachable from the mock, so not gated); the premultiplied pair was accepted with the wrong alpha state (now refused, and
gated). Round 3 **BLOCK** on the gate only: it judged the demotion fix correct but said the assertion added for it
(`bare_meshes == 0`) cannot fail, because an albedo-less draw still receives a material. That is true, and the assertion
is now a `CreateMesh` count comparison. The regression was in fact already caught in round 2's mutation run by
`refused>0` (recorded in `/tmp/particle_blend_mutations.json`), so the guard was never unproven; round 3 also found that
a carried stand-in mesh could ride a particle (`&& !carried`, now in the chain) and two report-only items. Recorded, not
fixed: `particle_submitted` is counted at capture, so a particle dropped later (missing mesh) is counted as submitted —
stats only; a non-ADD *alpha* op is refused although the runtime's alpha-writes-off branch would accept it (stricter,
never wrong); and the `on-notexture` drop does not increment `frame.skipped`, so the `draws` figure includes it.

## Limitations (explicit, not claimed as done)
- **No live evidence.** Nothing here shows that a particle lights the scene, looks right, or costs what it costs. That
  needs one camp/pond run with the proxy DLL installed, `NIER_REMIX_LIVE_PARTICLE_BLEND=1` and a labelled A/B; it is in
  the Handoff's "Waiting on the user".
- The composite path E1.3-E1.5 does not exist yet, so "no double contribution when composite and geometry paths coexist"
  is only pinned as "one instance per draw, and the particle never shares the world's mesh or material".
- The fold is not tied to an effect shader's bytecode: eligibility is the existing effect classification plus the blend
  state. A shader the census does not classify as an effect is not affected by this switch.
- Refused classes stay out, exactly as with the switch off: non-ADD ops, `BLEND_FACTOR` states, alpha-to-coverage,
  ONE/ZERO. That is deliberate (the runtime turns each of them solid), but it means "all effects recovered" is not what
  this spike says.
- The `s.bare`/`!carried` guards in the worker and the `!ui_pass` exclusion are not exercised by any gate case; they are
  defence against states the mock cannot produce (a failed `CreateMaterial`, the carry path, a HUD-target effect).
- No measurement: the extra mesh per particle geometry and the per-instance EXT are not measured for cost.

## Files touched (SHA-256 at acceptance)
`checks/particle_blend.h` `5981249d…`, `checks/test_particle_blend.py` `8416a5e8…`, `checks/live_types.h` `d788fdf8…`,
`checks/live_capture.h` `b58be8be…`, `checks/live_scene.h` `369e0703…`, `checks/remix_live.cpp` `6fb6057a…`,
`checks/remix_live_fake_runtime.cpp` `2776d705…`, `checks/menu_overlay_mock_game.cpp` `5fa1a8d1…`.
Full suite: **133/133 green**, `runtime/suite-e16-3` (`-j 14`, 330.6 s, source unchanged); `suite-e16-1` was 132/133
(the new gate could not find its X display under the suite's xvfb shim — fixed) and `suite-e16-2` 133/133 before the last
two guards. Nothing committed or pushed.
