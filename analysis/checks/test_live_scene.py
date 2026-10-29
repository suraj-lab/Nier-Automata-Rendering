#!/usr/bin/env python3
"""Gate for the worker-side live scene (analysis/checks/live_scene.h): handles, LRU eviction, draws.

Compiled natively with sanitizers against a recording stand-in for the Remix runtime, so handle lifetimes,
eviction and per-instance data are checked without a GPU or Wine.

Usage: python3 analysis/checks/test_live_scene.py [path/to/live_scene.h]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
VENDOR = A / 'remix-probe/vendor'
HEADER = Path(sys.argv[1]) if sys.argv[1:] else C / 'live_scene.h'

HARNESS = r'''
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "live_scene.h"

// ---- recording stand-in for the Remix runtime ---------------------------------------------------
static std::map<void*, std::size_t> live_meshes;   // handle -> vertex bytes (proves destroy frees)
static std::map<void*, int> live_materials;
static std::vector<std::string> calls;
static unsigned destroyed_meshes = 0, destroyed_materials = 0, lights = 0, destroyed_lights = 0;
static unsigned long long next_handle = 0x1000;
static std::vector<float> last_bones;
static std::vector<std::pair<float, float>> instances;  // (matrix[0][3], matrix[1][3]) = translation
static unsigned last_instances = 0;
static float last_aspect = 0;

static std::vector<unsigned long long> material_hashes;
static remixapi_ErrorCode REMIXAPI_CALL f_create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    calls.push_back(std::string("CreateMaterial ") + (i && i->albedoTexture ? "path" : "null"));
    if (i) material_hashes.push_back(static_cast<unsigned long long>(i->hash));
    live_materials[reinterpret_cast<void*>(next_handle)] = 1;
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_destroy_material(remixapi_MaterialHandle h) {
    destroyed_materials += live_materials.erase(reinterpret_cast<void*>(h)) ? 1u : 0u;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static bool fail_mesh_creation = false, hash_mesh_handles = false;
static remixapi_ErrorCode REMIXAPI_CALL f_create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* out) {
    if (fail_mesh_creation) return REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
    std::size_t bytes = 0;
    for (std::uint32_t s = 0; i && s < i->surfaces_count; ++s)
        bytes += i->surfaces_values[s].vertices_count * sizeof(remixapi_HardcodedVertex) +
                 i->surfaces_values[s].indices_count * sizeof(std::uint32_t);
    calls.push_back("CreateMesh");
    const auto handle = hash_mesh_handles ? i->hash : next_handle++;
    live_meshes[reinterpret_cast<void*>(handle)] = bytes;
    *out = reinterpret_cast<remixapi_MeshHandle>(handle);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_destroy_mesh(remixapi_MeshHandle h) {
    if (live_meshes.erase(reinterpret_cast<void*>(h))) ++destroyed_meshes;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static bool hash_light_handles = false;
static std::map<void*, float> live_lights;  // handle -> radiance.x (hash mode: handle == hash, as in the runtime)
static std::map<void*, float> live_sun_dirs; // handle -> distant direction.x
static remixapi_ErrorCode REMIXAPI_CALL f_create_light(const remixapi_LightInfo* i, remixapi_LightHandle* out) {
    ++lights;
    const auto handle = hash_light_handles ? static_cast<unsigned long long>(i->hash) : next_handle++;
    live_lights[reinterpret_cast<void*>(handle)] = i->radiance.x;
    const auto* d = static_cast<const remixapi_LightInfoDistantEXT*>(i->pNext);
    if (d && d->sType == REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DISTANT_EXT) live_sun_dirs[reinterpret_cast<void*>(handle)] = d->direction.x;
    *out = reinterpret_cast<remixapi_LightHandle>(handle);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_destroy_light(remixapi_LightHandle h) {
    ++destroyed_lights;
    live_lights.erase(reinterpret_cast<void*>(h));
    live_sun_dirs.erase(reinterpret_cast<void*>(h));
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_setup_camera(const remixapi_CameraInfo* c) {
    const auto* p = static_cast<const remixapi_CameraInfoParameterizedEXT*>(c->pNext);
    last_aspect = p ? p->aspect : -1.f;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_draw_instance(const remixapi_InstanceInfo* i) {
    ++last_instances;
    instances.push_back({i->transform.matrix[0][3], i->transform.matrix[1][3]});
    const auto* bones = static_cast<const remixapi_InstanceInfoBoneTransformsEXT*>(i->pNext);
    if (bones && bones->boneTransforms_count) {
        last_bones.clear();
        for (std::uint32_t b = 0; b < bones->boneTransforms_count; ++b)
            for (int r = 0; r < 3; ++r)
                for (int c = 0; c < 4; ++c) last_bones.push_back(bones->boneTransforms_values[b].matrix[r][c]);
    }
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_draw_light(remixapi_LightHandle) { return REMIXAPI_ERROR_CODE_SUCCESS; }

static remixapi_Interface make_api() {
    remixapi_Interface api{};
    api.CreateMaterial = f_create_material;
    api.DestroyMaterial = f_destroy_material;
    api.CreateMesh = f_create_mesh;
    api.DestroyMesh = f_destroy_mesh;
    api.CreateLight = f_create_light;
    api.DestroyLight = f_destroy_light;
    api.SetupCamera = f_setup_camera;
    api.DrawInstance = f_draw_instance;
    api.DrawLightInstance = f_draw_light;
    return api;
}

static live_capture::Upload make_upload(std::uint64_t key, std::size_t vertices, std::uint32_t texture = 0) {
    live_capture::Upload u;
    u.geometry = key;
    u.texture = texture;
    for (std::size_t i = 0; i < vertices; ++i) {
        live_capture::Vertex v{};
        v.color = 0xffffffffu;
        u.vertices.push_back(v);
        u.indices.push_back(static_cast<std::uint32_t>(i));
    }
    return u;
}

int main() {
    auto api = make_api();
    int failures = 0;
    const auto check = [&](const char* what, bool ok) {
        if (!ok) { std::printf("VIOLATION %s\n", what); ++failures; }
    };

    // 1. Eviction frees handles and respects the budget.
    {
        live_scene::State s;
        s.budget = 4096;
        for (std::uint64_t k = 1; k <= 40; ++k) {
            std::vector<live_capture::Upload> up{make_upload(k, 40)};  // one 40-vertex mesh ~2 KB
            live_capture::Frame frame;
            live_capture::Item item; item.geometry = k; frame.items.push_back(item);
            check("update failed", live_scene::update(api, up, {}, frame, s, nscn::Options{}));
        }
        check("budget exceeded", s.bytes <= s.budget);
        check("nothing evicted", s.evicted > 0);
        check("evicted handle leaked", destroyed_meshes == s.evicted);
        check("live meshes exceed what the budget holds", live_meshes.size() == s.meshes.size());
    }

    // 2. Rebuilding the same geometry replaces its mesh instead of leaking the old handle.
    {
        live_scene::State s;
        const std::size_t before = destroyed_meshes, live_before = live_meshes.size();
        std::vector<live_capture::Upload> up{make_upload(7, 20)};
        live_capture::Frame frame;
        live_scene::update(api, up, {}, frame, s, nscn::Options{});
        live_scene::update(api, up, {}, frame, s, nscn::Options{});
        check("rebuild did not replace", destroyed_meshes == before + 1);
        check("rebuild leaked a handle", s.meshes.size() == 1 && live_meshes.size() == live_before + 1);
    }

    // 2b. Actual Remix uses hash-as-handle: registration replaces the old mesh in place.
    {
        hash_mesh_handles = true;
        live_scene::State s;
        const auto before = destroyed_meshes;
        auto up = make_upload(777, 20);
        check("first hash mesh failed", live_scene::build_mesh(api, s, up));
        const auto handle = s.meshes[777];
        up.vertices[0].position[0] = 3.f;
        check("hash mesh replacement failed", live_scene::build_mesh(api, s, up));
        check("replacement destroyed itself", live_meshes.count(reinterpret_cast<void*>(handle)) == 1);
        check("same handle was destroyed", destroyed_meshes == before);
        fail_mesh_creation = true;
        check("failed replacement accepted", !live_scene::build_mesh(api, s, up));
        check("failed replacement lost old mesh", s.meshes[777] == handle && live_meshes.count(reinterpret_cast<void*>(handle)) == 1);
        fail_mesh_creation = false;
        live_scene::destroy(api, s);
        check("hash mesh not freed at teardown", destroyed_meshes == before + 1);
        hash_mesh_handles = false;
    }

    // 3. Lights are created once and reused; the camera aspect reaches SetupCamera.
    {
        live_scene::State s;
        const unsigned lights_before = lights;
        for (int i = 0; i < 5; ++i) live_scene::update(api, {}, {}, live_capture::Frame{}, s, nscn::Options{});
        check("lights recreated", lights == lights_before + 2 && s.sun && s.sky);
        float camera[14] = {0, 0, 0, 0, 0, -1, 0, 1, 0, 1, 0, 0, 60.f, 1.7f};
        // A frame with nothing built must make no runtime call at all (contract: camera, instances, lights, Present).
        last_aspect = 0; last_instances = 0;
        check("unready frame reported ready", !live_scene::ready(live_capture::Frame{}, s));
        live_scene::submit(api, live_capture::Frame{}, s, camera, 1.777f);
        check("unready frame touched the runtime", last_aspect == 0 && last_instances == 0);
        // With a built mesh the camera aspect reaches SetupCamera.
        live_scene::update(api, {make_upload(41, 6)}, {}, live_capture::Frame{}, s, nscn::Options{});
        live_capture::Frame one;
        live_capture::Item item; item.geometry = 41; item.count = 1; one.items.push_back(item);
        float identity[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        one.transforms.insert(one.transforms.end(), identity, identity + 12);
        check("submit failed", live_scene::submit(api, one, s, camera, 1.777f) == REMIXAPI_ERROR_CODE_SUCCESS);
        check("aspect not passed", last_aspect > 1.77f && last_aspect < 1.78f);
    }

    // 4. One instance per item, transforms copied, skinned palette passed through.
    {
        live_scene::State s;
        std::vector<live_capture::Upload> up{make_upload(11, 10), make_upload(12, 10)};
        live_capture::Frame frame;
        live_capture::Item a; a.geometry = 11; a.first = 0; a.count = 1; frame.items.push_back(a);
        float world[12] = {1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7};
        frame.transforms.insert(frame.transforms.end(), world, world + 12);
        live_capture::Item b; b.geometry = 12; b.first = 1; b.count = 1;
        frame.items.push_back(b);
        float world2[12] = {1, 0, 0, 8, 0, 1, 0, 9, 0, 0, 1, 10};
        frame.transforms.insert(frame.transforms.end(), world2, world2 + 12);
        live_scene::update(api, up, {}, frame, s, nscn::Options{});
        last_instances = 0; instances.clear();
        float camera[14] = {0, 0, 0, 0, 0, -1, 0, 1, 0, 1, 0, 0, 60.f, 1.7f};
        live_scene::submit(api, frame, s, camera, 1.7f);
        check("wrong instance count", last_instances == 2);
        check("transforms not copied", instances.size() == 2 && instances[0].first == 5.f && instances[1].second == 9.f);

        // A skinned item carries the palette it was given.
        live_capture::Frame skinned;
        live_capture::Item k; k.geometry = 11; k.first = 0; k.count = 1; k.first_bone = 0; k.bone_count = 2;
        skinned.items.push_back(k);
        float identity[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        skinned.transforms.insert(skinned.transforms.end(), identity, identity + 12);
        skinned.bones.insert(skinned.bones.end(), identity, identity + 12);
        float bone1[12] = {1, 0, 0, 4, 0, 1, 0, 0, 0, 0, 1, 0};
        skinned.bones.insert(skinned.bones.end(), bone1, bone1 + 12);
        last_bones.clear();
        live_scene::submit(api, skinned, s, camera, 1.7f);
        check("bones not passed", last_bones.size() == 24 && last_bones[3] == 0.f && last_bones[12 + 3] == 4.f);
    }

    // 5. A draw whose mesh is not built yet is skipped, not drawn with a stale handle.
    {
        live_scene::State s;
        live_capture::Frame frame;
        live_capture::Item item; item.geometry = 999; item.count = 1; frame.items.push_back(item);
        float camera[14] = {0, 0, 0, 0, 0, -1, 0, 1, 0, 1, 0, 0, 60.f, 1.7f};
        last_instances = 0;
        live_scene::submit(api, frame, s, camera, 1.7f);
        check("unbuilt mesh drawn", last_instances == 0);
    }

    // 6. Destroying the scene frees everything it created.
    {
        live_scene::State s;
        std::vector<live_capture::Upload> up{make_upload(21, 10, 3)};
        s.texture_paths.resize(3);
        s.texture_paths[2] = L"Z:\\textures\\live_3.dds";
        live_scene::update(api, up, {}, live_capture::Frame{}, s, nscn::Options{});
        const std::size_t meshes_before = s.meshes.size(), materials_before = s.materials.size();
        const std::size_t live_before = live_meshes.size(), destroyed_before = destroyed_meshes;
        live_scene::destroy(api, s);
        check("destroy missed a handle", meshes_before == 1 && materials_before == 1 &&
                                        live_meshes.size() + 1 == live_before && destroyed_meshes == destroyed_before + 1);
        check("destroy left state", s.meshes.empty() && s.materials.empty() && s.bytes == 0);
    }

    // 7. Meshes drawn in the current frame are never evicted, and every eviction is reported so the capture side
    //    can forget the geometry and upload it again when it reappears.
    {
        live_scene::State s;
        s.budget = 1;  // far below one mesh
        std::vector<live_capture::Upload> up{make_upload(31, 40), make_upload(32, 40)};
        live_capture::Frame both;
        live_capture::Item a; a.geometry = 31; both.items.push_back(a);
        live_capture::Item b; b.geometry = 32; both.items.push_back(b);
        live_scene::update(api, up, {}, both, s, nscn::Options{});
        check("evicted a mesh drawn this frame", s.meshes.count(31) == 1 && s.meshes.count(32) == 1);
        live_capture::Frame only_a;
        only_a.items.push_back(a);
        live_scene::update(api, {}, {}, only_a, s, nscn::Options{});
        check("unused mesh not evicted over budget", s.meshes.count(32) == 0 && s.meshes.count(31) == 1);
        const auto reported = live_scene::take_evicted(s);
        check("eviction not reported", reported.size() == 1 && reported[0] == 32);
        check("eviction reported twice", live_scene::take_evicted(s).empty());
    }

    // 8. The build backlog keeps only the newest upload per geometry: a geometry rewritten while queued is built
    //    once, with its newest data.
    {
        live_scene::State s;
        std::vector<live_capture::Upload> first;
        for (std::uint64_t k = 100; k < 100 + live_scene::kBuildsPerCall + 50; ++k) first.push_back(make_upload(k, 4));
        live_scene::update(api, std::move(first), {}, live_capture::Frame{}, s, nscn::Options{});
        const unsigned built_after_first = s.built;
        const std::uint64_t queued_key = 100 + live_scene::kBuildsPerCall + 10;  // still in the backlog
        std::vector<live_capture::Upload> second{make_upload(queued_key, 9)};
        live_scene::update(api, std::move(second), {}, live_capture::Frame{}, s, nscn::Options{});
        for (int i = 0; i < 4; ++i) live_scene::update(api, {}, {}, live_capture::Frame{}, s, nscn::Options{});
        check("backlog built a stale duplicate", s.built - built_after_first == 50);
        check("backlog lost the newest data", s.mesh_bytes.count(queued_key) &&
              s.mesh_bytes[queued_key] == 9 * sizeof(remixapi_HardcodedVertex) + 9 * sizeof(std::uint32_t));
    }

    // 10. A mesh the runtime refuses is retried a bounded number of times, not every frame forever (review N2).
    {
        live_scene::State s;
        fail_mesh_creation = true;
        unsigned reported = 0;
        for (int frame = 0; frame < 20; ++frame) {
            live_scene::update(api, {make_upload(77, 6)}, {}, live_capture::Frame{}, s, nscn::Options{});
            reported += static_cast<unsigned>(live_scene::take_evicted(s).size());
        }
        fail_mesh_creation = false;
        check("refused mesh retried forever", reported >= 1 && reported <= 3);
    }

    // 11. The game's captured sun replaces the placeholder; changes recreate it under hash-as-handle; absence keeps it.
    {
        hash_light_handles = true;
        live_lights.clear(); live_sun_dirs.clear();
        live_scene::State s;
        live_capture::Frame f;
        f.has_sun = true;
        f.sun = {{6.f, 5.1f, 4.8f}, {0.43f, -0.84f, 0.34f}};
        live_scene::update(api, {}, {}, f, s, nscn::Options{});
        check("captured sun not live", s.sun && live_lights.count(s.sun) && live_lights[s.sun] == 6.f &&
                                        live_sun_dirs[s.sun] == 0.43f);
        const unsigned before = lights;
        live_scene::update(api, {}, {}, f, s, nscn::Options{});
        check("unchanged sun recreated", lights == before);
        f.sun.colour[0] = 3.f;
        live_scene::update(api, {}, {}, f, s, nscn::Options{});
        check("changed sun lost or stale", s.sun && live_lights.count(s.sun) && live_lights[s.sun] == 3.f);
        live_scene::update(api, {}, {}, live_capture::Frame{}, s, nscn::Options{});
        check("frame without sun dropped it", s.sun && live_lights.count(s.sun) && live_lights[s.sun] == 3.f);
        live_scene::destroy(api, s);
        check("lights leaked at teardown", live_lights.empty());
        hash_light_handles = false;
    }

    // 9. Live materials use their own hash range, apart from the captured scene's 1000000/2000000 ranges.
    for (unsigned long long h : material_hashes)
        check("live material hash collides with the captured scene", h >= 3000000ull && h < 4000000ull);

    std::printf("failures=%d evicted=%u destroyed=%u lights=%u\n", failures, 0u, destroyed_meshes, lights);
    return failures ? 1 : 0;
}
'''


def main():
    if not HEADER.exists():
        print(json.dumps({'passed': False, 'error': f'missing {HEADER}'}, indent=2))
        sys.exit(1)
    work = Path(tempfile.mkdtemp(prefix='live-scene-', dir=Path(tempfile.gettempdir())))
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(HEADER.parent), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'compile failed:\n' + r.stderr[-2500:]}, indent=2))
        sys.exit(1)
    run = subprocess.run([str(work / 'harness')], capture_output=True, text=True)
    if run.returncode or 'VIOLATION' in run.stdout:
        print(json.dumps({'passed': False, 'error': (run.stdout + run.stderr)[-2500:]}, indent=2))
        sys.exit(1)
    report = {'passed': True, 'header': str(HEADER),
              'limits': 'Recording stand-in for the runtime; handle lifetimes and LRU, not Remix behaviour.'}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
