#pragma once
// Worker-side live scene: owns every Remix mesh/material for the per-frame draw stream, draws one
// instance per game draw, and evicts least-recently-used meshes above a byte budget.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <remix_c.h>
#include "live_types.h"
#include "nscn_scene.h"

namespace live_scene {

inline float light_scale = 1.f;  // NIER_REMIX_LIGHT_SCALE: tuned on the laptop probe first (REPROBE_LIGHT_SCALE)

struct State {
    std::map<std::uint64_t, remixapi_MeshHandle> meshes;
    std::map<std::uint64_t, std::size_t> mesh_bytes;
    std::map<std::uint64_t, std::uint64_t> last_used;
    std::map<std::uint64_t, remixapi_MaterialHandle> materials;  // texture id, plus alpha test above bit 32
    std::vector<std::wstring> texture_paths;  // indexed by (texture id - 1); Remix keeps each c_str()
    std::vector<live_capture::Upload> backlog;  // uploads deferred to later iterations, so one frame cannot stall
    std::vector<std::uint64_t> evicted_keys;     // reported to the capture side, which then uploads them again
    std::map<std::uint64_t, unsigned> refused;   // meshes the runtime refused: retried a few times, then left out
    remixapi_LightHandle sun = nullptr, sky = nullptr;
    live_capture::Sun sun_value;  // what `sun` was created with, when sun_captured
    bool sun_captured = false;
    std::vector<remixapi_LightHandle> lights;  // the game's point lights, index = position in Frame::lights
    std::vector<live_capture::Light> light_values;  // what each handle was created with
    std::size_t bytes = 0;
    std::size_t budget = std::size_t(512) << 20;
    std::uint64_t clock = 0;
    unsigned built = 0, evicted = 0;
    unsigned light_creates = 0;  // CreateLight calls for the game's lights: grows when lights move, never per frame for static ones
};

inline void destroy(const remixapi_Interface& api, State& s) {
    for (auto& [key, mesh] : s.meshes) if (mesh) api.DestroyMesh(mesh);
    for (auto& [id, material] : s.materials) if (material) api.DestroyMaterial(material);
    if (s.sun) api.DestroyLight(s.sun);
    if (s.sky) api.DestroyLight(s.sky);
    for (auto handle : s.lights) if (handle) api.DestroyLight(handle);
    s.meshes.clear();
    s.mesh_bytes.clear();
    s.last_used.clear();
    s.materials.clear();
    s.texture_paths.clear();
    s.sun = s.sky = nullptr;
    s.sun_captured = false;
    s.lights.clear();
    s.light_values.clear();
    s.bytes = 0;
}

// Textures first seen up to this frame, in id order, so the path strings stay alive.
inline void add_textures(State& s, const std::vector<live_capture::TextureFile>& files) {
    for (const auto& f : files) {
        if (f.id == 0) continue;
        if (s.texture_paths.size() < f.id) s.texture_paths.resize(f.id);
        s.texture_paths[f.id - 1] = f.path;
    }
}

// One material per (texture, alpha test). Opaque keeps the hash and settings the live path has always used; an
// alpha-tested one carries the game shader's own comparison and reference (alpha_test.h).
inline remixapi_MaterialHandle material_for(const remixapi_Interface& api, State& s, std::uint32_t texture,
                                            int alpha_op = 7, std::uint8_t alpha_ref = 0) {
    if (!texture) return nullptr;
    const bool tested = alpha_op != 7;
    const std::uint64_t key = texture | (tested ? (std::uint64_t(alpha_op) << 32 | std::uint64_t(alpha_ref) << 40) : 0);
    const auto known = s.materials.find(key);
    if (known != s.materials.end()) return known->second;
    if (texture > s.texture_paths.size() || s.texture_paths[texture - 1].empty()) return nullptr;
    remixapi_MaterialInfo info;
    remixapi_MaterialInfoOpaqueEXT ext;
    // 3000000+: the captured scene owns 1000000+ (opaque) and 2000000+ (cutout); both can exist after a fallback.
    // Alpha-tested live materials: 6000000000 + texture<<16 + op<<8 + ref, clear of every other range.
    const std::uint64_t hash = tested ? 6000000000ull + (std::uint64_t(texture) << 16) + (std::uint64_t(alpha_op) << 8) + alpha_ref
                                      : 3000000ull + texture;
    nscn::detail::make_material_info(info, ext, s.texture_paths[texture - 1].c_str(), hash, tested);
    if (tested) { ext.alphaTestType = alpha_op; ext.alphaReferenceValue = alpha_ref; }
    remixapi_MaterialHandle handle = nullptr;
    if (api.CreateMaterial(&info, &handle) || !handle) return nullptr;
    s.materials.emplace(key, handle);
    return handle;
}

// One upload -> one indexed mesh. Vertices are the compact bind-pose set; indices remap into them.
inline bool build_mesh(const remixapi_Interface& api, State& s, const live_capture::Upload& upload) {
    if (upload.vertices.empty() || upload.indices.empty()) return false;
    std::vector<remixapi_HardcodedVertex> vertices(upload.vertices.size());
    for (std::size_t i = 0; i < vertices.size(); ++i) {
        remixapi_HardcodedVertex& v = vertices[i];
        v = {};
        std::memcpy(v.position, upload.vertices[i].position, sizeof v.position);
        std::memcpy(v.normal, upload.vertices[i].normal, sizeof v.normal);
        std::memcpy(v.texcoord, upload.vertices[i].texcoord, sizeof v.texcoord);
        v.color = upload.vertices[i].color ? upload.vertices[i].color : 0xffffffffu;
    }
    remixapi_MeshInfoSurfaceTriangles surface{};
    surface.vertices_values = vertices.data();
    surface.vertices_count = vertices.size();
    surface.indices_values = upload.indices.data();
    surface.indices_count = upload.indices.size();
    surface.material = material_for(api, s, upload.texture, upload.alpha_op, upload.alpha_ref);
    remixapi_MeshInfoSkinning skinning{};
    if (upload.skinned && upload.bones.size() == 4 * upload.vertices.size() && upload.weights.size() == 4 * upload.vertices.size()) {
        skinning.bonesPerVertex = 4;
        skinning.blendWeights_values = upload.weights.data();
        skinning.blendWeights_count = static_cast<std::uint32_t>(upload.weights.size());
        skinning.blendIndices_values = upload.bones.data();
        skinning.blendIndices_count = static_cast<std::uint32_t>(upload.bones.size());
        surface.skinning_hasvalue = 1;
        surface.skinning_value = skinning;
    }
    remixapi_MeshInfo info{};
    info.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO;
    info.pNext = nullptr;
    info.hash = upload.geometry;  // stable per geometry, so the runtime can reuse work across frames
    info.surfaces_values = &surface;
    info.surfaces_count = 1;
    remixapi_MeshHandle mesh = nullptr;
    if (api.CreateMesh(&info, &mesh) || !mesh) return false;
    const std::size_t bytes = vertices.size() * sizeof(remixapi_HardcodedVertex) + upload.indices.size() * sizeof(std::uint32_t);
    const auto previous = s.meshes.find(upload.geometry);
    if (previous != s.meshes.end()) {  // same key rebuilt after a buffer rewrite: replace, do not leak
        s.bytes -= s.mesh_bytes[upload.geometry];
        if (previous->second != mesh) api.DestroyMesh(previous->second);  // Remix reuses hash-as-handle
    }
    s.meshes[upload.geometry] = mesh;
    s.mesh_bytes[upload.geometry] = bytes;
    s.last_used[upload.geometry] = s.clock + 1;  // protected in the frame it was built for
    s.bytes += bytes;
    ++s.built;
    return true;
}

// Least recently used first, but never a mesh drawn in the current frame: above budget with everything in use,
// the budget is exceeded rather than thrashing. Every eviction is reported so the geometry is uploaded again.
inline void evict(const remixapi_Interface& api, State& s) {
    if (s.bytes <= s.budget) return;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> unused;  // (last used, key)
    for (const auto& [key, used] : s.last_used)
        if (used < s.clock) unused.emplace_back(used, key);
    std::sort(unused.begin(), unused.end());
    for (const auto& [used, key] : unused) {
        if (s.bytes <= s.budget) break;
        const auto mesh = s.meshes.find(key);
        if (mesh != s.meshes.end()) {
            if (mesh->second) api.DestroyMesh(mesh->second);
            s.meshes.erase(mesh);
        }
        const auto size = s.mesh_bytes.find(key);
        if (size != s.mesh_bytes.end()) { s.bytes -= size->second; s.mesh_bytes.erase(size); }
        s.last_used.erase(key);
        s.evicted_keys.push_back(key);
        ++s.evicted;
    }
}

inline std::vector<std::uint64_t> take_evicted(State& s) {
    std::vector<std::uint64_t> out;
    out.swap(s.evicted_keys);
    return out;
}

// Drain everything the game thread queued, then make sure the lights exist. Returns false only when the
// runtime refuses. Uploads arrive separately from frames, so a frame the worker skips cannot lose geometry.
// Building thousands of meshes in one iteration would stall the frame; spread the first-sight geometry over
// several frames instead. Draws whose mesh is not built yet are simply skipped for now.
inline constexpr std::size_t kBuildsPerCall = 96;
inline constexpr unsigned kRetries = 3;
inline constexpr std::size_t kMaxBacklog = 20000;  // beyond this, the oldest are handed back to be uploaded later

inline bool update(const remixapi_Interface& api, std::vector<live_capture::Upload> uploads,
                   const std::vector<live_capture::TextureFile>& textures, const live_capture::Frame& frame,
                   State& s, const nscn::Options& options) {
    add_textures(s, textures);
    // Newest upload per geometry wins: a rewrite while queued replaces the queued one, so geometry rewritten every
    // frame cannot grow the backlog, and the stale version is never built.
    std::vector<live_capture::Upload> queue = std::move(s.backlog);
    s.backlog.clear();
    std::map<std::uint64_t, std::size_t> position;
    for (std::size_t i = 0; i < queue.size(); ++i) position[queue[i].geometry] = i;
    for (auto& upload : uploads) {
        const auto queued = position.find(upload.geometry);
        if (queued != position.end()) queue[queued->second] = std::move(upload);
        else { position[upload.geometry] = queue.size(); queue.push_back(std::move(upload)); }
    }
    std::size_t index = 0;
    for (; index < queue.size() && index < kBuildsPerCall; ++index)
        if (!build_mesh(api, s, queue[index]) && ++s.refused[queue[index].geometry] <= kRetries)
            s.evicted_keys.push_back(queue[index].geometry);  // capture uploads it again; a persistent refusal stops here
    for (; index < queue.size(); ++index) {
        if (s.backlog.size() < kMaxBacklog) s.backlog.push_back(std::move(queue[index]));
        else s.evicted_keys.push_back(queue[index].geometry);  // forgotten by the capture side, so not lost for good
    }
    if (!s.sun || !s.sky) {
        if (const remixapi_ErrorCode r = nscn::make_lights(api, options, s.sun, s.sky)) return false;
        s.sun_captured = false;
    }
    // The game's own sun replaces the placeholder; recreated only when its values change. No sun this frame keeps the last.
    if (frame.has_sun && (!s.sun_captured || std::memcmp(&frame.sun, &s.sun_value, sizeof frame.sun))) {
        // Handle == hash in the runtime: create-then-destroy would delete the new light, so destroy first.
        if (s.sun) api.DestroyLight(s.sun);
        s.sun = nullptr;
        s.sun_captured = !nscn::make_sun(api, frame.sun.direction, frame.sun.colour, options.sun_angle, s.sun);
        if (s.sun_captured) s.sun_value = frame.sun;
        else s.sun = nullptr;  // make_lights recreates the placeholder next frame
    }
    // The frame's light array is authoritative: create handles for lights without one, drop ones the game
    // stopped binding. A light whose values changed is destroyed and recreated with the same hash (0.6.6 has no
    // UpdateLight; the hash keeps the denoiser's history). Unchanged lights keep their handle: no churn.
    for (std::size_t i = frame.lights.size(); i < s.lights.size(); ++i) {
        if (s.lights[i]) api.DestroyLight(s.lights[i]);
        s.lights[i] = nullptr;
    }
    s.lights.resize(frame.lights.size());
    s.light_values.resize(frame.lights.size());
    for (std::size_t i = 0; i < frame.lights.size(); ++i) {
        const auto& l = frame.lights[i];
        if (s.lights[i] && light_convert::same(s.light_values[i], l)) continue;
        if (s.lights[i]) { api.DestroyLight(s.lights[i]); s.lights[i] = nullptr; }
        s.light_values[i] = l;
        const light_convert::Sphere c = light_convert::to_sphere(l, light_scale);  // shared with the laptop probe
        remixapi_LightInfoSphereEXT sphere{};
        sphere.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO_SPHERE_EXT;
        sphere.pNext = nullptr;
        sphere.position.x = c.position[0];
        sphere.position.y = c.position[1];
        sphere.position.z = c.position[2];
        sphere.radius = c.radius;
        sphere.shaping_hasvalue = c.shaped ? 1 : 0;
        if (c.shaped) {
            sphere.shaping_value.direction = {c.direction[0], c.direction[1], c.direction[2]};
            sphere.shaping_value.coneAngleDegrees = c.cone_angle_degrees;
            sphere.shaping_value.coneSoftness = c.cone_softness;
            sphere.shaping_value.focusExponent = 0.f;
        }
        sphere.volumetricRadianceScale = 1.f;
        remixapi_LightInfo info{};
        info.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO;
        info.pNext = &sphere;
        // 3/4 sun/sky, 3000000+ captured materials: game lights own 4000000+ (points) and 4500000+ (spots).
        info.hash = (l.spot ? 4500000ull : 4000000ull) + i;
        info.radiance.x = c.radiance[0];
        info.radiance.y = c.radiance[1];
        info.radiance.z = c.radiance[2];
        remixapi_LightHandle handle = nullptr;
        // A light the runtime refuses stays out (and is retried next frame) instead of failing the whole scene.
        if (api.CreateLight(&info, &handle) || !handle) handle = nullptr;
        else ++s.light_creates;
        s.lights[i] = handle;
    }
    ++s.clock;
    for (const auto& item : frame.items)
        if (s.meshes.count(item.geometry)) s.last_used[item.geometry] = s.clock;  // only meshes that exist
    evict(api, s);
    return true;
}

// True when at least one of the frame's draws has a built mesh. The runtime contract is camera, instances, lights,
// Present; a frame with nothing built yet (first frames, meshes still queued) must be skipped, not half-submitted.
// A frame needs at least one ray-traced (non-sky) instance: Remix hides SKY instances from ray tracing, and a frame
// with zero ray-traced surfaces crashes it (0-byte "Surface Material Buffer", divide by zero; NieR's title screen,
// 2026-10-29). Such a frame is held back and the previous image stays up.
inline bool ready(const live_capture::Frame& frame, const State& s) {
    for (const auto& item : frame.items)
        if (item.count && !item.sky && s.meshes.count(item.geometry)) return true;
    return false;
}

inline remixapi_ErrorCode submit(const remixapi_Interface& api, const live_capture::Frame& frame, State& s,
                                 const float camera[14], float aspect) {
    if (!ready(frame, s)) return REMIXAPI_ERROR_CODE_GENERAL_FAILURE;  // caller checks ready() first
    if (const remixapi_ErrorCode r = nscn::setup_camera(api, camera, aspect)) return r;
    for (const auto& item : frame.items) {
        const auto mesh = s.meshes.find(item.geometry);
        if (mesh == s.meshes.end() || !mesh->second) continue;
        for (unsigned i = 0; i < item.count; ++i) {
            const std::size_t base = (static_cast<std::size_t>(item.first) + i) * 12;
            if (base + 12 > frame.transforms.size()) break;
            remixapi_InstanceInfoBoneTransformsEXT bones{};
            bones.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BONE_TRANSFORMS_EXT;
            bones.pNext = nullptr;
            const std::size_t bone_base = static_cast<std::size_t>(item.first_bone) * 12;
            if (item.bone_count && bone_base + 12ull * item.bone_count <= frame.bones.size()) {
                bones.boneTransforms_values = reinterpret_cast<const remixapi_Transform*>(frame.bones.data() + bone_base);
                bones.boneTransforms_count = item.bone_count;
            }
            remixapi_InstanceInfo instance{};
            instance.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
            instance.pNext = bones.boneTransforms_count ? &bones : nullptr;
            instance.mesh = mesh->second;
            instance.doubleSided = 1;
            // The game drew this with alpha blending. Remix cannot blend per draw, so the closest faithful read is
            // cutout: foliage cards and grilles lose their transparent texels instead of rendering solid.
            if (item.blended) instance.categoryFlags |= REMIXAPI_INSTANCE_CATEGORY_BIT_ALPHA_BLEND_TO_CUTOUT;
            if (item.sky) instance.categoryFlags |= REMIXAPI_INSTANCE_CATEGORY_BIT_SKY;
            for (unsigned r = 0; r < 3; ++r)
                for (unsigned c = 0; c < 4; ++c) instance.transform.matrix[r][c] = frame.transforms[base + 4 * r + c];
            if (const remixapi_ErrorCode r = api.DrawInstance(&instance)) return r;
        }
    }
    if (s.sun) api.DrawLightInstance(s.sun);
    if (s.sky) api.DrawLightInstance(s.sky);
    for (auto handle : s.lights)
        if (handle) api.DrawLightInstance(handle);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}

}  // namespace live_scene
