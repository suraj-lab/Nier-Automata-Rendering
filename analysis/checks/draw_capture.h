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
#include "texture_capture.h"

namespace draw_capture {
// 0-based ID3D11DeviceContext vtable slots (IUnknown 0..2, ID3D11DeviceChild 3..6, then VSSetConstantBuffers=7 ...).
// Verified against d3d11.h ordering: DrawIndexed=12, DrawIndexedInstanced=20 (IASetIndexBuffer is 19).
constexpr std::size_t kDrawIndexed = 12;
constexpr std::size_t kDrawIndexedInstanced = 20;

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
    D3D11_VIEWPORT viewport{};
    geometry_capture::Capture geometry;
    std::vector<ConstantBuffer> vs_cbs;
    std::vector<texture_capture::Ref> ps_textures;  // material textures bound to the pixel shader
};

// Skip draws smaller than this many indices (fullscreen/post-process quads and particles are 4-6; a
// real mesh is hundreds+). Settable so the mock can lower it for testing.
inline unsigned min_index_count = 128;

// Whole-frame capture. The menu's Present hook calls end_frame() BEFORE its own ImGui drawing and
// begin_frame() AFTER it, so exactly one game frame's draws are recorded and never the menu's own.
// Caps bound the one-off stall and memory of a heavy frame; extra draws are counted, not recorded.
inline unsigned max_frame_draws = 4096;   // first real capture: ~3400 draws >= 128 indices in one frame
inline std::size_t max_frame_bytes = std::size_t(768) << 20;  // unique bytes read back (shared buffers count once)
inline std::atomic<bool> frame_active{false};
inline std::vector<Record> frame;  // guarded by mutex
inline geometry_capture::Cache cache;  // guarded by mutex; holds buffer references only while recording
inline texture_capture::Cache texture_cache;  // guarded by mutex; same lifetime as `cache`
inline std::vector<texture_capture::Texture> frame_textures;  // guarded by mutex; filled by end_frame()
inline std::size_t max_texture_bytes = std::size_t(1024) << 20;  // mip-0 bytes per frame; later ones get id 0
inline std::size_t frame_bytes = 0;
inline unsigned frame_skipped = 0;
inline std::mutex mutex;

inline bool capture_state(ID3D11Device* device, ID3D11DeviceContext* context, geometry_capture::Capture& geo,
                          std::vector<ConstantBuffer>& cbs, D3D11_VIEWPORT& viewport, geometry_capture::Cache* cache = nullptr) {
    if (!geometry_capture::capture(device, context, geo, cache)) return false;
    UINT num = 1;
    context->RSGetViewports(&num, &viewport);
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

inline void begin_frame() {
    std::lock_guard<std::mutex> lock(mutex);
    frame.clear(); cache.clear(); texture_cache.clear(); frame_textures.clear(); frame_bytes = 0; frame_skipped = 0;
    frame_active.store(true, std::memory_order_release);
}
// Stop recording; true if a frame was being recorded (its draws are then in `frame`). Records keep
// their shared bytes alive, so the cache (and its references on game buffers) is dropped here.
inline bool end_frame() {
    std::lock_guard<std::mutex> lock(mutex);
    cache.clear();
    frame_textures.swap(texture_cache.textures);  // keep the pixels, drop the resource references
    texture_cache.clear();
    return frame_active.exchange(false, std::memory_order_acq_rel);
}

inline void record_draw(ID3D11DeviceContext* self, bool instanced, UINT index_count, UINT start_index,
                        INT base_vertex, UINT instance_count, UINT start_instance) {
    std::lock_guard<std::mutex> lock(mutex);
    if (!frame_active.load(std::memory_order_relaxed)) return;
    if (frame.size() >= max_frame_draws || frame_bytes >= max_frame_bytes) { ++frame_skipped; return; }
    ID3D11Device* device = nullptr;
    self->GetDevice(&device);
    if (!device) { ++frame_skipped; return; }
    Record r;
    r.index_count = index_count; r.start_index = start_index; r.base_vertex = base_vertex;
    r.instanced = instanced; r.instance_count = instance_count; r.start_instance = start_instance;
    const std::size_t before = cache.read_bytes;
    if (capture_state(device, self, r.geometry, r.vs_cbs, r.viewport, &cache)) {
        r.valid = true;
        texture_capture::capture(device, self, texture_cache, r.ps_textures, max_texture_bytes);
        frame_bytes += cache.read_bytes - before;
        for (const auto& cb : r.vs_cbs) frame_bytes += cb.bytes.size();
        frame.push_back(std::move(r));
    } else {
        ++frame_skipped;
    }
    device->Release();
}

inline std::atomic<void*> g_next_draw_indexed{nullptr}, g_next_draw_indexed_instanced{nullptr};

inline void STDMETHODCALLTYPE hooked_draw_indexed(ID3D11DeviceContext* self, UINT index_count,
                                                  UINT start_index, INT base_vertex) {
    // Capture BEFORE the draw: the IA/VS state is already bound. Draws below the minimum index count
    // (fullscreen quads, particles) are skipped.
    if (index_count >= min_index_count && frame_active.load(std::memory_order_relaxed))
        record_draw(self, false, index_count, start_index, base_vertex, 0, 0);
    reinterpret_cast<DrawIndexedFn>(g_next_draw_indexed.load(std::memory_order_acquire))(self, index_count, start_index, base_vertex);
}

inline void STDMETHODCALLTYPE hooked_draw_indexed_instanced(ID3D11DeviceContext* self, UINT index_count,
        UINT instance_count, UINT start_index, INT base_vertex, UINT start_instance) {
    if (index_count >= min_index_count && frame_active.load(std::memory_order_relaxed))
        record_draw(self, true, index_count, start_index, base_vertex, instance_count, start_instance);
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
