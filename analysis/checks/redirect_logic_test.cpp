// Frozen test for redirect_logic.h (Part 3 decision logic, pure, no D3D).
// Contract: should_redirect() is called at every exit of the proxy's FUN_1800173c0 and returns true
// when PS SRV slot 0 must be rebound to the FSR Output for the draw that follows.
// Build: g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined
//        -fno-sanitize-recover=all redirect_logic_test.cpp -o redirect_logic_test
#include "redirect_logic.h"
#include <cassert>
#include <cstdio>

using redirect_logic::State;
using redirect_logic::should_redirect;

int main()
{
    int scene_a = 0, scene_b = 0, pre_aa_copy = 0, bloom_mip = 0, output = 0, output2 = 0;
    const void* A = &scene_a; const void* B = &scene_b; const void* C = &pre_aa_copy;
    const void* M = &bloom_mip; const void* O = &output; const void* O2 = &output2;

    // frame 10: draws before the dispatch (dispatch_frame still 9) never redirect, even the scene
    State s;
    assert(!should_redirect(s, true, 10, 9, A, O));      // pre-AA reader of the scene (#4686)
    assert(!s.have_scene);
    // the dispatching draw (bloom #4851): first exit with dispatch_frame == cur_frame -> capture + redirect
    assert(should_redirect(s, true, 10, 10, A, O));
    assert(s.have_scene && s.scene == A && s.scene_frame == 10);
    // later draws in the same frame: only the captured scene redirects
    assert(!should_redirect(s, true, 10, 10, M, O));     // bloom chain mip
    assert(!should_redirect(s, true, 10, 10, C, O));     // another texture at slot 0
    assert(should_redirect(s, true, 10, 10, A, O));      // tone-map #4871 reads the scene
    assert(s.scene == A);                                // not re-captured
    assert(!should_redirect(s, true, 10, 10, O, O));     // slot 0 already the Output
    assert(!should_redirect(s, true, 10, 10, nullptr, O)); // nothing bound

    // frame 11 before dispatch: stale capture must not redirect
    assert(!should_redirect(s, true, 11, 10, A, O));
    // frame 11 dispatch, scene texture re-created (resize): new capture
    assert(should_redirect(s, true, 11, 11, B, O2));
    assert(s.scene == B && s.scene_frame == 11);
    assert(!should_redirect(s, true, 11, 11, A, O2));    // old scene identity no longer matches

    // non-immediate context and missing Output never redirect and never capture
    State t;
    assert(!should_redirect(t, false, 5, 5, A, O));
    assert(!t.have_scene);
    assert(!should_redirect(t, true, 5, 5, A, nullptr));
    assert(!t.have_scene);
    assert(!should_redirect(t, true, 5, 5, nullptr, O));
    assert(!t.have_scene);
    assert(should_redirect(t, true, 5, 5, A, O));

    // frame counter wrap: equality is all that matters
    State w;
    assert(should_redirect(w, true, 0xffffffffu, 0xffffffffu, A, O));
    assert(!should_redirect(w, true, 0u, 0xffffffffu, A, O));
    assert(should_redirect(w, true, 0u, 0u, B, O));
    assert(w.scene == B && w.scene_frame == 0u);

    // a fresh State whose default scene_frame equals cur_frame must still capture first
    State z;
    assert(should_redirect(z, true, 0u, 0u, C, O));
    assert(z.scene == C);

    std::puts("redirect_logic_test: all passed");
    return 0;
}
