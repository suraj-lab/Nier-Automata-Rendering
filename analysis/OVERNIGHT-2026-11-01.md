# Overnight 2026-11-01: what the popping actually is, and what to do next

Written after three live runs (`live-presence2`, `live-motion`, `live-why`, `live-churn`), all restored. Builds:
`9b81c477` was the last live build; `ad516f32` adds the stand-in fix and has passed its gates but has **not** been
run on the laptop. Nothing is pushing secrets or leaving the laptop modified.

## 1. The measurement that matters

From `live-churn` funnel windows (`remix: funnel`, one line per ~3 s), instance-level:

| window | instances | drawn | mesh_missing | missing |
|---|---|---|---|---|
| 0.0 s | 1,254 | 49 | 1,205 | 96.1% (fill) |
| 6.4–28.6 s | ~9,250 | ~9,120 | 118–212 | 1.3–2.3% |
| **31.8 s** | **31,925** | 15,796 | **16,129** | **50.5%** (new area streaming) |
| **35.1 s** | **47,342** | 36,594 | **10,748** | **22.7%** |
| 39.5–53.1 s | ~48,000 | ~47,700 | 240–344 | 0.5–0.7% |
| 62.8 s | 46,453 | 42,530 | 3,923 | 8.4% (second stream-in) |
| 66.9–100 s | ~46,500 | ~46,000 | 535–583 | 1.1–1.2% |

Two different faults, now separated by number:

**A. Travel / new-area popping.** When the game streams a new area, the instance count triples and half of the
instances reach the renderer before their mesh exists. Not a bug in the identity logic: it is a build backlog
(2,915 builds deferred by the 4 ms budget in the same early window). Every one of those is a hole in the image.

**B. Standing-still popping.** 1,045 still-camera events in `live-churn`. Attributions: churn 38% (3,437 keys, all
`place_same`, 1,831 arriving before their mesh was built) and `absent` 61%. For the `absent` bucket:

- 951 still events, where `absent == appeared ±1` in only **151**; mean absent 5.7, appeared 8.4. So it is not a
  two-way key swap.
- A draw rejected before its key is computed (small, topology, layout) cannot explain it either: such a draw is
  filtered the same way every frame, so it was never in the presence set.
- Every post-key outcome (pass, prepass, deferred budget, read pending, decode failed) carries a key and is counted
  in a `capture_*` bucket, which is ~0%.
- Therefore `absent` means the **game stopped issuing those draws for a frame while the camera was still**. That is
  the engine's own visibility logic (manual cull `0x7F40F0` and FAR LOD, both verified by REA), not our capture and
  not the runtime.

## 2. What was fixed tonight (gated, not yet live)

| build | change | gates |
|---|---|---|
| `a0539040` | presence attribution closed ledger; held frames no longer look like whole-scene drops; presence/capture/camera/frac fire with TRACE off | unit + Wine, shown red by breaking the plumbing |
| `b0d37c38` | churn breakdown: which key component moved, and `arrived_missing` | unit + Wine (`MOCK_CHURN_EVERY`) |
| `9b81c477` | `place_same/near/far` (same object vs a neighbour sharing a buffer); gates retry a Wine device flake once | unit + Wine |
| `f6368383` | `key_moved` mask + `key_names` over all 17 key inputs | unit + Wine (vb0_ptr) |
| `58e88c0a` | backlog-aware build budget (`backlog_policy.h`: >10% unbuilt raises 4 ms to 20 ms, capped) and stand-in pairs that persist until the key's own mesh exists | `test_backlog_policy.py`, `test_live_scene.py` (merge kept/dropped, shown red) |
| `ad516f32` | **stand-in mesh**: a re-keyed object whose mesh is unbuilt is drawn with its predecessor's mesh for that frame; `ready()` accepts stand-in-only frames; `carried=` in the log | unit (carry, planning) + live_scene case, shown red by disabling it |

Also fixed tonight: a merged comment that made the occurrence match never consume its arrival, so `churn_occurrence`
was double-counted as `churn_pointer` in `live-churn` (31 keys, negligible for the totals, but it is why the masks
looked odd there).

Gate loop is now ~4 minutes for the whole suite (`gates.py --all --run --jobs 8`, 70/70 in 229 s, receipt
`analysis/runtime/gates/last.json`), 1–3 minutes for the affected subset, seconds for pure logic.

## 2b. Prior art found overnight (web research)

- Remix's default asset identity is `positions,indices,geometrydescriptor`; **no layout, no stride, no pointer**.
  Its `HashComponents` has no pointers, `getVertexRegion()` reads through the bind offset (ring slots hash equal),
  and it hashes only the vertices the indices touch.
- Remix's `DrawCallCache` pairs a draw with its previous frame by exact hash then by *fuzzy world position* — the
  same rule as our `place_same` stand-in. It also keeps `boneHash` stable across frames on purpose.
