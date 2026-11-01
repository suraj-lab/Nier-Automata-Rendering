#pragma once
// Frame-to-frame presence watch: which geometry keys were being submitted last frame and are not this frame.
// A key that leaves while the camera is still is a fault, not a viewpoint change, and a set of them leaving on the
// same frame is a mechanism. Bounded: the watch keeps only the key set and one capped list of names per step.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace dropout_watch {

struct Step {
    std::vector<std::uint64_t> dropped;   // present last step, absent now (sorted)
    std::vector<std::uint64_t> appeared;  // absent last step, present now (sorted)
    std::size_t present = 0;
};

class Watch {
  public:
    // `now` must be sorted and unique. First step has nothing to compare against: it only records.
    Step step(const std::set<std::uint64_t>& now) {
        Step out;
        out.present = now.size();
        if (!primed_) {
            last_ = now;
            primed_ = true;
            return out;
        }
        std::set_difference(last_.begin(), last_.end(), now.begin(), now.end(), std::back_inserter(out.dropped));
        std::set_difference(now.begin(), now.end(), last_.begin(), last_.end(), std::back_inserter(out.appeared));
        last_ = now;
        return out;
    }

    bool primed() const { return primed_; }
    std::size_t size() const { return last_.size(); }

  private:
    std::set<std::uint64_t> last_;
    bool primed_ = false;
};

// A step worth a log line: enough keys moved at once that it cannot be per-object noise.
inline bool notable(const Step& s, std::size_t threshold = 8) {
    return s.dropped.size() >= threshold || s.appeared.size() >= threshold;
}

// How far the camera moved and turned between two camera arrays (position xyz, forward xyz, ...; nscn layout).
// A dropout with both near zero cannot be a change of viewpoint: it is a fault.
struct Motion {
    float moved = 0.f;       // world units
    float turned_deg = 0.f;  // angle between forward vectors
    bool valid = false;
};

inline Motion motion(const float before[14], const float after[14]) {
    Motion m;
    for (int i = 0; i < 6; ++i)
        if (!std::isfinite(before[i]) || !std::isfinite(after[i])) return m;
    const float dx = after[0] - before[0], dy = after[1] - before[1], dz = after[2] - before[2];
    m.moved = std::sqrt(dx * dx + dy * dy + dz * dz);
    const float la = std::sqrt(before[3] * before[3] + before[4] * before[4] + before[5] * before[5]);
    const float lb = std::sqrt(after[3] * after[3] + after[4] * after[4] + after[5] * after[5]);
    if (la < 1e-6f || lb < 1e-6f) return m;
    float c = (before[3] * after[3] + before[4] * after[4] + before[5] * after[5]) / (la * lb);
    c = std::fmax(-1.f, std::fmin(1.f, c));
    m.turned_deg = std::acos(c) * 57.29577951308232f;
    m.valid = true;
    return m;
}

// Largest screen fraction, as last measured, among the keys that dropped: how visible the loss should have been.
inline double max_fraction(const std::vector<std::uint64_t>& keys, const std::map<std::uint64_t, double>& last) {
    double best = 0.0;
    for (const auto k : keys) {
        const auto it = last.find(k);
        if (it != last.end() && it->second > best) best = it->second;
    }
    return best;
}

// Why a key that was submitted last frame is not submitted now. Every dropped key lands in exactly one bucket:
//   submit_other      the renderer got it but did not draw it (bad transform, draw failed)
//   capture[reason]   the game drew it this frame and the capture classified it (pass, prepass, deferred, ...)
//   churn_occurrence  same draw (same source key), new geometry key: the skinned occurrence numbering moved
//   churn_pointer     a new key arrived with the same index buffer and range: a vertex buffer, offset or layout moved
//   churn_shape       a new key arrived with the same range but another index buffer: the buffers were recreated
//   absent            nothing this frame refers to it: the game did not issue the draw (or the batch overflowed)
// A churned key is the same object under a new name: the runtime sees a new mesh, which must be built first.
// Every input a geometry key is hashed from, so a re-keyed draw can say exactly which one moved.
struct Key {
    std::uint64_t vb[4] = {}, ib = 0, layout = 0;
    unsigned stride[4] = {}, offset[4] = {};
    unsigned ib_format = 0, ib_offset = 0;
    int base_vertex = 0;
};

