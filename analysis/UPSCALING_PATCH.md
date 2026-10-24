# FSR4 upscaling patch — design & state (2026-10-24)

## Goal

Make the closed NIER_DLAA proxy (d3d11.dll) do true upscaling: scene rendered at the
internal scale 0.75 (e.g. 2580×1080 for 3440×1440) → FSR4 → native output, instead of
native-AA (input == output).

## Status at checkpoint

- **Depth fix: DONE, live-verified.** Scene depth now scales with colour (`DEPTH_SCALE_RESULTS.md`).
  The depth-patch code cave (in `checks/depth_patch.h`) was reviewer-reviewed (found + fixed a
  P0 EFLAGS bug) and confirmed in-game: depth `2580x1080 D24S8 array=1` matching colour.
- **Upscale: parts 0, 0b, 1, 2 BUILT and live-verified (2026-10-24, test 2).** FSR4 log:
  `CreateFeature: 2580x1080 -> 3440x1440`, 6613 frames, 0 evaluate failures; jitter shake gone.
  Image is offset/zoomed and soft until Part 3 (see the copy-back note). Setter DLL `3aaf52fa…`.
  Test 1 (parts 0-2 only) failed: dispatch skipped with "linear depth target not found yet" ->
  Part 0b. Logs: `backups/upscale-test-20261024T132205Z/`.
- **Part 3 DONE, live-verified (test 3).** Correct framing and sharpness; bloom and tone-map read
  the native Output at slot 0, no copy-back. Design and evidence: `PART3_REDIRECT.md`. Setter v3
  `936602b3…` tested; v4 `3afafb60…` adds the reviewer's failure-path fixes (gated, not yet run).

## The 4-part patch (all addresses are RVAs in `NIER_DLAA_1.1.dll`, image base 0x180000000)

### Part 0 — the gate (`FUN_1800173c0`) — BUILT (proxy_patch.h)

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

Built as `jmp cave; nop` at 0x1800175ba (whole 56-byte block signature-checked). Cave passes iff |sceneW - camW*scale| < 1 and |sceneH - camH*scale| < 1 (`ucomiss 1.0,|d|; jbe skip`, NaN -> skip). `scale` is a cave data slot, 1.0 by default (= original gate); the setter writes 0.75 only after both the renderer scale patch and the proxy patch are Applied. Cave: 320 bytes, 16-aligned; OutW@0, OutH@21, Output@42, gate@64, gate0b@176, absmask@288, scale@304, 1.0@308. `kSites` applies 0b second-to-last and the dispatch gate last; everything is inert while the scale slot is 1.0, which it stays unless every site applied. The frame-counter check (`0x180017431` vs `DAT_18006a2e0`) still prevents double dispatch.

### Part 0b — the linear-depth capture gate — BUILT (proxy_patch.h), found in test 1

The capture that stores the linear-depth texture in global `0x1800abf40` (needed by dispatch,
which otherwise logs "linear depth target not found yet, skipping") has the same 56-byte
size gate: texture W/H `[rsp+0x48]/[rsp+0x4c]` vs camera W/H `[rbp-0x78]/[rbp-0x74]`, pass
`0x18001a6dc`, skip `0x18001a78f`. Pre-checks already require R32 format (39/41), 1 mip,
array 1, SRV bind. Patched as `jmp cave; nop; nop` (7 bytes) with the same rule and the shared
scale slot. A scan of the DLL for `cvtsi2ss` + `ucomiss` against the camera finds only these two
gates. Test 2 log: `linear depth target is ... (2580x1080 fmt=41 bind=0x28)`.

### Part 1 — OutWidth/OutHeight → native (BUILT, in proxy_patch.h)

Inside `FUN_180018210`, the NGX create params. `r13d`/`r12d` = scene W/H (loaded at
`0x1800186b4`/`0x1800186bb` from the scene desc `[rbp+0x10f0]/[rbp+0x10f4]`).

```
180018791: 45 8b c5  mov r8d,r13d   -> cvttss2si r8d,[rbp+0x1048]  (native W)
1800187a3: 45 8b c4  mov r8d,r12d   -> cvttss2si r8d,[rbp+0x104c]  (native H)
```
Native W/H are FLOATS (FUN_180016cdc stores them with movss); the original integer mov would have passed float bits (3440.0f -> 1163329536).
`Width`/`Height` (input) stay scene-sized; the evaluate's `DLSS.Render.Subrect` params
(`0x180018d7e`/`0x180018d82`) stay scene-sized — correct for upscaling.

