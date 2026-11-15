# Execution receipts — 2026-11-14 plan

**Latest:** [P1 local acceptance / C2 correction](P1_C2_LOCAL_ACCEPTANCE.md): suite s71 **112/112**, Luna final review OK. C2 shutdown hypothesis rejected; launcher timeout did not prove child hang. Older sections below are historical, not current acceptance.


User approved the pre-existing dirty tree as baseline and requested uninterrupted plan execution. No commit/push, remote operation, live deployment, system change or live-game permission is inferred.

Baseline HEAD: `de1f07cb0ee0f25de9e50553aa199a1271c5b579`.
Pre-existing changes: `AGENTS.md`, `analysis/PLAN_2026-11-14.md`, `.pi/`, research-2026-11-14 reports/images. Preserve them.

## Delegation ledger (repository-local; shared-ledger synchronization pending)

- A0 scout launch: failed before execution. Configured `openai-codex/gpt-5.3-codex-spark` is absent from active registry; tool suggested `openai/gpt-5.3-codex-spark`. No child/code/output produced. Gate: none; scope: clean. Lead continued reconnaissance directly; no CLI substitution.

- A0 parser worker: `31bfceba-2089-4590-9e99-f795490fcfea`, local-worker, desktop `pair/qwen/qwen3.8-27b`; one bounded implementation, only `checks/dump_shader_decls.py` changed by worker. Frozen gate SHA-256 `2b75bdc9cd0b9125f19946e5c060635565c508703360d177581ded265a5f283a`; lead reran green. Hidden malformed-container gate initially rejected worker's missing declared-size validation; lead added declared-size/header-overlap, variable extent and explicit SM4/5 checks, both gates green. Offset-origin mutation red (`SM4: wrong RDEF origin/stride`), restored. No runtime/game operation. Scope: clean. Shared ledger sync pending.
- A0 safety design reviewer: `7b7c6a26-0649-4b0c-9b0c-b4d97523e4ed`, read-only reviewer using registered `openai-codex/gpt-5.6-luna` (Spark absent; user specifically requested Codex provider). Result: BLOCK on three findings; all converted to regression cases and fixed (legacy launcher disabled, replay finally/ownership cleanup, reporting errors retained). Registry discovery was `pi --list-models`, not a substitute delegation CLI.

## A0 — active

Caller inspection found `guard.sh` called by `runtime/game-runs/g2-drive.sh`; `game_run.py` has no other Python/shell callers in checks/replay/game-runs. Both guards currently restore historical backups over changed real saves: unsafe and prohibited. `game_run.py` matches process environment by substring and scans unrelated games globally; tests must cover exact ownership and failure cleanup.

Baseline suite: `runtime/suite-s56/full-suite.json`, 94/94, 14 jobs, 246.3 s (historical, not fresh).

Hardware (live PCI enumeration): RX 9070 XT `03:00.0` / renderD128 (monitor GPU, prohibited for renders); RX 6800 XT `47:00.0` / renderD129 / `1002:73bf` (headless test GPU); integrated Raphael `5c:00.0` / renderD130. Existing LM Studio Qwen 27B llama-server PID 219866 is not task-owned; do not stop/unload it. No game/Wine/gamescope process observed during initial audit. No rendering benchmark authorized or run.

Suite audit: discovered tests use mocked/fake runtime and Wine prefixes; all 20 tests calling `wineserver -k` explicitly set `WINEPREFIX`; inspected wrappers use repository-local isolated prefixes and software rendering. `test_prepass_rule_captures.py` references a game capture path read-only. Transport tests mock subprocess execution.

**Preflight correction / limitation:** the first audit missed `test_shader_capture.py` using `Path.home() / '.wine-shader-gate'`; that test creates/removes its prefix outside the repository when HOME is not sandboxed. The first fresh 97/97 suite therefore is NOT an entirely repository-contained safety receipt. No real save fixture was used, and no additional external cleanup was attempted. Fixed at the suite entry point: HOME, XDG cache/config/data/state and TMPDIR are now under the suite output. `test_suite_sandbox.py` was red before implementation, green afterward, HOME-omission mutation red (`HOME escapes suite receipt`), then restored. Snapshot checks now include all checks Python helpers, not only test files.

## Additional delegation outcomes

- `41ae4555-bbed-4c7c-8c65-149de4faa22c`: Codex reviewer, read-only A0/A1 follow-up. BLOCK: RDEF lower table bounds, negative candidate index metadata, malformed shot conversion losing summary. RDEF/shot findings became failing gates and were fixed. The negative-index issue remains a documented defect of the isolated, rejected A1 candidate; production packer was restored, not represented as newly hardened.
- `17826a90-7f8d-4b9b-bc3e-7f68e73fb53d`: desktop local-worker `pair/qwen/qwen3.8-27b`, C3b implementation, one round, only `checks/terrain_bake.h` written. Lead reran native gate, integrated switch/cache call sites, reran integration gate and both mutation checks. Scope clean; no worker deployment.
- `aefb34c0-dab5-4246-a903-f8d380de3657`: Codex reviewer, read-only A0/C3b review. BLOCK on terminal malformed landed DDS retry churn and retained `baked_paths`. `test_terrain_mips_hidden.py` reproduced ten failures across legacy/opt-in variants; lead fixed terminal grey retention/failure counting and path release after material destruction. Added zero-ID validation. Hidden and integration gates then green. Review findings were dispositioned by lead tests; no claim of an unperformed final reviewer approval.

All shared-ledger synchronization remains pending; no outside-repository ledger was written. Token/cost values are unavailable and not invented.

## A0 evidence / current waiting scope

