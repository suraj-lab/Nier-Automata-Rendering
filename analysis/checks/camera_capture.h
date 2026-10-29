#pragma once
// Camera-only observation, independent of F9: bounded CB0 readback, no geometry or texture capture.
#include <d3d11.h>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <mutex>
#include "camera_decode.h"

namespace camera_capture {
struct Snapshot {
    std::array<float, 14> camera{};
    std::uint64_t sequence = 0;
};

inline std::atomic<bool> permitted{false};
inline std::atomic<ID3D11DeviceContext*> active_context{nullptr};
inline std::atomic<bool> frame_open{false};
inline std::mutex frame_mutex, snapshot_mutex;
inline float expected_aspect = 0;
inline unsigned attempts = 0;
inline bool pending_valid = false;
inline std::array<float, 14> pending{};
inline Snapshot published;

// Enable once before starting the worker; failure revokes future observations without waiting on the GPU.
inline void set_enabled(bool enabled) {
    permitted.store(enabled, std::memory_order_release);
    if (!enabled) active_context.store(nullptr, std::memory_order_release);
}

inline void begin_frame(ID3D11DeviceContext* context, float aspect) {
    active_context.store(nullptr, std::memory_order_release);
    frame_open.store(false, std::memory_order_release);
    std::lock_guard<std::mutex> lock(frame_mutex);
    attempts = 0;
    pending_valid = false;
    expected_aspect = aspect;
    if (!context || !std::isfinite(aspect) || aspect <= 0 || !permitted.load(std::memory_order_acquire)) return;
    frame_open.store(true, std::memory_order_release);
    active_context.store(context, std::memory_order_release);
}

inline void end_frame() {
    if (!frame_open.exchange(false, std::memory_order_acq_rel)) return;
    active_context.store(nullptr, std::memory_order_release);
    std::lock_guard<std::mutex> lock(frame_mutex);
    if (!pending_valid || !permitted.load(std::memory_order_acquire)) { pending_valid = false; return; }
    std::lock_guard<std::mutex> snapshot_lock(snapshot_mutex);
    published.camera = pending;
    ++published.sequence;
    pending_valid = false;
}

inline Snapshot latest() {
    std::lock_guard<std::mutex> lock(snapshot_mutex);
    return published;
}

// Called with frame_mutex held; all COM references and mappings are released before decoding.
inline bool read_cb0(ID3D11DeviceContext* context, std::array<float, 14>& result) {
    ID3D11Buffer* source = nullptr;
    context->VSGetConstantBuffers(0, 1, &source);
    if (!source) return false;
    D3D11_BUFFER_DESC desc{};
    source->GetDesc(&desc);
    // shortcut: observed VS CB0 is 256 bytes; widen only after another layout is capture-verified.
    if (desc.ByteWidth != 256 || !(desc.BindFlags & D3D11_BIND_CONSTANT_BUFFER)) {
        source->Release();
        return false;
    }
    if (!permitted.load(std::memory_order_acquire)) { source->Release(); return false; }
    ++attempts;
    ID3D11Device* device = nullptr;
    context->GetDevice(&device);
    if (!device) { source->Release(); return false; }
    D3D11_BUFFER_DESC staging_desc{};
    staging_desc.ByteWidth = desc.ByteWidth;
    staging_desc.Usage = D3D11_USAGE_STAGING;
    staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Buffer* staging = nullptr;
    const HRESULT created = device->CreateBuffer(&staging_desc, nullptr, &staging);
    device->Release();
    if (FAILED(created) || !staging) {
        if (staging) staging->Release();
        source->Release();
        return false;
    }
    if (!permitted.load(std::memory_order_acquire)) { staging->Release(); source->Release(); return false; }
    context->CopyResource(staging, source);
    source->Release();
    D3D11_MAPPED_SUBRESOURCE mapped{};
    const HRESULT hr = context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) { staging->Release(); return false; }
    std::array<unsigned char, 128> bytes{};
    const bool readable = mapped.pData != nullptr;
    if (readable) std::memcpy(bytes.data(), mapped.pData, bytes.size());
    context->Unmap(staging, 0);
    staging->Release();
    return readable && permitted.load(std::memory_order_acquire) && camera_decode::decode(bytes.data(), bytes.size(), result);
}

inline void observe(ID3D11DeviceContext* context, UINT index_count) {
    if (index_count < 128 || !context || !permitted.load(std::memory_order_acquire) ||
        active_context.load(std::memory_order_acquire) != context) return;
    std::lock_guard<std::mutex> lock(frame_mutex);
    if (!permitted.load(std::memory_order_acquire) || !frame_open.load(std::memory_order_acquire) ||
        active_context.load(std::memory_order_acquire) != context) return;
    D3D11_VIEWPORT viewport{};
    UINT count = 1;
    context->RSGetViewports(&count, &viewport);
    if (!count || !std::isfinite(viewport.Width) || !std::isfinite(viewport.Height) ||
        viewport.Width < 320 || viewport.Height < 200) return;
    const float aspect = viewport.Width / viewport.Height;
    if (std::fabs(aspect - expected_aspect) > .02f * expected_aspect) return;
    std::array<float, 14> camera{};
    if (read_cb0(context, camera) && std::fabs(camera[13] - expected_aspect) <= .02f * expected_aspect) {
        pending = camera;
        pending_valid = true;
        active_context.store(nullptr, std::memory_order_release); // at most one valid sample per game frame
    } else if (attempts >= 4) {
        active_context.store(nullptr, std::memory_order_release);
    }
}
} // namespace camera_capture
