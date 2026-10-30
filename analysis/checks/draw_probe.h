#pragma once
// CPU-only diagnosis of missing native draw callbacks; never copy/map resources or start Remix.
#include <d3d11.h>
#include <atomic>
#include <cstddef>
#include <mutex>
#include <thread>
#include "input_layout_hook.h"
#include "vtable_hook.h"

namespace draw_probe {
inline bool enabled() {
    static const bool on = [] { wchar_t value[2]{}; return GetEnvironmentVariableW(L"NIER_DRAW_PROBE", value, 2) == 1 && value[0] == L'1'; }();
    return on;
}
// Opt-in second experiment: when the slots hold the pristine original again (measured on the laptop: same context, same
// table, restored12=1 at the 1600x900 -> 2880x1800 switch), put our hooks back and log what happens. A slot that holds a
// third party's function is never touched: chaining to an unknown hook is how Present-recursion loops start.
inline bool rehook_enabled() {
    static const bool on = [] { wchar_t value[2]{}; return GetEnvironmentVariableW(L"NIER_DRAW_PROBE_REHOOK", value, 2) == 1 && value[0] == L'1'; }();
    return on;
}
inline std::atomic<unsigned long long> indexed{0}, instanced{0};
// Hook bookkeeping: "installed once and then lost" must be distinguishable from "never installed". The laptop lost
// both draw hooks on the SAME context object and the SAME table when it switched to 2880x1800, so the report below has
// to name the slot values instead of only comparing them.
constexpr unsigned kIndexedSlot = 12, kInstancedSlot = 20;  // d3d11_abi_check.cpp pins these against the headers
inline std::atomic<unsigned> install_attempts{0}, install_skipped{0}, install_ok{0};
inline std::atomic<void*> installed_context{nullptr}, installed_table{nullptr};
inline std::atomic<unsigned long long> maintenance_calls{0}, rehooks{0};
// Canary: a slot nobody else should care about, hooked with a pure forward. If it is restored along with the draw
// slots, something re-applies a saved copy of the whole vtable; if it survives, a component owns the two draw slots.
constexpr unsigned kCanarySlot = 108;  // ID3D11DeviceContextVtbl::IAGetPrimitiveTopology
inline std::atomic<void*> canary_next{nullptr};
inline void STDMETHODCALLTYPE canary_hook(ID3D11DeviceContext* self, D3D11_PRIMITIVE_TOPOLOGY* topology) {
    reinterpret_cast<void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, D3D11_PRIMITIVE_TOPOLOGY*)>(
        canary_next.load(std::memory_order_acquire))(self, topology);
}
inline std::atomic<bool> sampled{false};
inline std::mutex mutex;
struct Sample {
    void* context = nullptr;
    void* identity = nullptr;
    void* table = nullptr;
    unsigned type = 0, layout = 0, topology = 0, vb_mask = 0, ib_format = 0, cb0 = 0, cb11 = 0;
    float width = 0, height = 0;
};
inline Sample sample;

inline bool probe_protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

// Returns "already", "hooked", "failed" or "foreign". A foreign slot is never touched: chaining to a function we did
// not replace is how overlay Present-recursion loops start.
inline const char* rehook_slot(void** table, unsigned slot, void* hook, void* original) {
    if (table[slot] == hook) return "already";
    if (table[slot] != original) return "foreign";
    std::atomic<void*> ignored{nullptr};
    const auto result = vtable_hook::hook(table, slot, hook, ignored, probe_protect);
    return result == vtable_hook::Result::Hooked ? "hooked" : "failed";
}

// Repair points. The draw slots are reset by another layer once per frame, so repairing only at Present leaves the
// whole frame uncovered. These forwarders are called before drawing starts (binding render targets, mapping a buffer)
// and put our hooks back first. Only a slot holding the pristine original is repaired; a third party's pointer is
// never replaced, because chaining to an unknown function is how overlay loops start.
inline std::atomic<void*> stash_hook_indexed{nullptr}, stash_hook_instanced{nullptr};
inline std::atomic<void*> stash_original_indexed{nullptr}, stash_original_instanced{nullptr};
inline std::atomic<void*> repair_next_rts{nullptr}, repair_next_map{nullptr};
inline std::atomic<unsigned long long> repairs{0};

