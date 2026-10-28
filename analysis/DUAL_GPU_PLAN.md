# Dual-GPU plan: Remix on one card, NieR on the other (idea, 2026-10-28, not started)

## Why

In NieR at 3440x1440 the RX 9070 XT is 100% busy: Remix 7.3 fps, game 14 fps (PROGRESS.md, first checkpoint). Remix
path tracing (38 fps alone) and NieR's own frame + FSR4 take turns on one GPU, although NieR's image is fully covered
by Remix. The desktop also has an **RX 6800 XT**.

## Idea

- **9070 XT (RDNA4): Remix.** Hardware RT and XeSS; the expensive part.
- **6800 XT (RDNA2): NieR's own D3D11 frame** (DXVK). Its image is hidden under Remix in Remix mode, so its quality
  barely matters; it only has to keep the game loop, HUD-free frame and present at 60.

Our design already suits a split: the Remix frame reaches the game through system memory
(`CopyRenderingOutput` -> `GetRenderTargetData` -> `LockRect` -> `UpdateSubresource`), so the two renderers never share
a GPU resource and nothing in the transfer needs to change.

## FSR4 on the 6800 XT

FSR4 (FSR 4.1.1, our in-game upscaler via NIER_FSR4) is officially RDNA4-only, but the user reports it can run on the
6800 XT. **To verify**: which route (Proton/vkd3d-proton, Mesa/RADV version, any env or mod required), its cost on
RDNA2, and whether our bridge's provider check (`verify_fsr_inference.py`, which rejects fallback providers) still
selects 4.1.1 there. If it does not, FSR 3.1 is an acceptable fallback in Remix mode, where the game image is hidden.

## Questions to answer first (cheap, no game)

1. **Can each renderer be pinned to a card separately?** NieR's DXVK reads `dxvk.conf` / `DXVK_CONFIG` /
   `DXVK_CONFIG_FILE`; the Remix runtime reads `rtx.conf` from the game CWD. Candidates: DXVK's `dxgi.deviceFilter`
   (or equivalent) for the game side, Remix's own device-selection option for the runtime side (look it up in
   `analysis/runtime/remix-probe/RtxOptions-1.6.md`), `MESA_VK_DEVICE_SELECT` (process-wide, so only if the two
   need the same card). Verify each in the mock first (`run_live_mock.sh` + `DXVK_LOG_LEVEL=info` shows the chosen
   adapter in both logs).
2. **Which card drives the monitors?** Presenting from the card that is not connected to DP-2 costs a cross-GPU copy
   per frame (PRIME); measure it rather than assume.
3. **Does RADV expose ray tracing on the 6800 XT?** (RDNA2 has RT hardware.) Decides whether roles could ever swap.
4. **FSR4 on the 6800 XT** (above).
5. **Power/thermals**: both cards loaded at once; check the PSU headroom before long sessions.

## Order of work (when picked up)

1. Inventory: `vulkaninfo --summary`, `lspci`, which connector each monitor uses, current Mesa.
2. Mock game: pin DXVK to the 6800 XT and Remix to the 9070 XT; confirm from both logs; measure Remix fps alone vs
   with the mock rendering.
3. In NieR (with the user): same pinning, MangoHud on, compare against the single-GPU numbers above (7.3 / 14 fps).
4. Only if it pays off: make it a documented launch preset; otherwise record the numbers and drop it.

Related, single-GPU alternatives (PROGRESS.md "Next session"): cheap NieR rendering in Remix mode, lower Remix render
size + GPU stretch, async readback. These are independent of the dual-GPU route and stack with it.
