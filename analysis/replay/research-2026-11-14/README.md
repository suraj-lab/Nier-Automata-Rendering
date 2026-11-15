# Planning research receipt — 2026-11-14

## Authority and scope

Deliverable: expanded [`../../PLAN_2026-11-14.md`](../../PLAN_2026-11-14.md) and repository `AGENTS.md`.
This directory preserves delegated research, including uncertain or superseded recommendations. The plan's
“Findings that change the original plan” section is the correction index. A report's existence is not proof
that its agent finished successfully or that the lead verified every assertion.

No feature implementation, new deployment, commit or push was performed in the final document-editing pass.
Earlier research/replay activity is retained below as historical evidence, not presented as a fresh validation run.

## Delegated research ledger (repository-local receipt)

Initial workflow: `plan-1114-research-mwg6u9fk-epz2wf` (ten research assignments).
Reported completion: 709.2 seconds, $4.78; at least one child returned a rate-limit error despite writing a report.
Do not classify every initial child as successful from the workflow completion notification.
Retry workflow: `plan-1114-research-b-mwg7ff37-hs0jdw` (`plan_1114_research_b`), three assignments,
reported complete in 385.4 seconds, $0.37. Model identities are not reconstructed from memory.

| Assignment | Retained report | Outcome / verification disposition |
| --- | --- | --- |
| Historical plan/state digest | `plan_state_digest.md` | Partial report retained despite reported rate-limit failure; capture, AMD/DLSS and shutdown claims corrected in plan |
| Presentation reconnaissance | `p2_present_path_recon.md` | Retry completed; distinguishes existing device startup, native handoff and presenter ownership |
| Menu/DLSS reconnaissance | `p1_menu_dlss_recon.md` | Retry completed; enum/layer/worker details carried forward with runtime-identity prerequisite |
| Effects reconnaissance | `e1_effects_recon.md` | Report retained; small-draw omissions and invalid drop-tally fields carried forward; “exact composite” rejected |
| Laptop operations | `c_laptop_ops_recon.md` | Report retained; installer/config/log hazards became C3 gates, not permission to deploy |
| Sky/water/grade | `w_sky_water_grade_recon.md` | Retry completed; unknown CB semantics and water identification remain explicit |
| Online presentation/FG | `web_remix_present_framegen.md` | Primary references retained; other-client failures treated as test scenarios, not universal conclusions |
| Online NieR rendering | `web_nier_rendering.md` | Developer/material references retained; live capture/shader proof still required |
| Online effects/sky/water API | `web_remix_effects_sky_water.md` | API/source candidates retained subject to build compatibility |
| Online debug/alternative FG | `web_ops_debug_framegen_alt.md` | Unsupported teardown inference/forced-exit acceptance and lsfg-vk adoption rejected |

Earlier workflow result references (outside repository, read-only provenance):
- `~/.pi/workflows/projects/nier-automata-rendering-2eba3c0bcb31/runs/plan-1114-research-mwg6u9fk-epz2wf.json.result-705217254e3748fa0da1e70886c6ff8ec71940b043a6fa8ae75aa176471a269d`
- `~/.pi/workflows/projects/nier-automata-rendering-2eba3c0bcb31/runs/plan-1114-research-b-mwg7ff37-hs0jdw.json.result-6b3504e3cdd4624b9eb651ac904b3ae36dc9814c71455be667cd88407d4d6819`

### Independent review attempts

1. `reviewer` launch: configured `openai-codex/gpt-5.3-codex-spark` was absent from the active model registry.
   No review ran. Tool suggested `openai/gpt-5.3-codex-spark`.
2. Explicit retry with suggested provider/model: run `7e2804f8-28c5-4fc6-ba9b-432c7bf8a794`, mission
   `9e8bbedd-3aa3-4410-a17f-9fce90cb6270`. API returned HTTP 404, `model_not_found` / unavailable access.
   **Independent review is blocked, not passed.** No further automatic retries or silent fallback were made.

Lead performed local consistency/path/link/diff checks, but these are not a replacement for independent review.
A future review should focus on the new task dependency graph, source/build claims, calibrated truth and permission
boundaries. Shared delegation-ledger synchronization outside this repository remains pending permission; this
receipt ensures failures are not omitted in the meantime.

## Capture/replay evidence retained

Under `../../runtime/laptop-play-20261114/`, both completion markers exist. Final planning-pass local recount:

| Frame | Files | Sum of bytes |
| --- | ---: | ---: |
| `frame_67279062` | 22,380 | 5,813,513,277 |
| `frame_67078468` | 29,363 | 14,317,920,437 |

These agree with the earlier remote inventory. This final pass did not contact the laptop or compare remote
cryptographic manifests. Full source-byte identity remains unverified. SCP hard-link loss is a packing issue,
not evidence that file content was corrupted. Raw data was not normalized/relinked in this pass.

Fake replays: `../../runtime/replay/n1-fake-67279062` and `n1-fake-67078468` (same parent).
Real diagnostic replays: `../../runtime/replay/w0-desert-67279062/shot-899.png` and
`../../runtime/replay/w0-water-67078468/shot-899.png`; small JPEG copies in this directory.
Image metrics are in the plan; noisy replay performance was excluded from benchmark claims.

Historical suite receipt re-read: `../../runtime/suite-s56/full-suite.json`:
`passed=true`, `source_unchanged=true`, `total=94`, `wall_seconds=246.3`, `jobs=14`.
The suite was **not rerun** for this documentation-only revision.

## Final-pass validation

- `git diff --check`: passed after plan, policy and receipt creation.
- Task table and task specification IDs: 17 each, unique and matching.
- Local Markdown links in the plan and this receipt: all resolved; original-track coverage and fenced-block balance passed.
- Named existing runner/installer/terrain/menu/transport-test paths checked; corrected shader parser location
  from the speculative `replay/dump_shader_decls.py` to `checks/dump_shader_decls.py`.
- Verified suite runner's documented command shape directly from `checks/run_suite_parallel.py`; no suite run.
- Rechecked old plan's actual L1 screening bounds and final camp residuals. Observed residuals are now explicitly
  distinguished from approved multi-area tolerances, rather than referring to nonexistent universal thresholds.
- Refetched CGWorld's developer article, the pinned Remix API header, and Minecraft issue #54 via the web tool.
  This confirms access to primary references, not exhaustive verification of all online research assertions.

Unrelated pre-existing `.pi/` contents were left untouched. Temporary draft fragments under `/tmp/plan14/parts/`
are superseded and **not** the active plan: they contain rejected commit/save/shutdown/compositing assumptions.
