#pragma once
// Build-budget policy for a mesh-creation backlog.
//
// live-churn, 2026-11-01: while a new area streamed in, 16,129 of 31,925 instances (50.5%) reached the renderer
// before their mesh existed, and the 4 ms build budget deferred 2,915 builds in the same window. Holes in the image
// cost more than one slow frame, so the budget rises while the share of unbuilt instances is high, and is bounded
// by kMaxBudget so a long backlog cannot stall the game indefinitely.

namespace backlog_policy {

constexpr unsigned long long kBoosted = 20000;    // microseconds of mesh building allowed during a backlog
constexpr unsigned long long kMaxBudget = 20000;  // ceiling: never raise above this, whatever is configured
constexpr double kMissingShare = 0.10;            // unbuilt instances / submitted instances that counts as a backlog

// configured: NIER_REMIX_LIVE_BUILD_BUDGET_US (0 = off). instances/missing: last submitted frame.
inline unsigned long long budget(unsigned long long configured, unsigned long long instances,
                                 unsigned long long missing) {
    if (!configured || !instances) return configured;
    if (static_cast<double>(missing) / static_cast<double>(instances) < kMissingShare) return configured;
    const unsigned long long boosted = configured * 5ull;  // a spike is worth several frames of building
    return boosted > kMaxBudget ? kMaxBudget : boosted;
}

}  // namespace backlog_policy
