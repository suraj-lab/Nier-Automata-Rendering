# In-game frame dump: post-AA handoff — 2026-10-19

## Capture

Two frames dumped by the installed AA mod's own F10 frame dump (`NIER_DLAA.ini`
`[Debug] Enabled=1`, backed up, restored afterwards and hash-verified). No DLL swap.
Game at 3440×1440, FSR4.1.1 native AA active, Motion Blur on.

| Dump | Passes | Resources | Deferred lists |
| --- | --- | --- | --- |
| `framedump-capture/NIER_DLAA_frame_20261019_224309_810.txt` | 5876 | 5277 | 0 (none unrecorded) |
| `framedump-capture/NIER_DLAA_frame_20261019_224339_508.txt` | 4472 | 4266 | 0 (none unrecorded) |

The mod logs for that session are copied alongside. `T#` ids are per-dump.

## Result: the post-AA handoff is clean

In both frames, after the mod's AA copy-back into the scene texture (3440×1440
R11G11B10F), **exactly two passes read the scene**, both reading it at PS SRV
slot 0, and **nothing writes to it again**:

| Shader | Role | Viewport | Output |
| --- | --- | --- | --- |
| `68495C5BDCDE8322` | bloom downsample | 1720×720 | half-res chain → 430×179 bloom |
| `2C76D68A52500A65` | tone-map / composite (+bloom, +256×16 LUT) | 3440×1440 | native R11G11B10F |

These are the same two hashes the mod's AA gate keys on: the mod runs FSR right
before the first of them.

Everything after reads only native intermediates, not the scene:

```
AA copy-back → scene
  bloom downsample (68495C5B) → 1720×720 → 860×360 → 430×179 → … → bloom
  auto-exposure compute (100×56 → buffers)
  tone-map (2C76D68A): scene + bloom + LUT → native T_tonemap
  compute (F8E91DBD): T_tonemap → native T_ui
  HUD/UI draws (A1B77252, ~50 draws) → T_ui (+ an RGBA8 UI layer)
  final (7A49D93C): T_ui → 3440×1440 RGBA8 swap chain
```

Dump 1 annotated: `#5793` motion/depth CS, `#5794–5797` bridge copies, `#5798`
`CopyResource` copy-back, `#5800` bloom, `#5820` tone-map, `#5822–5874` HUD,
`#5875` final present target.

## What this means for render-scale upscaling

**The earlier blocker has a concrete solution.** The mod's
`CopyResource(scene, Output)` needs equal sizes, but the scene has only two
downstream readers, both at slot 0 and identified by shader hash. Instead of
copying native FSR output back into a smaller scene, those two draws can read the
native output directly: substitute its SRV at slot 0. They would then see a
3440×1440 texture exactly as they do today, so their shaders and viewports need no
change. The HUD and everything after already work on native-size targets, so they
stay native for free.

**The remaining hard part is the scene domain itself**, i.e. everything before AA:

- ~950–1100 scene draws per frame write the scene at a 3440×1440 viewport;
- depth and linear depth (R32F) and the depth-stencil are native-sized;
- pre-AA scene readers: shader `1F57D637A2FA4C4B` (reads the scene into another
  3440×1440 R11G11B10F target) and scene `CopySubresourceRegion` copies;
  these would have to move to render resolution together;
- camera W/H come from the swap chain (native), and drive the AA gate, projection
  jitter and NGX jitter scale (see `ROUTING_RESULTS.md`);
- the camera motion CS and character-motion replay must use matching render-res
  grids (see `MOTION_VECTOR_RESULTS.md`).

## Practical options (not decided)

1. **Patch or extend the closed mod**: native-size Output allocation, unequal
   NGX create, SRV redirect instead of copy-back. Hard: closed binary.
2. **Open replacement for the mod's AA path** in our own proxy: we already have
   the open FSR4 bridge, the extracted motion shaders with verified units, and the
   camera/jitter RE. Larger, but fully controllable and testable offline.
3. **Scene-domain scaling** is needed by either option and is the riskiest piece.
   The next evidence step is a dump-driven inventory of every native-sized
   resource and viewport written before the copy-back.

No implementation was started. No quality or performance claims yet.
