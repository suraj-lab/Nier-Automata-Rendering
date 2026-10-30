#pragma once
// Live scene capture: describes the game's draws for the current frame from CPU shadows and one-time
// reads, so the Remix worker can rebuild the scene every frame without GPU readback. No Remix API here.
//
// Why shadows: NieR issues ~3000 draws per frame and rewrites per-object constant buffers between them.
// Reading those back through staging copies costs ~0.1 ms each, so the game's own writes are mirrored on
// the CPU instead (Map/Unmap, UpdateSubresource, Copy*), and static buffers are read exactly once.
#include <d3d11.h>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <algorithm>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <vector>
#include "live_types.h"
#include "live_vertex_decode.h"
#include "live_skinning.h"
#include "input_layout_hook.h"
#include "vtable_hook.h"
#include "texture_capture.h"
#include "shader_capture.h"
#include "alpha_test.h"

namespace live_capture {

// ---- publication -------------------------------------------------------------------------------
// Recursive: reading a buffer back goes through CopyResource/CopySubresourceRegion, which are our own
// hooks and would otherwise re-enter a plain mutex on the same thread. Everything here runs on the game's
// immediate context, so there is only ever one thread at a time.
inline std::recursive_mutex& mutex() { static std::recursive_mutex m; return m; }
inline Frame& building() { static Frame f; return f; }
inline Frame& ready() { static Frame f; return f; }
inline std::atomic<std::uint64_t> ready_sequence{0};
inline std::atomic<bool> permitted{false};    // capture allowed (host alive and Running)
inline std::atomic<bool> suspended{false};    // F10 original view: no per-frame capture, writes still mirrored
inline std::atomic<bool> frame_open{false};   // between begin_frame and end_frame
inline std::atomic<ID3D11DeviceContext*> active_context{nullptr};
// One mapped pointer per resource between Map and Unmap: engines map several buffers at once.
inline std::map<ID3D11Resource*, void*>& mapped() { static std::map<ID3D11Resource*, void*> m; return m; }



// Uploads and textures are queued, not tied to one frame: the game publishes faster than the worker can
// draw, so a frame that carried a first-sight mesh would otherwise be dropped and that mesh never built.
inline std::vector<Upload>& pending_uploads() { static std::vector<Upload> q; return q; }
inline std::vector<TextureFile>& pending_textures() { static std::vector<TextureFile> q; return q; }
inline std::size_t pending_bytes = 0;
inline std::size_t max_pending_bytes = std::size_t(1024) << 20;  // one full first-sight frame is ~300 MB
inline std::atomic<unsigned> dropped_uploads{0};

inline std::vector<Upload> take_uploads() {
    std::lock_guard<std::recursive_mutex> lock(mutex());
    std::vector<Upload> out;
    out.swap(pending_uploads());
    pending_bytes = 0;
    return out;
}
inline std::vector<TextureFile> take_textures() {
    std::lock_guard<std::recursive_mutex> lock(mutex());
    std::vector<TextureFile> out;
    out.swap(pending_textures());
    return out;
}

// The newest complete frame, if any. The returned reference stays valid until the next call.
inline const Frame& latest() {
    static Frame copy;
    std::lock_guard<std::recursive_mutex> lock(mutex());
    copy = ready();
    return copy;
}

// ---- shadows and one-time reads ----------------------------------------------------------------
// One entry per game buffer we have seen. Identity (incarnation + generation) is separate from the bytes, so the
// bytes of a static vertex/index buffer can be dropped under memory pressure without forcing a rebuild or a
// readback: the bytes are only needed again if the geometry has to be rebuilt.
struct Shadow {
    std::vector<unsigned char> bytes;  // empty = not resident (static bytes dropped by the budget)
    std::uint64_t incarnation = 0;     // unique per entry: a freed pointer reused by a new buffer gets a new one
    std::uint64_t generation = 0;      // bumped on every write the game makes
    std::uint64_t used = 0;            // LRU clock for dropping bytes
    std::uint64_t used_frame = 0;      // for expiring entries of buffers the game has probably freed
    bool written = false;              // the game writes it through our hooks: its bytes are never dropped
    bool trimmable = false;            // static vertex/index data; constant buffers are small and always kept
};
inline std::map<ID3D11Buffer*, Shadow>& shadows() { static std::map<ID3D11Buffer*, Shadow> s; return s; }
inline std::size_t shadow_budget = std::size_t(256) << 20;
// While bytes of several buffers are being resolved, nothing may be dropped: the returned pointers would dangle.
inline unsigned pins = 0;
struct Pin { Pin() { ++pins; } ~Pin() { --pins; } };
inline std::size_t shadow_bytes = 0;
inline std::uint64_t shadow_clock = 0;
inline std::uint64_t next_incarnation = 1;
inline std::uint64_t frame_number = 0;
inline std::atomic<unsigned long long> trims{0};          // times static bytes were dropped (logged once)
inline std::uint64_t expire_frames = 1800;                // ~30-60 s unused: release our reference
inline std::atomic<unsigned long long> released{0};       // entries released by expiry (logged once)
// Per-frame cap on first-sight buffer readbacks: each is a GPU stall on the game's thread.
inline std::size_t read_bytes_this_frame = 0;
// Game-thread buffer readbacks since the session started (logged cumulatively; diff two stats lines for a rate).
// Reason: 0 first sight (or dropped by a copy into the buffer), 1 static bytes dropped by the shadow budget, 2 a write
// too large to mirror. Kind: 0 constant, 1 immutable, 2 default (or other), 3 dynamic.
inline std::atomic<unsigned long long> read_reasons[3]{}, read_kinds[4]{};
inline std::atomic<unsigned long long> read_bytes_total{0}, read_us_total{0}, texture_us_total{0};
inline unsigned long long now_us() {
    LARGE_INTEGER f, c;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return static_cast<unsigned long long>(c.QuadPart / f.QuadPart * 1000000 + c.QuadPart % f.QuadPart * 1000000 / f.QuadPart);
}
inline unsigned fail_vb_reads = 0;                         // test switch only
// Above this, a write is not mirrored: reading a large write-combined mapping back costs more than the whole draw
// stream (measured on the real game), so the bytes are dropped. A draw that needs them reads them through a staging
// copy: budgeted for first sight, immediate when the content changed (a changed mesh must never keep its old shape,
// so a >1 MiB buffer rewritten every frame pays a read every frame: unmeasured, and the knob is there for that).
inline std::size_t max_shadow_write = std::size_t(1) << 20;
// Shadow-map and other offscreen passes draw the same meshes into a smaller viewport. Submitting them as world geometry
// costs Remix a second copy of the scene for nothing (the scene is ray traced from the camera).
inline float previous_max_viewport = 0;

// ---- render-target filter -----------------------------------------------------------------------
// Measured on a real captured frame (2436 draws): 1375 draws into a 2580x1080 target, 920 into the shadow atlas
// (4096x4096), 58 bloom passes at 1290x540, 58 HUD sprites into the 3440x1440 backbuffer. A viewport-size test
// cannot separate them (the atlas viewport is 2048 wide, 60% of the frame's largest), so the render target is the
// discriminator: the scene is the largest target with the final image's aspect that is smaller than the final image
// (see choose_scene_target). Shadow atlases fail the aspect test, bloom chains are smaller than the scene.
// If the choice is wrong the frame has nothing to draw; three such frames in a row latch the filter off.
inline std::map<ID3D11RenderTargetView*, std::pair<unsigned, unsigned>>& target_sizes() {
    static std::map<ID3D11RenderTargetView*, std::pair<unsigned, unsigned>> m;
    return m;
}
inline std::map<std::pair<unsigned, unsigned>, unsigned>& target_counts() {
    static std::map<std::pair<unsigned, unsigned>, unsigned> m;
    return m;
}
inline unsigned scene_width = 0, scene_height = 0;  // chosen from the previous frame; 0 = not known yet
inline unsigned final_width = 0, final_height = 0;  // the image that reaches the screen
inline bool scene_target_enabled = true;
inline unsigned scene_target_fallbacks = 0;      // empty frames seen this session (reported)
inline unsigned scene_target_empty_streak = 0;   // consecutive empty frames: three latch the filter off
inline std::atomic<bool> scene_target_latched{false};  // the worker logs the latch once
inline bool hud_enabled = true;                  // NIER_REMIX_LIVE_NO_HUD=1: no HUD capture, no replay
inline bool sky_enabled = true;                  // NIER_REMIX_LIVE_NO_SKY=1: drop the sky dome (pre-1.9 picture)

// Cached per render-target-view pointer for one frame (begin_frame clears it), so a view released and its address
// reused by a differently-sized one is re-measured on the next frame instead of keeping its old size all session.
inline std::pair<unsigned, unsigned> target_size(ID3D11RenderTargetView* rtv) {
    if (!rtv) return {0, 0};
    auto& cache = target_sizes();
    const auto known = cache.find(rtv);
    if (known != cache.end()) return known->second;
    std::pair<unsigned, unsigned> size{0, 0};
    ID3D11Resource* resource = nullptr;
    rtv->GetResource(&resource);
    if (resource) {
        D3D11_RESOURCE_DIMENSION dimension = D3D11_RESOURCE_DIMENSION_UNKNOWN;
        resource->GetType(&dimension);
        if (dimension == D3D11_RESOURCE_DIMENSION_TEXTURE2D) {
            D3D11_TEXTURE2D_DESC desc{};
            static_cast<ID3D11Texture2D*>(resource)->GetDesc(&desc);
            // A view of a lower mip (a bloom chain in one texture) renders at that mip's size, not the texture's.
            D3D11_RENDER_TARGET_VIEW_DESC view{};
            rtv->GetDesc(&view);
            unsigned mip = 0;
            if (view.ViewDimension == D3D11_RTV_DIMENSION_TEXTURE2D) mip = view.Texture2D.MipSlice;
            else if (view.ViewDimension == D3D11_RTV_DIMENSION_TEXTURE2DARRAY) mip = view.Texture2DArray.MipSlice;
            size = {std::max(1u, desc.Width >> mip), std::max(1u, desc.Height >> mip)};
        } else if (dimension == D3D11_RESOURCE_DIMENSION_TEXTURE3D) {
            D3D11_TEXTURE3D_DESC desc{};
            static_cast<ID3D11Texture3D*>(resource)->GetDesc(&desc);
            size = {desc.Width, desc.Height};
        }
        resource->Release();
    }
    if (cache.size() > 4096) cache.clear();
    cache[rtv] = size;
    return size;
}

// Called between frames: pick the scene target for the frame that follows.
// The scene is the largest target that is strictly smaller than the final image and has the final image's aspect
// ratio: an engine renders the scene at the display aspect and at some internal scale, while shadow atlases are
// square-ish and bloom chains are half-size. If no target qualifies, the game draws the scene at final size.
// A wrong pick empties the frame, which `end_frame` detects and latches the filter off.
inline void choose_scene_target() {
    auto& counts = target_counts();
    std::pair<unsigned, unsigned> best{0, 0};
    unsigned best_area = 0;
    if (final_width && final_height) {
        for (const auto& [size, draws] : counts) {
            if (!draws || !size.first || !size.second) continue;
            if (size.first >= final_width || size.second >= final_height) continue;  // the final image itself
            // Same aspect within 1%, in integer arithmetic: cross-multiplied aspect equality with tolerance.
            const unsigned long long lhs = static_cast<unsigned long long>(size.first) * final_height;
            const unsigned long long rhs = static_cast<unsigned long long>(size.second) * final_width;
            const unsigned long long diff = lhs > rhs ? lhs - rhs : rhs - lhs;
            if (diff * 100ull > rhs) continue;
            const unsigned area = size.first * size.second;
            if (area > best_area) { best = size; best_area = area; }
        }
        if (!best.first) best = {final_width, final_height};
    } else {
        for (const auto& [size, draws] : counts) {  // final size unknown: the most-drawn target is the best guess
            if (draws > best_area) { best = size; best_area = draws; }
        }
    }
    counts.clear();
    scene_width = best.first;
    scene_height = best.second;
}
inline std::atomic<unsigned long long> skipped_writes{0};
inline std::atomic<unsigned> injected_failures{0};
inline std::size_t read_budget_per_frame = std::size_t(64) << 20;

// Geometry -> the shadow identities it was built from, so a rewrite forces exactly one rebuild.
inline std::map<std::uint64_t, std::uint64_t>& built_versions() { static std::map<std::uint64_t, std::uint64_t> m; return m; }
// What was last uploaded for each geometry. NieR rewrites dynamic buffers constantly, usually with identical bytes;
// re-creating the mesh for that pinned the mesh budget and tore the picture (measured: ~96 builds/s standing still).
// Which geometries are background shells. Has to outlive the decode: the decode only runs when a geometry is (re)built,
// so a per-frame recomputation would lose the flag on every frame the mesh is already on the GPU.
inline std::map<std::uint64_t, bool>& sky_geometries() { static std::map<std::uint64_t, bool> m; return m; }
inline std::map<std::uint64_t, std::uint64_t>& content_hashes() { static std::map<std::uint64_t, std::uint64_t> m; return m; }
// Skinned draws of one buffer set seen so far this frame (cleared by begin_frame): the occurrence is part of the key.
inline std::map<std::uint64_t, unsigned>& skinned_occurrences() { static std::map<std::uint64_t, unsigned> m; return m; }
// The worker evicted these meshes: forget that they were built, so they are uploaded again when drawn.
inline void forget(const std::vector<std::uint64_t>& keys) {
    if (keys.empty()) return;
    std::lock_guard<std::recursive_mutex> lock(mutex());
    for (std::uint64_t key : keys) { built_versions().erase(key); content_hashes().erase(key); }
}

struct TextureEntry { std::uint32_t id = 0; std::uint64_t used_frame = 0; };  // id 0 = not capturable, do not retry
inline std::map<ID3D11Resource*, TextureEntry>& texture_ids() { static std::map<ID3D11Resource*, TextureEntry> m; return m; }
inline std::uint32_t next_texture_id = 1;
inline std::wstring texture_dir;
inline std::vector<TextureFile>& all_textures() { static std::vector<TextureFile> t; return t; }
inline std::size_t published_textures = 0;
inline std::size_t texture_bytes_written = 0;
inline std::size_t texture_disk_budget = std::size_t(2048) << 20;
inline unsigned textures_this_frame = 0;
inline bool lights_read = false;
// The HUD snapshot lives on the game thread only: it holds the game's shader resource views, which must be released
// here rather than handed to the worker. Swapped at end_frame, read by the composite in Present.
struct UiSnapshot {
    std::vector<UiVertex> verts;
    std::vector<UiDraw> draws;
    std::vector<ID3D11ShaderResourceView*> srvs;  // one per draw
};
inline UiSnapshot& ui_building() { static UiSnapshot s; return s; }
inline UiSnapshot& ui_ready() { static UiSnapshot s; return s; }
inline std::atomic<unsigned> ui_draw_count{0};
inline void publish_ui() {
    UiSnapshot& ready = ui_ready();
    for (auto* srv : ready.srvs) if (srv) srv->Release();
    ready = std::move(ui_building());
    ui_building() = UiSnapshot{};
    ui_draw_count.store(static_cast<unsigned>(ready.draws.size()), std::memory_order_release);
}  // the slot-20 light array is frame-level data: read at most once per frame
inline unsigned textures_per_frame = 4;  // NIER_REMIX_LIVE_TEX_PER_FRAME (0 = none this frame): each new texture is a GPU readback + a file write on this thread
// Deferred textures and the geometries that were built before the texture existed: when the texture is finally
// captured, those geometries are invalidated so the existing rebuild path makes one new mesh with the material.
inline std::map<ID3D11Resource*, std::vector<std::uint64_t>>& waiting_materials() {
    static std::map<ID3D11Resource*, std::vector<std::uint64_t>> m; return m;
}

inline std::uint64_t hash_mix(std::uint64_t h, const void* data, std::size_t n) {
    const auto* p = static_cast<const unsigned char*>(data);
    for (std::size_t i = 0; i < n; ++i) h = (h ^ p[i]) * 1099511628211ull;
    return h;
}
inline std::uint64_t hash_value(std::uint64_t value) { return hash_mix(1469598103934665603ull, &value, sizeof value); }

inline void erase_shadow(std::map<ID3D11Buffer*, Shadow>::iterator it) {
    shadow_bytes -= it->second.bytes.size();
    it->first->Release();
    shadows().erase(it);
}

// Over budget: drop the bytes (not the identity) of static vertex/index buffers, least recently used first.
inline void trim_shadows() {
    if (pins || shadow_bytes <= shadow_budget) return;
    std::vector<std::pair<std::uint64_t, ID3D11Buffer*>> candidates;
    for (const auto& [buffer, shadow] : shadows())
        if (shadow.trimmable && !shadow.bytes.empty()) candidates.emplace_back(shadow.used, buffer);
    std::sort(candidates.begin(), candidates.end());
    for (const auto& [used, buffer] : candidates) {
        if (shadow_bytes <= shadow_budget) break;
        Shadow& shadow = shadows()[buffer];
        shadow_bytes -= shadow.bytes.size();
        std::vector<unsigned char>().swap(shadow.bytes);
        trims.fetch_add(1, std::memory_order_relaxed);
    }
}

// Release entries the game has not used for a while, so buffers it freed are not kept alive by our reference.
inline void expire_entries() {
    const std::uint64_t every = std::max<std::uint64_t>(1, std::min<std::uint64_t>(256, expire_frames / 4));
    if (frame_number % every != 0) return;
    for (auto it = shadows().begin(); it != shadows().end();) {
        auto next = std::next(it);
        if (it->second.used_frame + expire_frames < frame_number) { erase_shadow(it); released.fetch_add(1); }
        it = next;
    }
    // Textures are deliberately never expired: a re-export would get a new id, a second file and a second material,
    // and fill the disk budget. shortcut: their references are held for the session; bounded by the 2 GB budget.
}

// Host failed or stopped: no more capture, and every reference this session took is given back.
inline void set_permitted(bool ok) {
    permitted.store(ok, std::memory_order_release);
    if (!ok) {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        frame_open.store(false, std::memory_order_release);
        building() = Frame{};
        mapped().clear();
        while (!shadows().empty()) erase_shadow(shadows().begin());  // the game's buffers are no longer pinned
        for (auto& entry : texture_ids()) entry.first->Release();
        texture_ids().clear();
        built_versions().clear();
    }
}

// Pause capture without tearing anything down: no references are released and no maps are cleared, so nothing can be
// freed underneath GPU work that is still in flight. The F10 original view uses this; set_permitted(false) stays for a
// real failure, where the session is over anyway. (2026-10-28: tearing down on F10 caused a gfx page fault in
// dxvk-submit and a wedged GPU one second after resuming.)
// Writes keep being mirrored while suspended: a buffer the game rewrites behind the original view must not come back
// with its old bytes (review 2026-10-29). Only the per-frame capture stops.
inline void set_suspended(bool on) { suspended.store(on, std::memory_order_release); }

inline Shadow* find_shadow(ID3D11Buffer* buffer) {
    if (!buffer) return nullptr;
    const auto it = shadows().find(buffer);
    return it == shadows().end() ? nullptr : &it->second;
}

inline Shadow& new_shadow(ID3D11Buffer* buffer, const D3D11_BUFFER_DESC& desc, bool written) {
    buffer->AddRef();  // the key keeps the pointer from being reused while the entry exists
    Shadow& shadow = shadows()[buffer];
    shadow.incarnation = next_incarnation++;
    shadow.written = written;
    shadow.trimmable = !written && !(desc.BindFlags & D3D11_BIND_CONSTANT_BUFFER);
    shadow.used_frame = frame_number;
    return shadow;
}

// Identity of a buffer's current contents without touching its bytes; 0 = never seen (must be read).
inline std::uint64_t identity(ID3D11Buffer* buffer) {
    Shadow* shadow = find_shadow(buffer);
    if (!shadow) return 0;
    shadow->used_frame = frame_number;  // drawn = in use, even when its bytes are never needed again
    return hash_value(shadow->incarnation * 1000003ull ^ shadow->generation);
}

inline bool read_into(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Buffer* buffer,
                      const D3D11_BUFFER_DESC& desc, std::vector<unsigned char>& bytes) {
    D3D11_BUFFER_DESC staging = desc;
    staging.Usage = D3D11_USAGE_STAGING;
    staging.BindFlags = 0;
    staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    staging.MiscFlags = 0;
    staging.StructureByteStride = 0;
    ID3D11Buffer* copy = nullptr;
    if (FAILED(device->CreateBuffer(&staging, nullptr, &copy)) || !copy) return false;
    context->CopyResource(copy, buffer);
    D3D11_MAPPED_SUBRESOURCE map{};
    if (FAILED(context->Map(copy, 0, D3D11_MAP_READ, 0, &map))) { copy->Release(); return false; }
    bool ok = true;
    try {
        bytes.assign(static_cast<const unsigned char*>(map.pData), static_cast<const unsigned char*>(map.pData) + desc.ByteWidth);
    } catch (...) { ok = false; }
    context->Unmap(copy, 0);
    copy->Release();
    return ok;
}

// CPU copy of a whole buffer: the shadow if resident, otherwise one staging read that is kept. Caller holds mutex().
inline const std::vector<unsigned char>* buffer_bytes(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Buffer* buffer) {
    if (!buffer) return nullptr;
    D3D11_BUFFER_DESC desc{};
    Shadow* shadow = find_shadow(buffer);
    if (!shadow || shadow->bytes.empty()) {
        buffer->GetDesc(&desc);
        if (!desc.ByteWidth) return nullptr;
        std::vector<unsigned char> bytes;
        // Test switch (NIER_REMIX_LIVE_FAIL_VB_READS, unset = 0): a readback can fail in the field (device busy or
        // lost, staging creation failing); the mock cannot produce that on demand, so the gate injects it.
        if ((desc.BindFlags & D3D11_BIND_VERTEX_BUFFER) && fail_vb_reads) {
            --fail_vb_reads;
            injected_failures.fetch_add(1, std::memory_order_relaxed);
            return nullptr;
        }
        const unsigned reason = !shadow ? 0u : shadow->written ? 2u : 1u;
        const unsigned kind = (desc.BindFlags & D3D11_BIND_CONSTANT_BUFFER) ? 0u : desc.Usage == D3D11_USAGE_IMMUTABLE ? 1u
                            : desc.Usage == D3D11_USAGE_DYNAMIC ? 3u : 2u;
        const unsigned long long started = now_us();
        const bool read = read_into(device, context, buffer, desc, bytes);
        read_us_total.fetch_add(now_us() - started, std::memory_order_relaxed);
        if (!read) return nullptr;
        read_reasons[reason].fetch_add(1, std::memory_order_relaxed);
        read_kinds[kind].fetch_add(1, std::memory_order_relaxed);
        read_bytes_total.fetch_add(bytes.size(), std::memory_order_relaxed);
        read_bytes_this_frame += bytes.size();
        if (!shadow) shadow = &new_shadow(buffer, desc, false);  // new identity; a re-read keeps the old one
        shadow->bytes.swap(bytes);
        shadow_bytes += shadow->bytes.size();
    }
    shadow->used = ++shadow_clock;
    shadow->used_frame = frame_number;
    trim_shadows();
    return &shadow->bytes;
}

// ---- write tracking ----------------------------------------------------------------------------
// Every hook below is pure pass-through unless live capture is permitted: a normal launch must not pay for, or
// be put at risk by, shadowing it never uses. One mapped pointer per resource: engines map several at once.

// `mapped`: the bytes are the game's Map pointer (write-combined: slow to read back, so large writes are dropped).
// UpdateSubresource hands us the game's own system memory, which is cheap to copy at any size.
inline void note_write(ID3D11Buffer* buffer, const void* data, std::size_t size, bool mapped = true) {
    if (!buffer || !data || !size) return;
    D3D11_BUFFER_DESC desc{};
    buffer->GetDesc(&desc);
    if (!desc.ByteWidth || size < desc.ByteWidth) return;
    if (mapped && desc.ByteWidth > max_shadow_write && !(desc.BindFlags & D3D11_BIND_CONSTANT_BUFFER)) {
        Shadow* shadow = find_shadow(buffer);
        if (!shadow) shadow = &new_shadow(buffer, desc, true);
        else if (!shadow->bytes.empty()) {
            shadow_bytes -= shadow->bytes.size();
            std::vector<unsigned char>().swap(shadow->bytes);
        }
        shadow->written = true;  // a first-sight read made it look static; it is the game's write that dropped the bytes
        shadow->trimmable = false;
        ++shadow->generation;  // contents changed: geometry built from them is rebuilt by the next draw
        shadow->used = ++shadow_clock;
        shadow->used_frame = frame_number;
        skipped_writes.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    Shadow* shadow = find_shadow(buffer);
    if (!shadow) shadow = &new_shadow(buffer, desc, true);
    if (shadow->bytes.size() != desc.ByteWidth) {
        const std::size_t before = shadow->bytes.size();
        shadow->bytes.resize(desc.ByteWidth);
        shadow_bytes = shadow_bytes - before + shadow->bytes.size();
    }
    std::memcpy(shadow->bytes.data(), data, desc.ByteWidth);
    shadow->written = true;
    shadow->trimmable = false;
    ++shadow->generation;
    shadow->used = ++shadow_clock;
    shadow->used_frame = frame_number;
    trim_shadows();
}

inline void invalidate_shadow(ID3D11Resource* resource) {
    if (!resource) return;
    ID3D11Buffer* buffer = nullptr;
    if (FAILED(resource->QueryInterface(__uuidof(ID3D11Buffer), reinterpret_cast<void**>(&buffer))) || !buffer) return;
    const auto it = shadows().find(buffer);
    if (it != shadows().end()) erase_shadow(it);  // next use reads again under a new identity
    buffer->Release();
}

using MapFn = HRESULT (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, D3D11_MAP, UINT, D3D11_MAPPED_SUBRESOURCE*);
using UnmapFn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT);
using UpdateSubresourceFn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, const D3D11_BOX*, const void*, UINT, UINT);
using CopyResourceFn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, ID3D11Resource*);
using CopySubresourceRegionFn = void (STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, UINT, UINT, UINT, ID3D11Resource*, UINT, const D3D11_BOX*);

