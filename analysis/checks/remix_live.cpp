#include "remix_live.h"
#include <windows.h>
#include <d3d9.h>
#include <d3d11.h>
#include <atomic>
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <remix_c.h>
#include "nscn_scene.h"

namespace remix_live {
namespace {
using Log = void (*)(const char*, ...);

enum class State { Unchecked, Off, Waiting, Running, Failed };
std::atomic<State> state{State::Unchecked};
std::atomic<Log> logger{nullptr};
std::wstring runtime_path, scene_path;

struct Frame { std::vector<unsigned char> pixels; UINT width = 0, height = 0; DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN; unsigned long long seq = 0; };
// Guarded by `published`: the newest finished frame, and what the game currently presents.
std::mutex published;
Frame ready;
UINT want_width = 0, want_height = 0;
DXGI_FORMAT want_format = DXGI_FORMAT_UNKNOWN;
Frame shown;  // presenting thread only

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
    Frame back;
    unsigned long long seq = 0;
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
        const remixapi_ErrorCode b = nscn::build(api, scene, stem + L"_textures\\", nscn::Options{}, built);
        if (b) { fail("scene build", b); return false; }
        logger.load()("remix: started %ux%u startup=%d surfaces=%u sky_skipped=%u untextured=%u", width, height,
                      static_cast<int>(started), built.surfaces, built.sky_skipped, built.untextured);
        return true;
    }

    // One Remix frame -> back.pixels in the byte order of `format`.
    bool frame(DXGI_FORMAT format) {
        stage("submit");
        if (const remixapi_ErrorCode r = nscn::submit(api, scene, built, static_cast<float>(width) / static_cast<float>(height))) { fail("submit", r); return false; }
        stage("present");
        if (const remixapi_ErrorCode r = api.Present(nullptr)) { fail("Present", r); return false; }
        stage("copy");
        if (const remixapi_ErrorCode r = api.dxvk_CopyRenderingOutput(target, REMIXAPI_DXVK_COPY_RENDERING_OUTPUT_TYPE_FINAL_COLOR)) {
            fail("CopyRenderingOutput", r);
            return false;
        }
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
        stage("publish");
        std::lock_guard<std::mutex> lock(published);
        std::swap(back, ready);
        return true;
    }

    void run(UINT w, UINT h) {
        if (!start(w, h)) return;
        ULONGLONG window_start = GetTickCount64();
        while (state.load() != State::Failed) {
            const ULONGLONG begun = GetTickCount64();
            stage("messages");
            MSG msg;
            while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
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
                logger.load()("remix: %.1f fps over the last 300 frames", 300000.0 / static_cast<double>(now - window_start + 1));
                window_start = now;
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

void on_present(IDXGISwapChain* swapchain, Log log) {
    State s = state.load();
    if (s == State::Off || s == State::Failed) return;
    if (s == State::Unchecked) {
        logger.store(log);
        s = configure();
        state.store(s);
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
        if (SUCCEEDED(swapchain->GetDesc(&sd)) && sd.OutputWindow) keep_focus(sd.OutputWindow, log);
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
    if (shown.seq && shown.width == desc.Width && shown.height == desc.Height && shown.format == desc.Format) {
        ID3D11Device* device = nullptr;
        buffer->GetDevice(&device);
        ID3D11DeviceContext* context = nullptr;
        device->GetImmediateContext(&context);
        hook_stage.store("UpdateSubresource");
        context->UpdateSubresource(buffer, 0, nullptr, shown.pixels.data(), desc.Width * 4, 0);
        context->Release();
        device->Release();
        static bool reported = false;
        if (!reported) { reported = true; log("remix: composited first frame %ux%u", desc.Width, desc.Height); }
    }
    buffer->Release();
    hook_stage.store("returned to game");
}
}  // namespace remix_live
