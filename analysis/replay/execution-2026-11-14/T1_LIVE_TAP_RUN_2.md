# T1.3 live run 2 — `t1-tap-camp-2`, 2026-11-14 (user-approved)

- DLL 74ded3a63a9879f1b295f32bef80a1247646fec373876fdba5e1d0b401a24523 installed via install_live_dll.py
  (rollback `backups/live-scene-20261114T212251041070Z` holds fbc2269d…); left installed.
- Same command/recipe as run 1 (label t1-tap-camp-2). RX 6800 XT; save_ok=true, before == after; exit `timeout`,
  forced_pids [3968516, 3968560] (exact token, not a clean quit; no C2 Quit attempted).
- Tap: 12 records = 8 rejected-camera (camera moving at world entry) + **4 candidate pairs** (attempts 162/163/205/236,
  ~40-60 s after world entry, idle camp camera). Each: game/Remix camera parameters equal within 1e-4; Remix frame
  lags the tapped game frame by 3 camera sequences / 150-159 ms (still camera, so same view, NOT same instant).
  Both sides 3440x1440, full width (no pillarbox). Pair 236: game raw 8a308089…, Remix raw 7f18741a….

## Calibration of the tap against the original game's final image
The tapped R11G11B10 target holds values in [0, 0.992] (no HDR > 1, no non-finite) in every pair: it is already
display-encoded. Compared as stored with original-game final screenshots of the same save/recipe/resolution from
earlier runs (`t1-original-shortleft` shot-0, `t1-original-3440x1440` shot-2; earlier DLL, different session):
median |diff| 4.5/4.6 grey levels; on agreeing pixels per-channel linear fit gain 0.992-0.999, offset < 1 level.
Applying sRGB encode or decode makes it far worse (MAD 67 / 60 vs 5.9-6.1). Disagreement is concentrated in the top
(sky/foliage) and bottom (ground) bands - time/wind/animation between sessions, not a global curve.
**Conclusion: no tone mapping or gamma remains downstream of the tap; the only later stages are the final copy and
HUD sprites. The tap is the game's final image minus HUD**, with the stated timing limit (Remix side 3 camera
sequences older). Numbers: `runtime/game-runs/t1-tap-camp-2/t1.3-comparison.json`.
Labelled sheet for the user (no artistic judgment made): `t1-tap-camp-2-sheet.jpg` (original final / tap / Remix).
The lead could not view images in this session (context-mode read cap); judgment is numerical only.

## Status
Camp: calibrated same-camera pair with recipe (T1_D1 recipe + `NIER_REMIX_LIVE_TRUTH_PAIR_DIR`). T1 acceptance
still needs desert and pond pairs (US1/laptop or a hands-on route) and the character mask before W2.
