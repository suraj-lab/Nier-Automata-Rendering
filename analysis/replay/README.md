# Offline replay: NieR's live Remix path without the game (2026-11-12)

Replays an F9 capture's draw stream through the real proxy `d3d11.dll` every frame. The proxy then does what it does
in the game: it captures the draws, builds meshes and materials, and drives Remix. It needs no laptop, no game and no
monitor.

| file | what |
|---|---|
| `pack_capture.py` | F9 frame -> flat manifest + one constant-buffer blob. Hard-linked capture buffers stay one buffer. |
| `capture_replay.cpp` | Win64 replayer. Real PS blobs, layouts, CBs, textures, states and lights; a generated no-op VS (no VS blobs in captures). |
| `run_replay.py` | `--mode real` = Proton + real Remix in headless gamescope on the **RX 6800 XT** (drives no monitor). `--mode fake` = Wine + Xvfb + fake runtime. `--mode off` = hooks only. Writes `runtime/replay/<label>/summary.json` + `shot-N.png`. |
| `view.py` | Shrinks a shot or crop so an agent can look at it. Read it with `offset=1` (context-mode blocks whole-file reads). |

Runtime: `--runtime .../PortalRTX/bin/.trex/d3d9.dll`. The `runtime/remix-1.6.1/rt/d3d9.dll` shim failed to load
its `d3d9_x64.dll` (not investigated).

## Baseline (DLL `3c487b0a` (today `04719c50` differs only by the T2 switch), `deploy/rtx/desktop-replay.conf`, 2,500 frames, 6800 XT, XeSS Performance, `minPrimsInDynamicBLAS = 0`)

