#pragma once
#include "render_settings.h"

namespace render_menu {
using render_settings::Mode;
enum class SessionMode { Native, Custom75, NotApplied };
enum class Notice { None, Unsaved, RestartRequired, SaveFailed, ConfigInvalid, ConfigUnreadable, RecoveryRequired };
enum class FileState { Valid, Missing, Invalid, Unreadable };
enum class SaveOutcome { Committed, NotSaved, RecoveryRequired };

// Construct on the UI thread after startup completes, using the validated settings snapshot.
struct State {
    const SessionMode active;
    const bool custom75_available;
    Mode saved;
    Mode edited;
    FileState file = FileState::Valid;
    bool open = false;
    bool save_error = false;
    bool saved_this_session = false;
    bool recovery_required = false;

    State(SessionMode applied, Mode persisted, bool available)
        : active(applied), custom75_available(available), saved(persisted), edited(persisted) {}

    State(SessionMode applied, FileState observed_file, Mode next_launch, bool available)
        : active(applied), custom75_available(available), saved(next_launch), edited(next_launch),
          file(observed_file) {}
};

inline bool can_discard(const State& s) { return s.edited != s.saved; }
inline bool can_save(const State& s) {
    return !s.recovery_required && s.file != FileState::Unreadable &&
        (s.edited == Mode::Native || (s.edited == Mode::Custom75 && s.custom75_available)) &&
        (s.edited != s.saved || s.file == FileState::Invalid);
}
inline bool select(State& s, Mode mode) {
    if (mode != Mode::Native && (mode != Mode::Custom75 || !s.custom75_available)) return false;
    s.edited = mode;
    s.save_error = false;
    return true;
}
// shortcut: synchronous saves only; capture the submitted preset before adding an async writer.
inline void complete_save(State& s, SaveOutcome outcome, FileState observed, Mode observed_next_launch) {
    if (!can_save(s)) return;
    s.saved = observed_next_launch;
    s.file = observed;
    s.save_error = outcome == SaveOutcome::NotSaved;
    s.recovery_required = s.recovery_required || outcome == SaveOutcome::RecoveryRequired;
    s.saved_this_session = s.saved_this_session || outcome == SaveOutcome::Committed;
}
inline void complete_save(State& s, bool success) {
    if (success) complete_save(s, SaveOutcome::Committed, FileState::Valid, s.edited);
    else complete_save(s, SaveOutcome::NotSaved, s.file, s.saved);
}
inline void discard(State& s) { s.edited = s.saved; s.save_error = false; }
inline void close(State& s) { s.open = false; }
inline void toggle(State& s) { s.open = !s.open; }
inline Notice notice(const State& s) {
    if (s.recovery_required) return Notice::RecoveryRequired;
    if (s.file == FileState::Unreadable) return Notice::ConfigUnreadable;  // the reason Save is off
    if (s.save_error) return Notice::SaveFailed;
    if (can_discard(s)) return Notice::Unsaved;
    if (s.file == FileState::Invalid) return Notice::ConfigInvalid;
    if (s.saved_this_session &&
        (s.active == SessionMode::NotApplied ||
         (s.active == SessionMode::Native && s.saved != Mode::Native) ||
         (s.active == SessionMode::Custom75 && s.saved != Mode::Custom75)))
        return Notice::RestartRequired;
    return Notice::None;
}
} // namespace render_menu
