# Isolated NIER RENDER preview

**Standalone preview milestone complete; paused at the user's request.** This is a separate executable,
not a game DLL. The tested Custom75 install, original AA mod/config and 60 FPS cap were not changed.
No game process, game resources or real `NIER_RENDER.ini` are opened by this program.

## See the result

- `screenshots/state-sheet.png`: actual D3D11 captures of clean, dirty, saved and startup-failure UI.
- `screenshots/native-100.png`: conceptual Windows/Native case with unknown render size.
- `screenshots/custom75-200-scroll.png`: fixed footer and scrolling body at 1920×1080 / 200%.
- The full 42-image set and measured geometry are under the directory recorded in
  `../runtime/menu-preview/render-validation.json` (generated/gitignored).

All screenshots are labelled **simulated preview**. Saving updates only in-memory fixture state.
A displayed “saved” message here is NOT an on-disk game configuration change.

## Build and test

From the repository root, using the already-installed native GCC, MinGW x64, Python, Wine, Xvfb and
ImageMagick (no packages are installed by these scripts):

```sh
python3 analysis/menu-preview/build.py
python3 analysis/menu-preview/render_checks.py --smoke
python3 analysis/menu-preview/render_checks.py
```

Build output: `analysis/runtime/menu-preview/build/nier_menu_preview.exe`, with its `fonts/` directory
and license notices. The frontend in `panel.cpp` is shared code; the host uses Win32/D3D11, as the game
will on native Windows and through Proton. No separate Linux GTK/Qt application was introduced.

The capture runner uses a task-owned Wine prefix, isolated HOME/cache/runtime directories and Xvfb.
Only that prefix is stopped on completion/failure. Mono/Gecko installers and Wine menu integration are
disabled for this native C++ test app, not in the user's normal prefixes. `LIBGL_ALWAYS_SOFTWARE=1`
is scoped to the test environment; driver initialization may still enumerate hardware/Vulkan layers.
This is not a GPU benchmark or proof of a particular software/hardware renderer.

For interactive use, run the EXE with `fonts/` next to it in a graphical session. Supported arguments:

```text
--scale=1|1.5|2
--viewport=1920x1080|3440x1440
--case=custom75|native|dirty|saved|save-fail|startup-fail|closed
--capture
```

`--capture` creates `capture.bmp` and `metrics.json` in the current directory with CREATE_NEW;
existing files are never overwritten. Use a fresh writable directory. The runner converts BMPs to
PNG and removes only its own generated BMPs. Insert toggles, Escape closes the combo before the
panel, and F5 toggles the **host-only** simulated save failure. The real menu will not get that F5
simulator control. Closing/reopening retains unsaved selection; native-AA and failure labels stay
honest about what was applied/observed.

## Evidence

- 42 native ImGui CPU layout/state tests: 7 cases × 2 viewport sizes × 3 scales, ASan/UBSan and
  warnings-as-errors. Fixed footer bounds, scrolling at 200%, stable right-edge placement and
  non-compounding scaling are asserted.
- Real ImGui mouse input checks cover failed save/retry, discard, no writer callback and clean close.
  Keyboard logic checks cover popup-first Escape and Insert closing popups; closed frontend draws zero
  vertices. This is not proof that game input is captured.
- Windows x64 cross-build passed.
- 42 Win32/D3D11 captures executed under Wine/Xvfb, checking actual pixels, output size, panel/footer
  bounds, scrolling and closed state. Full result: `../runtime/menu-preview/render-validation.json`.
- Initial headless launch timed out. Stage/timeout diagnostics were added; a retry with unneeded
  installers disabled passed. Prefix warm-up also changed, so the original timeout's cause is NOT
  proven. The failed initial attempt and subsequent pass are retained in runtime logs.
- Independent Luna review accepted the offline preview with notes; unknown-size captions, disabled
  button styling and timeout logging findings were corrected and confirmed. The final full matrix
  was independently run by the lead after that review, not by the reviewer.

## Dependencies and limits

`vendor/manifest.json` pins and hashes every third-party source/font file. Build verifies hashes.
Dear ImGui **v1.91.9b**, commit `f5befd2d29e66809cd1110a152e375a7f1981f06`, is an explicit stable
static-font-atlas preview dependency, not the earlier master snapshot used for initial research.
Unmodified source and the upstream MIT notice are retained in `vendor/imgui/`. The standalone host
borrows the official Win32/D3D11 example's device/window setup under that license.

IBM Plex static fonts are pinned at `71f558992315a12ca1f06a2215d57962a1992162`; unmodified TTFs,
original names and the exact SIL OFL notice are retained in `vendor/fonts/`. There are no proprietary
game assets and no runtime font downloads. The preview atlas includes the Latin/em-dash glyphs it
uses; other planned decorative icons are replaced by ordinary labels/shapes.

`key_event` uses one documented, pinned ImGui internal popup-close API in its OWN context. Recheck
that dependency on upgrades or if context ownership changes. Preview scale is fixed per invocation;
monitor-to-monitor live DPI/font/device reinitialization is not implemented or validated.

Not done: native Windows/ARM64 execution, real physical-keyboard testing, actual game swapchain/input
attachment, renderer-resource lifetime/state restoration in the game, runtime status publication,
atomic settings persistence/invalid-config repair, deployment promotion or resolution/long-play
regression of a future menu build. Do not install this EXE as a DLL or copy it over the working proxy.

## Resume

Review these screenshots with the user. Next implementation seams are the real writer/status data
and actual swapchain/window/input ownership, each behind its own tests. Keep save-and-restart only.
Do not resume the paused FAR worker or enable uncapping/NR/FG. No further work runs overnight.
