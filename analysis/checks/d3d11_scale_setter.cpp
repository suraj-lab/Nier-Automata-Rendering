// Outer d3d11.dll: chainloads NIER_DLAA (d3d11_dlaa.dll), reads startup render settings,
// and installs the validated depth/upscale patches only for reduced rendering.
// Build: see analysis/SCALE_SETTER.md. Exports: d3d11_log_proxy.def (49 forwarders + 2 wrappers).
#include <windows.h>
#include <d3d11.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <string>
#include "scale_patch.h"
#include "depth_patch.h"
#include "proxy_patch.h"
#include "redirect_logic.h"
#include "render_settings.h"
#include "startup_status.h"
#include "menu_overlay.h"
static constexpr int kPollMs = 250, kPollTries = 480;  // ~120 s for the renderer to appear

typedef HRESULT (WINAPI *PFN_CreateDevice)(IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT,
    const D3D_FEATURE_LEVEL*, UINT, UINT, ID3D11Device**, D3D_FEATURE_LEVEL*, ID3D11DeviceContext**);
typedef HRESULT (WINAPI *PFN_CreateDeviceAndSwapChain)(IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT,
    const D3D_FEATURE_LEVEL*, UINT, UINT, const DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**, ID3D11Device**,
    D3D_FEATURE_LEVEL*, ID3D11DeviceContext**);

static PFN_CreateDevice real_CreateDevice = nullptr;
static PFN_CreateDeviceAndSwapChain real_CreateDeviceAndSwapChain = nullptr;
static std::wstring module_dir;
static volatile LONG setter_started = 0;
static startup_status::Publication startup_observation;
static HMODULE proxy_module = nullptr;
static std::uint8_t* proxy_cave = nullptr;
static redirect_logic::State redirect_state;
static ID3D11Texture2D* out_tex = nullptr;
static ID3D11ShaderResourceView* out_srv = nullptr;

static void logf_line(const char* fmt, ...)
{
    static FILE* file = module_dir.empty() ? nullptr : _wfopen((module_dir + L"NIER_SCALE.log").c_str(), L"a");
    if (!file) return;
    SYSTEMTIME t; GetLocalTime(&t);
    fprintf(file, "%02u:%02u:%02u.%03u pid=%lu ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds,
        static_cast<unsigned long>(GetCurrentProcessId()));
    va_list ap; va_start(ap, fmt); vfprintf(file, fmt, ap); va_end(ap);
    fputc('\n', file); fflush(file);
}

static bool readable(const void* p, std::size_t n)
{
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(p, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    if (!(mbi.Protect & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))) return false;
    return static_cast<const char*>(p) + n <= static_cast<const char*>(mbi.BaseAddress) + mbi.RegionSize;
}