- Frozen safety gate: `python3 analysis/checks/test_game_run_safety.py`, SHA-256 `933c165cd4b9978a5be04f944741170400d5727130b30e0e80064223473258d1`. Red witnessed old helper overwriting **synthetic** newer progress; green after report-only snapshots; substring-token mutation red, restored. Hidden cases cover cleanup/snapshot failure summaries and malformed replay shots. No real save was used as test data.
- Parser gate: `python3 analysis/checks/test_shader_decls.py`, SHA-256 `2b75bdc9cd0b9125f19946e5c060635565c508703360d177581ded265a5f283a`; SM4 absolute origin/24-byte and SM5/40-byte fixtures, two pinned real shaders, malformed hidden cases. Offset-origin mutation red and restored. Supplemental bounds findings also red before fixes.
- `runtime/a0-shader-audit/identity.json`: full local shim, Portal runtime, installed desktop proxy, header and replay config hashes. Cross-compiled `abi.cpp`/`.a0abi` section proves header 0.6.6 layout: 176 bytes; CreateMaterial 8, SetConfigVariable 80, Startup 152, Present 160. PE exports expose `remixapi_InitializeLibrary`; this is **static evidence, not loaded runtime API compatibility proof**. Laptop paths/hashes remain unverified.
- `runtime/a0-shader-audit/command.json`, `disassemble.log`, `lit.asm`: cross-compiled existing `checks/disassemble_shader.cpp`; CPU-only Wine D3DDisassemble succeeded in an isolated repository prefix/home. It corroborates used cb2 indices, but its output does not include RDEF variable names. No device/game/shader execution was requested.
- `runtime/a0-shader-audit/declarations.json`: corrected declarations for 625 local pixel shaders. `scene-cb2.json` decodes camp/desert/pond: lightColor at 0 = (6,5.1,4.8), (8,7.2,4.8), (10,9,7); lightVec 16, fog parameters 32, fog color 112. Full source/buffer hashes are in the report. Duplicate RDEF names make name-only binding joins ambiguous: retained the rejected name-only audit separately and disambiguated these three CB2 records by unique exact captured buffer size. No generalized name-only binding inference is accepted.
- Legacy ignored `runtime/game-runs/g2-drive.sh` is disabled before any action; it had ignored guard failures. Tracked `guard.sh` now requires a unique state directory and delegates report-only checks. Other historical launchers are not endorsed.
- Fresh suite `runtime/suite-s57-a0/full-suite.json`: 97/97, 14 jobs, 265.2 s; HOME limitation above. Superseding integrated receipt pending below.

**Status: waiting — actual loaded game/runtime API identity, approved live repeat baselines and remote identity comparison.** Local guard/parser substeps complete; do not infer approval for live runs from synthetic gates. Source manifest and final suite receipt are recorded after integration.

## Final local acceptance state

- Acceptance suite `runtime/suite-s60-acceptance/full-suite.json`: **104/104 passed, `source_unchanged: true`, 14 lanes, 249.6 s**, run on the stable source after every review fix. This is the only accepted suite receipt. Earlier `suite-s57-a0` (97/97, pre-sandbox), `suite-s58-integrated` (all tests passed but `source_unchanged: false` because review edits landed mid-run) and `suite-s59-final` (102/102, superseded by the later label/sanity gates) are historical. A run counts only when `passed` and `source_unchanged` are both true. `source_unchanged` covers `checks/*.py`, `*.h` and `*.cpp`, so helper edits invalidate a receipt instead of passing silently.
- `checks/test_game_run_safety_hidden.py` gained a cross-platform label case that failed against the old `Path.name`-only check (`unsafe cross-platform run label accepted`): `..\\escape`, `drive:escape` and empty labels reached `mkdir`. Fixed with one shared `safe_label()` in `checks/game_run_safety.py` used by both launchers; `checks/test_run_label_safety.py` (SHA-256 `db76475f887105477825e761f00ed9448ae3cc85f600fba4748bb88ded74aae9`) was red before implementation and now covers the negative set plus unchanged safe labels.
- `checks/test_shader_decls.py` had a harness hole: an empty candidate finished with exit 0 and no output, so the gate could not distinguish "passed" from "did nothing". Proven with a `sys.exit(0)` candidate, then repaired to fail-with-JSON. `checks/test_shader_decls_sanity.py` now keeps that regression frozen. The earlier gate hash is superseded; final identities are in `runtime/a0-shader-audit/source-manifest.json`.
- Suite snapshot pinning covers every `checks/*.py`, so edits to shared helpers such as `game_run_safety.py` during a run now invalidate the receipt instead of passing silently.
- Shared raw evidence (shaders, `NIER_SCALE.log`, `remix.log`, `recording.mp4`, `rec/`, screenshots) is pinned read-only in `runtime/a1-intake-20261114/shared-evidence.jsonl`, SHA-256 `f88638104b9c40a36622e76bd8a78dda363875a80b2843490c74e0c522c3935e`.
- Fresh opt-in terrain evidence: `python3 replay/run_replay.py c3b-mips-fake-desert runtime/laptop-play-20261114/frame_67279062 --mode fake --frames 400 --frame-ms 16 --env NIER_REMIX_LIVE_TERRAIN_MIPS=1` produced three distinct `_mips1.dds` assets (two 512²/10-level, one 256²/9-level), each byte-exact to the expected chain length, recorded in `runtime/replay/c3b-mips-fake-desert/mip-assets.json`. The default-off path stays byte-identical to the original implementation, proven by compiling the HEAD header separately.
- Ignored `runtime/game-runs/g2-drive.sh` carries a durable minimal disable patch at `legacy-launcher-disable.patch` (2 added lines, no other change); it cannot fail open on a guard error.
- `runtime/a0-shader-audit/source-manifest.json` pins every changed source/gate and the copied-prefix save directory; that prefix resolves inside this repository and is not the real save folder.

## W5 — evidence only, no anisotropy shipped