enum class Component : unsigned {
    Vb0Ptr, Vb1Ptr, Vb2Ptr, Vb3Ptr,
    Vb0Stride, Vb1Stride, Vb2Stride, Vb3Stride,
    Vb0Offset, Vb1Offset, Vb2Offset, Vb3Offset,
    IbPtr, IbOffset, IbFormat, LayoutPtr, BaseVertex, Count
};
inline const char* component_name(Component c) {
    static const char* names[] = {"vb0_ptr", "vb1_ptr", "vb2_ptr", "vb3_ptr", "vb0_stride", "vb1_stride",
                                  "vb2_stride", "vb3_stride", "vb0_offset", "vb1_offset", "vb2_offset",
                                  "vb3_offset", "ib_ptr", "ib_offset", "ib_format", "layout_ptr", "base_vertex"};
    return names[static_cast<unsigned>(c)];
}
inline std::uint32_t bit(Component c) { return 1u << static_cast<unsigned>(c); }
inline bool moved(std::uint32_t mask, Component c) { return (mask & bit(c)) != 0; }
inline unsigned component_count(std::uint32_t mask) { unsigned n = 0; for (; mask; mask &= mask - 1) ++n; return n; }
inline std::string component_names(std::uint32_t mask) {
    std::string out;
    for (unsigned i = 0; i < static_cast<unsigned>(Component::Count); ++i)
        if (mask & (1u << i)) out += std::string(out.empty() ? "" : " ") + component_name(static_cast<Component>(i));
    return out;
}

inline std::uint32_t key_diff(const Key& a, const Key& b) {
    std::uint32_t m = 0;
    const auto mark = [&](bool differs, Component c) { if (differs) m |= bit(c); };
    for (unsigned i = 0; i < 4; ++i) {
        mark(a.vb[i] != b.vb[i], static_cast<Component>(static_cast<unsigned>(Component::Vb0Ptr) + i));
        mark(a.stride[i] != b.stride[i], static_cast<Component>(static_cast<unsigned>(Component::Vb0Stride) + i));
        mark(a.offset[i] != b.offset[i], static_cast<Component>(static_cast<unsigned>(Component::Vb0Offset) + i));
    }
    mark(a.ib != b.ib, Component::IbPtr);
    mark(a.ib_offset != b.ib_offset, Component::IbOffset);
    mark(a.ib_format != b.ib_format, Component::IbFormat);
    mark(a.layout != b.layout, Component::LayoutPtr);
    mark(a.base_vertex != b.base_vertex, Component::BaseVertex);
    return m;
}

struct Ident {
    std::uint64_t source = 0, ib = 0;
    unsigned index_count = 0, start_index = 0;
    Key key;
    float position[3] = {};             // world translation of the instance
};
struct Seen {  // one capture event of this frame
    std::uint64_t geometry = 0, source = 0, ib = 0;
    unsigned index_count = 0, start_index = 0, reason = 0;
    Key key;
    float position[3] = {};
};
// churn_pointer breakdown: which key component moved (one re-key can move several; moved_other = none of these four,
// so another vertex slot, a stride or an IB offset). arrived_missing: churned arrivals whose mesh was not built yet,
// i.e. the frame the object is really gone from the image.
struct Why {
    unsigned submit_other = 0, churn_occurrence = 0, churn_pointer = 0, churn_shape = 0, absent = 0;
    unsigned moved_vb = 0, moved_offset = 0, moved_base = 0, moved_layout = 0, moved_other = 0;  // slot 0 summary
    std::uint32_t moved_mask = 0;      // union of key components that differed on any re-key
    unsigned component[static_cast<unsigned>(Component::Count)] = {};
    unsigned arrived_missing = 0;
    unsigned place_same = 0, place_near = 0, place_far = 0;  // churn_pointer arrival vs departure, world distance
    unsigned capture[32] = {};
};

