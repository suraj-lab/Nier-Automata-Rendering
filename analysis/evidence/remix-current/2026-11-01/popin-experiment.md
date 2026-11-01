# Pop-in experiment: scripted turns at three build budgets (2026-11-01)

DLL `807fd93f` (gates 72/72). Laptop `spaghetti`, standard live env, `PRESENCE_MIN=0` (one presence line per Remix
frame, with `| queue inst missing_inst first first_us budget_us game_frames phase`), `NIER_REMIX_LIVE_DRIVE` turning
the camera through the DirectInput mouse hook. Same save, same spot, hands off. Receipts (ignored):
`analysis/runtime/laptop-port/popin-{cal,b4000,b2000,b1000}-*.json`. Tables/plots: `analysis/checks/popin_data.py`.
Plot: `media/2026-11-01/popin-fit.png`.

Script after a 45 s load phase: still 15, turn +40 6 s, still 15, turn -40 6 s, still 15, turn +120 3 s, still 15,
turn -120 3 s, still 15, turn +10 12 s, still 15, turn -10 12 s, still 15. Turn rate measured, not assumed: 6-8 deg per
Remix frame for the first turn, 11-12 for the others.

## Findings

- NieR reads the camera mouse through `GetDeviceState` (`mouse_data=0`). It does **not** read the keyboard through
  DirectInput (`key_state=key_data=0`); it imports `GetAsyncKeyState`/`GetKeyState` and `XINPUT1_4`. Scripted walking
  did nothing; walking was left out of these runs.
- Holes come from **first-sight content**. The first turn needed 553-696 first-sight builds; turning over the same
  ground again needed 33-109. Revisits barely pop at any budget.
- One first-sight build costs **3.8-4.1 ms** of game-thread time (`first_us / first`), in all three runs. Service rate
  while holes exist: 55 / 60 / 109 builds/s at 1 / 2 / 4 ms.
- First turn, holes (instance-seconds) 1290 / 1029 / 821 at 1 / 2 / 4 ms; peak 590 / 433 / 342 instances missing.
- Fit over 17 turn events, exogenous inputs (`log N` new builds, `log B` budget): corr 0.06, cond(ZᵀZ) 1.14, so the
  design is close to identity. `holes ∝ N^1.11 · B^-0.20`, R² 0.80; 95% CI for the budget exponent [-0.73, 0.41].
  The budget is a weak lever; the count of new builds dominates.
- Queue form: `holes ≈ k·N²/(2r)`, `r = budget_per_game_frame × game_fps / c_build`, k ≈ 0.57. With c_build ≈ 4 ms,
  a 600-build turn cannot be cleared in under ~5 s of build time on one thread at any budget the game can afford.
- Still-camera floor in these runs: ~1 instance missing per frame (one object), far below live-churn's ~9.
- In backlog, first-sight time per game frame overshoots the budget (p90 16 / 26 / 39 ms): game-frame hitches.

## Limits

- One location, one save, three runs: budget effect on the first turn is monotonic, but its CI over all turns spans 0.
- `r` is endogenous (the backlog policy raises the budget when >10% is missing), so it is reported, not fitted on.
- The 4 ms build cost is measured as a total; which part (read, decode, upload) dominates is not split yet.

## Fix: decode planned once per draw (DLL f4091bc1), A/B against popin-b4000

`live_decode::build` resolved semantics with string compares and a per-vertex `std::vector<std::string>`, and
remapped indices through a `std::map`. Now the element→field plan is built once per draw and the remap is a flat
table (map fallback for sparse 32-bit ranges). Desktop, 2,941 real captured draws: 162 → 17 ns per vertex (10×);
output bit-identical to the old decoder on 8,832 cases (each draw as-is, with a truncated slot, with bone_count 1;
2,501 refusals with identical reasons). Gates 72/72; `test_live_vertex_decode.py` and `test_decode_failure.py` pass.

Prediction written before the run: first-turn holes 821 → ~100–270 instance·s.

