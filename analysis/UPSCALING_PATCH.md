# FSR4 upscaling patch — design & state (2026-10-24)

## Goal

Make the closed NIER_DLAA proxy (d3d11.dll) do true upscaling: scene rendered at the
internal scale 0.75 (e.g. 2580×1080 for 3440×1440) → FSR4 → native output, instead of
native-AA (input == output).

## Status at checkpoint

- **Depth fix: DONE, live-verified.** Scene depth now scales with colour (`DEPTH_SCALE_RESULTS.md`).
  The depth-patch code cave (in `checks/depth_patch.h`) was reviewer-reviewed (found + fixed a
  P0 EFLAGS bug) and confirmed in-game: depth `2580x1080 D24S8 array=1` matching colour.
- **Upscale patch: fully mapped; parts 1–2 built but INERT.** A pre-dispatch size gate
  (part 0, below) blocks FSR4 from running at reduced scale. Parts 1–2 are dead code until
  the gate is relaxed.

## The 4-part patch (all addresses are RVAs in `NIER_DLAA_1.1.dll`, image base 0x180000000)

### Part 0 — the gate (`FUN_1800173c0`) — CRITICAL, NOT YET BUILT

FSR4 is dispatched from `FUN_180018210`, but `FUN_1800173c0` only calls it when the
PS-SRV-slot-0 scene texture W/H **equal** the camera (native) W/H:

```
1800175ba: mov eax,[rbp+0x20]      ; scene W  (from the SRV-0 texture GetDesc)
1800175c0: cvtsi2ss xmm0,rax       ; (float)scene W
1800175c5: ucomiss xmm0,[rsp+0x78] ; vs camera W   <- gate
1800175ca: jp  0x180017680         ; unordered -> skip
1800175d0: jne 0x180017680         ; mismatch  -> skip
1800175d6: mov eax,[rbp+0x24]      ; scene H
1800175dc: cvtsi2ss xmm0,rax
1800175e1: ucomiss xmm0,[rsp+0x7c] ; vs camera H   <- gate
1800175e6: jp  0x180017680
1800175ec: jne 0x180017680
...
18001767a: call 0x180018210        ; the FSR4 dispatch
```

Relax to: `scene == camera * 0.75` (a `mulss` of the camera float by 0.75 in the cave, then
`ucomiss`). The frame-counter check (`0x180017431` vs `DAT_18006a2e0`) already prevents
double-dispatch when both bloom and tone-map read the reduced scene. Camera struct base here
is `[rsp+0x70]` (passed to `FUN_180015c80`), so camera W/H = `[rsp+0x78]` / `[rsp+0x7c]`.

### Part 1 — OutWidth/OutHeight → native (BUILT, in proxy_patch.h)

Inside `FUN_180018210`, the NGX create params. `r13d`/`r12d` = scene W/H (loaded at
`0x1800186b4`/`0x1800186bb` from the scene desc `[rbp+0x10f0]/[rbp+0x10f4]`).

```
180018791: 45 8b c5  mov r8d,r13d   -> mov r8d,[rbp+0x1048]  (native W)
1800187a3: 45 8b c4  mov r8d,r12d   -> mov r8d,[rbp+0x104c]  (native H)
```
`Width`/`Height` (input) stay scene-sized; the evaluate's `DLSS.Render.Subrect` params
(`0x180018d7e`/`0x180018d82`) stay scene-sized — correct for upscaling.

### Part 2 — Output texture → native (BUILT, in proxy_patch.h)

Inside `FUN_180017e20`, the Output texture (global `0x1800abf70`) is created at scene W/H
(`esi`/`edi`). The Output call:

```
180018006: 44 8b c7  mov r8d,edi    -> mov r8d,[rip+0xabe2c] (native H)
180018009: 8b d6     mov edx,esi    -> mov edx,[rip+0xabe28] (native W)
```
The other three targets (MotionVectors/Depth/prepass) stay scene-sized. Note: the factory
cache (`0x180017e50`) still keys on scene W/H; harmless at a fixed resolution.

### Part 3 — redirect bloom/tone-map to Output (NOT BUILT)

The single copy-back `CopyResource(scene <- Output)` at `0x180018e01` (only in the
`preset==0` branch) is dimension-invalid once Output is native. Fix: hook `PSSetShaderResources`
so bloom `68495C5B` and tone-map `2C76D68A` sample the Output SRV (global `0x1800abf70`)
instead of the scene at slot 0. This is the new device-vtable hook; the remaining hard piece.

## Native W/H sources

- In `FUN_180018210` stack: `[rbp+0x1048]` (W), `[rbp+0x104c]` (H) — camera copy at
  `[rbp+0x1040]`, filled by `FUN_180015c80`.
- Globals: `0x1800abe28` (W), `0x1800abe2c` (H) — usable from any function.

## Files

- `checks/proxy_patch.h` — parts 1+2 cave emitter + signatures.
- `checks/proxy_patch_test.cpp` — native unit test (passes).
- `checks/d3d11_scale_setter.cpp` — setter integration: chainloads proxy, patches it on load
  (`apply_proxy_patch`).
- `checks/analyze_framedump.py` + `test_analyze_framedump.py` — frame-dump analyzer (delegated).

## Reviewer findings (claude-haiku-5-5, 2026-10-24)

- Mechanics clean: register liveness, EFLAGS (flag-neutral — no pushfq/popfq needed here,
  unlike the depth cave), byte arithmetic, write ordering.
- **P1 (REJECT): the patch is inert** — the gate (part 0) prevents FSR4 from running at reduced
  scale, and if it did run, parts 1+2 would be value-identical no-ops.
- P2s to fold in on next pass: export cave offsets from `proxy_patch.h` (don't duplicate
  `{rva,10,0}/{rva,10,19}/{rva,5,38}` in the setter); load native W/H as one qword to avoid a
  torn pair; rollback already-applied patches if a later write fails.

## Delegate/benchmark ledger (2026-10-24)

- `reviewer` (cloud haiku) — depth patch: caught P0 EFLAGS → fixed.
- `scout` (cloud haiku) — mapped `FUN_180018210` + `FUN_180017e20` flow.
- `local-worker` (desktop Qwen 27B) — frame-dump analyzer: gated, first-try pass.
- `reviewer` (cloud haiku) — upscale patch: caught P1 (gate) → REJECT.
