# live-coverage: what Remix's own camera says should be on screen

Run: `live-coverage`, DLL `270f2d9a…`, 150 s, laptop, save loaded by hand. Original restored and hash-verified
(`6ba266d6…`), game alive, no crash.

New instrument: every submitted instance's mesh is projected with **the same camera basis we hand SetupCamera**
(position/forward/up/right/fovY/aspect -> `visibility_math::camera_from`), so "should be visible" is measured in the
runtime's own frame rather than ours. Coverage comes from the mesh's transformed 8-corner AABB; the fraction is a screen
box, so it **over**-estimates the pixels a shape covers.

Per window (22 windows, one line each in the log):

| field | meaning | observed |
|---|---|---|
| `inst` | instances submitted | 53 – 42,086 |
| `infrustum` | at least one corner in front and inside the frame | 60 – 77 % |
| `behind` | all corners behind the camera | 20 – 26 % |
| `offscreen` | in front but entirely outside the frame | **0 in every window** |
| `big` | fraction > 5 % of the frame | 2,481 – 8,761 |
| `best` | largest single-instance fraction | 0.893 – **1.000** |

## What this establishes

1. **Nothing is submitted off-screen.** `offscreen = 0` across all 22 windows: the capture->submit path is not handing
   Remix frustum-rejected geometry, so "the world is missing because we put it in the wrong place" is out.
2. **Geometry that should fill the frame is present.** `best = 1.000` in most windows, i.e. at least one instance's
   projected box covers the whole frame, and thousands of instances exceed 5 % each window.
3. Therefore the loss is **after** the instance is accepted: material state (alpha test discarding every texel), or the
   runtime's own handling of that instance.

The `best` key changes window to window (`528e9dd7ad618b7c` flags=0, `5c90456fffd6719` flags=0, `4da99…` flags=1),
including non-sky instances at fraction 1.000 — consistent with large floors/walls, and the reason a per-key check is
the next step rather than a global conclusion.

## Limits, stated so they are not over-read

- The fraction is an **AABB** screen box, not rasterised coverage: a diagonal wall over-estimates.
- Skinned meshes get **bind-pose** bounds, so their coverage numbers are unreliable; the counters do not separate them.
  A per-material breakdown (alpha state, texture presence) is what would make "should be visible" mean "should be a
  visible surface".

## Next

The one renderer-side variable we can flip without new code is `NIER_REMIX_LIVE_NO_ALPHA_TEST=1`. Materials currently
receive a parsed `alphaTestType`/`alphaReferenceValue` from the pixel shader's discard; an over-strict parse keeps
nothing and the object vanishes while every counter says drawn. That A/B is one run and it decides the branch.
