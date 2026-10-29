#pragma once
// Decodes a camera capture: first 128 bytes = 32 floats = row-major view 4x4
// (f0..f15) + perspective projection (f16..f31) -> 14 floats written to `out`.
// Pure, allocation-free; `out` is left untouched on any failure.
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace camera_decode {

static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559 &&
              std::numeric_limits<float>::digits == 24, "Camera input requires IEEE binary32 floats");

inline bool decode(const void* bytes, std::size_t size, std::array<float, 14>& out) {
    if (bytes == nullptr || size < 128) {
        return false;
    }
    float f[32];
    for (unsigned i = 0; i < 32; ++i) {
        const auto* p = static_cast<const unsigned char*>(bytes) + 4 * i;
        const std::uint32_t bits = std::uint32_t(p[0]) | (std::uint32_t(p[1]) << 8) |
                                   (std::uint32_t(p[2]) << 16) | (std::uint32_t(p[3]) << 24);
        std::memcpy(&f[i], &bits, 4);  // little-endian input, including unaligned bytes
    }
    for (const float v : f) {
        if (!std::isfinite(v)) {
            return false;
        }
    }

    const auto within = [](double v, double target, double tol) {
        return std::fabs(v - target) <= tol;
    };

    // View: last row must be [0,0,0,1] and the 3x3 must be a proper orthonormal rotation.
    if (!(within(f[12], 0.0, 1e-4) && within(f[13], 0.0, 1e-4) &&
          within(f[14], 0.0, 1e-4) && within(f[15], 1.0, 1e-4))) {
        return false;
    }
    const double R[3][3] = {{f[0], f[1], f[2]}, {f[4], f[5], f[6]}, {f[8], f[9], f[10]}};
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) {
            const double dot = R[i][0] * R[j][0] + R[i][1] * R[j][1] + R[i][2] * R[j][2];
            if (!within(dot, i == j ? 1.0 : 0.0, 1e-3)) {
                return false;
            }
        }
    }
    const double det = R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1]) -
                       R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0]) +
                       R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]);
    if (!within(det, 1.0, 1e-3)) {
        return false;
    }

    // Projection (perspective): m00>0, m11>0, m22<0, m23<0, m32==-1, m33==0; other entries may jitter.
    if (!(f[16] > 0.0f && f[21] > 0.0f && f[26] < 0.0f && f[27] < 0.0f)) {
        return false;
    }
    if (!(within(f[30], -1.0, 1e-4) && within(f[31], 0.0, 1e-4))) {
        return false;
    }

    const double tx = f[3], ty = f[7], tz = f[11];
    const double fovDegrees = 2.0 * std::atan(1.0 / static_cast<double>(f[21])) * 180.0 / std::acos(-1.0);
    const std::array<double, 14> values = {
        -(R[0][0] * tx + R[1][0] * ty + R[2][0] * tz),  // position = -R^T * t
        -(R[0][1] * tx + R[1][1] * ty + R[2][1] * tz),
        -(R[0][2] * tx + R[1][2] * ty + R[2][2] * tz),
        -R[2][0], -R[2][1], -R[2][2],  // forward
        R[1][0], R[1][1], R[1][2],     // up
        R[0][0], R[0][1], R[0][2],     // right
        fovDegrees, static_cast<double>(f[21]) / f[16],
    };
    std::array<float, 14> result{};
    for (unsigned i = 0; i < values.size(); ++i) {
        if (!std::isfinite(values[i]) || std::fabs(values[i]) > (std::numeric_limits<float>::max)()) {
            return false;
        }
        result[i] = static_cast<float>(values[i]);
    }
    if (!(result[12] > 0.0f && result[12] < 180.0f)) {
        return false;
    }
    if (!(result[13] > 0.0f)) {
        return false;
    }

    out = result;  // only assign after everything validated
    return true;
}

}  // namespace camera_decode
