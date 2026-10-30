// Test fixture standing in for NIER_DLAA's d3d11_dlaa.dll (never shipped). Like the real mod it hooks
// IDXGIFactory::CreateSwapChain at device creation and the swapchain's Present when one is created,
// by vtable slot. Its Present counts frames and can copy the backbuffer it receives to a file, so the
// test sees exactly what the outer menu layer passed down the chain.
#include <windows.h>
#include <d3d11.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cstdlib>

using CreateDeviceFn = decltype(&D3D11CreateDevice);
using CreateSwapChainFn = HRESULT (STDMETHODCALLTYPE*)(IDXGIFactory*, IUnknown*, DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**);
using PresentFn = HRESULT (STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);
static CreateSwapChainFn real_create = nullptr;
static PresentFn real_present = nullptr;
static std::atomic<unsigned> presents{0};
static wchar_t capture_path[MAX_PATH] = L"";

static void* patch(void* object, std::size_t index, void* replacement) {
    void** slot = *static_cast<void***>(object) + index;
    DWORD old = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) return nullptr;
    void* previous = *slot;
    *slot = replacement;
    VirtualProtect(slot, sizeof(void*), old, &old);
    return previous;
}

static void capture(IDXGISwapChain* swapchain) {
    ID3D11Texture2D* buffer = nullptr;
    if (FAILED(swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&buffer)))) return;
    ID3D11Device* device = nullptr; buffer->GetDevice(&device);
    ID3D11DeviceContext* context = nullptr; device->GetImmediateContext(&context);
    D3D11_TEXTURE2D_DESC desc{}; buffer->GetDesc(&desc);
    desc.Usage = D3D11_USAGE_STAGING; desc.BindFlags = 0; desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ; desc.MiscFlags = 0;
    ID3D11Texture2D* staging = nullptr;
    if (SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &staging))) {
        context->CopyResource(staging, buffer);
        D3D11_MAPPED_SUBRESOURCE map{};
        if (SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &map))) {
            if (FILE* f = _wfopen(capture_path, L"wb")) {
                const unsigned header[3] = {desc.Width, desc.Height, static_cast<unsigned>(desc.Format)};
                std::fwrite(header, sizeof header, 1, f);
                for (UINT y = 0; y < desc.Height; ++y)
                    std::fwrite(static_cast<unsigned char*>(map.pData) + y * map.RowPitch, 4, desc.Width, f);
                std::fclose(f);
            }
            context->Unmap(staging, 0);
        }
        staging->Release();
    }
    context->Release(); device->Release(); buffer->Release();
}

static HRESULT STDMETHODCALLTYPE stub_present(IDXGISwapChain* self, UINT sync, UINT flags) {
    const unsigned frame = presents.fetch_add(1) + 1;
    const char* mode = std::getenv("MOCK_CAMERA");
    if (mode && (!std::strcmp(mode, "present-boundary") || !std::strcmp(mode, "present-fail"))) {
        auto draw = reinterpret_cast<void (*)()>(reinterpret_cast<void*>(GetProcAddress(GetModuleHandleW(nullptr), "mock_downstream_camera_draw")));
        if (draw) draw();
        if (!std::strcmp(mode, "present-fail") && frame == 20) return E_FAIL;
    }
    if (capture_path[0]) { capture(self); capture_path[0] = 0; }
    return real_present(self, sync, flags);
}

static HRESULT STDMETHODCALLTYPE stub_create(IDXGIFactory* self, IUnknown* dev, DXGI_SWAP_CHAIN_DESC* desc, IDXGISwapChain** out) {
    const HRESULT hr = real_create(self, dev, desc, out);
    // STUB_NO_PRESENT_HOOK: like NIER_DLAA behind our proxy on the laptop, whose hooks never initialise.
    if (SUCCEEDED(hr) && out && *out && !real_present && !std::getenv("STUB_NO_PRESENT_HOOK"))
        real_present = reinterpret_cast<PresentFn>(patch(*out, 8, reinterpret_cast<void*>(&stub_present)));
    return hr;
}

extern "C" __declspec(dllexport) unsigned stub_present_count() { return presents.load(); }
extern "C" __declspec(dllexport) void stub_request_capture(const wchar_t* path) { wcsncpy(capture_path, path, MAX_PATH - 1); }

extern "C" __declspec(dllexport) HRESULT WINAPI D3D11CreateDevice(IDXGIAdapter* adapter, D3D_DRIVER_TYPE type, HMODULE sw,
    UINT flags, const D3D_FEATURE_LEVEL* levels, UINT n, UINT sdk, ID3D11Device** out, D3D_FEATURE_LEVEL* level,
    ID3D11DeviceContext** context) {
    static const CreateDeviceFn real = [] {
        FARPROC p = GetProcAddress(LoadLibraryW(L"C:\\windows\\system32\\d3d11.dll"), "D3D11CreateDevice");
        CreateDeviceFn f = nullptr; std::memcpy(&f, &p, sizeof f); return f;
    }();
    const HRESULT hr = real ? real(adapter, type, sw, flags, levels, n, sdk, out, level, context) : E_FAIL;
    if (SUCCEEDED(hr) && out && *out && !real_create) {  // "installing hooks" at device creation, like the real mod
        IDXGIDevice* dxgi = nullptr; IDXGIAdapter* a = nullptr; IDXGIFactory* factory = nullptr;
        if (SUCCEEDED((*out)->QueryInterface(__uuidof(IDXGIDevice), reinterpret_cast<void**>(&dxgi))) &&
            SUCCEEDED(dxgi->GetAdapter(&a)) && SUCCEEDED(a->GetParent(__uuidof(IDXGIFactory), reinterpret_cast<void**>(&factory))))
            real_create = reinterpret_cast<CreateSwapChainFn>(patch(factory, 10, reinterpret_cast<void*>(&stub_create)));
        if (factory) factory->Release();
        if (a) a->Release();
        if (dxgi) dxgi->Release();
    }
    return hr;
}

extern "C" __declspec(dllexport) HRESULT WINAPI D3D11CreateDeviceAndSwapChain(IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT,
    const D3D_FEATURE_LEVEL*, UINT, UINT, const DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**, ID3D11Device**, D3D_FEATURE_LEVEL*,
    ID3D11DeviceContext**) {
    return E_NOTIMPL;  // the mock game, like NieR, uses the factory path
}
