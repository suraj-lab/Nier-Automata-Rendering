#include "menu_state.h"
#include <cassert>
#include <initializer_list>
#include <type_traits>

using render_settings::Mode;
using render_menu::SessionMode;
using render_menu::Notice;
using render_menu::State;

static_assert(std::is_const_v<decltype(State::active)>);
static_assert(std::is_const_v<decltype(State::custom75_available)>);

static void check(const State& s) {
    const bool dirty = s.edited != s.saved;
    assert(render_menu::can_discard(s) == dirty);
    assert(render_menu::can_save(s) ==
           (dirty && (s.edited == Mode::Native ||
                      (s.edited == Mode::Custom75 && s.custom75_available))));
    const Notice expected = s.save_error ? Notice::SaveFailed
        : dirty ? Notice::Unsaved
        : s.saved_this_session &&
          (s.active == SessionMode::NotApplied || s.active == SessionMode::Remix50 ||
           (s.active == SessionMode::Native && s.saved != Mode::Native) ||
           (s.active == SessionMode::Custom75 && s.saved != Mode::Custom75))
            ? Notice::RestartRequired : Notice::None;
    assert(render_menu::notice(s) == expected);
}

int main() {
    {
        State s{SessionMode::Custom75, Mode::Custom75, true};
        assert(s.saved == Mode::Custom75 && s.edited == Mode::Custom75);
        assert(!s.open && !s.save_error && !s.saved_this_session);
        check(s);
        render_menu::complete_save(s, false);
        assert(!s.save_error);
        render_menu::complete_save(s, true);
        assert(!s.saved_this_session);
        assert(!render_menu::select(s, static_cast<Mode>(99)));
        assert(s.edited == Mode::Custom75);
        assert(render_menu::select(s, Mode::Native));
        assert(s.active == SessionMode::Custom75 && s.saved == Mode::Custom75);
        assert(render_menu::notice(s) == Notice::Unsaved);
        render_menu::toggle(s);
        assert(s.open);
        render_menu::close(s);
        assert(!s.open && s.edited == Mode::Native);
        render_menu::toggle(s);
        assert(s.open && s.edited == Mode::Native);
        render_menu::complete_save(s, false);
        assert(s.save_error && !s.saved_this_session);
        assert(s.saved == Mode::Custom75 && s.edited == Mode::Native);
        assert(render_menu::notice(s) == Notice::SaveFailed);
        render_menu::complete_save(s, true);
        assert(!s.save_error && s.saved_this_session);
        assert(s.active == SessionMode::Custom75 && s.saved == Mode::Native);
        assert(s.edited == Mode::Native);
        assert(!render_menu::can_save(s));
        assert(render_menu::notice(s) == Notice::RestartRequired);
        render_menu::discard(s);
        assert(s.saved == Mode::Native && s.edited == Mode::Native);
        assert(render_menu::notice(s) == Notice::RestartRequired);
        assert(render_menu::select(s, Mode::Custom75));
        render_menu::complete_save(s, false);
        assert(render_menu::notice(s) == Notice::SaveFailed);
        render_menu::discard(s);
        assert(!s.save_error && s.edited == Mode::Native);
        assert(render_menu::notice(s) == Notice::RestartRequired);
        assert(render_menu::select(s, Mode::Custom75));
        render_menu::complete_save(s, true);
        assert(s.saved == Mode::Custom75 && s.active == SessionMode::Custom75);
        assert(render_menu::notice(s) == Notice::None);
        check(s);
    }
    {
        State s{SessionMode::NotApplied, Mode::Custom75, false};
        assert(render_menu::notice(s) == Notice::None);
        assert(!render_menu::select(s, Mode::Custom75));
        assert(s.saved == Mode::Custom75 && s.edited == Mode::Custom75);
        assert(render_menu::select(s, Mode::Native));
        render_menu::complete_save(s, false);
        assert(s.active == SessionMode::NotApplied && s.saved == Mode::Custom75);
        render_menu::complete_save(s, true);
        assert(s.active == SessionMode::NotApplied && s.saved == Mode::Native);
        assert(render_menu::notice(s) == Notice::RestartRequired);
        assert(!render_menu::select(s, Mode::Custom75));
        assert(s.edited == Mode::Native);
        check(s);
    }
    {
        State s{SessionMode::Native, Mode::Native, false};
        assert(!render_menu::select(s, Mode::Custom75));
        assert(s.edited == Mode::Native && !render_menu::can_save(s));
        State supported{SessionMode::Native, Mode::Native, true};
        assert(render_menu::select(supported, Mode::Custom75));
        render_menu::complete_save(supported, true);
        assert(supported.active == SessionMode::Native);
        assert(render_menu::notice(supported) == Notice::RestartRequired);
        check(s); check(supported);
    }
    // Exhaust all 7-event traces to catch error/restart priority and close/reopen drift.
    for (const auto active : {SessionMode::Native, SessionMode::Custom75, SessionMode::NotApplied, SessionMode::Remix50}) {
        for (const auto saved : {Mode::Native, Mode::Custom75}) {
            for (const bool available : {false, true}) {
                for (unsigned trace = 0; trace < 823543; ++trace) { // 7^7
                    State s{active, saved, available};
                    unsigned events = trace;
                    for (unsigned i = 0; i < 7; ++i) {
                        const Mode old_saved = s.saved;
                        const Mode old_edit = s.edited;
                        const bool permitted = render_menu::can_save(s);
                        const unsigned event = events % 7;
                        events /= 7;
                        switch (event) {
                        case 0: render_menu::select(s, Mode::Native); break;
                        case 1: render_menu::select(s, Mode::Custom75); break;
                        case 2: render_menu::complete_save(s, false); break;
                        case 3: render_menu::complete_save(s, true); break;
                        case 4: render_menu::discard(s); break;
                        case 5: render_menu::toggle(s); break;
                        case 6: render_menu::close(s); break;
                        }
                        assert(s.active == active && s.custom75_available == available);
                        if (event != 3 || !permitted) assert(s.saved == old_saved);
                        if (event == 3 && permitted) assert(s.saved == old_edit);
                        if (event == 2 || event == 3 || event == 5 || event == 6)
                            assert(s.edited == old_edit);
                        if (event == 6) assert(!s.open);
                        check(s);
                    }
                }
            }
        }
    }
}
