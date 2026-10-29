#pragma once
// NieR's light arrays -> Remix lights. Shared by the live path (live_capture/live_scene) and the laptop probe
// (remix-probe/triangle.cpp, from an F9 capture's lights_t20.bin / lights_t22.bin), so what is tuned on the laptop is
// exactly what the game submits (ROADMAP: laptop first).
//
// Element layouts were read from the game's own pixel shaders (analysis/SHADER_DECLARATIONS.md):
//   point, t20, 48 B: 0 position xyz | 12 outer radius (range) | 28 gate | 32 colour rgb | 44 inner radius
//   spot,  t22, 80 B: 0 position xyz | 12 outer cone cos | 28 gate | 32 colour rgb | 44 inner cone cos | 48 direction xyz
// The game attenuates linearly: full colour inside the inner radius, zero at the outer radius. Remix lights are
// physical (a small emitter, inverse-square falloff), so the range becomes an intensity, not a size: the emitter keeps
// a small radius and its intensity is chosen so the irradiance at half the range equals the game's colour there.
// `scale` is the one free knob, tuned on the laptop against a capture (NIER_REMIX_LIGHT_SCALE / REPROBE_LIGHT_SCALE).
// Gate: test_light_convert.py.
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace light_convert {

struct Light {
    bool spot = false;
    float position[3] = {};
    float range = 0;          // point: outer radius; spot: unknown (bytes 16-27 unidentified), kDefaultSpotRange
    float colour[3] = {};
    float direction[3] = {};  // spot only, normalised
    float cone_outer_cos = -1, cone_inner_cos = -1;  // spot only
};

constexpr std::size_t kPointStride = 48, kSpotStride = 80;
constexpr unsigned kMaxLights = 64;            // a rendering budget, not a decode limit
constexpr float kDefaultSpotRange = 10.f;      // shortcut: spot range not identified in the 80-byte element yet
constexpr float kEmitterRadius = 0.1f;         // world units; NieR's world unit is about a metre

inline bool finite3(const float* v) { return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]); }

struct Sun {
    float colour[3] = {};
    float direction[3] = {};  // incoming rays, opposite the game's surface-to-light vector
};

// Verified scene PS CB2: rgb at byte 0, unit surface-to-light vector at byte 16 (not VS CB2).
inline bool parse_sun(const unsigned char* bytes, std::size_t size, Sun& out) {
    if (!bytes || size < 32) return false;
    float e[8];
    std::memcpy(e, bytes, sizeof e);
    if (!finite3(e) || !finite3(e + 4) || e[0] < 0 || e[1] < 0 || e[2] < 0 || e[7] != 0) return false;
    const float n = std::sqrt(e[4] * e[4] + e[5] * e[5] + e[6] * e[6]);
    if (!std::isfinite(n) || std::fabs(n - 1.f) > 1e-3f) return false;  // rejects the dummy [1,1,1] CB2
    Sun s{};
    for (int k = 0; k < 3; ++k) { s.colour[k] = e[k]; s.direction[k] = -e[4 + k] / n; }
    out = s;
    return true;
}

// Elements [first, first+count) of a structured buffer's bytes; zero-position and non-finite elements are padding.
inline void parse(const unsigned char* bytes, std::size_t size, std::size_t stride, std::size_t first, std::size_t count,
                  bool spot, std::vector<Light>& out) {
    if (!bytes || (stride != kPointStride && stride != kSpotStride)) return;
    for (std::size_t i = first; i < first + count && out.size() < kMaxLights; ++i) {
        if (size < stride * (i + 1)) break;
        float e[20] = {};
        std::memcpy(e, bytes + stride * i, stride);
        Light l;
        l.spot = spot;
        std::memcpy(l.position, e, sizeof l.position);
        std::memcpy(l.colour, e + 8, sizeof l.colour);
        if (!finite3(l.position) || !finite3(l.colour) || (!e[0] && !e[1] && !e[2])) continue;
        if (l.colour[0] <= 0 && l.colour[1] <= 0 && l.colour[2] <= 0) continue;  // contributes nothing
        if (spot) {
            l.range = kDefaultSpotRange;
            l.cone_outer_cos = e[3];
            l.cone_inner_cos = e[11];
            const float d[3] = {e[12], e[13], e[14]};
            const float n = std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
            if (!(n > 1e-6f) || !std::isfinite(n)) continue;
            for (int k = 0; k < 3; ++k) l.direction[k] = d[k] / n;
        } else {
            l.range = e[3];
            if (!(l.range > 0) || !std::isfinite(l.range)) continue;
        }
        out.push_back(l);
    }
}

inline bool same(const Light& a, const Light& b) {  // field-wise: the struct has padding after `spot`
    return a.spot == b.spot && !std::memcmp(a.position, b.position, sizeof a.position) && a.range == b.range &&
           !std::memcmp(a.colour, b.colour, sizeof a.colour) && !std::memcmp(a.direction, b.direction, sizeof a.direction) &&
           a.cone_outer_cos == b.cone_outer_cos && a.cone_inner_cos == b.cone_inner_cos;
}

// Remix sphere-light parameters for one game light.
struct Sphere {
    float position[3];
    float radius;
    float radiance[3];
    bool shaped = false;
    float direction[3] = {0, 0, 1};
    float cone_angle_degrees = 180;
    float cone_softness = 0;
};

inline Sphere to_sphere(const Light& l, float scale) {
    Sphere s{};
    std::memcpy(s.position, l.position, sizeof s.position);
    s.radius = kEmitterRadius;
    // Intensity I with I / d^2 = colour at d = range / 2; a sphere of radius r emits I = L * pi * r^2.
    const float half = 0.5f * l.range;
    const float k = scale * half * half / (3.14159265f * s.radius * s.radius);
    for (int c = 0; c < 3; ++c) s.radiance[c] = l.colour[c] * k;
    if (l.spot) {
        s.shaped = true;
        std::memcpy(s.direction, l.direction, sizeof s.direction);
        const float outer = std::acos(std::fmin(1.f, std::fmax(-1.f, l.cone_outer_cos))) * 57.2957795f;
        const float inner = std::acos(std::fmin(1.f, std::fmax(-1.f, l.cone_inner_cos))) * 57.2957795f;
        s.cone_angle_degrees = outer;
        // UsdLux-style softness: the falloff band as a 0-1 fraction of the cone (Remix passes it through unchanged).
        // shortcut: semantics read from the API, not seen rendered; confirm on the laptop with a capture's spots.
        s.cone_softness = outer > inner && outer > 0 ? std::fmin(1.f, (outer - inner) / outer) : 0.f;
    }
    return s;
}

}  // namespace light_convert
