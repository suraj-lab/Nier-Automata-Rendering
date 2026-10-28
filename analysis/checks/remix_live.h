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

namespace remix_live {
// Call on every Present of the game's swapchain, before the menu draws, on the presenting thread.
void on_present(IDXGISwapChain* swapchain, void (*log)(const char* format, ...));
}  // namespace remix_live