### Part 2 — Output texture → native (BUILT, in proxy_patch.h)

Inside `FUN_180017e20`, the Output texture (global `0x1800abf70`) is created at scene W/H
(`esi`/`edi`). The Output call:

```
180018006: 44 8b c7  mov r8d,edi    -> cvttss2si r8d,[rip+nativeH]
180018009: 8b d6     mov edx,esi    -> cvttss2si edx,[rip+nativeW]
```
The other three targets (MotionVectors/Depth/prepass) stay scene-sized. Note: the factory
cache (`0x180017e50`) still keys on scene W/H; harmless at a fixed resolution.

### Part 3 — redirect bloom/tone-map to Output (BUILT, live-verified; see PART3_REDIRECT.md)

CORRECTION (2026-10-24): the copy-back `CopyResource(scene <- Output)` at 0x180018e01 (context vtable +0x178) runs after EVERY successful evaluate (result & 0xfff00000 != 0xbad00000), not only for preset==0. DXVK CopyResource only rejects mismatched ArraySize/MipLevels and clamps to the overlap, so with native Output and a reduced scene it copies the top-left 2580x1080 crop: expected image = cropped/zoomed, no crash. Fixed by Part 3: an exit hook at 0x1800176ac calls the setter's `on_dispatch_exit`, which rebinds slot 0 to an SRV of the Output (global 0x1800abf70) for the draws that read the scene after dispatch; the copy-back call is skipped (6 bytes at 0x180018e01 -> jmp 0x180018e07).

## Native W/H sources

- In `FUN_180018210` stack: `[rbp+0x1048]` (W), `[rbp+0x104c]` (H) — camera copy at
  `[rbp+0x1040]`, filled by `FUN_180015c80`.
- Globals: `0x1800abe28` (W), `0x1800abe2c` (H) — usable from any function.

## Checked, no patch needed

- 0x180018910/0x180018923 compares native vs cached 0x1800ae008/c: reset flag only, not a skip gate;
- jitter: evaluate multiplies native-pixel jitter by sceneW/nativeW (0x180018b67, 0x180018d02);
- create flags 0x43 include MVLowRes and MV.Scale = 1.0, so render-res pixel MVs are correct;
- FSR4 bridge `upstream/Nier-FSR4/src/nier_fsr4.cpp` reads OutWidth/OutHeight (~line 1513) and uses maxRenderSize/maxUpscaleSize + renderSize/upscaleSize, so real upscaling is supported.

## Files

- `checks/proxy_patch.h` — parts 0, 0b, 1, 2, 3a (exit hook), 3b (copy-back skip) cave emitter + signatures (7 sites, 384-byte cave).
- `checks/proxy_patch_test.cpp` — native unit test; executes both gate caves and the exit hook (ms_abi callee).
- `checks/redirect_logic.h` + `redirect_logic_test.cpp` — Part 3 redirect decision (pure) and its frozen test.
- `checks/test_part3_integration.py` - frozen Part 3 gate (29 checks, includes the 23-check setter gate).
- `checks/test_setter_proxy_integration.py` - frozen gate for the setter integration (23 checks).
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
- `local-worker` (desktop Qwen 27B) - setter integration against the 23-check gate: first-try pass, accepted after lead rerun.
- `reviewer` (cloud haiku) - round 2 on the cave: encodings/semantics accepted; its P0 (preset==0 copy-back) rested on the stale Part 3 doc and was downgraded by the lead; P1 liveness cleared by lead objdump.
- `local-helper` (laptop Qwen 35B-A3B) - this doc update: FAILED twice (output-length cap on a
  full rewrite; then looped on exact-match edits in unicode-heavy PROGRESS.md). Most
  UPSCALING_PATCH.md edits landed; lead finished. Lesson: no exact-match prose edits for local models.
- `reviewer` (cloud haiku) - Part 0b: ACCEPT, P2 comment fix only. Pre-supplied objdump
  evidence in the brief compensated for the reviewer having no shell.
- Part 3: `scout` (cloud) mapped FUN_1800173c0 accurately from pre-extracted asm; `local-worker`
  shader recon went off-track (CPK archives) and was stopped; `local-worker` redirect + setter
  integration passed the 29-check gate first try; `local-helper` (laptop) wrote PART3_REDIRECT.md
  as a new file, correct first try; `reviewer` (cloud) ACCEPT for test, P1/P2 fixed in v4.
