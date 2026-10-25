#pragma once
// Convert captured vertex/index bytes + input-layout elements into Remix HardcodedVertex-compatible
// data. Pure byte parsing (little-endian D3D11), no D3D11 dependency, so it is CPU-testable.
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace geometry_convert {
// DXGI_FORMAT numeric values we parse.
constexpr int F_R32G32B32A32_FLOAT = 2;
constexpr int F_R32G32B32_FLOAT = 6;
constexpr int F_R16G16B16A16_FLOAT = 10;
constexpr int F_R32G32_FLOAT = 16;
constexpr int F_R8G8B8A8_UNORM = 28;
constexpr int F_R8G8B8A8_UINT = 30;
constexpr int F_R16G16_FLOAT = 34;

struct Element {
    std::string semantic;  // upper-cased, e.g. "POSITION", "NORMAL", "TEXCOORD", "COLOR"
    int format = 0;
    unsigned offset = 0;
};

struct Vertex {
    float position[3] = {0, 0, 0};
    float normal[3] = {0, 0, -1};
    float texcoord[2] = {0, 0};
    std::uint32_t color = 0xffffffff;
};

inline std::uint32_t read_u32(const unsigned char* p) { std::uint32_t v; std::memcpy(&v, p, 4); return v; }
inline std::uint16_t read_u16(const unsigned char* p) { std::uint16_t v; std::memcpy(&v, p, 2); return v; }
inline float read_f32(const unsigned char* p) { float v; std::memcpy(&v, p, 4); return v; }

// IEEE 754 half (16-bit) -> float.
inline float half_to_float(std::uint16_t h) {
    const std::uint32_t sign = static_cast<std::uint32_t>(h & 0x8000u) << 16;
    std::uint32_t exp = (h >> 10) & 0x1f;
    std::uint32_t mant = h & 0x3ff;
    std::uint32_t bits;
    if (exp == 0) {
        if (mant == 0) bits = sign;  // +/- zero
        else {  // subnormal: normalize, then the exponent is 113 (= 127 - 15 + 1) minus the shifts
            exp = 127 - 15 + 1;
            while (!(mant & 0x400)) { mant <<= 1; --exp; }
            mant &= 0x3ff;
            bits = sign | (exp << 23) | (mant << 13);
        }
    } else if (exp == 0x1f) {  // inf / nan
        bits = sign | 0x7f800000u | (mant << 13);
    } else {
        exp += 127 - 15;
        bits = sign | (exp << 23) | (mant << 13);
    }
    float f; std::memcpy(&f, &bits, 4); return f;
}

inline std::size_t element_size(int format) {
    switch (format) {
    case F_R32G32B32A32_FLOAT: return 16;
    case F_R32G32B32_FLOAT: return 12;
    case F_R16G16B16A16_FLOAT: return 8;
    case F_R32G32_FLOAT: return 8;
    case F_R8G8B8A8_UNORM:
    case F_R8G8B8A8_UINT: return 4;
    case F_R16G16_FLOAT: return 4;
    default: return 0;
    }
}

// Read one element's value at its offset into the vertex, dispatched by BOTH format and semantic.
inline bool read_element(const unsigned char* base, const Element& e, Vertex& out) {
    const unsigned char* p = base + e.offset;
    switch (e.format) {
    case F_R32G32B32_FLOAT:
        if (e.semantic == "POSITION") { out.position[0] = read_f32(p); out.position[1] = read_f32(p + 4); out.position[2] = read_f32(p + 8); return true; }
        if (e.semantic == "NORMAL")   { out.normal[0] = read_f32(p); out.normal[1] = read_f32(p + 4); out.normal[2] = read_f32(p + 8); return true; }
        return false;
    case F_R32G32_FLOAT:
        if (e.semantic == "TEXCOORD") { out.texcoord[0] = read_f32(p); out.texcoord[1] = read_f32(p + 4); return true; }
        return false;
    case F_R8G8B8A8_UNORM:
    case F_R8G8B8A8_UINT:
        if (e.semantic == "COLOR") { out.color = read_u32(p); return true; }
        return false;
    case F_R32G32B32A32_FLOAT:
        if (e.semantic == "POSITION") { out.position[0] = read_f32(p); out.position[1] = read_f32(p + 4); out.position[2] = read_f32(p + 8); return true; }
        if (e.semantic == "NORMAL")   { out.normal[0] = read_f32(p); out.normal[1] = read_f32(p + 4); out.normal[2] = read_f32(p + 8); return true; }
        if (e.semantic == "TEXCOORD") { out.texcoord[0] = read_f32(p); out.texcoord[1] = read_f32(p + 4); return true; }
        return false;
    case F_R16G16B16A16_FLOAT:
        if (e.semantic == "POSITION") { out.position[0] = half_to_float(read_u16(p)); out.position[1] = half_to_float(read_u16(p + 2)); out.position[2] = half_to_float(read_u16(p + 4)); return true; }
        if (e.semantic == "NORMAL")   { out.normal[0] = half_to_float(read_u16(p)); out.normal[1] = half_to_float(read_u16(p + 2)); out.normal[2] = half_to_float(read_u16(p + 4)); return true; }
        if (e.semantic == "TEXCOORD") { out.texcoord[0] = half_to_float(read_u16(p)); out.texcoord[1] = half_to_float(read_u16(p + 2)); return true; }
        return false;
    case F_R16G16_FLOAT:
        if (e.semantic == "TEXCOORD") { out.texcoord[0] = half_to_float(read_u16(p)); out.texcoord[1] = half_to_float(read_u16(p + 2)); return true; }
        return false;
    default:
        return false;  // unknown format: leave the field at default
    }
}

// `vertices_bytes` is a whole vertex buffer of `stride`-byte vertices; `elements` describes the format.
// Unknown/unsupported elements are ignored; a vertex with no POSITION keeps the default (0,0,0).
inline bool convert(const unsigned char* vertex_bytes, std::size_t byte_size, unsigned stride,
                    const std::vector<Element>& elements, std::vector<Vertex>& vertices) {
    if (!vertex_bytes || stride == 0 || byte_size % stride != 0) return false;
    vertices.clear();
    const std::size_t count = byte_size / stride;
    vertices.resize(count);
    for (std::size_t i = 0; i < count; ++i) {
        const unsigned char* base = vertex_bytes + i * stride;
        for (const auto& e : elements) {
            const std::size_t size = element_size(e.format);
            // subtraction-based bound check: e.offset + size must not wrap and must fit in the stride.
            if (size && size <= stride && e.offset <= stride - size) read_element(base, e, vertices[i]);
        }
    }
    return true;
}

// Convert an index buffer of `format` (R16_UINT=57 or R32_UINT=42) into u32 indices.
inline bool convert_indices(const unsigned char* index_bytes, std::size_t byte_size, int format,
                            std::vector<std::uint32_t>& indices) {
    indices.clear();
    if (!index_bytes && byte_size) return false;
    if (format == 57) {  // DXGI_FORMAT_R16_UINT
        if (byte_size % 2) return false;
        indices.reserve(byte_size / 2);
        for (std::size_t i = 0; i + 2 <= byte_size; i += 2) {
            std::uint16_t v; std::memcpy(&v, index_bytes + i, 2);
            indices.push_back(v);
        }
        return true;
    }
    if (format == 42) {  // DXGI_FORMAT_R32_UINT
        if (byte_size % 4) return false;
        indices.reserve(byte_size / 4);
        for (std::size_t i = 0; i + 4 <= byte_size; i += 4) indices.push_back(read_u32(index_bytes + i));
        return true;
    }
    return false;
}
}  // namespace geometry_convert
