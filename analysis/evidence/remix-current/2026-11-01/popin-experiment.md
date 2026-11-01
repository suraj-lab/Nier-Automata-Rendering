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
