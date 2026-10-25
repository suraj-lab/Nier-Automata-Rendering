#pragma once
// Menu-facing settings I/O: what the panel shows about NIER_RENDER.ini, and one real save attempt
// followed by a fresh read (render_menu::complete_save requires that re-observation).
#include "menu_state.h"
#include "settings_save.h"

namespace menu_settings_io {
struct Observation {
    settings_save::Snapshot snapshot;  // pass back to save(): the file the user was shown
    render_menu::FileState file = render_menu::FileState::Unreadable;
    render_settings::Mode next_launch = render_settings::Mode::Native;  // what startup will use
};

inline Observation observe(const std::wstring& path, settings_save::Reader reader) {
    using render_menu::FileState;
    using settings_save::Presence;
    Observation o;
    // Snapshot and reader are two reads; if they disagree on existence the file changed between them.
    for (int attempt = 0; attempt < 2; ++attempt) {
        o.snapshot = settings_save::observe(path);
        const auto settings = reader(path);
        o.next_launch = settings.mode;
        if ((o.snapshot.presence == Presence::Missing) != settings.defaulted) continue;
        std::vector<unsigned char> probe;
        const bool editable = render_settings_file::rewrite(o.snapshot.bytes, render_settings::Mode::Native, probe) ==
                              render_settings_file::EditResult::Updated;
        if (o.snapshot.presence == Presence::Missing) o.file = FileState::Missing;
        // Present but not safely editable counts as unreadable: offering Save would fail every time.
        else if (o.snapshot.presence == Presence::Present && editable)
            o.file = settings.valid ? FileState::Valid : FileState::Invalid;
        else o.file = FileState::Unreadable;
        return o;
    }
    // Still changing under us: refuse to save. next_launch is the latest reader result, shown as such.
    o.file = FileState::Unreadable;
    return o;
}

struct Report {
    render_menu::SaveOutcome outcome;
    Observation after;
    settings_save::Result detail;
};

inline Report save(const std::wstring& path, const Observation& shown, render_settings::Mode mode,
                   settings_save::Reader reader, settings_save::Hook hook = nullptr, void* context = nullptr) {
    const auto result = settings_save::save(path, shown.snapshot, mode, reader, hook, context);
    const auto outcome = result.outcome == settings_save::Outcome::Committed ? render_menu::SaveOutcome::Committed
        : result.outcome == settings_save::Outcome::RecoveryRequired ? render_menu::SaveOutcome::RecoveryRequired
        : render_menu::SaveOutcome::NotSaved;
    return {outcome, observe(path, reader), result};
}
}  // namespace menu_settings_io
