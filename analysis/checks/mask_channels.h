#pragma once
// One channel of a NieR mask texture as its own R8 texture, for Remix's metallic and roughness inputs.
//
// The game's lit shaders read metalness and gloss from two channels of one mask texture (analysis/PBR_MAPPING.md,
// traced per shader by material_roles.h); Remix reads each from the R channel of its own texture, roughness as
// perceptual roughness (opaque_surface_material_interaction.slangh: `roughness = roughnessSample.x`). NieR's GGX
// alpha is (1 - gloss)^2, so roughness = 1 - gloss exactly. Masks seen in the main view are BC1 or BC3 (71 / 29 of
// 100 draws), linear. No D3D types, so it compiles and is gated natively.
#include <cstddef>
#include <cstdint>
#include "normal_octahedral.h"

namespace mask_channels {

enum class Source { Bc1, Bc3, Rgba8, Bgra8 };

inline unsigned char to_byte(float v) {
    return static_cast<unsigned char>(v <= 0.f ? 0 : v >= 1.f ? 255 : static_cast<int>(v * 255.f + 0.5f));
}

// RGBA of texel (x, y) of a BC colour block. BC1 switches to 3-colour + transparent black when c0 <= c1; the colour
// half of BC2/BC3 always interpolates four colours (D3D block compression rules).
inline void colour_texel(const unsigned char* block, unsigned x, unsigned y, bool always_four, float rgba[4]) {
    const unsigned c0 = block[0] | (block[1] << 8), c1 = block[2] | (block[3] << 8);
    float a[3], b[3];
    normal_octahedral::rgb565(c0, a);
    normal_octahedral::rgb565(c1, b);
    const unsigned bits = block[4] | (block[5] << 8) | (block[6] << 16) | (static_cast<unsigned>(block[7]) << 24);
    const unsigned index = (bits >> (2 * (y * 4 + x))) & 3;
    rgba[3] = 1.f;
    const bool four = always_four || c0 > c1;
    for (int i = 0; i < 3; ++i) {
        if (index == 0) rgba[i] = a[i];
        else if (index == 1) rgba[i] = b[i];
        else if (four) rgba[i] = index == 2 ? (2.f * a[i] + b[i]) / 3.f : (a[i] + 2.f * b[i]) / 3.f;
        else rgba[i] = index == 2 ? (a[i] + b[i]) / 2.f : 0.f;
    }
    if (!four && index == 3) rgba[3] = 0.f;
}

// One level (mip) of `source` -> w*h bytes of channel `channel` (0 = R .. 3 = A), inverted (255 - v) if asked, then
// raised to at least `floor`. The floor is for roughness: "very smooth" authoring becomes a literal mirror in a path
// tracer, where raster hid it under specular highlights (FO4-Remix clamps roughness to >= 0.15 for the same reason).
// False when the source bytes are too short for the level, leaving `out` partly written.
inline bool extract_level(Source source, const unsigned char* src, std::size_t src_bytes, unsigned w, unsigned h,
                          unsigned channel, bool invert, unsigned char* out, unsigned char floor = 0) {
    if (channel > 3 || !w || !h) return false;
    const unsigned bw = (w + 3) / 4, bh = (h + 3) / 4;
    const std::size_t block_bytes = source == Source::Bc1 ? 8 : 16;
    if (source == Source::Bc1 || source == Source::Bc3) {
        if (src_bytes < static_cast<std::size_t>(bw) * bh * block_bytes) return false;
        const auto finish = [invert, floor](float v) {
            const unsigned char b = to_byte(v);
            const unsigned char r = invert ? static_cast<unsigned char>(255 - b) : b;
            return r < floor ? floor : r;
        };
        for (unsigned by = 0; by < bh; ++by)
            for (unsigned bx = 0; bx < bw; ++bx) {
                const unsigned char* block = src + (static_cast<std::size_t>(by) * bw + bx) * block_bytes;
                // Final output byte per palette index, computed once per block; then each texel looks up its index.
                unsigned char lut[8];
                std::uint64_t bits;
                unsigned bits_per_index;
                if (source == Source::Bc3 && channel == 3) {
                    float table[8];
                    normal_octahedral::bc4_table(block, false, table);
                    for (int k = 0; k < 8; ++k) lut[k] = finish(table[k]);
                    bits = normal_octahedral::bc4_bits(block);
                    bits_per_index = 3;
                } else {
                    const unsigned char* colour = source == Source::Bc1 ? block : block + 8;
                    const unsigned c0 = colour[0] | (colour[1] << 8), c1 = colour[2] | (colour[3] << 8);
                    float a[3], b[3];
                    normal_octahedral::rgb565(c0, a);
                    normal_octahedral::rgb565(c1, b);
                    const bool four = source == Source::Bc3 || c0 > c1;
                    float pal[4][4];
                    for (int i = 0; i < 3; ++i) {
                        pal[0][i] = a[i];
                        pal[1][i] = b[i];
                        pal[2][i] = four ? (2.f * a[i] + b[i]) / 3.f : (a[i] + b[i]) / 2.f;
                        pal[3][i] = four ? (a[i] + 2.f * b[i]) / 3.f : 0.f;
                    }
                    pal[0][3] = pal[1][3] = pal[2][3] = 1.f;
                    pal[3][3] = four ? 1.f : 0.f;
                    for (int k = 0; k < 4; ++k) lut[k] = finish(pal[k][channel]);
                    bits = colour[4] | (colour[5] << 8) | (colour[6] << 16) | (static_cast<unsigned>(colour[7]) << 24);
                    bits_per_index = 2;
                }
                const unsigned mask = (1u << bits_per_index) - 1;
                const unsigned x_end = w - bx * 4 < 4 ? w - bx * 4 : 4, y_end = h - by * 4 < 4 ? h - by * 4 : 4;
                for (unsigned y = 0; y < y_end; ++y) {
                    unsigned char* o = out + static_cast<std::size_t>(by * 4 + y) * w + bx * 4;
                    for (unsigned x = 0; x < x_end; ++x)
                        o[x] = lut[(bits >> (bits_per_index * (y * 4 + x))) & mask];
                }
            }
        return true;
    }
    if (src_bytes < static_cast<std::size_t>(w) * h * 4) return false;
    const unsigned at = source == Source::Bgra8 && channel < 3 ? 2 - channel : channel;  // BGRA: R is byte 2
    for (std::size_t i = 0; i < static_cast<std::size_t>(w) * h; ++i) {
        const unsigned char v = src[4 * i + at];
        const unsigned char r = invert ? static_cast<unsigned char>(255 - v) : v;
        out[i] = r < floor ? floor : r;
    }
    return true;
}

}  // namespace mask_channels
