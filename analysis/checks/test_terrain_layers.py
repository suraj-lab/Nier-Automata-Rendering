#!/usr/bin/env python3
"""Gate for item L5b (PLAN_2026-11-13): terrain layers by vertex colour, one Remix surface per layer.

Native, sanitized, against live_scene.h and terrain_layers.h with a recording fake API:
  - two layers (L0 = 1-R, L1 = R): red triangles take layer 1, the rest layer 0;
  - three layers (L0 = (1-R)(1-G), L1 = R(1-G), L2 = G): green wins over red, black stays layer 0;
  - no second layer captured: nothing assigned, one surface as before;
  - a mesh with assigned layers is built as one surface per layer present, each with its own albedo path, its own
    triangles, and its UVs scaled by its repeat relative to layer 0; a layer with no triangles has no surface.
The capture half (texture and repeat per slot from the tracer's uv[] roles) is checked on a real capture by replay.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
VENDOR = C.parent / 'remix-probe/vendor'

HARNESS = r'''
#include <cstdio>
#include <cwchar>
#include <map>
#include <string>
#include <vector>
#include "live_scene.h"
#include "terrain_layers.h"

static std::map<unsigned long long, std::wstring> albedo;   // material handle -> albedo path ("" = none)
struct Surf { unsigned long long material; std::size_t indices; float u0; };
static std::vector<std::vector<Surf>> meshes;
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    albedo[next_handle] = i && i->albedoTexture ? i->albedoTexture : L"";
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* out) {
    std::vector<Surf> s;
    for (std::uint32_t k = 0; k < i->surfaces_count; ++k) {
        const auto& sf = i->surfaces_values[k];
        float u = 0.f;   // the texcoord of the first vertex an index of this surface names
        if (sf.indices_count) u = sf.vertices_values[sf.indices_values[0]].texcoord[0];
        s.push_back({static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(sf.material)), sf.indices_count, u});
    }
    meshes.push_back(s);
    *out = reinterpret_cast<remixapi_MeshHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL ok_handle(void*) { return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL create_light(const remixapi_LightInfo*, remixapi_LightHandle* out) {
    *out = reinterpret_cast<remixapi_LightHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}

static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }

// Four triangles over 12 vertices; triangle t's three vertices carry colours[t] (R low byte) and u = 1.
static live_capture::Upload quad(const std::uint32_t colours[4]) {
    live_capture::Upload u;
    u.geometry = 0x1234500000001ull;
    u.texture = 1;
    for (std::uint32_t i = 0; i < 12; ++i) {
        live_capture::Vertex v{};
        v.texcoord[0] = 1.f;
        v.color = colours[i / 3];
        u.vertices.push_back(v);
        u.indices.push_back(i);
    }
    return u;
}

int main() {
    remixapi_Interface api{};
    api.CreateMaterial = create_material;
    api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
    api.CreateMesh = create_mesh;
    api.DestroyMesh = reinterpret_cast<decltype(api.DestroyMesh)>(ok_handle);
    api.CreateLight = create_light;
    api.DestroyLight = reinterpret_cast<decltype(api.DestroyLight)>(ok_handle);
    const live_capture::Frame frame{};
    const nscn::Options options{};
    const float scales[3][2] = {{5.f, 5.f}, {10.f, 10.f}, {25.f, 25.f}};

    {   // two layers
        const std::uint32_t colours[4] = {0x000000ffu, 0x00000000u, 0x000000ffu, 0x00000010u};
        auto u = quad(colours);
        const std::uint32_t ids[3] = {1, 2, 0};
        terrain_layers::assign(u, ids, scales);
        check("2: one layer per triangle", u.triangle_layer.size() == 4);
        check("2: red takes layer 1, the rest layer 0",
              u.triangle_layer == std::vector<std::uint8_t>({1, 0, 1, 0}));
        check("2: repeat relative to layer 0", u.layer_scale[1][0] == 2.f && u.layer_scale[0][0] == 1.f);
    }
    {   // three layers
        const std::uint32_t colours[4] = {0x0000ff00u, 0x000000ffu, 0x00000000u, 0x0000ffffu};
        auto u = quad(colours);
        const std::uint32_t ids[3] = {1, 2, 3};
        terrain_layers::assign(u, ids, scales);
        check("3: green -> 2, red -> 1, black -> 0, red+green -> 2",
              u.triangle_layer == std::vector<std::uint8_t>({2, 1, 0, 2}));
    }
    {   // height blend with the real numbers of 41686139 draws 1697/1703: t0 alpha 0.2, t1 alpha 1.0, cb1[1].w 0.1
        // G 0xf2 (0.95) alone: raw weights pick layer 2, the shader's w2 = sat((0.95 - 1.0) / 0.1) = 0 keeps layer 0;
        // R 0x80 (0.5): w1 = sat((0.5 - 0.2) / 0.1) = 1 -> layer 1.
        const std::uint32_t colours[4] = {0x0000f200u, 0x00000080u, 0x00000000u, 0x0000ff00u};
        auto u = quad(colours);
        const std::uint32_t ids[3] = {1, 2, 3};
        const float alpha[2] = {0.2f, 1.0f};
        terrain_layers::assign(u, ids, scales, alpha, 0.1f);
        // ... and even G = 1.0 gives w2 = sat(0 / 0.1) = 0: with t1's alpha at 1.0 the game never shows layer 2 here.
        check("height: green stays layer 0 below t1's alpha (even at 1.0), R above t0's alpha goes to layer 1",
              u.triangle_layer == std::vector<std::uint8_t>({0, 1, 0, 0}));
    }
    {   // nothing captured beyond layer 0
        const std::uint32_t colours[4] = {0x000000ffu, 0, 0, 0};
        auto u = quad(colours);
        const std::uint32_t ids[3] = {1, 0, 0};
        terrain_layers::assign(u, ids, scales);
        check("none: no assignment", u.triangle_layer.empty() && u.layer_texture[0] == 0);
    }
    {   // build: two of three layers present
        live_scene::State s;
        live_scene::update(api, {}, {live_capture::TextureFile{1, L"C:\\t\\live_1.dds", nullptr, false, -1, false},
                                     live_capture::TextureFile{2, L"C:\\t\\live_2.dds", nullptr, false, -1, false},
                                     live_capture::TextureFile{3, L"C:\\t\\live_3.dds", nullptr, false, -1, false}},
                           frame, s, options);
        const std::uint32_t colours[4] = {0x000000ffu, 0x00000000u, 0x000000ffu, 0x00000000u};
        auto u = quad(colours);
        const std::uint32_t ids[3] = {1, 2, 3};   // layer 2 captured but no triangle is green: no surface for it
        terrain_layers::assign(u, ids, scales);
        live_scene::update(api, {u}, {}, frame, s, options);
        check("build: one mesh", meshes.size() == 1);
        if (meshes.size() == 1) {
            const auto& m = meshes[0];
            check("build: one surface per layer present (2)", m.size() == 2);
            if (m.size() == 2) {
                check("build: layer 0 keeps its albedo", albedo[m[0].material] == L"C:\\t\\live_1.dds");
                check("build: layer 1 names its own albedo", albedo[m[1].material] == L"C:\\t\\live_2.dds");
                check("build: six indices each", m[0].indices == 6 && m[1].indices == 6);
                check("build: layer 1 UVs scaled by 10/5", m[0].u0 == 1.f && m[1].u0 == 2.f);
            }
        }
        live_scene::destroy(api, s);
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='terrain-layers-'))
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'compile failed:\n' + r.stderr[-2500:]}))
        return 1
    run = subprocess.run([str(work / 'harness')], capture_output=True, text=True,
                         env={**os.environ, 'NIER_REMIX_LIVE_GREY_FIRST': '0'})
    ok = run.returncode == 0
    print(json.dumps({'passed': ok, 'output': (run.stdout + run.stderr)[-2500:]}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
