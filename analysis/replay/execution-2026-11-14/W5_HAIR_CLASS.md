# W5 step 1 — hair classification, anisotropy on the hair material only (default off)

Date: 2026-11-15 (unattended iteration). Plan: `PLAN_2026-11-14.md`, W5 step 1. Status: **implemented, gated, reviewed;
accepted offline only.** Nothing was installed, run live, or written outside this repository; no GPU workload, no game
folder change, no laptop or remote action, nothing committed.

## What the step asked for, and what was built

> "find `g_AnisoParam*`'s offsets in the hair shader by disassembly, then classify hair draws the way W3 step 2
> classifies water (its own header + frozen gate, alpha-tested/skinned positives against a clothing/skin negative) and
> set `MaterialInfoOpaqueEXT.anisotropy` behind a default-off switch."

| Requirement | Where |
| --- | --- |
| the offsets, by disassembly | measured, below: `g_AnisoParam1` @ 96 → `cb1[6]`, `g_AnisoParam2` @ 112 → `cb1[7]` |
| classification | `checks/hair_class.h` (new): pure C++, one rule table, a reason code per refusal |
| switch, default off | `checks/live_capture.h`: `NIER_REMIX_LIVE_HAIR=1` (only `=1` enables it), counters `hair_draws` / `hair_submitted` / `hair_refused`, stats line `remix: live hair …` in `checks/remix_live.cpp` |
| declaration read | `live_capture.h`: the pixel shader's RDEF must name `g_AnisoParam1` **and** `g_AnisoParam2` exactly once each **in the same** declared buffer, read through `sky_layer::members` |
| the value read | `live_capture.h` `hair_lobe_on()`: `g_AnisoParam2.x` of the draw's own PS constant buffer, placed by `sky_layer::place` over `sky_layer::both_members(…, "g_AnisoParam1", "g_AnisoParam2")` (new helper) |
| own mesh key | `live_capture.h`: a classified draw is keyed `^ kHairGeometrySalt`, and the key is **re-applied** after the rigid-decode path rewrites `geometry = skin_base` (review P1; the same line keeps the water salt) |
| the material | `checks/live_scene.h` `material_for(..., bool hair)`: `ext.anisotropy = hair_class::kAnisotropy` (0.5), its own material key and hash, and the flag carried through the grey_first refresh |
| fake runtime | `checks/remix_live_fake_runtime.cpp`: `aniso=%.3f` on both `CreateMaterial` lines |
| fixture | `checks/menu_overlay_mock_game.cpp`: `MOCK_HAIR_PS=x` — a PS that declares the pair at 96/112 of one `PSParamBuffer1`, discards, reads `g_AnisoParam2.x`, plus a second buffer bound smaller than declared (the shape the real shader has), with 208 bytes bound for the 128-byte declaration |
| gate | `checks/test_live_hair.py` (new, SHA-256 `2fcb0fbc…`) |
| census | `replay/execution-2026-11-14/w5_hair_census.py` (new, `21461d9d…`) |

## Measured facts the classifier keys on (re-read by the gate, not remembered)

`python3 replay/execution-2026-11-14/w5_hair_census.py` over `runtime/laptop-play-20261114` (frames `frame_67078468` pond,
`frame_67279062` desert, 625 shader blobs) plus the camp capture `/mnt/second/…/NIER_CAPTURE` (read-only; not part of the
gate):

- **46 of the 625 blobs declare `g_AnisoParam1` and `g_AnisoParam2`**, always together, always in one `PSParamBuffer1`,
  always at byte offsets **96** and **112**; **21** of them also declare `g_SecondarySpecParam`.
- Disassembly of the drawn hair shader `ps_550297348744` (vendor `D3DDisassemble`, the technique
  `checks/test_dxbc_discard.py` established) reads only `cb1[6].x`, `cb1[6].y` (an alternate sign path and a secondary
  lobe term), `cb1[7].x` (the lobe's `if_nz` enable) and `cb1[7].yzyy` (per-axis roughness divisors:
  `div r18.xy, cb1[7].yzyy, r13.w`). 96/16 = 6, 112/16 = 7, and the same struct's `g_AlbedoColor` at 48 is read as
  `cb1[3]` at that site — that is what ties the member offsets to the register, and it is why the classifier can read a
  value rather than guess from a name. The gate asserts those four instruction shapes and the offsets.
