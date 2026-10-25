#pragma once
// Capture the pixel shader's bound material textures for a draw: static 2D textures only (render targets,
// depth and UAV-bound resources change during the frame and are not materials), mip 0 of slice 0, read
// back once per frame and written as DDS with a DX10 header so BC-compressed data stays compressed.
// No hooks: only PSGetShaderResources / CopySubresourceRegion / Map on the already-hooked context.
#include <d3d11.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <vector>

namespace texture_capture {

// Bytes per 4x4 block (BC) or per pixel (uncompressed); 0 = unsupported. `block` is 4 for BC, else 1.
struct FormatInfo { UINT bytes; UINT block; };
inline FormatInfo format_info(DXGI_FORMAT f) {
    switch (f) {
    case DXGI_FORMAT_BC1_TYPELESS: case DXGI_FORMAT_BC1_UNORM: case DXGI_FORMAT_BC1_UNORM_SRGB:
    case DXGI_FORMAT_BC4_TYPELESS: case DXGI_FORMAT_BC4_UNORM: case DXGI_FORMAT_BC4_SNORM:
        return {8, 4};
    case DXGI_FORMAT_BC2_TYPELESS: case DXGI_FORMAT_BC2_UNORM: case DXGI_FORMAT_BC2_UNORM_SRGB:
    case DXGI_FORMAT_BC3_TYPELESS: case DXGI_FORMAT_BC3_UNORM: case DXGI_FORMAT_BC3_UNORM_SRGB:
    case DXGI_FORMAT_BC5_TYPELESS: case DXGI_FORMAT_BC5_UNORM: case DXGI_FORMAT_BC5_SNORM:
    case DXGI_FORMAT_BC6H_TYPELESS: case DXGI_FORMAT_BC6H_UF16: case DXGI_FORMAT_BC6H_SF16:
    case DXGI_FORMAT_BC7_TYPELESS: case DXGI_FORMAT_BC7_UNORM: case DXGI_FORMAT_BC7_UNORM_SRGB:
        return {16, 4};
    case DXGI_FORMAT_R8G8B8A8_TYPELESS: case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_TYPELESS: case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8X8_UNORM: case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_R11G11B10_FLOAT:
    case DXGI_FORMAT_R16G16_FLOAT: case DXGI_FORMAT_R16G16_UNORM: case DXGI_FORMAT_R32_FLOAT:
        return {4, 1};
    case DXGI_FORMAT_R16G16B16A16_FLOAT: case DXGI_FORMAT_R16G16B16A16_UNORM: case DXGI_FORMAT_R32G32_FLOAT:
        return {8, 1};
    case DXGI_FORMAT_R8G8_UNORM: case DXGI_FORMAT_R16_FLOAT: case DXGI_FORMAT_R16_UNORM:
        return {2, 1};
    case DXGI_FORMAT_R8_UNORM: case DXGI_FORMAT_A8_UNORM:
        return {1, 1};
    default:
        return {0, 0};
    }
}

struct Texture {
    std::uint32_t id = 0;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    UINT width = 0, height = 0;
    UINT row_bytes = 0, rows = 0;  // tightly packed mip 0: rows of block rows (BC) or pixel rows
    std::vector<unsigned char> bytes;
};
struct Ref { UINT slot = 0; std::uint32_t id = 0; };

// One frame's textures. Keys hold a reference so a pointer cannot be reused until clear().
struct Cache {
    std::map<ID3D11Resource*, std::uint32_t> ids;  // 0 = seen but not capturable
    std::vector<Texture> textures;
    std::size_t bytes = 0;
    void clear() { for (auto& e : ids) e.first->Release(); ids.clear(); textures.clear(); bytes = 0; }
    Cache() = default;
    Cache(const Cache&) = delete;
    Cache& operator=(const Cache&) = delete;
    ~Cache() { clear(); }
};

inline bool read_mip0(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Texture2D* tex,
                      const D3D11_TEXTURE2D_DESC& desc, Texture& out) {
    const FormatInfo fi = format_info(desc.Format);
    if (!fi.bytes || !desc.Width || !desc.Height) return false;
    D3D11_TEXTURE2D_DESC sd = desc;
    sd.MipLevels = 1; sd.ArraySize = 1; sd.SampleDesc.Count = 1; sd.SampleDesc.Quality = 0;
    sd.Usage = D3D11_USAGE_STAGING; sd.BindFlags = 0; sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ; sd.MiscFlags = 0;
    ID3D11Texture2D* staging = nullptr;
    if (FAILED(device->CreateTexture2D(&sd, nullptr, &staging)) || !staging) return false;
    context->CopySubresourceRegion(staging, 0, 0, 0, 0, tex, D3D11CalcSubresource(0, 0, desc.MipLevels), nullptr);
    D3D11_MAPPED_SUBRESOURCE map{};
    if (FAILED(context->Map(staging, 0, D3D11_MAP_READ, 0, &map))) { staging->Release(); return false; }
    out.format = desc.Format; out.width = desc.Width; out.height = desc.Height;
    out.row_bytes = (desc.Width + fi.block - 1) / fi.block * fi.bytes;
    out.rows = (desc.Height + fi.block - 1) / fi.block;
    out.bytes.resize(std::size_t(out.row_bytes) * out.rows);
    for (UINT r = 0; r < out.rows; ++r)  // the mapped RowPitch may be padded; pack tightly
        std::memcpy(out.bytes.data() + std::size_t(r) * out.row_bytes,
                    static_cast<const unsigned char*>(map.pData) + std::size_t(r) * map.RowPitch, out.row_bytes);
    context->Unmap(staging, 0);
    staging->Release();
    return true;
}

// Record the PS material textures bound for the current draw. Reads each new static texture once per frame
// (stops reading new ones past `byte_budget`, recording id 0 for them). Never fails the draw capture.
inline void capture(ID3D11Device* device, ID3D11DeviceContext* context, Cache& cache, std::vector<Ref>& out,
                    std::size_t byte_budget) {
    out.clear();
    ID3D11ShaderResourceView* views[16] = {};
    context->PSGetShaderResources(0, 16, views);
    for (UINT slot = 0; slot < 16; ++slot) {
        if (!views[slot]) continue;
        ID3D11Resource* res = nullptr;
        views[slot]->GetResource(&res);
        views[slot]->Release();
        if (!res) continue;
        const auto it = cache.ids.find(res);
        if (it != cache.ids.end()) {
            if (it->second) out.push_back({slot, it->second});
            res->Release();
            continue;
        }
        std::uint32_t id = 0;
        ID3D11Texture2D* tex = nullptr;
        if (SUCCEEDED(res->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&tex))) && tex) {
            D3D11_TEXTURE2D_DESC desc{};
            tex->GetDesc(&desc);
            const UINT dynamic_binds = D3D11_BIND_RENDER_TARGET | D3D11_BIND_DEPTH_STENCIL | D3D11_BIND_UNORDERED_ACCESS;
            Texture t;
            if (!(desc.BindFlags & dynamic_binds) && desc.Usage != D3D11_USAGE_DYNAMIC && desc.SampleDesc.Count == 1 &&
                cache.bytes < byte_budget && read_mip0(device, context, tex, desc, t)) {
                id = t.id = static_cast<std::uint32_t>(cache.textures.size() + 1);
                cache.bytes += t.bytes.size();
                cache.textures.push_back(std::move(t));
            }
            tex->Release();
        }
        cache.ids.emplace(res, id);  // keeps the reference taken by GetResource
        if (id) out.push_back({slot, id});
    }
}

