// Mock game for the in-game menu: loads the proxy d3d11.dll from its own folder, creates a device and a
// factory swapchain like NieR, presents frames, presses Insert and clicks with real Win32 input.
// Usage: menu_overlay_mock_game.exe <click_x> <click_y>   (client coordinates; 0 0 = no click)
// Writes mock-result.txt. Frame plan: 1-29 closed, capture "closed" at 25, Insert at 30, capture "open" at 45,
// click at 50 (down) / 53 (up), capture "after" at 70, exit at 80.
#include <windows.h>
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
    unsigned presented = 0, cs_lost = 0;
    for (int frame = 1; frame <= 80; ++frame) {
        MSG msg; while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        if (frame == 30) key(VK_INSERT, true);
        if (frame == 32) key(VK_INSERT, false);
        if (frame == 48 && (click_x || click_y)) SetCursorPos(click.x, click.y);
        if (frame == 50 && (click_x || click_y)) button(true);
        if (frame == 53 && (click_x || click_y)) button(false);
        if (frame == 25) request(L"capture-closed.raw");
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
    std::fclose(out);
    swapchain->Release(); factory->Release(); adapter->Release(); dxgi->Release(); context->Release(); device->Release();
    return 0;
}