| | popin-b4000 | popin-fast-b4000 |
|---|---|---|
| ms per first-sight build (laptop) | 3.80 | **0.55** |
| first turn: new builds N / turn rate | 696 / 6.1° per frame | 1262 / 12.0° per frame |
| first turn: holes / peak / drain | 821 / 342 / 2.6 s | **199 / 163 / 0.6 s** |
| service rate while holes exist | 109 builds/s | 334 builds/s |
| later turns: peak missing | 44–144 | 8–9 |
| frames with the budget deferring builds | 118 | 16 |
| still-camera missing per frame | 1.7 | 4.9 (see below) |

- The first turn covered twice the angle (same mouse counts, different turn rate) and needed 1.8× the builds, yet
  had 4× fewer holes. The burst form `k·N²/(2r)` overpredicts here: arrivals were spread over the turn
  (1262 / 6 s ≈ 210/s) and stayed under the service rate (334/s), so little queue formed. The general form is a
  fluid queue: holes accumulate only while the arrival rate λ(t) exceeds r.
- The still-camera floor rose from 1.7 to 4.9 missing instances, made of re-keyed objects arriving unbuilt
  (arrived_missing 0.8 → 1.7 per frame) while waiting for reads (read_pending 6.6 → 8.7). The decoder does not touch
  that path, and the camera ended up facing a different view (the first turn went twice as far), so this is a
  different scene, not a regression. It is the λ_churn·W_read term: the content key / stand-in work.
- The same mouse delta produced 6.1° and 12.0° per frame on the first turn in two runs; turn rate must be measured,
  never assumed from the script.

## Fix: stable geometry key (DLL dc40a0da), A/B against popin-fast-b4000

Churn breakdown from the per-frame log: 99% of re-keys were `vb2_ptr` alone (6,713 / 7,433 per run), all `place_same`.
The key now hashes only the POSITION stream's pointer (plus strides, offsets, IB, range, layout as before); the other
streams' pointers go into the version, so a moved stream rebuilds the mesh under the same key and the old mesh keeps
drawing meanwhile (`geometry_key.h`). Draws sharing a key in one frame with different secondary streams get stable
variant keys by order, so they never alias; identical repeats still share one mesh. Gates 73/73: `test_geometry_key.py`
and a Wine case (`MOCK_CHURN_SLOT2`: slot 2 moves to an identical copy every 10 frames) that fails with the old key
and passes with the new one. Also fixed: `MOCK_CHURN_EVERY` leaked into later runs of `test_live_visibility.py`.

| | popin-fast-b4000 | popin-key-b4000 |
|---|---|---|
| churn_pointer (whole run) | 3,693 | **73** |
| arrived_missing (whole run) | 1,522 | **0** |
| still camera: keys dropping per frame (pop events) | 10.1 | **2.25** |
| still camera: of which absent (game stopped drawing) | 5.6 | 2.0 |
| Remix fps (median) | 10.4 | **15.5** |
| worst game frame per window, p90 | 104 ms | **70 ms** |
| version rebuilds (`buffer`) / bytes read | 5,770 / 14.8 GB | 13,558 / 32.0 GB |
| first turn holes / peak | 199 / 163 | 224 / 216 (N 1,262 both) |
| later turns: peak | 8-9 | 9-13 |

- Prediction (churn ~0, arrived_missing ~0) met. The remaining still-camera drops are the game's own `absent` draws.
- Still-camera *missing* stays at 2-5 instances (2.6 keys), constant, already present before (2.5 keys in
  fast-b4000): objects that are never built, with ~5 draws a frame in `read_pending`. A steady hole, not pop-in;
  needs a per-key trace (`NIER_REMIX_LIVE_TRACE=1`) to name.
- Cost: moved secondary streams are now read and rebuilt (2.2× version rebuilds, 2.2× bytes read). Frame rate still
  rose, because the runtime no longer creates a new mesh per re-key. Reading only the moved stream, and skipping the
  rebuild when the decoded content is unchanged before the read, is the follow-up if reads become the limit.

