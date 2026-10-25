# In-game menu (step 5) — offline build, not installed

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
- **Cursor (2026-10-25):** while the panel is open the overlay calls `ClipCursor(nullptr)` every frame and
  `ShowCursor(TRUE)` on open (balanced by `ShowCursor(FALSE)` on close), releasing the game's cursor capture
  so the mouse can reach the panel. Input still reaches the game (not consumed); open from the pause menu.
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

## Known limits
- Not tested in NieR, DXVK, WAX, Proton or native Windows/ARM64. Wine/wined3d mock only.
- Input is polled, not captured: clicks and Esc also reach the game. Open the panel from the game's pause menu.
  No mouse-wheel scrolling (drag the scrollbar). Insert is ignored until the startup snapshot exists.
- `Present1` is not hooked (NieR uses Present). Panel scale is fixed at the first frame (1/1.5/2 by height).
- Save does file I/O on the render thread: expect a short hitch on click.

## Live test plan (needs explicit user approval)
1. Game closed. Back up exactly: current `d3d11.dll`, `NIER_RENDER.ini`, `NIER_SCALE.log`, plus hashes.
2. Copy `runtime/menu-dll/d3d11.dll` and `nier_render_fonts\` into the game folder. Leave everything else as is.
3. User launches, opens the pause menu, presses Insert: panel visible? Startup state correct (Custom75 active)?
4. Select Native, Save, check the notice, close. Exit. Verify `NIER_RENDER.ini` and the log. Optionally relaunch
   to confirm Native, then switch back to Custom75 the same way.
5. Rollback: restore the backed-up DLL and INI, remove `nier_render_fonts\`; keep logs.
