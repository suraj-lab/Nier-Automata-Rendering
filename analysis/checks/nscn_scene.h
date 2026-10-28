#pragma once
// NSCN v3 scene file -> RTX Remix: one mesh (per-texture opaque/cutout materials), sun + sky dome lights.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
#include <remix_c.h>

namespace nscn {

struct Draw {
    std::uint32_t source, first, count, skinned, tex;
};
static_assert(sizeof(Draw) == 20, "Draw must be 20 bytes, file order");

struct Texture {
    std::uint32_t id;
    std::string name;
};

struct Scene {
    float camera[14];
    std::vector<Draw> draws;
    std::vector<float> tris;
    std::vector<Texture> textures;
};

constexpr std::size_t kTriFloats = 24;  // 3 vertices x (position[3], normal[3], uv[2])
constexpr std::size_t kNameBytes = 32;  // fixed albedo file-name field
constexpr std::size_t kHeaderBytes = 20 + 56;  // NSCN + version/draws/tris/textures, then 14 camera floats

// The converter writes a bare file name, never a path: reject anything that could escape scene_textures\.
inline bool valid_texture_name(const unsigned char* p, std::size_t n) {
    if (!n) return false;
    for (std::size_t i = 0; i < n; ++i) {
        const unsigned char c = p[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-'))
            return false;
    }
    return true;
}

inline bool parse(const std::vector<unsigned char>& b, Scene& s) {
    if (b.size() < kHeaderBytes || std::memcmp(b.data(), "NSCN", 4)) return false;
    std::uint32_t h[4];
    std::memcpy(h, b.data() + 4, 16);
    const std::uint64_t size = kHeaderBytes + 20ull * h[1] + 36ull * h[3] + 4ull * kTriFloats * h[2];
    if (h[0] != 3 || b.size() != size) return false;
    std::memcpy(s.camera, b.data() + 20, 56);
    s.draws.resize(h[1]);
    if (h[1]) std::memcpy(s.draws.data(), b.data() + kHeaderBytes, 20ull * h[1]);
    std::size_t o = kHeaderBytes + 20ull * h[1];
    s.textures.clear();
    for (std::uint32_t i = 0; i < h[3]; ++i, o += 36) {
        Texture t;
        std::memcpy(&t.id, b.data() + o, 4);
        const unsigned char* name = b.data() + o + 4;
        std::size_t n = 0;
        while (n < kNameBytes && name[n]) ++n;
        for (std::size_t k = n; k < kNameBytes; ++k)
            if (name[k]) return false;  // padding must be NUL
        if (!valid_texture_name(name, n)) return false;
        t.name.assign(reinterpret_cast<const char*>(name), n);
        s.textures.push_back(t);
    }
    s.tris.resize(kTriFloats * h[2]);
    if (h[2]) std::memcpy(s.tris.data(), b.data() + o, 4ull * kTriFloats * h[2]);
    for (const auto& d : s.draws)
        if (d.first > h[2] || d.count > h[2] - d.first) return false;
    for (const auto& d : s.draws) {  // a draw may only reference a texture the table carries
        if (!d.tex) continue;
        bool found = false;
        for (const auto& t : s.textures) found = found || t.id == d.tex;
        if (!found) return false;
    }
    for (float v : s.camera)
        if (!std::isfinite(v)) return false;
    for (float v : s.tris)
        if (!std::isfinite(v)) return false;
    return s.camera[12] > 0 && s.camera[12] < 180 && s.camera[13] > 0;
}

struct Options {
    float skip_max = 5000.f, sun = 2.f, sun_angle = 20.f, sky = 0.5f;
};

struct Built {
    std::vector<std::wstring> texture_paths;  // one per texture; must stay alive while Remix uses them
    std::vector<remixapi_HardcodedVertex> vertices;  // 3 per triangle, for EVERY triangle in the file
    std::vector<remixapi_MaterialHandle> materials;  // every material created, in creation order
    remixapi_MeshHandle mesh = nullptr;
    remixapi_LightHandle sun = nullptr, sky = nullptr;
    unsigned surfaces = 0, sky_skipped = 0, untextured = 0;
};

namespace detail {

inline std::wstring widen(const std::string& s) {
    std::wstring w;
    w.reserve(s.size());
    for (char c : s) w.push_back(static_cast<wchar_t>(static_cast<unsigned char>(c)));
    return w;
}

inline void make_material_info(remixapi_MaterialInfo& info, remixapi_MaterialInfoOpaqueEXT& ext,
                               const wchar_t* path, std::uint64_t hash, bool cutout) {
    info = {};
    ext = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &ext;
    info.hash = hash;
    info.albedoTexture = path;
    info.emissiveIntensity = 0;
    ext.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    ext.pNext = nullptr;
    ext.albedoConstant.x = ext.albedoConstant.y = ext.albedoConstant.z = 1.f;
    ext.opacityConstant = 1.f;
    ext.roughnessConstant = 0.6f;
    ext.metallicConstant = 0.f;
    ext.useDrawCallAlphaState = 0;
    ext.blendType_hasvalue = 1;
    ext.blendType_value = 2;
    ext.invertedBlend = 0;
    if (cutout) {
        ext.alphaTestType = 4;
        ext.alphaReferenceValue = 128;
    }
}

inline float extent_of(const Scene& s, const Draw& d) {
    // max over x/y/z of (max - min) across ALL 3*count vertex positions of the draw
    float mn[3] = {std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity(),
                   std::numeric_limits<float>::infinity()};
    float mx[3] = {-std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(),
                   -std::numeric_limits<float>::infinity()};
    for (std::uint32_t t = 0; t < d.count; ++t)
        for (std::size_t k = 0; k < 3; ++k) {
            const float* p = &s.tris[24 * (d.first + t) + 8 * k];
            for (int c = 0; c < 3; ++c) {
                mn[c] = std::min(mn[c], p[c]);
                mx[c] = std::max(mx[c], p[c]);
            }
        }
    float extent = 0.f;
    for (int c = 0; c < 3; ++c) extent = std::max(extent, mx[c] - mn[c]);
    return extent;
}

}  // namespace detail

inline void destroy(const remixapi_Interface& api, Built& b) {
    if (b.sky) api.DestroyLight(b.sky);
    if (b.sun) api.DestroyLight(b.sun);
    if (b.mesh) api.DestroyMesh(b.mesh);
    for (std::size_t i = b.materials.size(); i-- > 0;)
        if (b.materials[i]) api.DestroyMaterial(b.materials[i]);
    b.materials.clear();
    b.texture_paths.clear();
    b.vertices.clear();
    b.mesh = nullptr;
    b.sun = nullptr;
    b.sky = nullptr;
    b.surfaces = b.sky_skipped = b.untextured = 0;
}

inline remixapi_ErrorCode build(const remixapi_Interface& api, const Scene& s, const std::wstring& texture_dir,
                                const Options& o, Built& out) {
    const auto fail = [&](remixapi_ErrorCode e) {
        destroy(api, out);  // leave `out` empty
        return e;
    };

    // Rule 4, evaluated before ANY API call: no draw would become a surface (zero count or sky-sized)?
    bool any_surface = false;
    for (const auto& d : s.draws)
        if (d.count && detail::extent_of(s, d) <= o.skip_max) any_surface = true;
    if (!any_surface) return REMIXAPI_ERROR_CODE_GENERAL_FAILURE;

    // Materials: opaque + cutout twin per texture, in table order.
    out.texture_paths.clear();
    out.texture_paths.reserve(s.textures.size());  // Remix keeps each albedoTexture pointer: never reallocate after c_str()
    for (const auto& t : s.textures) {
        out.texture_paths.push_back(texture_dir + detail::widen(t.name));
        const wchar_t* path = out.texture_paths.back().c_str();  // kept alive by out.texture_paths
        remixapi_MaterialInfo info;
        remixapi_MaterialInfoOpaqueEXT ext;
        remixapi_MaterialHandle h = nullptr;
        detail::make_material_info(info, ext, path, 1000000ull + t.id, false);
        if (const remixapi_ErrorCode e = api.CreateMaterial(&info, &h)) return fail(e);
        if (!h) return fail(REMIXAPI_ERROR_CODE_GENERAL_FAILURE);
        out.materials.push_back(h);
        detail::make_material_info(info, ext, path, 2000000ull + t.id, true);
        if (const remixapi_ErrorCode e = api.CreateMaterial(&info, &h)) return fail(e);
        if (!h) return fail(REMIXAPI_ERROR_CODE_GENERAL_FAILURE);
        out.materials.push_back(h);
    }

    // Vertices: 3 per triangle, for EVERY triangle in the file.
    out.vertices.clear();
    out.vertices.resize(s.tris.size() / 24 * 3);
    for (std::size_t t = 0, base = s.tris.size() / 24; t < base; ++t) {
        for (std::size_t k = 0; k < 3; ++k) {
            const float* f = &s.tris[24 * t + 8 * k];
            remixapi_HardcodedVertex& v = out.vertices[3 * t + k];
            v = {};
            std::memcpy(v.position, f, 12);
            std::memcpy(v.normal, f + 3, 12);
            std::memcpy(v.texcoord, f + 6, 8);
            v.color = 0xffffffffu;
        }
    }

    // Surfaces, one per kept draw, in draw order.
    std::vector<remixapi_MeshInfoSurfaceTriangles> surfaces;
    surfaces.reserve(s.draws.size());
    for (const auto& d : s.draws) {
        if (!d.count) continue;
        if (detail::extent_of(s, d) > o.skip_max) {
            ++out.sky_skipped;
            continue;
        }
        remixapi_MaterialHandle m = nullptr;
        if (d.tex) {
            const bool cutout = (d.skinned & 2u) != 0;  // bit 1 only is the cutout flag
            for (std::size_t i = 0; i < s.textures.size(); ++i)
                if (s.textures[i].id == d.tex) {
                    m = cutout ? out.materials[2 * i + 1] : out.materials[2 * i];
                    break;
                }
        } else {
            ++out.untextured;  // tex 0 -> null material
        }
        remixapi_MeshInfoSurfaceTriangles sf{};
        sf.vertices_values = &out.vertices[3 * d.first];
        sf.vertices_count = 3ull * d.count;
        sf.indices_values = nullptr;
        sf.indices_count = 0;
        sf.material = m;
        surfaces.push_back(sf);
    }
    out.surfaces = static_cast<unsigned>(surfaces.size());

    remixapi_MeshInfo mi{};
    mi.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO;
    mi.pNext = nullptr;
    mi.hash = 2;
    mi.surfaces_values = surfaces.data();
    mi.surfaces_count = static_cast<std::uint32_t>(surfaces.size());
    if (const remixapi_ErrorCode e = api.CreateMesh(&mi, &out.mesh)) return fail(e);
    if (!out.mesh) return fail(REMIXAPI_ERROR_CODE_GENERAL_FAILURE);

    // Lights: sun (distant) first, then sky (dome). `fail` destroys everything already created.
    {
        remixapi_LightInfoDistantEXT ext{};
        ext.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DISTANT_EXT;
        ext.pNext = nullptr;
        ext.direction.x = 0.3015113f;
        ext.direction.y = -0.9045340f;
        ext.direction.z = 0.3015113f;
        ext.angularDiameterDegrees = o.sun_angle;
        ext.volumetricRadianceScale = 1.f;
        remixapi_LightInfo li{};
        li.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO;
        li.pNext = &ext;
        li.hash = 3;
        li.radiance.x = o.sun;
        li.radiance.y = o.sun;
        li.radiance.z = o.sun * 0.95f;
        if (const remixapi_ErrorCode e = api.CreateLight(&li, &out.sun)) return fail(e);
        if (!out.sun) return fail(REMIXAPI_ERROR_CODE_GENERAL_FAILURE);
    }
    {
        remixapi_LightInfoDomeEXT ext{};
        ext.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DOME_EXT;
        ext.pNext = nullptr;
        ext.transform.matrix[0][0] = ext.transform.matrix[1][1] = ext.transform.matrix[2][2] = 1.f;
        ext.colorTexture = nullptr;  // a dome texture crashes this runtime
        remixapi_LightInfo li{};
        li.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO;
        li.pNext = &ext;
        li.hash = 4;
        li.radiance.x = li.radiance.y = li.radiance.z = o.sky;
        if (const remixapi_ErrorCode e = api.CreateLight(&li, &out.sky)) return fail(e);
        if (!out.sky) return fail(REMIXAPI_ERROR_CODE_GENERAL_FAILURE);
    }
    return REMIXAPI_ERROR_CODE_SUCCESS;
}

inline remixapi_ErrorCode submit(const remixapi_Interface& api, const Scene& s, const Built& b, float aspect) {
    if (!b.mesh || !b.sun || !b.sky) return REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
    remixapi_CameraInfoParameterizedEXT cp{};
    cp.sType = REMIXAPI_STRUCT_TYPE_CAMERA_INFO_PARAMETERIZED_EXT;
    cp.pNext = nullptr;
    std::memcpy(&cp.position, &s.camera[0], 12);
    std::memcpy(&cp.forward, &s.camera[3], 12);
    std::memcpy(&cp.up, &s.camera[6], 12);
    std::memcpy(&cp.right, &s.camera[9], 12);
    cp.fovYInDegrees = s.camera[12];
    cp.aspect = aspect;
    cp.nearPlane = 0.1f;
    cp.farPlane = 20000.f;
    remixapi_CameraInfo ci{};
    ci.sType = REMIXAPI_STRUCT_TYPE_CAMERA_INFO;
    ci.pNext = &cp;
    ci.type = REMIXAPI_CAMERA_TYPE_WORLD;
    if (const remixapi_ErrorCode e = api.SetupCamera(&ci)) return e;
    remixapi_InstanceInfo ii{};
    ii.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
    ii.pNext = nullptr;
    ii.mesh = b.mesh;
    ii.doubleSided = 1;
    ii.transform.matrix[0][0] = ii.transform.matrix[1][1] = ii.transform.matrix[2][2] = 1.f;
    if (const remixapi_ErrorCode e = api.DrawInstance(&ii)) return e;
    if (const remixapi_ErrorCode e = api.DrawLightInstance(b.sun)) return e;
    return api.DrawLightInstance(b.sky);
}

}  // namespace nscn
