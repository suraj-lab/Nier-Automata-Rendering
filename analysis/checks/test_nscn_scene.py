#!/usr/bin/env python3
"""Frozen gate for nscn_scene.h: NSCN v3 scene file -> Remix materials, one mesh, sun + sky lights.

The header is what the in-game Remix host (remix_live.cpp) uses to put a converted F9 capture on screen. Its look
must equal the standalone probe's defaults (remix-probe/triangle.cpp, SCENE_FILE build, no REPROBE_* overrides),
because that is the image already accepted from the probe.

Every Remix call is made through a remixapi_Interface the caller passes in, so this gate replaces the runtime with a
recorder that deep-copies what it is given. Compiled natively with g++ (remix_c.h with its Win32 parts disabled).

Usage: test_nscn_scene.py <nscn_scene.h>
Prints {"passed": bool, "checks": [...], "error": str?}.
"""
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
VENDOR = C.parent / 'remix-probe' / 'vendor'
REAL = C.parent / 'runtime' / 'remix-probe' / 'textured-scene' / 'scene.bin'

HARNESS = r'''
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include "nscn_scene.h"

static_assert(sizeof(remixapi_HardcodedVertex) == 64, "pinned SDK vertex layout");

// ---- recorder ------------------------------------------------------------------------------------------------
struct Mat { unsigned long long hash; std::wstring albedo; const wchar_t* albedo_ptr; bool has_albedo; remixapi_MaterialInfoOpaqueEXT op; bool has_op;
             float emissive; remixapi_MaterialHandle handle; };
struct Surf { std::size_t first_vertex; std::size_t vertices; bool indices_null; std::size_t indices; remixapi_MaterialHandle material; };
struct MeshRec { unsigned long long hash; std::vector<Surf> surfaces; std::vector<remixapi_HardcodedVertex> verts; remixapi_MeshHandle handle; };
struct LightRec { unsigned long long hash; remixapi_StructType ext; remixapi_Float3D radiance;
                  remixapi_LightInfoDistantEXT distant; remixapi_LightInfoDomeEXT dome; bool dome_tex; remixapi_LightHandle handle; };
static std::vector<Mat> mats; static std::vector<MeshRec> meshes; static std::vector<LightRec> lights;
static std::vector<std::string> calls;  // ordered log of every call
static remixapi_CameraInfoParameterizedEXT cam_params; static remixapi_CameraType cam_type; static bool cam_ok;
static remixapi_InstanceInfo inst; static std::vector<void*> destroyed;
static int fail_material_at = -1, fail_mesh = 0, fail_light_at = -1, n_material = 0, n_light = 0;
static const remixapi_HardcodedVertex* base_vertices = nullptr;
static unsigned long long next_handle = 0x1000;

static remixapi_ErrorCode REMIXAPI_CALL f_create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    calls.push_back("CreateMaterial");
    if (n_material++ == fail_material_at) return REMIXAPI_ERROR_CODE_INVALID_ARGUMENTS;
    Mat m{}; m.hash = i->hash; m.has_albedo = i->albedoTexture != nullptr; m.albedo_ptr = i->albedoTexture;  // read later: the runtime keeps the pointer
    m.emissive = i->emissiveIntensity;
    const auto* op = static_cast<const remixapi_MaterialInfoOpaqueEXT*>(i->pNext);
    m.has_op = op && op->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT; if (m.has_op) m.op = *op;
    m.handle = reinterpret_cast<remixapi_MaterialHandle>(next_handle++); mats.push_back(m); *out = m.handle;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_destroy_material(remixapi_MaterialHandle h) { calls.push_back("DestroyMaterial"); destroyed.push_back(h); return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL f_create_mesh(const remixapi_MeshInfo* i, remixapi_MeshHandle* out) {
    calls.push_back("CreateMesh");
    if (fail_mesh) return REMIXAPI_ERROR_CODE_INVALID_ARGUMENTS;
    MeshRec r{}; r.hash = i->hash;
    const remixapi_HardcodedVertex* lo = nullptr;
    for (std::uint32_t k = 0; k < i->surfaces_count; ++k) if (!lo || i->surfaces_values[k].vertices_values < lo) lo = i->surfaces_values[k].vertices_values;
    base_vertices = lo;
    for (std::uint32_t k = 0; k < i->surfaces_count; ++k) {
        const auto& s = i->surfaces_values[k];
        r.surfaces.push_back({std::size_t(s.vertices_values - lo), s.vertices_count, s.indices_values == nullptr, s.indices_count, s.material});
        if (s.vertices_values) r.verts.insert(r.verts.end(), s.vertices_values, s.vertices_values + s.vertices_count);
    }
    r.handle = reinterpret_cast<remixapi_MeshHandle>(next_handle++); meshes.push_back(r); *out = r.handle;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_destroy_mesh(remixapi_MeshHandle h) { calls.push_back("DestroyMesh"); destroyed.push_back(h); return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL f_create_light(const remixapi_LightInfo* i, remixapi_LightHandle* out) {
    calls.push_back("CreateLight");
    if (n_light++ == fail_light_at) return REMIXAPI_ERROR_CODE_INVALID_ARGUMENTS;
    LightRec r{}; r.hash = i->hash; r.radiance = i->radiance;
    const auto* ext = static_cast<const remixapi_LightInfoDistantEXT*>(i->pNext);
    r.ext = ext ? ext->sType : REMIXAPI_STRUCT_TYPE_NONE;
    if (r.ext == REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DISTANT_EXT) r.distant = *ext;
    if (r.ext == REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DOME_EXT) { r.dome = *static_cast<const remixapi_LightInfoDomeEXT*>(i->pNext); r.dome_tex = r.dome.colorTexture != nullptr; }
    r.handle = reinterpret_cast<remixapi_LightHandle>(next_handle++); lights.push_back(r); *out = r.handle;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_destroy_light(remixapi_LightHandle h) { calls.push_back("DestroyLight"); destroyed.push_back(h); return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL f_setup_camera(const remixapi_CameraInfo* i) {
    calls.push_back("SetupCamera"); cam_type = i->type;
    const auto* p = static_cast<const remixapi_CameraInfoParameterizedEXT*>(i->pNext);
    cam_ok = p && p->sType == REMIXAPI_STRUCT_TYPE_CAMERA_INFO_PARAMETERIZED_EXT && i->sType == REMIXAPI_STRUCT_TYPE_CAMERA_INFO;
    if (cam_ok) cam_params = *p;
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL f_draw_instance(const remixapi_InstanceInfo* i) { calls.push_back("DrawInstance"); inst = *i; return REMIXAPI_ERROR_CODE_SUCCESS; }
static std::vector<remixapi_LightHandle> drawn_lights;
static int fail_draw_light = 0;
static remixapi_ErrorCode REMIXAPI_CALL f_draw_light(remixapi_LightHandle h) { calls.push_back("DrawLightInstance"); drawn_lights.push_back(h); return fail_draw_light ? REMIXAPI_ERROR_CODE_INVALID_ARGUMENTS : REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL f_present(const remixapi_PresentInfo*) { calls.push_back("Present"); return REMIXAPI_ERROR_CODE_SUCCESS; }

static remixapi_Interface api() {
    remixapi_Interface a{};
    a.CreateMaterial = f_create_material; a.DestroyMaterial = f_destroy_material;
    a.CreateMesh = f_create_mesh; a.DestroyMesh = f_destroy_mesh;
    a.CreateLight = f_create_light; a.DestroyLight = f_destroy_light;
    a.SetupCamera = f_setup_camera; a.DrawInstance = f_draw_instance; a.DrawLightInstance = f_draw_light;
    a.Present = f_present;
    return a;
}

// ---- output ----------------------------------------------------------------------------------------------------
static FILE* out = stdout;
static void str(const char* k, const std::string& v, bool comma = true) {
    std::string e; for (char c : v) { if (c == '\\' || c == '"') e.push_back('\\'); e.push_back(c); }  // JSON-escape
    std::fprintf(out, "\"%s\":\"%s\"%s", k, e.c_str(), comma ? "," : "");
}
static std::string narrow(const std::wstring& w) { std::string s; for (wchar_t c : w) s.push_back(c < 128 ? char(c) : '?'); return s; }
static void dump(const char* name, remixapi_ErrorCode rc, const nscn::Built* b) {
    // Remix keeps albedoTexture after CreateMaterial returns (the probe reserves for exactly this), so the path must
    // still be valid now, after build() returned. Under -fsanitize=address a dangling pointer aborts here.
    for (auto& m : mats) {
        const bool alive = std::find(destroyed.begin(), destroyed.end(), static_cast<void*>(m.handle)) == destroyed.end();
        if (m.albedo_ptr && alive) m.albedo = m.albedo_ptr;  // a destroyed material's path may be freed
    }
    std::fprintf(out, "{\"case\":\"%s\",\"rc\":%d,", name, int(rc));
    if (b) std::fprintf(out, "\"built\":{\"surfaces\":%u,\"sky_skipped\":%u,\"untextured\":%u,\"materials\":%zu,\"mesh\":%d,\"sun\":%d,\"sky\":%d,\"paths\":%zu,\"vertices\":%zu},",
                        b->surfaces, b->sky_skipped, b->untextured, b->materials.size(), b->mesh != nullptr, b->sun != nullptr, b->sky != nullptr,
                        b->texture_paths.size(), b->vertices.size());
    std::fprintf(out, "\"calls\":[");
    for (std::size_t i = 0; i < calls.size(); ++i) std::fprintf(out, "%s\"%s\"", i ? "," : "", calls[i].c_str());
    std::fprintf(out, "],\"materials\":[");
    for (std::size_t i = 0; i < mats.size(); ++i) {
        const auto& m = mats[i]; const auto& o = m.op;
        std::fprintf(out, "%s{\"hash\":%llu,\"handle\":%llu,\"has_albedo\":%d,", i ? "," : "", m.hash, (unsigned long long)m.handle, m.has_albedo);
        str("albedo", narrow(m.albedo));
        std::fprintf(out, "\"emissive\":%g,\"has_op\":%d,\"albedoConstant\":[%g,%g,%g],\"opacity\":%g,\"roughness\":%g,\"metallic\":%g,"
                     "\"useDrawCallAlphaState\":%d,\"alphaTestType\":%d,\"alphaReferenceValue\":%d,\"blendType_hasvalue\":%d,"
                     "\"blendType_value\":%d,\"invertedBlend\":%d}",
                     m.emissive, m.has_op, o.albedoConstant.x, o.albedoConstant.y, o.albedoConstant.z, o.opacityConstant, o.roughnessConstant,
                     o.metallicConstant, o.useDrawCallAlphaState, o.alphaTestType, o.alphaReferenceValue, o.blendType_hasvalue,
                     o.blendType_value, o.invertedBlend);
    }
    std::fprintf(out, "],\"meshes\":[");
    for (std::size_t i = 0; i < meshes.size(); ++i) {
        const auto& r = meshes[i];
        std::fprintf(out, "%s{\"hash\":%llu,\"surfaces\":[", i ? "," : "", r.hash);
        for (std::size_t k = 0; k < r.surfaces.size(); ++k) {
            const auto& s = r.surfaces[k];
            std::fprintf(out, "%s[%zu,%zu,%d,%zu,%llu]", k ? "," : "", s.first_vertex, s.vertices, s.indices_null, s.indices,
                         (unsigned long long)s.material);
        }
        std::fprintf(out, "],\"verts\":[");
        const std::size_t n = r.verts.size() < 12 ? r.verts.size() : 12;  // first four triangles is plenty
        for (std::size_t k = 0; k < n; ++k) {
            const auto& v = r.verts[k];
            std::fprintf(out, "%s[%g,%g,%g,%g,%g,%g,%g,%g,%u]", k ? "," : "", v.position[0], v.position[1], v.position[2],
                         v.normal[0], v.normal[1], v.normal[2], v.texcoord[0], v.texcoord[1], v.color);
        }
        std::fprintf(out, "],\"nverts\":%zu}", r.verts.size());
    }
    std::fprintf(out, "],\"lights\":[");
    for (std::size_t i = 0; i < lights.size(); ++i) {
        const auto& l = lights[i];
        std::fprintf(out, "%s{\"hash\":%llu,\"handle\":%llu,\"ext\":%d,\"radiance\":[%g,%g,%g],\"dir\":[%.7f,%.7f,%.7f],\"angle\":%g,\"vol\":%g,"
                     "\"dome_tex\":%d,\"dome_m\":[", i ? "," : "", l.hash, (unsigned long long)l.handle, int(l.ext),
                     l.radiance.x, l.radiance.y, l.radiance.z,
                     l.distant.direction.x, l.distant.direction.y, l.distant.direction.z, l.distant.angularDiameterDegrees,
                     l.distant.volumetricRadianceScale, l.dome_tex);
        for (int r = 0; r < 3; ++r) for (int c = 0; c < 4; ++c) std::fprintf(out, "%s%g", r || c ? "," : "", l.dome.transform.matrix[r][c]);
        std::fprintf(out, "]}");
    }
    std::fprintf(out, "],\"camera\":{\"ok\":%d,\"type\":%d,\"pos\":[%g,%g,%g],\"fwd\":[%g,%g,%g],\"up\":[%g,%g,%g],\"right\":[%g,%g,%g],"
                 "\"fov\":%g,\"aspect\":%g,\"near\":%g,\"far\":%g},",
                 cam_ok, int(cam_type), cam_params.position.x, cam_params.position.y, cam_params.position.z,
                 cam_params.forward.x, cam_params.forward.y, cam_params.forward.z, cam_params.up.x, cam_params.up.y, cam_params.up.z,
                 cam_params.right.x, cam_params.right.y, cam_params.right.z, cam_params.fovYInDegrees, cam_params.aspect,
                 cam_params.nearPlane, cam_params.farPlane);
    std::fprintf(out, "\"instance\":{\"sType\":%d,\"mesh\":%llu,\"doubleSided\":%d,\"m\":[", int(inst.sType), (unsigned long long)inst.mesh, inst.doubleSided);
    for (int r = 0; r < 3; ++r) for (int c = 0; c < 4; ++c) std::fprintf(out, "%s%g", r || c ? "," : "", inst.transform.matrix[r][c]);
    std::fprintf(out, "]},\"drawn_lights\":[");
    for (std::size_t i = 0; i < drawn_lights.size(); ++i) std::fprintf(out, "%s%llu", i ? "," : "", (unsigned long long)drawn_lights[i]);
    std::fprintf(out, "],\"destroyed\":[");
    for (std::size_t i = 0; i < destroyed.size(); ++i) std::fprintf(out, "%s%llu", i ? "," : "", (unsigned long long)destroyed[i]);
    std::fprintf(out, "]}\n");
}

static std::vector<unsigned char> read(const char* path) {
    std::ifstream f(path, std::ios::binary);
    return std::vector<unsigned char>(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
}

int main(int, char** argv) {
    // argv: mode file [extra...]
    const std::string mode = argv[1];
    const auto bytes = read(argv[2]);
    nscn::Scene s;
    if (mode == "parse") {
        const bool ok = nscn::parse(bytes, s);
        std::fprintf(out, "{\"ok\":%d", ok);
        if (ok) {
            std::fprintf(out, ",\"draws\":%zu,\"tris\":%zu,\"textures\":%zu,\"camera\":[", s.draws.size(), s.tris.size(), s.textures.size());
            for (int i = 0; i < 14; ++i) std::fprintf(out, "%s%.9g", i ? "," : "", s.camera[i]);
            std::fprintf(out, "],\"table\":[");
            const std::size_t n = s.draws.size() < 8 ? s.draws.size() : 8;
            for (std::size_t i = 0; i < n; ++i) { const auto& d = s.draws[i]; std::fprintf(out, "%s[%u,%u,%u,%u,%u]", i ? "," : "", d.source, d.first, d.count, d.skinned, d.tex); }
            std::fprintf(out, "],\"names\":[");
            const std::size_t m = s.textures.size() < 8 ? s.textures.size() : 8;
            for (std::size_t i = 0; i < m; ++i) std::fprintf(out, "%s[%u,\"%s\"]", i ? "," : "", s.textures[i].id, s.textures[i].name.c_str());
            std::fprintf(out, "]");
        }
        std::fprintf(out, "}\n");
        return 0;
    }
    if (!nscn::parse(bytes, s)) { std::fprintf(out, "{\"error\":\"scene did not parse\"}\n"); return 0; }
    const remixapi_Interface a = api();
    // "shortdir": empty dir + 2-letter names fit in std::wstring's small buffer, so a reallocating vector moves the
    // characters themselves and every earlier c_str() dangles (long strings would keep their heap buffer by luck).
    const std::wstring dir = mode == "shortdir" ? L"" : L"C:\\game\\scene_textures\\";
    nscn::Options o;
    if (mode == "options") { o.skip_max = 3.5f; o.sun = 3.f; o.sun_angle = 10.f; o.sky = 0.25f; }
    if (mode == "fail_material") fail_material_at = 2;
    if (mode == "fail_mesh") fail_mesh = 1;
    if (mode == "fail_sun") fail_light_at = 0;
    if (mode == "fail_sky") fail_light_at = 1;
    nscn::Built b;
    const remixapi_ErrorCode rc = nscn::build(a, s, dir, o, b);
    if (mode == "submit" || mode == "fail_submit") {
        calls.clear();
        fail_draw_light = mode == "fail_submit";
        const remixapi_ErrorCode src = nscn::submit(a, s, b, 2.5f);
        dump("submit", src, &b);
        return 0;
    }
    if (mode == "destroy") {
        calls.clear(); destroyed.clear();
        nscn::destroy(a, b);
        const bool empty = b.materials.empty() && !b.mesh && !b.sun && !b.sky && b.texture_paths.empty() && b.vertices.empty();
        nscn::destroy(a, b);  // second call: nothing left to destroy
        std::fprintf(out, "{\"empty_after\":%d,\"rc\":%d,", empty, int(rc));
        std::fprintf(out, "\"calls\":[");
        for (std::size_t i = 0; i < calls.size(); ++i) std::fprintf(out, "%s\"%s\"", i ? "," : "", calls[i].c_str());
        std::fprintf(out, "],\"destroyed\":[");
        for (std::size_t i = 0; i < destroyed.size(); ++i) std::fprintf(out, "%s%llu", i ? "," : "", (unsigned long long)destroyed[i]);
        std::fprintf(out, "],\"created\":{\"materials\":[");
        for (std::size_t i = 0; i < mats.size(); ++i) std::fprintf(out, "%s%llu", i ? "," : "", (unsigned long long)mats[i].handle);
        std::fprintf(out, "],\"mesh\":%llu,\"lights\":[%llu,%llu]}}\n", meshes.empty() ? 0ull : (unsigned long long)meshes[0].handle,
                     lights.size() > 0 ? (unsigned long long)lights[0].handle : 0ull, lights.size() > 1 ? (unsigned long long)lights[1].handle : 0ull);
        return 0;
    }
    if (mode == "real") {  // counts only: the real scene is large
        std::fprintf(out, "{\"rc\":%d,\"surfaces\":%u,\"sky_skipped\":%u,\"untextured\":%u,\"materials\":%zu,\"mesh_surfaces\":%zu,\"nverts\":%zu,"
                     "\"draws\":%zu,\"zero_draws\":%zu,\"textures\":%zu}\n", int(rc), b.surfaces, b.sky_skipped, b.untextured, b.materials.size(),
                     meshes.empty() ? 0 : meshes[0].surfaces.size(), meshes.empty() ? 0 : meshes[0].verts.size(), s.draws.size(),
                     std::size_t(std::count_if(s.draws.begin(), s.draws.end(), [](const nscn::Draw& d) { return d.count == 0; })), s.textures.size());
        return 0;
    }
    dump(mode.c_str(), rc, &b);
    return 0;
}
'''