Each run replays one F9 capture through the real proxy and the real Remix runtime, with the config that is the current
best: `dlssPreset = 2` (see below), XeSS Performance, every mesh in its own BLAS. `readback` is the worker's wait for
the path-traced frame; `game frame p50` is what the game thread (here the replayer's thread) spends per frame, our hooks
included.

| capture | scene | draws | Remix fps | readback ms | game frame p50 ms | `--mode off` ms | capture cost ms | run |
|---|---|---|---|---|---|---|---|---|
| 21396979 camp | 2580x1080 | 3,276 | 52.8 | 16.2 | 5.8 | 1.9 | 3.9 | `p6e-21396979` |
| 21565698 camp | 2580x1080 | 3,185 | 53.3 | 16.2 | 5.6 | 1.8 | 3.8 | `p6e-21565698` |
| 23275488 | 2580x1080 | 1,894 | 50.4 | 18.3 | 3.3 | 1.3 | 2.0 | `p6e-23275488` |
| 30632051 camp | 2580x1080 | 3,382 | 29.3 | 31.1 | 6.4 | 2.0 | 4.4 | `p6e-30632051` |
| 41686139 | 2580x1080 | 2,056 | 43.9 | 21.0 | 3.6 | 1.2 | 2.4 | `p6e-41686139` |
| 220084953 (laptop) | 2880x1800 | 484 | 28.2 | 33.8 | 1.7 | — | — | `p6d-220084953` |
| 220097046 (laptop) | 2880x1800 | 769 | 26.4 | 36.0 | 2.3 | — | — | `p6d-220097046` |

`--mode off` (`off2-*`) is the replayer with capture off: the game's own share of that column. The capture's own cost
is the difference, 0.7-1.3 us per draw, and it includes the reads, the mesh builds and the submission to the runtime -
the per-draw profiling split is in `PLAN_2026-11-12.md`, item P4.

30632051 is the heavy one: 389 alpha-tested (cutout) draws and 452 textures against 0 and 164-182 on the other camps,
and RADV has no opacity micromap.

Before tonight, on the same captures: 30632051 13.5 fps / 73.9 ms game frame (map read-back, P1), 41686139 23.8 fps /
47.8 ms (P1 plus a staging read of the camera on every frame), 21396979 14.5, 21565698 15.2, 23275488 34.5, laptop
24.6 / 22.8.

### Why the upscaler preset did nothing (fixed 2026-11-12)

`rtx.dlssPreset` defaults to `On`, and `updateUpscalerFromDlssPreset` writes `upscalerType = DLSS` into the Derived
layer, which outranks `rtx.conf` (`rtx_options.cpp:159-181`, `rtx_option_constants.h:194`). Without NGX,
`rtx_context.cpp:566` then falls back to TAAU at the non-NVIDIA `resolutionScale` 0.5. So every run before p4 was TAAU,
whatever `rtx.upscalerType` said. `rtx.dlssPreset = 2` (Custom) keeps the conf's upscaler, and the preset starts to
matter: 30632051 goes 25.1 fps (XeSS Performance) -> 31.8 (Ultra Performance) -> 8.2 (Native AA).

### Small meshes: `rtx.minPrimsInDynamicBLAS` (min 1,000 triangles by default)

49-52% of scene draws are under 1,000 triangles (median 966 on 30632051, 947 on 41686139), so by default they go into the
merged dynamic BLAS the runtime rebuilds every frame.

| value | 30632051 fps | readback ms |
|---|---|---|
| 1000 (default) | 25.1 | 36.8 |
| 300 | 27.0 | 34.0 |
| 0 (own BLAS) | **29.3** | 31.1 |
| 3000 | 21.7 | 40.9 |

Picture unchanged: edge energy equal to the default's, mean absolute difference 1.1-1.3 grey levels, which is the
denoiser's noise between two runs of the same static frame.

### The upscaler preset is the biggest knob at the laptop's resolution

The laptop captures are 2880x1800. `t2-xessup-220084953` against `p6d-220084953`: XeSS Ultra Performance
(`rtx.xess.preset = 0`) **39.4 fps**, XeSS Performance (`1`) 28.2, same config otherwise. On the laptop this is the
DLSS profile (`rtx.qualityDLSS = 0` = UltraPerf, what `laptop-c-fast.conf` already sets).

### What does NOT help on the heavy capture

| run | change | fps |
|---|---|---|
| `p6e-30632051` | none | 29.3 |
| `cut-noalpha-30632051` | `rtx.enableAlphaTest = False` (cutouts drawn solid) | 29.2 |
| `cut-secull-30632051` | `rtx.enableCullingInSecondaryRays = True` | 29.6 |

So the 389 cutout draws are not paying for their any-hit test on RADV (which has no opacity micromap), and secondary-ray
culling is not where the time goes. 30632051 is simply a heavier view than the other two camps (31 ms against 16 ms per
path-traced frame, with the same code and nearly the same draw count), which fits overdraw of overlapping foliage cards
rather than any single switch.

### Per-key, on 30632051 (one key per run)

| run | change | fps | readback ms |
|---|---|---|---|
| `p4-base-30632051` | none (XeSS Performance, Auto -> Low preset) | 25.1 | 36.8 |
| `p3x-up-30632051` | `rtx.xess.preset = 0` | 31.8 | 28.3 |
| `p3l-nosec-30632051` | `rtx.enableSecondaryBounces = False` | 33.9 | 26.4 |
| `p3l-nosec-rtxdi-30632051` | + `rtx.useRTXDI = False` | 33.5 | 26.6 |
| `p3l-nosec-up-30632051` | both of the above and `xess.preset = 0` | **40.1** | 21.7 |
| `p3c-base-30632051` | `rtx.graphicsPreset = 4` (Custom, stock quality) | 18.1 | 52.0 |
| `p3c-novol` | + `rtx.volumetrics.enable = False` | 18.4 | 51.1 |
| `p3c-nortxdi` | + `rtx.useRTXDI = False` | 20.6 | 45.3 |
| `p3c-b1` | + `rtx.pathMaxBounces = 1` | 20.8 | 45.0 |
| `p3c-nosec` | + `rtx.enableSecondaryBounces = False` | 26.2 | 35.0 |
| `p3c-nosep` | + `rtx.denoiseDirectAndIndirectLightingSeparately = False` | 18.7 | 50.5 |

Two rules from that table. A quality preset other than Custom writes over `rtx.conf` in the Quality layer, so a key the
preset owns (`pathMaxBounces`, `denoiseDirectAndIndirectLightingSeparately`, ...) only holds with
`rtx.graphicsPreset = 4`; keys the preset does not own (`enableSecondaryBounces`, `useRTXDI`, `xess.preset`,
`volumetrics.enable`) hold under Low. And Custom is not a free switch: it starts from stock quality, 18.1 fps against
Low's 25.1, so it is only worth it to change a preset-owned key. Turning secondary bounces off is the largest single
win (+35%), and it darkens the camp interior visibly (the shaded area under the canopy loses its bounce light):
`shot-2499.png` of `p3l-nosec-up-30632051` against `p4-base-30632051`.

## A replay that moves (2026-11-13, item T2)

`run_replay.py <label> <capture> --frames 600 --env NIER_REMIX_LIVE_CAMERA_ORBIT=12:1.5` sweeps the camera: 12 degrees of
yaw per second, plus a 1.5 units/second dolly along forward, applied to the 14-float camera the proxy hands Remix
(`checks/camera_orbit.h`, gated by `checks/test_camera_orbit.py`). Set it to `0` for the still replay; `<deg>` alone gives
a pure sweep. It exists because a frozen capture cannot exercise motion vectors, ghosting behind a moving character,
upscaler stability or texture arrival while travelling - `t2-orbit` (600 frames of 41686139) moves 60+ grey levels between
frames 100 and 300 at 58.5 fps. Object motion inside a capture is still frozen; only a scripted game run (G5) shows that.

## Material scoreboard (2026-11-13)

`python3 replay/material_scoreboard.py <id>` reads `runtime/replay/n1-fake-<id>/fake-remix.log` (a `--mode fake` run
with that label) and prints, by share of triangles, what each mesh's material carries: roughness and metal textures,
32x32 placeholder masks, constants only, or no material at all. Numbers and the work that follows from them are in
`analysis/PLAN_2026-11-13.md` section 3.

## Findings so far (not yet fixed)

1. **Material constant overrides are ignored.** In the main lit shader family (e.g. `0c2a34…`), `cb1[0]` holds flags:
   `.x` = use the normal map (else flat), `.y` = albedo := `cb1[4].xyz`, `.z` = gloss := `cb1[5].x`,
   `.w` = metal := `cb1[5].y`. About 470 scene draws over the desktop captures have `.z/.w` set, and their bound mask
   is a 32x32 placeholder. The live path reads that placeholder as metal/roughness.
2. **The terrain/ground blend family has no traced roles** (`f85282…`, `f7a8a9…`). Slot 0 repeat is `cb1[5].xy`
   (captured values 1, 5, 10, 25, 45), layers 1/2 use `cb1[5].zw`/`cb1[6].xy`, and vertex colour sets the weights. In
   replay `base-30632051` the material line still logs `uv:0:cb1[5].xy=1,1`, but the captured cb1[5] is 25. So the
   repeat bake does not take effect, and this now reproduces offline. The cause is not pinned yet.
3. Remix facts (scout, from the 1.6.1 source): `albedoConstant` **replaces** the texture and does not multiply it, so
   a tint has to be baked. Opacity comes from albedo alpha. A quality preset other than Custom **overrides rtx.conf**
   (`rtx_option_constants.h:194`). `CopyRenderingOutput` is queued, not blocking.
