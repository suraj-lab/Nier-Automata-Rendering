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

## live-why (a0539040), 2026-11-01 01:46, restored and verified

661 presence events, 22,828 dropped keys; attribution ledger closed in all 661 (`known == dropped`, no capture
overflow, no `present=0`). Buckets: absent 78%, churn_pointer 20% (4,672 keys), churn_shape 1%, churn_occurrence
0.3%, capture_pass 0.2%, submit_other 0. Capture- and renderer-side losses are ruled out. One dropout in five is
the same draw (same IB and index range) under a new geometry key, which Remix must build as a new mesh.
Only 7 events had a fully still camera (180 in live-motion); the longest stretch without a dropout event was 1.8 s
and the median per-event camera motion was 0.51 units / 0.65 deg, so this run does not test the still-camera blink.
Open: which key component changes under churn (VB pointer, VB offset, base vertex, layout), and whether the new
key arrives `mesh_missing` (the presence set counts mesh_missing as present, hiding that frame).

## Churn breakdown (b0d37c38)

`presence_why` adds `moved_vb moved_offset moved_base moved_layout moved_other` for each churn_pointer re-key (which
geometry-key component changed: slot-0 VB pointer, its offset, base vertex, input layout; `other` = none of these)
and `arrived_missing` (churned arrivals submitted before their mesh was built: the frame the object is really gone).
Gates: `test_dropout_watch.py` (all buckets), `test_live_visibility.py` churn case (`MOCK_CHURN_EVERY=10`: swap to an
identical VB copy, must read churn_pointer with moved_vb only; shown red with the VB component blanked). The mock
builds before submit, so `arrived_missing` is only unit-tested. Full suite 70/70, 227 s wall.

## live-churn (9b81c477, PRESENCE_MIN=1), 2026-11-01 02:13, restored and verified

1,414 presence events, ledger closed in all, no overflow. Three still-camera stretches (21 s, 18 s, 37 s);
1,045 events with camera motion < 0.01 units and < 0.1 deg.
- All events: absent 67%, churn_pointer 32% (4,726), churn_shape 1%, churn_occurrence 0.2%, submit_other 0.
- Still camera: absent 61%, churn_pointer 38% (3,437).
- churn_pointer place: same (< 1 cm) 100%, near 0, far 0: the same object in the same place, not a neighbour
  sharing an index buffer.
- Key component moved: VB pointer 0, VB offset 0, base vertex 0, layout 114, other 4,612 (98%). The moving
  component is outside slot-0 VB/offset/base/layout: VB slots 1-3, a stride, or the IB offset/format (unlogged).
- arrived_missing: 2,597 of 4,924 churned arrivals (52.7%); 1,831 with the camera still. Those frames submit the
  object without a built mesh, so it is absent from the Remix image: a measured cause of still-camera blinking.
Open: which remaining key component moves; what the still-camera `absent` 61% is (game not drawing, rejected before
the key is computed, or re-keyed with another range).

## live-churn funnel windows: two different faults

Instance-level per ~3 s window: steady state 0.5-2.3% of instances reach the renderer without a mesh; at 31.8 s
(instances 9,270 -> 31,925, new area streaming) it is 50.5%, at 35.1 s 22.7%, at 62.8 s 8.4%, then back to ~1.2%.
The same early window defers 2,915 builds on the 4 ms budget. Standing-still `absent` (61% of still-camera dropouts)
is not a two-way key swap (absent == appeared in 151 of 951 events) and cannot be a pre-key rejection (such a draw is
filtered identically every frame), so it is the game not issuing those draws: engine cull / FAR LOD, not capture.

## Prior art that validates the design (web research, 2026-11-01)

- Remix's default asset identity is `positions,indices,geometrydescriptor`
  (`rtx.geometryAssetHashRuleString`, RtxOptions.md): no layout, no strides, no pointers. Our key includes four
  pointers, four strides, four offsets, IB pointer/offset/format, layout and base vertex, i.e. everything volatile.
- Remix's own `HashComponents` has no buffer pointers, and `getVertexRegion()` reads through the bind offset, so ring
  slots hash equal (`d3d9_rtx_geometry.cpp`); it hashes only the vertices the indices touch.
- `DrawCallCache` pairs a draw with its previous frame by exact geometry hash, then by *fuzzy world position*
  (`rtx_draw_call_cache.cpp`): the same rule as our `place_same` stand-in.
- Remix states it keeps `boneHash` stable across frames rather than recomputing it, for exactly this reason.
- FAR (the known NieR:Automata fix mod) identifies its target buffer by `D3D11_BUFFER_DESC` fields and keeps a
  `std::map<ID3D11Buffer*, ...>`: desc signatures plus per-pointer state, not a global geometry key.

Consequence: the durable fix is a content key over the ranges the indices touch (positions and indices), with the
volatile pointer/stride/offset components out of the key, hashed off the draw thread. Until then, the stand-in keeps
the hole closed.

## Build budget policy and persistent stand-ins (ad516f32..58e88c0a)

- `backlog_policy.h`: when unbuilt instances exceed 10% of the submitted frame the build budget rises to 20 ms (5x,
  capped), converting a stream-in spike from 50% missing geometry into slower frames. Gated
  (`test_backlog_policy.py`: normal, spike, boundaries, disabled, ceiling).
- Stand-in pairs now persist until the new key's own mesh exists (`live_scene::merge_carry`), so a pair recognised on
  one frame still covers a build that lands several frames later. Gated in `test_live_scene.py`, shown red by
  dropping every old pair.
26 affected gates pass (build 58e88c0a).
