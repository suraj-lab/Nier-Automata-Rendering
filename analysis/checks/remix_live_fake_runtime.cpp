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
#include <atomic>
#include <cstdint>
#include <set>
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
// Instances this frame, and those that are ray traced. The real runtime hides SKY instances from ray tracing
// (rtx_instance_manager.cpp: cameraType Sky -> m_isHidden); a frame whose instances are all sky has zero surfaces while
// the material cache is not empty, and updateSurfaceMaterials then creates a 0-byte "Surface Material Buffer":
// integer divide by zero in DxvkBuffer (live crash 2026-10-29 17:33, d3d9.dll+0x1d30cc, title screen).
unsigned frame_instances = 0, frame_traced = 0;
bool hang_present = false;
std::atomic<bool> fail_next_copy{false};
unsigned frames = 0, copies = 0, fail_copy_at = 0, materials = 0, meshes = 0, lights = 0;
UINT last_w = 0, last_h = 0;
unsigned long long handle = 0x5000;
// Mesh handles are the hash, as in the real runtime. Laptop probe 2026-10-30 (analysis/remix-probe REPROBE_REPLACE):
// CreateMesh under a hash that is still live keeps the OLD geometry, and re-creating a hash after DestroyMesh crashed
// the runtime (access violation). Both are contract violations here, so the mock gates see what the runtime does.
std::set<unsigned long long> live_meshes, destroyed_meshes;

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
    live_meshes.clear();
    destroyed_meshes.clear();
    if (info) startup_window = info->hwnd;
    return registered ? REMIXAPI_ERROR_CODE_ALREADY_EXISTS : REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* h) {
    ++materials;
    if (i && i->albedoTexture) {
        char path[MAX_PATH * 3] = "";
        WideCharToMultiByte(CP_UTF8, 0, i->albedoTexture, -1, path, sizeof path, nullptr, nullptr);
        const char* slash = std::strrchr(path, '\\');
        const auto* ext = static_cast<const remixapi_MaterialInfoOpaqueEXT*>(i->pNext);
        const bool opaque_ext = ext && ext->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
        note("CreateMaterial path=%s presented=%u alpha=%d/%u hash=%llu", slash ? slash + 1 : path, frames,
             opaque_ext ? ext->alphaTestType : -1, opaque_ext ? unsigned(ext->alphaReferenceValue) : 0u,
             static_cast<unsigned long long>(i->hash));
    }
    *h = reinterpret_cast<remixapi_MaterialHandle>(handle++); return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* h) {
    ++meshes;
    unsigned long long verts = 0, indices = 0;
    bool skinned = false;
    std::uint32_t bones_per_vertex = 0;
    unsigned long long weights = 0;
    for (std::uint32_t s = 0; i && s < i->surfaces_count; ++s) {
        verts += i->surfaces_values[s].vertices_count;
        indices += i->surfaces_values[s].indices_count;
        const auto& sf = i->surfaces_values[s];
        if (sf.skinning_hasvalue) {
            skinned = true;
            bones_per_vertex = sf.skinning_value.bonesPerVertex;
            weights = sf.skinning_value.blendWeights_count;
        }
    }
    float v0[3] = {0, 0, 0};
    if (i && i->surfaces_count && i->surfaces_values[0].vertices_values && i->surfaces_values[0].vertices_count)
        std::memcpy(v0, i->surfaces_values[0].vertices_values[0].position, sizeof v0);
    note("CreateMesh hash=%llu surfaces=%u verts=%llu indices=%llu materials=%u skinned=%d bonesPerVertex=%u weights=%llu v0=%.3f,%.3f,%.3f presented=%u started=%d key=%llu",
         i ? static_cast<unsigned long long>(i->hash) : 0ull, i ? i->surfaces_count : 0u, verts, indices, materials,
         skinned ? 1 : 0, bones_per_vertex, weights, v0[0], v0[1], v0[2], frames, started,
         i ? static_cast<unsigned long long>(i->hash) >> 32 : 0ull);  // live_scene: capture key in the high 32 bits
    if (!started) note("VIOLATION CreateMesh before Startup");
    const unsigned long long hash = i ? static_cast<unsigned long long>(i->hash) : 0ull;
    if (!hash) { *h = reinterpret_cast<remixapi_MeshHandle>(handle++); return REMIXAPI_ERROR_CODE_SUCCESS; }
    if (live_meshes.count(hash)) note("VIOLATION CreateMesh hash=%llu reused while live: the runtime keeps the old geometry", hash);
    if (destroyed_meshes.count(hash)) note("VIOLATION CreateMesh hash=%llu re-created after DestroyMesh: the runtime crashed", hash);
    live_meshes.insert(hash);
    *h = reinterpret_cast<remixapi_MeshHandle>(hash); return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL create_light(const remixapi_LightInfo* info, remixapi_LightHandle* h) {
    ++lights; *h = reinterpret_cast<remixapi_LightHandle>(handle++);
    if (std::getenv("FAKE_REMIX_LIGHT_LOG") && info) {  // which lights the live path asked for, and with what
        const auto* sphere = static_cast<const remixapi_LightInfoSphereEXT*>(info->pNext);
        if (sphere && sphere->sType == REMIXAPI_STRUCT_TYPE_LIGHT_INFO_SPHERE_EXT)
            note("CreateLight n=%u sphere pos=%.3f,%.3f,%.3f radius=%.3f radiance=%.3f,%.3f,%.3f hash=%llu",
                 lights, sphere->position.x, sphere->position.y, sphere->position.z, sphere->radius,
                 info->radiance.x, info->radiance.y, info->radiance.z,
                 static_cast<unsigned long long>(info->hash));
        else
            note("CreateLight n=%u other radiance=%.3f,%.3f,%.3f hash=%llu", lights, info->radiance.x,
                 info->radiance.y, info->radiance.z, static_cast<unsigned long long>(info->hash));
    }
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL setup_camera(const remixapi_CameraInfo* c) {
    if (stage != 0) note("VIOLATION SetupCamera at stage %d", stage);
    if (frames == 0) {
        const auto* p = static_cast<const remixapi_CameraInfoParameterizedEXT*>(c->pNext);
        note("SetupCamera aspect=%.4f fov=%.2f", p ? p->aspect : -1.f, p ? p->fovYInDegrees : -1.f);
    }
    if (std::getenv("FAKE_REMIX_CAMERA_LOG")) {
        const auto* p = static_cast<const remixapi_CameraInfoParameterizedEXT*>(c->pNext);
        if (p) note("Camera pos=%.3f,%.3f,%.3f forward=%.3f,%.3f,%.3f fov=%.2f aspect=%.4f",
                    p->position.x, p->position.y, p->position.z, p->forward.x, p->forward.y, p->forward.z,
                    p->fovYInDegrees, p->aspect);
    }
    stage = 1; frame_instances = frame_traced = 0; return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL draw_instance(const remixapi_InstanceInfo* i) {
    if (stage < 1 || stage > 2) note("VIOLATION DrawInstance at stage %d", stage);
    ++frame_instances;
    if (i && !(i->categoryFlags & REMIXAPI_INSTANCE_CATEGORY_BIT_SKY)) ++frame_traced;
    if (std::getenv("FAKE_REMIX_INSTANCE_LOG") && i) {  // remixapi_Transform is float matrix[3][4]; there is no row 3
        const auto& m = i->transform.matrix;
        const auto* bones = static_cast<const remixapi_InstanceInfoBoneTransformsEXT*>(i->pNext);
        const std::uint32_t bone_count = bones && bones->sType == REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BONE_TRANSFORMS_EXT
                                             ? bones->boneTransforms_count : 0u;
        note("DrawInstance presented=%u mesh=%llu bones=%u flags=%u row0=%.3f,%.3f,%.3f,%.3f row1=%.3f,%.3f,%.3f,%.3f row2=%.3f,%.3f,%.3f,%.3f",
             frames,
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(i->mesh)), bone_count, i->categoryFlags,
             m[0][0], m[0][1], m[0][2], m[0][3], m[1][0], m[1][1], m[1][2], m[1][3],
             m[2][0], m[2][1], m[2][2], m[2][3]);
        if (bone_count && bones->boneTransforms_values) {
            const remixapi_Transform& b0 = bones->boneTransforms_values[0];
            const remixapi_Transform& b1 = bones->boneTransforms_values[bone_count > 1 ? 1 : 0];
            note("Bones count=%u b0=%.3f,%.3f,%.3f,%.3f b1=%.3f,%.3f,%.3f,%.3f", bone_count,
                 b0.matrix[0][0], b0.matrix[0][1], b0.matrix[0][2], b0.matrix[0][3],
                 b1.matrix[0][0], b1.matrix[0][1], b1.matrix[0][2], b1.matrix[0][3]);
        }
    }
    stage = 2; return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL draw_light(remixapi_LightHandle h) {
    if (stage < 2 || stage > 3) note("VIOLATION DrawLightInstance at stage %d", stage);
    if (std::getenv("FAKE_REMIX_LIGHT_LOG"))
        note("DrawLightInstance presented=%u handle=%llu", frames,
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(h)));
    stage = 3; return REMIXAPI_ERROR_CODE_SUCCESS;
}
remixapi_ErrorCode REMIXAPI_CALL present(const remixapi_PresentInfo*) {
    if (stage != 3) note("VIOLATION Present at stage %d", stage);
    if (frame_instances && !frame_traced)
        note("VIOLATION Present with %u instances, all SKY: zero ray-traced surfaces (real runtime: divide by zero)", frame_instances);
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
    if (fail_next_copy.load() || (fail_copy_at && copies == fail_copy_at)) {
        note("Copy %u failing on request", copies); return REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
    }
    IDirect3DSurface9* bb = nullptr; D3DSURFACE_DESC b{}, t{};
    if (FAILED(registered->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) { note("VIOLATION no backbuffer"); return REMIXAPI_ERROR_CODE_GENERAL_FAILURE; }
    bb->GetDesc(&b); bb->Release(); surface->GetDesc(&t);
    if (b.Width != t.Width || b.Height != t.Height) note("VIOLATION copy target %ux%u, backbuffer %ux%u", t.Width, t.Height, b.Width, b.Height);
    if (t.Width != last_w || t.Height != last_h) { note("Copy %ux%u", t.Width, t.Height); last_w = t.Width; last_h = t.Height; }
    // The "path-traced frame": opaque (R,G,B) = (200,40,120), deliberately asymmetric so a channel swap shows.
    // Plus a blue 32x32 bottom-right block: a composite that samples one texel (broken UVs clamp to that corner) turns
    // the whole frame blue, which a single uniform colour could never reveal.
    const RECT corner{static_cast<LONG>(t.Width) - 32, static_cast<LONG>(t.Height) - 32,
                      static_cast<LONG>(t.Width), static_cast<LONG>(t.Height)};
    return SUCCEEDED(registered->ColorFill(surface, nullptr, D3DCOLOR_XRGB(200, 40, 120))) &&
                   SUCCEEDED(registered->ColorFill(surface, &corner, D3DCOLOR_XRGB(30, 60, 220)))
               ? REMIXAPI_ERROR_CODE_SUCCESS
               : REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
}
}  // namespace

extern "C" __declspec(dllexport) void fake_fail_copy_next() { fail_next_copy.store(true); }

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
    api->DestroyMesh = [](remixapi_MeshHandle m) {
        const auto hash = static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(m));
        if (live_meshes.erase(hash)) destroyed_meshes.insert(hash);
        return REMIXAPI_ERROR_CODE_SUCCESS;
    };
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