inline Why attribute(const std::vector<std::uint64_t>& dropped, const std::vector<std::uint64_t>& appeared,
                     const std::map<std::uint64_t, Ident>& previous, const std::vector<Seen>& capture_now,
                     const std::map<std::uint64_t, unsigned>& submit_other_now,
                     const std::set<std::uint64_t>* missing_now = nullptr,
                     std::map<std::uint64_t, std::uint64_t>* carry = nullptr, bool assume_unbuilt = false) {
    Why why;
    // stand_in_ok: the arrival is provably the same object in the same place, so its predecessor's mesh may be drawn
    // for one frame instead of nothing. A neighbour sharing a buffer must never lend its geometry.
    const auto arrived = [&](std::uint64_t a, std::uint64_t from, bool stand_in_ok) {
        const bool unbuilt = assume_unbuilt || (missing_now && missing_now->count(a));
        if (missing_now && missing_now->count(a)) ++why.arrived_missing;
        if (carry && stand_in_ok && unbuilt) (*carry)[a] = from;   // the scene decides if it is still missing
    };
    std::map<std::uint64_t, const Seen*> by_geometry;
    for (const auto& e : capture_now)
        if (e.geometry) by_geometry.emplace(e.geometry, &e);
    std::set<std::uint64_t> arrivals(appeared.begin(), appeared.end());
    std::vector<std::uint64_t> unexplained;
    for (const auto k : dropped) {
        if (submit_other_now.count(k)) { ++why.submit_other; continue; }
        if (const auto it = by_geometry.find(k); it != by_geometry.end()) {
            ++why.capture[it->second->reason < 32 ? it->second->reason : 31];
            continue;
        }
        const auto p = previous.find(k);
        bool matched = false;
        if (p != previous.end() && p->second.source)
            for (const auto a : arrivals) {
                const auto s = by_geometry.find(a);
                if (s != by_geometry.end() && s->second->source == p->second.source) {
                    ++why.churn_occurrence;
                    arrived(a, k, true);  // same draw: the identity is exact, so a stand-in is allowed
                    arrivals.erase(a);
                    matched = true;
                    break;
                }
            }
        if (!matched) unexplained.push_back(k);
    }
    // Two passes so a loose match never takes an arrival that is another key's exact match.
    const auto match = [&](bool same_ib, unsigned& bucket) {
        std::vector<std::uint64_t> rest;
        for (const auto k : unexplained) {
            const auto p = previous.find(k);
            bool matched = false;
            bool same_place = false;   // set by the match below; shapes without geometry (churn_shape) stay false
            if (p != previous.end())
                for (const auto a : arrivals) {
                    const auto s = by_geometry.find(a);
                    if (s == by_geometry.end()) continue;
                    const Seen& e = *s->second;
                    if (e.index_count == p->second.index_count && e.start_index == p->second.start_index &&
                        (!same_ib || e.ib == p->second.ib)) {
                        ++bucket;
                        if (same_ib) {
                            const Ident& o = p->second;
                            const std::uint32_t m = key_diff(o.key, e.key);
                            why.moved_mask |= m;
                            for (unsigned c = 0; c < static_cast<unsigned>(Component::Count); ++c)
                                if (m & (1u << c)) ++why.component[c];
                            const bool v = moved(m, Component::Vb0Ptr), f = moved(m, Component::Vb0Offset),
                                       b = moved(m, Component::BaseVertex), l = moved(m, Component::LayoutPtr);
                            why.moved_vb += v; why.moved_offset += f; why.moved_base += b; why.moved_layout += l;
                            why.moved_other += !(v || f || b || l);
                            const float dx = e.position[0] - o.position[0], dy = e.position[1] - o.position[1],
                                        dz = e.position[2] - o.position[2];
                            const float d2 = dx * dx + dy * dy + dz * dz;
                            same_place = d2 < 1e-4f;
                            if (same_place) ++why.place_same; else if (d2 < 1.f) ++why.place_near; else ++why.place_far;
                        }
                        arrived(a, k, same_place); arrivals.erase(a); matched = true; break;
                    }
                }
            if (!matched) rest.push_back(k);
        }
        unexplained.swap(rest);
    };
    match(true, why.churn_pointer);
    match(false, why.churn_shape);
    why.absent = static_cast<unsigned>(unexplained.size());
    return why;
}

}  // namespace dropout_watch
