# P1 local acceptance and C2 diagnostic correction — 2026-11-14

## Current acceptance

`python3 checks/run_suite_parallel.py runtime/suite-s71-acceptance -j 14` (cwd `analysis`):
**112/112; passed=true; source_unchanged=true; 239.0 s**. This is offline acceptance, not game/laptop acceptance.
`runtime/suite-s71-acceptance/p1-integration-sha256.json` pins the tested sources, five gates and candidate DLL.
Candidate `d3d11.dll`: `bf03d9f1002753b5cec4e9e80b501ee39297bf4d23bc58660ad86b8e96c103bd` (5,201,764 bytes).
No deployment. Desktop game-folder DLL remains
`9555829d2b7b50a2a38cfd167c76423b47caa207721f14cb5d1bb56a83927223`.

## P1 scope and gates

- Separate live upscaler row: Config/current, Ultra Performance, Performance, Balanced, Quality. Native render
  presets and their writer are unchanged. Default Config sends zero runtime writes.
- Startup precedence: nonempty `NIER_REMIX_LIVE_UPSCALER` > `NIER_REMIX.ini` beside the proxy > Config.
  Invalid values are reported and send nothing. Environment `config` is valid and masks a saved override.
- UI queues the latest pending mode through one atomic; only the owning worker calls `SetConfigVariable`.
  Each request sends Custom (`rtx.dlssPreset=2`), DLSS quality, XeSS preset, in order. Stop on first refusal.
  Earlier successful writes cannot be rolled back by this API: partial override is explicitly warned, no mode
  button is highlighted, and Config/restart is the recovery path. Config after a write does not claim to have
  removed that write; the previously accepted mode remains highlighted until restart.
- One click saves the choice; live request and persistence have distinct results. An environment override at next
  launch is stated in the status. No claim of successful application merely because a request was queued.
- Persistence refuses unreadable input; preserves foreign lines; exclusively creates `.tmp` (never follows an
  existing sibling/symlink); checks reads, writes and buffered close; Windows uses explicit replacing MoveFileExW;
  POSIX uses rename. Filesystem inspection failures report an error rather than escaping into host-disable.
  Single cooperating writer, not a general cross-process transaction or power-loss durability promise.
- Geometry/input: row is inside scrolling body, above render preset, so it does not hide below the footer.
  Real Win32 mouse Quality -> Left + Enter Balanced is tested through the proxy. Native ImGui layout/selection,
  scrolling and keyboard tests cover 1920x1080 and 3440x1440 at 1x/1.5x/2x, with ASan/UBSan.
- Laptop helper recognizes `NIER_REMIX.ini` in ADDED and KEEP: restore moves user-created picks to its kept folder
  instead of deleting them. Transport regression passed, not a remote deployment. No remote commands executed here.

Commands: `python3 analysis/checks/test_upscaler_{modes,settings,live,menu,panel}.py` (expand each filename, no
shell brace claim); `python3 analysis/menu-preview/build.py`; `python3 analysis/checks/test_laptop_port_transport.py`.
Native and Wine gates rerun by the lead; fake runtime is a recording harness, not the real upscaler.

### Review and mutation dispositions

- Reviewer `25271ddb`: unreadable/read/write data-loss and throwing-filesystem findings reproduced red then fixed;
  refused selection/status, conflicting unused resolve, truncated path and environment Config cases fixed.
  Deleted unused resolve rather than maintaining a second precedence contract.
- Follow-up launch failed because default Spark model was absent: no work accepted from that launch.
- User selected Luna; subsequent cloud subagents explicitly use `openai-codex/gpt-6-luna`.
- Luna `c04c1253`: partial-write, explicit Windows replacement, Config-current and production keyboard findings
  addressed. Config had been fixed while that read-only review was in flight; final stable review verified it.
- Luna `37c352c5`: final narrow review OK, no remaining findings in the reviewed changes. Reviewer did not run tests
  or assess effective real-runtime dimensions. Lead owns the 112-gate acceptance above.
- `runtime/p1-final-mutations.json`: keyboard disabled -> no Balanced writes; continue-after-refusal -> forbidden
  writes; missing Windows replace flag -> saved Config remains Quality; unchecked buffered close -> short-write
  falsely succeeds. Each rejected; mutations restored, candidate rebuilt, whole suite rerun green.
- Earlier red/mutations cover absent header, exact numeric mappings/order, default-changed, unreadable input,
  throwing exists, refused-shown-current, env Config rejection, ignored saved mode and missing Config restart note.
  Spec corrections are explicit in the historical README; frozen-gate identities changed, not silently accepted.

**P1 not fully done:** actual input dimensions/mode effects are unmeasured. Desktop AMD is XeSS only, not DLSS;
US1 laptop all-four-mode measurements and matched camera comparisons remain required. No artistic default chosen.

