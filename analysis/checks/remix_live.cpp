#include "remix_live.h"
#include <unordered_map>
#include <windows.h>
#include <d3d9.h>
#include <d3d11.h>
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <mutex>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <remix_c.h>
#include "nscn_scene.h"
#include "camera_capture.h"
#include "live_capture.h"
#include "live_scene.h"
#include "hud_replay.h"
#include "hud_shader.h"

namespace remix_live {
namespace {
using Log = void (*)(const char*, ...);

enum class State { Unchecked, Off, Waiting, Running, Failed };
std::atomic<State> state{State::Unchecked};
std::atomic<bool> original_view{false};
std::atomic<Log> logger{nullptr};
std::wstring runtime_path, scene_path, sky_path;
nscn::Options live_options;  // set once in configure(), before the worker starts
bool live_enabled = false;  // NIER_REMIX_LIVE=1: build the scene from the game's draw stream instead of the file
std::uint64_t live_sequence = 0;        // worker only
std::wstring live_texture_dir;
std::size_t live_mesh_budget = std::size_t(512) << 20;

struct Frame { std::vector<unsigned char> pixels; UINT width = 0, height = 0; DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN; unsigned long long seq = 0; };
// Guarded by `published`: the newest finished frame, and what the game currently presents.
std::mutex published;
Frame ready;
UINT want_width = 0, want_height = 0;
DXGI_FORMAT want_format = DXGI_FORMAT_UNKNOWN;
Frame shown;  // presenting thread only
bool native_hud_composed = false, native_hud_attempted = false;  // reset after each Present

// Where the worker and the game's Present hook are, so a stall can be attributed from the log (2026-10-28: Remix
// stuck in its first frame inside NieR with the game frozen; the mock game never reproduced it).
std::atomic<const char*> worker_stage{"idle"};
std::atomic<ULONGLONG> worker_stage_since{0};
std::atomic<const char*> hook_stage{"idle"};
std::atomic<unsigned long long> presents{0};
std::atomic<ULONGLONG> last_present{0};
void stage(const char* s) { worker_stage.store(s); worker_stage_since.store(GetTickCount64()); }

bool rgba(DXGI_FORMAT f) { return f == DXGI_FORMAT_R8G8B8A8_UNORM || f == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB; }
bool bgra(DXGI_FORMAT f) { return f == DXGI_FORMAT_B8G8R8A8_UNORM || f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB; }

void watchdog() {
    const char* reported = nullptr;
    ULONGLONG reported_since = 0, reported_at = 0;
    while (state.load() != State::Failed) {
        Sleep(1000);
        const char* s = worker_stage.load();
        const ULONGLONG since = worker_stage_since.load(), now = GetTickCount64();
        if (now - since < 5000) continue;
        // One line per stall, then at most every 30 s while it lasts.
        if (s == reported && since == reported_since && now - reported_at < 30000) continue;
        reported = s; reported_since = since; reported_at = now;
        if (Log l = logger.load())
            l("remix: watchdog worker in '%s' for %llu ms; game presents=%llu, last %llu ms ago, hook in '%s'", s, now - since,
              presents.load(), last_present.load() ? now - last_present.load() : 0ull, hook_stage.load());
    }
}

void fail(const char* why, long code = 0) {
    camera_capture::set_enabled(false);
    live_capture::set_permitted(false);
    State expected = state.load();
    if (expected == State::Failed) return;
    state.store(State::Failed);
    if (Log l = logger.load()) l("remix: disabled (%s %ld); game frames are shown", why, code);
}

std::wstring env(const wchar_t* name) {
    wchar_t buffer[1024];
    const DWORD n = GetEnvironmentVariableW(name, buffer, 1024);
    return n && n < 1024 ? std::wstring(buffer, n) : std::wstring();
}
bool absolute(const std::wstring& p) {
    return (p.size() >= 3 && p[1] == L':' && (p[2] == L'\\' || p[2] == L'/')) || p.rfind(L"\\\\", 0) == 0;
}

State configure() {
    if (env(L"NIER_REMIX") != L"1") return State::Off;
    runtime_path = env(L"NIER_REMIX_RUNTIME");
    scene_path = env(L"NIER_REMIX_SCENE");
    if (!absolute(runtime_path)) { fail("NIER_REMIX_RUNTIME must be an absolute path"); return State::Failed; }
    if (!absolute(scene_path)) { fail("NIER_REMIX_SCENE must be an absolute path"); return State::Failed; }
    live_enabled = env(L"NIER_REMIX_LIVE") == L"1";
    if (live_enabled) {
        live_texture_dir = env(L"NIER_REMIX_LIVE_TEX");
        if (!absolute(live_texture_dir)) { fail("NIER_REMIX_LIVE_TEX must be an absolute path"); return State::Failed; }
        live_capture::texture_dir = live_texture_dir;
        CreateDirectoryW(live_texture_dir.c_str(), nullptr);
        // Mesh budget in MB (or KB, for tests); shadow budget for static vertex/index bytes in KB.
        if (const std::wstring budget = env(L"NIER_REMIX_LIVE_BUDGET"); !budget.empty())
            if (const unsigned long long mb = _wcstoui64(budget.c_str(), nullptr, 10)) live_mesh_budget = static_cast<std::size_t>(mb) << 20;
        if (const std::wstring budget = env(L"NIER_REMIX_LIVE_BUDGET_KB"); !budget.empty())
            if (const unsigned long long kb = _wcstoui64(budget.c_str(), nullptr, 10)) live_mesh_budget = static_cast<std::size_t>(kb) << 10;
        if (const std::wstring kb = env(L"NIER_REMIX_LIVE_MAX_WRITE_KB"); !kb.empty())
            live_capture::max_shadow_write = std::min<std::size_t>(std::size_t(_wcstoui64(kb.c_str(), nullptr, 10)), 1u << 24) << 10;
        // 1 = submit every render target (the old behaviour: shadow maps and post passes included), 0 or unset = only
        // the scene target.
        if (const std::wstring all = env(L"NIER_REMIX_LIVE_ALL_TARGETS"); !all.empty())
            live_capture::scene_target_enabled = _wcstoui64(all.c_str(), nullptr, 10) == 0;
        if (const std::wstring kb = env(L"NIER_REMIX_LIVE_READ_BUDGET_KB"); !kb.empty())
            live_capture::read_budget_per_frame = std::min<std::size_t>(std::size_t(_wcstoui64(kb.c_str(), nullptr, 10)), 1u << 24) << 10;
        if (const std::wstring fails = env(L"NIER_REMIX_LIVE_FAIL_VB_READS"); !fails.empty())
            live_capture::fail_vb_reads = static_cast<unsigned>(_wcstoui64(fails.c_str(), nullptr, 10));
        if (const std::wstring frames = env(L"NIER_REMIX_LIVE_EXPIRE_FRAMES"); !frames.empty())
            if (const unsigned long long n = _wcstoui64(frames.c_str(), nullptr, 10))
                live_capture::expire_frames = std::min<unsigned long long>(n, 1000000);  // no wrap in used_frame + expire
        if (const std::wstring budget = env(L"NIER_REMIX_LIVE_SHADOW_KB"); !budget.empty())
            if (const unsigned long long kb = _wcstoui64(budget.c_str(), nullptr, 10)) live_capture::shadow_budget = static_cast<std::size_t>(kb) << 10;
        // NIER_REMIX_LIVE_TEX_PER_FRAME: new textures captured per frame. 0 = none this frame, default 4, clamped to 64.
        // Rollback switches for the live test (analysis/ROADMAP.md): no HUD capture/replay; drop the sky dome again.
        live_capture::hud_enabled = env(L"NIER_REMIX_LIVE_NO_HUD") != L"1";
        live_capture::sky_enabled = env(L"NIER_REMIX_LIVE_NO_SKY") != L"1";
        // Dome fill: a header-valid HDR DDS (NIER_REMIX_SKY_DDS, default nier_sky_hdr.dds beside the scene). Without one
        // the dome adds no light. Strength 2.0 was chosen on the laptop A/B (sky-fill-0.5-vs-2.png).
        sky_path = env(L"NIER_REMIX_SKY_DDS");
        if (sky_path.empty()) sky_path = scene_path.substr(0, scene_path.find_last_of(L"\\/") + 1) + L"nier_sky_hdr.dds";
        if (absolute(sky_path) && GetFileAttributesW(sky_path.c_str()) != INVALID_FILE_ATTRIBUTES) {
            live_options.sky_texture = sky_path.c_str();
            live_options.sky = 2.f;
            if (const std::wstring s = env(L"NIER_REMIX_SKY"); !s.empty()) {
                const float v = std::wcstof(s.c_str(), nullptr);
                if (v >= 0 && v < 1e4f) live_options.sky = v;
            }
            logger.load()("remix: sky dome texture %ls strength %.2f", sky_path.c_str(), live_options.sky);
        }
        if (const std::wstring s = env(L"NIER_REMIX_LIGHT_SCALE"); !s.empty()) {
            const float v = std::wcstof(s.c_str(), nullptr);
            if (v > 0 && v < 1e6f) live_scene::light_scale = v;
        }
        if (const std::wstring n = env(L"NIER_REMIX_LIVE_TEX_PER_FRAME"); !n.empty())
            live_capture::textures_per_frame = std::min<unsigned>(static_cast<unsigned>(_wcstoui64(n.c_str(), nullptr, 10)), 64);
    }
    logger.load()("remix: enabled runtime=%ls scene=%ls", runtime_path.c_str(), scene_path.c_str());
    return State::Waiting;
}

std::vector<unsigned char> read_file(const std::wstring& path) {
    std::vector<unsigned char> bytes;
    if (FILE* f = _wfopen(path.c_str(), L"rb")) {
        unsigned char chunk[1 << 16];
        std::size_t n;
        while ((n = std::fread(chunk, 1, sizeof chunk, f)) > 0) bytes.insert(bytes.end(), chunk, chunk + n);
        std::fclose(f);
    }
    return bytes;
}

// The runtime calls ShowWindow/SetWindowPos on its window (measured: it came up fullscreen and white over the
// player's monitor). Veto every show, move and resize, so it stays hidden at the size it was created with.
std::atomic<int> window_events{0};
void note_window(const char* what, unsigned long a, unsigned long b) {
    if (window_events.fetch_add(1) < 40)  // enough to see who maps it; never floods the log
        if (Log l = logger.load()) l("remix: hidden window %s %lx %lx thread=%lu", what, a, b, GetCurrentThreadId());
}
LRESULT CALLBACK hidden_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_STYLECHANGING && wp == static_cast<WPARAM>(GWL_STYLE)) {
        auto* st = reinterpret_cast<STYLESTRUCT*>(lp);
        note_window("style", st->styleOld, st->styleNew);
        st->styleNew &= ~static_cast<DWORD>(WS_VISIBLE | WS_MAXIMIZE);
        return 0;
    }
    if (msg == WM_WINDOWPOSCHANGING) {
        auto* pos = reinterpret_cast<WINDOWPOS*>(lp);
        note_window("pos", pos->flags, static_cast<unsigned long>(pos->cx) << 16 | static_cast<unsigned long>(pos->cy));
        pos->flags &= ~static_cast<UINT>(SWP_SHOWWINDOW);
        pos->flags |= SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE;
        return 0;
    }
    if (msg == WM_SHOWWINDOW) { note_window("show", static_cast<unsigned long>(wp), static_cast<unsigned long>(lp)); if (wp) return 0; }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// One-time inventory of this process's top-level windows, so a stray visible window can be attributed.
BOOL CALLBACK list_window(HWND hwnd, LPARAM) {
    DWORD pid = 0;
    const DWORD thread = GetWindowThreadProcessId(hwnd, &pid);
    if (pid != GetCurrentProcessId()) return TRUE;
    wchar_t cls[64] = L"", title[64] = L"";
    GetClassNameW(hwnd, cls, 64);
    InternalGetWindowText(hwnd, title, 64);  // GetWindowText would SendMessage to the owner thread and can block forever
    RECT r{};
    GetWindowRect(hwnd, &r);
    logger.load()("remix: window %p class=%ls title=%ls visible=%d rect=%ld,%ld %ldx%ld thread=%lu%s", static_cast<void*>(hwnd), cls,
                  title, IsWindowVisible(hwnd) ? 1 : 0, r.left, r.top, r.right - r.left, r.bottom - r.top, thread,
                  thread == GetCurrentThreadId() ? " (remix worker)" : "");
    return TRUE;
}

// Everything Remix-side lives on this thread.
struct Worker {
    remixapi_Interface api{};
    remixapi_HMODULE module = nullptr;
    HWND window = nullptr;
    IDirect3D9Ex* d3d9 = nullptr;
    IDirect3DDevice9Ex* device = nullptr;
    IDirect3DSurface9* target = nullptr;    // DEFAULT pool: CopyRenderingOutput writes here
    IDirect3DSurface9* readback = nullptr;  // SYSTEMMEM mirror we can lock
    UINT width = 0, height = 0;             // the device's real backbuffer size
    nscn::Scene scene;
    nscn::Built built;
    live_scene::State live;
    // (budget applied in start(): the member is created before configure() runs)
    unsigned live_wait_frames = 0;   // frames since start without a live draw stream
    bool live_reported = false;
    bool shadow_trim_reported = false;
    bool release_reported = false;
    bool injection_reported = false;
    bool big_write_reported = false;
    bool pass_reported = false;
    bool latch_reported = false;
    Frame back;
    unsigned long long seq = 0;
    std::uint64_t camera_sequence = 0;
    bool paused = false;

