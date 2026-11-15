# W3 step 2 — water classification, gated against hair/foliage/glass negatives

Date: 2026-11-15 (unattended iteration). Plan: `PLAN_2026-11-14.md`, W3 step 2. Status: **accepted offline, default off.**
Nothing was installed, run live, or written outside this repository; no GPU workload, no game folder change, no laptop or
remote action, nothing committed.

## What the step asked for, and what was built

> "Gate classification against hair/foliage/glass negatives. Teach fake runtime to inspect translucent extensions,
> blend/category flags and resource lifetimes. Off retains today's cutout path. Mutation: classify all blends as water or
> retain forced cutout on selected water; both must fail."

| Requirement | Where |
| --- | --- |
| classification | `checks/water_class.h` (new): pure C++, one rule table, a reason code per refusal |
| switch, default off | `checks/live_capture.h`: `NIER_REMIX_LIVE_WATER=1` (only `=1` enables it), counters `water_draws` / `water_submitted` / `water_refused`; also printed as `remix: live water …` by `checks/remix_live.cpp` |
| declaration read | `live_capture.h`: the pixel shader's DXBC `RDEF` member `g_TranslucentParam`, via the existing `sky_layer::members` parser — never a shader name, never a value |
| own mesh key | `live_capture.h`: a classified water draw is keyed `^ 0x77617465725f7375`, so its translucent mesh cannot displace the cutout/opaque mesh built from the same buffers (same pattern as E1.6's particles) |
| translucent material | `checks/live_scene.h`: `material_for(..., bool water)` chains `remixapi_MaterialInfoTranslucentEXT` after today's opaque ext, with its own material key and hash; the `grey_first` refresh keeps the flag |
| instance category | `live_scene.h` `submit`: `ANIMATED_WATER`, and the forced `ALPHA_BLEND_TO_CUTOUT` is skipped — only for a mesh that is not bare |
| fake runtime inspection | `checks/remix_live_fake_runtime.cpp`: `trans=1 index=… diffuse=… thinwall=… transcol=… dist=…` on every `CreateMaterial`; `matlive=0/1/-1` on every `DrawInstance` plus a `VIOLATION … which is not live` line; material-hash lifetime accounting (`material_live`, `mesh_material_hash`) |
| fixture | `checks/menu_overlay_mock_game.cpp`: `MOCK_WATER_PS` (a world shader that declares `g_TranslucentParam` in a named cbuffer and reads it as a no-op at 0, because a compiler drops a declared-but-unread cbuffer from RDEF), and a discarding variant when `MOCK_CUTOUT_PS` is also set |
| gate | `checks/test_live_water.py` (new, SHA-256 `44dbdbd535c04eba…`) |

## Measured facts the classifier keys on (not remembered — re-read by the gate)

`replay/execution-2026-11-14/w3_water_census.py` → `runtime/live-water/census.txt`, over
`runtime/laptop-play-20261114` (frames `frame_67078468` pond, `frame_67279062` desert, 625 shader blobs):

- **7 of the 625 blobs declare `g_TranslucentParam`.** Two of them are the shaders the two frames draw
  (`ps_550347550280`, `ps_550347548488`); the other five (`ps_550347546696`, `…549384`, `…550728`, `…551176`, `…551624`)
  are variants of the same family that neither frame draws. Every declarer also declares `g_RefractParam`,
  `g_WaterFogParam` or `g_WetParam1`.
- **Of the 31 shaders the two frames draw, exactly those two declare it.** The gate asserts both facts (it rescans every
  blob and guards against a skip: an unparseable RDEF fails the gate rather than passing silently).
- **All 20 water draws are in state (blend_enable 1, SRC_ALPHA 5, INV_SRC_ALPHA 6, op ADD 1).**
- **`g_WaterFogParam` alone cannot be the test:** only `ps_550347548488` declares it, and the capture's largest
  translucent surface (16,848 indices) belongs to the shader that does not.
- **Blending alone is not water:** the seven other blended shaders of the same captures are the post/effect passes
  (declaring `g_EffectPixelCommonBuffers`), `ps_550292875656`, and the surface shaders `ps_550339515912` /
  `ps_550337747400` — none declares the water member. (What `550292875656` is remains undetermined in the recon; it
  matters only that it is not water.)
- The camp capture is **not** read by this gate; `replay/execution-2026-11-14/README.md:90` records water keywords there,
  so the claim above is scoped to the pond and desert captures.

## The classifier (`water_class::why`, first rule that matches)

Blend enabled → (not alpha-to-coverage, op ADD, SRC_ALPHA/INV_SRC_ALPHA) → not alpha-tested → not skinned → not sky →
not an effect shader → not a depth pass → has a captured albedo → declares `g_TranslucentParam` → **water**.

A refusal always beats the declaration, which is exactly the first mutation the plan names.

## Gate result — red before, green after (frozen first)

- **Red (before any implementation):** part 1 (the measured table above) passed; part 2 failed with
  `fatal error: water_class.h: No such file or directory`. That is the right reason: the gate needed the module, not a
  passing no-op.
- **Green:** `python3 checks/test_live_water.py` prints
  `W3 water class gate: OK` and, per case:
  - `default` — 189 blended instances, all `ALPHA_BLEND_TO_CUTOUT`, no material carries translucency, nothing counted;
  - `zero-parity` — unset and `=0` submit the same category multiset and the same material-hash set;
  - `on-water` — every instance `ANIMATED_WATER`, none cutout; one `CreateMaterial … trans=1 index=1.330 diffuse=1
    thinwall=0,0.000 transcol=1.000,1.000,1.000 dist=0.000`, naming the same albedo the cutout material names and a hash
    no cutout material uses; `submitted>=1`, `refused=0`;
  - `on-glass` — blended, no declaration: cutout as today, nothing submitted;
  - `on-foliage` — an alpha-tested card that *does* declare the member: cutout as today, never water;
  - `on-additive` — additive blending: no category bit at all, as today, never water;
  - `lifetimes` — every `DrawInstance` in all six runs resolves its mesh to a *live* material hash (`matlive=1`, no `-1`,
    no `VIOLATION`).

## Mutations — 17 red, each file restored byte-identically

`replay/execution-2026-11-14/w3_water_mutations.py` → `runtime/live-water/mutations.json` (run on the final tree,
SHA-256 of every restored file asserted equal before/after). The two the plan names are first and seventh:

| # | mutation | scope | result |
| --- | --- | --- | --- |
| 1 | classify every blend as water (drop the declaration rule) | native | RED |
| 2 | accept an alpha-tested card | native | RED |
| 3 | accept a skinned draw | native | RED |
| 4 | accept a non-alpha blend state | native | RED |
| 5 | accept a draw with no albedo | native | RED |
| 6 | accept a sky draw | native | RED |
| 7 | **retain the forced cutout on selected water** | full | RED |
| 8 | drop the `ANIMATED_WATER` bit | full | RED |
| 9 | send the material without its translucent extension | full | RED |
| 10 | let a water material share the cutout material's hash | full | RED |
| 11 | let a water material be the cutout material itself | full | RED |
| 12 | a guessed refractive index (1.30) | full | RED |
| 13 | drop the diffuse layer | full | RED |
| 14 | refresh a water material as a cutout one | native | RED |
| 15 | treat the declaration as always present | full | RED |
| 16 | skip the classifier for every blended draw | full | RED |
| 17 | drop the water geometry key | full | RED |

## Independent review — `reviewer` on `anthropic/claude-haiku-5-5` (one round, synchronous)

Verdict "OK with notes"; no P0. Dispositions:

- **P1.1 (gate integrity) fixed:** the lifetime check filtered out `matlive=-1` (a bare mesh passes "live" vacuously).
  The gate now asserts on every instance, `-1` included.
- **P1.2 fixed:** the foliage and additive cases only checked "not water"; they now pin today's path too (foliage
  `CUTOUT` and not `WATER`; additive neither bit — additive is not "blended" in the capture's narrow sense, so today's
  submission is opaque, which the reviewer's suggestion would have asserted wrongly).
- **P1.3 fixed:** part 1 accepted a *missing* water shader blob (`is not False` on `None`); now `is True`.
- **P2.4 fixed (record):** there is no has-value flag for `transmittanceMeasurementDistance`, so 0 is what "not measured"
  looks like on the wire; the comment now says that, and the gate pins `dist=0.000`.
- **P2.5 fixed:** with `GREY_FIRST=0`, a water draw whose albedo never landed could have carried `ANIMATED_WATER` over a
  bare mesh; the bit is now set only for a mesh that is not bare, and the `material_for` comment matches what happens.
- **P2.6 fixed:** the "albedo path" assertions were tautological; the native harness now compares the water and cutout
  materials' `albedoTexture`, and the fake part compares the water material's `path=` with the cutout run's.
- **P2.7 fixed:** the "only two shaders" claim was not gated and over-generalised; part 1 now rescans every blob and the
  docstring/`water_class.h` scope the claim to the two captures read (7 declarers of 625, 2 of the 31 drawn).
- **P2.8 fixed:** the mutation runner and its JSON are kept (paths above) and summarised here.
- **P3.9/P3.10/P3.12/P3.13 recorded and applied:** the capture's state record has no alpha-to-coverage field, so the
  comment no longer claims it was measured; `550292875656` is no longer called the sky; "writes depth" removed; the
  `useDiffuseLayer = 1` choice is labelled unmeasured.
- **P3.11 recorded:** the recon's desert count for `ps_550347548488` (5 drawn, the records hold 1) is a recon arithmetic
  slip; the classifier's `20` is right and the gate counts the draws itself.
- **P3.15 fixed:** the classifier input is only built when the switch is on, and the sky comment now says what the lookup
  really does (pre-salt geometry key; no entry on a first sight).
- **P3.16/P3.17 recorded as limitations** (below).
- Not checked by the reviewer: the runtime source is not in that checkout, so the "the runtime resolves a material by
  hash" claim was not re-verified; and it could not run the gate (no shell). The lead re-ran the gate and all mutations.

## Full suite

- `runtime/suite-w3-water` — **133/134**, red only `test_live_water.py`: the mock's `wine` launch hit its 180 s timeout
  (`TimeoutExpired … after 180 seconds`), not an assertion.
- `runtime/suite-w3-water-s2` — **133/134**, same single timeout at the same first launch.
- Both were re-run alone and the suite re-run after the cause was fixed: `outside()` now uses the same isolated, warm
  `WINEPREFIX`/`HOME`/`XDG` environment as every other live gate (`runtime/live-water/prefix`) instead of inheriting the
  suite's fresh per-run HOME, which made every run pay a full `wineboot` under 14-way load.
- **`runtime/suite-w3-water-s3` — 134/134, wall 310.1 s, `-j 14`, source unchanged.** Green.

## Limitations, recorded honestly

- **Nothing about the appearance is measured.** `refractiveIndex` 1.33 is water's; `thinWallThickness` stays unset
  (0) and `transmittanceMeasurementDistance` is 0 because no offline evidence fixes their scene units; `useDiffuseLayer
  = 1` is a choice for W3 step 3/4, not a measurement. The real runtime's handling of a zero distance with no
  transmittance texture is unverified — W3 step 3 must check it against the pond capture.
- **The water sheet is not identified yet.** The 16,848-index draw is the recon's best candidate; W3 step 1's
  hide-one-candidate A/B still has to prove it.
- **Hair has no live fixture** (the mock game draws no skinned card): the classifier's refusal of skinned and
  alpha-tested draws is pinned natively only.
- **`ANIMATED_WATER` semantics:** the repo's notes disagree on whether the category bit alone is enough or the
  `rtx.translucentMaterial.animatedWaterEnable` config is also needed (`web_remix_effects_sky_water.md`). Unresolved;
  part of W3 step 3.
- **`NIER_REMIX_LIVE_GREY_FIRST=0` (rollback only):** a water draw whose albedo is deferred flips to `texture = 0` and
  back, so it alternates between the water key and the cutout key until the file lands; the stand-in path may pair them.
  Transient, rollback-only, unmeasured.
- **The camp capture is unread**, so a shader there could declare the member with a state this classifier accepts;
  the class would then be classified water without a pond check.

## Files touched (SHA-256 of the tree this receipt describes)

```
water_class.h                  e8209d196b75acd2979d2da9665974d3d49190ff4d3ba4a1381b186367190487   (new)
test_live_water.py             44dbdbd535c04eba6888b47a1182179a9549ef463958af41355a8e140edd57cd
live_capture.h                 31782eee7716bfad7549b570b445063ad1319095470c1bef594e6ce07bdf9d4c
live_scene.h                   3a7e749cc1e91bcc2ad0bb867b5c096de3021e333c55a57590bba532259ab91f
live_types.h                   f9334fc997c725083c938f3e924a3e2c216d4f751cd7806270169a04db025b38
remix_live.cpp                 f34c11a1752a9241e2f741e682c4ad0e19446564b3394811ed795c4f78975e0b
remix_live_fake_runtime.cpp    47135307766c0321ccb3465ab4da4927714005c720f261548801ffb7fedf54b5
menu_overlay_mock_game.cpp     235c11900a4523bc0a3c36db75ba751a0df1454f10ad417eed9d07ca9fab7691
```

Evidence: `runtime/live-water/{mutations.json,census.txt}`, `replay/execution-2026-11-14/w3_water_{census,mutations}.py`,
`runtime/suite-w3-water-s3/full-suite.json`.

## What still waits on the user (unchanged by this step)

One fresh live F9 camp/pond capture with `NIER_REMIX_LIVE_TEX_SLOTS=32` (also R2a's cost measurement), and one A/B with
`NIER_REMIX_LIVE_WATER=1` on a pond spot with a labelled sheet — W3 steps 1, 3 and 4. Both need approval under
`AGENTS.md` (copied prefix, RX 6800 XT, save hash before/after); nothing was attempted.
