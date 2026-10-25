// FROZEN gate for menu file-state/save-outcome support. Do not edit to make a candidate pass.
// Contract (additive to menu_state.h; existing API and menu_state_test.cpp must keep passing):
//   enum class FileState { Valid, Missing, Invalid, Unreadable };
//   enum class SaveOutcome { Committed, NotSaved, RecoveryRequired };
//   Notice gains ConfigInvalid, ConfigUnreadable, RecoveryRequired (appended after SaveFailed).
//   State gains `FileState file` (Valid via the old constructor) and `bool recovery_required` (false),
//   and a constructor State(SessionMode, FileState, Mode next_launch, bool custom75_available).
//   `saved` = the preset the next launch will use (Missing->Custom75 default, Invalid/Unreadable->Native).
//   can_save: !recovery_required && file != Unreadable && edited selectable && (dirty || file == Invalid).
//   complete_save(State&, SaveOutcome, FileState observed, Mode observed_next_launch):
//     no-op unless can_save; else saved/file := observation (caller re-reads the file after EVERY attempt),
//     save_error := outcome == NotSaved, recovery_required |= outcome == RecoveryRequired,
//     saved_this_session |= outcome == Committed. edited and open are never changed.
//   Old complete_save(State&, bool) == complete_save(s, Committed, Valid, edited) / (s, NotSaved, file, saved).
//   notice priority: RecoveryRequired, ConfigUnreadable, SaveFailed, Unsaved, ConfigInvalid, RestartRequired, None.
//   (Unreadable outranks Unsaved/SaveFailed: it is the reason Save is disabled. Review aeda98e0.)
#include "menu_state.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
#include <type_traits>

using render_settings::Mode;
using render_menu::FileState;
using render_menu::Notice;
using render_menu::SaveOutcome;
using render_menu::SessionMode;
using render_menu::State;

static_assert(std::is_const_v<decltype(State::active)>);
static_assert(std::is_const_v<decltype(State::custom75_available)>);
static_assert(std::is_same_v<decltype(State::file), FileState>);
static_assert(std::is_same_v<decltype(State::recovery_required), bool>);
static_assert(static_cast<int>(Notice::None) == 0 && static_cast<int>(Notice::Unsaved) == 1 &&
              static_cast<int>(Notice::RestartRequired) == 2 && static_cast<int>(Notice::SaveFailed) == 3);

static unsigned long long checks = 0;

static bool selectable(const State& s, Mode m) {
    return m == Mode::Native || (m == Mode::Custom75 && s.custom75_available);
}

static void check(const State& s) {
    const bool dirty = s.edited != s.saved;
    assert(render_menu::can_discard(s) == dirty);
    const bool save = !s.recovery_required && s.file != FileState::Unreadable && selectable(s, s.edited) &&
                      (dirty || s.file == FileState::Invalid);
    assert(render_menu::can_save(s) == save);
    const bool restart = s.saved_this_session &&
        (s.active == SessionMode::NotApplied ||
         (s.active == SessionMode::Native && s.saved != Mode::Native) ||
         (s.active == SessionMode::Custom75 && s.saved != Mode::Custom75));
    const Notice expected = s.recovery_required ? Notice::RecoveryRequired
        : s.file == FileState::Unreadable ? Notice::ConfigUnreadable
        : s.save_error ? Notice::SaveFailed
        : dirty ? Notice::Unsaved
        : s.file == FileState::Invalid ? Notice::ConfigInvalid
        : restart ? Notice::RestartRequired : Notice::None;
    assert(render_menu::notice(s) == expected);
    ++checks;
}

static Mode next_launch(FileState f, Mode valid_mode) {
    return f == FileState::Valid ? valid_mode : f == FileState::Missing ? Mode::Custom75 : Mode::Native;
}

