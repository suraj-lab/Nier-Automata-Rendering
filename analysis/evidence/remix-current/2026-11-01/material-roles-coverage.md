# Material roles: why surfaces still look grey, chrome and washed out (offline, 2026-11-01)

Scope: how often the per-shader PBR tracer (`analysis/checks/pbr_trace.py`, ported as `material_roles.h`) actually pins
a role, what the live path does when it cannot, and which of the two is responsible for the remaining visual faults.
No game run was used.

## 1. What the live logs showed

Only the three 2026-11-01 receipts print `remix: material` lines (the diagnostic shipped that day):

| run | lines | lines with a traced role |
|---|---:|---:|
| pbr-diag1 | 51 | 17 |
| pbr-verify1 | 64 | 20 |
| frametime1 | 47 | 2 |
| distinct shaders, all three | 128 | 5 |

So live, ~4% of logged shaders carry a traced role. That number alone cannot say whether the tracer or the shader set
is at fault, which is what section 2 measures.

**Logging defect found on the way, narrower than it first looked:** `live_capture.h:1511` (the capture path) calls
`note_material({current_ps(context), false, …})` with the flag hard-coded, while line 1332 passes `true` for the draws it
skips *as* effects — which is why 40 of the 128 logged lines across the three runs carry `effect=1`. So the column is
accurate for skipped effects, and lies only when `NIER_REMIX_LIVE_EFFECTS=1` keeps an effect draw in the scene: it then
reaches line 1511 and is logged `effect=0`. Consequence for this note: frametime1's 45 `effect=0` lines are genuinely
non-effect draws, which is what the classification in section 3 assumes. Fix is one expression (`pixel.effect`), planned
in `analysis/PLAN_2026-11-01_effect-field.md`.

## 2. Tracer coverage over real shaders we have offline

`analysis/runtime/pbr-re/meta` is the laptop's full live pixel-shader set (605 shaders, `.asm` + `.dxbc`).
`analysis/runtime/laptop-port/pbr-diag1/winasm` is the same 605 disassembled by Microsoft's compiler instead of Wine's.

| corpus | shaders | albedo | metal | gloss | normal | detail | all four |
|---|---:|---:|---:|---:|---:|---:|---:|
| meta (full live set) | 605 | 104 | 102 | 94 | 111 | 103 | 61 |
| winasm (same, Microsoft disasm) | 605 | 104 | 102 | 94 | 111 | 103 | 61 |
| all_lit (curated lit set) | 3,080 | 2,022 | 1,999 | 2,022 | 2,183 | 2,000 | 1,309 |

Two facts: the tracer is exactly stable across disassemblers (re-confirms the existing claim, now on this corpus), and
**coverage on the full live set is 17% for albedo, 10% for all four roles** — against 66% on the curated lit set. The
live set includes every pixel shader the game draws, so the gap is not a tracer bug by itself: most of those shaders
are not lit materials.

## 3. What the 473 zero-role shaders actually are

Each of the 473 was classified from its own disassembly (does it sample a material slot 0-7; does it contain lighting
maths):

| class | count | share |
|---|---:|---:|
| samples a material slot, **no lighting maths** → unlit / albedo-only | 228 | 38% |
| **lit** and samples a material slot → roles not pinnable (real gap) | 218 | 36% |
| no texture sample at all (vertex colour / flat overlay) | 16 | 3% |
| samples only materials-excluded slots (11 shadow, 12/19 fog, 13 depth, 14 dither, 17 AO) | 11 | 2% |
| pinned at least one role | 132 | 22% |

The 218 lit-but-unpinnable shaders are the actionable set. Examples, all with 4-8 material slots bound and lighting
present: `ps_550290355144` (slots 0-7, cutout), `ps_550292532424` (slots 0-3, cutout), `ps_550292535560` (slot 0),
`ps_550290361864` (slot 0, opaque). The tracer's stated rule is to leave a role out rather than guess, so these are
honest refusals — but the draw still has to reach Remix with *something*.

## 4. What the live path does with an untraced shader

From `live_capture.h` (albedo) and `live_scene.h` (metal/gloss/normal):