    D3DPRESENT_PARAMETERS params(UINT w, UINT h) const {
        D3DPRESENT_PARAMETERS pp{};
        pp.BackBufferWidth = w; pp.BackBufferHeight = h; pp.BackBufferFormat = D3DFMT_A8R8G8B8;
        pp.BackBufferCount = 1; pp.SwapEffect = D3DSWAPEFFECT_DISCARD; pp.Windowed = TRUE;
        pp.hDeviceWindow = window; pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
        return pp;
    }

    void release_surfaces() {
        if (target) { target->Release(); target = nullptr; }
        if (readback) { readback->Release(); readback = nullptr; }
    }

    // Size the copy from the device's backbuffer, never from the request (LIVE_TRANSFER.md rule 2).
    bool make_surfaces(UINT asked_w, UINT asked_h) {
        release_surfaces();
        IDirect3DSurface9* bb = nullptr;
        if (FAILED(device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb)) || !bb) { fail("GetBackBuffer"); return false; }
        D3DSURFACE_DESC d{};
        bb->GetDesc(&d);
        bb->Release();
        if (d.Width != asked_w || d.Height != asked_h) {
            logger.load()("remix: device backbuffer %ux%u, asked for %ux%u", d.Width, d.Height, asked_w, asked_h);
            fail("backbuffer size differs from the game's");
            return false;
        }
        width = d.Width; height = d.Height;
        if (FAILED(device->CreateRenderTarget(width, height, D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE, &target, nullptr)) ||
            FAILED(device->CreateOffscreenPlainSurface(width, height, D3DFMT_A8R8G8B8, D3DPOOL_SYSTEMMEM, &readback, nullptr))) {
            fail("copy surfaces");
            return false;
        }
        return true;
    }

