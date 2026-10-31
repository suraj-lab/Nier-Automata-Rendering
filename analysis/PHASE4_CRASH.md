# Phase 4 first live run crashed: pre-packed bone indices (2026-10-31)

**Run** `live-gpu-skin` (build `caa4ab5d`, `NIER_REMIX_LIVE_GPU_SKIN=1`, laptop, 1.6.1 A64EC). The game died about
10 s after the world loaded (12:39:06 shadow budget, last line 12:39:14), before the first Remix frame. No WER
event and no Windows dump: the runtime's Sentry handler takes the crash, and `restore` then deleted
`data\rtx-remix` with the minidump in it (fixed: `KEEP` now holds the whole `.sentry-native` folder).

**Cause, from the source of the exact runtime** (`remix-1.6.1` `rtx_remix_api.cpp:961-976`): `CreateMesh` reads
`vertices_count * bonesPerVertex` **unpacked** `uint32` indices and packs them into bytes itself. We passed one
pre-packed word per slot (3V words), so it read 12V words: a 9V-word host over-read. The mock never read the
arrays, so the gate passed. The docs (`UPSTREAM_SKINNING_STRIDE.md`, `PHASE4_PLAN.md`) carried the same error,
taken from the GPU-side buffer layout instead of the API's input.

**Why the earlier hardware probe "passed"**: it passed the same packed words. Its IoU 1.000 says that mesh did not
depend on which bones were picked. `SKINNING_4BONE_RESULT.md` now carries a correction banner.

**Fix** (`three_slot_layout`): four unpacked indices per slot, `blendIndices_count = 12V`, indices > 255 refused
(the runtime packs each into one byte).

**Gate** (`remix_live_fake_runtime.cpp`): the fake now enforces the real read extents. `VIOLATION` if
`blendIndices_count < vertices * bonesPerVertex`, if `blendWeights_count < vertices + bonesPerVertex - 2`, or if an
index exceeds 255. Red on `caa4ab5d`'s layout (`blendIndices_count=195 < 780`, "index 256"), green after the fix.

**Hardware re-probe** (laptop, shipped 1.6.1 x64 `.trex\d3d9.dll`, probe `remix-mesh.exe` `f67e5395…`, built by
`runtime/remix-probe/skin-stride-repro/build_probe.py`), real captured NieR submesh and palette, vs the CPU bake:

| variant | IoU | px differing > 0.02 | max |
|---|---|---|---|
| `REPROBE_SPREAD=1`, unpacked indices | 0.992 | 2 | 0.031 |
| control `REPROBE_SPREAD_ROTATE=1` (bones rotated against weights) | 0.912 | 500 | 0.105 |

The control proves this probe can now see a wrong index layout; the fixed layout matches the reference.
Receipts: `runtime/remix-probe/windows-skin-{cpu-ref,spread,spread-rot}-v2-20261031T12*.json`.

Lesson: a fake runtime that does not read what the real one reads cannot gate a layout. Model the read extents.
