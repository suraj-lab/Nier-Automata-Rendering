# Motion-vector units — offline results, 2026-10-19

## Result

**The retained mod's camera and character-motion producer shaders both use
screen-space pixel displacements**, with previous-minus-current direction under
the intended previous-frame matrix bindings. The bridge copies those values
unchanged and supplies unity scale by default. AMD's FSR 4.1.1 manual independently
specifies current-to-previous screen-space vectors, with motionVectorScale for
alternate units. There is no evidence-based reason to add another blanket W/H
multiplier to the bridge.

This closes the earlier **shader unit/operand-order question**, not game motion
correctness. Actual previous-frame timing, bone/camera data, depth conventions,
coverage, temporal quality and reduced-render/native-output routing remain open.
No game was launched or instrumented; no installed files or source binary changed.

## Binary identity and extraction

Original `input/NIER_DLAA_1.1.dll`, SHA-256:
`f1c77c58fdd265b25dfa262c8660d49a4463a05bb0ee88daf732727f15e717ce`.

Structurally validated five embedded DXBC containers; retained raw bytes, chunk
metadata, file offsets, PE-section VA mappings and SHA-256 hashes in
`offline-motion/shader-manifest.json`. One other DXBC magic occurrence was not a
valid container. Structural bounds/overlap/token-length checks do not claim a
DXBC checksum-algorithm verification.

| Role | File offset / VA | Size | SHA-256 |
| --- | --- | --- | --- |
| Motion/depth compute | `0x508b0` / `0x180051ab0` | 2792 | `95f7aa588e446e02e7ffb935b84ee597de79425eda0f86ef0dab449050bd08aa` |
| Character-motion pixel | `0x52590` / `0x180053790` | 1596 | `2bbc5b25961b0c3f8e9ae2749b5aa68eddd4bbae0d2df83c1b95886d113ac649` |
| Character-motion vertex | `0x52bd0` / `0x180053dd0` | 3572 | `3a5022b43d222f1d8b06fc81106ecf4ae0c74798f935ce800d84de65fa47a44f` |

`checks/disassemble_shader.cpp` calls the SDK's D3DDisassemble in the existing
private workspace Proton prefix. It creates no GPU device and executes no shader.
All five disassemblies are retained under `offline-motion/shaders/`. Helper tests
confirm success, usage/missing-input/malformed-input rejection and no-clobber output
creation. Builds use MinGW C++17 with `-Wall -Wextra -Werror`.

## Camera branch: direct bytecode evidence

`offline-motion/shaders/cs_5_0_0508b0.asm:20-43`:

1. Construct pixel-centre NDC from thread XY and g_Size; subtract g_JitterNdc.
2. Reconstruct view position from depth/projection constants and transform with
   g_ViewToPrevClip; divide previous clip XY by W.
3. Subtract current unjittered NDC from that previous NDC.
4. Multiply by g_Size and `(0.5,-0.5)`; mask camera motion when previous W is invalid.

Thus the output is `(previousNDC-currentNDC)*(W/2,-H/2)`: pixel X right, pixel Y
down. The RDEF names/offsets are independently retained in
`offline-motion/compute-reflection.json`: a 128-byte CB, matrix at 0, projection
at 64, depth pair at 80, linear conversion at 88, jitter at 96, size at 104, debug
selector at 112.

The actual dispatch creates this exact 2792-byte CS at VA `0x180051ab0`, stores it
in `DAT_1800abfb8`, and binds it for dispatch:
`evidence/dlaa-render-dispatch-function.json`, decoded pseudocode 223-241, 461-480,
Evidence `ev_0786e85e94c2c3a424ad0b893af1ab09c2a6595c68c8c922169160cf17524326`.
The earlier `0x180019490` lead proved to be NGX capability initialization, not the
CS creator; its separately retained record is named accordingly.

## Character branch: direct bytecode plus binding evidence

`offline-motion/shaders/ps_5_0_052590.asm:22-30` computes the same pixel conversion
from SV_Position, jitter, target size and interpolated previous clip XY/W. It
writes XY displacement and validity W=1. Earlier instructions reject invalid
previous W and a depth mismatch greater than about 2%; those discards affect
coverage, not displacement units.

The vertex shader emits current projected position and previous skinned/projected
position. Source matrix timing is not established by shader names or static math.

`object-shader-create-function.decoded.c:33-64` creates the exact extracted VS/PS
at `0x180053dd0`/`0x180053790`, lengths `0xdf4`/`0x63c`, storing them in
`DAT_1800ae1c8`/`DAT_1800ae1d0`. The replay routine binds those shaders and its
32-byte jitter/size/linear-depth CB (`object-motion-replay-function.decoded.c:92-100,
130-141`). Its SRV getter supplies the object surface to the compute dispatch.

