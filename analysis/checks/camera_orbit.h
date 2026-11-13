#pragma once
// Item T2 (PLAN_2026-11-13): make a replay (or an unattended game run) move, so the renderer can be exercised in motion.
//
// The camera the proxy hands to Remix is the 14-float form camera_decode.h produces:
//   [0..2] position, [3..5] forward, [6..8] up, [9..11] right, [12] vertical fov in degrees, [13] aspect ratio.
// This applies a yaw sweep around the up vector and/or a dolly along the forward vector, both as a function of elapsed
// time, leaving the frame's own orientation otherwise untouched. Pure and allocation-free, so it is gated natively.
#include <array>
#include <cmath>
#include <cstddef>

namespace camera_orbit {

constexpr double kPi = 3.14159265358979323846;

inline void normalise(float v[3]) {
    const double len = std::sqrt(double(v[0]) * v[0] + double(v[1]) * v[1] + double(v[2]) * v[2]);
    if (!(len > 1e-9)) { v[0] = 0.f; v[1] = 0.f; v[2] = -1.f; return; }
    for (int i = 0; i < 3; ++i) v[i] = static_cast<float>(double(v[i]) / len);
}

inline double dot(const float a[3], const float b[3]) {
    return double(a[0]) * b[0] + double(a[1]) * b[1] + double(a[2]) * b[2];
}

inline void cross(const float a[3], const float b[3], float out[3]) {
    const double x = double(a[1]) * b[2] - double(a[2]) * b[1];
    const double y = double(a[2]) * b[0] - double(a[0]) * b[2];
    const double z = double(a[0]) * b[1] - double(a[1]) * b[0];
    out[0] = static_cast<float>(x);
    out[1] = static_cast<float>(y);
    out[2] = static_cast<float>(z);
}

// Rotate `v` about the unit vector `axis` by `radians` (Rodrigues). No-op for a zero angle.
inline void rotate(float v[3], const float axis[3], double radians) {
    const double c = std::cos(radians), s = std::sin(radians);
    float k[3];
    cross(axis, v, k);                       // axis x v
    const double kv = dot(axis, v);          // axis . v
    for (int i = 0; i < 3; ++i) {
        const double value = double(v[i]) * c + double(k[i]) * s + double(axis[i]) * kv * (1.0 - c);
        v[i] = static_cast<float>(value);
    }
}

// `seconds` since the motion started, `degrees_per_second` of yaw about up, `units_per_second` of dolly along forward.
// Returns true when anything was applied. The basis stays orthonormal: forward and right are rotated together and
// re-orthonormalised against up, so a caller that trusts the decode's invariants still can.
inline bool apply(std::array<float, 14>& camera, double seconds, double degrees_per_second, double units_per_second) {
    if (!(seconds > 0.0) || (!degrees_per_second && !units_per_second)) return false;
    float* position = &camera[0];
    float* forward = &camera[3];
    float* up = &camera[6];
    float* right = &camera[9];
    normalise(forward);
    normalise(up);
    normalise(right);
    if (degrees_per_second) {
        rotate(forward, up, seconds * degrees_per_second * kPi / 180.0);
        cross(forward, up, right);           // right = forward x up: (-Z) x (+Y) = +X, the decode's convention
        normalise(right);
        cross(right, forward, up);           // up = right x forward, so the three stay orthonormal after the yaw
        normalise(up);
    }
    if (units_per_second) {
        for (int i = 0; i < 3; ++i) position[i] = static_cast<float>(double(position[i]) + forward[i] * units_per_second * seconds);
    }
    return true;
}

}  // namespace camera_orbit
