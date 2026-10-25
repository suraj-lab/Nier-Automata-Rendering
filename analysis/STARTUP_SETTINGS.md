# Startup settings candidate (2026-10-24)

## Status

**Both approved startup smoke tests passed on Proton.** The user reports no visual issues in Native
and "done, looks good" in Custom75. Native logs confirm 3440x1440 native AA and no patch/scale writes.
Custom75 logs confirm both patches, a 0.75 renderer/gate scale, Output SRV/slot-0 redirect and FSR4
2580x1080 -> 3440x1440. Bridge colour/depth/MVs share the reduced dimensions; output stays native.
The run reaches logged evaluation frame 3600 with no error/warning lines. This is a smoke test, not
a frame-by-frame correctness proof, headroom benchmark or long-session test.

Evidence: the backup's `native-run/` and `custom75-run/` folders, each with logs and `result.json`.
`NIER_RENDER.ini` remains on **Custom75**. The assistant did not launch the game or change files
between the user's Custom75 run and result capture. Original mod DLL, `NIER_DLAA.ini`/debug settings
and native 60 FPS cap remain unchanged. Luna accepted the source/failure tests before live testing.

Pre-test v4 SHA256: `3afafb606b38a30536ee8a89b93093e1971414e8f13cc89a8c796f011afc161f`.
Verified backup: `backups/startup-settings-test-20261024T161800Z/` (private/gitignored), including
original DLLs/INI, logs, `receipt.json` and `RESTORE.md`. `NIER_RENDER.ini` did not exist before the test.
Live receipt/log offsets: `analysis/runtime/startup-settings/live-test.json`. Restore only with the
game closed; keep new logs. The tracked v4 build and pinned deployment script remain unchanged.

Candidate DLL: `analysis/runtime/startup-settings/d3d11.dll` (gitignored).
SHA256: `c4996b836646f9b26db6dcd57df609daa754e49a5f89b23ce454e0874fb248e0`.
The manifest beside it records its source hash. Do not substitute this DLL into the hash-pinned v4
deployment script or overwrite `analysis/build/scale-setter/d3d11.dll`.

**2026-10-25 source is now ahead of that installed build:** terminal startup-status publication is
implemented and fault-tested in source. A separate offline DLL is at
`analysis/runtime/settings-writer/status-candidate/d3d11.dll` (SHA256
`914948447eeae3c3e8b486402c99d3da61a1e191ec8eb5a37afe3eca5bdd9fdd`). It was NOT installed.
The old startup manifest is a point-in-time source receipt, not a claim that today's source still
matches it. See `SETTINGS_WRITE_PLAN.md` for reviewed component scope and pending real persistence.

## Settings contract

The candidate reads `NIER_RENDER.ini` beside the outer `d3d11.dll`, once per game startup.
The current test selects Custom75:

```ini
[Rendering]
Preset=Custom75
```

- `Custom75`: 75% per axis, currently validated in v3/v4 at 2580x1080 -> 3440x1440.
  This custom ratio is not the standard FSR Quality preset. The new candidate still needs its own
  game test.
- `Native`: bypass this setter's depth/proxy patches and scale polling/writing. The setter still
  chainloads `d3d11_dlaa.dll`; Native does not uninstall the mod or remove its native-resolution AA.
- Missing file: preserve the existing Custom75 default.
- Existing file with a missing/empty/unknown key, overlong value, directory in place of the file,
  unreadable file, or broken parent path: select Native and report invalid/unreadable configuration.
- Values accept ASCII case differences and surrounding ASCII whitespace. The Win32 profile API
  supplies normal INI section/key parsing. The pure selector rejects suffixes and Unicode lookalikes.

The startup log reports the selected preset, scale, `valid` and `defaulted`; `defaulted=1` means the
file was absent. Explicit Native reports that no patches or scale writes ran. This is not a live
settings menu; changing the file requires a game restart.

## Failure handling

The reduced path requires depth and proxy patch success before calling the scale setter.
The proxy installer prepares all seven sites' memory protections before changing any instruction.
It remembers original bytes and restores overlapping page protections in reverse acquisition order.
Cache-flush failure after publication rolls back the code bytes; a protection-restoration failure
triggers another write-protection acquisition, rollback and restoration attempt. The installer keeps
a published cave allocated for the process lifetime in case another thread is still executing it.

Limits:

- These are startup patches, not a thread-suspension/hot-reload transaction. An opcode-last store
  does not make a multi-byte instruction replacement atomic with another executing thread.
- Persistent protection/cache failures can prevent complete recovery. The log says restart required;
  the setter refuses reduced scale. Do not advertise this as an unconditional, untouched-Native fallback.
- A depth patch can remain installed after proxy failure; at scale 1.0 it preserves native dimensions.
- This work does not change the inherited depth patch's installation mechanism or the SRV redirect's
  runtime behaviour. It does not prove freedom from rendering/resource-lifetime issues in-game.

## Checks completed

- Pure `render_settings_test.cpp`: ASan/UBSan and `-Werror`, all passed. The local worker wrote only
  `render_settings.h`; lead reran its frozen gate and Luna reviewed the integration.
- `test_startup_settings.py`: two native harnesses compile the actual production function bodies.
  They inject failure at each prepare site, combined prepare/cleanup failures, cave/site cache-flush
  failures and a postcommit protection-restoration failure. They check original bytes/protections,
  Native's early return, handle balance and scale/gate guards. The original sequential installer
  failed the prepare-site regression before the fix.
- `test_render_settings_io.py`: **11 real Win32 API cases passed under Wine**, using generated
  files and an isolated prefix below `analysis/runtime/settings-io/`. Includes UTF-16 INI files,
  a read-sharing denial, directories, empty/absent keys and oversized values. No NieR proxy or game
  loaded. Wine initialized helper processes/drivers, including the host's implicit Vulkan layer;
  its profile implementation is not proof of identical Windows-on-ARM behaviour.
- Existing Part 3 gate: **29/29**, including previous setter build/export checks and unchanged frozen
  cave/header checks. MinGW candidate built with `-Werror`; all 51 export names/ordinals match the
  original proxy, with 49 correct forwarders and no D3D/DXGI imports.
- GPU sampler: eight fake-sysfs tests pass. Luna found non-finite optional readings leaking into
  CSV; lead reproduced/fixed the issue and added a blank-cell regression. Live measurement remains pending.

Reproduce from the repository root:

```sh
python3 analysis/checks/test_startup_settings.py
python3 analysis/checks/test_part3_integration.py
python3 analysis/checks/test_render_settings_io.py
```

The last command requires Wine and the MinGW cross-compiler and creates only test artifacts/prefix
state under `analysis/runtime/settings-io/`. It may initialize Wine helper processes and drivers.
The first two commands build native/MinGW test artifacts in temporary directories.

## Next checkpoint

Keep the working Custom75 configuration unchanged. Claude Design's handoff is received; review
corrections and the tested standalone menu-state candidate are in `menu-design/IMPLEMENTATION_NOTES.md`.
The menu controller is not integrated into the production setter. Resolve the overlay/input seam and
safe settings persistence before attachment; the first version saves for restart, not hot reload. A separate resolution-change
regression and longer session remain before deployment promotion/additional presets. Do not overwrite
the v4 build or loosen its deployment hash checks to install this candidate.

Then add validated presets one at a time and evaluate FG/NR backends. FAR uncap remains a separate,
disabled workstream; source research does not establish safe high-FPS gameplay. See `FAR_RESEARCH.md`.
