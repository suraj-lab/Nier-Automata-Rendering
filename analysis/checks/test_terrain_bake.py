#!/usr/bin/env python3
"""Gate for item L5b's terrain bake (checks/terrain_bake.h + live_scene.h). Native, sanitized, real files on disk.

  - bake: a texel whose layer-0 alpha is below the vertex red takes layer 1 (sharpness 0.01), the rest keep layer 0;
  - the baked DDS (RGBA8 sRGB) reads back to the same colours;
  - a terrain mesh with two vertex-red levels is built as two surfaces whose materials name their baked tiles, and the
    tile files exist with the blend of their level;
  - built before the layer files exist: a grey material first, then, once both files land, the same hash destroyed and
    created again with the baked tile (the late-texture swap).
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
#include <map>
#include <string>
#include <vector>
#include "live_scene.h"
#include "terrain_layers.h"
#include "terrain_bake.h"

struct Made { std::wstring path; unsigned long long hash; };
static std::map<unsigned long long, Made> made;   // handle -> what CreateMaterial was given
static std::vector<unsigned long long> destroyed;
static std::vector<std::vector<unsigned long long>> meshes;   // per mesh: surface material handles
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    made[next_handle] = {i->albedoTexture ? i->albedoTexture : L"", i->hash};
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL destroy_material(remixapi_MaterialHandle h) {
    destroyed.push_back(static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(h)));
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* out) {
    std::vector<unsigned long long> m;
    for (std::uint32_t k = 0; k < i->surfaces_count; ++k)
        m.push_back(static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(i->surfaces_values[k].material)));
    meshes.push_back(m);
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

// 2x2 layer 0: black, alphas 0, 0.25, 0.5, 1.0; layer 1: white, alpha 1.
static terrain_bake::Image layer(bool white) {
    terrain_bake::Image im; im.w = 2; im.h = 2;
    const float alphas[4] = {0.f, 0.25f, 0.5f, 1.f};
    for (int i = 0; i < 4; ++i) for (int c = 0; c < 4; ++c) im.rgba.push_back(c < 3 ? (white ? 1.f : 0.f) : (white ? 1.f : alphas[i]));
    return im;
}
static live_capture::Upload quad(std::uint64_t key, const std::uint32_t colours[4]) {
    live_capture::Upload u; u.geometry = key; u.texture = 1;
    for (std::uint32_t i = 0; i < 12; ++i) {
        live_capture::Vertex v{}; v.color = colours[i / 3]; u.vertices.push_back(v); u.indices.push_back(i);
    }
    return u;
}

int main(int argc, char** argv) {
    const std::string dir = argc > 1 ? argv[1] : ".";
    {   // the blend itself
        const auto out = terrain_bake::bake(layer(false), layer(true), 0.3f, 0.01f);
        check("bake: alpha 0 and 0.25 below R 0.3 take layer 1", out.rgba[0] > 0.99f && out.rgba[4] > 0.99f);
        check("bake: alpha 0.5 and 1.0 keep layer 0", out.rgba[8] < 0.01f && out.rgba[12] < 0.01f);
        terrain_bake::Image back;
        check("dds: round trip reads", terrain_bake::read_dds(terrain_bake::dds_bytes(out), back) && back.w == 2);
        check("dds: same colours after sRGB encode/decode", back.rgba.size() == 16 && back.rgba[0] > 0.99f && back.rgba[8] < 0.01f);
    }
    const std::wstring wdir(dir.begin(), dir.end());
    const std::wstring p1 = wdir + L"/live_1.dds", p2 = wdir + L"/live_2.dds";
    remixapi_Interface api{};
    api.CreateMaterial = create_material; api.DestroyMaterial = destroy_material;
    api.CreateMesh = create_mesh; api.DestroyMesh = reinterpret_cast<decltype(api.DestroyMesh)>(ok_handle);
    api.CreateLight = create_light; api.DestroyLight = reinterpret_cast<decltype(api.DestroyLight)>(ok_handle);
    const live_capture::Frame frame{};
    const nscn::Options options{};
    const float scales[3][2] = {{5.f, 5.f}, {5.f, 5.f}, {1.f, 1.f}};
    const std::uint32_t ids[3] = {1, 2, 0};
    // Red 0 on two triangles (level 0), red 0xf0 on two (level 7).
    const std::uint32_t colours[4] = {0x00000000u, 0x000000f0u, 0x00000000u, 0x000000f0u};
    {   // files on disk first: baked at once
        check("write layer files", live_scene::write_whole(p1, terrain_bake::dds_bytes(layer(false))) &&
                                   live_scene::write_whole(p2, terrain_bake::dds_bytes(layer(true))));
        live_scene::State s;
        live_scene::update(api, {}, {live_capture::TextureFile{1, p1, nullptr, false, -1, false},
                                     live_capture::TextureFile{2, p2, nullptr, false, -1, false}}, frame, s, options);
        auto u = quad(0x1111100000001ull, colours);
        terrain_layers::assign(u, ids, scales, nullptr, 0.01f);
        check("assign: bake recorded with two levels", u.bake_sharpness == 0.01f && u.triangle_bucket ==
              std::vector<std::uint8_t>({0, 7, 0, 7}));
        live_scene::update(api, {u}, {}, frame, s, options);
        check("build: one mesh, two baked surfaces", meshes.size() == 1 && meshes[0].size() == 2);
        if (meshes.size() == 1 && meshes[0].size() == 2) {
            const std::wstring a = made[meshes[0][0]].path, b = made[meshes[0][1]].path;
            check("build: level 0 names bake_1_2_0", a.find(L"bake_1_2_0_") != std::wstring::npos);
            check("build: level 7 names bake_1_2_7", b.find(L"bake_1_2_7_") != std::wstring::npos);
            std::vector<unsigned char> f;
            terrain_bake::Image im;
            check("tile 7 on disk: alpha 0, 0.25, 0.5 below R 0.94 -> white, alpha 1.0 -> black",
                  live_scene::read_whole(b, f) && terrain_bake::read_dds(f, im) && im.rgba[0] > 0.99f &&
                  im.rgba[8] > 0.99f && im.rgba[12] < 0.01f);
        }
        live_scene::destroy(api, s);
    }
    meshes.clear(); made.clear(); destroyed.clear();
    {   // built before the files land: grey, then the swap under the same hash
        live_scene::State s;
        auto u = quad(0x2222200000001ull, colours);
        terrain_layers::assign(u, ids, scales, nullptr, 0.01f);
        live_scene::update(api, {}, {live_capture::TextureFile{1, L"", nullptr, false, -1, false}}, frame, s, options);
        s.landed.assign(2, 0); s.texture_paths.assign(2, L"");   // nothing on disk yet
        live_scene::update(api, {u}, {}, frame, s, options);
        bool grey = meshes.size() == 1 && meshes[0].size() == 2;
        for (const auto m : grey ? meshes[0] : std::vector<unsigned long long>{}) grey = grey && made[m].path.empty();
        check("late: built grey while the layers are missing", grey);
        const unsigned long long first_hash = grey ? made[meshes[0][1]].hash : 0;
        live_scene::update(api, {}, {live_capture::TextureFile{1, p1, nullptr, false, -1, false},
                                     live_capture::TextureFile{2, p2, nullptr, false, -1, false}}, frame, s, options);
        bool swapped = false;
        for (const auto& [h, m] : made) if (m.hash == first_hash && m.path.find(L"bake_1_2_7_") != std::wstring::npos) swapped = true;
        // Both tiles are swapped (the base layer-0 material is swapped too, by grey-first, so >= 2 destroys).
        unsigned tiles = 0;
        for (const auto& [h, m] : made) if (m.path.find(L"bake_1_2_") != std::wstring::npos) ++tiles;
        check("late: the same hash re-created with the baked tile", swapped && tiles == 2 && destroyed.size() >= 2);
        live_scene::destroy(api, s);
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='terrain-bake-'))
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'compile failed:\n' + r.stderr[-2500:]}))
        return 1
    run = subprocess.run([str(work / 'harness'), str(work)], capture_output=True, text=True, env=dict(os.environ))
    ok = run.returncode == 0
    print(json.dumps({'passed': ok, 'output': (run.stdout + run.stderr)[-2500:]}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
