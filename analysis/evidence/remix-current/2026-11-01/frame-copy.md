# Offline frame conversion optimization

Scope: `remix_live.cpp` copies the D3D9 readback's BGRA bytes into the published game frame. The old inner loop
copied four scalar bytes per pixel, optionally swapping red/blue and always forcing opaque alpha. Existing live
logs measured the whole conversion stage at roughly 10-12 ms on the ARM64 laptop under x64 emulation.

`frame_copy.h` now does that same operation four pixels at a time with baseline SSE2, with a scalar tail. The existing
readback, lock/unlock, frame publication, backbuffer formats and HUD path are unchanged. No renderer quality setting
or new switch/dependency is introduced. The header is in `gates.py`'s DLL dependencies.

## Offline acceptance

- `python3 analysis/checks/test_frame_copy.py --benchmark`
- Correctness: byte-exact against the old scalar loop under ASan/UBSan; widths 0..65, heights 0/1/3, all source and
  destination alignment offsets 0..15, tight and odd padded rows, reversed row pitch, untouched padding/source,
  opaque alpha, SIMD tails and empty images. Independent hand-computed pixel checks. Windows x64 cross-build.
- Mutation checks: disabling channel swapping or disabling SIMD alpha forcing each fails the byte comparison.
  Receipt: `analysis/runtime/frame-copy/red-checks.json` (ignored runtime artifact).
- `python3 analysis/checks/gates.py --all --run --jobs 8`: **77/77**, source unchanged, DLL SHA-256
  `4103584bf8ef5cf5c3e1dbd34a84dde6a061240ef37257eb046be90f837d0c70`.
  This includes the existing Wine mock's full readback-to-backbuffer RGBA/BGRA and HUD cases.

Native desktop, same `-O2` as the production build, 2880x1800, median of nine samples (12 copies/sample):

| destination | old scalar | SSE2 | ratio |
|---|---:|---:|---:|
| BGRA | 2.373 ms | 0.733 ms | 3.24x |
| RGBA | 2.386 ms | 0.855 ms | 2.79x |

These timings are informational, not a flaky performance assertion. They do not measure the ARM64 laptop's x64
emulation or predict game FPS. GPU path-tracing/readback waits remain; removing those needs separate design and a
later live verification. No game was launched, laptop accessed, or build installed for this task.

## Later live follow-up

The combined build's approved `frametime1` run measured 3.5 ms conversion in world-associated reporting windows,
compared with 11.0 ms in the earlier AC `pbr-look1` run. See `frametime1.md` for power/scene confounders and the
remaining readback wait. This supports the conversion improvement, not a controlled overall-FPS claim.

## Review / delegation ledger

- Scout launch failed: configured `openai-codex/gpt-5.3-codex-spark` absent from the local registry. No output accepted.
- Reviewer `f507b92a-0c65-4e9e-bc8d-aad51bf7ebec`, explicitly using the registry-suggested
  `openai/gpt-5.3-codex-spark`, failed with provider 404/model-not-found. No review delivered or accepted.
- No worker implementation was delegated. Lead inspected the implementation and reran all gates. Independent
  review remains unavailable; the shared ledger outside the repository was not modified.
