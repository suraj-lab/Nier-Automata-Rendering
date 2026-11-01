#pragma once
// Scripted camera input for pop-in experiments: NIER_REMIX_LIVE_DRIVE="still:30,turn:8:40,still:20,walk:8,still:20".
// Each phase is kind:seconds[:mouse counts per poll]. walk/back push the left stick forward/back (camera-relative). Turning and walking happen in separate phases so the fit of
// missing meshes against turn rate, movement and build budget has independent columns (live-churn: turn and move
// correlated 0.73 when a person drove the camera). The clock starts at the first live frame; after the last phase
// nothing is injected. Injection lives in input_capture.h (DirectInput hook); the frame log reports the phase.
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <string>
#include <vector>

namespace input_drive {

enum class Kind { Still, Turn, Walk, Back };
struct Phase { Kind kind; double seconds; long dx; };
struct Now { int phase = -1; long dx = 0; int walk = 0; };  // walk: +1 forward, -1 back; phase -1: not driving

// Empty on any malformed entry: a half-parsed script would label the data with the wrong phases.
inline std::vector<Phase> parse(const std::string& text) {
    std::vector<Phase> out;
    std::size_t at = 0;
    while (at < text.size()) {
        std::size_t end = text.find(',', at);
        if (end == std::string::npos) end = text.size();
        const std::string item = text.substr(at, end - at);
        at = end + 1;
        const std::size_t c1 = item.find(':');
        if (c1 == std::string::npos) return {};
        const std::string kind = item.substr(0, c1);
        const std::size_t c2 = item.find(':', c1 + 1);
        const std::string secs = item.substr(c1 + 1, c2 == std::string::npos ? std::string::npos : c2 - c1 - 1);
        char* stop = nullptr;
        const double seconds = std::strtod(secs.c_str(), &stop);
        if (secs.empty() || *stop || !(seconds > 0)) return {};
        Phase p{Kind::Still, seconds, 0};
        if (kind == "turn") {
            if (c2 == std::string::npos) return {};
            const std::string dx = item.substr(c2 + 1);
            const long v = std::strtol(dx.c_str(), &stop, 10);
            if (dx.empty() || *stop || !v) return {};
            p = {Kind::Turn, seconds, v};
        } else if (kind == "walk" || kind == "back" || kind == "still") {
            if (c2 != std::string::npos) return {};
            p.kind = kind == "walk" ? Kind::Walk : kind == "back" ? Kind::Back : Kind::Still;
        } else {
            return {};
        }
        out.push_back(p);
    }
    return out;
}

inline Now at(const std::vector<Phase>& script, double t) {
    if (t < 0) return {};
    for (std::size_t i = 0; i < script.size(); ++i) {
        if (t < script[i].seconds)
            return {static_cast<int>(i), script[i].kind == Kind::Turn ? script[i].dx : 0,
                    script[i].kind == Kind::Walk ? 1 : script[i].kind == Kind::Back ? -1 : 0};
        t -= script[i].seconds;
    }
    return {};
}

inline unsigned long long now_us() {
    return static_cast<unsigned long long>(std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}

inline std::vector<Phase> script;                    // written once, before start_us is set
inline std::atomic<unsigned long long> start_us{0};  // 0 = not started
// Which DirectInput calls the game makes, and how many were changed: if turning never moves the camera, these say why.
inline std::atomic<unsigned long long> mouse_state{0}, mouse_data{0}, key_state{0}, key_data{0}, injected{0};
// XInputGetState calls for pad 0, and how many reported the scripted walk (NieR reads the keyboard elsewhere).
inline std::atomic<unsigned long long> pad_calls{0}, pad_walk{0};

inline Now current() {
    const unsigned long long s = start_us.load(std::memory_order_acquire);
    return s ? at(script, static_cast<double>(now_us() - s) / 1e6) : Now{};
}

}  // namespace input_drive
