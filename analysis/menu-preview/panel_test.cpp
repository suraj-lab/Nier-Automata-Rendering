#include "panel.h"
#include "imgui_internal.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <stdexcept>

using namespace menu_preview;
using render_settings::Mode;
using render_menu::State;
using render_menu::SessionMode;
using render_menu::FileState;
using render_menu::Notice;
using render_menu::SaveOutcome;
// fail: the attempt fails and the fresh read finds `reread`. recovery: publish left the file moved away.
struct Writer { bool fail = false, recovery = false; int calls = 0; Mode submitted = Mode::Custom75;
                FileState reread_file = FileState::Valid; Mode reread = Mode::Custom75; };
static SaveReport save(Mode value, void* raw) {
    auto& w = *static_cast<Writer*>(raw); ++w.calls; w.submitted = value;
    if (w.recovery) return {SaveOutcome::RecoveryRequired, FileState::Missing, Mode::Custom75};
    if (w.fail) return {SaveOutcome::NotSaved, w.reread_file, w.reread};
    return {SaveOutcome::Committed, FileState::Valid, value};
}
static bool near(float a, float b) { return std::fabs(a-b) < 1.1f; }
static ImVec2 center(Rect r) { return ImVec2((r.min.x+r.max.x)/2,(r.min.y+r.max.y)/2); }

