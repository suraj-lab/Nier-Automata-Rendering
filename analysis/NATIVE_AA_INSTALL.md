# Native-AA installation and operation

This records the historical native-AA installation phase, not the full current
setup. LodMod, WAX textures, and the Windows 10 executable were added later; use
[PROGRESS.md](../PROGRESS.md) for authoritative state and the current launch options
at the top of [VISUAL_STACK.md](VISUAL_STACK.md).

## Installed

Game directory:
`/mnt/second/SteamLibrary/steamapps/common/NieRAutomata`

Eight new files were added, with no existing files overwritten:

- `d3d11.dll` — exact patched NIER_DLAA 1.1 proxy tested in earlier phases.
- `NIER_DLAA.ini` — upstream mod defaults: enabled, character motion enabled,
  visible motion blur hidden while AA runs, diagnostic modes disabled.
- `NIER_FSR4.dll` — the same local bridge build that passed synthetic FSR4.1.1.
- `NIER_FSR4.ini` — production defaults, including Version=4.1.1 and reading
  camera values from the real mod. Not the synthetic-test camera configuration.
- `amd_fidelityfx_loader_dx12.dll`
- `amd_fidelityfx_upscaler_dx12.dll`
- `AMD_FidelityFX_LICENSE.md`
- `NIER_FSR4_README.md`

The proxy was copied last, after all supporting files were installed and hash
verified. The executable, Steam API DLL, existing FAR/Special K configs, and all
existing saves/configs were unchanged at installation verification.

No NVIDIA DLSS DLL, OptiScaler, NR, frame-generation, FPS-unlock, texture, or LodMod
files were installed. DLSS/DLAA names in the proxy INI and logs are inherited from
the original mod; its patched backend is FSR, not NVIDIA DLSS.

## Verified backup

`../backups/native-aa-20261018T201659Z/`

Eight original files were backed up and checked against SHA-256 hashes:

- All five files in the game's actual `Documents/My Games/NieR_Automata`
  directory, including the save slot, SystemData, GameData, Graphic.ini and
  Steam Auto-Cloud metadata.
- The existing game-root `FAR.ini` and `d3d11.ini`.
- The existing Steam app-userdata file for app 524220.

The backup root was created private (mode 0700). It contains `manifest.json`
with source locations, relative backup paths, byte counts and hashes. Save-file
contents were not printed or altered. Full Steam account/authentication config
was not copied.

Installation manifest:
`evidence/native-aa-installation.json`.

## GE-Proton11-7 registration

Created this directory symlink, without replacing an existing registration:

```text
~/.local/share/Steam/compatibilitytools.d/GE-Proton11-7-x86_64
  -> ~/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64
```

Steam's display/internal tool name is **GE-Proton11-7-x86_64**.

This avoids a duplicate 1.5 GiB runner installation, but the workspace runner
must remain at that path while Steam uses it. Do not move/delete that runner
without updating the registration. The downloaded archive is not required for
running it, but has been retained as acquisition evidence.

Steam was running and was not stopped. No live Steam VDF settings were edited.
The new tool may not appear until Steam is fully exited and reopened; merely
closing its window may leave it running in the tray.

## Required Steam UI steps

1. Exit/reopen Steam when convenient.
2. NieR:Automata -> Properties -> Compatibility: enable the forced compatibility
   tool selection and choose **GE-Proton11-7-x86_64**.
3. Properties -> General -> Launch Options:

   ```text
   WINEDLLOVERRIDES="d3d11=n,b" mangohud gamemoderun %command%
   ```

This retains the previous MangoHud/GameMode wrappers and adds the native proxy
DLL override. Original launch options were:

```text
mangohud gamemoderun %command%
```

GE11-1 passed loader/interop tests but used FSR3 fallback with this SDK. GE11-7
actually created provider 4.1.1 contexts, so do not skip the runner selection.
No `PROTON_FSR4_UPGRADE`, NVIDIA spoofing, or NVAPI setting is needed for the
successful synthetic path we tested.

## Required in-game settings and first test

- **Anti-Aliasing: Off.** Avoid MSAA: the proxy requires a single-sampled HDR scene.
- **Motion Blur: On.** The character-velocity pass must run. The mod's
  `HideMotionBlur=1` suppresses the visible blur while its AA is active.
- Keep the game's normal 60 FPS limit; do not add an FPS unlock yet.
- Load a save and move the camera. The toggle is now **F8** (Moonlander layer 2,
  physical 8 key), configured as `ToggleKey=0x77`. Restart the game to ensure it
  reads this change; no running-process patch was performed.

The existing `Graphic.ini` only contains display-device metadata, so no guessed
AA or motion-blur keys were added. These settings must be selected through the
game UI rather than patching the user's binary SystemData file.

The first launch can compile shaders. Do not infer success solely from the game
starting or an AA toggle changing the picture. Check the game-root logs:

- `NIER_FSR4.log`: a successfully created context ending in `provider 4.1.1`,
  followed by evaluation activity, rather than only an available-provider list.
- `NIER_DLAA.log`: actual camera/depth recognition and character-motion activity.

Menu-only frames may have no recognized scene/camera. If the mod is inactive in
actual gameplay, crashes, or shows artifacts, keep both logs for inspection.
Subsequent live inspection confirms GE11-7, an active provider 4.1.1 context at
3440x1440, evaluations through at least frame 14400, and character-motion draws.
No FAR/Special K module was observed; both system graphics DLLs match DXVK and
the local proxy matches the tested DLAA-to-FSR bridge. `FAR.ini` is preserved but
does not establish an active FAR installation. Retained observations are in
`evidence/first-live-game-verification.json`. Visual/temporal quality has not been
independently verified.

## Reversibility

No original game files need restoring to remove this additive package. With the
game closed, move only the eight files named in the installation manifest into
a separate quarantine directory, then select the previous Proton runner and
restore the original launch options. Preserve any subsequently edited mod INIs
and generated logs instead of blindly deleting them.

Do not restore old saves over newer healthy saves. The backup is for recovery
if needed, not something to apply automatically. No save restoration was run.

This installs native-resolution AA only. Actual engine-resolution upscaling,
DLSS5 NR, frame generation, and compatibility with other recommended mods remain
separate, unverified work.
