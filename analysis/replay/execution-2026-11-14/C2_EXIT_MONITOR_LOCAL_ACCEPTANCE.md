# C2.1 child exit-status monitor — local acceptance, 2026-11-14

Offline (Wine console exes in private owned prefixes; mocked replay launches). No game/GPU/replay run. C2 stays OPEN:
no hang-time stack, no real NieR Quit, no fix.

- `checks/exit_monitor.cpp` (1b042027…): `exit_monitor.exe <report> <child> [args]` starts the child, waits on THAT
  process only, mirrors its exit code, writes the report exclusively (`pid=`, `exit_code=`, `elapsed_ms=`, `done=1`;
  launch failure `error=launch`). Windows argv quoting (backslashes before quotes).
- `replay/run_replay.py` (c03b9aae…) opt-in `--exit-monitor [--exit-grace S]`: wraps capture_replay.exe, stops
  waiting S s after the target exited (`exit=target-exited`), records `target_exit` and `launcher_survived_cleanup`
  (keys only with the flag). With the flag, pass = target exit 0 + presented + no errors; forced cleanup of lingering
  launcher/services is still listed in `forced_pids` (not called clean shutdown). Default path unchanged.
- Frozen gate `checks/test_exit_monitor.py`: written aacbdc78…, red "unrecognized --exit-monitor". Oracle defect
  disclosed: its spawn case timed the wine host (which can outlive the target while a grandchild runs - the C2
  confusion itself); corrected to time the report and still require the mirrored code. Original archived
  `exit-monitor-gate-original.py`; corrected 3d1da2c6….
- Worker: local-worker (pair/qwen/qwen3.8-27b) `20f152f1` wrote both files, then timed out at 30 min without a report;
  lead reran gates. Luna unavailable (Codex usage limit).
- Reviewer `dc003508` (anthropic/claude-haiku-5-5): BLOCK on P0 (launch-failure/malformed report crashed run_replay
  after cleanup, losing summary.json) and P1 argv quoting. Hidden gate `test_exit_monitor_hidden.py` 7acb0b61… red on
  both (KeyError 'pid'; `x\"y D:\out"` merged); lead fixed; green. P2s: launcher surviving cleanup now reported;
  keys only with flag. Not changed: build() compiles exit_monitor.exe on every run (mingw already required).
- Mutations red (`runtime/c2-exit-monitor-mutations.json`): grace ignored, exit code ignored, no wait for target,
  exit code not mirrored.
- Suite s78 123/123 (before reviewer fixes); gates rerun green after fixes.
