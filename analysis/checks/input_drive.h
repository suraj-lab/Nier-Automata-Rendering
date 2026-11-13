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
#include <utility>
#include <vector>

namespace input_drive {

enum class Kind { Still, Turn, Walk, Back, Press };
// XInput button bits, so the script names the button the game's own prompts name (A confirms in NieR's menus).
constexpr unsigned short kUp = 0x0001, kDown = 0x0002, kLeft = 0x0004, kRight = 0x0008, kStart = 0x0010,
                       kBack = 0x0020, kA = 0x1000, kB = 0x2000, kX = 0x4000, kY = 0x8000;
inline unsigned short button(const std::string& name) {
    const std::pair<const char*, unsigned short> names[] = {
        {"A", kA}, {"B", kB}, {"X", kX}, {"Y", kY}, {"UP", kUp}, {"DOWN", kDown}, {"LEFT", kLeft},
        {"RIGHT", kRight}, {"START", kStart}, {"BACK", kBack}};
    for (const auto& entry : names)
        if (name == entry.first) return entry.second;
    return 0;
}
struct Phase { Kind kind; double seconds; long dx; unsigned short buttons = 0; };
// walk: +1 forward, -1 back; buttons: XInput bits held for a `press` phase; phase -1: not driving
struct Now { int phase = -1; long dx = 0; int walk = 0; unsigned short buttons = 0; };

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
        const auto number = [](const std::string& text, double& out) {
            char* stop = nullptr;
            out = std::strtod(text.c_str(), &stop);
            return !text.empty() && stop && !*stop;
        };
        Phase p{Kind::Still, 0, 0, 0};
        if (kind == "turn") {
            // turn:<seconds>:<mouse counts per poll>
            if (c2 == std::string::npos) return {};
            const std::string secs = item.substr(c1 + 1, c2 - c1 - 1), dx = item.substr(c2 + 1);
            double seconds = 0;
            char* stop = nullptr;
            const long v = std::strtol(dx.c_str(), &stop, 10);
            if (!number(secs, seconds) || !(seconds > 0) || dx.empty() || *stop || !v) return {};
            p = {Kind::Turn, seconds, v};
        } else if (kind == "press") {
            // press:<BUTTON>:<seconds> — the button first, because its name is not a number
            if (c2 == std::string::npos) return {};
            const std::string name = item.substr(c1 + 1, c2 - c1 - 1), secs = item.substr(c2 + 1);
            const unsigned short b = button(name);
            double seconds = 0;
            if (!b || !number(secs, seconds) || !(seconds > 0)) return {};  // unknown button: refuse whole
            p = {Kind::Press, seconds, 0, b};
        } else if (kind == "walk" || kind == "back" || kind == "still" || kind == "wait") {
            // `wait` is `still` under the name a menu script reads better with: both drive nothing.
            if (c2 != std::string::npos) return {};
            double seconds = 0;
            if (!number(item.substr(c1 + 1), seconds) || !(seconds > 0)) return {};
            p = {kind == "walk" ? Kind::Walk : kind == "back" ? Kind::Back : Kind::Still, seconds, 0};
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
                    script[i].kind == Kind::Walk ? 1 : script[i].kind == Kind::Back ? -1 : 0,
                    script[i].kind == Kind::Press ? script[i].buttons : static_cast<unsigned short>(0)};
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
// XInputGetState calls for pad 0, how many reported the scripted walk, and how many carried a menu press.
inline std::atomic<unsigned long long> pad_calls{0}, pad_walk{0}, pad_buttons{0};
// NIER_REMIX_LIVE_MENU_DRIVE: the title screen and the save menu, from process start, because the world script above
// cannot run before there is a world. It stops the moment the world script starts (`menu_active`), so the two scripts
// can never press at the same time. The X11 route (xdotool) cannot work here: a headless gamescope has no X display for
// the game, and the DirectInput/XInput hooks in input_capture.h already carry every press the game's menus read.
inline std::vector<Phase> menu_script;
inline std::atomic<unsigned long long> menu_start_us{0};
inline std::atomic<bool> menu_active{false};

// Both scripts are read from the environment on the first input poll, not by the proxy's Remix initialiser, so they
// work in a plain run with Remix off (G1/G2/G4 run A). Whichever path polls input first pays for the parse, and a
// script's seconds count from that first poll.
inline void load_from_env() {
    static std::atomic<bool> loaded{false};
    bool expected = false;
    if (!loaded.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) return;
    const auto read = [](const char* name) {
        const char* value = std::getenv(name);
        return value ? std::string(value) : std::string();   // ASCII scripts only
    };
    if (const std::string drive = read("NIER_REMIX_LIVE_DRIVE"); !drive.empty()) script = parse(drive);
    const std::string menu = read("NIER_REMIX_LIVE_MENU_DRIVE");
    if (!menu.empty()) {
        menu_script = parse(menu);
        if (!menu_script.empty()) {
            menu_start_us.store(now_us(), std::memory_order_release);
            menu_active.store(true, std::memory_order_release);
        }
    }
}

inline Now current() {
    load_from_env();
    const unsigned long long s = start_us.load(std::memory_order_acquire);
    return s ? at(script, static_cast<double>(now_us() - s) / 1e6) : Now{};
}

inline Now menu_current() {
    load_from_env();
    if (!menu_active.load(std::memory_order_acquire)) return {};
    const unsigned long long s = menu_start_us.load(std::memory_order_acquire);
    return s ? at(menu_script, static_cast<double>(now_us() - s) / 1e6) : Now{};
}

}  // namespace input_drive
