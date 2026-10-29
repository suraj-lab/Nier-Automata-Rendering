#pragma once
// Bake all four game weights explicitly; Remix API's weight stride can mis-skin these meshes.
#include <cmath>
#include "live_vertex_decode.h"

namespace live_skinning {
inline bool bake(live_decode::Output& out, const unsigned char* palette, std::size_t bytes) {
    if (!palette || bytes < 48 || out.vertices.empty() || out.bones.size() != 4 * out.vertices.size() ||
        out.weights.size() != 4 * out.vertices.size()) return false;
    auto baked = out.vertices;
    for (std::size_t i = 0; i < out.vertices.size(); ++i) {
        const auto& src = out.vertices[i];
        float position[3] = {}, normal[3] = {};
        for (int r = 0; r < 3; ++r)
            if (!std::isfinite(src.position[r]) || !std::isfinite(src.normal[r])) return false;
        for (unsigned k = 0; k < 4; ++k) {
            const float w = out.weights[4 * i + k];
            if (!std::isfinite(w) || w < 0) return false;
            if (w == 0) continue;  // zero-weight slots in real captures contain unused bone indices
            const auto bone = out.bones[4 * i + k];
            if (bone >= bytes / 48) return false;
            float m[12];
            std::memcpy(m, palette + static_cast<std::size_t>(bone) * 48, sizeof m);
            for (float x : m) if (!std::isfinite(x)) return false;
            for (int r = 0; r < 3; ++r) {
                position[r] += w * (m[4*r] * src.position[0] + m[4*r+1] * src.position[1] +
                                    m[4*r+2] * src.position[2] + m[4*r+3]);
                normal[r] += w * (m[4*r] * src.normal[0] + m[4*r+1] * src.normal[1] + m[4*r+2] * src.normal[2]);
            }
        }
        for (int r = 0; r < 3; ++r)
            if (!std::isfinite(position[r]) || !std::isfinite(normal[r])) return false;
        const float length = std::hypot(normal[0], std::hypot(normal[1], normal[2]));
        for (int r = 0; r < 3; ++r) {
            baked[i].position[r] = position[r];
            baked[i].normal[r] = length > 0 ? normal[r] / length : 0;
        }
    }
    out.vertices.swap(baked);
    out.bones.clear();
    out.weights.clear();
    return true;
}
}  // namespace live_skinning