FLOATS = 24


def scene_bytes(camera, draws, textures, tris, version=3):
    """NSCN v3, layout identical to scene_from_frame.py / triangle.cpp parse_scene."""
    b = bytearray(b'NSCN')
    b += struct.pack('<4I', version, len(draws), len(tris), len(textures))
    b += struct.pack('<14f', *camera)
    for d in draws:
        b += struct.pack('<5I', *d)
    for tid, name in textures:
        raw = name if isinstance(name, bytes) else name.encode()
        b += struct.pack('<I', tid) + raw + b'\0' * (32 - len(raw))
    for t in tris:
        b += struct.pack('<24f', *t)
    return bytes(b)


def tri(x0, y0, z0, size=1.0, n=(0, 0, -1), uv0=0.0):
    """A triangle whose three vertices are distinguishable: position, normal and uv all differ."""
    vs = [(x0, y0, z0), (x0 + size, y0, z0), (x0, y0 + size, z0)]
    uvs = [(uv0, 0.0), (uv0 + 0.5, 0.0), (uv0, 0.5)]
    out = []
    for (p, q) in zip(vs, uvs):
        out += [*p, *n, *q]
    return out


CAMERA = [1.5, 2.5, -3.5, 0, 0, 1, 0, 1, 0, 1, 0, 0, 50.0, 2.4]
TEXTURES = [(41, 'tex_41.dds'), (7, 'tex_7.dds')]
# Triangles: 0-1 small (draw 0), 2 small (draw 1), 3 small (draw 2), 4 huge (draw 3), 5 small (draw 5)
TRIS = [tri(0, 0, 5, uv0=0.0), tri(1, 0, 5, uv0=0.1), tri(2, 0, 5, uv0=0.2), tri(3, 0, 5, uv0=0.3),
        tri(-3000, 0, 10, size=6000.0), tri(4, 0, 5, uv0=0.4)]
