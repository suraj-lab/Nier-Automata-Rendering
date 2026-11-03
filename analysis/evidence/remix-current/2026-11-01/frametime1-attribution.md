# frametime1: where the late-run slowdown actually is (offline attribution, no new run)

Source: `analysis/runtime/laptop-port/frametime1-20261101T203530Z.json` (log, 7,390 lines, 20:35:35.835 –
20:41:10.222), DLL `8b0f167225e480c3`, AC / Performance, `NIER_REMIX_LIVE_MIN_INDICES=3`, `TEX_PER_FRAME=16`,
build budget 4000 us. Recording `analysis/runtime/laptop-port/frametime1/frametime1.mp4` starts 20:37:16 and ends
20:41:10, so it covers everything after the first minute of the log.

Method: every 60-frame report window was paired with the `live draws` / `live rebuilds` / `live reads` report emitted at
the same timestamp; cumulative counters were differenced between consecutive reports, so each number below is the work
done in one report window (~4.6 s at 13 fps). Windows with fewer than 100 instances are excluded (menu / pre-scene),
leaving 55 of 64. "fast" = fps >= 13 (28 windows), "slow" = fps < 11 (10 windows). Pearson r and Spearman rho are
against that window's fps.

## Result

| metric per window | fast median | slow median | mean | r (fps) | rho (fps) |
|---|---:|---:|---:|---:|---:|
| **other** (ms/frame) | 3.65 | **38.55** | 21.83 | **-0.79** | -0.73 |
| readback (ms/frame) | 56.50 | 59.15 | 58.02 | -0.08 | -0.36 |
| texture capture (ms) | 12.50 | **167.00** | 75.27 | -0.75 | -0.62 |
| texture uploads | 2.00 | 60.50 | 31.04 | -0.69 | -0.62 |
| texture-triggered mesh rebuilds (`texture=`) | 0.00 | 13.00 | 19.87 | -0.61 | -0.47 |
| captures created (`created`) | 0.00 | 9.00 | 31.91 | -0.57 | -0.38 |
| read requests | 243.50 | 354.50 | 303.78 | -0.69 | -0.52 |
| read time (ms) | 329.00 | 509.50 | 368.67 | -0.84 | -0.74 |
| read bytes (kb) | 962,560 | 1,431,552 | 1,088,314 | -0.83 | -0.70 |
| builds deferred by budget | 4.50 | 122.50 | 282.71 | -0.62 | -0.46 |
| mesh builds (`built`) | 3,760 | 4,268 | 3,995 | **-0.09** | -0.33 |
| mesh bytes (MB) | 12.49 | 76.31 | 45.02 | -0.39 | -0.40 |
| scene instances | 382 | 390 | 522 | +0.08 | -0.11 |
| pose rebuilds | 0 | 0 | 0 | n/a | n/a |

`other` is computed in `remix_live.cpp` as wall time per frame minus update/submit/present/copy/readback/convert/publish,
so it is the only bucket that absorbs everything unaccounted, including the wait for the game's next frame.

Against `other`, the strongest correlations are `created` +0.86, `read requests` +0.82, `texture-triggered rebuilds`
+0.82, `deferred builds` +0.81, `read bytes` +0.77, `texture uploads` +0.70, `texture capture` +0.69. Against
`readback` they are all weakly negative (-0.09 … -0.46), i.e. the path tracer is not what got slower.

## Reading

1. **Path tracing did not slow down.** `readback` (56.5 -> 59.2 ms/frame) is flat and the scene draw count is flat.
   The loss is entirely in the worker's unaccounted time, 10.6x.
2. **Mesh churn is not the cause either.** `built` per window is flat (1.13x, r -0.09) and `pose=0` in all 55 windows,
   which independently confirms Phase 4 removed skinned-pose churn.
3. **What does scale with the loss is ingest of streamed content**: texture capture time 13.4x, texture uploads 30x,
   capture creation 0 -> 9 (up to 723 in the loading windows), deferred builds 27x, and meshes rebuilt *because* a
   deferred texture finally landed (0 -> 13/window). Larger meshes arrive too (bytes 6.1x) while the build count
   stays flat, which is the high-LOD content arriving.
