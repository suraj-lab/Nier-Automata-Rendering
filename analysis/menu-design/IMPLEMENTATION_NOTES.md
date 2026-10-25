# Claude Design handoff: acceptance and implementation notes

## Accepted visual target

Use `design_handoff_nier_render_panel/README.md` and `NieR Render Panel.dc.html` as the refined UI
reference. Preserve all three received files unchanged, including `support.js`. The export is a
browser design prototype, not code to load into the game DLL.

The independent reviewer accepted the visual/state spec with implementation notes. Lead tests of the
actual extracted prototype state script passed 10 scenarios. No browser, CDN, support.js, game DLL,
filesystem writer or injected overlay was executed by those tests.

## Corrections to carry into C++, not edits to the original export

1. **Right-edge positioning:** with pivot `(1,0)`, pass the RIGHT EDGE anchor, not the top-left x.
   Use viewport origin + available width - scaled inset. Do not subtract window width as well.
   The handoff's prose formula and pivot recipe otherwise shift the window a second width left.
2. **DPI:** restore a pristine baseline style before `ScaleAllSizes(scale)`, or apply only a ratio to
   the previous scale. Never repeatedly scale already-scaled values by the absolute DPI factor.
   Pick font/DPI APIs after pinning the actual ImGui revision; don't assume an older recipe remains
   source-compatible. The CSS prototype loads IBM Plex Sans/Mono from Google Fonts; the game build
   needs pinned, licensed local font assets and notices, not network font downloads or system fonts.
3. **Short viewport / 200% scale:** explicitly allocate the body scrolling region and fixed footer.
   `AlwaysAutoResize` plus constraints is not sufficient proof that action buttons remain reachable.
4. **Input:** enabling ImGui keyboard navigation/capture flags does not block the game's own input.
   Test Win32 messages plus actual game raw-input/DirectInput behavior, popup-first Esc handling,
   focus loss, and closed-menu pass-through on Windows and Proton. F8 remains owned by the AA mod.
5. **Simulator-only controls:** the export's startup-failure toggle can clear an error without a
   restart, and “Next save fails” remains armed across retries. Neither belongs in the game UI.
   Treat those as scenario controls, not production transition requirements.
6. **Runtime labels:** don't copy fixture-derived OS/capability/dimension values into production.
   Windows is not globally blocked from Custom75; no driver/GPU brand implies backend support.
   Unknown sizes remain unknown, and Native skips our patches rather than proving other mods
   render at a particular resolution.

## Portable controller candidate

`../checks/menu_state.h` reuses `render_settings::Mode` and contains only in-memory transitions.
`menu_state_test.cpp` was written before the header. Both session outcome and validated availability
are const; selecting/saving cannot mutate the applied session. Save-error priority, saved/restart
feedback, disabled Custom75, close/reopen and return-to-current-mode behavior are covered.

Construct the state only after the startup reader/patch attempt has produced a stable result. This
avoids allowing a menu save to race the current launch's initial settings read. The UI thread owns
all mutable state. The saved enum comes from a known valid reader result, not unchecked strings.
The I/O integration still needs missing/invalid/unreadable-config metadata and explicit repair tests;
never label a fallback enum as a successfully saved on-disk value. Detect external file changes before
writing rather than treating this cached enum as a fresh filesystem observation.

`complete_save` is synchronous acknowledgement, not an INI writer. Call it only after a real write
succeeds/fails for the current edited preset. Asynchronous writes would require capturing the request;
they are deliberately not implemented. Existing saves, unknown INI fields and failure atomicity need
separate filesystem tests before connecting a writer. `NotApplied` is never relabelled Native.

Current validation (receipts: `../runtime/menu-state/validation.json`):
- Actual exported JavaScript state: 10 scenarios passed, two simulator quirks characterized.
- C++17 standalone controller: warnings-as-errors + ASan/UBSan passed.
- All 7-event traces across 3 session outcomes × 2 saved modes × 2 capability values checked:
  9,882,516 traces / 69,177,612 transitions.
- MinGW x64 cross-build passed. The Windows EXE was NOT run; this is not Windows/ARM64 compatibility.

This header is not included by the production setter. No new DLL, overlay/input hook, config writer,
uncap, FG or NR was installed. The verified Custom75 candidate and 60 FPS setup are untouched.

## Laptop style extraction: checked data ready

After the user confirmed game-free, laptop Qwen 35B-A3B (`a029dbdb-ea88-4376-93fb-fcdf6e15e618`)
extracted `claude_style_tokens.json`: 19 colors, 11 layout and 16 typography tokens, three DPI
scales and twelve glyphs. The helper put its JSON in the managed report; the first gate failed
because the repository file was absent. The lead promoted the exact JSON block with exclusive-create,
then reran `python3 analysis/checks/test_menu_style_tokens.py`: passed. Extra source-membership checks
passed; all three received handoff hashes and installed game files remain unchanged.

This is a data snapshot, not a runtime parser/dependency to add to the game. Use the checked values
when writing the ImGui style; no live JSON configuration feature is requested. The later standalone
preview now includes pinned, unmodified IBM Plex static TTFs and their exact OFL notice. Receipt for
this extraction: `../runtime/menu-style-tokens/validation.json`.

## Isolated preview complete; paused for the night

`../menu-preview/README.md` documents the implemented panel, Win32/D3D11 host and selected actual
screenshots. All 42 CPU layout/state cases and 42 Wine/Xvfb D3D11 captures passed. The pinned ImGui
version is v1.91.9b (static font atlas), not the master snapshot used only for initial research.
Luna reviewed the candidate and confirmed fixes for unknown captions, disabled-button styling and
timeout diagnostics. The first Wine launch timed out; the successful retry changed optional-installer
settings and used a warmed prefix, so its original cause is still unproven.

The frontend/host share no resources with the game. Saves are fixture-only and Windows/ARM64 native
execution remains untested. No work runs overnight. After the user reviews the screenshots, resolve
real settings persistence/status publication and the game's actual swapchain/window/input seam,
resource/device-reset lifetime and state restoration behind separate gates. The standalone app is
not a game hook. Keep judgment/acceptance with the lead and respect each local node's single slot.
