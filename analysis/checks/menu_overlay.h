#pragma once
// In-game settings panel: hooks the game's swapchain Present after the existing mod layers and
// draws the menu-preview panel while it is open. Fails closed: any setup error leaves frames untouched.
#include <d3d11.h>
#include <string>
#include "render_settings.h"
#include "startup_status.h"

namespace menu_overlay {
struct Host {
    std::wstring module_dir;  // folder of the outer d3d11.dll, ends with a backslash
    render_settings::Settings (*reader)(const std::wstring& path);
    const startup_status::Publication* startup;
    void (*log)(const char* format, ...);
};
// Call after a successful device creation. swapchain may be null (factory path is hooked instead).
void install(ID3D11Device* device, IDXGISwapChain* swapchain, const Host& host);
}  // namespace menu_overlay