inline std::atomic<void*> g_next_map{nullptr}, g_next_unmap{nullptr}, g_next_update{nullptr};
inline std::atomic<void*> g_next_copy{nullptr}, g_next_copy_region{nullptr};
using CreateBufferFn = HRESULT (STDMETHODCALLTYPE*)(ID3D11Device*, const D3D11_BUFFER_DESC*, const D3D11_SUBRESOURCE_DATA*, ID3D11Buffer**);
inline std::atomic<void*> g_next_create_buffer{nullptr};
inline std::atomic<unsigned long long> created_captures{0};  // vertex/index buffers whose bytes came from pInitialData

// A vertex/index buffer created with initial data: keep those bytes as its shadow, so its first draw needs no GPU
// readback. They stay trimmable (budget-governed like any static bytes): a level's geometry can exceed the budget.
inline HRESULT STDMETHODCALLTYPE hooked_create_buffer(ID3D11Device* self, const D3D11_BUFFER_DESC* desc,
                                                      const D3D11_SUBRESOURCE_DATA* init, ID3D11Buffer** out) {
    const HRESULT hr = reinterpret_cast<CreateBufferFn>(g_next_create_buffer.load(std::memory_order_acquire))(self, desc, init, out);
    if (SUCCEEDED(hr) && out && *out && desc && desc->ByteWidth && init && init->pSysMem &&
        (desc->BindFlags & (D3D11_BIND_VERTEX_BUFFER | D3D11_BIND_INDEX_BUFFER)) &&
        !(desc->BindFlags & (D3D11_BIND_CONSTANT_BUFFER | D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_STREAM_OUTPUT)) &&  // GPU-writable: no hook sees those writes
        permitted.load(std::memory_order_acquire)) try {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        if (permitted.load(std::memory_order_acquire) && !find_shadow(*out)) {
            std::vector<unsigned char> bytes(static_cast<const unsigned char*>(init->pSysMem),
                                             static_cast<const unsigned char*>(init->pSysMem) + desc->ByteWidth);
            Shadow& shadow = new_shadow(*out, *desc, false);
            shadow.bytes.swap(bytes);
            shadow_bytes += shadow.bytes.size();
            shadow.used = ++shadow_clock;
            created_captures.fetch_add(1, std::memory_order_relaxed);
            trim_shadows();
        }
    } catch (...) {}
    return hr;
}

