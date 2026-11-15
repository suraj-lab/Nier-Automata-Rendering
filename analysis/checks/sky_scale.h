// W1.3 step 1b (PLAN_2026-11-14): a *textured* sky layer's colour is t0 * g_IntensityParam.y * g_MeshColor.rgb
// (runtime/w1-disasm/sky_ps.asm:24-30), and g_AlbedoParam.w == 0 selects t0. Remix's `albedoConstant` *replaces* the
// albedo texture instead of multiplying it (replay/research-2026-11-12/remix_material_api.md:19-21), so the product is
// written once per (texture, factor) as its own DDS beside the game's copied texture, and the material names that copy
// with a constant of 1,1,1.
//
// The decode is terrain_bake::read_dds (BC1/BC2/BC3/RGBA8/BGRA8 -- camp's cloud layers are BC2) and the write is
// terrain_bake::dds_bytes, in the source's own colour encoding. Portable C++17, no D3D; gate: checks/test_sky_scale.py.
#ifndef SKY_SCALE_H
#define SKY_SCALE_H

#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "sky_layer.h"
#include "terrain_bake.h"

namespace sky_scale {

// Distinct copies per session, and the factor grid they are quantised to: an animated intensity must not write a file
// per frame. Past the cap the layer keeps today's texture (t0 at full intensity) and is counted, never a black sky.
inline constexpr unsigned kMaxCopies = 8;
inline constexpr float kQuantum = 1.f / 64.f;
// A header claim above this is refused before anything is allocated (4096x4096 = 268 MB of floats; camp's layers are
// 2048x2048). read_dds allocates before it can notice a short payload.
inline constexpr std::uint64_t kMaxPixels = 4096ull * 4096ull;
// The runtime decodes albedo with pow(x, 2.2) itself, whatever the DDS tag says (research-2026-11-12/remix_material_api.md:
// "the shader always applies pow(x,2.2)"; a UNORM source is one decode). The layer's bytes are therefore sRGB-encoded
// art, and multiplying the colour it *renders* by f means multiplying those bytes by f^(1/2.2).
inline constexpr float kDecodeGamma = 2.2f;

inline std::atomic<unsigned long long> draws{0};     // sky draws whose textured layer got a factor
inline std::atomic<unsigned long long> copies{0};    // copies written
inline std::atomic<unsigned long long> refused{0};   // copies that could not be written: today's texture stands

inline float quantize(float factor) { return std::round(factor / kQuantum) * kQuantum; }

// The factor a textured layer multiplies its texture by: the shader's own g_IntensityParam.y, and only while the mesh
// tint is the identity (all three areas measured so far are). A tinted layer keeps today's texture rather than a copy
// whose name would carry one of three factors. false: an albedo override (a constant, not a texture), nothing to scale
// (factor 1), or a value this path will not write.
inline bool layer_factor(const sky_layer::Inputs& in, float& out) {
    if (!in.present || in.use_albedo) return false;
    for (int k = 0; k < 3; ++k)
        if (!(std::fabs(in.mesh[k] - 1.f) <= 1e-6f)) return false;
    if (!std::isfinite(in.intensity) || in.intensity <= 0.f || in.intensity > 64.f) return false;
    const float f = quantize(in.intensity);
    if (!(f > 0.f) || f == 1.f) return false;   // factor 1 is today's texture, not a copy of it
    out = f;
    return true;
}

// sky_<texture id>_<factor in thousandths>.dds, in the layer texture's own directory.
inline std::wstring file_name(std::uint32_t id, float factor) {
    const unsigned milli = static_cast<unsigned>(std::lround(factor * 1000.f));
    return L"sky_" + std::to_wstring(id) + L"_" + std::to_wstring(milli) + L".dds";
}

// A header claim this path will not decode: read_dds allocates 16 bytes per texel before it can see a short payload, so
// an 8192x8192 header with no payload would cost a gigabyte before being refused.
inline bool plausible_size(std::uint64_t width, std::uint64_t height) {
    const std::uint64_t pixels = width * height;
    return pixels != 0 && pixels <= kMaxPixels;
}

// The copy: the source's mip 0 with its RGB bytes scaled by factor^(1/kDecodeGamma) (and a full mip chain), so the
// runtime's own decode yields exactly the source's colour times `factor`. Only an untagged (UNORM) source is written:
// the live path tags every albedo UNORM (remix_live.cpp's albedo_unorm), and a tagged source would be decoded twice, so
// its factor would sit in a different space -- it is refused and counted instead of guessed at. An 8-bit copy clamps
// above white: a factor that pushes a channel past 1.0 is approximated rather than represented in HDR (a limitation).
// false: not one of our 2D DDS files, a tagged or cube source, an implausible header, or nothing written.
inline bool scaled_dds(const std::vector<unsigned char>& source, float factor, std::vector<unsigned char>& out) {
    out.clear();
    if (!std::isfinite(factor) || factor <= 0.f) return false;
    if (source.size() < 148 || std::memcmp(source.data(), "DDS ", 4) != 0) return false;
    std::uint32_t head[32], dx10[5];
    std::memcpy(head, source.data(), sizeof head);
    std::memcpy(dx10, source.data() + 128, sizeof dx10);
    const std::uint64_t pixels = static_cast<std::uint64_t>(head[4]) * head[3];
    if (!plausible_size(head[4], head[3])) return false;
    if (dx10[1] != 3 || (dx10[2] & 0x4u) != 0) return false;   // not a 2D texture: a cube would be one face
    switch (dx10[0]) {   // the untagged formats read_dds decodes
        case 71: case 74: case 77: case 28: case 87: break;
        default: return false;
    }
    terrain_bake::Image image;
    if (!terrain_bake::read_dds(source, image, nullptr, true)) return false;
    if (static_cast<std::uint64_t>(image.w) * image.h != pixels || image.rgba.size() != pixels * 4) return false;
    const float gain = std::pow(factor, 1.f / kDecodeGamma);
    for (std::size_t i = 0; i < static_cast<std::size_t>(pixels); ++i)
        for (int c = 0; c < 3; ++c) image.rgba[i * 4 + c] *= gain;
    out = terrain_bake::dds_bytes(image, true, false);
    return !out.empty();
}

}  // namespace sky_scale

#endif  // SKY_SCALE_H
