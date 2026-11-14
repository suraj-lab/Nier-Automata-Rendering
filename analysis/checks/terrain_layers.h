// Item L5b (PLAN_2026-11-13): NieR's terrain shaders blend up to three albedo layers by vertex colour; Remix has one
// albedo per surface. assign() gives each triangle its dominant layer, from the same weights the shader's lerp chain
// uses (runtime/l5-disasm/scene/0f537e3024e964ad.txt lines 79-80, 117-120):
//   three layers: L0 = (1-R)(1-G), L1 = R(1-G), L2 = G      two layers: L0 = 1-R, L1 = R
// The shader is a height blend: w1 = sat((R - t0.a) / s), w2 = sat((G - t1.a) / s), s = cb1[1].w (lines 79-81). Here
// each layer's alpha is its texture's mean alpha (alpha[0] = t0, alpha[1] = t1).
// shortcut: the mean, not the texel under each triangle, so a seam can sit off the game's where a layer's alpha varies
// a lot (41686139: t0 alpha 0.05-0.43, t1 1.0 everywhere). Sample per triangle if a sheet shows seams in the wrong place.
// With alpha 0 and s 1 the weights are the raw vertex colour (the first version of this rule).
#pragma once
#include <cmath>
#include <cstdint>
#include <vector>
#include "live_types.h"

namespace terrain_layers {

// ids[0] is the albedo already on the upload; ids[k] == 0: layer k absent. scales: absolute UV repeats per layer; layer
// 0's is already baked into the vertices, so the upload stores the others relative to it.
inline float sat(float v) { return v < 0.f ? 0.f : v > 1.f ? 1.f : v; }

inline void assign(live_capture::Upload& u, const std::uint32_t ids[3], const float scales[3][2],
                   const float alpha[2] = nullptr, float sharpness = 1.f) {
    const float a0 = alpha ? alpha[0] : 0.f, a1 = alpha ? alpha[1] : 0.f;
    const float s = sharpness > 1e-4f ? sharpness : 1e-4f;
    if (!ids[0] || (!ids[1] && !ids[2]) || u.indices.size() % 3) return;
    const bool three = ids[2] != 0;
    u.triangle_layer.assign(u.indices.size() / 3, 0);
    for (std::size_t t = 0; t < u.triangle_layer.size(); ++t) {
        float w[3] = {0.f, 0.f, 0.f};
        for (std::size_t c = 0; c < 3; ++c) {
            const std::uint32_t index = u.indices[t * 3 + c];
            const std::uint32_t col = index < u.vertices.size() ? u.vertices[index].color : 0u;
            const float r = static_cast<float>(col & 0xffu) / 255.f, g = static_cast<float>((col >> 8) & 0xffu) / 255.f;
            const float w1 = sat((r - a0) / s), w2 = sat((g - a1) / s);   // the shader's lerp weights
            if (three) { w[0] += (1.f - w1) * (1.f - w2); w[1] += w1 * (1.f - w2); w[2] += w2; }
            else { w[0] += 1.f - w1; w[1] += w1; }
        }
        std::uint8_t best = 0;
        for (std::uint8_t k = 1; k < 3; ++k) if (ids[k] && w[k] > w[best]) best = k;
        u.triangle_layer[t] = best;
    }
    for (int k = 0; k < 3; ++k) {
        u.layer_texture[k] = ids[k];
        for (int a = 0; a < 2; ++a) u.layer_scale[k][a] = scales[0][a] != 0.f ? scales[k][a] / scales[0][a] : 1.f;
    }
}

// A blended terrain overlay (f5be3a42...: lines 59-84) writes a coverage alpha, not a colour alpha:
//   alpha = max(2 / (1 + exp(-w * (z * (t0.a * B * f - 0.5) + 0.5))) - 1, 0),  z, w = cb1[10].z, .w, B = COLOR.b,
// f = facing powers (1 on a floor). Remix gets the overlay as a solid surface, so triangles the game leaves (nearly)
// transparent are dropped instead: coverage below 0.5 -> layer 255, no surface. Applied after assign().
// shortcut: f = 1 (floors); a wall-like overlay would need the vertex normal against cb0[0]/cb0[1].
inline constexpr std::uint8_t kDropped = 255;
inline float coverage(float a_times_b, float z, float w) {
    const float x = -w * (z * (a_times_b - 0.5f) + 0.5f);
    const float a = 2.f / (1.f + std::exp(x)) - 1.f;
    return a > 0.f ? a : 0.f;
}
inline void drop_uncovered(live_capture::Upload& u, float t0_alpha, float z, float w) {
    if (u.triangle_layer.empty() || !(w > 0.f) || u.indices.size() != u.triangle_layer.size() * 3) return;
    std::vector<std::uint8_t> layers = u.triangle_layer;
    std::size_t kept = 0;
    for (std::size_t t = 0; t < layers.size(); ++t) {
        float b = 0.f;
        for (std::size_t c = 0; c < 3; ++c) {
            const std::uint32_t index = u.indices[t * 3 + c];
            const std::uint32_t col = index < u.vertices.size() ? u.vertices[index].color : 0u;
            b += static_cast<float>((col >> 16) & 0xffu) / 255.f;
        }
        if (coverage(t0_alpha * b / 3.f, z, w) < 0.5f) layers[t] = kDropped;
        else ++kept;
    }
    if (kept) u.triangle_layer.swap(layers);   // never drop a whole mesh: an empty mesh is no mesh
}

}  // namespace terrain_layers
