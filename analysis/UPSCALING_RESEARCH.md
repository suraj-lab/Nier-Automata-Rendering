# Engine-resolution upscaling: research decision

Date: 2026-10-19. Initial static research is preserved below. Subsequent camera
RE, logger correction, offline tests and isolated synthetic GPU validation are
recorded in [OFFLINE_VALIDATION.md](OFFLINE_VALIDATION.md). Both 3440×1440 native
and 1720×720→3440×1440 pass with FSR4.1.1, also through the synthetic logger/AA-proxy
device chain. These are not game integration or temporal-quality results.
The user cannot open NieR: no game launch, live game capture or installed changes.
The subsequent [motion-vector results](MOTION_VECTOR_RESULTS.md) resolve the
producer unit question; native-output routing remains unproven.

## Decision

Do not implement the proposed two-hook scaler yet. Intercepting allocation and
viewports may be useful, but it does not establish a reduced-scene → native-post
handoff. The bridge already supports unequal render/output resolutions; the
closed NIER_DLAA caller's resource routing is the immediate blocker.

## Source-backed findings

References below use `upstream/Nier-FSR4` commit
`32667ad4cb579f83798e78fe5df1589c731d010c`.

1. **The bridge is not native-AA-only.** `src/nier_fsr4.cpp:1510-1524` reads
   `Width/Height` separately from `OutWidth/OutHeight`. Dispatch at `1236-1258`
   uses a render extent and the actual output resource dimensions. Existing
   [synthetic results](FSR4_RESULTS.md) cover 320×180 → 640×360, not the game path.
2. **Changing OutWidth alone cannot enlarge a texture.** `Bridge::Ensure` at
   `716-817` creates shared textures from supplied resource descriptors. Evaluate
   at `1172-1196` reconciles context sizing with the actual output resource.
3. **There are two copy-backs.** The bridge copies its shared output into the
   supplied NGX Output at `1297`. The closed proxy then copies that Output into
   the original scene: `docs/REVERSE_ENGINEERING.md:72-80` and existing
   `evidence/dlaa-render-dispatch-function.json`, JSON pointer
   `/normalized_result/pseudocode`, decoded lines 524-526. The latter invokes
   context offset `0x178` (slot 47, CopyResource).
4. **The second copy blocks naive scaling.** Native Output cannot be copied into
   a reduced scene using CopyResource. Microsoft requires identical dimensions
   and says it “doesn't support any stretch.” A region copy does not stretch
   either. A distinct native downstream destination/routing arrangement must be
   identified before reducing scene allocations.
5. **The original logger was unsafe to reuse unchanged** (corrected later; see the validation report).
   `checks/d3d11_log_proxy.cpp:78-82` installs a viewport callback at slot 40,
   not RSSetViewports slot 44. This is a wrong-signature hook, not merely a bad log
   label. At `88-96` it loads system D3D11 directly, bypassing NIER_DLAA. Its two
   creation exports do not establish the original proxy's full export contract;
   delayed immediate contexts, deferred contexts and hook failures also need
   checking before a trustworthy integrated capture.

The initial pass spot-checked the sizing code, both copy-back references, and
logger slot/chain behavior without new decompilation. The subsequent offline
analysis below adds focused Ghidra evidence; no GPU test was performed.

## API constraints and unresolved game behavior

- [CopyResource](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicecontext-copyresource)
  and [CopySubresourceRegion](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicecontext-copysubresourceregion)
  require compatible in-bounds copies, not resampling.
- [OMSetRenderTargets](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicecontext-omsetrendertargets)
  requires matching MRT dimensions; do not resize one color attachment blindly.
  The cited page does not establish a universal equal-width/height DSV rule.
- Viewports do not update scissors, shader size constants, compute dispatches,
  or deferred-context recordings. Actual game usage remains unmeasured.
