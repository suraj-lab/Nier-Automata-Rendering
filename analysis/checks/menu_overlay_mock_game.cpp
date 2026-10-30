// Mock game for the in-game menu: loads the proxy d3d11.dll from its own folder, creates a device and a
// factory swapchain like NieR, presents frames, presses Insert and clicks with real Win32 input.
// Usage: menu_overlay_mock_game.exe <click_x> <click_y>   (client coordinates; 0 0 = no click)
// Writes mock-result.txt. Frame plan: 1-29 closed, capture "closed" at 25, Insert at 30, capture "open" at 45,
// click at 50 (down) / 53 (up), capture "after" at 70, exit at 80.
// Opt-in for the Remix host test (defaults unchanged): MOCK_BGRA=1 -> B8G8R8A8 backbuffer, MOCK_FRAME_MS=<n>
// -> sleep per frame (default 16), MOCK_RESIZE_AT=<frame> -> ResizeBuffers at that frame to MOCK_RESIZE_TO=<w>x<h>
// (default 1280x720), MOCK_START=<w>x<h> -> initial backbuffer size (default 1920x1080; the window stays 1920x1080).
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <limits>
#include <functional>
#include "vtable_hook.h"
#include <map>

// The live-camera gate verifies this slot with offsetof(ID3D11DeviceContextVtbl, CopyResource).
static std::atomic<void*> next_copy{nullptr};
static unsigned camera_reads = 0, geometry_reads = 0, frame_camera_reads = 0, peak_camera_reads = 0;
static unsigned geometry_reads_late = 0;
static int mock_frame_index = 0;
static std::function<void()> downstream_draw;
extern "C" __declspec(dllexport) void mock_downstream_camera_draw() { if (downstream_draw) downstream_draw(); }
static bool spy_protect(void* p, std::size_t n, unsigned long mode, unsigned long* old) {
    return VirtualProtect(p, n, mode, old) != 0;
}
static void STDMETHODCALLTYPE spy_copy(ID3D11DeviceContext* self, ID3D11Resource* dst, ID3D11Resource* src) {
    D3D11_RESOURCE_DIMENSION kind{}; src->GetType(&kind);
    if (kind == D3D11_RESOURCE_DIMENSION_BUFFER) {
        ID3D11Buffer* buffer = nullptr;
        if (SUCCEEDED(src->QueryInterface(__uuidof(ID3D11Buffer), reinterpret_cast<void**>(&buffer)))) {
            D3D11_BUFFER_DESC d{}; buffer->GetDesc(&d); buffer->Release();
            if (d.BindFlags & D3D11_BIND_CONSTANT_BUFFER) { ++camera_reads; ++frame_camera_reads; }
            if (d.BindFlags & (D3D11_BIND_VERTEX_BUFFER | D3D11_BIND_INDEX_BUFFER)) { ++geometry_reads; if (mock_frame_index >= 60) ++geometry_reads_late; }
        }
    }
    using Fn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, ID3D11Resource*);
    reinterpret_cast<Fn>(next_copy.load())(self, dst, src);
}

// ---- a stand-in for an overlay that finds Present through the SHARED DXGI vtable (MOCK_OVERLAY_REHOOK=N) ----
// Typical overlay code: discover Present from a dummy swapchain's vtable, patch the start of that function's code,
// and keep ONE global "original" that its single detour calls. Re-discovery (Steam does it when another graphics API
// loads; on the laptop that is when Remix starts) patches the newly found function and overwrites the global. If the
// shared slot then holds another layer's hook, the old patch now leads back into that layer: an endless Present loop.
// "Calling the original" is done by unpatching around the call; loops are cut at depth 16 and counted.
using OvPresentFn = HRESULT (STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);
struct OvPatch { bool on = false; unsigned char saved[14] = {}; };
static std::map<void*, OvPatch>& ov_patches() { static std::map<void*, OvPatch> m; return m; }
static void* ov_orig = nullptr;
static int ov_depth = 0;
static unsigned ov_calls = 0, ov_loops = 0, ov_discoveries = 0;
static OvPresentFn second_next = nullptr;
static unsigned second_calls = 0, second_created = 0, foreign_hooked = 0, foreign_created = 0;
static HRESULT STDMETHODCALLTYPE second_present(IDXGISwapChain* self, UINT sync, UINT flags) {
    ++second_calls;
    return second_next(self, sync, flags);
}
static void ov_write(void* fn, const unsigned char* bytes) {
    DWORD old = 0;
    VirtualProtect(fn, 14, PAGE_EXECUTE_READWRITE, &old);
    std::memcpy(fn, bytes, 14);
    VirtualProtect(fn, 14, old, &old);
    FlushInstructionCache(GetCurrentProcess(), fn, 14);
}
static HRESULT STDMETHODCALLTYPE ov_present(IDXGISwapChain* self, UINT sync, UINT flags);
static void ov_patch(void* fn) {
    auto& entry = ov_patches()[fn];
    if (entry.on) return;
    std::memcpy(entry.saved, fn, 14);
    unsigned char jump[14] = {0xFF, 0x25, 0, 0, 0, 0};  // jmp [rip+0]; dq target
    void* detour = reinterpret_cast<void*>(&ov_present);
    std::memcpy(jump + 6, &detour, 8);
    ov_write(fn, jump);
    entry.on = true;
}
static void ov_unpatch(void* fn) {
    auto it = ov_patches().find(fn);
    if (it == ov_patches().end() || !it->second.on) return;
    ov_write(fn, it->second.saved);
    it->second.on = false;
}
static HRESULT STDMETHODCALLTYPE ov_present(IDXGISwapChain* self, UINT sync, UINT flags) {
    if (ov_depth >= 16) { ++ov_loops; return S_OK; }  // the real overlay would overflow the stack here
    ++ov_depth; ++ov_calls;
    void* orig = ov_orig;
    ov_unpatch(orig);
    const HRESULT hr = reinterpret_cast<OvPresentFn>(orig)(self, sync, flags);
    ov_patch(orig);
    --ov_depth;
    return hr;
}
static void ov_discover(IDXGISwapChain* dummy) {
    void* fn = (*reinterpret_cast<void***>(dummy))[8];
    ov_patch(fn);
    ov_orig = fn;
    ++ov_discoveries;
}

