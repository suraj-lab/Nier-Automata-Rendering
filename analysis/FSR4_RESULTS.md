# Phase 3: actual FSR4.1.1 dispatch under Proton

Historical phase-3 results below remain intact. Later 2026-10-19 synthetic tests
at 3440×1440, plus the corrected logger device-chain test, are recorded in
[OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md). No game was launched for those tests.

## Result

**Passed with the portable GE-Proton11-7 runner on the RX 9070 XT.**

The same locally built, unmodified Nier-FSR4 bridge DLL processed:

| Case | Render resolution | Output resolution | Frames | Successful provider |
| --- | --- | --- | --- | --- |
| Native AA | 640x360 | 640x360 | 16 | 4.1.1 |
| 2x upscaling | 320x180 | 640x360 | 16 | 4.1.1 |

Both cases completed all evaluations with zero evaluation failures. Independent
readback verification found finite, nonuniform RGB values, no untouched sentinel
pixels, and correctly sized RGBA16F output files. This is synthetic inference and
backend-upscaling evidence, **not an in-game integration or quality benchmark**.

No game files, saves, game launch options, existing game prefix, or Steam runner
selection were changed. The game executable's SHA-256 was rechecked unchanged.
No new system packages were installed. Both upstream source checkouts are clean.

## Official AMD runtime provenance

Origin: https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK

- Tag: `v2.3.0`
- Commit: `60f4ea81909200d8542eca14dccb2628b763a9a3`
- Sparse checkout: `../upstream/FidelityFX-SDK-v2.3.0`
- Only the two required signedbin DLLs and AMD's license were selected, plus
  Git's default root files. No SDK installer or remote script was executed.

Both DLLs exactly match the hashes pinned by the Nier-FSR4 bridge's CI:

| DLL | Bytes | SHA-256 |
| --- | --- | --- |
| `amd_fidelityfx_loader_dx12.dll` | 26,376 | `e2d85aa05a9bd9ed8b38935fdf5199372cca6f74c12015143bb6f945ee1608aa` |
| `amd_fidelityfx_upscaler_dx12.dll` | 28,761,864 | `d0dcccc74a43c44ba435b7a369b456e0970d8a4464e4bd683119b374f2c9fb46` |

AMD's license is retained beside the test binaries. Source and integrity checks
are recorded in `evidence/amd-runtime-provenance.json`. The files come from AMD's
`signedbin` directory; a separate Authenticode trust-chain validation was not run.

## What failed on GE-Proton11-1

The original runner successfully processed the frames, but the runtime only
advertised providers `3.1.5` and `2.3.4`. Both created contexts used **3.1.5**.
The bridge explicitly fell back after finding no `4.1.1` match.

That is not an FSR4 success, even though the test executable exited 0 and the
images looked valid. Baseline artifacts are retained in `fsr-test/` and
`evidence/fsr-inference-run/`.

A diagnostic run with the same runner and `WINEDEBUG=-all,+amdxc` confirmed that
the AMD compatibility shim reported `FSR 4 supported: 1` and received wave-matrix
queries, yet the SDK still did not expose provider 4.1.1. Its logs are retained
in `evidence/fsr-provider-trace/`.

Native Ghidra analysis of the actual installed `amdxc64.dll` is retained:

- `evidence/amd-shim-fsr-support.json`:
  `ev_1fda0623ea91f46c1c3c3c84a1e61b30e03dbbdd2a3fd6a99f37b01dba9e3d0a`
- `evidence/amd-shim-create-interface.json`:
  `ev_2569b9de0ad2feefc16977b17e404a20cf37dd9949863b7d67e35d8d5e148cb6`

These establish the older shim's capability-check and interface paths; they do
not isolate the exact missing FSR4.1.1 compatibility change. The GE tag's Wine
submodule source was also inspected, but GE applies additional patches, so that
unpatched source is not treated as identical to the shipped shim.

The earlier assumption that GE-Proton11-1 would be sufficient for this path was
wrong. Do not use its successful loader/ABI tests as evidence of FSR4 inference.

## Portable GE-Proton11-7 comparison

Newer GE release notes explicitly mention updated amdxc/FSR4 support. The project
itself lists GE-Proton11-7 as its tested runner, so that exact version was tested
rather than guessing environment overrides or spoofing hardware support.

