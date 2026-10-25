# Handoff: NieR Render Panel (in-game overlay)

## Overview
A compact in-game rendering control panel for NieR:Automata. It shows the rendering mode applied this session and lets the player choose one of two presets for the **next launch**: Custom75 or Native. One shared UI runs on native Windows and on Linux via Proton. In both cases the overlay is Win32/D3D11.

v1 scope is fixed. The panel has two presets, no live switching and no automatic restart. It has no resolution sliders, extra FSR presets, sharpening, frame generation, FPS-cap control, metrics or install controls.

## About the design files
`NieR Render Panel.dc.html` is a **design reference built in HTML**. It is an interactive prototype that shows the intended look and behaviour, not production code. Implement it in **C++ Dear ImGui with the Win32 + D3D11 backends**, using ordinary immediate-mode widgets and a few simple drawn rects. The prototype simulates saves in memory only. It never touches the game directory and never injects anything.

Open the file in a browser. Use the scenario, viewport, scale and simulate controls at the top, or click a row in the State Sheet to load that state.

## Fidelity
**High fidelity.** Colours, type sizes, spacing and copy are final. Match them within ImGui's limits.

## Panel geometry
- Width **552** logical px. Natural height ≈ **516**. Corner radius **2**. 1px border `#B8B19C`. No blur, gradient or glow.
- Position: top-right of the game viewport with a **32 px inset**: `pos = (display.x − 32 − w, 32)`.
- Max height = `display.y − 64`. The header and footer are fixed and the body scrolls. **Footer actions must never scroll off.**
- Scale: 100 / 150 / 200 %. All sizes below are at 1×. Multiply by the DPI scale.
- Check it on 3440×1440 and 1920×1080. At 1920×1080 and 200%, the body must scroll.

### ImGui structure
```
SetNextWindowPos(..., pivot (1,0)); SetNextWindowSizeConstraints({552*s,0},{552*s,display.y-64})
Begin("##nier_render", nullptr, NoTitleBar|NoResize|NoCollapse|NoSavedSettings|NoMove|AlwaysAutoResize)
  Header                       // fixed
  Separator
  BeginChild("body", {0, -footerH})   // scrolls
    ACTIVE THIS SESSION section
    Separator
    PRESET FOR NEXT LAUNCH section (BeginCombo)
  EndChild
  Footer: feedback strip, [Save][Discard], shortcut hint   // fixed
End
```

## Sections and components (top to bottom)

### 1. Header (padding 20 top / 24 sides / 16 bottom; 1px rule `#C9C2AE` below)
- Title `NIER RENDER`: Sans 20 / 700, letter-spacing +0.12em, `#26272A`.
- Runtime line, Mono 13, `#55554C`, uppercase, e.g. `FSR 4.1.1 · D3D11 · PROTON` or `AA BACKEND UNKNOWN · D3D11 · WINDOWS`. Every value comes from runtime probes. Show `unknown` until it has been observed. **Never infer the backend from the OS or GPU vendor.**
- Close button: 36×36, glyph ✕ at 18px, transparent. Hover shows a 1px `#B8B19C` border. Label "Close (Esc)".

### 2. ACTIVE THIS SESSION (padding 18 vertical; row gap 10; rule below)
- Label: Sans 13 / 600, uppercase, +0.14em, `#55554C`.
- Badge (right side), Sans 12 / 600, uppercase, +0.1em, padding 3×10, radius 2:
  - Applied: `● APPLIED`, bg `#48523C`, text `#F3F0E6`.
  - Startup failure: `✕ NOT APPLIED`, bg `#8E2F1E`, text `#FBF3EE`.
- Mode name: Sans 28 / 500, e.g. `Custom75`. Next to it is a chip in Mono 13, bg `#D9D3C1`, text `#3A3B36`, padding 2×8: `75% / axis` for Custom75, `full resolution` for Native.
- Native only: a note line in Sans 14 `#55554C`, "Controller patches skipped · existing AA mod kept".
- Dimensions row, grid `1fr 48px 1fr`: render value / `→` / display value. Values in Mono 19 `#26272A`; captions in Sans 14 `#55554C` ("Render resolution", "Display resolution").
  - Unknown render size: value `—`, caption "Render resolution: not observed".
