#pragma once
// Pure vertex decode for one draw: compact bind-pose vertices + remapped indices (+ bone data when skinned).
// Split out of the capture hook so it can be checked against real captured draws without D3D11.
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace live_decode {

struct Element {
    std::string semantic;   // upper case
    int format = 0;
    unsigned offset = 0;
    unsigned slot = 0;
    bool per_instance = false;  // per-instance input, never per-vertex data
};
struct Slot {
    const unsigned char* bytes = nullptr;
    std::size_t size = 0;
    unsigned stride = 0;
    unsigned offset = 0;  // the offset the buffer is bound with
};
struct Vertex {
    float position[3];
    float normal[3];
    float texcoord[2];
    std::uint32_t color;
};
struct Output {
    std::vector<Vertex> vertices;      // one per distinct referenced vertex, first-reference order
    std::vector<std::uint32_t> indices; // the draw's index list remapped into `vertices`
    std::vector<std::uint32_t> bones;   // 4 per vertex, skinned draws only
    std::vector<float> weights;         // 4 per vertex, skinned draws only
};

namespace detail {
inline std::size_t format_size(int format) {
    switch (format) {
    case 2: return 16;   // R32G32B32A32_FLOAT
    case 6: return 12;   // R32G32B32_FLOAT
    case 10: return 8;   // R16G16B16A16_FLOAT
    case 16: return 8;   // R32G32_FLOAT
    case 28: return 4;   // R8G8B8A8_UNORM
    case 30: return 4;   // R8G8B8A8_UINT
    case 34: return 4;   // R16G16_FLOAT
    default: return 0;
    }
}
inline float half(const unsigned char* p) {
    std::uint16_t h;
    std::memcpy(&h, p, sizeof h);
    std::uint32_t exponent = (h >> 10) & 31u, fraction = h & 1023u;
    std::uint32_t bits = static_cast<std::uint32_t>(h & 0x8000u) << 16;
    if (exponent == 31) bits |= 0x7f800000u | (fraction << 13);
    else if (exponent) bits |= ((exponent + 112u) << 23) | (fraction << 13);
    else if (fraction) {
        exponent = 113;
        while (!(fraction & 1024u)) { fraction <<= 1; --exponent; }
        bits |= (exponent << 23) | ((fraction & 1023u) << 13);
    }
    float value;
    std::memcpy(&value, &bits, sizeof value);
    return value;
}
}  // namespace detail

// `first_index` is the byte offset of the draw's first index inside `index_bytes` (IB offset included).
// Rejects (leaving `out` empty) on any out-of-range access, so a malformed draw can never read garbage.
inline bool build(const Slot* slots, unsigned slot_count, const std::vector<Element>& elements,
                  const unsigned char* index_bytes, std::size_t index_bytes_size, unsigned index_width,
                  std::size_t first_index, std::uint32_t index_count, std::int32_t base_vertex,
                  std::uint32_t bone_count, bool skinned, Output& out) {
    out = Output{};
    if (!slots || !slot_count || !index_bytes || !index_count || index_count % 3 != 0) return false;
    if (index_width != 2 && index_width != 4) return false;
    if (first_index > index_bytes_size ||
        static_cast<std::size_t>(index_count) * index_width > index_bytes_size - first_index)
        return false;
    for (unsigned i = 0; i < slot_count; ++i)
        if (!slots[i].bytes || !slots[i].stride) return false;
    for (const auto& e : elements) {
        const std::size_t size = detail::format_size(e.format);
        if (!size || e.slot >= slot_count) return false;
        if (e.offset > slots[e.slot].stride || size > slots[e.slot].stride - e.offset) return false;
    }

    std::map<std::uint32_t, std::uint32_t> compact;  // original vertex number -> output index
    out.indices.reserve(index_count);
    for (std::uint32_t i = 0; i < index_count; ++i) {
        const unsigned char* p = index_bytes + first_index + static_cast<std::size_t>(i) * index_width;
        std::uint32_t raw = 0;
        if (index_width == 2) { std::uint16_t v; std::memcpy(&v, p, 2); raw = v; }
        else std::memcpy(&raw, p, 4);
        const std::int64_t numbered = static_cast<std::int64_t>(raw) + base_vertex;
        if (numbered < 0 || numbered > 0xffffffffll) return false;
        const std::uint32_t original = static_cast<std::uint32_t>(numbered);
        const auto seen = compact.find(original);
        if (seen != compact.end()) { out.indices.push_back(seen->second); continue; }

        Vertex vertex{};
        vertex.color = 0xffffffffu;
        vertex.normal[2] = -1.f;  // a draw without NORMAL keeps a usable default, as the offline converter does
        bool positioned = false;
        std::vector<std::string> seen_semantics;
        for (unsigned slot = 0; slot < slot_count; ++slot) {
            if (static_cast<std::size_t>(slots[slot].offset) +
                static_cast<std::size_t>(original) * slots[slot].stride + slots[slot].stride > slots[slot].size)
                return false;
            const unsigned char* base = slots[slot].bytes + slots[slot].offset +
                                        static_cast<std::size_t>(original) * slots[slot].stride;
            for (const auto& e : elements) {
                if (e.slot != slot || e.per_instance) continue;
                bool first = true;
                for (const auto& s : seen_semantics) if (s == e.semantic) first = false;
                if (!first) continue;  // TEXCOORD1 must not overwrite TEXCOORD0
                const unsigned char* f = base + e.offset;
                bool read = true;
                if (e.semantic == "POSITION" && e.format == 6) {
                    std::memcpy(vertex.position, f, sizeof vertex.position);
                    positioned = true;
                } else if (e.semantic == "NORMAL" && e.format == 6) {
                    std::memcpy(vertex.normal, f, sizeof vertex.normal);
                } else if (e.semantic == "NORMAL" && e.format == 10) {
                    for (int k = 0; k < 3; ++k) vertex.normal[k] = detail::half(f + 2 * k);
                } else if (e.semantic == "TEXCOORD" && e.format == 16) {
                    std::memcpy(vertex.texcoord, f, sizeof vertex.texcoord);
                } else if (e.semantic == "TEXCOORD" && e.format == 34) {
                    for (int k = 0; k < 2; ++k) vertex.texcoord[k] = detail::half(f + 2 * k);
                } else if (e.semantic == "COLOR" && (e.format == 28 || e.format == 30)) {
                    std::memcpy(&vertex.color, f, sizeof vertex.color);
                } else {
                    read = false;
                }
                if (read) seen_semantics.push_back(e.semantic);
            }
        }
        if (!positioned) return false;

        if (skinned) {
            std::uint32_t bones_local[4] = {0, 0, 0, 0};
            float weights_local[4] = {0, 0, 0, 0};
            for (const auto& e : elements) {
                if (e.per_instance) continue;
                const unsigned char* base = slots[e.slot].bytes + slots[e.slot].offset +
                                            static_cast<std::size_t>(original) * slots[e.slot].stride;
                if (e.semantic == "BLENDINDICES" && e.format == 30)
                    for (int k = 0; k < 4; ++k) bones_local[k] = base[e.offset + k];
                if (e.semantic == "BLENDWEIGHT" && e.format == 28)
                    for (int k = 0; k < 4; ++k) weights_local[k] = base[e.offset + k] / 255.f;
            }
            for (int k = 0; k < 4; ++k)  // real captures contain garbage indices in zero-weight slots
                if (weights_local[k] > 0.f && bones_local[k] >= bone_count) return false;
            out.bones.insert(out.bones.end(), bones_local, bones_local + 4);
            out.weights.insert(out.weights.end(), weights_local, weights_local + 4);
        }
        compact.emplace(original, static_cast<std::uint32_t>(out.vertices.size()));
        out.vertices.push_back(vertex);
        out.indices.push_back(static_cast<std::uint32_t>(out.vertices.size() - 1));
    }
    return true;
}

}  // namespace live_decode