Official release:
https://github.com/GloriousEggroll/proton-ge-custom/releases/tag/GE-Proton11-7

Downloaded `GE-Proton11-7-x86_64.tar.gz` (563,784,602 bytes). Verified both the
release API's SHA-256 digest and the release's SHA-512 sidecar before extracting
with Python's safe `data` extraction filter into a new workspace directory.

- SHA-256: `c5448b76a230384e2d7bc6beb5ccb97bafb7e2c3b6c527cb03a1a546bbcb00a0`
- SHA-512: `7db87e9787e20c35cbdac26018431d5794626b626e4067b050684e45a88cc2ca229d7d263519eafb2e168cde5bef57611065d159d3685aaec152ccb9abe3073f`
- Portable runner: `runners/GE-Proton11-7-x86_64/proton`
- Separate test compatdata: `runtime/proton-ge11-7-test`
- Test binaries and output: `fsr-test-ge11-7/`
- Logs: `evidence/fsr-inference-ge11-7/`
- Acquisition evidence: `evidence/ge11-7-provenance.json`

The runner was **not installed into Steam's compatibilitytools directory**.
It and its archive remain in the workspace (about 2 GiB together, excluding
prefixes, caches, and other test artifacts). No global environment, shell config,
AMD driver, or existing Proton installation was modified.

The actual successful log lines are:

```text
FSR: context created, render 640x360 -> 640x360, flags 0xA1 (DLSS flags 0x43), provider 4.1.1
FSR: context created, render 320x180 -> 640x360, flags 0xA1 (DLSS flags 0x43), provider 4.1.1
summary (feature destroyed): 32 frames evaluated, 0 evaluate failures, 0 context rebuilds since start
```

The GE11-7 log identifies FP8 support. It also contains unsuccessful optional
`amdxcffx64` upgrade-library loads; that DLL was not supplied in this test.
Those messages do not negate the separately confirmed SDK 4.1.1 contexts and
successful dispatches. Initial texture-sharing attempts also fail before the
existing simultaneous-access fallback succeeds. No checks were disabled and no
upstream code was changed to obtain the successful result.

The comparison changes the runner stack and uses a fresh test prefix. It does
not bisect an individual Wine, DXVK, vkd3d-proton, or amdxc patch.

## Probe and verification

`checks/fsr_inference_probe.cpp` loads the actual built `NIER_FSR4.dll` and calls
its exported NGX interface. It uses the same verified parameter-vtable layout as
the original mod. It does not include a substitute FSR implementation.

Inputs are synthetic HDR colour blocks/gradients, a static depth plane, and zero
motion vectors. Jitter is zero; history resets are requested on frames 0 and 8.
DebugChecking is enabled in the test-only INI. Camera values are supplied by that
INI instead of reading any game memory. The probe saves the final mapped GPU
output from each case as little-endian RGBA16F, respecting row pitch.

A small half-float decoding self-check is included. Build command and warnings
are retained in `evidence/fsr-inference-build.log`; MinGW emitted generic
GetProcAddress function-pointer-cast warnings, not build errors. No compiler
warning checks were disabled to make the build pass.

The raw probe's exit code establishes only dispatch/output sanity. The separate
strict verifier also requires both created contexts to be provider **4.1.1**,
all 32 successful evaluations, and valid raw RGB output. It was tested against
the real GE11-1 baseline as a negative control, which it correctly rejects.

From the project root, recheck the retained results:

```sh
python3 analysis/checks/verify_fsr_inference.py analysis/fsr-test-ge11-7
```

The following intentionally returns exit status 1:

```sh
python3 analysis/checks/verify_fsr_inference.py analysis/fsr-test
```

Machine-readable outcome: `evidence/fsr4-validation-summary.json`.

## Remaining work

1. Obtain explicit approval for backups and reversible deployment into the Steam
   game directory, and for registering/copying GE11-7 into Steam if needed.
2. Start with native AA only. Verify actual scene/depth/motion capture, camera
   cuts, HUD, transparency, and cutscenes, then add the established mods one by one.
3. True engine-resolution upscaling still requires changing NieR's rendering
   targets, viewport sizes, and compositing/HUD path. The synthetic 2x test proves
   backend support, not that those engine changes have been implemented.
4. DLSS5 neural rendering and frame generation remain separate, untested stages.

No game-level visual quality, latency, long-running stability, or performance
claim follows from these small, static synthetic tests.
