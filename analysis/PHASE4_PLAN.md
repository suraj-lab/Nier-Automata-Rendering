# Phase 4: one skinned mesh per object, bone transforms per frame

Everything below rests on two measurements from 2026-10-30:

* 77% of skinned main-view draws are genuinely blended (110 of 142 in an F9 capture); 29% of their
  vertices use four bone influences, and weights sum to exactly 255/255 (`PROGRESS.md`, 142-draw census).
* Four bones per vertex via the API are exact in the three-slot layout on the shipped runtime: probe
  `f5d2c6d0` gave silhouette IoU 1.000 and max 1/255 per pixel against the CPU bake
  (`SKINNING_4BONE_RESULT.md`, `UPSTREAM_SKINNING_STRIDE.md`).

## What changes in `analysis/checks/live_capture.h`

Today, for a skinned draw:

* the key is the draw hashed with its occurrence index, plus a `pose` hash of the bone palette, so every
  animation pose is a new geometry and rebuilds the mesh (`kReasonPose`; 29,900 rebuilds in 180 s, 82% of
  all rebuilds);
* `live_skinning::bake` writes world-space positions into the vertex buffer, so the mesh on the GPU is only
  valid for that pose;
* the instance transform is identity and the bone palette never reaches Remix.

After the change, for a skinned draw that cannot be served rigid (the existing `rigid_bones()` path keeps
the single-bone draws):

1. Key on geometry only: `geometry` stays the draw hash, `pose` is not folded in, and `skin_base` is reused
   so the occurrence index does not leak in.
2. Build the mesh once, in bind space, with three slots per real vertex:
   * `vertices.resize(3 * V)`, real vertex `i` at slot `3i`, the other two slots dummies that no index
     references; positions and normals as captured, weights cleared (`skinning_hasvalue` carries the data);
   * `bonesPerVertex = 4`, `blendWeights_count = 3V`, weights `w0,w1,w2` at `3i, 3i+1, 3i+2` (the shader
     derives the fourth);
   * four unpacked `uint32` indices per slot, `blendIndices_count = 12V` (the runtime packs them; corrected 2026-10-31);
   * index buffer remapped `j -> 3j`, index count unchanged.
3. Per frame, send the palette with `remixapi_InstanceInfoBoneTransformsEXT`
   (`boneTransforms_values` = the 48-byte-stride matrices converted to `remixapi_Transform`), one
   `DrawInstance` per object, instance transform identity (or the anchor translation, see below).
4. Never rebuild on a pose change: the geometry hash is unchanged, so `built_versions()` keeps it.

## The three things that will bite

* **Bind-pose bounds.** Remix culls and bounds instances from the mesh, and a bind-space mesh with a
  character's limbs elsewhere will be culled at some camera angles. The reference implementation
  (l4d2-rtx, `analysis/PRIOR_ART.md`; its `src/comp/game/api_skinned.cpp` is quoted in
  `NEW_VEGAS_RTX_NOTES.md`; the repo could not be re-fetched on 2026-10-30, so treat that quote as
  second-hand) keeps the mesh in bind space and sets the instance transform to
  `T(bone0 anchor)`; the instance bounds then follow the actor. Do the same: instance transform =
  translation of bone 0 (rounded to 1/16 unit, as they do, to keep motion history stable).
* **Per-frame BLAS refit cost.** Every animated instance now refits instead of being rebuilt; the runtime
  refits whenever the bone hash changes. l4d2-rtx holds a pose that moved less than 1e-5 linear / 1/256 unit
  and resends the previous bytes, because camera-only movement perturbs camera-relative bones in their low
  bits. Copy that hold, or the whole world refits every frame while standing still.
* **Memory.** Three times the vertex buffer and three times the vertices in the BLAS for skinned meshes.
  Measure the live allocation before and after on the laptop; if it hurts, fall back to two bones
  (`REPROBE_BONES2`, IoU 0.982, one slot per vertex, no duplication) for meshes that pass the 5%-weight-cut
  test (51 of 142 draws qualify).

## Gate to write first (in `analysis/checks/test_live_skinning_capture.py`, mock in Wine)

New case `gpu-bone` with a mock that animates a two-bone-per-vertex mesh (the existing `MOCK_SKIN_SPLIT`
shape does this) and a fake runtime that records `CreateMesh` and `DrawInstance` lines:

* exactly one `CreateMesh` for the whole run (build once, in own space: `v0=0.000`), no `pose` rebuilds;
* every frame sends bone transforms: the log must show a non-empty bone list whose translation follows the
  mock's animation;
* instance transform translations follow bone 0, not the raw palette offset;
* holds: two consecutive frames with a pose delta below the hold threshold send identical bytes (assert
  byte equality, not a flag);
* indices remapped: the fake runtime's index count stays the captured count while `verts = 3 * captured`.

## Order of work

1. Gate first (red), then the writer in `live_capture.h`, mock support (`MOCK_SKIN_SPLIT` already blends).
2. Live A/B on the laptop: `--live` with the change behind `NIER_REMIX_LIVE_GPU_SKIN=1`, same save, compare
   `live rebuilds` (pose should drop to 0), fps, and the picture. Keep the old path selectable until the A/B
   is green twice.
3. Only then remove the CPU bake for non-rigid skinned draws.

## Not in scope

Morph-target faces (`MeshInfoRefreshGeometryEXT` in the reference), superseded by
`RefreshGeometryEXT`; and frame generation, which still needs Remix to own presentation.
