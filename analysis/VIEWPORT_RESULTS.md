# Viewport sizing and render-scale control — 2026-10-23 (offline)

Static analysis of `input/NieRAutomata_win10.unpacked.exe`
(SHA-256 `44ee2dc0…a28c2`) with MinGW objdump. No game launch, no Ghidra run,
no installed-file changes. Re-check: `python3 offline-viewport/verify_viewport_scale.py`
(18 assertions, all pass).

## Answer to option 1

**Successfully configured scene passes take their viewports from the bound target.**
This is not sufficient for scene scaling: the later depth investigation found that
screen-sized depth ignores the scale and the engine can reject the colour/depth
pair before binding it. See [DEPTH_SCALE_RESULTS.md](DEPTH_SCALE_RESULTS.md).

### Evidence

1. **One viewport path.** The whole exe has only two `RSSetViewports`
   (D3D11 context slot 44, `+0x160`) call sites. One is the engine wrapper
   `SetViewport` `0x140255c50` (engine context vtable `0x140db1788` slot 14).
   The other, `0x1405941f0`, runs once in the shutdown sequence.
2. **The engine wrapper tracks a "current target size"** at `+0x570/+0x574`.
   Getters: vtable `+0x1a0` → `0x140257140`, `+0x1a8` → `0x140257150`. It is
   written by the two render-target setters:
   - `0x140255720` (single RT): size = RT texture's `+0xc/+0x10`.
   - `0x140255cf0` (MRT, 4 slots): size = RT0's width/height divided by
     `2^mip`, or the depth-stencil's `+0x8/+0xc` when there's no colour target.
3. **The main begin-pass routine `0x140243b90` (45 direct callers)** binds
   targets, then calls `passState.SetViewport(0,0,getCurW(),getCurH(),…)` via
   `0x1402436c0`. This is the general scene path.
4. Other viewport writers:
   - Rect blit helper `0x140254fd0`: draws a sub-rect, then restores the full
     viewport to `getCurW/getCurH`.
   - 2D/UI draw helper `0x14018bde0`: uses a caller-supplied float viewport, then
     restores to the bound target object's size (`passState+0x60 → +0x8 →
     +0x8/+0xc`). It falls back to native `renderer+0x3c/+0x40` or the UI size
     `0x14177f270/274` (1600×900-based) only when no target is bound.
   - `0x14077f520` / `0x14077f730`: fixed 1024×1024 (fixed-size RTs).
5. **Resize correction:** `0x14024a150` updates size constants and UI aspect
   state, but its `0x14024a9c0` helper creates a 16-byte constant buffer, not a
   render target. Actual colour resize (`0x140252610`) uses the scale; depth
   resize (`0x140252210`) does not. The earlier claim that every registered
   target was re-created scaled was incorrect.

## Correction: there *is* a runtime scale setter, but it is dormant

`GAME_RENDER_SCALE.md` said no runtime setter exists. There is one:

| Function | Effect | Callers |
|---|---|---|
| `0x14024d2b0` | `renderer->+0x80 = xmm0` (scale) | 2, both in `0x14075eaf0` |
| `0x14024d2f0` | `renderer->+0x00 = ecx` (mode) | 4 |

- In `0x14075eaf0`, both scale calls pass `1.0f` (`0x140dba840`). They are gated
  by `0x14086ace0(0x33)` / `(0x36)`, a debug-key bitset test behind the flag
  `0x141029c68`. That flag lives in zero-initialised `.dataa`, and its only
  writer is in a teardown-style function (`0x14075ef30`). So this is a debug
  hotkey that resets scale to 1.0 and is unreachable in retail (static inference).
- Through the renderer global, nothing else writes `+0x80` or `+0x00`.
  The renderer init writes mode = 1 (`0x140249797`) and scale = 1.0 (`0x1402497bf`).

## The mode value and engine CAS

- `0x1402f3e60` is **AMD CAS `CasSetup`**. It writes const0 = `in/out` scale
  plus `0.5*in/out-0.5` offset, const1.x = `-1/lerp(8,5,sharpness)`, const1.y = the
  same value packed to half via a table, and const1.z = `8*in/out`. Here `in` =
  scaled size; `out` = native **only when mode == 2**, otherwise `out` = `in`.
- **Mode 2 is never assigned.** All four mode-setter calls pass 0 or 1:
  - imm 1 / 0 in the debug fn;
  - `setne` in `0x14076fc00`;
  - `(options->+0xc0 == 0)` in `0x140985470`, also mirrored to `0x141421f5c`.

  So the engine's CAS-upscale branch is dead on PC, and CAS only sharpens at 1:1.
  The meaning of the 0/1 option at `+0xc0` is not identified.

## Consequences for option 2 (in-game scale test)

- A scale-only write is insufficient: scene-depth allocation and metadata must
  also match the reduced colour size on creation and resize.
- **CAS risk remains unisolated:** its constants use `in = out = scaled` when
  mode is not 2, while its result target is native. Incorrect sampling or partial
  coverage is possible, not a demonstrated cause of the black image. Test with
  CAS off first. Mode 2 is an untested alternative; the settings code rewrites
  mode to 0/1, and changing it does not fix the separate depth mismatch.
- The NIER_DLAA size gate still skips AA when scene ≠ swap-chain size (expected).

## Not established

- Writes to `renderer+0x00/+0x80` through a `this` pointer (renderer methods
  not loading the global) are not excluded by this scan.
- Explicit float viewports passed into `0x14018bde0` (2 calls from one function)
  are caller-defined; they appear to be 2D draws, not scene passes.
- Compute passes are not viewport-bound. Their dispatch sizes (from target
  size vs screen size) are not traced.
- The later 0.75 game capture confirms reduced colour targets and matching
  viewports, but lacks main scene-depth bindings and has incorrect visible
  output. It is not successful end-to-end scaling validation.