// Allocate an executable cave within +-2 GB of the image (so the E9 rel32 jump reaches).
static void* alloc_cave_near(const void* image, std::size_t size)
{
    const std::uintptr_t img = reinterpret_cast<std::uintptr_t>(image);
    const std::uintptr_t deltas[] = {
        0x02000000ULL, 0x03000000ULL, 0x04000000ULL, 0x05000000ULL,
        0x06000000ULL, 0x07000000ULL, 0x08000000ULL, 0x09000000ULL,
    };
    for (auto d : deltas) {
        void* p = VirtualAlloc(reinterpret_cast<void*>(img + d), size,
                               MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
        if (p) return p;
    }
    for (auto d : deltas) {
        void* p = VirtualAlloc(reinterpret_cast<void*>(img - d), size,
                               MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
        if (p) return p;
    }
    return nullptr;
}

static depth_patch::Result apply_depth_patch(unsigned char* image, std::size_t size)
{
    if (!depth_patch::check_signatures(image, size))
        return depth_patch::Result::SigMismatch;

    void* cave = alloc_cave_near(image, depth_patch::kCaveSize);
    if (!cave) { logf_line("depth patch: no cave memory"); return depth_patch::Result::NoMemory; }

    const std::uint64_t cave_va = reinterpret_cast<std::uint64_t>(cave);
    const std::uint64_t image_va = reinterpret_cast<std::uint64_t>(image);
    const std::uint64_t renderer_va = image_va + depth_patch::kRendererRva;
    const std::uint64_t patch_va = image_va + depth_patch::kPatchRva;
    const std::uint64_t return_va = image_va + depth_patch::kReturnRva;

    std::uint8_t cave_bytes[depth_patch::kCaveSize];
    const std::size_t n = depth_patch::emit_cave(cave_bytes, sizeof(cave_bytes), cave_va, renderer_va, return_va);
    if (n == 0) return depth_patch::Result::BadRange;
    std::memcpy(cave, cave_bytes, n);

    std::uint8_t jmp[6] = { 0 };
    depth_patch::emit_jump(jmp, patch_va, cave_va);
    jmp[5] = 0x90;

    DWORD old = 0;
    if (!VirtualProtect(reinterpret_cast<void*>(patch_va), 6, PAGE_EXECUTE_READWRITE, &old)) {
        logf_line("depth patch: VirtualProtect failed err=%lu", GetLastError());
        return depth_patch::Result::NoMemory;
    }
    std::uint8_t* p = reinterpret_cast<std::uint8_t*>(patch_va);
    std::memcpy(p + 1, jmp + 1, 4);   // rel32 tail first
    p[5] = jmp[5];                     // dead byte (0x90)
    p[0] = jmp[0];                     // 0xE9 opcode last: jump goes live only on this atomic store
    FlushInstructionCache(GetCurrentProcess(), p, 6);
    DWORD ignore = 0;
    VirtualProtect(reinterpret_cast<void*>(patch_va), 6, old, &ignore);

    logf_line("depth patch: applied cave=%p patch=%p (cave %zu bytes)", cave, reinterpret_cast<void*>(patch_va), n);
    return depth_patch::Result::Applied;
}

// Part 3: called from the proxy's dispatch-function exit hook (cave, MS x64 ABI). Rebinds
// PS SRV slot 0 to the FSR Output for the draw that follows, so the scene is consumed
// natively and the size-invalid copy-back can be skipped.
static void on_dispatch_exit(ID3D11DeviceContext* ctx)
{
    auto* base = reinterpret_cast<unsigned char*>(proxy_module);
    if (!base) return;

    // Cheap early-outs before any COM call.
    ID3D11DeviceContext* imm = *reinterpret_cast<ID3D11DeviceContext* volatile*>(base + proxy_patch::kImmediateCtxRva);
    if (imm != ctx) return;
    const std::uint32_t cur = *reinterpret_cast<std::uint32_t volatile*>(base + proxy_patch::kCurFrameRva);
    const std::uint32_t disp = *reinterpret_cast<std::uint32_t volatile*>(base + proxy_patch::kDispatchFrameRva);
    if (cur != disp) return;
    ID3D11Texture2D* out = *reinterpret_cast<ID3D11Texture2D* volatile*>(base + proxy_patch::kOutputTexRva);
    if (!out) return;

    ID3D11ShaderResourceView* srv = nullptr;
    ctx->PSGetShaderResources(0, 1, &srv);
    if (!srv) return;
    ID3D11Resource* res = nullptr;
    srv->GetResource(&res);
    srv->Release();
    if (res) res->Release();

    if (!redirect_logic::should_redirect(redirect_state, true, cur, disp, res, out)) return;

    // (Re)create on a new Output texture, and retry while a previous attempt left no SRV.
    if (out_tex != out || !out_srv) {
        if (out_srv) { out_srv->Release(); out_srv = nullptr; }
        out_tex = out;
        ID3D11Device* dev = nullptr;
        ctx->GetDevice(&dev);
        if (dev) {
            ID3D11ShaderResourceView* view = nullptr;
            const HRESULT hr = dev->CreateShaderResourceView(out, nullptr, &view);
            dev->Release();
            if (SUCCEEDED(hr)) out_srv = view;
            else if (view) view->Release();  // don't trust the out-param on failure
            static int create_logs = 0;  // a persistent failure retries every frame; cap the log
            if (SUCCEEDED(hr) || create_logs < 5) {
                if (!SUCCEEDED(hr)) ++create_logs;
                logf_line("part3 redirect: output SRV %p for tex %p hr=0x%08lx", out_srv, out,
                    static_cast<unsigned long>(hr));
            }
        }
    }

    if (!out_srv) {
        // The cave always skips the copy-back, so this frame shows the un-upscaled scene.
        static int skip_logs = 0;
        if (skip_logs < 5) {
            ++skip_logs;
            logf_line("part3 redirect: no Output SRV, copy-back skipped without redirect frame=%u", cur);
        }
    } else {
        ctx->PSSetShaderResources(0, 1, &out_srv);
        static bool first = true;
        if (first) {
            first = false;
            logf_line("part3 redirect: first slot-0 redirect frame=%u", cur);
        }
    }
}

static proxy_patch::Result apply_proxy_patch()
{
    auto* image = reinterpret_cast<unsigned char*>(proxy_module);
    if (!image) return proxy_patch::Result::BadImage;
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
    const std::size_t size = nt->OptionalHeader.SizeOfImage;

    if (!proxy_patch::check_signatures(image, size))
        return proxy_patch::Result::SigMismatch;

    void* cave = alloc_cave_near(image, proxy_patch::kCaveSize);
    if (!cave) { logf_line("proxy patch: no cave memory"); return proxy_patch::Result::NoMemory; }

    const std::uint64_t cave_va = reinterpret_cast<std::uint64_t>(cave);
    const std::uint64_t image_va = reinterpret_cast<std::uint64_t>(image);

    std::uint8_t cave_bytes[proxy_patch::kCaveSize];
    const std::size_t n = proxy_patch::emit_cave(cave_bytes, sizeof(cave_bytes), cave_va, image_va,
        reinterpret_cast<std::uint64_t>(&on_dispatch_exit));
    if (n != proxy_patch::kCaveSize) {
        logf_line("proxy patch: cave emit failed");
        VirtualFree(cave, 0, MEM_RELEASE);
        return proxy_patch::Result::BadRange;
    }
    std::memcpy(cave, cave_bytes, n);
    if (!FlushInstructionCache(GetCurrentProcess(), cave, n)) {
        logf_line("proxy patch: cave cache flush failed err=%lu", GetLastError());
        VirtualFree(cave, 0, MEM_RELEASE);
        return proxy_patch::Result::NoMemory;
    }

    constexpr std::size_t count = sizeof(proxy_patch::kSites) / sizeof(proxy_patch::kSites[0]);
    DWORD prior[count] = {};
    std::uint8_t original[count][10] = {};
    // Pages overlap between sites: restore protections in reverse acquisition order.
    const auto restore_pages = [&](std::size_t prepared) {
        bool ok = true;
        while (prepared) {
            const auto i = --prepared;
            const auto& p = proxy_patch::kSites[i];
            DWORD ignore = 0;
            if (!VirtualProtect(image + p.rva, p.len, prior[i], &ignore)) {
                logf_line("proxy patch: protection restore failed at %p err=%lu", image + p.rva, GetLastError());
                ok = false;
            }
        }
        return ok;
    };
    // No code changes until every site's protection has been acquired successfully.
    for (std::size_t i = 0; i < count; ++i) {
        const auto& p = proxy_patch::kSites[i];
        std::memcpy(original[i], image + p.rva, p.len);
        if (!VirtualProtect(image + p.rva, p.len, PAGE_EXECUTE_READWRITE, &prior[i])) {
            logf_line("proxy patch: prepare failed at %p err=%lu; no code written", image + p.rva, GetLastError());
            if (!restore_pages(i) && !restore_pages(i))
                logf_line("proxy patch: page cleanup failed twice; restart required");
            VirtualFree(cave, 0, MEM_RELEASE);
            return proxy_patch::Result::NoMemory;
        }
    }
    const auto rollback = [&] {
        bool ok = true;
        for (std::size_t i = count; i-- > 0;) {
            const auto& p = proxy_patch::kSites[i];
            std::memcpy(image + p.rva + 1, original[i] + 1, p.len - 1);
            image[p.rva] = original[i][0];
            if (!FlushInstructionCache(GetCurrentProcess(), image + p.rva, p.len)) ok = false;
        }
        if (!ok) logf_line("proxy patch: rollback cache flush failed; restart required");
        return ok;
    };
    bool committed = true;
    // shortcut: startup-only patching, suspend/coordinate threads before any future hot reload.
    for (const auto& p : proxy_patch::kSites) {
        const std::uint64_t patch_va = image_va + p.rva;
        std::uint8_t jmp[10] = { 0 };
        proxy_patch::emit_jump(jmp, patch_va, cave_va + p.cave_off);
        std::uint8_t* pd = image + p.rva;
        std::memcpy(pd + 1, jmp + 1, 4);
        std::memset(pd + 5, 0x90, p.len - 5);
        pd[0] = jmp[0];
        if (!FlushInstructionCache(GetCurrentProcess(), pd, p.len)) {
            logf_line("proxy patch: code cache flush failed at %p err=%lu", pd, GetLastError());
            rollback();
            committed = false;
            break;
        }
    }
    bool restored = restore_pages(count);
    if (!restored) {
        // Reacquire all pages before undoing code; some protections were already restored.
        bool writable = true;
        for (const auto& p : proxy_patch::kSites) {
            DWORD ignore = 0;
            if (!VirtualProtect(image + p.rva, p.len, PAGE_EXECUTE_READWRITE, &ignore)) writable = false;
        }
        if (writable) rollback();
        else logf_line("proxy patch: rollback could not acquire pages; restart required");
        restored = restore_pages(count);
        committed = false;
    }
    // Retain the cave after publishing any jumps: another thread may still be executing it.
    if (!committed || !restored) return proxy_patch::Result::NoMemory;

    proxy_cave = static_cast<std::uint8_t*>(cave);
    logf_line("proxy patch: applied cave=%p (%zu patches, cave %zu bytes)", cave,
        sizeof(proxy_patch::kSites) / sizeof(proxy_patch::kSites[0]), n);
    return proxy_patch::Result::Applied;
}

static render_settings::Settings read_render_settings(const std::wstring& path)
{
    using render_settings::ReadState;
    const DWORD attrs = GetFileAttributesW(path.c_str());
    if (attrs == INVALID_FILE_ATTRIBUTES) {
        const DWORD error = GetLastError();
        return render_settings::select(error == ERROR_FILE_NOT_FOUND ? ReadState::Missing : ReadState::Unreadable, L"");
    }
    if (attrs & FILE_ATTRIBUTE_DIRECTORY) return render_settings::select(ReadState::Unreadable, L"");
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return render_settings::select(ReadState::Unreadable, L"");
    wchar_t value[128] = {};
    const DWORD length = GetPrivateProfileStringW(L"Rendering", L"Preset", L"", value, 128, path.c_str());
    CloseHandle(file);
    if (length >= 127) return render_settings::select(ReadState::Unreadable, L"");
    return render_settings::select(ReadState::Value, std::wstring_view(value, length));
}

static render_settings::Settings load_render_settings()
{
    return read_render_settings(module_dir + L"NIER_RENDER.ini");
}

static DWORD WINAPI setter_thread(void*)
{
    const auto settings = load_render_settings();
    startup_status::Snapshot observed;
    observed.settings_observed = true;
    observed.settings = settings;
    const auto publish = [&](startup_status::Outcome outcome, startup_status::Failure failure, std::int32_t detail = 0) {
        observed.outcome = outcome;
        observed.failure = failure;
        observed.detail = detail;
        startup_observation.publish(observed);
    };
    const float kScale = render_settings::scale(settings.mode);
    logf_line("render settings: Preset=%ls scale=%.3f valid=%d defaulted=%d (startup only)",
              render_settings::name(settings.mode).data(), kScale, settings.valid, settings.defaulted);
    if (settings.mode == render_settings::Mode::Native) {
        logf_line("native mode: no depth/proxy patches or scale write%s",
                  settings.valid ? "" : " (invalid/unreadable config)");
        publish(startup_status::Outcome::NativeBypass, settings.valid ? startup_status::Failure::None : startup_status::Failure::InvalidConfig);
        return 0;
    }
    auto* image = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
    const std::size_t size = nt->OptionalHeader.SizeOfImage;
    logf_line("setter start exe_base=%p size_of_image=0x%zx target_scale=%.3f", static_cast<void*>(image), size, kScale);

    // Depth code-cave patch first (before target creation reads the scale).
    depth_patch::Result dr = depth_patch::Result::SigMismatch;
    for (int i = 0; i < 8 && dr == depth_patch::Result::SigMismatch; ++i) {
        dr = apply_depth_patch(image, size);
        if (dr == depth_patch::Result::SigMismatch) Sleep(100);
    }
    logf_line("depth patch result: %s", depth_patch::name(dr));

    if (dr != depth_patch::Result::Applied) {
        logf_line("depth patch failed (%s): NOT scaling to avoid the black scene", depth_patch::name(dr));
        publish(startup_status::Outcome::NotApplied, startup_status::Failure::Depth, static_cast<std::int32_t>(dr));
        return 0;
    }

    // Reduced rendering is allowed only after every required proxy patch succeeds.
    proxy_patch::Result pr = apply_proxy_patch();
    logf_line("proxy patch result: %s", proxy_patch::name(pr));
    if (pr != proxy_patch::Result::Applied) {
        logf_line("proxy patch failed: NOT scaling; inspect errors above");
        publish(startup_status::Outcome::NotApplied, startup_status::Failure::Proxy, static_cast<std::int32_t>(pr));
        return 0;
    }

    scale_patch::Result r = scale_patch::Result::NoRenderer, first = r;
    scale_patch::Info info;
    for (int i = 0; i < kPollTries; ++i) {
        r = scale_patch::try_apply(image, size, kScale, readable, &info);
        if (i == 0) first = r;
        if (i == 0 && scale_patch::retryable(r)) logf_line("waiting: %s", scale_patch::name(r));
        if (!scale_patch::retryable(r)) break;
        Sleep(kPollMs);
    }
    if (r == scale_patch::Result::Applied)
        logf_line("applied renderer=%p screen=%ux%u scale %.3f -> %.3f (scaled targets %ux%u after resolution re-apply)",
            info.renderer, info.width, info.height, info.before, kScale,
            static_cast<unsigned>(info.width * kScale), static_cast<unsigned>(info.height * kScale));
    else
        logf_line("no write: %s (first=%s) renderer=%p screen=%ux%u scale=%.3f", scale_patch::name(r),
            scale_patch::name(first), info.renderer, info.width, info.height, info.before);

    bool gate_ready = false;
    if (r == scale_patch::Result::Applied && pr == proxy_patch::Result::Applied && proxy_cave) {
        std::memcpy(proxy_cave + proxy_patch::kScaleOff, &kScale, sizeof(kScale));
        gate_ready = true;
        logf_line("proxy gate scale set to %.3f", kScale);
    }
    if (r == scale_patch::Result::Applied)
        publish(gate_ready ? startup_status::Outcome::Custom75Applied : startup_status::Outcome::Incomplete,
                gate_ready ? startup_status::Failure::None : startup_status::Failure::MissingGate);
    else
        publish(startup_status::Outcome::NotApplied, startup_status::Failure::Renderer, static_cast<std::int32_t>(r));
    return 0;
}

static void start_setter_once()
{
    if (InterlockedCompareExchange(&setter_started, 1, 0) != 0) return;
    HANDLE h = CreateThread(nullptr, 0, setter_thread, nullptr, 0, nullptr);
    if (h) CloseHandle(h);
    else {
        const DWORD error = GetLastError();
        startup_status::Snapshot observed;
        observed.detail = static_cast<std::int32_t>(error);
        startup_observation.publish(observed);
        logf_line("CreateThread failed err=%lu", static_cast<unsigned long>(error));
    }
}

static bool load_real()
{
    static const bool ready = [] {
        HMODULE self = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                reinterpret_cast<LPCWSTR>(&load_real), &self)) return false;
        wchar_t path[32768];
        const DWORD length = GetModuleFileNameW(self, path, 32768);
        if (!length || length >= 32768) return false;
        wchar_t* filename = wcsrchr(path, L'\\');
        if (!filename) return false;
        module_dir.assign(path, filename + 1);
        const std::wstring next = module_dir + L"d3d11_dlaa.dll";
        HMODULE real = LoadLibraryExW(next.c_str(), nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!real || real == self) { logf_line("cannot load d3d11_dlaa.dll err=%lu; no system fallback", GetLastError()); return false; }
        proxy_module = real;
        FARPROC create = GetProcAddress(real, "D3D11CreateDevice");
        FARPROC swap = GetProcAddress(real, "D3D11CreateDeviceAndSwapChain");
        std::memcpy(&real_CreateDevice, &create, sizeof(create));
        std::memcpy(&real_CreateDeviceAndSwapChain, &swap, sizeof(swap));
        logf_line("next-stage module=%p exports_ready=%d", static_cast<void*>(real), create && swap);
        return create && swap;
    }();
    return ready;
}

