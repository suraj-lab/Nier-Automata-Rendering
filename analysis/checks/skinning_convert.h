// Reference only, not linked into the DLL: the shipping decode is live_vertex_decode.h. Kept because its gate
// (test_skinning_convert.py) checks the skinning arithmetic against NieR's own on real draws.
#ifndef SKINNING_CONVERT_H
#define SKINNING_CONVERT_H

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace skinning_convert {

struct Element { std::string semantic; int format = 0; unsigned offset = 0; };
struct SkinVertex {
    float position[3]; float normal[3]; float texcoord[2]; std::uint32_t color;
    std::uint32_t bone[4]; float weight[4];
};

namespace detail {
inline unsigned format_size(int format) {
    switch (format) {
    case 2: return 16;
    case 6: return 12;
    case 10: case 16: return 8;
    case 28: case 30: case 34: case 42: return 4;
    case 57: return 2;
    default: return 0;
    }
}

inline std::uint32_t read_index(const unsigned char* p, unsigned size) {
    if (size == 2) {
        std::uint16_t value;
        std::memcpy(&value, p, sizeof value);
        return value;
    }
    std::uint32_t value;
    std::memcpy(&value, p, sizeof value);
    return value;
}

inline float half(const unsigned char* p) {
    std::uint16_t h;
    std::memcpy(&h, p, sizeof h);
    std::uint32_t exponent = (h >> 10) & 31u;
    std::uint32_t fraction = h & 1023u;
    std::uint32_t bits = static_cast<std::uint32_t>(h & 0x8000u) << 16;
    if (exponent == 31) {
        bits |= 0x7f800000u | (fraction << 13);
    } else if (exponent != 0) {
        bits |= ((exponent + 112u) << 23) | (fraction << 13);
    } else if (fraction != 0) {
        exponent = 113;
        while ((fraction & 1024u) == 0) {
            fraction <<= 1;
            --exponent;
        }
        bits |= (exponent << 23) | ((fraction & 1023u) << 13);
    }
    float value;
    std::memcpy(&value, &bits, sizeof value);
    return value;
}
} // namespace detail

inline bool build(const unsigned char* vertices, std::size_t vertex_bytes, unsigned stride,
                  const std::vector<Element>& elements,
                  const unsigned char* index_bytes, std::size_t index_bytes_size, int index_format,
                  std::uint32_t start_index, std::uint32_t index_count, std::uint32_t bone_count,
                  std::vector<SkinVertex>& out, std::vector<std::uint32_t>& indices) {
    out.clear();
    indices.clear();
    const auto reject = [&]() {
        out.clear();
        indices.clear();
        return false;
    };
    if (!vertices || !index_bytes || !stride || vertex_bytes % stride != 0 ||
        !index_count || index_count % 3 != 0 || (index_format != 57 && index_format != 42))
        return false;
    const unsigned index_size = index_format == 57 ? 2 : 4;
    const std::size_t available = index_bytes_size / index_size;
    if (start_index > available || index_count > available - start_index ||
        index_count > indices.max_size() / 2)
        return false;

    const Element *position = nullptr, *normal = nullptr, *texcoord = nullptr,
                  *color = nullptr, *bones = nullptr, *weights = nullptr;
    for (const auto& e : elements) {
        const unsigned size = detail::format_size(e.format);
        if (!size || e.offset > stride || size > stride - e.offset)
            return false;
        if (e.semantic == "POSITION") {
            if (e.format != 6) return false;
            position = &e;
        } else if (e.semantic == "NORMAL") {
            if (e.format != 6 && e.format != 10) return false;
            normal = &e;
        } else if (e.semantic == "TEXCOORD") {
            if (e.format != 16 && e.format != 34) return false;
            texcoord = &e;
        } else if (e.semantic == "COLOR") {
            if (e.format != 28 && e.format != 30) return false;
            color = &e;
        } else if (e.semantic == "BLENDINDICES") {
            if (e.format != 30) return false;
            bones = &e;
        } else if (e.semantic == "BLENDWEIGHT") {
            if (e.format != 28) return false;
            weights = &e;
        }
    }
    if (!position || !bones || !weights)
        return false;

    const std::size_t count = index_count;
    const std::uint32_t unused = std::numeric_limits<std::uint32_t>::max();
    // The output vector's tail is a hash table of first references, not a whole-buffer map.
    indices.resize(2 * count, unused);
    const unsigned char* draw = index_bytes + static_cast<std::size_t>(start_index) * index_size;
    for (std::uint32_t i = 0; i < index_count; ++i) {
        const auto original = detail::read_index(draw + static_cast<std::size_t>(i) * index_size, index_size);
        if (original >= vertex_bytes / stride)
            return reject();
        std::size_t bucket = (original * 2654435761u) % index_count;
        while (indices[count + bucket] != unused) {
            const auto first = indices[count + bucket];
            if (detail::read_index(draw + static_cast<std::size_t>(first) * index_size, index_size) == original)
                break;
            bucket = (bucket + 1) % count;
        }
        const auto first = indices[count + bucket];
        if (first != unused) {
            indices[i] = indices[first];
            continue;
        }

        const unsigned char* v = vertices + static_cast<std::size_t>(original) * stride;
        SkinVertex result{};
        result.color = 0xffffffffu;
        std::memcpy(result.position, v + position->offset, sizeof result.position);
        if (normal) {
            if (normal->format == 6)
                std::memcpy(result.normal, v + normal->offset, sizeof result.normal);
            else
                for (unsigned k = 0; k < 3; ++k)
                    result.normal[k] = detail::half(v + normal->offset + 2 * k);
        }
        if (texcoord) {
            if (texcoord->format == 16)
                std::memcpy(result.texcoord, v + texcoord->offset, sizeof result.texcoord);
            else
                for (unsigned k = 0; k < 2; ++k)
                    result.texcoord[k] = detail::half(v + texcoord->offset + 2 * k);
        }
        if (color)
            std::memcpy(&result.color, v + color->offset, sizeof result.color);
        for (unsigned k = 0; k < 4; ++k) {
            result.bone[k] = v[bones->offset + k];
            const unsigned weight = v[weights->offset + k];
            result.weight[k] = static_cast<float>(weight) / 255.0f;
            // Real draws contain garbage bone indices in zero-weight slots.
            if (weight != 0 && result.bone[k] >= bone_count)
                return reject();
        }
        indices[count + bucket] = i;
        indices[i] = static_cast<std::uint32_t>(out.size());
        out.push_back(result);
    }
    indices.resize(count);
    return true;
}

} // namespace skinning_convert
#endif