- **Startup failure** replaces the mode name with:
  - "Not applied — renderer unchanged" (Sans 22 / 500)
  - the reason in Sans 14 `#6E2416` (e.g. "Reason: upscaler bridge did not initialise at startup.")
  - "Setup retries only on the next game launch. Saving a preset does not clear this." (Sans 14 `#55554C`)
  - Both dimensions show `—`, with captions "…: unknown".

### 3. PRESET FOR NEXT LAUNCH (padding 18 top; row gap 10)
- Label row: label on the left. On the right, `Saved: <value>` in Mono 13 `#55554C`. This always shows the value on disk.
- Combo: height 46, bg `#F3F0E6`, 1px `#9C9580` border (hover `#26272A`), radius 2, Sans 16. Chevron ▾ (▴ when open). It shows the **edited** value.
- There are exactly two options, each a two-line `Selectable` (Sans 16 label, Sans 14 description). Highlight bg `#DCD7C6`; ✓ marks the current selection.
  - `Custom75 — 75% per axis`: "Custom ratio, not the standard FSR Quality preset."
  - `Native — full-resolution AA`: "Skips this controller's upscale patches; existing AA mod stays."
- **Capability gating:** if Custom75 is not validated for the current game/profile/backend, keep it listed but disabled (`ImGuiSelectableFlags_Disabled`, ink `#7A776B`, mark ⊘). Its description becomes "Unavailable: not validated for this game/backend setup." Also show this line below the combo: "⊘ Custom75 unavailable: not validated for this game/backend setup." Base availability on validated capabilities only. **Never disable it just because the OS is Windows, and never enable DLSS-type options because of the GPU vendor.**
- Help text below the combo describes the edited option (Sans 14 `#55554C`):
  - Custom75: "Renders at 75% per axis, then upscales to display. A custom ratio, not the standard FSR Quality preset."
  - Native: "Renders at full resolution. Skips this controller's upscale patches; the existing AA mod stays installed."

### 4. Footer (fixed; padding 12 top / 24 sides / 18 bottom; gap 12)
- **Feedback strip** (padding 10×14, Sans 15, icon glyph before the text):
  - none: bg `#DCD7C6`, text `#3A3B36`, "No unsaved changes."
  - dirty: bg `#E6D3A3`, text `#3A2E12`, "△ Unsaved. This session stays on {active}." With a startup failure, the second sentence becomes "This session's renderer stays unchanged."
  - saved: same amber colours, "↻ **{saved} saved for next launch. Restart required.**" followed by a Sans 14 line, "This session keeps {active} at {render} → {display}."
  - error: bg `#EBCFC4`, text `#5A1E14`, "✕ **Save failed: settings file could not be written.**" followed by "Saved preset is still {saved}. Your {edited} selection is kept. This session stays on {active}."
- **Buttons**, grid `1.4fr 1fr`, gap 12, height 44, Sans 16, radius 2:
  - Save (enabled): bg `#48523C`, text `#F3F0E6`, hover `#3A4330`. Its label is "Save for next launch", or "Retry save" after a failure.
  - Discard (enabled): bg `#F3F0E6`, 1px `#9C9580` border, text `#26272A`.
  - Disabled (both): transparent, 1px `#C9C2AE` border, text `#8E8A7C`. Use `BeginDisabled()` plus style overrides, so a disabled button **must not look like a filled button**.
- Shortcut hint: Mono 13 `#55554C`, "Insert open/close · Esc close · Tab/arrows navigate".

## State model
Keep three separate values plus status flags:
```
Mode active;          // fixed at startup from what was actually applied; never changes in-session
Mode saved;           // value on disk
Mode edited;          // in-memory selection
bool startupError;    // + reason string; cleared only by a game restart
bool saveError;       // last write failed
bool savedThisSession;
dirty = (edited != saved)
```
Transitions:
- **Initial** (Proton example): active = saved = edited = Custom75. Save and Discard are disabled.
- **Select Native** → only `edited` changes. Shows the dirty notice. Save and Discard are enabled. ACTIVE stays Custom75, 2580×1080 → 3440×1440.
- **Save OK** → `saved = edited`; `saveError = false`; `savedThisSession = true`. If `saved != active` or `startupError`, show the restart notice. Both buttons are disabled. **Do not relabel the session or claim the rendering changed.**
- **Save fails** → `saved` and `active` are unchanged and `edited` is kept. Show the error notice; the primary button becomes "Retry save". Never show a success notice after a failed write.
- **Discard** → `edited = saved`; clears `saveError`. It does not undo a completed save.
- **Selecting an option** clears `saveError`.
- **Close (✕ / Esc / Insert)** → no I/O, no save, no patching, no restart. Keep `edited` in memory for reopening. No confirmation modal.
- **Startup failure** → see section 2. A successful save does not clear it. There is no live retry.

