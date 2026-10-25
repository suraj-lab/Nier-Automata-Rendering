# NieR:Automata FSR4 upscaling - install

Renders the scene at 0.75x (2580x1080 for 3440x1440) and upscales it with FSR4 to native, with
native-resolution bloom/tone-map/HUD. Stack: game -> `d3d11.dll` (our setter, v4) -> `d3d11_dlaa.dll`
(NIER_DLAA 1.1, FSR4-patched) -> NIER_FSR4 bridge. Background: `../PART3_REDIRECT.md`, `../UPSCALING_PATCH.md`.

```
analysis/deploy/nier_upscale.sh status    # what is installed (by hash)
analysis/deploy/nier_upscale.sh install   # native AA -> upscaling, or upgrade an older setter build
analysis/deploy/nier_upscale.sh restore   # back to native AA
analysis/deploy/test_nier_upscale.sh      # test against a throw-away copy (needs the local baseline)
```

- Close the game first; every mode refuses while it runs and changes nothing if a file is unrecognised.
- No in-game resolution re-apply is needed: the setter writes the scale before the startup resize.
- Debug keys (F10 frame dumps) are off after install; set `NIER_DLAA.ini` `[Debug] Enabled=1` to use them.
- Logs: `NIER_SCALE.log` (patches, `part3 redirect` lines), `NIER_FSR4.log` (`CreateFeature: 2580x1080 -> 3440x1440`).
- The original mod files live in `backups/native-aa-baseline/` (gitignored: the mod is not ours to redistribute).
- Pinned hashes: setter v4 `3afafb60...`, mod `3d628eb5...`, ini `3163360d...` (full values in the script).

## Startup-settings candidate (separate temporary test)

`../STARTUP_SETTINGS.md` records passing Native/Custom75 startup smoke tests; the candidate remains
temporarily installed with Custom75 selected. This script still targets v4 and does **not** recognise,
deploy or restore that candidate or read/copy `NIER_RENDER.ini.example`. Use the pre-test backup/receipt in
`backups/startup-settings-test-20261024T161800Z/` to roll back with the game closed. Do not replace this
script's pinned DLL/hash until the candidate passes its game test. v4 ignores the new settings file.