## Still camera: never-built objects and one-frame skips (DLL 01324318), popin-gaps-b4000 → popin-hold2-b4000

Instruments (`4c2c4a18`): return gaps per dropped key (1, 2, 3, 4-8, 9-30 frames, gone) and a `stuck` line for any key
submitted without a mesh for 30 frames. popin-gaps-b4000 (still phases): 28% of departures were back on the next Remix
frame, 67% gone for more than 30. Four keys were stuck in `read_pending` all run, all sharing one vertex buffer
(vb1 `9c221e8af0`, stride 8) that the game rewrites every frame.

Cause: a read that lands after the game rewrote the buffer is a stale snapshot, and it was handed to the first draw
that polled it and dropped at the end of the frame, with a new copy issued. On the GPU every copy lands between frames,
so the same first draw won every time and the later draws sharing the buffer never got bytes. The mock hid it: its
read latency counted polls, which let the second draw win on alternate frames. Fixes: `NIER_REMIX_LIVE_READ_LATENCY`
counts frames since the copy; a landed snapshot serves every draw until a newer copy lands (bounded, dropped with the
buffer's shadow). Gate: `test_live_read_counters.py` async-shared, red without the fix (`remix: stuck ...
capture=read_pending`, the live signature).

Hold (`live_scene.h`, `NIER_REMIX_LIVE_HOLD=0` disables): an item last frame had and this frame lacks is drawn once
more with last frame's transforms; the stored copy only holds items the game drew, so nothing is held twice.
Reason: one Remix frame shows one game frame of ~5, so a one-game-frame skip stays on screen ~66 ms.

Also: the drive script now starts at the first frame with >= 100 instances (popin-hold-b4000 lost 9 of 14 phases to a
loading screen and is not used here).

| still camera | popin-gaps-b4000 | popin-hold2-b4000 |
|---|---|---|
| stuck keys | 4 | **0** |
| instances without a mesh, per frame | 4.45 | **0.03** |
| frames with any visible drop | 36% | **5%** |
| visible drops per frame (mean) | 2.73 | 1.85 (concentrated in those 5% of frames) |
| held per frame | – | 5.66 |
| buffer rebuilds/s | 60 | 380 |
| Remix fps / worst game frame p90 | 14.9 / 78 ms | 10.8 / 108 ms |

The cost row is the snapshot fix: objects on every-frame-rewritten buffers now rebuild every frame from snapshots
(before, they waited in `read_pending`). Fixed in `2b569a36`: each snapshot is hashed once when it lands (8-byte
steps), and a draw whose snapshot contents and resident buffer identities match its last build skips the decode
(mock: 142 → 4 rebuilds, 138 skipped). The view differed between runs (first turn 11.5° vs 8° per frame,
375 vs 250 instances), so fps is not a clean A/B.

### popin-skip-b4000 (DLL 2b569a36): still-camera gains hold; the rebuild cost needed a finer key

| still camera | popin-hold2-b4000 | popin-skip-b4000 |
|---|---|---|
| instances without a mesh, per frame | 0.03 | **0.00** |
| frames with any visible drop | 5.4% | 5.5% |
| stuck keys | 0 | 0 |
| later turns: holes (instance·s) | 4, 0, 0 | 5, 0, 0 |
| buffer rebuilds/s / skipped/s | 380 / – | 305 / 61 |

Whole-snapshot hashing skipped only 61 of ~365 rebuilds/s, yet `identical` shows ~5-7 rebuilds per frame decoding to
the mesh already on the GPU: NieR rewrites other objects' regions of a shared vertex buffer every frame, so the whole
buffer changes while each object's own vertices do not. `2b569a36` → `46ffadff`: the skip compares a hash of only the
bytes the draw reads (its index slice and the referenced vertex range of each slot, plus the pose); the landing hash is
gone. Gate: async-shared-other (an unindexed vertex changes every frame) 142 rebuilds with whole-buffer hashing,
4 with range hashing. Not yet measured live. Views differ between these runs (250-460 instances per frame), so
Remix fps is not compared here.
