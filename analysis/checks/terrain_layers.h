// Item L5b (PLAN_2026-11-13): NieR's terrain shaders blend up to three albedo layers by vertex colour; Remix has one
// albedo per surface. assign() gives each triangle its dominant layer, from the same weights the shader's lerp chain
// uses (runtime/l5-disasm/scene/0f537e3024e964ad.txt lines 79-80, 117-120):
//   three layers: L0 = (1-R)(1-G), L1 = R(1-G), L2 = G      two layers: L0 = 1-R, L1 = R
// shortcut: the shader also subtracts each layer's texture alpha and sharpens by cb1[1].w (a height blend); the vertex
// colour alone decides here, so a seam can sit a little off the game's. Use the alpha when a sheet shows it matters.
#pragma once
#include <cstdint>
#include "live_types.h"

namespace terrain_layers {

// ids[0] is the albedo already on the upload; ids[k] == 0: layer k absent. scales: absolute UV repeats per layer; layer
// 0's is already baked into the vertices, so the upload stores the others relative to it.
inline void assign(live_capture::Upload& u, const std::uint32_t ids[3], const float scales[3][2]) {
    if (!ids[0] || (!ids[1] && !ids[2]) || u.indices.size() % 3) return;
    const bool three = ids[2] != 0;
    u.triangle_layer.assign(u.indices.size() / 3, 0);
    for (std::size_t t = 0; t < u.triangle_layer.size(); ++t) {
        float w[3] = {0.f, 0.f, 0.f};
        for (std::size_t c = 0; c < 3; ++c) {
            const std::uint32_t index = u.indices[t * 3 + c];
            const std::uint32_t col = index < u.vertices.size() ? u.vertices[index].color : 0u;
            const float r = static_cast<float>(col & 0xffu) / 255.f, g = static_cast<float>((col >> 8) & 0xffu) / 255.f;
            if (three) { w[0] += (1.f - r) * (1.f - g); w[1] += r * (1.f - g); w[2] += g; }
            else { w[0] += 1.f - r; w[1] += r; }
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

}  // namespace terrain_layers