- [AMD FSR 4.1.1 integration guidance](https://gpuopen.com/manuals/fsr_sdk/techniques/super-resolution-ml/)
  requires coherent render/output extents, jitter, motion-vector scaling and
  depth metadata. Allocation histograms do not establish these contracts or
  locate the native post/HUD boundary.

## Offline continuation: allocator and consuming-draw boundary

The original DLL's SHA-256 was rechecked as
`f1c77c58fdd265b25dfa262c8660d49a4463a05bb0ee88daf732727f15e717ce`.
New analysis uses a separate snapshot,
`snapshots/NIER_DLAA_upscaling_offline_20261019.json`; the original snapshot was
not extended. Addresses/pseudocode are static observations, not executed behavior.

### What is now located

- **Allocator `0x180017e20`:** caches scene width/height/format and allocates all
  four targets at that same width/height (decoded pseudocode lines 23-24, 74-95,
  129-131): MV `DAT_1800abf60` is R16G16_FLOAT; depth `...bf68` is R32_FLOAT;
  Output `...bf70` uses the scene format; auxiliary `...bf78` is RGBA16F.
  There is no separate display-size allocation argument in this routine.
- **Texture helper `0x180019c50`:** creates one-mip/one-layer, single-sample,
  default-usage textures with the supplied dimensions/format and flags `0x88`
  (SRV|UAV). The SDK layout/enum assertions below corroborate this decoding.
- **Pre-dispatch gate `0x1800173c0`:** checks an immediate context (GetType),
  identifies two pixel-shader hashes (`0x68495c5bdcde8322`,
  `0x2c76d68a52500a65`), and obtains the texture behind PS SRV slot 0. It compares
  that texture's width/height with values returned by the camera getter before
  invoking `0x180018210` (decoded lines 63-74, 110-124). **Shrinking the scene
  without coordinating camera metadata can bypass AA entirely.** The precise
  camera-field semantics and necessary jitter adjustments remain to be traced.
- **Draw hook `0x180004130`:** invokes the gate before forwarding the game's Draw
  (decoded lines 32-38). This locates a candidate consuming-draw interception
  boundary, not a confirmed native post/HUD target. The active render targets,
  shader semantics, subsequent readers/writers and resource lifetimes are unknown.
- **Hook-install correction:** `0x180006480`, not `0x180005750`, installs context
  hooks. The latter installs DXGI factory swap-chain hooks. The device installer
  at `0x1800039c0` calls both. This corrects the earlier resume-note attribution.
- The bounded xref result for Output global `0x1800abf70` reports eight addresses,
  all within the allocator or dispatch. It reveals no separate native handoff;
  this does not exclude indirect aliases or other unobserved game consumers.

### New retained evidence

Each path is relative to this document's directory. Full records retain provider
limitations and decompiler uncertainty.

| File under `evidence/` | Evidence ID |
| --- | --- |
| `upscale-output-allocation-function.json` | `ev_e6fa1e38aefd2f6f9d153b42d887e9c249ae8309a5667b7de1000d2c2f6f21aa` |
| `upscale-texture-create-helper.json` | `ev_d7568cfaba61d3dd22a89b4d87e31a3ef3c7ed617efb30e51d91918fd4e54b6c` |
| `upscale-dispatch-caller-function.json` | `ev_92cc16a9eb1233c7e3bae75b13134fe7ec6c0d3a8f44e96139faa1515e2e31bb` |
| `upscale-draw-hook-function.json` | `ev_30bcfcc8dcb38b7165a487f1b3e47506e7395a78efdae64883143fe979f27e15` |
| `upscale-context-hook-install-function.json` | `ev_f1698019231c37d4860edbb479881e8c3c161b8bc570f102eb3faca4ed1d7f06` |
| `upscale-immediate-context-hooks.json` | `ev_755ed3d25514500d969e7e5a4f4099ad23243592853e98ae4cc6250c036f59ef` |
| `upscale-output-resource-xrefs.json` | `ev_8e1cf6f92b439d33f8400dfcc3e99953a006b08a945c440c143f2f90d2b5408c` |

### Checks completed without the game

Added [d3d11_abi_check.cpp](checks/d3d11_abi_check.cpp). It checks vtable slots,
callback types, texture descriptor offsets and format/bind enums used in the RE.
This passed with warnings treated as errors:

```sh
x86_64-w64-mingw32-g++ -std=c++17 -Wall -Wextra -Werror -fsyntax-only analysis/checks/d3d11_abi_check.cpp
```

This initial check was compile-only, not a Windows executable or GPU test. Slot
40 is DrawInstancedIndirect, conclusively not a viewport callback. The later
logger correction fixes the source; the older built DLL remains unchanged and
must not be reused. New isolated tests are described in the validation report.

Static PE inspection also reproduced 51 original exports, with creation ordinals
22/23, versus only two logger exports at 1/2. Names alone are not export parity.
A read-only scout independently audited logger initialization, optional outputs,
hook publication/failure handling and context coverage. Fixing only slot 44 is
not sufficient to preserve the working chain. Its full report is retained under
subagent run `7d290651-2a39-47a8-8522-a6fe3f64e539`.

## Revised validation order

1. Allocator, pre-consumer entry, camera/jitter state and motion-vector pixel units
   are now mapped. Next resolve dimension-source typing and native output routing.
   Do not equate a shader hash match with HUD semantics.
2. The measurement-only logger correction and isolated immediate/deferred tests
   now pass. Resource/binding/copy/NGX correlation and remaining creation/recreation
   paths need further offline coverage before a useful game capture.
3. With explicit live-game authorization, capture resource identities/descriptors,
   bindings, copies, viewport/scissor state and NGX sizing across a native-AA
   frame. Preserve the working chain; restore and hash-check after temporary use.
4. Only once the native handoff is established, prototype one fixed render scale
   with coherent depth/MVs/jitter and native post/HUD. Retain native-AA regression
   checks and the 60 FPS cap. Dynamic resolution and frame generation are later.

No exact binary patch or performance benefit is established. Merely retaining a
native texture and shrinking its viewport is not proven to reduce all scene work.

## Research provenance

Workflow `20048dbc-f703-4c5d-9952-ebe2bdc4bed4` completed two read-only children:
`local-sizing-contract` (`f7cd711b-b6f8-4e8f-a713-52421e2f2d7b`) and
`api-feasibility` (`3eef8e01-a980-46b8-b0f8-59167ffb61d5`). Full reports are
retention-managed subagent artifacts; this file preserves the actionable synthesis.
Upstream checkouts remain clean. This initial pass added the compile-only ABI
check; the subsequent authorized implementation changed workspace logger/probe
sources and added native/Python tests. The production bridge source and installed
game, saves, configs, runner selection and system settings were not changed.
No game-quality or performance claims were added.
