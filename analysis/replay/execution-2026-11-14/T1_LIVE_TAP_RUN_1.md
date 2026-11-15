# T1.3 live run 1 — `t1-tap-camp-1`, 2026-11-14 (user-approved single desktop run)

- DLL: installed candidate fbc2269d36b51506d6868fe07b48a5c3b8c09d5d9fce38211e4af9bb2a83e770 via
  `checks/install_live_dll.py --install --expect …` (user-approved); previous 9555829d… in rollback
  `backups/live-scene-20261114T210457921230Z`. Left installed per user choice.
- Command: `game_run.py t1-tap-camp-1 --live --isolated-prefix --size 3440x1440 --limit 200 --shots 100,140,180
  --env NIER_REMIX_SIZE=3440x1440 --env NIER_REMIX_LIVE_TRUTH_PAIR_DIR=<run>\shots --menu-drive <T1 shortleft recipe>`.
- GPU: gamescope selected 'AMD Radeon RX 6800 XT (RADV NAVI21)'; DXVK found RX 6800 XT. LM Studio model resident on
  that GPU (not task-owned, idle); no timing claims.
- Save: `save_ok=true`, before == after. Exit `timeout` with forced_pids [3906518, 3906566] (exact token) - NOT a clean
  quit; no C2 Quit observation was attempted (game_run has no exit monitor; pause-menu quit automation unproven).
- Shots 0-2: 3440x1440 full width (no pillarbox this run).

## Tap result
The tap worked in the real game: 4 records written ~1.7 s after the world appeared, all `rejected-camera`
(correctly): the camera was still turning at world entry; Remix lagged the game by 2-3 camera sequences
(max parameter deltas 4.9 / 0.13 / 0.13 / 0.09; Remix completion 23-300 ms before capture). No raw pair was written.
**No calibrated or even candidate pair; T1.3 not achieved.**

## Consequent fix (plan T1.4 "bounded frequency, reject moving pairs")
v1 counted rejections in the 4-attempt budget, so all attempts were spent while the camera moved. v2: <=4 candidate
pairs (GPU copies) and <=8 rejection records per session; once 8 rejections are recorded, moving frames are skipped
silently until the camera is still. Gates revised and disclosed (originals archived as `*-v1-original.py`):
frozen `test_truth_pair_tap.py` 30bc7240… (bound), hidden 4a929e52… (+`MOCK_CAMERA_DRIFT_UNTIL`: drift then still
must still yield a candidate) red on v1 for exactly that reason, green on v2. Mutations red (appended to
`runtime/t1-tap-mutations.json`). Suite s80 124/124. New candidate DLL 74ded3a6… (not installed).
A second live run needs user approval.
