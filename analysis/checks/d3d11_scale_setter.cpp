// Outer d3d11.dll: chainloads renamed NIER_DLAA (d3d11_dlaa.dll) and, once, sets the game's
// internal render scale (renderer+0x80) to kScale. No hooks, no code patching.
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

static constexpr float kScale = 0.75f;
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
    if (n != proxy_patch::kCaveSize) { logf_line("proxy patch: cave emit failed"); return proxy_patch::Result::BadRange; }
    std::memcpy(cave, cave_bytes, n);

    for (const auto& p : proxy_patch::kSites) {
        const std::uint64_t patch_va = image_va + p.rva;
        std::uint8_t jmp[10] = { 0 };
        proxy_patch::emit_jump(jmp, patch_va, cave_va + p.cave_off);

        DWORD old = 0;
        if (!VirtualProtect(reinterpret_cast<void*>(patch_va), p.len, PAGE_EXECUTE_READWRITE, &old)) {
            logf_line("proxy patch: VirtualProtect failed at %p err=%lu", reinterpret_cast<void*>(patch_va), GetLastError());
            return proxy_patch::Result::NoMemory;
        }
        std::uint8_t* pd = reinterpret_cast<std::uint8_t*>(patch_va);
        std::memcpy(pd + 1, jmp + 1, 4);        // rel32 tail
        std::memset(pd + 5, 0x90, p.len - 5);   // NOP pad (none when len==5)
        pd[0] = jmp[0];                          // 0xE9 opcode last (atomic store -> jump goes live)
        FlushInstructionCache(GetCurrentProcess(), pd, p.len);
        DWORD ignore = 0;
        VirtualProtect(reinterpret_cast<void*>(patch_va), p.len, old, &ignore);
    }

    proxy_cave = static_cast<std::uint8_t*>(cave);
    logf_line("proxy patch: applied cave=%p (%zu patches, cave %zu bytes)", cave,
        sizeof(proxy_patch::kSites) / sizeof(proxy_patch::kSites[0]), n);
    return proxy_patch::Result::Applied;
}

static DWORD WINAPI setter_thread(void*)
{
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
        return 0;
    }

    // Proxy upscale patch (FSR4 scene->native output) — non-fatal if it fails.
    proxy_patch::Result pr = apply_proxy_patch();
    logf_line("proxy patch result: %s", proxy_patch::name(pr));

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

    if (r == scale_patch::Result::Applied && pr == proxy_patch::Result::Applied && proxy_cave) {
        std::memcpy(proxy_cave + proxy_patch::kScaleOff, &kScale, sizeof(kScale));
        logf_line("proxy gate scale set to %.3f", kScale);
    }
    return 0;
}

static void start_setter_once()
{
    if (InterlockedCompareExchange(&setter_started, 1, 0) != 0) return;
    HANDLE h = CreateThread(nullptr, 0, setter_thread, nullptr, 0, nullptr);
    if (h) CloseHandle(h); else logf_line("CreateThread failed err=%lu", GetLastError());
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

extern "C" HRESULT WINAPI D3D11CreateDevice(IDXGIAdapter* adapter, D3D_DRIVER_TYPE type, HMODULE sw,
    UINT flags, const D3D_FEATURE_LEVEL* levels, UINT nlevels, UINT sdk, ID3D11Device** outdev,
    D3D_FEATURE_LEVEL* outfl, ID3D11DeviceContext** outctx)
{
    if (!load_real()) return E_FAIL;
    const HRESULT hr = real_CreateDevice(adapter, type, sw, flags, levels, nlevels, sdk, outdev, outfl, outctx);
    const DWORD error = GetLastError();
    if (SUCCEEDED(hr)) start_setter_once();
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
    SetLastError(error);
    return hr;
}
