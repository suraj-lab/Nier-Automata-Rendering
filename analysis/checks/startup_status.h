#pragma once
#include "render_settings.h"
#include <atomic>
#include <cstdint>

namespace startup_status {
enum class Outcome : std::uint8_t { NativeBypass, Custom75Applied, NotApplied, Incomplete, NotStarted, Remix50Applied };
enum class Failure : std::uint8_t { None, InvalidConfig, Depth, Proxy, Renderer, MissingGate, ThreadCreation };

// No backend/GPU/dimensions: those require direct frame/resource observations, not boot values.
struct Snapshot {
    bool settings_observed = false;
    render_settings::Settings settings{render_settings::Mode::Native, false, false};
    Outcome outcome = Outcome::NotStarted;
    Failure failure = Failure::ThreadCreation;
    std::int32_t detail = 0;
};

// One immutable terminal result per DLL lifetime; no pointers or allocations cross threads.
class Publication {
    std::atomic<unsigned> state_{0}; // 0 empty, 1 writer owns the slot, 2 published
    Snapshot snapshot_{};
public:
    bool publish(const Snapshot& snapshot) noexcept {
        unsigned empty = 0;
        if (!state_.compare_exchange_strong(empty, 1, std::memory_order_relaxed)) return false;
        snapshot_ = snapshot;
        state_.store(2, std::memory_order_release);
        return true;
    }
    bool read(Snapshot& snapshot) const noexcept {
        if (state_.load(std::memory_order_acquire) != 2) return false;
        snapshot = snapshot_;
        return true;
    }
};
} // namespace startup_status
