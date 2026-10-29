#pragma once
#include "menu_state.h"
#include "startup_status.h"
#include <cstdio>

namespace menu_session {

struct Session {
    render_menu::SessionMode mode;
    bool custom75_available;
    char reason[160];
};

inline Session from_status(const startup_status::Snapshot& s) {
    using render_menu::SessionMode;
    using startup_status::Failure;
    using startup_status::Outcome;
    Session r{SessionMode::NotApplied, false, {}};
    const int code = static_cast<int>(s.detail);
    switch (s.outcome) {
        case Outcome::NativeBypass:
            r.mode = SessionMode::Native;
            r.custom75_available = true;
            return r;
        case Outcome::Custom75Applied:
            r.mode = SessionMode::Custom75;
            r.custom75_available = true;
            return r;
        case Outcome::Remix50Applied:
            r.mode = SessionMode::Remix50;
            r.custom75_available = true;
            return r;
        case Outcome::Incomplete:
            std::snprintf(r.reason, sizeof r.reason,
                          "Partially applied: renderer scaled without upscale gate. Use Native and restart.");
            return r;
        case Outcome::NotStarted:
            if (s.failure == Failure::ThreadCreation) {
                r.custom75_available = true;
                std::snprintf(r.reason, sizeof r.reason, "Startup thread could not start (error %d).", code);
            } else {
                std::snprintf(r.reason, sizeof r.reason, "Unknown startup status (code %d).", code);
            }
            return r;
        case Outcome::NotApplied:
            switch (s.failure) {
                case Failure::Depth:
                    std::snprintf(r.reason, sizeof r.reason, "Depth patch failed (code %d); scaling skipped.", code);
                    return r;
                case Failure::Proxy:
                    std::snprintf(r.reason, sizeof r.reason,
                                  "Upscale bridge patch failed (code %d); scaling skipped.", code);
                    return r;
                case Failure::Renderer:
                    std::snprintf(r.reason, sizeof r.reason,
                                  "Renderer scale not applied (code %d); scaling skipped.", code);
                    return r;
                default:
                    break;
            }
            [[fallthrough]];
        default:
            std::snprintf(r.reason, sizeof r.reason, "Unknown startup status (code %d).", code);
    }
    return r;
}

} // namespace menu_session
