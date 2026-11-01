#pragma once
// Which input layouts reach the decoder with no POSITION element. The refusal is structural - those draws can never
// decode - so the semantic set is the only thing that identifies the family (a pass we should filter earlier, or a
// geometry type we mis-parse). Bounded: a few distinct signatures per window, overflow counted rather than printed.
#include <algorithm>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>
#include "live_vertex_decode.h"

namespace layout_signature {

constexpr std::size_t kMaxDistinct = 6;
constexpr std::size_t kMaxLen = 120;

struct Entry {
    char text[kMaxLen] = {};
    unsigned long long count = 0;
};

// "NORMAL,POSITION,TEXCOORD:34" style: semantics sorted, duplicates collapsed, format appended only when a semantic
// repeats, so two layouts that differ only in a format are still distinguishable.
inline std::string of(const std::vector<live_decode::Element>& elements) {
    std::vector<std::string> parts;
    parts.reserve(elements.size());
    char buf[48];
    for (const auto& e : elements) {
        if (e.per_instance) continue;  // per-instance data never supplies a vertex position
        std::snprintf(buf, sizeof buf, "%s:%d", e.semantic.c_str(), e.format);
        parts.emplace_back(buf);
    }
    if (parts.empty()) return "(no per-vertex elements)";
    std::sort(parts.begin(), parts.end());
    parts.erase(std::unique(parts.begin(), parts.end()), parts.end());
    std::string joined;
    for (const auto& p : parts) {
        if (!joined.empty()) joined += ',';
        joined += p;
        if (joined.size() >= kMaxLen - 1) break;  // bounded: a pathological layout cannot grow the line
    }
    joined.resize(std::min(joined.size(), kMaxLen - 1));
    return joined;
}

inline std::mutex& mutex() { static std::mutex m; return m; }
inline std::vector<Entry>& store() { static std::vector<Entry> v; return v; }
inline unsigned long long& overflowed() { static unsigned long long n = 0; return n; }

inline void note(const std::vector<live_decode::Element>& elements) {
    const std::string text = of(elements);
    std::lock_guard<std::mutex> lock(mutex());
    for (auto& e : store())
        if (text == e.text) { ++e.count; return; }
    if (store().size() >= kMaxDistinct) { ++overflowed(); return; }
    Entry e;
    std::snprintf(e.text, sizeof e.text, "%s", text.c_str());
    e.count = 1;
    store().push_back(e);
}

inline std::vector<Entry> take() {
    std::lock_guard<std::mutex> lock(mutex());
    std::vector<Entry> out;
    out.swap(store());
    overflowed() = 0;
    std::sort(out.begin(), out.end(), [](const Entry& a, const Entry& b) { return a.count > b.count; });
    return out;
}

}  // namespace layout_signature
