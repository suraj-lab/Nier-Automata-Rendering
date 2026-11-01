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

## Start here: frametime1 (DLL 8b0f1672, AC / Performance, original game files restored)

- Both frame-time optimizations passed 77/77 offline gates: SSE2 frame conversion and one mask readback shared by
  metallic/roughness within a draw. User: "Frame time seems a lot better", with remaining slowdowns appearing
  related to LOD/textures. That cause still needs attribution.
- World-associated reporting windows (at least 100 instances at report time): conversion **3.5 ms**, versus
  **11.0 ms** in the earlier AC `pbr-look1` run; readback wait **58.4 ms**, world Remix FPS median **13.1**.
  Different scenes/builds/draw thresholds prevent a controlled total-FPS comparison. Do not compare the last
  battery run's 8 FPS to this AC run as a code-only gain.
- Late windows fall to 8.8-9.0 FPS; final cumulative counts: 226,924 mesh builds, 12,702 resident meshes,
  2,476,290,488 mesh bytes, 1,723 texture outputs. Investigate churn and stream-in before changing LOD rules.
- Recording contact sheets still show green/blue character/pod overlays, white sheets, smooth-looking dunes and
  chrome-like distant terrain. The low threshold remains 3; these visual faults remain unresolved.
- Saved receipt: `analysis/runtime/laptop-port/frametime1-20261101T203530Z.json`; video/contact sheets:
  `analysis/runtime/laptop-port/frametime1/` (ignored local artifacts). Durable findings:
  `analysis/evidence/remix-current/2026-11-01/frametime1.md`.
- **Resume offline:** align the recording (starts 20:37:16) with log timestamps; compare slow-window texture-time
  deltas, mesh rebuild reasons, scene counts and worker stage times. Distinguish game LOD changes from capture
  churn, texture uploads and GPU rendering waits. No further run or code change is scheduled until resumption.

## Prior run: pbr-verify1 (DLL 7f56d0a7, `NIER_REMIX_LIVE_MIN_INDICES=3`, on battery)

- Albedo/metal roles now traced live (17-18 world shaders each in the logged set).
- **Foliage and grass are back** with the size filter lowered: the 128-index filter was the cause.
- **New problems, all from small draws the filter used to hide:** 2B drawn solid green (pod/access point) and with
  blue overlays (desert); large white slabs in the sky and flat pale cards on the ground; floating orange/brown
  sheets. Cost: accepted draws 124 -> 8,588 per window, 169,916 meshes built.
- **Unchanged:** flat untextured dunes, white city ground, chrome-looking far terrain and rocks. The logged terrain
  repeat was `1,1` (logged at the first draw, before the constant buffer is readable, so not yet conclusive).

## Plan, in order

1. **Small draws: keep foliage, drop overlays (replace the blunt threshold with a rule).**
   - First use `frametime1`'s existing recording/logs to attribute the late slowdowns and isolate overlay candidates.
     If more evidence is needed, extend draw diagnostics with depth write, blend, alpha test, layout semantics,
     viewport, texture count and PS family. `remix: small` only logs rejected draws, so accepted small draws need
     a diagnostic too. Any new laptop run needs approval.
   - Candidate rule to test, not a verified classifier: keep small surface draws with an opaque or alpha-tested
     material shader; distinguish no-depth-write/flat-colour overlay draws without discarding legitimate foliage.
   - Gate: mock with a foliage-like small draw (kept) and an overlay-like one (dropped). Then one live run.
   - Watch the cost: decide whether per-instance small meshes need batching (FO4-Remix uses GPU instancing).
2. **Terrain look (flat dunes, white ground).**
   - Log the repeat after the constant buffer is readable, not at the first draw; confirm the real `cb1[5]` values.
   - If they are 1, inspect vertex-shader output and the source UV stream for upstream tiling; do not assume it.
   - Then choose a representative layer for the 3-layer height blend (dominant vertex weight per draw).
3. **Chrome far terrain / rocks.** In-run A/B like the hold toggle: PBR textures and normals on/off every few
   seconds, to attribute it to roughness, normals, or something outside the material. Terrain gloss comes from
   per-layer constants (cb1[3], cb1[4]); send those as roughness constants once attributed.
4. **Washed out colours.** Bake the per-instance tint (`cb4 * cb8[instance]`) the shader multiplies into albedo;
   consider the second-UV multiply texture (slot 1). Compare one frame against the game's own image.
5. **Frame times.** First offline optimization implemented: `frame_copy.h` replaces the scalar readback colour
   conversion with baseline SSE2 (four pixels at a time). Desktop benchmark at 2880x1800: BGRA 2.373 -> 0.733 ms,
   RGBA 2.386 -> 0.855 ms (2.8-3.2x faster for conversion only). Byte-exact sanitizer gate, two mutation checks,
   Windows cross-build and full suite 77/77 passed; initial DLL `4103584bf8ef5cf5`. The combined build's
   `frametime1` run measured conversion at 3.5 ms in world-associated windows. GPU/readback waits remain dominant.
   Evidence: `analysis/evidence/remix-current/2026-11-01/frame-copy.md`.

   Second offline optimization implemented: metallic and roughness share one raw mask capture within the draw.
   The Wine mock observes one mask staging copy instead of two, with identical channel outputs; a one-readback
   budget still defers and retries correctly. Mutation check and full suite 77/77 passed; combined DLL
   `8b0f167225e480c3`, subsequently used for `frametime1`. No isolated live FPS/hitch gain attributed to sharing.
   Evidence: `analysis/evidence/remix-current/2026-11-01/shared-mask.md`.

   Prior runs, before this optimization (Remix worker, ms per Remix frame, medians):

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
        FO4-Remix does (`analysis/FO4_REMIX_RECONSTRUCTION.md`, "second window presenter"). Could avoid CPU readback
        and the remaining conversion (3.5 ms in `frametime1`); it cannot remove path-tracing time hidden in the wait.
        Plan HUD composition and verify frame-generation/Reflex requirements separately.
     c. Cut path-tracing load where it is not visible: the small-draw rule (step 1) instead of a low threshold,
        effects out, rtx.conf quality settings chosen by measurement, not guessed.
   - **Game-thread spikes (window-maximum p90 78-208 ms) need attribution.** Attribute them with the existing `slow_*` phase counters
     (reads / texture / build) per window; known suspects: GPU texture readbacks on the game thread (up to
     `NIER_REMIX_LIVE_TEX_PER_FRAME`=16 per frame; duplicate mask reads now removed within a draw), mesh decodes
     during stream-in, and the mesh churn the low size threshold caused (169,916 builds). Remaining fixes follow
     the measurement: async texture readback like the buffer reads, and the build budget for decodes.
   - Target, to be checked by measurement: game frame p90 under 33 ms (no visible hitches), Remix frame under
     33 ms before frame generation. Always compare on AC power (receipts record `power_start`).
6. **Effects (particles, smoke).** Left out by decision; revisit after 1-4 (the game's own effects could be
   composited over the Remix image).
7. **Movement** (the bigger pop-in challenge): scripted walks on a long open path; metric is holes weighted by
   screen size, not dropped keys.
8. **Housekeeping.** Runs on battery are slower (receipts record `power_start`); plug in for comparable runs.
   `main` is ahead of `origin`: push when you say so.