inline HRESULT STDMETHODCALLTYPE hooked_map(ID3D11DeviceContext* self, ID3D11Resource* resource, UINT subresource,
                                            D3D11_MAP type, UINT flags, D3D11_MAPPED_SUBRESOURCE* mapped_data) {
    const HRESULT hr = reinterpret_cast<MapFn>(g_next_map.load(std::memory_order_acquire))(self, resource, subresource, type, flags, mapped_data);
    if (permitted.load(std::memory_order_acquire) && SUCCEEDED(hr) && mapped_data && resource && subresource == 0 &&
        (type == D3D11_MAP_WRITE_DISCARD || type == D3D11_MAP_WRITE || type == D3D11_MAP_WRITE_NO_OVERWRITE)) {
        try {
            std::lock_guard<std::recursive_mutex> lock(mutex());
            mapped()[resource] = mapped_data->pData;
        } catch (...) {}
    }
    return hr;
}

inline void STDMETHODCALLTYPE hooked_unmap(ID3D11DeviceContext* self, ID3D11Resource* resource, UINT subresource) {
    if (resource && subresource == 0 && permitted.load(std::memory_order_acquire)) try {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        const auto entry = mapped().find(resource);
        if (entry != mapped().end()) {
            ID3D11Buffer* buffer = nullptr;
            if (SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Buffer), reinterpret_cast<void**>(&buffer))) && buffer) {
                D3D11_BUFFER_DESC desc{};
                buffer->GetDesc(&desc);
                // A mapped buffer pointer always spans ByteWidth (unlike UpdateSubresource's source), so the whole
                // copy is in bounds. WRITE_DISCARD hands back the full buffer; the other modes write in place.
                note_write(buffer, entry->second, desc.ByteWidth);
                buffer->Release();
            }
            mapped().erase(entry);
        }
    } catch (...) {}
    reinterpret_cast<UnmapFn>(g_next_unmap.load(std::memory_order_acquire))(self, resource, subresource);
}

