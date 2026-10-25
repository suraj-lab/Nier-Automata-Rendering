#include "menu_overlay.h"
#include <dxgi1_2.h>
#include <d3dcompiler.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <exception>
#include <memory>
#include "vtable_hook.h"
#include "menu_session.h"
#include "menu_settings_io.h"
#include "../menu-preview/panel.h"
#include "backends/imgui_impl_dx11.h"
#include "backends/imgui_impl_win32.h"

// The DX11 backend compiles two tiny shaders. Resolve the compiler at runtime so the proxy DLL gains
// no load-time dependency on d3dcompiler_47.dll; if it is missing, the overlay simply stays off.
extern "C" HRESULT WINAPI D3DCompile(LPCVOID data, SIZE_T size, LPCSTR name, const D3D_SHADER_MACRO* defines,
    ID3DInclude* include, LPCSTR entry, LPCSTR target, UINT flags1, UINT flags2, ID3DBlob** code, ID3DBlob** errors) {
    using Fn = decltype(&D3DCompile);
    static const Fn fn = [] {
        HMODULE m = LoadLibraryExW(L"d3dcompiler_47.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        FARPROC p = m ? GetProcAddress(m, "D3DCompile") : nullptr;
        Fn f = nullptr; std::memcpy(&f, &p, sizeof(f)); return f;
    }();
    return fn ? fn(data, size, name, defines, include, entry, target, flags1, flags2, code, errors) : E_NOINTERFACE;
}

namespace menu_overlay {
namespace {
// COM vtable slots (IUnknown 0-2, IDXGIObject 3-6, IDXGIDeviceSubObject 7).
constexpr std::size_t kCreateSwapChain = 10, kCreateSwapChainForHwnd = 15, kPresent = 8;

using CreateSwapChainFn = HRESULT (STDMETHODCALLTYPE*)(IDXGIFactory*, IUnknown*, DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**);
using CreateForHwndFn = HRESULT (STDMETHODCALLTYPE*)(IDXGIFactory2*, IUnknown*, HWND, const DXGI_SWAP_CHAIN_DESC1*,
    const DXGI_SWAP_CHAIN_FULLSCREEN_DESC*, IDXGIOutput*, IDXGISwapChain1**);
using PresentFn = HRESULT (STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);

Host host;
std::atomic<bool> installed{false};
std::atomic<void*> next_create{nullptr}, next_create_hwnd{nullptr}, next_present{nullptr};
std::atomic<IDXGISwapChain*> target{nullptr};  // latest game swapchain; identity only, not owned

// Render-thread state: touched only inside Present on the target swapchain.
enum class Phase { Waiting, Ready, Disabled };
Phase phase = Phase::Waiting;
float scale = 1;
HWND window = nullptr;
ID3D11Device* device = nullptr;
ID3D11DeviceContext* context = nullptr;
menu_preview::Fonts fonts;
std::unique_ptr<render_menu::State> state;
menu_settings_io::Observation shown;
menu_session::Session session{};
char display_size[32] = "";
bool insert_was = false, escape_was = false, warned_not_ready = false, cursor_released = false;

bool protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

bool hook(void* object, std::size_t index, void* replacement, std::atomic<void*>& next, const char* name) {
    void** table = *static_cast<void***>(object);
    const auto r = vtable_hook::hook(table, index, replacement, next, protect);
    host.log("menu: hook %s slot %zu -> %d", name, index, static_cast<int>(r));
    return r == vtable_hook::Result::Hooked || r == vtable_hook::Result::AlreadyHooked ||
           r == vtable_hook::Result::RestoreFailed;
}

HRESULT STDMETHODCALLTYPE present(IDXGISwapChain* self, UINT sync, UINT flags);

std::atomic<void**> present_table{nullptr};

void adopt(IDXGISwapChain* swapchain) {
    if (!swapchain) return;
    void** table = *reinterpret_cast<void***>(swapchain);
    void** expected = nullptr;
    // One saved "next Present" serves one vtable; a different swapchain class would chain wrongly.
    if (present_table.compare_exchange_strong(expected, table)) {
        if (!hook(swapchain, kPresent, reinterpret_cast<void*>(&present), next_present, "Present")) return;
    } else if (expected != table) {
        host.log("menu: swapchain %p has a different class; menu stays on the first one", static_cast<void*>(swapchain));
        return;
    }
    target.store(swapchain, std::memory_order_release);
}

// Factories may implement CreateSwapChain by calling CreateSwapChainForHwnd through the vtable (Wine and
// DXVK do). Adopt only when the outermost call returns, after every other layer has hooked the new
// swapchain, so the menu is always the outermost Present layer.
thread_local int creating = 0;

HRESULT STDMETHODCALLTYPE create_swapchain(IDXGIFactory* self, IUnknown* dev, DXGI_SWAP_CHAIN_DESC* desc, IDXGISwapChain** out) {
    const auto next = reinterpret_cast<CreateSwapChainFn>(next_create.load(std::memory_order_acquire));
    ++creating;
    const HRESULT hr = next(self, dev, desc, out);
    if (--creating == 0 && SUCCEEDED(hr) && out) adopt(*out);
    return hr;
}

HRESULT STDMETHODCALLTYPE create_for_hwnd(IDXGIFactory2* self, IUnknown* dev, HWND hwnd, const DXGI_SWAP_CHAIN_DESC1* desc,
    const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fs, IDXGIOutput* output, IDXGISwapChain1** out) {
    const auto next = reinterpret_cast<CreateForHwndFn>(next_create_hwnd.load(std::memory_order_acquire));
    ++creating;
    const HRESULT hr = next(self, dev, hwnd, desc, fs, output, out);
    if (--creating == 0 && SUCCEEDED(hr) && out) adopt(*out);
    return hr;
}

menu_preview::SaveReport save(render_settings::Mode mode, void*) {
    const auto report = menu_settings_io::save(host.module_dir + L"NIER_RENDER.ini", shown, mode, host.reader);
    shown = report.after;
    host.log("menu: save %s -> outcome=%d step=%d error=%lu file=%d next=%s", mode == render_settings::Mode::Native ?
        "Native" : "Custom75", static_cast<int>(report.outcome), static_cast<int>(report.detail.step),
        static_cast<unsigned long>(report.detail.error), static_cast<int>(report.after.file),
        render_settings::name(report.after.next_launch) == L"Native" ? "Native" : "Custom75");
    return {report.outcome, report.after.file, report.after.next_launch};
}

void disable(const char* why) {
    host.log("menu: disabled (%s); frames pass through unchanged", why);
    phase = Phase::Disabled;
}

void initialize(IDXGISwapChain* swapchain) {
    DXGI_SWAP_CHAIN_DESC desc{};
    if (FAILED(swapchain->GetDesc(&desc)) || !desc.OutputWindow) return disable("no swapchain window");
    if (FAILED(swapchain->GetDevice(__uuidof(ID3D11Device), reinterpret_cast<void**>(&device)))) return disable("no D3D11 device");
    device->GetImmediateContext(&context);
    window = desc.OutputWindow;
    const UINT height = desc.BufferDesc.Height;
    scale = height >= 2160 ? 2.f : height >= 1440 ? 1.5f : 1.f;  // shortcut: fixed at first frame; no live DPI changes
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    auto& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.LogFilename = nullptr;
    // Cursor is managed explicitly in render_panel: release the game's capture while the panel is open.
    try {
        menu_preview::apply_style(scale);
        fonts = menu_preview::load_fonts(std::filesystem::path(host.module_dir) / L"nier_render_fonts", scale);
    } catch (const std::exception& error) {
        host.log("menu: font setup failed: %s", error.what());
        ImGui::DestroyContext();
        return disable("fonts");
    }
    if (!ImGui_ImplWin32_Init(window)) { ImGui::DestroyContext(); return disable("win32 backend"); }
    // Create shaders/buffers now: with asserts compiled out, a later silent failure would draw nothing.
    if (!ImGui_ImplDX11_Init(device, context) || !ImGui_ImplDX11_CreateDeviceObjects()) {
        ImGui_ImplDX11_Shutdown(); ImGui_ImplWin32_Shutdown(); ImGui::DestroyContext(); return disable("dx11 backend");
    }
    std::snprintf(display_size, sizeof display_size, "%u\xC3\x97%u", desc.BufferDesc.Width, height);
    host.log("menu: ready window=%p backbuffer=%ux%u scale=%.1f (Insert toggles)", static_cast<void*>(window),
             desc.BufferDesc.Width, height, scale);
    phase = Phase::Ready;
}

bool ensure_state() {
    if (state) return true;
    startup_status::Snapshot snapshot;
    if (!host.startup->read(snapshot)) return false;
    session = menu_session::from_status(snapshot);
    shown = menu_settings_io::observe(host.module_dir + L"NIER_RENDER.ini", host.reader);
    state = std::make_unique<render_menu::State>(session.mode, shown.file, shown.next_launch, session.custom75_available);
    return true;
}

void render_panel(IDXGISwapChain* swapchain) {
    auto& io = ImGui::GetIO();
    const bool focused = GetForegroundWindow() == window;
    const bool insert = focused && (GetAsyncKeyState(VK_INSERT) & 0x8000);
    const bool escape = focused && (GetAsyncKeyState(VK_ESCAPE) & 0x8000);
    const bool insert_pressed = insert && !insert_was, escape_pressed = escape && !escape_was;
    insert_was = insert; escape_was = escape;
    if (insert_pressed && !ensure_state() && !warned_not_ready) {
        host.log("menu: Insert ignored, startup setup still running");
        warned_not_ready = true;
    }
    if (!state) return;
    if (insert_pressed) menu_preview::key_event(*state, ImGuiKey_Insert);
    if (escape_pressed) menu_preview::key_event(*state, ImGuiKey_Escape);
    // The game clips/hides the cursor each frame; free it while the panel is open and re-assert the
    // clip every frame so the game's next clip is undone. ShowCursor pairs across the open/close cycle.
    if (state->open) {
        ClipCursor(nullptr);
        if (!cursor_released) {
            cursor_released = true;
            ShowCursor(TRUE);
            SetCursor(LoadCursorW(nullptr, MAKEINTRESOURCEW(32512)));  // IDC_ARROW (W form; UNICODE may be off)
            host.log("menu: cursor released (panel open)");
        }
    } else if (cursor_released) {
        cursor_released = false;
        ShowCursor(FALSE);  // hide again; net counter change across the cycle is zero
    }
    if (!state->open) return;

    io.AddKeyEvent(ImGuiKey_Escape, escape);
    io.AddMouseButtonEvent(0, focused && (GetAsyncKeyState(GetSystemMetrics(SM_SWAPBUTTON) ? VK_RBUTTON : VK_LBUTTON) & 0x8000));
    io.MouseDrawCursor = false;  // use the now-visible OS cursor, not ImGui's own
    ImGui_ImplDX11_NewFrame();
    ImGui_ImplWin32_NewFrame();
    ImGui::NewFrame();
    const menu_preview::RuntimeInfo info{nullptr, nullptr, display_size, *session.reason ? session.reason : nullptr};
    menu_preview::draw_panel(*state, info, fonts, scale, save, nullptr);
    ImGui::Render();
    ImDrawData* draw = ImGui::GetDrawData();
    static bool reported = false;
    if (!reported && draw) {
        host.log("menu: first open frame vertices=%d lists=%d display=%.0fx%.0f", draw->TotalVtxCount,
                 draw->CmdListsCount, draw->DisplaySize.x, draw->DisplaySize.y);
        reported = draw->TotalVtxCount > 0;
    }
    if (!draw || !draw->TotalVtxCount) return;

    // A fresh view per frame: holding a backbuffer reference would make the game's ResizeBuffers fail.
    ID3D11Texture2D* backbuffer = nullptr;
    if (FAILED(swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&backbuffer)))) return;
    ID3D11RenderTargetView* view = nullptr;
    const HRESULT hr = device->CreateRenderTargetView(backbuffer, nullptr, &view);
    backbuffer->Release();
    if (FAILED(hr)) {
        static bool logged = false;
        if (!logged) host.log("menu: backbuffer view failed hr=0x%08lx", static_cast<unsigned long>(hr));
        logged = true;
        return;
    }
    ID3D11RenderTargetView* saved[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT] = {};
    ID3D11DepthStencilView* saved_depth = nullptr;
    context->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, saved, &saved_depth);
    // The backend restores VS/PS/GS, IA, RS, OM blend/depth, PS slot 0 and VS CB 0, but clears HS/DS/CS
    // without restoring them. Keep the game's bindings for those three stages.
    ID3D11HullShader* hs = nullptr; ID3D11DomainShader* ds = nullptr; ID3D11ComputeShader* cs = nullptr;
    ID3D11ClassInstance *hs_i[256] = {}, *ds_i[256] = {}, *cs_i[256] = {};
    UINT hs_n = 256, ds_n = 256, cs_n = 256;
    context->HSGetShader(&hs, hs_i, &hs_n);
    context->DSGetShader(&ds, ds_i, &ds_n);
    context->CSGetShader(&cs, cs_i, &cs_n);
    context->OMSetRenderTargets(1, &view, nullptr);
    ImGui_ImplDX11_RenderDrawData(draw);
    context->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, saved, saved_depth);
    context->HSSetShader(hs, hs_i, hs_n);
    context->DSSetShader(ds, ds_i, ds_n);
    context->CSSetShader(cs, cs_i, cs_n);
    for (auto* v : saved) if (v) v->Release();
    if (saved_depth) saved_depth->Release();
    for (auto* s : {static_cast<IUnknown*>(hs), static_cast<IUnknown*>(ds), static_cast<IUnknown*>(cs)}) if (s) s->Release();
    for (UINT i = 0; i < hs_n; ++i) if (hs_i[i]) hs_i[i]->Release();
    for (UINT i = 0; i < ds_n; ++i) if (ds_i[i]) ds_i[i]->Release();
    for (UINT i = 0; i < cs_n; ++i) if (cs_i[i]) cs_i[i]->Release();
    view->Release();
}

