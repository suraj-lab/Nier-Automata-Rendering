# NieR:Automata rendering investigation

## Scope and status

Status refreshed 2026-10-27 (late evening). Intent and per-platform plan: [VISION.md](VISION.md).

Status refreshed 2026-10-27 (evening). [PROGRESS.md](PROGRESS.md) is the authoritative resume record (installed
hashes, rollback chain, verified facts, next steps); its top "Checkpoint" section is the place to start.

| Area | Status |
| --- | --- |
| FSR4.1.1 native AA | Working in-game at 3440x1440 (NIER_DLAA, now chained behind our proxy as `d3d11_dlaa.dll`). |
| Resolution upscaling | **Working:** Custom75 renders 2580x1080 and FSR4 upscales to 3440x1440 (user-confirmed). |
| Startup settings | `NIER_RENDER.ini` selects Native / Custom75 for the next launch; honest startup status. |
| In-game menu | **Installed, live-tested:** Insert panel, save-for-next-launch, mouse/camera blocked while open. |
| RTX Remix | **Textured** path-traced stills from one F9 capture (190 albedo textures, 2.74M triangles). Not live in the game. |
| Remix live in NieR | **Pipeline fully proven, nothing in-game yet** (2026-10-27): frame leaves the runtime (`CopyRenderingOutput(FINAL_COLOR)`, 0.49 ms @1080p), reaches a **D3D11 texture in the same process** with DXVK and Remix each holding a Vulkan device (1.78 ms), and per-draw submission costs 0.24 µs (3000 draws = 0.73 ms). Render: 21 fps native / 48 XeSS Quality / **60.65 XeSS Performance = the game's own cap**. Remaining: in-game host, live draw stream, UI fallback, visual quality. See [VISION.md](VISION.md), [LIVE_TRANSFER.md](analysis/LIVE_TRANSFER.md), [LIVE_IN_GAME_PLAN.md](analysis/LIVE_IN_GAME_PLAN.md). |
| Visual stack | LodMod + WAX texture injection; 289 textures active. Special K quarantined. |
| DLSS 5 NR | Parked: blocked on a legitimately obtained `nvngx_dlssnr.dll`. |
| Frame generation | `lsfg-vk` excluded by decision. Desktop: native FSR FG would need a DX12 present takeover (proxy owns Present and already has colour/depth/MVs) — unbuilt. Laptop: DL frame generation available. Native 60 FPS cap kept (research in `analysis/FAR_*.md`). |

### Documentation by stage

1. Native AA and visual stack: `analysis/NATIVE_AA_INSTALL.md`, `analysis/VISUAL_STACK.md`, `analysis/FSR4_RESULTS.md`.
2. Upscaling research: `analysis/UPSCALING_RESEARCH.md`, `GAME_RENDER_SCALE.md`, `VIEWPORT_RESULTS.md`,
   `DEPTH_SCALE_RESULTS.md`, `MOTION_VECTOR_RESULTS.md`, `ROUTING_RESULTS.md`, `FRAMEDUMP_RESULTS.md`.
3. Upscaling patch and deployment: `analysis/SCALE_SETTER.md`, `PART3_REDIRECT.md`, `UPSCALING_PATCH.md`,
   `analysis/deploy/README.md`.
4. Startup settings and saving: `analysis/STARTUP_SETTINGS.md`, `SETTINGS_WRITE_PLAN.md`.
5. Menu design and preview: `analysis/menu-design/README.md`, `analysis/menu-preview/README.md`.
6. In-game menu, mouse fix, F9 capture (with install history): `analysis/IN_GAME_MENU.md`.
7. RTX Remix (feasibility -> first mesh -> scenes, verified transforms): `analysis/REMIX_FEASIBILITY.md`,
   `analysis/remix-probe/README.md`.
   Live transfer (solved, with measurements and the API-order rules): `analysis/LIVE_TRANSFER.md`,
   `analysis/INTEROP_API.md`.
8. Frame-rate research (parked): `analysis/FAR_RESEARCH.md`, `FAR_UNCAP_FOLLOWUP.md`.

Use **GE-Proton11-7-x86_64**, in-game Anti-Aliasing **Off**, Motion Blur **On**:

```text
WINEDLLOVERRIDES="d3d11=n,b;dinput8=n,b;dxgi=n,b" mangohud gamemoderun %command%
```

`d3d11.dll` is our proxy (upscaling, menu, capture) and chains to `d3d11_dlaa.dll` (FSR4 AA);
`dinput8.dll` supplies LodMod, and `dxgi.dll` supplies WAX. The game uses the Windows 10 executable. WAX gameplay patches,
including inventory auto-purge and FPS uncap, remain disabled. The native
**60 FPS cap stays in place**: upscaling is for GPU headroom, not an FPS unlock.