// DDS with a DX10 header (BC data kept as-is). Returns false on any write error.
inline bool write_dds(const wchar_t* path, const Texture& t) {
    FILE* f = _wfopen(path, L"wb");
    if (!f) return false;
    std::uint32_t h[32] = {};
    h[0] = 0x20534444;            // "DDS "
    h[1] = 124;                   // header size
    h[2] = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000;  // CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE
    h[3] = t.height; h[4] = t.width;
    h[5] = static_cast<std::uint32_t>(t.bytes.size());  // linear size of mip 0
    h[7] = 1;                     // mip count
    h[19] = 32;                   // pixel format size
    h[20] = 0x4;                  // DDPF_FOURCC
    h[21] = 0x30315844;           // "DX10"
    h[27] = 0x1000;               // DDSCAPS_TEXTURE
    const std::uint32_t dx10[5] = {static_cast<std::uint32_t>(t.format), 3 /*TEXTURE2D*/, 0, 1, 0};
    const bool ok = std::fwrite(h, 4, 32, f) == 32 && std::fwrite(dx10, 4, 5, f) == 5 &&
                    std::fwrite(t.bytes.data(), 1, t.bytes.size(), f) == t.bytes.size();
    return (std::fclose(f) == 0) && ok;
}

}  // namespace texture_capture
