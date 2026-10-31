# Exact 4-bone GPU skinning on the stock Remix runtime (no fork needed)

Measured 2026-10-30 against `NVIDIAGameWorks/dxvk-remix` @ `main`, files fetched and read locally
(`rtx_remix_api.cpp`, `src/dxvk/shaders/rtx/pass/skinning.h`, `gpu_skinning.comp.slang`,
`rtx_geometry_utils.cpp`, `public/include/remix/remix_c.h`).

## The bug, precisely

`rtx_remix_api.cpp` (createMesh, ~line 1021):

    dst.blendWeightBuffer  = { blendWeightsSlice, 0, sizeof(float), R32_SFLOAT };   // stride 4 bytes
    dst.blendIndicesBuffer = { blendIndicesSlice, 0, sizeof(uint32_t), R8G8B8A8_USCALED };

`rtx_geometry_utils.cpp` copies those strides straight into the skinning params
(`blendWeightStride = blendWeightBuffer.stride()`), and `skinning.h` reads

    const uint baseWeightsOffset = (cb.blendWeightOffset + idx * cb.blendWeightStride) / 4;
    ... blendWeight = srcBlendWeight[baseWeightsOffset + i + j];

so vertex `idx` always starts at weight float `idx`, whatever `bonesPerVertex` says. With 4 bones the
weights of neighbouring vertices overlap, which is the tearing we measured (IoU 0.763). With 2 bones
the stride happens to be right for the first weight and the second is derived, which is why 2-bone
works (IoU 0.982).

## Why the obvious workaround does not work

Spacing the *weight array* three floats apart does nothing: `blendWeightStride` is hardcoded to
`sizeof(float)` in `rtx_remix_api.cpp`, so vertex `i` always starts at weight float `i`. Verified by
compiling the pinned shader: with a dense 3-stride weight array the result still tears.

## What does work: keep real vertices three slots apart

Because vertex `i` reads `weights[i], weights[i+1], weights[i+2]` and derives the fourth, a vertex is
exact when it owns three consecutive slots:

* build the vertex array with 3x the vertices, the real vertex `i` at slot `3i` (its two neighbours
  `3i+1, 3i+2` are never referenced);
* weights at `3i, 3i+1, 3i+2` are `w0, w1, w2` of vertex `i`, and `blendWeights_count = 3V + 4`: the padding
  slots are skinned too, and the last one reads up to index `3V+1`, so a bare `3V` reads past the end;
* one packed `uint32` per slot (four uint8 bone indices) — the index stride of 4 bytes is already right,
  `wordsPerTuple = ceil(4/4) = 1`;
* remap the index buffer: drawn index `j` becomes `3 * j`.

NieR's weights are byte-quantised and sum to exactly 255/255 per vertex (142 of 142 skinned main-view
draws measured), so the derived fourth weight is exact to the 1/255 quantisation.

Cost: three times the vertex buffer memory (and the BLAS is built over all three slots) for skinned
meshes, and a 3x vertex count in the mesh info. Triangle count is unchanged.

## Measured

`analysis/checks/test_three_slot_skin_layout.py` compiles the pinned `skinning.h` as C++ with shim GLSL
types and runs it with the runtime's own strides on the real weight/index tuples of three captured
draws (2095, 220, 135 vertices):

| layout | worst error vs our four-weight bake |
|---|---|
| three slots per real vertex | 0.000004, 0.000000, 0.000000 |
| dense, as the API calls it today | 100.03, 12.90, 14.94 |

The gate also hashes the pinned upstream headers and requires the mutation (spread -> dense) to fail.

## Why no validation blocks it

`blendWeights_count` is used in exactly one place, `sizeInBytes(...)` for the copy
(`rtx_remix_api.cpp:983`); `blendIndices_count` is not read at all; `dst.vertexCount` comes from
`vertices_count`. No code compares the counts with `vertexCount * bonesPerVertex` in
`rtx_remix_api.cpp`, `rtx_geometry_utils.*`, `rtx_asset_replacer.*` or `remix_c.h`.

## Consequence for Phase 4

One stable mesh per skinned draw (bind space, 4 bones, three-slot vertices) plus per-frame
`remixapi_InstanceInfoBoneTransformsEXT` replaces the per-pose CPU bake for the 77% of skinned world
geometry that is genuinely blended. That removes the pose rebuild churn (82% of all rebuilds) and the
frame-to-frame colour flicker that comes from re-creating meshes every frame.

Settled on the laptop, 2026-10-30: the shipped 1.6.1 A64EC runtime matches `main`. Probe `f5d2c6d0…` with
`REPROBE_SPREAD=1` reproduces the four-weight CPU reference to **IoU 1.000 and max 1/255 per pixel**
(`SKINNING_4BONE_RESULT.md`).