inline void stash_hooks(void* indexed, void* instanced, void* indexed_original, void* instanced_original) {
    stash_hook_indexed.store(indexed);
    stash_hook_instanced.store(instanced);
    stash_original_indexed.store(indexed_original);
    stash_original_instanced.store(instanced_original);
}

inline void repair(ID3D11DeviceContext* context) {
    if (!context || !stash_hook_indexed.load(std::memory_order_acquire)) return;
    void** table = *reinterpret_cast<void***>(context);
    if (rehook_slot(table, kIndexedSlot, stash_hook_indexed.load(), stash_original_indexed.load())[0] == 'h') ++repairs;
    if (rehook_slot(table, kInstancedSlot, stash_hook_instanced.load(), stash_original_instanced.load())[0] == 'h') ++repairs;
}

inline void STDMETHODCALLTYPE repair_omset_render_targets(ID3D11DeviceContext* self, UINT count,
                                                          ID3D11RenderTargetView* const* views,
                                                          ID3D11DepthStencilView* depth) {
    try { repair(self); } catch (...) {}
    reinterpret_cast<void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, ID3D11RenderTargetView* const*,
                                               ID3D11DepthStencilView*)>(repair_next_rts.load(std::memory_order_acquire))(
        self, count, views, depth);
}

// HRESULT, not void: a forwarder that drops the return code hands the game garbage and corrupts dynamic uploads.
inline HRESULT STDMETHODCALLTYPE repair_map(ID3D11DeviceContext* self, ID3D11Resource* resource, UINT subresource,
                                            D3D11_MAP map_type, UINT flags, D3D11_MAPPED_SUBRESOURCE* mapped) {
    try { repair(self); } catch (...) {}
    return reinterpret_cast<HRESULT (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, D3D11_MAP, UINT,
                                                         D3D11_MAPPED_SUBRESOURCE*)>(
        repair_next_map.load(std::memory_order_acquire))(self, resource, subresource, map_type, flags, mapped);
}

constexpr unsigned kRtsSlot = 33, kMapSlot = 14;  // d3d11_abi_check.cpp pins these against the headers

inline void* identity(IUnknown* object) {
    IUnknown* same = nullptr;
    if (!object || FAILED(object->QueryInterface(__uuidof(IUnknown), reinterpret_cast<void**>(&same))) || !same) return nullptr;
    void* result = same;  // diagnostic identity only, never dereferenced after Release
    same->Release();
    return result;
}

inline void observe(ID3D11DeviceContext* context, UINT count, bool is_instanced) {
    if (!enabled()) return;
    (is_instanced ? instanced : indexed).fetch_add(1, std::memory_order_relaxed);
    if (!context || count < 128 || sampled.load(std::memory_order_acquire)) return;
    std::lock_guard<std::mutex> lock(mutex);
    if (sampled.load(std::memory_order_relaxed)) return;
    sample.context = context;
    sample.identity = identity(context);
    sample.table = *reinterpret_cast<void***>(context);
    sample.type = context->GetType();
    D3D11_PRIMITIVE_TOPOLOGY topology{};
    context->IAGetPrimitiveTopology(&topology);
    sample.topology = topology;
    ID3D11InputLayout* layout = nullptr;
    context->IAGetInputLayout(&layout);
    input_layout_hook::Layout elements;
    sample.layout = input_layout_hook::lookup(layout, elements);
    if (layout) layout->Release();
    ID3D11Buffer* vbs[4]{};
    UINT strides[4]{}, offsets[4]{};
    context->IAGetVertexBuffers(0, 4, vbs, strides, offsets);
    for (unsigned i = 0; i < 4; ++i) if (vbs[i]) { sample.vb_mask |= 1u << i; vbs[i]->Release(); }
    ID3D11Buffer* ib = nullptr;
    DXGI_FORMAT format{};
    UINT offset = 0;
    context->IAGetIndexBuffer(&ib, &format, &offset);
    sample.ib_format = ib ? format : DXGI_FORMAT_UNKNOWN;
    if (ib) ib->Release();
    for (unsigned slot : {0u, 11u}) {
        ID3D11Buffer* cb = nullptr;
        context->VSGetConstantBuffers(slot, 1, &cb);
        D3D11_BUFFER_DESC desc{};
        if (cb) { cb->GetDesc(&desc); cb->Release(); }
        (slot ? sample.cb11 : sample.cb0) = desc.ByteWidth;
    }
    D3D11_VIEWPORT viewport{};
    UINT n = 1;
    context->RSGetViewports(&n, &viewport);
    sample.width = n ? viewport.Width : 0;
    sample.height = n ? viewport.Height : 0;
    sampled.store(true, std::memory_order_release);
}