- FAR, the known NieR fix mod, keys its state by `D3D11_BUFFER_DESC` fields plus a `std::map<ID3D11Buffer*, ...>`:
  desc signature and per-pointer state, not one global geometry key.
- No public documentation of NieR's buffer strategy exists; a per-frame scratch ring for index/UV/tangent streams is
  inference, not sourced.

**Consequence:** our key hashes 17 volatile inputs. The durable fix is a content key over the index-touched ranges
(positions + indices), computed off the draw thread, with pointers, strides and offsets out of the key. The stand-in
is the cheap bridge until then — and the `key_names` field tells us which component to drop first.

## 3. Next instrument, in the order I would run them

1. **`live-keys`** (build `ad516f32` or later): confirms the stand-in works (`carried=` > 0, and mesh_missing share
   falls at stream-in spikes) and names the churning key component (`key_names`). One 150 s run, standing still
   twice. Expected: `carried` ≈ most of the 1,831; `key_names` non-empty on the still-camera events.
2. **Build-backlog policy.** During a stream-in spike, `deferred_budget` explodes while the frame shows holes. A
   policy that raises the build budget when `mesh_missing / instances` is above a threshold (say 10%) converts
   holes into one slower frame. Cheap, gate-able as a pure function of the counters.
3. **Engine-side attribution for `absent`.** Two options, both REA-first:
   - count entries into the manual-cull function (`0x7F40F0`) and its two callers per frame, then correlate with
     still-camera `absent` (vtable hooks only: the proxy has no inline detour, so this needs a call-site hook or a
     data watch on `DAT_1412500d0`);
   - or log, per frame, how many LOD transitions the FAR setup applies (fields verified in
     `analysis/runtime/prior-art-deep-20261031/far-lod-setup.json`).
4. **Content key** (validated by the prior art above): hash positions over the index-touched vertices and the index
   bytes, per `(buffer, offset, bytes)`, invalidating on `Map(DISCARD/WRITE)`; keep
   `{layout, slot-0 stride, index count, start index, content hashes}` and drop every pointer, offset and stride.
   Remix does exactly this and never keys on resources. Worth it even after the stand-in: it also stops the wasted
   reads and builds that churn causes.

## 3b. Final state of the tree tonight

- Build `2a53894a`, full suite **71/71 in 229.7 s** (`gates.py --all --run --jobs 8`), source unchanged.
- Last commit: skinned draws are never carried (this frame's palette on the predecessor's bind pose would be a wrong
  pose, not a missing one); shown red by removing the guard.
- Nothing installed on the laptop, nothing pushed; `main` is 14 commits ahead of `origin`.

## 4. Additional points of investigation (not yet scheduled)

- **Skinned meshes and the stand-in.** A skinned object's transform is bones, not the instance matrix. Carrying a
  skinned predecessor's mesh would show the previous pose; `place_same` uses the instance translation, which for
  skinned draws may be meaningless. Carrier should probably be disabled for `item.bone_count > 0` until measured.
- **`dropped_frac` is an AABB fraction.** It overstates visible area (a diagonal wall reads 1.000). A screen-space
  coverage estimate from the projected vertices on a coarse grid would be honest and cheap.
- **Mesh-count drop 1,818 → 1,040** from `live-float4` is still unexplained and may be the same identity churn seen
  from the other side.
- **Evictions vs stand-ins.** `carried=` draws use meshes the LRU may evict at any moment; the eviction order should
  prefer keys that are not stand-in sources this frame.
- **Pass filter and `prepass`.** `pass` is still the largest capture bucket (14k–40k draws per window). The 30-frame
  hysteresis has never been checked against real pass sequences; a run with `NIER_REMIX_LIVE_TRACE=1` plus the
  per-frame capture histogram would settle whether scene-target flips cause any visible loss.
- **Async read staleness.** Reads accept older snapshots; the stand-in depends on `previous_ident` being from the
  previous *submitted* frame. If reads lag, a re-key pair can be computed against a frame that is 1–2 behind.
- **`arrived_missing` before/after.** `live-churn` measured 52.7% of churned arrivals unbuilt *before* the build
  budget policy change; the same number after `ad516f32` is the acceptance test for the stand-in.
- **Texture/lighting backlog** (the original next phase): normal Y handedness unverified, slot 2
  roughness/metal unresolved, terrain UV unknown, `lights=0` in some scenes.
- **Performance**: PT ~9 fps with ~92–97 ms readback; frame generation needs the presentation redesign (a second
  window presenter, per the FO4 reconstruction).

## 5. Honest limits of tonight's conclusions

- The 32% churn share and the 61% `absent` share are shares of *dropout keys*, not of screen area.
- Nothing tonight proves the stand-in improves the visible picture; it proves it removes holes that were measured.
- `place_same` compares instance translations only; a rotation-only change would look identical.
- The stream-in spikes (50.5%, 22.7%) correlate with new content arriving; they are not proof that every hole in
  that window is a missing mesh versus the game's own first-draw behaviour.
