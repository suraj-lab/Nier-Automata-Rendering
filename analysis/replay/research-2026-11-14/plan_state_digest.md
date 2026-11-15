# State digest: what `PLAN_2026-11-13.md` says, what is still true, what the 2026-11-14 plan must carry

Author: research agent `state_digest`, 2026-11-14. Read-only. The only file written is this one.

Abbreviations used below:

| Short | File |
|---|---|
| P13 | `analysis/PLAN_2026-11-13.md` (2137 lines). `P13:N` = line N |
| P14 | `analysis/PLAN_2026-11-14.md` (49 lines) |
| RM | `analysis/replay/README.md` |
| LIVE_CAP | `analysis/checks/live_capture.h` |
| REMIX_LIVE | `analysis/checks/remix_live.cpp` |
| LIVE_SCENE | `analysis/checks/live_scene.h` |

Coverage: I read all of P13 (every line from 1 to 2137), P14 (all), and RM (all). I checked the switch
defaults, the Remix API cites, and the laptop log numbers against the source and files. Nothing was built, run or
installed. Commands used were `grep`, `sed`, `sha256sum`, `du`, `git status` and `git log`.

Status words used in the tables:

- **DONE**: the item's done-when is met in the evidence cited.
- **DONE, default ON / OFF**: the code works and the switch default is shown.
- **OPEN**: work or a decision is still needed.
- **BLOCKED (on X)**: needs X, which this plan cannot make.
- **UNVERIFIED**: I could not check it. The reason is given.

---

## 1. Every item id in P13

### 1a. Track L (look). Table at P13:186-194

| Id | One-line description | Final Status text in P13 (short) | Evidence labels and numbers (run labels, file:line) | Now | Blocked on / next |
|---|---|---|---|---|---|
| L1 | Exposure and tone map for the UNORM picture | "final pass done 2026-11-14, in the game" (P13:186) | Camp pick "3 or 4" = variant 4 (global tonemap, `saturation 1.3`), P13:~258-270 (`l1-*`, `l1b-*`). Guard runs `l1c-30632051` 28.9, `l1c-41686139` 42.8, `l1c-23275488` 49.4 fps (`summary.json` `steady_fps_median`). Fast profile rejected: `l1f-23275488` median luma 0.000, 76.8% crushed (P13:L1 step 5-6 result, ~P13:277-298). In game: truth `game-truth` median 0.306 / p95 0.554 / sat 0.184 / R:B 1.214; ours `game-final` 0.316 / 0.530 / 0.180 / 1.217; 55.5 fps (P13:761-797). Conf: `deploy/rtx/game.conf:30-44` | DONE (camp, in game) | Open: one truth pair on the laptop (grade was fitted under XeSS, no Ray Reconstruction, P13:2100-2120). Re-judging the fast profile after the final grade is not recorded. |
| L2 | Normal maps on by default | "done 2026-11-13 (default on, DLL `141629a8`, suite 86/86)" (P13:187) | Orientation from shader decode: no flip (P13:L2 result, ~P13:330-357). `l2-default-30632051` 28.6 fps vs guard 29.0 (-1.4%). Textures 452 -> 600. Default flip in `REMIX_LIVE:252` (`!= L"0"`). User: "can't tell the difference apart from very minor shadows" (2026-11-13). | DONE, default ON | Residual: left-handed UV layouts cannot be fixed by the Y flip (P13:L2 result). |
| L3 | Constant overrides from `cb1[0]` flags (was T1) | "steps 1-7 done 2026-11-13 behind `NIER_REMIX_LIVE_FLAG_CONSTANTS=1`... default flip is the user's pick" (P13:188) | Gate `test_live_flag_constants.py`, suite 89/89 (`suite-s40`). Placeholder row 8.8% / 14.7% -> 0 (P13:L3 steps 3-7, ~P13:422-465). Replay fps 29.7 / 29.4 and 44.1 / 44.1 (`l3r-*`). Picture moves little: 2.1% of camp pixels change by >20 levels. Default ON since the four-switch pick 2026-11-13 (`live_capture.h:586`). | DONE, default ON. The P13 status text is stale. | Open: `if_z` trap. Only `if_nz` resolves a flag, so `enable` can be wrong for an `if_z` gate (P13:L3 step 2 result). No record that this was checked. |
| L4 | Meshes sent with no material | "done 2026-11-13: the whole null row is deferred albedo never revisited" (P13:189) | Null row 16.3% -> 0 (30632051) and 4.0% -> 0 (41686139) with GREY_FIRST (`l4g-*`, 1,200 fake frames, P13:L4 result ~567-592). Counter `bare_meshes=` 137 / 622,214 -> 0 / 0 (gate case F, `test_live_late_files.py`). | DONE with GREY_FIRST on. With it off the row remains (one written reason). | None. |
| L5 | (a) untraced lit shaders; (b) terrain and ground blend family | "(a) resolved by L7's depth rule; (b) terrain done 2026-11-14 by a per-red-level tile bake... default flip is the user's pick" (P13:190) | (a): constants-only row 15.1% -> 4.6% (camp), 18.6% -> 6.1% (41686139) after L7 (P13:L7 result ~625-669). The hand-kept table (D3) was **not built**. (b): `terrain_bake.h`, gate `test_terrain_bake.py`. In game: floor 0.326 median (game 0.306), p95 0.550 (0.554), sat 0.205 (0.184), 45.5 fps replay (P13:L5b terrain bake ~899-921). Default ON since 2026-11-14 (`live_capture.h:570`). | (b) DONE, default ON. (a) residual, no table built. | (a): whether 4.6% / 6.1% is worth a table is UNVERIFIED. The stop rule (P13:L5) says the table is the fallback. |
| L6 | Emission for unlit and glowing surfaces | "blocked by data 2026-11-14" (P13:191) | Scout `l6_emission.md`: emissive terms in two lit shaders (cube `t8`, 2D `t10`) and one soft particle (P13:923-933). The 228 unlit shaders are classed by `effect=` (P13:L6 facts). | BLOCKED on data | A capture with lit signs or night (user F9, or a save elsewhere). P14 W4 has the same block. |
| L7 | Submit only real surfaces (was T3) | "done 2026-11-14: depth pre-pass and frame-1 leak (on by default), blended draws classified, overlay rule behind `NIER_REMIX_LIVE_SKIP_OVERLAYS=1` (default off)" (P13:192) | Depth rule `checks/depth_only.h`, gate `test_depth_only.py`, default ON (`live_capture.h:554`): meshes 1,257 -> 1,096; fps (real Remix) 26.9 -> 34.4 camp, 40.6 -> 46.2 41686139 (P13:L7 depth result ~625-669). Frame-1 leak, `WAIT_FOR_TARGET` default ON (`live_capture.h:563`): 87 + 48 leaked meshes -> 0 (P13:frame-1 result ~670-696). Blended draws: 91 (camp) and 46 (41686139) classified (P13:L7 blended ~823-845). Overlay rule `checks/overlay_rule.h`, `test_overlay_rule.py` (8 cases), default OFF (`live_capture.h:575-577`): camp 961 -> 950 meshes, no visible change. | DONE, depth and leak default ON. Overlay rule available, default OFF. | Overlay default: user has not picked (P13:~2130 "Optional"). |
| L8 | Per-instance tint, hair, water (was T5) | "open" (P13:193) | Tint: L3 constant albedo carries the tint for 9 of 30 scene shaders (`test_live_flag_constants.py` case `tinted`, mock `MOCK_FLAG_TINT`). Per-instance `cb8[rN.w]` form not done (a `shortcut:`), P13:L8 tint ~785-800. Hair: draw albedo is `(0.515, 0.474, 0.429)`, beige. Silver lobe `cb1[6..9]` (lines 315-330, 453-455 of the hair shader) not approximated, P13:L8 hair. Water: none of the captures has water (P13:923-933). | OPEN | Hair look: a user decision (P13:L8 hair; section 9 Q4 in P13:2100-2120). Water: laptop capture `frame_67078468` has water (P14); not analysed in any recorded file. |
| L9 | Sky from the game instead of a fixed file | "blocked by data 2026-11-14: all 7 captures... share one sun colour, one fog colour" (P13:194) | `PSParamBuffer1` identical in every capture with scene constants: sun (6.0, 5.1, 4.8), fog colour white 6.208 (P13:923-933). The dome is a fixed `nier_sky_hdr.dds` at strength 2.0 (`remix_live.cpp` sky block, ~276-278; P13:11.7). | BLOCKED on data | P14 W1 needs a desert truth frame. The desert laptop capture `frame_67279062` exists (P14), not yet analysed in a recorded file. |

Order rule carried in P13 (P13:~L table and P13:1569-1588): L1 and L2 first, then L3-L9, one writer per file.

### 1b. Track T (texture arrival, temporal). Table at P13:972-974

| Id | One-line description | Final Status text (short) | Evidence | Now | Blocked on / next |
|---|---|---|---|---|---|
| T1 | Show a mesh at once in grey; swap the material when the texture lands; no mesh rebuild | "done behind `NIER_REMIX_LIVE_GREY_FIRST=1` 2026-11-13... default flip is the user's pick" (P13:972) | Mechanism: texture id reserved at first sight; grey albedo (0.5) while the file is missing; destroy + create under the same hash (P13:T1 result ~1121-1166). Real Remix `t1-off-s` / `t1-on-s` (30632051, 1,150 frames): diff to settled frame 400 51.9 -> 15.0; 600 19.1 -> 3.4; 800+ 1.7-2.5 -> 2.9-3.0. Mesh builds 1,257 vs 2,579; texture-triggered rebuilds 0 vs 20; fps 29.0 vs 29.4. Gate `test_live_late_material.py`, suite 88/88 (`suite-s38`). Default ON since 2026-11-13 (`live_capture.h:599`, `live_scene.h:148`). | DONE, default ON. Status text is stale. | **Cutouts:** the proposed default (cutout meshes held back until their albedo lands, P13:T1 step 4) is **not in the code**. `live_scene.h:544` builds every mesh under GREY_FIRST unless `HOLD_UNTEXTURED=1`. The decision is open (P13:Section 9 Q1). Soak with `--switch 300` (T1 step 6) not recorded. |
| T2 | A replay that moves | "done 2026-11-13 (`NIER_REMIX_LIVE_CAMERA_ORBIT`, gate `test_camera_orbit.py`, `replay/README.md`)" (P13:973) | `REMIX_LIVE:53-70` parses the switch. `t2-orbit`: 600 frames, 41686139, `12:1.5`, 58.5 fps; shots 60.45 and 62.88 grey levels apart (P13:T2 result ~1168-1186). Suite 87/87 (`suite-s36`). | DONE | Object motion is still frozen in a capture (P13:T2 limit). Built in the proxy, not in `capture_replay.cpp` as step 1 said. |
| T3 | Motion vectors for skinned meshes | "answered + measured in the game 2026-11-14... default flip is the user's pick (recommended)" (P13:974) | Pose rebuilds 70,415 (CPU) -> 0 (GPU), 8 s turn, `t3-skin-off` / `t3-skin-on` (P13:T3 findings table ~1206-1234). In game, 7 min (`s2-gpuskin`): median fps 45.6 -> 59.9; p10 30.6 -> 58.6; meshes built 487,870 -> 1,774 (P13:S2 result ~846-865). `ab-defaults` 5 min: 60.0 median, p10 59.1 (P13:2100-2120). Default ON since 2026-11-14 (`REMIX_LIVE:268`). | DONE, default ON | The picture A/B for regression (same moment, shots) is not recorded (P13:T3 "open question"). `buffer=` / `buffer_dynamic=` churn (13-14k) is a separate item, not planned. |

