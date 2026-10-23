// Windowed D3D11 swapchain probe: closer to a game than the console FSR probe.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <cstdio>

static LRESULT CALLBACK Proc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(h, m, w, l);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int)
{
    FILE* out = _wfopen(L"windowed-present-results.txt", L"w");
    if (!out) return 2;
    WNDCLASSW wc{};
    wc.lpfnWndProc = Proc;
    wc.hInstance = inst;
    wc.lpszClassName = L"SKProbe";
    RegisterClassW(&wc);
    HWND hwnd = CreateWindowW(L"SKProbe", L"SK probe", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                              0, 0, 640, 360, nullptr, nullptr, inst, nullptr);
    fprintf(out, "WINDOW %s\n", hwnd ? "OK" : "FAIL"); fflush(out);
    if (!hwnd) return 1;

    DXGI_SWAP_CHAIN_DESC sd{};
    sd.BufferCount = 2;
    sd.BufferDesc.Width = 640;
    sd.BufferDesc.Height = 360;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hwnd;
    sd.SampleDesc.Count = 1;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    ID3D11Device* dev = nullptr; ID3D11DeviceContext* ctx = nullptr; IDXGISwapChain* sc = nullptr;
    const D3D_FEATURE_LEVEL fl = D3D_FEATURE_LEVEL_11_0;
    HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, &fl, 1,
                                               D3D11_SDK_VERSION, &sd, &sc, &dev, nullptr, &ctx);
    fprintf(out, "CREATE 0x%08lX\n", (unsigned long)hr); fflush(out);
    if (FAILED(hr)) return 1;

    ID3D11Texture2D* back = nullptr; ID3D11RenderTargetView* rtv = nullptr;
    sc->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&back);
    dev->CreateRenderTargetView(back, nullptr, &rtv);
    int presented = 0;
    DWORD start = GetTickCount();
    while (GetTickCount() - start < 4000)
    {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        const float c[4] = {0.1f, 0.2f, 0.3f, 1.0f};
        ctx->ClearRenderTargetView(rtv, c);
        if (SUCCEEDED(sc->Present(1, 0))) ++presented;
    }
    fprintf(out, "PRESENTED %d\nRESULT %s\n", presented, presented > 30 ? "PASS" : "FAIL");
    fclose(out);
    rtv->Release(); back->Release(); sc->Release(); ctx->Release(); dev->Release();
    DestroyWindow(hwnd);
    return presented > 30 ? 0 : 1;
}
