# live-normal1: octahedral normals in, and what the recording actually shows

Run: `live-normal1`, DLL `0c75cb5f…` (build `0c75cb5f1d991c7a`), 200 s, laptop, save loaded by hand.
Original `d3d11.dll` restored and hash-verified (`6ba266d6…`) after exit; game alive at end, no crash, no Sentry data.
Recording: `NieR Automata 2026.10.31 - 22.08.15.09.mp4`, 2880x1800, 134.17 s, 8050 frames (~60 fps).
Log: receipt `live-normal1-20261031T220658Z.json` (the `log` field holds the text; it is ~50 MB, so analyse it in code).

Flags: `NORMAL=1` (convert), `GPU_SKIN=1`, `ASYNC_READS=1`, `BUILD_BUDGET_US=4000`, `TRACE=1`, `BUDGET=3072`, DLSS perf conf.

## 1. The normal conversion ran and did not fail

- No `normal texture format not converted` line: every slot-4 texture matched a supported format.
- `textures=320 untextured=0`; the game's mip chains still ship (conversion is per level).
- Not established: whether the converted normals look *right*. Stills cannot settle handedness, and the ground still looks
  flat and pale after conversion, so either the source encoding differs from the assumption or the ground's own material
  (terrain UV / albedo) is the remaining fault. Do not claim this fixed materials.

## 2. What the picture does

Frame measures (`scan.py`, `flat.py`, `white.py` over the game stream only):

| time | floor band mean RGB | what is visible |
|---|---|---|
| 12 s | (112,104,100) | interior corridor, walls/floor/columns all present and textured |
| 20 s | — | same, complete |
| 38–46 s | (191,190,189) neutral | open camp: everything present (tents, buildings, NPCs, flowers) but washed flat, floor detail collapses to ~2.7 mean \|dx\| |
| 128 s | (210,212,215) slightly blue | lower half empty pale, only a fence, a rock wall, a board and the character remain |

The blue-biased colour at 128 s is sky/fog where ground should be, i.e. **absent geometry**, not a bright surface. The
neutral grey at 38–46 s is a surface that is present but has lost its texture detail. Two different faults; previous runs
showed the same two.

## 3. Where the geometry goes — measured, not guessed

From the run's own counters and the trace:

- `built=4019`, `meshes=4019`, `evicted=0`, `dropped=0`, `mesh_bytes≈1.02 GiB` (budget 3072 MiB). Nothing was evicted.
- **8,536 of 34,879 submitted instances (24.5%) reference a mesh that does not exist** — 3,754 distinct geometries,
  94% of them non-skinned world geometry. Those instances are skipped by `live_scene::submit`, so the object is not drawn.
- `build_deferred=92977`: the 4 ms per-frame build budget defers ~34 first-sight builds per frame while only ~0.5 mesh per
  frame actually gets built (4019 builds / 200 s ≈ 20/s against ~43 capture frames/s).
- The backlog holds 20,000 uploads; beyond that `live_scene::update` hands entries back via `evicted_keys`, so capture
  re-uploads them and the same geometries keep failing to build. This is starvation, not eviction.

So the pop is ours and it is now located: **the game draws the object, the capture passes it, the mesh never gets built in
time, and submission skips it.** It is not the engine culling (the trace shows the draw present) and not memory pressure
(`evicted=0` at 1.02 GiB).

## 4. Performance, honestly

PT frame rate median **8.7 fps** (range 7.6–13.1), with `readback≈96 ms` of a ~115 ms frame; `other` is 0.1 ms, so the
time is the GPU finishing the path-traced frame, not our CPU work. The game itself is healthy: `game_max_ms=71`,
`worst_capture_ms=8`, `shown_backwards=0`, `camera_gap_max=0`.

"Performance no longer terrible" is consistent with the game thread being smooth; the PT image is still a slideshow, and
at ~115 ms per displayed frame every skipped instance is visible for a tenth of a second.

## 5. Next experiment (no rebuild needed)

`NIER_REMIX_LIVE_BUILD_BUDGET_US` is the lever. Suggested A/B, one variable:

1. `BUILD_BUDGET_US=0` (unlimited) — expect `mesh_missing` to collapse and the world to appear; watch `game_max_ms` for
   the single-huge-mesh stall that motivated the budget.
2. If the game stalls, `BUILD_BUDGET_US=20000` and compare `mesh_missing`, `game_max_ms` and `built`.

Both are environment changes only: no new DLL, no gate changes, no install beyond the one already hash-pinned.