    bool start(UINT w, UINT h) {
        stage("scene parse");
        if (!nscn::parse(read_file(scene_path), scene)) { fail("scene file missing or invalid"); return false; }
        stage("runtime load");
        const remixapi_ErrorCode loaded = remixapi_lib_loadRemixDllAndInitialize(runtime_path.c_str(), &api, &module);
        if (loaded) { fail("runtime load", loaded); return false; }
        if (!api.dxvk_CreateD3D9 || !api.dxvk_RegisterD3D9Device || !api.dxvk_CopyRenderingOutput || !api.Startup ||
            !api.Present || !api.CreateMaterial || !api.CreateMesh || !api.CreateLight || !api.SetupCamera ||
            !api.DrawInstance || !api.DrawLightInstance || !api.DestroyMaterial || !api.DestroyMesh || !api.DestroyLight) {
            fail("runtime lacks a required API member");
            return false;
        }
        WNDCLASSW wc{};
        wc.lpfnWndProc = hidden_proc; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"nier-remix-live";
        RegisterClassW(&wc);
        // Hidden: Remix needs a window for its swapchain; the player must never see a second one.
        window = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, wc.lpszClassName, L"nier remix", WS_POPUP, -32000, -32000,
                                 static_cast<int>(w), static_cast<int>(h), nullptr, nullptr, wc.hInstance, nullptr);
        if (!window) { fail("CreateWindow", static_cast<long>(GetLastError())); return false; }
        logger.load()("remix: hidden window %p created on thread %lu", static_cast<void*>(window), GetCurrentThreadId());
        // Order is mandatory (LIVE_TRANSFER.md): our device first, registered, then Startup refuses with ALREADY_EXISTS.
        stage("dxvk_CreateD3D9");
        if (api.dxvk_CreateD3D9(0, &d3d9) || !d3d9) { fail("dxvk_CreateD3D9"); return false; }
        D3DPRESENT_PARAMETERS pp = params(w, h);
        stage("CreateDeviceEx");
        const HRESULT created = d3d9->CreateDeviceEx(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, window,
            D3DCREATE_HARDWARE_VERTEXPROCESSING | D3DCREATE_MULTITHREADED, &pp, nullptr, &device);
        if (FAILED(created) || !device) { fail("CreateDeviceEx", created); return false; }
        stage("RegisterD3D9Device");
        if (const remixapi_ErrorCode r = api.dxvk_RegisterD3D9Device(device)) { fail("dxvk_RegisterD3D9Device", r); return false; }
        remixapi_StartupInfo startup{};
        startup.sType = REMIXAPI_STRUCT_TYPE_STARTUP_INFO;
        startup.hwnd = window;
        startup.combineGuiInFinalColor = 1;
        stage("Startup");
        const remixapi_ErrorCode started = api.Startup(&startup);
        if (started != REMIXAPI_ERROR_CODE_SUCCESS && started != REMIXAPI_ERROR_CODE_ALREADY_EXISTS) { fail("Startup", started); return false; }
        if (!make_surfaces(w, h)) return false;
        const std::wstring stem = scene_path.substr(0, scene_path.rfind(L'.'));
        stage("scene build");
        if (!live_enabled) {  // live mode builds meshes from the game's draws; the file is only a fallback
            const remixapi_ErrorCode b = nscn::build(api, scene, stem + L"_textures\\", nscn::Options{}, built);
            if (b) { fail("scene build", b); return false; }
        }
        logger.load()("remix: started %ux%u startup=%d surfaces=%u sky_skipped=%u untextured=%u live=%d", width, height,
                      static_cast<int>(started), built.surfaces, built.sky_skipped, built.untextured, live_enabled ? 1 : 0);
        live.budget = live_mesh_budget;
        live_capture::set_permitted(live_enabled);
        return true;
    }

    // One Remix frame -> back.pixels in the byte order of `format`.
    bool frame(DXGI_FORMAT format) {
        const auto camera = camera_capture::latest();
        if (camera.sequence != camera_sequence) {
            std::memcpy(scene.camera, camera.camera.data(), sizeof scene.camera);
            if (!camera_sequence)
                logger.load()("remix: live camera first sample seq=%llu pos=%.3f,%.3f,%.3f fov=%.2f",
                              static_cast<unsigned long long>(camera.sequence), camera.camera[0], camera.camera[1],
                              camera.camera[2], camera.camera[12]);
            camera_sequence = camera.sequence;
        }
        const float aspect = static_cast<float>(width) / static_cast<float>(height);
        if (live_enabled) {
            const live_capture::Frame& frame = live_capture::latest();
            std::vector<live_capture::Upload> uploads = live_capture::take_uploads();
            const std::vector<live_capture::TextureFile> textures = live_capture::take_textures();
            if (!big_write_reported && live_capture::skipped_writes.load(std::memory_order_relaxed)) {
                big_write_reported = true;
                logger.load()("remix: live %llu large buffer writes not mirrored on the CPU (re-read when drawn)",
                              live_capture::skipped_writes.load(std::memory_order_relaxed));
            }
            if (!injection_reported && live_capture::injected_failures.load(std::memory_order_relaxed)) {
                injection_reported = true;
                logger.load()("remix: live injected vertex-buffer read failures (test switch NIER_REMIX_LIVE_FAIL_VB_READS)");
            }
            if (!release_reported && live_capture::released.load(std::memory_order_relaxed)) {
                release_reported = true;
                logger.load()("remix: live released %llu stale buffer references (unused for %llu frames)",
                              live_capture::released.load(), static_cast<unsigned long long>(live_capture::expire_frames));
            }
            if (!shadow_trim_reported && live_capture::trims.load(std::memory_order_relaxed)) {
                shadow_trim_reported = true;
                logger.load()("remix: live shadow budget reached (%llu KB); static vertex/index bytes are dropped and re-read only to rebuild",
                              static_cast<unsigned long long>(live_capture::shadow_budget >> 10));
            }
            if (!latch_reported && live_capture::scene_target_latched.load(std::memory_order_acquire)) {
                latch_reported = true;
                logger.load()("remix: live scene target filter latched off after 3 consecutive empty frames; every target is "
                              "submitted from now on (shadow maps and post passes included)");
            }
            if (!pass_reported && frame.skipped_pass) {
                pass_reported = true;
                logger.load()("remix: live scene target %ux%u of %ux%u; %u draws into other targets skipped (shadow maps, post passes)",
                              frame.scene_w, frame.scene_h, live_capture::final_width, live_capture::final_height,
                              frame.skipped_pass);
            }
            if (frame.valid() && frame.sequence != live_sequence) {
                live_sequence = frame.sequence;
                stage("live update");
                if (!live_scene::update(api, std::move(uploads), textures, frame, live, live_options)) { fail("live scene update"); return false; }
                live_capture::forget(live_scene::take_evicted(live));
                if (!live_reported) {
                    live_reported = true;
                    logger.load()("remix: live scene first frame draws=%u meshes=%u instances=%u textures=%u skinned=%u",
                                  frame.draws, live.built, static_cast<unsigned>(frame.transforms.size() / 12),
                                  static_cast<unsigned>(live.texture_paths.size()), frame.skinned);
                }
                if (!live_scene::ready(frame, live)) {  // nothing built yet: keep the previous image
                    stage("live waiting");
                    Sleep(2);
                    return true;
                }
                stage("submit");
                if (const remixapi_ErrorCode r = live_scene::submit(api, frame, live, scene.camera, aspect)) { fail("live submit", r); return false; }
                if (seq % 300 == 1)
                    logger.load()("remix: live draws=%u instances=%u meshes=%u built=%u evicted=%u identical=%u "
                                  "blended=%u untextured=%u textures=%u hud=%u small_viewport=%u scene=%ux%u skipped_pass=%u "
                                  "fallbacks=%u mesh_bytes=%llu dropped=%u lights=%u light_creates=%u sky=%u prepass=%u alpha_tested=%u light_state=0x%x",
                                  frame.draws, static_cast<unsigned>(frame.transforms.size() / 12),
                                  static_cast<unsigned>(live.meshes.size()), live.built, live.evicted, frame.rebuilt_identical,
                                  frame.blended, frame.untextured, static_cast<unsigned>(live.texture_paths.size()),
                                  live_capture::ui_draw_count.load(),
                                  frame.small_viewport, frame.scene_w, frame.scene_h, frame.skipped_pass,
                                  frame.target_fallbacks, static_cast<unsigned long long>(live.bytes),
                                  live_capture::dropped_uploads.load(), static_cast<unsigned>(frame.lights.size()), live.light_creates, frame.sky,
                                  frame.skipped_prepass, frame.alpha_tested, frame.light_state);
                live_wait_frames = 0;
            } else if (!uploads.empty() || !textures.empty()) {
                // Geometry queued while no new frame arrived still has to be built.
                if (!live_scene::update(api, std::move(uploads), textures, frame, live, live_options)) { fail("live scene update"); return false; }
                live_capture::forget(live_scene::take_evicted(live));
                stage("live waiting");
                return true;
            } else {
                // Nothing new this iteration. While live has never produced a frame (menus, loading screens, or every
                // draw filtered out) the game's own image is what must stay on screen. Substituting the captured
                // scene showed a completely different place and hid the menus: the user pressed F10 to get the game
                // back. Showing no Remix at all is the honest state until real draws arrive.
                if (!live_sequence && ++live_wait_frames == 101)
                    logger.load()("remix: no live draws yet after %u frames; showing the game's own image until they arrive",
                                  live_wait_frames);
                stage("live waiting");
                Sleep(2);
                return true;
            }
        } else {
            stage("submit");
            if (const remixapi_ErrorCode r = nscn::submit(api, scene, built, aspect)) { fail("submit", r); return false; }
        }
        stage("present");
        const ULONGLONG t0 = GetTickCount64();
        if (const remixapi_ErrorCode r = api.Present(nullptr)) { fail("Present", r); return false; }
        const ULONGLONG t1 = GetTickCount64();
        stage("copy");
        if (const remixapi_ErrorCode r = api.dxvk_CopyRenderingOutput(target, REMIXAPI_DXVK_COPY_RENDERING_OUTPUT_TYPE_FINAL_COLOR)) {
            fail("CopyRenderingOutput", r);
            return false;
        }
        const ULONGLONG t2 = GetTickCount64();
        stage("readback");
        if (FAILED(device->GetRenderTargetData(target, readback))) { fail("GetRenderTargetData"); return false; }
        D3DLOCKED_RECT locked{};
        stage("lock");
        if (FAILED(readback->LockRect(&locked, nullptr, D3DLOCK_READONLY))) { fail("LockRect"); return false; }
        back.pixels.resize(static_cast<std::size_t>(width) * height * 4);
        const bool swap = rgba(format);  // source is A8R8G8B8 = bytes B,G,R,A
        for (UINT y = 0; y < height; ++y) {
            const unsigned char* s = static_cast<const unsigned char*>(locked.pBits) + static_cast<std::size_t>(y) * locked.Pitch;
            unsigned char* d = &back.pixels[static_cast<std::size_t>(y) * width * 4];
            for (UINT x = 0; x < width; ++x, s += 4, d += 4) {
                d[0] = swap ? s[2] : s[0]; d[1] = s[1]; d[2] = swap ? s[0] : s[2]; d[3] = 255;
            }
        }
        readback->UnlockRect();
        back.width = width; back.height = height; back.format = format; back.seq = ++seq;
        const ULONGLONG t3 = GetTickCount64();
        stage("publish");
        std::lock_guard<std::mutex> lock(published);
        std::swap(back, ready);
        const ULONGLONG t4 = GetTickCount64();
        t_present += t1 - t0; t_copy += t2 - t1; t_readback += t3 - t2; t_publish += t4 - t3; ++t_frames;
        return true;
    }

    // Milliseconds per stage, averaged over the reporting window. GetTickCount64 is 1 ms, which is enough at 200 ms
    // frames and useless below 16 ms; that is fine for finding which stage dominates now.
    ULONGLONG t_submit = 0, t_present = 0, t_copy = 0, t_readback = 0, t_publish = 0, t_frames = 0;

    void run(UINT w, UINT h) {
        if (!start(w, h)) return;
        ULONGLONG window_start = GetTickCount64();
        while (state.load() != State::Failed) {
            const ULONGLONG begun = GetTickCount64();
            stage("messages");
            MSG msg;
            while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
            if (original_view.load()) { stage("original-view"); Sleep(50); continue; }
            UINT gw, gh; DXGI_FORMAT gf;
            { std::lock_guard<std::mutex> lock(published); gw = want_width; gh = want_height; gf = want_format; }
            // Never Reset the Remix device: inside NieR a ResetEx during the game's own resize froze the game once and
            // crashed it once (2026-10-28). A size change after start pauses Remix; the game's frames are shown.
            const bool fits = gw == width && gh == height;
            if (fits != !paused) {
                paused = !fits;
                if (paused) logger.load()("remix: paused (game backbuffer %ux%u, Remix %ux%u); game frames shown", gw, gh, width, height);
                else logger.load()("remix: resumed at %ux%u", width, height);
            }
            if (paused) { stage("paused"); Sleep(50); continue; }
            if (!frame(gf)) return;
            if (seq == 1) { state.store(State::Running); logger.load()("remix: first frame ready"); window_start = GetTickCount64(); }
            if (seq == 1 || seq == 120) {
                RECT r{}; GetWindowRect(window, &r);
                logger.load()("remix: hidden window at frame %llu visible=%d rect=%ld,%ld %ldx%ld", seq, IsWindowVisible(window) ? 1 : 0,
                              r.left, r.top, r.right - r.left, r.bottom - r.top);
                EnumWindows(list_window, 0);
            }
            if (seq % 300 == 1 && seq > 1) {
                const ULONGLONG now = GetTickCount64();
                const ULONGLONG elapsed = now - window_start;
                if (elapsed >= 100 && t_frames) {
                    const double n = static_cast<double>(t_frames);
                    logger.load()("remix: %.1f fps over the last 300 frames (ms/frame: present %.0f, copy %.0f, "
                                  "readback %.0f, publish %.0f, other %.0f)",
                                  300000.0 / static_cast<double>(elapsed), t_present / n, t_copy / n, t_readback / n,
                                  t_publish / n, static_cast<double>(elapsed) / n - (t_present + t_copy + t_readback + t_publish) / n);
                    t_submit = t_present = t_copy = t_readback = t_publish = t_frames = 0;
                    window_start = now;
                }
            }
            const ULONGLONG spent = GetTickCount64() - begun;
            stage("pacing");
            if (spent < 16) Sleep(static_cast<DWORD>(16 - spent));  // never outrun the game's 60 fps cap
        }
    }
};

