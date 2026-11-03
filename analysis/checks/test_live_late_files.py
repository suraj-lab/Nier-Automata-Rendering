#!/usr/bin/env python3
"""Gate: live_scene.h builds a mesh only once every texture file its material names has landed, and then once.

Texture files are written on their own thread (remix_live.cpp TextureWriter), so live_scene can see an upload naming a
texture id before that file exists. Building it bare and again later doubles Remix mesh builds exactly during
streaming bursts (and breaks the build-once gates), so the upload waits in the backlog. Native, sanitized, against a
recording stand-in runtime:
  A. albedo landed, normal not: nothing is built; when the normal lands it is built once, with albedo and normal;
  B. nothing landed: nothing is built; both land in one update -> built once, with both;
  C. a file that was never written lands with an empty path: built once without it (constants), never again;
  D. a newer upload of a waiting geometry wins: one build, with the new vertices;
  E. a complete mesh is not rebuilt by later landings of other files;
  F. an albedo that was never written: built once, without a material (untextured), never again.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
VENDOR = C.parent / 'remix-probe/vendor'

HARNESS = r'''
#include <cstdio>
#include <map>
#include <string>
#include <vector>
#include "live_scene.h"

struct Mat { bool albedo, normal; };
static std::map<unsigned long long, Mat> materials;
struct Mesh { unsigned long long material; std::size_t vertices; };
static std::vector<Mesh> meshes;
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    materials[next_handle] = {i && i->albedoTexture, i && i->normalTexture};
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* out) {
    meshes.push_back({static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(i->surfaces_values[0].material)),
                      i->surfaces_values[0].vertices_count});
    *out = reinterpret_cast<remixapi_MeshHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL ok_handle(void*) { return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL create_light(const remixapi_LightInfo*, remixapi_LightHandle* out) {
    *out = reinterpret_cast<remixapi_LightHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}

static live_capture::Upload upload(std::uint64_t key, std::uint32_t texture, std::uint32_t normal, std::size_t n = 6) {
    live_capture::Upload u;
    u.geometry = key; u.texture = texture; u.normal = normal;
    for (std::size_t i = 0; i < n; ++i) { u.vertices.push_back(live_capture::Vertex{}); u.indices.push_back(static_cast<std::uint32_t>(i)); }
    return u;
}
static live_capture::TextureFile file(std::uint32_t id, const wchar_t* path) {
    live_capture::TextureFile f; f.id = id; f.path = path; return f;
}

static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }
static Mat mat_of(const Mesh& m) { return m.material ? materials[m.material] : Mat{false, false}; }

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
    const auto L = [](std::uint32_t id, const wchar_t* path) { return file(id, path); };
    {   // A + E
        live_scene::State s;
        live_scene::update(api, {}, {L(1, L"C:\\t\\live_1.dds")}, frame, s, options);
        live_scene::update(api, {upload(10, 1, 2)}, {}, frame, s, options);
        live_scene::update(api, {}, {}, frame, s, options);
        check("A: not built while the normal is still being written", meshes.empty());
        live_scene::update(api, {}, {L(2, L"C:\\t\\live_2.dds")}, frame, s, options);
        check("A: built once when the normal landed", meshes.size() == 1);
        check("A: with albedo and normal", meshes.size() == 1 && mat_of(meshes[0]).albedo && mat_of(meshes[0]).normal);
        live_scene::update(api, {}, {L(3, L"C:\\t\\live_3.dds")}, frame, s, options);
        check("E: an unrelated landing does not rebuild a complete mesh", meshes.size() == 1);
        live_scene::destroy(api, s);
    }
    meshes.clear();
    {   // B
        live_scene::State s;
        live_scene::update(api, {upload(20, 1, 2)}, {}, frame, s, options);
        check("B: nothing built before anything landed", meshes.empty());
        live_scene::update(api, {}, {L(1, L"C:\\t\\live_1.dds"), L(2, L"C:\\t\\live_2.dds")}, frame, s, options);
        check("B: built once when both landed", meshes.size() == 1);
        check("B: with albedo and normal", meshes.size() == 1 && mat_of(meshes[0]).albedo && mat_of(meshes[0]).normal);
        live_scene::destroy(api, s);
    }
    meshes.clear();
    {   // C
        live_scene::State s;
        live_scene::update(api, {}, {L(1, L"C:\\t\\live_1.dds")}, frame, s, options);
        live_scene::update(api, {upload(30, 1, 2)}, {}, frame, s, options);
        live_scene::update(api, {}, {L(2, L"")}, frame, s, options);
        check("C: built once when the unwritten normal landed", meshes.size() == 1);
        check("C: albedo, no normal", meshes.size() == 1 && mat_of(meshes[0]).albedo && !mat_of(meshes[0]).normal);
        live_scene::update(api, {}, {L(3, L"C:\\t\\live_3.dds")}, frame, s, options);
        live_scene::update(api, {}, {}, frame, s, options);
        check("C: never rebuilt", meshes.size() == 1);
        live_scene::destroy(api, s);
    }
    meshes.clear();
    {   // D
        live_scene::State s;
        live_scene::update(api, {}, {L(1, L"C:\\t\\live_1.dds")}, frame, s, options);
        live_scene::update(api, {upload(40, 1, 2, 6)}, {}, frame, s, options);
        live_scene::update(api, {upload(40, 1, 2, 9)}, {L(2, L"C:\\t\\live_2.dds")}, frame, s, options);
        check("D: one build", meshes.size() == 1);
        check("D: the newer upload's vertices, with the normal",
              meshes.size() == 1 && meshes[0].vertices == 9 && mat_of(meshes[0]).normal);
        live_scene::destroy(api, s);
    }
    meshes.clear();
    {   // F
        live_scene::State s;
        live_scene::update(api, {upload(50, 1, 0)}, {L(1, L"")}, frame, s, options);
        live_scene::update(api, {}, {L(2, L"C:\\t\\live_2.dds")}, frame, s, options);
        check("F: built once, without a material", meshes.size() == 1 && meshes[0].material == 0);
        live_scene::destroy(api, s);
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='live-late-files-'))
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'compile failed:\n' + r.stderr[-2500:]}))
        return 1
    run = subprocess.run([str(work / 'harness')], capture_output=True, text=True)
    ok = run.returncode == 0
    print(json.dumps({'passed': ok, 'output': (run.stdout + run.stderr)[-2500:]}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