// One line naming the modules that can own a D3D11 hook, so a lost vtable slot can be attributed to something in the
// process instead of guessed at. Logged once per process, not as a report line.
inline void narrow(const wchar_t* wide, char* out, unsigned size) {
    unsigned i = 0;
    for (; wide && wide[i] && i + 1 < size; ++i) out[i] = static_cast<char>(wide[i]);
    out[i] = 0;
}

// Watcher: samples the two draw slots continuously and names the module each distinct function pointer belongs to.
// Sampling at Present only ever shows the pristine pointer, because the owner installs its hook for the duration of
// its own work and puts the original back afterwards; a poller catches it in the act.
inline void watcher(void** table, void (*log)(const char*, ...), unsigned seconds) {
    void* seen_fn[16] = {};
    unsigned count = 0;
    const ULONGLONG stop = GetTickCount64() + seconds * 1000ull;
    while (GetTickCount64() < stop) {
        for (unsigned slot : {kIndexedSlot, kInstancedSlot}) {
            void* fn = __atomic_load_n(&table[slot], __ATOMIC_ACQUIRE);
            bool known = false;
            for (unsigned i = 0; i < count; ++i) if (seen_fn[i] == fn) { known = true; break; }
            if (known || count >= 16) continue;
            seen_fn[count++] = fn;
            HMODULE owner = nullptr;
            GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               static_cast<LPCWSTR>(fn), &owner);
            wchar_t path[MAX_PATH]{};
            if (owner) GetModuleFileNameW(owner, path, MAX_PATH);
            char name[MAX_PATH]{};
            narrow(path, name, sizeof name);
            log("draw-watcher: slot=%u fn=%p module=%s", slot, fn, name[0] ? name : "(unknown)");
        }
        Sleep(1);
    }
    log("draw-watcher: done distinct=%u", count);
}

inline void log_modules(void (*log)(const char*, ...)) {
    static bool done = false;
    if (done || !log) return;
    done = true;
    const wchar_t* names[] = {L"d3d11.dll", L"d3d11_dlaa.dll", L"dxgi.dll", L"gameoverlayrenderer64.dll",
                              L"steam_api64.dll", L"nvngx_dlss.dll", L"nvngx_dlssg.dll", L"sl.interposer.dll",
                              L"nvspcap64.dll", L"nvoglv64.dll"};
    char line[512] = {};
    for (const wchar_t* name : names) {
        const HMODULE module = GetModuleHandleW(name);
        char narrow[64] = {};
        for (unsigned i = 0; i < 63 && name[i]; ++i) narrow[i] = static_cast<char>(name[i]);
        char entry[96] = {};
        sprintf_s(entry, "%s=%p ", narrow, static_cast<void*>(module));
        strcat_s(line, entry);
    }
    log("draw-probe modules: %s", line);
}

