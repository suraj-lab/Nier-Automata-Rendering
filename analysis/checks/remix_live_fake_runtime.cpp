// Test fixture standing in for the RTX Remix runtime (never shipped). Exports remixapi_InitializeLibrary and
// hands out an interface whose D3D9 side is Wine's real d3d9 (so device creation, Reset, GetRenderTargetData and
// LockRect are the real code paths), while "rendering" is a ColorFill with a known colour. Every call is appended
// to fake-remix.log in the working directory, and order violations are logged as "VIOLATION ..." lines, so the
// test can pin the call contract from LIVE_TRANSFER.md without a GPU.
// FAKE_REMIX_FAIL=copy:<n> makes the n-th CopyRenderingOutput fail, to test the fallback to game frames.
#define REMIX_LIBRARY_EXPORTS
#include <windows.h>
#include <d3d9.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <remix_c.h>

namespace {
FILE* out = nullptr;
void note(const char* fmt, ...) {
    if (!out) out = std::fopen("fake-remix.log", "w");
    if (!out) return;
    va_list a; va_start(a, fmt); std::vfprintf(out, fmt, a); va_end(a);
    std::fputc('\n', out); std::fflush(out);
}
IDirect3DDevice9Ex* registered = nullptr;
HWND startup_window = nullptr;
bool started = false;
int stage = 0;  // per-frame order: 0 idle, 1 camera, 2 instance, 3+ lights, 9 presented
bool hang_present = false;
unsigned frames = 0, copies = 0, fail_copy_at = 0, materials = 0, meshes = 0, lights = 0;
UINT last_w = 0, last_h = 0;
unsigned long long handle = 0x5000;

remixapi_ErrorCode REMIXAPI_CALL create_d3d9(remixapi_Bool, IDirect3D9Ex** out9) {
    note("CreateD3D9 registered=%d started=%d", registered != nullptr, started);
    return SUCCEEDED(Direct3DCreate9Ex(D3D_SDK_VERSION, out9)) ? REMIXAPI_ERROR_CODE_SUCCESS : REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
}
remixapi_ErrorCode REMIXAPI_CALL register_device(IDirect3DDevice9Ex* device) {
    IDirect3DSurface9* bb = nullptr; D3DSURFACE_DESC d{};
    if (SUCCEEDED(device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) { bb->GetDesc(&d); bb->Release(); }
    note("Register %ux%u started=%d", d.Width, d.Height, started);
    if (started) note("VIOLATION register after Startup");
    registered = device;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL startup(const remixapi_StartupInfo* info) {
    note("Startup hwnd_visible=%d combineGui=%d registered=%d", info && IsWindowVisible(info->hwnd), info ? info->combineGuiInFinalColor : -1,
         registered != nullptr);
    if (!registered) note("VIOLATION Startup before Register");
    started = true;
    if (info) startup_window = info->hwnd;
    return registered ? REMIXAPI_ERROR_CODE_ALREADY_EXISTS : REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo*, remixapi_MaterialHandle* h) {
    ++materials; *h = reinterpret_cast<remixapi_MaterialHandle>(handle++); return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* h) {
    ++meshes; note("CreateMesh surfaces=%u materials=%u started=%d", i->surfaces_count, materials, started);
    if (!started) note("VIOLATION CreateMesh before Startup");
    *h = reinterpret_cast<remixapi_MeshHandle>(handle++); return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL create_light(const remixapi_LightInfo*, remixapi_LightHandle* h) {
    ++lights; *h = reinterpret_cast<remixapi_LightHandle>(handle++); return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL setup_camera(const remixapi_CameraInfo* c) {
    if (stage != 0) note("VIOLATION SetupCamera at stage %d", stage);
    if (frames == 0) {
        const auto* p = static_cast<const remixapi_CameraInfoParameterizedEXT*>(c->pNext);
        note("SetupCamera aspect=%.4f fov=%.2f", p ? p->aspect : -1.f, p ? p->fovYInDegrees : -1.f);
    }
    stage = 1; return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL draw_instance(const remixapi_InstanceInfo*) {
    if (stage != 1) note("VIOLATION DrawInstance at stage %d", stage);
    stage = 2; return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL draw_light(remixapi_LightHandle) {
    if (stage < 2 || stage > 3) note("VIOLATION DrawLightInstance at stage %d", stage);
    stage = 3; return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL present(const remixapi_PresentInfo*) {
    if (stage != 3) note("VIOLATION Present at stage %d", stage);
    if (hang_present && frames == 3) { note("Present hanging on request"); Sleep(INFINITE); }
    ++frames; stage = 9;
    if (frames == 1 && startup_window) {
        // What the real runtime does to its window (measured 2026-10-27: it imports ShowWindow/SetWindowPos and the
        // "hidden" window came up fullscreen and white over the player's monitor). The host must keep it hidden.
        ShowWindow(startup_window, SW_SHOW);
        SetWindowPos(startup_window, HWND_TOP, 0, 0, 3440, 1440, SWP_SHOWWINDOW);
        RECT r{}; GetWindowRect(startup_window, &r);
        note("Window after show attempt visible=%d size=%ldx%ld", IsWindowVisible(startup_window) ? 1 : 0, r.right - r.left, r.bottom - r.top);
        // The real runtime also creates its own visible "RemixGuiInputSink" window copying this window's rectangle
        // (measured 2026-10-27). Wine fullscreens a borderless window that covers a monitor: white over the desktop.
        HWND sink = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, L"STATIC", L"", WS_POPUP, r.left, r.top,
                                    r.right - r.left, r.bottom - r.top, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
        // FAKE_REMIX_FAIL=steal-focus: the sink takes the foreground (suspected in NieR: the game dropped to its 720x480
        // focus-lost window 0.2-0.4 s after Remix started). Default: shown without activation.
        const char* f = std::getenv("FAKE_REMIX_FAIL");
        if (f && !std::strcmp(f, "steal-focus")) { ShowWindow(sink, SW_SHOW); SetForegroundWindow(sink); note("Sink took focus"); }
        else ShowWindow(sink, SW_SHOWNOACTIVATE);
        RECT sr{}; GetWindowRect(sink, &sr);
        note("Sink rect=%ld,%ld,%ld,%ld", sr.left, sr.top, sr.right, sr.bottom);
    }
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL copy_output(IDirect3DSurface9* surface, remixapi_dxvk_CopyRenderingOutputType type) {
    ++copies;
    if (stage != 9) note("VIOLATION CopyRenderingOutput at stage %d (no Present since the last copy)", stage);
    stage = 0;
    if (type != REMIXAPI_DXVK_COPY_RENDERING_OUTPUT_TYPE_FINAL_COLOR) note("VIOLATION copy type %d", static_cast<int>(type));
    if (fail_copy_at && copies == fail_copy_at) { note("Copy %u failing on request", copies); return REMIXAPI_ERROR_CODE_GENERAL_FAILURE; }
    IDirect3DSurface9* bb = nullptr; D3DSURFACE_DESC b{}, t{};
    if (FAILED(registered->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) { note("VIOLATION no backbuffer"); return REMIXAPI_ERROR_CODE_GENERAL_FAILURE; }
    bb->GetDesc(&b); bb->Release(); surface->GetDesc(&t);
    if (b.Width != t.Width || b.Height != t.Height) note("VIOLATION copy target %ux%u, backbuffer %ux%u", t.Width, t.Height, b.Width, b.Height);
    if (t.Width != last_w || t.Height != last_h) { note("Copy %ux%u", t.Width, t.Height); last_w = t.Width; last_h = t.Height; }
    // The "path-traced frame": opaque (R,G,B) = (200,40,120), deliberately asymmetric so a channel swap shows.
    return SUCCEEDED(registered->ColorFill(surface, nullptr, D3DCOLOR_XRGB(200, 40, 120))) ? REMIXAPI_ERROR_CODE_SUCCESS
                                                                                            : REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
}
}  // namespace

extern "C" __declspec(dllexport) remixapi_ErrorCode REMIXAPI_CALL remixapi_InitializeLibrary(const remixapi_InitializeLibraryInfo* info,
                                                                                            remixapi_Interface* api) {
    if (const char* f = std::getenv("FAKE_REMIX_FAIL"); f && !std::strncmp(f, "copy:", 5)) fail_copy_at = static_cast<unsigned>(std::atoi(f + 5));
    if (const char* f = std::getenv("FAKE_REMIX_FAIL"); f && !std::strcmp(f, "hang:present")) hang_present = true;
    note("InitializeLibrary version_minor=%llu", info ? static_cast<unsigned long long>(REMIXAPI_VERSION_GET_MINOR(info->version)) : 0ull);
    *api = remixapi_Interface{};
    api->Shutdown = [] { return REMIXAPI_ERROR_CODE_SUCCESS; };
    api->CreateMaterial = create_material;
    api->DestroyMaterial = [](remixapi_MaterialHandle) { return REMIXAPI_ERROR_CODE_SUCCESS; };
    api->CreateMesh = create_mesh;
    api->DestroyMesh = [](remixapi_MeshHandle) { return REMIXAPI_ERROR_CODE_SUCCESS; };
    api->SetupCamera = setup_camera;
    api->DrawInstance = draw_instance;
    api->CreateLight = create_light;
    api->DestroyLight = [](remixapi_LightHandle) { return REMIXAPI_ERROR_CODE_SUCCESS; };
    api->DrawLightInstance = draw_light;
    api->dxvk_CreateD3D9 = create_d3d9;
    api->dxvk_RegisterD3D9Device = register_device;
    api->dxvk_CopyRenderingOutput = copy_output;
    api->Startup = startup;
    api->Present = present;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