`python3 analysis/replay/execution-2026-11-14/hair_evidence.py` → `runtime/a0-shader-audit/hair-candidates.json` (corrected declarations, three captures, all referenced bytecode present): camp 3 candidate shaders / 31 draws, desert 2 / 9, pond 2 / 13. Every candidate declares `g_AnisoParam1`/`g_AnisoParam2` (plus `g_SecondarySpecParam` on the larger shaders) and is recorded with opaque blend state, depth write on, full-viewport, texture/sampler inputs and shader SHA-256.

Not done, deliberately: no anisotropy value is sent and no material mapping changed. Plan W5.2 requires verifying the runtime's anisotropy implementation and an available tangent basis; declaration presence does not prove a tangent texture is sampled, and adding an unused map is explicitly out of scope. Scalp/lashes/alpha-card separation and the hidden-draw check also remain open — all candidates happen to be opaque, so alpha-card hair is not in this set. User visual pick and shimmer/motion comparison remain external.

## A1 — rejected spike, production baseline restored

- Frozen unit gate preserved unchanged at `test_pack_capture_content_frozen.py`, SHA-256 `c1fbf90b1a05fa5b1a56a6eb6be4fe9fdcc3becc8bf2687fcb664f96287b1ed1`. Invoke `python3 analysis/replay/execution-2026-11-14/run_rejected_packer_gate.py`; this proves UNIT behavior only, not integration acceptance. Red with old inode behavior, green candidate, inode-only mutation red, restored. Candidate code/diff retained beside this receipt; it is not imported by production or discovered by the suite.
- `python3 analysis/replay/execution-2026-11-14/intake_receipt.py` originally hashed both raw folders and packed to `runtime/a1-intake-20261114/`. This script was subsequently changed to import the isolated candidate explicitly; original runtime receipts are retained. Local manifests: desert 22,380 files / 5,813,513,277 bytes, SHA-256 `b83ea9766026c70eccc90465c2b0dbb68a2f8bda2dc5adde4ee7080babc6f947`; pond 29,363 / 14,317,920,437, SHA-256 `6c6f6251b394569be473e43c02c39f5f39e66cb615c85a1afdece9a2d10b9d68`. Remote source hashes remain unverified.
- Candidate packed buffers 112/170; hash times 4.567/8.868 s, pack times 3.384/8.175 s (single local observations, not benchmarks). Raw folders were not rewritten, relinked, normalized or retransferred.
- Actual candidate commands (from `analysis/`): `python3 replay/run_replay.py a1-content-fake-<frame> runtime/laptop-play-20261114/frame_<frame> --mode fake --frames 400 --frame-ms 16 --dedup-content`, frame IDs 67279062 and 67078468. `--dedup-content` has since been removed from production; do not reuse that command there. Both presented 400, missing shaders/textures/bad layouts zero, no forced cleanup. **Rejected:** meshes 176/319 instead of 183/347; pond frame-200 instance-triangle sum 887,169 instead of 887,306. Equal content is not enough to preserve this hook's buffer-pointer-derived geometry/material identity.
- Production `replay/pack_capture.py` restored exactly to HEAD by reversing only this task's patch. Known-good controls: `python3 replay/run_replay.py a1-control-inode-<frame> runtime/laptop-play-20261114/frame_<frame> --mode fake --frames 400 --frame-ms 16`. Both exit 0, no forced cleanup/errors; restored meshes/instances 183/183 and 347/745, textures 163/320, lights 5/7. All 51,743 raw files were rehashed after replays: `post-replay-raw-verification.json` matches original local SHA-256 manifests.

**Status: waiting — identity-preserving design/new authoritative logical-buffer identity, then frozen real-capture accounting gate.** Count/size acquisition, local hashes and restored default replays are verified. Content-deduplicated replay is NOT accepted or shipped; no source-hash or original-color truth claim.

## C3b — local code/gates complete; visual/runtime acceptance waiting

Changed: `checks/terrain_bake.h`, `live_scene.h`, `remix_live.cpp`; default unchanged. Opt-in `NIER_REMIX_LIVE_TERRAIN_MIPS=1` emits full RGBA8 sRGB DDS chains, filtering linear RGB/alpha using integer-area bins. Versioned `_mips1.dds` names and material keys avoid stale one-mip assets. Terminal malformed landed inputs retain grey without per-frame destruction/recreation; teardown releases filename strings after material destruction.

- `python3 analysis/checks/test_terrain_mips.py`, frozen SHA-256 `4af01cbb0663625d7a07b8460cb92308f9881c0b8d6810bc000ac4e286c529fd`: red missing full-chain API, green worker/lead; header-only payload mutation red and restored. Asserts 512²/10 levels/1,398,248 bytes, flags/caps/pitch, level-zero equality, linear-light colors, odd tail and invalid image shape.
- `python3 analysis/checks/test_terrain_mips_integration.py`, frozen SHA-256 `5587ed7093545e24eaff259e809e130260d8c4ae4a03fe483edb6497aeaade92`: red missing switch, green with actual scene/material/cache path; disabled caller mutation red then restored.
- `python3 analysis/checks/test_terrain_mips_hidden.py`: review-derived malformed/late inputs and teardown green after witnessed ten failures.
- `runtime/c3b-legacy-compat/receipt.json`: compiled original HEAD header separately, default DDS output byte-identical for 1×1, 3×5 and 512² finite channel ramps. No comparison against the same new implementation masquerading as a baseline.

**Status: waiting — approved real-runtime fresh asset warning/image comparison and laptop cycle.** No artistic/default selection, live install or claim that fake/native tests prove runtime mip warnings are resolved.

## Other ready inspection completed / remaining dependency map