DRAWS = [
    (100, 0, 2, 0, 41),   # textured, opaque material for 41
    (101, 2, 1, 2, 7),    # cutout flag (bit 1) -> cutout twin of 7
    (102, 3, 1, 0, 0),    # untextured -> default material (null handle)
    (103, 4, 1, 0, 41),   # 6000 units wide -> sky, skipped
    (104, 5, 0, 0, 41),   # zero triangles -> ignored entirely (neither a surface nor skipped)
    (105, 5, 1, 1, 7),    # bit 0 only is NOT the cutout flag -> opaque material for 7
]


def ts_short():
    """Three textures with 2-letter names: their paths fit in std::wstring's inline buffer."""
    return scene_bytes(CAMERA, [(1, 0, 1, 0, 1), (2, 1, 1, 0, 2), (3, 2, 1, 0, 3)], [(1, 't1'), (2, 't2'), (3, 't3')], TRIS)


def run_harness(exe, mode, path):
    r = subprocess.run([str(exe), mode, str(path)], capture_output=True, text=True, timeout=600)
    if 'AddressSanitizer' in r.stderr or 'runtime error' in r.stderr:
        first = next((l for l in r.stderr.splitlines() if 'ERROR' in l or 'runtime error' in l), r.stderr[:300])
        raise AssertionError(f'harness {mode}: memory/UB error: {first.strip()} -- e.g. a pointer handed to Remix '
                             f'(albedoTexture, vertices) that does not outlive build()')
    assert r.returncode == 0, f'harness {mode} exited {r.returncode}: {r.stderr[-800:]}'
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f'harness {mode} printed non-JSON: {r.stdout[:400]!r}')


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b)) and len(a) == len(b)