inline void STDMETHODCALLTYPE hooked_update(ID3D11DeviceContext* self, ID3D11Resource* resource, UINT dst_subresource,
                                            const D3D11_BOX* box, const void* data, UINT row_pitch, UINT depth_pitch) {
    if (resource && dst_subresource == 0 && data && permitted.load(std::memory_order_acquire)) try {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        ID3D11Buffer* buffer = nullptr;
        // Re-checked under the lock: a teardown in between must not be followed by a new shadow (a new reference).
        if (permitted.load(std::memory_order_acquire) && SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Buffer), reinterpret_cast<void**>(&buffer))) && buffer) {
            D3D11_BUFFER_DESC desc{};
            buffer->GetDesc(&desc);
            if (!box) {
                note_write(buffer, data, desc.ByteWidth, false);
            } else if (box->left < box->right && box->right <= desc.ByteWidth) {
                // `data` holds only the boxed bytes: copy exactly those into an existing shadow. Without a shadow
                // there is nothing to patch; the next use reads the buffer once and sees the update.
                if (Shadow* shadow = find_shadow(buffer)) {
                    if (shadow->bytes.size() == desc.ByteWidth) {
                        std::memcpy(shadow->bytes.data() + box->left, data, box->right - box->left);
                        shadow->written = true;   // the game writes it: its bytes must never be dropped
                        shadow->trimmable = false;
                        ++shadow->generation;
                        shadow->used = ++shadow_clock;
                        shadow->used_frame = frame_number;
                    } else {
                        invalidate_shadow(buffer);  // bytes not resident: cannot patch, so read again later
                    }
                }
            } else {
                invalidate_shadow(buffer);  // malformed box: drop rather than guess
            }
            buffer->Release();
        }
    } catch (...) {}
    reinterpret_cast<UpdateSubresourceFn>(g_next_update.load(std::memory_order_acquire))(
        self, resource, dst_subresource, box, data, row_pitch, depth_pitch);
}

inline void STDMETHODCALLTYPE hooked_copy_resource(ID3D11DeviceContext* self, ID3D11Resource* dst, ID3D11Resource* src) {
    if (permitted.load(std::memory_order_acquire)) try {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        invalidate_shadow(dst);  // contents now mirror src; drop rather than track aliases
    } catch (...) {}
    reinterpret_cast<CopyResourceFn>(g_next_copy.load(std::memory_order_acquire))(self, dst, src);
}

inline void STDMETHODCALLTYPE hooked_copy_region(ID3D11DeviceContext* self, ID3D11Resource* dst, UINT dst_sub,
                                                 UINT dst_x, UINT dst_y, UINT dst_z, ID3D11Resource* src, UINT src_sub,
                                                 const D3D11_BOX* box) {
    if (permitted.load(std::memory_order_acquire)) try {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        invalidate_shadow(dst);
    } catch (...) {}
    reinterpret_cast<CopySubresourceRegionFn>(g_next_copy_region.load(std::memory_order_acquire))(
        self, dst, dst_sub, dst_x, dst_y, dst_z, src, src_sub, box);
}

// ---- textures ----------------------------------------------------------------------------------
// Mip 0 of a PS material texture, written once per resource as a DDS the Remix runtime can load. Each one is a GPU
// readback and a file write on the game's thread, so they are rate-limited per frame and capped on disk.
enum class TextureResult { Captured, Unusable, Deferred };