- Each frame draws exactly **two** aniso declarers, both skinned with the same input layout
  (POSITION/TANGENT/TEXCOORD/BLENDINDICES/BLENDWEIGHT/TEXCOORD/NORMAL), both unblended (blend_enable 0, depth_enable 1,
  depth_write 0). Only one of them declares `g_SecondarySpecParam`, and only that one takes the lobe: its three draws
  carry **1, 1, 0** at offset 112 (the 10,656-index mesh does not), the other family **0 on all 10 (pond) / 6 (desert)
  draws**. So a declaration alone cannot be the test — that is the plan's mutation and it is red in the gate.
- Alpha test separates the families: the hair shader **discards**, the other does not. Their t0 alpha coverage supports
  the split (decoded from the captures' DDS by the census script): **22.3%** of the hair family's texels are fully
  transparent in pond and desert (**59.7%** in camp, **0.0%** for the other family), BC1/BC2 alpha.
- The buffer that declares the pair is bound at PS slot 1 with **208 bytes against its 192-byte declaration** in the hair
  draws (the other family binds exactly 176). So no size equality finds the slot; `sky_layer::place`'s "fits" fallback
  does — verified against the captured blob and the draw's own binding sizes by the gate's native harness.
- Not measured / not claimed: that these draws are visually 2B's hair (a hide-draw check needs a live run), which of
  scalp/lashes/cards each one is, that the other family is clothing rather than fur or velvet, and any aesthetic value
  for the 0.5 scalar.

## The classifier (`hair_class::why`, first rule that matches)

Blend enabled → not alpha-tested → not skinned → sky → effect → depth pass → no captured albedo → no `g_AnisoParam1`/
`g_AnisoParam2` pair → the draw's own `g_AnisoParam2.x` is not > 0 → **hair**. A refusal always beats the declaration,
and the constant-buffer read happens only for a draw that passes every other rule.

## Gate result — red before, green after (frozen first)

- **Red (before any implementation):** part 1 (the measured table) passed; part 2 failed with
  `fatal error: hair_class.h: No such file or directory`. The right reason.
- **Green:** `python3 checks/test_live_hair.py` prints `W5 hair class gate: OK`, with part 2 printing `failures=0`. Part 3
  cases: `default` (switch off: 1 material, all isotropic), `zero-parity` (unset and `=0` build the same materials),
  `on-hair` (aniso 0.500, its own hash, same albedo, no draw-call alpha, no translucency), `on-lobe-off` (refused,
  today's material), `on-plain` (no declaration: nothing classified), `on-unskinned` (refused; materials equal to the
  same run with the switch off), `on-grey-default` (grey_first at its shipped default: 2 materials — grey and refreshed —
  both at 0.500), `lifetimes` (every drawn mesh resolves to a live material hash in all seven runs).
- The gate's own placement block runs `sky_layer::members`, `sky_layer::both_members`, `sky_layer::place` and
  `sky_layer::detail::value` **on the captured shader and the draw's own bytes**, asserting slot 1 and the two lobe
  values, and that offering *every* declared buffer to `place` is refused for this shader — the reason the live path
  filters. That block found a real defect in the first implementation (see review P2-3).

## Mutations — 20 red, each restored byte-identically

`python3 runtime/tmp/w5_mutations.py` → `runtime/live-hair/mutations.json` (`43f6dedf…`), 20 mutations, 0 stayed green.
Fourteen run the native harness (every rule removed one at a time; anisotropy 0; anisotropy 1.5; isotropic material;
shared hash; shared key; refresh dropping the flag); six run the whole gate (never read the lobe; read 0 as on;
declaration always false; count a refused draw as submitted; classify every textured draw; anisotropy on every
material). Each entry records its file, the mutation, the scope, the evidence and the restored SHA-256.

One candidate mutation is **not** observable and is recorded as such rather than called red: passing every declared
buffer to `place()` in `hair_lobe_on` (the shape the pre-review code had). The mock's shader cannot reproduce the
capture's ambiguity honestly, but the harness pins that `place()` over all declared buffers **is** refused for the real
captured shader, so the filter's necessity is data-backed.

## Review — one `reviewer` call on `anthropic/claude-haiku-5-5` (synchronous)

Findings and dispositions:

- **P1 fixed — the rigid decode dropped the salt.** `geometry = skin_base` on a first single-bone decode rewrote the key
  the classification had just salted, so a hair mesh could be built under the isotropic key and reused by a non-hair draw
  of the same buffers (the water path had the same hole). Both salts now live in named constants and are re-applied on
  that path.
- **P1 fixed — the gate docstring claimed a measurement nothing produced.** The 22.3%/0.0% alpha figures are now the
  census script's output (reproducible command, recorded above) and the wording no longer attributes them to gate part 1;
  the "cloth" label is stated as the recon's, not as something measured here.
- **P2 fixed — the gate did not check the placement the live path runs.** Added: the harness runs the production
  `members`/`both_members`/`place`/`value` on the captured blob with the draw's own binding sizes and the captured
  bytes. It exposed that `place()` over all twelve declared buffers fails for this shader — i.e. the first implementation
  would have refused **every** hair draw live, silently.
- **P2 fixed — grey_first (shipped default: on) was never exercised live.** Added the `on-grey-default` run.
- **P2 recorded, not fixed — switch-off parity is proven by inspection and at material level, not against a pre-W5
  build.** No build with the branch compiled out was made; the gate compares unset with `=0` and pins the material's own
  answers, and every write in the path is under `if (hair)`.
- **P3 fixed** — the hair sky lookup now also checks the salted key the build writes; `sky_layer::members` failures clear
  the declaration list instead of leaving a partial parse; the pair must be one buffer's and `g_AnisoParam2` unique; the
  live negatives now compare their materials with the switch off; the docstring's remaining details are asserted (625
  blobs, one-buffer pair, the draws' blend/depth state, the exact 1,1,0 lobe pattern, the four instruction shapes).
- **P3 recorded, not fixed** — `sky_layer::detail::value` validates all four lanes, so the lobe refuses on garbage in
  `.y/.z` (conservative: today's material, and the measured draws carry 0.1/70 there); a transient constant-buffer read
  failure flips a first-sight draw's mesh key once (only reachable with async reads, which default off); `alpha_to_coverage`
  is not modelled in `hair_class::Draw` (a blended draw is already refused, and no capture measures A2C on the hair draws);
  `hair_submitted` counts before the upload-dropped path (same shape as the accepted water counter); a shader whose
  bytecode lookup fails once is never re-read as hair (the inherited `pixel_info` policy).

## Suite

- `runtime/suite-w5-hair/full-suite.json` (`f69a2552…`) — **135/135**, `-j 14`, 352.3 s, `source_unchanged: true`, with
  the first version of this change (before the review fixes).
- `runtime/suite-w5-hair-s2/full-suite.json` (`80fbb953…`) — **136/137**, `-j 14`, 315.1 s, after the review fixes. The
  one red is `test_private_run_prefix.py`, which **passed (0.1 s) in the first suite** and whose failure is unrelated to
  this item: `runtime/game-runs/game_run.py` was rewritten at **12:54:42 today** by another process (it now calls
  `prepare_private_prefix(RUNS / a.template, …)`, a path the test's patched `RUNS` does not contain), while no file this
  item touched is named there. Recorded rather than "fixed": it is another writer's in-flight work. See
  `runtime/auto/BLOCKED`.
- `test_live_water.py`, `test_sky_layer.py`, `test_sky_scale.py` re-run green after the shared changes
  (`sky_layer::both_members`, clear-on-parse-failure, the rigid-path salt).

## Files touched (SHA-256)

```
4efcf59f…  checks/hair_class.h                     (new)
2fcb0fbc…  checks/test_live_hair.py                (new)
21461d9d…  replay/execution-2026-11-14/w5_hair_census.py  (new)
1af5f34e…  checks/sky_layer.h                      (both_members only)
d93aca29…  checks/live_capture.h
a2c63617…  checks/live_types.h
315232fe…  checks/live_scene.h
72a16c50…  checks/remix_live.cpp
2531e41f…  checks/remix_live_fake_runtime.cpp
a088ecab…  checks/menu_overlay_mock_game.cpp
```