def main():
    checks = []
    try:
        candidate = Path(sys.argv[1]).resolve()
        assert candidate.is_file(), f'missing candidate {candidate}'
        text = candidate.read_text(errors='replace')
        assert 'test_nscn_scene' not in text, 'candidate must not reference the gate'
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'nscn_scene.h').write_text(text)
            (d / 'harness.cpp').write_text(HARNESS)
            (d / 'second.cpp').write_text('#include "nscn_scene.h"\nbool second_tu(const std::vector<unsigned char>& b) { nscn::Scene s; return nscn::parse(b, s); }\n')
            exe = d / 'harness'
            cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER', '-D_WIN64=1', '-D__stdcall=',
                   '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(d), str(d / 'harness.cpp'), str(d / 'second.cpp'), '-o', str(exe)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            assert r.returncode == 0, 'compile failed (g++ -Wall -Wextra -Werror, two translation units):\n' + r.stderr[-3000:]
            assert 'pragma GCC diagnostic' not in text, 'no diagnostic pragmas: they leak into every file that includes the header'
            checks.append('compiles natively with -Wall -Wextra -Werror into two translation units, no diagnostic pragmas')

            def write(name, data):
                p = d / name
                p.write_bytes(data)
                return p

            good = write('good.bin', scene_bytes(CAMERA, DRAWS, TEXTURES, TRIS))

            # ---- 1. parse ---------------------------------------------------------------------------------------
            p = run_harness(exe, 'parse', good)
            assert p['ok'] == 1, 'valid scene rejected'
            assert (p['draws'], p['tris'], p['textures']) == (6, 6 * FLOATS, 2), p
            assert close(p['camera'], CAMERA, 1e-6), p['camera']
            assert p['table'][:2] == [[100, 0, 2, 0, 41], [101, 2, 1, 2, 7]], p['table']
            assert p['names'] == [[41, 'tex_41.dds'], [7, 'tex_7.dds']], p['names']
            checks.append('parse: valid v3 scene -> camera, draw table, texture names, triangle floats')

            bad = {}
            base = bytearray(scene_bytes(CAMERA, DRAWS, TEXTURES, TRIS))
            bad['v2'] = scene_bytes(CAMERA, DRAWS, TEXTURES, TRIS, version=2)
            bad['truncated'] = bytes(base[:-1])
            bad['extra byte'] = bytes(base) + b'\0'
            bad['bad magic'] = b'X' + bytes(base[1:])
            bad['draw past triangles'] = scene_bytes(CAMERA, DRAWS[:5] + [(105, 5, 2, 0, 7)], TEXTURES, TRIS)
            bad['missing texture id'] = scene_bytes(CAMERA, DRAWS[:5] + [(105, 5, 1, 0, 99)], TEXTURES, TRIS)
            bad['path in name'] = scene_bytes(CAMERA, DRAWS, [(41, '../x.dds'), (7, 'tex_7.dds')], TRIS)
            bad['backslash in name'] = scene_bytes(CAMERA, DRAWS, [(41, 'a\\b.dds'), (7, 'tex_7.dds')], TRIS)
            bad['empty name'] = scene_bytes(CAMERA, DRAWS, [(41, ''), (7, 'tex_7.dds')], TRIS)
            junk = bytearray(scene_bytes(CAMERA, DRAWS, TEXTURES, TRIS))
            off = 20 + 56 + 20 * len(DRAWS) + 4 + len('tex_41.dds') + 1
            junk[off] = ord('Z')
            bad['non-NUL padding'] = bytes(junk)
            nan_tri = [list(t) for t in TRIS]
            nan_tri[2][4] = float('nan')
            bad['NaN triangle'] = scene_bytes(CAMERA, DRAWS, TEXTURES, nan_tri)
            bad['inf camera'] = scene_bytes([float('inf')] + CAMERA[1:], DRAWS, TEXTURES, TRIS)
            bad['fov 180'] = scene_bytes(CAMERA[:12] + [180.0, 2.4], DRAWS, TEXTURES, TRIS)
            bad['fov 0'] = scene_bytes(CAMERA[:12] + [0.0, 2.4], DRAWS, TEXTURES, TRIS)
            bad['aspect 0'] = scene_bytes(CAMERA[:13] + [0.0], DRAWS, TEXTURES, TRIS)
            bad['empty file'] = b''
            bad['header only'] = bytes(base[:20 + 56 - 1])
            for name, data in bad.items():
                assert run_harness(exe, 'parse', write('bad.bin', data))['ok'] == 0, f'parse accepted: {name}'
            # a header claiming 2^32-1 triangles must be rejected by the size check, not by allocating
            huge = bytearray(base)
            struct.pack_into('<I', huge, 12, 0xFFFFFFFF)
            assert run_harness(exe, 'parse', write('bad.bin', bytes(huge)))['ok'] == 0, 'parse accepted a lying triangle count'
            checks.append(f'parse rejects {len(bad) + 1} malformed files (version, size, magic, ranges, names, NaN/inf, fov/aspect, lying count)')

            # ---- 2. build: materials --------------------------------------------------------------------------
            r = run_harness(exe, 'build', good)
            assert r['rc'] == 0, f'build failed rc={r["rc"]}'
            m = r['materials']
            assert [x['hash'] for x in m] == [1000041, 2000041, 1000007, 2000007], \
                f'materials must be (opaque, cutout) per texture in table order, hashes 1000000+id / 2000000+id: {[x["hash"] for x in m]}'
            for x in m:
                assert x['has_op'] == 1, 'material pNext must be a remixapi_MaterialInfoOpaqueEXT'
                assert x['has_albedo'] == 1, 'every texture material carries albedoTexture'
                assert close(x['albedoConstant'], [1, 1, 1]), x['albedoConstant']
                assert (x['opacity'], x['roughness'], x['metallic'], x['emissive']) == (1, 0.6, 0, 0), x
                # Changed 2026-10-29 with evidence: (0, 1, 2, 0) + alphaTestType 0 pinned a defect. blendType_hasvalue is
                # "blending enabled" and alphaTestType 0 is kNever; the laptop A/B of capture frame_23275488 showed every
                # surface see-through with them, solid with NVIDIA's remix.h defaults (test_material_defaults.py).
                assert (x['useDrawCallAlphaState'], x['blendType_hasvalue'], x['blendType_value'], x['invertedBlend']) == (0, 0, 0, 0), x
            assert [(x['alphaTestType'], x['alphaReferenceValue']) for x in m] == [(7, 0), (4, 128), (7, 0), (4, 128)], \
                'opaque: alphaTestType 7 (kAlways) ref 0; cutout twin: alphaTestType 4 (Greater) ref 128'
            assert [x['albedo'] for x in m] == ['C:\\game\\scene_textures\\tex_41.dds'] * 2 + ['C:\\game\\scene_textures\\tex_7.dds'] * 2, \
                [x['albedo'] for x in m]
            sd = write('short.bin', ts_short())
            r_s = run_harness(exe, 'shortdir', sd)
            assert r_s['rc'] == 0 and [x['albedo'] for x in r_s['materials']] == ['t1', 't1', 't2', 't2', 't3', 't3'], r_s['materials']
            checks.append('build: opaque + cutout twin per texture with the probe defaults (blend 2, alpha test 4/128, rough 0.6, albedo path = dir + name)')

            # ---- 3. build: mesh ---------------------------------------------------------------------------------
            assert r['calls'][:4] == ['CreateMaterial'] * 4 and r['calls'][4] == 'CreateMesh', r['calls']
            assert len(r['meshes']) == 1, 'exactly one mesh'
            mesh = r['meshes'][0]
            assert mesh['hash'] == 2, 'mesh hash 2 (probe: mesh=2, sun=3, sky=4)'
            h = {x['hash']: x['handle'] for x in m}
            assert mesh['surfaces'] == [[0, 6, 1, 0, h[1000041]], [6, 3, 1, 0, h[2000007]], [9, 3, 1, 0, 0], [15, 3, 1, 0, h[1000007]]], \
                f'surfaces [first_vertex, vertices, indices_null, indices_count, material]: {mesh["surfaces"]}'
            v = mesh['verts']
            assert close(v[0], [0, 0, 5, 0, 0, -1, 0.0, 0.0, 0xffffffff], 1e-5), v[0]
            assert close(v[1], [1, 0, 5, 0, 0, -1, 0.5, 0.0, 0xffffffff], 1e-5), v[1]
            assert close(v[5], [1, 1, 5, 0, 0, -1, 0.1, 0.5, 0xffffffff], 1e-5), v[5]
            b = r['built']
            assert (b['surfaces'], b['sky_skipped'], b['untextured'], b['materials'], b['mesh'], b['sun'], b['sky']) == (4, 1, 1, 4, 1, 1, 1), b
            assert b['paths'] == 2, 'one kept-alive wide path per texture'
            assert b['vertices'] == 3 * 6, 'one remixapi_HardcodedVertex per triangle corner, for every triangle in the file'
            checks.append('build: one non-indexed mesh, surfaces in draw order, sky (>5000 units) skipped, zero-count draws ignored, '
                          'cutout = bit 1 only, untextured -> null material, vertices copied exactly')

            # ---- 4. build: lights -------------------------------------------------------------------------------
            L = r['lights']
            assert r['calls'][5:] == ['CreateLight', 'CreateLight'], r['calls']
            assert [x['hash'] for x in L] == [3, 4], 'sun hash 3, sky hash 4'
            sun, sky = L
            assert close(sun['dir'], [0.3015113, -0.9045340, 0.3015113], 1e-6), sun['dir']
            assert (sun['angle'], sun['vol']) == (20, 1), sun
            assert close(sun['radiance'], [2, 2, 1.9], 1e-6), sun['radiance']
            assert sky['dome_tex'] == 0, 'the dome texture crashes this runtime: never attach one'
            assert close(sky['dome_m'], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]), sky['dome_m']
            assert close(sky['radiance'], [0.5, 0.5, 0.5]), sky['radiance']
            assert sun['ext'] != sky['ext'] and sun['ext'] != 0 and sky['ext'] != 0, 'sun is a distant light, sky a dome light'
            checks.append('build: sun = distant (0.3015,-0.9045,0.3015) 20 deg, radiance (2,2,1.9); sky = dome, identity, no texture, 0.5')

            # ---- 5. options propagate -----------------------------------------------------------------------------
            r = run_harness(exe, 'options', good)
            assert r['rc'] == 0
            # skip_max 3.5: the 6000-unit draw and draw 0 (2 triangles spanning 0..2 x 0..1, extent 2) -> only the big one is wider
            assert r['built']['sky_skipped'] == 1 and r['built']['surfaces'] == 4, r['built']
            sun, sky = r['lights']
            assert sun['angle'] == 10 and close(sun['radiance'], [3, 3, 2.85], 1e-6) and close(sky['radiance'], [0.25] * 3), (sun, sky)
            tight = run_harness(exe, 'parse', good)  # sanity: same file
            assert tight['ok'] == 1
            two = write('two.bin', scene_bytes(CAMERA, [(1, 0, 2, 0, 41), (2, 2, 1, 0, 7)], TEXTURES, TRIS))
            r2 = run_harness(exe, 'options', two)
            assert r2['built']['sky_skipped'] == 0 and r2['built']['surfaces'] == 2, r2['built']
            checks.append('options: sun, sun_angle, sky and skip_max all reach the runtime')

            # extent rule: max over x/y/z of (max - min) across all vertex positions of the draw, compared with '>'
            edge = [tri(0, 0, 5, size=5000.0), tri(0, 0, 5, size=5000.5)]
            e = write('edge.bin', scene_bytes(CAMERA, [(1, 0, 1, 0, 0), (2, 1, 1, 0, 0)], [], edge))
            re_ = run_harness(exe, 'build', e)
            assert re_['built']['sky_skipped'] == 1 and re_['built']['surfaces'] == 1, \
                f'extent exactly 5000 is kept, 5000.5 is skipped: {re_["built"]}'
            checks.append('sky rule: extent == skip_max kept, > skip_max skipped')

            # ---- 6. submit ------------------------------------------------------------------------------------------
            r = run_harness(exe, 'submit', good)
            assert r['rc'] == 0
            assert r['calls'] == ['SetupCamera', 'DrawInstance', 'DrawLightInstance', 'DrawLightInstance'], \
                f'one frame is camera, instance, sun, sky -- and never Present (the host presents): {r["calls"]}'
            c = r['camera']
            assert c['ok'] == 1 and c['type'] == 0, 'parameterized camera, REMIXAPI_CAMERA_TYPE_WORLD'
            assert close(c['pos'] + c['fwd'] + c['up'] + c['right'], CAMERA[:12]), c
            assert c['fov'] == 50 and c['aspect'] == 2.5 and close([c['near'], c['far']], [0.1, 20000], 1e-4), \
                'fov from the scene, aspect from the caller (not the scene), near 0.1, far 20000'
            i = r['instance']
            assert i['doubleSided'] == 1 and i['mesh'] != 0 and close(i['m'], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]), i
            assert r['drawn_lights'] == [r['lights'][0]['handle'], r['lights'][1]['handle']], 'sun then sky'
            r = run_harness(exe, 'fail_submit', good)
            assert r['rc'] == 3 and r['calls'] == ['SetupCamera', 'DrawInstance', 'DrawLightInstance'], \
                f'submit stops at the first failing call and returns its code (3): {r["rc"]} {r["calls"]}'
            checks.append('submit: SetupCamera(world, scene camera, caller aspect) -> DrawInstance(identity, double-sided) -> sun -> sky; no Present; '
                          'first failure stops it and its code is returned')

            # ---- 7. failure cleanup ---------------------------------------------------------------------------------
            for mode, created_before in (('fail_material', 2), ('fail_mesh', 4), ('fail_sun', 4), ('fail_sky', 4)):
                r = run_harness(exe, mode, good)
                assert r['rc'] == 3, f'{mode}: build must return the failing call\'s own error code (3), got {r["rc"]}'
                b = r['built']
                assert (b['materials'], b['mesh'], b['sun'], b['sky'], b['surfaces']) == (0, 0, 0, 0, 0), \
                    f'{mode}: Built must be left empty after a failure: {b}'
                expected = len(r['materials']) + len(r['lights']) + (1 if mode in ('fail_sun', 'fail_sky') else 0)
                assert len(r['destroyed']) == expected, f'{mode}: every created object destroyed exactly once: {r["destroyed"]}'
                assert len(set(r['destroyed'])) == len(r['destroyed']), f'{mode}: double destroy {r["destroyed"]}'
                for x in r['materials']:
                    assert x['handle'] in r['destroyed'], f'{mode}: material {x["handle"]} leaked'
                for x in r['lights']:
                    assert x['handle'] in r['destroyed'], f'{mode}: light {x["handle"]} leaked'
                assert len(r['materials']) == created_before, f'{mode}: stopped at the first failure'
            empty = write('empty.bin', scene_bytes(CAMERA, [(1, 0, 0, 0, 0)], [], []))
            r = run_harness(exe, 'build', empty)
            assert r['rc'] == 1 and r['calls'] == [], \
                f'a scene with no drawable surface returns REMIXAPI_ERROR_CODE_GENERAL_FAILURE (1) before any API call: {r["rc"]} {r["calls"]}'
            checks.append('failure: first failing call stops build, everything created so far destroyed once, Built empty; no-surface scene fails before the API')

            # ---- 8. destroy ----------------------------------------------------------------------------------------
            r = run_harness(exe, 'destroy', good)
            assert r['rc'] == 0 and r['empty_after'] == 1, r
            mats_ = r['created']['materials']
            want = [r['created']['lights'][1], r['created']['lights'][0], r['created']['mesh'], *reversed(mats_)]
            assert r['destroyed'] == want, f'destroy order: sky, sun, mesh, materials newest first. got {r["destroyed"]} want {want}'
            assert r['calls'] == ['DestroyLight', 'DestroyLight', 'DestroyMesh'] + ['DestroyMaterial'] * 4, r['calls']
            checks.append('destroy: sky, sun, mesh, materials in reverse; Built emptied; second destroy is a no-op')

            # ---- 9. real capture ----------------------------------------------------------------------------------
            if REAL.is_file():
                raw = REAL.read_bytes()
                version, ndraw, ntri, ntex = struct.unpack_from('<4I', raw, 4)
                p = run_harness(exe, 'parse', REAL)
                assert p['ok'] == 1 and (p['draws'], p['tris'] // FLOATS, p['textures']) == (ndraw, ntri, ntex), p
                r = run_harness(exe, 'real', REAL)
                assert r['rc'] == 0, r
                assert r['surfaces'] + r['sky_skipped'] + r['zero_draws'] == r['draws'], f'every draw accounted for: {r}'
                assert r['mesh_surfaces'] == r['surfaces'] and r['materials'] == 2 * r['textures'], r
                checks.append(f'real capture {REAL.parent.name}: {ndraw} draws, {ntri} triangles, {ntex} textures -> '
                              f'{r["surfaces"]} surfaces, {r["sky_skipped"]} sky, {r["untextured"]} untextured')
            else:
                checks.append(f'real capture skipped: {REAL} not present')
    except AssertionError as e:
        print(json.dumps({'passed': False, 'checks': checks, 'error': str(e)[:4000]}, indent=1))
        return 1
    except Exception as e:  # noqa: BLE001  a broken candidate must fail cleanly, never with a traceback
        print(json.dumps({'passed': False, 'checks': checks, 'error': f'{type(e).__name__}: {e}'[:4000]}, indent=1))
        return 1
    print(json.dumps({'passed': True, 'checks': checks}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