HRESULT STDMETHODCALLTYPE present(IDXGISwapChain* self, UINT sync, UINT flags) {
    const auto next = reinterpret_cast<PresentFn>(next_present.load(std::memory_order_acquire));
    if (self == target.load(std::memory_order_acquire) && !(flags & DXGI_PRESENT_TEST) && phase != Phase::Disabled) {
        try {
            if (phase == Phase::Waiting) initialize(self);
            if (phase == Phase::Ready) render_panel(self);
        } catch (...) {
            disable("unexpected exception");
        }
    }
    return next(self, sync, flags);
}
}  // namespace

void install(ID3D11Device* dev, IDXGISwapChain* swapchain, const Host& h) {
    if (!dev) return;
    if (!installed.exchange(true)) {
        host = h;
        IDXGIDevice* dxgi = nullptr;
        IDXGIAdapter* adapter = nullptr;
        IDXGIFactory* factory = nullptr;
        if (SUCCEEDED(dev->QueryInterface(__uuidof(IDXGIDevice), reinterpret_cast<void**>(&dxgi))) &&
            SUCCEEDED(dxgi->GetAdapter(&adapter)) &&
            SUCCEEDED(adapter->GetParent(__uuidof(IDXGIFactory), reinterpret_cast<void**>(&factory)))) {
            hook(factory, kCreateSwapChain, reinterpret_cast<void*>(&create_swapchain), next_create, "CreateSwapChain");
            IDXGIFactory2* factory2 = nullptr;
            if (SUCCEEDED(factory->QueryInterface(__uuidof(IDXGIFactory2), reinterpret_cast<void**>(&factory2)))) {
                hook(factory2, kCreateSwapChainForHwnd, reinterpret_cast<void*>(&create_for_hwnd), next_create_hwnd,
                     "CreateSwapChainForHwnd");
                factory2->Release();
            }
        } else {
            host.log("menu: no DXGI factory from device; menu unavailable");
        }
        if (factory) factory->Release();
        if (adapter) adapter->Release();
        if (dxgi) dxgi->Release();
    }
    adopt(swapchain);
}
}  // namespace menu_overlay
