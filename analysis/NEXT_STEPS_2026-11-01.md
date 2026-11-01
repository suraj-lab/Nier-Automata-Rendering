# Where things stand and what to do next (2026-11-01, end of session)

## Done this session (all gated, committed; details in the linked evidence)

- **Pop-in, still camera and turning:** solved for practical purposes (`analysis/evidence/remix-current/2026-11-01/popin-experiment.md`).
  Decode 10x faster; geometry key on the POSITION stream; shared stale snapshots (never-built objects); range-hash
  rebuild skip; one-frame hold (free, cuts still-camera drop frames 40% -> 6.6%). Instruments: per-frame log,
  return gaps, stuck keys, scripted turns/walks (DirectInput mouse, XInput stick).
- **Materials from the game's own shaders** (`analysis/PBR_MAPPING.md`): per-shader tracer (`pbr_trace.py`,
  C++ `material_roles.h`, identical on 3,688 shaders incl. Microsoft-format disassembly); normal map from the traced
  slot (slot 4 is a detail normal); metallic / roughness R8 textures from the mask, roughness floor 0.15; effects
  shaders left out; terrain texture repeat traced and baked into UVs; per-shader `remix: material` and
  `remix: small` diagnostic lines; `NIER_REMIX_LIVE_MIN_INDICES` A/B switch.
- User verdicts: surfaces "clearly better"; colours "better, but somewhat" washed out.

## Last run: pbr-verify1 (DLL 7f56d0a7, `NIER_REMIX_LIVE_MIN_INDICES=3`, on battery)

- Albedo/metal roles now traced live (17-18 world shaders each in the logged set).
- **Foliage and grass are back** with the size filter lowered: the 128-index filter was the cause.
- **New problems, all from small draws the filter used to hide:** 2B drawn solid green (pod/access point) and with
  blue overlays (desert); large white slabs in the sky and flat pale cards on the ground; floating orange/brown
  sheets. Cost: accepted draws 124 -> 8,588 per window, 169,916 meshes built.
- **Unchanged:** flat untextured dunes, white city ground, chrome-looking far terrain and rocks. The logged terrain
  repeat was `1,1` (logged at the first draw, before the constant buffer is readable, so not yet conclusive).

## Plan, in order

1. **Small draws: keep foliage, drop overlays (replace the blunt threshold with a rule).**
   - Instrument (low threshold run): extend `remix: small` with draw state (depth write, blend, alpha test, layout
     semantics, viewport, texture count) and the PS family; match the green/blue/white cases in the recording.
   - Expected rule: keep small draws that write depth with a surface layout (TEXCOORD/NORMAL) and an opaque or
     alpha-tested material shader; drop no-depth-write, POSITION-only, full-screen/flat-colour overlay shaders.
   - Gate: mock with a foliage-like small draw (kept) and an overlay-like one (dropped). Then one live run.
   - Watch the cost: decide whether per-instance small meshes need batching (FO4-Remix uses GPU instancing).
2. **Terrain look (flat dunes, white ground).**
   - Log the repeat after the constant buffer is readable, not at the first draw; confirm the real `cb1[5]` values.
   - If they are 1, the repeat lives in the vertex shader: capture VS bytecode as PS already is, trace `v2`.
   - Then choose a representative layer for the 3-layer height blend (dominant vertex weight per draw).
3. **Chrome far terrain / rocks.** In-run A/B like the hold toggle: PBR textures and normals on/off every few
   seconds, to attribute it to roughness, normals, or something outside the material. Terrain gloss comes from
   per-layer constants (cb1[3], cb1[4]); send those as roughness constants once attributed.
4. **Washed out colours.** Bake the per-instance tint (`cb4 * cb8[instance]`) the shader multiplies into albedo;
   consider the second-UV multiply texture (slot 1). Compare one frame against the game's own image.
5. **Frame times.** Measured (Remix worker, ms per Remix frame, medians):

   | run | power | Remix fps | readback | convert | submit+update | game worst frame p50 / p90 |
   |---|---|---|---|---|---|---|
   | gaps-b4000 | AC | 14.9 | 54.5 | 10.0 | 1.4 | 56 / 78 |
   | toggle-b4000 | AC | 13.9 | 57.8 | 10.7 | 2.0 | 73 / 86 |
   | pbr-look1 | AC | 13.1 | 56.8 | 10.9 | 2.7 | 61 / 154 |
   | pbr-diag1 | battery | 9.6 | 84.3 | 11.9 | 2.5 | 68 / 131 |
   | pbr-verify1 | battery | 8.1 | 95.4 | 11.9 | 5.9 | 93 / 208 |

   Two separate problems:
   - **Remix frame time (~70 ms) is the readback path.** We wait for the path-traced image, copy it back to the CPU
     (`readback`) and convert it for the game's swapchain (`convert`). Submission is ~2 ms. Steps:
     a. Split `readback` into GPU path-tracing time vs. the copy itself (Remix's own frame timing; one run at a
        lower `rtx.resolutionScale` / DLSS Ultra Performance to see how it scales).
     b. **Remove the readback: let Remix present directly**, in its own window or swapchain over the game window, as
        FO4-Remix does (`analysis/FO4_REMIX_RECONSTRUCTION.md`, "second window presenter"). Saves the copy and the
        10-12 ms convert, and is the prerequisite for DLSS frame generation and Reflex. The HUD then has to be
        composited by Remix's side (the game's HUD replay already exists).
     c. Cut path-tracing load where it is not visible: the small-draw rule (step 1) instead of a low threshold,
        effects out, rtx.conf quality settings chosen by measurement, not guessed.
   - **Game-thread spikes (p90 78-208 ms) are ours.** Attribute them with the existing `slow_*` phase counters
     (reads / texture / build) per window; known suspects: GPU texture readbacks on the game thread (up to
     `NIER_REMIX_LIVE_TEX_PER_FRAME`=16 per frame, two per mask now), mesh decodes during stream-in, and the mesh
     churn the low size threshold caused (169,916 builds). Fixes follow the measurement: async texture readback
     like the buffer reads, one readback per mask for both derived textures, and the build budget for decodes.
   - Target, to be checked by measurement: game frame p90 under 33 ms (no visible hitches), Remix frame under
     33 ms before frame generation. Always compare on AC power (receipts record `power_start`).
6. **Effects (particles, smoke).** Left out by decision; revisit after 1-4 (the game's own effects could be
   composited over the Remix image).
7. **Movement** (the bigger pop-in challenge): scripted walks on a long open path; metric is holes weighted by
   screen size, not dropped keys.
8. **Housekeeping.** Runs on battery are slower (receipts record `power_start`); plug in for comparable runs.
   `main` is ahead of `origin`: push when you say so.
