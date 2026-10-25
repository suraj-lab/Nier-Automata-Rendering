// FROZEN gate for geometry_convert.h. Do not edit to make a candidate pass.
#include "geometry_convert.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

using geometry_convert::Element;
using geometry_convert::Vertex;

static void put_f32(std::vector<unsigned char>& b, float v) {
    unsigned char t[4]; std::memcpy(t, &v, 4); b.insert(b.end(), t, t + 4);
}
static void put_u32(std::vector<unsigned char>& b, std::uint32_t v) {
    unsigned char t[4]; std::memcpy(t, &v, 4); b.insert(b.end(), t, t + 4);
}

int main() {
    unsigned checks = 0;
    // Layout: POSITION float3 @0, NORMAL float3 @12, TEXCOORD float2 @24, stride 32 (4 pad).
    const std::vector<Element> layout = {{"POSITION", 6, 0}, {"NORMAL", 6, 12}, {"TEXCOORD", 16, 24}};
    std::vector<unsigned char> bytes;
    const float data[3][8] = {{1,2,3, 0,0,-1, 0,0}, {4,5,6, 0,1,0, 0.5f,0.5f}, {7,8,9, 1,0,0, 1,1}};
    for (int i = 0; i < 3; ++i) {
        put_f32(bytes, data[i][0]); put_f32(bytes, data[i][1]); put_f32(bytes, data[i][2]);
        put_f32(bytes, data[i][3]); put_f32(bytes, data[i][4]); put_f32(bytes, data[i][5]);
        put_f32(bytes, data[i][6]); put_f32(bytes, data[i][7]);
    }
    assert(bytes.size() == 3 * 32);  // POSITION@0 + NORMAL@12 + TEXCOORD@24 = 32, no pad
    std::vector<Vertex> vertices;
    assert(geometry_convert::convert(bytes.data(), bytes.size(), 32, layout, vertices));
    assert(vertices.size() == 3);
    for (int i = 0; i < 3; ++i) {
        for (int k = 0; k < 3; ++k) assert(std::fabs(vertices[i].position[k] - data[i][k]) < 1e-6);
        for (int k = 0; k < 3; ++k) assert(std::fabs(vertices[i].normal[k] - data[i][3 + k]) < 1e-6);
        for (int k = 0; k < 2; ++k) assert(std::fabs(vertices[i].texcoord[k] - data[i][6 + k]) < 1e-6);
        assert(vertices[i].color == 0xffffffff);  // no COLOR element -> default
    }
    ++checks;

    // COLOR element (R8G8B8A8_UNORM) at its own offset.
    std::vector<unsigned char> cv;
    put_f32(cv, 1); put_f32(cv, 2); put_f32(cv, 3);   // POSITION @0
    put_u32(cv, 0x11223344);                          // COLOR @12
    put_f32(cv, 0.5f); put_f32(cv, 0.25f);            // TEXCOORD @16
    std::vector<Vertex> color_out;
    const std::vector<Element> color_layout = {{"POSITION", 6, 0}, {"COLOR", 28, 12}, {"TEXCOORD", 16, 16}};
    assert(geometry_convert::convert(cv.data(), 24, 24, color_layout, color_out));
    assert(color_out.size() == 1 && color_out[0].color == 0x11223344);
    assert(std::fabs(color_out[0].texcoord[1] - 0.25f) < 1e-6);
    ++checks;

    // Half-float formats (R16G16B16A16_FLOAT=10, R16G16_FLOAT=34) — what the real capture produced.
    assert(std::fabs(geometry_convert::half_to_float(0x3C00) - 1.0f) < 1e-6);
    assert(std::fabs(geometry_convert::half_to_float(0xC000) - -2.0f) < 1e-6);
    assert(geometry_convert::half_to_float(0x0000) == 0.0f);
    assert(std::fabs(geometry_convert::half_to_float(0x0001) - 5.9604645e-8f) < 1e-12f);  // 2^-24 subnormal
    assert(std::fabs(geometry_convert::half_to_float(0x7BFF) - 65504.0f) < 1.0f);
    assert(std::isinf(geometry_convert::half_to_float(0x7C00)));
    std::vector<unsigned char> hb;
    const unsigned short pos[4] = {0x3C00, 0x4000, 0x4200, 0x4400};  // 1,2,3,4
    const unsigned short uv[2] = {0x3800, 0x3400};                    // 0.5, 0.25
    for (auto v : pos) { hb.push_back(static_cast<unsigned char>(v & 0xff)); hb.push_back(static_cast<unsigned char>(v >> 8)); }
    for (auto v : uv)  { hb.push_back(static_cast<unsigned char>(v & 0xff)); hb.push_back(static_cast<unsigned char>(v >> 8)); }
    const std::vector<Element> hlayout = {{"POSITION", 10, 0}, {"TEXCOORD", 34, 8}};
    std::vector<Vertex> hout;
    assert(geometry_convert::convert(hb.data(), 12, 12, hlayout, hout));
    assert(hout.size() == 1);
    assert(std::fabs(hout[0].position[0] - 1) < 1e-6 && std::fabs(hout[0].position[1] - 2) < 1e-6 && std::fabs(hout[0].position[2] - 3) < 1e-6);
    assert(std::fabs(hout[0].texcoord[0] - 0.5f) < 1e-6 && std::fabs(hout[0].texcoord[1] - 0.25f) < 1e-6);
    ++checks;

    // Index conversion: R16_UINT (57) and R32_UINT (42).
    std::vector<std::uint32_t> idx;
    const unsigned char i16[6] = {0x00,0x00, 0x01,0x00, 0x02,0x00};
    assert(geometry_convert::convert_indices(i16, 6, 57, idx) && (idx == std::vector<std::uint32_t>{0, 1, 2}));
    const unsigned char i32[12] = {0,0,0,0, 1,0,0,0, 2,0,0,0};
    assert(geometry_convert::convert_indices(i32, 12, 42, idx) && (idx == std::vector<std::uint32_t>{0, 1, 2}));
    ++checks;

    // Failure cases.
    assert(!geometry_convert::convert(bytes.data(), 33, 32, layout, vertices));  // not a multiple of stride
    assert(!geometry_convert::convert(nullptr, 0, 32, layout, vertices));        // null with zero size
    assert(!geometry_convert::convert_indices(i16, 5, 57, idx));                 // odd R16 size
    assert(!geometry_convert::convert_indices(i32, 10, 42, idx));                // non-multiple R32 size
    assert(!geometry_convert::convert_indices(i16, 6, 0, idx));                  // unknown format
    // A huge offset must NOT wrap the bound check (reviewer P2): element is skipped, vertex stays default.
    const std::vector<Element> huge = {{"POSITION", 6, 0xFFFFFFF0u}};
    std::vector<Vertex> skipped;
    assert(geometry_convert::convert(bytes.data(), 32, 32, huge, skipped));
    assert(skipped.size() == 1 && skipped[0].position[0] == 0.0f && skipped[0].color == 0xffffffff);
    ++checks;

    std::printf("{\"passed\":true,\"checks\":%u}\n", checks);
}
