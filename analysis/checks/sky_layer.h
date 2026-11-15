// W1.3 step 1 (PLAN_2026-11-14): the per-layer inputs of NieR's sky shader, read out of the draw's own pixel shader
// and constant buffers, and folded into the material's base colour.
//
// The shader (runtime/w1-disasm/sky_ps.asm, FNV-1a 64 of its bytecode 0x33856d1d3ba64bb3, the same in camp, desert and
// pond) computes one layer as:
//   base  = (g_AlbedoParam.w > 0 ? g_AlbedoParam.rgb : t0(uv + g_UvOffset)) * g_IntensityParam.y;   asm lines 24-26
//   base *= saturate(t17(uv) + g_ShadowParam.z);  base *= g_MeshColor.rgb;                          asm lines 27-30
// then blends the fog LUT over it. Of those inputs only three are in a capture: intensity, the albedo override and the
// mesh colour. t17 is never captured (PS slot 17 is outside texture_capture's 0-15) and the fog LUT's cube face is
// missing, so a fold here carries no fog and no ambient occlusion: measured limitations, recorded in
// replay/execution-2026-11-14/W1_SKY_LAYERS.md.
//
// Why the offsets are never guessed: the sky PS declares `PSParamBuffer1` **twice** (64 bytes at bind 1, 128 at bind 2)
// and the captures bind neither at its declared size (112 bytes at slot 1), so "the widest binding", "the first
// declaration" and "the last one" all read the wrong bytes. Two earlier guesses of that kind produced the wrong
// numbers this file exists to replace (PLAN_2026-11-13.md L9, corrected by W1_SKY_CB_VALUES.md). The slot comes from
// the shader's own RDEF bind table plus the sizes the draw actually binds (sky_cb_dump.py's rule), and the byte offset
// comes from the member declaration.
//
// Portable C++17, no D3D types: the live path passes bytes, the gates pass files. Gate: checks/test_sky_layer.py.
#ifndef SKY_LAYER_H
#define SKY_LAYER_H

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace sky_layer {

inline constexpr std::uint64_t kSkyPsCode = 0x33856d1d3ba64bb3ull;  // FNV-1a 64 of the sky PS bytecode
inline constexpr std::uint32_t kUnbound = 0xffffffffu;
inline constexpr std::size_t kSlots = 16;   // D3D11_PS_COMMONSHADER_CONSTANT_BUFFER_API_SLOT_COUNT: what a draw can bind

inline std::uint64_t fnv1a64(const unsigned char* bytes, std::size_t count) {
    std::uint64_t h = 0xcbf29ce484222325ull;
    for (std::size_t i = 0; i < count; ++i) h = (h ^ bytes[i]) * 0x100000001b3ull;
    return h;
}
inline std::uint64_t fnv1a64(const std::vector<unsigned char>& bytes) { return fnv1a64(bytes.data(), bytes.size()); }

// One named member of a declared constant buffer. `buffer_size` and `binds` belong to the buffer that declares it: two
// buffers can share a name (the sky shader's PSParamBuffer1), and the size is what tells them apart.
struct Decl {
    std::string name;
    std::string buffer;             // the constant buffer that declares it
    std::uint32_t offset = 0;        // byte offset inside the buffer
    std::uint32_t size = 0;          // bytes the member occupies
    std::uint32_t buffer_size = 0;   // bytes the buffer declares
    std::vector<std::uint32_t> binds;   // slots the buffer may be bound at, per the shader's resource table
};
// A slot as this draw binds it: how many bytes the runtime reports, and the bytes themselves when they were read.
struct Binding {
    std::uint32_t bytes = 0;
    const unsigned char* data = nullptr;
};
// The folded inputs of one sky layer. `present` is false when the shader does not declare all three members, or any of
// them cannot be read: then nothing is folded and today's material stands (never a zero-filled guess).
struct Inputs {
    bool present = false;
    bool use_albedo = false;         // g_AlbedoParam.w > 0: the shader's base colour is the constant, not t0
    float albedo[3] = {0.f, 0.f, 0.f};
    float intensity = 1.f;           // g_IntensityParam.y
    float mesh[3] = {1.f, 1.f, 1.f}; // g_MeshColor.rgb
};

namespace detail {
inline std::uint32_t u32(const unsigned char* p) {
    std::uint32_t v = 0;
    std::memcpy(&v, p, 4);
    return v;
}
inline std::string name_at(const std::vector<unsigned char>& rdef, std::uint32_t offset) {
    std::string out;
    if (offset >= rdef.size()) return out;
    for (std::size_t i = offset; i < rdef.size(); ++i) {
        if (rdef[i] == 0) return out;
        if (out.size() > 256) return std::string();   // a name that long is not a name: refuse rather than grow
        out.push_back(static_cast<char>(rdef[i]));
    }
    return std::string();
}
inline bool same_binds(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b) { return a == b; }
}  // namespace detail

// Every named constant-buffer member the shader declares, from its DXBC `RDEF` chunk. false: not a DXBC container, no
// RDEF chunk, or a table that does not fit its own bounds. Never throws, never reads past the blob.
inline bool members(const std::vector<unsigned char>& dxbc, std::vector<Decl>& out) {
    out.clear();
    if (dxbc.size() < 32 || std::memcmp(dxbc.data(), "DXBC", 4) != 0) return false;
    if (detail::u32(dxbc.data() + 24) != dxbc.size()) return false;   // the container's own size must match
    const std::uint32_t chunks = detail::u32(dxbc.data() + 28);
    if (!chunks || 32ull + 4ull * chunks > dxbc.size()) return false;
    const unsigned char* rdef = nullptr;
    std::uint32_t rdef_size = 0;
    for (std::uint32_t i = 0; i < chunks; ++i) {
        const std::uint32_t at = detail::u32(dxbc.data() + 32 + 4 * i);
        if (at < 32 || 8ull + at > dxbc.size()) return false;
        const std::uint32_t size = detail::u32(dxbc.data() + at + 4);
        if (8ull + at + size > dxbc.size()) return false;
        if (std::memcmp(dxbc.data() + at, "RDEF", 4) == 0) { rdef = dxbc.data() + at + 8; rdef_size = size; }
    }
    if (!rdef || rdef_size < 28) return false;
    const std::vector<unsigned char> chunk(rdef, rdef + rdef_size);
    const std::uint32_t cb_count = detail::u32(chunk.data());
    const std::uint32_t cb_offset = detail::u32(chunk.data() + 4);
    const std::uint32_t res_count = detail::u32(chunk.data() + 8);
    const std::uint32_t res_offset = detail::u32(chunk.data() + 12);
    const std::uint32_t target = detail::u32(chunk.data() + 16);
    const std::uint32_t major = (target >> 8) & 0xffu;
    if (major != 4 && major != 5) return false;   // only the shader models the game ships (ps_4_0 / ps_5_0)
    const std::uint32_t stride = major == 5 ? 40u : 24u;
    if ((cb_count && cb_offset < 28) || 24ull * cb_count + cb_offset > chunk.size()) return false;
    if ((res_count && res_offset < 28) || 32ull * res_count + res_offset > chunk.size()) return false;
    // Bind slots come from the resource table (kind 0 = cbuffer), not from the declaration order.
    std::vector<std::pair<std::string, std::vector<std::uint32_t>>> binds;
    for (std::uint32_t i = 0; i < res_count; ++i) {
        const unsigned char* entry = chunk.data() + res_offset + 32ull * i;
        if (detail::u32(entry + 4) != 0) continue;   // not a constant buffer
        const std::string name = detail::name_at(chunk, detail::u32(entry));
        if (name.empty()) return false;
        const std::uint32_t bind = detail::u32(entry + 20);
        bool placed = false;
        for (auto& [known, slots] : binds)
            if (known == name) { slots.push_back(bind); placed = true; }
        if (!placed) binds.push_back({name, {bind}});
    }
    for (std::uint32_t i = 0; i < cb_count; ++i) {
        const unsigned char* entry = chunk.data() + cb_offset + 24ull * i;
        const std::string buffer = detail::name_at(chunk, detail::u32(entry));
        if (buffer.empty()) return false;
        const std::uint32_t var_count = detail::u32(entry + 4);
        const std::uint32_t var_offset = detail::u32(entry + 8);
        const std::uint32_t buffer_size = detail::u32(entry + 12);
        if ((var_count && var_offset < 28) || stride * static_cast<std::uint64_t>(var_count) + var_offset > chunk.size())
            return false;
        std::vector<std::uint32_t> slots;
        for (const auto& [known, at] : binds)
            if (known == buffer) slots = at;
        for (std::uint32_t v = 0; v < var_count; ++v) {
            const unsigned char* var = chunk.data() + var_offset + stride * static_cast<std::uint64_t>(v);
            Decl d;
            d.name = detail::name_at(chunk, detail::u32(var));
            d.buffer = buffer;
            d.offset = detail::u32(var + 4);
            d.size = detail::u32(var + 8);
            d.buffer_size = buffer_size;
            d.binds = slots;
            if (d.name.empty() || static_cast<std::uint64_t>(d.offset) + d.size > buffer_size)
                return false;   // a member outside its own buffer (64-bit: an offset near 2^32 must not wrap)
            out.push_back(std::move(d));
        }
    }
    return true;
}

// Where each declared buffer is bound, as sky_cb_dump.py's rule does it: an exact declared-size match is assigned
// first, then the remaining buffers only if exactly one unclaimed slot can hold them. Two candidates of the right size
// are refused (kUnbound means "this draw binds nothing for it", which reads as no fold). One slot per declaration.
inline bool place(const std::vector<Decl>& decls, const std::array<std::uint32_t, kSlots>& bound,
                  std::vector<std::uint32_t>& out) {
    out.assign(decls.size(), kUnbound);
    // Distinct buffers, in declaration order: a name with two sizes is two buffers (the sky shader's PSParamBuffer1).
    struct Buffer { std::uint32_t size = 0; std::vector<std::uint32_t> binds; std::vector<std::size_t> members; };
    std::vector<Buffer> buffers;
    for (std::size_t i = 0; i < decls.size(); ++i) {
        bool found = false;
        for (auto& b : buffers)
            if (b.size == decls[i].buffer_size && detail::same_binds(b.binds, decls[i].binds)) {
                b.members.push_back(i);
                found = true;
            }
        if (!found) buffers.push_back({decls[i].buffer_size, decls[i].binds, {i}});
    }
    std::vector<std::uint32_t> assigned(buffers.size(), kUnbound);
    std::vector<std::size_t> pending;
    for (std::size_t i = 0; i < buffers.size(); ++i) {
        std::vector<std::uint32_t> claimed;   // a slot carries one buffer
        for (std::size_t k = 0; k < i; ++k)
            if (assigned[k] != kUnbound) claimed.push_back(assigned[k]);
        std::vector<std::uint32_t> exact;
        for (const std::uint32_t slot : buffers[i].binds) {
            if (slot >= kSlots || bound[slot] != buffers[i].size) continue;
            bool taken = false;
            for (const std::uint32_t c : claimed) taken |= c == slot;
            if (!taken) exact.push_back(slot);
        }
        if (exact.size() == 1) assigned[i] = exact[0];
        else if (exact.size() > 1) return false;   // two slots carry exactly the declared size: no way to choose
        else pending.push_back(i);
    }
    for (const std::size_t i : pending) {
        std::vector<std::uint32_t> claimed;
        for (std::size_t k = 0; k < buffers.size(); ++k)
            if (assigned[k] != kUnbound) claimed.push_back(assigned[k]);
        std::vector<std::uint32_t> fits;
        bool any_bound = false;
        for (const std::uint32_t slot : buffers[i].binds) {
            if (slot >= kSlots) continue;
            bool taken = false;
            for (const std::uint32_t c : claimed) taken |= c == slot;
            if (taken) continue;
            any_bound |= bound[slot] != 0;
            if (bound[slot] >= buffers[i].size) fits.push_back(slot);
        }
        if (fits.size() == 1) assigned[i] = fits[0];
        else if (fits.size() > 1) return false;   // ambiguous: refuse instead of picking one
        else if (any_bound) return false;         // bound, but too small to hold the declaration: refuse
        // else: nothing bound for this buffer at all: kUnbound, and reading it is refused below
    }
    for (std::size_t i = 0; i < buffers.size(); ++i)
        for (const std::size_t member : buffers[i].members) out[member] = assigned[i];
    return true;
}

namespace detail {
inline bool value(const Decl& d, std::uint32_t slot, const std::array<Binding, kSlots>& bindings, float* out) {
    if (slot >= kSlots) return false;
    const Binding& b = bindings[slot];
    if (!b.data || static_cast<std::uint64_t>(d.offset) + 16u > b.bytes) return false;   // every member here is a float4
    for (int k = 0; k < 4; ++k) {
        float v = 0.f;
        std::memcpy(&v, b.data + d.offset + 4u * static_cast<std::uint32_t>(k), 4);
        if (!std::isfinite(v) || std::fabs(v) > 1e6f) return false;   // a garbage buffer is not a value
        out[k] = v;
    }
    return true;
}
}  // namespace detail

// The three members, read from the buffers this draw binds. false (and `in.present` false) when a member is not
// declared exactly once, not placed, not bound, or holds something that is not a finite float4.
// The subset of `decls` that names `first` and `second` in ONE declared buffer, or empty when either is missing or
// declared twice. `place` is then asked about that one buffer instead of every buffer the shader declares, which matters:
// it refuses as soon as any other declared buffer is bound smaller than its declaration, and a shader with a dozen PS
// buffers is regularly in that state (the hair shader binds twelve, one of them a 4-byte index buffer at slot 9).
inline std::vector<Decl> both_members(const std::vector<Decl>& decls, const char* first, const char* second) {
    std::vector<Decl> out;
    for (const Decl& d : decls)
        if (d.name == first || d.name == second) out.push_back(d);
    if (out.size() != 2 || out[0].buffer != out[1].buffer) return {};
    return out;
}

inline bool read(const std::vector<Decl>& decls, const std::vector<std::uint32_t>& placed,
                 const std::array<Binding, kSlots>& bindings, Inputs& in) {
    in = Inputs{};
    const auto find = [&decls, &placed](const char* name, const Decl** decl, std::uint32_t& slot) {
        int found = 0;
        for (std::size_t i = 0; i < decls.size(); ++i)
            if (decls[i].name == name) { ++found; *decl = &decls[i]; slot = i < placed.size() ? placed[i] : kUnbound; }
        return found == 1;   // declared in two buffers: refuse
    };
    const Decl* intensity = nullptr;
    const Decl* albedo = nullptr;
    const Decl* mesh = nullptr;
    std::uint32_t intensity_slot = kUnbound, albedo_slot = kUnbound, mesh_slot = kUnbound;
    if (!find("g_IntensityParam", &intensity, intensity_slot) || !find("g_AlbedoParam", &albedo, albedo_slot) ||
        !find("g_MeshColor", &mesh, mesh_slot))
        return false;
    float i4[4] = {0, 0, 0, 0}, a4[4] = {0, 0, 0, 0}, m4[4] = {0, 0, 0, 0};
    if (!detail::value(*intensity, intensity_slot, bindings, i4) || !detail::value(*albedo, albedo_slot, bindings, a4) ||
        !detail::value(*mesh, mesh_slot, bindings, m4))
        return false;
    in.present = true;
    in.use_albedo = a4[3] > 0.f;
    for (int k = 0; k < 3; ++k) {
        in.albedo[k] = a4[k];
        in.mesh[k] = m4[k];
    }
    in.intensity = i4[1];
    return true;
}

// The base colour of a layer as one constant, when the shader itself uses a constant (g_AlbedoParam.w > 0).
// false for a textured layer: Remix's albedoConstant *replaces* the albedo texture instead of multiplying it
// (replay/research-2026-11-12/remix_material_api.md:19-21), so t0 * factor has no expression in this API.
inline bool constant_colour(const Inputs& in, float out[3]) {
    if (!in.present || !in.use_albedo) return false;
    for (int k = 0; k < 3; ++k) {
        const float v = in.albedo[k] * in.intensity * in.mesh[k];
        if (!std::isfinite(v) || std::fabs(v) > 1e4f) return false;   // implausible: leave today's material
        out[k] = v;
    }
    return true;
}
}  // namespace sky_layer

#endif  // SKY_LAYER_H
