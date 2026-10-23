# Visual stack: LodMod + WAX texture injection

## Current recorded state (documentation refreshed 2026-10-19)

The later 2026-10-18 session supersedes the deployment notes below. See
[PROGRESS.md](../PROGRESS.md) for authoritative installed hashes and rollback notes.
This documentation refresh did not re-test the game.

- FSR4 native AA + LodMod + WAX are working in the recorded setup.
- WAX's `dxgi.dll` replaces the blocked Special K route; Special K is quarantined.
- The Lite texture pack is active through WAX: 289 textures reported active.
- The Windows 10 game executable is installed; Steam verification can restore
  scripts that re-select the incompatible executable. See the resume record.
- WAX gameplay patches, inventory auto-purge, and FPS uncap stay disabled.
- afmf-linux is installed but dormant; in-game frame generation is untested.

Current launch options with **GE-Proton11-7-x86_64**:

```text
WINEDLLOVERRIDES="d3d11=n,b;dinput8=n,b;dxgi=n,b" mangohud gamemoderun %command%
```

Keep in-game Anti-Aliasing off, Motion Blur on, F8 as the AA toggle, and the native
60 FPS cap. Do not substitute the historical Special K DLL for WAX.

## Historical deployment and diagnosis

Everything below records the earlier LodMod-only phase, including its old launch
options, staged-texture status, and next steps. It is not the current setup.

### Earlier result

Installed **LodMod 0.77.5 only** beside the existing, unchanged FSR4 native-AA
package. The complete visual stack is **not** installed or validated yet.

Added game-root files:

- `dinput8.dll`: LodMod's multi-API proxy, renamed from the user's `xinput1_4.dll`.
- `LodMod.ini`: complete author config/filter tables, with three preset changes.

The existing `d3d11.dll`, FSR4 DLLs/config, F8 toggle, game executable, old FAR
configs, and latest saves were hash-checked unchanged. No FPS unlock or frame
generation was added. The game was closed throughout deployment.

Installation manifest: `evidence/visual-stack-installation.json`.
Fresh private backup: `../backups/visual-stack-20261018T210248Z/` (nine files,
including saves after the latest user play session and current mod configs).

## Historical launch options for the LodMod-only test

Keep **GE-Proton11-7-x86_64** selected. Add the DirectInput proxy override:

```text
WINEDLLOVERRIDES="d3d11=n,b;dinput8=n,b" mangohud gamemoderun %command%
```

The previous options containing only `d3d11=n,b` are insufficient to explicitly
select the new DirectInput proxy. No live Steam VDF settings were edited.
Do not add a local `dxgi.dll` from the staging folder yet.

Keep in-game Anti-Aliasing off and Motion Blur on. F8 (Moonlander layer 2,
physical 8 key) remains the native-AA toggle. Leave the normal 60 FPS limit in
place during visual-stack validation.

## LodMod preset and provenance

User-supplied archive:
`~/Downloads/Automata-LodMod-165-0-77-5-1735827200.zip`

Archive SHA-256:
`89312cb5370a81506916bb4d3e20ce07ac6a51ff56d76e033e8358b259cca84d`

Proxy SHA-256:
`06c5e5f1b3f4675f6d09fcaa81a6b5326b74e15a3d12312678527df68922c919`

The official source at `../upstream/NieRAutomata-LodMod`, commit
`fc7316bd3309ab38eb2a4016a96f9282d285fb90`, documents a multi-API wrapper including
DirectInput and checks game-build header timestamps. Our executable's timestamp
1624484031 at header offset 0x1a8 matches its Steam/Win7 (2021) entry and occurs in
the shipped mod binary. This is a static build-recognition check, not exhaustive
validation of every runtime patch.

Starting settings:

| Setting | Installed | Author archive default |
| --- | --- | --- |
| LODMultiplier | 10 | 0 (disable LODs entirely) |
| ShadowResolution | 4096 | 8192 |
| ShadowDistanceMinimum | 35 | 70 |
| DisableManualCulling | true | true |

The source comments recommend 10 or above (or disabled LODs) for reducing AO bleed.
The smaller shadow-resolution/distance pair is a conservative profiling starting
point, not a measured optimum. Other author settings/filter tables are intact.
Those tables contain duplicate keys under their Windows INI semantics; they were
not rewritten merely to satisfy Python ConfigParser's stricter parser.

In-game validation still needs to check distant geometry, shadows, traversal and
whether any filtering produces unexpected visible models. The heavier defaults
can be considered after measuring the actual visual stack.

## Texture assets: verified and staged, NOT ACTIVE

The downloaded Lite archive contains **292 DDS files**, about 0.95 GiB total:

- 4 2B textures
- 3 A2 textures
- 266 environment textures
- 13 font/UI textures credited by the author to Triforceguard
- 6 machine textures

The full archive contains 302 DDS files, including the same 13 font/UI textures.
Both archives share 292 basenames, so installing both would create ambiguous
replacement hashes. Only the Lite contents were staged. There is no need to add
another copy of its font/UI files.

Staging location: `visual-stack/stage/SK_Res/`.
No new texture files have been copied into the actual game's SK_Res directory.
The pre-existing game SK_Res/Achievements content was untouched.

