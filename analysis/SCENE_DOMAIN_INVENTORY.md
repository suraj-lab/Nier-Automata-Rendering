# Scene-domain inventory (pre-AA) — 2026-10-19

Source: the two retained in-game frame dumps in `framedump-capture/` (3440×1440,
FSR4 native AA). Ids below are from dump 1 (`…224309_810.txt`); dump 2 has the same
textures, writers, formats and structure under different ids. Offline parsing only.

## Summary

The game's screen-sized work before AA uses a small, stable set of resources:

| Class | Count | Scale with render res? |
| --- | --- | --- |
| Native 3440×1440 game targets | 14 | **yes** |
| Half-res 1720×720 game targets | 5 | **yes** |
| Quarter-res 860×360 | 1 | **yes** |
| Screen-tile compute buffers (2 dispatches, 108×48 / 108×80 groups) | 2 | **yes**, sizes derived from screen |
| AA mod / bridge targets (native) | 7 | handled by the mod patch, not the game |
| Shadow atlas (4096², drawn as 2048² quadrants), 256² env faces, 1024×1 LUT, fixed small textures | — | no (resolution-independent) |

Viewports before AA: native 3440×1440 (~1560–1680 draws), half-res 1720×720
(74–128), quarter 860×360 (1). Shadow/env/LUT viewports are fixed sizes.

## Pass sequence (dump 1)

| Entries | What | Targets written |
| --- | --- | --- |
| 2782–3424 | depth / linear-depth prepass (`778EA6BE`, `2DF8EB45`) | `T2787` R32F linear depth, `T2788` D24S8 depth |
| 3425–3426 | depth copies | `T3632` D24S8, `T3633` R32F |
| 3427–3428 | screen-tile compute from linear depth (light/cluster style) | buffers 10.4 MB, 158.5 MB |
| 4618 | full-screen pass (`0EFDB3BC`), then read ~980× by scene draws | `T3835` RGBA8 mask |
| 4621–4626 | HDR target + half-res depth + half-res R8 pair (blur) + native R8 upsample (AO-like) | `T3841`, `T3844`, `T3846`, `T3848`, `T3850` |
| 4627–4647 | background/sky-style passes | `T2773` + `T2774` D24S8, `T3902`, `T3904` |
| 4648–5791 | **main scene** (~1360 draws) | `T2772` scene R11G11B10F, depth `T2788` |
| 5456–5457 | full-screen passes | `T4825`, `T3841` |
| 5461–5585 | **half-res transparency/particles** (`6EBC42FB`, ~130 draws) | `T4826` RGBA8 + `T4827` D24S8 (1720×720) |
| 5586–5590 | composite half-res result into scene; scene copy; quarter-res downsample | `T2772`, `T2781`, `T4946` (860×360) |
| 5591–5791 | further transparent draws reading the scene copy | `T2772` |
| 5628 | scene copy | `T2781` |
| 5793–5798 | **AA mod**: motion/depth CS, bridge copies, copy-back | mod targets, then `T2772` |

## Global texture block (important)

Every post-AA draw (bloom, blur, tone-map, all ~52 HUD draws, final present pass),
and most scene passes, have the same textures in PS SRV slots 4–14: `T3841` (HDR
target), `T2781` (scene copy), `T2787` (linear depth, slots 11 and 13), plus fixed
small textures. This looks like an engine-wide binding left in place. The dump
records bound slots, not slots each shader actually samples.

**Open item:** check whether the post-AA shaders sample those slots, and whether by
UV (works at any resolution) or by pixel coordinates (would break at render res).
That needs the shaders' resource declarations. Options: the mod's `DumpShaders`
option in one more INI-only capture, or reverse-engineering the mod's shader-hash
function and matching DXBC found in the game's data offline.

## Implications for a render-scale patch

- **Post side (mod patch):** native FSR output + SRV redirect at the two scene
  readers (`68495C5B`, `2C76D68A`) instead of the equal-size copy-back. HUD and
  final pass are already native.
- **Scene side (game):** the 14 native + 5 half + 1 quarter targets, the tile
  buffers, and the native/half viewports must all move to render resolution
  together. The depth copies and the scene copy must match their sources.
  Fixed-size shadow/env/LUT resources stay untouched.
- Camera W/H, jitter and both motion-vector grids must follow render resolution
  (see `ROUTING_RESULTS.md`, `MOTION_VECTOR_RESULTS.md`).
- The mod's own character-motion target has no recorded writer (the mod's replay
  draws bypass its dump), so its size must come from the mod's code.

## Missing

- Shader slot usage of post-AA passes (above).
- Which game code chooses these sizes: if all derive from one internal resolution
  value, patching that value may scale the whole scene domain at once. That is a
  question for REA on the game executable, not the mod.
