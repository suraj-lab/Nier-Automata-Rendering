# T1 / D1 live evidence — 2026-11-14 (desktop, headless RX 6800 XT, 3440x1440)

Runs used the fixed guards, a copied Proton prefix and the headless 6800 XT. Every run: `save_ok: true`, real
save hashes identical before/after, only the run's own `gamescopereaper`/proton children killed by exact ownership.
No system/Steam setting changed. Full commands are in each `runtime/game-runs/<label>/summary.json`.

## What unblocked the pipeline

The installed game is no longer the build the code patches were derived from
(`NieRAutomata.exe` SHA-256 `09854c2d45d9a72e66357e72f50cee379bb2eafe35b3d64e5e88f4eddc8613fa`, 17,613,568 B;
the headers pin `44ee2dc0…`). All seven anchored signatures are gone:

| anchor | declared RVA | matches | equivalent hits |
| --- | --- | ---: | --- |
| `depth_prologue` | 0x258fe0 | no | 18 (generic) |
| `depth_patch` | 0x25904e | no | 1 at 0x25914e |
| `scale_sig1` | 0x248179 | no | 0 |
| `scale_sig2` | 0x2481b8 | no | 9 (ambiguous) |
| `proxy_out_width` | 0x18791 | no | 0 |
| `proxy_out_height` | 0x187a3 | no | 0 |
| `proxy_output` | 0x18006 | no | 75 (generic) |

Receipt: `runtime/a0-shader-audit/game-patch-anchors.json`, produced read-only by
`replay/execution-2026-11-14/derive_game_patch_anchors.py`. The proxy's refusal (`depth patch result:
signature-mismatch`, "NOT scaling to avoid the black scene") is correct fail-closed behaviour. Re-deriving those
anchors is its own RE task and is **not** required for native-resolution work, because:

- `NIER_REMIX_SIZE` must equal the game's backbuffer. At gamescope 1920x1080 the game runs 640x350 (its own copied-prefix
  `Graphic.ini`), which is why 1600x900 Remix stayed `paused`.
- At gamescope **3440x1440** with `--env NIER_REMIX_SIZE=3440x1440` the log shows
  `live scene target 3440x1440 of 3440x1440` and `resumed at 3440x1440`: the game renders at the real desktop
  resolution without any code patch. `game_run.py` gained `--size WxH` for this
  (`checks/test_game_run_size.py`: red "no command builder exposed", green after; safe labels unchanged).

## Menu automation (proven recipe)

The 2026-11-13 "sequence that works" still loads the world, but its trailing `LEFT` presses have to be shortened:
with a long hold, the faster non-Remix run applies them **in-world** and rotates the camera, so the pair no longer
matches. Working script for both sides:

```
wait:45,press:A:0.3,wait:5,press:A:0.3,wait:5,press:A:0.3,wait:5,press:LEFT:0.05,wait:1,press:A:0.3,wait:5,
press:LEFT:0.05,wait:1,press:A:0.3,wait:5,press:LEFT:0.05,wait:1,press:A:0.3,wait:120
```

`press:LEFT:0.05` is enough to move the Yes/No dialog from No to Yes, and short enough that the world camera shift
is negligible. A drive with no `LEFT` never loads: the dialog defaults to **No** (`t1-original-clean`).

## Camp pair at 3440x1440

| Side | Run | Shot | L1 median | p95 | clip >0.98 | crush <0.02 | saturation |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| original | `t1-original-shortleft` | shot-2 | 0.367 | 0.571 | 0.0% | **0.0%** | 0.182 |
| Remix | `t1-remix-clean` | shot-2 | 0.541 | 0.784 | 0.0% | **25.6%** | 0.122 |

Mean absolute difference: **56.31** grey levels. Same camera, same save, same 3440x1440 target; the character idle
pose differs by a few frames (idle animation phase), so character pixels are excluded from any tuned comparison.

**Correction after measuring the black bars:** the 25.6% "crush" is the ultrawide pillarbox (content x 440..2999 of
3440, aspect exactly 16:9), not a grading defect. The honest reading of this pair is therefore limited to the
*unpillarboxed* centre, and a grade comparison must wait for a 16:9-matched pair. What does survive is the
desaturation observation (0.122 vs 0.182) and a clear D1/P2 constraint: Remix renders 16:9 and the handoff centres
it, so 3440×1440 comparisons mix two different horizontal FOVs.

Labelled sheet for the user: `execution-2026-11-14/t1-camp-3440-pair.jpg` (full frames + a zoomed crop of the
terminal/ground region). No artistic default was chosen.

## Status

- T1: camp pair acquired at real resolution with a reproducible recipe; desert and pond pairs still pending (each
  needs the same two-run treatment at its own location), and the character-region mask must be defined before the
  W2 comparison is frozen.
- D1: unblocked and demonstrated at 3440x1440; the measurement receipt (repeats, warm-up windows, adapter, fps) is
  still to be produced on the baseline and candidate.
- A0 patch anchors: stale by game update, needs re-derivation or an explicit decision to keep the scale feature off.
