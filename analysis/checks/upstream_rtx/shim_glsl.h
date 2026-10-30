#pragma once
// Minimal GLSL-shaped types so the pinned upstream shader logic (upstream_rtx/pass/skinning.h) compiles
// as C++ without dxvk's SIMD math. Same semantics as GLSL: float4 is a column vector, and
// Matrix4 * float4 is a row-dot-product (translation in the fourth column).
#include <cmath>
#include <cstdint>

typedef unsigned int uint;

struct Vector3 {
    float x, y, z;
    Vector3() : x(0), y(0), z(0) {}
    explicit Vector3(float s) : x(s), y(s), z(s) {}
    Vector3(float a, float b, float c) : x(a), y(b), z(c) {}
    Vector3 operator+(const Vector3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vector3& operator/=(float s) { x /= s; y /= s; z /= s; return *this; }
};

struct Vector4i {
    int x, y, z, w;
    Vector4i() : x(0), y(0), z(0), w(0) {}
    Vector4i(int a, int b, int c, int d) : x(a), y(b), z(c), w(d) {}
    int operator[](int i) const { return i == 0 ? x : i == 1 ? y : i == 2 ? z : w; }  // GLSL uint4[i]
};

struct Vector4 {
    float x, y, z, w;
    Vector4() : x(0), y(0), z(0), w(0) {}
    explicit Vector4(float s) : x(s), y(s), z(s), w(s) {}  // GLSL float4(s)
    Vector4(float a, float b, float c, float d) : x(a), y(b), z(c), w(d) {}
    Vector4 operator+(const Vector4& o) const { return {x + o.x, y + o.y, z + o.z, w + o.w}; }
    Vector4& operator+=(const Vector4& o) { x += o.x; y += o.y; z += o.z; w += o.w; return *this; }
    Vector4 operator*(float s) const { return {x * s, y * s, z * s, w * s}; }
};

inline float length(const Vector3& v) { return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z); }

inline Vector3 normalize(const Vector3& v) {
    const float l = length(v);
    return l > 0 ? Vector3(v.x / l, v.y / l, v.z / l) : Vector3();
}


namespace dxvk {
struct Matrix4 {
    Vector4 rows[4];
    Vector4 operator*(const Vector4& p) const {
        return Vector4{rows[0].x * p.x + rows[0].y * p.y + rows[0].z * p.z + rows[0].w * p.w,
                       rows[1].x * p.x + rows[1].y * p.y + rows[1].z * p.z + rows[1].w * p.w,
                       rows[2].x * p.x + rows[2].y * p.y + rows[2].z * p.z + rows[2].w * p.w,
                       rows[3].x * p.x + rows[3].y * p.y + rows[3].z * p.z + rows[3].w * p.w};
    }
};

// The generated header for gpu_skinning.comp.slang; only the fields skinning.h reads.
struct SkinningArgs {
    Matrix4* bones;
    uint blendWeightOffset, blendIndicesOffset;
    uint blendWeightStride, blendIndicesStride;
    uint srcPositionOffset, srcNormalOffset, dstPositionOffset, dstNormalOffset;
    uint srcPositionStride, srcNormalStride, dstPositionStride, dstNormalStride;
    uint numVertices, numBones;
    uint useIndices, useOctahedralNormals;
};
}  // namespace dxvk
