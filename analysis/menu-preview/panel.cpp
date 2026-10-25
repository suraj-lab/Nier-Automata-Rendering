#include "panel.h"
#include "style_tokens.h"
#include "imgui_internal.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <vector>

namespace menu_preview {
namespace c = preview_style::colors;
namespace l = preview_style::layout;
using render_menu::SessionMode;
using render_settings::Mode;

static const char* mode_name(Mode m) { return m == Mode::Native ? "Native" : "Custom75"; }
static const char* known(const char* value) { return value && *value ? value : "—"; }
static void text(const Fonts& f, FontRole role, const char* value, ImU32 ink = c::text, bool wrap = false) {
    ImGui::PushFont(f.items[role]);
    ImGui::PushStyleColor(ImGuiCol_Text, ink);
    if (wrap) ImGui::PushTextWrapPos(0);
    ImGui::TextUnformatted(value);
    if (wrap) ImGui::PopTextWrapPos();
    ImGui::PopStyleColor();
    ImGui::PopFont();
}
static Rect last_item() { return {ImGui::GetItemRectMin(), ImGui::GetItemRectMax()}; }

Fonts load_fonts(const std::filesystem::path& dir, float scale) {
    if (!(scale == 1 || scale == 1.5f || scale == 2)) throw std::runtime_error("Unsupported preview scale");
    const char* faces[] = {"Sans-Bold", "Sans-Medium", "Sans-Medium", "Sans-Medium", "Sans-Regular",
                          "Sans-Regular", "Sans-SemiBold", "Mono-Regular", "Mono-Medium", "Sans-SemiBold"};
    const float sizes[] = {20, 28, 22, 16, 15, 14, 13, 13, 19, 12};
    static const ImWchar ranges[] = {0x20, 0xff, 0x2013, 0x2014, 0};
    Fonts fonts;
    for (int i = 0; i < FontCount; ++i) {
        std::ifstream file(dir / (std::string("IBMPlex") + faces[i] + ".ttf"), std::ios::binary | std::ios::ate);
        const auto size = file.tellg();
        if (!file || size <= 0 || size > 4 * 1024 * 1024) throw std::runtime_error("Missing/invalid pinned font");
        file.seekg(0);
        std::vector<char> data(static_cast<std::size_t>(size));
        if (!file.read(data.data(), size)) throw std::runtime_error("Cannot read pinned font");
        void* owned = IM_ALLOC(data.size());
        if (!owned) throw std::bad_alloc();
        std::memcpy(owned, data.data(), data.size());
        fonts.items[i] = ImGui::GetIO().Fonts->AddFontFromMemoryTTF(owned, static_cast<int>(data.size()), sizes[i]*scale, nullptr, ranges);
        if (!fonts.items[i]) throw std::runtime_error("Cannot load pinned font");
    }
    ImGui::GetIO().FontDefault = fonts.items[Body];
    if (!ImGui::GetIO().Fonts->Build()) throw std::runtime_error("Cannot build font atlas");
    return fonts;
}

void apply_style(float scale) {
    ImGuiStyle base;
    ImGui::StyleColorsLight(&base);
    auto color = [](ImU32 v) { return ImGui::ColorConvertU32ToFloat4(v); };
    base.WindowPadding = ImVec2(24, 20);
    base.FramePadding = ImVec2(12, 14);
    base.ItemSpacing = ImVec2(10, 10);
    base.WindowRounding = base.FrameRounding = base.PopupRounding = 2;
    base.WindowBorderSize = base.FrameBorderSize = 1;
    base.ScrollbarSize = 12;
    base.Colors[ImGuiCol_WindowBg] = base.Colors[ImGuiCol_ChildBg] = color(c::surface);
    base.Colors[ImGuiCol_PopupBg] = color(c::field);
    base.Colors[ImGuiCol_Text] = color(c::text);
    base.Colors[ImGuiCol_TextDisabled] = color(c::disabled_text);
    base.Colors[ImGuiCol_Border] = color(c::panel_border);
    base.Colors[ImGuiCol_Separator] = color(c::rule);
    base.Colors[ImGuiCol_FrameBg] = color(c::field);
    base.Colors[ImGuiCol_FrameBgHovered] = color(c::neutral);
    base.Colors[ImGuiCol_Button] = color(c::primary);
    base.Colors[ImGuiCol_ButtonHovered] = base.Colors[ImGuiCol_ButtonActive] = color(c::primary_hover);
    base.Colors[ImGuiCol_Header] = base.Colors[ImGuiCol_HeaderHovered] = color(c::neutral);
    base.Colors[ImGuiCol_NavCursor] = color(c::text);
    base.ScaleAllSizes(scale); // Always a pristine baseline, never the previous scaled style.
    ImGui::GetStyle() = base;
}

void key_event(render_menu::State& state, ImGuiKey key) {
    const bool popup = ImGui::IsPopupOpen(nullptr, ImGuiPopupFlags_AnyPopupId | ImGuiPopupFlags_AnyPopupLevel);
    if (key == ImGuiKey_Insert) {
        if (state.open) {
            // shortcut: pinned ImGui internal API; revisit on upgrade or shared popup ownership.
            ImGui::ClosePopupsOverWindow(nullptr, false);
        }
        render_menu::toggle(state);
    } else if (key == ImGuiKey_Escape && !popup) {
        render_menu::close(state);
    }
}

void draw_panel(render_menu::State& state, const RuntimeInfo& rt, const Fonts& fonts,
                float s, SavePreset save, void* user, Geometry* geometry) {
    Geometry observed;
    if (geometry) *geometry = observed;
    if (!state.open) return;
    const bool failed = state.active == SessionMode::NotApplied;
    const Mode active = state.active == SessionMode::Custom75 ? Mode::Custom75 : Mode::Native;
    const auto notice = render_menu::notice(state);
    char line[240] = "No unsaved changes.", sub[320] = "";
    ImU32 strip = c::neutral, ink = c::text;
    using render_menu::FileState;
    using render_menu::Notice;
    if (notice == Notice::RecoveryRequired) {
        std::snprintf(line, sizeof(line), "Save interrupted: settings file needs recovery.");
        std::snprintf(sub, sizeof(sub), "Recovery copies were kept beside NIER_RENDER.ini. Next launch uses %s. Saving is off until restart.",
                      mode_name(state.saved));
        strip = c::error_bg; ink = c::error_text;
    } else if (notice == Notice::ConfigUnreadable) {
        std::snprintf(line, sizeof(line), "Settings file can't be read or safely edited. Saving is off.");
        std::snprintf(sub, sizeof(sub), "Last read: next launch uses %s. Fix or remove NIER_RENDER.ini, then restart.",
                      mode_name(state.saved));
        strip = c::error_bg; ink = c::error_text;
    } else if (notice == Notice::ConfigInvalid) {
        std::snprintf(line, sizeof(line), "Settings file has an invalid preset.");
        std::snprintf(sub, sizeof(sub), "Next launch uses %s. Save to repair the file.", mode_name(state.saved));
        strip = c::pending_bg; ink = c::pending_text;
    } else if (notice == Notice::Unsaved) {
        std::snprintf(line, sizeof(line), "Unsaved. %s", failed ? "This session stays as it started." :
            active == Mode::Native ? "This session stays on Native." : "This session stays on Custom75.");
        strip = c::pending_bg; ink = c::pending_text;
    } else if (notice == render_menu::Notice::RestartRequired) {
        std::snprintf(line, sizeof(line), "%s saved for next launch. Restart required.", mode_name(state.saved));
        if (failed) std::snprintf(sub, sizeof(sub), "This session stays as it started.");
        else std::snprintf(sub, sizeof(sub), "This session keeps %s at %s -> %s.", mode_name(active), known(rt.render_size), known(rt.display_size));
        strip = c::pending_bg; ink = c::pending_text;
    } else if (notice == render_menu::Notice::SaveFailed) {
        std::snprintf(line, sizeof(line), "Save failed: settings file could not be written.");
        // state.saved is the fresh read after the attempt, not a cached value.
        std::snprintf(sub, sizeof(sub), "Next launch uses %s. Your %s selection is kept.", mode_name(state.saved), mode_name(state.edited));
        strip = c::error_bg; ink = c::error_text;
    }
    const ImVec2 viewport = ImGui::GetIO().DisplaySize;
    const float width = l::width*s, max_height = viewport.y - 2*l::viewport_inset*s;
    if (max_height <= 0 || viewport.x < width + 2*l::viewport_inset*s) return;
    ImGui::SetNextWindowPos(ImVec2(viewport.x-l::viewport_inset*s, l::viewport_inset*s), ImGuiCond_Always, ImVec2(1,0));
    ImGui::SetNextWindowSize(ImVec2(width, std::min(l::nominal_height*s, max_height)), ImGuiCond_Always);
    ImGui::Begin("##nier_render", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
        ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoCollapse |
        ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
    observed.panel = {ImGui::GetWindowPos(), ImVec2(ImGui::GetWindowPos().x+ImGui::GetWindowWidth(), ImGui::GetWindowPos().y+ImGui::GetWindowHeight())};
    const ImVec2 start = ImGui::GetCursorScreenPos();
    text(fonts, Title, "NIER RENDER");
    ImGui::SetCursorScreenPos(ImVec2(start.x+ImGui::GetContentRegionAvail().x-36*s, start.y));
    ImGui::PushStyleColor(ImGuiCol_Button, IM_COL32(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_Text, c::text);
    const bool close = ImGui::Button("X##close", ImVec2(36*s,36*s));
    ImGui::PopStyleColor(2);
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("Close (Esc)");
    if (close) { render_menu::close(state); ImGui::End(); return; }
    ImGui::SetCursorScreenPos(ImVec2(start.x,start.y+28*s));
    text(fonts, Mono, rt.backend ? rt.backend : "BACKEND UNKNOWN", c::secondary_text);
    ImGui::SetCursorScreenPos(ImVec2(start.x,start.y+58*s));
    ImGui::Separator();
    ImGui::SetCursorPosY(ImGui::GetCursorPosY()+4*s);
    const float wrap_width = width-2*l::panel_padding*s-32*s;
    auto height = [&](const char* value, FontRole role) {
        ImGui::PushFont(fonts.items[role]);
        float y = *value ? ImGui::CalcTextSize(value, nullptr, false, wrap_width).y : 0;
        ImGui::PopFont(); return y;
    };
    const float box_h = std::max(32*s, 16*s+height(line, Body)+(*sub ? 4*s+height(sub, Secondary) : 0));
    const float footer_h = box_h+12*s+44*s+12*s+13*s;
    ImGui::BeginChild("body", ImVec2(0,std::max(1.0f,ImGui::GetContentRegionAvail().y-footer_h-10*s)), ImGuiChildFlags_None);
    ImGui::Dummy(ImVec2(0,8*s)); // Together with item spacing, the section has 18 logical px of top padding.
    text(fonts, Label, "ACTIVE THIS SESSION", c::secondary_text);
    if (failed) {
        text(fonts, Headline, "Not applied as configured", c::reason_text, true);
        text(fonts, Secondary, rt.failure_reason ? rt.failure_reason : "Startup setup failed.", c::reason_text, true);
    } else {
        text(fonts, ModeName, mode_name(active));
        ImGui::SameLine();
        text(fonts, Badge, active == Mode::Native ? "BYPASS / FULL RESOLUTION" : "ACTIVE / 75% PER AXIS", c::secondary_text);
        if (active == Mode::Native) text(fonts, Secondary, "Controller patches skipped; existing AA mod kept.", c::secondary_text, true);
    }
    text(fonts, Dimensions, failed ? "—" : known(rt.render_size));
    ImGui::SameLine(218*s); text(fonts, Dimensions, "->", c::secondary_text);
    ImGui::SameLine(278*s); text(fonts, Dimensions, failed ? "—" : known(rt.display_size));
    text(fonts, Secondary, failed || !rt.render_size || !*rt.render_size ? "Render size: unknown" : "Render resolution", c::secondary_text);
    ImGui::SameLine(278*s); text(fonts, Secondary, failed || !rt.display_size || !*rt.display_size ? "Display size: unknown" : "Display resolution", c::secondary_text);
    ImGui::Separator();
    text(fonts, Label, "PRESET FOR NEXT LAUNCH", c::secondary_text);
    char saved[64];
    if (state.file == FileState::Valid) std::snprintf(saved,sizeof(saved),"Saved: %s",mode_name(state.saved));
    else std::snprintf(saved,sizeof(saved),"%s -> next launch %s",state.file == FileState::Missing ? "No settings file" :
        state.file == FileState::Invalid ? "Invalid file" : "Unreadable file",mode_name(state.saved));
    text(fonts, Mono, saved, c::secondary_text);
    ImGui::PushFont(fonts.items[Control]);
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(12*s,15*s));
    ImGui::PushStyleColor(ImGuiCol_Button,c::field);
    ImGui::SetNextItemWidth(-1);
    const char* edited = state.edited == Mode::Native ? "Native — full-resolution AA" : "Custom75 — 75% per axis";
    const bool combo = ImGui::BeginCombo("##preset",edited);
    observed.preset = last_item();
    if (combo) {
        ImGui::BeginDisabled(!state.custom75_available);
        if (ImGui::Selectable("Custom75 — 75% per axis",state.edited==Mode::Custom75)) render_menu::select(state,Mode::Custom75);
        ImGui::EndDisabled();
        if (ImGui::Selectable("Native — full-resolution AA",state.edited==Mode::Native)) render_menu::select(state,Mode::Native);
        ImGui::EndCombo();
    }
    ImGui::PopStyleColor(); ImGui::PopStyleVar(); ImGui::PopFont();
    if (!state.custom75_available) text(fonts,Secondary,"Custom75 unavailable: not validated for this setup.",c::reason_text,true);
    text(fonts, Secondary, state.edited == Mode::Native ?
        "Skips this controller's upscale patches; the existing AA mod stays installed." :
        "Renders at 75% per axis. A custom ratio, not the standard FSR Quality preset.",c::secondary_text,true);
    observed.body_scroll_max = ImGui::GetScrollMaxY();
    ImGui::EndChild();
    const ImVec2 box = ImGui::GetCursorScreenPos();
    ImGui::GetWindowDrawList()->AddRectFilled(box,ImVec2(box.x+ImGui::GetContentRegionAvail().x,box.y+box_h),strip,2*s);
    ImGui::SetCursorScreenPos(ImVec2(box.x+16*s,box.y+8*s));
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX()+wrap_width);
    text(fonts,Body,line,ink);
    if (*sub) {
        ImGui::SetCursorScreenPos(ImVec2(box.x+16*s,box.y+8*s+height(line,Body)+4*s));
        text(fonts,Secondary,sub,ink);
    }
    ImGui::PopTextWrapPos();
    ImGui::SetCursorScreenPos(ImVec2(box.x,box.y+box_h+12*s));
    ImGui::PushFont(fonts.items[Control]);
    const bool can_save = render_menu::can_save(state) && save;
    const bool can_discard = render_menu::can_discard(state);
    ImGui::PushStyleColor(ImGuiCol_Button,can_save ? c::primary : IM_COL32(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_Text,can_save ? c::on_primary : c::disabled_text);
    ImGui::PushStyleVar(ImGuiStyleVar_DisabledAlpha,1.0f);
    ImGui::BeginDisabled(!can_save);
    const char* label = state.save_error ? "Retry save" :
        state.file == FileState::Invalid && !can_discard ? "Repair settings file" : "Save for next launch";
    if (ImGui::Button(label,ImVec2(320*s,44*s))) {
        const SaveReport r = save(state.edited,user);
        render_menu::complete_save(state,r.outcome,r.file,r.next_launch);
    }
    observed.save = last_item();
    ImGui::EndDisabled(); ImGui::PopStyleVar(); ImGui::PopStyleColor(2);
    ImGui::SameLine(0,12*s);
    ImGui::PushStyleColor(ImGuiCol_Button,can_discard ? c::field : IM_COL32(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered,c::neutral);
    ImGui::PushStyleColor(ImGuiCol_ButtonActive,c::neutral);
    ImGui::PushStyleColor(ImGuiCol_Text,can_discard ? c::text : c::disabled_text);
    ImGui::PushStyleVar(ImGuiStyleVar_DisabledAlpha,1.0f);
    ImGui::BeginDisabled(!can_discard);
    if (ImGui::Button("Discard changes",ImVec2(172*s,44*s))) render_menu::discard(state);
    observed.discard = last_item();
    ImGui::EndDisabled(); ImGui::PopStyleVar(); ImGui::PopStyleColor(4); ImGui::PopFont();
    text(fonts,Mono,"Insert: toggle  |  Esc: close  |  Cap unchanged",c::secondary_text);
    ImGui::End();
    if (geometry) *geometry = observed;
}
} // namespace menu_preview