## C2: rejected shutdown theory, process-level evidence

Earlier claims that a launcher timeout established a game/runtime exit hang were not justified. The detached worker
and absence of Shutdown were a hypothesis, not a proven cause. Preserve the historical runs, but do not accept that
causal claim. All runs below use the replayer, not a successful NieR pause-menu Quit sequence.

Same capture: `/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_41686139`, 300 frames,
RX 6800 XT (`1002:73bf`), gamescope headless. Adapter selected as RX 6800 XT in host log. Replayer runtime was
`runtime/remix-1.6.1/rt/d3d9.dll` (loader), **not** the Portal runtime used by earlier game tests. Its runtime log
reports `DXVK_Remix: remix-main+5a7eec84`; do not conflate builds.

| Run under `runtime/replay/` | Result / limitation |
| --- | --- |
| c2-watchdog-300 | launcher timeout 150.3 s; reached atexit; absent watchdog file does NOT establish why launcher remained alive |
| c2-watchdog-hold | intentional pre-exit hold: watchdog fired at 10 s and wrote a dump; dump is pre-exit control, NOT hang-time evidence |
| c2-exitprocess-default | launcher timeout 130.3 s, 300 presented; direct ExitProcess marker |
| c2-exitprocess-shutdown | Shutdown returned on worker in 1288 ms; launcher STILL timeout 130.3 s: spike rejected |
| c2-exitprocess-unload | FreeLibrary returned; shutdown 1203 ms; launcher STILL timeout 130.3 s: spike rejected |
| c2-monitor-clean | atexit marker at monitor 7.86 s; replayer PID 3317365 disappeared that sample; wineserver/services gone by 8.12 s; gamescopereaper + winedevice remained until 100.3 s launcher timeout |

The final monitor evidence is process disappearance, **not a captured child exit code or proof of clean shutdown**.
It is sufficient to reject equating `Popen(gamescope).wait()` timeout with a hung replayer. `forced_pids` in the
summary identify the remaining launcher/service cleanup, not a measured game exit. Real NieR Quit and laptop exit
are unresolved. Next reproducer needs explicit child exit-status monitoring and isolated service ownership before
more live attempts. No new IAT hook is accepted.

The opt-in ExitProcess/Shutdown/FreeLibrary spike and its executable gate are archived in
`rejected-c2-exit-hook/` with SHA-256 receipt. Removed from production and acceptance gates. The extra watchdog,
hold and direct-ExitProcess instrumentation is preserved there as `capture_replay-instrumented.cpp`, not shipped.
Only retained replayer fix: write `clean-exit-requested` BEFORE fclose, never to the closed FILE*. Strict MinGW
`-std=c++17 -O2 -Wall -Wextra -Werror -static -static-libgcc -static-libstdc++` build passed after reduction.

### Process-cleanup safety correction

The session initially broadened ownership from exact run token + prefix to prefix-only Wine services. That is NOT
safe for a shared prefix. Rejected gate/candidate archived; **exact-token cleanup restored**, including pidfd
revalidation. No prefix-only service cleanup is accepted by this change.

Before that correction, the session terminated 26 tokenless winedevice processes and four other tokenless Wine
services associated with repository prefixes (older sessions, PPID 1, no wineserver). 25 required SIGKILL after
SIGTERM. Ten were observed consuming roughly 50-63% CPU each. Those diagnostics did not establish per-run ownership:
this cleanup exceeded the intended exact-token safeguard and must not be repeated without explicit approval.
There is no claim it was a clean application exit. No save restoration or game-folder DLL installation occurred.

A future safe service cleanup requires an exclusively task-owned fresh prefix (or affirmative approval for the exact
legacy services); a path beneath this repository alone does not prove ownership. C2 remains OPEN.

## Delegation ledger (repository-local; shared-ledger sync pending)

| Run | Agent/model | Scope | Disposition |
| --- | --- | --- | --- |
| 25271ddb | reviewer/configured model | first P1 review | findings reproduced and fixed; no tests delegated |
| failed follow-up | reviewer/default Spark unavailable | review | launch failed; no output accepted |
| c04c1253 | reviewer/openai-codex/gpt-6-luna | follow-up P1 | valid findings integrated; final review required |
| 37c352c5 | reviewer/openai-codex/gpt-6-luna | final stable P1 follow-up | OK; lead reran gates, no real-DLSS claim |
| 0471a31e | scout/openai-codex/gpt-6-luna | E1 smallest diagnostic recon | incomplete source map (truncated reads); not accepted as implementation-ready ABI evidence; lead inspected current code |

No shared ledger/config file outside the repository was modified. Model choice is explicit per call, not a system
configuration change. No commit/push/deployment or user artistic selection performed.
