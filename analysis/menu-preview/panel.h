#pragma once
#include "imgui.h"
#include "../checks/menu_state.h"
#include <filesystem>

namespace menu_preview {
enum FontRole { Title, ModeName, Headline, Control, Body, Secondary, Label, Mono, Dimensions, Badge, FontCount };
struct Fonts { ImFont* items[FontCount]{}; };
struct RuntimeInfo {
    const char* backend;
    const char* render_size;
    const char* display_size;
    const char* failure_reason;
};
struct Rect { ImVec2 min{}, max{}; };
struct Geometry {
    Rect panel, preset, save, discard;
    float body_scroll_max = 0;
};
// One save attempt plus a fresh read of the file afterwards (see render_menu::complete_save).
struct SaveReport {
    render_menu::SaveOutcome outcome;
    render_menu::FileState file;
    render_settings::Mode next_launch;
};
using SavePreset = SaveReport (*)(render_settings::Mode, void*);

// Caller owns one ImGui context/UI thread; font files are pinned preview assets.
Fonts load_fonts(const std::filesystem::path& directory, float scale);
void apply_style(float scale);
// Call before NewFrame so Escape sees the popup state before ImGui consumes the key.
void key_event(render_menu::State& state, ImGuiKey key);
void draw_panel(render_menu::State& state, const RuntimeInfo& runtime, const Fonts& fonts,
                float scale, SavePreset save, void* user, Geometry* geometry = nullptr);
} // namespace menu_preview