`python3 analysis/replay/execution-2026-11-14/inventory_candidates.py` produced `runtime/a0-shader-audit/candidate-inventory.json`: camp/desert/pond recorded draws 3382/923/1176; zero missing referenced PS files, zero emission-keyword shaders, 2/4/2 water/effect-keyword shaders. These are declaration-keyword hypotheses and exact draw-state censuses, NOT proof of emission absence or accepted effect classes. Old captures omit small passes and needed target/blend/view metadata.

## Status at end of this execution pass

Locally gated and green: A0 safety guards, shader-metadata parser, suite isolation, C3b opt-in terrain mips, W5/W4/E1 declaration evidence. Rejected and reverted: content-deduplicated capture packing. Everything else needs an external action listed in `SESSION_CARDS.md`: approved live game/capture/rendering slots, loaded-runtime API identity, a PowerShell-capable deployment test environment, laptop access, or the user's labelled visual picks. No commit, push, deploy, remote command, system setting change, model unload or artistic default was performed.

- C3a: inspected helper/transport tests; no local PowerShell executable, full original laptop DLL pin absent. Current helper's `.off` collision handling, direct-run env deletion, log/config restore handling and short hash pin are not cleared for deployment. Needs executable PowerShell transition gates and approved laptop cycle; no remote command executed.
- T1/C2/D1: need approved game/capture/owned exit reproducer and rendering resource slot; safeguards first, no game run side effects.
- P1/R2: A0 loaded runtime identity/capture contract prerequisites not satisfied; no unverified runtime option/control or format deployment implemented.
- E1/W1/W3/W5: A1 identity-preserving replay and T1/expanded capture facts remain dependencies. W4 initial inventory insufficient for data-backed emissive fixture; US2 evidence required before enabling intensity.
- P2 waits P1, actual NVIDIA/HAGS/runtime capability and approved spike. W2 waits calibrated pairs and accepted material/effect variants. Z1/C1 cannot accept an unfinished backlog or substitute AMD/fake measurements for laptop play.

External requests are batched in [SESSION_CARDS.md](SESSION_CARDS.md); no repeated user questions, commits, pushes, deploys, model unloading or system changes were performed.

## Orchestration receipts (2026-11-14, session 2)

| Call | Agent / model | Purpose | Outcome |
| --- | --- | --- | --- |
| workflow `nier-w2-local-p1-recon-mwge07pm-mijx7s` attempt 1 | local-worker + 2× scout, `scout`/`reviewer` agentTypes, codex models | W2 metrics impl, P1 key recon, patch-anchor recon | **Failed**: `unknown agentType "scout"; using default tools/model`, then `Codex error: The usage limit has been reached`. 0 agents completed, nothing written. Recorded as a failure, not retried blindly. |
| same run, resumed | implementation `pair/qwen/qwen3.8-27b`; recon+review `deepseek/deepseek-flash` | same packages | Workflow agentTypes are not registered, so every call names its model explicitly. Reviewer reassigned to deepseek as instructed. |
| subagent `525063d7-b6c5-4b3f-a4ba-8ff4d79e121a` | laptop-worker (Gemma) | run-lock implementation against frozen gate `139fe393…` | dispatched; lead must rerun the gate |
| frozen gate `checks/test_run_lock.py` | lead | one-run-at-a-time enforcement | red `no run lock API`; gate SHA-256 `139fe393ae40627830863c126ed2ff551dcfeb50de813327369db1f1a6cf2b58` |

No token/cost figures are reported because no receipt provides them. Shared-ledger synchronization is still pending.

## Cross-run contamination (lead error, recorded)

`t1-remix-1440p16x9` and `t1-original-1440p16x9` were started back-to-back and ran concurrently. Result: the Remix
side's shots are 320×240 and the original side produced none — both runs are invalid for any purpose and are kept
only as the motivating evidence for the run lock. The launcher had no mutual exclusion; nothing else was affected
(each run still killed only its own token/prefix children, and both reported `save_ok: true`).

## Ultrawide finding (D1/P2, new)

`t1-remix-clean` at 3440×1440 is **pillarboxed**: content occupies x 440..2999 (2,560 px wide) with 440 px black bars
on each side, content aspect exactly 1.778 (16:9). The game's own frame fills the full 2.39:1 width. So Remix renders a
16:9 image and the handoff centres it, which both wastes 25.6% of the frame and changes the horizontal FOV relative to
the original. Any W2 comparison at 3440×1440 is invalid until this is understood; the earlier camp "crush 25.6%"
figure is exactly these bars, not a grade defect. This is a real D1/P2 constraint that the plan did not anticipate.

## Session 2 outcomes (orchestrated)

Fleet results, recorded as delivered:

| Delegation | Model | Outcome |
| --- | --- | --- |
| workflow attempt 1 (2 scouts + local-worker + reviewer) | codex / qwen | failed: unknown `agentType` names in workflows, then `Codex error: The usage limit has been reached` |
| workflow resume, W2 metrics | `pair/qwen/qwen3.8-27b` | failed: `Subagent produced no assistant output`; no file written |
| workflow resume, P1 + patch-anchor recon | `deepseek/deepseek-flash` | completed (result delivery pending; not accepted as evidence yet) |
| workflow resume, review | `deepseek/deepseek-flash` | ran after the implementation failure, so it had nothing to review |
| laptop-worker `525063d7` | `pair/gemma-4-31b-it` | failed: `no available node advertises the requested model`; laptop does not advertise Gemma right now |

Lesson recorded: workflow `agentType` values are not the subagent registry names, so every workflow call names its
model explicitly. A worker that produces no output is a recorded failure, not a silent retry target: the lead wrote
`replay/pair_metrics.py` instead.

## New gated work this session

