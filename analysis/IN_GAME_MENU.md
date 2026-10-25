# In-game menu (step 5) — installed and live-tested

Status 2026-10-25: installed in NieR (current build `31fc04351e2f…`), live-tested by the user: panel renders,
both save directions commit, the camera no longer moves while the panel is open. The same DLL also hosts the
F9 frame capture used by the RTX Remix work (see below). Stage history at the end.

The proxy `d3d11.dll` now hosts the settings panel inside the game. Press **Insert** to open or close it;
**Esc** closes it. Save writes `NIER_RENDER.ini` for the **next launch** only. Nothing changes live.

## How it attaches
- Existing layers, from shipped binaries: NIER_DLAA (`d3d11_dlaa.dll`) hooks `IDXGIFactory::CreateSwapChain` /
  `CreateSwapChainForHwnd` and `SwapChain::Present` by **vtable slot** at device creation. WAX (`dxgi.dll`) uses
  `retour` **inline detours** and checks code bytes.
- Ours: vtable-slot hooks only (`checks/vtable_hook.h`), so no code bytes are rewritten. After device creation
  we hook the factory's two create slots. The swapchain is adopted only when the **outermost** create call returns,
  because Wine/DXVK implement CreateSwapChain via a vtable call to CreateSwapChainForHwnd. The menu is
  then the outermost Present layer; every other layer still runs on every frame.
- First Present: ImGui context, pinned fonts from `nier_render_fonts\` beside the DLL, Win32 + DX11 backends,
  device objects created up front. Any failure logs `menu: disabled (...)` and frames pass through unchanged.
- Closed panel: per frame only two `GetAsyncKeyState` calls. Open: a fresh backbuffer RTV per frame, released
  after drawing, so no backbuffer reference is held across frames (no `ResizeBuffers` hook needed). OM render
  targets and the HS/DS/CS shader bindings are saved and restored (the ImGui DX11 backend clears those three
  stages without restoring them; found by review c9bc992c). The backend restores the rest of what it touches.
- **Cursor and mouse (2026-10-25, `checks/input_capture.h`):** while the panel is open the overlay calls
  `ClipCursor(nullptr)` every frame and `ShowCursor(TRUE)` on open (balanced on close), and blocks the game's
  mouse three ways: a WndProc subclass consumes mouse + `WM_INPUT` messages; an IAT patch makes the game's
  `SetCursorPos` re-centering a no-op; and **DirectInput8** `GetDeviceState`/`GetDeviceData` (vtable slots 9/10,
  checked against `dinput.h`) return zeroed state / no events for mouse-type devices only. NieR reads mouselook
  through DINPUT8, so the first two alone did not stop the camera. Keyboard and gamepad still reach the game.
- Panel state: built on the first Insert after the startup snapshot is published (`menu_session.h`) plus a
  fresh file read (`menu_settings_io.h`). Save = real writer + re-read. `D3DCompile` is loaded at runtime from
  `d3dcompiler_47.dll`; ImGui asserts are compiled out; XInput is not loaded.

## Evidence (offline)
- `checks/test_menu_overlay.py`: real proxy DLL under an isolated Wine prefix + Xvfb with a mock game (factory
  swapchain like NieR) and a stub `d3d11_dlaa.dll` that hooks the same slots first.
  - repair: Insert opens the panel, real `SendInput` click repairs `Preset=Quality` to `Native`; closed
    capture shows no drawing; the stub counts 80/80 frames.
  - no-fonts: overlay disables itself; 80/80 frames; INI untouched.
  - Pipeline state: the mock game binds a compute shader across every Present. Before the HS/DS/CS fix it was
    lost on 51 frames (exactly the open-panel frames); after the fix `cs_lost=0`.
  - Found during testing: nested create calls made the layer order depend on factory internals; fixed.
- `vtable_hook.h`: desktop worker, frozen ASan+TSan gate; a slot-before-original race negative was caught 3/3.
- Part3 29/29 (now builds the full menu DLL), startup/reader/writer/menu gates, preview 66+66.
- DLL: `runtime/menu-dll/d3d11.dll`; 51 exports / 49 forwarders; imports only system DLLs (no d3d11, dxgi,
  d3dcompiler, xinput). Screenshot: `menu-preview/screenshots/ingame-mock-repair.png`.

## F9 frame capture (same DLL, for RTX Remix)
- F9 records one whole game frame: every `DrawIndexed`/`DrawIndexedInstanced` (context vtable slots 12/20) with
  at least 128 indices, between two Presents, into `NIER_CAPTURE\frame_<tick>\draw_NNNN\` (capture.json,
  vb_<slot>.bin, ib.bin, cb_<slot>.bin). Frame boundaries sit around the menu's own ImGui drawing.
- Static vertex/index buffers are read once per frame and hard-linked into each draw folder (`buffers\`);
  dynamic buffers are always read fresh. PS-bound static textures are saved once as DDS (`textures\`).
  Caps: 4096 draws, 768 MB unique buffers, 1 GB textures; `frame.json` reports draws/skipped/bytes.
- Real frame: 2995 draws, 0 skipped, 456 MB, ~7 s stall. Converters and renders: `REMIX_FEASIBILITY.md`.
- Gates: `checks/test_geometry_capture.py` (cache sharing, dynamic buffers), `checks/test_menu_overlay.py`
  (frame boundaries with the panel closed and open, hard links, DDS byte-exact, render target excluded,
  DirectInput blanking with a keyboard negative).

## Known limits
- Tested in NieR on Proton/DXVK/WAX (Arch). Not tested on native Windows/ARM64.
- Insert/Esc keys are polled, so Esc also reaches the game; open the panel from the game's pause menu.
  No mouse-wheel scrolling (drag the scrollbar). Insert is ignored until the startup snapshot exists.
- `Present1` is not hooked (NieR uses Present). Panel scale is fixed at the first frame (1/1.5/2 by height).
- Save does file I/O on the render thread: expect a short hitch on click.

## Stage history (installed builds, each with a backup + hash receipt under `backups/ingame-menu-*`)
1. `ac58f09f…` first live build: panel + save (live-tested OK).
2. `f1a43946…` cursor release (`ClipCursor`/`ShowCursor`).
3. `fb4cb25c…` F9 single-draw capture; `2324df2a…` WndProc + `SetCursorPos` blocking (camera still moved).
4. `f3da6005…` capture size filter + viewport; `8d7d184c…` DirectInput mouse block (camera fixed, user-confirmed);
   `8506cea2…` layout slot in capture JSON.
5. `93da7ac9…` F9 = whole frame; `947784e0…` per-frame buffer cache + hard links (full 2995-draw frame).
6. `31fc0435…` PS material texture capture (DDS). Not yet run in the game.

## Original live test plan (done 2026-10-25)
1. Game closed. Back up exactly: current `d3d11.dll`, `NIER_RENDER.ini`, `NIER_SCALE.log`, plus hashes.
2. Copy `runtime/menu-dll/d3d11.dll` and `nier_render_fonts\` into the game folder. Leave everything else as is.
3. User launches, opens the pause menu, presses Insert: panel visible? Startup state correct (Custom75 active)?
4. Select Native, Save, check the notice, close. Exit. Verify `NIER_RENDER.ini` and the log. Optionally relaunch
   to confirm Native, then switch back to Custom75 the same way.
5. Rollback: restore the backed-up DLL and INI, remove `nier_render_fonts\`; keep logs.