static void install_menu(ID3D11Device* device, IDXGISwapChain* swapchain)
{
    menu_overlay::install(device, swapchain, {module_dir, read_render_settings, &startup_observation, logf_line});
}

extern "C" HRESULT WINAPI D3D11CreateDevice(IDXGIAdapter* adapter, D3D_DRIVER_TYPE type, HMODULE sw,
    UINT flags, const D3D_FEATURE_LEVEL* levels, UINT nlevels, UINT sdk, ID3D11Device** outdev,
    D3D_FEATURE_LEVEL* outfl, ID3D11DeviceContext** outctx)
{
    if (!load_real()) return E_FAIL;
    const HRESULT hr = real_CreateDevice(adapter, type, sw, flags, levels, nlevels, sdk, outdev, outfl, outctx);
    const DWORD error = GetLastError();
    if (SUCCEEDED(hr)) start_setter_once();
    if (SUCCEEDED(hr) && outdev) install_menu(*outdev, nullptr);
    SetLastError(error);
    return hr;
}

extern "C" HRESULT WINAPI D3D11CreateDeviceAndSwapChain(IDXGIAdapter* adapter, D3D_DRIVER_TYPE type,
    HMODULE sw, UINT flags, const D3D_FEATURE_LEVEL* levels, UINT nlevels, UINT sdk,
    const DXGI_SWAP_CHAIN_DESC* sd, IDXGISwapChain** outsc, ID3D11Device** outdev,
    D3D_FEATURE_LEVEL* outfl, ID3D11DeviceContext** outctx)
{
    if (!load_real()) return E_FAIL;
    const HRESULT hr = real_CreateDeviceAndSwapChain(adapter, type, sw, flags, levels, nlevels, sdk, sd, outsc,
        outdev, outfl, outctx);
    const DWORD error = GetLastError();
    if (SUCCEEDED(hr)) start_setter_once();
    if (SUCCEEDED(hr) && outdev) install_menu(*outdev, outsc ? *outsc : nullptr);
    SetLastError(error);
    return hr;
}
