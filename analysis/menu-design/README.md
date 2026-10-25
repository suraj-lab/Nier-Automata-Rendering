# Menu design decision

**Paused after the validated standalone preview, at the user's request.** The refined export in
`design_handoff_nier_render_panel/` is preserved unchanged. The real ImGui preview and screenshots
are in `../menu-preview/` (see its README); review corrections remain in `IMPLEMENTATION_NOTES.md`.
No in-game overlay or new game installation has been made.

## Selected base

Use our tested settings backend with a **single original Dear ImGui panel**, not a Special K fork.
Use the official Win32/D3D11 example and backends as implementation references. FAR/Special K informs
option grouping; ReShade informs compact preset/status hierarchy. Do not copy either host framework.

Dear ImGui snapshot inspected: `4e99c0ab1a28c2b3d1f250ec0266dbf1e455ef58`.
Its `LICENSE.txt` identifies the MIT license and Omar Cornut copyright; retain notices if vendoring.
The example creates its own window/swapchain. It is NOT a drop-in hook for an existing game: attachment,
resource lifetime, resize handling, D3D state restoration and input capture still need engineering/tests.
No ImGui sources or third-party UI assets have been vendored by this design task.

### Both Windows and Linux

Use one UI/settings model: Win32/D3D11 in the Windows game process, natively on Windows and through
Proton on Linux. Do not create separate GTK and WinUI applications. The current startup smoke tests
cover Linux/Proton on RX 9070 XT only. Future Windows-on-ARM testing must respect the x64 game
process ABI; host ARM64 does not mean an ARM64 DLL can replace an x64 game DLL.

Platform/backend/version/actual dimensions are runtime fields. Gate modes by validated game/profile/
backend capability, not OS name alone. The Windows design scenario intentionally shows Native,
unknown render size and unavailable Custom75 for an unvalidated setup; a validated Windows setup
can expose Custom75. This is a UI requirement, not implemented capability detection or compatibility
proof. Keep DPI, bundled-font licensing and keyboard/focus differences in the integration test plan.

Sources:
- https://github.com/ocornut/imgui/blob/4e99c0ab1a28c2b3d1f250ec0266dbf1e455ef58/examples/example_win32_directx11/main.cpp
- https://github.com/ocornut/imgui/blob/4e99c0ab1a28c2b3d1f250ec0266dbf1e455ef58/LICENSE.txt
- https://github.com/crosire/reshade (visual reference only; no code copied)
- `../FAR_RESEARCH.md` (pinned FAR source, version limits and mixed per-file/root licensing evidence)

## UI choice

Warm ivory/charcoal, thin rules, muted olive action, amber pending/restart feedback. A 552×516 logical
pixel window with 24px internal padding, initially upper-right with a 32px viewport inset. No tabs,
sidebar, game assets, custom blur shaders or future-feature controls. Use legible sans type and mono
numbers; the SVG references system Noto fonts but embeds no font files. Audit font rights before
bundling a font with a real overlay.

One dropdown: Native / Custom75. Read-only ACTIVE mode and actual render/output dimensions above it.
Save means **next launch**, not live resource recreation. Keep active/saved/edited state separate;
errors cannot masquerade as successful application. Native keeps the AA mod, and Custom75 must not
be labelled the standard FSR Quality preset. Unknown actual sizes should stay unknown.

**Hotkey:** Insert, with Esc to close. F8 is already `ToggleKey=0x77` in the installed `NIER_DLAA.ini`
and must not be reused. Insert does not appear in the inspected NIER_DLAA/LodMod key fields; WAX,
raw-input/DirectInput interaction and desktop-level conflicts remain unverified. Do not claim input
is isolated just because the ImGui example exposes `WantCaptureMouse/Keyboard`.

## Handoff

- `menu-reference.svg` / `.png`: current Proton example; active, edited, saved and failure references.
- `menu-windows-concept.svg` / `.png`: the same panel, Windows/Native scenario; NOT runtime validation.
- `CLAUDE_DESIGN_PROMPT.md`: paste-ready cross-platform prompt, scope and exact state behaviours.

Original handoff (completed): both PNGs and the prompt were sent to Claude Design; its received
export is now the UI target. The SVGs remain editable early references. For current implementation
status and remaining integration work, see `IMPLEMENTATION_NOTES.md`. No private game files, logs
or binaries need to be sent to a designer.

Rebuild the PNGs after changing SVGs with `rsvg-convert <source.svg> -o <output.png>`.

The paired panels are comparisons of one window, not two simultaneous overlays. Lower feedback
cards document alternate states, not extra windows or permanent UI sections. Dimension numbers
illustrate the verified current session; they are not hardcoded runtime capabilities.

The installed Custom75 build/config and 60 FPS cap stay untouched. No menu code, graphics hook or
config writer was installed. After design review, freeze UI-state tests, delegate bounded controller
code to the local worker, and implement/review the D3D11/window/input seam separately. Build any menu
candidate in a new path; keep the validated startup candidate and v4 rollback artifact intact.
