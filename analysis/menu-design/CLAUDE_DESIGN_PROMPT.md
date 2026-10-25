# Claude Design prompt

Attach `menu-reference.png` and `menu-windows-concept.png`, then paste the text below.
The SVG sources are available if you want to inspect their layers. Do not attach game DLLs, private
logs, backups or a full repository dump. The Windows image is a design scenario, not a tested runtime.

---

Design a compact **cross-platform in-game rendering control panel for NieR:Automata**, targeting
**native Windows and Linux through Proton**. Use my attached original references as the starting
direction. Refine them into a polished, interactive design prototype; do not turn this into a web
dashboard or a generic mod-manager app.

## Chosen direction

- One floating panel, about **552 × 516 logical pixels**, placed near the upper-right of the game
  viewport with a 32px inset. The two panels in the reference show different states of the SAME
  panel; the real menu opens only one window.
- Warm ivory surfaces, charcoal text, muted olive primary action, amber pending/restart feedback.
  Restrained NieR-inspired utility UI: square or 2px corners, thin rules, uppercase small section
  labels, clear spacing. No glass blur, neon, gradients, giant cards, sidebar, tabs or decorative gauges.
- Legible sans-serif body type and monospaced resolution numbers. Target 15–16px body text at 1×,
  with usable 150%/200% scaling. Keep footer actions visible on smaller viewports; scroll content
  rather than shrink text until unreadable. Use keyboard focus and text/icons in addition to colour.
- The actual implementation will use **C++ Dear ImGui + Win32/D3D11 backends**. Prefer visuals and
  interactions feasible with ordinary immediate-mode widgets and a few simple drawn shapes.
  FAR/Special K and ReShade are hierarchy/density references, not code or branding to copy. Do not
  use proprietary game fonts, game screenshots, textures or logos.

## Cross-platform requirements

- One shared UI and settings model. The actual game/overlay uses Win32/D3D11 both on native Windows
  and under Proton; this is not a separate Linux GTK app and Windows WinUI app.
- Windows-on-ARM is an eventual target too: the x64 game may run under emulation on an ARM64 host.
  The injected DLL must match the GAME PROCESS ABI, not blindly the host CPU. No Windows/ARM64
  compatibility has been established by the current Linux tests. Keep this as engineering context,
  not a prominent architecture selector or compatibility badge in the menu.
- Platform, backend, version, GPU and dimensions are runtime information, not permanently “Proton”,
  “AMD” or “FSR4”. Show an honest unknown value until observed; do not infer the AA backend from OS.
- Feature availability must follow validated game/profile/backend capabilities, not an OS-only rule.
  The attached Windows scenario uses Native with unknown render size and an unvalidated Custom75
  option. That does NOT mean Windows will always lack Custom75: validated setups should get the same
  control. Do not advertise DLSS/NR/FG support just because the host has an NVIDIA GPU.
- Keep the same look on both platforms. Account for DPI/font availability, keyboard/focus handling,
  and an upper-right panel on both 3440×1440 ultrawide and 1920×1080. No Linux paths, shell commands,
  package-manager instructions or platform-specific installation controls in the panel. Do not rely
  on a system font installed only on Linux; implementation needs a built-in or licensed bundled font.

## What exists and works

The settings backend has passed Native/Custom75 game smoke tests on **Linux/Proton + RX 9070 XT**.
Windows is planned, not validated. The overlay itself has NOT been implemented or installed.
Current verified Proton test-session data:

- **Custom75:** 75% per axis; render colour/depth/motion vectors at **2580×1080**, FSR4 output at
  **3440×1440**. This is a custom ratio, NOT the standard “FSR Quality” preset.
- **Native:** skip this controller's upscale/depth/proxy patches and scale write; keep the existing
  AA mod. Example dimensions: **3440×1440 → 3440×1440**. Native does not mean uninstalling the mod.
- The current verified bridge is **FSR 4.1.1 / D3D11 / Proton**. Treat these labels as example runtime
  data, not a promise for Windows or a backend selector. Do not invent live FPS metrics.
- The controller leaves the game's 60 FPS cap alone. No FPS-cap control belongs in this version.

## Panel contents

1. Header: `NIER RENDER`, compact backend/platform line and a close button.
2. `ACTIVE THIS SESSION`: actual applied mode, render → display dimensions, and honest status.
3. `PRESET FOR NEXT LAUNCH`: one dropdown with exactly the two defined modes:
   **Custom75 — 75% per axis** and **Native — full-resolution AA**. Include a short explanation.
   If Custom75 is unvalidated/unavailable for the current setup, disable it and explain why; do not
   silently rename it, invent a supported preset, or disable it merely because the OS is Windows.
4. Inline change/save/restart feedback.
5. Primary **Save for next launch** and secondary **Discard changes** actions.
6. Small shortcut hint: **Insert** opens/closes, **Esc** closes. Insert is the chosen design binding;
   actual integration must still check input conflicts. F8 is unavailable: the existing AA mod uses it.

## Critical state behaviour

Keep **active**, **saved**, and **edited** values separate:

- Initially all are Custom75. No unsaved changes: disable Save and Discard.
- Selecting Native changes only the edited selection. Show “Unsaved. This session stays on Custom75.”
  Enable Save/Discard. Keep the ACTIVE mode and its 2580×1080 → 3440×1440 dimensions unchanged.
- Successful Save changes the saved value, not the active value. Show “Native saved for next launch.
  Restart required.” Disable Save/Discard when there is no remaining unsaved edit. Do not relabel
  the current session Native or pretend that rendering changed.
- Discard resets the edit to the last saved value. It does not undo a completed save.
- Closing the panel must not save, restart, patch or inject anything. Keep unsaved edits in memory
  for reopening during this session; do not add a confirmation-modal flow.
- Saving failure: retain the edit and previous saved value, keep active rendering untouched, show
  a readable error with Retry available. Never show a success/restart confirmation for a failed write.
- Startup setup failure: show **“Not applied — renderer unchanged”** plus a concise reason. Use `—`
  for unknown dimensions. Do not invent an effective Native mode or measured dimensions, and do not
  clear an existing startup error merely because settings were saved successfully. No live patch retry:
  startup setup retries require a game restart, especially after persistent protection/cache failures.

No live switching or automatic game restart. The prototype simulates saves in memory only; it must
not access the real game directory or download/inject DLLs.

## Deliver

- Briefly identify any hierarchy, legibility or state-confusion issues before refining the reference.
- An interactive prototype covering unchanged, unsaved, saved/restart-required, save-failure and
  startup-failure states. Include the verified Proton/Custom75 example and a Windows/Native example
  with unknown render size and a capability-dependent unavailable Custom75 option. Mark Windows
  sample data as conceptual, not measured or compatibility-tested.
- A clean final panel plus a small state sheet, not multiple permanent windows or a whole app shell.
- Typography/colour/spacing tokens and brief implementation notes for an ImGui engineer.
- Keyboard navigation, visible focus, readable contrast and a closed-menu state with no residual HUD.

Keep v1 limited to the two working presets. Do NOT add resolution sliders, extra FSR presets,
sharpening controls, frame generation, neural rendering, uncapping, benchmark graphs, install buttons
or greyed-out future-feature sections. Improve the clarity and finish of this design, not its scope.
