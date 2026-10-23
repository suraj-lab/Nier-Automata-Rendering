# Phase 2: native analysis and isolated Proton checks

Historical phase record. Actual FSR4.1.1 dispatch was subsequently validated in
[phase 3](FSR4_RESULTS.md); its runner requirement and limitations are recorded there.

## Outcome

- Ghidra/REA native analysis works.
- The unmodified FSR4 bridge source compiles locally with MinGW.
- Upstream loader/parameter smoke test: **36 assertions passed, zero failed**.
- Synthetic D3D11 -> D3D12 -> D3D11 GPU roundtrip: **passed**, with byte-exact
  readback for RGBA16_FLOAT and R11G11B10_FLOAT colour textures.
- No FSR inference, game rendering, DLSS5 NR, or frame generation was tested.

No Steam game files, saves, game launch options, or existing game prefix were
modified. The original executable's SHA-256 was rechecked unchanged. The
upstream checkout remains clean. All builds, analysis artifacts and the new
Proton prefix are under this workspace.

## Tooling and configuration

Installed by the user and verified using `pacman -Q`:

- `ghidra 12.1.2-2.1`
- `jdk21-openjdk 21.0.12.1.u1-2`
- `mingw-w64-gcc 16.2.0-2.1`

Ghidra root, obtained from the package manifest: `/opt/ghidra`.
JDK root, obtained from the Java executable: `/usr/lib/jvm/java-21-openjdk`.

REA's existing public CLI launcher was used:
`/home/suraj/.npm/_npx/af752b90495482d7/node_modules/.bin/rea` (version 6.4.0).
Its process environment set `GHIDRA_INSTALL_DIR`, `JAVA_HOME`, `TMPDIR` and
`HOME` for the analysis invocation only. No persistent MCP, shell, or system
configuration was edited. The already-connected MCP process was not reconfigured.

Provider diagnostics are retained in `evidence/provider-check.json`. They report
Ghidra available, including the matching Linux x86-64 native decompiler. REA's
CLI closes its owned ephemeral native sessions on completion; a reusable
provider-neutral snapshot is in `snapshots/NIER_DLAA_1.1.json`.

## Native observations: exact NIER_DLAA 1.1 proxy

Input: `input/NIER_DLAA_1.1.dll`, a workspace copy of the bundled original.
SHA-256: `f1c77c58fdd265b25dfa262c8660d49a4463a05bb0ee88daf732727f15e717ce`.

### NGX loader, `0x1800229a0`

The recovered function constructs NGX library paths and searches application
and NVIDIA registry locations. Ghidra finds one caller at `0x18001ffc0`.
This corroborates the documented location used by upstream's exact-build loader
replacement; it is not evidence of successful FSR execution.

Evidence: `evidence/ngx-loader-function.json`:
`ev_be528ac32f0a6a8724e12ace691de08ab4667de31a604df9dd9129db9a390b70`.

### NGX evaluation parameter helper, `0x180019f20`

Recovered code transfers Color, Output, Depth, MotionVectors, jitter, reset,
motion-vector scale and render-subrectangle dimensions to NGX parameters before
calling the evaluation wrapper. It also forwards optional generic NGX fields;
that does **not** mean the game supplies valid data for every optional field.

Evidence: `evidence/ngx-evaluate-params-function.json`:
`ev_27ddc4ebb00b9dab3ad0d98e9eb3aa3c5a891fc13f0e42b53bc371b02a407296`.

### Render dispatch, `0x180018210`

The recovered caller:

- Restricts scene colour to RGBA16F or R11G11B10F and one sample.
- Skips processing without recognized camera constants or a depth target.
- Sets Width and OutWidth to the same scene width; Height and OutHeight to the
  same scene height; requests DLAA quality value 5 and flags `0x43`.
- Supplies the scene texture plus output/depth/motion-vector globals to the
  parameter helper.
- On successful evaluation, invokes the D3D11 context vtable slot at `0x178`,
  consistent with `CopyResource`, to copy the mod output into the scene texture.

This is direct static evidence for a native-AA, same-resolution integration.
Simply requesting a lower FSR quality setting does not resize the game's scene
or provide a separate full-resolution compositing/HUD path.

Evidence: `evidence/dlaa-render-dispatch-function.json`:
`ev_0786e85e94c2c3a424ad0b893af1ab09c2a6595c68c8c922169160cf17524326`.

These findings come from Ghidra pseudocode, references and assembly, not the
original mod source or a game execution trace. Ghidra's records preserve flow,
no-return and indirect-reference limitations. The game executable itself was not
decompiled in this phase.

