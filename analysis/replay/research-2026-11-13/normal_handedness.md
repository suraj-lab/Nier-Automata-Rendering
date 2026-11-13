# Normal-map handedness: what the game does and what Remix does (2026-11-13)

Answers L2 step 1 and 2 of `analysis/PLAN_2026-11-13.md` from the game's own bytecode and from remix-1.6.1's source.
Both halves were read here; nothing below is a scout claim.

## 1. The game's main lit family

Shader `ps_550290354696` (`runtime/pbr-re/meta`, roles `albedo=0.xyz metal=2.x gloss=2.y~ normal=3.xyz detail=4.xy`),
D3DDisassemble text, instruction by instruction:

| line | instruction | meaning |
|---|---|---|
| 39 | `sample_indexable(texture2d) r0.yzw, r1.xyxx, t3.wxyz, s3` | the normal map is t3 |
| 42 | `add r0.xyz, r0.yzwy, l(-0.5,-0.5,-0.5,0)` | decode `sample - 0.5`, so `r0.xyz` is the tangent-space (x, y, z) |
| 53 | `mul r0.x, r0.x, v4.w` | the vertex tangent's handedness `w` is folded into **x**, not into y |
| 54-55 | `mul r3.xyz, v3.yzxy, v4.zxyz` / `mad r3.xyz, v4.yzxy, v3.zxyz, -r3.xyzx` | `r3 = cross(v4, v3) = T x N` |
| 56 | `mul r6.xyz, -r0.y, r3.xyzx` | the y term is `-y * (T x N) = y * (N x T)` |
| 57 | `mad r0.xyw, r0.x, v4.xyxz, r6.xyxz` | `x * T  +  y * (N x T)` |
| 58 | `mad r0.xyz, r0.z, v3.xyzx, r0.xywx` | `+ z * N` |
| 53-55 again | dp3 / rsq / mul | normalise |

`v2` is the world position (`add r6.xyz, -v2.xyzx, cb5[0].xyzx` builds view-minus-position), `v3` the interpolated
normal, `v4` the vertex tangent (`xyz`) with its handedness in `w`. The same five instructions appear in
`ps_550292531976.asm:56-58` and `ps_550292544968.asm:73-75` (register numbers differ, the swizzles that carry the
tangent and the normal differ per family, the signs do not), so this is the family convention, not one shader's.

In words: **red runs along the vertex tangent, green runs along `N x T`, blue is the shading normal, and the vertex
tangent's handedness multiplies red.** The game flips red on a mesh whose UV layout is left-handed. Green is never
negated.

## 2. What Remix does with the same texture

| fact | where |
|---|---|
| the material normal texture is decoded as **unsigned octahedral**, hemisphere form (no lower-quadrant fold) | `opaque_surface_material_interaction.slangh:788` -> `packing.slangh:357-362` -> `:324` |
| `t = (p.x+p.y, p.x-p.y) * 0.5`, `v = (t.x, t.y, 1-\|t.x\|-\|t.y\|)`, normalised | `packing.slangh:326-330` |
| the tangent frame is built from the triangle's **UV derivatives**: `rawTangent = dP/du`, `rawBitangent = dP/dv` | `math.slangh:415-447` |
| `B = signNotZero(dot(cross(N,T), dP/dv)) * cross(N,T)`, so **B always points along +dP/dv** and the frame may be left-handed | `math.slangh:487-497` |
| `tangentNormal` is transformed by `transpose(worldToTangent)` with that frame | `opaque_surface_material_interaction.slangh:791-793` |

So Remix: **red along +dP/du, green along +dP/dv, blue along the interpolated normal.**

Our encoder is the exact inverse of that decode (`checks/normal_octahedral.h:64-77`): verified byte-for-byte in
`checks/test_normal_octahedral.py`, whose new orientation block asserts green -> `+y` and `FLIP_Y` -> `-y`.

## 3. The answer, and why it is not a single bit

Write `w' = sign(dot(N x T, dP/dv))` for a mesh. The game's frame is `(w'*T, N x T, N)`; Remix's is
`(dP/du, dP/dv, N)` = `(T, w'*(N x T), N)`. Expressed in the same basis the game's normal `(x, y, z)` is Remix's
`(w'*x, w'*y, z)`:

- **`w' = +1`** (right-handed UV layout, the ordinary case): the two agree exactly. **No flip.**
- **`w' = -1`**: the game mirrors **both** red and green relative to Remix. `NIER_REMIX_LIVE_NORMAL_FLIP_Y` alone
  is not that transformation and would be wrong; the right per-mesh correction is a negation of x and y, which the
  capture does not let us compute (no vertex tangent, no vertex shader bytecode: `PLAN_2026-11-13.md` 11.8).

Consequence for L2: the default must be **no flip**, with `NIER_REMIX_LIVE_NORMAL_FLIP_Y=1` kept as the A/B switch.
The residual risk, recorded rather than guessed: meshes whose UV layout is left-handed get inverted relief in both
axes. It cannot be measured from a capture; a truth picture from the game (`G4`) at a surface with lettering is the
only way to see it, and the A/B sheet (`n1-normal-30632051` against `n1-normalflip-30632051`) is what the user picks
from in the meantime.

## 4. Detail normal (slot 4)

`live_capture.h:1676` takes the normal map **only** from `roles.normal.slot`; the tracer's `normal` role is the map
that the shader subtracts `0.5` from (`ps_550290354696.asm:42`) and `detail_normal` is the map it scales by `2` and
biases by `-1` on two lanes (`:45-48`), a separate role that no code path reads as the main normal. So the
"blotchy, wet-looking" slot-4 experiment cannot come back through the default path.