Static patch checks, Ghidra analysis, and isolated Proton loader/GPU interop
checks passed. The loader/ABI test passed 36 assertions; GPU sharing passed two
synthetic colour roundtrips; actual FSR4.1.1 passed 32 synthetic frames across
native-AA and 2x upscaling cases. **Synthetic upscaling is not game integration.**
GE-Proton11-1 fell back to FSR 3.1.5; GE11-7 created provider 4.1.1 contexts.
Real-game evaluation was recorded through frame 14400; see
`analysis/evidence/first-live-game-verification.json` and
[FSR4 results](analysis/FSR4_RESULTS.md).

**Visual/temporal quality and performance gains are not independently verified.**

## Historical baseline (before deployment; not current configuration)

- Game: `/mnt/second/SteamLibrary/steamapps/common/NieRAutomata`
- Steam app ID: `524220`; manifest build ID: `7020666`.
- `NieRAutomata.exe`: x86-64 PE, 17,786,752 bytes.
- Executable SHA-256:
  `042e9fef839eb1c7722cee971d5f50c132b018ec02aa0d4ae38dbc62d5a9daa8`
- Static imports include `d3d11.dll` and `dxgi.dll`.
- Selected Proton: `GE-Proton11-1`.
- Steam launch options: `mangohud gamemoderun %command%`.
- Vulkan diagnostic: RX 9070 XT, RADV GFX1201, Mesa `26.2.4-arch3.1`.
- The selected GE-Proton installation's DXVK DLLs contain the version string
  `v2.7.1-822-g8c9b4822dd40d350`. This does not prove which DLLs a live game loads.
- Earlier read-only inventory found `FAR.ini`, `d3d11.ini`, and historical logs
  identifying Special K `25.12.2.5`, but no root `d3d11.dll` or `dxgi.dll`.
  Those remnants do not establish that Special K is currently active.
- `FAR.ini` contains `UncapFPS=true`; review before runtime baseline testing.

Local identity/import inspection used Python's standard library and `objdump`.
Subsequent Ghidra findings for the exact mod proxy are in `analysis/RESULTS.md`;
no decompilation of the game executable itself is claimed.

## Upstream frozen for this investigation

Repository: https://github.com/yogesh1239/Nier-FSR4

Commit: `32667ad4cb579f83798e78fe5df1589c731d010c`.

The checkout was clean before and after inspection. No upstream files were edited.

Relevant files, relative to `upstream/Nier-FSR4`:

- `docs/REVERSE_ENGINEERING.md`: documented NIER_DLAA hooks and NGX interface.
- `tools/patch_mod.py`: exact-build SHA-256 guard and NGX loader replacement.
- `src/nier_fsr4.cpp`: D3D11/D3D12 interop and FSR provider dispatch.
- `tests/smoke.cpp`: loader, exports, parameter ABI, and unwind smoke checks.
- `.github/workflows/release.yml`: build pipeline and pinned output hashes.
- `third_party/NIER_DLAA/README.md`: binary provenance and redistribution caveat.

## Checks performed: passed

The bundled original NIER_DLAA 1.1 proxy matches the patcher's input hash:

`f1c77c58fdd265b25dfa262c8660d49a4463a05bb0ee88daf732727f15e717ce`

Ran the upstream Python patcher against that DLL in a temporary workspace, and
checked with assertions that:

1. The loader stub is exactly 41 bytes.
2. The patched output matches the SHA-256 pinned by upstream CI:
   `3d628eb576b505180206653d72e4e4da6a4345334f19863256ab5b10e06b6915`.
3. File length is unchanged; all 42 changed bytes fall within the 41-byte loader
   stub and four-byte unwind-header regions, at file offsets `0x21da0` and
   `0x650f0` respectively.
4. The output contains the expected loader stub and unwind header.
5. A one-byte-modified input is rejected with exit status 1 and no output file.

Temporary outputs were removed automatically. Original DLL and game executable
were not patched. These are static patcher checks, **not** the Windows/Wine or GPU
smoke test.

## Source findings and remaining gates

### Existing integration is native AA, not engine-resolution upscaling

Upstream documents capture of HDR scene colour, camera jitter, generated depth
and camera motion, and character motion from the game's velocity pass. Static
strings in the bundled proxy corroborate those intended roles, but do not prove
that the hooks execute successfully on our game build.

The proxy requests input and output at the same resolution. Character motion
requires the game's motion-blur pass; upstream advises leaving Motion Blur on
while the mod suppresses the visual blur.