## Loader/ABI runtime checks

Built `build/NIER_FSR4.dll` from the pinned upstream source without editing it.
Built upstream `tests/smoke.cpp` and a minimal file-output wrapper,
`checks/proton_abi_smoke.cpp`. The initial console-only invocation exited 0 but
its assertion output was not captured; that alone was not treated as a verified
pass. The wrapper records the same upstream assertions directly to a file.

Ran under the installed GE-Proton11-1 with a newly created compatdata directory:
`runtime/proton-test` (not Steam app 524220's compatdata).

The recorded run passed 36 assertions covering the patched loader, selected
backend module, expected exports, unwind metadata and parameter ABI.

- Results: `build/abi-check-results.txt`.
- Bridge log: `evidence/abi-recorded-NIER_FSR4.log`.
- Build commands/output: `evidence/bridge-build.log`,
  `evidence/smoke-build.log`, `evidence/abi-recorder-build.log`.

## Real GPU interop probe

`checks/gpu_interop_probe.cpp` includes the pinned upstream bridge implementation
and links its existing parameter implementation. It does not reimplement the
resource-sharing code, load the AMD FSR runtime, or load the game.

The self-check creates a hardware D3D11 device, lets the existing bridge create
its same-adapter D3D12 device and shared fences, and exercises:

1. Shared colour/output creation for RGBA16_FLOAT (DXGI 10), then R11G11B10_FLOAT
   (DXGI 26). Shared depth R32_FLOAT (41) and motion R16G16_FLOAT (34) creation.
2. D3D11 upload/copy and ready-fence signal.
3. D3D12 wait, GPU copy between the shared colour and output textures, and
   done-fence signal.
4. D3D11 wait, staging readback, and row-pitch-aware byte comparison against a
   known nonzero input pattern.

Both colour roundtrips passed. Depth and motion shared-resource creation passed;
their contents were not roundtripped. The probe deliberately uses a GPU copy
rather than a compute/FSR dispatch. It flushes D3D11 and waits for D3D12 completion
for deterministic validation, so it does not establish frame-pipelined performance
or the absence of a synchronization problem in a production dispatch loop.

The bridge log identifies the physical adapter as RX 9070 XT (RADV GFX1201).
All shared texture types required the existing simultaneous-access fallback:
flags `0x21` for inputs and `0x25` for UAV output. No source change was needed.

- Results: `build/gpu-interop-results.txt`.
- Bridge/adapter/sharing log: `evidence/gpu-interop-NIER_FSR4.log`.
- Build command/output: `evidence/interop-probe-build.log`.

The probe uses tiny 16x16 resources and two colour roundtrips. This proves that
basic sharing works in this test environment, not game-scale performance,
long-running stability, correct FSR computation, or temporal image quality.

## Re-running the tests

Build commands are recorded verbatim in the build logs listed above. From this
`analysis` directory, with the two test executables built:

```sh
ROOT="$PWD"
PROTON="$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton11-1/proton"
export STEAM_COMPAT_DATA_PATH="$ROOT/runtime/proton-test"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.local/share/Steam"
export STEAM_COMPAT_INSTALL_PATH="$ROOT/build"
export SteamAppId=0 SteamGameId=0 WINEDEBUG=-all
export WINEDLLOVERRIDES='mscoree,mshtml='
export DXVK_LOG_PATH="$ROOT/evidence"
export MESA_SHADER_CACHE_DIR="$ROOT/runtime/shadercache"
cd "$ROOT/build"
"$PROTON" run "$PWD/proton_abi_smoke.exe" \
  "Z:${PWD//\//\\}" "Z:${PWD//\//\\}\\mod_proxy.dll"
"$PROTON" run "$PWD/gpu_interop_probe.exe"
```

The commands use Bash path substitution. Test result files and test application
logs in `build` are regenerated on a rerun. Inspect the result files, not just
the Proton launcher's exit status or console output.

## Next gates

1. Obtain the official signed AMD FSR SDK 2.3.0 loader/upscaler DLLs matching the
   vendored headers. They are not yet present in the test build.
2. Run a synthetic FSR context creation/evaluation test and verify the provider
   that actually succeeds is FSR4, not an older fallback.
3. Plan backups and reversible game deployment before touching the Steam copy;
   validate scene/depth/motion recognition and history behavior in-game.
4. Keep true resolution upscaling, DLSS5 NR and frame generation separate from
   native-AA validation. Do not infer support for any of those from this phase.
