// Item L5b (PLAN_2026-11-13): bake NieR's two-layer terrain height blend into one tile per vertex-red level.
//
// The ground shader (204f7be9..., 0f537e30...) picks per texel: w1 = sat((COLOR.r - t0.a) / cb1[1].w), albedo =
// lerp(t0, t1, w1). With a sharpness of 0.01 that is a texel-level mix (41686139's floor: about a third layer 1 at
// R 0.09), which no per-triangle layer choice can show. Both layers repeat the same number of times, so at a fixed R the
// mix is itself a tile: bake it once per R level and give each triangle the tile of its mean R.
// Portable (no D3D types): the worker bakes from the DDS files the writer put on disk; gated natively.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>
#include "mask_channels.h"

namespace terrain_bake {

inline constexpr unsigned kLevels = 8;        // vertex-red buckets; tile k is baked at R = (k + 0.5) / kLevels
inline constexpr unsigned kMaxSize = 512;     // tiles are box-filtered down to this (8 tiles x 1 MB per layer pair)

struct Image { unsigned w = 0, h = 0; std::vector<float> rgba; };   // linear light, alpha linear

inline float srgb_to_linear(float c) { return c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f); }
inline float linear_to_srgb(float c) {
    c = c < 0.f ? 0.f : c > 1.f ? 1.f : c;
    return c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.f / 2.4f) - 0.055f;
}

// Mip 0 of one of our own DDS files (texture_capture::write_dds: 128-byte header, DX10 extension, mips tightly packed).
// BC1 (71/72), BC3 (77/78), RGBA8 (28/29), BGRA8 (87/91); the *_SRGB formats are decoded to linear.
inline bool read_dds(const std::vector<unsigned char>& file, Image& out) {
    if (file.size() < 148 || std::memcmp(file.data(), "DDS ", 4) != 0) return false;
    std::uint32_t h[32], dx10[5];
    std::memcpy(h, file.data(), sizeof h);
    if (h[21] != 0x30315844) return false;   // "DX10"
    std::memcpy(dx10, file.data() + 128, sizeof dx10);
    const unsigned w = h[4], hh = h[3], fmt = dx10[0];
    if (!w || !hh || w > 16384 || hh > 16384) return false;
    mask_channels::Source source;
    bool srgb = false;
    switch (fmt) {
        case 71: source = mask_channels::Source::Bc1; break;
        case 72: source = mask_channels::Source::Bc1; srgb = true; break;
        case 77: source = mask_channels::Source::Bc3; break;
        case 78: source = mask_channels::Source::Bc3; srgb = true; break;
        case 28: source = mask_channels::Source::Rgba8; break;
        case 29: source = mask_channels::Source::Rgba8; srgb = true; break;
        case 87: source = mask_channels::Source::Bgra8; break;
        case 91: source = mask_channels::Source::Bgra8; srgb = true; break;
        default: return false;
    }
    const std::size_t pixels = static_cast<std::size_t>(w) * hh;
    std::vector<unsigned char> channel(pixels);
    out.w = w; out.h = hh;
    out.rgba.assign(pixels * 4, 0.f);
    for (unsigned c = 0; c < 4; ++c) {
        if (!mask_channels::extract_level(source, file.data() + 148, file.size() - 148, w, hh, c, false, channel.data()))
            return false;
        for (std::size_t i = 0; i < pixels; ++i) {
            const float v = channel[i] / 255.f;
            out.rgba[i * 4 + c] = (srgb && c < 3) ? srgb_to_linear(v) : v;
        }
    }
    return true;
}

// Box filter by 2 until both sides fit kMaxSize.
inline Image shrink(Image im) {
    while (im.w > kMaxSize || im.h > kMaxSize) {
        const unsigned w = std::max(1u, im.w / 2), h = std::max(1u, im.h / 2);
        Image o; o.w = w; o.h = h; o.rgba.assign(static_cast<std::size_t>(w) * h * 4, 0.f);
        for (unsigned y = 0; y < h; ++y)
            for (unsigned x = 0; x < w; ++x)
                for (unsigned c = 0; c < 4; ++c) {
                    float sum = 0.f;
                    for (unsigned dy = 0; dy < 2; ++dy)
                        for (unsigned dx = 0; dx < 2; ++dx) {
                            const unsigned sx = std::min(im.w - 1, x * 2 + dx), sy = std::min(im.h - 1, y * 2 + dy);
                            sum += im.rgba[(static_cast<std::size_t>(sy) * im.w + sx) * 4 + c];
                        }
                    o.rgba[(static_cast<std::size_t>(y) * w + x) * 4 + c] = sum / 4.f;
                }
        im = std::move(o);
    }
    return im;
}

// The shader's per-texel blend at a fixed vertex red, at full resolution (t1 sampled nearest at t0's size), then shrunk.
inline Image bake(const Image& t0, const Image& t1, float r, float sharpness) {
    const float s = sharpness > 1e-4f ? sharpness : 1e-4f;
    Image o; o.w = t0.w; o.h = t0.h; o.rgba.assign(t0.rgba.size(), 0.f);
    for (unsigned y = 0; y < t0.h; ++y)
        for (unsigned x = 0; x < t0.w; ++x) {
            const std::size_t i = (static_cast<std::size_t>(y) * t0.w + x) * 4;
            const unsigned x1 = static_cast<unsigned>(static_cast<std::uint64_t>(x) * t1.w / t0.w);
            const unsigned y1 = static_cast<unsigned>(static_cast<std::uint64_t>(y) * t1.h / t0.h);
            const std::size_t j = (static_cast<std::size_t>(y1) * t1.w + x1) * 4;
            float w1 = (r - t0.rgba[i + 3]) / s;
            w1 = w1 < 0.f ? 0.f : w1 > 1.f ? 1.f : w1;
            for (unsigned c = 0; c < 3; ++c) o.rgba[i + c] = t0.rgba[i + c] + w1 * (t1.rgba[j + c] - t0.rgba[i + c]);
            o.rgba[i + 3] = 1.f;
        }
    return shrink(std::move(o));
}

// One mip of R8G8B8A8_UNORM_SRGB (29), in write_dds's layout.
inline std::vector<unsigned char> dds_bytes(const Image& im) {
    std::uint32_t h[32] = {};
    h[0] = 0x20534444; h[1] = 124; h[2] = 0x1 | 0x2 | 0x4 | 0x1000 | 0x8; h[3] = im.h; h[4] = im.w; h[5] = im.w * 4;
    h[7] = 1; h[19] = 32; h[20] = 0x4; h[21] = 0x30315844; h[27] = 0x1000;
    const std::uint32_t dx10[5] = {29, 3, 0, 1, 0};
    std::vector<unsigned char> out(148 + static_cast<std::size_t>(im.w) * im.h * 4);
    std::memcpy(out.data(), h, sizeof h);
    std::memcpy(out.data() + 128, dx10, sizeof dx10);
    for (std::size_t i = 0; i < static_cast<std::size_t>(im.w) * im.h; ++i)
        for (unsigned c = 0; c < 4; ++c) {
            const float v = c < 3 ? linear_to_srgb(im.rgba[i * 4 + c]) : im.rgba[i * 4 + c];
            out[148 + i * 4 + c] = mask_channels::to_byte(v);
        }
    return out;
}

}  // namespace terrain_bake