void worker_main(UINT w, UINT h) {
    // shortcut: the worker and its runtime are never torn down; process exit ends them. Upgrade with live streaming.
    auto* worker = new Worker();
    try { worker->run(w, h); } catch (...) { fail("exception in worker"); }
}
}  // namespace

// NieR drops to a 720x480 window whenever it loses focus. If a window of this process other than the game's (i.e. one
// of Remix's) takes the foreground, give it back; focus moving to another application is the player's choice.
void keep_focus(HWND game, Log log) {
    static HWND last = nullptr;
    static int notes = 0;
    HWND fg = GetForegroundWindow();
    if (fg == last) return;
    last = fg;
    DWORD pid = 0;
    if (fg) GetWindowThreadProcessId(fg, &pid);
    wchar_t cls[64] = L"";
    if (fg) GetClassNameW(fg, cls, 64);
    if (notes < 40) { ++notes; log("remix: focus -> %p class=%ls own_process=%d", static_cast<void*>(fg), cls, pid == GetCurrentProcessId() ? 1 : 0); }
    if (fg && fg != game && pid == GetCurrentProcessId()) {
        SetForegroundWindow(game);
        log("remix: focus returned to the game from %p class=%ls", static_cast<void*>(fg), cls);
        last = GetForegroundWindow();
    }
}

