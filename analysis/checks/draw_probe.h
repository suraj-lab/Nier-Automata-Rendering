#pragma once
// CPU-only diagnosis of missing native draw callbacks; never copy/map resources or start Remix.
#include <d3d11.h>
#include <atomic>
#include <mutex>
#include "input_layout_hook.h"

namespace draw_probe {
inline bool enabled() {
    static const bool on = [] { wchar_t value[2]{}; return GetEnvironmentVariableW(L"NIER_DRAW_PROBE", value, 2) == 1 && value[0] == L'1'; }();
    return on;
}
inline std::atomic<unsigned long long> indexed{0}, instanced{0};
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

inline void report(IDXGISwapChain* swapchain, void (*log)(const char*, ...), void* indexed_hook, void* instanced_hook) {
    if (!enabled() || !log) return;
    static ULONGLONG last = 0;
    const ULONGLONG now = GetTickCount64();
    if (last && now - last < 5000) return;
    last = now;
    ID3D11Device* device = nullptr;
    if (FAILED(swapchain->GetDevice(__uuidof(ID3D11Device), reinterpret_cast<void**>(&device))) || !device) return;
    ID3D11DeviceContext* context = nullptr;
    device->GetImmediateContext(&context);
    if (!context) { device->Release(); return; }
    void** table = *reinterpret_cast<void***>(context);
    const unsigned mask = (table[12] == indexed_hook ? 1u : 0u) | (table[20] == instanced_hook ? 2u : 0u);
    const bool layout_hook = (*reinterpret_cast<void***>(device))[input_layout_hook::kCreateInputLayout] ==
                             reinterpret_cast<void*>(&input_layout_hook::hooked_create_input_layout);
    DXGI_SWAP_CHAIN_DESC desc{};
    swapchain->GetDesc(&desc);
    {
        std::lock_guard<std::mutex> lock(mutex);
        log("draw-probe: indexed=%llu instanced=%llu armed_context=%p armed_identity=%p armed_table=%p hook_mask=%u "
            "layout_hook=%u sample=%u sample_context=%p sample_identity=%p sample_table=%p type=%u layout=%u "
            "topology=%u vb_mask=%u ib_format=%u cb0=%u cb11=%u viewport=%.0fx%.0f backbuffer=%ux%u",
            indexed.load(std::memory_order_relaxed), instanced.load(std::memory_order_relaxed),
            static_cast<void*>(context), identity(context), static_cast<void*>(table), mask, static_cast<unsigned>(layout_hook),
            static_cast<unsigned>(sampled.load(std::memory_order_relaxed)), sample.context, sample.identity, sample.table,
            sample.type, sample.layout, sample.topology, sample.vb_mask, sample.ib_format, sample.cb0, sample.cb11,
            sample.width, sample.height, desc.BufferDesc.Width, desc.BufferDesc.Height);
        sample = Sample{};
        sampled.store(false, std::memory_order_relaxed);
    }
    context->Release();
    device->Release();
}
}  // namespace draw_probe