int main() {
    {   // Old constructor means a valid file; new fields default safely.
        State s{SessionMode::Custom75, Mode::Custom75, true};
        assert(s.file == FileState::Valid && !s.recovery_required);
        check(s);
    }
    {   // Invalid preset: repair is offered even though the edit equals the Native fallback.
        State s{SessionMode::Native, FileState::Invalid, Mode::Native, true};
        assert(s.saved == Mode::Native && s.edited == Mode::Native && !s.open);
        assert(render_menu::can_save(s) && !render_menu::can_discard(s));
        assert(render_menu::notice(s) == Notice::ConfigInvalid);
        render_menu::complete_save(s, SaveOutcome::Committed, FileState::Valid, Mode::Native);
        assert(s.file == FileState::Valid && s.saved == Mode::Native && s.saved_this_session && !s.save_error);
        assert(!render_menu::can_save(s) && render_menu::notice(s) == Notice::None);
        check(s);
    }
    {   // Unreadable file: never written, whatever is selected.
        State s{SessionMode::Native, FileState::Unreadable, Mode::Native, true};
        assert(!render_menu::can_save(s) && render_menu::notice(s) == Notice::ConfigUnreadable);
        assert(render_menu::select(s, Mode::Custom75));
        assert(!render_menu::can_save(s) && render_menu::notice(s) == Notice::ConfigUnreadable);
        render_menu::complete_save(s, SaveOutcome::Committed, FileState::Valid, Mode::Custom75);
        assert(s.saved == Mode::Native && s.file == FileState::Unreadable && !s.saved_this_session);
        render_menu::complete_save(s, true);  // old API is gated the same way
        assert(s.saved == Mode::Native && !s.saved_this_session);
        check(s);
    }
    {   // Missing file: next launch is the Custom75 default; re-saving that default is not offered.
        State s{SessionMode::Custom75, FileState::Missing, Mode::Custom75, true};
        assert(!render_menu::can_save(s) && render_menu::notice(s) == Notice::None);
        assert(render_menu::select(s, Mode::Native) && render_menu::can_save(s));
        render_menu::complete_save(s, SaveOutcome::NotSaved, FileState::Missing, Mode::Custom75);
        assert(s.save_error && s.edited == Mode::Native && s.saved == Mode::Custom75 && s.file == FileState::Missing);
        assert(render_menu::notice(s) == Notice::SaveFailed && render_menu::can_save(s));
        check(s);
    }
    {   // Stale snapshot: another program changed the file. Show the re-read value, not the old cache.
        State s{SessionMode::Custom75, FileState::Valid, Mode::Custom75, true};
        assert(render_menu::select(s, Mode::Native));
        render_menu::complete_save(s, SaveOutcome::NotSaved, FileState::Invalid, Mode::Native);
        assert(s.save_error && s.file == FileState::Invalid && s.saved == Mode::Native && s.edited == Mode::Native);
        assert(!s.saved_this_session && render_menu::notice(s) == Notice::SaveFailed);
        assert(render_menu::can_save(s));  // invalid file is repairable
        assert(render_menu::select(s, Mode::Native) && !s.save_error);
        assert(render_menu::notice(s) == Notice::ConfigInvalid);
        check(s);
    }
    {   // Recovery required is sticky for the session and blocks further saves.
        State s{SessionMode::Custom75, FileState::Valid, Mode::Custom75, true};
        render_menu::toggle(s);
        assert(render_menu::select(s, Mode::Native));
        render_menu::complete_save(s, SaveOutcome::RecoveryRequired, FileState::Missing, Mode::Custom75);
        assert(s.recovery_required && !s.save_error && !s.saved_this_session && s.open);
        assert(s.file == FileState::Missing && s.saved == Mode::Custom75 && s.edited == Mode::Native);
        assert(!render_menu::can_save(s) && render_menu::notice(s) == Notice::RecoveryRequired);
        render_menu::discard(s);
        assert(render_menu::select(s, Mode::Native));
        render_menu::complete_save(s, SaveOutcome::Committed, FileState::Valid, Mode::Native);
        render_menu::complete_save(s, true);
        assert(s.recovery_required && s.saved == Mode::Custom75 && !s.saved_this_session);
        assert(render_menu::notice(s) == Notice::RecoveryRequired);
        check(s);
    }
    {   // Committed save reflects the observation, then restart rule applies as before.
        State s{SessionMode::Custom75, FileState::Valid, Mode::Custom75, true};
        assert(render_menu::select(s, Mode::Native));
        render_menu::complete_save(s, SaveOutcome::Committed, FileState::Valid, Mode::Native);
        assert(s.saved == Mode::Native && s.saved_this_session && render_menu::notice(s) == Notice::RestartRequired);
        check(s);
    }

    // Exhaustive 4-event traces over every consistent starting state.
    struct Obs { SaveOutcome outcome; FileState file; Mode mode; };
    Obs obs[15]; unsigned n = 0;
    for (auto o : {SaveOutcome::Committed, SaveOutcome::NotSaved, SaveOutcome::RecoveryRequired})
        for (auto f : {FileState::Valid, FileState::Missing, FileState::Invalid, FileState::Unreadable})
            for (auto m : {Mode::Native, Mode::Custom75})
                if (next_launch(f, m) == m) obs[n++] = {o, f, m};  // only reads the reader can produce
    assert(n == 15);  // Valid x2 + Missing + Invalid + Unreadable, per outcome
    const unsigned events = 5 + n + 2;  // select N, select C, discard, toggle, close, observations, old true/false
    for (auto active : {SessionMode::Native, SessionMode::Custom75, SessionMode::NotApplied})
    for (auto file : {FileState::Valid, FileState::Missing, FileState::Invalid, FileState::Unreadable})
    for (auto valid_mode : {Mode::Native, Mode::Custom75}) {
        if (file != FileState::Valid && valid_mode == Mode::Custom75) continue;
        for (bool available : {false, true}) {
            unsigned long long total = 1;
            for (int i = 0; i < 4; ++i) total *= events;
            for (unsigned long long trace = 0; trace < total; ++trace) {
                State s{active, file, next_launch(file, valid_mode), available};
                check(s);
                unsigned long long rest = trace;
                for (int i = 0; i < 4; ++i) {
                    const State before = s;
                    const bool permitted = render_menu::can_save(s);
                    const unsigned e = static_cast<unsigned>(rest % events); rest /= events;
                    if (e == 0) render_menu::select(s, Mode::Native);
                    else if (e == 1) render_menu::select(s, Mode::Custom75);
                    else if (e == 2) render_menu::discard(s);
                    else if (e == 3) render_menu::toggle(s);
                    else if (e == 4) render_menu::close(s);
                    else if (e < 5 + n) render_menu::complete_save(s, obs[e-5].outcome, obs[e-5].file, obs[e-5].mode);
                    else render_menu::complete_save(s, e == 5 + n);
                    assert(s.active == active && s.custom75_available == available);
                    assert(!before.recovery_required || s.recovery_required);
                    const bool saving = e >= 5;
                    if (saving) assert(s.edited == before.edited && s.open == before.open);
                    if (!saving || !permitted) {
                        assert(s.saved == before.saved && s.file == before.file);
                        assert(s.recovery_required == before.recovery_required);
                        assert(s.saved_this_session == before.saved_this_session);
                        if (saving) assert(s.save_error == before.save_error);
                    }
                    if (saving && permitted) {
                        const bool legacy = e >= 5 + n;
                        const Obs o = legacy ? (e == 5 + n ? Obs{SaveOutcome::Committed, FileState::Valid, before.edited}
                                                           : Obs{SaveOutcome::NotSaved, before.file, before.saved})
                                             : obs[e-5];
                        assert(s.saved == o.mode && s.file == o.file);
                        assert(s.save_error == (o.outcome == SaveOutcome::NotSaved));
                        assert(s.recovery_required == (before.recovery_required || o.outcome == SaveOutcome::RecoveryRequired));
                        assert(s.saved_this_session == (before.saved_this_session || o.outcome == SaveOutcome::Committed));
                    }
                    if (e == 4) assert(!s.open);
                    check(s);
                }
            }
        }
    }
    std::printf("{\"passed\":true,\"checks\":%llu}\n", checks);
}
