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
