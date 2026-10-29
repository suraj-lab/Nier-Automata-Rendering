# Live scene: per-frame draw stream into Remix

Goal: the Remix scene follows the game instead of showing one captured frame. Opt-in, default off,
camera path and F9 capture unchanged.

## Verified facts (real capture `frame_9443695`, 2995 draws)

| Fact | Value |
|---|---|
| index buffers | 2989 R32_UINT, 6 R16_UINT, always indexed |
| `base_vertex` | always 0 |
| `start_index` | usually non-zero -> honour IB offset + start index |
| vertex buffers | 2-4 bound slots; slot 0 stride 28, slot 1 stride 8/12/16/20, slots 2-3 rare |
| layouts | 23 distinct; POSITION is always R32G32B32 at offset 0 |
| instanced draws | 51 (`DrawIndexedInstanced`, 2-28 instances) |
| skinned draws | 568 carry BLENDINDICES(R8G8B8A8_UINT) + BLENDWEIGHT(R8G8B8A8_UNORM) |
| CB11 | bound for every draw; 3x4 row-major world matrix per instance at 64-byte stride, or a 48-byte-stride bone palette when the draw is skinned |
| index count | every draw >= 128 |

Camera (VS CB0) is already live; see `camera_capture.h`.

## Why readback cannot be per draw per frame

2995 draws x one CB readback per frame is ~300 ms of GPU round trips. Constant/vertex/index data that
the game writes must be shadowed on the CPU instead:

- hook `Map`/`Unmap`, `UpdateSubresource`, `CopySubresourceRegion`, `CopyResource` on the selected
  immediate context; keep a bounded CPU copy per buffer, written by the game itself.
- `DEFAULT`/`IMMUTABLE` buffers with no shadow: read once, cache forever, keyed by the buffer pointer.
- A draw is described only from shadows and caches; nothing is read back per frame.

## Interface (frozen for the worker)

Game thread (`live_capture.h`), called from the existing DrawIndexed/DrawIndexedInstanced hooks while
the Remix host is `Waiting`/`Running` and capture permission is granted (same gate as the camera):

```
struct MeshKey {                 // identity of the geometry bytes in the game's buffers
    const void* vb[4]; std::uint32_t vb_offset[4]; std::uint32_t stride[4]; unsigned vb_count;
    const void* ib; std::uint32_t ib_offset; int ib_format;
    std::uint32_t index_count, start_index; std::int32_t base_vertex;
    std::uint64_t layout_hash;  bool skinned;
};
struct Instance { float world[12]; };          // 3x4 row-major from CB11
struct DrawItem { MeshKey key; std::uint32_t material; unsigned first_instance, instance_count; };
struct MeshData { MeshKey key; std::vector<remixapi_HardcodedVertex> vertices; };  // 3 per triangle
struct Frame {
    std::vector<MeshData> new_meshes;      // only keys the worker has not built yet
    std::vector<std::wstring> new_textures;// DDS paths written this frame (dedup by resource)
    std::vector<DrawItem> draws;
    std::vector<Instance> instances;       // DrawItem indexes into this
};
```

Worker side (in `remix_live.cpp`, owns every Remix handle): map `MeshKey -> MeshHandle`,
`std::wstring -> MaterialHandle`; per frame create the meshes/materials in `new_*`, then
`SetupCamera` + one `DrawInstance` per instance with `transform = Instance.world` expanded to 4x4.
Evict least-recently-used meshes above a byte budget.

## v1 scope, deliberate limits

- Skinned draws are supported: bind-pose indexed mesh + `MeshInfoSurfaceTriangles.skinning_value`
  (4 bones/vertex) and the CB11 palette per instance through `InstanceInfoBoneTransformsEXT`. A weighted
  bone index outside the palette rejects the draw (real captures contain such data).
- Instance matrices are the only transform: `remixapi_Transform` is `float matrix[3][4]` (verified in
  `remix-probe/vendor/remix_c.h:200-202`), so NieR's 3x4 row-major CB11 world matrix is copied element
  for element -- translation stays in `matrix[row][3]`, and there is NO fourth row to fill. If the live
  world turns out mirrored/rotated the 3x3 needs a transpose; that is the only open convention question.
- No index buffers in Remix: geometry is expanded to 3 vertices per triangle, as the offline converter
  already proves.
- Textures: mip 0 of each new PS material texture written once as DDS (existing `texture_capture`),
  material created once per path.

## Superseded: expansion is too expensive

The first draft followed the offline converter and expanded each triangle into 3 vertices, because the
static scene bakes world transforms into positions. A live mesh must NOT bake: the instance transform
carries the world matrix, so the draw's own index list is kept and only the referenced vertices are
uploaded (remapped indices). Measured on the real capture: 9.25M triangles per frame, ~1.27 GB if
expanded, ~3x smaller and cheaper to build when indexed.

## Gate

`analysis/checks/test_live_geometry.py` (same Wine/Xvfb/fake-Runtime harness as the camera gate):
static + dynamic buffers, a mesh that appears mid-run, one texture, moving CB11 world matrices.
It asserts: bounded readbacks that do not grow with frames, one mesh per geometry key (two after the
late mesh appears), per-frame `DrawInstance` transforms that follow CB11, exactly one DDS, live camera
still arriving, and Remix-off/F9 behaviour unchanged.
