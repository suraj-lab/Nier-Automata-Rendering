#pragma once
// NieR tangent-space normals -> Remix's unsigned-octahedral encoding. No D3D types, so it compiles and is gated
// natively: remix-1.6.1's material shader decodes UNSIGNED OCTAHEDRAL from the normal texture, while NieR stores
// 8-bit UNORM X,Y in R,G with no Z (four consecutive linear 1024x1024 captures decode to every texel inside the
// unit disc). Raw X,Y there give a plausible but wrong bump field: the lumpy blotches seen live.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace normal_octahedral {

enum class Source { Bc1, Bc5Unorm, Bc5Snorm, Rgba8, Bgra8 };

inline void rgb565(unsigned c, float out[3]) {
    out[0] = static_cast<float>((c >> 11) & 31) / 31.f;
    out[1] = static_cast<float>((c >> 5) & 63) / 63.f;
    out[2] = static_cast<float>(c & 31) / 31.f;
}

// BC1/BC2/BC3 colour block: 4x4 texels, two RGB565 endpoints, 2-bit indices, row-major. False for the transparent
// texel of a 3-colour block, which carries no usable normal.
inline bool bc1_texel(const unsigned char* block, unsigned x, unsigned y, float rgb[3]) {
    const unsigned c0 = block[0] | (block[1] << 8), c1 = block[2] | (block[3] << 8);
    float a[3], b[3];
    rgb565(c0, a);
    rgb565(c1, b);
    const unsigned bits = block[4] | (block[5] << 8) | (block[6] << 16) | (static_cast<unsigned>(block[7]) << 24);
    const unsigned index = (bits >> (2 * (y * 4 + x))) & 3;
    if (index == 0) { std::memcpy(rgb, a, sizeof a); return true; }
    if (index == 1) { std::memcpy(rgb, b, sizeof b); return true; }
    if (index == 2) { for (int i = 0; i < 3; ++i) rgb[i] = (2 * a[i] + b[i]) / 3.f; return true; }
    if (c0 > c1) { for (int i = 0; i < 3; ++i) rgb[i] = (a[i] + 2 * b[i]) / 3.f; return true; }
    rgb[0] = rgb[1] = rgb[2] = 0.f;
    return false;
}

// One channel of a BC4/BC5 block (8 bytes): two endpoints and 3-bit indices; SNORM endpoints stay signed.
inline float bc4_texel(const unsigned char* block, unsigned x, unsigned y, bool snorm) {
    auto endpoint = [snorm](unsigned char v) {
        return snorm ? static_cast<float>(static_cast<signed char>(v)) / 127.f : static_cast<float>(v) / 255.f;
    };
    float table[8];
    table[0] = endpoint(block[0]);
    table[1] = endpoint(block[1]);
    if (table[0] > table[1]) {
        for (int i = 1; i <= 6; ++i) table[i + 1] = table[0] + (table[1] - table[0]) * i / 7.f;
    } else {
        for (int i = 1; i <= 4; ++i) table[i + 1] = table[0] + (table[1] - table[0]) * i / 5.f;
        table[6] = snorm ? -1.f : 0.f;
        table[7] = 1.f;
    }
    std::uint64_t bits = 0;
    for (int i = 0; i < 6; ++i) bits |= static_cast<std::uint64_t>(block[2 + i]) << (8 * i);
    return table[(bits >> (3 * (y * 4 + x))) & 7];
}

// The shader's encode: s = |x|+|y|+z, R = (x/s + y/s)/2 + .5, G = (x/s - y/s)/2 + .5. Z is reconstructed because
// the game does not store it.
inline void encode_octahedral(float x, float y, unsigned char out[2]) {
    const float z2 = 1.f - x * x - y * y;
    float z = z2 > 0.f ? std::sqrt(z2) : 0.f;
    const float len = std::sqrt(x * x + y * y + z * z);
    if (len > 1e-6f) { x /= len; y /= len; z /= len; } else { x = 0.f; y = 0.f; z = 1.f; }
    const float s = std::fabs(x) + std::fabs(y) + std::fabs(z);
    const float ox = x / s, oy = y / s;
    const auto to_byte = [](float v) {
        return static_cast<unsigned char>(std::min(255.f, std::max(0.f, v * 255.f + 0.5f)));
    };
    out[0] = to_byte((ox + oy) * 0.5f + 0.5f);
    out[1] = to_byte((ox - oy) * 0.5f + 0.5f);
}

// Bytes one tightly-packed level of this source occupies for a w x h level (block formats store whole 4x4 blocks).
inline std::size_t level_bytes(Source source, unsigned w, unsigned h) {
    const std::size_t bw = (w + 3u) / 4u, bh = (h + 3u) / 4u;
    switch (source) {
        case Source::Bc1: return bw * bh * 8;
        case Source::Bc5Unorm:
        case Source::Bc5Snorm: return bw * bh * 16;
        default: return static_cast<std::size_t>(w) * h * 4;
    }
}

// Converts one level into RGBA8 octahedral. `out` must hold w*h*4 bytes. False when the input is too short or a
// texel has no usable normal, so an unexpected texture is left as the game wrote it rather than half-converted.
inline bool convert_level(Source source, const unsigned char* in, std::size_t in_bytes, unsigned w, unsigned h,
                          bool flip_y, unsigned char* out) {
    if (!in || !out || in_bytes < level_bytes(source, w, h)) return false;
    const std::size_t bw = (w + 3u) / 4u;
    for (unsigned y = 0; y < h; ++y) {
        for (unsigned x = 0; x < w; ++x) {
            float nx, ny;
            if (source == Source::Bc1) {
                float rgb[3];
                if (!bc1_texel(in + (static_cast<std::size_t>(y / 4) * bw + x / 4) * 8, x % 4, y % 4, rgb)) return false;
                nx = rgb[0] * 2.f - 1.f;
                ny = rgb[1] * 2.f - 1.f;
            } else if (source == Source::Bc5Unorm || source == Source::Bc5Snorm) {
                const unsigned char* block = in + (static_cast<std::size_t>(y / 4) * bw + x / 4) * 16;
                const bool snorm = source == Source::Bc5Snorm;
                const float u = bc4_texel(block, x % 4, y % 4, snorm);
                const float v = bc4_texel(block + 8, x % 4, y % 4, snorm);
                // SNORM is already signed; only UNORM needs the [0,1] -> [-1,1] remap.
                nx = snorm ? u : u * 2.f - 1.f;
                ny = snorm ? v : v * 2.f - 1.f;
            } else {
                const unsigned char* texel = in + (static_cast<std::size_t>(y) * w + x) * 4;
                nx = static_cast<float>(source == Source::Rgba8 ? texel[0] : texel[2]) / 255.f * 2.f - 1.f;
                ny = static_cast<float>(texel[1]) / 255.f * 2.f - 1.f;
            }
            if (flip_y) ny = -ny;
            unsigned char* o = out + (static_cast<std::size_t>(y) * w + x) * 4;
            encode_octahedral(nx, ny, o);
            o[2] = 0;
            o[3] = 255;
        }
    }
    return true;
}

}  // namespace normal_octahedral
