# Phase 4 live: `live-gpu-skin2` (2026-10-31 13:20, laptop, build `33fe971c`)

Same command as `live-nrm2` plus `NIER_REMIX_LIVE_GPU_SKIN=1`. Ran the full 150 s (`alive_at_end=True`), no crash.
Laptop restored to `6ba266d6`. Logs: `analysis/runtime/laptop-port/live-gpu-skin2-*`.

| | `live-nrm2` (CPU bake) | `live-gpu-skin2` |
|---|---|---|
| pose rebuilds | 12 -> 12948 | **0 -> 0** |
| meshes built | 15012 | 4210 |
| `other` ms/frame, mean (max) | 72.7 (157.5) | **5.3 (28.1)** |
| readback ms/frame | 34.8 | 42.6 |
| convert ms/frame | 8.6 | 8.1 |
| fps, mean of windows (min) | 10.1 (4.8), 9 windows | **17.8 (12.0)**, 29 windows |

Now readback-bound: the frame is waiting for the path tracer, not for us.

Open, not yet explained:
- `buffer` rebuilds 569 -> 15280 at a steady ~190/s even while `first` is flat (13:22:39 on). Likely skinned draws
  whose dynamic VB is Map(DISCARD)ed every frame: before Phase 4 the pose check ran first and counted them as `pose`.
  Cheap in CPU (`other` 5 ms) but it costs uploads and memory.
- `evicted` 0 -> 1064 (rebuild line) / 2342 (draws line), `mesh_bytes` 537 MB at the end: the eviction budget is now hit,
  probably the 3x skinned vertex memory plus the buffer churn. Evicted meshes are rebuilt when drawn: possible popping.
- Four "first frame ready" lines within 50 ms on one worker thread: duplicate logging, not restarts.

## What the user saw (on the panel)

"The game world is a lot more stable"; "15ish fps" and it felt more stable. But: **the camera gets stuck when moving
it around**, **character animations were getting stuck**, textures still flicker a little, not all textures present,
normal-map orientation not judged.

## Two causes found from source and log, not yet confirmed live

1. **Shared skinned mesh**: Phase 4 gave all occurrences of a draw one mesh, but remix-1.6.1 skins into the mesh's
   BLAS entry (`rtx_scene_manager.cpp:400-428`: `modifiedGeometryData`, `lastBoneHash` on the BlasEntry), not per
   instance. Identical characters showed one pose and re-skinned each other. Fixed in `d90bef5` (build `b2bab23d`):
   occurrence back in the key, pose still out; the fake runtime now flags it.
2. **Game-thread GPU readbacks at ~40% of wall time** (13% in `live-nrm2`), ~130 MB/s, tracking the `buffer`
   rebuilds (~190/s). These stall the game itself, which fits the camera freezing in steps. Not fixed: `b2bab23d`
   adds `buffer_skinned`, `buffer_dynamic`, `game_frames`, `game_max_ms` to the rebuild line so the next run shows
   which draws cause it and how long the game's worst frames are.

## Run 3: `live-gpu-skin3` (build `b2bab23d`, per-occurrence skinned meshes + stall diagnostics)

User: "models looked better ish, the camera issue is egregious and should take priority".
Log: game thread runs at only ~20-27 fps with worst frames of 130-460 ms every window (one of 1391 ms). In steady
state ~240 reads per 4 s window, nearly all **first-sight reads of IMMUTABLE buffers**, ~5 ms each and almost no
bytes (14:11:55: 237 reads, 0 MB, 1169 ms): the cost is the GPU sync per Map, not bandwidth. ~28% of game-thread
time. `buffer` rebuilds are all dynamic buffers (buffer_dynamic == buffer), ~15% skinned; not the main read source.
`created` (immutables captured at creation) stays low, so these buffers reach the game through a path our
CreateBuffer hook does not see; not investigated yet.
Fix: `98c022d` (build `c34dd8fb`), `NIER_REMIX_LIVE_ASYNC_READS=1`: no read blocks the game thread any more.