- **Run lock** (`checks/game_run_safety.py`, `runtime/game-runs/game_run.py`): one run at a time, live owner never
  stolen, stale locks only with `recover_stale=True`, corrupt lock = refusal, clean refusal message.
  Gate `checks/test_run_lock.py`. Red: `no run lock API`. Green after implementation. Three gate defects were found
  and fixed by running it: a foreign *live* owner was unexercised (mutation slipped through until the case was
  added), the harness patched the shared `subprocess` module and broke itself, and the CLI case depended on a stray
  lock file so it passed standalone by luck and failed in the suite. Mutations now prove both the live-owner refusal
  and the launcher-level refusal fail closed. Lock path is overridable only for tests via `NIER_RUN_LOCK`.
- **Display size** (`--size`): gamescope W/H now explicit; gate `checks/test_game_run_size.py`.
- **Pair metrics** (`replay/pair_metrics.py`): per-region L1 statistics with exclusion masks, gate
  `checks/test_pair_metrics.py`. The gate's own hand-computed expectation was wrong (87.5% crush, not 100%) and was
  corrected before implementation; the gate cross-checks the whole-frame numbers against `frame_tools.stats`.

## Measurements that constrain the plan

- Ultrawide: Remix renders 16:9 and is pillarboxed inside 3440×1440 (440 px bars each side, content aspect 1.778).
- The game does not accept 2560×1440: it stays at 1600×900, Remix stays `paused`, and screenshots come back 320×240.
  Only the monitor's own 3440×1440 mode produced a full-size render. Changing display modes is a system change and
  needs explicit approval, so a matched 16:9 pair is not currently obtainable.
- Per-region report `runtime/a0-shader-audit/camp-region-report.json` shows Remix crush concentrated in every region
  that overlaps the pillarbox bars, which is why the earlier whole-frame "grade" reading was wrong.

## Acceptance

`runtime/suite-s63-acceptance/full-suite.json`: 107/107, `source_unchanged: true`, 14 lanes, 249.0 s. The earlier
`s62` run failed `test_run_lock.py` (`refusal did not mention the lock`) and is retained as the evidence that the
gate flaw was real.

## Aspect blocker, tested rather than assumed (session 2)

Two candidate workarounds for the ultrawide pillarbox were tested offline against the existing camp pair:

| Test | Result |
| --- | --- |
| Remix content (x 440..2999) vs the original's same crop | mean abs diff 49.2 grey levels |
| Best horizontal alignment of the original crop, ±500 px, step 20 | optimum only at the search edge (dx=440, 45.2) — never converges |
| Best vertical alignment, ±60 px | exact at dy=0 |
| Is the Remix frame a scaled-down crop? | 0.90x..1.10x all worse than 1.00x (49.8-52.3) |

So the Remix 16:9 frame is **not** a crop, a shift or a rescale of the game's 2.39:1 frame: the two images differ in
horizontal field of view, not by a transform that can be undone offline. A matched pair therefore needs the game to
present 16:9, which means either a display-mode change (system configuration — not done, needs explicit approval) or
finding the game's own resolution control (no registry keys exist in the copied prefix; `Graphic.ini` carries only
`VideoCard` and `Output`, so the value is written by the game itself).

Consequence: W2 grade fitting stays blocked on acquisition, while everything else (safety, capture pipeline, region
tooling, terrain, shader metadata) is unblocked. This is recorded as an external dependency, not as a task failure.

## Independent review of the region tool (reviewer `6a36d3f1`, deepseek-flash)

The review could not rerun the gate (no shell tool) and said so, so the lead reran it. It confirmed the metric
definitions are arithmetically identical to `frame_tools.py`, that the pixel tiling has no gap or overlap, and that
edge clamping always yields at least one in-bounds pixel. Three real defects, each turned into a failing gate case
before the fix:

1. **P1 `frame_delta` ignored the exclusion mask** — the headline number stayed dominated by the pillarbox bars and the
   idle-animation character while the regions reported small residuals, exactly the misreading the plan fights.
   Now masked; a mutation that unmasks it fails the gate (`exclusion not applied to frame_delta: 5.0`).
2. **P2 `exclude` silently coerced falsy junk** (`0`, `""`, `null`, `{}`) into "no exclusions". Now a ValueError; the
   coercion mutation fails the gate.
3. **P2 the 7x3 case did not distinguish `round` from `ceil`** — the review proved `round(0.5*7)=4=ceil(3.5)`. Added a
   width-6 case where banker's rounding goes down (`[0.75,0,1,1]` -> 2 columns, ceil would give 1).

Also added the missing non-identical path, which pins `identical: False` and the 0..255 grey-level scale of
`frame_delta` (previously only the all-zero case was exercised).

Gate is now `test_pair_metrics.py` SHA-256 `74a5d3f3c449db15a58db24f853e46411ea17ccd1272253658b49006427b5d8d`;
acceptance `runtime/suite-s65-acceptance/full-suite.json`: 107/107, `source_unchanged: true`.

Corrected region report (`runtime/a0-shader-audit/camp-region-report.json`, masked delta 53.9 over 634,336 excluded
pixels) still mixes the pillarbox into every region that spans the bars, so it is a tooling validation, not a grade
verdict.

## Ultrawide, resolved as far as the build allows (two workflow recons + one probe run)

Two independent recon agents read the handoff code and cross-checked each other. Corrections to my own earlier
claims, which stand:

- **My "the handoff centres it" was wrong.** Both handoff paths are size-exact and full-frame
  (`remix_live.cpp:1296-1298` RTV equality, `:1329-1335` clip-space full-screen quad, `:1448`/`:1453-1455`
  whole-frame `UpdateSubresource` at `desc.Width*4`), `make_surfaces` hard-fails on any size mismatch (`:716-731`),
  and the aspect handed to Remix is the target's own 2.389 (`:842` → `:941` → `nscn_scene.h:181`). So nothing in this
  repository places or centres a 16:9 region; the bars arrive inside Remix's composited output.
