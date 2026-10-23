# Offline work and isolated GPU validation — 2026-10-19

Later continuation: [motion-vector results](MOTION_VECTOR_RESULTS.md) resolves
both shader branches' pixel-unit convention and records extracted-CS GPU checks.
The FSR dispatch tests below remain a separate, earlier validation stage.

## Scope

The user cannot open NieR. No game launch, live game capture, installed DLL swap,
save/config change, package installation, commit or push was performed.
The later GPU request was exercised with a synthetic executable in a new
workspace-only Proton prefix, private HOME/client-data/cache/log directories.
A Wine prefix is not a security sandbox; these were trusted local test binaries.

## Results

| Check | Result | Does not establish |
| --- | --- | --- |
| Logger/probe MinGW builds with `-Wall -Wextra -Werror` | Pass | Game compatibility |
| SDK ABI/layout compile check | Pass | Runtime interface usage |
| Linux hook registry test, including ASan/UBSan | Pass | Every Windows patch/protection failure |
| Verifier unit tests | 7 pass | Temporal image quality |
| Retained 640×360 GPU output verification | Pass; FSR3 negative control rejected | A fresh baseline GPU run |
| Synthetic native 3440×1440 and 1720×720→3440×1440 | 32 evaluations, provider 4.1.1, zero failures | Engine-resolution scaling |
| Same resolutions through logger→renamed AA-proxy device chain | Another 32 evaluations; immediate/deferred viewport logs pass | Game's closed-mod evaluate/copy-back path |

All four saved RGBA16F outputs have 39,628,800 bytes each. Independent CPU
verification checks provider identity, exact case/context dimensions, evaluation
count, completion, finite/non-sentinel RGB, spatial variation and bounded range.
There is no FPS, latency, power, memory-peak or temporal-quality benchmark here.
The synthetic inputs retain zero motion/jitter and a constant depth plane.

Actual selected GPU: RX 9070 XT, RADV GFX1201, Mesa 26.2.4. The bridge selects the
same D3D11/D3D12 adapter. Independent builds ran in parallel; decompilation is
CPU-bound, and extra GPU load would not accelerate it.

## Logger changes

Sources: `checks/d3d11_log_proxy.cpp`, `.def`, `d3d11_hook_registry.h`,
`d3d11_hook_registry_test.cpp`, and `d3d11_abi_check.cpp`.

- Correct viewport slot 44; recover originals per vtable slot rather than globally.
- Checked page-protection changes and compare/exchange publication; failure
  diagnostics explicitly invalidate incomplete captures.
- Thread-safe one-time sibling `d3d11_dlaa.dll` loading; no system-runtime fallback.
  Process-lifetime residency prevents simple dangling hook pointers on unload.
- Both creation exports log and recover optional device/immediate-context outputs;
  successful base CreateDeferredContext calls install viewport observation too.
- Texture records include result, object identity and sample quality. Zero-count
  viewport calls are logged; each detail line has context and PID/TID attribution.
- All 51 original export names/ordinals are preserved. Creation wrappers remain
  ordinals 22/23; the other 49 are exact `d3d11_dlaa.NAME` PE forwarders.

New build: `build/offline-logger/d3d11.dll`, SHA-256
`f5c779862e5b4155595ac6ff36fdf13eb533b8bcb235e7f200af05abf64eb7a7`.
Full export comparison: `build/offline-logger/export-verification.json`.
The older `build/d3d11_log_proxy.dll` was not replaced.

Fresh review found a viewport attribution issue, which was fixed; follow-up found
no further issues (review runs `9518ddda-f568-4c85-8f8e-58f00e1bfba2`,
`2bf26502-8951-407e-b40c-a3304a3c4c0b`). This is not deployment approval.

The synthetic chain test actually loaded the retained patched AA fixture renamed
`d3d11_dlaa.dll`, SHA-256
`3d628eb576b505180206653d72e4e4da6a4345334f19863256ab5b10e06b6915`.
NIER_DLAA logs report MH_OK immediate/deferred hooks. Logger records show both
context types, unchanged 3440×1440 viewports and zero-count unbinds, with no hook
errors. A warning about the runtime lacking D3D11CreateDeviceForD3D12 remains;
that unrelated export was not exercised. Export parity is not proof every API is
implemented by the downstream runtime.

**Limit:** the probe calls the bridge's NGX exports directly. Loading the AA proxy
and creating its device does not trigger its game-specific camera/shader/evaluate
path. Multi-device re-hooking, newer deferred APIs, swap-chain creation, all
optional-output combinations, page-protection failure injection, unload, render
binding/copy flow and actual game performance remain unvalidated. This logger
still measures allocation/viewports, not a complete render graph. Do not deploy it
on the strength of this test alone.

