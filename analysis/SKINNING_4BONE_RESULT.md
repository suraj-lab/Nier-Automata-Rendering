# Exact 4-bone GPU skinning works on the shipped runtime (verified on the laptop, 2026-10-30 23:57)

Probe `remix-mesh.exe` `f5d2c6d0ecb2975c8030f90553c9e8f26854165b8f4326e9d4c4f0bcf57c0979`, built by
`python3 analysis/remix-probe/build.py --mesh analysis/runtime/remix-probe/skin-stride-repro/captured_mesh.h`,
run twice on `spaghetti` through `python3 analysis/remix-probe/run_remote.py <label> --mesh --env ...` against
the shipped RTX Remix 1.6.1 x64 runtime at
`C:\Program Files\NVIDIA Corporation\RTX Remix\deps\remix_runtime\runtime\.trex\d3d9.dll`.
Both runs rendered one frame (`rtxImagePostTonemapping_*.dds`, 512x512) and were stopped by the 90 s watchdog
as designed; the mesh is the real captured NieR submesh with its real palette (`captured_mesh.h`).

## Result

| variant | how | silhouette IoU vs reference | notes |
|---|---|---|---|
| `REPROBE_CPU_SKINNING=1` | reference: four weights baked on the CPU, no skinning info sent | 1.000 (reference) | 117779 px above 0.02 |
| `REPROBE_SPREAD=1` | four bones on the GPU, real vertices at slots 3i | **1.000** | mean abs diff 0.0000, p99 0.0000, **max 0.0039 (1/255)** |
| `REPROBE_BONES2=1` (earlier) | two bones, top-2 renormalised | 0.982 | approximation, visible difference |
| dense 4-bone (earlier) | what the API does by default | 0.763 | torn |

Images: `media/2026-10-30/laptop-skin-cpu-ref-4bone.png`, `media/2026-10-30/laptop-skin-spread-4bone.png`
(rendered from the DDS captures with `analysis/remix-probe/dds_stack.py`).

## What this settles

The shipped 1.6.1 A64EC runtime reads weights at the same 1-float stride as `dxvk-remix` `main`, and the
three-slot layout described in `UPSTREAM_SKINNING_STRIDE.md` reproduces four-weight CPU skinning to the last
8-bit step. Phase 4 can therefore keep one mesh per skinned object in bind space and send only
`remixapi_InstanceInfoBoneTransformsEXT` per frame, with no runtime fork.

## Limits

One static pose of one captured submesh, one runtime version, one machine. It proves the weight and index
layout and the derived fourth weight. It does not prove per-frame bone updates (BLAS refit cost), nor
that every shader in the game decomposes the same way. The live A/B is still required.

## How to reproduce

    python3 analysis/remix-probe/build.py --mesh analysis/runtime/remix-probe/skin-stride-repro/captured_mesh.h
    python3 analysis/remix-probe/run_remote.py skin-cpu-ref-4bone --mesh --env REPROBE_CPU_SKINNING=1
    python3 analysis/remix-probe/run_remote.py skin-spread-4bone --mesh --env REPROBE_SPREAD=1
    # then, for each captures-skin-*-4bone-*/ directory:
    python3 analysis/remix-probe/dds_stack.py out.png <captures dir>/rtxImagePostTonemapping_*.dds

Offline gate that pins the sources this rests on: `analysis/checks/test_three_slot_skin_layout.py`.
