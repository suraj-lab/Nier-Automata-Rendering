// Read-only: reports what Wine's DXGI/GDI expose, as a game would see them.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dxgi.h>
#include <cstdio>
#include <vector>

int main()
{
    std::printf("== EnumDisplayDevices ==\n");
    for (DWORD i = 0;; ++i) {
        DISPLAY_DEVICEW dd{}; dd.cb = sizeof(dd);
        if (!EnumDisplayDevicesW(nullptr, i, &dd, 0)) break;
        DEVMODEW dm{}; dm.dmSize = sizeof(dm);
        EnumDisplaySettingsW(dd.DeviceName, ENUM_CURRENT_SETTINGS, &dm);
        std::printf("%lu %ls primary=%d attached=%d current=%lux%lu pos=%ld,%ld\n", i, dd.DeviceName,
            !!(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE), !!(dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP),
            dm.dmPelsWidth, dm.dmPelsHeight, dm.dmPosition.x, dm.dmPosition.y);
    }
    std::printf("== DXGI adapter 0 outputs ==\n");
    IDXGIFactory1* factory = nullptr;
    if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&factory)))) return 1;
    IDXGIAdapter1* adapter = nullptr;
    if (FAILED(factory->EnumAdapters1(0, &adapter))) return 1;
    for (UINT o = 0;; ++o) {
        IDXGIOutput* output = nullptr;
        if (adapter->EnumOutputs(o, &output) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_OUTPUT_DESC desc{};
        output->GetDesc(&desc);
        UINT count = 0;
        output->GetDisplayModeList(DXGI_FORMAT_R8G8B8A8_UNORM, 0, &count, nullptr);
        std::vector<DXGI_MODE_DESC> modes(count);
        if (count) output->GetDisplayModeList(DXGI_FORMAT_R8G8B8A8_UNORM, 0, &count, modes.data());
        UINT maxW = 0, maxH = 0;
        for (const auto& m : modes)
            if (m.Width * m.Height > maxW * maxH) { maxW = m.Width; maxH = m.Height; }
        const RECT& r = desc.DesktopCoordinates;
        std::printf("output %u %ls desktop=%ld,%ld-%ld,%ld attached=%d modes=%u max=%ux%u\n", o, desc.DeviceName,
            r.left, r.top, r.right, r.bottom, desc.AttachedToDesktop, count, maxW, maxH);
        output->Release();
    }
    adapter->Release(); factory->Release();
    return 0;
}
