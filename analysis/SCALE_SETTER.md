# Render-scale setter — Phase A (offline), 2026-10-23

An outer `d3d11.dll` that chainloads renamed NIER_DLAA (`d3d11_dlaa.dll`) and writes the
game's internal render scale once: `renderer+0x80 = 0.75`. No hooks, no code patching,
no INI. Not installed in the game.

## How it works

- The game imports `d3d11.dll` statically, so the DLL loads before SteamStub decrypts
  `.text`. The setter therefore starts a thread from the first successful
  `D3D11CreateDevice*` call instead of DllMain.
- The thread polls every 250 ms for up to ~120 s (`scale_patch::try_apply`). It writes
  only if all of these hold:
  - both code signatures match (RVA `0x248179` `4c8b1520705301`; RVA `0x2481b8`
    `f3410f598280000000`)
  - sig1's RIP-relative displacement resolves to the renderer global RVA `0x177f1a0`
  - the renderer pointer is non-null and its memory is committed RW (`VirtualQuery`)
  - width/height are within 320..16384 × 200..16384
  - the current scale is exactly 1.0
- The global is published only after the renderer is fully constructed (`0x14024986c`
  after `+0x80 = 1.0` at `0x1402497bf`), so `scale == 1.0` is a valid readiness check.
- Signature mismatch, wrong scale and bad image size are permanent: it logs and never
  writes. It logs to `NIER_SCALE.log` beside the DLL.

## Files

| File | Role |
|---|---|
| `checks/scale_patch.h` | pure check+write logic |
| `checks/scale_patch_test.cpp` | native unit test (11 cases) |
| `checks/d3d11_scale_setter.cpp` | DLL (chainload + setter thread) |
| `checks/d3d11_log_proxy.def` | reused export table (49 forwarders + 2 wrappers) |
| `checks/verify_scale_setter_exports.py` | export parity vs `input/NIER_DLAA_1.1.dll` |
| `checks/scale_setter_mock_game.cpp` | Proton mock game planting signatures at real RVAs |
| `build/scale-setter/d3d11.dll` | built DLL, SHA-256 `eb91ad7275f6875fcbac7e12244b86fc68c4d168f943b8d40346bbf0eff33bc8` |
| `isolated-scale-setter-20261023/` | private harness, logs, `launch-manifest.json`, `verification.json` |

Build:
```
g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
    checks/scale_patch_test.cpp -o build/scale-setter/scale_patch_test
x86_64-w64-mingw32-g++ -std=c++17 -O2 -Wall -Wextra -Werror -shared -static -static-libgcc -static-libstdc++ \
    -o build/scale-setter/d3d11.dll checks/d3d11_scale_setter.cpp checks/d3d11_log_proxy.def
x86_64-w64-mingw32-g++ -std=c++17 -O2 -Wall -Wextra -Werror -static -static-libgcc -static-libstdc++ \
    -o build/scale-setter/scale_setter_mock_game.exe checks/scale_setter_mock_game.cpp -ld3d11
```

## Results

| Check | Result |
|---|---|
| Signatures present at both RVAs in the unpacked exe; sig1 disp → `0x177f1a0` | pass |
| Unit test (match, each sig flipped, disp flipped, null, unreadable, bad size ×2, not-default, bad scale, small image) under ASan/UBSan | pass |
| MinGW build with `-Werror` | pass |
| Exports: 51 names/ordinals identical to NIER_DLAA 1.1, 49 forwarders, 2 local; no d3d11/dxgi imports | pass |
| Proton: `fsr_inference_probe` via setter → NIER_DLAA → FSR4; 32 evaluations, 3440×1440 verifier | pass (RGB ranges identical to the 19 Oct logger run); setter: `bad-image`, no write |
| Proton mock `match`: renderer 1920×1200, scale 1.0 → 0.75 | pass |
| Proton mock `mismatch`: scale stays 1.0, `signature-mismatch` | pass |

## Not covered

- The real game: renderer timing, actual target re-creation, image correctness.
- A thread-race test against a live game writer. None is known: the only other
  `+0x80` writer is the dead debug hotkey.

## Notes for Phase B

- **Resolution under Moonlight:** Xwayland (`DISPLAY=:1`) reports `HEADLESS-2` as
  **1920×1200**, not 2880×1800 (Hyprland output scale). The game will likely run at
  1920×1200, giving a scaled scene of 1440×900.
- Installed `d3d11.dll` is still NIER_DLAA `3d628eb5…`; `NIER_DLAA.ini` `3163360d…`.
  Graphic.ini path: `/mnt/second/SteamLibrary/steamapps/compatdata/524220/pfx/drive_c/users/steamuser/Documents/My Games/NieR_Automata/Graphic.ini`.
