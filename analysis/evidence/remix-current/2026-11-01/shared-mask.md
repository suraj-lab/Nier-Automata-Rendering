# Offline shared mask capture

## Change

`live_capture::write_texture` can use an already captured immutable mip chain. The draw's material-capture block
keeps these snapshots keyed by resource, so metallic and roughness queue different IDs/channel flags backed by the
same raw pixels. Only new GPU reads consume `NIER_REMIX_LIVE_TEX_PER_FRAME`; deriving the second output does not
need another readback slot. Existing per-output disk-budget accounting is unchanged.

The per-kind ID cache, deferred-texture waiters and geometry invalidation path are unchanged. DDS channel extraction
still happens on the worker, which copies the immutable source before converting. There is no persistent new raw
pixel cache: the local map dies after the draw and the queued worker files release their snapshots as before.
Sharing is draw-local; if a different role first appears in a later draw after the raw bytes are gone, another
capture may be needed. This change removes the normal metallic/gloss pair's duplicate capture, not all conceivable
cross-draw reads. It does not make texture readback asynchronous.

## Gate

Extended `test_live_normal_map.py` and its synthetic mock:

- An independent `CopySubresourceRegion` spy counts actual staging copies from the mask, not the capture budget.
  A compiled `offsetof(ID3D11DeviceContextVtbl, CopySubresourceRegion)` assertion verifies the spy's slot 46.
- Before the fix the gate fails: expected one mask copy, observed **two**.
- After the fix, normal-on/off and roughness-floor cases all observe **one** mask copy. PBR disabled observes zero.
- Metallic remains R8 value 200; roughness remains R8 value 38 with the floor, or 25 without it.
- With a one-readback-per-frame budget, the mask is initially deferred; retries eventually produce a material with
  both PBR maps and the normal map. DDS formats, dimensions, mip counts and complete payloads match the unrestricted
  case (ignoring file names/IDs).
- Mutation: discard the shared source before each request. The gate fails again with two mask copies. The mutation
  was reverted before acceptance; receipt `analysis/runtime/shared-mask/red-check.json`.

`python3 analysis/checks/gates.py --all --run --jobs 8`: **77/77**, source unchanged, combined DLL SHA-256
`8b0f167225e480c3b5a4f769f73b78ede1cb9a56ec76821b0d809a3f3d5f14b2`. This includes the previous SSE2 frame-copy
optimization, material/mip tests, and deferred-material tests. Suite receipt: `analysis/runtime/gates/last.json`.

The offline work involved no game launch, remote access or install. This proves fewer staging copies and unchanged
mock output, not actual laptop FPS or hitch reduction. The later approved combined-build `frametime1` run is recorded
in `frametime1.md`; it does not isolate the shared-mask change's live benefit. Independent reviewer remains unavailable (provider configuration failure recorded
in `frame-copy.md`); no new delegation was attempted for this small change.
