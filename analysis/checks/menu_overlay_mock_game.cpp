// Mock game for the in-game menu: loads the proxy d3d11.dll from its own folder, creates a device and a
// factory swapchain like NieR, presents frames, presses Insert and clicks with real Win32 input.
// Usage: menu_overlay_mock_game.exe <click_x> <click_y>   (client coordinates; 0 0 = no click)
// Writes mock-result.txt. Frame plan: 1-29 closed, capture "closed" at 25, Insert at 30, capture "open" at 45,
// click at 50 (down) / 53 (up), capture "after" at 70, exit at 80.
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

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
    HMODULE stub = GetModuleHandleW(L"d3d11_dlaa.dll");
    auto create = reinterpret_cast<decltype(&D3D11CreateDevice)>(reinterpret_cast<void*>(GetProcAddress(proxy, "D3D11CreateDevice")));
    char self_path[MAX_PATH] = ""; GetModuleFileNameA(proxy, self_path, MAX_PATH);
    std::fprintf(out, "proxy=%s\n", self_path);
    ID3D11Device* device = nullptr; ID3D11DeviceContext* context = nullptr;
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
    sd.BufferCount = 2; sd.BufferDesc.Width = 1920; sd.BufferDesc.Height = 1080;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM; sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
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
    const char ps_src[] = "float4 main() : SV_TARGET { return float4(0,0,0,0); }\n";
    ID3DBlob* ps_blob = nullptr;
    if (!compile || FAILED(compile(ps_src, sizeof ps_src - 1, "ps", nullptr, nullptr, "main", "ps_4_0", 0, 0, &ps_blob, nullptr)))
        { std::fprintf(out, "FAIL mesh ps\n"); return 3; }
    ID3D11PixelShader* mesh_ps = nullptr;
    device->CreatePixelShader(ps_blob->GetBufferPointer(), ps_blob->GetBufferSize(), nullptr, &mesh_ps);
    ps_blob->Release();
    D3D11_TEXTURE2D_DESC mrt{}; mrt.Width = 64; mrt.Height = 64; mrt.MipLevels = 1; mrt.ArraySize = 1;
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
    const auto draw_mesh = [&]() {
        const UINT mstride = 16, moff = 0;
        context->OMSetRenderTargets(1, &mesh_rtv, nullptr);
        D3D11_VIEWPORT vp{0, 0, 64, 64, 0, 1};
        context->RSSetViewports(1, &vp);
        context->IASetInputLayout(mesh_layout);
        context->IASetVertexBuffers(0, 1, &mesh_vb_buf, &mstride, &moff);
        context->IASetIndexBuffer(mesh_ib_buf, DXGI_FORMAT_R16_UINT, 0);
        context->VSSetShader(mesh_vs, nullptr, 0);
        context->PSSetShader(mesh_ps, nullptr, 0);
        context->VSSetConstantBuffers(0, 1, &mesh_cb_buf);
        context->PSSetConstantBuffers(0, 1, &mesh_cb_buf);  // one PS buffer at a slot the VS also uses
        context->PSSetShaderResources(0, 3, mesh_srvs);
        context->DrawIndexed(192, 0, 0);
    };
    unsigned presented = 0, cs_lost = 0;
    for (int frame = 1; frame <= 80; ++frame) {
        MSG msg; while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        // Frame capture: F9 held 1-4 records exactly one frame; the mesh is drawn twice every frame 1-6, so
        // a wrong frame boundary shows up as a draw count other than 2. Second F9 (38-41) runs with the panel open:
        // its ImGui draws must not be recorded either.
        if (frame == 1) key(VK_F9, true);
        if (frame <= 6 || (frame >= 38 && frame <= 44)) { draw_mesh(); draw_mesh(); }  // 2 draws sharing buffers
        if (frame == 4) key(VK_F9, false);
        if (frame == 38) key(VK_F9, true);
        if (frame == 41) key(VK_F9, false);
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
        ID3D11Texture2D* buffer = nullptr;
        swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&buffer));
        ID3D11RenderTargetView* view = nullptr;
        device->CreateRenderTargetView(buffer, nullptr, &view);
        const float color[4] = {0.114f, 0.141f, 0.133f, 1};  // same dark background as the preview captures
        context->ClearRenderTargetView(view, color);
        view->Release(); buffer->Release();
        context->CSSetShader(cs, nullptr, 0);
        if (SUCCEEDED(swapchain->Present(1, 0))) ++presented;
        ID3D11ComputeShader* bound = nullptr; context->CSGetShader(&bound, nullptr, nullptr);
        if (bound != cs) ++cs_lost;
        if (bound) bound->Release();
        Sleep(16);
    }
    std::fprintf(out, "presented=%u stub_presents=%u foreground=%d cs_lost=%u\n", presented, count(),
                 GetForegroundWindow() == hwnd, cs_lost);
    cs->Release();
    di_keyboard->Release(); di_mouse->Release(); di->Release();
    std::fclose(out);
    swapchain->Release(); factory->Release(); adapter->Release(); dxgi->Release(); context->Release(); device->Release();
    return 0;
}
