# live-budgetfix: the accounting fix did not fix the popping

Run: `live-budgetfix`, DLL `e0233798…` (first-sight decode charged to its own per-frame allowance), 150 s, laptop.
Original `d3d11.dll` restored and hash-verified (`6ba266d6…`); game alive at end, no crash.

Baseline is `live-normal1` (same flags, 200 s). Rates are comparable; totals are not, because the runs differ in length.

| metric | live-normal1 | live-budgetfix |
|---|---|---|
| submitted instances without a mesh | **24.47 %** | **24.86 %** |
| mesh_missing events | 8,536 | 4,924 |
| submit events | 34,879 | 19,808 |
| distinct geometries missing | 3,754 | 2,954 |
| built meshes | 4,019 | 2,495 |
| build_deferred | 92,977 | 63,370 |
| buffer rebuilds (dynamic) | 5,306 (5,266) | 2,909 (2,909) |
| evicted | 0 | 0 |
| PT fps median | 8.7 | 9.0 |
| readback median | 96.6 ms | 92.5 ms |
| worst game frame | 1,374 ms | **19,928 ms** |

## What this means

The hypothesis is **falsified**: charging first-sight decode to its own allowance changed the missing rate by +0.4 points,
which is noise, not a fix. Decode is not the limiter — real decode is 114 µs median, and 4 ms of allowance is worth ~35
meshes per frame even today.

So the rate limiter is elsewhere in `live_capture::observe`. The remaining candidate is the second gate on the same line:

```cpp
const bool deferred = over_build_budget ||
                      (!changed && needs_read && read_bytes_this_frame >= read_budget_per_frame);
```

plus async reads that never land for a buffer the game keeps rewriting (`read_pending`, invalidation, re-issue). The run's
read counters support that reading: `pending=54171`, `waits=39354` across `reads=6099` in the previous run.

## The missing instrument

The trace cannot currently say *why* a draw produced no upload: a deferred draw still reaches the end of `observe` and is
labelled `accepted`. Until the capture side emits a distinct reason for each exit — `budget`, `read_budget`, `read_pending`,
`unchanged`, `dropped` — the popping cannot be attributed. That is a ~10-line change in `live_capture.h` and one more run,
and it is the next step. Guessing again first is what produced this falsified hypothesis.

## Also measured

A single 20-second game stall (`game_max_ms=19,928`) whose `worst_capture_ms` was only 21 ms, i.e. not in our capture hook:
the block is downstream of it. Two smaller stalls (465 ms, 1,449 ms) in the same run. Not diagnosed; recorded so it is not
mistaken for a load-time hitch later.

## Status of the change

The accounting split (`first_sight_us_this_frame`) stays: charging mandatory rebuild work to a discretionary allowance was
wrong on its own terms, and it is neutral in outcome. It is not the fix, and is not presented as one.