The CS (`cs_5_0_0508b0.asm:44-47`) copies that texture's XY unchanged when W>0.5;
it otherwise selects camera motion. This is **replacement**, not addition of
camera and object vectors. Exactly W=0.5 selects camera motion.

New static REA records are under `offline-motion/`, with target-bound Evidence IDs:

- Object creator `0x18001d570`: `ev_be2f043bf64ccb10ee10a36964f4099695651c8d1caaa990f4d09f6361fdf9d8`.
- Replay `0x18001cbb0`: `ev_71cc047da4df6dbafd7dd29bf51e5bc5b76b803e12e2b51c9818112af252ff34`.
- Object SRV getter `0x18001d9f0`: `ev_3366aebc97a68f1b94a2e8965f365e1ecbe8ec3e720a8dcf3c95a6745107b1e1`.
- The shader address xref records and NGX capability-init dossier retain their own
  Evidence IDs; the updated snapshot is `offline-motion/NIER_DLAA_motion_snapshot.json`.

## Consumer contract

Primary source: [AMD FSR Upscaling 4.1.1, Providing motion vectors](https://gpuopen.com/manuals/fsr_sdk/techniques/super-resolution-ml/#providing-motion-vectors),
retrieved 2026-10-19. Its Space section specifies motion from the current pixel to
its previous-frame position in screen-space range `[-width,-height]..[width,height]`.
It permits motionVectorScale to convert other spaces. Its input guidance excludes
jitter from vectors unless the cancellation flag is enabled.

Local bridge source `upstream/Nier-FSR4/src/nier_fsr4.cpp:1206-1213,1243-1246`
copies the MV surface, then forwards scale/jitter metadata with config multipliers;
it performs no vector-value normalization. NGX flags 0x43 select render-resolution
MVs, not jitter cancellation. With production defaults their FSR translation is
0x21; the synthetic test's DebugChecking adds 0x80, producing the observed 0xa1.
Bit translation is not a unit conversion.

The read-only source scout's inability to retrieve the primary manual was resolved
by parent retrieval; local SDK comments alone were not treated as unit proof.

## Actual GPU checks of the extracted compute shader

`checks/motion_shader_probe.cpp` executes the **retained bytecode**, not a rewritten
version, on synthetic tiny inputs using the RX 9070 XT and private test prefix.
It supplies the reflected CB layout, linear depth 0.5→view depth 1, known previous
transforms and object data, dispatches 8×8 groups, and reads every output pixel
respecting row pitch. An initial sentinel detects unwritten values.

Ten cases: identity; positive/negative camera displacement; half-size camera pixel
scaling; nonmultiple 20×12 extent; object override at two sizes; exact mask=0.5;
jittered identity; invalid previous W. **All ten pass in R16G16_FLOAT and all ten
pass in diagnostic R32G32_FLOAT.** This does not execute the character pixel
shader's rasterization/depth-rejection path or an FSR history reconstruction.

### Precision calibration, including the retained failure

The initial fixed 0.001-pixel threshold failed the 20×12 R16 case by
0.001953125 pixels. The original executable, log and false validation result are
preserved in `offline-motion/motion-gpu-validation.json` and `logs/motion-gpu/`.
A float32-output diagnostic separated the arithmetic from half storage: final
float32 maximum error is only `3.57627869e-7` there, consistent with the R16
result being one storage ULP away. This does not establish a specific rounding mode.

Final checks use one self-checked binary16 ULP **per expected component** for R16,
and a tighter 1e-5-pixel bound for R32. Other R16 cases have zero observed error.
This is a precision-aware test bound, not an arbitrary global threshold increase.
Full commands, binary/shader hashes, case errors and bounds are retained in
`offline-motion/motion-gpu-checked-validation.json`; preliminary float diagnostic
results are retained separately. Half and ULP decoding have assert-style checks.

## Implication for resolution scaling

Do not scale motion values twice. The camera CS uses scene dimensions while the
object PS uses its replay target dimensions. The merge also uses integer texture
loads, not normalized sampling. A reduced-resolution implementation must keep
both producer grids and constants coherent, or explicitly map/rescale them before
merging; one global MV scale cannot repair a field with mixed per-branch units.

The next unresolved gate is still the native-output/post-HUD handoff and closed
proxy copy-back contract, plus exact dimension-source typing. A later game capture
is needed for actual inputs, coverage, temporal timing and image quality—not to
establish the basic pixel-versus-normalized shader unit convention.
