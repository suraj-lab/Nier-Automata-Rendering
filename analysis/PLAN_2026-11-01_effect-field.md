# Plan: the `effect=` log field (next session, approved, not yet executed)

Status: **approved for the next session, nothing executed yet.** Written 2026-11-01 at the end of the session that
produced `analysis/evidence/remix-current/2026-11-01/material-roles-coverage.md`. Background and the measurement that
led here: that document, sections 1 and 7.

## Correction this plan rests on

An earlier reading — mine — said the `effect=` field in every `remix: material` line is a literal `false`, so the column
was useless. That is wrong, and the evidence doc has been corrected:

- `live_capture.h:1332` calls `note_material({current_ps(context), true, {}, {}, 7})` for the draws it skips **as**
  effects. Those lines carry `effect=1`; 40 of the 128 logged lines across the three 2026-11-01 runs do.
- `live_capture.h:1511`, the capture path, hard-codes `false`. Effect draws never reach it **unless**
  `NIER_REMIX_LIVE_EFFECTS=1` keeps them in the scene, and then they are logged `effect=0`.

So the field is accurate for skipped effects and lies only when effects are kept. Consequence for the material analysis:
frametime1's 45 `effect=0` lines are genuinely non-effect draws, which is what the classification in the evidence doc
assumes. No conclusion in that document changes.

## 1. Files or areas involved

| file | role |
|---|---|
| `analysis/checks/live_capture.h` (line 1511) | the hard-coded `false` in the `note_material(...)` call |
| `analysis/checks/test_live_normal_map.py` | parses `remix: material` lines but asserts nothing about `effect` |
| `analysis/evidence/remix-current/2026-11-01/material-roles-coverage.md` | **already corrected** in the 2026-11-01 session |

## 2. What changes and why

- **Code, one expression:** `note_material({current_ps(context), false, …})` becomes `pixel.effect`. With
  `NIER_REMIX_LIVE_EFFECTS=1` an effect draw is currently logged `effect=0`; that is the one case where the column lies,
  and the flag is already computed at line 1123 (`declares_effect_buffers`). No rendering change.
- **Test:** two assertions in the Wine mock — a draw declaring `t27`/`t30` (what `declares_effect_buffers` looks for)
  logs `effect=1`, an ordinary draw logs `effect=0`. Without this the one-liner cannot be verified offline.
- **Not proposed:** any metal/gloss implementation (the 218-shader gap has no verified design; it needs corpus research,
  not code), the terrain-repeat re-log and the per-instance tint bake (both invisible while roughness is a constant
  0.6 / metallic constant 0 for 83% of shaders), and any live game run.

## 3. What could go wrong

- The mock may not produce an effect shader today. Then the mock's shader set has to grow, which touches a fixture other
  live tests share — that is the real risk in this change and it can ripple.
- The DLL boundary changes, so a future install is a new build hash and receipts must record it. No install is part of
  this plan.
- Re-running the full suite may surface failures unrelated to this change; report them, do not "fix" them quietly.

## 4. How to verify

1. `python3 analysis/checks/test_live_normal_map.py` green, **and red when the one-liner is reverted** (mutation check,
   project convention).
2. `python3 analysis/checks/test_roles_coverage.py` still green — unchanged behaviour.
3. Full gate suite as the last checkpoint counted it (77) plus the new role gate = 78/78.
4. Read the evidence doc's `effect=` paragraph against `live_capture.h` lines 1332 and 1511; the claim must match source.
5. Honest limit: offline proves the mock path only. The field is proven live on the next approved game run.

## Preconditions

- No game run, no install, no commit without the operator's word. `main` was at `79394e5` with four untracked artifacts
  (two evidence notes, the roles gate and its fixture) at the end of the 2026-11-01 session.
