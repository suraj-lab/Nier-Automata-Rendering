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
// Why a decode was refused. The distinction that matters live: a *transient* refusal (the game was writing the buffer
// while we read it -> IndexBytesShort / VertexOutOfRange) must be retried, while a *structural* one (UnsupportedFormat,
// NoPosition) will never succeed and is worth banning. live_capture used to ban both, so one bad frame removed an
// object for the rest of the session.
enum class Failure {
    None, InvalidInput, BadIndexWidth, IndexBytesShort, SlotMissing, UnsupportedFormat, BadStride,
    IndexBaseOutOfRange, VertexOutOfRange, NoPosition, BoneOutOfRange, Count
};
inline const char* failure_name(Failure f) {
    switch (f) {
        case Failure::None: return "none";
        case Failure::InvalidInput: return "invalid_input";
        case Failure::BadIndexWidth: return "bad_index_width";
        case Failure::IndexBytesShort: return "index_bytes_short";
        case Failure::SlotMissing: return "slot_missing";
        case Failure::UnsupportedFormat: return "unsupported_format";
        case Failure::BadStride: return "bad_stride";
        case Failure::IndexBaseOutOfRange: return "index_base_out_of_range";
        case Failure::VertexOutOfRange: return "vertex_out_of_range";
        case Failure::NoPosition: return "no_position";
        case Failure::BoneOutOfRange: return "bone_out_of_range";
        default: return "unknown";
    }
}
inline bool transient(Failure f) {
    return f == Failure::IndexBytesShort || f == Failure::VertexOutOfRange || f == Failure::SlotMissing;
}

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
//
// Speed matters here: this runs on the game thread for every mesh seen for the first time. popin-b1000/2000/4000
// (2026-11-01) measured ~4 ms per first-sight build on the laptop, the service rate behind pop-in. Which element feeds
// which field depends only on the layout, so it is planned once per draw; the per-vertex loop reads fixed offsets.
inline bool build(const Slot* slots, unsigned slot_count, const std::vector<Element>& elements,
                  const unsigned char* index_bytes, std::size_t index_bytes_size, unsigned index_width,
                  std::size_t first_index, std::uint32_t index_count, std::int32_t base_vertex,
                  std::uint32_t bone_count, bool skinned, Output& out, Failure* why = nullptr) {
    out = Output{};
    const auto refuse = [why](Failure f) { if (why) *why = f; return false; };
    if (why) *why = Failure::None;
    if (!slots || !slot_count || !index_bytes || !index_count || index_count % 3 != 0) return refuse(Failure::InvalidInput);
    if (index_width != 2 && index_width != 4) return refuse(Failure::BadIndexWidth);
    if (first_index > index_bytes_size ||
        static_cast<std::size_t>(index_count) * index_width > index_bytes_size - first_index)
        return refuse(Failure::IndexBytesShort);
    for (unsigned i = 0; i < slot_count; ++i)
        if (!slots[i].bytes || !slots[i].stride) return refuse(Failure::SlotMissing);
    for (const auto& e : elements) {
        const std::size_t size = detail::format_size(e.format);
        if (!size || e.slot >= slot_count) return refuse(Failure::UnsupportedFormat);
        if (e.offset > slots[e.slot].stride || size > slots[e.slot].stride - e.offset) return refuse(Failure::BadStride);
    }

    // The plan: per slot in order, the first readable element of each semantic (TEXCOORD1 must not overwrite
    // TEXCOORD0). Unreadable formats do not claim their semantic, so a later readable one still can.
    enum Kind { Position, Normal, Texcoord, ColorBytes, ColorFloat };
    struct Read { Kind kind; unsigned slot, offset; bool half; };
    std::vector<Read> plan;
    std::vector<const std::string*> claimed;
    bool positioned = false;
    for (unsigned slot = 0; slot < slot_count; ++slot)
        for (const auto& e : elements) {
            if (e.slot != slot || e.per_instance) continue;
            bool taken = false;
            for (const auto* s : claimed) taken = taken || *s == e.semantic;
            if (taken) continue;
            const bool f3 = e.format == 6 || e.format == 2 || e.format == 10;
            Kind kind;
            if (e.semantic == "POSITION" && f3) kind = Position;
            else if (e.semantic == "NORMAL" && f3) kind = Normal;
            else if (e.semantic == "TEXCOORD" && (e.format == 16 || e.format == 34 || e.format == 2 || e.format == 10)) kind = Texcoord;
            else if (e.semantic == "COLOR" && (e.format == 28 || e.format == 30)) kind = ColorBytes;
            else if (e.semantic == "COLOR" && (e.format == 2 || e.format == 10)) kind = ColorFloat;
            else continue;
            plan.push_back({kind, slot, e.offset, e.format == 10 || e.format == 34});
            claimed.push_back(&e.semantic);
            positioned = positioned || kind == Position;
        }
    // Skinning: the last BLENDINDICES/BLENDWEIGHT element of the right format wins, as before.
    const Element* blend_indices = nullptr;
    const Element* blend_weights = nullptr;
    if (skinned)
        for (const auto& e : elements) {
            if (e.per_instance) continue;
            if (e.semantic == "BLENDINDICES" && e.format == 30) blend_indices = &e;
            if (e.semantic == "BLENDWEIGHT" && e.format == 28) blend_weights = &e;
        }

    const unsigned char* indices = index_bytes + first_index;
    const auto index_at = [&](std::uint32_t i) -> std::int64_t {
        const unsigned char* p = indices + static_cast<std::size_t>(i) * index_width;
        std::uint32_t raw = 0;
        if (index_width == 2) { std::uint16_t v; std::memcpy(&v, p, 2); raw = v; }
        else std::memcpy(&raw, p, 4);
        return static_cast<std::int64_t>(raw) + base_vertex;
    };
    // Remap original vertex number -> output index. A flat table over the referenced range when it is compact (always
    // for 16-bit indices); a map otherwise, so a sparse 32-bit range cannot allocate gigabytes.
    std::int64_t low = 0xffffffffll, high = -1;
    for (std::uint32_t i = 0; i < index_count; ++i) {
        const std::int64_t n = index_at(i);
        if (n < 0 || n > 0xffffffffll) continue;  // refused in order below
        low = n < low ? n : low;
        high = n > high ? n : high;
    }
    constexpr std::uint32_t kUnseen = 0xffffffffu;
    const std::size_t span = high >= low ? static_cast<std::size_t>(high - low + 1) : 0;
    const bool flat = span <= (std::size_t(1) << 22) || (span <= std::size_t(4) * index_count && span <= (std::size_t(1) << 24));
    std::vector<std::uint32_t> table(flat ? span : 0, kUnseen);
    std::map<std::uint32_t, std::uint32_t> sparse;
    out.indices.reserve(index_count);

    for (std::uint32_t i = 0; i < index_count; ++i) {
        const std::int64_t numbered = index_at(i);
        if (numbered < 0 || numbered > 0xffffffffll) return refuse(Failure::IndexBaseOutOfRange);
        const std::uint32_t original = static_cast<std::uint32_t>(numbered);
        std::uint32_t* slot_in_table = flat ? &table[static_cast<std::size_t>(numbered - low)] : nullptr;
        if (flat && *slot_in_table != kUnseen) { out.indices.push_back(*slot_in_table); continue; }
        if (!flat) {
            const auto seen = sparse.find(original);
            if (seen != sparse.end()) { out.indices.push_back(seen->second); continue; }
        }

        for (unsigned slot = 0; slot < slot_count; ++slot)
            if (static_cast<std::size_t>(slots[slot].offset) +
                static_cast<std::size_t>(original) * slots[slot].stride + slots[slot].stride > slots[slot].size)
                return refuse(Failure::VertexOutOfRange);
        if (!positioned) return refuse(Failure::NoPosition);

        Vertex vertex{};
        vertex.color = 0xffffffffu;
        vertex.normal[2] = -1.f;  // a draw without NORMAL keeps a usable default, as the offline converter does
        for (const Read& r : plan) {
            const unsigned char* f = slots[r.slot].bytes + slots[r.slot].offset +
                                     static_cast<std::size_t>(original) * slots[r.slot].stride + r.offset;
            const auto comp = [f, &r](int k) -> float {
                if (r.half) return detail::half(f + 2 * k);
                float v;
                std::memcpy(&v, f + 4 * k, sizeof v);
                return v;
            };
            switch (r.kind) {
            case Position: for (int k = 0; k < 3; ++k) vertex.position[k] = comp(k); break;
            case Normal: for (int k = 0; k < 3; ++k) vertex.normal[k] = comp(k); break;
            case Texcoord: for (int k = 0; k < 2; ++k) vertex.texcoord[k] = comp(k); break;
            case ColorBytes: std::memcpy(&vertex.color, f, sizeof vertex.color); break;
            case ColorFloat: {
                unsigned char rgba[4];
                for (int k = 0; k < 4; ++k) {
                    const float v = comp(k);
                    rgba[k] = static_cast<unsigned char>(v < 0.f ? 0.f : v > 1.f ? 255.f : v * 255.f + 0.5f);
                }
                std::memcpy(&vertex.color, rgba, sizeof vertex.color);
                break;
            }
            }
        }

        if (skinned) {
            std::uint32_t bones_local[4] = {0, 0, 0, 0};
            float weights_local[4] = {0, 0, 0, 0};
            const auto at = [&](const Element* e) {
                return slots[e->slot].bytes + slots[e->slot].offset + static_cast<std::size_t>(original) * slots[e->slot].stride +
                       e->offset;
            };
            if (blend_indices) for (int k = 0; k < 4; ++k) bones_local[k] = at(blend_indices)[k];
            if (blend_weights) for (int k = 0; k < 4; ++k) weights_local[k] = at(blend_weights)[k] / 255.f;
            for (int k = 0; k < 4; ++k)  // real captures contain garbage indices in zero-weight slots
                if (weights_local[k] > 0.f && bones_local[k] >= bone_count) return refuse(Failure::BoneOutOfRange);
            out.bones.insert(out.bones.end(), bones_local, bones_local + 4);
            out.weights.insert(out.weights.end(), weights_local, weights_local + 4);
        }
        const std::uint32_t next = static_cast<std::uint32_t>(out.vertices.size());
        if (flat) *slot_in_table = next;
        else sparse.emplace(original, next);
        out.vertices.push_back(vertex);
        out.indices.push_back(next);
    }
    return true;
}

}  // namespace live_decode
