# FAR investigation and custom rendering menu - first pass

Scope: offline research only. FPS remains capped at 60 in the installed game. No Special K/FAR
DLL was loaded for this investigation. Our startup-settings candidate has since passed Native and
Custom75 live smoke tests (see `STARTUP_SETTINGS.md`); menu, extra presets, NR, FG and uncap remain
unimplemented.

## Evidence and version boundary

- Original FAR: https://github.com/Kaldaien/FAR explicitly targets the original 2017 Steam
  executable and warns that it is incompatible with the updated 2021 Steam/Microsoft Store builds.
- Modern game-specific source: SpecialKO/SpecialK, `src/plugins/nier.cpp`, pinned at
  `1f39b92c9cdd50e5d12296bed1e551473edb09c3`.
  https://github.com/SpecialKO/SpecialK/blob/1f39b92c9cdd50e5d12296bed1e551473edb09c3/src/plugins/nier.cpp
  Offline copies and hashes: `analysis/runtime/far-recon/source-manifest.json` (gitignored).
- Shipped artifact here: quarantined Special K 26.10.10 `dxgi.dll`, SHA256
  `8a7d7e42fecf0035ab26d57b46c78a02219e4e92c0239d76ac3827093fdeb9dd`.
  REA static resource inventory Evidence `ev_14777b9fe51b5f36d5efe589ce376c315287cde2d5cd42201b9ba682373d7e81`
  identifies that artifact. Resources are opaque; this is NOT evidence of its timing code.
  The source snapshot is not established as a byte-identical match to that release.

## How FAR removes the cap (source observations, not live observations)

1. **Find the game's limiter.** `SK_FAR_SetLimiterWait`, lines 656-756: distinct Steam2017 and
   Steam2021 signature patterns locate the Sleep call and a nearby wait-loop branch. Six Sleep-call
   bytes can be replaced with NOPs. Only the Sleep signature gets independent validation; the
   spinlock location comes from a fixed offset, not a second signature check. Failure to locate
   the Sleep patch point disables the patchable path.
2. **Bypass the remaining wait.** `far_game_state_s::uncapFPS`, lines 2584-2618: legacy versions
   NOP a two-byte branch; Steam2021 writes `EB 48` (a short unconditional jump). This is not merely
   disabling VSync, and the legacy absolute addresses in comments are NOT addresses to copy into our build.
3. **Handle game timing as well as presentation.** For Steam2017, the uncap alters minimum/maximum
   timestep branches (2610-2617). For Steam2021 those branches are not used; per-frame code at
   854-885 writes a time scale from measured frame delta relative to 1/60 second into a game field.
   At an ideal 120 FPS this expression is approximately 0.5. Only `isInMenu()` forces 1.0;
   other cap conditions do not enter this expression. Values >= 1.075 reset to 1.0, with a comment
   about the game's low-FPS compensation. The write to base+`0x1029F88` follows the uncap preference,
   not the actual cap state; disabling that preference has no explicit reset in this block.
   This heuristic does not prove decoupled simulation/rendering or correct physics at arbitrary FPS.
4. **Reconsider the cap every frame.** `needFPSCap`, 105-149, and update logic, 839-850: user
   preference, patchability, menus and shortcuts influence it. Steam2021 also checks cursor visibility
   and hacking state. FastLoad bypasses later cap checks during loading, but only after patchability
   and user-enforced-cap checks pass. The inner cursor/hacking SEH handler swallows its exception
   and continues; only the outer handler fails closed by clearing `patchable`.
   Steam2021 `capFPS` conditionally sets the external target to 60 (if the configured or current
   target is nonpositive or above 60), then returns at 2643-2644 before restoring instructions or
   time scale. Already-valid lower targets are retained. Trace Special K's limiter integration before
   claiming this restores the game's own limiter or guarantees an exact 60 FPS cap.
   `FAR_UNCAP_FOLLOWUP.md` records source-checked clarifications and the interrupted local-worker run.