inline void report(IDXGISwapChain* swapchain, void (*log)(const char*, ...), void* indexed_hook, void* instanced_hook,
                   void* indexed_original, void* instanced_original) {
    if (!enabled() || !log) return;
    ID3D11Device* device = nullptr;
    if (FAILED(swapchain->GetDevice(__uuidof(ID3D11Device), reinterpret_cast<void**>(&device))) || !device) return;
    ID3D11DeviceContext* context = nullptr;
    device->GetImmediateContext(&context);
    if (!context) { device->Release(); return; }
    log_modules(log);
    void** table = *reinterpret_cast<void***>(context);
    // Entry state of the canary, before any maintenance: a canary that is restored as well means a saved snapshot of
    // the whole table was re-applied, not that one component owns the two draw slots.
    const bool canary_intact = table[kCanarySlot] == reinterpret_cast<void*>(&canary_hook);
    if (rehook_enabled() && !canary_intact && table[kCanarySlot] == canary_next.load(std::memory_order_acquire))
        rehook_slot(table, kCanarySlot, reinterpret_cast<void*>(&canary_hook), canary_next.load());
    void* slot_indexed = table[kIndexedSlot];
    void* slot_instanced = table[kInstancedSlot];
    // The logged mask and the restored/foreign classification always describe the state found on entry, before any
    // maintenance below, so a loss stays visible.
    const unsigned mask = (slot_indexed == indexed_hook ? 1u : 0u) | (slot_instanced == instanced_hook ? 2u : 0u);
    const bool restored_indexed = indexed_original && slot_indexed == indexed_original;
    const bool restored_instanced = instanced_original && slot_instanced == instanced_original;
    const bool foreign_indexed = !(mask & 1u) && !restored_indexed;
    const bool foreign_instanced = !(mask & 2u) && !restored_instanced;
    const char* rehook_indexed = "-";
    const char* rehook_instanced = "-";
    unsigned mask_after = mask;
    if (rehook_enabled()) {
        static std::atomic<bool> started{false};
        if (!started.exchange(true)) {
            // Detached on purpose: the diagnostic never outlives the process and nothing waits on it.
            std::thread(watcher, table, log, 40u).detach();
        }
    }
    // Opt-in maintenance on EVERY Present, not just every five seconds: an actor that restores the table more often
    // than we sample would otherwise hide whether draws reach a hook that stays in place.
    if (rehook_enabled()) {
        ++maintenance_calls;
        rehook_indexed = rehook_slot(table, kIndexedSlot, indexed_hook, indexed_original);
        rehook_instanced = rehook_slot(table, kInstancedSlot, instanced_hook, instanced_original);
        if (rehook_indexed[0] == 'h' || rehook_instanced[0] == 'h') ++rehooks;
        mask_after = (table[kIndexedSlot] == indexed_hook ? 1u : 0u) | (table[kInstancedSlot] == instanced_hook ? 2u : 0u);
    }
    static ULONGLONG last = 0;
    const ULONGLONG now = GetTickCount64();
    if (last && now - last < 5000) { context->Release(); device->Release(); return; }
    last = now;
    const bool layout_hook = (*reinterpret_cast<void***>(device))[input_layout_hook::kCreateInputLayout] ==
                             reinterpret_cast<void*>(&input_layout_hook::hooked_create_input_layout);
    DXGI_SWAP_CHAIN_DESC desc{};
    swapchain->GetDesc(&desc);
    {
        std::lock_guard<std::mutex> lock(mutex);
        log("draw-probe: indexed=%llu instanced=%llu armed_context=%p armed_identity=%p armed_table=%p hook_mask=%u "
            "layout_hook=%u sample=%u sample_context=%p sample_identity=%p sample_table=%p type=%u layout=%u "
            "topology=%u vb_mask=%u ib_format=%u cb0=%u cb11=%u viewport=%.0fx%.0f backbuffer=%ux%u "
            "install_attempts=%u install_skipped=%u install_ok=%u ctx_installed=%p table_installed=%p "
            "slot12=%p slot20=%p orig12=%p orig20=%p restored12=%u restored20=%u foreign12=%u foreign20=%u "
            "rehook12=%s rehook20=%s rehook_mask=%u maintenance=%llu rehooks=%llu canary=%u repairs=%llu",
            indexed.load(std::memory_order_relaxed), instanced.load(std::memory_order_relaxed),
            static_cast<void*>(context), identity(context), static_cast<void*>(table), mask, static_cast<unsigned>(layout_hook),
            static_cast<unsigned>(sampled.load(std::memory_order_relaxed)), sample.context, sample.identity, sample.table,
            sample.type, sample.layout, sample.topology, sample.vb_mask, sample.ib_format, sample.cb0, sample.cb11,
            sample.width, sample.height, desc.BufferDesc.Width, desc.BufferDesc.Height,
            install_attempts.load(std::memory_order_relaxed), install_skipped.load(std::memory_order_relaxed),
            install_ok.load(std::memory_order_relaxed), installed_context.load(std::memory_order_relaxed),
            installed_table.load(std::memory_order_relaxed), slot_indexed, slot_instanced, indexed_original,
            instanced_original, static_cast<unsigned>(restored_indexed), static_cast<unsigned>(restored_instanced),
            static_cast<unsigned>(foreign_indexed), static_cast<unsigned>(foreign_instanced),
            rehook_indexed, rehook_instanced, mask_after,
            maintenance_calls.load(std::memory_order_relaxed), rehooks.load(std::memory_order_relaxed),
            static_cast<unsigned>(canary_intact), repairs.load(std::memory_order_relaxed));
        sample = Sample{};
        sampled.store(false, std::memory_order_relaxed);
    }
    context->Release();
    device->Release();
}
}  // namespace draw_probe