- The cross-check also caught the first report claiming `rtx_context.cpp:748-758`/`:1259-1261` were "axis-separate
  copies" (they are the composition dispatch and a sparse-rendering warning) and that `rtx.resolutionScale = 1.0`
  was a candidate fix (a double no-op: the installed conf has it commented out, and the XeSS branch ignores it).

**Probe run that settled the stage** (`game-runs/t1-remix-noupscaler`, run-local conf via `DXVK_RTX_CONFIG_FILE`,
nothing written to the game folder): with `rtx.upscalerType = 0` the 3440x1440 frame is **full width**
(`content x 0..3439`, bars L0 R0) instead of pillarboxed. So the 16:9 fit lives in the upscale stage — XeSS at a
2.389 aspect. `save_ok: true`, only the run's own children killed.

**But it is not a usable pair.** The labelled sheet `t1-camp-3440-matched-pair.jpg` shows the no-upscaler frame is
magnified relative to the original (2B and the terminal fill much more of the frame), i.e. the internal render
resolution no longer maps 1:1 to the output. The per-region numbers from that pair (upper wall 0.480 -> 0.253 etc.)
are therefore **framing artefacts and are not reported as grade findings**. This corrects the intermediate reading.

State of the aspect question: a valid paired capture needs the game to present 16:9 (display-mode change: not done,
needs approval) or a working internal-resolution mapping for the ultrawide upscale path (unresolved in this runtime
build). W2 grade fitting stays blocked on acquisition; the tooling, guards, terrain and shader work are unaffected.

## P1 started: selection core and persistence (laptop lane back up)

The PAIR laptop node advertises its model again, so the laptop lane is usable. Two frozen gates were written by the
lead and implemented by `laptop-worker` (Gemma), then re-verified by the lead:

| Gate | SHA-256 (frozen) | Result |
| --- | --- | --- |
| `checks/test_upscaler_modes.py` | `e694d9be98284031e18112d5f1fd3b771dbbf33c22237e91f91995812ec4b5e0` | red (no header), green after worker, lead reran |
| `checks/test_upscaler_settings.py` | `2c7a6fc5eb357f86557e3c753383de3e1d7da833cf4a71f49e9cab98c32e7ba7`, now `bc21b4c0c8173df9` | red (no header); worker wrote it, gate failed on a dead `found` variable; lead fixed it, then tightened the gate |

`upscaler_modes.h` pins what P1 must send: Config = zero writes; every other mode writes `rtx.dlssPreset=2` first
(a non-Custom preset would override the quality key) and then `rtx.qualityDLSS`/`rtx.xess.preset` with the plan's
numbers (0/1/2/3). Mutations prove the gate bites: mapping Quality->2 fails (`FAIL quality`), and reversing the write
order fails all four modes.

## C2 (exit hang): the reproducer is scripted but the menu timing is not solved

Every 2026-11-14 run ended in a deadline kill, so no clean-exit path has been exercised yet. Two scripted
quit attempts failed to open the pause menu at all (`c2-quit-attempt-1` pressed BACK+DOWNs+A, `c2-pause-menu` pressed
B/Escape); both reached and rendered the world, so the failure is the menu route, not the world.

**Cause identified by reading the code** (which is what the plan asks for before any fix): the proxy has no teardown at
all. `remix_live.cpp:1237` says so explicitly — *"shortcut: the worker and its runtime are never torn down; process
exit ends them"* — the worker is started detached at `:1431`, `Shutdown` is never called anywhere (`grep Shutdown` →
no hits in `remix_live.cpp`, `live_scene.h`, `nscn_scene.h`), and the proxy logs no shutdown lines because there are
none. A detached worker plus a never-shut-down runtime is a plausible mechanism for a process that outlives the game
window, but it is **not yet proven as the hang**: the owned reproducer still needs one clean exit.

Next C2 step is therefore a real exit hook rather than more blind menu presses — e.g. the F10/Insert style toggle
already in the proxy, or a documented keyboard route to Quit — followed by observing whether the process ends.

## Correction: the pillarbox is intermittent, not a fixed upscaler property

Same XeSS config, two runs: `t1-remix-clean` (12:08) pillarboxed (bars 440/440), `c2-quit-attempt-1` (13:31) **full
width** (bars 0/0). So the earlier "XeSS letterboxes a 2.389 aspect" reading is too strong: the 16:9 fit appears in
some runs and not others, which points at a start-up ordering effect (Remix starting before the game resizes) rather
than a fixed aspect rule. The no-upscaler probe only showed that one run was bar-free; it did not isolate a cause.

Camera matching, not aspect, is now the open acquisition problem: framing correlation between the full-width Remix
frame and the original is 0.23 (not matched), and the tight-menu-sequence attempt (`t1-original-tight`) never left the
START MENU, because the presses arrived before the title screen.

## P1 gate hardening, and two more of my own spec errors

The persistence gate passed only after fixing defects on both sides:

- **My harness** compiled with `-Werror` and left `argc` unused, and asserted `NIER_RENDER.ini` was exactly **26 bytes**
  when the fixture it writes is 28. Both were my arithmetic, not the worker's code. Replaced the magic size with a
  before/after content comparison.
- **The worker's header** carried dead state: `bool found` was set in `load_mode` and never read, which `-Werror`
  rejected. Removing it also confirmed the invalid-value path reports rather than silently falling back — proven by a
  mutation that drops the error assignment (`FAIL invalid value reported`).
- **`"config"` was not a valid name** in `upscaler_modes.h` even though the settings file stores it, so the two gates
  disagreed. Added the name to both, keeping `"" -> Config` and case-sensitivity.

