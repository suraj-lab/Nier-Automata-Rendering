// FROZEN gate for menu_session.h. Do not edit to make a candidate pass.
// Contract (pure C++17 header, namespace menu_session, includes only menu_state.h/startup_status.h/<cstdio>):
//   struct Session { render_menu::SessionMode mode; bool custom75_available; char reason[160]; };
//   inline Session from_status(const startup_status::Snapshot&);
// reason is always NUL-terminated; empty ("") exactly when mode is Native or Custom75.
// %d below is Snapshot::detail (std::int32_t, printed as int).
//   NativeBypass (any failure)        -> Native,   available true,  ""
//   Custom75Applied (any failure)     -> Custom75, available true,  ""
//   NotApplied + Depth                -> NotApplied, false, "Depth patch failed (code %d); scaling skipped."
//   NotApplied + Proxy                -> NotApplied, false, "Upscale bridge patch failed (code %d); scaling skipped."
//   NotApplied + Renderer             -> NotApplied, false, "Renderer scale not applied (code %d); scaling skipped."
//   Incomplete (any failure)          -> NotApplied, false,
//        "Partially applied: renderer scaled without upscale gate. Use Native and restart."
//   NotStarted + ThreadCreation       -> NotApplied, true,  "Startup thread could not start (error %d)."
//   anything else (other combinations or out-of-range enum values)
//                                     -> NotApplied, false, "Unknown startup status (code %d)."
// Custom75 stays available after Native bypass or a thread-start failure (setup was never attempted);
// it is unavailable after this build's patches failed, because the next launch would fail the same way.
#include "menu_session.h"
#include <cassert>
#include <climits>
#include <cstdio>
#include <cstring>
#include <type_traits>

using render_menu::SessionMode;
using startup_status::Failure;
using startup_status::Outcome;
using startup_status::Snapshot;

static_assert(std::is_same_v<decltype(menu_session::Session::reason), char[160]>);
static unsigned checks = 0;

static void expect(Outcome o, Failure f, std::int32_t detail, SessionMode mode, bool available, const char* reason) {
    Snapshot s;
    s.settings_observed = true;
    s.outcome = o;
    s.failure = f;
    s.detail = detail;
    const menu_session::Session got = menu_session::from_status(s);
    assert(got.mode == mode);
    assert(got.custom75_available == available);
    assert(std::memchr(got.reason, 0, sizeof got.reason));
    if (std::strcmp(got.reason, reason)) {
        std::fprintf(stderr, "reason mismatch\n got: %s\nwant: %s\n", got.reason, reason);
        assert(false);
    }
    assert((*got.reason == 0) == (mode != SessionMode::NotApplied));
    ++checks;
}

int main() {
    const Failure all[] = {Failure::None, Failure::InvalidConfig, Failure::Depth, Failure::Proxy,
                           Failure::Renderer, Failure::MissingGate, Failure::ThreadCreation};
    char want[160];
    for (std::int32_t d : {0, 7, -1, INT_MIN, INT_MAX}) {
        for (Failure f : all) {
            expect(Outcome::NativeBypass, f, d, SessionMode::Native, true, "");
            expect(Outcome::Custom75Applied, f, d, SessionMode::Custom75, true, "");
            expect(Outcome::Incomplete, f, d, SessionMode::NotApplied, false,
                   "Partially applied: renderer scaled without upscale gate. Use Native and restart.");
        }
        std::snprintf(want, sizeof want, "Depth patch failed (code %d); scaling skipped.", static_cast<int>(d));
        expect(Outcome::NotApplied, Failure::Depth, d, SessionMode::NotApplied, false, want);
        std::snprintf(want, sizeof want, "Upscale bridge patch failed (code %d); scaling skipped.", static_cast<int>(d));
        expect(Outcome::NotApplied, Failure::Proxy, d, SessionMode::NotApplied, false, want);
        std::snprintf(want, sizeof want, "Renderer scale not applied (code %d); scaling skipped.", static_cast<int>(d));
        expect(Outcome::NotApplied, Failure::Renderer, d, SessionMode::NotApplied, false, want);
        std::snprintf(want, sizeof want, "Startup thread could not start (error %d).", static_cast<int>(d));
        expect(Outcome::NotStarted, Failure::ThreadCreation, d, SessionMode::NotApplied, true, want);
        std::snprintf(want, sizeof want, "Unknown startup status (code %d).", static_cast<int>(d));
        for (Failure f : {Failure::None, Failure::InvalidConfig, Failure::MissingGate, Failure::ThreadCreation,
                          static_cast<Failure>(200)})
            expect(Outcome::NotApplied, f, d, SessionMode::NotApplied, false, want);
        for (Failure f : {Failure::None, Failure::InvalidConfig, Failure::Depth, Failure::Proxy, Failure::Renderer,
                          Failure::MissingGate, static_cast<Failure>(200)})
            expect(Outcome::NotStarted, f, d, SessionMode::NotApplied, false, want);
        for (Failure f : all)
            expect(static_cast<Outcome>(200), f, d, SessionMode::NotApplied, false, want);
    }
    // Default snapshot is what a reader sees if the producer never wrote one: thread-start failure.
    const auto unset = menu_session::from_status(Snapshot{});
    assert(unset.mode == SessionMode::NotApplied && unset.custom75_available);
    assert(!std::strcmp(unset.reason, "Startup thread could not start (error 0)."));
    std::printf("{\"passed\":true,\"checks\":%u}\n", checks + 1);
}
