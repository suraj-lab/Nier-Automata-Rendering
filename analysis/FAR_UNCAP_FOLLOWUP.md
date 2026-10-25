# FAR uncap follow-up: source facts and local-worker outcome

Scope: read-only. No uncapping or runtime A/B test authorized/performed here. Keep the installed
60 FPS setup. Source remains SpecialKO/SpecialK `1f39b92c9cdd50e5d12296bed1e551473edb09c3`,
`src/plugins/nier.cpp`, SHA256 `5031907e6d2e653919837b23e09d76aee96bece930fa9c84c2fa63609d9eb09c`.

## What the lead checked against that exact source

- `uncapFPS`, 2584–2605: restores the configured Special K target to `__target_fps`, then writes
  Steam2021's wait branch to `EB 48`. Legacy versions use a different two-byte change. This is not
  just a VSync switch; see the original Sleep/signature/timestep notes in `FAR_RESEARCH.md`.
- `capFPS`, 2624–2644: **conditionally** assigns `__target_fps=60` if either the configured target
  or current target is nonpositive or above 60. If both are already in `(0,60]`, it does not force
  an exact 60 target. The Steam2021 return precedes the instruction-restoration code. That path
  does not restore the game wait branch or explicitly reset the timestep field.
- Per-frame work, 839–885: cap transitions use `needFPSCap`; the separate Steam2021 timestep write
  follows the uncap preference, not actual capped state. The scale is measured delta divided by
  a 1/60-second counter interval, except menus force 1 and values >=1.075 reset to 1. There is no
  explicit reset in this block when the preference becomes false. Field physics semantics and
  correct high-FPS gameplay still need exact-build evidence, not merely its source variable name.
- `needFPSCap`, 105–150: not patchable/user-enforced cap takes priority; FastLoad during loading
  then bypasses later checks. Steam2021 checks cursor/hacking, then menu/shorting flags. The inner
  cursor/hacking exception is swallowed; only the outer handler clears patchability and returns cap.
  There is no separate explicit cutscene predicate here. Shared flags may still correlate with
  cutscenes; source text alone cannot establish protection of every cutscene.
- FastLoad, 890–920: explicitly obtains the swapchain's Special K limiter and suspends it while
  loading, setting `present_interval=0`; it resumes/restores the saved interval on loading exit.
  The external pacing boundary is concrete, but its full implementation is outside this snapshot.
- Initial version selection, 1699–1708: a legacy pattern hit selects Steam2017, no Steam AppID
  selects Microsoft, otherwise Steam2021 is selected by elimination. Do not copy this as positive
  validation of our exact executable.
- Typed-pointer hazard, 123–127: `pHacking = (DWORD*)*ppHacking + 0x4B` advances **0x4B DWORDs**
  (0x12C bytes), not 0x4B bytes. Any future exact-build analysis must preserve that distinction.

## What was not accepted from the local draft

The worker ran beyond its eight-minute brief and was interrupted. A draft exists under the managed
artifact output, but the run is paused, not a completed/accepted independent review. Its late calls
repeatedly edited prose to hit a strict word-count limit. Future small local research should ask
for a few bullets and one output write, not an exact word-count trimming loop.

Do not import these overstatements:
- `SK_RunOnce` calls are not proven no-ops: its macro definition is absent from this snapshot.
- A return before game-byte restoration establishes a dependency on other pacing; it does not prove
  “100% external limiter” or predict observed FPS if that limiter fails. VSync, other hooks and
  driver/presentation behavior still matter.
- No explicit cutscene predicate does not prove every cutscene runs uncapped.
- A proposed immediate 120-FPS A/B is not approved or safe just because the draft suggests it.

Worker: `bc33ffcd-024a-41e0-a435-f69d3c357904`, desktop Qwen 27B. No source or live game changes.
Draft: `~/.pi/agent/sessions/--home-suraj-Projects-Nier-Automata-Rendering--/subagent-artifacts/outputs/bc33ffcd-024a-41e0-a435-f69d3c357904/analysis/runtime/far-recon/local-uncap-review.md`.

## Next evidence, still offline

Trace `__target_fps` consumers / limiter suspend-resume and `SK_RunOnce` definitions at the SAME
commit, then correlate limiter/state/timestep sites to the exact game artifact. Use REA for shipped
binary analysis. Plan 60/90/120 gameplay/menu/hacking/loading/cutscene checks only after verified,
reversible patches and correct cap/timestep restoration are designed; no live test is implied here.
