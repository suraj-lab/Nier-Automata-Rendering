#pragma once
// Live RTX Remix inside the proxy (VISION.md goal 1: a converted F9 scene, path-traced, in the game window).
// Off unless the process environment has NIER_REMIX=1; then NIER_REMIX_RUNTIME (absolute path of the Remix
// d3d9.dll) and NIER_REMIX_SCENE (absolute path of a scene_from_frame.py scene.bin, textures in
// <scene stem>_textures\) are required.
//
// A worker thread owns the runtime, its D3D9 device and a hidden window, renders, copies FINAL_COLOR to system
// memory and publishes the frame. Present only uploads the newest published frame into the game's backbuffer,
// so the game never waits for Remix. Any failure logs one "remix: disabled (...)" line and the game's own frames
// are shown from then on. With NIER_REMIX unset or not "1", on_present returns immediately and logs nothing.
#include <dxgi.h>
#include <d3d11.h>

namespace remix_live {
// Before an indexed game draw: replace the world before the verified native HUD pass begins.
void before_draw(ID3D11DeviceContext* context, UINT index_count);
// Call on every Present of the game's swapchain, before the menu draws, on the presenting thread.
void on_present(IDXGISwapChain* swapchain, void (*log)(const char* format, ...));
// After our overlay drawing, arm camera-only observation for the next game frame (off unless Remix is active).
void begin_game_frame(IDXGISwapChain* swapchain);
// P1 menu -> worker: request an upscaler::Mode (as int). False when no live worker has started (row not shown).
bool request_upscaler(int mode);
// Last fully accepted mode as int, 5 for a partial override (restart required), -1 before startup/off/failure.
int upscaler_mode();
}  // namespace remix_live