**The gate did not actually pin atomicity.** A direct in-place write passed, because the "failed save leaves the
previous contents intact" case fails before anything is written (missing directory). Added an observable atomicity
assertion: a successful save must replace the directory entry (`st_ino` changes) and leave no `.tmp` sibling. A
mutation that drops the temp file now fails (`FAIL save replaced the file (rename, not in-place write)`).

Final gate identities: `test_upscaler_modes.py` `a4b9ede42f6b37fd…`, `test_upscaler_settings.py` `bc21b4c0c8173df9…`.
Acceptance `runtime/suite-s66-acceptance/full-suite.json`: **109/109, `source_unchanged: true`**.

Laptop lane record: it produced `upscaler_modes.h` correctly, then returned *no output* on the settings task twice
(`843d8e73`, `b657e5a8`). The second attempt did write a header, which the lead then had to repair. Net: the lane
works intermittently for code and is not reliable enough to rely on unprompted; every result was re-verified here.

## P1 wired end to end (fake runtime proves the calls)

`checks/remix_live_fake_runtime.cpp` now implements `SetConfigVariable`: it records `SetConfigVariable <key> <value>`
into its own log, refuses a key named by `FAKE_REMIX_CONFIG_FAIL`, and leaves the member null when
`FAKE_REMIX_NO_CONFIG=1` so the "older runtime" path is testable. `checks/remix_live.cpp` applies the selection on the
worker thread, once, right after Startup (never on the game thread, which the plan forbids), through
`upscaler::writes_for`, and logs `remix: upscaler selection ...` for accepted, rejected and skipped cases.

Gate `checks/test_upscaler_live.py` (SHA-256 `22522a8a8eebf93bc79b9c48feb953dfe1ba78e943cd27a01a574800991b1105`)
drives the existing Wine mock + fake runtime and pins four cases:

| Case | Pinned behaviour |
| --- | --- |
| unset | zero `SetConfigVariable` lines and no selection line: today's default is untouched |
| `balanced` | exactly `('rtx.dlssPreset','2'), ('rtx.qualityDLSS','2'), ('rtx.xess.preset','2')` in that order |
| `ultra-super` | no writes, and the value is named in the log |
| runtime without the member | no writes, no crash, the skip is named (`SetConfigVariable`) |

Mutation: making the default `quality` instead of nothing fails the gate with the three unexpected writes
(`unset wrote config: [('rtx.dlssPreset','2'), ('rtx.qualityDLSS','3'), ('rtx.xess.preset','3')]`); restored.

Three of my own gate defects were found by running it rather than reading it: a loose `'upscaler' not in log` assertion
that tripped on ordinary option lines (now a precise marker), no display handling (now the same `xvfb-run --inside`
re-exec as `test_remix_live.py`), and no Wine prefix, so the suite provisioned a fresh one under 14 lanes and hit the
180 s timeout (now a pinned warm repo-local prefix).

Acceptance `runtime/suite-s69-acceptance/full-suite.json`: **110/110, `source_unchanged: true`**, 253.3 s.

## E1 effect-drop reporting accepted; bounded census next

- `live_capture.h` effect-drop tally now uses already observed raw blend/source/destination, discard flag and target
  format instead of hardcoded zeros. It still drops effects by default and releases/returns at the same point.
- `test_effect_tally.py`: real structured t27/t30 SM5 fixture + ordinary negative; correct-red, green,
  old-arguments mutation-red, restored green. Fixture keeps ordinary geometry so the worker can report its state.
- `EFFECT_INVENTORY.md`: camp/desert/pond recorded draws 3382/923/1176, blend-enabled92/24/47,
  structured-t27 candidate draws11/10/27. These are bounded legacy samples and declaration candidates, not a
  complete census or smoke/water/material identification. Combat and small passes are missing.
- Final reviewer d274429d (`openai-codex/gpt-6-luna`): OK; no rendering/default change and no visual overclaim.
- `runtime/suite-s72-acceptance/full-suite.json`: **113/113**, source_unchanged=true,241.3s.
  Candidate DLL SHA-256 `3b50b057fad86b97602f4978917d91fbece8e5c72a812007512882a653b5b372`, not deployed.
- NEXT gate `test_effect_census.py` frozen at SHA-256 `940bfd062255a87c1fef01b3d0e58eb887c1e1730348acc38792600af6e68d51`: first two default-off/ordinary controls pass;
  red `small-t27: no effect census (small draws must be counted before rejection)`. Fixtures explicitly bind
  structured PS t27/t30 stride48 view first1/count2 and VS t31 stride80 first0/count1, restore all bindings,
  and can draw six indices; no production census implementation accepted yet. Tally regression remains green.
- Delegation: next bounded E1.1 diagnostic-only implementation to an explicit Luna model. Lead retains core integration,
  frozen gate, resource/malformed-input review, mutation tests and acceptance. Shared-ledger synchronization pending;
  no out-of-repository ledger/config write authorized.

## E1 bounded census local acceptance (s73)

See [inventory and limitations](EFFECT_INVENTORY.md). Opt-in diagnostic now records small known-effect draws before
rejection, with bounded real state/VS+PS descriptors and bytecode-verified identity; no effect submission. Gate
original-target-size error corrected transparently, six mutation-red/restored-green checks, reviewer1b3c1691 Luna OK,
lead full suite **114/114 source_unchanged=true**. Worker532100f5 completed no code; lead implementation, not delegated
acceptance. Candidate DLL SHA256 `f6c3b0ba0fd80c1719e8283ac119b6dba160613315eab3734644fe3c21d40cdc`, NOT deployed.
E1 visual/class/combat/real-overhead acceptance and R2 versioned capture remain open.

## Strict priority-order resumption — A0.2

