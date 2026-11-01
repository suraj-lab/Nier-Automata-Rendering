# Live runs 2026-10-31/11-01: from capture ledger to presence attribution

Laptop `spaghetti`, Remix 1.6.1 ARM64EC, 2880x1800 panel, standard live env (async reads, GPU skin, normal on,
build budget 4000 us, texture budget 3072). All runs: preflight `GAME_NOT_RUNNING` + original `d3d11.dll`
`6ba266d6...`, install, 150 s, restore verified. Every run alive at end, no crash. Receipts (ignored):
`analysis/runtime/laptop-port/<label>-*.json`, key `log` holds the log text.

| run | DLL | question | answer |
|---|---|---|---|
| live-funnel | ac729807 | where do draws go (closed ledger, every draw one bucket) | 24.5% mesh_missing was mostly fill; steady 2.9-6% |
| live-retry | c80d8e63 | permanent decode ban vs bounded retry | steady missing 1.3%; rest `no_position` |
| live-layout | 4969350f | which layout has no position | 3983/3985 `COLOR:2,POSITION:2,TEXCOORD:2` (float4) |
| live-float4 | 422a3e15 | float4/half4 reader | no_position 0, decode_failed 0, steady missing 0.6-0.7%. User: no visible change |
| live-coverage | 270f2d9a | is submitted geometry on screen for Remix's camera | offscreen 0 in all windows; in-frustum 60-77% |
| live-presence | 5a8e73c1 | presence watch | 0 lines: block sat behind the TRACE early return (wasted run) |
| live-presence2 | 4d563ab2 | presence watch, fixed | 671 lines, but capture histogram all zero: also behind TRACE (`trace(tracing)`) |
| live-motion | 855afb8b | camera motion + screen fraction per dropout | see below |

Both wasted runs had an instrument that only fired with `NIER_REMIX_LIVE_TRACE=1`. `test_live_visibility.py`
now fails unless presence, capture counters, camera motion, screen fraction and attribution all fire with the trace
off, and each new assertion was shown red by breaking the plumbing it guards.

## Correction to the live-normal1 "5-frame blink"

The worker samples every ~5 game frames (capture-seq step between snapshots: 1 x1724, 5 x629, 2 x406, 6 x233).
Measured in worker snapshots, static-camera gaps are 1 snapshot (350), 2 (19), 3 (1): a one-Remix-frame blink, not
a 5-frame one.

## live-motion (855afb8b), 605 presence events, camera valid in all

- 487 drop events (>=8 keys): 307 with camera moving, 180 with camera completely still.
- Still-camera: 3 whole-scene `present=0` events (01:15:54, 0.8 s). Held frames (`no_new_render`, `not_ready`)
  stepped the watch with an empty set and keep the previous image: most likely an instrument artefact; fixed in
  a0539040 (held frames are skipped).
- 81 still-camera drops covered >10% of the screen (`dropped_frac`, AABB-based, over-estimates).
- 100 clean still-camera blinks: N keys leave and exactly N return on the next presence event (43->43, 20->20,
  12->12, 15->15, 32->32 ...).
- Capture counters at the drop frame minus the return frame: no counter moves by the dropped count (pass 2/100,
  prepass 1/100, small 3/100, unchanged 3/100, deferred_budget 0/100). Budget, deferral, async reads, pass filter
  and decode failures do not explain the blinks.
- 117 of 177 still drops had >= half the dropped count replaced by new keys in the same frame: key churn candidate.
  The geometry key hashes VB/IB pointers, offsets, start index, base vertex and layout pointer, and skinned meshes
  add a draw-order occurrence number (`live_capture.h`), so the same object can return under a new key.

## Next instrument (a0539040)

`remix: presence_why` puts every dropped key in one bucket: `submit_other` (renderer refused), `capture_<reason>`
(game drew it, we classified it), `churn_occurrence` (same source key, new occurrence key), `churn_pointer` (new
key, same IB and range), `churn_shape` (same range, new IB), `absent` (nothing this frame refers to it). Plumbing
proof fields `known` and `capture_events`. Unit gate `test_dropout_watch.py`; Wine gate `test_live_visibility.py`.
Only `absent` has been exercised by a real (mock) draw; churn and capture buckets are unit-tested only.

Full suite at a0539040: 70/70, 229 s wall with `gates.py --all --run --jobs 8` (receipt
`analysis/runtime/gates/last.json`, source unchanged).