4. So the operator's "LOD and textures" instinct is right about the *content*, but the cost is not the game's LOD
   switching and not the path tracer: it is our ingest of what streams in with higher LOD, charged to the frame.
5. The two catastrophic windows (2.7 fps at 20:38:16, 2.9 fps at 20:36:32) are the same mechanism at loading scale:
   `created` 294/723, texture capture 289/396 ms, deferred builds 3,660/1,596, `game_max_ms` 155/348.

## What this does not settle

`other` cannot distinguish (a) the worker idling while the game thread does texture capture, from (b) unaccounted
worker CPU (buffer captures, mesh builds, texture-triggered rebuilds). Both are consistent with the correlations, and
both point at the same fix family, but the split changes which fix pays first. One env-only A/B separates them:
same save, same spot, `NIER_REMIX_LIVE_TEX_PER_FRAME=0` versus `16`. If `other` collapses with texture capture off,
(a) is the mechanism and the fix is to move capture off the game thread's critical path (the planned async readback);
if `other` stays high, (b) is the mechanism and the fix is the build budget / texture-triggered rebuild path.

Second, cheap: `NIER_REMIX_LIVE_BUILD_MS=0` versus `4000` (`deferred builds` 4.5 -> 122.5 per window).

Caveats: `funnel` counters appear in two line variants that reset at different points (`topo`/`unchanged` deltas can go
negative), so nothing above uses them. `decode_failures=313` was all reached before the first report window and did not
grow; it is not part of this slowdown. Report windows are 60 worker frames, not equal wall time, so cross-window
comparisons are per-window rates, not per-second.

## Settled offline (2026-11-03): (b), texture conversion on the Remix worker, untimed

No laptop run was needed. Three independent pieces:

1. **Source.** `remix_live.cpp` (`frame()`, the loop over `take_textures()` right before `live update`) runs
   `to_channel` (metallic / roughness R8), `to_octahedral` (normal -> RGBA8) and `write_dds` for every new texture **on
   the Remix worker, outside every timed stage**, so its whole cost lands in `other`. It was moved there from the game
   thread on 2026-10-31 (1.1 s game freezes, `live_types.h` comment on `TextureFile`); the cost moved, it did not go.
2. **Cost, desktop native x64 -O2** (`normal_octahedral.h` / `mask_channels.h` as shipped, BC1 full mip chain):

   | size | octahedral normal | one mask channel |
   |---|---:|---:|
   | 1024 | 20.3 ms (5 MB RGBA8 out) | 12.4 ms |
   | 2048 | 81.0 ms (21 MB) | 49.3 ms |
   | 4096 | 323 ms (85 MB) | 197 ms |

   A material with normal + metallic + roughness at 1024 is ~45 ms before the file write; the laptop runs the x64 DLL
   under ARM64 emulation, so slower. The log gives 25-40 ms of `other` per new texture output: consistent.
   Windows with no new texture outputs: `other` 3.2 ms, 14.1 fps (n=18); with any: 23.0 ms, 12.1 fps (n=35).
3. **The recording** (post-tonemap ground truth; method from Rayman3-RTX `session-findings-20261103.md` 6.1),
   `frametime1_video.py`: per report window, the longest visible freeze correlates with new texture outputs
   **r = +0.70**, distinct-image rate with them r = -0.69 (44 windows). Freezes of 0.77-1.74 s sit in exactly the
   texture-burst windows (20:38:16, :21, :28, :37, :56, 20:39:30, 20:41:08). That is what the user saw as
   "LOD/texture slowdowns".

So the fix is not the game-thread readback. It is either moving this loop off the render worker (a writer thread;
a material appears when its file exists, `test_live_late_material.py` territory) or making the conversion cheap:
`bc1_texel` re-decodes both RGB565 endpoints for each of the 16 texels of a block, with float maths per texel.

## Next actions, in order

1. ~~The two env-only A/Bs above~~ — superseded by the section above; no run needed to pick the fix.
2. Whichever leg wins, gate the fix offline first: async texture readback (extends the existing buffer read path in
   `live_capture.h`) or a texture-triggered-rebuild budget, both testable with the Wine mock as `shared-mask.md` and
   `frame-copy.md` were.
3. Do not change LOD policy: `built`, `pose` and instance counts say it is not the churn.