- **Albedo:** if `roles.albedo.slot < 0`, the code scans slots 0-15 and takes the **first usable texture** as albedo
  (`live_capture.h`, `else` branch after `if (roles.albedo.slot >= 0)`). **Measured, this fallback is sound:** of the 104
  shaders whose albedo the lighting maths does name, slot 0 is that albedo in **100 (96%)** (the other 4 are slot 5), and
  432 of the 501 untraced shaders sample slot 0 first, so the scan lands on slot 0 for them. Wrong-slot albedo is
  therefore *not* the main fault; the earlier "possibly the wrong texture" reading was an inference that the data does
  not support.
- **Metal, gloss and normal:** taken **only** from traced roles. Untraced → no textures at all.
- **Material constants:** `nscn_scene.h` sets `roughnessConstant = 0.6f`, `metallicConstant = 0.f` for every material
  that has no roughness/metallic texture.

So an untraced lit draw arrives as: possibly-wrong albedo + roughness 0.6 everywhere + zero metalness.

That is the signature of the open visual faults, and it explains why they survived the material work:
grey/flat surfaces (one roughness for every surface), chrome-looking distant terrain and rocks (zero metalness, so the
metal/fresnel response never appears), washed-out colour (the shader's own tint and lighting never reaching a
per-surface roughness). The decisive number is the metal/gloss half, not the albedo half:
**500 of 605 shaders (83%) carry neither a metal nor a gloss texture** (metal traced on 102, gloss on 94), while albedo
arrives at roughly the right slot 96% of the time.

## 5. A candidate fallback that was measured and rejected

The plan was to give the 218 lit-but-unpinnable shaders an albedo from the output write's provenance instead of the
first usable slot. Prototyped over the 605 corpus: it would have gained an albedo for 269 of the 501 untraced shaders —
but checked against the 104 shaders where the lighting maths names the albedo, **it agreed on only 32, disagreed on 11
and returned nothing on 61**. A rule that is wrong or silent on two thirds of the known cases is a guess, so it is not in
the tracer, and it must not be added on this evidence.

## 6. The frozen gate

`analysis/checks/test_roles_coverage.py` (fixture `analysis/checks/fixtures/material-roles-meta.json`, 605 shaders,
29 KB) pins, offline and in ~3 s:

1. the tracer's roles over the 605 corpus match the fixture exactly (albedo 104, metal 102, gloss 94, normal 111,
   detail 103, all four 61);
2. Wine's and Microsoft's disassemblies of the same 605 blobs agree shader for shader (605 pairs);
3. slot 0 is the traced albedo for 100 of 104 — the number that licenses the live fallback;
4. the first sampled slot is 0 for 432 of the 501 untraced shaders;

with three mutations proven live: breaking the metals pattern moves 154 shaders, moving a victim shader from slot 0 to
slot 5 changes its roles, and an off-by-one slot-0 count is rejected.

## 7. Next steps that follow from this

1. **Metal/gloss is the gap worth attacking**: 500 of 605 shaders get none. The obvious next hypothesis — widen the
   metals literal search (the F0 lerp currently accepts only `0.03`/`0.08`) — **was measured and closed**: among the 102
   pinned shaders 95 carry `0.03` and 91 carry `0.08`, but among the 218 lit-but-unpinned only 17 carry `0.03` and 21
   carry `0.08`, and their only other small `mad` constants are the `-0.03`/`-0.08` halves of that same lerp. There is no
   F0 lerp in most of the 218 to widen to; they are a different shading path, and the tracer's refusal there is correct.
2. Fix `effect=` (pass `pixel.effect`) so future runs separate lit from unlit without disassembly. One expression;
   planned and approved in `analysis/PLAN_2026-11-01_effect-field.md`, not executed yet.
3. Per-layer terrain gloss/roughness and the per-instance tint bake stay blocked behind item 1: while 83% of shaders
   reach Remix with `roughnessConstant 0.6` and `metallicConstant 0`, neither can show through.

Evidence for this note is reproducible offline: `python3 analysis/checks/pbr_trace.py --dir analysis/runtime/pbr-re/meta
--json /tmp/meta.json` plus the slot/lighting probe described in section 3.