int main(int argc, char** argv) {
    assert(argc == 2);
    unsigned layouts = 0;
    for (auto viewport : {ImVec2(1920,1080),ImVec2(3440,1440)}) {
        for (float scale : {1.f,1.5f,2.f}) {
            IMGUI_CHECKVERSION(); ImGui::CreateContext();
            auto& io = ImGui::GetIO(); io.IniFilename = nullptr;
            io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
            io.DisplaySize = viewport; io.DeltaTime = 1.f/60;
            apply_style(scale); const float padding = ImGui::GetStyle().FramePadding.y;
            apply_style(scale); assert(near(ImGui::GetStyle().FramePadding.y,padding));
            assert(std::fabs(ImGui::GetStyle().Colors[ImGuiCol_WindowBg].x-232.f/255) < 0.0001f);
            const auto fonts = load_fonts(argv[1],scale);
            assert(fonts.items[ModeName]->FindGlyphNoFallback(0x2014));
            assert(fonts.items[Dimensions]->FindGlyphNoFallback(0xD7));
            unsigned char* pixels; int atlas_w,atlas_h;
            io.Fonts->GetTexDataAsRGBA32(&pixels,&atlas_w,&atlas_h);
            assert(pixels && atlas_w>0 && atlas_h>0);
            io.Fonts->SetTexID(1);
            RuntimeInfo info{"FSR 4.1.1 · D3D11 · PROTON (SIMULATED)","2580×1080","3440×1440","Simulated startup failure."};
            Writer writer;
            Geometry geometry;
            auto frame = [&](State& s, SavePreset callback = save) {
                ImGui::NewFrame(); draw_panel(s,info,fonts,scale,callback,&writer,&geometry); ImGui::Render();
            };
            auto click = [&](State& s, Rect r) {
                auto p = center(r); io.AddMousePosEvent(p.x,p.y); io.AddMouseButtonEvent(0,true); frame(s);
                io.AddMouseButtonEvent(0,false); frame(s);
            };
            // 0 custom75, 1 native, 2 dirty, 3 saved, 4 save-fail, 5 startup-fail, 6 not-applied+saved,
            // 7 missing file, 8 invalid file, 9 unreadable file (+edit), 10 recovery required.
            const Notice expected_notice[] = {Notice::None, Notice::None, Notice::Unsaved, Notice::RestartRequired,
                Notice::SaveFailed, Notice::None, Notice::RestartRequired, Notice::None, Notice::ConfigInvalid,
                Notice::ConfigUnreadable, Notice::RecoveryRequired};
            for (int scenario = 0; scenario < 11; ++scenario) {
                const bool bad = scenario==8 || scenario==9;
                const SessionMode active = scenario==1 || bad ? SessionMode::Native :
                    scenario==5 || scenario==6 ? SessionMode::NotApplied : SessionMode::Custom75;
                const FileState file = scenario==7 ? FileState::Missing : scenario==8 ? FileState::Invalid :
                    scenario==9 ? FileState::Unreadable : FileState::Valid;
                State s{active,file,scenario==1 || bad ? Mode::Native : Mode::Custom75,scenario<5 || scenario>6};
                s.open = true;
                if ((scenario>=2 && scenario<=4) || scenario==6 || scenario==10) render_menu::select(s,Mode::Native);
                if (scenario==9) render_menu::select(s,Mode::Custom75);
                if (scenario==3 || scenario==6) render_menu::complete_save(s,SaveOutcome::Committed,FileState::Valid,Mode::Native);
                if (scenario==4) render_menu::complete_save(s,SaveOutcome::NotSaved,FileState::Valid,Mode::Custom75);
                if (scenario==10) render_menu::complete_save(s,SaveOutcome::RecoveryRequired,FileState::Missing,Mode::Custom75);
                assert(render_menu::notice(s) == expected_notice[scenario]);
                for (int n=0;n<3;++n) frame(s);
                assert(near(geometry.panel.max.x,viewport.x-32*scale));
                assert(near(geometry.panel.min.y,32*scale));
                assert(near(geometry.panel.max.x-geometry.panel.min.x,552*scale));
                assert(geometry.panel.max.y <= viewport.y-32*scale+1);
                for (Rect r : {geometry.save,geometry.discard}) {
                    assert(r.min.y >= geometry.panel.min.y);
                    assert(r.max.y < geometry.panel.max.y);
                    assert(r.max.x <= geometry.panel.max.x);
                    assert(near(r.max.y-r.min.y,44*scale));
                }
                if (viewport.y==1080 && scale==2) {
                    if (!(geometry.body_scroll_max>0)) {
                        std::fprintf(stderr,"Scroll missing: scenario=%d panel_y=%f..%f save_y=%f..%f\n",scenario,
                            geometry.panel.min.y,geometry.panel.max.y,geometry.save.min.y,geometry.save.max.y);
                        for (auto* window : ImGui::GetCurrentContext()->Windows)
                            if (window->Flags & ImGuiWindowFlags_ChildWindow)
                                std::fprintf(stderr,"child=%s size=%f content=%f scroll_max=%f\n",window->Name,window->Size.y,window->ContentSize.y,window->ScrollMax.y);
                    }
                    assert(geometry.body_scroll_max>0);
                }
                assert(s.active == active);
                if (scenario==9 || scenario==10) {  // Save is shown but cannot fire
                    const int calls = writer.calls; click(s,geometry.save); assert(writer.calls == calls);
                }
                ++layouts;
            }
            if (scale==1 && viewport.x==1920) {
                State s{SessionMode::Custom75,Mode::Custom75,true};s.open=true;
                render_menu::select(s,Mode::Native);
                frame(s);frame(s);
                writer.fail=true; click(s,geometry.save);
                assert(writer.calls==1 && writer.submitted==Mode::Native);
                assert(s.save_error && s.saved==Mode::Custom75 && s.active==SessionMode::Custom75);
                writer.fail=false; frame(s); click(s,geometry.save);
                assert(writer.calls==2 && s.saved==Mode::Native && s.active==SessionMode::Custom75);
                render_menu::select(s,Mode::Custom75); frame(s);click(s,geometry.discard);
                assert(s.edited==Mode::Native && s.saved==Mode::Native);
                render_menu::select(s,Mode::Custom75); frame(s,nullptr);frame(s,nullptr);
                const int old_calls=writer.calls;
                auto p=center(geometry.save);io.AddMousePosEvent(p.x,p.y);io.AddMouseButtonEvent(0,true);frame(s,nullptr);
                io.AddMouseButtonEvent(0,false);frame(s,nullptr);
                assert(writer.calls==old_calls && s.saved==Mode::Native);
                frame(s); click(s,geometry.preset);
                assert(ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId));
                key_event(s,ImGuiKey_Escape); assert(s.open);
                io.AddKeyEvent(ImGuiKey_Escape,true);frame(s);
                io.AddKeyEvent(ImGuiKey_Escape,false);frame(s);
                assert(!ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId));
                key_event(s,ImGuiKey_Escape);frame(s);
                assert(!s.open && ImGui::GetDrawData()->TotalVtxCount==0);
                assert(s.edited==Mode::Custom75 && s.saved==Mode::Native);
                key_event(s,ImGuiKey_Insert);frame(s);frame(s);
                click(s,geometry.preset);
                assert(ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId));
                key_event(s,ImGuiKey_Insert);frame(s);frame(s);
                assert(!s.open && !ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId));
                assert(ImGui::GetDrawData()->TotalVtxCount==0);

                // Failed save shows the fresh read (another program saved Native), not the cached Custom75.
                State stale{SessionMode::Custom75,FileState::Valid,Mode::Custom75,true};stale.open=true;
                render_menu::select(stale,Mode::Native);frame(stale);frame(stale);
                writer.fail=true;writer.reread_file=FileState::Valid;writer.reread=Mode::Native;
                click(stale,geometry.save);
                assert(stale.save_error && stale.saved==Mode::Native && render_menu::notice(stale)==Notice::SaveFailed);
                // Invalid file: Save repairs it even though Native is already selected.
                writer.fail=false;
                State invalid{SessionMode::Native,FileState::Invalid,Mode::Native,true};invalid.open=true;
                frame(invalid);frame(invalid);
                const int before_repair=writer.calls;click(invalid,geometry.save);
                assert(writer.calls==before_repair+1 && writer.submitted==Mode::Native);
                assert(invalid.file==FileState::Valid && render_menu::notice(invalid)==Notice::None);
                // Recovery result: sticky, and Save no longer fires.
                State moved{SessionMode::Custom75,FileState::Valid,Mode::Custom75,true};moved.open=true;
                render_menu::select(moved,Mode::Native);frame(moved);frame(moved);
                writer.recovery=true;click(moved,geometry.save);writer.recovery=false;
                assert(moved.recovery_required && moved.file==FileState::Missing && moved.saved==Mode::Custom75);
                const int after_recovery=writer.calls;frame(moved);click(moved,geometry.save);
                assert(writer.calls==after_recovery && render_menu::notice(moved)==Notice::RecoveryRequired);
            }
            ImGui::DestroyContext();
        }
    }
    std::printf("{\"passed\":true,\"layouts\":%u,\"viewports\":2,\"dpi_scales\":3,\"limits\":\"ImGui CPU layout/input tests, not GPU/game integration\"}\n",layouts);
}
