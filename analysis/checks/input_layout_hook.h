#pragma once
// Hook ID3D11Device::CreateInputLayout so the vertex format (element semantics/formats/offsets) can
// be recovered. D3D11 does not expose an input layout's elements from the bound layout, so this maps
// each ID3D11InputLayout* to the elements it was created with. Mirrors the menu overlay's vtable hook.
#include <d3d11.h>
#include <atomic>
#include <mutex>
#include <string>
#include <vector>
#include "vtable_hook.h"

namespace input_layout_hook {
struct Element {
    std::string semantic;
    UINT index = 0;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    UINT slot = 0;
    UINT offset = 0;
    UINT slot_class = 0;   // D3D11_INPUT_PER_VERTEX_DATA (0) or PER_INSTANCE (1)
    UINT step_rate = 0;
};
struct Layout { std::vector<Element> elements; };

using CreateInputLayoutFn = HRESULT (STDMETHODCALLTYPE*)(ID3D11Device*, const D3D11_INPUT_ELEMENT_DESC*,
                                                         UINT, const void*, SIZE_T, ID3D11InputLayout**);

// ID3D11Device::CreateInputLayout, 0-based vtable slot (IUnknown occupies 0..2, then the 9 device
// create methods precede it: CreateBuffer..CreateDepthStencilView are slots 3..10).
constexpr std::size_t kCreateInputLayout = 11;

inline std::mutex& mutex() { static std::mutex m; return m; }
inline std::vector<std::pair<ID3D11InputLayout*, Layout>>& store() {
    static std::vector<std::pair<ID3D11InputLayout*, Layout>> s; return s;
}
inline void record(ID3D11InputLayout* layout, std::vector<Element>&& elements) {
    if (!layout) return;
    std::lock_guard<std::mutex> lock(mutex());
    store().emplace_back(layout, Layout{std::move(elements)});
}
inline bool lookup(ID3D11InputLayout* layout, Layout& out) {
    if (!layout) return false;
    std::lock_guard<std::mutex> lock(mutex());
    for (auto& [k, v] : store()) if (k == layout) { out = v; return true; }
    return false;
}

inline std::atomic<void*> g_next{nullptr};

inline HRESULT STDMETHODCALLTYPE hooked_create_input_layout(ID3D11Device* self,
        const D3D11_INPUT_ELEMENT_DESC* descs, UINT count, const void* bytecode, SIZE_T length,
        ID3D11InputLayout** out) {
    const auto next = reinterpret_cast<CreateInputLayoutFn>(g_next.load(std::memory_order_acquire));
    const HRESULT hr = next(self, descs, count, bytecode, length, out);
    if (SUCCEEDED(hr) && out && *out && descs && count) {
        std::vector<Element> elements;
        elements.reserve(count);
        for (UINT i = 0; i < count; ++i) {
            Element e;
            e.semantic = descs[i].SemanticName ? descs[i].SemanticName : "";
            e.index = descs[i].SemanticIndex;
            e.format = descs[i].Format;
            e.slot = descs[i].InputSlot;
            e.offset = descs[i].AlignedByteOffset;
            e.slot_class = descs[i].InputSlotClass;
            e.step_rate = descs[i].InstanceDataStepRate;
            elements.push_back(std::move(e));
        }
        record(*out, std::move(elements));
    }
    return hr;
}

inline bool protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

// Install once. Returns true if the hook is chainable (Hooked/AlreadyHooked/RestoreFailed).
inline bool install(ID3D11Device* device) {
    static bool done = false;
    if (!device || done) return done;
    done = true;
    void** table = *reinterpret_cast<void***>(device);
    const auto r = vtable_hook::hook(table, kCreateInputLayout,
                                     reinterpret_cast<void*>(&hooked_create_input_layout), g_next, protect);
    return r == vtable_hook::Result::Hooked || r == vtable_hook::Result::AlreadyHooked ||
           r == vtable_hook::Result::RestoreFailed;
}
}  // namespace input_layout_hook
