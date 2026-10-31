# Docked live run with mip chains and normal maps (2026-10-31 08:50)

Build `ded971fd` (NIER_REMIX_SIZE + slot-4 normal maps), run `live-nrm2`, laptop docked, RDP session on the
external ultrawide (primary 3440x1440), game presenting on the panel (2880x1800).

    --env NIER_REMIX_SIZE=2880x1800 --env NIER_REMIX_LIVE_NORMAL=1 --env NIER_REMIX_LIVE_TEX_PER_FRAME=16
    --rtx-conf analysis/deploy/rtx/laptop-b-dlss-perf.conf --live --no-ec-hooks

## Result

* `NIER_REMIX_SIZE` fixed the docked failure: the scene ran at 2880x1800 with no `paused` line at all, where
  the same setup before the flag paused 1/100 s after start. No crash; the game was alive at the end
  (receipt `live-nrm2-20261031T085049Z.json`, task_result 0) and the game folder is restored to `6ba266d6`.
* **Zero** "suboptimal replacement texture" warnings in the runtime log (16,609 bytes kept), where a one-level
  DDS produced them before: the mip-chain copy is doing what it was for.
* Textures applied visibly (user: "textures actually applied a lot"). Counters: 183 textures, `untextured=0`,
  587 draws, 725 instances, 1475 meshes, `scene=2880x1800`, `skipped_pass=690`.
* fps samples: 4.8 fps 6.9 fps 22.5 fps 13.9 fps 8.3 fps — still churn-bound, not fill-bound.
* Churn unchanged, as expected: `pose=12948` rebuilds (of 15012 built), `buffer=5580`, `texture=299`. The pose
  count is genuine blended-skin animation and is what Phase 4 removes.

## Remaining, in the user's words

"some skinning and pop issues": both are the per-pose rebuild path (`analysis/PHASE4_PLAN.md`). Nothing else was
reported wrong in this run.

Raw counters:

```
live rebuilds first=2021 unknown=5 buffer=5580 pose=12948 texture=299 evicted=0
live draws=587 instances=725 meshes=1475 built=15012 evicted=0 identical=3 blended=15 untextured=0 textures=183 hud=0 small_viewport=0 scene=2880x1800 skipped_pass=690 fallbacks=5 mesh_bytes
```
