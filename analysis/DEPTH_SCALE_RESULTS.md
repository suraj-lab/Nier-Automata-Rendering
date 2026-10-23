# Scene depth and internal render scale — 2026-10-23

## Result

The saved Win10 executable has **scale-aware colour targets but scale-unaware
screen-sized depth-stencil targets**, both on initial creation and on resize.
The engine validates their sizes before binding them. A 0.75 scale therefore
makes ordinary scene colour/depth pairs incompatible.

This is a concrete defect in the scale-only experiment, and strongly explains
the broken scene. It is **not yet proof that fixing depth alone restores the
image**: the test also had CAS enabled, and no pixel readback or corrected run
isolated the first failing pass.

## Evidence and reproduction

- Executable: `input/NieRAutomata_win10.unpacked.exe`, SHA-256
  `44ee2dc0e1f2fd939ddb39f028edb4238ecac4e9c80daad3ce925d50545a28c2`.
- New evidence: [`offline-depth/binary-traces.asm`](offline-depth/binary-traces.asm)
  (bounded objdump excerpts) and
  [`offline-depth/verification.json`](offline-depth/verification.json)
  (addresses, source-frame hashes, trace hash, 34 passing checks).
- Re-run from the workspace root:
  ```sh
  python3 analysis/offline-depth/verify_depth_scale.py
  ```
  The verifier checks the executable hash first and disassembles the relevant
  ranges afresh. Its parser self-checks also reject a missing resource table.
  `--record` creates the evidence files only when they do not exist.
- These are **objdump-derived static traces**, not new REA/Ghidra Evidence IDs.
  Existing Ghidra snapshots were not modified. The only runtime evidence is the
  already recorded 19 Oct and 23 Oct frame dumps. No new game or GPU execution.

All VAs below use image base `0x140000000`; runtime callers must account for ASLR.

## 1. Colour and depth take different sizing paths

| Path | Initial creation | Resize callback | Size source |
|---|---|---|---|
| Scaled colour | `0x140248170` | scale-aware branch at `0x1402526f5`, in `0x140252610` | screen W/H multiplied by `renderer+0x80` |
| Screen depth | `0x14024c340` | `0x140252210` | screen W/H, optionally multiplied by the constant **0.5** |

The colour initializer multiplies width/height by the scale at `0x1402481b8`
and `0x1402481e0`; its resize path does so at `0x140252705` and `0x14025273f`.
The two depth paths never load `renderer+0x80`. Their half-size constant at
`0x140dba7f0` is the float `0.5`, verified from the PE bytes.

Depth initializer call sites identify the screen-sized handles:

| Handle VA | Call site | Half-size flag |
|---|---|---|
| `0x1410bf6b0` | `0x140772522` | 0 |
| `0x1410bf6c0` | `0x140772546` | 0 |
| `0x1410bf6e0` | `0x14077256a` | 0 |
| `0x1410bf7b0` | `0x14077264a` | 1 |

The half-size handle is paired with `g_VelocityTexture[0]` (`0x1410c0320`)
in `0x14077edc0`. Fixed shadow and other fixed-size depth resources use separate
explicit-size calls and should not be blanket-scaled.

For the recorded 1920×1080 test:

| Domain | Colour | Depth from these paths |
|---|---|---|
| Full scene, scale 1.0 | 1920×1080 | 1920×1080 |
| Full scene, scale 0.75 | 1440×810 | 1920×1080 |
| Half scene, scale 0.75 | 720×405 | 960×540 |

Depth sizes in this table are **derived from the code**, not measured from
unbound depth objects in the frame dump.

## 2. Engine metadata and D3D creation

Initial creation: `0x14024c340` → `0x14024aa90` → `0x140253410`.
Resize: node vtable `0x140db1e48 + 0x10` → `0x140252210` →
`0x140253410` (call at `0x14025230b`).

That shared wrapper dispatches backend vtable `0x140db1490 + 0x50` to
`0x14025ce80`, which adjusts `this` and jumps to `0x140258fe0`.
The backend uses descriptor W/H for `CreateTexture2D` (device slot 5, `+0x28`)
and `CreateDepthStencilView` (slot 10, `+0x50`). With the nonzero format argument
used by these screen-depth calls it selects DXGI format 45, D24_UNORM_S8_UINT.
On success it also copies descriptor W/H into engine object fields `+0x08/+0x0c`.

Consequently, changing only a D3D texture's dimensions would leave the engine
metadata inconsistent. Both the real allocation and the engine's descriptor
contract must agree.

## 3. Mismatch is rejected by the engine first

`0x1402439a0` constructs and validates a pass description. At `0x140243b5c`
and `0x140243b62`, it compares depth metadata W/H with the selected colour
size. Either mismatch branches to `0x140243b78` and returns false.

The begin-pass routine `0x140243b90` checks that result at `0x140243be7` and
returns false on failure, **before** its backend target-binding call at
`0x140243c0b`. Some inspected callers do not check that return before continuing
(e.g. `0x14077def7` followed by a clear call).

This corrects the earlier claim that D3D11 necessarily saw the mismatched pair
and simply dropped its depth. The engine can reject setup itself, leaving prior
state in use. The dump cannot by itself identify which CPU rejection occurred.

## 4. What the recorded frames actually establish

The 23 Oct capture contains **444 HDR draw entries** targeting 1440×810 with a
matching viewport, all reporting `DS=-`. The resource table references **one**
D24S8 texture: fixed 256×256 (`T1577`, cleared during the frame). It references
no main scene-sized D24S8 texture. The earlier claim of no D24S8 anywhere was wrong.

The 19 Oct native capture does reference full-size 3440×1440 D24S8 scene depth.
These captures are different scenes/resolutions; their draw counts are not a
like-for-like benchmark. Resource tables describe resources referenced by a
captured operation, not every allocation still alive in the process.

The 23 Oct trace also records tone-map and compute work feeding native
1920×1080 intermediates, then HUD draws. That proves a command path exists;
it does **not** establish correct colours, CAS sampling or pixel contents.

## 5. Correction to earlier resize evidence

`0x14024a9c0` does not rebuild a texture. It creates a **16-byte constant buffer**
via `0x14024bc50`, containing size and reciprocal-size values. Its use in
`0x14024a150` was incorrectly cited as proof that every render target is
re-created scaled. The actual colour and depth callbacks above establish their
separate resize behaviours.

## Next fix requirements (not implemented)

- Cover selected scene-depth surfaces on both initial creation and resize.
  `0x140253410` is a candidate shared interception point, not a validated patch.
- Preserve engine metadata, dynamic-resize flags, sample count and fixed-size
  shadow/UI depth. Do not change global screen size; native HUD/output depends on it.
- Match colour rounding: derive the scaled full size first, then half/quarter
  sizes. Odd dimensions need tests; scaling an already rounded native half-size
  need not produce the same result.
- Test the selection logic and refusal paths offline before another installation.
- Next game test: desktop/Dell, CAS off, screenshots plus F10 dump. Check scene
  colour/depth/viewport agreement and native HUD, not just whether it stops being black.

No setter source or DLL changed in this investigation. No runtime fix or new
in-game test is approved by the evidence-recording approval.