inline TextureResult write_texture(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Resource* resource,
                                   std::uint32_t& id) {
    if (texture_dir.empty() || texture_bytes_written >= texture_disk_budget) return TextureResult::Unusable;
    if (textures_this_frame >= textures_per_frame) return TextureResult::Deferred;
    ID3D11Texture2D* texture = nullptr;
    if (FAILED(resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture))) || !texture)
        return TextureResult::Unusable;
    D3D11_TEXTURE2D_DESC desc{};
    texture->GetDesc(&desc);
    const UINT dynamic_binds = D3D11_BIND_RENDER_TARGET | D3D11_BIND_DEPTH_STENCIL | D3D11_BIND_UNORDERED_ACCESS;
    TextureResult result = TextureResult::Unusable;
    texture_capture::Texture pixels;
    if (!(desc.BindFlags & dynamic_binds) && desc.Usage != D3D11_USAGE_DYNAMIC && desc.SampleDesc.Count == 1) {
        ++textures_this_frame;
        const unsigned long long started = now_us();
        const bool read = texture_capture::read_mip0(device, context, texture, desc, pixels);
        texture_us_total.fetch_add(now_us() - started, std::memory_order_relaxed);
        if (read) {
            const std::uint32_t assigned = next_texture_id;
            wchar_t name[64];
            swprintf(name, 64, L"\\live_%u.dds", assigned);
            const std::wstring path = texture_dir + name;
            if (texture_capture::write_dds(path.c_str(), pixels)) {
                all_textures().push_back(TextureFile{assigned, path});
                texture_bytes_written += pixels.bytes.size();
                id = assigned;
                ++next_texture_id;
                result = TextureResult::Captured;
            }
        }
    }
    texture->Release();
    return result;
}

inline unsigned max_draws = 4096;

inline unsigned min_index_count = 128;

inline void begin_frame(ID3D11DeviceContext* context, unsigned width = 0, unsigned height = 0) {
    // No frame opens behind the F10 original view, so nothing is captured and no empty frame reaches the latch.
    if (!permitted.load(std::memory_order_acquire) || suspended.load(std::memory_order_acquire)) return;
    {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        previous_max_viewport = building().max_viewport;
        building() = Frame{};  // built_versions() survives: a geometry is rebuilt only when its buffers change
        building().scene_w = scene_width;
        building().scene_h = scene_height;
        if (width && height) { final_width = width; final_height = height; }
        ++frame_number;
        textures_this_frame = 0;
        lights_read = false;
        read_bytes_this_frame = 0;
        target_sizes().clear();
        skinned_occurrences().clear();
        expire_entries();
    }
    active_context.store(context, std::memory_order_release);
    frame_open.store(true, std::memory_order_release);
}

inline bool end_frame() {
    if (!frame_open.exchange(false, std::memory_order_acq_rel)) return false;
    active_context.store(nullptr, std::memory_order_release);
    std::lock_guard<std::recursive_mutex> lock(mutex());
    Frame& done = building();
    // A frame the filter emptied means the scene target was chosen wrong: latch the filter off rather than
    // alternating between a full and an empty picture. Three in a row, because an empty frame at a level load
    // or a resolution change is normal and those are scattered over a session.
    publish_ui();
    if (scene_target_enabled && done.items.empty() && done.skipped_pass) {
        ++scene_target_fallbacks;
        if (++scene_target_empty_streak >= 3) {
            scene_target_enabled = false;
            scene_width = scene_height = 0;
            scene_target_latched.store(true, std::memory_order_release);
        }
    } else if (!done.items.empty()) {
        scene_target_empty_streak = 0;
    }
    choose_scene_target();
    done.scene_w = scene_width;
    done.scene_h = scene_height;
    done.target_fallbacks = scene_target_fallbacks;
    done.sequence = ready_sequence.load() + 1;
    ready() = std::move(done);
    done = Frame{};
    ready_sequence.store(ready().sequence, std::memory_order_release);
    return true;
}