static void key(WORD vk, bool down) {
    INPUT in{}; in.type = INPUT_KEYBOARD; in.ki.wVk = vk; in.ki.dwFlags = down ? 0 : KEYEVENTF_KEYUP;
    SendInput(1, &in, sizeof in);
}
static void button(bool down) {
    INPUT in{}; in.type = INPUT_MOUSE; in.mi.dwFlags = down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
    SendInput(1, &in, sizeof in);
}
// Move the OS cursor like a real physical mouse (SendInput), NOT SetCursorPos (which the overlay
// now blocks to stop the game's re-centering).
static void move_mouse(POINT screen) {
    INPUT in{}; in.type = INPUT_MOUSE;
    in.mi.dx = static_cast<LONG>((static_cast<long long>(screen.x) * 65535) / GetSystemMetrics(SM_CXSCREEN));
    in.mi.dy = static_cast<LONG>((static_cast<long long>(screen.y) * 65535) / GetSystemMetrics(SM_CYSCREEN));
    in.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &in, sizeof in);
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 3) return 2;
    const int click_x = _wtoi(argv[1]), click_y = _wtoi(argv[2]);
    FILE* out = _wfopen(L"mock-result.txt", L"w");
    if (!out) return 2;
    WNDCLASSW wc{}; wc.lpfnWndProc = DefWindowProcW; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"MockNier";
    RegisterClassW(&wc);
    RECT rect{0, 0, 1920, 1080}; AdjustWindowRect(&rect, WS_OVERLAPPEDWINDOW, FALSE);
    HWND hwnd = CreateWindowW(wc.lpszClassName, L"mock", WS_OVERLAPPEDWINDOW, 0, 0, rect.right - rect.left,
                              rect.bottom - rect.top, nullptr, nullptr, wc.hInstance, nullptr);
    ShowWindow(hwnd, SW_SHOW); SetForegroundWindow(hwnd); SetFocus(hwnd);

    // DirectInput devices created BEFORE the menu exists, like NieR's camera mouse. Never acquired, so the
    // real GetDeviceState fails and leaves the buffer alone: a 0xAB-filled buffer coming back zeroed proves
    // the overlay's hook blanked it.
    IDirectInput8W* di = nullptr; IDirectInputDevice8W* di_mouse = nullptr; IDirectInputDevice8W* di_keyboard = nullptr;
    if (FAILED(DirectInput8Create(GetModuleHandleW(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8W, reinterpret_cast<void**>(&di), nullptr)) ||
        FAILED(di->CreateDevice(GUID_SysMouse, &di_mouse, nullptr)) || FAILED(di->CreateDevice(GUID_SysKeyboard, &di_keyboard, nullptr))) {
        std::fprintf(out, "FAIL dinput\n"); return 3;
    }
    di_mouse->SetDataFormat(&c_dfDIMouse); di_keyboard->SetDataFormat(&c_dfDIKeyboard);
    // 1 = buffer zeroed by the hook, 0 = untouched (still 0xAB)
    const auto blanked = [](IDirectInputDevice8W* dev, DWORD size) {
        unsigned char buf[256]; std::memset(buf, 0xAB, sizeof buf);
        dev->GetDeviceState(size, buf);
        for (DWORD i = 0; i < size; ++i) if (buf[i] != 0) return 0;
        return 1;
    };

    HMODULE proxy = LoadLibraryW(L"d3d11.dll");
    // MOCK_OVERLAY_REHOOK: the overlay's dummy swapchain comes from the system d3d11 before the game device exists (so
    // before our proxy hooks anything); first discovery now, re-discovery at frame N.
    const int overlay_rehook = std::getenv("MOCK_OVERLAY_REHOOK") ? std::atoi(std::getenv("MOCK_OVERLAY_REHOOK")) : 0;
    IDXGISwapChain* overlay_dummy = nullptr;
    if (overlay_rehook) {
        HWND dummy_window = CreateWindowW(wc.lpszClassName, L"overlay-dummy", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, nullptr,
                                          nullptr, wc.hInstance, nullptr);
        auto system_create = reinterpret_cast<decltype(&D3D11CreateDeviceAndSwapChain)>(reinterpret_cast<void*>(
            GetProcAddress(LoadLibraryW(L"C:\\windows\\system32\\d3d11.dll"), "D3D11CreateDeviceAndSwapChain")));
        DXGI_SWAP_CHAIN_DESC dd{};
        dd.BufferCount = 1; dd.BufferDesc.Width = 64; dd.BufferDesc.Height = 64; dd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        dd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; dd.OutputWindow = dummy_window; dd.SampleDesc.Count = 1; dd.Windowed = TRUE;
        ID3D11Device* dummy_device = nullptr;
        if (!system_create || FAILED(system_create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION,
                                                   &dd, &overlay_dummy, &dummy_device, nullptr, nullptr)) || !overlay_dummy) {
            std::fprintf(out, "FAIL overlay dummy\n"); return 3;
        }
        ov_discover(overlay_dummy);
    }
    HMODULE stub = GetModuleHandleW(L"d3d11_dlaa.dll");
    auto create = reinterpret_cast<decltype(&D3D11CreateDevice)>(reinterpret_cast<void*>(GetProcAddress(proxy, "D3D11CreateDevice")));
    char self_path[MAX_PATH] = ""; GetModuleFileNameA(proxy, self_path, MAX_PATH);
    std::fprintf(out, "proxy=%s\n", self_path);
    ID3D11Device* device = nullptr; ID3D11DeviceContext* context = nullptr;
    if (create && std::getenv("MOCK_PROXY_FIRST_DEVICE")) {
        // Device enumeration can create a throwaway device through our proxy before the game makes its real one.
        ID3D11Device* probe_device = nullptr; ID3D11DeviceContext* probe_context = nullptr;
        if (FAILED(create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION,
                          &probe_device, nullptr, &probe_context))) { std::fprintf(out, "FAIL probe device\n"); return 3; }
        probe_context->Release(); probe_device->Release();
    }
    if (!create || FAILED(create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &device, nullptr, &context))) {
        std::fprintf(out, "FAIL device\n"); return 3;
    }
    stub = GetModuleHandleW(L"d3d11_dlaa.dll");
    auto count = reinterpret_cast<unsigned (*)()>(reinterpret_cast<void*>(GetProcAddress(stub, "stub_present_count")));
    auto request = reinterpret_cast<void (*)(const wchar_t*)>(reinterpret_cast<void*>(GetProcAddress(stub, "stub_request_capture")));
    if (!count || !request) { std::fprintf(out, "FAIL stub exports\n"); return 3; }
    IDXGIDevice* dxgi = nullptr; IDXGIAdapter* adapter = nullptr; IDXGIFactory* factory = nullptr;
    device->QueryInterface(__uuidof(IDXGIDevice), reinterpret_cast<void**>(&dxgi));
    dxgi->GetAdapter(&adapter);
    adapter->GetParent(__uuidof(IDXGIFactory), reinterpret_cast<void**>(&factory));
    DXGI_SWAP_CHAIN_DESC sd{};
    UINT start_w = 1920, start_h = 1080, resize_w = 1280, resize_h = 720;
    if (const char* e = std::getenv("MOCK_START")) std::sscanf(e, "%ux%u", &start_w, &start_h);
    if (const char* e = std::getenv("MOCK_RESIZE_TO")) std::sscanf(e, "%ux%u", &resize_w, &resize_h);
    sd.BufferCount = 2; sd.BufferDesc.Width = start_w; sd.BufferDesc.Height = start_h;
    const char* bgra = std::getenv("MOCK_BGRA");
    sd.BufferDesc.Format = bgra && !std::strcmp(bgra, "1") ? DXGI_FORMAT_B8G8R8A8_UNORM : DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    const DWORD frame_ms = std::getenv("MOCK_FRAME_MS") ? static_cast<DWORD>(std::atoi(std::getenv("MOCK_FRAME_MS"))) : 16;
    const int resize_at = std::getenv("MOCK_RESIZE_AT") ? std::atoi(std::getenv("MOCK_RESIZE_AT")) : 0;
    const char* camera_mode = std::getenv("MOCK_CAMERA");
    if (camera_mode) {
        const auto hooked = vtable_hook::hook(*reinterpret_cast<void***>(context), 47,
            reinterpret_cast<void*>(&spy_copy), next_copy, spy_protect);
        if (hooked != vtable_hook::Result::Hooked) { std::fprintf(out, "FAIL camera copy spy\n"); return 3; }
    }
    sd.OutputWindow = hwnd; sd.SampleDesc.Count = 1; sd.Windowed = TRUE; sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    IDXGISwapChain* swapchain = nullptr;
    if (FAILED(factory->CreateSwapChain(device, &sd, &swapchain))) { std::fprintf(out, "FAIL swapchain\n"); return 3; }
    POINT click{click_x, click_y}; ClientToScreen(hwnd, &click);
    // A game compute shader bound across Present: the overlay must leave it bound (the ImGui DX11 backend
    // clears HS/DS/CS without restoring them).
    using CompileFn = decltype(&D3DCompile);
    FARPROC compile_proc = GetProcAddress(LoadLibraryW(L"d3dcompiler_47.dll"), "D3DCompile");
    CompileFn compile = nullptr; std::memcpy(&compile, &compile_proc, sizeof compile);
    const char cs_src[] = "[numthreads(1,1,1)] void main() {}";
    ID3DBlob* blob = nullptr; ID3D11ComputeShader* cs = nullptr;
    if (!compile || FAILED(compile(cs_src, sizeof cs_src - 1, nullptr, nullptr, nullptr, "main", "cs_5_0", 0, 0, &blob, nullptr)) ||
        FAILED(device->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &cs))) {
        std::fprintf(out, "FAIL compute shader\n"); return 3;
    }
    blob->Release();
    // A cutout pixel shader: the capture hook must write its bytecode when NIER_SHADER_DIR is set, so an
    // offline tool can tell `discard` shaders from opaque ones (test_shader_capture.py asserts this).
    const char cutout_src[] = "Texture2D t : register(t0); SamplerState s : register(s0);"
                              "float4 main(float2 uv : TEXCOORD0) : SV_Target { float4 c = t.Sample(s, uv);"
                              " if (c.a < 0.5) discard; return c; }";
    ID3DBlob* cutout_blob = nullptr; ID3D11PixelShader* cutout_ps = nullptr;
    if (!compile || FAILED(compile(cutout_src, sizeof cutout_src - 1, nullptr, nullptr, nullptr, "main", "ps_5_0", 0, 0, &cutout_blob, nullptr)) ||
        FAILED(device->CreatePixelShader(cutout_blob->GetBufferPointer(), cutout_blob->GetBufferSize(), nullptr, &cutout_ps))) {
        std::fprintf(out, "FAIL cutout pixel shader\n"); return 3;
    }
    cutout_blob->Release();
    // Distinctive render state, so the capture path's state block can be proven end-to-end rather than assumed:
    // alpha blending, depth test on but write off with GREATER, and FRONT-face culling in wireframe.
    D3D11_BLEND_DESC bd{};
    bd.RenderTarget[0].BlendEnable = TRUE;
    bd.RenderTarget[0].SrcBlend = D3D11_BLEND_SRC_ALPHA;
    bd.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD;
    // Alpha fields and a 4-bit mask: wined3d accepted 0 / 0xFF, DXVK (correctly) rejects them as invalid.
    bd.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ONE;
    bd.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_ZERO;
    bd.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
    bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    ID3D11BlendState* probe_blend = nullptr;
    if (FAILED(device->CreateBlendState(&bd, &probe_blend))) { std::fprintf(out, "FAIL blend state\n"); return 3; }
    // Additive blending (particles, light shafts): blending is on, but it is not a cutout and must not be marked one.
    D3D11_BLEND_DESC abd = bd;
    abd.RenderTarget[0].SrcBlend = D3D11_BLEND_ONE;
    abd.RenderTarget[0].DestBlend = D3D11_BLEND_ONE;
    ID3D11BlendState* additive_blend = nullptr;
    if (FAILED(device->CreateBlendState(&abd, &additive_blend))) { std::fprintf(out, "FAIL additive blend\n"); return 3; }
    D3D11_DEPTH_STENCIL_DESC dd{};
    dd.DepthEnable = TRUE; dd.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ZERO; dd.DepthFunc = D3D11_COMPARISON_GREATER;
    dd.FrontFace = dd.BackFace = {D3D11_STENCIL_OP_KEEP, D3D11_STENCIL_OP_KEEP, D3D11_STENCIL_OP_KEEP, D3D11_COMPARISON_ALWAYS};
    ID3D11DepthStencilState* probe_depth = nullptr;
    if (FAILED(device->CreateDepthStencilState(&dd, &probe_depth))) { std::fprintf(out, "FAIL depth state\n"); return 3; }
    D3D11_RASTERIZER_DESC rd{};
    rd.FillMode = D3D11_FILL_WIREFRAME; rd.CullMode = D3D11_CULL_FRONT; rd.DepthClipEnable = TRUE;
    ID3D11RasterizerState* probe_raster = nullptr;
    if (FAILED(device->CreateRasterizerState(&rd, &probe_raster))) { std::fprintf(out, "FAIL raster state\n"); return 3; }
    // Capture test: a known mesh + F9 trigger. The menu is closed until frame 30, so poll_capture
    // arms capture_next (F9 down at frame 1) and the mesh draw (frame 3) is the next DrawIndexed.
    const char vs_src[] =
        "struct VSOut { float4 pos : SV_POSITION; };\n"
        "VSOut main(float4 pos : POSITION, float4 col : COLOR) { VSOut o; o.pos = pos; return o; }\n";
    ID3DBlob* vs_blob = nullptr;
    if (!compile || FAILED(compile(vs_src, sizeof vs_src - 1, "vs", nullptr, nullptr, "main", "vs_4_0", 0, 0, &vs_blob, nullptr)))
        { std::fprintf(out, "FAIL mesh vs\n"); return 3; }
    D3D11_INPUT_ELEMENT_DESC mesh_desc[2] = {
        {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0,  D3D11_INPUT_PER_VERTEX_DATA, 0},
        {"COLOR",    0, DXGI_FORMAT_R8G8B8A8_UNORM,     0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0},
    };
    ID3D11InputLayout* mesh_layout = nullptr;
    device->CreateInputLayout(mesh_desc, 2, vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), &mesh_layout);
    ID3D11VertexShader* mesh_vs = nullptr;
    device->CreateVertexShader(vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), nullptr, &mesh_vs);
    vs_blob->Release();
    // MOCK_CUTOUT_PS: the scene's pixel shader alpha-tests its texture the way NieR's foliage shaders do
    // (lt r, alpha, l(0.5) / discard_nz r): the live path must give those meshes an alpha-test material.
    const char ps_src[] = "float4 main() : SV_TARGET { return float4(0,0,0,0); }\n";
    const char cutout_ps_src[] =
        "Texture2D t : register(t0);\n"
        "float4 main(float4 p : SV_POSITION) : SV_TARGET { float4 c = t.Load(int3(0, 0, 0)); if (c.a < 0.5) discard; return c; }\n";
    const bool mesh_discards = std::getenv("MOCK_CUTOUT_PS") != nullptr;
    ID3DBlob* ps_blob = nullptr;
    const char* mesh_ps_src = mesh_discards ? cutout_ps_src : ps_src;
    const SIZE_T mesh_ps_len = mesh_discards ? sizeof cutout_ps_src - 1 : sizeof ps_src - 1;
    if (!compile || FAILED(compile(mesh_ps_src, mesh_ps_len, "ps", nullptr, nullptr, "main", "ps_4_0", 0, 0, &ps_blob, nullptr)))
        { std::fprintf(out, "FAIL mesh ps\n"); return 3; }
    ID3D11PixelShader* mesh_ps = nullptr;
    device->CreatePixelShader(ps_blob->GetBufferPointer(), ps_blob->GetBufferSize(), nullptr, &mesh_ps);
    ps_blob->Release();
    // The scene target: the display aspect at half scale, like an engine's internal render target. Square-ish or
    // final-sized targets are other passes; the render-target filter keyed on this distinction (live-passes mode).
    // live-odd uses a square scene target, which no aspect rule can recognise: the filter must then latch itself off
    // rather than present an empty picture.
    const bool square_rt = camera_mode && !std::strcmp(camera_mode, "live-odd");
    // MOCK_SCENE_FULL: the scene target is as large as the final image (native render scale). Blended scene draws into
    // it must stay world geometry, not be taken for the HUD.
    const bool full_rt = std::getenv("MOCK_SCENE_FULL") != nullptr;
    D3D11_TEXTURE2D_DESC mrt{}; mrt.Width = square_rt ? 512 : (full_rt ? 1920 : 960); mrt.Height = square_rt ? 512 : (full_rt ? 1080 : 540);
    mrt.MipLevels = 1; mrt.ArraySize = 1;
    mrt.Format = DXGI_FORMAT_R8G8B8A8_UNORM; mrt.SampleDesc.Count = 1; mrt.Usage = D3D11_USAGE_DEFAULT; mrt.BindFlags = D3D11_BIND_RENDER_TARGET;
    ID3D11Texture2D* mesh_rt_tex = nullptr; device->CreateTexture2D(&mrt, nullptr, &mesh_rt_tex);
    ID3D11RenderTargetView* mesh_rtv = nullptr; device->CreateRenderTargetView(mesh_rt_tex, nullptr, &mesh_rtv);
    // A triangle fan with 65 vertices -> 64 triangles -> 192 indices (>= the 128-index capture filter).
    unsigned char mesh_vb[65 * 16];
    for (unsigned i = 0; i < sizeof(mesh_vb); ++i) mesh_vb[i] = static_cast<unsigned char>((i * 13 + 7) & 0xff);
    unsigned short mesh_ib[192];
    unsigned mi = 0;
    for (unsigned i = 1; i <= 63; ++i) { mesh_ib[mi++] = 0; mesh_ib[mi++] = static_cast<unsigned short>(i); mesh_ib[mi++] = static_cast<unsigned short>(i + 1); }
    mesh_ib[mi++] = 0; mesh_ib[mi++] = 64; mesh_ib[mi++] = 1;  // close the fan
    unsigned char mesh_cb[64];
    for (unsigned i = 0; i < sizeof(mesh_cb); ++i) mesh_cb[i] = static_cast<unsigned char>((i * 17 + 3) & 0xff);
    D3D11_BUFFER_DESC mb{}; mb.ByteWidth = sizeof(mesh_vb); mb.Usage = D3D11_USAGE_DEFAULT; mb.BindFlags = D3D11_BIND_VERTEX_BUFFER;
    D3D11_SUBRESOURCE_DATA md = {mesh_vb, 0, 0}; ID3D11Buffer* mesh_vb_buf = nullptr; device->CreateBuffer(&mb, &md, &mesh_vb_buf);
    D3D11_BUFFER_DESC mib{}; mib.ByteWidth = sizeof(mesh_ib); mib.Usage = D3D11_USAGE_DEFAULT; mib.BindFlags = D3D11_BIND_INDEX_BUFFER;
    D3D11_SUBRESOURCE_DATA mid = {mesh_ib, 0, 0}; ID3D11Buffer* mesh_ib_buf = nullptr; device->CreateBuffer(&mib, &mid, &mesh_ib_buf);
    D3D11_BUFFER_DESC mcb{}; mcb.ByteWidth = sizeof(mesh_cb); mcb.Usage = D3D11_USAGE_DEFAULT; mcb.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    D3D11_SUBRESOURCE_DATA mcd = {mesh_cb, 0, 0}; ID3D11Buffer* mesh_cb_buf = nullptr; device->CreateBuffer(&mcb, &mcd, &mesh_cb_buf);
    float camera_cb[64] = {};
    camera_cb[0] = camera_cb[5] = camera_cb[10] = camera_cb[15] = 1;
    camera_cb[16] = 1080.f / 1920.f; camera_cb[21] = 1;
    camera_cb[26] = -1.00001f; camera_cb[27] = -.1f; camera_cb[30] = -1;
    D3D11_BUFFER_DESC camera_desc{}; camera_desc.ByteWidth = sizeof camera_cb;
    camera_desc.Usage = D3D11_USAGE_DEFAULT; camera_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    ID3D11Buffer* camera_buffer = nullptr;
    if (camera_mode && FAILED(device->CreateBuffer(&camera_desc, nullptr, &camera_buffer))) {
        std::fprintf(out, "FAIL camera buffer\n"); return 3;
    }
    // PS material textures: slot 0 static RGBA 4x4, slot 1 a render target (must NOT be captured), slot 2 static
    // BC1 8x8 (2x2 blocks of 8 bytes). Byte patterns are recomputed by test_menu_overlay.py.
    unsigned char rgba[4 * 4 * 4], bc1[2 * 2 * 8];
    for (unsigned i = 0; i < sizeof rgba; ++i) rgba[i] = static_cast<unsigned char>((i * 7 + 3) & 0xff);
    for (unsigned i = 0; i < sizeof bc1; ++i) bc1[i] = static_cast<unsigned char>((i * 5 + 1) & 0xff);
    const auto make_srv = [&](UINT w, UINT h, DXGI_FORMAT fmt, const void* data, UINT pitch, UINT bind) {
        D3D11_TEXTURE2D_DESC td{}; td.Width = w; td.Height = h; td.MipLevels = 1; td.ArraySize = 1; td.Format = fmt;
        td.SampleDesc.Count = 1; td.Usage = D3D11_USAGE_DEFAULT; td.BindFlags = D3D11_BIND_SHADER_RESOURCE | bind;
        D3D11_SUBRESOURCE_DATA sd = {data, pitch, 0};
        ID3D11Texture2D* t = nullptr; ID3D11ShaderResourceView* v = nullptr;
        if (FAILED(device->CreateTexture2D(&td, data ? &sd : nullptr, &t)) || FAILED(device->CreateShaderResourceView(t, nullptr, &v))) return v;
        t->Release();
        return v;
    };
    ID3D11ShaderResourceView* mesh_srvs[3] = {
        make_srv(4, 4, DXGI_FORMAT_R8G8B8A8_UNORM, rgba, 16, 0),
        make_srv(16, 16, DXGI_FORMAT_R8G8B8A8_UNORM, nullptr, 0, D3D11_BIND_RENDER_TARGET),
        make_srv(8, 8, DXGI_FORMAT_BC1_UNORM, bc1, 16, 0)};
    if (!mesh_srvs[0] || !mesh_srvs[1] || !mesh_srvs[2]) { std::fprintf(out, "FAIL textures\n"); return 3; }
    // The tiled-forward light arrays, bound the way the game binds them, so an F9 capture records them for the laptop
    // probe: points at t20 (48-byte elements, BUFFEREX view, the view starts at element 1), spots at t22 (80 bytes).
    ID3D11ShaderResourceView* capture_lights[2] = {};
    {
        float points[36] = {};                    // 3 elements; element 0 is skipped by the view's FirstElement
        float* p1 = points + 12; p1[0] = 7; p1[1] = 8; p1[2] = 9; p1[3] = 30; p1[8] = 1; p1[9] = 0.5f; p1[10] = 0.25f; p1[11] = 2;
        float* p2 = points + 24; p2[0] = -4; p2[1] = 2; p2[2] = 11; p2[3] = 12; p2[8] = 0.5f; p2[9] = 0.5f; p2[10] = 2; p2[11] = 1;
        float spots[20] = {1, 2, 3, 0.866f, 0, 0, 0, 0, 3, 3, 3, 0.966f, 0, -1, 0, 0, 0, 0, 0, 0};
        const auto make = [&](const float* data, UINT bytes, UINT stride, bool ex, UINT first, UINT count) {
            D3D11_BUFFER_DESC bd{}; bd.ByteWidth = bytes; bd.Usage = D3D11_USAGE_IMMUTABLE; bd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
            bd.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED; bd.StructureByteStride = stride;
            D3D11_SUBRESOURCE_DATA sd{}; sd.pSysMem = data;
            ID3D11Buffer* b = nullptr; ID3D11ShaderResourceView* v = nullptr;
            D3D11_SHADER_RESOURCE_VIEW_DESC vd{}; vd.Format = DXGI_FORMAT_UNKNOWN;
            if (ex) { vd.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX; vd.BufferEx.FirstElement = first; vd.BufferEx.NumElements = count; }
            else { vd.ViewDimension = D3D11_SRV_DIMENSION_BUFFER; vd.Buffer.FirstElement = first; vd.Buffer.NumElements = count; }
            if (SUCCEEDED(device->CreateBuffer(&bd, &sd, &b)) && b) { device->CreateShaderResourceView(b, &vd, &v); b->Release(); }
            return v;
        };
        capture_lights[0] = make(points, sizeof points, 48, true, 1, 2);
        capture_lights[1] = make(spots, sizeof spots, 80, false, 0, 1);
        if (!capture_lights[0] || !capture_lights[1]) { std::fprintf(out, "FAIL capture lights\n"); return 3; }
    }
    const auto draw_mesh = [&]() {
        const UINT mstride = 16, moff = 0;
        context->OMSetRenderTargets(1, &mesh_rtv, nullptr);
        D3D11_VIEWPORT vp{0, 0, camera_mode ? 1920.f : 64.f, camera_mode ? 1080.f : 64.f, 0, 1};
        context->RSSetViewports(1, &vp);
        context->IASetInputLayout(mesh_layout);
        context->IASetVertexBuffers(0, 1, &mesh_vb_buf, &mstride, &moff);
        context->IASetIndexBuffer(mesh_ib_buf, DXGI_FORMAT_R16_UINT, 0);
        context->VSSetShader(mesh_vs, nullptr, 0);
        context->PSSetShader(mesh_ps, nullptr, 0);
        ID3D11Buffer* vertex_cb = camera_mode ? camera_buffer : mesh_cb_buf;
        context->VSSetConstantBuffers(0, 1, &vertex_cb);
        context->PSSetConstantBuffers(0, 1, &mesh_cb_buf);  // one PS buffer at a slot the VS also uses
        context->PSSetShaderResources(0, 3, mesh_srvs);
        context->PSSetShaderResources(20, 1, &capture_lights[0]);
        context->PSSetShaderResources(22, 1, &capture_lights[1]);
        context->OMSetBlendState(probe_blend, nullptr, 0xFFFFFFFF);
        context->OMSetDepthStencilState(probe_depth, 0);
        context->RSSetState(probe_raster);
        if (camera_mode && !std::strcmp(camera_mode, "instanced")) context->DrawIndexedInstanced(192, 2, 0, 0, 0);
        else context->DrawIndexed(192, 0, 0);
    };
    if (camera_mode && (!std::strcmp(camera_mode, "present-boundary") || !std::strcmp(camera_mode, "present-fail"))) {
        downstream_draw = [&] {
            const float x = camera_cb[3], y = camera_cb[7], z = camera_cb[11];
            camera_cb[3] = camera_cb[7] = camera_cb[11] = -999;
            context->UpdateSubresource(camera_buffer, 0, nullptr, camera_cb, 0, 0);
            draw_mesh();
            camera_cb[3] = x; camera_cb[7] = y; camera_cb[11] = z;
            context->UpdateSubresource(camera_buffer, 0, nullptr, camera_cb, 0, 0);
        };
    }
    // Live-geometry mode: mesh A every frame (dynamic VB, content changes once at frame 50), mesh B from
    // frame 40 (DEFAULT buffers), one material texture, and a CB11 world translation that follows the frame.
    // Buffers written through Map are shadowable, so a correct live path reads no geometry back per frame.
    const bool live_offset = camera_mode && !std::strcmp(camera_mode, "live-offset");
    // live-box: boxed (partial) UpdateSubresource from a source that ends exactly at a guard page, plus a
    // never-bound dynamic buffer whose reference count shows whether the proxy holds on to game buffers.
    const bool live_box = camera_mode && !std::strcmp(camera_mode, "live-box");
    // live-evict: mesh A every frame, mesh B only on frames 40-45 and again from 65, mesh C (A's buffers, 189
    // indices) from 55. With a budget for two meshes, C's arrival must evict the then-unused B, and B must be
    // rebuilt when it comes back instead of staying invisible.
    const bool live_evict = camera_mode && !std::strcmp(camera_mode, "live-evict");
    // live-passes: the same mesh is also drawn into a differently-sized target with a small viewport, the way a
    // shadow-pass would be. Those draws must never reach Remix.
    const bool live_passes = camera_mode && !std::strcmp(camera_mode, "live-passes");
    const bool live_odd = camera_mode && !std::strcmp(camera_mode, "live-odd");
    // live-blend: the scene draws use classic straight-alpha blending, the way foliage and grilles are drawn.
    const bool live_blend = camera_mode && !std::strcmp(camera_mode, "live-blend");
    // live-lights: the scene draws are accompanied by the tiled-forward light array NieR binds at PS slot 20
    // (structured buffer, 48-byte elements). live-nolights is the same scene with an empty array: the red test.
    const bool live_lights = camera_mode && !std::strcmp(camera_mode, "live-lights");
    // live-hud: like live-late, plus a green clip-space quad drawn into the backbuffer after the scene, the way the
    // game draws its HUD sprite pass. Used to prove the UI is replayed over the Remix image.
    const bool live_native_hud = camera_mode && !std::strcmp(camera_mode, "live-native-hud");
    const bool live_hud = live_native_hud || (camera_mode && !std::strcmp(camera_mode, "live-hud"));
    const bool live_nolights = camera_mode && !std::strcmp(camera_mode, "live-nolights");
    // live-late: two geometries with two different textures, steady from frame 1, no evictions. Used to prove that a
    // geometry whose texture was not captured yet gets its material when the texture finally lands.
    const bool live_late = camera_mode && !std::strcmp(camera_mode, "live-late");
    // live-additive: blending is on but additive, as particles and light shafts are drawn. Not a cutout.
    const bool live_additive = camera_mode && !std::strcmp(camera_mode, "live-additive");
    const bool live_untransformed = camera_mode && !std::strcmp(camera_mode, "live-nocb");
    const bool live_skin_poses = camera_mode && !std::strcmp(camera_mode, "live-skin-poses");
    const bool live_skinned = live_skin_poses || (camera_mode && !std::strcmp(camera_mode, "live-skinned"));
    // MOCK_SKIN_ANIMATE (live-skin-poses): both characters change pose every frame, as an animated character does.
    const bool skin_animate = std::getenv("MOCK_SKIN_ANIMATE") != nullptr;
    const bool live_mode = camera_mode && (!std::strcmp(camera_mode, "live") || live_skinned || live_untransformed || live_offset ||
                                           live_box || live_evict || live_passes || live_odd || live_blend || live_additive ||
                                           live_late || live_lights || live_nolights || live_hud);
    ID3D11Buffer* live_vb = nullptr, *live_ib = nullptr, *live_vb2 = nullptr, *live_ib2 = nullptr, *live_cb11 = nullptr;
    ID3D11Buffer* live_sky_vb = nullptr, *live_sky_ib = nullptr;
    ID3D11Texture2D* atlas_tex = nullptr;
    ID3D11RenderTargetView* atlas_rtv = nullptr;
    ID3D11Buffer* live_lights_buf = nullptr, *live_lights_buf_moved = nullptr;
    ID3D11ShaderResourceView* live_lights_srv = nullptr, *live_lights_srv_moved = nullptr;
    ID3D11Texture2D* hud_depth_tex = nullptr;
    ID3D11DepthStencilView* hud_dsv = nullptr;
    const int empty_every = [] { const char* v = std::getenv("MOCK_EMPTY_EVERY"); return v ? std::atoi(v) : 0; }();
    // MOCK_SKY_ONLY_UNTIL=N: before frame N only the sky dome is drawn, like NieR's title screen backdrop.
    const int sky_only_until = [] { const char* v = std::getenv("MOCK_SKY_ONLY_UNTIL"); return v ? std::atoi(v) : 0; }();
    unsigned state_lost = 0;  // frames whose depth view / blend factor did not survive Present
    const bool prepass = std::getenv("MOCK_PREPASS") != nullptr;  // draw every mesh twice: POSITION-only first
    ID3D11InputLayout* prepass_layout = nullptr;
    ID3D11VertexShader* prepass_vs = nullptr;
    ID3D11Buffer* hud_vb = nullptr;
    ID3D11Buffer* hud_ib = nullptr;
    ID3D11Buffer* hud_cb11 = nullptr;
    ID3D11PixelShader* hud_ps = nullptr;
    ID3D11Texture2D* hud_tex = nullptr;
    ID3D11ShaderResourceView* hud_srvs = nullptr;
    ID3D11Texture2D* native_hdr = nullptr;
    ID3D11RenderTargetView* native_hdr_rtv = nullptr;
    ID3D11ShaderResourceView* native_hdr_srv = nullptr;
    ID3D11PixelShader* native_hud_ps = nullptr;
    ID3D11VertexShader* native_hud_vs = nullptr, *native_blit_vs = nullptr;
    ID3D11PixelShader* native_blit_ps = nullptr;
    ID3D11Buffer* native_identity = nullptr;
    ID3D11RasterizerState* native_raster = nullptr;
    static unsigned char sky_template[65 * 20];
    static unsigned char live_vb_template[130 * 20];
    static unsigned live_ib_template[192];
    // MOCK_LATE_IMMUTABLE: from frame 60 (Remix running, capture permitted) an IMMUTABLE vertex/index buffer pair with
    // initial data is created and drawn, the way a streamed-in area's meshes are. z = 7.5 tells it apart.
    const bool late_immutable = std::getenv("MOCK_LATE_IMMUTABLE") != nullptr;
    ID3D11Buffer* late_vb = nullptr, *late_ib = nullptr;
    const bool rewrite_same = std::getenv("MOCK_LIVE_REWRITE_SAME") != nullptr;  // same bytes every frame
    const int spender_from = [] { const char* v = std::getenv("MOCK_LIVE_SPENDER_FROM"); return v ? std::atoi(v) : 0; }();
    ID3D11InputLayout* live_layout = nullptr, *live_layout_slot1 = nullptr;
    unsigned cb11_refs_20 = 0, cb11_refs_79 = 0;
    ID3D11VertexShader* live_vs = nullptr;
    bool skinned_ready = false;
    if (live_mode) {
        if (live_lights || live_nolights) {
            // Field layout taken from the game's own light shader (analysis/SHADER_DECLARATIONS.md):
            // 0..2 position, 3 outer radius, 8..10 colour rgb, 11 inner radius, 48-byte stride.
            float lights[24] = {};
            const auto put = [&](unsigned index, float px, float py, float pz, float outer,
                                 float r, float g, float b, float inner) {
                float* e = &lights[index * 12];
                e[0] = px; e[1] = py; e[2] = pz; e[3] = outer;
                e[8] = r; e[9] = g; e[10] = b; e[11] = inner;
            };
            // live-nolights binds one valid element with an all-zero position instead of an empty array: a zero-element
            // structured SRV is not a valid D3D11 view, and the capture is specified to skip zero-position lights.
            if (!live_nolights) {
                put(0, 100.f, 20.f, 300.f, 25.f, 3.f, 1.5f, 0.5f, 1.f);
                put(1, -50.f, 5.f, 650.f, 40.f, 0.2f, 0.6f, 4.f, 2.f);
            }
            if (live_lights) {
                // From frame 50 the first light has moved: a lamp carried by a character, a flickering torch. The
                // Remix light must follow it (no UpdateLight in the 0.6.6 API: destroy and recreate).
                float moved[24];
                std::memcpy(moved, lights, sizeof moved);
                moved[0] = 110.f;
                D3D11_BUFFER_DESC mbd{}; mbd.Usage = D3D11_USAGE_IMMUTABLE; mbd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
                mbd.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED; mbd.StructureByteStride = 48; mbd.ByteWidth = sizeof moved;
                D3D11_SUBRESOURCE_DATA msd{}; msd.pSysMem = moved;
                // A BUFFEREX view, the way structured buffers are commonly viewed: the reader must accept it as well as
                // BUFFER (the first array above). The old reader took BUFFER only and found no lights in the real game.
                D3D11_SHADER_RESOURCE_VIEW_DESC mv{};
                mv.Format = DXGI_FORMAT_UNKNOWN; mv.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
                mv.BufferEx.FirstElement = 0; mv.BufferEx.NumElements = 2; mv.BufferEx.Flags = 0;
                if (FAILED(device->CreateBuffer(&mbd, &msd, &live_lights_buf_moved)) ||
                    FAILED(device->CreateShaderResourceView(live_lights_buf_moved, &mv, &live_lights_srv_moved)))
                    { std::fprintf(out, "FAIL moved light srv\n"); return 3; }
            }
            D3D11_BUFFER_DESC lbd{}; lbd.Usage = D3D11_USAGE_IMMUTABLE; lbd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
            lbd.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED; lbd.StructureByteStride = 48;
            const UINT elements = live_nolights ? 1u : 2u;
            lbd.ByteWidth = live_nolights ? 48u : sizeof lights;
            D3D11_SUBRESOURCE_DATA lsd{}; lsd.pSysMem = lights;
            if (FAILED(device->CreateBuffer(&lbd, &lsd, &live_lights_buf))) { std::fprintf(out, "FAIL light buffer\n"); return 3; }
            D3D11_SHADER_RESOURCE_VIEW_DESC lsdv{};
            lsdv.Format = DXGI_FORMAT_UNKNOWN; lsdv.ViewDimension = D3D11_SRV_DIMENSION_BUFFER;
            lsdv.Buffer.FirstElement = 0; lsdv.Buffer.NumElements = elements;
            if (FAILED(device->CreateShaderResourceView(live_lights_buf, &lsdv, &live_lights_srv))) { std::fprintf(out, "FAIL light srv\n"); return 3; }
        }
        if (live_hud) {
            // Sample a green 4x4 texture rather than returning a constant: the replay draws the HUD with the game's own
            // texture view, so the gate can only pass if that view reaches the composited frame.
            const char hud_ps_src[] =
                "Texture2D t : register(t0); SamplerState s : register(s0);\n"
                "float4 main(float2 uv : TEXCOORD0) : SV_TARGET { return t.Sample(s, uv); }\n";
            const unsigned char green[4 * 4 * 4] = {0};
            {
                std::memset(const_cast<unsigned char*>(green), 0, sizeof green);
                for (unsigned i = 0; i < 16; ++i) {
                    const_cast<unsigned char*>(green)[i * 4 + 0] = 20;
                    const_cast<unsigned char*>(green)[i * 4 + 1] = 230;
                    const_cast<unsigned char*>(green)[i * 4 + 2] = 30;
                    const_cast<unsigned char*>(green)[i * 4 + 3] = 255;
                }
            }
            D3D11_TEXTURE2D_DESC htd{}; htd.Width = 4; htd.Height = 4; htd.MipLevels = 1; htd.ArraySize = 1;
            htd.Format = DXGI_FORMAT_R8G8B8A8_UNORM; htd.SampleDesc.Count = 1; htd.Usage = D3D11_USAGE_IMMUTABLE;
            htd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
            D3D11_SUBRESOURCE_DATA htsd{}; htsd.pSysMem = green; htsd.SysMemPitch = 16;
            if (FAILED(device->CreateTexture2D(&htd, &htsd, &hud_tex)) || !hud_tex ||
                FAILED(device->CreateShaderResourceView(hud_tex, nullptr, &hud_srvs))) {
                std::fprintf(out, "FAIL hud texture\n"); return 3;
            }
            ID3DBlob* hud_blob = nullptr;
            if (!compile || FAILED(compile(hud_ps_src, sizeof hud_ps_src - 1, "ps", nullptr, nullptr, "main", "ps_4_0", 0, 0, &hud_blob, nullptr)) ||
                FAILED(device->CreatePixelShader(hud_blob->GetBufferPointer(), hud_blob->GetBufferSize(), nullptr, &hud_ps))) {
                std::fprintf(out, "FAIL hud ps\n"); return 3;
            }
            hud_blob->Release();
            // Clip-space quad left of centre (x -1.3..-0.1): CB11 moves it to -0.7..0.5. Then u,v for the input layout.
            const float quad[4][5] = {{-1.3f, -0.6f, 0.f, 0.f, 1.f}, {-0.1f, -0.6f, 0.f, 1.f, 1.f},
                                      {-1.3f, 0.6f, 0.f, 0.f, 0.f}, {-0.1f, 0.6f, 0.f, 1.f, 0.f}};
            D3D11_BUFFER_DESC qbd{}; qbd.ByteWidth = sizeof quad; qbd.Usage = D3D11_USAGE_IMMUTABLE;
            qbd.BindFlags = D3D11_BIND_VERTEX_BUFFER;
            D3D11_SUBRESOURCE_DATA qsd{}; qsd.pSysMem = quad;
            if (FAILED(device->CreateBuffer(&qbd, &qsd, &hud_vb))) { std::fprintf(out, "FAIL hud vb\n"); return 3; }
            // Indexed, like the game's sprite pass: the capture path only observes indexed draws.
            const unsigned short quad_ib[6] = {0, 1, 2, 2, 1, 3};
            D3D11_BUFFER_DESC qibd{}; qibd.ByteWidth = sizeof quad_ib; qibd.Usage = D3D11_USAGE_IMMUTABLE;
            qibd.BindFlags = D3D11_BIND_INDEX_BUFFER;
            D3D11_SUBRESOURCE_DATA qibsd{}; qibsd.pSysMem = quad_ib;
            if (FAILED(device->CreateBuffer(&qibd, &qibsd, &hud_ib))) { std::fprintf(out, "FAIL hud ib\n"); return 3; }
            // The game's HUD carries its own matrix in CB11, in the game's layout: three float4 registers, translation
            // in element 3 of each (out_r = dot(register_r, float4(p, 1)), the same layout as the world matrices).
            // The quad above sits left of centre; this moves it right by 0.6 so it covers the centre. Applied in the
            // wrong order, the translation lands in w instead and the quad never reaches the centre.
            float shift[16] = {1, 0, 0, 0.6f, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
            D3D11_BUFFER_DESC hcd{}; hcd.ByteWidth = sizeof shift; hcd.Usage = D3D11_USAGE_IMMUTABLE;
            hcd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
            D3D11_SUBRESOURCE_DATA hcsd{}; hcsd.pSysMem = shift;
            if (FAILED(device->CreateBuffer(&hcd, &hcsd, &hud_cb11))) { std::fprintf(out, "FAIL hud cb11\n"); return 3; }
            // A depth view bound across Present, as a game leaves it: the replay must hand it back.
            D3D11_TEXTURE2D_DESC dd{}; dd.Width = 1920; dd.Height = 1080; dd.MipLevels = 1; dd.ArraySize = 1;
            dd.Format = DXGI_FORMAT_D24_UNORM_S8_UINT; dd.SampleDesc.Count = 1; dd.Usage = D3D11_USAGE_DEFAULT;
            dd.BindFlags = D3D11_BIND_DEPTH_STENCIL;
            if (FAILED(device->CreateTexture2D(&dd, nullptr, &hud_depth_tex)) ||
                FAILED(device->CreateDepthStencilView(hud_depth_tex, nullptr, &hud_dsv))) { std::fprintf(out, "FAIL hud dsv\n"); return 3; }
        }
        if (live_native_hud) {
            const char* path = std::getenv("MOCK_NATIVE_HUD_PS");
            FILE* shader = path ? std::fopen(path, "rb") : nullptr;
            if (!shader) { std::fprintf(out, "FAIL native HUD fixture missing\n"); return 3; }
            static unsigned char code[65536]; const auto bytes = std::fread(code, 1, sizeof code, shader); std::fclose(shader);
            if (!bytes || FAILED(device->CreatePixelShader(code, bytes, nullptr, &native_hud_ps))) {
                std::fprintf(out, "FAIL native HUD PS\n"); return 3;
            }
            // flags.x < 0: the shipped PS inverts the sprite colour when COLOR3.x >= 0 (ps_1888250464.asm).
            const char vs_src[] =
                "cbuffer M:register(b0){row_major float4x4 m;}\n"
                "struct O{float4 p:SV_POSITION;float2 uv:TEXCOORD0;float2 maskuv:TEXCOORD1;float4 mask:TEXCOORD2;"
                "float4 c:COLOR0;float4 a:COLOR1;float4 b:COLOR2;float4 flags:COLOR3;};\n"
                "O main(float3 p:POSITION,float2 uv:TEXCOORD0){O o;o.p=mul(m,float4(p,1));o.uv=uv;o.maskuv=uv;"
                "o.mask=float4(0,0,0,1);o.c=1;o.a=1;o.b=1;o.flags=float4(-1,0,0,0);return o;}";
            const char blit_src[] =
                "struct O{float4 p:SV_POSITION;float2 uv:TEXCOORD0;};\n"
                "O main(uint i:SV_VertexID){O o;o.uv=float2(i&1,i>>1);o.p=float4(o.uv.x*2-1,1-o.uv.y*2,0,1);return o;}";
            ID3DBlob* v = nullptr;
            if (!compile || FAILED(compile(vs_src, sizeof vs_src-1, "native", nullptr, nullptr, "main", "vs_4_0", 0, 0, &v, nullptr)) ||
                FAILED(device->CreateVertexShader(v->GetBufferPointer(), v->GetBufferSize(), nullptr, &native_hud_vs))) {
                std::fprintf(out, "FAIL native HUD VS\n"); return 3;
            }
            v->Release(); v = nullptr;
            if (FAILED(compile(blit_src, sizeof blit_src-1, "blit", nullptr, nullptr, "main", "vs_4_0", 0, 0, &v, nullptr)) ||
                FAILED(device->CreateVertexShader(v->GetBufferPointer(), v->GetBufferSize(), nullptr, &native_blit_vs))) {
                std::fprintf(out, "FAIL native HUD blit VS\n"); return 3;
            }
            v->Release(); v = nullptr;
            // Final compositor: a pixel copy whose input signature matches the blit VS (SV_POSITION first).
            const char blit_ps_src[] = "Texture2D t:register(t0);float4 main(float4 p:SV_POSITION):SV_TARGET{return t.Load(int3(p.xy,0));}";
            if (FAILED(compile(blit_ps_src, sizeof blit_ps_src-1, "blitps", nullptr, nullptr, "main", "ps_4_0", 0, 0, &v, nullptr)) ||
                FAILED(device->CreatePixelShader(v->GetBufferPointer(), v->GetBufferSize(), nullptr, &native_blit_ps))) {
                std::fprintf(out, "FAIL native HUD blit PS\n"); return 3;
            }
            v->Release();
            D3D11_TEXTURE2D_DESC td{}; td.Width=1920; td.Height=1080; td.MipLevels=1; td.ArraySize=1;
            td.Format=DXGI_FORMAT_R11G11B10_FLOAT; td.SampleDesc.Count=1;
            td.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
            if (FAILED(device->CreateTexture2D(&td,nullptr,&native_hdr)) ||
                FAILED(device->CreateRenderTargetView(native_hdr,nullptr,&native_hdr_rtv)) ||
                FAILED(device->CreateShaderResourceView(native_hdr,nullptr,&native_hdr_srv))) {
                std::fprintf(out,"FAIL native HDR target\n"); return 3;
            }
            const float identity[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
            D3D11_BUFFER_DESC bd{}; bd.ByteWidth=sizeof identity; bd.Usage=D3D11_USAGE_IMMUTABLE; bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
            D3D11_SUBRESOURCE_DATA init{}; init.pSysMem=identity;
            D3D11_RASTERIZER_DESC rd{}; rd.FillMode=D3D11_FILL_SOLID; rd.CullMode=D3D11_CULL_NONE;
            if (FAILED(device->CreateBuffer(&bd,&init,&native_identity)) || FAILED(device->CreateRasterizerState(&rd,&native_raster))) {
                std::fprintf(out,"FAIL native HUD state\n"); return 3;
            }
        }
        const char lvs[] =
            "struct VSOut { float4 pos : SV_POSITION; };\n"
            "VSOut main(float3 pos : POSITION, float2 uv : TEXCOORD) { VSOut o; o.pos = float4(pos, 1); return o; }\n";
        ID3DBlob* lb = nullptr;
        if (!compile || FAILED(compile(lvs, sizeof lvs - 1, "lvs", nullptr, nullptr, "main", "vs_4_0", 0, 0, &lb, nullptr)))
            { std::fprintf(out, "FAIL live vs\n"); return 3; }
        D3D11_INPUT_ELEMENT_DESC ld[2] = {
            {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0,  D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT,    0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0},
        };
        D3D11_INPUT_ELEMENT_DESC ld1[2] = {
            {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 1, 0,  D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT,    1, 12, D3D11_INPUT_PER_VERTEX_DATA, 0},
        };
        if (FAILED(device->CreateInputLayout(ld1, 2, lb->GetBufferPointer(), lb->GetBufferSize(), &live_layout_slot1)))
            { lb->Release(); std::fprintf(out, "FAIL live layout slot1\n"); return 3; }
        if (FAILED(device->CreateInputLayout(ld, 2, lb->GetBufferPointer(), lb->GetBufferSize(), &live_layout)) ||
            FAILED(device->CreateVertexShader(lb->GetBufferPointer(), lb->GetBufferSize(), nullptr, &live_vs)))
            { lb->Release(); std::fprintf(out, "FAIL live pipeline\n"); return 3; }
        lb->Release();
        if (prepass) {
            // NieR's depth pre-pass: the same buffers, a POSITION-only layout and its own vertex shader, drawn into the
            // scene target before the full pass (every capture: 38-42% of scene draws, each with a full-layout twin).
            const char pvs[] = "float4 main(float3 pos : POSITION) : SV_POSITION { return float4(pos, 1); }\n";
            ID3DBlob* pb = nullptr;
            const D3D11_INPUT_ELEMENT_DESC pd[1] = {{"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0}};
            if (!compile || FAILED(compile(pvs, sizeof pvs - 1, "pvs", nullptr, nullptr, "main", "vs_4_0", 0, 0, &pb, nullptr)) ||
                FAILED(device->CreateInputLayout(pd, 1, pb->GetBufferPointer(), pb->GetBufferSize(), &prepass_layout)) ||
                FAILED(device->CreateVertexShader(pb->GetBufferPointer(), pb->GetBufferSize(), nullptr, &prepass_vs)))
                { if (pb) pb->Release(); std::fprintf(out, "FAIL prepass pipeline\n"); return 3; }
            pb->Release();
        }
        if (live_skinned) {
            unsigned char sv[65 * 28] = {};
            for (unsigned i = 0; i < 65; ++i) {
                float* p = reinterpret_cast<float*>(sv + i * 28);
                p[0] = (i == 0) ? 0.f : 1.f + (i % 7) * 0.1f;
                p[1] = (i == 0) ? 0.f : (i % 5) * 0.2f;
                p[2] = 0.5f;
                sv[i * 28 + 20] = 0; sv[i * 28 + 21] = 0; sv[i * 28 + 24] = 255;  // all weight on bone 0
            }
            unsigned sind[192];
            unsigned si = 0;
            for (unsigned i = 1; i <= 63; ++i) { sind[si++] = 0; sind[si++] = i; sind[si++] = i + 1; }
            sind[si++] = 0; sind[si++] = 64; sind[si++] = 1;
            D3D11_BUFFER_DESC bd{}; bd.ByteWidth = sizeof sv; bd.Usage = D3D11_USAGE_DYNAMIC;
            bd.BindFlags = D3D11_BIND_VERTEX_BUFFER; bd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
            if (FAILED(device->CreateBuffer(&bd, nullptr, &live_vb))) { std::fprintf(out, "FAIL skinned vb\n"); return 3; }
            D3D11_MAPPED_SUBRESOURCE m{};
            if (FAILED(context->Map(live_vb, 0, D3D11_MAP_WRITE_DISCARD, 0, &m))) { std::fprintf(out, "FAIL skinned map\n"); return 3; }
            std::memcpy(m.pData, sv, sizeof sv);
            context->Unmap(live_vb, 0);
            D3D11_BUFFER_DESC ibd{}; ibd.ByteWidth = sizeof sind; ibd.Usage = D3D11_USAGE_IMMUTABLE;
            ibd.BindFlags = D3D11_BIND_INDEX_BUFFER;
            D3D11_SUBRESOURCE_DATA ibdata = {sind, 0, 0};
            if (FAILED(device->CreateBuffer(&ibd, &ibdata, &live_ib))) { std::fprintf(out, "FAIL skinned ib\n"); return 3; }
            const char svs[] =
                "struct VSOut { float4 pos : SV_POSITION; };\n"
                "VSOut main(float3 pos : POSITION, float2 uv : TEXCOORD, float4 bi : BLENDINDICES, float4 bw : BLENDWEIGHT)"
                " { VSOut o; o.pos = float4(pos, 1); return o; }\n";
            ID3DBlob* sb = nullptr;
            if (!compile || FAILED(compile(svs, sizeof svs - 1, "svs", nullptr, nullptr, "main", "vs_4_0", 0, 0, &sb, nullptr)))
                { std::fprintf(out, "FAIL skinned vs\n"); return 3; }
            D3D11_INPUT_ELEMENT_DESC sd[4] = {
                {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0,  D3D11_INPUT_PER_VERTEX_DATA, 0},
                {"TEXCOORD", 0, DXGI_FORMAT_R16G16_FLOAT,    0, 16, D3D11_INPUT_PER_VERTEX_DATA, 0},
                {"BLENDINDICES", 0, DXGI_FORMAT_R8G8B8A8_UINT, 0, 20, D3D11_INPUT_PER_VERTEX_DATA, 0},
                {"BLENDWEIGHT", 0, DXGI_FORMAT_R8G8B8A8_UNORM, 0, 24, D3D11_INPUT_PER_VERTEX_DATA, 0},
            };
            if (FAILED(device->CreateInputLayout(sd, 4, sb->GetBufferPointer(), sb->GetBufferSize(), &live_layout)) ||
                FAILED(device->CreateVertexShader(sb->GetBufferPointer(), sb->GetBufferSize(), nullptr, &live_vs)))
                { sb->Release(); std::fprintf(out, "FAIL skinned pipeline\n"); return 3; }
            sb->Release();
            D3D11_BUFFER_DESC cbd{}; cbd.ByteWidth = 96; cbd.Usage = D3D11_USAGE_DYNAMIC;
            cbd.BindFlags = D3D11_BIND_CONSTANT_BUFFER; cbd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
            if (FAILED(device->CreateBuffer(&cbd, nullptr, &live_cb11))) { std::fprintf(out, "FAIL skinned cb11\n"); return 3; }
            skinned_ready = true;
        }
        if (!live_skinned) {
        const unsigned vertex_count = live_offset ? 130u : 65u;
        unsigned char lverts[130 * 20] = {};
        for (unsigned i = 0; i < vertex_count; ++i) {
            float* p = reinterpret_cast<float*>(lverts + i * 20);
            const unsigned k = i % 65;
            p[0] = (k == 0) ? 0.f : 1.f + (k % 7) * 0.1f;
            p[1] = (k == 0) ? 0.f : (k % 5) * 0.2f;
            p[2] = (i < 65) ? 0.5f : 2.5f;  // the second half is distinguishable by z
            p[3] = 0.25f; p[4] = 0.75f;
        }
        unsigned lindices[384];
        unsigned li = 0;
        for (unsigned base = 0; base < 130; base += 65) {
            for (unsigned i = 1; i <= 63; ++i) { lindices[li++] = base + 0; lindices[li++] = base + i; lindices[li++] = base + i + 1; }
            lindices[li++] = base + 0; lindices[li++] = base + 64; lindices[li++] = base + 1;
        }
        std::memcpy(live_vb_template, lverts, sizeof lverts);
        std::memcpy(live_ib_template, lindices, sizeof live_ib_template);
        D3D11_BUFFER_DESC lbd{}; lbd.ByteWidth = live_offset ? vertex_count * 20 : sizeof lverts; lbd.Usage = D3D11_USAGE_DYNAMIC;
        lbd.BindFlags = D3D11_BIND_VERTEX_BUFFER; lbd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        if (FAILED(device->CreateBuffer(&lbd, nullptr, &live_vb))) { std::fprintf(out, "FAIL live vb\n"); return 3; }
        D3D11_MAPPED_SUBRESOURCE lm{};
        if (FAILED(context->Map(live_vb, 0, D3D11_MAP_WRITE_DISCARD, 0, &lm))) { std::fprintf(out, "FAIL live vb map\n"); return 3; }
        std::memcpy(lm.pData, lverts, lbd.ByteWidth);
        context->Unmap(live_vb, 0);
        D3D11_BUFFER_DESC lib{}; lib.ByteWidth = live_offset ? sizeof lindices : 192 * 4; lib.Usage = D3D11_USAGE_IMMUTABLE;
        lib.BindFlags = D3D11_BIND_INDEX_BUFFER;
        D3D11_SUBRESOURCE_DATA lid = {lindices, 0, 0};
        if (FAILED(device->CreateBuffer(&lib, &lid, &live_ib))) { std::fprintf(out, "FAIL live ib\n"); return 3; }
        D3D11_BUFFER_DESC lbd2{}; lbd2.ByteWidth = lbd.ByteWidth; lbd2.Usage = D3D11_USAGE_DEFAULT;
        lbd2.BindFlags = D3D11_BIND_VERTEX_BUFFER;
        D3D11_SUBRESOURCE_DATA lid2 = {lverts, 0, 0};
        if (FAILED(device->CreateBuffer(&lbd2, &lid2, &live_vb2))) { std::fprintf(out, "FAIL live vb2\n"); return 3; }
        D3D11_BUFFER_DESC lib2 = lib;
        if (FAILED(device->CreateBuffer(&lib2, &lid, &live_ib2))) { std::fprintf(out, "FAIL live ib2\n"); return 3; }
        D3D11_BUFFER_DESC cb11d{}; cb11d.ByteWidth = 64; cb11d.Usage = D3D11_USAGE_DYNAMIC;
        cb11d.BindFlags = D3D11_BIND_CONSTANT_BUFFER; cb11d.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        if (FAILED(device->CreateBuffer(&cb11d, nullptr, &live_cb11))) { std::fprintf(out, "FAIL live cb11\n"); return 3; }
        {
            // Same layout, but spanning 100000 units: a sky dome. The captured-scene path refuses these, because
            // a dome enclosing the camera renders black.
            unsigned char sky[65 * 20] = {};
            for (unsigned i = 0; i < 65; ++i) {
                float* v = reinterpret_cast<float*>(sky + i * 20);
                v[0] = -50000.f + i * 1500.f; v[1] = 0.f; v[2] = 50000.f;
                v[3] = 0.f; v[4] = 0.f;
            }
            std::memcpy(sky_template, sky, sizeof sky);
            D3D11_BUFFER_DESC sbd{}; sbd.ByteWidth = sizeof sky;
            sbd.Usage = spender_from ? D3D11_USAGE_DYNAMIC : D3D11_USAGE_DEFAULT;
            sbd.CPUAccessFlags = spender_from ? D3D11_CPU_ACCESS_WRITE : 0;
            sbd.BindFlags = D3D11_BIND_VERTEX_BUFFER;
            D3D11_SUBRESOURCE_DATA sd = {sky, 0, 0};
            if (FAILED(device->CreateBuffer(&sbd, &sd, &live_sky_vb)))  // initial data even when DYNAMIC
                { std::fprintf(out, "FAIL sky vb\n"); return 3; }
            D3D11_BUFFER_DESC sib{}; sib.ByteWidth = 192 * 4; sib.Usage = D3D11_USAGE_IMMUTABLE;
            sib.BindFlags = D3D11_BIND_INDEX_BUFFER;
            static unsigned sky_indices[192];
            unsigned si = 0;
            for (unsigned i = 1; i <= 63; ++i) { sky_indices[si++] = 0; sky_indices[si++] = i; sky_indices[si++] = i + 1; }
            sky_indices[si++] = 0; sky_indices[si++] = 64; sky_indices[si++] = 1;
            D3D11_SUBRESOURCE_DATA sid = {sky_indices, 0, 0};
            if (FAILED(device->CreateBuffer(&sib, &sid, &live_sky_ib))) { std::fprintf(out, "FAIL sky ib\n"); return 3; }
        }
        }
    }
    // One vertex (20 bytes) placed so its last byte is the last byte before a PAGE_NOACCESS page: reading even one
    // byte past it faults. A hook that copies the whole buffer instead of the box crashes the game here.
    unsigned char* guarded_vertex = nullptr;
    ID3D11Buffer* unbound_dynamic = nullptr;
    unsigned unbound_refs = 0;
    if (live_box) {
        auto* pages = static_cast<unsigned char*>(VirtualAlloc(nullptr, 8192, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
        DWORD old = 0;
        if (!pages || !VirtualProtect(pages + 4096, 4096, PAGE_NOACCESS, &old)) { std::fprintf(out, "FAIL guard page\n"); return 3; }
        guarded_vertex = pages + 4096 - 20;
        float* v = reinterpret_cast<float*>(guarded_vertex);
        v[0] = 7.f; v[1] = 8.f; v[2] = 9.f; v[3] = 0.f; v[4] = 0.f;
        D3D11_BUFFER_DESC ud{}; ud.ByteWidth = 4096; ud.Usage = D3D11_USAGE_DYNAMIC;
        ud.BindFlags = D3D11_BIND_VERTEX_BUFFER; ud.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        if (FAILED(device->CreateBuffer(&ud, nullptr, &unbound_dynamic))) { std::fprintf(out, "FAIL unbound dynamic\n"); return 3; }
    }
    unsigned presented = 0, cs_lost = 0, reads_at_failure = 0, reads_after_failed_present = 0, reads_while_bypassed = 0;
    bool failure_observed = false, previous_present_failed = false;
    double live_frame_ms = 0.0;
    for (int frame = 1; frame <= 80; ++frame) {
        if (overlay_dummy && frame == overlay_rehook) {
            if (std::getenv("MOCK_FOREIGN_SWAPCHAIN")) {
                // An internal driver/Remix DXGI swapchain uses a different device. Our global factory hooks see it,
                // but it must never receive our private Present or replace the game's target.
                HWND foreign_window = CreateWindowW(wc.lpszClassName, L"foreign", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64,
                                                    nullptr, nullptr, wc.hInstance, nullptr);
                auto system_create = reinterpret_cast<decltype(&D3D11CreateDeviceAndSwapChain)>(reinterpret_cast<void*>(
                    GetProcAddress(GetModuleHandleW(L"C:\\windows\\system32\\d3d11.dll"), "D3D11CreateDeviceAndSwapChain")));
                DXGI_SWAP_CHAIN_DESC fd = sd; fd.OutputWindow = foreign_window; fd.BufferDesc.Width = fd.BufferDesc.Height = 64;
                IDXGISwapChain* foreign = nullptr; ID3D11Device* foreign_device = nullptr;
                if (FAILED(system_create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION,
                                         &fd, &foreign, &foreign_device, nullptr, nullptr)) || !foreign) {
                    std::fprintf(out, "FAIL foreign swapchain\n"); return 3;
                }
                ++foreign_created;
                foreign_hooked = (*reinterpret_cast<void***>(foreign))[8] == (*reinterpret_cast<void***>(swapchain))[8];
                foreign->Release(); foreign_device->Release(); DestroyWindow(foreign_window);
            } else if (std::getenv("MOCK_SECOND_PRESENT_CHAIN")) {
                // A second swapchain of the same class, after another mod changed its shared Present slot. It must not
                // overwrite the saved downstream chain used by the first object's private vtable (review P1).
                void** shared = *reinterpret_cast<void***>(overlay_dummy);
                second_next = reinterpret_cast<OvPresentFn>(shared[8]);
                DWORD old = 0; VirtualProtect(&shared[8], sizeof(void*), PAGE_READWRITE, &old);
                shared[8] = reinterpret_cast<void*>(&second_present);
                VirtualProtect(&shared[8], sizeof(void*), old, &old);
                HWND other_window = CreateWindowW(wc.lpszClassName, L"second-chain", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64,
                                                  nullptr, nullptr, wc.hInstance, nullptr);
                DXGI_SWAP_CHAIN_DESC other = sd; other.OutputWindow = other_window;
                other.BufferDesc.Width = other.BufferDesc.Height = 64;
                IDXGISwapChain* second = nullptr;
                if (FAILED(factory->CreateSwapChain(device, &other, &second)) || !second) {
                    std::fprintf(out, "FAIL second swapchain\n"); return 3;
                }
                ++second_created;
                second->Release(); DestroyWindow(other_window);
                VirtualProtect(&shared[8], sizeof(void*), PAGE_READWRITE, &old);
                shared[8] = reinterpret_cast<void*>(second_next);
                VirtualProtect(&shared[8], sizeof(void*), old, &old);
            } else ov_discover(overlay_dummy);
        }
        mock_frame_index = frame;
        MSG msg; while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        // Frame capture: F9 held 1-4 records exactly one frame; the mesh is drawn twice every frame 1-6, so
        // a wrong frame boundary shows up as a draw count other than 2. Second F9 (38-41) runs with the panel open:
        // its ImGui draws must not be recorded either.
        frame_camera_reads = 0;
        LARGE_INTEGER t0{}, f{};
        if (live_mode) { QueryPerformanceCounter(&t0); QueryPerformanceFrequency(&f); }
        if (camera_mode && !std::strcmp(camera_mode, "fail-before-draw") && frame == 20) {
            HMODULE fake = GetModuleHandleW(L"fake_remix.dll");
            auto fail_copy = fake ? reinterpret_cast<void (*)()>(reinterpret_cast<void*>(GetProcAddress(fake, "fake_fail_copy_next"))) : nullptr;
            if (!fail_copy) { std::fprintf(out, "FAIL failure trigger\n"); return 3; }
            fail_copy();
            for (unsigned tries = 0; tries < 100 && !failure_observed; ++tries) {
                if (FILE* log = std::fopen("NIER_SCALE.log", "r")) {
                    char line[2048];
                    while (std::fgets(line, sizeof line, log)) if (std::strstr(line, "remix: disabled (")) failure_observed = true;
                    std::fclose(log);
                }
                if (!failure_observed) Sleep(10);
            }
            if (!failure_observed) { std::fprintf(out, "FAIL no host failure acknowledgment\n"); return 3; }
            reads_at_failure = camera_reads;
        }
        const unsigned before_draw = camera_reads;
        if (camera_mode) {
            const bool second = frame > 40;
            camera_cb[3] = second ? -40.f : -10.f;
            camera_cb[7] = second ? -5.f : -2.f;
            camera_cb[11] = second ? -60.f : -30.f;
            if (!std::strcmp(camera_mode, "invalid") || (!std::strcmp(camera_mode, "invalid-late") && second))
                camera_cb[0] = std::numeric_limits<float>::quiet_NaN();
            context->UpdateSubresource(camera_buffer, 0, nullptr, camera_cb, 0, 0);
            if (!live_mode) for (unsigned draw = 0; draw < 8; ++draw) draw_mesh();
            if (live_mode && live_cb11 && (frame == 20 || frame == 79)) {
                const unsigned refs = live_cb11->AddRef() - 1;
                live_cb11->Release();
                (frame == 20 ? cb11_refs_20 : cb11_refs_79) = refs;
            }
            if (live_box && (frame == 10 || frame == 60)) {
                // Frame 10: before mesh B's buffer was ever read. Frame 60: after, so a shadow exists and must take
                // the partial write, which moves vertex 0 of mesh B to (7,8,9).
                const D3D11_BOX box{0, 0, 0, 20, 1, 1};
                context->UpdateSubresource(live_vb2, 0, &box, guarded_vertex, 0, 0);
            }
            if (live_box && frame == 12) {
                D3D11_MAPPED_SUBRESOURCE um{};
                if (SUCCEEDED(context->Map(unbound_dynamic, 0, D3D11_MAP_WRITE_DISCARD, 0, &um))) {
                    std::memset(um.pData, 0x5a, 4096);
                    context->Unmap(unbound_dynamic, 0);
                }
                unbound_refs = unbound_dynamic->AddRef() - 1;  // 1 = only the game holds it
                unbound_dynamic->Release();
            }
            if (live_skinned && skinned_ready) {
                D3D11_MAPPED_SUBRESOURCE lm{};
                if (SUCCEEDED(context->Map(live_cb11, 0, D3D11_MAP_WRITE_DISCARD, 0, &lm))) {
                    float* w = static_cast<float*>(lm.pData);
                    std::memset(w, 0, 96);
                    w[0] = w[5] = w[10] = 1.f;              // bone 0: identity
                    if (live_skin_poses) w[3] = skin_animate ? frame * 0.25f : (frame < 40 ? 0.f : 10.f);
                    w[12] = w[17] = w[22] = 1.f; w[15] = 5.f; // bone 1: translated on x
                    context->Unmap(live_cb11, 0);
                }
                const UINT sstride = 28, soff = 0;
                context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
                context->OMSetRenderTargets(1, &mesh_rtv, nullptr);
                D3D11_VIEWPORT svp{0, 0, 1920.f, 1080.f, 0, 1};
                context->RSSetViewports(1, &svp);
                context->IASetInputLayout(live_layout);
                context->VSSetShader(live_vs, nullptr, 0);
                context->PSSetShader(mesh_ps, nullptr, 0);
                context->VSSetConstantBuffers(0, 1, &camera_buffer);
                context->VSSetConstantBuffers(11, 1, &live_cb11);
                context->PSSetShaderResources(0, 1, &mesh_srvs[0]);
                context->IASetVertexBuffers(0, 1, &live_vb, &sstride, &soff);
                context->IASetIndexBuffer(live_ib, DXGI_FORMAT_R32_UINT, 0);
                context->DrawIndexed(192, 0, 0);
                if (live_skin_poses) {
                    // Same VB/IB/layout, different character palette in the same frame.
                    if (SUCCEEDED(context->Map(live_cb11, 0, D3D11_MAP_WRITE_DISCARD, 0, &lm))) {
                        float* w = static_cast<float*>(lm.pData);
                        std::memset(w, 0, 96);
                        w[0] = w[5] = w[10] = w[12] = w[17] = w[22] = 1.f;
                        w[3] = skin_animate ? 20.f + frame * 0.25f : (frame < 40 ? 20.f : 30.f); w[15] = 5.f;
                        context->Unmap(live_cb11, 0);
                    }
                    context->DrawIndexed(192, 0, 0);
                }
            } else if (live_mode) {
                D3D11_MAPPED_SUBRESOURCE lm{};
                if (SUCCEEDED(context->Map(live_cb11, 0, D3D11_MAP_WRITE_DISCARD, 0, &lm))) {
                    float* w = static_cast<float*>(lm.pData);
                    std::memset(w, 0, 64);
                    w[0] = w[5] = w[10] = 1.f;
                    w[3] = static_cast<float>(frame); w[7] = 2.f; w[11] = 3.f;
                    context->Unmap(live_cb11, 0);
                }
                if (frame == 50 && SUCCEEDED(context->Map(live_vb, 0, D3D11_MAP_WRITE_DISCARD, 0, &lm))) {
                    // WRITE_DISCARD invalidates the whole buffer, so rewrite all of it, keeping each vertex's
                    // position but changing the UVs: a real engine never writes half a discarded buffer.
                    unsigned char* p = static_cast<unsigned char*>(lm.pData);
                    const unsigned rewrite_count = live_offset ? 130u : 65u;
                    for (unsigned i = 0; i < rewrite_count; ++i) {
                        float* v = reinterpret_cast<float*>(p + i * 20);
                        v[0] = (i % 65 == 0) ? 0.f : 1.f + ((i % 65) % 7) * 0.1f;
                        v[1] = (i % 65 == 0) ? 0.f : ((i % 65) % 5) * 0.2f;
                        v[2] = (i < 65) ? 0.5f : 2.5f;
                        v[3] = 0.5f; v[4] = 0.5f;
                    }
                    context->Unmap(live_vb, 0);
                }
                const UINT mstride = 20, moff = 0;
                context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);  // real games always set it
                if (live_passes && !atlas_rtv) {
                    D3D11_TEXTURE2D_DESC atd{}; atd.Width = 256; atd.Height = 256; atd.MipLevels = 1; atd.ArraySize = 1;
                    atd.Format = DXGI_FORMAT_R8G8B8A8_UNORM; atd.SampleDesc.Count = 1; atd.Usage = D3D11_USAGE_DEFAULT;
                    atd.BindFlags = D3D11_BIND_RENDER_TARGET;
                    if (FAILED(device->CreateTexture2D(&atd, nullptr, &atlas_tex)) ||
                        FAILED(device->CreateRenderTargetView(atlas_tex, nullptr, &atlas_rtv))) { std::fprintf(out, "FAIL atlas rtv\n"); return 3; }
                }
                context->OMSetRenderTargets(1, &mesh_rtv, nullptr);
                D3D11_VIEWPORT lvp{0, 0, 1920.f, 1080.f, 0, 1};
                context->RSSetViewports(1, &lvp);
                context->IASetInputLayout(live_layout);
                context->VSSetShader(live_vs, nullptr, 0);
                context->PSSetShader(mesh_ps, nullptr, 0);
                context->VSSetConstantBuffers(0, 1, &camera_buffer);
                context->VSSetConstantBuffers(11, 1, &live_cb11);
                context->PSSetShaderResources(0, 1, &mesh_srvs[0]);
                // Blend state is explicit per mode: the live-capture path reads it to decide cutout vs opaque, so the
                // "plain" runs must not inherit the probe state left bound by the camera-capture draws.
                context->OMSetBlendState(live_blend ? probe_blend : (live_additive ? additive_blend : nullptr), nullptr, 0xFFFFFFFF);
                // Slot 20 is bound only after the first (sky) draw: the light array must still be read from a later
                // draw of the same frame, not lost because the first draw had none.
                ID3D11ShaderResourceView* lights_now = frame >= 50 && live_lights_srv_moved ? live_lights_srv_moved : live_lights_srv;
                { ID3D11ShaderResourceView* none = nullptr; context->PSSetShaderResources(20, 1, &none); }
                const bool empty_frame = empty_every > 0 && frame % empty_every == 0;  // only the other passes draw
                if (live_passes) {
                    // Two draws of the scene mesh into a 256x256 target: a shadow-pass stand-in. They carry the same
                    // geometry, CB11 and texture as the main view, so only the render target tells them apart.
                    context->OMSetRenderTargets(1, &atlas_rtv, nullptr);
                    D3D11_VIEWPORT avp{0, 0, 128.f, 128.f, 0, 1};
                    context->RSSetViewports(1, &avp);
                    context->IASetVertexBuffers(0, 1, &live_vb, &mstride, &moff);
                    context->IASetIndexBuffer(live_ib, DXGI_FORMAT_R32_UINT, 0);
                    context->DrawIndexed(192, 0, 0);
                    context->DrawIndexed(192, 0, 0);
                    context->OMSetRenderTargets(1, &mesh_rtv, nullptr);
                    context->RSSetViewports(1, &lvp);
                }
                static const unsigned repeats = [] {
                    const char* n = std::getenv("MOCK_LIVE_DRAWS");
                    const unsigned v = n ? static_cast<unsigned>(std::atoi(n)) : 1u;
                    return v ? v : 1u;
                }();
                if (live_untransformed) {
                    ID3D11Buffer* none = nullptr;
                    context->VSSetConstantBuffers(11, 1, &none);
                }
                if (!std::strcmp(camera_mode, "live")) {
                    // Review findings, each a draw that must never become a mesh:
                    context->IASetVertexBuffers(0, 1, &live_vb, &mstride, &moff);
                    context->IASetIndexBuffer(live_ib, DXGI_FORMAT_R32_UINT, 0);
                    context->DrawIndexedInstanced(186, 0, 0, 0, 0);                 // zero instances draws nothing
                    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
                    context->DrawIndexed(183, 0, 0);                                 // not a triangle list
                    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
                    ID3D11Buffer* holes[2] = {nullptr, live_vb};                     // null slot below a bound one
                    const UINT hole_strides[2] = {0, 20}, hole_offsets[2] = {0, 0};
                    context->IASetVertexBuffers(0, 2, holes, hole_strides, hole_offsets);
                    context->IASetInputLayout(live_layout_slot1);
                    context->DrawIndexed(180, 0, 0);
                    context->IASetInputLayout(live_layout);
                    ID3D11Buffer* none = nullptr; const UINT zero = 0;
                    context->IASetVertexBuffers(1, 1, &none, &zero, &zero);
                }
                if (rewrite_same && live_vb && frame != 50) {  // frame 50 must carry the real content change
                    // Identical bytes rewritten every frame: the capture must not turn that into a mesh rebuild.
                    D3D11_MAPPED_SUBRESOURCE map{};
                    if (SUCCEEDED(context->Map(live_vb, 0, D3D11_MAP_WRITE_DISCARD, 0, &map))) {
                        std::memcpy(map.pData, live_vb_template, sizeof live_vb_template);
                        context->Unmap(live_vb, 0);
                    }
                }
                if (spender_from && live_sky_vb && frame >= spender_from) {
                    D3D11_MAPPED_SUBRESOURCE map{};
                    if (SUCCEEDED(context->Map(live_sky_vb, 0, D3D11_MAP_WRITE_DISCARD, 0, &map))) {
                        std::memcpy(map.pData, sky_template, sizeof sky_template);
                        // Its content must change, or the capture never rebuilds it and never reads it.
                        reinterpret_cast<float*>(map.pData)[0] = -50000.f + static_cast<float>(frame % 7);
                        context->Unmap(live_sky_vb, 0);
                    }
                }
                // live-late keeps the texture order deterministic (A then B), so the sky dome is left out of it;
                // the sky has its own scenarios.
                if (!empty_frame && !live_offset && live_sky_vb && !live_late) {
                    // A sky-sized draw every frame; it must be skipped, not uploaded.
                    context->IASetVertexBuffers(0, 1, &live_sky_vb, &mstride, &moff);
                    context->IASetIndexBuffer(live_sky_ib, DXGI_FORMAT_R32_UINT, 0);
                    context->DrawIndexed(192, 0, 0);
                }
                if (lights_now) context->PSSetShaderResources(20, 1, &lights_now);  // slot 20: the game's light array
                for (unsigned repeat = 0; repeat < (empty_frame || frame < sky_only_until ? 0u : repeats); ++repeat)
                for (int pass = (frame >= 40 || live_late || live_hud) ? 2 : 1; pass >= 1; --pass) {
                    if (live_evict && pass == 2 && frame > 45 && frame < 65) continue;  // B unused in between
                    if (live_evict || live_late || live_hud) context->PSSetShaderResources(0, 1, &mesh_srvs[pass == 2 ? 2 : 0]);
                    ID3D11Buffer* vb = pass == 2 ? live_vb2 : live_vb;
                    ID3D11Buffer* ib = pass == 2 ? live_ib2 : live_ib;
                    context->IASetVertexBuffers(0, 1, &vb, &mstride, &moff);
                    context->IASetIndexBuffer(ib, DXGI_FORMAT_R32_UINT, 0);
                    if (live_offset) {
                        const UINT half = 65 * 20;
                        context->IASetVertexBuffers(0, 1, &vb, &mstride, &moff);
                        context->DrawIndexed(192, 192, 0);   // second half via start_index
                        context->DrawIndexed(192, 0, 65);    // second half via base_vertex
                        context->IASetVertexBuffers(0, 1, &vb, &mstride, &half);
                        context->DrawIndexed(192, 0, 0);     // second half via the vertex-buffer offset
                        context->IASetVertexBuffers(0, 1, &vb, &mstride, &moff);
                    } else {
                        if (prepass_layout) {
                            context->IASetInputLayout(prepass_layout);
                            context->VSSetShader(prepass_vs, nullptr, 0);
                            context->DrawIndexed(192, 0, 0);
                            context->IASetInputLayout(live_layout);
                            context->VSSetShader(live_vs, nullptr, 0);
                        }
                        context->DrawIndexed(192, 0, 0);
                        if (live_evict && pass == 1 && frame >= 55) context->DrawIndexed(189, 0, 0);  // mesh C
                    }
                }
                if (late_immutable && frame >= 60) {
                    if (!late_vb) {
                        unsigned char verts[65 * 20];
                        std::memcpy(verts, live_vb_template, sizeof verts);
                        for (unsigned i = 0; i < 65; ++i) reinterpret_cast<float*>(verts + i * 20)[2] = 7.5f;
                        D3D11_BUFFER_DESC vd{}; vd.ByteWidth = sizeof verts; vd.Usage = D3D11_USAGE_IMMUTABLE;
                        vd.BindFlags = D3D11_BIND_VERTEX_BUFFER;
                        D3D11_SUBRESOURCE_DATA vs = {verts, 0, 0};
                        D3D11_BUFFER_DESC id{}; id.ByteWidth = sizeof live_ib_template; id.Usage = D3D11_USAGE_IMMUTABLE;
                        id.BindFlags = D3D11_BIND_INDEX_BUFFER;
                        D3D11_SUBRESOURCE_DATA is = {live_ib_template, 0, 0};
                        if (FAILED(device->CreateBuffer(&vd, &vs, &late_vb)) || FAILED(device->CreateBuffer(&id, &is, &late_ib)))
                            { std::fprintf(out, "FAIL late immutable\n"); return 3; }
                    }
                    context->IASetVertexBuffers(0, 1, &late_vb, &mstride, &moff);
                    context->IASetIndexBuffer(late_ib, DXGI_FORMAT_R32_UINT, 0);
                    context->DrawIndexed(192, 0, 0);
                }
            }
        } else {
            if (frame == 1) key(VK_F9, true);
            if (frame <= 6 || (frame >= 38 && frame <= 44)) { draw_mesh(); draw_mesh(); }  // 2 draws sharing buffers
            if (frame == 4) key(VK_F9, false);
            if (frame == 38) key(VK_F9, true);
            if (frame == 41) key(VK_F9, false);
        }
        if (previous_present_failed) reads_after_failed_present += camera_reads - before_draw;
        if (camera_mode && !std::strcmp(camera_mode, "bypass")) {
            if (frame == 20 || frame == 50) key(VK_F10, true);
            if (frame == 22 || frame == 52) key(VK_F10, false);
            if (frame >= 24 && frame <= 48) reads_while_bypassed += camera_reads - before_draw;
        }
        if (frame == 30) key(VK_INSERT, true);
        if (frame == 32) key(VK_INSERT, false);
        if (frame == 48 && (click_x || click_y)) move_mouse(click);
        if (frame == 50 && (click_x || click_y)) button(true);
        if (frame == 53 && (click_x || click_y)) button(false);
        if (frame == 25) request(L"capture-closed.raw");
        if (frame == 26) std::fprintf(out, "di_mouse_closed=%d\n", blanked(di_mouse, sizeof(DIMOUSESTATE)));
        if (frame == 40) {
            HMODULE owner = nullptr;
            GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               static_cast<LPCWSTR>((*reinterpret_cast<void***>(di_mouse))[9]), &owner);
            std::fprintf(out, "di_mouse_open=%d di_keyboard_open=%d di_slot9_in_proxy=%d\n",
                         blanked(di_mouse, sizeof(DIMOUSESTATE)), blanked(di_keyboard, 256), owner == proxy);
        }
        if (frame == 45) request(L"capture-open.raw");
        if (frame == 70) request(L"capture-after.raw");
        if (frame == resize_at)
            std::fprintf(out, "resize_hr=0x%08lx\n", static_cast<unsigned long>(swapchain->ResizeBuffers(0, resize_w, resize_h, DXGI_FORMAT_UNKNOWN, 0)));
        ID3D11Texture2D* buffer = nullptr;
        swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&buffer));
        ID3D11RenderTargetView* view = nullptr;
        device->CreateRenderTargetView(buffer, nullptr, &view);
        const float color[4] = {0.114f, 0.141f, 0.133f, 1};  // same dark background as the preview captures
        context->ClearRenderTargetView(view, color);
        if (live_hud && hud_vb && hud_ps) {
            // The game's HUD pass: alpha-blended sprites into the final target, after the 3D scene.
            D3D11_TEXTURE2D_DESC bd{}; buffer->GetDesc(&bd);
            D3D11_VIEWPORT hv{0.f, 0.f, static_cast<float>(bd.Width), static_cast<float>(bd.Height), 0.f, 1.f};
            context->RSSetViewports(1, &hv);
            if (live_native_hud) {
                const float original[4]={0.1f,0.15f,0.2f,1};
                context->ClearRenderTargetView(native_hdr_rtv,original);
                context->RSSetState(native_raster);
            }
            context->OMSetRenderTargets(1, live_native_hud ? &native_hdr_rtv : &view, live_native_hud ? nullptr : hud_dsv);
            const float factor[4] = {0.25f, 0.5f, 0.75f, 1.f};
            context->OMSetBlendState(probe_blend, factor, 0x0F0F0F0F);  // straight alpha, like HUD sprites
            context->IASetInputLayout(live_layout);
            context->VSSetShader(live_native_hud ? native_hud_vs : live_vs, nullptr, 0);
            context->PSSetShader(live_native_hud ? native_hud_ps : hud_ps, nullptr, 0);
            context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            const UINT hud_stride = 20, hud_offset = 0;
            context->IASetVertexBuffers(0, 1, &hud_vb, &hud_stride, &hud_offset);
            context->IASetIndexBuffer(hud_ib, DXGI_FORMAT_R16_UINT, 0);
            context->VSSetConstantBuffers(11, 1, &hud_cb11);  // screen-space matrix, as a HUD draw has
            context->PSSetShaderResources(0, 1, &hud_srvs);   // the sprite's own texture
            if (live_native_hud) {
                context->VSSetConstantBuffers(0,1,&hud_cb11);  // real HUD uses CB0, not CB11
                context->PSSetShaderResources(1,1,&hud_srvs); // native mask sampler reads alpha=1
            }
            context->DrawIndexed(6, 0, 0);
            if (live_native_hud) {
                // Second sprite is left of the first: replacing the background twice would erase the first.
                context->VSSetConstantBuffers(0,1,&native_identity);
                context->DrawIndexed(6,0,0);
                context->OMSetRenderTargets(1,&view,nullptr);
                context->OMSetBlendState(nullptr,nullptr,0xffffffff);
                context->IASetInputLayout(nullptr);
                context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
                context->VSSetShader(native_blit_vs,nullptr,0);
                context->PSSetShader(native_blit_ps,nullptr,0);
                context->PSSetShaderResources(0,1,&native_hdr_srv);
                context->Draw(4,0);  // game's final compositor, after all native HUD sprites
                ID3D11ShaderResourceView* null_view=nullptr;
                context->PSSetShaderResources(0,1,&null_view);
            }
        }
        view->Release(); buffer->Release();
        context->CSSetShader(cs, nullptr, 0);
        if (live_mode) { LARGE_INTEGER t1{}; QueryPerformanceCounter(&t1); live_frame_ms += (t1.QuadPart - t0.QuadPart) * 1000.0 / f.QuadPart; }
        const HRESULT present_result = swapchain->Present(1, 0);
        if (live_hud && hud_dsv) {
            // The game's state across Present must be what it left: the HUD replay runs inside Present.
            ID3D11RenderTargetView* rtv_after = nullptr; ID3D11DepthStencilView* dsv_after = nullptr;
            context->OMGetRenderTargets(1, &rtv_after, &dsv_after);
            ID3D11BlendState* blend_after = nullptr; float factor_after[4] = {}; UINT mask_after = 0;
            context->OMGetBlendState(&blend_after, factor_after, &mask_after);
            if (live_native_hud) {
                if (dsv_after || blend_after || mask_after != 0xffffffff) ++state_lost;
            } else if (dsv_after != hud_dsv || blend_after != probe_blend || mask_after != 0x0F0F0F0F || factor_after[1] != 0.5f) ++state_lost;
            if (rtv_after) rtv_after->Release();
            if (dsv_after) dsv_after->Release();
            if (blend_after) blend_after->Release();
        }
        previous_present_failed = FAILED(present_result);
        if (SUCCEEDED(present_result)) ++presented;
        if (frame_camera_reads > peak_camera_reads) peak_camera_reads = frame_camera_reads;
        ID3D11ComputeShader* bound = nullptr; context->CSGetShader(&bound, nullptr, nullptr);
        if (bound != cs) ++cs_lost;
        if (bound) bound->Release();
        Sleep(frame_ms);
    }
    if (live_mode) std::fprintf(out, "live_frame_ms=%.2f\n", live_frame_ms / 80.0);
    if (live_hud) std::fprintf(out, "hud_state_lost=%u\n", state_lost);
    {
        // Is the immediate context's Map (vtable slot 14) inside the proxy, i.e. are the live-capture hooks installed?
        HMODULE owner = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCWSTR>((*reinterpret_cast<void***>(context))[14]), &owner);
        std::fprintf(out, "ctx_map_in_proxy=%d\n", owner == proxy);
    }
    if (overlay_rehook) std::fprintf(out, "overlay_calls=%u overlay_loops=%u overlay_discoveries=%u second_calls=%u second_created=%u foreign_hooked=%u foreign_created=%u\n",
                                    ov_calls, ov_loops, ov_discoveries, second_calls, second_created, foreign_hooked, foreign_created);
    std::fprintf(out, "presented=%u stub_presents=%u foreground=%d cs_lost=%u\n", presented, count(),
                 GetForegroundWindow() == hwnd, cs_lost);
    if (camera_mode) std::fprintf(out, "geometry_reads_late=%u\n", geometry_reads_late);
    if (live_box) std::fprintf(out, "unbound_refs=%u\n", unbound_refs);
    if (live_mode) std::fprintf(out, "cb11_refs_20=%u cb11_refs_79=%u\n", cb11_refs_20, cb11_refs_79);
    if (unbound_dynamic) unbound_dynamic->Release();
    if (camera_mode) std::fprintf(out, "camera_reads=%u geometry_reads=%u peak_camera_reads=%u reads_after_failure=%u reads_after_failed_present=%u failure_observed=%u reads_while_bypassed=%u\n",
                                 camera_reads, geometry_reads, peak_camera_reads,
                                 failure_observed ? camera_reads - reads_at_failure : 0, reads_after_failed_present,
                                 failure_observed ? 1u : 0u, reads_while_bypassed);
    downstream_draw = {};
    for (ID3D11Buffer* b : {live_vb, live_ib, live_vb2, live_ib2, live_cb11, live_sky_vb, live_sky_ib}) if (b) b->Release();
    if (live_layout) live_layout->Release();
    if (live_layout_slot1) live_layout_slot1->Release();
    if (live_vs) live_vs->Release();
    for (IUnknown* p : std::initializer_list<IUnknown*>{native_hdr, native_hdr_rtv, native_hdr_srv, native_hud_ps,
                                                          native_hud_vs, native_blit_vs, native_blit_ps, native_identity, native_raster})
        if (p) p->Release();
    if (camera_buffer) camera_buffer->Release();
    cs->Release();
    di_keyboard->Release(); di_mouse->Release(); di->Release();
    std::fclose(out);
    swapchain->Release(); factory->Release(); adapter->Release(); dxgi->Release(); context->Release(); device->Release();
    return 0;
}