void before_draw(ID3D11DeviceContext* context, UINT index_count) {
    if (state.load() != State::Running || !live_enabled || !live_capture::hud_enabled || original_view.load() ||
        native_hud_composed || native_hud_attempted || !shown.seq || index_count > 256 ||
        !context || context->GetType() != D3D11_DEVICE_CONTEXT_IMMEDIATE) return;
    ID3D11PixelShader* ps = nullptr;
    context->PSGetShader(&ps, nullptr, nullptr);
    // shortcut: keyed by pointer, so a released-and-reused PS address keeps the old verdict; key by bytecode if that bites.
    static std::unordered_map<ID3D11PixelShader*, bool> verdicts;
    auto known = verdicts.find(ps);
    if (known == verdicts.end()) {
        std::vector<unsigned char> code;
        const bool found = shader_capture::lookup(ps, code);
        const bool is_sprite = found && hud_shader::is_sprite(code.data(), code.size());
        if (found) known = verdicts.emplace(ps, is_sprite).first;  // unknown (not yet stored) is retried
        if (!found) { if (ps) ps->Release(); return; }
    }
    const bool sprite = known->second;
    if (ps) ps->Release();
    if (!sprite) return;
    ID3D11RenderTargetView* view = nullptr;
    ID3D11DepthStencilView* depth = nullptr;
    context->OMGetRenderTargets(1, &view, &depth);
    if (depth || !view) { if (depth) depth->Release(); if (view) view->Release(); return; }
    ID3D11Resource* resource = nullptr;
    view->GetResource(&resource);
    view->Release();
    ID3D11Texture2D* raw = nullptr;
    if (resource) { resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&raw)); resource->Release(); }
    const auto release = [](ID3D11Texture2D* p) { if (p) p->Release(); };
    const std::unique_ptr<ID3D11Texture2D, decltype(release)> target(raw, release);
    if (!target) return;
    D3D11_TEXTURE2D_DESC desc{};
    target->GetDesc(&desc);
    if (desc.Format != DXGI_FORMAT_R11G11B10_FLOAT || desc.Width != shown.width || desc.Height != shown.height ||
        desc.SampleDesc.Count != 1) return;  // only the verified full-resolution HUD target, never sprite atlases
    native_hud_attempted = true;
    static ID3D11Texture2D* source = nullptr;
    static ID3D11ShaderResourceView* srv = nullptr;
    static UINT width = 0, height = 0;
    static DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    static unsigned long long uploaded = 0;
    // Worker pixels are already tone-mapped: preserve their byte values, do not sRGB-decode them a second time.
    const DXGI_FORMAT wanted = rgba(shown.format) ? DXGI_FORMAT_R8G8B8A8_UNORM : DXGI_FORMAT_B8G8R8A8_UNORM;
    if (!source || width != shown.width || height != shown.height || format != wanted) {
        ID3D11Device* device = nullptr;
        context->GetDevice(&device);
        if (!device) return;
        D3D11_TEXTURE2D_DESC sd{};
        sd.Width = shown.width; sd.Height = shown.height; sd.MipLevels = 1; sd.ArraySize = 1;
        sd.Format = wanted; sd.SampleDesc.Count = 1; sd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture2D* next = nullptr;
        ID3D11ShaderResourceView* next_view = nullptr;
        const bool ok = SUCCEEDED(device->CreateTexture2D(&sd, nullptr, &next)) &&
                        SUCCEEDED(device->CreateShaderResourceView(next, nullptr, &next_view));
        device->Release();
        if (!ok) { if (next) next->Release(); if (next_view) next_view->Release(); return; }
        if (srv) srv->Release();
        if (source) source->Release();
        source = next; srv = next_view; width = sd.Width; height = sd.Height; format = wanted; uploaded = 0;
    }
    if (uploaded != shown.seq) {
        context->UpdateSubresource(source, 0, nullptr, shown.pixels.data(), shown.width * 4, 0);
        uploaded = shown.seq;
    }
    static hud_replay::Pipeline pipeline;
    live_capture::UiSnapshot quad;
    quad.verts = {{{-1,1,0},{0,0}}, {{-1,-1,0},{0,1}}, {{1,-1,0},{1,1}},
                  {{-1,1,0},{0,0}}, {{1,-1,0},{1,1}}, {{1,1,0},{1,0}}};
    live_capture::UiDraw draw{};
    draw.count = 6;
    draw.world[0] = draw.world[5] = draw.world[10] = 1;
    quad.draws.push_back(draw);
    quad.srvs.push_back(srv);
    native_hud_composed = hud_replay::draw(context, target.get(), quad, pipeline, true);
    // The original DrawIndexed now renders its own sprite, and the game's final compositor remains untouched.
    static bool reported = false;
    if (native_hud_composed && !reported) {
        reported = true;
        D3D11_VIEWPORT vp{}; UINT n = 1;
        context->RSGetViewports(&n, &vp);
        if (Log l = logger.load()) l("remix: native HUD handoff %ux%u before game sprites target=%ux%u viewport=%.0f,%.0f %.0fx%.0f",
                                     width, height, desc.Width, desc.Height, vp.TopLeftX, vp.TopLeftY, vp.Width, vp.Height);
    }
}

