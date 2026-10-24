# Part 3 - route FSR Output to bloom/tone-map (design, 2026-10-24)

## Problem
After test 2 (FSR4 2580x1080 -> 3440x1440 working), the image is offset/zoomed and soft: the mod's `CopyResource(scene <- Output)` at 0x180018e01 copies only the top-left 2580x1080 of the native Output into the reduced scene (DXVK clamps), and post-processing then reads that crop.

## Who reads the scene (frame dump of test 2, `backups/upscale-test-20261024T132205Z/NIER_DLAA_frame_20261024_145825_848.txt`)
- #4686 PS 1F57D637 reads scene T2619 at slot 0 BEFORE FSR (pre-AA copy into T2628) -> must NOT be redirected.
- #4849 CopyResource dst=T2619 src=T4540 = the copy-back (Output = T4540, 3440x1440).
- #4851 bloom PS 68495C5B reads T2619 at slot 0 = the draw that triggers FSR dispatch (first match of the frame).
- #4871 tone-map PS 2C76D68A reads T2619 at slot 0, renders 3440x1440 -> exits early at the proxy's once-per-frame check, so a patch at the dispatch site alone would miss it.

## Proxy facts (FUN_1800173c0, from scout recon + lead objdump)
- Order: immediate-ctx check ([0x1800abfc8]) -> once-per-frame check ([0x18006a288] vs current frame [0x1800abc08]) -> PSGetShader (ctx vtable +0x250) + hash compare -> PSGetShaderResources slot 0 (+0x248) -> size gate -> FSR dispatch at 0x18001767a.
- Every path exits through 0x1800176ac with rdi = context, rsp 16-aligned, flags dead, rax unused by callers.
- Output texture global 0x1800abf70: bind flags 0x88 (SRV|UAV) but the proxy never creates an SRV for it.
- The proxy hooks 23 context slots (Draw*, PSSetShader, OMSetRenderTargets, Dispatch, CopyResource, ...) but NOT PSSetShaderResources (slot 8) or PSGetShaderResources, so the redirect cannot re-enter the proxy.

## Design
- 3a Exit hook: 7 bytes at 0x1800176ac (`mov rcx,[rbp+0x50]; xor rcx,rsp`) -> jmp cave. Cave pushes rax,rcx,rdx,r8-r11, sub rsp 0x28, mov rcx,rdi, call [exit_fn], restores, replays the 7 bytes, jmp 0x1800176b3. exit_fn = setter's `on_dispatch_exit(ID3D11DeviceContext*)` (MS x64 ABI), stored in the cave at +376.
- 3b Copy-back skip: 6 bytes at 0x180018e01 (`call [rax+0x178]`) -> jmp cave -> jmp 0x180018e07.
- Apply order in kSites: OutW, OutH, Output, exit hook, copy-back skip, depth gate (0b), dispatch gate (0). The copy-back is never skipped unless the redirect hook applied first. Cave is 384 bytes.
- on_dispatch_exit (setter): cheap early-outs first (immediate ctx, current frame == dispatch frame, Output non-null), then PSGetShaderResources slot 0 -> resource identity -> `redirect_logic::should_redirect`. The first exit after the dispatch in a frame is the dispatching draw: it captures that slot-0 resource as "the scene" for this frame; later draws redirect only if slot 0 is that same resource. On redirect: create (once per Output texture) an SRV for Output via ctx->GetDevice()->CreateShaderResourceView(out, nullptr, ...) and PSSetShaderResources(0, 1, &srv).
- Rules of should_redirect: not immediate / no slot0 / no Output / frame != dispatch frame -> no; slot0 == Output -> no; new frame -> capture + yes; else slot0 == captured scene.

## Verification
- `checks/proxy_patch_test.cpp` executes the exit-hook fragment natively (ms_abi callee clobbers volatile regs; checks ctx in rcx, 16-byte alignment, restored r8, replayed cookie xor).
- `checks/redirect_logic_test.cpp` (frozen) covers the rules incl. frame wrap and resize re-capture.
- `checks/test_part3_integration.py` (frozen gate): logic test + previous setter gate + setter contract checks.
- objdump of the emitted cave matches the design.

## Open risk
Unknown whether the tone-map shader samples t0 with plain normalized UVs (then a native Output just works) or multiplies UVs by a render-scale constant (then the redirect still crops and the constant must be fixed). Next in-game test answers it; if needed, set NIER_DLAA.ini DumpShaders=1 to dump the shader.

## Result (test 3, 2026-10-24): WORKS
- User: image correctly framed and sharp ("looks good", indistinguishable from native).
- NIER_SCALE.log: `7 patches, cave 384 bytes`; `part3 redirect: output SRV ... hr=0x00000000` at start
  and after each of two resolution changes; first redirect at frame 397.
- NIER_FSR4.log: render 2580x1080 -> 3440x1440, 6490 + 7361 frames, 0 evaluate failures.
- Frame dump `NIER_DLAA_frame_20261024_153623_846.txt`: #5264 CopySubresourceRegion dst=T4803
  (3440x1440 R11G11B10F bind=0x88 = Output); bloom #5266 and tone-map #5286 read T4803 at slot 0;
  pre-AA reader #5048 untouched; no CopyResource in the frame.
- Open risk closed: the tone-map samples t0 with plain normalized UVs; no constant patch needed.

## Follow-up (v4, gated, not yet run in-game)
- Reviewer P1/P2: retry Output SRV creation while none exists, assign only on SUCCEEDED, log
  (capped) when the copy-back is skipped without a redirect.
