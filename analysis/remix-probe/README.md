# Standalone Remix probe — triangle, captured NieR meshes and whole NieR scenes

Status 2026-10-25: renders on the laptop (Windows ARM, x64 runtime via the Toolkit) and on the Arch desktop
under Proton (Portal RTX's runtime). The "shutdown hang" was launching over SSH (session 0), not a runtime bug.
Findings and screenshots: `../REMIX_FEASIBILITY.md`. The original triangle notes follow below.

## Variants and tools

| Build | Command | Input |
|---|---|---|
| reference triangle | `python3 build.py` -> `remix-triangle.exe` | none |
| one captured draw | `python3 capture_to_mesh.py <draw_dir> <dir>/captured_mesh.h`, then `build.py --mesh <dir>/captured_mesh.h` -> `remix-mesh.exe` | F9 draw folder |
| whole captured frame | `python3 scene_from_frame.py <frame_dir> scene.bin`, then `build.py --scene` -> `remix-scene.exe` | F9 frame folder |

- All builds: `--self-check` (CPU only), `--render C:\abs\path\d3d9.dll` (16 frames), add `--hold` to keep
  rendering until the window closes (5 min cap; the mesh build spins, the scene stays put).
- Laptop screenshot run: `python3 run_remote.py <label> [--mesh | --scene <scene.bin>] --conf rtx.no-ngx.conf
  [--hold --shot-frame N]`. Large scenes need about 15 s before the first RTX frame: use `--hold --shot-frame 1500`.
- Live window in the user's laptop session: `./show_on_laptop.sh <label> [mesh|scene] [scene.bin]`.
- Desktop (Proton): `STEAM_COMPAT_DATA_PATH=<scratch> STEAM_COMPAT_CLIENT_INSTALL_PATH=~/.local/share/Steam
  <proton-cachyos>/proton run ./remix-triangle.exe --render 'Z:\...\PortalRTX\bin\.trex\d3d9.dll' --hold`.
- Scene mode: NieR's camera from `cb0`, a distant sun, window aspect with the game's vertical FOV, draws
  wider than 5 km skipped (NieR sky shells block the sun).
- Gates: `test_capture_to_mesh.py` (+ `_hidden`), `test_scene_from_frame.py` (+ `_hidden`).

## Original triangle notes

This is an isolated Windows x64 SDK probe, not a NieR mod. Its current reference scene follows
NVIDIA's RemixAPI_C sample: a triangle using the default material, parameterized camera and sphere
light. A custom material is also created/deleted to exercise that API, but not bound in the baseline.
No game assets, hooks, Toolkit project or language-model inference are involved.

## Approved Windows test result (2026-10-25)

The x64 probe loaded the Toolkit's x64 runtime on Spaghetti (Windows ARM / RTX Spark N1X), created
scene resources and submitted 16 frames successfully. A process-local `DXVK_DUMP_SCREENSHOT_FRAME=10`
export captured the actual renderer output: `screenshots/reference-triangle.png` shows a dim green
triangle. Native half-float DDS and logs remain under `analysis/runtime/remix-probe/`.

The original custom scene captured near-black; the reference scene changed several parameters, so
its success does not identify one cause. Resource deletion succeeds, but **Shutdown API hangs**.
An external 90-second watchdog stopped each hung probe; none remain running. Do not run this build
without a watchdog. SSH runs in session 0, not the user's desktop session 1; that is a possible
factor, not a proven cause. Evidence: `analysis/runtime/remix-probe/render-evidence.json`.

This proves a rendered synthetic mesh through the x64 Remix API on this host—not NieR integration,
clean shutdown, interactive presentation, full-game performance or a general ARM compatibility claim.

## Preparation (Arch only)

```
python3 analysis/remix-probe/build.py
```

This verifies the pinned unmodified MIT SDK header, runs native CPU scene/argument self-checks with
ASan/UBSan and warnings-as-errors, then cross-compiles `analysis/runtime/remix-probe/remix-triangle.exe`.
The build checks it has no static D3D9/D3D11/DXGI/Vulkan/CUDA imports. No Windows executable, Wine,
Remix runtime or GPU workload is launched. Receipt: adjacent `validation.json`.

## Further Windows tests — require approval; shutdown still needs debugging

The runtime binary is NOT bundled/downloaded. First select a supported x64 runtime compatible with
the pinned header (public API 0.6.6, upstream commit in `vendor/manifest.json`); do not substitute an
arbitrary ARM64 DLL merely because the host is Windows ARM. Copy the probe into a dedicated scratch
folder, not NieR's folder and not the Toolkit project folder. The runtime may generate logs/caches.

- No arguments: print help; no runtime load.
- `--self-check`: CPU checks only; no runtime load.
- `--render C:\absolute\runtime\d3d9.dll`: **real RTX work**, creates its own 512x512 window.
  An absolute drive-qualified path is required. Checks initialization and required function pointers,
  submits at most 16 frames with 250ms sleeps, then attempts shutdown (currently hangs). Close the
  window to stop submissions; an external watchdog is still required to handle the shutdown hang.

The frame/resolution bounds are NOT a GPU, power, memory or wall-time cap: runtime initialization
may allocate substantial VRAM/RAM, take time or fail. Do not execute it while the laptop's workload
must remain unaffected. API return-code success alone does not prove the triangle is visible or
correct; inspect the image and preserve logs. A reference triangle is now verified by runtime capture;
scene correctness beyond that image, interactive desktop output and clean shutdown remain unverified.

The window is kept alive until runtime Shutdown on normal/early exits. This program does not set
Remix configuration variables or call asset/project editing tools; system/runtime behavior is still
outside the CPU/cross-build evidence. The build script installs nothing into the game or laptop;
approved transfer/test commands copied versioned probe folders under Downloads on Spaghetti.