Actual lower-resolution upscaling still needs render-target/viewport changes,
full-resolution HUD treatment, and correct downstream post-processing sizes.

### The first Proton-specific runtime gate is cross-API sharing

`src/nier_fsr4.cpp` requires:

- `ID3D11Device5` (around line 543) and `ID3D11DeviceContext4` (around line 665).
- A same-adapter D3D12 device, selected using the D3D11 adapter LUID (lines 550-595).
- Shared fences in both directions (lines 620-654).
- Shared D3D12 textures opened in D3D11 (lines 750-808).
- Ordered D3D11 copy/signal -> D3D12 wait/dispatch/signal -> D3D11 wait/copy-back
  (dispatch path around lines 1200-1297).

For our Proton stack, those calls cross DXVK and vkd3d-proton. The isolated probe
now passes shared-resource creation and byte-exact colour roundtrips using the
existing bridge, with a GPU copy in place of FSR dispatch. It requires the
bridge's existing simultaneous-access fallback. Subsequent actual FSR4 dispatch
also passes under GE11-7 (see phase 3); real-game operation was subsequently observed, but frame-pipelined performance
remains unbenchmarked.

### Verify the provider that actually succeeds

The bridge enumerates providers and explicitly falls back to other versions if
the requested one fails (`src/nier_fsr4.cpp`, around lines 998-1088).
An image being processed, or a log listing an available FSR4 provider, is not
proof that FSR4 was ultimately used. Inspect the successful provider and context
creation logs; rule out FSR 3.x/2.x fallback.

### Existing smoke test is not a GPU integration test

`tests/smoke.cpp` checks loader dispatch, exported entry points, parameter vtable
slots, and unwind metadata. It does not create a real D3D11/D3D12 rendering device
or dispatch FSR against a real game frame. CI runs that smoke test on Windows.

### Historical native-AA deployment checks

The user installed Ghidra 12.1.2, JDK 21, and MinGW GCC 16.2. REA native analysis
works through its existing CLI with process-local Ghidra/JDK settings. Persistent
MCP and system configuration were not changed.

The bridge and tests build successfully. Loader/ABI and GPU-sharing checks pass
under GE11-1, but actual FSR4.1.1 requires GE11-7 in the tested configuration.
Official SDK 2.3.0 runtime hashes match the bridge's pins, and a strict verifier
rejects the older-provider fallback. See `analysis/FSR4_RESULTS.md`.

## Next milestone: engine-resolution upscaling

Research found that the FSR4 bridge already supports unequal sizes, but the
closed proxy copies Output back into the scene. Native Output cannot be copied
into a reduced scene texture. Allocation/viewport hooks alone cannot solve this.
See the [source-cited research decision](analysis/UPSCALING_RESEARCH.md).

1. Allocator, pre-Draw gate, camera/jitter fields, motion-vector units and the
   camera-dimension source (swap-chain size at Present) are mapped. Next design a
   native destination outside the proxy's equal-size copy-back. See
   [routing results](analysis/ROUTING_RESULTS.md).
2. The measurement logger is corrected and passes isolated immediate/deferred
   tests. Expand resource/binding/copy correlation and remaining creation-path
   tests before attempting a game capture.
3. With separate live-game approval, capture native-AA resource flow while keeping
   the working chain intact; do not change dimensions during this capture.
4. Only after establishing the handoff, test a fixed-scale prototype, then GPU
   headroom and temporal quality at the unchanged 60 FPS cap.

The user cannot open the game: live game validation and installed-file changes
remain deferred. Authorized isolated RX 9070 XT tests passed **3440×1440 native**
and **1720×720→3440×1440** with FSR4.1.1, including a logger→renamed-AA-proxy
D3D11 device-chain test (**64 total synthetic evaluations**, no failures).
Native/sanitized hook tests, SDK checks, seven verifier tests and export parity
pass. This does not validate the closed mod's game dispatch, native HUD, temporal
quality or performance. See [offline validation](analysis/OFFLINE_VALIDATION.md).

The motion-shader follow-up confirms pixel/current-to-previous units in both
producer branches. The extracted compute shader also passes ten synthetic GPU
cases in each of FP16/FP32 output formats; the object pixel shader remains static
analysis only. See [motion-vector results](analysis/MOTION_VECTOR_RESULTS.md).

See [PROGRESS.md](PROGRESS.md) for safe resume steps. Frame-generation testing
follows; DLSS 5 NR remains blocked separately.

## Distribution boundary

Upstream includes a third-party mod binary, and its README says redistribution
permission is the repository owner's responsibility. A root source license was
not present in the inspected checkout. Do not assume permission to redistribute
the bundled proxy, modified binaries, game content, or NVIDIA model weights.