Notice priority: error > dirty > saved/restart (only if `savedThisSession && (saved != active || startupError)`) > none.

## Input and focus
- Enable `ImGuiConfigFlags_NavEnableKeyboard` while open and swallow game input while the panel has focus.
- **Insert** toggles the panel. **Esc** closes the open combo first, then the window. F8 is reserved by the existing AA mod. Check Insert for input conflicts at integration.
- On open, focus the combo. In the combo, ↑/↓ move between enabled options only; Enter/Space selects; Tab closes the combo.
- Focus ring: 2px `#26272A` outline with a 2px offset on every interactive item. Override `ImGuiCol_NavHighlight` and draw a rect with the offset if needed.
- **Closed state:** submit no window at all. No HUD stub, tooltip or toast.

## Design tokens
Colours:
| token | hex |
|---|---|
| surface | `#E8E3D3` |
| field / option list | `#F3F0E6` |
| neutral strip / highlight | `#DCD7C6` |
| chip | `#D9D3C1` |
| rule | `#C9C2AE` |
| panel border | `#B8B19C` |
| field border | `#9C9580` |
| text | `#26272A` |
| text-2 (≈6.2:1 on surface) | `#55554C` |
| disabled text | `#8E8A7C` |
| primary / hover | `#48523C` / `#3A4330` |
| on-primary | `#F3F0E6` |
| pending bg / ink | `#E6D3A3` / `#3A2E12` |
| error bg / ink | `#EBCFC4` / `#5A1E14` |
| error badge / reason ink | `#8E2F1E` / `#6E2416` |

Type: **IBM Plex Sans** (400/500/600/700) and **IBM Plex Mono** (400/500). Both are under the SIL Open Font License. **Bundle the TTFs with the DLL**; never load a system font.
- Title 20/700 +0.12em · mode 28/500 · startup headline 22/500 · combo/buttons 16 · body/notice 15 · secondary 14 · labels 13/600 uppercase +0.14em · runtime line/hints Mono 13 · dimensions Mono 19 · badges 12/600.
- ImGui has no letter-spacing, so draw the uppercase labels per-glyph with an extra advance, or accept the default tracking.
- Merge the glyphs ✕ △ ↻ ⊘ ● ✓ ▾ ▴ → — × · into the atlas, or substitute small drawn shapes.

Spacing: panel padding 24 · section padding 18 · row gap 10 · footer gap 12 · control heights 44–46 · inset 32 · rules 1px · radius 2. There are no shadows apart from an optional 2px hard offset (`rgba(0,0,0,.25)`).

Scaling: rebuild the font atlas at `15 × dpiScale` (with the other sizes proportional) and call `ImGui::GetStyle().ScaleAllSizes(dpiScale)`. Read DPI through Win32, so it behaves the same on Windows and Proton.

## Runtime data
- Verified Proton example: FSR 4.1.1 / D3D11 / Proton, RX 9070 XT. Custom75 renders at 2580×1080 and outputs at 3440×1440. Native is 3440×1440 → 3440×1440.
- The Windows example in the prototype is **conceptual**: Native, render size not observed, Custom75 unavailable (not validated). It is not measured or compatibility-tested.
- Windows-on-ARM: the injected DLL must match the **game process ABI** (x64 under emulation), not the host CPU. This is engineering context only and has no UI.
- Leave the game's 60 FPS cap alone. Do not show FPS or any live metrics.

## Files
- `NieR Render Panel.dc.html`: interactive prototype covering all states, the review notes, the state sheet, the tokens and the ImGui notes. It needs `support.js` beside it.
- `support.js`: prototype runtime for the HTML file. Not part of the implementation.

## Assets
None. There are no game screenshots, textures, logos or proprietary fonts. Icons are text glyphs.