All selected archive entries were constrained to the expected texture path,
checked for path traversal/symlinks, checked for DDS headers, and hash verified
after extraction. Four noncanonical author filenames were preserved unchanged,
not guessed/renamed: `38BFD9BA 2k.dds`, `937E19F2old.dds`, `2E4CB26E .dds`, and
`722D71642.dds`. Their presence does not prove the texture injector recognizes
each one. No executables or desktop.ini files from these archives were extracted.

Full staging manifest: `evidence/visual-texture-staging.json`.

## Special K / FAR: isolated test blocked, NOT INSTALLED

Official release **SK_26_10_10** was downloaded from:
https://github.com/SpecialKO/SpecialK/releases/tag/SK_26_10_10

Archive SHA-256 matches the GitHub release digest:
`4dcaf920740cbae2fc8cdf75f7b5ed6aa72280fdbf1cfa9e3d5eb53f23f38fcd`.

Only its x64 DLL was staged as `dxgi.dll`; the working FSR4 `d3d11.dll` was not
replaced. Staged configs limit Special K hooks to D3D11, enable texture injection,
and set a 60 FPS target. The staged FAR config disables UncapFPS, FastLoad and
its separate motion-blur fix, while preserving FAR's disabled LOD patch. These
configs are **not the installed game configs**.

Two headless synthetic runs were bounded and recorded:

1. The full loader probe stalled before returning from its DirectInput stage.
2. A smaller Special K + FSR4 probe without LodMod still stalled around device
   initialization; it never produced completed inference/readback checks.

Only those owned test prefixes were terminated afterward. Real Steam and the
real game prefix were not stopped or reconfigured.

Logs:

- `evidence/visual-stack-probe-run/`
- `visual-stack/compat-test/logs/dxgi.log`
- `evidence/specialk-fsr-only/`
- `visual-stack/specialk-fsr-only/logs/dxgi.log`

This does **not** prove Special K can never work in the actual game. The test is
headless, uses a synthetic executable, and does not activate game-specific FAR
patches. It does mean this DXGI injection arrangement has not passed our safety
check, so it was not installed into the working game. The immediate blocking
wait has not been diagnosed/bisected; no security checks were disabled and no
random version/flag combinations were installed to bypass the test.

Without an active Special K texture injector, the GPUnity pack is not active.
Do not copy the entire staging directory into the game: it contains this blocked
Special K arrangement and uninstalled FAR settings.

## Follow-up Special K diagnosis (isolated prefixes only)

- Console probe, default config: stalls after the `CoCreateInstance` detour.
- Console probe with `[Compatibility.General] AsyncInit=false`, Steam API
  auto-inject/callback pumping off and Steam input disabled: Special K logs
  `Initialization Finished!` and installs deferred D3D11 hooks, then stalls after
  starting NvAPI initialization. `[NVIDIA.API] Disable=true` did not change this.
- New windowed D3D11 swapchain probe (`checks/windowed_present_probe.cpp`):
  control without mods presents 302 frames and passes; Special K as dxgi.dll
  alone, and with the FSR4 d3d11 proxy, both stall before the probe writes output.
- Native/winedbg stack capture was attempted but did not yield a usable Windows
  thread stack; not pursued further.

A delegated web-research pass (brief saved by the subagent run) found no public
report matching this stall, a closed GE issue stating GE-Proton11-7 runs Special K
as dxgi.dll, and working Linux NieR setups that load Special K inside the real
game. Combined with the fresh-prefix behaviour, the synthetic harness is likely
not representative. The real game prefix already ran Special K 25.12.2.5 (as
d3d11.dll) on 2026-09-06 according to its old logs.

Next: a controlled real-game test with Special K as dxgi.dll (d3d11 slot stays
with the FSR4 proxy), Steam integration off/sync init config, FAR FPS unlock off,
and the Lite textures copied into SK_Res. Rollback = move dxgi.dll/dxgi.ini out.
Fallback texture injector if Special K fails: WAX (dxgi/d3d11/dinput8 loader).

## What did pass

The same loader/inference probe **without Special K**, with LodMod as dinput8 and
the real FSR4 d3d11 proxy, passed:

- DirectInput8Create returned S_OK and a valid interface.
- 16 native-AA plus 16 2x-upscaling synthetic evaluations succeeded.
- Both contexts selected provider 4.1.1.
- Independent raw-image/strict-provider checks passed.

Evidence: `evidence/lod-fsr-only/` and `visual-stack/lod-fsr-only/`.
The non-game executable intentionally does not apply LodMod's game-memory
patches, so this tests forwarding/inference coexistence, not in-game LOD visuals.

## Next steps and rollback

1. Validate LodMod in the actual game with the new override, without Special K.
2. Diagnose a supported Special K injection/init path for the real game, then
   activate the staged texture pack. Do not claim the full stack is finished.
3. Implement true engine-resolution upscaling after the visual stack is stable.
   Lower rendering cost does not by itself lift NieR's 60 FPS cap; assess any
   FPS unlock separately rather than risk game behavior.
4. Reprofile, then test frame generation last.

To undo this phase, with the game closed, move only the added `dinput8.dll` and
`LodMod.ini` into a quarantine folder and remove the dinput8 launch override.
Do not remove the working FSR4 d3d11 proxy or restore older saves over healthy
newer progress. No original game file was overwritten in this phase.