## Camera/jitter findings

Static-only source: original NIER_DLAA DLL, SHA-256
`f1c77c58fdd265b25dfa262c8660d49a4463a05bb0ee88daf732727f15e717ce`.
Evidence and verbatim pseudocode: `offline-camera/`; the complete 15-record
Evidence-ID index is `offline-camera/evidence-index.json`. Parent spot-checked
producer, setter and jitter operations and verified target digests.

| Camera-copy offset, base `0x1800abe20` | Static interpretation |
| --- | --- |
| +0x00 / +0x04 | Source token / accepted-camera sequence |
| +0x08 / +0x0c | Float width / height |
| +0x10 / +0x14 | Generated pixel-domain jitter X / Y |
| +0x18..+0x57 / +0x58..+0x97 | Two unjittered matrices; second strongly supported as projection |
| +0x98 / +0x9c / +0xa0 | Position candidates, corroborated by distance reset |
| +0xa4 / +0xa8 | Near / far-minus-near candidates |

Key observations:

- Getter `0x180015c80` copies 0xac bytes only when camera state is valid.
- Producer **0x180015510** (`camera-producer-180015703.decoded.c:112-211`)
  generates a 32-entry repeating Halton(2,3)-style sequence. It publishes
  unjittered camera state and pixel jitter before mutating mapped matrices.
- Projection mutation uses `(2*jx/W, -2*jy/H)`. Camera acceptance requires
  valid projection structure and aspect matching W/H within 1%.
- Setter `0x180016cd0` casts incoming dimensions to float. Its recovered caller
  `0x1800054c0` uses an indirect +0x60 descriptor call. Display/swap-chain sizing
  is a supported inference, not established interface identity.
- The dispatch gate compares scene dimensions with camera W/H. NGX jitter is
  `sign*jx*(sceneW/W)` and corresponding Y; MV scale is 1.0. The sign helper
  `0x180019c20` is not the jitter generator.
- Compute state capture/restore covers CS shader/classes, SRVs, UAVs, constant
  buffers and samplers. It does not prove complete graphics-state preservation.

Representative retained evidence:
`camera-getter-function.json` (`ev_2a9874c4bc21a9628812fa17232d11d92c9b64c6888b0c20ff823f9226a4b667`),
`camera-producer-180015703.json` (`ev_5c9aa3a4d12bd56f294f2967d022a2c4bfbef17ca89eae998e164a628a32f866`),
`detail-180015be0.json` (`ev_5505a12e4771876e0331e0ff1282f0bacd5cfc4f4a4ecf87d11c408d086994a4`).

## Reproduction and artifacts

Private test root: `isolated-gpu-3440-20261019/`.

- `work/`: first GPU run, no outer logger; `verification.json` at test root.
- `logger-work/`: second run, logger plus renamed patched proxy;
  `logger-verification.json` at test root.
- `launch-manifest.json`, `logger-launch-manifest.json`: exact command/cwd and
  input hashes; second run intentionally reuses only the first private prefix.
- `logs/`, `logger-logs/`: Proton/launcher/DXVK logs; `compatdata/`, `steam-client/`,
  `home/`, `config/`, `data/`, `cache/`: private state, not installed Steam/game data.

Probe defaults remain 640×360. Its build-only `PROBE_WIDTH/PROBE_HEIGHT` constants
select the test size; no production bridge change was needed. Verifier defaults
remain compatible with retained 640×360 results; its Python API accepts expected
width/height without inferring them from potentially incorrect runtime output.

```sh
python3 analysis/checks/test_verify_fsr_inference.py
x86_64-w64-mingw32-g++ -std=c++17 -Wall -Wextra -Werror -fsyntax-only analysis/checks/d3d11_abi_check.cpp
g++ -std=c++17 -Wall -Wextra -Werror -pthread analysis/checks/d3d11_hook_registry_test.cpp -o analysis/build/offline-logger/registry-test
analysis/build/offline-logger/registry-test
```

## Next unresolved seam

Motion-vector shader units have since been established; see the continuation
linked above. Before scaling, type the indirect dimension source and design a
reduced-input/native-output routing strategy that respects camera/jitter/grid
calibration and the closed proxy's final CopyResource. The game's actual post/HUD consumers still require a later approved
capture. No texture-resizing or binary-patch prototype was deployed.