// ---- pixel-shader alpha test --------------------------------------------------------------------
// Each pixel shader is disassembled once, the first time a scene draw uses it (23 per frame in the real capture),
// with d3dcompiler_47 resolved at runtime like the overlay's D3DCompile: the DLL gains no import. No compiler, no
// bytecode, or a failed disassembly all mean "no alpha test": the draw stays opaque, as before.
using DisassembleFn = HRESULT (WINAPI*)(LPCVOID, SIZE_T, UINT, LPCSTR, ID3DBlob**);
inline DisassembleFn disassembler() {
    static const DisassembleFn fn = [] {
        HMODULE m = LoadLibraryExW(L"d3dcompiler_47.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        FARPROC p = m ? GetProcAddress(m, "D3DDisassemble") : nullptr;
        DisassembleFn f = nullptr;
        std::memcpy(&f, &p, sizeof f);
        return f;
    }();
    return fn;
}
inline std::map<ID3D11PixelShader*, alpha_test::Result>& alpha_tests() {
    static std::map<ID3D11PixelShader*, alpha_test::Result> m;
    return m;
}
// shortcut: keyed by shader pointer without a reference; a released shader's address reused by another would keep the
// first one's answer. NieR creates its pixel shaders at load and keeps them; upgrade if live runs show otherwise.
inline alpha_test::Result pixel_alpha_test(ID3D11DeviceContext* context) {
    ID3D11PixelShader* ps = nullptr;
    context->PSGetShader(&ps, nullptr, nullptr);
    if (!ps) return {};
    alpha_test::Result result;
    const auto known = alpha_tests().find(ps);
    if (known != alpha_tests().end()) {
        result = known->second;
    } else {
        std::vector<unsigned char> bytecode;
        ID3DBlob* text = nullptr;
        if (shader_capture::lookup(ps, bytecode) && disassembler() &&
            SUCCEEDED(disassembler()(bytecode.data(), bytecode.size(), 0, nullptr, &text)) && text) {
            result = alpha_test::parse(std::string(static_cast<const char*>(text->GetBufferPointer()), text->GetBufferSize()));
        }
        if (text) text->Release();
        if (alpha_tests().size() > 65536) alpha_tests().clear();  // bounded, like the other caches
        alpha_tests()[ps] = result;
    }
    ps->Release();
    return result;
}

// ---- draw observation --------------------------------------------------------------------------
inline void release_all(ID3D11Buffer** buffers, unsigned count, ID3D11Buffer* ib, ID3D11InputLayout* layout) {
    for (unsigned i = 0; i < count; ++i) if (buffers[i]) buffers[i]->Release();
    if (ib) ib->Release();
    if (layout) layout->Release();
}

// One draw -> one Item plus, when the geometry or its buffers changed, one compact Upload.
inline void observe(ID3D11DeviceContext* context, UINT index_count, UINT start_index, INT base_vertex,
                    UINT instance_count, UINT start_instance) {
    if (!permitted.load(std::memory_order_acquire) || suspended.load(std::memory_order_acquire) ||
        !frame_open.load(std::memory_order_acquire)) return;
    if (!context || active_context.load(std::memory_order_acquire) != context) return;
    if (!instance_count) return;  // zero instances draws nothing
    // The HUD is drawn as short indexed quads (often 6 indices), so the world-geometry minimum cannot apply to it.
    // Both discriminators are cheap: the bound blend state and the bound render target.
    ID3D11RenderTargetView* early_rtv = nullptr;
    context->OMGetRenderTargets(1, &early_rtv, nullptr);
    const std::pair<unsigned, unsigned> early_target = target_size(early_rtv);
    if (early_rtv) early_rtv->Release();
    bool blended = false;
    {
        ID3D11BlendState* blend = nullptr;
        context->OMGetBlendState(&blend, nullptr, nullptr);
        if (blend) {
            D3D11_BLEND_DESC desc{};
            blend->GetDesc(&desc);
            const D3D11_RENDER_TARGET_BLEND_DESC& rt = desc.RenderTarget[0];
            blended = desc.AlphaToCoverageEnable == FALSE && rt.BlendEnable && rt.BlendOp == D3D11_BLEND_OP_ADD &&
                      rt.SrcBlend == D3D11_BLEND_SRC_ALPHA && rt.DestBlend == D3D11_BLEND_INV_SRC_ALPHA;
            blend->Release();
        }
    }
    // A scene target the size of the final image (native scale) cannot be told apart from the HUD's by size: then the
    // HUD is not captured rather than taking the scene's blended draws for sprites.
    // shortcut: at native scale a blended HUD element of >= min_index_count indices is submitted as world geometry;
    // telling the swapchain buffer from the scene target by resource would fix it. Upgrade if native scale is played.
    const std::pair<unsigned, unsigned> final_size{final_width, final_height};
    const bool ui_pass = hud_enabled && scene_target_enabled && scene_width && final_width && blended &&
                         early_target == final_size && std::pair<unsigned, unsigned>{scene_width, scene_height} != final_size;
    if (!ui_pass && index_count < min_index_count) return;
    D3D11_PRIMITIVE_TOPOLOGY topology = D3D11_PRIMITIVE_TOPOLOGY_UNDEFINED;
    context->IAGetPrimitiveTopology(&topology);
    if (topology != D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST) return;  // strips/lines/points are not triangle lists

    ID3D11InputLayout* layout = nullptr;
    context->IAGetInputLayout(&layout);
    ID3D11Buffer* vbs[4] = {};
    UINT strides[4] = {}, offsets[4] = {};
    context->IAGetVertexBuffers(0, 4, vbs, strides, offsets);
    ID3D11Buffer* ib = nullptr;
    DXGI_FORMAT ib_format = DXGI_FORMAT_UNKNOWN;
    UINT ib_offset = 0;
    context->IAGetIndexBuffer(&ib, &ib_format, &ib_offset);
    input_layout_hook::Layout elements;
    const bool have_layout = input_layout_hook::lookup(layout, elements);
    unsigned vb_count = 0;
    for (unsigned i = 0; i < 4; ++i) if (vbs[i]) vb_count = i + 1;
    bool hole = false;  // a null slot below a bound one: never seen in NieR's captures; skip it before any read
    for (unsigned i = 0; i < vb_count; ++i) hole = hole || !vbs[i];
    if (!ib || !vb_count || hole || !have_layout || (ib_format != DXGI_FORMAT_R32_UINT && ib_format != DXGI_FORMAT_R16_UINT)) {
        release_all(vbs, 4, ib, layout);
        return;
    }

    // Skinned: drawn as a bind-pose mesh with the frame's bone palette (see below).
    bool skinned = false;
    for (const auto& e : elements.elements)
        if (e.semantic == "BLENDINDICES" || e.semantic == "BLENDWEIGHT") skinned = true;

    const unsigned index_width = ib_format == DXGI_FORMAT_R16_UINT ? 2 : 4;
    std::uint64_t key = 1469598103934665603ull;
    for (unsigned i = 0; i < vb_count; ++i) {
        const std::uint64_t pointer = static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(vbs[i]));
        key = hash_mix(key, &pointer, sizeof pointer);
        key = hash_value(key ^ strides[i]);
        key = hash_value(key ^ offsets[i]);
    }
    const std::uint64_t ib_pointer = static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(ib));
    key = hash_mix(key, &ib_pointer, sizeof ib_pointer);
    key = hash_value(key ^ ib_offset);
    key = hash_value(key ^ static_cast<std::uint64_t>(ib_format));
    key = hash_value(key ^ index_count);
    key = hash_value(key ^ start_index);
    key = hash_value(key ^ static_cast<std::uint64_t>(static_cast<std::uint32_t>(base_vertex)));
    key = hash_value(key ^ static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(layout)));
    std::uint64_t geometry = key;

    D3D11_VIEWPORT viewport{};
    UINT viewports = 1;
    context->RSGetViewports(&viewports, &viewport);
    const float viewport_area = viewport.Width * viewport.Height;


    // Render-target filter (see the render-target block above): count every candidate draw per target, then keep
    // only the scene target. This runs before any buffer read or material work, so a skipped pass costs one call.
    // Draws into the final image, alpha blended, are the HUD: they are not world geometry (the scene filter drops
    // them) but they must be replayed over the Remix image, so they are captured separately instead of discarded.
    const std::pair<unsigned, unsigned> target = early_target;
    {
        std::lock_guard<std::recursive_mutex> lock(mutex());
        ++target_counts()[target];
        if (scene_target_enabled && scene_width && target != std::pair<unsigned, unsigned>{scene_width, scene_height} && !ui_pass) {
            ++building().skipped_pass;
            release_all(vbs, 4, ib, layout);
            return;
        }
    }

    // NieR's depth pre-pass: every opaque mesh is drawn into the scene target twice, first with a layout that carries
    // only POSITION (+ bone data when skinned), then with its full layout. Four real captures: 38-42% of scene draws,
    // every one with a full-layout twin later in the frame (test_prepass_rule_captures.py). Submitted, the pre-pass copy
    // is a flat shell with no UVs or normals over every object, and doubles the mesh set.
    if (!ui_pass) {
        bool surface = false;
        for (const auto& e : elements.elements)
            surface = surface || e.semantic == "TEXCOORD" || e.semantic == "NORMAL" || e.semantic == "TANGENT" ||
                      e.semantic == "COLOR";  // kSurfaceSemantics: keep in step with test_prepass_rule_captures.py
        if (!surface) {
            std::lock_guard<std::recursive_mutex> lock(mutex());
            ++building().skipped_prepass;
            release_all(vbs, 4, ib, layout);
            return;
        }
    }

    ID3D11Device* device = nullptr;
    context->GetDevice(&device);
    if (!device) { release_all(vbs, 4, ib, layout); return; }

    std::lock_guard<std::recursive_mutex> lock(mutex());
    // A teardown (set_permitted(false)) may have run since the check at the top: take no new references after it.
    if (!permitted.load(std::memory_order_acquire)) { release_all(vbs, 4, ib, layout); device->Release(); return; }
    Frame& frame = building();
    if (viewport_area > frame.max_viewport) frame.max_viewport = viewport_area;
    const float reference = std::max(frame.max_viewport, previous_max_viewport);
    if (reference > 0.f && viewport_area * 100.f < reference * 25.f) ++frame.small_viewport;
    if (frame.items.size() >= max_draws) { ++frame.skipped; release_all(vbs, 4, ib, layout); device->Release(); return; }
    ++frame.draws;
    if (skinned) ++frame.skinned;

    // CB11: instance world matrices (64-byte stride) or a bone palette (48-byte stride).
    ID3D11Buffer* cb11 = nullptr;
    context->VSGetConstantBuffers(11, 1, &cb11);
    struct ReleaseOnExit { ID3D11Buffer* p; ~ReleaseOnExit() { if (p) p->Release(); } } cb11_guard{cb11};
    const std::vector<unsigned char>* constants = cb11 ? buffer_bytes(device, context, cb11) : nullptr;
    const unsigned bone_count = skinned && constants
        ? static_cast<unsigned>(std::min<std::size_t>(256, constants->size() / 48)) : 0;
    if (skinned && !bone_count) { ++frame.skipped; release_all(vbs, 4, ib, layout); device->Release(); return; }
    if (!constants) { ++frame.skipped_untransformed; release_all(vbs, 4, ib, layout); device->Release(); return; }
    // Baked characters sharing VB/IB can have different poses in the same frame; never alias their meshes. The key is
    // the draw plus its occurrence in this frame, not the pose: a pose-keyed mesh per animation frame filled the mesh
    // budget and evicted the static world (live 2026-10-29: 59917 built, 56915 evicted). The pose goes into the
    // version instead, so a new pose rebuilds and replaces the mesh under the same key.
    // shortcut: if the game reorders identical characters between frames, their keys swap and both rebuild each frame.
    std::uint64_t pose = 0;
    if (skinned) {
        geometry = hash_value(geometry ^ (0x5c1d000000000000ull + skinned_occurrences()[geometry]++));
        pose = hash_mix(1469598103934665603ull, constants->data(), 48ull * bone_count);
    }

    std::uint32_t texture = 0;
    bool texture_deferred = false;
    {
        ID3D11ShaderResourceView* views[16] = {};
        context->PSGetShaderResources(0, 16, views);
        for (unsigned slot = 0; slot < 16; ++slot) {
            if (!views[slot]) continue;
            ID3D11Resource* resource = nullptr;
            views[slot]->GetResource(&resource);
            if (resource && !texture && !texture_deferred) {  // first usable PS texture is the material albedo
                const auto known = texture_ids().find(resource);
                if (known != texture_ids().end()) {
                    known->second.used_frame = frame_number;
                    texture = known->second.id;
                } else {
                    std::uint32_t id = 0;
                    const TextureResult result = write_texture(device, context, resource, id);
                    if (result == TextureResult::Deferred) {
                        texture_deferred = true;  // the texture lands later; this geometry is uploaded without it for now
                        auto& waiters = waiting_materials();
                        if (waiters.size() > 65536) waiters.clear();  // bounded, like the other caches
                        auto& keys = waiters[resource];
                        if (std::find(keys.begin(), keys.end(), geometry) == keys.end()) keys.push_back(geometry);
                    } else {
                        resource->AddRef();  // the key keeps the pointer from being reused while the entry exists
                        texture_ids()[resource] = TextureEntry{id, frame_number};
                        texture = id;
                        if (id) {  // the texture has landed: rebuild the meshes that were made without it
                            const auto waiter = waiting_materials().find(resource);
                            if (waiter != waiting_materials().end()) {
                                for (const std::uint64_t key : waiter->second) { built_versions().erase(key); content_hashes().erase(key); }
                                waiting_materials().erase(waiter);
                            }
                        }
                    }
                }
            }
            if (resource) resource->Release();
        }
        for (unsigned slot = 0; slot < 16; ++slot)
            if (views[slot]) views[slot]->Release();  // GetShaderResources added one reference each
    }

    // Alpha test from the game's own pixel shader (foliage, grass cards, decals): NieR discards, it does not blend.
    const alpha_test::Result alpha = pixel_alpha_test(context);
    if (alpha.discards) ++frame.alpha_tested;

    // The game's light arrays (tiled forward): point lights at PS slot 20 (48-byte elements), spot lights at slot 22
    // (80-byte). Frame-level, not per-draw: the first scene draw that has slot 20 bound reads both for the whole frame;
    // a draw without it (the sky, a depth-only pass) does not spend the read. Structured-buffer views come as BUFFER or
    // BUFFEREX (same FirstElement/NumElements layout); the earlier reader took BUFFER only and saw no lights live.
    if (!lights_read) {
        const auto read_array = [&](UINT slot, std::size_t stride, bool spot, unsigned shift) {
            ID3D11ShaderResourceView* srv = nullptr;
            context->PSGetShaderResources(slot, 1, &srv);
            if (!srv) return false;
            frame.light_state |= 1u << shift;
            D3D11_SHADER_RESOURCE_VIEW_DESC vsd{};
            srv->GetDesc(&vsd);
            ID3D11Resource* resource = nullptr;
            srv->GetResource(&resource);
            const bool buffer_view = vsd.ViewDimension == D3D11_SRV_DIMENSION_BUFFER ||
                                     vsd.ViewDimension == D3D11_SRV_DIMENSION_BUFFEREX;
            ID3D11Buffer* buffer = nullptr;
            if (buffer_view && resource &&
                SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Buffer), reinterpret_cast<void**>(&buffer))) && buffer) {
                frame.light_state |= 2u << shift;
                D3D11_BUFFER_DESC bdesc{};
                buffer->GetDesc(&bdesc);
                if (bdesc.StructureByteStride == stride) {
                    frame.light_state |= 4u << shift;
                    // BUFFER and BUFFEREX share the leading FirstElement/NumElements fields of the union.
                    const std::size_t first = vsd.Buffer.FirstElement, count = vsd.Buffer.NumElements;
                    if (const std::vector<unsigned char>* b = count ? buffer_bytes(device, context, buffer) : nullptr) {
                        frame.light_state |= 8u << shift;
                        light_convert::parse(b->data(), b->size(), stride, first, count, spot, frame.lights);
                    }
                }
                buffer->Release();
            }
            if (resource) resource->Release();
            srv->Release();  // GetShaderResources added one reference
            return true;
        };
        frame.lights.clear();
        if (read_array(20, light_convert::kPointStride, false, 0)) {
            lights_read = true;
            read_array(22, light_convert::kSpotStride, true, 4);
        }
    }

    // Identity of the geometry's buffers, without touching their bytes. Bytes are needed only to (re)build, so
    // already-built geometry costs nothing per frame even when its static bytes were dropped under the budget.
    // HUD pass: decode now and keep the quad for the replay. Deliberately outside the geometry cache: sprite
    // vertices change every frame (text, bars, dialogue), so there is nothing worth caching.
    Pin pinned;  // from here on several buffer_bytes() results are held at once: nothing may be trimmed under them
    if (ui_pass) {
        const std::vector<unsigned char>* ib_bytes = buffer_bytes(device, context, ib);
        const std::vector<unsigned char>* vb_bytes[4] = {};
        bool readable = ib_bytes != nullptr;
        for (unsigned i = 0; i < vb_count && readable; ++i) {
            vb_bytes[i] = buffer_bytes(device, context, vbs[i]);
            readable = vb_bytes[i] != nullptr;
        }
        if (readable) {
            live_decode::Slot decode_slots[4];
            for (unsigned i = 0; i < vb_count; ++i)
                decode_slots[i] = {vb_bytes[i]->data(), vb_bytes[i]->size(), strides[i], offsets[i]};
            std::vector<live_decode::Element> decode_elements;
            decode_elements.reserve(elements.elements.size());
            for (const auto& e : elements.elements)
                decode_elements.push_back({e.semantic, static_cast<int>(e.format), e.offset, e.slot,
                                           e.slot_class == D3D11_INPUT_PER_INSTANCE_DATA});
            const std::size_t first_index = static_cast<std::size_t>(ib_offset) + static_cast<std::size_t>(start_index) * index_width;
            live_decode::Output decoded;
            if (live_decode::build(decode_slots, vb_count, decode_elements, ib_bytes->data(), ib_bytes->size(),
                                   index_width, first_index, index_count, base_vertex, 0, false, decoded) &&
                !decoded.indices.empty()) {
                std::lock_guard<std::recursive_mutex> lock(mutex());
                UiSnapshot& ui_frame = ui_building();
                ID3D11ShaderResourceView* ui_srv = nullptr;
                context->PSGetShaderResources(0, 1, &ui_srv);  // the sprite's own texture, kept referenced until drawn
                UiDraw draw;
                draw.first = static_cast<unsigned>(ui_frame.verts.size());
                draw.count = static_cast<unsigned>(decoded.indices.size());
                draw.texture = texture;
                if (constants && constants->size() >= sizeof draw.world)
                    std::memcpy(draw.world, constants->data(), sizeof draw.world);
                else {
                    const float identity12[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
                    std::memcpy(draw.world, identity12, sizeof draw.world);
                }
                for (const std::uint32_t index : decoded.indices) {
                    if (index >= decoded.vertices.size()) break;
                    UiVertex v;
                    std::memcpy(v.position, decoded.vertices[index].position, sizeof v.position);
                    std::memcpy(v.texcoord, decoded.vertices[index].texcoord, sizeof v.texcoord);
                    ui_frame.verts.push_back(v);
                }
                ui_frame.draws.push_back(draw);
                ui_frame.srvs.push_back(ui_srv);  // may be null: the replay skips those
            }
        }
        release_all(vbs, 4, ib, layout);
        device->Release();
        return;
    }

    std::uint64_t version = 0;
    bool unknown = identity(ib) == 0;
    for (unsigned i = 0; i < vb_count; ++i) unknown = unknown || identity(vbs[i]) == 0;
    const auto version_now = [&] {
        std::uint64_t v = identity(ib);
        for (unsigned i = 0; i < vb_count; ++i) v = hash_value(v ^ identity(vbs[i]));
        return skinned ? hash_value(v ^ pose) : v;
    };
    version = version_now();
    const auto previously = built_versions().find(geometry);
    const auto resident = [](ID3D11Buffer* b) { const Shadow* sh = find_shadow(b); return sh && !sh->bytes.empty(); };
    bool sky_extent = false;  // decoded geometry's world extent says this is the background shell
    bool needs_read = !resident(ib);
    for (unsigned i = 0; i < vb_count; ++i) needs_read = needs_read || !resident(vbs[i]);
    const bool changed = previously != built_versions().end() && previously->second != version;
    // A deferred texture must not hold the geometry back: it is uploaded without a material for now, and the
    // texture's arrival invalidates it (waiting_materials) so the next draw rebuilds the mesh with the material.
    const bool deferred = !changed && needs_read && read_bytes_this_frame >= read_budget_per_frame;
    const bool rebuild = !deferred && (unknown || previously == built_versions().end() || previously->second != version);
    const std::vector<unsigned char>* ib_bytes = nullptr;
    const std::vector<unsigned char>* vb_bytes[4] = {};
    bool readable = false;
    if (rebuild) {
        ib_bytes = buffer_bytes(device, context, ib);
        readable = ib_bytes != nullptr;
        for (unsigned i = 0; i < vb_count && readable; ++i) {
            vb_bytes[i] = buffer_bytes(device, context, vbs[i]);
            readable = vb_bytes[i] != nullptr;
        }
        version = version_now();  // a first read creates the identities
    }

    if (rebuild && readable) {
        // One decode implementation, also exercised against real captured draws by
        // analysis/checks/test_live_vertex_decode.py. Every slot below vb_count was read successfully here.
        live_decode::Slot decode_slots[4];
        for (unsigned i = 0; i < vb_count; ++i)
            decode_slots[i] = {vb_bytes[i]->data(), vb_bytes[i]->size(), strides[i], offsets[i]};
        std::vector<live_decode::Element> decode_elements;
        decode_elements.reserve(elements.elements.size());
        for (const auto& e : elements.elements)
            decode_elements.push_back({e.semantic, static_cast<int>(e.format), e.offset, e.slot,
                                       e.slot_class == D3D11_INPUT_PER_INSTANCE_DATA});
        const std::size_t first_index = static_cast<std::size_t>(ib_offset) + static_cast<std::size_t>(start_index) * index_width;
        live_decode::Output decoded;
        bool ok = live_decode::build(decode_slots, vb_count, decode_elements, ib_bytes->data(),
                                                      ib_bytes->size(), index_width, first_index, index_count,
                                                      base_vertex, bone_count, skinned, decoded);
        if (ok && skinned) ok = live_skinning::bake(decoded, constants->data(), 48ull * bone_count);
        if (ok && !decoded.indices.empty()) {
            // World-space extent of the first instance, exactly like the accepted captured-scene rule: a sky
            // dome only reveals itself after the world matrix, and local space alone would misjudge scaled meshes.
            float low[3] = {1e30f, 1e30f, 1e30f}, high[3] = {-1e30f, -1e30f, -1e30f};
            float world[12];
            const bool have_world = constants && constants->size() >= 48 && !skinned;
            if (have_world) std::memcpy(world, constants->data(), sizeof world);
            for (const auto& v : decoded.vertices) {
                float point[3] = {v.position[0], v.position[1], v.position[2]};
                if (have_world) {
                    float moved[3];
                    for (int r = 0; r < 3; ++r)
                        moved[r] = world[4 * r] * point[0] + world[4 * r + 1] * point[1] + world[4 * r + 2] * point[2] + world[4 * r + 3];
                    std::memcpy(point, moved, sizeof point);
                }
                for (int c = 0; c < 3; ++c) {
                    low[c] = std::min(low[c], point[c]);
                    high[c] = std::max(high[c], point[c]);
                }
            }
            const float extent = std::max({high[0] - low[0], high[1] - low[1], high[2] - low[2]});
            // Sky dome / background shell: recognised by its world extent (same rule as the captured-scene path). It
            // is not world geometry — ray tracing it encloses the camera — so it is submitted with the SKY category
            // instead of being dropped, which is what makes the background exist at all.
            sky_extent = extent > 5000.f;
            sky_geometries()[geometry] = sky_extent;
            std::uint64_t content = 1469598103934665603ull;
            content = hash_mix(content, decoded.vertices.data(), decoded.vertices.size() * sizeof(decoded.vertices[0]));
            content = hash_mix(content, decoded.indices.data(), decoded.indices.size() * sizeof(decoded.indices[0]));
            content = hash_mix(content, decoded.bones.data(), decoded.bones.size() * sizeof(decoded.bones[0]));
            content = hash_mix(content, decoded.weights.data(), decoded.weights.size() * sizeof(decoded.weights[0]));
            const auto known = content_hashes().find(geometry);
            const bool unchanged = previously != built_versions().end() && known != content_hashes().end() &&
                                   known->second == content;
            if (unchanged) {
                built_versions()[geometry] = version;  // the mesh on the GPU is already this geometry
                ++frame.rebuilt_identical;             // ... and the draw below still has to be emitted
            } else {
            content_hashes()[geometry] = content;

            Upload upload;
            upload.geometry = geometry;
            upload.texture = texture;
            upload.skinned = false;  // skinned draws were baked into world space above
            upload.blended = blended;
            upload.sky = sky_extent;
            if (alpha.discards) { upload.alpha_op = alpha.op; upload.alpha_ref = alpha.reference; }
            upload.vertices.resize(decoded.vertices.size());
            for (std::size_t i = 0; i < decoded.vertices.size(); ++i) {
                std::memcpy(upload.vertices[i].position, decoded.vertices[i].position, sizeof upload.vertices[i].position);
                std::memcpy(upload.vertices[i].normal, decoded.vertices[i].normal, sizeof upload.vertices[i].normal);
                std::memcpy(upload.vertices[i].texcoord, decoded.vertices[i].texcoord, sizeof upload.vertices[i].texcoord);
                upload.vertices[i].color = decoded.vertices[i].color;
            }
            upload.indices = std::move(decoded.indices);
            upload.bones = std::move(decoded.bones);
            upload.weights = std::move(decoded.weights);
            if (built_versions().size() > 200000) { built_versions().clear(); content_hashes().clear(); sky_geometries().clear(); }  // bounded; one rebuild each
            built_versions()[geometry] = version;
            const std::size_t bytes = upload.vertices.size() * sizeof(Vertex) + upload.indices.size() * 4 +
                                      upload.weights.size() * 4 + upload.bones.size() * 4;
            if (pending_bytes + bytes > max_pending_bytes) {
                // The worker is not draining (stalled or failed). Do not mark the geometry built, so it is
                // retried on a later frame instead of vanishing for the rest of the session.
                ++dropped_uploads;
                built_versions().erase(geometry);
            } else {
                pending_bytes += bytes;
                pending_uploads().push_back(std::move(upload));
            }
            }
        } else {
            ++frame.skipped;
            built_versions()[geometry] = version;  // do not retry a broken draw every frame
        }
    }

    Item item;
    item.geometry = geometry;
    item.texture = texture;
    item.blended = blended;
    const auto sky_known = sky_geometries().find(geometry);
    item.sky = sky_known != sky_geometries().end() && sky_known->second;
    if (item.sky && !sky_enabled) { ++frame.skipped_sky; release_all(vbs, 4, ib, layout); device->Release(); return; }
    if (item.sky) ++frame.sky;  // per draw, so the stats line shows the sky every frame, not only when it is built
    if (blended) ++frame.blended;
    if (!texture) ++frame.untextured;  // no material: distinguishes 'texture never written' from 'material not created'
    item.first = static_cast<unsigned>(frame.transforms.size() / 12);
    item.count = instance_count;
    if (skinned) {
        // Already world-space: no GPU skinning palette and no second world transform.
        item.count = 1;
        const float identity[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        frame.transforms.insert(frame.transforms.end(), identity, identity + 12);
    } else {
        for (unsigned i = 0; i < item.count; ++i) {
            const std::size_t offset = 64ull * (static_cast<std::size_t>(i) + start_instance);
            if (constants && constants->size() >= offset + 48) {
                float matrix[12];
                std::memcpy(matrix, constants->data() + offset, sizeof matrix);  // bytes, not byte values
                frame.transforms.insert(frame.transforms.end(), matrix, matrix + 12);
            } else {
                const float identity[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
                frame.transforms.insert(frame.transforms.end(), identity, identity + 12);
            }
        }
    }
    frame.items.push_back(item);
    if (!frame.has_sun && !item.sky) {
        // First scene draw with a verified PS CB2 sun (rgb, unit surface-to-light, w=0); dummy bindings fail parse.
        ID3D11Buffer* cb2 = nullptr;
        context->PSGetConstantBuffers(2, 1, &cb2);
        if (cb2) {
            if (const std::vector<unsigned char>* b = buffer_bytes(device, context, cb2))
                frame.has_sun = light_convert::parse_sun(b->data(), b->size(), frame.sun);
            cb2->Release();
        }
    }
    for (std::size_t i = published_textures; i < all_textures().size(); ++i) pending_textures().push_back(all_textures()[i]);
    published_textures = all_textures().size();
    release_all(vbs, 4, ib, layout);
    device->Release();
}

inline bool protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

// 0-based ID3D11DeviceContext vtable slots, verified against the mingw header with an offsetof probe
// (analysis/runtime/slots/slots.cpp): IUnknown 0..2, ID3D11DeviceChild 3..6, then the context methods.
// The live-camera gate re-runs that probe, so drift is caught by a test rather than by a wrong hook.
constexpr std::size_t kMap = 14;
constexpr std::size_t kUnmap = 15;
constexpr std::size_t kCopySubresourceRegion = 46;
constexpr std::size_t kCopyResource = 47;
constexpr std::size_t kUpdateSubresource = 48;
constexpr std::size_t kCreateBuffer = 3;  // ID3D11Device; checked by test_live_camera's offsetof probe

inline bool install(ID3D11DeviceContext* context) {
    if (!context) return false;
    static bool done = false;
    if (done) return true;
    done = true;
    void** table = *reinterpret_cast<void***>(context);
    const auto ok = [](vtable_hook::Result r) {
        return r == vtable_hook::Result::Hooked || r == vtable_hook::Result::AlreadyHooked ||
               r == vtable_hook::Result::RestoreFailed;
    };
    ID3D11Device* device = nullptr;
    context->GetDevice(&device);
    bool device_ok = false;
    if (device) {
        void** device_table = *reinterpret_cast<void***>(device);
        device_ok = ok(vtable_hook::hook(device_table, kCreateBuffer, reinterpret_cast<void*>(&hooked_create_buffer),
                                         g_next_create_buffer, protect));
        device->Release();
    }
    // Context hooks do not depend on the device hook: without CreateBuffer the old first-sight read still works.
    const bool context_ok =
           ok(vtable_hook::hook(table, kMap, reinterpret_cast<void*>(&hooked_map), g_next_map, protect)) &&
           ok(vtable_hook::hook(table, kUnmap, reinterpret_cast<void*>(&hooked_unmap), g_next_unmap, protect)) &&
           ok(vtable_hook::hook(table, kUpdateSubresource, reinterpret_cast<void*>(&hooked_update), g_next_update, protect)) &&
           ok(vtable_hook::hook(table, kCopyResource, reinterpret_cast<void*>(&hooked_copy_resource), g_next_copy, protect)) &&
           ok(vtable_hook::hook(table, kCopySubresourceRegion, reinterpret_cast<void*>(&hooked_copy_region), g_next_copy_region, protect));
    return context_ok && device_ok;
}

}  // namespace live_capture