void on_present(IDXGISwapChain* swapchain, Log log) {
    State s = state.load();
    if (s == State::Off || s == State::Failed) return;
    if (s == State::Unchecked) {
        logger.store(log);
        s = configure();
        state.store(s);
        camera_capture::set_enabled(s == State::Waiting);
        if (s != State::Waiting) return;
    }
    presents.fetch_add(1);
    last_present.store(GetTickCount64());
    hook_stage.store("GetBuffer");
    ID3D11Texture2D* buffer = nullptr;
    if (FAILED(swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&buffer))) || !buffer) return;
    D3D11_TEXTURE2D_DESC desc{};
    buffer->GetDesc(&desc);
    if (!rgba(desc.Format) && !bgra(desc.Format)) {
        buffer->Release();
        fail("unsupported backbuffer format", desc.Format);
        return;
    }
    // NieR runs its intro at 720x480 and only later sizes the swapchain to the display; resetting a live Remix device
    // froze/crashed it (2026-10-28). So Remix starts once, at the size of the monitor the game window is on, and the
    // worker pauses (game frames shown) whenever the backbuffer differs. shortcut: a game resolution other than the
    // monitor's keeps Remix paused; add an NIER_REMIX_SIZE override if that is ever wanted.
    static bool worker_started = false;
    UINT start_w = 0, start_h = 0;
    if (!worker_started) {
        DXGI_SWAP_CHAIN_DESC sd{};
        MONITORINFO mi{};
        mi.cbSize = sizeof mi;
        if (FAILED(swapchain->GetDesc(&sd)) || !GetMonitorInfoW(MonitorFromWindow(sd.OutputWindow, MONITOR_DEFAULTTONEAREST), &mi)) {
            buffer->Release();
            fail("monitor size unavailable");
            return;
        }
        start_w = static_cast<UINT>(mi.rcMonitor.right - mi.rcMonitor.left);
        start_h = static_cast<UINT>(mi.rcMonitor.bottom - mi.rcMonitor.top);
        worker_started = true;
    }
    const bool start = start_w != 0;
    hook_stage.store("focus");
    {
        DXGI_SWAP_CHAIN_DESC sd{};
        if (SUCCEEDED(swapchain->GetDesc(&sd)) && sd.OutputWindow) {
            keep_focus(sd.OutputWindow, log);
            static bool f10_was = false;
            const bool pressed = GetForegroundWindow() == sd.OutputWindow && (GetAsyncKeyState(VK_F10) & 0x8000);
            if (pressed && !f10_was) {
                const bool bypass = !original_view.load();
                original_view.store(bypass);
                if (live_enabled) live_capture::set_suspended(bypass);  // no shadowing behind the original view
                log("remix: F10 original-game view %s", bypass ? "on (capture suspended)" : "off (capture resumed)");
            }
            f10_was = pressed;
        }
    }
    hook_stage.store("frame lock");
    {
        std::lock_guard<std::mutex> lock(published);
        want_width = desc.Width; want_height = desc.Height; want_format = desc.Format;
        if (ready.seq != shown.seq) std::swap(ready, shown);
    }
    if (start) {
        log("remix: starting at monitor size %ux%u (game backbuffer %ux%u format=%d)", start_w, start_h, desc.Width, desc.Height,
            static_cast<int>(desc.Format));
        stage("starting");
        std::thread(worker_main, start_w, start_h).detach();
        std::thread(watchdog).detach();
    }
    // A frame rendered for another size or byte order is stale (resize in flight): show the game's frame.
    if (!original_view.load() && shown.seq && shown.width == desc.Width && shown.height == desc.Height && shown.format == desc.Format) {
        ID3D11Device* device = nullptr;
        buffer->GetDevice(&device);
        ID3D11DeviceContext* context = nullptr;
        device->GetImmediateContext(&context);
        if (!native_hud_composed) {
        hook_stage.store("UpdateSubresource");
        context->UpdateSubresource(buffer, 0, nullptr, shown.pixels.data(), desc.Width * 4, 0);
        if (live_enabled && live_capture::hud_enabled) {
            // The game's HUD goes back on top of the path-traced image; state is saved and restored inside.
            static hud_replay::Pipeline hud_pipeline;
            hook_stage.store("hud replay");
            const bool hud_ok = hud_replay::draw(context, buffer, live_capture::ui_ready(), hud_pipeline);
            static bool hud_logged = false;
            // Once, for the first frame that carried a HUD: the first composites happen before the HUD exists.
            if (!hud_logged && (!live_capture::ui_ready().draws.empty() || !hud_ok)) {
                hud_logged = true;
                const auto& ui = live_capture::ui_ready();
                log("remix: hud replay draws=%u verts=%u srvs=%u ok=%d failed=%d",
                    static_cast<unsigned>(ui.draws.size()), static_cast<unsigned>(ui.verts.size()),
                    static_cast<unsigned>(ui.srvs.size()), hud_ok ? 1 : 0, hud_pipeline.failed ? 1 : 0);
            }
        }
        }
        // Test switch: write what actually reached the screen, once. The .raw captures elsewhere are taken before our
        // composite, so they cannot prove the HUD survived it.
        if (const std::wstring capture = env(L"NIER_REMIX_CAPTURE_COMPOSITE"); !capture.empty()) {
            static bool written = false;
            // Capture a frame that actually carried a HUD: the first composites happen before the HUD exists.
            const bool native_only = env(L"NIER_REMIX_CAPTURE_NATIVE_ONLY") == L"1";
            if (!written && (native_only ? native_hud_composed : (native_hud_composed || live_capture::ui_draw_count.load() > 0))) {
                written = true;
                D3D11_TEXTURE2D_DESC sd = desc;
                sd.Usage = D3D11_USAGE_STAGING;
                sd.BindFlags = 0;
                sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
                sd.MiscFlags = 0;
                ID3D11Texture2D* staging = nullptr;
                if (SUCCEEDED(device->CreateTexture2D(&sd, nullptr, &staging)) && staging) {
                    context->CopyResource(staging, buffer);
                    D3D11_MAPPED_SUBRESOURCE m{};
                    if (SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &m))) {
                        if (FILE* f = _wfopen(capture.c_str(), L"wb")) {
                            for (UINT y = 0; y < desc.Height; ++y)
                                std::fwrite(static_cast<const unsigned char*>(m.pData) + std::size_t(y) * m.RowPitch,
                                            desc.Width * 4, 1, f);
                            std::fclose(f);
                        }
                        context->Unmap(staging, 0);
                    }
                    staging->Release();
                }
            }
        }
        context->Release();
        device->Release();
        static bool reported = false;
        if (!reported) { reported = true; log("remix: composited first frame %ux%u", desc.Width, desc.Height); }
    }
    buffer->Release();
    hook_stage.store("returned to game");
}
void begin_game_frame(IDXGISwapChain* swapchain) {
    native_hud_composed = native_hud_attempted = false;
    const State current = state.load();
    if ((current != State::Waiting && current != State::Running) || original_view.load()) return;
    ID3D11Texture2D* buffer = nullptr;
    const HRESULT hr = swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&buffer));
    if (FAILED(hr) || !buffer) { if (buffer) buffer->Release(); return; }
    D3D11_TEXTURE2D_DESC desc{};
    buffer->GetDesc(&desc);
    ID3D11Device* device = nullptr;
    buffer->GetDevice(&device);
    buffer->Release();
    if (!device) return;
    ID3D11DeviceContext* raw_context = nullptr;
    device->GetImmediateContext(&raw_context);
    device->Release();
    const auto release = [](ID3D11DeviceContext* p) { if (p) p->Release(); };
    const std::unique_ptr<ID3D11DeviceContext, decltype(release)> context(raw_context, release);
    camera_capture::begin_frame(context.get(), desc.Height ? static_cast<float>(desc.Width) / desc.Height : 0.f);
    if (live_enabled) {
        // Hooks only for a live session: with Remix or live capture off, the game's Map/Unmap/Copy calls stay untouched.
        live_capture::install(context.get());
        live_capture::begin_frame(context.get(), desc.Width, desc.Height);
    }
}
}  // namespace remix_live
