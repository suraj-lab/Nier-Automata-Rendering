#pragma once
// Hook ID3D11DeviceContext::DrawIndexed / DrawIndexedInstanced and, on a trigger, capture the draw
// arguments plus the bound geometry (via geometry_capture) and the VS constant buffers (raw transform
// bytes). This completes the offline capture: geometry + format + draw args + transforms.
#include <d3d11.h>
#include <atomic>
#include <mutex>
#include <vector>
#include "vtable_hook.h"
#include "geometry_capture.h"

namespace draw_capture {
// 0-based ID3D11DeviceContext vtable slots (IUnknown 0..2, ID3D11DeviceChild 3..6).
constexpr std::size_t kDrawIndexed = 12;
constexpr std::size_t kDrawIndexedInstanced = 19;

using DrawIndexedFn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, INT);
using DrawIndexedInstancedFn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, UINT, INT, UINT);

struct ConstantBuffer {
    UINT slot = 0, first = 0, num = 0, byte_width = 0;
    std::vector<unsigned char> bytes;
};
struct Record {
    bool valid = false;
    UINT index_count = 0, start_index = 0; INT base_vertex = 0;
    bool instanced = false; UINT instance_count = 0, start_instance = 0;
    geometry_capture::Capture geometry;
    std::vector<ConstantBuffer> vs_cbs;
};

inline std::atomic<bool> capture_next{false};
inline std::atomic<bool> ready{false};
inline Record record;
inline std::mutex mutex;

inline bool capture_state(ID3D11Device* device, ID3D11DeviceContext* context,
                          geometry_capture::Capture& geo, std::vector<ConstantBuffer>& cbs) {
    if (!geometry_capture::capture(device, context, geo)) return false;
    cbs.clear();
    ID3D11Buffer* buffers[D3D11_COMMONSHADER_CONSTANT_BUFFER_API_SLOT_COUNT] = {};
    context->VSGetConstantBuffers(0, D3D11_COMMONSHADER_CONSTANT_BUFFER_API_SLOT_COUNT, buffers);
    for (UINT i = 0; i < D3D11_COMMONSHADER_CONSTANT_BUFFER_API_SLOT_COUNT; ++i) {
        if (!buffers[i]) continue;
        D3D11_BUFFER_DESC d{}; buffers[i]->GetDesc(&d);
        ConstantBuffer cb;
        cb.slot = i; cb.byte_width = d.ByteWidth;  // first/num are only in the *1 variant; full bytes are what matter
        if (!geometry_capture::read_buffer(device, context, buffers[i], 0, d.ByteWidth, cb.bytes)) {
            buffers[i]->Release(); return false;
        }
        cbs.push_back(std::move(cb));
        buffers[i]->Release();
    }
    return true;
}

inline void publish(ID3D11DeviceContext* self, bool instanced, UINT index_count, UINT start_index,
                    INT base_vertex, UINT instance_count, UINT start_instance) {
    ID3D11Device* device = nullptr;
    self->GetDevice(&device);
    if (!device) return;
    Record r;
    r.index_count = index_count; r.start_index = start_index; r.base_vertex = base_vertex;
    r.instanced = instanced; r.instance_count = instance_count; r.start_instance = start_instance;
    if (capture_state(device, self, r.geometry, r.vs_cbs)) r.valid = true;
    {
        std::lock_guard<std::mutex> lock(mutex);
        record = std::move(r);
        ready.store(true, std::memory_order_release);
    }
    device->Release();
}

inline std::atomic<void*> g_next_draw_indexed{nullptr}, g_next_draw_indexed_instanced{nullptr};

inline void STDMETHODCALLTYPE hooked_draw_indexed(ID3D11DeviceContext* self, UINT index_count,
                                                  UINT start_index, INT base_vertex) {
    // Capture BEFORE the draw: the IA/VS state is already bound and the real draw may need no RT in a mock.
    if (capture_next.exchange(false)) publish(self, false, index_count, start_index, base_vertex, 0, 0);
    reinterpret_cast<DrawIndexedFn>(g_next_draw_indexed.load(std::memory_order_acquire))(self, index_count, start_index, base_vertex);
}

inline void STDMETHODCALLTYPE hooked_draw_indexed_instanced(ID3D11DeviceContext* self, UINT index_count,
        UINT instance_count, UINT start_index, INT base_vertex, UINT start_instance) {
    if (capture_next.exchange(false))
        publish(self, true, index_count, start_index, base_vertex, instance_count, start_instance);
    reinterpret_cast<DrawIndexedInstancedFn>(g_next_draw_indexed_instanced.load(std::memory_order_acquire))(
        self, index_count, instance_count, start_index, base_vertex, start_instance);
}

inline bool protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

inline bool install(ID3D11DeviceContext* context) {
    static bool done = false;
    if (!context || done) return done;
    done = true;
    void** table = *reinterpret_cast<void***>(context);
    const auto a = vtable_hook::hook(table, kDrawIndexed, reinterpret_cast<void*>(&hooked_draw_indexed),
                                     g_next_draw_indexed, protect);
    const auto b = vtable_hook::hook(table, kDrawIndexedInstanced, reinterpret_cast<void*>(&hooked_draw_indexed_instanced),
                                     g_next_draw_indexed_instanced, protect);
    const auto ok = [](vtable_hook::Result r) { return r == vtable_hook::Result::Hooked || r == vtable_hook::Result::AlreadyHooked || r == vtable_hook::Result::RestoreFailed; };
    return ok(a) && ok(b);
}
}  // namespace draw_capture