The uncap therefore comprises limiter patches + timing compensation + game-state policy + Special K's
own frame pacing. Porting just the NOPs is not a complete or safe implementation.

## Rendering fixes and menu

FAR is game-specific functionality hosted by Special K, not a standalone modern upscaler framework.
The source includes GI workload controls, bloom/AO target manipulation, LOD/camera/HUD options and
other version-dependent patches. CreateTexture2D/CreateShaderResourceView hooks are installed around
1721-1731. `SK_FAR_PlugInCfg` (2093 onward) uses Dear ImGui; preferences are stored through Special K's
parameter/configuration system. Options differ by game version (e.g. the post-processing group at
2114 is excluded for Steam2021). Copying the entire UI would drag in that host infrastructure.

Licensing: nier.cpp retains an MIT-style permission header; the fetched repository root LICENSE
is GPLv3. Audit each reused file and dependency before distributing anything. Do not assume that all
Special K code shares the original FAR repository's licence. A source-informed independent design
is possible; this investigation is not a clean-room separation.

## Linux failure evidence (do not generalize)

Quarantined logs in `quarantine/specialk-crash-20261018T215003Z/logs/dxgi.log` report Special K 26.10.10,
a failed hook on `sub_84D070` (`MH_ERROR_UNSUPPORTED_FUNCTION`) and a version-info assertion in
`SK_Assert_SameDLLVersion`. Synthetic probes also stalled at initialization (`VISUAL_STACK.md:130+`).
These are leads for investigation, not a proven single root cause or proof FAR never works on Proton.

## Proposed smallest replacement

Keep the working d3d11 chain and leave WAX/LodMod in place. Reuse our render/depth/output-routing
work rather than install a second generic DXGI hook stack.

1. **Settings first:** the candidate reads `Native`/`Custom75` at startup and refuses scale reduction
   if prerequisite patching fails. Both startup smoke tests passed; `STARTUP_SETTINGS.md` records
   the evidence and remaining resolution-change/long-session checks. Keep the Custom 75% label,
   not standard FSR Quality. Live changes still need coordinated target recreation, resource release,
   NGX/FSR context recreation and history reset. Test rounding and depth parity for each new preset.
2. **Thin in-game menu:** one Dear ImGui D3D11 overlay after the reconstruction/post/HUD pipeline.
   It calls the same settings logic, shows requested vs effective sizes/backend, preserves D3D state,
   and handles input focus without passing menu clicks/keys into gameplay. No unsupported toggles.
3. **Backend capabilities:** separate upscaling, NR, FG and real FPS limit. Enable only backends that
   initialize on the actual GPU/OS/API. Linux AMD and Windows-on-ARM NVIDIA do not have interchangeable
   runtimes. NR placement (pre/post upscale) is backend-specific, not a universal checkbox.
4. **One FG backend at a time:** determine hooks, depth/MV requirements, HUD handling, swapchain
   ownership and latency. Do not allow multiple FG injectors to own presentation at once. Generated
   display frames do not increase simulation rate or remove input latency.
5. **Uncap separately, default off:** verify the exact executable, limiter and game-state locations;
   prove timestep behaviour and menus, hacking, cutscenes, loading and representative gameplay at
   60/90/120 FPS. Only then offer a real-FPS limit. No copied hard-coded addresses or broad scans.

Outstanding: correlate FAR source to our exact shipped game build; trace Special K limiter integration;
identify the logged Proton hook failure; choose overlay/input attachment points. Independent source
review qualified the limiter/timing findings above; Luna accepted the startup candidate for offline
use only. Neither review establishes cross-platform NR/FG compatibility or high-FPS gameplay correctness.

## Deferred measurement work

The GPU sampler `analysis/measurements/sample_gpu.py` was produced by local-worker. Luna's review
caught non-finite optional readings leaking into CSV; lead reproduced it, added a regression test,
and changed those readings to None/blank cells. All 8 fake-sysfs tests pass. Live sampling/A/B capture
remain parked while the FAR/menu direction is discussed. Do not run local inference during captures.