### 1c. Track S (stability). Table at P13:1239-1240

| Id | One-line description | Final Status text (short) | Evidence | Now | Blocked on / next |
|---|---|---|---|---|---|
| S1 | Exit hang (old S4; P14 calls it C2) | "reproduced 2026-11-13... the thread stack needs the user (ptrace is blocked)" (P13:1239) | `REPLAY_EXIT=clean` (`capture_replay.cpp`): `s1-clean-300` never exits, 300 frames presented, 146 s timeout. `s1-warm` 202 s, same. `s1-long` 422 s, no exit (P13:S1 result ~1269-1299). `--mode off` (Remix not started) exits in 4.1 s (120 frames). `kernel.yama.ptrace_scope` = 1. Source: `rtx_initializer.cpp:201-209` (prewarm loop, no timeout, scout-claimed in P13:11.6). | BLOCKED (on permission) | Two ways to attach (sudo, or `ptrace_scope=0` for one run). A permission-free test is **not run**: `s1-no-shutdown` (skip `remixapi_Shutdown` and record exit and the next run). P13:S1 result last bullet. |
| S2 | Soak after each track lands | "first soak 2026-11-14: 12 min in the game, no crash, memory flat" (P13:1240) | `s2-soak`: 12 min, camp, alternating still and 40 deg/s turn. No crash, save unchanged. 1,787 meshes / 467 MB, flat. 2 of 479 windows > 100 ms (worst 278 ms). 25-29 fps while turning on CPU skin (P13:S2 result ~846-865). Replay: 60,000 frames, 1,074 s, exit 0, 43.4 fps median, RSS 1.87-1.98 GB, no trend (P13:11.2 "Soak"). | PARTIAL | No soak on the final defaults (GPU skin, all switches). G5 asks for 30 min of a looped route (P13:G5 table). Not done. |

### 1d. Track G (unattended game runs). Table at P13:1335-1339

| Id | One-line description | Final Status text (short) | Evidence | Now | Blocked on / next |
|---|---|---|---|---|---|
| G1 | Does the game start headless, nothing changed? | "reaches a rendering state 2026-11-13; needs Steam running (DRM); picture still missing" (P13:1335) | No Steam: stops at `Waiting for SteamStub DRM` (`logs/wax.log.2026-11-13`, P13:G1 result ~1365-1383). With Steam: renders on `Radeon RX 6800/6800 XT` (radv 26.2.6), menu ready 1600x900, first slot-0 redirect frame 556. Save backup `SlotData_0.dat` `1b76c94f…` unchanged. Steam start command in P13:G1 result table. | DONE in substance (game runs). The title-screen picture is UNVERIFIED as a file. Later shots from `game_run.py` stand in. | None for the plan. |
| G2 | Get into the world with no person | "done: dozens of unattended cold starts to the camp today, save unchanged every time" (P13:1336) | Menu script `wait:45,press:A:0.3,...` (P13:G2 result ~1412-1449). `g2-load4` (`save_ok: true`, 90 s camp). `g2-repeat1` (`live: false`) and `g2-repeat2` (`live: true`), both `save_ok: true`, exit `timeout`. Source: `input_drive.h:105-125`, `input_capture.h:260`. | DONE. Done-when "three runs in a row reach the world" with a first-frame log line: UNVERIFIED (the summaries do not show it). | None. |
| G3 | Capture without F9 | "done 2026-11-13 (`frame_12935626` from `g3-capture`, packed and replayed)" (P13:1337) | `NIER_CAPTURE_AT` at `menu_overlay.cpp:502`. Capture: 570 draws, 214 textures, 172.8 MB. `pack_capture.py` accepts it. Replay fake 570 draws; real `g4-truth` 900 frames at 60.0 fps (P13:G3/G4 result ~1488-1519). | DONE | None. |
| G4 | The game's own frame, paired with ours | "done 2026-11-14: exact pairs with the camera held still (`game-truth` vs `game-final`)" (P13:1338) | First pair 2026-11-13 `/tmp/g4-pair.jpg` (not kept): game median 0.372 / p95 0.569 / sat 0.180; ours 0.495 / 0.859 / 0.108 (P13:G3/G4 result). 2026-11-14 exact pair: P13:L1 final pass. Limits: 640x350 (the copied prefix's `Graphic.ini`), 24 missing shaders (`missing_shaders=24`). | DONE for the camp only | Other places need the user (R1, R5). |
| G5 | Scripted motion runs (pop-in, ghosting, fps, quit time) | "done 2026-11-14: 12-min soak (S2) and the GPU-skinning A/B in motion; quit time is S1" (P13:1339) | `g5-motion4`: 21 pictures, mean frame-to-frame difference 77 levels while turning, 3 when still (P13:G5 result ~1536-1557). Three traps listed there (`NIER_REMIX_SIZE` must equal the backbuffer; the `remix-1.6.1` shim does not present; the world script needs the live path). | PARTIAL | Quit time needs S1. The "Crash or hang over 30 min of a looped route" row (P13:G5 table) is not done (see S2). |

### 1e. Track P (performance). P13:1559-1567

No numbered items. P13 says "Nothing planned... parked with numbers in `PLAN_2026-11-12.md` section 4b". The fast profile (`rtx.enableSecondaryBounces = False`) was judged under D4 (see section 2): **rejected on data**. It stays commented in `deploy/rtx/laptop-c-fast.conf:29`.

### 1f. Section 6 (what needs the user or hardware). P13:1593-1598

| Id | What | State in P13 | State now (this digest) |
|---|---|---|---|
| R1 | Picture of the game's own frame at each capture point | "Startable: Track G, G4, for the spot the save loads at" (P13:1593) | PARTIAL: camp only (G4). Other places BLOCKED (user). |
| R2 | Capture v2: VS bytecode, the game's final frame, draws under 128 indices, RT format per draw, full mip chains | "Usable once G3 works" (P13:1594) | OPEN, not started. No file shows work on it. UNVERIFIED. |
| R3 | Live laptop run with `deploy/rtx/laptop-c-fast.conf` | "Not possible now" (P13:1595) | BLOCKED (user at the laptop). A play session did happen on 2026-11-14 (P13:2100-2120, log `runtime/laptop-play-20261114/NIER_SCALE.log`). |
| R4 | RX 9070 XT numbers | "Not allowed (it drives the monitors)" (P13:1596) | FORBIDDEN by rule (P13:constraint 3, P13:11.11). See the contradiction in section 7. |
| R5 | Captures of other scenes (desert, city, water, combat effects) | "Out of reach" (P13:1597) | BLOCKED (user). Laptop captures `frame_67078468` (water) and `frame_67279062` (desert) exist since 2026-11-14 (P14; content UNVERIFIED by me). |
| R6 | Combat, cutscenes, menus beyond the load | "Needs a person" (P13:1598) | BLOCKED (user). P14 C1. |

### 1g. Section 9 questions still open (P13:1644-1660)