User directed execution strictly by the active plan. Next unfinished A0.2 runner teardown issue: Wine service
processes lose the run token; a shared-prefix path alone cannot establish ownership. No more prefix-only cleanup.
Frozen gate `test_private_run_prefix.py` proves private-copy/save-link preservation, exclusive destination,
token+path+directory-identity owner receipt, foreign/shared/conflicting processes excluded and mocked game-run
launch/cleanup using the same private prefix. Correct red: private-prefix preparation absent. No real process
signals, game/Wine/GPU/deployment/remote activity is part of this gate. Optional CLI compatibility selection
`--isolated-prefix` preserves existing runner behavior while enabling an explicitly owned copied prefix.
Remix Toolkit/MCP is not required for A0. User will be contacted before any later Toolkit connection.

## A0.2 private-prefix acceptance and repeat baseline

Plan order resumed at A0, not at a new visual/menu feature. Worker5c344ebb (openai-codex/gpt-6-luna) implemented
private-prefix copying and game caller opt-in; frozen main gate SHA4c918f10da7b54a29f4d063d54e4a64c20275c2869ab96dd758f2554d620b830 unchanged.
Lead hidden gate caught dangling destination symlink escape, fixed before acceptance. Reviewerd65ecdbb caught parent
alias ownership; hidden case red then fixed. Follow-up reviewer4e250517: OK. Lead added/tested replay caller wiring.
Mutations rejected: trust shared prefix; omit inode witness; leave copied save link pointing to template; cleanup
using shared instead of launched prefix (game and replay). Mutations restored. Same-size Python mutation briefly
left stale generated bytecode; removed only obsolete task-module .pyc files, reran affected gates green; later
mutation used fresh repository-local PYTHONPYCACHEPREFIX. No source regression accepted.

`runtime/suite-s74-a0/full-suite.json`: **117/117**, source_unchanged=true,249.9s. Source pins in
`runtime/suite-s74-a0/a0-source-sha256.json`. Only `--isolated-prefix` admits tokenless services, with exact
run-token/path/directory-device+inode owner receipt from exclusively created new copy; legacy shared prefixes
remain token-only. No prefix-only cleanup or real-save restoration.

Fresh repeat baselines: exact commands/identities in `runtime/a0-private-repeat/receipt.json`.
`a0-private-fake-1` and `a0-private-fake-2`: software-rendered recording fake, separate copied prefixes,120/120
presented each, child/launcher exit0, errors=[],forced_pids=[],remaining_owned_pids=[];16.0s and15.7s total.
Both replay2056 draws,0missing shaders/textures/bad layouts. These are safe fake-replay repeat/teardown evidence,
NOT a real Remix/game clean-quit fix, true-resolution performance, artistic acceptance or laptop DLSS measurement.
No game-folder install or Toolkit/MCP connection. Real-runtime/remote comparison gates remain explicit.

Next priority per plan table: A1 immutable capture intake/identity-preserving packing, reviewing its rejected spike
and existing capture identity evidence before choosing any implementation. No more P1/E1 expansion in its place.

## A1 validation accepted (parent deduplication NOT done)

[A1 validation acceptance](A1_VALIDATION_ACCEPTANCE.md):119/119full suite; both400-frame fake replays match exact
mesh/triangle/material/instance/texture/light controls, noforcedcleanup;all51,743raw hashes unchanged. Resource
validation step accepted. Dedup remains blocked on an identity-preserving design/source alias evidence; no core
geometry-key change or rejected candidate reinstated. Proceed to next ready C3 substep per plan priority.

## C3b fresh real-runtime comparison (next after blocked A1 identity / C3a platform gates)

[C3b receipt](C3B_REAL_MIP_COMPARISON.md): real Portal runtime/RX6800XT,24fresh512x512terrain assets per side;
1->10mips,24->0terrain suboptimal warnings, all24level-zero payloads identical; geometry/draw/texture counts
unchanged; native2580x1080frames preserved. Initial zero-bake fixture rejected, not success. No aesthetic default,
performance, real clean-quit or laptop-cycle acceptance claimed. Source unchanged since119/119suite, so no suite
rerun solely for these evidence documents. Next ready task per plan table: T1.1 opt-in pre-overwrite tap gate.

## T1.1/T1.2 offline
[receipt](T1_TAP_DECODE_LOCAL_ACCEPTANCE.md). T1.3 needs live-run permission (session card). Subagents moved off openai-codex (usage limit) to anthropic/claude-haiku-5-5 reviewer.

## C2.1 exit monitor (offline)
[receipt](C2_EXIT_MONITOR_LOCAL_ACCEPTANCE.md). C2 open: real Quit/hang-time stacks pending.

## T1.3 live run 1
[t1-tap-camp-1](T1_LIVE_TAP_RUN_1.md): tap works live; all 4 attempts rejected (moving camera); v2 budget fix gated; second run awaits approval.

## T1.3 live run 2
[t1-tap-camp-2](T1_LIVE_TAP_RUN_2.md): 4 camera-matched camp pairs; tap = original final minus HUD (gain ~1, median 4.5 levels vs original-game screenshots). Desert/pond pending.

## E1 live census runs 1-3
Effects: ~12/frame into a pre-tone-map ping-pong pair (incl. additive), 4/frame into the display-space HUD target (depth off). See EFFECT_INVENTORY.md.

## E1.3a handoff at effect (offline)
[receipt](E1_HANDOFF_AT_EFFECT_LOCAL.md); live check pending approval.

## E1 draw order
[result](E1_DRAW_ORDER_RESULT.md): no display-space effects in steady camp gameplay; handoff-at-effect rejected and removed; suite s88 126/126.

## W1.1 sky census
[receipt](W1_SKY_CENSUS.md); NV-RTX sky/effects follow-up in analysis/NEW_VEGAS_RTX_SKY_EFFECTS_2026-11-15.md.
