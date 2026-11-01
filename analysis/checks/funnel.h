#pragma once
// One accounting line per window: every draw the hook saw lands in exactly one bucket, and the instance side is counted
// the same way, so "24% of instances have no mesh" becomes "N draws were deferred_budget, M were read_pending, ...".
// Prior art: FO4-Remix `[SemCapture] pendingByGate` (semantic_capture.cpp:2215-2232, 2580) counts each non-submitted
// drawable by its last failed resolver step, with an `other` bucket so nothing is unaccounted for.
#include <atomic>
#include <cstddef>
#include <cstdio>
#include <cstdint>
#include "visibility_trace.h"

namespace funnel {

constexpr unsigned kReasons = static_cast<unsigned>(visibility_trace::Reason::Count);

struct Totals {
    unsigned long long reason[kReasons] = {};
    unsigned long long instance_drawn = 0, instance_missing = 0, instance_bad_transform = 0, instance_failed = 0;
    unsigned long long other = 0;  // draws counted that have no reason slot (never expected; makes the balance visible)
};

// Accumulated between reports; the worker exchanges them for zero so each line covers one window.
inline std::atomic<unsigned long long> reason_total[kReasons];
inline std::atomic<unsigned long long> instance_drawn{0}, instance_missing{0}, instance_bad_transform{0};
inline std::atomic<unsigned long long> instance_failed{0}, uncounted{0};

inline void count(visibility_trace::Reason r, unsigned long long n = 1) {
    const unsigned i = static_cast<unsigned>(r);
    if (i < kReasons) reason_total[i].fetch_add(n, std::memory_order_relaxed);
    else uncounted.fetch_add(n, std::memory_order_relaxed);
}

inline void count_instance(visibility_trace::Reason r, unsigned long long n = 1) {
    switch (r) {
        case visibility_trace::Reason::Drawn: instance_drawn.fetch_add(n, std::memory_order_relaxed); break;
        case visibility_trace::Reason::MeshMissing: instance_missing.fetch_add(n, std::memory_order_relaxed); break;
        case visibility_trace::Reason::BadTransform: instance_bad_transform.fetch_add(n, std::memory_order_relaxed); break;
        case visibility_trace::Reason::DrawFailed: instance_failed.fetch_add(n, std::memory_order_relaxed); break;
        default: uncounted.fetch_add(n, std::memory_order_relaxed); break;
    }
}

inline Totals take() {
    Totals t;
    for (unsigned i = 0; i < kReasons; ++i) t.reason[i] = reason_total[i].exchange(0, std::memory_order_relaxed);
    t.instance_drawn = instance_drawn.exchange(0, std::memory_order_relaxed);
    t.instance_missing = instance_missing.exchange(0, std::memory_order_relaxed);
    t.instance_bad_transform = instance_bad_transform.exchange(0, std::memory_order_relaxed);
    t.instance_failed = instance_failed.exchange(0, std::memory_order_relaxed);
    t.other = uncounted.exchange(0, std::memory_order_relaxed);
    return t;
}

inline unsigned long long draws(const Totals& t) {
    unsigned long long n = t.other;
    for (unsigned i = 0; i < kReasons; ++i) n += t.reason[i];
    return n;
}

inline unsigned long long instances(const Totals& t) {
    return t.instance_drawn + t.instance_missing + t.instance_bad_transform + t.instance_failed;
}

// "ok" when nothing fell outside a bucket; the instance side is balanced by construction, so only the draw side can
// lose one. A non-ok balance is a logging bug, and must be seen rather than assumed.
inline const char* balance(const Totals& t) { return t.other == 0 ? "ok" : "UNCOUNTED"; }

// Fills `out` (at least 1024 bytes) with the histogram in enum order, skipping zero buckets: a normal window prints
// ~8 names, but every bucket firing at once still fits, so the line is never silently truncated.
inline int format(char* out, std::size_t n, const Totals& t) {
    int used = std::snprintf(out, n, "draws=%llu", draws(t));
    for (unsigned i = 0; i < kReasons; ++i) {
        if (!t.reason[i] || used < 0 || static_cast<std::size_t>(used) >= n) continue;
        used += std::snprintf(out + used, n - static_cast<std::size_t>(used), " %s=%llu",
                              visibility_trace::reason_name(static_cast<visibility_trace::Reason>(i)), t.reason[i]);
    }
    if (used >= 0 && static_cast<std::size_t>(used) < n)
        used += std::snprintf(out + used, n - static_cast<std::size_t>(used),
                              " | instances=%llu drawn=%llu mesh_missing=%llu bad_transform=%llu draw_failed=%llu balance=%s",
                              instances(t), t.instance_drawn, t.instance_missing, t.instance_bad_transform,
                              t.instance_failed, balance(t));
    return used;
}

}  // namespace funnel