| Id | Question | Answer status |
|---|---|---|
| Q1 | Cutout meshes in the grey stage: hold back or show grey? | OPEN. Code shows grey for all (`live_scene.h:544`). |
| Q2 | After a game session: keep the DLL that is installed (`065432e4` the old, or newest)? | OPEN as a question. Installed DLL now is `9555829d` (sha256 checked: `runtime/menu-dll/d3d11.dll` and the game folder's `d3d11.dll` match, 2026-11-14). No explicit user answer recorded. |
| Q3 | Installing into the game folder is implied by "the game may run". Right? | Acted on (installs `7250f3e8`, then `9555829d`). No explicit answer recorded. UNVERIFIED that the user agreed. |

### 1h. Decisions D1-D8 (2026-11-13). P13:40-47

Recorded in section 2 below with their landing place.

### 1i. Next work, agreed 2026-11-14. P13:2121-2137

| Id | Item |
|---|---|
| NW1 | Remix owns presentation (frame generation). Remix presents into the game window. Game Present withheld. Menus, loading and HUD still show. Gate-first, behind a switch. P14 P2 is the same item. |
| NW2 | Standard DLSS modes (Quality / Balanced / Performance / Ultra Performance) as an Insert-menu row using `SetConfigVariable`. P14 P1 is the same item. |
| NW3 | Sky (L9), water (L8), desert grade (L1 second area) from the two laptop captures. P14 W1, W3, W2. |
| NW4 | Mip chains for the terrain bakes (10 "suboptimal replacement texture" lines on the laptop log). |
| NW5 | `laptop_port.py install` should set `ec_hooks.dll` aside for a play install. S1 once ptrace is allowed. P14 C3 and C2. |

### 1j. Loose ends with no item id (all from P13's body)

| Loose end | Where | Note |
|---|---|---|
| Shaders in shared `NIER_CAPTURE/shaders/ps_<pointer>.dxbc` are keyed by process pointer. A later session overwrote 14,460 of 28,175 files. | P13:~691-700 ("Also found") | Capture should write shaders into its own frame folder. S-track item, never created. |
| F5: key collisions past 65,535 texture ids | P13:~775-779 (review fixes) | Not fixed. |
| F8: a shader created before the hook and reused after | same | Not fixed. |
| F10: roughness floor written on another thread, only with its env set | same | Not fixed. |
| F11: `bare` map not trimmed on eviction (memory only) | same | Not fixed. |
| Per-instance tint `cb8[rN.w]` form (white tints) | P13:L8 tint | A `shortcut:`. |
| `missing_shaders=24` in the game replay: some draws fall back | P13:G3/G4 result | Not fixed. |
| Object motion inside a capture is frozen | P13:T2 limit, RM | Only game runs show it (G5). |
| Relaxed `open` counter in `test_live_map_redirect.py` and `test_live_albedo_tag.py` never checked by a mutation | P13:12.1 step 4 | Do this before building on them. |
| Shim runtime `remix-1.6.1/rt/d3d9.dll` fails with error 126 unless the DLL directory is set; the in-game path must use `PortalRTX/bin/.trex/d3d9.dll` | P13:11.2 "Shim runtimes", G5 trap 2, RM "Runtime" | Fixed in `remix_live.cpp` (`SetDllDirectoryW`). |
| Object pops in while travelling (texture arrival at first sight) | P13:11.10 | Measured only in replay. G5 covers the game. |

### 1k. Mapping from P13 ids to P14 ids (ids collide)

| P13 id | Meaning in P13 | P14 id | Meaning in P14 |
|---|---|---|---|
| S1 | Exit hang | C2 | Exit hang "(old S1)" |
| L9 | Sky | W1 | Sky "(old L9)" |
| L8 water | Water | W3 | Water "(old L8)" |
| L6 | Emission | W4 | Emission "(old L6)" |
| L8 hair | Hair | W5 | Hair |
| L1 desert grade | Second area for the grade | W2 | Grade for the desert and camp |
| D1 (decision: game may run) | user decision | **D1** | Desktop at real resolution (a different thing) |
| P (performance track) | parked | **P1, P2** | Standard DLSS modes; Remix presents (different things) |
| — | — | E1, C1, C3 | New in P14 (effects; play session; laptop install) |

Collision risk: P14 reuses `D1`, `P1`, `P2`. A reader of P13 will read them the wrong way. The new plan should rename one set.

---

## 2. User decisions and picks, with dates

### 2a. Decisions D1-D8 (2026-11-13, P13:40-47)

| # | Decision (short) | Landed in | Source |
|---|---|---|---|
| D1 | The game **may run on this desktop**, unattended. The user cannot interact with it | Track G, sections 1, 5, 6 | P13:40 |
| D2 | A mesh whose texture has not arrived is shown at once in plain grey. The colour pops in | T1 step 4; code `GREY_FIRST` | P13:41 |
| D3 | A hand-kept per-shader table is acceptable for lit shaders the tracer cannot cover | L5 step 2 (not built, see 1a) | P13:42 |
| D4 | The fast profile is judged after the exposure pass | L1 step 6. Judged: rejected on data | P13:43; P13 L1 step 5-6 result |
| D5 | Albedo is written UNORM | Done, default since `3878183a` | P13:44; `REMIX_LIVE:233` |
| D6 | Steam may be started on this desktop for game runs | Track G, G1 | P13:45 |
| D7 | The only save is at the Resistance Camp | Track G (G4), section 6 (R5) | P13:46 |
| D8 | The plan is not to be executed by its author; it carries all research and method | Banner, sections 11 and 12 | P13:47 |

### 2b. Picks and answers after the decisions

| Date | Pick or answer | Effect | Source |
|---|---|---|---|
| 2026-11-13 | UNORM preferred: "looks more accurate to the game" (sRGB against UNORM sheet) | D5 | P13:13-35 ("Changed on 2026-11-13"); P13:1668 |
| 2026-11-13 | L1 pick: "3 or 4" → variant 4 (global tonemap, `saturation 1.3`) | In all four confs; `deploy/rtx/desktop-replay.conf:29` shows `saturation 1.3` | P13:L1 result, ~258-270 |
| 2026-11-13 | L2 orientation: "can't tell the difference apart from very minor shadows" | No Y flip stays the default | P13:L1 result end (~276) |
| 2026-11-13 | **All four switches flipped on by default**: `GREY_FIRST`, `SKIP_DEPTH_PS`, `WAIT_FOR_TARGET`, `FLAG_CONSTANTS` | Each rolls back with `=0` | P13:697-727 ("User picked 2026-11-13") |
| 2026-11-14 (morning) | "Picked the recommendations": `GPU_SKIN` and `TERRAIN_LAYERS` on by default | Each rolls back with `=0` | P13:~2110-2125 ("2026-11-14 morning, user picked the recommendations") |
| 2026-11-14 | Effects missing in Remix: user note (P14 E1) | New item E1, open | P14:E1 |
| 2026-11-14 | "Note this down as the next piece of work" (Remix presentation) | NW1 | P13:2121-2137 |
| 2026-11-14 | Laptop play with `ec_hooks.dll` set aside: "much better state" | Laptop runs with the current build | P13:2100-2120 (laptop first crash and play) |
| 2026-11-14 | Two F9 captures (desert and water) on the laptop, copied to `runtime/laptop-play-20261114/` | NW3, W1-W3, W5 data | P13:2100-2120; P14 |
| 2026-11-01 (from a source comment only) | Effects left out of the scene: "user decision 2026-11-01" | `keep_effects=false` default | `checks/live_capture.h:1693-1694` (comment); `:592` |

### 2c. Still waiting for a user pick (no default flip without it)

| Pick | Why it is open | Source |
|---|---|---|
| Cutout meshes in grey, or held back (Q1) | Code shows grey for all. Plan default (hold back) not built | P13:T1 step 4; P13:Section 9 Q1; `live_scene.h:544` |
| Hair: approximate the silver lobe (smoother hair) | Look decision | P13:L8 hair |
| Overlay rule default (`SKIP_OVERLAYS`) | "Optional", small effect | P13:~2130 ("Waiting for the user's pick", item 3) |
| Fast profile (`enableSecondaryBounces = False`) | Rejected on data by the lead; the user's answer not recorded | P13:L1 step 5-6 result; `deploy/rtx/laptop-c-fast.conf:29` |
| L8 hair, L6 intensity, L9 option | Each needs a sheet first | P13:L6 step 4; P13:L9 steps |

---

## 3. Rules, method and mistakes (P13 sections 1, 2, 12) as a checklist

### 3a. Section 1: constraints of the phase (P13:49-60)

- [ ] **No person drives the game.** Replay of F9 captures is the main tool. Game runs are unattended (D1).
- [ ] **Game folder** `/mnt/second/SteamLibrary/steamapps/common/NieRAutomata` is written only by `checks/install_live_dll.py` (hash-pinned, with rollback folder) and by the game. Nothing else is added, edited or deleted there. After a session, check the installed hash against the receipt. Back up the save folder before the first run.
- [ ] Do not use the **RX 9070 XT** (it drives the monitors). Replay and game runs use the **RX 6800 XT**, headless.
- [ ] No package installs. No system config change.
- [ ] Suite stays green after every change: `python3 checks/run_suite_parallel.py runtime/<dir> -j 24` (about 3 min).
- [ ] Frame rate must not fall. Section 7 of this digest has the numbers.

### 3b. Section 2: method (P13:78-103)

Command block as written in P13 (copy for the new plan; all paths relative to `analysis/`):

```
cd analysis
G=/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE      # read-only
python3 checks/build_menu_dll.py                                           # after any change to checks/*.h|*.cpp
python3 replay/run_replay.py <label> $G/frame_<id> --frames 2500 [--env KEY=VALUE] [--conf FILE]   # real runtime
python3 replay/run_replay.py <label> $G/frame_<id> --mode fake --frames 400                         # what we send, as text
python3 replay/material_scoreboard.py <id> [<id>]                          # needs runtime/replay/n1-fake-<id>
python3 replay/frame_tools.py stats <shot.png> [...]                       # the numbers of section 3b
python3 replay/frame_tools.py diff <a.png> <b.png>                         # grey levels; under 2 is denoiser noise
python3 replay/frame_tools.py sheet /tmp/x.jpg "old=<a.png>" "new=<b.png>" [--crop x0,y0,x1,y1]
python3 replay/view.py <shot.png> /tmp/x.jpg                               # small JPEG an agent can Read (offset=1)
python3 checks/run_suite_parallel.py runtime/suite-<n> -j 24               # must be 86/86 or more
```

Results go to `analysis/runtime/replay/<label>/`: `summary.json` (`steady_fps_median`), `shot-2499.png`, `NIER_SCALE.log`, and in fake mode `fake-remix.log`.

Rules for every item (P13:104-127):

- [ ] **1. Measure first.** Write the number that shows the problem before changing code.
- [ ] **2. Gate before code** for anything with logic: a failing test in `checks/` that the change turns green, and that goes red when reverted (`/skill:frozen-gates`).
- [ ] **3. New behaviour behind a switch**, default off, until the user picks from a sheet. Then flip the default and keep the switch as rollback (as with UNORM).
- [ ] **4. A/B sheet for the user**: same capture, same frame (`shot-2499.png`), old left, new right, labelled. One JPEG per capture under `/tmp/`, copied to the laptop's `Downloads` when reachable. Windows cannot be opened from SSH (session 0). The user opens the file.
- [ ] **5. Performance guard**: after any proxy change, rerun the three reference captures. Fail the item if a capture drops more than **3%** below the table in section 7.
- [ ] **6. Review**: a `reviewer` pass on the diff before an item is done. Findings are input.
- [ ] **7. Scout claims about the Remix source are checked in the source** before a change depends on them.
- [ ] **8. Do not stop while an item is open.** Stop only for a pick the user must make, hardware not here, or an unexplained red suite (then revert to green first).

Reference captures (P13:118-124): `30632051` (heavy camp, worst case), `41686139`, `23275488` are the **reference captures for look work** (desktop captures with pixel shaders). `21396979` and `21565698` are older camp captures for frame rate only. Laptop captures `220084953` and `220097046` are under `runtime/laptop-port/frametime2/NIER_CAPTURE/`.

### 3c. Section 1 "What each tool can prove" (P13:62-76)

| Tool | Replay (works) | Unattended game run (Track G) | Still out of reach |
|---|---|---|---|
| What the proxy sends for a real frame | yes | yes | |
| The path-traced picture | yes | yes | |
| The game's own picture at the same spot | no | yes (same save, same script, Remix off) | |
| Motion: vectors, ghosting, pop-in while travelling | no | yes, for a walk and turn script | combat, cutscenes |
| Frame rate | 6800 XT, replayer as the game | 6800 XT, real game thread | laptop GPU, DLSS, frame generation, 9070 XT |
| Quit time, loading screens | no | yes | |
| Other scenes | the seven captures only | the camp, plus what a walk reaches | desert, city, water need a save there |

Rule from P13:76: every look change ends in one of three ways: a number right by construction (a flag read from the game's constant buffer, a format tag), a match against the game's own frame, or a sheet for the user to pick from. **An agent does not decide that a picture looks better.**

### 3d. Section 12: method (P13:1922-2056)

**12.1 The loop for one item** (P13:1924-1939)

- [ ] 1. Number first. Write it in the item. If it cannot be produced, the item is an investigation and ends in a table.
- [ ] 2. Gate: a test that fails today for the reason the item names. Run it and see it fail.
- [ ] 3. Change behind a switch that defaults to off. Smallest diff that turns the gate green.
- [ ] 4. Mutation: revert the change (or flip the switch) and see the gate go red again. A gate that stays green proves nothing.
- [ ] 5. Suite: `run_suite_parallel.py` in a fresh folder, all green.
- [ ] 6. Replay, real runtime, three reference captures: fps against the guard, shot against the last accepted shot.
- [ ] 7. Sheet for the user where the change shows. The default flips only after the user picks.
- [ ] 8. Review by a `reviewer` on the whole diff. Fix or record each finding.
- [ ] 9. Write down: Status cell, numbers in `replay/README.md`, a dated entry in `PROGRESS.md`.

**12.2 Four levels of test** (P13:1941-1950)

| Level | Command | Time | Proves | Does not prove |
|---|---|---|---|---|
| Mock gate | `python3 checks/test_<name>.py` | 0.5-3 min | Our logic on a constructed case, run under Wine, Xvfb and llvmpipe against a fake runtime that logs every call | NieR's real data, the real path tracer |
| Replay, fake | `run_replay.py <label> <capture> --mode fake --frames 400` | 1-3 min, no GPU | What we send for a real game frame, as text (`fake-remix.log`) | The picture |
| Replay, real | `run_replay.py <label> <capture> --frames 2500` | 1-3 min, 6800 XT | The picture and fps with the real runtime | Motion, the game's own picture, the laptop |
| Game run | Track G (built) | | Motion, loading, quit, the game's picture | Other scenes, the laptop |

**12.3 Writing a mock gate** (P13:1952-1971)

- [ ] Copy the shape of `checks/test_live_albedo_tag.py` or `checks/test_live_map_redirect.py`. A gate re-runs itself inside `xvfb-run` with a private Wine prefix under `runtime/<gate-name>/`, builds the mock and fake runtime with mingw (`-Wall -Wextra -Werror`), and writes `validation.json`.
- [ ] **Every env var a gate sets must be in `ENV_KEYS`** (`checks/test_remix_live.py:32`). The runner strips those keys first.
- [ ] The mock grows by switches: `MOCK_<NAME>` in `menu_overlay_mock_game.cpp`.
- [ ] The fake runtime (`remix_live_fake_runtime.cpp`) logs `CreateMaterial`, `CreateMesh`, instances. A line starting `VIOLATION` marks a call the real runtime would reject. Every gate asserts no `VIOLATION`. **When the real runtime behaves in a way the fake does not model, teach the fake first.**
- [ ] Assert on bytes and counts. Name the first mismatch in the message.
- [ ] A counter printed by the worker can be read mid-frame. Take the settled value, not one sample.
- [ ] Say in the docstring what the gate cannot prove. Add it to the suite.

**12.4 Measuring frame rate** (P13:1973-1987)

- [ ] 2,500 frames, one capture, one change per run. Read `steady_fps_median` and `steady_ms`.
- [ ] Builds that should match differ by about 1% (30632051: 29.3 on `3c487b0a`, 29.0 on `3878183a`). Under 3% is not a result. Repeat before believing a small win.
- [ ] **One job on the GPU at a time.** A replay beside another replay, a suite run or a game gives meaningless numbers.
- [ ] `--mode off` gives the replayer's own cost. Subtract it.
- [ ] `--env NIER_REMIX_LIVE_PROFILE=1` adds `remix: live observe us/frame` lines. `--env REPLAY_PROFILE=1` adds the D3D11 call split.
- [ ] Replay ends with `TerminateProcess`, so the exit hang (S1) does not show unless `REPLAY_EXIT=clean`.
- [ ] One-key confs live in `runtime/replay/confs/<name>.conf`. Copy `deploy/rtx/desktop-replay.conf`, add the key. **Keep `rtx.dlssPreset = 2` in every conf.**

**12.5 Measuring the picture** (P13:1988-2001)

- [ ] `frame_tools.py stats`: median luma, p95, clipped (>0.98) and crushed (<0.02) share, mean saturation. They rank candidates and catch blown or crushed frames. They do not say which picture is right.
- [ ] `frame_tools.py diff`: 1.1-1.5 grey levels is denoiser noise between identical runs. Under 2 means "unchanged". Normal maps gave 5.55.
- [ ] `frame_tools.py sheet`: refuses panels of different size. Use `--crop`. Same capture and frame always.
- [ ] An agent may look at `replay/view.py` output (small JPEG, `Read` with `offset=1`). It finds gross faults only. It does not settle taste.

**12.6 Material scoreboard** (P13:2002-2010)

- [ ] `replay/material_scoreboard.py <id>` reads `runtime/replay/n1-fake-<id>/fake-remix.log`. Reads 400 frames. A mask of 32 pixels or less is a placeholder (a heuristic: L3 replaces it with the game's flag).
- [ ] Rerun after every material item. Put before and after rows in the item.

**12.7 Reading the runtime source** (P13:2011-2022)

- [ ] `rtx_options.h` declares every `rtx.*` key with its default. Look a key up there before it goes in a conf.
- [ ] Scout brief that worked: one question per agent, read-only, "every claim needs a file path, a line number and a one-line quote", "if you cannot find it say not found", answer first, 60 lines at most.
- [ ] **A scout's answer is a lead.** Open the lines before a change depends on it.
- [ ] Through `workflow`, name the model: `anthropic/claude-haiku-5-5` on this provider.

**12.8 Handing work to other models** (P13:2023-2032)

- [ ] Only **gated** code goes to a local model. The frozen gate is the brief.
- [ ] Never accept "passed" from a worker. Rerun the gate.
- [ ] One writer per file at a time. `live_capture.h` and `live_scene.h` are touched by T1, L3, L4, L6.
- [ ] Prose and exact-match edits stay with the lead.
- [ ] Log every delegated task in `~/Documents/Local-Model-Delegation-Outcomes.jsonl`.
- [ ] Skip delegation when the brief takes longer than the task.

**12.9 Safety rules** (P13:2033-2041)

- [ ] Nothing committed or pushed unless the user asks. `git status` before edits.
- [ ] The game folder: only the installer and the game write there.
- [ ] No package installs. No system setting changes.
- [ ] A background job ends by its own process group. Nothing not started here is killed.
- [ ] `/tmp` is lost on reboot. Anything a later reader needs goes into `replay/research-<date>/`.

**12.10 Mistakes already made** (P13:2042-2055 table). Each one is a rule:

| # | Mistake | What it cost | Rule |
|---|---|---|---|
| M1 | Trusting `rtx.upscalerType` in the conf | Every replay before 2026-11-12 ran TAAU | Check a key took effect by its result |
| M2 | Reading cumulative counters as rates | "1,538 texture rebuilds" reported as churn. It is a one-time startup cost | Take the difference between stats lines |
| M3 | Comparing a "before" taken under another config | Part of the 14.5 -> 52.8 fps headline was the TAAU fix | State what changed between two numbers |
| M4 | A redirected Map kept past its mapping | Found by review, not a gate | Review every diff, then add the gate |
| M5 | A gate reading one sample of a live counter | One false failure in the suite | Settled values only |
| M6 | Assuming a DXGI enum value | Three wrong numbers in a new gate (BC5 is 83, BC7 is 98 and 99, BGRA 87 and 91) | Print the value from the compiler |
| M7 | Assuming a window opens on the laptop over SSH | Three failed attempts | Copy the file, tell the user where it is |
| M8 | Believing normal maps were on | No replay had them | Read the default in the code (`remix_live.cpp:252`) |
| M9 | Starting a large port at 01:00 with nobody to look | Parked | Large look changes need the user's eyes the same day |

Further mistakes found in P13's body (not in the table):

| # | Mistake | Where | Rule |
|---|---|---|---|
| M10 | A switch applied **globally** (four gates froze the old contract, twice). Every experiment reverted | P13:T1 progress, ~1031-1100 | New behaviour behind a switch from the first edit |
| M11 | Refresh created orphan materials because the map key was passed, not the material's own hash | P13:T1 progress fact 3 | Reuse the material's own hash |
| M12 | A path passed early (from `texture_paths`) before the file was on disk | P13:T1 progress fact 2 | `landed` means on disk |
| M13 | The fake runtime did not log a no-albedo material, so a grey one looked like a destroy with no create | P13:T1 progress fact 4 | Teach the fake first |
| M14 | Narrow `blended=` counter (70) used as the number of blended draws. Raw D3D11 blend state gave 53.8% of triangles | P13:L4/L6/L7 table, ~593-624 | Measure with the widest honest counter, then narrow it |
| M15 | `rtx.conf` never read by the game for G1-G5 and the first L1 runs. Remix looks in the working directory | P13:L1 final pass, ~761-770 | Confirm with a log line (`remix: rtx.conf <path>`) |
| M16 | A crash blamed on the conf. Bisect showed a one-off start-up failure | P13:L1 final pass; commit `2e67060` | Bisect before blaming a change |
| M17 | `untextured=0` counter read as "no untextured meshes" (137 were) | P13:L4 step 5 | Counters must agree with the scoreboard |
| M18 | Saturation range from the doc comment ([0, 1]) treated as a clamp. 1.3 took effect | P13:L1 result, note on the key | A key's range is what its result shows |
| M19 | A pair taken during a scripted turn did not match (load jitter of 1-2 s) | P13:all-switches section | Take game comparisons with the camera still |
| M20 | Steam started without `DISPLAY` / `WAYLAND_DISPLAY` / DBus: it exits | P13:G1 result table | Use the exact env in the table |
| M21 | `gamescope` calls `setsid`, so `timeout --foreground` did not reap runs | P13:G2 result | Runner finds its own processes by `NIER_RUN_LABEL` and kills them |
| M22 | Shader-file reuse across game sessions silently replaced 14,460 files | P13:~691-700 | Per-capture shader folder (loose end) |

---

## 4. Section 6 and section 8, in substance

### 4a. Section 6: what needs the user, a person at the controls, or other hardware (P13:1589-1604)

Substance, not verbatim:

- **R1, the game's own frame at each capture point.** This is the only ground truth for "looks like the game". It is startable now for the save's spot (the camp, Track G G4). Other places need the user: a screenshot, or an F9 capture at the place, or a save there.
- **R2, capture v2.** Adds vertex shader bytecode, the game's final frame, draws under 128 indices (post passes, colour grade), render target format per draw, and full mip chains. Makes the game's picture reproducible offline. Code and gates can be written in the mock now. Usable once G3 works (it does).
- **R3, live laptop run** with `deploy/rtx/laptop-c-fast.conf`: frame rate on the real target, DLSS, frame generation. Not possible unattended. G5 covers pop-in and ghosting on the desktop in the meantime.
- **R4, RX 9070 XT numbers.** The real desktop target. Not allowed: it drives the monitors.
- **R5, other scenes** (desert, city outdoors, water, combat effects). L8 water and L7 effects had no data. The only save is at the camp (D7). Nobody can play from there.
- **R6, anything a script cannot do**: combat, cutscenes, menus beyond the load. Needs a person.

Checklist for the next live run (P13:1600-1603): frame rate and `other` ms against frametime2 (14.8 fps, 4.1 ms); longest freeze; camera holds; exposure outdoors and indoors; normal map orientation on a surface with lettering; chrome surfaces gone; ghosting behind 2B while running; texture blink at first sight; quit time.

### 4b. Section 8: who does what (P13:1626-1635)

| Role | Use for | Rule |
|---|---|---|
| lead | gates, replay runs, sheets, acceptance, anything on a real system | Reruns every gate itself |
| `scout` (small cloud model) | reading the dxvk-remix source, option names, shader disassembly digests | Read-only. A claim that decides a change is checked in the source first |
| `local-worker` / cloud `worker` | gated ports: L3 step 2, L5 step 2, the fake-runtime changes for T1 | Frozen gate first, one writer per file, log to the ledger (`/skill:local-delegation`) |
| `reviewer` | every diff before an item is done | Findings are input |
| user | picks from sheets (L1 and the fast profile, L2 confirm, L3, L6, L7, T1 cutouts), answers section 9 | Cannot interact with the game (D1). No item may depend on the user pressing a key in it |

---

## 5. End-of-file state (P13:2057-2137), what happened on 2026-11-14

### 5a. State at the end of the 2026-11-13/14 session (P13:2057-2120)

**In the game, installed and default:** grey-first textures, depth pre-pass skipped, frame-1 pass leak closed, the game's own material flags, tint on flag colours, review fixes, and the game's `rtx.conf` actually read, with the L1 grade fitted to the game's own frame (median 0.316 vs 0.306, p95 0.530 vs 0.554, saturation 0.180 vs 0.184, warmth 1.217 vs 1.214). 55 fps at 640x350 in the copied prefix. 12-minute soak stable.

**Waiting for the user's pick at that time** (each one variable, measured in the game): GPU skinning (59.9 vs 45.6 fps median while turning, p10 58.6 vs 30.6, every mesh built once; recommended), terrain layers (gravel-and-sand floor; recommended), overlays (optional; no visible change), 2B's hair (silver lobe; look decision).

**Blocked on the user:**
- **S1 exit hang**: a deadlock in Remix's teardown. Proved: 4.1 s exit with Remix off, never with it on. The thread stack needs `ptrace` (`kernel.yama.ptrace_scope=1`).
- **L6 emission, L8 water, L9 sky**: every capture is one area and time of day (same sun and fog constants). Unattended walking out of the camp ends at a door. Needs F9 captures outdoors in the City Ruins, at night, and near water.
- **Laptop**: it ran the October DLAA mod at that time, not the live Remix path. Moving it over is an install on the play machine.

**Done in that session, in plan order:** L1 final pass, L2, L3, L4, L5 (a and terrain bake), L7 (depth rule, leak, blended classification), L8 tint, T1, T2, T3 (measured), S2 soak, G1-G5, plus fixes found on the way (shader identity on address reuse, `rtx.conf` never read in-game, empty-path material, races). Suite 94/94 at the end.

**2026-11-14 morning, user picked the recommendations:** `GPU_SKIN` and `TERRAIN_LAYERS` on by default. The CPU-bake gate (`test_live_skinning_capture.py`) pins `GPU_SKIN=0` as rollback. Suite 94/94 (`suite-s56`), DLL installed. In-game with no overrides (`ab-defaults`, 5 min of still and turn): 60.0 fps median, p10 59.1 while moving; pose rebuilds 0; terrain tiles baked. Same run with the terrain bake off (`ab-noterrain`): 59.9 / 59.1. The bake costs nothing.

**Laptop updated 2026-11-14** (`spaghetti`, RTX Spark N1X, ARM64) by `deploy/laptop_port.py install`. The October NIER_DLAA proxy was backed up (hash `6ba266d6…` verified). Today's build `9555829d…` is chained behind it. Plus `NIER_ENV.ini` (`deploy/laptop-NIER_ENV.ini`) and `rtx.conf` (`deploy/rtx/laptop-game.conf`: laptop conf B, DLSS with Ray Reconstruction, the L1 grade). The proxy points Remix at that conf itself. Not launched by the lead. `laptop_port.py restore` puts the DLAA install back. Open: grade fitted under XeSS without Ray Reconstruction.

**Laptop first launch, 2026-11-14 08:01: crashed** 0.8 s after the Present hook, before Remix started. Access violation in `ntdll` with `ec_hooks.dll` and `d3d11.dll` on the stack (dump `runtime/laptop-port/dumps/play-20261114.dmp`, `checks/read_minidump.py`). Known from October (`LAPTOP_PORT.md:136-148`): the DLAA `ec_hooks.dll` writes its hooks into our proxy. Steam also rewrote `NieRAutomata.exe` at 07:58 (17,837,952 -> 17,613,568 bytes).

### 5b. Laptop play 2026-11-14, 08:13-08:19 (P13:2100-2120)

- Log: `runtime/laptop-play-20261114/NIER_SCALE.log`. The user played with `ec_hooks` set aside (`ec_hooks.dll.off`).
- Remix fps: P13 says **17.1 median, p10 13.3** (user saw ~25 on the game side). **My recount from the same log**: 75 "remix: X fps" windows, median **17.0**, nearest-rank p10 **14.1** (method of P13 unknown: UNVERIFIED).
- Readback 51 ms of the frame (`GetRenderTargetData` + `LockRect`). My recount: median **50.6 ms** over the 75 windows. Desktop equivalent 7.9 ms (P13). Other stages under 3 ms.
- GPU bound at 2880x1800, DLSS Performance. October: 13.1 fps, 58 ms.
- Change made: `rtx.qualityDLSS = 0` (Ultra Performance) in `deploy/rtx/laptop-game.conf:10` (rollback `= 1`, line 9). See contradiction C5 on the evidence for this.
- Recording (87 s, desert, `replay/research-2026-11-14/`): geometry, characters, HUD, sun shadows right. Sky a flat grey-blue plate (L9). Sand mustard (warm balance and saturation 1.6 on an already warm scene). Shadow sides near black (no sky light).
- F9 captures copied: `frame_67078468` (water, 9.2 GB apparent size by `du`; P14 says 13.6 GB) and `frame_67279062` (desert, 5.5 GB).

### 5c. Section 11 facts that the new plan stands on (P13:1675-1921)

These are the research claims. Key ones:

| Fact | Source | Status |
|---|---|---|
| `rtx.dlssPreset` defaults to On and writes `upscalerType = DLSS` in the Derived layer, which outranks `rtx.conf`. Every conf must carry `rtx.dlssPreset = 2` | `rtx_options.cpp:159-181`, `rtx_option_constants.h:194` (P13:11.1; measured) | Measured |
| A non-Custom graphics preset overwrites conf keys it owns (`pathMaxBounces`, `denoiseDirectAndIndirectLightingSeparately`). Keys not owned hold under any preset | P13:11.1; `rtx_option_layer.cpp:731` (scout) | Scout, partly measured (P13 table at 1856-1866 of RM) |
| `albedoConstant` **replaces** the texture; it does not multiply | `opaque_surface_material_interaction.slangh:638, 656-658` (P13:11.3) | Source (scout) |
| Albedo is decoded with `pow(x, 2.2)` even when tagged sRGB, so an sRGB DDS decodes twice | `rtx_texture.cpp:145-147` (P13:11.3) | Source (scout) |
| `alphaTestType` 0 means Never: a zeroed struct gives an invisible surface | `surface_shared.h:47-48` (P13:11.3) | Source (scout) |
| Material handle is its hash; `CreateMaterial` under a live hash is ignored; destroy + create is the in-place swap | `rtx_remix_api.cpp:886`, `rtx_asset_replacer.cpp:222-227` (P13:T1 progress) | **Source read by the lead** |
| `CreateMesh` under a live handle is ignored; new vertices dropped | `rtx_asset_replacer.cpp:243-247` (P13:T3 findings) | **Source read by the lead** |
| Previous vertex positions exist for any object Remix updates, but the API cannot update a live mesh, so only Remix-skinned meshes get them | `rtx_scene_manager.cpp:512-544` (P13:T3 findings) | **Source read by the lead** |
| Textures must be DDS files on disk. No upload-from-memory API | `rtx_asset_data_manager.cpp:620-633`, `rtx_remix_api.cpp:1784-1797` (P13:11.4) | Scout |
| A file missing at `CreateMaterial` is never retried | `rtx_remix_api.cpp:276-279` (P13:11.4) | Scout |
| Sky-category API instances are hidden; no API fills the sky probe. The dome light is the route | `rtx_instance_manager.cpp:1047-1050` (P13:11.7) | Scout |
| Default tone map Local, `useLegacyACES` true; auto exposure on, EV -2 to 5 | `rtx_options.h:1181-1188`, `rtx_auto_exposure.h:76-84` (P13:11.7) | Scout |
| `CopyRenderingOutput` is queued, not blocking | `rtx_remix_api.cpp:1453-1556` (P13:11.2) | Scout |
| Prewarm wait at destroy has no timeout | `rtx_initializer.cpp:57, 201-209` (P13:11.6, read by the lead) | **Source read by the lead**; the cause of S1 is not confirmed by a stack |
| `remix_c.h` is **not** in the 1.6.1 tree. The nearest copy is `runtime/remix-probe/sample/include/remix/remix_c.h` (API 0.6.6) | P13:11.3 | See contradiction C1 |
| Game main lit family: `cb1[0]` flags `.x` normal, `.y` albedo `cb1[4].xyz`, `.z` gloss `cb1[5].x`, `.w` metal `cb1[5].y` | P13:11.8; `checks/pbr_trace.py`; RM finding 1 | Measured (L3 step 1, 5 hand-traced shaders) |
| Terrain family: slot-0 repeat `cb1[5].xy`; layers 1-2 use `cb1[5].zw`, `cb1[6].xy`; vertex colour sets weights | P13:11.8, RM finding 2 | Closed 2026-11-12 (P13:11.8). RM still says "not pinned" (stale) |
| What an F9 capture holds, and what it does not (no VS bytecode, no final picture, no draws under 128 indices, no full mips) | P13:11.8 | Measured |
| Replay consequence: with no VS, the replayer runs a generated VS that puts every vertex at the origin, so the game's picture cannot be reproduced offline | P13:11.8 | Source: `replay/capture_replay.cpp` header |

Per-capture stats line (P13:11.9): 30632051 has 3,382 game draws, 1,354 into other targets (skipped), 778 prepass dropped, 1,239 submitted as 1,420 instances from 1,257 meshes, 452 textures, 70 blended (narrow counter), 389 alpha-tested, 26 lights, 7 sky draws, 374 MB mesh bytes. Shadow-copy budget (262,144 KB) reached.

---

## 6. Current switch defaults (source checked 2026-11-14)

All lines are from the source files in `analysis/checks/`. "Set to" is the value that turns the behaviour on or off. "Rollback" is the value that gives today's old behaviour. Gate column names the gate that pins the rollback, from P13.

| Switch | Default now | Set to | Rollback | Read at | Picked by user | Gate / evidence |
|---|---|---|---|---|---|---|
| `NIER_REMIX_LIVE_ALBEDO_UNORM` | **ON** (UNORM) | `=0` = sRGB tag (old) | `=0` | `REMIX_LIVE:233` (`!= L"0"`) | 2026-11-13 (D5) | `test_live_albedo_tag.py` |
| `NIER_REMIX_LIVE_NORMAL` | **ON** | `=0` = no normal maps | `=0` | `REMIX_LIVE:252`; `LIVE_CAP:540` | L2 default flip, orientation confirmed 2026-11-13 | `test_live_normal_map.py` (case 3b, case 2) |
| `NIER_REMIX_LIVE_NORMAL_FLIP_Y` | OFF | `=1` = flip Y | (leave unset) | `REMIX_LIVE:265` (`== L"1"`) | No flip picked | `test_normal_octahedral.py` |
| `NIER_REMIX_LIVE_NORMAL_RAW` | OFF (converted) | `=1` = raw bytes | (leave unset) | `REMIX_LIVE:264` | — | — |
| `NIER_REMIX_LIVE_PBR` | ON | `=0` = no mask-derived PBR | `=0` | `REMIX_LIVE:253` | — | — |
| `NIER_REMIX_LIVE_FLAG_CONSTANTS` | **ON** | `=0` = textures (old) | `=0` | `LIVE_CAP:586` | 2026-11-13 (four switches) | `test_live_flag_constants.py` (rollback arm) |
| `NIER_REMIX_LIVE_GREY_FIRST` | **ON** | `=0` = hold back | `=0` | `LIVE_CAP:599`, `LIVE_SCENE:148` | 2026-11-13 (four switches) | `test_live_late_material.py`; hold-back gates pin `=0` |
| `NIER_REMIX_LIVE_HOLD_UNTEXTURED` | OFF | `=1` = hold back (the rollback companion) | (leave unset) | `LIVE_SCENE:149` (`env_flag`, needs `=1`) | with GREY_FIRST | `test_live_late_files.py` case F |
| `NIER_REMIX_LIVE_SKIP_DEPTH_PS` | **ON** | `=0` = submit depth shells (old) | `=0` | `LIVE_CAP:554` | 2026-11-13 (four switches) | `test_depth_only.py` |
| `NIER_REMIX_LIVE_WAIT_FOR_TARGET` | **ON** | `=0` = frame-1 leak (old) | `=0` | `LIVE_CAP:563` | 2026-11-13 (four switches) | `test_live_scene_target.py` case `wait-target` |
| `NIER_REMIX_LIVE_TERRAIN_LAYERS` | **ON** | `=0` = layer 0 only (old) | `=0` | `LIVE_CAP:570` | 2026-11-14 (morning) | `test_terrain_bake.py`, `test_terrain_layers.py` |
| `NIER_REMIX_LIVE_GPU_SKIN` | **ON** (comment at `LIVE_CAP:593-595` still says "off by default": stale) | `=0` = CPU bake (old) | `=0` | `REMIX_LIVE:268` (`!= L"0"`) | 2026-11-14 (morning) | `test_live_skinning_capture.py` (pins `=0`) |
| `NIER_REMIX_LIVE_SKIP_OVERLAYS` | OFF | `=1` = skip multiplicative and tint overlays | (leave unset) | `LIVE_CAP:575-577` (`== '1'`) | not picked (optional) | `test_overlay_rule.py` |
| `NIER_REMIX_LIVE_EFFECTS` | OFF (effects dropped) | `=1` = keep effect draws as solid geometry | (leave unset) | `REMIX_LIVE:259`; `LIVE_CAP:592`, `:1719` | 2026-11-01 (from source comment) | — |
| `NIER_REMIX_LIVE_MAP_REDIRECT` | ON | `=0` = old read-back mirror | `=0` | `REMIX_LIVE:231`; `LIVE_CAP:62` | — | `test_live_map_redirect.py` |
| `NIER_REMIX_LIVE_HOLD` | ON | `=0` = no one-frame hold | `=0` | `REMIX_LIVE:303` | — | — |
| `NIER_REMIX_LIVE_ASYNC_READS` | OFF | `=1` = non-blocking staging reads | (leave unset) | `REMIX_LIVE:230`; `LIVE_CAP:163` | — | — |
| `NIER_REMIX_LIVE_NO_ALPHA_TEST` | OFF | `=1` = all materials "always keep" | (leave unset) | `REMIX_LIVE:302` | — | — |
| `NIER_REMIX_LIVE_NO_HUD` | OFF | `=1` = no HUD capture | (leave unset) | `REMIX_LIVE:247` | — | — |
| `NIER_REMIX_LIVE_NO_SKY` | OFF | `=1` = drop sky dome | (leave unset) | `REMIX_LIVE:248` | — | — |
| `NIER_REMIX_SKY` | dome strength 2.0 (per comment) | number | — | `REMIX_LIVE:276-278` | L1 A/B 2026-11-13: 1.0 discarded (clip 2.1%) | — |
| `NIER_REMIX_LIVE_ROUGHNESS_FLOOR` | 0.15 | 0..1 | — | `REMIX_LIVE:254`; comment at `:89` | — | — |
| `NIER_REMIX_LIVE_MIN_INDICES` | 128 | n | — | `LIVE_CAP:1160`; `REMIX_LIVE:260` | — | — |
| `NIER_REMIX_LIVE_SHADER_ROWS` | 12 | n | — | `REMIX_LIVE:1078-1079` | — | — |
| `NIER_REMIX_LIVE_BUILD_LOG` | OFF | `=1` | (leave unset) | `LIVE_SCENE:150` (`env_flag`) | — | — |
| `NIER_REMIX_LIVE_PROFILE` | OFF | `=1` | (leave unset) | `REMIX_LIVE:232` | — | — |
| `NIER_REMIX_LIVE_SKIP_CODE` | 0 (off) | 16 hex digits (FNV-1a of a shader's bytecode) | — | `LIVE_CAP:579-583` | diagnostic only | — |
| `NIER_REMIX_LIVE_CAMERA_ORBIT` | unset (off) | `<deg/s>[:<units/s>]` | — | `REMIX_LIVE:53-70` | diagnostic (T2) | `test_camera_orbit.py` |
| `NIER_REMIX_LIVE_DRIVE` | unset (off) | input script | — | `REMIX_LIVE:297`; `input_drive.h:124` | — | `test_input_drive.py` |
| `NIER_REMIX_LIVE_MENU_DRIVE` | unset (off) | menu script | — | `input_drive.h:125` | — | `test_input_drive.py` |
| `NIER_CAPTURE_AT` | unset (off) | seconds, comma list | — | `menu_overlay.cpp:502` | — | `test_menu_overlay.py` case `capture-at` |
| `DXVK_RTX_CONFIG_FILE` | set by the proxy to the `rtx.conf` beside the DLL when unset and the file exists | path | set it empty? UNVERIFIED | `REMIX_LIVE:752-761` | 2026-11-14 fix (P13:L1 final pass) | `test_live_flag_constants.py` case `rtx-conf` |

Conf defaults (the `rtx.*` keys, not env):

| File | Keys that matter | Note |
|---|---|---|
| `deploy/rtx/game.conf` (installed in the game folder as `rtx.conf`) | `rtx.dlssPreset = 2` (`:30`), `rtx.tonemap.saturation = 1.6` (`:41`), `rtx.tonemap.exposureBias = -0.85` (`:44`), plus the rest of the grade (contrast 0.90, colorBalance 1.0 0.89 0.70, tonemappingMode 0) | Base is the replay conf. XeSS through `dlssPreset 2` |
| `deploy/rtx/laptop-game.conf` (laptop) | `rtx.dlssPreset = 2` (`:6`), `rtx.qualityDLSS = 0` (`:10`; rollback `= 1` at `:9`), `rtx.tonemap.saturation = 1.6` (`:17`), `exposureBias = -0.85` (`:20`) | DLSS with Ray Reconstruction (per P13 note) |
| `deploy/rtx/desktop-replay.conf` | `rtx.dlssPreset = 2` (`:6`), `saturation 1.3` (`:29`) | Replay base |
| `deploy/rtx/laptop-c-fast.conf` | `rtx.enableSecondaryBounces = False` **commented** (`:29`); `rtx.qualityDLSS = 0` (`:11`), `graphicsPreset = 3` (`:12`) | The fast profile stays off (judged on data) |

---

## 7. Measured numbers the new plan must hold

### 7a. Frame rate guard for the reference captures (P13:2 table, DLL `3878183a`, `n1-base-*`)

| Capture | fps to hold | Fail below (-3%) | Other measured on the same DLL |
|---|---:|---:|---|
| 30632051 (heavy camp) | **29.0** | 28.1 | `l1c-30632051` 28.9 (L1 exposure only, same DLL): within 0.3% |
| 41686139 | **42.9** | 41.6 | `l1c-41686139` 42.8 |
| 23275488 | **49.3** | 47.8 | `l1c-23275488` 49.4 |

Floors after the next change: re-measure on the **current installed DLL `9555829d`**. The 13 plan does not record a guard run for it. UNVERIFIED for all three captures.

### 7b. Frame rate with later DLLs (replay, real runtime, 2580x1080, 2500 frames)

| DLL | Label | 30632051 | 41686139 | 23275488 | Note |
|---|---|---:|---:|---:|---|
| `141629a8` (L2 normals on) | `l2-default-30632051` | 28.6 | — | — | -1.4% against 29.0 |
| `7250f3e8` (four switches) | `l7r-on-*` (22:30), `all-on-*` (23:11) | 34.4 / 32.9 | 46.2 / 45.9 | not measured | P13 table says camp 32.8, 41686139 45.7 |
| `7250f3e8` | `l7r-off-*` (same day, switches off) | 27.1 | 40.7 | — | |
| not stated | `tint-*` (23:49-23:52) | 33.4 | 45.5 | — | |

**Gap:** no real-runtime guard run exists for `23275488` after the L1 exposure pass (10:17, 2026-11-13). UNVERIFIED for the current defaults.

Fake-mode runs (`n1-fake-*`, `l3-*`, `l4-*`, `l5-*`, `l7-*`) report 5-12 fps. **These are not frame-rate numbers.** They use the fake runtime.

### 7c. Real game, camp, 640x350 (the copied prefix's `Graphic.ini`). Not comparable to replays

| Stage | fps median | Source |
|---|---:|---|
| Game-side today, still camera (before switches) | 44.5 | P13:all-switches table |
| Four switches | 54.2 | P13:all-switches table |
| + L1 grade in `game.conf` (`game-final`) | 55.5 | P13:L1 final pass |
| + GPU skin + terrain (`ab-defaults`, 5 min still and turn) | **60.0** (p10 59.1 moving) | P13:2100-2120 |
| CPU skinning in motion, 7 min (`s2-gpuskin` off) | 45.6 (p10 30.6) | P13:S2 result |
| 12 min camp soak with CPU skin (`s2-soak`) | ~54 still, 25-29 turning | P13:S2 result |

### 7d. Replay numbers, README baseline (DLL `3c487b0a`, `p6e-*`, 2500 frames, 6800 XT, XeSS Performance, `minPrimsInDynamicBLAS = 0`)

RM, section "Baseline". Each row is what the plan must not fall below on that DLL:

| Capture | Draws | Remix fps | Readback ms | Game frame p50 ms | `--mode off` ms | Capture cost ms | Run label |
|---|---:|---:|---:|---:|---:|---:|---|
| 21396979 camp | 3,276 | 52.8 | 16.2 | 5.8 | 1.9 | 3.9 | `p6e-21396979` |
| 21565698 camp | 3,185 | 53.3 | 16.2 | 5.6 | 1.8 | 3.8 | `p6e-21565698` |
| 23275488 | 1,894 | 50.4 | 18.3 | 3.3 | 1.3 | 2.0 | `p6e-23275488` |
| 30632051 camp | 3,382 | 29.3 | 31.1 | 6.4 | 2.0 | 4.4 | `p6e-30632051` |
| 41686139 | 2,056 | 43.9 | 21.0 | 3.6 | 1.2 | 2.4 | `p6e-41686139` |
| 220084953 (laptop capture, 2880x1800) | 484 | 28.2 | 33.8 | 1.7 | — | — | `p6d-220084953` |
| 220097046 (laptop capture, 2880x1800) | 769 | 26.4 | 36.0 | 2.3 | — | — | `p6d-220097046` |

Other RM numbers the plan must not lose:

- **Before the fixes** (same captures): 30632051 13.5 fps, 41686139 23.8, 21396979 14.5, 21565698 15.2, 23275488 34.5, laptop 24.6 / 22.8 (RM, "Before tonight").
- **`minPrimsInDynamicBLAS`** on 30632051: 1000 (default) 25.1 fps (readback 36.8); 300 27.0 (34.0); **0 = adopted, 29.3 (31.1)**; 3000 21.7 (40.9). Picture unchanged (1.1-1.3 grey levels).
- **Upscaler preset** on 30632051: XeSS Performance 25.1; `rtx.xess.preset = 0` (Ultra Performance) 31.8 (`p3x-up-30632051`); Native AA 8.2.
- **Laptop capture, XeSS** (not DLSS): `t2-xessup-220084953` XeSS Ultra Performance **39.4 fps** against `p6d-220084953` XeSS Performance **28.2**. P14's "+40%" is this number (see C5).
- **Secondary bounces off** (`rtx.enableSecondaryBounces = False`): 33.9 fps alone; with Ultra Performance and no RTXDI: 40.1 (`p3l-nosec-up-30632051`). Darkens the camp interior. **Judged and rejected on data** (P13 L1 step 6: `l1f-23275488` median luma 0.000, 76.8% crushed).
- **Per-key on 30632051 under Custom** (`graphicsPreset = 4`, stock quality): base 18.1; `useRTXDI = False` 20.6; `pathMaxBounces = 1` 20.8; `enableSecondaryBounces = False` 26.2; `volumetrics.enable = False` 18.4; `denoiseDirectAndIndirectLightingSeparately = False` 18.7.
- **Did not help** (do not retry without a new reason): `rtx.enableAlphaTest = False` 29.2; `rtx.enableCullingInSecondaryRays = True` 29.6; `rtx.useRTXDI = False` on top of no-secondary: 33.5 (nothing gained).
- **Proxy's own cost** (`p4-prof5-30632051`, µs per frame): state 288, input assembly 409, key 1,166, material 319, rest 2,051. 0.7-1.3 µs per draw across captures.
- **Closed questions** (RM / P13:11.2): duplicate submissions none (0 repeats of geometry, shader and constants on 30632051 and 41686139); direct present not worth it (readback is the worker's wait); camera constant buffer read once (41686139 game frame 26.5 -> 4.2 ms).
- **Soak** (replay): 60,000 frames, two captures alternating every 300, 1,074 s, exit 0, 43.4 fps median, RSS 1.87-1.98 GB, no trend, 1,835 meshes (`s2-soak-3063-2139`).
- **T2 orbit**: `t2-orbit` 58.5 fps, 600 frames, 41686139, `12:1.5`.
- **Picture guard** (P13:12.5 and 3b): 30632051 UNORM median 0.526 / p95 0.927 / clip 0.4% / crush 1.0% / sat 0.128 (`n1-base`). After L1 pick: median 0.456 with exposure 0.5 etc. (P13:L1 table). **Game truth** camp (`game-truth`): median 0.306 / p95 0.554 / p05 0.168 / sat 0.184 / R:B 1.214. **Current target** (`game-final`): 0.316 / 0.530 / 0.190 / 0.180 / 1.217.
- **Noise floor**: diff between identical runs 1.1-1.5 grey levels (P13:12.5). Under 2 = unchanged.

### 7e. Laptop (spaghetti, RTX Spark N1X), the only laptop numbers

| Quantity | Value | Source |
|---|---|---|
| Remix fps median, 2880x1800, DLSS Performance | 17.1 (P13) / **17.0 (my recount, 75 windows)** | `NIER_SCALE.log`, `remix: N fps over the last 60 frames` |
| p10 | 13.3 (P13) / **14.1 (my recount, nearest-rank)** | same, method UNVERIFIED |
| Readback median | 51 ms (P13) / **50.6 ms (my recount)** | same |
| Desktop readback for comparison | 7.9 ms (P13) | P13:2100-2120 |
| October, DLAA + DLSS Performance | 13.1 fps, 58 ms | P13:2100-2120 |

### 7f. Measured on the desktop only, and laptop item changes not yet measured

- **D1 (P14)** asks for 40 fps presented at 2880x1800. No measured baseline on DLSS with the current build. UNVERIFIED.
- **DLSS Ultra Performance on the laptop** is **not measured**. The +40% that justified it is XeSS on the desktop (RM "The upscaler preset is the biggest knob", and C5 below).

---

## 8. Contradictions and stale text (for the 2026-11-14 plan)

Each one is checked against the file cited. The last column says what to do.

| # | What P14 (or P13) says | What the evidence says | Action |
|---|---|---|---|
| C1 | P14 P1: "`SetConfigVariable` (`remix_c.h:786`)" | In `runtime/remix-probe/sample/include/remix/remix_c.h`, `SetConfigVariable` is at **line 724** (typedef) and **line 810** (struct member). Line 786 is `PFN_remixapi_dxvk_SetDefaultOutput`. The implementation is `runtime/remix-source/0ba9973f…/rtx_remix_api.cpp:1267`. P13:11.3 says `remix_c.h` is **not** in the 1.6.1 tree | Fix the cite to `remix_c.h:810` and `rtx_remix_api.cpp:1267`, or verify the header of the Remix build that is in use |
| C2 | P14 header: "commit + push after each item" as a rule that carries over | `analysis/AGENTS.md` and the repo rules: "Nothing is committed or pushed unless the user asks." `git status -sb`: `main...origin/main`, no ahead or behind. 158 commits; the last 20 are 2026-11-14 commits that were pushed. P13 says "Every step is committed and pushed" (P13:2100-2120). No record that the user asked | Remove the rule, or get the user's explicit approval for commit and push |
| C3 | P14 C2 (exit hang): "blocked on permission" | P13:S1 result records a permission-free fact (`--mode off` exits 4.1 s) and an experiment that needs no permission (`s1-no-shutdown`, not run). P14 drops both | Add the no-permission test before the item is blocked |
| C4 | P14 D1: "Desktop at its real resolution (3440x1440, 6800 XT: no DLSS, no frame generation)" | P13 rule 3 and P13:11.11 and R4: the RX 9070 XT drives the monitors and is off limits. The 6800 XT is headless with no monitor. A 3440x1440 run on the 6800 XT is a headless run, not the desktop's own GPU. The item cannot run as written | Say which GPU, which resolution and how it is headless. Or ask the user (R4). Rename the item (ID collides with P13 D1) |
| C5 | P14 P1 and laptop change: "+40% measured at 2880x1800 in replay" for `rtx.qualityDLSS = 0` (RM, laptop section) | The +40% is **XeSS** Ultra Performance on the desktop (`t2-xessup-220084953` 39.4 vs `p6d-220084953` 28.2). RM says "on the laptop this is the DLSS profile" with no DLSS measurement. Ultra Performance on DLSS is UNVERIFIED on any GPU | Measure DLSS Ultra Performance in replay (`--env` or conf) before citing +40% |
| C6 | P13:Track L L1 note and P14 "readback" | P13:11.2 says readback is "the worker's wait for the traced frame, not a copy the game thread pays". P13 laptop note says "readback 51 ms of the frame". P14 P2: "removes the per-frame readback". Whether readback costs game-thread frame time is unclear | The P2 spike should settle it: measure game-frame time with and without the readback |
| C7 | P14 W1 and W2: "numbers against the game's frame at the same spot" for the desert | P13 R1, R5, D7: the only save is at the camp. Nobody can play from there. A desert truth frame needs the user (save or F9 in the desert). Unattended it is impossible | Mark W1 and W2 as BLOCKED (on user) for the truth frame. Or add a user step |
| C8 | P14 header: "the laptop... sky is a flat grey-blue plate", and "frame_67078468 13.6 GB" | `du --apparent-size`: `frame_67078468` is **9.2 GB**, `frame_67279062` is 5.5 GB. The 13.6 GB figure is not what is on disk | Use the measured size |
| C9 | P14 "17.1 median, p10 13.3" (from P13:2100-2120) | My recount from the same log: median 17.0, nearest-rank p10 14.1 (75 windows). Method not stated | State the method, or use the recount |
| C10 | P13 status text, T1, L3, L5 (rows at P13:186-190, 972): "default flip is the user's pick" | The user picked on 2026-11-13 (four switches) and 2026-11-14 (GPU skin, terrain). Code shows default ON (see section 6). Status text is stale | Update the status text in the new plan |
| C11 | `live_capture.h:593-595` says `NIER_REMIX_LIVE_GPU_SKIN` is "Off by default" | `REMIX_LIVE:268` sets `!= L"0"` (ON since 2026-11-14) | Fix the comment (not a plan item; a note) |
| C12 | RM "Findings so far" 2 says the terrain repeat bake "is not pinned yet" | P13:11.8 says "closed 2026-11-12" (the repeat is the captured `cb1[5]`, with uv bake, `uv_bits`) | RM is stale. Update RM |
| C13 | RM header: `DLL 3c487b0a (today 04719c50 differs only by the T2 switch)`; P13 §2 guard uses `3878183a` | Two DLL hashes for two baselines. Current installed is `9555829d` (checked) | The new guard table must name its DLL |
| C14 | P13 section 0 "Working tree: uncommitted on main" (P13:17) vs the end state "committed and pushed" | git shows a clean tree on `main...origin/main` (untracked `.pi/` only, not ours) | Update the section 0 text in the new plan |
| C15 | P14 "Remix owns presentation... removes the per-frame readback as a side effect" vs P13:11.2 "Direct present instead of readback: not worth it" | Two different claims about the same thing. P13 decided it was not worth it on a measured basis, for the game thread. P14 wants it for frame generation | Note the reversal. The go/no-go spike decides it |
| C16 | P13:L5 "(a) untraced lit shaders" stop rule: "go to the table" | The table (D3) was accepted by the user but not built. L7 later cut the residual to 4.6% | Decide whether the table is worth building |
| C17 | Runtime source path. P14: "`runtime/remix-source/0ba9973f…` (the dxvk-remix source of the runtime in use)". P13: `analysis/runtime/src/dxvk-remix` (remix-1.6.1), with `rtx_user_menu.cpp:372` and options in it | `remix-source/0ba9973f…` has 14 files and no `rtx_options.h` or menu code. `src/dxvk-remix` is the full tree. Which one built the DLL in use (`PortalRTX/bin/.trex/d3d9.dll`) is UNVERIFIED: that path is not in the repo tree | Say which source tree each cite uses, and confirm the build |
| C18 | P14 E1 "live_capture.h:1693-1724", "1666" | Checked: `:1414` (`declares_effect_buffers`), `:1666` (scene-target filter), `:1694-1724` (effect drop, `:1719`). **Matches** | None |
| C19 | P14 P1 "`rtx_user_menu.cpp:372`" (in the P14 text: "rtx_user_menu.cpp:372 disables the mode list otherwise") | `src/dxvk-remix/src/dxvk/imgui/rtx_user_menu.cpp:372` is `const bool disableNonPresetSettings = RtxOptions::dlssPreset() != DlssPreset::Custom && dlssSupported;` **Matches**, in the `imgui` folder | None (path to add) |
| C20 | P13 claims `rtx_render/rtx_user_menu.cpp` (not a path) | The file is in `src/dxvk/imgui/` | Use the correct path |

---

## Open questions

1. **Cutouts in the grey stage (Q1).** Does the user want cutout meshes held back until their albedo lands, or shown grey? The code shows grey for all (`live_scene.h:544`). Determined by: a sheet from a replay with the writer delayed, at frame 20, 120, 2499, both ways (P13:T1 step 7). The user picks.
2. **Game folder DLL after a session (Q2).** Keep `9555829d` (installed now) or go back to `065432e4`? Determined by: the user's answer. Nothing in the record gives one.
3. **Remix binary identity.** Which source tree built `PortalRTX/bin/.trex/d3d9.dll` in use: `runtime/src/dxvk-remix` or `runtime/remix-source/0ba9973f…`? Determined by: `strings` or the build hash of the DLL in the Remix install. Not done by me (the path is not in the repo tree; I did not search outside the repo).
4. **Guard for DLL `9555829d`.** Current fps on `30632051`, `41686139`, `23275488` under the current defaults, with the replay. Determined by: `run_replay.py` with the three reference captures, one at a time, 2500 frames. Not done by me.
5. **`23275488` with the four switches and the L1 grade.** Not measured in replay. Determined by the same run as 4.
6. **Laptop frame rate with DLSS Ultra Performance.** Not measured. Determined by: the user's play session, or a replay on the desktop with `rtx.qualityDLSS = 0` in DLSS mode (not XeSS). The second is possible without the user.
7. **Readback and game-thread time (C6).** Does the readback cost game-thread time? Determined by: `NIER_REMIX_LIVE_PROFILE=1` with and without readback in a replay (P2 spike).
8. **Exit hang, no-permission test (C3).** Does a process with `Shutdown` skipped exit clean and behave on the next run? Determined by: `s1-no-shutdown` (P13:S1 result last bullet). No permission needed.
9. **Exit hang, stack (S1).** Which wait is stuck? Determined by a thread stack (`winedbg --command "bt all"` or `gdb -p`). Needs `ptrace` permission (`kernel.yama.ptrace_scope=1`): the user's decision.
10. **Emission (L6 / W4).** Which shaders emit, and which captures have lit signs or night? Determined by: a user F9 capture at night or near signs, or a save elsewhere. Needs the user.
11. **Water (L8 / W3).** Are the water draws in `frame_67078468` and what do they need? Determined by: a `material_scoreboard.py` run and the shader table (`NIER_REMIX_LIVE_SHADER_ROWS`) on that capture. Not done by me (fake mode is possible without a GPU; I did not run it).
12. **Sky (L9 / W1).** Is `PSParamBuffer1` in `frame_67279062` the same as the camp's? Determined by: the same reading as P13:923-933 on the desert capture. Not done by me.
13. **Hair (L8, W5).** Approximate the silver lobe, or accept beige? Determined by: a user sheet (A/B). The user decides.
14. **Fast profile (D4) after the final grade.** The L1 step 6 says repeat after the final pick. Not recorded. Determined by: the same three-capture run with and without `enableSecondaryBounces`, and the user's answer.
15. **`if_z` gate form (L3 step 2 trap).** Is any shader's `enable` flag under `if_z`? Determined by: grep of the disassembly (`runtime/pbr-re/lit/`) for `if_z` near `cb1[0]`. Not checked by me.
16. **Soak on final defaults (S2).** Clean for 30 min of a looped route? Determined by: `game_run.py --live` with the G5 route for 30 min (P13:G5 table). Not run.
17. **Laptop numbers method (C9).** Which window and percentile did P13 use for 17.1 and 13.3? Determined by: the author of P13:2100-2120.
18. **Capture size (C8).** Is `frame_67078468` 9.2 GB or 13.6 GB? Measured: 9.2 GB apparent. Determined: the user, or a `du` with the same flags on the laptop copy.
19. **Two DLL hashes in RM and P13 (C13).** `04719c50` was said to be the T2 switch build. Not confirmed in source. Determined by: `sha256sum` of the DLL those runs used (their `summary.json` has no hash field).
20. **The cutout claim T1 step 6 soak, and the T1 "time to last CreateMaterial"** (P13:T1 step 5 and 6). Not recorded. Determined by: the fake-mode log, time from first `CreateMesh` to last `CreateMaterial`.
21. **Shader folder keyed by pointer (loose end).** Is the per-capture shader folder implemented? Not in the record. Determined by: a grep for the shader output path in `checks/` (not done by me).
22. **G2 "three runs in a row" (done-when).** Does each of three cold starts log `remix: live scene first frame`? Determined by: the three run logs in `runtime/game-runs/` (`g2-repeat1` has `live: false`, so it cannot show it).

---

## Recommended steps for the plan

1. **Carry the rules, change one.** Copy P13 sections 1, 2 and 12 (this digest, section 3) into the new plan. Replace "commit + push after each item" (P14 header) with "commit and push only when the user asks" (`AGENTS.md`). Check: `git log` shows no new commit or push without a user request. (Fixes C2.)
2. **Rename the colliding ids.** P14 uses D1, P1, P2 for things that P13 uses D1 (decision), P (performance track). Keep P13's ids for the old items and give the new ones fresh prefixes (for example `N1-N5`). Check: `grep -n '^| D1 ' analysis/PLAN_*` shows one meaning per file. (Fixes the 1k table.)
3. **Fix the Remix cite (P14 P1).** Use `runtime/remix-probe/sample/include/remix/remix_c.h:810` (member) and `runtime/remix-source/0ba9973f…/rtx_remix_api.cpp:1267` (implementation), and say which copy. Before writing the conf, check the key name in the source tree that built the DLL. Check: a log line from the real run with the key, and the fake runtime log of the call. Do not write a key name that is not in `rtx_options.h`. (Fixes C1, C17.)
4. **P1 (standard DLSS modes), gate first.** Gate in the fake runtime: the Insert-menu row sets `rtx.qualityDLSS` through `SetConfigVariable` (fake logs the call). Then one replay per mode with `--env` or conf, and the logged render size per mode. Behind a switch, default off (the current `rtx.qualityDLSS` stays). Check: the real run's log shows the render size change for each of the four modes. Record the numbers in RM.
5. **Measure the laptop change before citing it (C5).** Replay on the desktop with `rtx.qualityDLSS = 0` in DLSS mode (not XeSS) at 2880x1800, on `220084953`, 2500 frames, 1 job on the GPU. Compare with `rtx.qualityDLSS = 1`. Check: `steady_fps_median` in `summary.json` for both. Only then keep "+40%" in the plan.
6. **Guard table for the current DLL.** Run the three reference captures (30632051, 41686139, 23275488) with the current defaults and the current installed DLL `9555829d`, one at a time. Floors = measured x 0.97. Put the DLL hash in the table. Check: `summary.json` files under `analysis/runtime/replay/<label>/`. (Fixes section 7a gap and open question 4-5.)
7. **Presentation spike (P2 / NW1), go/no-go first.** Gate-first: in the fake runtime, a present-from-Remix path that withholds the game's Present, with the HUD still drawn. Settle C6 first: measure game-frame time with the readback on and off (`NIER_REMIX_LIVE_PROFILE=1`). Check: the go/no-go decision is written into the item with numbers. The rest of the item waits on it.
8. **E1 effects, step 1 from P14.** Use the shader table (`NIER_REMIX_LIVE_SHADER_ROWS`) and `effect=` counts on `30632051` and the desert capture. Record per shader: blend state, render target, draw count. Check: a table in the item. Keep `NIER_REMIX_LIVE_EFFECTS=1` as the A/B arm. Do not change defaults before the user picks.
9. **W1 and W2 (sky, grade): mark the truth-frame step as BLOCKED on the user (C7).** Add the step "user F9 or screenshot at a desert spot with Remix off" to section 6 of the new plan. Until then, do the sky numbers (L9 option b) from the desert capture alone and say so. Check: the item's done-when names the user step.
10. **W3 water (L8), data first.** Run `replay/material_scoreboard.py` on `frame_67078468` (fake mode, 400 frames, label `n1-fake-67078468` per the naming rule). Find the water draws. Check: the table of water shaders with triangle share is in the item before any code.
11. **L6 emission (W4): ask the user for one night capture.** Do not code before it. Check: the item says what capture is needed and why (signs, lamps).
12. **C1 (cutouts, Q1): put a sheet to the user.** Replay with the writer delayed, frames 20, 120, 2499, cutouts held back and cutouts grey (the sheet P13:T1 step 7 describes). Check: the user's answer is recorded in section 2 of the new plan. Only then change `live_scene.h:544`.
13. **Hair (L8 / W5): user sheet, then a gated approximation.** Sheet: beige (today), silver lobe approximated (smoother hair). If the user picks the approximation, gate it in the mock (`MOCK_FLAG_TINT` style) behind a switch. Check: the gate red then green, the sheet kept.
14. **Fast profile (D4): re-judge after the final grade.** Run the three captures with and without `enableSecondaryBounces` under the current `game.conf`/`desktop-replay.conf`. Record the answer in `deploy/rtx/laptop-c-fast.conf` (commented, with the reason). Check: `laptop-c-fast.conf:29` has the answer with its numbers.
15. **S1 (C2), the no-permission test first.** Run `s1-no-shutdown`: `REPLAY_EXIT=clean` with `Shutdown` skipped, 300 frames, then a second run. Record exit time and whether the second run is clean. Check: `run_replay.py` output and exit code. Only if it fails, ask for ptrace (open question 9).
16. **S2, soak on final defaults.** Run `game_run.py --live` with the G5 route for 30 minutes on the current defaults. Record RSS, mesh count, frame time and exit code. Check: the report exists under `analysis/runtime/game-runs/`. Compare with the 12-minute soak (P13:S2).
17. **Clean up stale text (C10-C14, C20).** Update the status cells of T1, L3, L5 (default is ON now). Fix `live_capture.h:593-595` comment (GPU skin is on). Fix RM "Findings so far" item 2 (closed 2026-11-12). Replace section 0 "uncommitted" text. Check: `grep -n 'default flip is the user' analysis/PLAN_2026-11-13.md` returns nothing in the new plan.
18. **Fix the laptop numbers (C8, C9).** Use the recount (17.0, 14.1, readback 50.6 ms) with the method written down. Use the measured capture size (9.2 GB). Check: a one-line script or command in the item that produces the numbers from `NIER_SCALE.log`.
19. **Name the source tree for each cite (C17).** For any Remix cite in the new plan, write which tree (`runtime/src/dxvk-remix` or `runtime/remix-source/0ba9973f…`). Check the build of the DLL in use before a change depends on a cite.
20. **Record each user pick in section 2 of the new plan, with its date.** A pick is not a decision until it is in that table. Check: each default flip in the new plan has a row with its date.
21. **Keep the rollback arms in the gates.** For each switch in section 6, the gate that pins the rollback must stay in the suite. Check: the suite runs with each switch at its rollback value, and the default run stays green.
22. **Loose ends (section 1j) as items with a number.** At least: per-capture shader folder (M22), key collisions F5, F8, F10, F11, and the `open` counter mutation check (P13:12.1 step 4). Check: each has a gate or a written reason.
23. **Run the suite once per item.** `python3 checks/run_suite_parallel.py runtime/suite-<n> -j 24`, 94/94 at the last count (P13:2121-2137). Check: count recorded in the item.
