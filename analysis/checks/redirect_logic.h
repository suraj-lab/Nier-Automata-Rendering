// Part 3 slot-0 redirect decision (pure C++, no D3D). Called at every exit of the proxy's
// dispatch function; returns true when PS SRV slot 0 must be rebound to the FSR Output for
// the draw that follows. Unit-tested natively by redirect_logic_test.cpp.
#pragma once
#include <cstdint>

namespace redirect_logic {

struct State { std::uint32_t scene_frame = 0; bool have_scene = false; const void* scene = nullptr; };

inline bool should_redirect(State& s, bool immediate, std::uint32_t cur_frame, std::uint32_t dispatch_frame,
                            const void* slot0_res, const void* output_res)
{
    if (!immediate || slot0_res == nullptr || output_res == nullptr || dispatch_frame != cur_frame)
        return false;
    if (slot0_res == output_res) return false;
    if (!s.have_scene || s.scene_frame != cur_frame) {
        s.scene = slot0_res;
        s.scene_frame = cur_frame;
        s.have_scene = true;
        return true;
    }
    return slot0_res == s.scene;
}

}  // namespace redirect_logic
