# frametime1: live follow-up to the offline frame-time changes

## Build and run

- DLL SHA-256: `8b0f167225e480c3b5a4f769f73b78ede1cb9a56ec76821b0d809a3f3d5f14b2`.
  Gate receipt: 77/77, source hashes unchanged at installation.
- Includes SSE2 frame conversion (`frame-copy.md`) and shared metallic/roughness mask readback (`shared-mask.md`).
- Label `frametime1`, 330 seconds, runtime `upstream-1.6.1-x64\d3d9_a64ec.dll`,
  config `analysis/deploy/rtx/laptop-b-dlss-perf.conf`. Same flags as `pbr-verify1`:
  `NIER_REMIX_SIZE=2880x1800`, `NIER_REMIX_LIVE_TEX_PER_FRAME=16`, normal/GPU skin/async buffer reads on,
  build budget 4000 us, live budget 3072, `NIER_REMIX_LIVE_MIN_INDICES=3`, no ec_hooks.
- AC power confirmed before launch; start/end battery status 2 with Performance power plan, charge 73% -> 75%.
- Game alive at scheduled end; no crash dump reported. Restore completed and verified original `d3d11.dll`
  SHA-256 `6ba266d64a8f67767700c535ee0c3c0596cf50280cf3e301e68518d8e3418b5a`.
- Receipt: `analysis/runtime/laptop-port/frametime1-20261101T203530Z.json`.
  Runtime log has the same prefix and `-remix-dxvk.log` suffix (ignored local artifacts).

## Timing

The stage values are medians of reporting-window averages, not per-frame percentiles. Pair each FPS line with its
following `live draws` line and select reports with at least 100 instances. This excludes menu-only reports but
can still include a window spanning a loading transition. FPS measures completed Remix worker frames, not the
game's Present rate or any frame-generated output.

| run | power | selected windows | Remix FPS | update | submit | readback | convert | other |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pbr-look1 | AC / Performance | 33 | 13.1 | 1.7 ms | 1.1 ms | 57.9 ms | 11.0 ms | 3.3 ms |
| pbr-verify1 | battery / Standard | 32 | 8.0 | 3.5 ms | 2.75 ms | 97.15 ms | 12.1 ms | 6.1 ms |
| frametime1 | AC / Performance | 55 | 13.1 | 2.7 ms | 2.4 ms | 58.4 ms | 3.5 ms | 5.6 ms |

Conversion falls from 11.0 to 3.5 ms compared with the earlier AC run (about 3.1x faster for that stage). The scenes,
material implementation and draw threshold differ, so this is not a matched A/B of overall FPS. The 8 -> 13 FPS
change from the last battery run also includes a power-plan change; do not attribute it to code alone. Shared-mask
readback's isolated live benefit has not been measured. The readback stage still includes waiting for GPU rendering.

User feedback: "Frame time seems a lot better, now any fps slowdown seems related to lod and textures. As you can
see textures is still an issue." Treat LOD/texture attribution as a hypothesis to check, not an established cause.

Late report samples:

- 20:41:01: 8.8 FPS; update 11.9 ms, readback 54.4 ms, convert 3.6 ms, other 41.3 ms.
- 20:41:08: 9.0 FPS; update 7.0 ms, readback 57.6 ms, convert 5.2 ms, other 38.1 ms.
- Final live-scene totals: 226,924 cumulative mesh builds; 12,702 resident meshes; 2,476,290,488 accounted mesh bytes;
  1,723 texture outputs. These counts justify examining rebuild/streaming cost, but do not by themselves identify
  LOD as the cause. Accounted mesh bytes are not a measurement of actual GPU memory residency.

## Recording and remaining visual problems

Copied the user's recording `NieR Automata 2026.11.01 - 20.37.16.16.mp4` (234.11 seconds, 1,710,238,323 bytes) to
`analysis/runtime/laptop-port/frametime1/frametime1.mp4`; four contact sheets sit beside it. Recordings/captures stay
out of Git. Viewed sheets 0 and 2: camp surface detail/flowers are present, but green 2B at the access point,
blue character/pod surfaces, large pale sheets and smooth-looking dunes/chrome-like distant terrain persist.
No frame-by-frame LOD/texture-event attribution has been completed.

## Resume here

1. Align recording time zero with 20:37:16 and inspect slow-window texture-time deltas, rebuild reasons and worker
   stage times. Separate texture capture/upload, mesh churn and runtime rendering cost before changing LOD policy.
2. Replace the low draw-size threshold with an evidence-backed foliage/overlay distinction. Accepted small draws
   need diagnostics too; the existing `small` lines describe only rejected draws. Keep grass/flowers in the gate.
3. Fix terrain shader inputs and layer handling; attribute the chrome appearance before changing PBR values.
4. Keep remaining asynchronous texture reads and direct presentation as scoped follow-ups. A direct presenter
   cannot remove path-tracing time merely because that time appears under `readback` now.

Session paused at the user's request. No more launches or implementation changes after this checkpoint without
resuming the task; future laptop runs still need approval.
