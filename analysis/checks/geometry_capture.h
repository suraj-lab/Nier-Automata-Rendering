#pragma once
// Read back the currently-bound input-assembler geometry (raw vertex/index buffer bytes + stride/
// offset/format). This is the first half of the Remix object capture: it gets the bytes, but NOT the
// per-element vertex layout (position/normal/uv), which D3D11 does not expose from the bound layout
// and needs a follow-up via CreateInputLayout hooking or shader reflection.
#include <d3d11.h>
#include <cstdint>
#include <vector>

namespace geometry_capture {
struct VertexSlot {
    UINT slot = 0;
    UINT stride = 0;
    UINT offset = 0;
    UINT byte_width = 0;
    std::vector<unsigned char> bytes;
};
struct IndexSnap {
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    UINT offset = 0;
    UINT byte_width = 0;
    std::vector<unsigned char> bytes;
};
struct Capture {
    bool has_index = false;
    VertexSlot vertex[16];
    UINT vertex_count = 0;
    IndexSnap index;
    ID3D11InputLayout* layout = nullptr;  // resolve elements via input_layout_hook::lookup
};

// Copy a buffer to a staging buffer and read its bytes. Fails closed: any error clears `bytes`.
inline bool read_buffer(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Buffer* buffer,
                        UINT offset, UINT byte_width, std::vector<unsigned char>& bytes) {
    bytes.clear();
    if (!buffer || !byte_width) return false;
    D3D11_BUFFER_DESC desc{};
    buffer->GetDesc(&desc);
    if (desc.ByteWidth < offset + byte_width) return false;
    D3D11_BUFFER_DESC staging = desc;
    staging.Usage = D3D11_USAGE_STAGING;
    staging.BindFlags = 0;
    staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    staging.MiscFlags = 0;
    ID3D11Buffer* copy = nullptr;
    if (FAILED(device->CreateBuffer(&staging, nullptr, &copy)) || !copy) return false;
    context->CopyResource(copy, buffer);
    D3D11_MAPPED_SUBRESOURCE map{};
    if (FAILED(context->Map(copy, 0, D3D11_MAP_READ, 0, &map))) { copy->Release(); return false; }
    const auto* p = static_cast<const unsigned char*>(map.pData) + offset;
    bytes.assign(p, p + byte_width);
    context->Unmap(copy, 0);
    copy->Release();
    return true;
}

// Capture the current IA state. `vertex_slots` lists which vertex slots to try (default all 16).
// The vertex buffers are read in their ENTIRETY (full desc.ByteWidth) because the object's range is
// only knowable from the index values, which is a later offline step.
inline bool capture(ID3D11Device* device, ID3D11DeviceContext* context, Capture& out) {
    out = Capture{};
    ID3D11Buffer* buffers[16] = {};
    UINT strides[16] = {}, offsets[16] = {};
    context->IAGetVertexBuffers(0, 16, buffers, strides, offsets);
    for (UINT slot = 0; slot < 16; ++slot) {
        if (!buffers[slot]) continue;
        D3D11_BUFFER_DESC desc{};
        buffers[slot]->GetDesc(&desc);
        VertexSlot& v = out.vertex[out.vertex_count++];
        v.slot = slot;
        v.stride = strides[slot];
        v.offset = offsets[slot];
        v.byte_width = desc.ByteWidth;
        if (!read_buffer(device, context, buffers[slot], 0, desc.ByteWidth, v.bytes)) return false;
        buffers[slot]->Release();
    }
    ID3D11Buffer* ib = nullptr;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    UINT ib_offset = 0;
    context->IAGetIndexBuffer(&ib, &format, &ib_offset);
    if (ib) {
        D3D11_BUFFER_DESC desc{};
        ib->GetDesc(&desc);
        out.has_index = true;
        out.index.format = format;
        out.index.offset = ib_offset;
        out.index.byte_width = desc.ByteWidth;
        if (!read_buffer(device, context, ib, 0, desc.ByteWidth, out.index.bytes)) { ib->Release(); return false; }
        ib->Release();
    }
    context->IAGetInputLayout(&out.layout);
    return out.vertex_count > 0;
}
}  // namespace geometry_capture
