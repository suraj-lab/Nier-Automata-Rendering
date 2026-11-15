# Working rules for this repository

## Active plan and request scope

**Project closed 2026-11-15 (RTX Remix route stopped; see the end of `analysis/PLAN_2026-11-14.md`). No plan is
active; do not resume its backlog without a new user decision.** The last plan was `analysis/PLAN_2026-11-14.md`; earlier plans are historical evidence. Change this
pointer explicitly when a successor is accepted, rather than guessing from filename order. Read the active plan's
baseline, task dependencies and evidence before execution.

A request to research, review or improve the plan authorizes that deliverable, not implementation of the entire
backlog. Finish its review/validation without launching game runs or deployments as a side effect.

## Keep executing ready work

During implementation, select the first ready substep in the plan's priority order, finish it, record evidence and
continue immediately. Do not end a turn merely to report progress or ask what to do next. If a task needs the user,
laptop, missing capture or permission, record that exact dependency and continue other independent ready work.
Batch external requests into the plan's session cards. Never mark a blocker, unrun test or rejected spike as done.

Stop only when the requested scope is complete, no safe ready work remains, unexpected user changes need resolving,
or an unexplained failure cannot be repaired safely. State the reason and smallest required action. An unknown
regression must not be left as the accepted result: isolate/revert only this task's changes, preserve diagnostics
and rerun the last known green state. Never reset someone else's work to obtain green tests.

## Safety and baseline preservation

- Run `git status` before editing; preserve user changes. Stop and ask about unexpected/unrelated modifications.
- Nothing is committed or pushed unless explicitly requested. No automatic commit/push instruction in a plan
  overrides this rule.
- Desktop game-folder writes use `analysis/checks/install_live_dll.py`, full SHA-256 pinning and a rollback folder.
  Laptop deployment uses its separately reviewed helper only with explicit permission. Planning is not permission
  to operate remote machines, deploy, change system/Steam settings or write outside this repository.
- Game runs use a copied Proton prefix; verify no save path escapes through a symlink to the real prefix. Hash the
  real save before/after. On mismatch stop runs and preserve both versions; ask before restoring anything. Never
  overwrite newer progress with `save-backup-*` automatically. Audit existing guard behavior before live runs.
- Use the headless RX 6800 XT for desktop rendering tests, never the monitor-driving RX 9070 XT. Verify the adapter
  in the run log. One GPU workload at a time; coordinate inference and do not unload models or kill processes that
  are not task-owned without approval. No package installs or system configuration changes without asking.
- Raw captures are evidence. Preserve them; distinguish transfer completion, structural validation, local hashes,
  source-hash verification and replay readiness. Do not duplicate active transfers or normalize the only raw copy.

## Gates, delegation and acceptance

- Every behavioral change preserves today's default behind a switch or compatibility selection. Demonstrate its
  frozen gate failing for the right reason before implementation, then green and mutation-red. Restore mutations.
- Follow `/skill:frozen-gates`, `/skill:local-delegation` and the active plan's work packages. Delegate bounded code
  against frozen tests, reconnaissance to `scout`, independent review to `reviewer`; use local/laptop workers only
  with resource availability and extracted facts. Lead owns design, integration, real-system actions and acceptance.
- Parallel workflows are for independent packages. One writer per worktree/file set; serialize shared core/fake
  runtime edits. Workflow cloud agents need an explicit provider/model; read workflow-authoring before writing scripts.
- Never accept a worker's “passed” without rerunning its gate. Review callers, fixtures, malformed inputs, cleanup
  and default-off behavior; run relevant regressions and the full suite after integration. Record every delegation,
  including failures. If the shared ledger is outside authorized paths, retain a repository-local receipt and note
  pending synchronization instead of writing outside the repository silently.
- Record exact commands, source/runtime/config/capture identities, selected GPU, red/green/mutation results, review
  dispositions, measurements and limitations next to each task. Separate historical evidence from fresh validation.
- User chooses artistic defaults from labelled comparisons. No agent substitutes its aesthetic judgment, treats
  AMD XeSS measurements as laptop DLSS results, or calls a forced process termination a clean shutdown.
