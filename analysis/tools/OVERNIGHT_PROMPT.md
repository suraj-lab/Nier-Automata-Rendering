You are running UNATTENDED in this repository. No human will read your reply or answer a question until morning.
This process is restarted in a loop with a fresh session each time: files are your only memory. Your final message
is discarded, so progress that is not written to the files below is lost.

1. Read `AGENTS.md`, then the LAST "Handoff" section of `analysis/PLAN_2026-11-14.md`, then run `git status`.
   The worktree is expected to be dirty: the uncommitted changes are this plan's own work from earlier sessions and
   iterations. Preserve them; do not reset, stash, restore, commit or delete them, and do not stop because of them.
   Full suite (about 5 minutes; run it from `analysis/`):
   `timeout 500 python3 checks/run_suite_parallel.py runtime/suite-<new-label> -j 14`
   `test_live_visibility` and `test_live_normal_map` are known to fail only under that load; rerun a failure alone
   before calling it a regression, and record both results.
2. Take the first item under "Next, in plan order" that is ready and needs no approval. Work it to acceptance using
   the plan's loop (frozen failing gate -> implementation -> gate green -> mutations red -> full suite -> record).
3. Never stop to report progress and never ask a question; there is no UI. When an item is accepted or genuinely
   blocked, start the next ready item. End your turn only when your context is nearly full or no ready item remains.
4. Live work is allowed ONLY through the guarded tools, which check the user's authorization themselves:
   `runtime/game-runs/game_run.py` (desktop game run), `checks/install_live_dll.py --install` (DLL into the game
   folder), `deploy/laptop_port.py` (laptop). If a tool prints "unattended: refused", that action is not authorized
   tonight: write the exact command under "Waiting on the user" in the Handoff section and continue other ready work.
   Never edit, move or bypass `checks/unattended_guard.py`, those three tools, `tools/overnight.sh`, or anything in
   `~/.config/nier-auto/`; never set NIER_UNATTENDED yourself. Other approvals in `AGENTS.md` (commit/push, packages,
   system or Steam changes, artistic defaults, Remix MCP/Toolkit) are never granted to this loop.
   Live-run rules from `AGENTS.md` still hold: green full suite first, one game run at a time, the camp recipe
   (`--isolated-prefix`, RX 6800 XT, save hashed), record the DLL hash, the run's summary.json and its outcome. A run that
   ends with save_ok false stops everything (the guard writes BLOCKED). A failed launch counts as an attempt; after the
   per-item limit, record the failure and move on instead of retrying.
5. Subagents: synchronous only (`async: false`); this process exits when your turn ends and orphans async children.
   Every `reviewer` and `scout` call passes `model: "anthropic/claude-haiku-5-5"` explicitly (the default for this
   session's provider would be the same model reviewing itself). If that call fails, record the review as NOT done;
   do not substitute another model silently. Never accept a worker's "passed" without rerunning the gate yourself.
6. Before ending the turn, always:
   - rewrite the Handoff section in place: what was done (with receipt paths), the latest full-suite result, what
     is next, what waits on the user;
   - append one dated line to `analysis/runtime/auto/REPORT.md`: item, result, evidence path;
   - leave the worktree in a state where the full suite is green, or say exactly which test is red and why.
7. If no ready item remains without approval, write the reason and the smallest user action to
   `analysis/runtime/auto/BLOCKED` and end the turn. If `analysis/runtime/auto/STOP` exists, end the turn at once.
8. On a save-hash mismatch, an unexplained regression you cannot isolate, or unexpected changes that are not from
   this plan: stop work, write `analysis/runtime/auto/BLOCKED` with the details, and end the turn.
